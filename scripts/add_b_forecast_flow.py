"""Add Company B inference storage and dashboard feed to the flow."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
file = root / "nodered/flow.json"
flow = json.loads(file.read_text(encoding="utf-8"))
nodes = {node["id"]: node for node in flow}
if "in_b_forecast" not in nodes:
    nodes["in_b_forecast"] = {"id": "in_b_forecast", "type": "mqtt in", "z": "team12_tab",
        "name": "Company B next-state forecast", "topic": "team12/observed_b/forecast/#",
        "qos": "0", "datatype": "json", "broker": "mqtt_broker", "x": 155, "y": 1670,
        "wires": [["fn_b_forecast_sql", "fn_overview"]]}
    nodes["fn_b_forecast_sql"] = {"id": "fn_b_forecast_sql", "type": "function", "z": "team12_tab",
        "name": "save B forecast", "x": 430, "y": 1670, "outputs": 1,
        "func": """const p=msg.payload;
return {topic:'INSERT INTO company_b_forecasts (asset,ts_dataset,ts_replay,current_status,predicted_next_status,model,condition) VALUES ($a,$tsd,$tsr,$current,$next,$model,$condition)',params:{$a:p.asset,$tsd:p.ts_dataset,$tsr:p.ts_replay,$current:p.current_status,$next:p.predicted_next_status,$model:p.model,$condition:p.condition}};""",
        "wires": [["sql_bind"]]}
    fn = nodes["fn_overview"]["func"]
    fn = fn.replace("if(t==='team12/db/b-recent'", "if(t.startsWith('team12/observed_b/forecast/')) s.bForecast=p;\nif(t==='team12/db/b-recent'")
    fn = fn.replace("bStatusBars:bStatusBars};", "bStatusBars:bStatusBars,bForecast:s.bForecast};")
    nodes["fn_overview"]["func"] = fn
    markup = nodes["ui_overview"]["format"]
    marker = "    <p>Company B records saved:"
    insertion = """    <div class='callout' ng-if='msg.payload.bForecast'><b>Next reported state · machine {{msg.payload.bForecast.asset}}:</b> {{msg.payload.bForecast.predicted_next_status}} (currently {{msg.payload.bForecast.current_status}}; {{msg.payload.bForecast.model}}). Prediction assumes another report exactly one dataset minute later. It is not a measured outcome.</div>
"""
    if marker not in markup:
        raise RuntimeError("Company B dashboard marker missing")
    nodes["ui_overview"]["format"] = markup.replace(marker, insertion + marker, 1)
    file.write_text(json.dumps(list(nodes.values()), indent=2, ensure_ascii=False), encoding="utf-8")
print("Company B forecast flow installed")
