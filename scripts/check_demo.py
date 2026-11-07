"""Inspect the SQLite and logs left by the live MQTT/Node-RED demo."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "db" / "team12.db"
TABLES = ("machine_events", "rejected_records", "machine_metrics",
          "machine_alerts", "forecasts", "forecast_advisories",
          "sim_state", "sim_commands", "ml_demo_runs", "sim_reviews",
          "company_b_events", "company_b_metrics", "company_b_forecasts")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-command", action="store_true",
                        help="require a virtual actuator command and acknowledgement")
    parser.add_argument("--require-review", action="store_true",
                        help="require an accepted proposal before a virtual command")
    parser.add_argument("--require-rejected", action="store_true",
                        help="require a deliberately invalid record")
    args = parser.parse_args()
    if not DB.exists():
        raise SystemExit("No database yet; run scripts/run_demo.py first")
    with sqlite3.connect(DB) as conn:
        counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in TABLES}
        has_loop = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                                "AND name='loop_metrics'").fetchone() is not None
        if has_loop:
            counts["loop_metrics"] = conn.execute("SELECT COUNT(*) FROM loop_metrics").fetchone()[0]
        print("Rows recorded through MQTT and Node-RED:")
        for table, count in counts.items():
            print(f"  {table:<21} {count}")
        selected = json.loads((ROOT / "results" / "model_comparison.json").read_text())["chosen_model"]
        checks = {
            "valid observed records stored": counts["machine_events"] > 0,
            "Company B observed records stored": counts["company_b_events"] > 0,
            "Company B rolling metrics stored": counts["company_b_metrics"] > 0,
            "Company B next-state predictions stored": counts["company_b_forecasts"] > 0,
            "rolling metrics stored": counts["machine_metrics"] > 0,
            "forecast stored with one of the three studied families": (
                counts["forecasts"] > 0 and
                conn.execute("SELECT COUNT(*) FROM forecasts WHERE model IS NULL OR model NOT IN (?,?,?,?)",
                             (selected, "demo_ridge", "demo_gradient_boosting",
                              "demo_neural_network")).fetchone()[0] == 0),
            "ML-based advisory stored": counts["forecast_advisories"] > 0,
            "virtual-line state stored": counts["sim_state"] > 0,
            "observed and virtual sources separate": (
                conn.execute("SELECT COUNT(*) FROM machine_events WHERE source <> 'observed'").fetchone()[0] == 0
                and conn.execute("SELECT COUNT(*) FROM sim_state WHERE source <> 'simulated'").fetchone()[0] == 0),
        }
        if args.require_rejected:
            checks["bad record rejected and stored"] = counts["rejected_records"] > 0
        if args.require_command:
            sent = {row[0] for row in conn.execute(
                "SELECT command_id FROM sim_commands WHERE direction='command'")}
            acked = {row[0] for row in conn.execute(
                "SELECT command_id FROM sim_commands WHERE direction='ack' AND accepted=1")}
            checks["virtual command acknowledged"] = bool(sent & acked)
            if has_loop:
                checks["command round-trip latency measured"] = conn.execute(
                    "SELECT COUNT(*) FROM loop_metrics WHERE metric='command_round_trip_ms'"
                ).fetchone()[0] > 0
        if args.require_review:
            reviewed = {row[0] for row in conn.execute(
                "SELECT proposal_id FROM sim_reviews WHERE decision='accept'")}
            sent = {row[0] for row in conn.execute(
                "SELECT command_id FROM sim_commands WHERE direction='command'")}
            checks["operator accepted command before MQTT actuation"] = bool(reviewed & sent)
        if has_loop:
            print("\nClosed-loop performance (processing-laptop clock):")
            labels = {"command_round_trip_ms": "command round trip (Accept -> ACK)",
                      "ingest_to_forecast_ms": "record received -> forecast",
                      "forecast_compute_ms": "model compute per forecast"}
            for metric, label in labels.items():
                values = sorted(v for (v,) in conn.execute(
                    "SELECT value FROM loop_metrics WHERE metric=?", (metric,)))
                if values:
                    p95 = values[round(0.95 * (len(values) - 1))]
                    print(f"  {label:<38} avg {sum(values) / len(values):8.1f} ms   "
                          f"p95 {p95:8.1f} ms   n={len(values)}")
                else:
                    print(f"  {label:<38} not measured in this run")
        fcols = {row[1] for row in conn.execute("PRAGMA table_info(forecasts)")}
        if "ts_dataset" in fcols:
            sys.path.insert(0, str(ROOT / "scripts"))
            from add_live_model_view import LIVE_SQL, SLOTS
            scored = {}
            for _, _, model, _, predicted, actual, slots in conn.execute(LIVE_SQL):
                if slots == SLOTS and actual is not None:
                    scored.setdefault(model, []).append(abs(predicted - actual))
            print("\nLive forecast check (forecast vs the real next 30 minutes):")
            for model, errors in sorted(scored.items()):
                print(f"  {model:<24} average error {sum(errors) / len(errors):5.2f} items   n={len(errors)}")
            if not scored:
                print("  no forecast has its full 30 minutes of data yet")
            checks["forecasts scored against real data"] = bool(scored)
    nr_log = ROOT / "logs" / "nodered.log"
    if nr_log.exists():
        checks["Node-RED SQLite had no errors"] = "[error] [sqlite:" not in nr_log.read_text(
            encoding="utf-8", errors="replace")
    print("\nChecks:")
    for name, ok in checks.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

