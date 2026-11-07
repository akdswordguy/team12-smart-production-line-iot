"""
The VIRTUAL production line (and its actuator).

================= EVERYTHING IN THIS FILE IS SIMULATED =================
The real dataset has no stage order, no queues and no waiting times, so a
true line bottleneck cannot be measured from it. This simulator is where
queues, waiting time and before/after comparisons come from. Its numbers
are never presented as factory measurements.
========================================================================

How it works (one simulated second at a time):
  1. Tokens arrive at Stage 1 following a Poisson process.
  2. Each stage is a SINGLE SERVER: it works on ONE token at a time.
     While it is busy, new tokens wait in that stage's queue.
  3. A finished token moves to the next stage's queue, or leaves the line.

Fair comparison trick:
  Every token is given its "effort" for each stage when it is created -
  a random number drawn once. The time a stage takes is
      effort / rate
  so if we re-run with a different rate, the SAME tokens need the SAME
  relative effort. Only the stage speed changes. That is what makes the
  with-action vs no-action comparison honest.

Run as a live service:  python src/line_sim.py
Use as a library:       from line_sim import Line
"""

import json
import math
import os
import random
import time
from collections import deque

from common import CONFIG, connect, now_iso, publish, topic

SIM = CONFIG["simulation"]


class Stage:
    """One station on the virtual line. Works on one token at a time."""

    def __init__(self, index, name, rate_per_min, metrics_window):
        self.index = index
        self.name = name
        self.configured_rate = rate_per_min   # the rate from config.yaml
        self.rate = rate_per_min              # current rate (can change)

        # ML-driven mode only: capacity follows the active model's forecast
        # for this stage's machine. 1.0 (the default) leaves the stage as is.
        self.ml_factor = 1.0
        self.ml_machine = None
        self.ml_forecast = None

        self.queue = []          # tokens waiting for this stage
        self.token = None        # the ONE token being worked on
        self.finish_at = None    # simulated second when it will be done
        self.down_until = 0      # stage is stopped until this second (alarm)

        self.completed = 0
        self.wait_total = 0.0      # summed queue wait of finished tokens
        self.wait_count = 0

        # busy_share / starved_share are measured over the LAST
        # metrics_window seconds, not since the start of the run.
        # This matters: a stage that was comfortable for two hours and then
        # breaks must look busy within minutes, not hours. A running average
        # since t=0 would take most of the shift to cross any threshold.
        self.recent_busy = deque(maxlen=metrics_window)
        self.recent_starved = deque(maxlen=metrics_window)

    def is_down(self, second):
        return second < self.down_until

    def avg_wait(self):
        return self.wait_total / self.wait_count if self.wait_count else 0.0

    def busy_share(self):
        if not self.recent_busy:
            return 0.0
        return sum(self.recent_busy) / len(self.recent_busy)

    def starved_share(self):
        if not self.recent_starved:
            return 0.0
        return sum(self.recent_starved) / len(self.recent_starved)


class Line:
    """A three-stage virtual line. No MQTT in here - pure simulation,
    so it can also be used by scripts/tests without a broker."""

    def __init__(self, stage_config, arrival_rate_per_min, seed, duration,
                 metrics_window=None):
        if metrics_window is None:
            metrics_window = SIM["metrics_window_seconds"]
        self.stages = [
            Stage(i, s["name"], s["rate_per_min"], metrics_window)
            for i, s in enumerate(stage_config)
        ]
        self.duration = duration
        self.arrival_rate = arrival_rate_per_min
        self.tokens_arrived = 0
        self.ml_model = None      # model whose forecasts set the capacities

        # Two separate random streams so changing one does not disturb
        # the other. Both are seeded, so every run is reproducible.
        self.arrival_rng = random.Random(seed)
        self.effort_rng = random.Random(seed + 1)

        self.arrivals = self._plan_arrivals()
        self.next_arrival = 0
        self.next_token_id = 0

        self.finished = []       # tokens that completed the whole line
        self.second = 0

    def _plan_arrivals(self):
        """Decide up front exactly when every token arrives.

        Doing this before the run means the no-action and with-action runs
        see an IDENTICAL arrival sequence.
        """
        times = []
        t = 0.0
        mean_gap = 60.0 / self.arrival_rate
        while t < self.duration:
            t += self.arrival_rng.expovariate(1.0 / mean_gap)
            if t < self.duration:
                times.append(int(t))
        return times

    def _new_token(self, second):
        """Create a token and fix its effort at every stage, once."""
        token = {
            "id": self.next_token_id,
            "arrived": second,
            "effort": [self.effort_rng.expovariate(1.0) for _ in self.stages],
            "wait": 0.0,
            "queued_at": second,
        }
        self.next_token_id += 1
        return token

    def step(self):
        """Advance the line by exactly one simulated second."""
        second = self.second

        # --- 1. arrivals join the first stage's queue -----------------------
        while (self.next_arrival < len(self.arrivals)
               and self.arrivals[self.next_arrival] <= second):
            self.next_arrival += 1
            token = self._new_token(second)
            self.stages[0].queue.append(token)
            self.tokens_arrived += 1

        # --- 2. finish any token whose service time is up -------------------
        # Walk the stages backwards so a token can move on in the same second
        # the stage in front of it frees up.
        for stage in reversed(self.stages):
            if stage.token is not None and second >= stage.finish_at:
                token = stage.token
                stage.token = None
                stage.finish_at = None
                stage.completed += 1

                if stage.index + 1 < len(self.stages):
                    token["queued_at"] = second
                    self.stages[stage.index + 1].queue.append(token)
                else:
                    token["left_at"] = second
                    self.finished.append(token)

        # --- 3. start work on the next token, if the stage is free ----------
        for stage in self.stages:
            if stage.token is None and stage.queue and not stage.is_down(second):
                token = stage.queue.pop(0)
                waited = second - token["queued_at"]
                token["wait"] += waited
                stage.wait_total += waited
                stage.wait_count += 1

                # THE core formula. effort is fixed per token; rate can change.
                # In ML-driven mode the rate is scaled by the model's forecast.
                service_seconds = token["effort"][stage.index] * (
                    60.0 / (stage.rate * stage.ml_factor))
                stage.token = token
                stage.finish_at = second + max(1, int(round(service_seconds)))

            # --- 4. book-keeping for this second ----------------------------
            busy = stage.token is not None
            # idle with an empty queue = waiting for work = starved
            starved = (not busy) and (not stage.queue) and not stage.is_down(second)
            stage.recent_busy.append(1 if busy else 0)
            stage.recent_starved.append(1 if starved else 0)

        self.second += 1

    def apply_scenario(self, scenario):
        """Break something, on purpose, at a known time. This is how we get
        a bottleneck whose correct answer we already know."""
        if scenario["kind"] == "none" or self.second != scenario["start_second"]:
            return None

        stage = self.stages[scenario["stage_index"]]

        if scenario["kind"] == "slowdown":
            old = stage.rate
            stage.rate = stage.configured_rate * scenario["severity"]
            return (f"SCENARIO at t={self.second}s: {stage.name} slowed from "
                    f"{old:.2f} to {stage.rate:.2f} tokens/min")

        if scenario["kind"] == "alarm":
            stage.down_until = self.second + scenario["alarm_duration_seconds"]
            return (f"SCENARIO at t={self.second}s: {stage.name} STOPPED "
                    f"until t={stage.down_until}s (alarm)")
        return None

    def set_ml_forecast(self, stage_index, machine, forecast_items, model):
        """ML-driven mode: a stage can make what its machine is forecast to make.

        The forecast is items in the next 30 minutes; divided by 30 it is a
        rate per minute. Relative to the stage's calibrated rate it becomes a
        capacity factor, bounded so one odd forecast cannot stop the line.
        """
        stage = self.stages[stage_index]
        factor = (float(forecast_items) / 30.0) / stage.configured_rate
        stage.ml_factor = max(ML_DRIVEN["factor_min"], min(ML_DRIVEN["factor_max"], factor))
        stage.ml_machine = machine
        stage.ml_forecast = round(float(forecast_items), 2)
        self.ml_model = model
        return stage.ml_factor

    def set_rate(self, stage_index, new_rate):
        """The actuator's one job: change a stage's rate."""
        stage = self.stages[stage_index]
        old = stage.rate
        stage.rate = new_rate
        return old, new_rate

    def snapshot(self):
        """Current state of every stage, plus line totals. All simulated."""
        elapsed = max(self.second, 1)
        stages = []
        for s in self.stages:
            stages.append({
                "stage_index": s.index,
                "stage_name": s.name,
                "rate_per_min": round(s.rate, 3),
                "configured_rate": round(s.configured_rate, 3),
                "queue_length": len(s.queue),
                "busy_share": round(s.busy_share(), 3),
                "starved_share": round(s.starved_share(), 3),
                "completed": s.completed,
                "avg_wait_seconds": round(s.avg_wait(), 1),
                "is_down": s.is_down(self.second),
                "effective_rate": round(s.rate * s.ml_factor, 3),
                "ml_factor": round(s.ml_factor, 3),
                "ml_machine": s.ml_machine,
                "ml_forecast": s.ml_forecast,
            })

        waits = [t["wait"] for t in self.finished]
        return {
            "source": "simulated",          # never "observed"
            "sim_second": self.second,
            "ts_replay": now_iso(),
            "stages": stages,
            "line_completed": len(self.finished),
            "line_throughput_per_hour": round(
                len(self.finished) / (elapsed / 3600.0), 2),
            "avg_wait_seconds": round(sum(waits) / len(waits), 1) if waits else 0.0,
            "tokens_in_system": (
                self.tokens_arrived - len(self.finished)
            ),
            "ml_model": self.ml_model,
        }


# ---------------------------------------------------------------------------
# Live service: publish state, accept commands, acknowledge them.
# ---------------------------------------------------------------------------
line = None
mqtt_client = None
shift_over = False

# Optional ML-driven line (off unless TEAM12_ML_DRIVEN=1, set by --ml-driven).
# Each stage is linked to the Company A machine its rate was calibrated from
# (config simulation.ml_driven.stage_machines). The active model's 30-minute
# forecast for that machine sets the stage's capacity, and demand is set near
# capacity, so the stage the model expects to be weakest becomes the
# bottleneck. A different model can therefore move the bottleneck.
ML_DRIVEN = {"enabled": False, **SIM["ml_driven"]}


def on_forecast(payload):
    if not isinstance(payload, dict) or payload.get("source") != "forecast":
        return
    try:
        machine = int(payload["asset"])
        forecast = float(payload["predicted_items"])
    except (KeyError, TypeError, ValueError):
        return
    machines = ML_DRIVEN["stage_machines"]
    if machine in machines:
        line.set_ml_forecast(machines.index(machine), machine, forecast, payload.get("model"))


def on_message(client, userdata, message):
    if message.topic.startswith(topic("forecast") + "/"):
        try:
            on_forecast(json.loads(message.payload.decode()))
        except Exception:
            pass
        return
    on_command(client, userdata, message)


def on_command(client, userdata, message):
    """The ACTUATOR. Receives a command, applies it, and always replies."""
    try:
        cmd = json.loads(message.payload.decode())
    except Exception:
        return
    if not isinstance(cmd, dict):
        return

    ack = {
        "source": "simulated",
        "command_id": cmd.get("command_id"),
        "sim_second": line.second,
        "ts_replay": now_iso(),
        "action": cmd.get("action"),
        "stage_index": cmd.get("stage_index"),
    }

    # The actuator refuses anything it does not understand or cannot do.
    if shift_over:
        ack.update(accepted=False, reason="shift finished; command not applied")
    elif cmd.get("action") != "increase_rate":
        ack.update(accepted=False, reason=f"unknown action '{cmd.get('action')}'")
    elif (type(cmd.get("stage_index")) is not int
          or not 0 <= cmd["stage_index"] < len(line.stages)):
        ack.update(accepted=False, reason="stage_index out of range")
    else:
        stage = line.stages[cmd["stage_index"]]
        proposed = cmd.get("new_rate")
        ceiling = stage.configured_rate * CONFIG["decision"]["max_rate_multiplier"]
        step_limit = stage.rate * (1 + CONFIG["decision"]["rate_increase"]) + 0.002
        if (type(proposed) not in (int, float) or not math.isfinite(proposed)
                or not stage.rate < proposed <= min(ceiling + 0.001, step_limit)):
            ack.update(accepted=False, reason="rate outside bounded next step")
        elif (type(cmd.get("old_rate")) not in (int, float)
              or abs(cmd["old_rate"] - stage.rate) > 0.002):
            ack.update(accepted=False, reason="stale rate command")
        else:
            old, new = line.set_rate(cmd["stage_index"], proposed)
            ack.update(accepted=True, old_rate=round(old, 3), new_rate=round(new, 3),
                       reason="rate updated")
            print(f"  [actuator] {stage.name}: "
                  f"{old:.2f} -> {new:.2f} tokens/min")

    publish(client, topic("sim_ack"), ack)


def main():
    global line, mqtt_client, shift_over

    # The scenario comes from config.yaml, but you can override just the
    # KIND from the command line without editing anything:
    #     TEAM12_SCENARIO=alarm python src/line_sim.py
    scenario = dict(SIM["scenario"])
    override = os.environ.get("TEAM12_SCENARIO")
    if override:
        if override not in ("none", "slowdown", "alarm"):
            raise SystemExit(f"TEAM12_SCENARIO must be none|slowdown|alarm, "
                             f"got '{override}'")
        scenario["kind"] = override
        print(f"(scenario overridden from the environment: {override})")

    try:
        sim_speed = float(os.getenv("TEAM12_SIM_SPEED", SIM["speed"]))
    except ValueError as exc:
        raise SystemExit("TEAM12_SIM_SPEED must be a positive number") from exc
    if not math.isfinite(sim_speed) or sim_speed <= 0:
        raise SystemExit("TEAM12_SIM_SPEED must be a positive finite number")

    shift_over = False
    ML_DRIVEN["enabled"] = any(os.getenv(name, "").lower() in ("1", "true", "yes")
                               for name in ("TEAM12_ML_DRIVEN", "TEAM12_ML_ARRIVALS"))
    arrival_rate = SIM["arrival_rate_per_min"]
    if ML_DRIVEN["enabled"]:
        arrival_rate = ML_DRIVEN["arrival_rate_per_min"]
        scenario["kind"] = "none"     # the model, not a script, creates the bottleneck
    line = Line(SIM["stages"], arrival_rate, SIM["seed"], SIM["duration_seconds"])

    mqtt_client = connect("line_sim")
    mqtt_client.on_message = on_message
    mqtt_client.subscribe(topic("sim_command"))
    if ML_DRIVEN["enabled"]:
        mqtt_client.subscribe(topic("forecast") + "/#")
        pairs = ", ".join(f"{s.name} <- machine {m}"
                          for s, m in zip(line.stages, ML_DRIVEN["stage_machines"]))
        print(f"ML-DRIVEN LINE ON: {pairs}. Each stage's capacity follows the active "
              f"model's forecast; demand {arrival_rate} tokens/min; no scripted fault.")
    mqtt_client.loop_start()

    print("VIRTUAL LINE - all values below are SIMULATED")
    for s in line.stages:
        print(f"  {s.name}: {s.rate} tokens/min")
    print(f"  arrivals: {arrival_rate} tokens/min")
    print(f"  scenario: {scenario['kind']} on stage {scenario['stage_index']} "
          f"at t={scenario['start_second']}s")
    print(f"  running {SIM['duration_seconds']}s of simulated time at "
          f"{sim_speed:g}x\n")

    publish_every = 60          # publish state once per simulated minute
    seconds_per_tick = 1.0 / sim_speed

    while line.second < line.duration:
        note = line.apply_scenario(scenario)
        if note:
            print(f"  {note}")
            publish(mqtt_client, topic("sim_alert"), {
                "source": "simulated", "kind": "scenario_injected",
                "message": note, "sim_second": line.second,
                "ts_replay": now_iso(),
            })

        line.step()

        if line.second % publish_every == 0:
            state = line.snapshot()
            publish(mqtt_client, topic("sim_state"), state)
            if line.second % 900 == 0:      # print every 15 simulated minutes
                queues = "  ".join(
                    f"{s['stage_name'][:7]} q={s['queue_length']:<3} "
                    f"busy={s['busy_share']:.0%}"
                    for s in state["stages"])
                print(f"  t={line.second:>6}s  {queues}  "
                      f"done={state['line_completed']}")

        time.sleep(seconds_per_tick)

    shift_over = True
    final = line.snapshot()
    publish(mqtt_client, topic("sim_state"), final)
    print(f"\nSimulated run finished (ALL FIGURES SIMULATED):")
    print(f"  tokens completed : {final['line_completed']}")
    print(f"  throughput       : {final['line_throughput_per_hour']}/h")
    print(f"  average wait     : {final['avg_wait_seconds']}s")

    print("  actuator still listening; late commands are refused. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()


if __name__ == "__main__":
    main()
