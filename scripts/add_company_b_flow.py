"""Install the separate Company B ingestion and dashboard nodes."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "nodered/flow.json"
flow = json.loads(FILE.read_text(encoding="utf-8"))
nodes = {node["id"]: node for node in flow}
if "in_b_raw" in nodes:
    print("Company B flow already installed")
    raise SystemExit(0)


def put(node):
    nodes[node["id"]] = node


def mqtt_in(id_, label, topic, targets, y):
    put({"id": id_, "type": "mqtt in", "z": "team12_tab", "name": label,
         "topic": topic, "qos": "0", "datatype": "json", "broker": "mqtt_broker",
         "x": 150, "y": y, "wires": [targets]})


def fn(id_, label, code, wires, y, outputs=1):
    put({"id": id_, "type": "function", "z": "team12_tab", "name": label,
         "func": code.strip(), "outputs": outputs, "x": 430, "y": y,
         "wires": wires})


mqtt_in("in_b_raw", "Company B real one-minute records",
        "team12/observed_b/machine/#", ["fn_b_validate"], 1550)
fn("fn_b_validate", "validate and store Company B", r"""
const m=msg.payload;
let reason=null;
const states=['Alarm','Standby','MachineOn','Production','Loading','Tooling'];
if(!m||typeof m!=='object'||Array.isArray(m)) reason='B payload not an object';
else if(!Number.isInteger(m.asset)) reason='B asset not an integer';
else if(typeof m.ts_dataset!=='string'||!Number.isFinite(Date.parse(m.ts_dataset))||typeof m.ts_replay!=='string'||!Number.isFinite(Date.parse(m.ts_replay))) reason='B timestamp invalid';
else if(!states.includes(m.status)) reason='B status not documented';
else if(m.source!=='observed_b'||m.company!=='B') reason='B source mismatch';
if(reason) return [null,{topic:'INSERT INTO rejected_records (ts_replay,topic,reason,raw_payload) VALUES ($ts,$topic,$reason,$raw)',params:{$ts:new Date().toISOString(),$topic:msg.topic,$reason:reason,$raw:JSON.stringify(m)}}];
return [{topic:'INSERT OR IGNORE INTO company_b_events (source,run_id,seq,asset,ts_dataset,ts_replay,status,power_avg,alarm_time,loading_time,tooling_time,maintenance_time,support_time) VALUES ($source,$run,$seq,$asset,$tsd,$tsr,$status,$power,$alarm,$loading,$tooling,$maintenance,$support)',validated_payload:m,params:{$source:'observed_b',$run:m.run_id,$seq:m.seq,$asset:m.asset,$tsd:m.ts_dataset,$tsr:m.ts_replay,$status:m.status,$power:Number.isFinite(m.power_avg)?m.power_avg:null,$alarm:m.alarm_time,$loading:m.loading_time,$tooling:m.tooling_time,$maintenance:m.maintenance_time,$support:m.support_time}},null];
""", [["sql_bind"], ["sql_bind"]], 1550, outputs=2)
put({"id": "db_b_events", "type": "sqlite", "z": "team12_tab", "mydb": "sqlite_db",
     "sqlquery": "msg.topic", "sql": "", "name": "SQLite Company B events",
     "x": 790, "y": 1550, "wires": [["fn_b_publish"]]})
# Existing sql_bind targets the original SQLite node. It must route B event
# writes to the B node while all other statements retain their original path.
bind = nodes["sql_bind"]
bind["outputs"] = 2
bind["func"] = bind["func"].replace("return msg;", "if(msg.topic.includes('company_b_events')) return [null,msg]; return [msg,null];")
bind["wires"] = [["db_events"], ["db_b_events"]]
fn("fn_b_publish", "publish B only after SQLite success", """
const m=msg.validated_payload;
if(!m)return null;
return {topic:'team12/observed_b/validated/'+m.asset,payload:JSON.stringify(m)};
""", [["out_b_validated"]], 1550)
put({"id":"out_b_validated","type":"mqtt out","z":"team12_tab",
     "name":"stored B records to analytics","topic":"","qos":"0","retain":"false",
     "respTopic":"","contentType":"","userProps":"","correl":"","expiry":"",
     "broker":"mqtt_broker","x":1060,"y":1550,"wires":[]})
mqtt_in("in_b_metrics", "Company B rolling state metrics",
        "team12/observed_b/metrics/#", ["fn_b_store_metrics", "fn_overview"], 1610)
fn("fn_b_store_metrics", "save B rolling metrics", """
const p=msg.payload;
return {topic:'INSERT INTO company_b_metrics (asset,ts_dataset,ts_replay,latest_status,reports_30m,production_share,alarm_share,conditional_alarm_pct) VALUES ($a,$tsd,$tsr,$status,$n,$prod,$alarm,$conditional)',params:{$a:p.asset,$tsd:p.ts_dataset,$tsr:p.ts_replay,$status:p.latest_status,$n:p.reports_30m,$prod:p.production_share,$alarm:p.alarm_share,$conditional:p.conditional_alarm_pct}};
""", [["sql_bind"]], 1610)

overview = nodes["fn_overview"]
code = overview["func"]
code = code.replace("reviewText:'No operator decision yet'};", "reviewText:'No operator decision yet',bMap:{},bRows:[]};")
code = code.replace("s.demoModels=s.demoModels||{};", "s.bMap=s.bMap||{};s.bRows=s.bRows||[];s.demoModels=s.demoModels||{};")
code = code.replace("if(t==='team12/db/counts')", """if(t.startsWith('team12/observed_b/metrics/')) s.bMap[p.asset]={asset:p.asset,status:p.latest_status,reports:p.reports_30m,production:Math.round(100*p.production_share),alarm:Math.round(100*p.alarm_share)};
if(t==='team12/db/b-recent'&&Array.isArray(p)) s.bRows=p;
if(t==='team12/db/counts')""")
code = code.replace("context.set('overview',s);", """const bStatuses=['Production','Standby','MachineOn','Loading','Tooling','Alarm'];
const bValues=Object.values(s.bMap);
const bStatusBars=bStatuses.map(name=>({name,count:bValues.filter(x=>x.status===name).length,pct:bValues.length?Math.round(100*bValues.filter(x=>x.status===name).length/bValues.length):0}));
context.set('overview',s);""")
code = code.replace("reviewText:s.reviewText};", "reviewText:s.reviewText,bMachines:bValues.sort((a,b)=>a.asset-b.asset),bRows:s.bRows,bStatusBars:bStatusBars};")
overview["func"] = code

queries = nodes["fn_db_queries"]
queries["func"] = queries["func"].replace("AS accepted,", "AS accepted, (SELECT COUNT(*) FROM company_b_events) AS b_accepted, (SELECT COUNT(*) FROM company_b_metrics) AS b_metrics,")
queries["func"] = queries["func"].replace("return [counts,recent,models];", "const bRecent={topic:\"SELECT id,asset,substr(ts_dataset,1,16) AS ts_dataset,status FROM company_b_events ORDER BY id DESC LIMIT 8\",payload:[]};return [counts,recent,models,bRecent];")
queries["outputs"] = 4
queries["wires"].append(["db_b_recent"])
put({"id":"db_b_recent","type":"sqlite","z":"team12_tab","mydb":"sqlite_db",
     "sqlquery":"msg.topic","sql":"","name":"SQLite recent B records",
     "x":730,"y":1220,"wires":[["fn_db_b_recent"]]})
fn("fn_db_b_recent","format stored B rows",
   "msg.topic='team12/db/b-recent';msg.payload=Array.isArray(msg.payload)?msg.payload:[];return msg;",
   [["fn_overview"]],1220)

template = nodes["ui_overview"]
markup = template["format"]
markup = markup.replace("  <div class='panel wide' id='database-status'>", """
  <div class='panel wide' id='company-b-live'>
    <div class='sectionlabel'>Company B · live one-minute replay</div>
    <h3>Operating states from stored Company B records</h3>
    <p class='muted'>Company B has no item-count column. Its 14 reporting machines in this replay are shown separately from Company A. The state bars describe the latest reported state per machine.</p>
    <div class='demo-grid'><div class='demo-card' ng-repeat='bar in msg.payload.bStatusBars'><b>{{bar.name}}</b><div class='bartrack'><div class='barfill' ng-style='{"width":bar.pct+"%"}'></div></div><span class='muted'>{{bar.count}} machines · {{bar.pct}}%</span></div></div>
    <p>Company B records saved: <b>{{msg.payload.dbCounts.b_accepted}}</b> · rolling metrics saved: <b>{{msg.payload.dbCounts.b_metrics}}</b></p>
    <div class='tablewrap'><table><thead><tr><th>Dataset time</th><th>Machine</th><th>State</th></tr></thead><tbody><tr ng-repeat='r in msg.payload.bRows track by r.id'><td>{{r.ts_dataset}}</td><td>{{r.asset}}</td><td>{{r.status}}</td></tr></tbody></table></div>
  </div>
  <div class='panel wide' id='database-status'>""")
markup = markup.replace("Fixed Company A replay →", "Fixed Company A + B replays →")
template["format"] = markup
nodes["ui_tab_present"]["name"] = "Production Monitor · A + B"
FILE.write_text(json.dumps(list(nodes.values()), indent=2, ensure_ascii=False), encoding="utf-8")
print("Installed separate Company B MQTT, SQLite and dashboard path")
