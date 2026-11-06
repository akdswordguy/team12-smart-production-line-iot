"""
Decision engine for the VIRTUAL line.

Two parts:
  1. choose_action(...)  a PURE function - no MQTT, no clock, no files.
                         The live service and the offline before/after
                         comparison both call this same function, so the
                         demo and the results can never disagree.
  2. main()              the live service: listen to sim state, publish
                         commands, log acknowledgements.

Bottleneck rule (all evidence must agree):
    busy          the stage is working almost all the time
    queue growing work is piling up IN FRONT of it
    not starved   it is not simply waiting for input
A stage that is merely the busiest is NOT enough: Stage 3 runs at 83% in a
healthy line and must not be flagged.

Run:  python src/decision.py
"""

import json
import uuid

from common import CONFIG, connect, now_iso, publish, topic

DEC = CONFIG["decision"]
MON = CONFIG["monitoring"]
recent_machine_metrics = {}


def new_memory():
    """All the state the engine remembers between checks. Plain dict so you
    can print it at any time."""
    return {
        "streak": {},            # stage_index -> consecutive suspicious checks
        "queue_history": {},     # stage_index -> recent queue lengths
        "commands_sent": 0,
        "last_command_second": -10 ** 9,
        "last_advice": None,     # so the same advice is not repeated forever
    }


def advise(memory, advice):
    """Return this advice only the FIRST time it applies.

    Without this the engine repeats "investigate interruption" at every
    check for as long as the stage is down, which floods the dashboard.
    """
    key = (advice["recommendation"], advice["stage_index"])
    if memory["last_advice"] == key:
        return None
    memory["last_advice"] = key
    return advice


# ---------------------------------------------------------------------------
# The pure decision function.
# ---------------------------------------------------------------------------
def choose_action(state, memory):
    """Look at one snapshot of the virtual line and decide what to do.

    Returns a dict:
        {"type": "command",  ...}  send this to the actuator
        {"type": "advice",   ...}  tell the operator, but do not act
        None                       nothing to do
    """
    second = state["sim_second"]
    stages = state["stages"]

    # The line has to fill up before any queue means anything.
    if second < DEC["warmup_seconds"]:
        return None

    # --- 0. remember how long each queue has been -------------------------
    # We need the HISTORY to tell a growing queue from a merely long one.
    for s in stages:
        hist = memory["queue_history"].setdefault(s["stage_index"], [])
        hist.append(s["queue_length"])
        if len(hist) > 20:
            hist.pop(0)

    # --- 1. who looks like a bottleneck this check? -------------------------
    suspects = []
    for s in stages:
        i = s["stage_index"]
        hist = memory["queue_history"][i]

        busy_enough = s["busy_share"] >= DEC["busy_share_threshold"]
        queue_long = s["queue_length"] >= DEC["queue_threshold"]

        # Is the queue GROWING, or just briefly long?
        # A healthy stage can be busy with 5 waiting for a few minutes and
        # then catch up. A real capacity constraint cannot catch up, so its
        # queue is longer now than it was a few checks ago. Without this
        # test the engine "fixes" a perfectly healthy line.
        back = DEC["sustained_checks"]
        if DEC["require_queue_growth"] and len(hist) > back:
            queue_growing = hist[-1] > hist[-1 - back]
        else:
            queue_growing = True   # test disabled in config

        # A stage that is down is stopped, not capacity-limited.
        if s.get("is_down"):
            suspects.append((s, "down"))
        elif busy_enough and queue_long and queue_growing:
            suspects.append((s, "capacity"))

    # Update the streak counters for every stage.
    suspect_indexes = {s["stage_index"] for s, _ in suspects}
    for s in stages:
        i = s["stage_index"]
        if i in suspect_indexes:
            memory["streak"][i] = memory["streak"].get(i, 0) + 1
        else:
            memory["streak"][i] = 0

    if not suspects:
        memory["last_advice"] = None     # situation cleared
        return None

    # The worst suspect is the one with the longest queue in front of it.
    suspects.sort(key=lambda pair: pair[0]["queue_length"], reverse=True)
    stage, kind = suspects[0]
    i = stage["stage_index"]

    # --- 2. has it held long enough to be believed? -------------------------
    if memory["streak"][i] < DEC["sustained_checks"]:
        return None

    evidence = (
        f"busy {stage['busy_share']:.0%}, queue {stage['queue_length']}, "
        f"starved {stage['starved_share']:.0%}, "
        f"for {memory['streak'][i]} checks"
    )

    # --- 3. a STOPPED stage is a different problem --------------------------
    # This is what makes the alarm demo give a different recommendation.
    if kind == "down":
        return advise(memory, {
            "type": "advice",
            "sim_second": second,
            "stage_index": i,
            "stage_name": stage["stage_name"],
            "recommendation": "investigate interruption",
            "reason": (
                f"{stage['stage_name']} is STOPPED, not slow ({evidence}). "
                f"Adding capacity to a stopped stage achieves nothing - "
                f"restart it first."
            ),
        })

    # --- 4. budget checks ---------------------------------------------------
    if memory["commands_sent"] >= DEC["max_commands"]:
        return None
    if second - memory["last_command_second"] < DEC["cooldown_seconds"]:
        return None   # still waiting to see what the last command did

    # --- 5. the bounded action ---------------------------------------------
    current = stage["rate_per_min"]
    ceiling = stage["configured_rate"] * DEC["max_rate_multiplier"]
    proposed = current * (1.0 + DEC["rate_increase"])
    new_rate = min(proposed, ceiling)

    if new_rate <= current + 1e-9:
        return advise(memory, {
            "type": "advice",
            "sim_second": second,
            "stage_index": i,
            "stage_name": stage["stage_name"],
            "recommendation": "escalate - automatic limit reached",
            "reason": (
                f"{stage['stage_name']} is still the constraint ({evidence}) "
                f"but it is already at the configured ceiling "
                f"({ceiling:.2f} tokens/min). A human decision is needed."
            ),
        })

    memory["commands_sent"] += 1
    memory["last_command_second"] = second

    return {
        "type": "command",
        "command_id": uuid.uuid4().hex[:8],
        "action": "increase_rate",
        "sim_second": second,
        "stage_index": i,
        "stage_name": stage["stage_name"],
        "old_rate": round(current, 3),
        "new_rate": round(new_rate, 3),
        "reason": (
            f"{stage['stage_name']} is the limiting stage ({evidence}). "
            f"Raising its rate by {DEC['rate_increase']:.0%} to "
            f"{new_rate:.2f} tokens/min (ceiling {ceiling:.2f})."
        ),
    }


# ---------------------------------------------------------------------------
# Live service
# ---------------------------------------------------------------------------
memory = new_memory()
last_check_second = -10 ** 9
pending = None


def on_message(client, userdata, message):
    global last_check_second, pending

    try:
        payload = json.loads(message.payload.decode())
    except Exception:
        return

    if message.topic == topic("sim_approval"):
        if (not isinstance(payload, dict) or pending is None
                or payload.get("proposal_id") != pending["command_id"]
                or payload.get("decision") not in ("accept", "reject")):
            return
        accepted = payload["decision"] == "accept"
        review = {"source": "simulated", "proposal_id": pending["command_id"],
                  "decision": payload["decision"], "ts_replay": now_iso(),
                  "sim_second": pending["sim_second"],
                  "stage_index": pending["stage_index"],
                  "stage_name": pending["stage_name"],
                  "old_rate": pending["old_rate"],
                  "new_rate": pending["new_rate"],
                  "reason": pending["reason"]}
        if accepted:
            memory["last_command_second"] = max(last_check_second, pending["sim_second"])
            publish(client, topic("sim_review"), review)
            command = {**pending, "ts_replay": now_iso()}
            publish(client, topic("sim_command"), command)
            print(f"Operator accepted {pending['command_id']}; command sent", flush=True)
        else:
            memory["commands_sent"] -= 1
            publish(client, topic("sim_review"), review)
            print(f"Operator rejected {pending['command_id']}; actuator unchanged", flush=True)
        pending = None
        return

    if message.topic == topic("forecast_advisory"):
        return

    # Machine forecasting is an advisory branch. The supplied CSV has no
    # routing or actuator, so ML can recommend investigation, never claim
    # to have physically changed a factory machine.
    if message.topic.startswith(topic("observed_metrics") + "/"):
        recent_machine_metrics[payload["asset"]] = payload
        return

    if (message.topic.startswith(topic("forecast") + "/")
            and message.topic != topic("forecast_advisory")):
        asset = payload.get("asset")
        metrics = recent_machine_metrics.get(asset)
        if metrics is None:
            return
        forecast = float(payload.get("predicted_items", 0))
        base = metrics.get("baseline_items_per_slot")
        recent_prod = metrics.get("productive_share", 0)
        coverage = metrics.get("coverage", 0)
        expected = base * (CONFIG["ml"]["horizon_minutes"] / 5) if base else None
        if coverage < 1 or recent_prod < 0.8 or expected is None:
            recommendation = "monitor"
            reason = ("Forecast received; recent operation is not sufficiently "
                      "continuous and productive for a fair baseline comparison.")
        elif forecast < expected * MON["forecast_low_ratio"]:
            recommendation = "inspect machine or replan workload"
            reason = (f"ML predicts {forecast:.1f} items in 30 minutes versus "
                      f"{expected:.1f} expected for six productive slots.")
        else:
            recommendation = "continue monitoring"
            reason = (f"ML predicts {forecast:.1f} items in 30 minutes versus "
                      f"{expected:.1f} expected for six productive slots.")
        advisory = {
            "source": "forecast", "asset": asset,
            "ts_dataset": payload.get("ts_dataset"),
            "ts_replay": now_iso(),
            "model": payload.get("model"),
            "predicted_items": round(forecast, 2),
            "expected_items": round(expected, 2) if expected is not None else None,
            "recommendation": recommendation, "reason": reason,
        }
        publish(client, topic("forecast_advisory"), advisory)
        print(f"  [forecast decision] machine {asset}: {recommendation} â€” {reason}")
        return

    # Acknowledgements from the actuator: just report them.
    if message.topic == topic("sim_ack"):
        mark = "accepted" if payload.get("accepted") else "REFUSED"
        print(f"  [ack] command {payload.get('command_id')} {mark}: "
              f"{payload.get('reason')}")
        return

    if message.topic != topic("sim_state"):
        return

    # Only check the line every so often.
    second = payload.get("sim_second", 0)
    if second - last_check_second < DEC["check_every_seconds"]:
        return
    last_check_second = second

    if pending is not None:
        return

    action = choose_action(payload, memory)
    if action is None:
        return

    if action["type"] == "advice":
        print(f"  [t={second}s] ADVICE ({action['recommendation']}): "
              f"{action['reason']}")
        publish(client, topic("sim_alert"), {
            "source": "simulated", "kind": "advice",
            "ts_replay": now_iso(), **action,
        })
        return

    print(f"  [t={second}s] PROPOSAL -> {action['stage_name']}: "
          f"{action['old_rate']} -> {action['new_rate']} tokens/min")
    print(f"           reason: {action['reason']}")
    pending = {
        "source": "simulated", "ts_replay": now_iso(), **action,
    }
    publish(client, topic("sim_proposal"), pending)


def main():
    client = connect("decision")
    client.on_message = on_message
    client.subscribe(topic("sim_state"))
    client.subscribe(topic("sim_ack"))
    client.subscribe(topic("sim_approval"))
    client.subscribe(topic("observed_metrics") + "/#")
    client.subscribe(topic("forecast") + "/#")

    print("Decision engine watching the VIRTUAL line.")
    print(f"  flag a stage when busy >= {DEC['busy_share_threshold']:.0%} "
          f"AND queue >= {DEC['queue_threshold']}, "
          f"for {DEC['sustained_checks']} checks")
    print(f"  action: +{DEC['rate_increase']:.0%} rate, "
          f"max {DEC['max_rate_multiplier']}x configured, "
          f"at most {DEC['max_commands']} commands\n")

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print(f"\nSent {memory['commands_sent']} commands.")


if __name__ == "__main__":
    main()
