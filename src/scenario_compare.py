"""
Before / after evaluation of the control loop. ALL FIGURES ARE SIMULATED.

For each scenario we run the virtual line TWICE:
    no_action    the problem happens and nobody intervenes
    with_action  the decision engine detects it and sends commands
Both runs use the SAME seed, so they get the same arrival times and the same
token efforts. The only difference is whether we acted.

Writes results/scenario_comparison.json and results/SCENARIO_RESULTS.md

Run:  python src/scenario_compare.py
"""

import copy

from common import CONFIG, ROOT, save_json
from decision import choose_action, new_memory
from line_sim import Line

SIM = CONFIG["simulation"]
DEC = CONFIG["decision"]

# The three scenarios we demonstrate. Each one overrides config.simulation.scenario.
SCENARIOS = {
    "healthy": {"kind": "none", "stage_index": 1, "start_second": 0,
                "severity": 1.0, "alarm_duration_seconds": 0},
    "slowdown": dict(SIM["scenario"], kind="slowdown"),
    "alarm": dict(SIM["scenario"], kind="alarm"),
}


def run_once(scenario, act):
    """Run the virtual line once.

    act=False  nobody intervenes
    act=True   the decision engine may send commands, and the actuator
               applies them immediately
    """
    line = Line(SIM["stages"], SIM["arrival_rate_per_min"],
                SIM["seed"], SIM["duration_seconds"])
    memory = new_memory()
    events = []
    last_check = -10 ** 9

    while line.second < line.duration:
        note = line.apply_scenario(scenario)
        if note:
            events.append({"sim_second": line.second, "type": "scenario",
                           "detail": note})

        line.step()

        # The decision engine looks at the line on a fixed interval.
        if act and line.second - last_check >= DEC["check_every_seconds"]:
            last_check = line.second
            action = choose_action(line.snapshot(), memory)

            if action and action["type"] == "command":
                old, new = line.set_rate(action["stage_index"], action["new_rate"])
                events.append({
                    "sim_second": line.second, "type": "command",
                    "stage": action["stage_name"],
                    "old_rate": round(old, 3), "new_rate": round(new, 3),
                    "reason": action["reason"],
                    "ack": "accepted",      # the actuator applied it
                })
            elif action and action["type"] == "advice":
                events.append({
                    "sim_second": line.second, "type": "advice",
                    "stage": action["stage_name"],
                    "recommendation": action["recommendation"],
                    "reason": action["reason"],
                })

    final = line.snapshot()
    return {
        "completed": final["line_completed"],
        "throughput_per_hour": final["line_throughput_per_hour"],
        "avg_wait_seconds": final["avg_wait_seconds"],
        "tokens_arrived": line.next_arrival,
        "stages": [
            {
                "name": s["stage_name"],
                "final_rate": s["rate_per_min"],
                "configured_rate": s["configured_rate"],
                "queue_at_end": s["queue_length"],
                "busy_share": s["busy_share"],
                "starved_share": s["starved_share"],
            }
            for s in final["stages"]
        ],
        "events": events,
    }


def compare(name, scenario):
    print(f"\n=== scenario: {name} ({scenario['kind']}) ===")
    without = run_once(copy.deepcopy(scenario), act=False)
    with_act = run_once(copy.deepcopy(scenario), act=True)

    commands = [e for e in with_act["events"] if e["type"] == "command"]
    advice = [e for e in with_act["events"] if e["type"] == "advice"]

    delta_tp = with_act["throughput_per_hour"] - without["throughput_per_hour"]
    delta_wait = with_act["avg_wait_seconds"] - without["avg_wait_seconds"]

    print(f"  arrivals (identical in both runs): {without['tokens_arrived']}")
    print(f"  no action  : {without['completed']} done, "
          f"{without['throughput_per_hour']}/h, wait {without['avg_wait_seconds']}s")
    print(f"  with action: {with_act['completed']} done, "
          f"{with_act['throughput_per_hour']}/h, wait {with_act['avg_wait_seconds']}s")
    print(f"  commands sent: {len(commands)}, advice: {len(advice)}")
    for e in commands:
        print(f"    t={e['sim_second']}s {e['stage']} "
              f"{e['old_rate']} -> {e['new_rate']} (ack {e['ack']})")
    for e in advice:
        print(f"    t={e['sim_second']}s ADVICE: {e['recommendation']}")

    return {
        "scenario": name,
        "scenario_config": scenario,
        "no_action": without,
        "with_action": with_act,
        "difference": {
            "completed": with_act["completed"] - without["completed"],
            "throughput_per_hour": round(delta_tp, 2),
            "avg_wait_seconds": round(delta_wait, 1),
        },
        "commands_sent": len(commands),
        "advice_given": len(advice),
    }


def write_markdown(results):
    lines = [
        "# Virtual-line scenario results",
        "",
        "> **Every number on this page is SIMULATED.** The fixed dataset contains",
        "> no stage order, no queues and no waiting times, so these figures test",
        "> our detection and control logic. They are not measurements of any",
        "> factory, and no improvement here describes a real production line.",
        "",
        "Both runs in each scenario use the same seed, so arrivals and token",
        "efforts are identical. The only difference is whether the decision",
        "engine was allowed to act.",
        "",
        "## Summary",
        "",
        "| Scenario | Arrivals | Completed (no action) | Completed (with action) "
        "| Throughput /h | Avg wait (s) | Commands |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        na, wa, d = r["no_action"], r["with_action"], r["difference"]
        lines.append(
            f"| {r['scenario']} | {na['tokens_arrived']} | {na['completed']} | "
            f"{wa['completed']} | {na['throughput_per_hour']} -> "
            f"{wa['throughput_per_hour']} ({d['throughput_per_hour']:+}) | "
            f"{na['avg_wait_seconds']} -> {wa['avg_wait_seconds']} "
            f"({d['avg_wait_seconds']:+}) | {r['commands_sent']} |"
        )

    for r in results:
        lines += ["", f"## Scenario: {r['scenario']}", ""]
        cfg = r["scenario_config"]
        if cfg["kind"] == "none":
            lines.append("A healthy line. Nothing is broken.")
        elif cfg["kind"] == "slowdown":
            lines.append(
                f"Stage {cfg['stage_index'] + 1} is slowed to "
                f"{cfg['severity']:.0%} of its rate at t={cfg['start_second']}s. "
                f"Its capacity drops below the arrival rate, so its queue grows "
                f"without limit - a capacity constraint."
            )
        elif cfg["kind"] == "alarm":
            lines.append(
                f"Stage {cfg['stage_index'] + 1} stops completely at "
                f"t={cfg['start_second']}s for "
                f"{cfg['alarm_duration_seconds']}s. The correct response is "
                f"different: a stopped stage must be restarted, not sped up."
            )
        lines += [
            "",
            "| Stage | Configured | Final rate (with action) | Queue at end "
            "(no action) | Queue at end (with action) | Busy (no action) |",
            "|---|---|---|---|---|---|",
        ]
        for sn, sw in zip(r["no_action"]["stages"], r["with_action"]["stages"]):
            lines.append(
                f"| {sn['name']} | {sn['configured_rate']} | {sw['final_rate']} | "
                f"{sn['queue_at_end']} | {sw['queue_at_end']} | "
                f"{sn['busy_share']:.0%} |"
            )

        events = r["with_action"]["events"]
        if events:
            lines += ["", "**What the engine did:**", ""]
            for e in events:
                if e["type"] == "scenario":
                    lines.append(f"- `t={e['sim_second']}s` {e['detail']}")
                elif e["type"] == "command":
                    lines.append(
                        f"- `t={e['sim_second']}s` **command** to {e['stage']}: "
                        f"{e['old_rate']} -> {e['new_rate']} tokens/min, "
                        f"actuator **{e['ack']}**. {e['reason']}")
                else:
                    lines.append(
                        f"- `t={e['sim_second']}s` **advice**: "
                        f"{e['recommendation']}. {e['reason']}")
        lines.append("")

    (ROOT / "results" / "SCENARIO_RESULTS.md").write_text("\n".join(lines))


def main():
    results = [compare(name, cfg) for name, cfg in SCENARIOS.items()]
    save_json(ROOT / "results" / "scenario_comparison.json", results)
    write_markdown(results)
    print("\nWrote results/scenario_comparison.json and results/SCENARIO_RESULTS.md")


if __name__ == "__main__":
    main()
