"""
Machine monitoring (the "Analytics" box in the architecture diagram).

Listens to the replayed machine records, keeps a short rolling window per
machine, and publishes:
    team12/observed/metrics/<asset>   rolling indicators
    team12/observed/alert             explainable alerts
    team12/forecast/<asset>           ML forecast (only if a model is saved)

Every machine is compared with ITS OWN baseline at the SAME hour of day.
We never compare machine 0 with machine 1 - they make different products,
so their item counts are not comparable.

Run:  python src/analytics.py
"""

import json
import math
import time
from collections import deque
from datetime import datetime, timezone

from common import CONFIG, ROOT, connect, now_iso, path, publish, topic

MON = CONFIG["monitoring"]
WINDOW = MON["rolling_slots"]
SLOT_SECONDS = CONFIG["cleaning"]["slot_seconds"]

# Status codes actually present in the file (the audit found no status 0).
VALID_STATUS = {1, 2, 3}

# Loaded at startup.
BASELINE = {}
MODEL = None

# Per machine: up to WINDOW distinct recent five-minute slots.
history = {}
# Per machine: how many checks in a row have been below the baseline.
low_streak = {}
# Per machine: how many checks in a row have had a high alarm share.
alarm_streak = {}
# Per machine: the last alert we announced, so we only report changes.
last_alert_kind = {}
# Counters for the dashboard.
counters = {"accepted": 0, "rejected": 0}

# Replay run currently feeding each machine. A replay started again from the
# dashboard re-sends the same dataset timestamps under a new run_id; without
# a reset they would all look "late" and be ignored.
last_run_id = {}


def start_new_run_if_needed(asset, run_id):
    """Clear one machine's live state when a new replay run begins."""
    if run_id is None or last_run_id.get(asset) == run_id:
        return False
    is_restart = asset in last_run_id
    last_run_id[asset] = run_id
    if is_restart:
        history.pop(asset, None)
        low_streak.pop(asset, None)
        alarm_streak.pop(asset, None)
        last_alert_kind.pop(asset, None)
    return is_restart


# ---------------------------------------------------------------------------
# Validation - a bad record must never reach the metrics.
# ---------------------------------------------------------------------------
def validate(msg):
    """Return (ok, reason) for one observed Company A event."""
    if not isinstance(msg, dict):
        return False, "not a JSON object"
    for field in ("asset", "ts_dataset", "items", "status"):
        if field not in msg:
            return False, f"missing field '{field}'"
    if not isinstance(msg["asset"], int) or isinstance(msg["asset"], bool):
        return False, "asset must be an integer"
    if not isinstance(msg["items"], (int, float)) or isinstance(msg["items"], bool):
        return False, "items must be a number"
    if not math.isfinite(msg["items"]) or msg["items"] < 0:
        return False, "negative or non-finite items"
    if (not isinstance(msg["status"], int) or isinstance(msg["status"], bool)
            or msg["status"] not in VALID_STATUS):
        return False, f"unknown status code ({msg['status']})"
    try:
        stamp = datetime.fromisoformat(str(msg["ts_dataset"]).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return False, "dataset timestamp needs a timezone"
    except ValueError:
        return False, "invalid dataset timestamp"
    return True, "ok"


def slot_second(msg):
    stamp = datetime.fromisoformat(str(msg["ts_dataset"]).replace("Z", "+00:00"))
    return int(stamp.timestamp()) // SLOT_SECONDS * SLOT_SECONDS


def update_history(asset, msg):
    """Aggregate repeated records in a slot and drop slots outside the window.

    Returns (accepted, is_new_slot). A late out-of-order event is rejected
    from live metrics; Node-RED still retains its raw record for audit.
    """
    key = slot_second(msg)
    rows = history.setdefault(asset, deque(maxlen=WINDOW))
    if rows and key < rows[-1]["slot_second"]:
        return False, False

    is_new = not rows or key != rows[-1]["slot_second"]
    if is_new:
        stamp = datetime.fromtimestamp(key, timezone.utc).isoformat()
        rows.append({
            "slot_second": key, "slot": stamp, "ts_dataset": stamp,
            "items": 0.0, "records": 0, "productive_count": 0,
            "alarm_count": 0, "cycle_sum": 0.0, "cycle_count": 0,
            "cycle_valid_sum": 0.0, "cycle_valid_count": 0,
            "power_sum": 0.0, "power_count": 0,
        })
    row = rows[-1]
    row["records"] += 1
    row["items"] += float(msg["items"])
    row["productive_count"] += int(msg["status"] in (1, 2))
    row["alarm_count"] += int(msg["status"] == 3)
    cycle = msg.get("cycle_time")
    if isinstance(cycle, (int, float)) and math.isfinite(cycle):
        row["cycle_sum"] += float(cycle)
        row["cycle_count"] += 1
        if msg.get("cycle_ok", True):
            row["cycle_valid_sum"] += float(cycle)
            row["cycle_valid_count"] += 1
    power = msg.get("power_avg")
    if msg.get("power_ok", True) and isinstance(power, (int, float)) and math.isfinite(power):
        row["power_sum"] += float(power)
        row["power_count"] += 1
    row["productive_share"] = row["productive_count"] / row["records"]
    row["alarm_share"] = row["alarm_count"] / row["records"]
    row["cycle_time_mean"] = (
        row["cycle_sum"] / row["cycle_count"] if row["cycle_count"] else None)
    row["power_mean"] = (
        row["power_sum"] / row["power_count"] if row["power_count"] else None)

    cutoff = key - (WINDOW - 1) * SLOT_SECONDS
    while rows and rows[0]["slot_second"] < cutoff:
        rows.popleft()
    return True, is_new


# ---------------------------------------------------------------------------
# Rolling indicators
# ---------------------------------------------------------------------------
def baseline_for(asset, hour):
    """This machine's normal items per PRODUCTIVE slot at this hour of day.

    Falls back to the machine's overall baseline when that hour has too
    little history to trust.
    """
    per_asset = BASELINE.get(str(asset), {})
    entry = per_asset.get(str(hour))
    if not entry or entry["slots_observed"] < MON["min_baseline_slots"]:
        entry = per_asset.get("overall")
    if not entry or entry["median_items_per_slot"] <= 0:
        return None
    return entry["median_items_per_slot"]


def compute_metrics(asset):
    """Summarise the last WINDOW expected time slots, including gaps."""
    rows = history[asset]
    n = len(rows)  # distinct observed slots inside the expected time range
    items_total = sum(r["items"] for r in rows)
    items_per_slot = items_total / n if n else 0.0

    productive = sum(r["productive_share"] for r in rows) / n if n else 0.0
    alarm = sum(r["alarm_share"] for r in rows) / n if n else 0.0
    productive_rows = [r for r in rows if r["productive_share"] > 0.8]
    items_per_productive = (
        sum(r["items"] for r in productive_rows) / len(productive_rows)
        if productive_rows else None)

    valid_count = sum(r["cycle_valid_count"] for r in rows)
    cycle_mean = (
        sum(r["cycle_valid_sum"] for r in rows) / valid_count
        if valid_count else None)

    coverage = n / WINDOW
    hour = datetime.fromtimestamp(rows[-1]["slot_second"], timezone.utc).hour
    base = baseline_for(asset, hour)
    ratio = (
        items_per_productive / base
        if base and items_per_productive is not None else None)

    return {
        "source": "observed",
        "asset": asset,
        "ts_dataset": rows[-1]["ts_dataset"],
        "ts_replay": now_iso(),
        "window_slots": n,
        "rolling_items": round(items_total, 2),
        "items_per_slot": round(items_per_slot, 3),
        "items_per_productive_slot": (
            round(items_per_productive, 3) if items_per_productive is not None else None),
        "productive_share": round(productive, 3),
        "alarm_share": round(alarm, 3),
        "cycle_time_indicator": round(cycle_mean, 2) if cycle_mean is not None else None,
        "coverage": round(coverage, 3),
        "baseline_items_per_slot": base,
        "baseline_ratio": round(ratio, 3) if ratio is not None else None,
        "baseline_hour": hour,
    }


# ---------------------------------------------------------------------------
# Alerts - each one says WHY, and what the data can and cannot tell us.
# ---------------------------------------------------------------------------
def classify(m, asset):
    """Decide whether to raise an alert for this machine.

    Returns an alert dict, or None.
    """
    # Not enough data to judge. Say so instead of crying wolf.
    if m["coverage"] < MON["min_coverage"]:
        low_streak[asset] = 0
        alarm_streak[asset] = 0
        return {
            "level": "info",
            "kind": "insufficient_data",
            "message": (
                f"Machine {asset}: only {m['window_slots']}/{WINDOW} expected "
                f"slots arrived. Not judging output."
            ),
        }

    # ---- Case 1: the machine is being interrupted --------------------------
    # High alarm share is direct evidence, so we do not need the output
    # ratio (a machine stuck in alarm has no productive slots to compare).
    is_alarmy = m["alarm_share"] >= MON["high_alarm_share"]
    alarm_streak[asset] = alarm_streak[asset] + 1 if is_alarmy else 0

    if alarm_streak[asset] >= MON["sustained_slots"]:
        return {
            "level": "warning",
            "kind": "interruption",
            "recommendation": "investigate interruption",
            "message": (
                f"Machine {asset}: {m['alarm_share']:.0%} of the last "
                f"{m['window_slots']} slots were in alarm state, for "
                f"{alarm_streak[asset]} checks running. This is downtime, "
                f"not a capacity limit - fixing the stoppage comes before "
                f"adding capacity."
            ),
        }

    # ---- Case 2: running, but producing less than it normally does --------
    if m["baseline_ratio"] is None:
        low_streak[asset] = 0
        return None

    is_low = m["baseline_ratio"] < MON["low_output_ratio"]
    low_streak[asset] = low_streak[asset] + 1 if is_low else 0

    if low_streak[asset] < MON["sustained_slots"]:
        return None

    pct = round((1 - m["baseline_ratio"]) * 100)

    # Low output while running, without alarms. On THIS dataset we cannot
    # tell a slow machine from a starved one, because status 0 (idle) never
    # appears and there is no queue data. We say so rather than guessing.
    return {
        "level": "warning",
        "kind": "underperformance",
        "recommendation": "capacity-constraint candidate - cause not determinable from this dataset",
        "message": (
            f"Machine {asset}: while running, it produced {pct}% below its "
            f"own {m['baseline_hour']}:00 baseline "
            f"({m['items_per_productive_slot']} vs "
            f"{m['baseline_items_per_slot']} items per productive slot) for "
            f"{low_streak[asset]} checks, with few alarms "
            f"({m['alarm_share']:.0%}). This dataset has no idle state and "
            f"no queue data, so slow-vs-starved cannot be separated here. "
            f"See the virtual line."
        ),
    }


# ---------------------------------------------------------------------------
# Optional: 30-minute forecast, if a model has been trained.
# ---------------------------------------------------------------------------
def guard_prediction(bundle, asset, raw_prediction):
    """Bound a demo forecast by that asset's training-only target range."""
    prediction = max(float(raw_prediction), 0.0)
    limit = bundle.get("forecast_limit_by_asset", {}).get(str(asset))
    guarded = limit is not None and prediction > limit
    return (min(prediction, limit) if guarded else prediction), guarded, limit


def latency_metrics(started, received_ms=None, now_ms=None):
    """Closed-loop timings for one forecast, all on this laptop's clock.

    forecast_compute_ms: feature building + model prediction.
    ingest_to_forecast_ms: Node-RED received the record -> validated it ->
    stored it in SQLite -> republished it -> analytics -> forecast ready.
    Node-RED runs on the same laptop as analytics, so both stamps share a clock.
    """
    metrics = [("forecast_compute_ms", (time.perf_counter() - started) * 1000.0)]
    if isinstance(received_ms, (int, float)) and not isinstance(received_ms, bool):
        now_ms = time.time() * 1000.0 if now_ms is None else now_ms
        delay = now_ms - received_ms
        if 0 <= delay < 60_000:          # ignore impossible clock values
            metrics.append(("ingest_to_forecast_ms", delay))
    return [(name, round(value, 2)) for name, value in metrics]


def try_forecast(client, asset, received_ms=None, detail="live record"):
    """Publish a forecast. Silently skipped when no model is saved yet.

    MODEL is the bundle saved by ml_train.py: the fitted model plus the
    exact feature column order it was trained on, so the live features
    cannot drift out of order.
    """
    if MODEL is None or len(history[asset]) < CONFIG["ml"]["lookback_slots"]:
        return
    started = time.perf_counter()
    try:
        import ml_features
        rows = list(history[asset])[-CONFIG["ml"]["lookback_slots"]:]
        features = ml_features.features_from_live_rows(
            asset, rows, MODEL["feature_columns"])
        raw_prediction = float(MODEL["model"].predict([features])[0])
        prediction, guarded, guard = guard_prediction(MODEL, asset, raw_prediction)
        publish(client, topic("forecast", asset), {
            "source": "forecast",          # never "observed"
            "asset": asset,
            "model": MODEL["name"],
            "horizon_minutes": MODEL["horizon_minutes"],
            "predicted_items": round(prediction, 2),
            "prediction_guarded": guarded,
            "guard_limit": guard,
            "ts_dataset": rows[-1]["ts_dataset"],
            "ts_replay": now_iso(),
        })
        for name, value in latency_metrics(started, received_ms):
            publish(client, topic("perf_metric"), {
                "source": "forecast", "metric": name, "value": value,
                "detail": f"machine {asset} {MODEL['name']} {detail}",
                "ts_replay": now_iso()})
    except Exception as e:
        print(f"  (forecast skipped for machine {asset}: {e})")


# ---------------------------------------------------------------------------
# MQTT wiring
# ---------------------------------------------------------------------------
def on_message(client, userdata, message):
    try:
        msg = json.loads(message.payload.decode())
    except Exception:
        counters["rejected"] += 1
        print("  REJECTED: payload is not valid JSON")
        return

    if message.topic == topic("ml_select"):
        select_model(client, msg)
        return

    ok, reason = validate(msg)
    if not ok:
        counters["rejected"] += 1
        print(f"  REJECTED machine {msg.get('asset', '?') if isinstance(msg, dict) else '?'}: "
              f"{reason} (metrics unchanged)")
        return

    asset = msg["asset"]
    if start_new_run_if_needed(asset, msg.get("run_id")):
        print(f"  machine {asset}: new replay run {msg.get('run_id')} - window restarted")
    accepted, is_new_slot = update_history(asset, msg)
    if not accepted:
        counters["rejected"] += 1
        print(f"  REJECTED late record for machine {asset} (metrics unchanged)")
        return

    counters["accepted"] += 1
    low_streak.setdefault(asset, 0)
    alarm_streak.setdefault(asset, 0)
    metrics = compute_metrics(asset)
    publish(client, topic("observed_metrics", asset), metrics)

    prod = metrics["items_per_productive_slot"]
    print(f"  machine {asset}  "
          f"items/productive-slot={('%5.2f' % prod) if prod is not None else '  n/a'}  "
          f"baseline={metrics['baseline_items_per_slot']}  "
          f"ratio={metrics['baseline_ratio']}  "
          f"alarm={metrics['alarm_share']:.0%}  "
          f"coverage={metrics['coverage']:.0%}")

    # Repeated rows within a slot update the aggregate but do not count as
    # additional time steps for the sustained alert or forecast.
    if not is_new_slot:
        return

    alert = classify(metrics, asset)
    new_kind = alert["kind"] if alert else None
    old_kind = last_alert_kind.get(asset)
    if new_kind != old_kind:
        if alert is None:
            alert = {
                "level": "info",
                "kind": "cleared",
                "message": f"Machine {asset}: back to normal ({old_kind} ended).",
            }
        alert.update({"source": "observed", "asset": asset,
                      "ts_replay": now_iso(),
                      "ts_dataset": metrics["ts_dataset"]})
        publish(client, topic("observed_alert"), alert)
        print(f"  >> ALERT [{alert['kind']}] {alert['message']}")
    last_alert_kind[asset] = new_kind

    if metrics["coverage"] >= 1.0:
        try_forecast(client, asset, received_ms=msg.get("received_ms"))


def refresh_forecasts(client):
    """Re-forecast every machine's latest complete window with the active model.

    Without this, a model switch only shows up when the next record arrives,
    so switching after a replay has finished would appear to do nothing.
    """
    refreshed = 0
    for asset in sorted(history):
        if history[asset] and compute_metrics(asset)["coverage"] >= 1.0:
            try_forecast(client, asset, detail="model switch")
            refreshed += 1
    print(f"  re-forecast {refreshed} machine(s) with {MODEL['name']}", flush=True)
    return refreshed


def select_model(client, request):
    """Hot-swap only known local artifacts; MQTT cannot supply a file path."""
    global MODEL
    name = request.get("model") if isinstance(request, dict) else None
    if name == "validated_winner":
        model_file = path("model")
    elif name in ("ridge", "gradient_boosting", "neural_network"):
        model_file = ROOT / "results" / "demo_models" / f"{name}.joblib"
    else:
        return
    if not model_file.is_file():
        publish(client, topic("ml_active"), {
            "status": "error", "model": name,
            "error": "Train this demo model first.", "ts_replay": now_iso()})
        return
    try:
        import joblib
        candidate = joblib.load(model_file)
        if (candidate["horizon_minutes"] != CONFIG["ml"]["horizon_minutes"]
                or len(candidate["feature_columns"]) != 45):
            raise ValueError("Model feature contract does not match live analytics")
        MODEL = candidate
        provenance = candidate.get("provenance", "full_validated_study")
        publish(client, topic("ml_active"), {
            "status": "active", "model": candidate["name"],
            "provenance": provenance, "ts_replay": now_iso()})
        print(f"Active model switched to {candidate['name']} ({provenance})", flush=True)
        refresh_forecasts(client)
    except Exception as exc:
        publish(client, topic("ml_active"), {
            "status": "error", "model": name, "error": str(exc),
            "ts_replay": now_iso()})


def main():
    global BASELINE, MODEL

    BASELINE = json.loads(path("baseline").read_text())
    print(f"Loaded baselines for {len(BASELINE)} machines.")

    model_file = path("model")
    if model_file.exists():
        import joblib
        MODEL = joblib.load(model_file)
        print(f"Loaded forecasting model '{MODEL['name']}' "
              f"({MODEL['horizon_minutes']}-minute horizon, "
              f"active MAE {MODEL.get('active_mae')}).")
    else:
        print("No saved model yet - forecasts disabled. "
              "Run `python src/ml_train.py` to enable them.")

    client = connect("analytics")
    client.on_message = on_message
    client.subscribe(topic("observed_validated") + "/#")
    client.subscribe(topic("ml_select"))
    if MODEL is not None:
        publish(client, topic("ml_active"), {
            "status": "active", "model": MODEL["name"],
            "provenance": MODEL.get("provenance", "full_validated_study"),
            "ts_replay": now_iso()})
    print(f"Watching {topic('observed_validated')}/# ... Ctrl-C to stop.\n")

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print(f"\nAccepted {counters['accepted']}, "
              f"rejected {counters['rejected']} records.")


if __name__ == "__main__":
    main()



