"""
Phase 1 - Data audit.

Reads the RAW dataset files (never modifies them) and checks every claim we
make in the report. Writes:
    docs/DATA_AUDIT.md       - human readable audit
    results/audit.json       - the same numbers, machine readable

Run:  python src/audit.py
"""

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
DOCS = ROOT / "docs"
RESULTS = ROOT / "results"

# A power reading above this is physically implausible for these machines.
# Chosen from the observed distribution (99.99th percentile is far below it).
POWER_SANITY_LIMIT = 2000.0


def load_company_a():
    """Load the raw Company A file. We never write back to this file."""
    f = RAW / "company_A.csv"
    if not f.exists():
        raise SystemExit(
            f"\nMissing file: {f}\n\n"
            f"The dataset is not here yet. Get it with:\n"
            f"    python scripts/fetch_dataset.py\n"
        )
    return pd.read_csv(f, parse_dates=["ts"])


def basic_shape(df):
    return {
        "rows": int(len(df)),
        "columns": list(df.columns),
        "assets": sorted(int(a) for a in df["asset"].unique()),
        "first_ts": str(df["ts"].min()),
        "last_ts": str(df["ts"].max()),
    }


def check_status_codes(df):
    """README documents status 0 (idle). Check whether it actually occurs."""
    counts = df["status"].value_counts().sort_index()
    return {
        "observed_status_values": [float(v) for v in counts.index],
        "counts": {str(k): int(v) for k, v in counts.items()},
        "status_0_present": bool((df["status"] == 0).any()),
    }


def check_alarm_duplicates_status(df):
    """If alarm == (status == 3) in every row, the two columns carry the same
    information. Using both as model features would leak the answer."""
    is_status_3 = (df["status"] == 3).astype(int)
    agree = int((is_status_3 == df["alarm"]).sum())
    return {
        "rows": int(len(df)),
        "rows_where_alarm_equals_status3": agree,
        "rows_where_they_differ": int(len(df) - agree),
        "alarm_is_redundant": bool(agree == len(df)),
    }


def check_power(df):
    p = df["power_avg"]
    return {
        "min": float(p.min()),
        "max": float(p.max()),
        "mean": float(p.mean()),
        "median": float(p.median()),
        "p99": float(p.quantile(0.99)),
        "p99_99": float(p.quantile(0.9999)),
        "rows_above_sanity_limit": int((p > POWER_SANITY_LIMIT).sum()),
        "sanity_limit_used": POWER_SANITY_LIMIT,
    }


def check_cycle_time(df):
    c = df["cycle_time"]
    positive_items = df["items"] > 0
    return {
        "min": float(c.min()),
        "max": float(c.max()),
        "appears_capped_at_60": bool(c.max() <= 60),
        "rows_items_positive_and_cycle_zero": int((positive_items & (c == 0)).sum()),
        "rows_items_positive": int(positive_items.sum()),
    }


def check_gaps(df):
    """Per asset, how far apart are consecutive records?

    The paper mentions 1-minute collection. We report what the file shows.
    """
    out = {}
    for asset, g in df.sort_values("ts").groupby("asset"):
        gaps = g["ts"].diff().dt.total_seconds().dropna()
        if gaps.empty:
            continue
        counts = gaps.value_counts().head(5)
        out[str(int(asset))] = {
            "records": int(len(g)),
            "modal_gap_seconds": float(counts.index[0]),
            "top_gaps_seconds": {str(k): int(v) for k, v in counts.items()},
            "median_gap_seconds": float(gaps.median()),
            "max_gap_hours": round(float(gaps.max()) / 3600, 2),
        }
    return out


def check_duplicates(df):
    dup = df.duplicated(subset=["ts", "asset"]).sum()
    return {"duplicate_ts_asset_rows": int(dup)}


def find_replay_windows(df, assets, hours=4, min_coverage=0.9):
    """Find continuous time windows where ALL chosen assets report densely.

    We want a short, honest slice for the live demo: a period where the three
    machines really were reporting, so the dashboard is not full of gaps.

    Coverage = (distinct five-minute slots present) / (expected slots).
    Returns the candidate windows sorted by how interesting they are
    (most alarm activity first, so the demo has something to show).
    """
    sub = df[df["asset"].isin(assets)].copy()
    sub = sub[sub["ts"] >= "2022-01-01"]  # recent, denser part of the file
    sub = sub.set_index("ts").sort_index()

    expected_per_asset = hours * 12  # 12 five-minute slots per hour
    window = f"{hours}h"
    candidates = []

    # Step through the data in non-overlapping windows.
    for start, chunk in sub.resample(window):
        if chunk.empty:
            continue
        ok = True
        per_asset = {}
        for a in assets:
            machine_times = chunk.index[chunk["asset"] == a]
            n = int(machine_times.floor("5min").nunique())
            cov = n / expected_per_asset
            per_asset[str(a)] = round(cov, 3)
            if cov < min_coverage:
                ok = False
        if not ok:
            continue
        candidates.append(
            {
                "start": str(start),
                "end": str(start + pd.Timedelta(window)),
                "coverage_per_asset": per_asset,
                "total_items": float(chunk["items"].sum()),
                "alarm_rows": int((chunk["status"] == 3).sum()),
                "distinct_status": sorted(float(v) for v in chunk["status"].unique()),
            }
        )

    # Prefer windows that contain some alarm activity and real output.
    candidates.sort(key=lambda c: (c["alarm_rows"] > 0, c["total_items"]), reverse=True)
    return candidates


def pick_three_assets(df):
    """Pick 3 assets that report densely in 2022 and actually produce items."""
    recent = df[df["ts"] >= "2022-01-01"]
    stats = recent.groupby("asset").agg(
        records=("ts", "size"),
        items=("items", "sum"),
    )
    stats = stats[stats["items"] > 0]
    top = stats.sort_values("records", ascending=False).head(3)
    return sorted(int(a) for a in top.index)


def main():
    DOCS.mkdir(exist_ok=True)
    RESULTS.mkdir(exist_ok=True)

    print("Loading raw company_A.csv ...")
    df = load_company_a()

    audit = {
        "file": "data/raw/company_A.csv",
        "shape": basic_shape(df),
        "status_codes": check_status_codes(df),
        "alarm_vs_status": check_alarm_duplicates_status(df),
        "power": check_power(df),
        "cycle_time": check_cycle_time(df),
        "duplicates": check_duplicates(df),
        "gaps_per_asset": check_gaps(df),
    }

    assets = pick_three_assets(df)
    audit["chosen_assets"] = assets
    windows = find_replay_windows(df, assets, hours=4, min_coverage=0.9)
    audit["replay_window_candidates"] = windows[:10]
    audit["replay_windows_found"] = len(windows)

    (RESULTS / "audit.json").write_text(json.dumps(audit, indent=2))
    write_markdown(audit)
    print(f"Wrote {RESULTS/'audit.json'} and {DOCS/'DATA_AUDIT.md'}")
    print(f"Chosen assets: {assets}")
    if windows:
        print(f"Best replay window: {windows[0]['start']} -> {windows[0]['end']}")
    else:
        print("No window met the coverage bar - loosen min_coverage.")


def write_markdown(a):
    s = a["shape"]
    lines = [
        "# Data audit - Company A",
        "",
        "Generated by `python src/audit.py`. Every number here was measured from",
        "`data/raw/company_A.csv`, not copied from the paper or the README.",
        "",
        "## File as we received it",
        "",
        f"- Rows: **{s['rows']:,}**",
        f"- Columns: `{', '.join(s['columns'])}`",
        f"- Machines (`asset`): {s['assets']}",
        f"- Time span: {s['first_ts']} -> {s['last_ts']}",
        "",
        "### Difference from the repository README",
        "",
        "The README lists only `ts, asset, items, status, power_avg, cycle_time`.",
        "The actual file also contains **`status_time`** and **`alarm`**.",
        "We use the file, and record the discrepancy here.",
        "",
        "## Finding 1 - status code 0 never occurs",
        "",
        f"Observed status values: {a['status_codes']['observed_status_values']}",
        "",
        "| status | meaning (README) | rows |",
        "|---|---|---|",
    ]
    meaning = {"0.0": "idle", "1.0": "manual production", "2.0": "automatic production", "3.0": "alarm / interrupted"}
    for k, v in a["status_codes"]["counts"].items():
        lines.append(f"| {k} | {meaning.get(k, '?')} | {v:,} |")
    lines += [
        "",
        "The documented *idle* state (0) is **absent**. So we cannot distinguish",
        "\"machine idle\" from \"machine not reporting\". This is the main reason",
        "starvation cannot be measured on the real data and must come from the",
        "virtual line.",
        "",
        "## Finding 2 - `alarm` duplicates `status == 3`",
        "",
        f"- Rows where `alarm == (status == 3)`: **{a['alarm_vs_status']['rows_where_alarm_equals_status3']:,}**",
        f"- Rows where they differ: **{a['alarm_vs_status']['rows_where_they_differ']:,}**",
        "",
        "They carry the same information. Using both to predict anything",
        "alarm-related would be **target leakage**, so our feature builder uses",
        "only `status`-derived shares.",
        "",
        "## Finding 3 - power outliers",
        "",
        f"- max: **{a['power']['max']:,.0f} kW**",
        f"- 99th percentile: {a['power']['p99']:.1f} kW",
        f"- 99.99th percentile: {a['power']['p99_99']:.1f} kW",
        f"- rows above our sanity limit of {a['power']['sanity_limit_used']:.0f} kW: **{a['power']['rows_above_sanity_limit']:,}**",
        "",
        "The maximum is 2^24, a classic sensor/encoding artefact. We **flag**",
        "these rows rather than delete them; the raw file stays untouched.",
        "",
        "## Finding 4 - cycle_time",
        "",
        f"- range: {a['cycle_time']['min']:.0f} .. {a['cycle_time']['max']:.0f} seconds",
        f"- capped at 60s: **{a['cycle_time']['appears_capped_at_60']}**",
        f"- rows with `items > 0` but `cycle_time == 0`: **{a['cycle_time']['rows_items_positive_and_cycle_zero']:,}**",
        "",
        "The repository describes this as total seconds to produce items, but",
        "the observed 60 s cap and zero values alongside positive item counts",
        "make per-item or end-to-end timing unsafe to infer. We label it on",
        "the dashboard as **\"reported cycle-time indicator\"**.",
        "",
        "## Finding 5 - reporting interval",
        "",
        "The paper describes 1-minute collection. Measured per machine:",
        "",
        "| asset | records | modal gap (s) | median gap (s) | largest gap (h) |",
        "|---|---|---|---|---|",
    ]
    for asset, g in sorted(a["gaps_per_asset"].items(), key=lambda kv: int(kv[0])):
        lines.append(
            f"| {asset} | {g['records']:,} | {g['modal_gap_seconds']:.0f} | "
            f"{g['median_gap_seconds']:.0f} | {g['max_gap_hours']:.1f} |"
        )
    lines += [
        "",
        "We therefore treat **5 minutes** as the nominal slot and always publish a",
        "coverage figure so the dashboard never implies data we do not have.",
        "",
        "## Finding 6 - no routing, no queues",
        "",
        "There is no column for work-in-progress, item transfer, queue length,",
        "waiting time, demand, or finished-line output. Each `asset` is an",
        "independent machine. **A real line bottleneck cannot be verified from",
        "this file.** Queues and waiting time in this project come only from the",
        "clearly-labelled virtual line.",
        "",
        "## Replay slice chosen for the live demo",
        "",
        f"- Assets: **{a['chosen_assets']}** (densest 2022 reporters that produce items)",
        f"- Windows meeting >=90% coverage for all three: **{a['replay_windows_found']}**",
        "",
    ]
    if a["replay_window_candidates"]:
        w = a["replay_window_candidates"][0]
        lines += [
            "Best candidate:",
            "",
            f"- start: `{w['start']}`",
            f"- end:   `{w['end']}`",
            f"- coverage per asset: {w['coverage_per_asset']}",
            f"- items produced in window: {w['total_items']:.0f}",
            f"- rows in alarm state: {w['alarm_rows']}",
            "",
        ]
    lines += [
        "## What we may and may not claim",
        "",
        "| Claim | Supported by |",
        "|---|---|",
        "| Machine output, state share, alarm share | Observed data |",
        "| Machine under-performing vs its own baseline | Observed data |",
        "| Queue length, waiting time, starvation | **Virtual line only** |",
        "| Line bottleneck, before/after of an action | **Virtual line only** |",
        "",
    ]
    DOCS.joinpath("DATA_AUDIT.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()

