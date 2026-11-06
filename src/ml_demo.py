"""Train one real Company A model on demand for the interactive classroom demo.

All three buttons use the same small, chronological, purged subset. These
scores are deliberately separate from the full offline model-selection study.
"""
import json
import threading
import time
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

import ml_features
from common import CONFIG, ROOT, connect, now_iso, path, publish, topic
from ml_train import TARGET, fit_quietly, label_span, model_specs, nonnegative

MODELS = ("ridge", "gradient_boosting", "neural_network")
LOCK = threading.Lock()
DEMO_DIR = ROOT / "results" / "demo_models"


@lru_cache(maxsize=1)
def demo_data():
    """Use identical forward-time examples for every button click."""
    # The fixed replay is 28 March 2022. Train only on the preceding weeks,
    # so a quick demo override does not extrapolate from early January.
    frame = pd.read_csv(path("features"), nrows=210000, parse_dates=["slot"])
    frame = frame[(frame["slot"] >= pd.Timestamp("2022-03-01", tz="UTC")) &
                  (frame["slot"] < pd.Timestamp("2022-03-28", tz="UTC"))].tail(50000)
    times = frame["slot"].drop_duplicates().sort_values().to_numpy()
    cutoff = pd.Timestamp(times[int(len(times) * 0.7)])
    train = frame[(frame["slot"] + label_span()) < cutoff]
    valid = frame[frame["slot"] >= cutoff]
    columns = ml_features.feature_columns(frame)
    if len(train) < 1000 or len(valid) < 100 or not (valid[TARGET] > 0).any():
        raise RuntimeError("The fixed demo slice has too few usable validation examples")
    return train, valid, columns


def train_one(name):
    if name not in MODELS:
        raise ValueError("Unknown model")
    train, valid, columns = demo_data()
    spec = model_specs(1.0)[name]
    start = time.perf_counter()
    model = fit_quietly(spec["build"](), train[columns].to_numpy(),
                        train[TARGET].to_numpy())
    train_seconds = time.perf_counter() - start
    # A quick subset can make an extrapolating model emit impossible spikes.
    # Set the same per-machine bound for all three candidates from TRAINING
    # targets only. This is a guardrail, not a factory capacity measurement.
    limits = {str(asset): round(float(value) * 1.2, 2)
              for asset, value in train.groupby("asset")[TARGET].quantile(.995).items()}
    raw_pred = nonnegative(model.predict(valid[columns].to_numpy()))
    row_limits = valid["asset"].map(lambda asset: limits[str(asset)]).to_numpy()
    pred = np.minimum(raw_pred, row_limits)
    actual = valid[TARGET].to_numpy()
    active = actual > 0
    idle = ~active
    result = {
        "model": name, "family": spec["family"], "status": "trained",
        "source": "demo_subset", "train_rows": len(train),
        "valid_rows": len(valid), "active_valid_rows": int(active.sum()),
        "train_seconds": round(train_seconds, 2),
        "forecast_guard": "1.2x training-period per-machine 99.5th percentile",
        "active_mae": round(float(np.abs(pred[active] - actual[active]).mean()), 3),
        "idle_mae": round(float(np.abs(pred[idle] - actual[idle]).mean()), 3)
                    if idle.any() else None,
        "overall_mae": round(float(np.abs(pred - actual).mean()), 3),
        "ts_replay": now_iso(),
    }
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    bundle = {"name": "demo_" + name, "model": model,
              "feature_columns": columns,
              "horizon_minutes": CONFIG["ml"]["horizon_minutes"],
              "active_mae": result["active_mae"],
              "provenance": "small_demo_subset",
              "forecast_limit_by_asset": limits}
    destination = DEMO_DIR / f"{name}.joblib"
    temporary = destination.with_suffix(".tmp")
    joblib.dump(bundle, temporary)
    temporary.replace(destination)
    return result


def main():
    client = connect("ml-demo")

    def work(name):
        try:
            publish(client, topic("ml_train_result"), {
                "model": name, "status": "training", "ts_replay": now_iso()})
            result = train_one(name)
            publish(client, topic("ml_train_result"), result)
            print(f"Trained {name}: active MAE {result['active_mae']}", flush=True)
        except Exception as exc:
            publish(client, topic("ml_train_result"), {
                "model": name, "status": "error", "error": str(exc),
                "ts_replay": now_iso()})
            print(f"Training {name} failed: {exc}", flush=True)
        finally:
            LOCK.release()

    def on_message(_client, _userdata, message):
        try:
            request = json.loads(message.payload.decode())
            name = request.get("model")
        except Exception:
            return
        if name not in MODELS:
            return
        if not LOCK.acquire(blocking=False):
            publish(client, topic("ml_train_result"), {
                "model": name, "status": "busy",
                "error": "Another training run is in progress; retry shortly.",
                "ts_replay": now_iso()})
            return
        threading.Thread(target=work, args=(name,), daemon=True).start()

    client.on_message = on_message
    client.subscribe(topic("ml_train_request"))
    print("ML demo trainer ready; three real Company A training buttons available.", flush=True)
    client.loop_forever()


if __name__ == "__main__":
    main()
