"""
Create (or reset) the SQLite database from db/schema.sql.

Run:  python scripts/init_db.py
      python scripts/init_db.py --reset     (delete everything and start over)

Use --reset only when you intentionally want a fresh demo database.
"""

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from common import ROOT, path  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true",
                    help="delete the existing database first")
    args = ap.parse_args()

    db_file = path("sqlite")
    db_file.parent.mkdir(parents=True, exist_ok=True)

    if args.reset and db_file.exists():
        db_file.unlink()
        print(f"Deleted {db_file}")

    schema = (ROOT / "db" / "schema.sql").read_text()
    conn = sqlite3.connect(db_file)
    conn.executescript(schema)
    # Existing demo databases keep their history and gain these audit fields.
    forecast_columns = {row[1] for row in conn.execute("PRAGMA table_info(forecasts)")}
    if "prediction_guarded" not in forecast_columns:
        conn.execute("ALTER TABLE forecasts ADD COLUMN prediction_guarded INTEGER NOT NULL DEFAULT 0")
    if "guard_limit" not in forecast_columns:
        conn.execute("ALTER TABLE forecasts ADD COLUMN guard_limit REAL")
    demo_columns = {row[1] for row in conn.execute("PRAGMA table_info(ml_demo_runs)")}
    if "seed" not in demo_columns:
        conn.execute("ALTER TABLE ml_demo_runs ADD COLUMN seed INTEGER")
    conn.commit()

    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    conn.close()

    print(f"Database ready: {db_file}")
    for (name,) in tables:
        print(f"  - {name}")


if __name__ == "__main__":
    main()
