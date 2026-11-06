"""
Prove that the features the LIVE service builds equal the features the
model was TRAINED on - using real Company A records, not synthetic ones.

Why this script exists
----------------------
A forecast is only trustworthy if the numbers fed to the model at run time
mean the same thing as the numbers it learned from. Those two paths are
built by different code:

    TRAINING   company_A.csv -> clean.to_slots()      -> ml_features.build_for_asset()
    LIVE       MQTT records  -> analytics.update_history() -> ml_features.features_from_live_rows()

The unit test in tests/test_logic.py checks the second half of each path on
synthetic rows where every slot holds exactly one record. This script checks
BOTH halves on the real file, including slots that hold several records and
slots with flagged power or cycle readings - the cases synthetic data misses.

It compares, for many randomly chosen (machine, origin) pairs:
  stage 1   every aggregated slot field   (analytics vs clean)
  stage 2   every model input feature     (live vector vs training row)

Run:  python scripts/verify_feature_parity.py
      python scripts/verify_feature_parity.py --samples 500
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import analytics  # noqa: E402
import clean  # noqa: E402
import ml_features  # noqa: E402
from common import CONFIG, path  # noqa: E402

SLOT_SECONDS = CONFIG["cleaning"]["slot_seconds"]
LOOKBACK = ml_features.LOOKBACK

# Slot fields that must agree between the two aggregation paths.
SLOT_FIELDS = ["items", "productive_share", "alarm_share",
               "power_mean", "cycle_time_mean"]

TOLERANCE = 1e-9


def raw_records_for(raw, asset, slots):
    """The original CSV rows that fall inside the given slots, with the same
    quality flags the training path applies."""
    want = set(slots)
    rows = raw[(raw["asset"] == asset) & (raw["slot"].isin(want))]
    return rows.sort_values("ts")


def to_mqtt_message(row):
    """Exactly the payload src/publisher.py puts on the wire."""
    return {
        "asset": int(row["asset"]),
        "ts_dataset": row["ts"].isoformat(),
        "items": float(row["items"]),
        "status": int(row["status"]),
        "status_time": float(row["status_time"]),
        "power_avg": float(row["power_avg"]),
        "cycle_time": float(row["cycle_time"]),
        "power_ok": bool(row["power_ok"]),
        "cycle_ok": bool(row["cycle_ok"]),
    }


def compare_slot_rows(live_rows, offline_rows):
    """Stage 1: did the two aggregation paths produce the same slots?"""
    problems = []
    if len(live_rows) != len(offline_rows):
        return [f"slot count {len(live_rows)} live vs {len(offline_rows)} offline"]

    for live, (_, offline) in zip(live_rows, offline_rows.iterrows()):
        for field in SLOT_FIELDS:
            a, b = live.get(field), offline[field]
            if a is None and pd.isna(b):
                continue
            if a is None or pd.isna(b):
                problems.append(f"{field}: live={a!r} offline={b!r}")
                continue
            if abs(float(a) - float(b)) > TOLERANCE:
                problems.append(
                    f"{field}: live={float(a):.10g} offline={float(b):.10g}")
    return problems


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=200,
                        help="how many (machine, origin) pairs to check")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    print("Loading the training feature table ...")
    features = pd.read_csv(path("features"), parse_dates=["slot"])
    columns = ml_features.feature_columns(features)

    print("Loading the cleaned slots ...")
    slots = pd.read_csv(path("clean_events"), parse_dates=["slot"])

    print("Loading the raw file and applying the training quality flags ...")
    raw = clean.add_quality_flags(
        pd.read_csv(path("raw_company_a"), parse_dates=["ts"]))
    raw["slot"] = raw["ts"].dt.floor(f"{SLOT_SECONDS}s")

    sample = features.sample(n=min(args.samples, len(features)),
                             random_state=args.seed)

    stage1_failures, stage2_failures = [], []
    multi_record_slots = 0
    flagged_slots = 0
    checked = 0

    print(f"\nChecking {len(sample)} (machine, origin) pairs ...\n")
    for _, row in sample.iterrows():
        asset = int(row["asset"])
        origin = row["slot"]

        # The lookback window the live service would hold at this origin:
        # the LOOKBACK slots immediately before it.
        step = pd.Timedelta(seconds=SLOT_SECONDS)
        window = [origin - step * k for k in range(LOOKBACK, 0, -1)]

        records = raw_records_for(raw, asset, window)
        if len(records) < LOOKBACK:
            continue   # the raw file has no record for one of those slots

        if len(records) > LOOKBACK:
            multi_record_slots += 1
        if (~records["power_ok"]).any() or (~records["cycle_ok"]).any():
            flagged_slots += 1

        # ---- replay those records through the LIVE path --------------------
        analytics.history.pop(asset, None)
        for _, record in records.iterrows():
            message = to_mqtt_message(record)
            ok, reason = analytics.validate(message)
            if not ok:
                stage1_failures.append(
                    f"machine {asset} origin {origin}: live validation "
                    f"rejected a real record ({reason})")
                break
            analytics.update_history(asset, message)
        live_rows = list(analytics.history.get(asset, []))

        # ---- stage 1: aggregated slots must match --------------------------
        offline_rows = slots[(slots["asset"] == asset)
                             & (slots["slot"].isin(window))].sort_values("slot")
        problems = compare_slot_rows(live_rows, offline_rows)
        if problems:
            stage1_failures.append(
                f"machine {asset} origin {origin}: " + "; ".join(problems[:3]))
            continue

        # ---- stage 2: model input features must match ----------------------
        try:
            live_vector = ml_features.features_from_live_rows(
                asset, live_rows, columns)
        except ValueError as exc:
            stage2_failures.append(
                f"machine {asset} origin {origin}: live builder refused ({exc})")
            continue

        training_vector = [float(row[c]) for c in columns]
        for name, live_value, train_value in zip(columns, live_vector,
                                                 training_vector):
            if abs(live_value - train_value) > TOLERANCE:
                stage2_failures.append(
                    f"machine {asset} origin {origin}: {name} "
                    f"live={live_value:.10g} training={train_value:.10g}")
        checked += 1

    # ---- report ------------------------------------------------------------
    print(f"Pairs fully checked              : {checked}")
    print(f"  of those, slots with >1 record : {multi_record_slots}")
    print(f"  of those, with a flagged reading: {flagged_slots}")
    print(f"Features compared per pair       : {len(columns)}")
    print()
    print(f"Stage 1 (slot aggregation) failures : {len(stage1_failures)}")
    for line in stage1_failures[:5]:
        print(f"    {line}")
    print(f"Stage 2 (model features)  failures : {len(stage2_failures)}")
    for line in stage2_failures[:5]:
        print(f"    {line}")

    if stage1_failures or stage2_failures:
        print("\nFAIL - the live service would feed the model different "
              "numbers from the ones it was trained on.")
        return 1

    print(f"\nPASS - across {checked} real windows and "
          f"{checked * len(columns):,} feature comparisons, the live path "
          f"and the training path agree exactly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
