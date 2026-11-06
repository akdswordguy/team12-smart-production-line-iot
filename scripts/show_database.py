"""Read-only proof that the MQTT demo wrote its data to SQLite."""

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "db" / "team12.db"
TABLES = (
    "machine_events", "rejected_records", "machine_metrics", "machine_alerts",
    "forecasts", "forecast_advisories", "sim_state", "sim_commands",
    "ml_demo_runs", "sim_reviews", "company_b_events", "company_b_metrics",
)


def main():
    if not DB.exists():
        raise SystemExit(f"Database not found: {DB}\nStart scripts/run_demo.py first.")
    print(f"SQLite file: {DB}")
    with sqlite3.connect(DB.as_uri() + "?mode=ro", uri=True) as conn:
        print("\nStored row counts:")
        for table in TABLES:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table:<22} {count:>7,}")
        print("\nLatest observed records (factory timestamp, machine, items, state):")
        for row in conn.execute(
            "SELECT ts_dataset, asset, items, status FROM machine_events "
            "ORDER BY id DESC LIMIT 5"
        ):
            print("  ", *row)
        print("\nLatest Company B records (factory timestamp, machine, state):")
        for row in conn.execute(
            "SELECT ts_dataset, asset, status FROM company_b_events ORDER BY id DESC LIMIT 5"
        ):
            print("  ", *row)
        rejected = conn.execute(
            "SELECT ts_replay, reason FROM rejected_records ORDER BY id DESC LIMIT 3"
        ).fetchall()
        if rejected:
            print("\nRecent rejected input (replay timestamp, reason):")
            for row in rejected:
                print("  ", *row)
        print("\nLatest model forecasts (replay timestamp, machine, predicted items, model):")
        for row in conn.execute(
            "SELECT ts_replay, asset, predicted_items, model FROM forecasts "
            "ORDER BY id DESC LIMIT 3"
        ):
            print("  ", *row)
        print("\nLatest virtual control messages (direction, command, accepted):")
        for row in conn.execute(
            "SELECT direction, command_id, accepted FROM sim_commands "
            "ORDER BY id DESC LIMIT 4"
        ):
            print("  ", *row)
        print("\nLatest interactive model runs (model, active MAE, train seconds):")
        for row in conn.execute(
            "SELECT model, active_mae, train_seconds FROM ml_demo_runs "
            "ORDER BY id DESC LIMIT 3"
        ):
            print("  ", *row)
        print("\nLatest operator decisions (proposal, decision, stage):")
        for row in conn.execute(
            "SELECT proposal_id, decision, stage_name FROM sim_reviews "
            "ORDER BY id DESC LIMIT 3"
        ):
            print("  ", *row)


if __name__ == "__main__":
    main()
