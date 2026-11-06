"""
Turn cleaned 5-minute slots into supervised learning examples.

The question we ask the model:
    "Given everything known up to NOW, how many items will this machine
     produce in the NEXT 30 minutes?"

Two rules we never break:

1. NO FUTURE INFORMATION. Every feature is built from slots STRICTLY
   BEFORE the prediction moment. The target is built from slots strictly
   after it. If a feature could not be known at prediction time, it is not
   a feature.

2. COMPLETE CONSECUTIVE WINDOWS ONLY. The dataset has gaps. We lay every
   machine on a full 5-minute grid, so a gap becomes a blank, and then we
   keep only windows where every lookback slot AND every horizon slot is
   present. A window that straddles a 3-hour outage is thrown away rather
   than quietly treated as continuous.

Run:  python src/ml_features.py
"""

import pandas as pd

from common import CONFIG, path, require

ML = CONFIG["ml"]
SLOT_MINUTES = CONFIG["cleaning"]["slot_seconds"] // 60

LOOKBACK = ML["lookback_slots"]                       # e.g. 6 slots = 30 min
HORIZON = ML["horizon_minutes"] // SLOT_MINUTES       # e.g. 30 min = 6 slots

# Columns we build lag features from.
LAG_SOURCES = ["items", "productive_share", "alarm_share",
               "power_mean", "cycle_time_mean"]


def build_for_asset(g, asset, all_assets):
    """Build the feature table for ONE machine."""
    g = g.sort_values("slot").set_index("slot")

    # Put the machine on a complete 5-minute grid. Missing slots become NaN,
    # which is how a gap stays visible instead of silently closing up.
    full = pd.date_range(g.index.min(), g.index.max(), freq=f"{SLOT_MINUTES}min")
    g = g.reindex(full)
    g.index.name = "slot"

    out = pd.DataFrame(index=g.index)

    # ---- features: only slots BEFORE the prediction moment ----------------
    # shift(1) = the previous slot, shift(2) = two slots ago, and so on.
    for col in LAG_SOURCES:
        for lag in range(1, LOOKBACK + 1):
            out[f"{col}_lag{lag}"] = g[col].shift(lag)

    # Simple summaries of the same history.
    past_items = pd.concat([g["items"].shift(k) for k in range(1, LOOKBACK + 1)], axis=1)
    out["items_sum_last30"] = past_items.sum(axis=1, min_count=LOOKBACK)
    out["items_mean_last30"] = past_items.mean(axis=1)
    out["items_max_last30"] = past_items.max(axis=1)

    # Time of day. Machines behave differently on night shift.
    out["hour"] = out.index.hour
    out["dayofweek"] = out.index.dayofweek
    out["is_weekend"] = (out.index.dayofweek >= 5).astype(int)

    # Which machine this is (one-hot, so linear models treat the ids as
    # categories rather than as numbers with an order).
    for a in all_assets:
        out[f"asset_{a}"] = 1 if a == asset else 0

    # ---- target: the NEXT 30 minutes --------------------------------------
    future = pd.concat([g["items"].shift(-k) for k in range(0, HORIZON)], axis=1)
    out["target_items_next30"] = future.sum(axis=1, min_count=HORIZON)

    out["asset"] = asset

    # Dropping NaN here is what enforces "complete consecutive windows":
    # any window touching a gap has a NaN somewhere and disappears.
    return out.dropna().reset_index()


def build_feature_table():
    f = require("clean_events",
                "Build the cleaned slots first:\n"
                "    python src/clean.py")
    print("Reading cleaned slots ...")
    df = pd.read_csv(f, parse_dates=["slot"])

    wanted = ML["assets"] or sorted(df["asset"].unique().tolist())
    all_assets = sorted(int(a) for a in df["asset"].unique())

    frames = []
    for asset, g in df.groupby("asset"):
        if int(asset) not in wanted:
            continue
        built = build_for_asset(g, int(asset), all_assets)
        print(f"  machine {int(asset)}: {len(built):,} complete windows")
        frames.append(built)

    table = pd.concat(frames, ignore_index=True)
    # Sort by time: the chronological split in ml_train.py depends on this.
    table = table.sort_values("slot").reset_index(drop=True)
    return table


def feature_columns(table):
    """Everything except the identifiers and the target."""
    return [c for c in table.columns
            if c not in ("slot", "asset", "target_items_next30")]


def features_from_live_rows(asset, rows, columns, all_assets=None):
    """Build the feature vector for the NEXT five-minute slot.

    Offline training at origin T uses slots T-1 through T-LOOKBACK and
    predicts T through T+HORIZON-1. Live data ending at slot L therefore
    uses origin T=L+one slot. Require a consecutive history.
    """
    if len(rows) < LOOKBACK:
        raise ValueError(f"need {LOOKBACK} rows, got {len(rows)}")

    recent = rows[-LOOKBACK:]
    stamps = [pd.Timestamp(r.get("slot", r.get("ts_dataset"))) for r in recent]
    step = pd.Timedelta(minutes=SLOT_MINUTES)
    if any(b - a != step for a, b in zip(stamps, stamps[1:])):
        raise ValueError("live forecast needs consecutive five-minute slots")
    newest_first = list(reversed(recent))

    values = {}
    for lag, row in enumerate(newest_first, start=1):
        values[f"items_lag{lag}"] = float(row["items"])
        values[f"productive_share_lag{lag}"] = float(
            row.get("productive_share", 1.0 if row.get("status") in (1, 2) else 0.0))
        values[f"alarm_share_lag{lag}"] = float(
            row.get("alarm_share", 1.0 if row.get("status") == 3 else 0.0))
        power = row.get("power_mean", row.get("power_avg"))
        cycle = row.get("cycle_time_mean", row.get("cycle_time"))
        if power is None or cycle is None or pd.isna(power) or pd.isna(cycle):
            raise ValueError("live forecast needs valid power and cycle readings")
        values[f"power_mean_lag{lag}"] = float(power)
        values[f"cycle_time_mean_lag{lag}"] = float(cycle)

    items = [float(r["items"]) for r in recent]
    values["items_sum_last30"] = sum(items)
    values["items_mean_last30"] = sum(items) / len(items)
    values["items_max_last30"] = max(items)

    origin = stamps[-1] + step
    values["hour"] = origin.hour
    values["dayofweek"] = origin.dayofweek
    values["is_weekend"] = 1 if origin.dayofweek >= 5 else 0

    for col in columns:
        if col.startswith("asset_"):
            values[col] = 1 if col == f"asset_{asset}" else 0
    return [values.get(c, 0.0) for c in columns]


def main():
    table = build_feature_table()
    out = path("features")
    out.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(out, index=False)

    print(f"\n{len(table):,} examples, {len(feature_columns(table))} features")
    print(f"  period: {table['slot'].min()} -> {table['slot'].max()}")
    print(f"  target: items in the next {ML['horizon_minutes']} minutes")
    print(f"  wrote {out}")


if __name__ == "__main__":
    main()
