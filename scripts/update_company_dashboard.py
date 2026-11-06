"""Render the audited A/B monthly comparison inside the Node-RED dashboard."""
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FLOW = ROOT / "nodered/flow.json"
REPORT = ROOT / "results/company_comparison.json"
BEGIN = "<!-- company-comparison:start -->"
END = "<!-- company-comparison:end -->"
B_BEGIN = "<!-- company-b-models:start -->"
B_END = "<!-- company-b-models:end -->"


def render(report):
    months = sorted({row["month"] for row in report["monthly"]})
    by_key = {(row["month"], row["company"]): row for row in report["monthly"]}
    lines = []
    for tick in (0, 5, 10, 15, 20, 25):
        y = 205 - tick / 25 * 170
        lines.append(f'<line x1="42" y1="{y:.1f}" x2="735" y2="{y:.1f}" stroke="#dce8ee"/>')
        lines.append(f'<text x="8" y="{y + 4:.1f}" fill="#607586" font-size="12">{tick}%</text>')
    for i, month in enumerate(months):
        lines.append(f'<text x="{45 + i * 84}" y="230" fill="#607586" font-size="12">{month[5:]}</text>')
    for company, color in (("A", "#087ba5"), ("B", "#d97706")):
        points = " ".join(f"{55 + i * 84},{205 - by_key[(month, company)]['alarm_conditional_pct'] / 25 * 170:.1f}"
                          for i, month in enumerate(months))
        lines.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="3"/>')
        for i, month in enumerate(months):
            y = 205 - by_key[(month, company)]["alarm_conditional_pct"] / 25 * 170
            lines.append(f'<circle cx="{55 + i * 84}" cy="{y:.1f}" r="4" fill="{color}"/>')
    rows = []
    a_lower = 0
    for month in months:
        a, b = by_key[(month, "A")], by_key[(month, "B")]
        a_lower += a["alarm_conditional_pct"] < b["alarm_conditional_pct"]
        rows.append(f'<tr><td>{html.escape(month)}</td><td>{a["alarm_conditional_pct"]:.2f}%</td>'
                    f'<td>{b["alarm_conditional_pct"]:.2f}%</td><td>{a["mean_report_density_pct"]:.1f}%</td>'
                    f'<td>{b["mean_report_density_pct"]:.1f}%</td></tr>')
    a, b = report["summary"]["A"], report["summary"]["B"]
    return f"""
  <div class='panel wide' id='company-comparison'>
    <div class='sectionlabel'>Company A vs B · fixed dataset · Jan–Sep 2022</div>
    <h3>Recorded interruption comparison</h3>
    <p>Among reports labelled Production or Alarm, the machine-equal monthly alarm share averaged <b>{a['mean_monthly_alarm_conditional_pct']:.2f}% for A</b> and <b>{b['mean_monthly_alarm_conditional_pct']:.2f}% for B</b>. A was lower in {a_lower} of 9 shared months. Lower is better for this specific interruption measure.</p>
    <svg style='width:100%;height:auto;max-height:300px;background:#f8fafc;border:1px solid #e4eaf0;border-radius:6px' viewBox='0 0 760 250' role='img' aria-label='Monthly alarm share among production or alarm records, Company A and B'>{''.join(lines)}</svg>
    <div class='legend'><span><i class='key' style='background:#087ba5'></i>Company A</span><span><i class='key' style='background:#d97706'></i>Company B</span></div>
    <div class='tablewrap'><table><thead><tr><th>Month</th><th>A alarm share</th><th>B alarm share</th><th>A report density</th><th>B report density</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
    <div class='callout'><b>Interpretation:</b> This does not rank total factory output or efficiency. A has item counts but B does not; B also has Standby, Loading, Tooling and MachineOn states absent from A's 2022 state set. We compare only Production versus Alarm reports, average machines equally, and show report density because B reports much less frequently ({b['mean_monthly_report_density_pct']:.2f}% versus A {a['mean_monthly_report_density_pct']:.2f}% of continuous grid slots). Missing reports are not assumed to be downtime.</div>
  </div>
"""


def render_b_models(report):
    names = {"logistic_regression": "Logistic regression · traditional",
             "gradient_boosting": "Gradient boosting · ensemble",
             "neural_network": "Neural network · deep learning"}
    rows = []
    for key, item in report["candidates"].items():
        score = item["validation"]["macro_f1"]
        rows.append(f'<tr><td>{names[key]}</td><td>{score:.3f}</td>'
                    f'<td><div class="bartrack"><div class="barfill" style="width:{score*100:.1f}%"></div></div></td>'
                    f'<td>{item["training_seconds"]:.2f}s</td></tr>')
    base = report["baseline_persistence_test"]["macro_f1"]
    test = report["selected_test"]["macro_f1"]
    return f"""
  <div class='panel wide' id='company-b-models'>
    <div class='sectionlabel'>Company B · three trained models</div>
    <h3>Next reported machine state</h3>
    <p>Input: current state, power, machine and time. Target: the state in the next record when it arrives exactly one dataset minute later. Models trained on earlier fixed B records; validation and test are later time periods.</p>
    <div class='tablewrap'><table><thead><tr><th>Algorithm</th><th>Validation macro F1</th><th>Score</th><th>Fit time</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
    <p>Selected by validation: <b>{names[report['selected']]}</b>. Held-out test macro F1: <b>{test:.3f}</b>; simple same-state baseline: <b>{base:.3f}</b>. Higher is better.</p>
    <div class='callout'><b>Read this honestly:</b> The selected ML model scores {test-base:+.3f} against the simple baseline on the later test period. This does not prove an operational improvement. Company A predicts item counts (MAE); Company B classifies operating states (macro F1), so their model scores are not directly comparable.</div>
  </div>
"""


def main():
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    flow = json.loads(FLOW.read_text(encoding="utf-8"))
    template = next(node for node in flow if node["id"] == "ui_overview")
    markup = template["format"]
    panel = render(report)
    if BEGIN in markup:
        start = markup.index(BEGIN)
        end = markup.index(END, start) + len(END)
        markup = markup[:start] + BEGIN + panel + END + markup[end:]
    else:
        marker = "  <div class='panel wide' id='company-b-live'>"
        if marker not in markup:
            raise RuntimeError("Install the Company B flow before rendering comparison")
        markup = markup.replace(marker, BEGIN + panel + END + marker, 1)
    template["format"] = markup
    b_report = json.loads((ROOT / "results/company_b_models.json").read_text(encoding="utf-8"))
    markup = template["format"]
    b_panel = render_b_models(b_report)
    if B_BEGIN in markup:
        start = markup.index(B_BEGIN)
        end = markup.index(B_END, start) + len(B_END)
        markup = markup[:start] + B_BEGIN + b_panel + B_END + markup[end:]
    else:
        marker = "  <div class='panel wide' id='company-b-live'>"
        markup = markup.replace(marker, B_BEGIN + b_panel + B_END + marker, 1)
    template["format"] = markup
    FLOW.write_text(json.dumps(flow, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Rendered fixed Company A/B comparison on dashboard")


if __name__ == "__main__":
    main()
