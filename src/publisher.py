"""
The virtual IoT node.

Replays a small slice of REAL Company A records and publishes each one to
MQTT, as if the machines were reporting right now.

Every message carries TWO timestamps:
    ts_dataset  when the factory actually recorded it (2022)
    ts_replay   when we published it (today)
Nothing downstream can mistake 2022 data for a live event.

Run:  python src/publisher.py
      python src/publisher.py --speed 120        (faster)
      python src/publisher.py --inject-bad 10    (every 10th record is broken,
                                                  to show validation working)
"""

import argparse
import json
import time
import uuid

import pandas as pd

from common import CONFIG, connect, now_iso, path, publish, topic

REPLAY = CONFIG["replay"]

# Message format version. Bump it if you change the payload shape.
SCHEMA_VERSION = 1


def load_slice():
    """Load the pre-cut demo slice made by src/clean.py."""
    f = path("replay_slice")
    if not f.exists():
        raise SystemExit(f"{f} not found. Run:  python src/clean.py")
    df = pd.read_csv(f, parse_dates=["ts"])
    return df.sort_values("ts").reset_index(drop=True)


def build_payload(row, seq, run_id):
    """Turn one CSV row into the JSON message we publish.

    Keep this function boring - it is the contract between Python and
    Node-RED. If you add a field here, add it to db/schema.sql too.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "observed",          # never "simulated" - this is real data
        "run_id": run_id,              # lets Node-RED drop repeats on restart
        "seq": seq,                    # position in the replay
        "asset": int(row["asset"]),
        "ts_dataset": row["ts"].isoformat(),   # when the factory recorded it
        "ts_replay": now_iso(),                # when we published it
        "items": float(row["items"]),
        "status": int(row["status"]),
        "status_time": float(row["status_time"]),
        "power_avg": float(row["power_avg"]),
        "cycle_time": float(row["cycle_time"]),
        # Quality flags from src/clean.py, carried through so the dashboard
        # can grey out readings we do not trust.
        "power_ok": bool(row["power_ok"]),
        "cycle_ok": bool(row["cycle_ok"]),
    }


def break_payload(payload):
    """Deliberately corrupt a message, to prove validation catches it.

    Used by --inject-bad. Node-RED should route this to the 'rejected'
    table and the metrics should NOT move.
    """
    bad = dict(payload)
    bad["items"] = -5            # impossible: you cannot produce -5 items
    bad["status"] = 99           # not a documented status code
    bad["note"] = "deliberately invalid record (publisher --inject-bad)"
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--speed", type=float, default=REPLAY["speed"],
                    help="dataset seconds per wall-clock second")
    ap.add_argument("--limit", type=int, default=REPLAY["max_records"],
                    help="stop after N records (0 = all)")
    ap.add_argument("--inject-bad", type=int, default=0,
                    help="corrupt every Nth record (0 = never)")
    args = ap.parse_args()

    df = load_slice()
    if args.limit:
        df = df.head(args.limit)

    run_id = uuid.uuid4().hex[:8]
    client = connect("publisher")
    client.loop_start()

    print(f"Replaying {len(df)} records from {df['ts'].min()} to {df['ts'].max()}")
    print(f"  machines: {sorted(df['asset'].unique().tolist())}")
    print(f"  speed:    {args.speed}x  (run_id {run_id})")
    print()

    previous_ts = None
    sent = 0
    bad_sent = 0

    for seq, row in df.iterrows():
        # Wait the same gap the factory had, divided by the speed-up.
        if previous_ts is not None:
            gap = (row["ts"] - previous_ts).total_seconds()
            if gap > 0:
                time.sleep(gap / args.speed)
        previous_ts = row["ts"]

        payload = build_payload(row, int(seq), run_id)

        if args.inject_bad and seq > 0 and seq % args.inject_bad == 0:
            payload = break_payload(payload)
            bad_sent += 1

        client.publish(topic("observed_machine", payload["asset"]),
                       json.dumps(payload), qos=1).wait_for_publish(timeout=10)
        sent += 1

        flag = "  <-- INVALID" if "note" in payload else ""
        print(f"  [{sent:>3}] machine {payload['asset']}  "
              f"{payload['ts_dataset'][11:19]}  "
              f"items={payload['items']:>5.1f}  "
              f"status={payload['status']}{flag}")

    time.sleep(0.5)  # let the last message leave
    client.loop_stop()
    client.disconnect()
    print(f"\nDone. Published {sent} records ({bad_sent} deliberately invalid).")


if __name__ == "__main__":
    main()
