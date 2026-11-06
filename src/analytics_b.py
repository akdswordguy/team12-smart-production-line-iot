"""Rolling Company B operating-state indicators after Node-RED storage."""
import json
from collections import deque
from datetime import datetime, timedelta
import joblib
import numpy as np

from common import ROOT, connect, now_iso, publish, topic
from ml_train_b import FEATURES, STATES

WINDOW = timedelta(minutes=30)
history = {}


def forecast(record, bundle):
    stamp = datetime.fromisoformat(record["ts_dataset"])
    values = {"power_log": float(np.log1p(max(0, min(2000, record.get("power_avg") or 0)))),
              "hour": stamp.hour, "dayofweek": stamp.weekday()}
    values.update({f"status_{state}": int(record["status"] == state) for state in STATES})
    values.update({f"asset_{asset}": int(record["asset"] == asset) for asset in range(18)})
    predicted = str(bundle["model"].predict(np.asarray([[values[f] for f in FEATURES]]))[0])
    return {"source": "forecast_b", "company": "B", "asset": record["asset"],
            "ts_dataset": record["ts_dataset"], "ts_replay": now_iso(),
            "current_status": record["status"], "predicted_next_status": predicted,
            "model": bundle["name"], "condition": "next report exactly 1 minute later"}


last_run_id = {}


def update(record):
    asset = record["asset"]
    stamp = datetime.fromisoformat(record["ts_dataset"])
    run_id = record.get("run_id")
    if run_id is not None and last_run_id.get(asset) != run_id:
        last_run_id[asset] = run_id
        history.pop(asset, None)          # a new replay run starts afresh
    rows = history.setdefault(asset, deque())
    rows.append((stamp, record["status"]))
    if len(rows) > 1 and stamp < rows[-2][0]:
        rows = history[asset] = deque(sorted(rows, key=lambda pair: pair[0]))
    latest = rows[-1][0]
    while rows and rows[0][0] <= latest - WINDOW:
        rows.popleft()
    statuses = [status for _, status in rows]
    production = statuses.count("Production")
    alarm = statuses.count("Alarm")
    relevant = production + alarm
    return {
        "source": "observed_b", "company": "B", "asset": asset,
        "ts_dataset": latest.isoformat(), "ts_replay": now_iso(),
        "latest_status": rows[-1][1], "reports_30m": len(rows),
        "production_share": round(production / len(rows), 3),
        "alarm_share": round(alarm / len(rows), 3),
        "conditional_alarm_pct": round(100 * alarm / relevant, 2) if relevant else None,
    }


def main():
    bundle = joblib.load(ROOT / "results/company_b_model.joblib")
    client = connect("analytics-b")

    def on_message(_client, _userdata, message):
        try:
            record = json.loads(message.payload.decode())
            metric = update(record)
            if metric:
                publish(client, topic("company_b_metrics", metric["asset"]), metric)
                # Score one snapshot per five dataset minutes per asset; keep
                # all stored records and rolling metrics, without blocking the
                # MQTT callback on a model prediction for every raw report.
                if datetime.fromisoformat(record["ts_dataset"]).minute % 5 == 0:
                    publish(client, topic("company_b_forecast", metric["asset"]), forecast(record, bundle))
        except (KeyError, ValueError, TypeError) as exc:
            print(f"B metric skipped: {exc}", flush=True)

    client.on_message = on_message
    client.subscribe(topic("company_b_validated") + "/#")
    print("Company B analytics watching stored validated records", flush=True)
    client.loop_forever()


if __name__ == "__main__":
    main()
