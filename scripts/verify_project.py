"""Check the fixed dataset, saved model and dashboard before a demo."""

import hashlib
import json
import re
from pathlib import Path

import joblib

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_DATA_SHA256 = "888838fe508a42e83c55f39ad4898566ef5e3dcc354edbac84000c8def49629a"
EXPECTED_B_SHA256 = "2614e7bd3d264fcfcd11c2dbdc66be0115bbab21c5aafe2e18d8ac0dbeb5e816"


def main():
    raw = ROOT / "data" / "raw" / "company_A.csv"
    with raw.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    assert digest == EXPECTED_DATA_SHA256, "Company A CSV differs from the fixed source"
    with (ROOT / "data/raw/company_B.zip").open("rb") as stream:
        b_digest = hashlib.file_digest(stream, "sha256").hexdigest()
    assert b_digest == EXPECTED_B_SHA256, "Company B ZIP differs from the fixed source"
    report = json.loads((ROOT / "results" / "model_comparison.json").read_text())
    bundle = joblib.load(ROOT / "results" / "chosen_model.joblib")
    assert bundle["name"] == report["chosen_model"]
    assert len(bundle["feature_columns"]) == report["features"]
    flow = json.loads((ROOT / "nodered" / "flow.json").read_text())
    nodes = {node["id"]: node for node in flow}
    assert "db_poll" in nodes and "ui_overview" in nodes
    assert "model-evaluation" in nodes["ui_overview"]["format"]
    assert "database-status" in nodes["ui_overview"]["format"]
    assert "company-comparison" in nodes["ui_overview"]["format"]
    assert "in_b_raw" in nodes and "db_b_events" in nodes
    assert "in_b_forecast" in nodes and "company-b-models" in nodes["ui_overview"]["format"]
    b_report = json.loads((ROOT / "results/company_b_models.json").read_text())
    b_bundle = joblib.load(ROOT / "results/company_b_model.joblib")
    assert len(b_report["candidates"]) == 3 and b_bundle["name"] == b_report["selected"]
    comparison = json.loads((ROOT / "results/company_comparison.json").read_text())
    assert comparison["summary"]["A"]["months"] == comparison["summary"]["B"]["months"] == 9
    public = json.loads((ROOT / "config/public_broker.json").read_text())
    assert re.fullmatch(r"team12/demo-[a-f0-9]{16,32}", public["topic_root"])
    assert (ROOT / "docs/PUBLIC_BROKER_DEMO.md").exists()
    assert all((ROOT / path).exists() for path in (
        "data/processed/features.csv", "data/processed/replay_slice.csv",
        "results/scenario_comparison.json", "db/schema.sql",
        "data/processed/company_b_replay.csv"))
    print("PASS: fixed Company A SHA-256 matches")
    print("PASS: fixed Company B SHA-256 matches")
    print(f"PASS: {report['examples']:,} prepared examples, {report['features']} features")
    print(f"PASS: saved selected model = {bundle['name']}")
    print("PASS: database and model-evaluation dashboard nodes are present")
    print("PASS: Company B MQTT, SQLite and nine-month comparison are present")


if __name__ == "__main__":
    main()
