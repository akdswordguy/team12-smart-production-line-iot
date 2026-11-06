"""Add the classroom training and approval controls to the Node-RED flow.

Safe to rerun: nodes have stable IDs and markup has explicit boundaries.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "nodered" / "flow.json"
flow = json.loads(FILE.read_text(encoding="utf-8"))
nodes = {n["id"]: n for n in flow}
if "id='interactive-ml'" in nodes["ui_overview"]["format"]:
    print("Interactive controls already installed in", FILE)
    raise SystemExit(0)


def add(node):
    nodes[node["id"]] = node


def mqtt_in(node_id, name, topic_name, targets, y):
    add({"id": node_id, "type": "mqtt in", "z": "team12_tab", "name": name,
         "topic": topic_name, "qos": "0", "datatype": "json",
         "broker": "mqtt_broker", "x": 155, "y": y, "wires": [targets]})


def function(node_id, name, code, targets, y):
    add({"id": node_id, "type": "function", "z": "team12_tab", "name": name,
         "func": code, "outputs": 1, "x": 465, "y": y, "wires": [targets]})


mqtt_in("in_ml_train", "ML demo training result", "team12/ml/train/result",
        ["fn_ml_train", "fn_overview"], 1280)
mqtt_in("in_ml_active", "active forecast model", "team12/ml/active",
        ["fn_overview"], 1320)
mqtt_in("in_sim_proposal", "virtual line proposal", "team12/sim/proposal",
        ["fn_overview"], 1360)
mqtt_in("in_sim_review", "operator decision", "team12/sim/review",
        ["fn_sim_review", "fn_overview"], 1400)

function("fn_ml_train", "save real demo training metrics", """
const p=msg.payload;
if(p.status!=='trained') return null;
return {topic:'INSERT INTO ml_demo_runs (ts_replay,model,train_rows,valid_rows,active_valid_rows,active_mae,idle_mae,overall_mae,train_seconds) VALUES ($ts,$m,$tr,$vr,$av,$a,$i,$o,$s)',params:{$ts:p.ts_replay,$m:p.model,$tr:p.train_rows,$vr:p.valid_rows,$av:p.active_valid_rows,$a:p.active_mae,$i:p.idle_mae,$o:p.overall_mae,$s:p.train_seconds}};
""".strip(), ["sql_bind"], 1280)
function("fn_sim_review", "save operator accept or reject", """
const p=msg.payload;
return {topic:'INSERT INTO sim_reviews (proposal_id,ts_replay,decision,sim_second,stage_index,stage_name,old_rate,new_rate,reason) VALUES ($id,$ts,$d,$sec,$idx,$name,$old,$new,$reason)',params:{$id:p.proposal_id,$ts:p.ts_replay,$d:p.decision,$sec:p.sim_second,$idx:p.stage_index,$name:p.stage_name,$old:p.old_rate,$new:p.new_rate,$reason:p.reason}};
""".strip(), ["sql_bind"], 1400)
function("fn_ui_action", "validate dashboard control", """
const p=msg.payload||{};
const allowed=['ridge','gradient_boosting','neural_network'];
let dest,body;
if(p.kind==='train'&&allowed.includes(p.model)){
 dest='team12/ml/train/request';body={model:p.model};
}else if(p.kind==='select'&&(allowed.includes(p.model)||p.model==='validated_winner')){
 dest='team12/ml/select';body={model:p.model};
}else if(p.kind==='review'&&['accept','reject'].includes(p.decision)&&/^[a-f0-9]{8}$/.test(p.proposal_id||'')){
 dest='team12/sim/approval';body={proposal_id:p.proposal_id,decision:p.decision};
}else return null;
return {topic:dest,payload:JSON.stringify(body)};
""".strip(), ["out_ui_action"], 1450)
add({"id": "out_ui_action", "type": "mqtt out", "z": "team12_tab",
     "name": "dashboard request to MQTT", "topic": "", "qos": "0",
     "retain": "false", "respTopic": "", "contentType": "",
     "userProps": "", "correl": "", "expiry": "",
     "broker": "mqtt_broker", "x": 740, "y": 1450, "wires": []})

forecast_code = nodes["fn_forecast"]["func"]
forecast_code = forecast_code.replace(
    "(ts_replay, asset, horizon_minutes, predicted_items, model) VALUES ($tsr,$a,$h,$p,$model)",
    "(ts_replay, asset, horizon_minutes, predicted_items, model, prediction_guarded, guard_limit) VALUES ($tsr,$a,$h,$p,$model,$guarded,$limit)")
forecast_code = forecast_code.replace("$model: f.model }", "$model: f.model, $guarded: f.prediction_guarded ? 1 : 0, $limit: f.guard_limit }")
nodes["fn_forecast"]["func"] = forecast_code

overview = nodes["fn_overview"]
code = overview["func"]
code = code.replace("Number(p.predicted_items).toFixed(1)+' items';", "Number(p.predicted_items).toFixed(1)+' items'+(p.prediction_guarded?' (training-range cap)':'');")
code = code.replace("dbRows:[]};", "dbRows:[],demoModels:{},activeModel:{model:'gradient_boosting',provenance:'full_validated_study'},proposal:null,reviewText:'No operator decision yet'};")
code = code.replace("s.outputHistory=s.outputHistory||{};", "s.demoModels=s.demoModels||{};s.activeModel=s.activeModel||{model:'gradient_boosting',provenance:'full_validated_study'};s.outputHistory=s.outputHistory||{};")
code = code.replace("if(t==='team12/db/counts')", """if(t==='team12/ml/train/result') s.demoModels[p.model]=p;
if(t==='team12/db/models'&&Array.isArray(p)) p.forEach(r=>{if(!s.demoModels[r.model]||s.demoModels[r.model].status==='trained')s.demoModels[r.model]={...r,status:'trained'};});
if(t==='team12/ml/active') {if(p.status==='active') s.activeModel=p;else s.modelError=p.error;}
if(t==='team12/sim/proposal') {s.proposal=p;s.reviewText='Waiting for operator choice';}
if(t==='team12/sim/review') {if(s.proposal&&s.proposal.command_id===p.proposal_id)s.proposal=null;s.reviewText=(p.decision==='accept'?'Accepted':'Rejected')+' proposal '+p.proposal_id+' for '+p.stage_name;}
if(t==='team12/db/counts')""")
code = code.replace("dbRows:s.dbRows||[]};", "dbRows:s.dbRows||[],demoModels:s.demoModels,activeModel:s.activeModel,modelError:s.modelError,proposal:s.proposal,reviewText:s.reviewText};")
code = code.replace("context.set('overview',s);", """const trained=Object.entries(s.demoModels).filter(([name,r])=>r.status==='trained'&&Number.isFinite(Number(r.active_mae)));
trained.sort((a,b)=>Number(a[1].active_mae)-Number(b[1].active_mae));
const demoLeader=trained.length===3?trained[0][0]+' (active MAE '+trained[0][1].active_mae+')':'Train all three to compare the quick-run scores';
context.set('overview',s);""")
code = code.replace("demoModels:s.demoModels,activeModel", "demoModels:s.demoModels,demoLeader:demoLeader,activeModel")
overview["func"] = code

template = nodes["ui_overview"]
template["wires"] = [["fn_ui_action"]]
markup = template["format"]
markup = markup.replace("</style>", """
.t12 .controls{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.t12 .btn{border:0;border-radius:6px;background:#087ba5;color:#fff;padding:9px 13px;font:700 13px Arial;cursor:pointer}
.t12 .btn:disabled{opacity:.45;cursor:not-allowed}
.t12 .btn.secondary{background:#e7f0f5;color:#174765}
.t12 .btn.reject{background:#a83838}
.t12 .demo-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:12px}
.t12 .demo-card{border:1px solid #dce7ee;border-radius:8px;padding:14px;background:#f8fbfd}
.t12 .demo-card h4{margin:0 0 7px;font-size:14px}
@media(max-width:760px){.t12 .demo-grid{grid-template-columns:1fr}}
</style>""")
model_panel = """
  <div class='panel wide' id='interactive-ml'>
    <div class='sectionlabel'>Interactive ML lab · fixed Company A data</div>
    <h3>Train and compare three models</h3>
    <p class='muted'>Each button really fits a new model on the same 50,000-row chronological pre-replay demo slice. A 25-minute label embargo protects the validation period. These quick-run scores are separate from the full 681,935-example evaluation above.</p>
    <div class='demo-grid'>
      <div class='demo-card' ng-repeat='m in [{id:"ridge",name:"Ridge regression",family:"Traditional"},{id:"gradient_boosting",name:"Gradient boosting",family:"Ensemble"},{id:"neural_network",name:"Neural network",family:"Two hidden layers"}]'>
        <h4>{{m.name}}</h4><div class='muted'>{{m.family}}</div>
        <div class='metric' ng-if='msg.payload.demoModels[m.id].status==="trained"'>{{msg.payload.demoModels[m.id].active_mae}} <small>active MAE</small></div>
        <div class='muted' ng-if='msg.payload.demoModels[m.id].status==="trained"'>Overall MAE {{msg.payload.demoModels[m.id].overall_mae}} · idle MAE {{msg.payload.demoModels[m.id].idle_mae}} · {{msg.payload.demoModels[m.id].train_rows}} train / {{msg.payload.demoModels[m.id].valid_rows}} validation · {{msg.payload.demoModels[m.id].train_seconds}}s</div>
        <div class='status' ng-if='msg.payload.demoModels[m.id].status==="training"'>Training on real data…</div>
        <div class='status' ng-if='msg.payload.demoModels[m.id].status==="error" || msg.payload.demoModels[m.id].status==="busy"'>{{msg.payload.demoModels[m.id].error}}</div>
        <div class='controls'><button class='btn' ng-click='send({payload:{kind:"train",model:m.id}})'>Train demo model</button><button class='btn secondary' ng-disabled='msg.payload.demoModels[m.id].status!=="trained"' ng-click='send({payload:{kind:"select",model:m.id}})'>Use for live forecasts</button></div>
      </div>
    </div>
    <p class='status'><b>Quick-run leader:</b> {{msg.payload.demoLeader}}</p>
    <div class='controls'><button class='btn secondary' ng-click='send({payload:{kind:"select",model:"validated_winner"}})'>Restore full-study winner</button></div>
    <p class='status'>Active forecasting model: <b>{{msg.payload.activeModel.model}}</b> · {{msg.payload.activeModel.provenance}} <span ng-if='msg.payload.modelError'> · {{msg.payload.modelError}}</span></p>
    <p class='muted'>The full study chose gradient boosting by time-ordered validation. Quick models use the same training-derived per-machine range guard; capped live forecasts are marked. Switching here changes subsequent forecasts; it does not retrain the full study or claim a physical factory improvement.</p>
  </div>
"""
markup = markup.replace("<!-- model-evaluation:end -->", "<!-- model-evaluation:end -->" + model_panel)
review_panel = """
  <div class='panel wide' id='operator-review'><span class='badge sim'>SIMULATED LINE</span><h3>Approve a proposed bottleneck action</h3>
    <div ng-if='msg.payload.proposal'>
      <div class='metric'>{{msg.payload.proposal.stage_name}}: {{msg.payload.proposal.old_rate}} → {{msg.payload.proposal.new_rate}} tokens/min</div>
      <p>{{msg.payload.proposal.reason}}</p>
      <div class='controls'><button class='btn' ng-click='send({payload:{kind:"review",decision:"accept",proposal_id:msg.payload.proposal.command_id}})'>Accept and send command</button><button class='btn reject' ng-click='send({payload:{kind:"review",decision:"reject",proposal_id:msg.payload.proposal.command_id}})'>Reject action</button></div>
    </div>
    <p ng-if='!msg.payload.proposal' class='muted'>Waiting for a sustained simulated bottleneck. No command is sent without your acceptance.</p>
    <div class='status'>{{msg.payload.reviewText}}</div>
  </div>
"""
markup = markup.replace("  <div class='panel'><h3>Decision sent through MQTT</h3>", review_panel + "  <div class='panel'><h3>Decision sent through MQTT</h3>")
template["format"] = markup

query = nodes["fn_db_queries"]
query["func"] = query["func"].replace("AS acknowledgements", "AS acknowledgements, (SELECT COUNT(*) FROM ml_demo_runs) AS demo_trainings, (SELECT COUNT(*) FROM sim_reviews WHERE decision='accept') AS operator_accepts, (SELECT COUNT(*) FROM sim_reviews WHERE decision='reject') AS operator_rejects")
query["func"] = query["func"].replace("AS forecasts,", "AS forecasts, (SELECT COUNT(*) FROM forecasts WHERE prediction_guarded=1) AS guarded_forecasts,")
query["func"] = query["func"].replace("return [counts,recent];", "const models={topic:\"SELECT r.* FROM ml_demo_runs r JOIN (SELECT model,MAX(id) AS last_id FROM ml_demo_runs GROUP BY model) latest ON r.id=latest.last_id\",payload:[]};return [counts,recent,models];")
query["outputs"] = 3
query["wires"].append(["db_ml_runs"])
add({"id":"db_ml_runs","type":"sqlite","z":"team12_tab","mydb":"sqlite_db",
     "sqlquery":"msg.topic","sql":"","name":"SQLite latest demo models",
     "x":730,"y":1180,"wires":[["fn_db_models"]]})
function("fn_db_models","format latest saved demo training",
         "msg.topic='team12/db/models';msg.payload=Array.isArray(msg.payload)?msg.payload:[];return msg;",
         ["fn_overview"],1180)
markup = template["format"].replace("<small>Accepted / sent commands</small>", "<small>Actuator ACK / sent commands</small>")
markup = markup.replace("    <div class='tablewrap'><table><thead><tr><th>Latest observed row", "    <p class='muted'>Interactive runs saved: {{msg.payload.dbCounts.demo_trainings}} model trainings · {{msg.payload.dbCounts.operator_accepts}} accepted proposals · {{msg.payload.dbCounts.operator_rejects}} rejected proposals.</p>\n    <div class='tablewrap'><table><thead><tr><th>Latest observed row")
markup = markup.replace("model trainings ·", "model trainings · {{msg.payload.dbCounts.guarded_forecasts}} guarded forecasts ·")
template["format"] = markup

FILE.write_text(json.dumps(list(nodes.values()), indent=2, ensure_ascii=False), encoding="utf-8")
print("Installed model controls and approval gate in", FILE)
