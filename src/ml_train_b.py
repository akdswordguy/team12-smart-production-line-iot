"""Three separate Company B models for next-minute operating-state classification.

Only consecutive one-minute records before the 28 March replay are used.
Company A's item-count model is a different task and is never compared by F1.
"""
import json
import time
import warnings
import zipfile
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from common import ROOT

STATES = ["Alarm", "Standby", "MachineOn", "Production", "Loading", "Tooling"]
FEATURES = (["power_log", "hour", "dayofweek"] +
            [f"status_{s}" for s in STATES] + [f"asset_{i}" for i in range(18)])
REPORT = ROOT / "results/company_b_models.json"
MODEL = ROOT / "results/company_b_model.joblib"


def data():
    with zipfile.ZipFile(ROOT / "data/raw/company_B.zip") as archive, archive.open("company_B.csv") as stream:
        frame = pd.read_csv(stream, usecols=["ts", "asset", "status", "power_avg"])
    frame = frame[(frame.ts >= "2022-01-01") & (frame.ts < "2022-03-28")].copy()
    frame["ts"] = pd.to_datetime(frame.ts, utc=True)
    frame = frame.sort_values(["asset", "ts"])
    frame["next_ts"] = frame.groupby("asset").ts.shift(-1)
    frame["target"] = frame.groupby("asset").status.shift(-1)
    frame = frame[(frame.next_ts - frame.ts) == pd.Timedelta(minutes=1)]
    frame = frame.sort_values(["ts", "asset"]).tail(150000).copy()
    frame["power_log"] = np.log1p(frame.power_avg.clip(lower=0, upper=2000).fillna(0))
    frame["hour"] = frame.ts.dt.hour
    frame["dayofweek"] = frame.ts.dt.dayofweek
    for state in STATES:
        frame[f"status_{state}"] = (frame.status == state).astype(int)
    for asset in range(18):
        frame[f"asset_{asset}"] = (frame.asset == asset).astype(int)
    times = frame.ts.drop_duplicates().sort_values().to_numpy()
    cut1 = pd.Timestamp(times[int(len(times) * .70)])
    cut2 = pd.Timestamp(times[int(len(times) * .85)])
    train = frame[frame.next_ts < cut1]
    valid = frame[(frame.ts >= cut1) & (frame.next_ts < cut2)]
    test = frame[frame.ts >= cut2]
    return train, valid, test


def scores(actual, predicted):
    return {"macro_f1": round(float(f1_score(actual, predicted, labels=STATES,
                                             average="macro", zero_division=0)), 4),
            "balanced_accuracy": round(float(balanced_accuracy_score(actual, predicted)), 4),
            "accuracy": round(float(accuracy_score(actual, predicted)), 4)}


def main():
    train, valid, test = data()
    specs = {
        "logistic_regression": ("traditional", lambda: make_pipeline(
            StandardScaler(), LogisticRegression(max_iter=200))),
        "gradient_boosting": ("ensemble", lambda: HistGradientBoostingClassifier(
            max_iter=120, max_depth=6, random_state=42)),
        "neural_network": ("neural", lambda: make_pipeline(
            StandardScaler(), MLPClassifier(hidden_layer_sizes=(32, 16), max_iter=30,
                                            early_stopping=True, random_state=42))),
    }
    x_train, y_train = train[FEATURES].to_numpy(), train.target.to_numpy()
    x_valid, y_valid = valid[FEATURES].to_numpy(), valid.target.to_numpy()
    x_test, y_test = test[FEATURES].to_numpy(), test.target.to_numpy()
    candidates, fitted = {}, {}
    for name, (family, builder) in specs.items():
        started = time.perf_counter()
        model = builder()
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=ConvergenceWarning)
            model.fit(x_train, y_train)
        fit_seconds = round(time.perf_counter() - started, 2)
        candidates[name] = {"family": family, "validation": scores(y_valid, model.predict(x_valid)),
                            "training_seconds": fit_seconds}
        fitted[name] = model
        print(name, candidates[name], flush=True)
    selected = max(candidates, key=lambda k: candidates[k]["validation"]["macro_f1"])
    selected_model = fitted[selected]
    report = {
        "task": "next operating state after exactly one minute of continuous reporting",
        "source": "fixed Company B ZIP, before 2022-03-28 replay",
        "features": FEATURES, "train_rows": len(train), "validation_rows": len(valid),
        "test_rows": len(test), "train_period": [str(train.ts.min()), str(train.ts.max())],
        "validation_period": [str(valid.ts.min()), str(valid.ts.max())],
        "test_period": [str(test.ts.min()), str(test.ts.max())],
        "baseline_persistence_validation": scores(y_valid, valid.status.to_numpy()),
        "baseline_persistence_test": scores(y_test, test.status.to_numpy()),
        "candidates": candidates, "selected": selected,
        "selected_test": scores(y_test, selected_model.predict(x_test)),
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    joblib.dump({"model": selected_model, "name": selected, "features": FEATURES}, MODEL)
    print("Selected", selected, "saved to", MODEL, flush=True)


if __name__ == "__main__":
    main()
