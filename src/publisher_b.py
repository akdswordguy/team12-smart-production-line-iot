"""Replay the fixed Company B one-minute records through MQTT."""
import argparse
import json
import time
import uuid

import pandas as pd

from common import CONFIG, ROOT, connect, now_iso, publish, topic

SLICE = ROOT / "data/processed/company_b_replay.csv"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--speed", type=float, default=CONFIG["replay"]["speed"])
    parser.add_argument("--limit", type=int, default=0, help="publish at most N B records; 0 means all")
    args = parser.parse_args()
    if args.speed <= 0:
        parser.error("speed must be positive")
    if args.limit < 0:
        parser.error("limit cannot be negative")
    if not SLICE.exists():
        raise SystemExit("Company B slice missing: run scripts/prepare_company_b.py")
    frame = pd.read_csv(SLICE, parse_dates=["ts"])
    if args.limit:
        frame = frame.head(args.limit)
    run_id = uuid.uuid4().hex[:8]
    client = connect("publisher-b")
    client.loop_start()
    previous = None
    try:
        for seq, row in frame.iterrows():
            stamp = row["ts"]
            if previous is not None:
                gap = (stamp - previous).total_seconds()
                if gap > 0:
                    time.sleep(gap / args.speed)
            previous = stamp
            payload = {
                "source": "observed_b", "company": "B", "run_id": run_id,
                "seq": int(seq), "asset": int(row["asset"]),
                "ts_dataset": stamp.isoformat(), "ts_replay": now_iso(),
                "status": str(row["status"]),
                "power_avg": float(row["power_avg"]),
                "alarm_time": float(row["alarm_time"]),
                "loading_time": float(row["loading_time"]),
                "tooling_time": float(row["tooling_time"]),
                "maintenance_time": float(row["maintenance_time"]),
                "support_time": float(row["support_time"]),
            }
            client.publish(topic("company_b_raw", payload["asset"]),
                           json.dumps(payload), qos=1).wait_for_publish(timeout=10)
            if seq % 200 == 0:
                print(f"Company B sent {seq + 1}/{len(frame)}", flush=True)
    finally:
        time.sleep(0.5)
        client.loop_stop()
        client.disconnect()
    print(f"Company B replay complete: {len(frame)} records", flush=True)


if __name__ == "__main__":
    main()
