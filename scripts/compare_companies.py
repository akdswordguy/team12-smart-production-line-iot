"""Comparable Company A/B state chart from the fixed repository files.

This is a conditional interruption comparison, not a throughput ranking.
A has five-minute slots and B has one-minute reports with extra state types.
"""
import json
import sys
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
START, END = "2022-01", "2022-09"  # nine complete shared calendar months


def summarize_a():
    frame = pd.read_csv(ROOT / "data/processed/events_clean.csv",
                        usecols=["asset", "slot", "productive_share", "alarm_share"])
    frame["month"] = frame["slot"].str[:7]
    frame = frame[frame["month"].between(START, END)].copy()
    grouped = frame.groupby(["month", "asset"], as_index=False).agg(
        reports=("slot", "size"), production=("productive_share", "sum"),
        alarm=("alarm_share", "sum"))
    grouped["alarm_conditional"] = grouped["alarm"] / (
        grouped["production"] + grouped["alarm"])
    grouped["density"] = grouped["reports"] / (
        pd.to_datetime(grouped["month"] + "-01").dt.days_in_month * 288)
    return grouped, {"production": int(round(grouped.production.sum())),
                     "alarm": int(round(grouped.alarm.sum()))}


def summarize_b():
    archive = ROOT / "data/raw/company_B.zip"
    with zipfile.ZipFile(archive) as zipped, zipped.open("company_B.csv") as stream:
        frame = pd.read_csv(stream, usecols=["ts", "asset", "status"])
    frame["month"] = frame["ts"].str[:7]
    frame = frame[frame["month"].between(START, END)].copy()
    counts = frame["status"].value_counts().to_dict()
    frame["production"] = (frame["status"] == "Production").astype(int)
    frame["alarm"] = (frame["status"] == "Alarm").astype(int)
    grouped = frame.groupby(["month", "asset"], as_index=False).agg(
        reports=("ts", "size"), production=("production", "sum"),
        alarm=("alarm", "sum"))
    denominator = grouped["production"] + grouped["alarm"]
    grouped["alarm_conditional"] = (grouped["alarm"] / denominator).where(
        denominator > 0)
    grouped["density"] = grouped["reports"] / (
        pd.to_datetime(grouped["month"] + "-01").dt.days_in_month * 1440)
    return grouped, {k: int(v) for k, v in counts.items()}


def monthly(grouped, company):
    records = []
    for month, frame in grouped.groupby("month", sort=True):
        comparable = frame.dropna(subset=["alarm_conditional"])
        records.append({
            "company": company, "month": month,
            "machines_reporting": int(frame.asset.nunique()),
            "reports": int(frame.reports.sum()),
            "alarm_conditional_pct": round(float(comparable.alarm_conditional.mean() * 100), 2),
            "mean_report_density_pct": round(float(frame.density.mean() * 100), 2),
        })
    return records


def build_report():
    a, ac = summarize_a()
    b, bc = summarize_b()
    rows = monthly(a, "A") + monthly(b, "B")
    summary = {}
    for company in ("A", "B"):
        subset = [r for r in rows if r["company"] == company]
        summary[company] = {
            "months": len(subset),
            "mean_monthly_alarm_conditional_pct": round(
                sum(r["alarm_conditional_pct"] for r in subset) / len(subset), 2),
            "mean_monthly_report_density_pct": round(
                sum(r["mean_report_density_pct"] for r in subset) / len(subset), 2),
            "total_reports": sum(r["reports"] for r in subset),
        }
    lower = min(summary, key=lambda k: summary[k]["mean_monthly_alarm_conditional_pct"])
    return {
        "source": "fixed SME Manufacturing Dataset, Company A and B",
        "period": ["2022-01-01", "2022-09-30"],
        "metric": "machine-equal mean alarm share among Production-or-Alarm reports",
        "interpretation": "Lower is better only for this conditional interruption proxy; overall company throughput or efficiency cannot be ranked.",
        "report_density_note": "Reports per expected 5-minute (A) or 1-minute (B) grid slot; B may report selectively, so this is context rather than a quality penalty.",
        "lower_conditional_alarm_company": lower,
        "summary": summary,
        "monthly": sorted(rows, key=lambda r: (r["month"], r["company"])),
        "state_counts": {"A": ac, "B": bc},
    }


if __name__ == "__main__":
    report = build_report()
    out = ROOT / "results" / "company_comparison.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print("Lower conditional interruption share:", report["lower_conditional_alarm_company"])
    print("Wrote", out)
