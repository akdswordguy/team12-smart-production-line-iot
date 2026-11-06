"""
OPTIONAL. Writes MQTT messages into SQLite, exactly as the Node-RED flow does.

The Node-RED flow in nodered/flow.json is the REQUIRED path for this
project - the assignment asks for Node-RED between MQTT and the database,
and that is what the demo uses.

This script exists for two practical reasons:
  * you can test the database and the queries without Node-RED running
    (handy on a headless machine, or while writing the report);
  * it keeps the SQL in one readable Python file, so you can see at a
    glance what the flow's function nodes are inserting.

If you run this AND Node-RED at the same time, every row is stored twice.
Run one or the other.

Run:  python src/recorder.py
"""

import json
import sqlite3

from common import connect, path, publish, topic

# The same statements the Node-RED function nodes use. Python's sqlite3
# names parameters with a colon, Node-RED's sqlite node uses a dollar sign;
# the columns and tables are identical.
SQL = {
    "event": """
        INSERT OR IGNORE INTO machine_events
            (source, run_id, seq, asset, ts_dataset, ts_replay, items, status,
             status_time, power_avg, cycle_time, power_ok, cycle_ok)
        VALUES (:source, :run_id, :seq, :asset, :ts_dataset, :ts_replay,
                :items, :status, :status_time, :power_avg, :cycle_time,
                :power_ok, :cycle_ok)""",
    "rejected": """
        INSERT INTO rejected_records (ts_replay, topic, reason, raw_payload)
        VALUES (:ts_replay, :topic, :reason, :raw_payload)""",
    "metrics": """
        INSERT INTO machine_metrics
            (asset, ts_dataset, ts_replay, window_slots, rolling_items,
             items_per_slot, items_per_productive_slot, productive_share,
             alarm_share, cycle_time_indicator, coverage,
             baseline_items_per_slot, baseline_ratio, baseline_hour)
        VALUES (:asset, :ts_dataset, :ts_replay, :window_slots, :rolling_items,
                :items_per_slot, :items_per_productive_slot, :productive_share,
                :alarm_share, :cycle_time_indicator, :coverage,
                :baseline_items_per_slot, :baseline_ratio, :baseline_hour)""",
    "alert": """
        INSERT INTO machine_alerts
            (ts_replay, ts_dataset, asset, level, kind, recommendation, message)
        VALUES (:ts_replay, :ts_dataset, :asset, :level, :kind,
                :recommendation, :message)""",
    "forecast": """
        INSERT INTO forecasts (ts_replay, asset, horizon_minutes, predicted_items, model)
        VALUES (:ts_replay, :asset, :horizon_minutes, :predicted_items, :model)""",
    "forecast_advisory": """
        INSERT INTO forecast_advisories
            (source, ts_replay, ts_dataset, asset, model, predicted_items,
             expected_items, recommendation, reason)
        VALUES ('forecast', :ts_replay, :ts_dataset, :asset, :model,
                :predicted_items, :expected_items, :recommendation, :reason)""",
    "sim_state": """
        INSERT INTO sim_state
            (source, run_label, ts_replay, sim_second, stage_index, stage_name,
             rate_per_min, configured_rate, queue_length, busy_share,
             starved_share, completed, avg_wait_seconds, is_bottleneck)
        VALUES ('simulated', :run_label, :ts_replay, :sim_second, :stage_index,
                :stage_name, :rate_per_min, :configured_rate, :queue_length,
                :busy_share, :starved_share, :completed, :avg_wait_seconds,
                :is_bottleneck)""",
    "command": """
        INSERT INTO sim_commands
            (command_id, direction, ts_replay, sim_second, action, stage_index,
             detail, reason, old_rate, new_rate, accepted)
        VALUES (:command_id, :direction, :ts_replay, :sim_second, :action,
                :stage_index, :detail, :reason, :old_rate, :new_rate,
                :accepted)""",
}

VALID_STATUS = {1, 2, 3}
counts = {}


def bump(key):
    counts[key] = counts.get(key, 0) + 1


def handle_machine(conn, msg, topic_name):
    """Same validation gate as the Node-RED flow: bad records go to
    rejected_records and nowhere else."""
    reason = None
    if not isinstance(msg, dict):
        reason = "payload is not an object"
    elif "asset" not in msg or "ts_dataset" not in msg:
        reason = "missing asset or ts_dataset"
    elif not isinstance(msg.get("items"), (int, float)) or msg["items"] < 0:
        reason = "items missing or negative"
    elif int(msg.get("status", -1)) not in VALID_STATUS:
        reason = "status not in (1,2,3)"

    if reason:
        conn.execute(SQL["rejected"], {
            "ts_replay": msg.get("ts_replay") if isinstance(msg, dict) else None,
            "topic": topic_name, "reason": reason,
            "raw_payload": json.dumps(msg)[:2000],
        })
        bump("rejected")
        return False

    conn.execute(SQL["event"], {
        "source": msg.get("source", "observed"),
        "run_id": msg.get("run_id"), "seq": msg.get("seq"),
        "asset": msg["asset"], "ts_dataset": msg["ts_dataset"],
        "ts_replay": msg["ts_replay"], "items": msg["items"],
        "status": msg["status"], "status_time": msg.get("status_time"),
        "power_avg": msg.get("power_avg"), "cycle_time": msg.get("cycle_time"),
        "power_ok": 1 if msg.get("power_ok", True) else 0,
        "cycle_ok": 1 if msg.get("cycle_ok", True) else 0,
    })
    bump("events")
    return True


def on_message(client, userdata, message):
    conn = userdata
    try:
        msg = json.loads(message.payload.decode())
    except Exception:
        conn.execute(SQL["rejected"], {
            "ts_replay": None, "topic": message.topic,
            "reason": "payload is not valid JSON",
            "raw_payload": str(message.payload[:200])})
        conn.commit()
        bump("rejected")
        return

    t = message.topic
    accepted_machine = False

    if t.startswith(topic("observed_machine")):
        accepted_machine = handle_machine(conn, msg, t)

    elif t.startswith(topic("observed_metrics")):
        conn.execute(SQL["metrics"], {k: msg.get(k) for k in (
            "asset", "ts_dataset", "ts_replay", "window_slots", "rolling_items",
            "items_per_slot", "items_per_productive_slot", "productive_share",
            "alarm_share", "cycle_time_indicator", "coverage",
            "baseline_items_per_slot", "baseline_ratio", "baseline_hour")})
        bump("metrics")

    elif t == topic("observed_alert"):
        conn.execute(SQL["alert"], {k: msg.get(k) for k in (
            "ts_replay", "ts_dataset", "asset", "level", "kind",
            "recommendation", "message")})
        bump("alerts")

    elif t.startswith(topic("forecast")):
        conn.execute(SQL["forecast"], {k: msg.get(k) for k in (
            "ts_replay", "asset", "horizon_minutes", "predicted_items", "model")})
        bump("forecasts")

    elif t == topic("forecast_advisory"):
        conn.execute(SQL["forecast_advisory"], {k: msg.get(k) for k in (
            "ts_replay", "ts_dataset", "asset", "model", "predicted_items",
            "expected_items", "recommendation", "reason")})
        bump("forecast_advisory")

    elif t == topic("sim_state"):
        for st in msg.get("stages", []):
            conn.execute(SQL["sim_state"], {
                "run_label": "live", "ts_replay": msg["ts_replay"],
                "sim_second": msg["sim_second"], "is_bottleneck": 0,
                **{k: st.get(k) for k in (
                    "stage_index", "stage_name", "rate_per_min",
                    "configured_rate", "queue_length", "busy_share",
                    "starved_share", "completed", "avg_wait_seconds")}})
        bump("sim_state")

    elif t in (topic("sim_command"), topic("sim_ack")):
        is_ack = t == topic("sim_ack")
        conn.execute(SQL["command"], {
            "command_id": msg.get("command_id"),
            "direction": "ack" if is_ack else "command",
            "ts_replay": msg.get("ts_replay"),
            "sim_second": msg.get("sim_second"),
            "action": msg.get("action"),
            "stage_index": msg.get("stage_index"),
            "detail": msg.get("stage_name"),
            "reason": msg.get("reason"),
            "old_rate": msg.get("old_rate"),
            "new_rate": msg.get("new_rate"),
            "accepted": (1 if msg.get("accepted") else 0) if is_ack else None,
        })
        bump("ack" if is_ack else "commands")

    conn.commit()
    if accepted_machine:
        publish(client, topic("observed_validated", msg["asset"]), msg)


def main():
    db = path("sqlite")
    if not db.exists():
        raise SystemExit(f"{db} not found. Run:  python scripts/init_db.py")

    conn = sqlite3.connect(db)
    client = connect("recorder")
    client.user_data_set(conn)
    client.on_message = on_message
    client.subscribe("team12/#")

    print(f"Recording everything on team12/# into {db}")
    print("(This mirrors the Node-RED flow. Run one or the other, not both.)")
    print("Ctrl-C to stop.\n")

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\nStored:")
        for k, v in sorted(counts.items()):
            print(f"  {k:<12} {v}")
        conn.close()


if __name__ == "__main__":
    main()
