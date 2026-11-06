"""Refresh the dashboard's saved model and simulation evidence after training.

The live cards still come from MQTT and SQLite. This script changes only the
offline evaluation panel in flow.json, using the project result files.
"""

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FLOW = ROOT / "nodered" / "flow.json"
BEGIN = "<!-- model-evaluation:start -->"
END = "<!-- model-evaluation:end -->"

STYLE = """
/* model-eval-style */
.t12 .sectionlabel{font-size:11px;font-weight:800;letter-spacing:.09em;color:#0d7495;text-transform:uppercase}
.t12 .modelgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px;margin:16px 0}
.t12 .modelbox{border:1px solid #e2eaf0;border-radius:8px;background:#f8fbfd;padding:14px;min-width:0}
.t12 .modelbox h4{font-size:14px;margin:0 0 10px;color:#17324d}
.t12 .barrow{display:grid;grid-template-columns:116px 1fr 48px;gap:8px;align-items:center;margin:9px 0;font-size:12px}
.t12 .bartrack{height:13px;background:#e4edf2;border-radius:20px;overflow:hidden}
.t12 .barfill{height:100%;background:#92a9b6;border-radius:20px}
.t12 .barfill.winner{background:#0789b6}
.t12 .modelchart{width:100%;height:170px;background:white;border:1px solid #e4eaf0;border-radius:6px}
.t12 .callout{border-left:4px solid #0789b6;background:#edf7fa;padding:10px 13px;margin-top:14px;border-radius:0 5px 5px 0}
.t12 .simcallout{border-left-color:#d97706;background:#fff7eb}
.t12 .kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:12px 0}
.t12 .kpi{border:1px solid #dce7ee;border-radius:8px;background:#f8fbfd;padding:12px}
.t12 .kpi strong{display:block;font-size:22px;line-height:1.2;color:#103e57}
.t12 .kpi small{color:#536a79;font-size:12px}
.t12 .replaygrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:14px}
.t12 .replaycard{border:1px solid #dce7ee;border-radius:8px;padding:14px;background:#f8fbfd}
.t12 .replaycard h4{margin:0 0 7px;font-size:15px}
.t12 .replaycard .btn{margin-top:7px}
.t12 .comparebar{height:15px;background:#e4edf2;border-radius:20px;overflow:hidden;margin:5px 0 12px}
.t12 .comparebar span{display:block;height:100%;background:#087ba5}
.t12 .comparebar .b{background:#d97706}
@media(max-width:760px){.t12 .modelgrid{grid-template-columns:1fr}.t12 .kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:760px){.t12 .replaygrid{grid-template-columns:1fr}}
"""

REPLAY_PANEL = """<!-- replay-controls:start -->
  <div class='panel wide' id='replay-controls'>
    <div class='sectionlabel'>MQTT replay controls</div>
    <h3>Start each company's data stream</h3>
    <p class='muted'>Start the device role with --manual-replay first. The buttons send MQTT requests to that role. Both streams can run together; each uses its own topics, database tables and analytics.</p>
    <div class='replaygrid'>
      <div class='replaycard'><h4>Company A · output and forecasting</h4>
        <div class='status'>Device: {{msg.payload.replayState.A || 'Waiting for device'}}</div>
        <button class='btn' ng-disabled="msg.payload.replayState.A !== 'ready'" ng-click='send({payload:{kind:"replay",company:"A"}})'>Start Company A</button>
        <p class='muted'>Stored records: {{msg.payload.dbCounts.accepted || 0}} / 146 · forecasts: {{msg.payload.dbCounts.forecasts || 0}}</p>
      </div>
      <div class='replaycard'><h4>Company B · machine operating states</h4>
        <div class='status'>Device: {{msg.payload.replayState.B || 'Waiting for device'}}</div>
        <button class='btn' ng-disabled="msg.payload.replayState.B !== 'ready'" ng-click='send({payload:{kind:"replay",company:"B"}})'>Start Company B</button>
        <p class='muted'>Stored records: {{msg.payload.dbCounts.b_accepted || 0}} / 1,526 · live status charts below</p>
      </div>
    </div>
  </div>
<!-- replay-controls:end -->"""

LIVE_COMPARISON = """<!-- live-comparison:start -->
    <div class='replaygrid'>
      <div class='replaycard'><h4>Company A · replay sample</h4><b>{{msg.payload.dbCounts.accepted || 0}} stored records</b>
        <p>Alarm among production or alarm reports: <b>{{msg.payload.dbCounts.a_alarm_pct == null ? 'Waiting' : (msg.payload.dbCounts.a_alarm_pct + '%')}}</b></p>
        <div class='comparebar'><span ng-style='{"width":(msg.payload.dbCounts.a_alarm_bar || 0)+"%"}'></span></div>
      </div>
      <div class='replaycard'><h4>Company B · replay sample</h4><b>{{msg.payload.dbCounts.b_accepted || 0}} stored records</b>
        <p>Alarm among production or alarm reports: <b>{{msg.payload.dbCounts.b_alarm_pct == null ? 'Waiting' : (msg.payload.dbCounts.b_alarm_pct + '%')}}</b></p>
        <div class='comparebar'><span class='b' ng-style='{"width":(msg.payload.dbCounts.b_alarm_bar || 0)+"%"}'></span></div>
      </div>
    </div>
    <p class='muted'>Live bars use only records received in this replay. Bar scale: 0–20% alarm share. Compare the same condition, not output: B has no item-count column. The nine-month graph below is the fuller historical context.</p>
<!-- live-comparison:end -->"""


def fold_svg(cv):
    colors = {"ridge": "#7f97a6", "gradient_boosting": "#0789b6",
              "neural_network": "#d97706"}
    lines = []
    for tick in (1.5, 2.0, 2.5):
        y = 145 - (tick - 1.4) / 1.1 * 120
        lines.append(f'<line x1="42" y1="{y:.1f}" x2="408" y2="{y:.1f}" stroke="#dfe8ee"/>')
        lines.append(f'<text x="6" y="{y + 4:.1f}" font-size="11" fill="#607586">{tick:.1f}</text>')
    for i in range(4):
        x = 50 + 115 * i
        lines.append(f'<text x="{x - 9}" y="166" font-size="11" fill="#607586">F{i + 1}</text>')
    for name in colors:
        values = cv[name]["per_fold"]
        points = " ".join(f"{50 + 115 * i},{145 - (v - 1.4) / 1.1 * 120:.1f}"
                          for i, v in enumerate(values))
        lines.append(f'<polyline points="{points}" fill="none" stroke="{colors[name]}" '
                     'stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>')
    return ('<svg class="modelchart" viewBox="0 0 420 175" role="img" '
            'aria-label="Four rolling validation folds; lower active MAE is better">'
            + "".join(lines) + '</svg>')


def render_panel(report, scenarios):
    cv = report["cross_validation"]["scores"]
    results = report["results"]
    candidates = [
        ("ridge", "Ridge regression", "Traditional"),
        ("gradient_boosting", "Gradient boosting", "Ensemble"),
        ("neural_network", "Neural network", "Neural"),
    ]
    bars = []
    rows = []
    max_cv = max(cv[name]["mean"] for name, _, _ in candidates)
    for name, label, family in candidates:
        r = results[name]
        score = cv[name]["mean"]
        width = score / max_cv * 100
        winner = ' winner' if name == report["chosen_model"] else ''
        bars.append(f'<div class="barrow"><span>{html.escape(label)}</span>'
                    f'<div class="bartrack"><div class="barfill{winner}" style="width:{width:.1f}%"></div></div>'
                    f'<b>{score:.3f}</b></div>')
        rows.append('<tr' + (' class="selected"' if winner else '') + '>'
                    f'<td>{html.escape(label)}</td><td>{family}</td>'
                    f'<td>{score:.3f}</td><td>{cv[name]["per_fold"][-1]:.3f}</td>'
                    f'<td>{r["active"]["mae"]:.3f}</td><td>{r["idle"]["mae"]:.3f}</td>'
                    f'<td>{r["test_rmse"]:.3f}</td><td>{r["train_seconds"]:.1f}s</td>'
                    f'<td>{r["predict_ms_per_1000"]:.2f} ms</td>'
                    f'<td>{r["model_size_mb"]:.3f} MB</td></tr>')
    winner = report["chosen_model"]
    deployed = results["deployed_" + winner]
    persistence = results["baseline_persistence"]
    slowdown = next(s for s in scenarios if s["scenario"] == "slowdown")
    before = slowdown["no_action"]
    after = slowdown["with_action"]
    gain = (after["completed"] / before["completed"] - 1) * 100
    wait_drop = (1 - after["avg_wait_seconds"] / before["avg_wait_seconds"]) * 100
    return f"""
  <div class='panel wide' id='model-evaluation'>
    <div class='sectionlabel'>Offline model evaluation · fixed Company A dataset</div>
    <h3>Why this model was selected</h3>
    <p>Three separately trained families used the same {report['examples']:,} complete examples, {report['features']} past-only features and next-30-minute item-count target. The test period was held back until selection was locked.</p>
    <div class='modelgrid'>
      <div class='modelbox'><h4>Four-fold mean active MAE · lower is better</h4>{''.join(bars)}<div class='muted'>Validation evidence used to choose the deployed family.</div></div>
      <div class='modelbox'><h4>Active MAE across time-ordered folds</h4>{fold_svg(cv)}<div class='legend'><span><i class='key' style='background:#7f97a6'></i>Ridge</span><span><i class='key' style='background:#0789b6'></i>Boosting</span><span><i class='key' style='background:#d97706'></i>Neural</span></div></div>
    </div>
    <div class='tablewrap'><table><thead><tr><th>Algorithm</th><th>Family</th><th>CV active MAE</th><th>Latest fold</th><th>Test active MAE</th><th>Test idle MAE</th><th>Test RMSE</th><th>Train time</th><th>Predict / 1000</th><th>Size</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
    <p class='muted'>Count prediction is a regression task: MAE and RMSE apply; classification accuracy, precision and recall do not. Candidate test scores are displayed for audit, never used for model selection. Test columns are each model fitted on the training block only; the shipped gradient-boosting model was then refit on all pre-test data (test active MAE {deployed['active']['mae']:.3f}). Training time and latency were measured on the training machine.</p>
    <div class='callout'><b>Selected: Gradient boosting.</b> Its mean validation active MAE was {cv[winner]['mean']:.3f}; the neural network was only {report['cross_validation']['margin_over_runner_up_percent']:.2f}% behind. The last fold favoured boosting by {report['cross_validation']['recent_fold_margin_over_runner_up_percent']:.2f}%. The deployed model was refit on all pre-test data. On the later test period its active MAE was {deployed['active']['mae']:.3f}, versus {persistence['active']['mae']:.3f} for the simple persistence reference. The winner did not win every fold.</div>
    <div class='callout simcallout'><b>Offline virtual-line control check:</b> with an automatic acceptance policy under identical simulated arrivals and Stage 2 slowdown, control completed {after['completed']} items versus {before['completed']} without action (+{gain:.1f}%). Average wait fell from {before['avg_wait_seconds']:.0f}s to {after['avg_wait_seconds']:.0f}s (−{wait_drop:.1f}%). Manual approval in the live demo can change this outcome. These are simulation results, not factory measurements.</div>
  </div>
"""


def main():
    report = json.loads((ROOT / "results" / "model_comparison.json").read_text())
    scenarios = json.loads((ROOT / "results" / "scenario_comparison.json").read_text())
    nodes = json.loads(FLOW.read_text(encoding="utf-8-sig"))
    template = next(n for n in nodes if n["id"] == "ui_overview")
    markup = template["format"]
    if BEGIN not in markup:
        old = markup.index("  <div class='panel wide'><h3>Model comparison</h3>")
        following = markup.index("  <div class='panel'><span class='badge'>OBSERVED DATA</span>", old)
        markup = markup[:old] + BEGIN + END + "\n" + markup[following:]
    assert markup.count(BEGIN) == markup.count(END) == 1
    left = markup.index(BEGIN) + len(BEGIN)
    right = markup.index(END)
    markup = markup[:left] + "\n" + render_panel(report, scenarios) + markup[right:]
    if "/* model-eval-style */" not in markup:
        markup = markup.replace("</style>", STYLE + "\n</style>", 1)
    elif ".t12 .replaygrid" not in markup:
        markup = markup.replace("</style>", STYLE[STYLE.index(".t12 .replaygrid"):]+"\n</style>", 1)
    if "<!-- replay-controls:start -->" not in markup:
        markup = markup.replace("<!-- company-comparison:start -->", REPLAY_PANEL + "\n\n<!-- company-comparison:start -->", 1)
    if "<!-- live-comparison:start -->" not in markup:
        markup = markup.replace("    <svg style='width:100%;height:auto;max-height:300px", LIVE_COMPARISON + "\n    <svg style='width:100%;height:auto;max-height:300px", 1)
    template["format"] = markup
    overview = next(n for n in nodes if n["id"] == "fn_overview")
    old_ack = "s.ack=(p.accepted?'Accepted':'Rejected')+' command '+p.command_id;"
    new_ack = ("s.ack=(p.accepted?'Accepted':'Rejected')+' command '+p.command_id"
               "+(p.accepted?'':': '+p.reason);")
    if old_ack in overview["func"]:
        overview["func"] = overview["func"].replace(old_ack, new_ack)
    func = overview["func"]
    if "s.replayState=s.replayState||" not in func:
        func = func.replace("s.bMap=s.bMap||{};", "s.replayState=s.replayState||{A:'Waiting for device',B:'Waiting for device'};s.bMap=s.bMap||{};", 1)
        func = func.replace("if(t==='team12/ml/train/result')", "if(t==='team12/replay/status'&&['A','B'].includes(p.company)) s.replayState[p.company]=p.state;\nif(t==='team12/ml/train/result')", 1)
        func = func.replace("msg.payload={machines:", "msg.payload={replayState:s.replayState,machines:", 1)
    overview["func"] = func
    action = next(n for n in nodes if n["id"] == "fn_ui_action")
    if "p.kind==='replay'" not in action["func"]:
        action["func"] = action["func"].replace(
            "}else return null;",
            "}else if(p.kind==='replay'&&['A','B'].includes(p.company)){\n dest='team12/replay/control';body={action:'start',company:p.company};\n}else return null;", 1)
    counts = next(n for n in nodes if n["id"] == "fn_db_queries")
    if "AS a_alarm_pct" not in counts["func"]:
        counts["func"] = counts["func"].replace(
            "AS operator_rejects",
            "AS operator_rejects, (SELECT ROUND(100.0*SUM(CASE WHEN status=3 THEN 1 ELSE 0 END)/NULLIF(SUM(CASE WHEN status IN (1,2,3) THEN 1 ELSE 0 END),0),1) FROM machine_events) AS a_alarm_pct, (SELECT ROUND(100.0*SUM(CASE WHEN status='Alarm' THEN 1 ELSE 0 END)/NULLIF(SUM(CASE WHEN status IN ('Production','Alarm') THEN 1 ELSE 0 END),0),1) FROM company_b_events) AS b_alarm_pct, (SELECT MIN(100,ROUND(500.0*SUM(CASE WHEN status=3 THEN 1 ELSE 0 END)/NULLIF(SUM(CASE WHEN status IN (1,2,3) THEN 1 ELSE 0 END),0),1)) FROM machine_events) AS a_alarm_bar, (SELECT MIN(100,ROUND(500.0*SUM(CASE WHEN status='Alarm' THEN 1 ELSE 0 END)/NULLIF(SUM(CASE WHEN status IN ('Production','Alarm') THEN 1 ELSE 0 END),0),1)) FROM company_b_events) AS b_alarm_bar", 1)
    if not any(n["id"] == "in_replay_status" for n in nodes):
        nodes.append({"id":"in_replay_status","type":"mqtt in","z":"team12_tab",
                      "name":"device A/B replay status","topic":"team12/replay/status",
                      "qos":"0","datatype":"json","broker":"mqtt_broker",
                      "x":140,"y":1510,"wires":[["fn_overview"]]})
    FLOW.write_text(json.dumps(nodes, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Dashboard model evaluation updated from results/model_comparison.json")


if __name__ == "__main__":
    main()
