"""Add closed-loop performance, replay-again and shift-restart controls to the flow.

Idempotent: running it again changes nothing. It edits nodered/flow.json in
place, keeping the file's existing formatting (2-space JSON, CRLF endings).

Adds
  * a receive-time stamp in Node-RED validation, so analytics can time
    "record received -> forecast published" on the processing laptop's clock
  * team12/perf/metric -> loop_metrics table (command round trip, latencies)
  * dashboard queries and a "Closed-loop performance" panel
  * "Replay Company A/B again" and "Restart virtual shift" buttons
  * an optional note when the virtual line runs in ML-driven arrivals mode
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from common import CONFIG  # noqa: E402

FLOW = ROOT / "nodered" / "flow.json"
MARK = "<!-- closed-loop-performance:start -->"


def replace_once(text, old, new, label):
    if text.count(old) != 1:
        raise SystemExit(f"{label}: expected one match for {old[:60]!r}")
    return text.replace(old, new)


def scenario_summary():
    runs = {s["scenario"]: s for s in json.loads(
        (ROOT / "results" / "scenario_comparison.json").read_text())}
    slow = runs["slowdown"]
    before, after = slow["no_action"]["completed"], slow["with_action"]["completed"]
    wait0, wait1 = slow["no_action"]["avg_wait_seconds"], slow["with_action"]["avg_wait_seconds"]
    return {
        "healthy_commands": runs["healthy"]["commands_sent"],
        "items": f"{before} → {after} ({100 * (after - before) / before:+.1f}%)",
        "wait": f"{wait0:.0f} → {wait1:.0f} s ({100 * (wait1 - wait0) / wait0:+.1f}%)",
    }


def metric_sql(metric, alias):
    where = f"FROM loop_metrics WHERE metric='{metric}'"
    return (f"(SELECT COUNT(*) {where}) AS {alias}_n, "
            f"(SELECT ROUND(AVG(value)) {where}) AS {alias}_avg, "
            f"(SELECT ROUND(MAX(value)) {where}) AS {alias}_max, "
            f"(SELECT ROUND(value) {where} ORDER BY value LIMIT 1 OFFSET "
            f"(SELECT CAST(ROUND(0.95*(COUNT(*)-1)) AS INTEGER) {where})) AS {alias}_p95")


EXTRA_COUNTS = ", ".join([
    metric_sql("command_round_trip_ms", "rt"),
    metric_sql("ingest_to_forecast_ms", "ing"),
    "(SELECT ROUND(AVG(value),1) FROM loop_metrics WHERE metric='forecast_compute_ms') AS fc_avg",
    "(SELECT COUNT(*) FROM sim_commands WHERE direction='ack' AND accepted=0) AS refused_acks",
    "(SELECT ROUND(MIN(value)) FROM loop_metrics WHERE metric='command_gap_s') AS min_cmd_gap",
    "(SELECT COUNT(*) FROM loop_metrics WHERE metric='command_gap_s') AS gap_n",
    "(SELECT COUNT(*) FROM machine_events WHERE run_id=(SELECT run_id FROM machine_events "
    "ORDER BY id DESC LIMIT 1)) AS a_run",
    "(SELECT COUNT(*) FROM company_b_events WHERE run_id=(SELECT run_id FROM company_b_events "
    "ORDER BY id DESC LIMIT 1)) AS b_run",
])


def panel_html():
    s = scenario_summary()
    cooldown = CONFIG["decision"]["cooldown_seconds"]
    dc = "msg.payload.dbCounts"
    return f"""{MARK}
  <div class='panel wide' id='closed-loop-performance'>
    <div class='sectionlabel'>Closed-loop performance · measured in this run</div>
    <h3>Response time, stability and control effect</h3>
    <p class='muted'>Read from the loop_metrics and sim_commands tables in SQLite. Both ends of every timing are measured on the processing laptop's own clock, so a clock difference between the two laptops cannot distort them.</p>
    <div class='kpis'>
      <div class='kpi'><strong>{{{{{dc}.rt_n ? {dc}.rt_avg + ' ms' : '–'}}}}</strong><small>Command round trip: Accept → MQTT → device applies → ACK back<span ng-if='{dc}.rt_n'> · {{{{{dc}.rt_n}}}} command(s), max {{{{{dc}.rt_max}}}} ms</span></small></div>
      <div class='kpi'><strong>{{{{{dc}.ing_n ? {dc}.ing_avg + ' ms' : '–'}}}}</strong><small>Record → forecast: Node-RED receipt → SQLite → analytics → forecast<span ng-if='{dc}.ing_n'> · p95 {{{{{dc}.ing_p95}}}} ms · {{{{{dc}.ing_n}}}} forecasts</span></small></div>
      <div class='kpi'><strong>{{{{{dc}.fc_avg != null ? {dc}.fc_avg + ' ms' : '–'}}}}</strong><small>Model compute per forecast (features + prediction)</small></div>
      <div class='kpi'><strong>{{{{{dc}.acknowledgements || 0}}}} / {{{{{dc}.commands || 0}}}}</strong><small>Commands acknowledged as applied<span ng-if='{dc}.refused_acks'> · {{{{{dc}.refused_acks}}}} refused</span></small></div>
    </div>
    <div class='kpis'>
      <div class='kpi'><strong>{{{{{dc}.operator_accepts || 0}}}} / {{{{{dc}.operator_rejects || 0}}}}</strong><small>Operator decisions: accepted / rejected. Nothing is sent without approval.</small></div>
      <div class='kpi'><strong>{{{{{dc}.min_cmd_gap != null ? {dc}.min_cmd_gap + ' s' : '–'}}}}</strong><small>Shortest gap between two commands in one shift (simulated). The {cooldown} s cooldown prevents rapid switching.<span ng-if='!{dc}.gap_n'> Needs two accepted commands.</span></small></div>
      <div class='kpi'><strong>{s['healthy_commands']}</strong><small>Commands on a healthy line (offline check): no unnecessary actions.</small></div>
      <div class='kpi'><strong>{s['items']}</strong><small>Items, no action → with action (offline simulation). Wait {s['wait']}.</small></div>
    </div>
  </div>
<!-- closed-loop-performance:end -->
"""


def main():
    flow = json.loads(FLOW.read_text(encoding="utf-8"))
    nodes = {n["id"]: n for n in flow}
    template = nodes["ui_overview"]
    if MARK in template["format"]:
        print("Closed-loop panel already installed; nothing to do.")
        return
    crlf = b"\r\n" in FLOW.read_bytes()

    # 1. Receive-time stamp (milliseconds since epoch, processing laptop clock).
    v = nodes["fn_validate"]
    v["func"] = "const receivedMs = Date.now();\n" + v["func"]
    v["func"] = replace_once(v["func"], "node.status({fill: 'green'",
                             "m.received_ms = receivedMs;\nnode.status({fill: 'green'",
                             "fn_validate")

    # 2. Store closed-loop metrics.
    flow.append({
        "id": "in_perf", "type": "mqtt in", "z": "team12_tab",
        "name": "closed-loop timings", "topic": CONFIG["topics"]["perf_metric"],
        "qos": "0", "datatype": "json", "broker": "mqtt_broker",
        "x": 140, "y": 1570, "wires": [["fn_perf"]]})
    flow.append({
        "id": "fn_perf", "type": "function", "z": "team12_tab",
        "name": "store loop metric", "outputs": 1, "noerr": 0,
        "func": ("const p = msg.payload;\n"
                 "const known = ['command_round_trip_ms','ingest_to_forecast_ms','forecast_compute_ms','command_gap_s'];\n"
                 "if (!p || !known.includes(p.metric) || typeof p.value !== 'number' || !isFinite(p.value)) return null;\n"
                 "return {topic: 'INSERT INTO loop_metrics (ts_replay, metric, value, detail) VALUES ($tsr,$metric,$value,$detail)',\n"
                 "        params: {$tsr: p.ts_replay || new Date().toISOString(), $metric: p.metric,\n"
                 "                 $value: p.value, $detail: String(p.detail || '').slice(0, 120)}};"),
        "x": 400, "y": 1570, "wires": [["sql_bind"]]})

    # 3. Dashboard queries.
    q = nodes["fn_db_queries"]
    q["func"] = replace_once(q["func"], ' AS b_alarm_bar",payload:[]};',
                             f' AS b_alarm_bar, {EXTRA_COUNTS}",payload:[]}};', "fn_db_queries")

    # 4. Shift restart button, line state and optional ML arrival note.
    a = nodes["fn_ui_action"]
    a["func"] = replace_once(
        a["func"], "}else return null;",
        "}else if(p.kind==='line_restart'){\n dest='team12/replay/control';body={action:'restart_line'};\n}else return null;",
        "fn_ui_action")
    o = nodes["fn_overview"]
    o["func"] = replace_once(o["func"], "['A','B'].includes(p.company)",
                             "['A','B','line'].includes(p.company)", "fn_overview company")
    o["func"] = replace_once(
        o["func"],
        "if(t==='team12/sim/state' && Array.isArray(p.stages)){",
        "if(t==='team12/sim/state' && Array.isArray(p.stages)){\n"
        " if(typeof p.sim_second==='number' && typeof s.lastSimSecond==='number' && p.sim_second<s.lastSimSecond){"
        "s.proposal=null;s.reviewText='Virtual shift restarted';s.action='No command sent yet (new shift)';"
        "s.ack='Waiting for a command';s.queueHistory={};s.busyHistory={};}\n"
        " s.lastSimSecond=p.sim_second;\n"
        " s.arrival=p.arrival_source?{scale:p.arrival_scale,model:p.arrival_source}:null;",
        "fn_overview sim_state")
    o["func"] = replace_once(o["func"], "msg.payload={replayState:s.replayState,",
                             "msg.payload={arrival:s.arrival||null,replayState:s.replayState,",
                             "fn_overview payload")

    # 5. Template: replay-again buttons, this-run counts, restart button, panel.
    f = template["format"]
    for company, total, field in (("A", "146", "accepted"), ("B", "1,526", "b_accepted")):
        f = replace_once(
            f, f"""<button class='btn' ng-disabled="msg.payload.replayState.{company} !== 'ready'\"""",
            f"""<button class='btn' ng-disabled="['ready','completed','error'].indexOf(msg.payload.replayState.{company}) < 0\"""",
            f"button {company}")
        f = replace_once(f, f"}})'>Start Company {company}</button>",
                         f"}})'>{{{{msg.payload.replayState.{company}==='completed' ? 'Replay Company {company} again' : 'Start Company {company}'}}}}</button>",
                         f"label {company}")
        run = "a_run" if company == "A" else "b_run"
        f = replace_once(f, f"Stored records: {{{{msg.payload.dbCounts.{field} || 0}}}} / {total}",
                         f"This run: {{{{msg.payload.dbCounts.{run} || 0}}}} / {total} · stored in total: {{{{msg.payload.dbCounts.{field} || 0}}}}",
                         f"counts {company}")
    f = replace_once(
        f, "<p class='muted'>Completed: {{msg.payload.completed}} simulated items.",
        "<p class='status' ng-if='msg.payload.arrival'>ML-driven arrivals: material entering Stage 1 is scaled ×{{msg.payload.arrival.scale}} by the {{msg.payload.arrival.model}} forecasts (bounded 0.7–1.3×).</p>"
        "<p class='muted'>Completed: {{msg.payload.completed}} simulated items.",
        "arrival note")
    f = replace_once(
        f, "    <div class='status'>{{msg.payload.reviewText}}</div>\n  </div>",
        "    <div class='status'>{{msg.payload.reviewText}}</div>\n"
        "    <div class='controls'><button class='btn secondary' ng-disabled=\"['running','restarted'].indexOf(msg.payload.replayState.line) < 0\" "
        "ng-click='send({payload:{kind:\"line_restart\"}})'>Restart virtual shift</button>"
        "<span class='muted'>Starts a new simulated 8-hour shift on the device so the bottleneck can be shown again.</span></div>\n  </div>",
        "restart button")
    # Insert the panel inside the row, after the actuator response panel.
    anchor = "<p class='muted'>Acknowledgement confirms whether the virtual command was accepted.</p></div>\n"
    f = replace_once(f, anchor, anchor + panel_html(), "panel")
    template["format"] = f

    text = json.dumps(flow, indent=2, ensure_ascii=False) + "\n"
    if crlf:
        text = text.replace("\n", "\r\n")
    FLOW.write_bytes(text.encode("utf-8"))
    print("Installed closed-loop panel, timing storage, replay-again and shift-restart controls.")


if __name__ == "__main__":
    main()
