"""Make the model's effect visible live on the dashboard.

Idempotent: running it again changes nothing. It edits nodered/flow.json in
place, keeping its formatting (2-space JSON, CRLF endings).

Adds
  * "Train and use" (train, then switch live forecasts, in one click)
  * a model-switch marker on the forecast trend and a before/after table
  * a live forecast check: each forecast is compared with the real 30
    minutes once they have arrived, giving a live error per model
  * Company B live next-state hit rate against the same-state baseline
  * a stage table with simulated clock, shift progress, queue trend arrows,
    the current bottleneck highlighted and, in the ML-driven line, which
    machine forecast sets each stage's capacity
  * a decision history under the approval card
"""

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from common import CONFIG  # noqa: E402

FLOW = ROOT / "nodered" / "flow.json"
MARK = "id='live-forecast-check'"
SHIFT = int(CONFIG["simulation"]["duration_seconds"])
SLOTS = int(CONFIG["ml"]["horizon_minutes"]) // 5


def replace_once(text, old, new, label):
    if text.count(old) != 1:
        raise SystemExit(f"{label}: expected one match for {old[:70]!r}")
    return text.replace(old, new)


# Actual items in the 30 minutes a forecast covers (slots after ts_dataset).
# Replays of the same dataset repeat timestamps, so take one row per slot.
WINDOW_END = "replace(datetime(substr(f.ts_dataset,1,19),'+30 minutes'),' ','T')||'+00:00'"
LIVE_SQL = (
    "SELECT f.id, f.asset, f.model, substr(f.ts_dataset,12,5) AS at, ROUND(f.predicted_items,1) AS predicted, "
    "(SELECT SUM(items) FROM (SELECT e.ts_dataset, MAX(e.items) AS items FROM machine_events e "
    f"WHERE e.asset=f.asset AND e.ts_dataset>f.ts_dataset AND e.ts_dataset<={WINDOW_END} "
    "GROUP BY e.ts_dataset)) AS actual, "
    "(SELECT COUNT(DISTINCT e.ts_dataset) FROM machine_events e "
    f"WHERE e.asset=f.asset AND e.ts_dataset>f.ts_dataset AND e.ts_dataset<={WINDOW_END}) AS slots "
    "FROM forecasts f WHERE f.ts_dataset IS NOT NULL ORDER BY f.id DESC LIMIT 600"
)
B_HITS_SQL = (
    "SELECT f.model, COUNT(*) AS n, SUM(f.predicted_next_status=e.status) AS hits, "
    "SUM(f.current_status=e.status) AS same_hits, "
    "SUM(f.current_status<>e.status) AS changes, "
    "SUM(f.current_status<>e.status AND f.predicted_next_status=e.status) AS change_hits "
    "FROM company_b_forecasts f JOIN (SELECT asset, ts_dataset, MAX(status) AS status FROM company_b_events "
    "GROUP BY asset, ts_dataset) e ON e.asset=f.asset AND "
    "e.ts_dataset=replace(datetime(substr(f.ts_dataset,1,19),'+1 minutes'),' ','T')||'+00:00' "
    "GROUP BY f.model"
)
HISTORY_SQL = (
    "SELECT substr(ts_replay,12,8) AS at, sim_second, stage_name, old_rate, new_rate, decision "
    "FROM sim_reviews ORDER BY id DESC LIMIT 8"
)

OVERVIEW_DB = """
if(t==='team12/db/live-checks'&&Array.isArray(p)){
 const done=p.filter(r=>r.slots===__SLOTS__&&r.actual!==null);
 const by={};done.forEach(r=>{const m=by[r.model]||(by[r.model]={model:r.model,n:0,abs:0,bias:0});m.n++;m.abs+=Math.abs(r.predicted-r.actual);m.bias+=r.predicted-r.actual;});
 s.live={pending:p.length-done.length,checked:done.length,
  byModel:Object.values(by).map(m=>({model:m.model,n:m.n,mae:(m.abs/m.n).toFixed(2),bias:(m.bias/m.n).toFixed(2)})).sort((a,b)=>a.mae-b.mae),
  recent:done.slice(0,8).map(r=>({...r,error:(r.predicted-r.actual).toFixed(1)}))};
 const focus=done.length?done[0].asset:null;
 const pts=done.filter(r=>r.asset===focus).slice(0,30).sort((a,b)=>a.at<b.at?-1:(a.at>b.at?1:a.id-b.id));
 const top=Math.max(1,...pts.map(r=>Math.max(r.predicted,r.actual)));
 const xy=(v,i,a)=>(5+(a.length===1?0:i/(a.length-1)*93)).toFixed(1)+','+(95-v/top*85).toFixed(1);
 s.live.max=Math.ceil(top);s.live.focus=focus;s.live.predPoints=pts.map((r,i,a)=>xy(r.predicted,i,a)).join(' ');s.live.actPoints=pts.map((r,i,a)=>xy(r.actual,i,a)).join(' ');
}
if(t==='team12/db/b-hits'&&Array.isArray(p)) s.bHits=p.map(r=>({...r,rate:r.n?Math.round(100*r.hits/r.n):0,same:r.n?Math.round(100*r.same_hits/r.n):0,changeRate:r.changes?Math.round(100*r.change_hits/r.changes):null}));
if(t==='team12/db/history'&&Array.isArray(p)) s.history=p;
"""

FORECAST_TRACK = """
 s.forecastModels=s.forecastModels||{};s.lastForecast=s.lastForecast||{};s.switchCompare=s.switchCompare||{};
 s.forecastModels[key]=(s.forecastModels[key]||[]).concat([p.model]).slice(-30);
 const prevF=s.lastForecast[key];
 if(prevF&&prevF.model!==p.model) s.switchCompare[key]={machine:p.asset,from:prevF.model,before:prevF.value.toFixed(1),to:p.model,after:Number(p.predicted_items).toFixed(1)};
 s.lastForecast[key]={model:p.model,value:Number(p.predicted_items)};
"""

STAGE_TRACK = """
 const prevQ={};(s.stages||[]).forEach(x=>prevQ[x.stage_index]=x.queue_length);
 const worst=p.stages.reduce((a,x)=>(!a||x.busy_share>a.busy_share||(x.busy_share===a.busy_share&&x.queue_length>a.queue_length))?x:a,null);
 const secs=Number(p.sim_second||0);const hh=String(Math.floor(secs/3600)).padStart(2,'0'),mm=String(Math.floor(secs%3600/60)).padStart(2,'0');
 s.sim={clock:hh+':'+mm,progress:Math.min(100,Math.round(100*secs/__SHIFT__)),updated:new Date().toLocaleTimeString(),ml:p.ml_model||null};
 s.stages=p.stages.map(x=>({...x,busy:Math.round(Number(x.busy_share||0)*100),limiting:worst&&x.stage_index===worst.stage_index&&x.busy_share>=0.9,
  trend:prevQ[x.stage_index]===undefined?'':(x.queue_length>prevQ[x.stage_index]?'▲':(x.queue_length<prevQ[x.stage_index]?'▼':'•')),
  capacityPct:x.ml_forecast!==null&&x.ml_forecast!==undefined?Math.round(100*Number(x.ml_factor||1)):null}));
"""


def main():
    flow = json.loads(FLOW.read_text(encoding="utf-8"))
    nodes = {n["id"]: n for n in flow}
    template = nodes["ui_overview"]
    if MARK in template["format"]:
        print("Live model view already installed; nothing to do.")
        return
    crlf = b"\r\n" in FLOW.read_bytes()

    # 1. Store the dataset time of every forecast, so it can be checked later.
    fc = nodes["fn_forecast"]
    fc["func"] = replace_once(fc["func"], "prediction_guarded, guard_limit) VALUES ($tsr,$a,$h,$p,$model,$guarded,$limit)'",
                              "prediction_guarded, guard_limit, ts_dataset) VALUES ($tsr,$a,$h,$p,$model,$guarded,$limit,$tsd)'",
                              "fn_forecast sql")
    fc["func"] = replace_once(fc["func"], "$limit: f.guard_limit }", "$limit: f.guard_limit, $tsd: f.ts_dataset || null }",
                              "fn_forecast params")

    # 2. "Train and use".
    a = nodes["fn_ui_action"]
    a["func"] = replace_once(a["func"], "if(p.seed==='new')body.seed='new';",
                             "if(p.seed==='new')body.seed='new';if(p.use===true)body.use=true;", "fn_ui_action")

    # 3. Three more read-back queries, each with its own SQLite node.
    q = nodes["fn_db_queries"]
    q["func"] = replace_once(
        q["func"], "return [counts,recent,models,bRecent];",
        "const liveChecks={topic:" + json.dumps(LIVE_SQL) + ",payload:[]};"
        "const bHits={topic:" + json.dumps(B_HITS_SQL) + ",payload:[]};"
        "const history={topic:" + json.dumps(HISTORY_SQL) + ",payload:[]};"
        "return [counts,recent,models,bRecent,liveChecks,bHits,history];", "fn_db_queries")
    q["outputs"] = 7
    template_db, template_fn = nodes["db_counts"], nodes["fn_db_recent"]
    for i, (name, topic_name) in enumerate((("live", "live-checks"), ("b_hits", "b-hits"), ("history", "history"))):
        db = copy.deepcopy(template_db)
        db.update({"id": f"db_{name}", "name": f"read {topic_name}", "y": template_db.get("y", 0) + 60 * (i + 4),
                   "wires": [[f"fn_db_{name}"]]})
        fn = copy.deepcopy(template_fn)
        fn.update({"id": f"fn_db_{name}", "name": f"tag {topic_name}", "y": db["y"],
                   "func": f"msg.topic='team12/db/{topic_name}';msg.payload=Array.isArray(msg.payload)?msg.payload:[];return msg;",
                   "wires": [["fn_overview"]]})
        flow.extend([db, fn])
        q["wires"].append([db["id"]])

    # 4. Overview function.
    o = nodes["fn_overview"]
    f = o["func"]
    f = replace_once(f, "s.forecastHistory[key]=(s.forecastHistory[key]||[]).concat([Number(p.predicted_items)]).slice(-30);\n",
                     "s.forecastHistory[key]=(s.forecastHistory[key]||[]).concat([Number(p.predicted_items)]).slice(-30);\n"
                     + FORECAST_TRACK.strip("\n") + "\n", "forecast tracking")
    f = replace_once(f, "if(t==='team12/ml/active') {if(p.status==='active') s.activeModel=p;else s.modelError=p.error;}",
                     "if(t==='team12/ml/active') {if(p.status==='active'){if(!s.activeModel||s.activeModel.model!==p.model){"
                     "s.switchInfo={model:p.model,at:new Date().toLocaleTimeString()};s.switchCompare={};}s.activeModel=p;s.modelError=null;}"
                     "else s.modelError=p.error;}", "ml active")
    f = replace_once(f, " s.arrival=p.arrival_source?{scale:p.arrival_scale,model:p.arrival_source}:null;\n"
                        " s.stages=p.stages.map(x=>({...x,busy:Math.round(Number(x.busy_share||0)*100)}));\n",
                     STAGE_TRACK.replace("__SHIFT__", str(SHIFT)).strip("\n") + "\n", "stage tracking")
    f = replace_once(f, "const colors=['#087ba5','#d97706','#4e70b5','#64748b'];",
                     OVERVIEW_DB.replace("__SLOTS__", str(SLOTS)).strip("\n") + "\n"
                     "const colors=['#087ba5','#d97706','#4e70b5','#64748b'];", "db topics")
    f = replace_once(f, "msg.payload={arrival:s.arrival||null,",
                     "const fm=Object.values(s.forecastModels||{})[0]||[];const marks=[];"
                     "fm.forEach((m,i)=>{if(i>0&&m!==fm[i-1])marks.push({x:(5+(fm.length===1?0:i/(fm.length-1)*93)).toFixed(1),label:m});});\n"
                     "msg.payload={forecastMarks:marks,switchInfo:s.switchInfo||null,switchRows:Object.values(s.switchCompare||{}).sort((a,b)=>a.machine-b.machine),"
                     "live:s.live||null,bHits:s.bHits||[],history:s.history||[],sim:s.sim||null,", "payload")
    o["func"] = f

    # 5. Template.
    t = template["format"]
    t = replace_once(
        t, "<button class='btn secondary' ng-click='send({payload:{kind:\"train\",model:m.id,seed:\"new\"}})'>Train with new seed</button>",
        "<button class='btn secondary' ng-click='send({payload:{kind:\"train\",model:m.id,seed:\"new\"}})'>Train with new seed</button>"
        "<button class='btn secondary' ng-click='send({payload:{kind:\"train\",model:m.id,use:true}})'>Train and use</button>",
        "train and use")
    t = replace_once(
        t, "    <p class='status'>Active forecasting model: <b>{{msg.payload.activeModel.model}}</b>",
        "    <div class='callout' ng-if='msg.payload.switchInfo'><b>Live forecasts switched to {{msg.payload.switchInfo.model}} at {{msg.payload.switchInfo.at}}.</b>"
        " <span ng-if='!msg.payload.switchRows.length'>Re-forecasting the latest windows…</span>"
        "<table ng-if='msg.payload.switchRows.length'><thead><tr><th>Machine</th><th>Before</th><th>After</th></tr></thead><tbody>"
        "<tr ng-repeat='r in msg.payload.switchRows'><td>{{r.machine}}</td><td>{{r.before}} items ({{r.from}})</td><td><b>{{r.after}} items</b> ({{r.to}})</td></tr>"
        "</tbody></table></div>\n"
        "    <p class='status'>Active forecasting model: <b>{{msg.payload.activeModel.model}}</b>",
        "switch callout")
    t = replace_once(
        t, "<polyline ng-repeat='line in msg.payload.forecastLines track by line.name'",
        "<line ng-repeat='mk in msg.payload.forecastMarks' ng-attr-x1='{{mk.x}}' ng-attr-x2='{{mk.x}}' y1='5' y2='95' stroke='#a83838' "
        "stroke-width='1' stroke-dasharray='3 2' vector-effect='non-scaling-stroke'/>"
        "<polyline ng-repeat='line in msg.payload.forecastLines track by line.name'", "forecast marker")
    t = replace_once(
        t, "<p class='muted'>Horizontal: recent replay updates. Vertical: predicted items, 0 to {{msg.payload.forecastMax}}.</p>",
        "<p class='muted'>Horizontal: recent replay updates. Vertical: predicted items, 0 to {{msg.payload.forecastMax}}."
        "<span ng-repeat='mk in msg.payload.forecastMarks'> Red dashed line: switched to <b>{{mk.label}}</b>.</span>"
        "<span ng-if='msg.payload.switchInfo'> New points since {{msg.payload.switchInfo.at}} come from <b>{{msg.payload.switchInfo.model}}</b>.</span></p>",
        "forecast marker note")

    live_panel = """  <div class='panel wide' id='live-forecast-check'><span class='badge'>LIVE MODEL CHECK</span><h3>Forecast vs what really happened</h3>
    <p class='muted'>Each forecast covers the next 30 minutes. Once those 30 minutes of replayed data have arrived, the forecast is scored against the real total. This is measured live, in this run, for whichever model made the forecast.</p>
    <div class='kpis'>
      <div class='kpi' ng-repeat='m in msg.payload.live.byModel'><strong>{{m.mae}}</strong><small>{{m.model}}: average error in items over {{m.n}} checked forecasts (bias {{m.bias}})</small></div>
      <div class='kpi' ng-if='msg.payload.live'><strong>{{msg.payload.live.pending}}</strong><small>Forecasts still waiting for their 30 minutes of data</small></div>
    </div>
    <p class='muted' ng-if='!msg.payload.live || !msg.payload.live.checked'>No forecast has been checked yet; the first checks appear about 30 dataset minutes after Company A starts.</p>
    <div ng-if='msg.payload.live.checked'>
      <svg class='chart' viewBox='0 0 100 100' preserveAspectRatio='none'><line x1='5' y1='95' x2='98' y2='95' stroke='#bdcbd7' stroke-width='.4'/><polyline ng-attr-points='{{msg.payload.live.actPoints}}' fill='none' stroke='#64748b' stroke-width='1.5' vector-effect='non-scaling-stroke'/><polyline ng-attr-points='{{msg.payload.live.predPoints}}' fill='none' stroke='#087ba5' stroke-width='1.5' stroke-dasharray='4 2' vector-effect='non-scaling-stroke'/></svg>
      <div class='legend'><span><i class='key' style='background:#087ba5'></i>Forecast</span><span><i class='key' style='background:#64748b'></i>Actual 30-minute total</span><span class='muted'>Machine {{msg.payload.live.focus}}, last checked forecasts in data-time order, 0 to {{msg.payload.live.max}} items</span></div>
      <div class='tablewrap'><table><thead><tr><th>Machine</th><th>Data time</th><th>Model</th><th>Forecast</th><th>Actual</th><th>Error</th></tr></thead><tbody><tr ng-repeat='r in msg.payload.live.recent'><td>{{r.asset}}</td><td>{{r.at}}</td><td>{{r.model}}</td><td>{{r.predicted}}</td><td>{{r.actual}}</td><td>{{r.error}}</td></tr></tbody></table></div>
    </div>
  </div>
"""
    stage_old = ("<h3>Stage status</h3><div class='tablewrap'><table><thead><tr><th>Stage</th><th>Waiting</th><th>Busy</th><th>Rate (tokens/min)</th></tr></thead>"
                 "<tbody><tr ng-repeat='s in msg.payload.stages track by s.stage_index'><td>{{s.stage_name}}</td><td>{{s.queue_length}}</td><td>{{s.busy}}%</td><td>{{s.rate_per_min}}</td></tr></tbody></table></div>")
    stage_new = ("<h3>Stage status</h3>"
                 "<div ng-if='msg.payload.sim'><div class='comparebar'><span ng-style='{\"width\":msg.payload.sim.progress+\"%\"}'></span></div>"
                 "<p class='muted'>Simulated shift time <b>{{msg.payload.sim.clock}}</b> of 08:00 ({{msg.payload.sim.progress}}%) · last update {{msg.payload.sim.updated}}"
                 "<span ng-if='msg.payload.sim.ml'> · ML-driven line: capacities follow <b>{{msg.payload.sim.ml}}</b> forecasts</span></p></div>"
                 "<div class='tablewrap'><table><thead><tr><th>Stage</th><th>Waiting</th><th>Busy</th><th>Rate set (tokens/min)</th>"
                 "<th ng-if='msg.payload.sim.ml'>Model capacity</th></tr></thead>"
                 "<tbody><tr ng-repeat='s in msg.payload.stages track by s.stage_index' ng-class='{selected:s.limiting}'>"
                 "<td>{{s.stage_name}}<span ng-if='s.limiting'> · current bottleneck</span></td><td>{{s.queue_length}} {{s.trend}}</td><td>{{s.busy}}%</td><td>{{s.rate_per_min}}</td>"
                 "<td ng-if='msg.payload.sim.ml'><span ng-if='s.capacityPct!==null'>{{s.effective_rate}}/min ({{s.capacityPct}}%) · machine {{s.ml_machine}} forecast {{s.ml_forecast}}</span></td></tr></tbody></table></div>"
                 "<p class='muted'>▲ queue grew since the last update, ▼ shrank, • unchanged. The highlighted row is the stage working hardest right now.</p>")
    t = replace_once(t, stage_old, stage_new, "stage table")
    t = replace_once(
        t, "<p class='status' ng-if='msg.payload.arrival'>ML-driven arrivals: material entering Stage 1 is scaled ×{{msg.payload.arrival.scale}} by the {{msg.payload.arrival.model}} forecasts (bounded 0.7–1.3×).</p>",
        "", "old arrival note")
    t = replace_once(t, "  <div class='panel wide'><span class='badge sim'>SIMULATED LINE</span><h3>Stage status</h3>",
                     live_panel + "  <div class='panel wide'><span class='badge sim'>SIMULATED LINE</span><h3>Stage status</h3>", "live panel")
    t = replace_once(
        t, "<span class='muted'>Starts a new simulated 8-hour shift on the device so the bottleneck can be shown again.</span></div>\n",
        "<span class='muted'>Starts a new simulated 8-hour shift on the device so the bottleneck can be shown again.</span></div>\n"
        "    <div class='tablewrap' ng-if='msg.payload.history.length'><table><thead><tr><th>Decision time</th><th>Shift time</th><th>Stage</th><th>Proposed rate</th><th>Operator</th></tr></thead>"
        "<tbody><tr ng-repeat='h in msg.payload.history'><td>{{h.at}}</td><td>{{(h.sim_second/3600)|number:1}} h</td><td>{{h.stage_name}}</td><td>{{h.old_rate}} → {{h.new_rate}}</td><td>{{h.decision==='accept'?'Accepted':'Rejected'}}</td></tr></tbody></table></div>\n",
        "history")
    t = replace_once(
        t, "Prediction assumes another report exactly one dataset minute later. It is not a measured outcome.</div>",
        "Prediction assumes another report exactly one dataset minute later. It is not a measured outcome.</div>\n"
        "    <div class='kpis' ng-if='msg.payload.bHits.length'><div class='kpi' ng-repeat='h in msg.payload.bHits'><strong>{{h.rate}}%</strong>"
        "<small>{{h.model}}: next state predicted correctly, live, over {{h.n}} checked reports. Same-state guess: {{h.same}}%."
        "<span ng-if='h.changeRate!==null'> When the state changed: {{h.changeRate}}% of {{h.changes}}.</span></small></div></div>",
        "b hits")
    template["format"] = t

    text = json.dumps(flow, indent=2, ensure_ascii=False) + "\n"
    if crlf:
        text = text.replace("\n", "\r\n")
    FLOW.write_bytes(text.encode("utf-8"))
    print("Installed the live model view.")


if __name__ == "__main__":
    main()
