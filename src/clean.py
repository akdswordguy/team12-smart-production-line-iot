"""
Phase 1 (part 2) - Cleaning and derived tables.

Reads  data/raw/company_A.csv   (never writes to it)
Writes data/processed/events_clean.csv   cleaned events for training
       data/processed/replay_slice.csv   the small slice used in the live demo
       data/processed/baseline.json      each machine's own normal output
       results/calibration.json          starting rates for the virtual line

Cleaning is FLAGGING, not deleting. Every raw row survives with extra
columns saying whether we trust each measurement.

Run:  python src/clean.py
"""

import pandas as pd

from common import CONFIG, ROOT, path, require, save_json

CLEAN = CONFIG["cleaning"]
REPLAY = CONFIG["replay"]


def load_raw():
    f = require("raw_company_a",
                "The dataset is not here yet. Get it with:\n"
                "    python scripts/fetch_dataset.py")
    print("Reading raw company_A.csv ...")
    return pd.read_csv(f, parse_dates=["ts"])


def add_quality_flags(df):
    """Add columns that say what we trust. Nothing is dropped here.

    power_ok      False when the power reading is physically impossible
    cycle_ok      False when items were produced but cycle_time is 0
    productive    True when the machine was producing (status 1 or 2)
    in_alarm      True when status == 3
    """
    df = df.copy()

    limit = CLEAN["power_sanity_limit_kw"]
    df["power_ok"] = df["power_avg"] <= limit

    # The audit found 18,687 rows with items > 0 but cycle_time == 0.
    # We keep the item count (it is the thing we forecast) but mark the
    # cycle-time reading as untrustworthy.
    df["cycle_ok"] = ~((df["items"] > 0) & (df["cycle_time"] == 0))

    df["productive"] = df["status"].isin([1, 2])
    df["in_alarm"] = df["status"] == 3

    # status 0 (idle) never appears in this file, so we cannot tell
    # "idle" apart from "not reporting". Recorded in docs/DATA_AUDIT.md.

    n_power = int((~df["power_ok"]).sum())
    n_cycle = int((~df["cycle_ok"]).sum())
    print(f"  flagged {n_power} impossible power readings")
    print(f"  flagged {n_cycle} rows with items>0 but cycle_time==0")
    return df


def to_slots(df):
    """Snap every record onto a fixed 5-minute grid per machine.

    The audit showed the real spacing is 300 s, but with gaps. Putting
    records on a grid lets us measure COVERAGE: how many of the slots we
    expected actually arrived.
    """
    slot = f"{CLEAN['slot_seconds']}s"
    df = df.copy()
    df["slot"] = df["ts"].dt.floor(slot)

    # Compute these columns once. Per-group Python lambdas are prohibitively
    # slow when the source contains hundreds of thousands of five-minute slots.
    df["power_valid_value"] = df["power_avg"].where(df["power_ok"])
    df["power_flagged_value"] = (~df["power_ok"]).astype("int8")
    df["cycle_flagged_value"] = (~df["cycle_ok"]).astype("int8")
    grouped = df.groupby(["asset", "slot"], sort=True).agg(
        items=("items", "sum"),
        records=("ts", "size"),
        productive_share=("productive", "mean"),
        alarm_share=("in_alarm", "mean"),
        cycle_time_mean=("cycle_time", "mean"),
        power_mean=("power_valid_value", "mean"),
        power_flagged=("power_flagged_value", "sum"),
        cycle_flagged=("cycle_flagged_value", "sum"),
    )
    return grouped.reset_index()


def build_baseline(slots, exclude_start, exclude_end):
    """Each machine's own normal output, per hour of day, UNDER COMPARABLE
    CONDITIONS.

    Two rules that matter:

    1. A machine is only compared with ITSELF. Machine 0 and machine 1 make
       different products, so their item counts are not comparable.

    2. We only average over slots where the machine was actually PRODUCING
       (productive_share > 0.8). Without this the baseline is meaningless:
       machines 0 and 1 are usually stopped at 04:00, so their raw median
       output at that hour is 0, and every running machine then looks
       "infinitely above baseline" or divides by zero.
       The baseline answers "how much does this machine make per slot WHEN
       IT IS RUNNING at this hour", which is the question we actually ask.

    The demo window is excluded so the live demo is not compared with itself.
    """
    s = slots.copy()
    in_demo_window = (s["slot"] >= exclude_start) & (s["slot"] < exclude_end)
    s = s[~in_demo_window]

    # Comparable conditions: the machine was producing.
    s = s[s["productive_share"] > 0.8]
    s["hour"] = s["slot"].dt.hour

    baseline = {}
    for (asset, hour), g in s.groupby(["asset", "hour"]):
        baseline.setdefault(str(int(asset)), {})[str(int(hour))] = {
            "median_items_per_slot": round(float(g["items"].median()), 3),
            "mean_items_per_slot": round(float(g["items"].mean()), 3),
            "slots_observed": int(len(g)),
        }

    # Fallback for any hour with too little history (used by analytics.py).
    for asset, g in s.groupby("asset"):
        baseline.setdefault(str(int(asset)), {})["overall"] = {
            "median_items_per_slot": round(float(g["items"].median()), 3),
            "mean_items_per_slot": round(float(g["items"].mean()), 3),
            "slots_observed": int(len(g)),
        }
    return baseline


def calibrate_virtual_line(slots, assets):
    """Derive plausible stage service rates from real output.

    Important distinction for the viva:
      AVERAGE OUTPUT is not CAPACITY. A machine averaging 0.4 items/min is
      not limited to 0.4 - that average includes slots where it was waiting,
      changing product, or barely loaded. We use the 90th percentile of its
      rate during productive slots as a capacity proxy: "what it manages on
      a good run".

    This is the only link between the real data and the virtual line, and it
    is a calibration, not a measurement of a line.
    """
    out = {}
    slot_minutes = CLEAN["slot_seconds"] / 60.0
    for asset in assets:
        g = slots[(slots["asset"] == asset) & (slots["productive_share"] > 0.8)]
        if g.empty:
            continue
        per_min = g["items"] / slot_minutes
        out[str(int(asset))] = {
            "mean_items_per_min": round(float(per_min.mean()), 2),
            "median_items_per_min": round(float(per_min.median()), 2),
            "p90_items_per_min": round(float(per_min.quantile(0.90)), 2),
            "capacity_proxy_used": round(float(per_min.quantile(0.90)), 2),
            "slots_used": int(len(g)),
        }
    return {
        "note": (
            "Starting rates for the VIRTUAL line, calibrated from real output. "
            "capacity_proxy_used (p90 of items/min during productive slots) is "
            "what we copy into config.yaml simulation.stages. The dataset has "
            "no stage order, so assigning these machines to stages 1/2/3 is our "
            "documented assumption, not a measurement."
        ),
        "per_asset": out,
    }


def main():
    raw = load_raw()
    flagged = add_quality_flags(raw)

    # Keep the training period (config: cleaning.train_from onwards).
    train_from = pd.Timestamp(CLEAN["train_from"], tz="UTC")
    recent = flagged[flagged["ts"] >= train_from]
    print(f"  {len(recent):,} rows from {CLEAN['train_from']} onwards")

    slots = to_slots(recent)
    print(f"  {len(slots):,} five-minute slots across {slots['asset'].nunique()} machines")

    out = path("clean_events")
    out.parent.mkdir(parents=True, exist_ok=True)
    slots.to_csv(out, index=False)
    print(f"  wrote {out}")

    # --- the small slice we replay in the live demo --------------------------
    start = pd.Timestamp(REPLAY["start"])
    end = pd.Timestamp(REPLAY["end"])
    demo = flagged[
        (flagged["ts"] >= start)
        & (flagged["ts"] < end)
        & (flagged["asset"].isin(REPLAY["assets"]))
    ].sort_values("ts")
    demo.to_csv(path("replay_slice"), index=False)
    print(f"  wrote {path('replay_slice')}  ({len(demo)} records, "
          f"{demo['asset'].nunique()} machines)")

    # --- each machine's own baseline ----------------------------------------
    baseline = build_baseline(slots, start, end)
    save_json(path("baseline"), baseline)
    print(f"  wrote {path('baseline')}")

    # --- starting rates for the virtual line --------------------------------
    calib = calibrate_virtual_line(slots, REPLAY["assets"])
    save_json(ROOT / "results" / "calibration.json", calib)
    print(f"  wrote results/calibration.json")
    for asset, v in calib["per_asset"].items():
        print(f"    machine {asset}: median {v['median_items_per_min']} items/min "
              f"while producing")


if __name__ == "__main__":
    main()
