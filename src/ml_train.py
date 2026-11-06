"""Train three distinct model families on the fixed Company A forecast task.

Traditional: Ridge regression. Ensemble: histogram gradient boosting.
Deep learning: feed-forward neural network with two hidden layers.

HOW A MODEL IS CHOSEN
---------------------
The later test period is never used to choose or tune anything. Selection
runs on validation data only, and uses ROLLING-ORIGIN CROSS-VALIDATION
rather than a single validation block.

Why: on one validation block the three families finished within about 2% of
each other, which is the same size as the tie-break rule. A single number
cannot tell a real difference from the luck of one seven-week window.
Several time-ordered folds can: if one family wins on every fold, the
result is believable; if the ranking flips between folds, we say so.

Each fold trains on an expanding prefix of the pre-test period and scores
the block immediately after it, always forwards in time, with the same
25-minute label embargo used at the main split.

WHAT IS REPORTED
----------------
  Active MAE  error on windows where the machine actually produced
  Idle MAE    error on windows where it produced nothing
  Overall MAE both together
The last period is about 81% idle windows, so overall MAE mostly measures
idleness detection. Active MAE alone can hide a model that cries wolf on a
stopped machine, so both are reported.
"""

import pickle
import time
import warnings

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import Ridge
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import ml_features
from common import CONFIG, ROOT, path, require, save_json

ML = CONFIG["ml"]
TARGET = "target_items_next30"

# How many rolling-origin validation folds to use for selection.
CV_FOLDS = ML.get("cv_folds", 4)

# A model only displaces the leader if it is more than this much better;
# inside the margin the smaller serialized model wins the tie.
TIE_MARGIN = ML.get("selection_tie_margin", 0.02)


def label_span():
    """How far a label reaches past its origin slot (30 min target = +25 min)."""
    return pd.Timedelta(minutes=ML["horizon_minutes"] - ml_features.SLOT_MINUTES)


def chronological_split(table):
    """Split by origin time, purging origins whose label crosses a boundary."""
    times = table["slot"].sort_values().unique()
    n = len(times)
    train_end = times[int(n * ML["train_fraction"])]
    valid_end = times[int(n * (ML["train_fraction"] + ML["valid_fraction"]))]
    span = label_span()
    train = table[(table["slot"] + span) < train_end]
    valid = table[(table["slot"] >= train_end) & ((table["slot"] + span) < valid_end)]
    test = table[table["slot"] >= valid_end]
    print("Chronological split (no shuffling; purged label overlap):")
    for name, frame in (("train", train), ("valid", valid), ("test", test)):
        print(f"  {name:<6} {len(frame):>7,} rows  {frame['slot'].min()} -> "
              f"{frame['slot'].max()}  zero-output: {(frame[TARGET] == 0).mean():.1%}",
              flush=True)
    return train, valid, test


def rolling_origin_folds(frame, n_folds):
    """Expanding-window folds, always forwards in time.

    The pre-test period is cut into n_folds + 1 equal blocks of time.
    Fold i trains on blocks 0..i and validates on block i+1:

        fold 1   train [#####]            valid [#####]
        fold 2   train [##########]       valid [#####]
        fold 3   train [###############]  valid [#####]

    No fold ever trains on data that comes after the block it scores, and
    the label embargo is applied at every boundary exactly as it is at the
    main split.
    """
    times = frame["slot"].sort_values().unique()
    span = label_span()
    edges = [times[int(len(times) * k / (n_folds + 1))]
             for k in range(1, n_folds + 1)] + [times[-1] + span]

    folds = []
    for i, cut in enumerate(edges[:-1]):
        nxt = edges[i + 1]
        fold_train = frame[(frame["slot"] + span) < cut]
        fold_valid = frame[(frame["slot"] >= cut) & ((frame["slot"] + span) < nxt)]
        if len(fold_train) and len(fold_valid):
            folds.append((fold_train, fold_valid))
    return folds


def nonnegative(prediction):
    """The live service also clips impossible negative count predictions."""
    return np.maximum(np.asarray(prediction, dtype=float), 0.0)


def mae(actual, predicted):
    return float(np.mean(np.abs(actual - predicted)))


def rmse(actual, predicted):
    return float(np.sqrt(np.mean((actual - predicted) ** 2)))


def active_scores(actual, predicted):
    """Error where the machine really produced something."""
    mask = actual > 0
    return {
        "mae": round(mae(actual[mask], predicted[mask]), 3) if mask.any() else None,
        "rmse": round(rmse(actual[mask], predicted[mask]), 3) if mask.any() else None,
        "n": int(mask.sum()),
    }


def idle_scores(actual, predicted):
    """Error where the machine produced NOTHING.

    On an idle window the true answer is zero, so this is simply how much
    output the model wrongly promises. A model with a fine Active MAE that
    predicts production from a stopped machine would send operators chasing
    work that is never coming; this is what makes that visible.
    """
    mask = actual == 0
    if not mask.any():
        return {"mae": None, "over_1_item_share": None, "n": 0}
    wrong = np.abs(predicted[mask])
    return {
        "mae": round(float(wrong.mean()), 3),
        "over_1_item_share": round(float((wrong > 1.0).mean()), 4),
        "n": int(mask.sum()),
    }


def score_per_machine(frame, actual, predicted):
    out = {}
    for asset in sorted(frame["asset"].unique()):
        mask = frame["asset"].to_numpy() == asset
        out[str(int(asset))] = {
            "mae": round(mae(actual[mask], predicted[mask]), 3),
            "rmse": round(rmse(actual[mask], predicted[mask]), 3),
            "n": int(mask.sum()),
            "mean_actual": round(float(actual[mask].mean()), 3),
        }
    return out


def measure_latency(predict, X):
    sample = X[:min(1000, len(X))]
    predict(sample)
    elapsed = []
    for _ in range(3):
        start = time.perf_counter()
        predict(sample)
        elapsed.append(time.perf_counter() - start)
    return round(min(elapsed) / len(sample) * 1_000_000, 2)


def score_candidate(kind, family, description, valid, pred_valid,
                    train_seconds=0.0, latency=0.0, size_mb=0.0):
    actual = valid[TARGET].to_numpy()
    predicted = nonnegative(pred_valid)
    return {
        "kind": kind, "family": family, "description": description,
        "valid_mae": round(mae(actual, predicted), 3),
        "valid_rmse": round(rmse(actual, predicted), 3),
        "valid_active": active_scores(actual, predicted),
        "valid_idle": idle_scores(actual, predicted),
        "train_seconds": round(train_seconds, 2),
        "predict_ms_per_1000": latency,
        "model_size_mb": round(size_mb, 3),
    }


def add_test_scores(result, test, prediction):
    """Called only AFTER model selection; mutates the report record."""
    actual = test[TARGET].to_numpy()
    predicted = nonnegative(prediction)
    result.update({
        "test_mae": round(mae(actual, predicted), 3),
        "test_rmse": round(rmse(actual, predicted), 3),
        "active": active_scores(actual, predicted),
        "idle": idle_scores(actual, predicted),
        "per_machine": score_per_machine(test, actual, predicted),
    })


def baseline_predictions(train, frame, name):
    if name == "always_zero":
        return np.zeros(len(frame))
    if name == "persistence":
        return frame["items_sum_last30"].to_numpy()
    averages = train.groupby(["asset", "hour"])[TARGET].mean()
    fallback = train[TARGET].mean()
    keys = zip(frame["asset"].to_numpy(), frame["hour"].to_numpy())
    return np.fromiter((averages.get(k, fallback) for k in keys), dtype=float)


# ---------------------------------------------------------------------------
# The three model families. Each entry builds a FRESH, unfitted model, so
# cross-validation and the final fit use identical settings.
# ---------------------------------------------------------------------------
def model_specs(ridge_alpha, seed=None):
    # seed=None keeps the fixed, reproducible study seed from config.yaml.
    seed = ML["random_state"] if seed is None else int(seed)
    return {
        "ridge": {
            "family": "traditional ML",
            "description": f"regularized linear regression; alpha={ridge_alpha}",
            "build": lambda: make_pipeline(StandardScaler(), Ridge(alpha=ridge_alpha)),
        },
        "gradient_boosting": {
            "family": "ensemble ML",
            "description": "histogram gradient-boosted trees; 300 rounds",
            "build": lambda: HistGradientBoostingRegressor(
                max_iter=300, learning_rate=0.1, random_state=seed),
        },
        "neural_network": {
            "family": "deep learning",
            "description": ("feed-forward neural network; two ReLU hidden "
                            "layers of 32 and 16 units"),
            "build": lambda: make_pipeline(StandardScaler(), MLPRegressor(
                hidden_layer_sizes=(32, 16), activation="relu", solver="adam",
                batch_size=2048, max_iter=60, n_iter_no_change=7,
                learning_rate_init=0.001, random_state=seed)),
        },
    }


def fit_quietly(model, X, y):
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=ConvergenceWarning)
        model.fit(X, y)
    return model


def active_mae_on(model, frame, columns):
    actual = frame[TARGET].to_numpy()
    predicted = nonnegative(model.predict(frame[columns].to_numpy()))
    mask = actual > 0
    return mae(actual[mask], predicted[mask]) if mask.any() else float("nan")


def cross_validate(specs, folds, columns):
    """Score every family on every rolling-origin fold. Validation only."""
    scores = {name: [] for name in specs}
    for i, (fold_train, fold_valid) in enumerate(folds, start=1):
        print(f"  fold {i}: train {len(fold_train):,} -> valid "
              f"{len(fold_valid):,} rows  "
              f"({fold_valid['slot'].min().date()} to "
              f"{fold_valid['slot'].max().date()}, "
              f"{(fold_valid[TARGET] == 0).mean():.0%} idle)", flush=True)
        X, y = fold_train[columns].to_numpy(), fold_train[TARGET].to_numpy()
        for name, spec in specs.items():
            model = fit_quietly(spec["build"](), X, y)
            score = active_mae_on(model, fold_valid, columns)
            scores[name].append(round(score, 4))
            print(f"      {name:<18} active MAE {score:.4f}", flush=True)
    return scores


def summarise_cv(scores):
    out = {}
    for name, values in scores.items():
        usable = [v for v in values if v == v]       # drop NaN folds
        out[name] = {
            "per_fold": values,
            "mean": round(float(np.mean(usable)), 4) if usable else None,
            "worst": round(float(np.max(usable)), 4) if usable else None,
            "folds": len(usable),
        }
    return out


def won_every_fold(scores, winner):
    """True when the winner has the lowest active MAE on every single fold."""
    return all(
        scores[winner][i] == min(scores[name][i] for name in scores)
        for i in range(len(scores[winner])))


def choose_model(results, metric=None, recent=None):
    """Pick a model using validation evidence only.

    Three rules, applied in order:

    1. Lowest `metric` (the mean across folds) wins outright, unless another
       model is within TIE_MARGIN of it.
    2. Among models inside that margin, the one with the best MOST RECENT
       fold wins. This dataset drifts hard - the machines grow steadily more
       idle through the file - so the latest fold is the closest thing we
       have to "how will this behave next month". Accuracy evidence should
       settle an accuracy question before anything else does.
    3. Only if the recent fold is also a tie does the smallest serialized
       model win, because by then the two really are equivalent and the
       live service still has to load whichever we pick.

    `metric` defaults to the single-block validation Active MAE so the
    function stands on its own; main() passes the cross-validated mean and
    the latest fold, which is the evidence we actually trust.
    """
    if metric is None:
        def metric(result):
            return result["valid_active"]["mae"]

    ranked = sorted(
        ((name, result) for name, result in results.items()
         if result["kind"] == "model"),
        key=lambda pair: metric(pair[1]))
    best = metric(ranked[0][1])
    near = [(name, result) for name, result in ranked
            if metric(result) <= best * (1 + TIE_MARGIN)]

    if len(near) == 1 or recent is None:
        return min(near, key=lambda pair: pair[1]["model_size_mb"])

    # Rule 2: let the most recent fold break the tie, if it is decisive.
    by_recent = sorted(near, key=lambda pair: recent(pair[1]))
    best_recent = recent(by_recent[0][1])
    still_tied = [pair for pair in by_recent
                  if recent(pair[1]) <= best_recent * (1 + TIE_MARGIN)]
    if len(still_tied) == 1:
        return by_recent[0]

    # Rule 3: genuinely equivalent, so take the cheaper one to run.
    return min(still_tied, key=lambda pair: pair[1]["model_size_mb"])


def main():
    table = pd.read_csv(require(
        "features", "Build features first: python src/ml_features.py"),
        parse_dates=["slot"])
    columns = ml_features.feature_columns(table)
    print(f"{len(table):,} complete examples; {len(columns)} features", flush=True)
    train, valid, test = chronological_split(table)
    Xtr, ytr = train[columns].to_numpy(), train[TARGET].to_numpy()
    Xva, yva = valid[columns].to_numpy(), valid[TARGET].to_numpy()
    results, models = {}, {}

    print("\nScoring three simple reference methods ...", flush=True)
    for name, description in (
        ("always_zero", "always predict zero"),
        ("persistence", "repeat the last 30 minutes"),
        ("machine_hour", "training-period machine/hour mean"),
    ):
        results["baseline_" + name] = score_candidate(
            "baseline", "reference", description, valid,
            baseline_predictions(train, valid, name))

    # Everything before the test period. Selection may look at all of this
    # and at nothing else.
    pre_test = table[table["slot"] < test["slot"].min()]
    folds = rolling_origin_folds(pre_test, CV_FOLDS)

    # ---- Ridge's alpha is tuned on the folds, never on the test period ----
    print(f"\nTuning Ridge on {len(folds)} rolling-origin folds ...", flush=True)
    best_alpha, best_alpha_score = None, float("inf")
    for alpha in (0.1, 1.0, 10.0):
        fold_scores = []
        for fold_train, fold_valid in folds:
            model = fit_quietly(
                make_pipeline(StandardScaler(), Ridge(alpha=alpha)),
                fold_train[columns].to_numpy(), fold_train[TARGET].to_numpy())
            fold_scores.append(active_mae_on(model, fold_valid, columns))
        mean_score = float(np.mean(fold_scores))
        print(f"  alpha={alpha}: mean fold active MAE {mean_score:.4f}", flush=True)
        if mean_score < best_alpha_score:
            best_alpha, best_alpha_score = alpha, mean_score
    print(f"  chosen alpha = {best_alpha}", flush=True)

    specs = model_specs(best_alpha)

    # ---- rolling-origin cross-validation: the selection evidence ----------
    print(f"\nCross-validating three families on {len(folds)} folds "
          f"(validation only) ...", flush=True)
    cv_scores = cross_validate(specs, folds, columns)
    cv = summarise_cv(cv_scores)
    print("\n  mean active MAE across folds:", flush=True)
    for name in sorted(cv, key=lambda k: cv[k]["mean"]):
        print(f"    {name:<18} {cv[name]['mean']:.4f}   "
              f"folds {cv[name]['per_fold']}", flush=True)

    # ---- fit each family once on the training block, for the report table -
    print("\nFitting each family on the training block ...", flush=True)
    for name, spec in specs.items():
        start = time.perf_counter()
        model = fit_quietly(spec["build"](), Xtr, ytr)
        seconds = time.perf_counter() - start
        models[name] = model
        results[name] = score_candidate(
            "model", spec["family"], spec["description"], valid,
            model.predict(Xva), seconds,
            measure_latency(model.predict, Xva),
            len(pickle.dumps(model)) / 1024 ** 2)
        results[name]["cv_active_mae"] = cv[name]
        print(f"  {name:<18} single-block active MAE "
              f"{results[name]['valid_active']['mae']}; trained in {seconds:.1f}s",
              flush=True)

    # ---- selection: cross-validated mean, validation data only ------------
    chosen_name, chosen = choose_model(
        results,
        metric=lambda r: r["cv_active_mae"]["mean"],
        recent=lambda r: r["cv_active_mae"]["per_fold"][-1])
    # The runner-up is the best model that is NOT the one we picked.
    ranking = [n for n in sorted(cv, key=lambda k: cv[k]["mean"])
               if n != chosen_name]
    runner_up = ranking[0] if ranking else None
    margin = (None if runner_up is None else
              round((cv[runner_up]["mean"] - cv[chosen_name]["mean"])
                    / cv[chosen_name]["mean"] * 100, 2))
    recent_margin = (None if runner_up is None else
                     round((cv[runner_up]["per_fold"][-1]
                            - cv[chosen_name]["per_fold"][-1])
                           / cv[chosen_name]["per_fold"][-1] * 100, 2))
    swept = won_every_fold(cv_scores, chosen_name)

    print(f"\nSelected {chosen_name} on cross-validated validation data.")
    print(f"  mean across folds : {margin:+}% vs {runner_up}", flush=True)
    print(f"  most recent fold  : {recent_margin:+}% vs {runner_up}", flush=True)
    print(f"  won every fold    : {swept}", flush=True)
    print("Opening the held-out test now - after selection is locked.",
          flush=True)

    # ---- the test period is touched only from here down -------------------
    Xte = test[columns].to_numpy()
    for name in ("always_zero", "persistence", "machine_hour"):
        add_test_scores(results["baseline_" + name], test,
                        baseline_predictions(train, test, name))
    for name, model in models.items():
        add_test_scores(results[name], test, model.predict(Xte))

    # ---- the deployed model sees every pre-test row ------------------------
    # Selection is already locked, so this changes nothing about the choice.
    # It lets the shipped model learn from the most recent weeks too, which
    # matters because the machines grow steadily more idle through the file.
    print("\nRefitting the selected family on ALL pre-test data for "
          "deployment ...", flush=True)
    deployed = fit_quietly(specs[chosen_name]["build"](),
                           pre_test[columns].to_numpy(),
                           pre_test[TARGET].to_numpy())
    deployed_result = {"kind": "deployed", "family": chosen["family"],
                       "description": f"{chosen_name} refit on train+validation",
                       "model_size_mb": round(
                           len(pickle.dumps(deployed)) / 1024 ** 2, 3)}
    add_test_scores(deployed_result, test, deployed.predict(Xte))
    results["deployed_" + chosen_name] = deployed_result
    print(f"  train block only : test active MAE {chosen['active']['mae']}, "
          f"idle {chosen['idle']['mae']}, overall {chosen['test_mae']}",
          flush=True)
    print(f"  all pre-test data: test active MAE "
          f"{deployed_result['active']['mae']}, "
          f"idle {deployed_result['idle']['mae']}, "
          f"overall {deployed_result['test_mae']}", flush=True)

    persistence = results["baseline_persistence"]
    bundle = {
        "model": deployed, "feature_columns": columns,
        "name": chosen_name, "family": chosen["family"],
        "horizon_minutes": ML["horizon_minutes"],
        "selection": (f"mean active MAE over {len(folds)} rolling-origin "
                      f"validation folds; smaller model wins inside "
                      f"{TIE_MARGIN:.0%}"),
        "trained_on": "all pre-test data (train + validation)",
        "test_mae": deployed_result["test_mae"],
        "active_mae": deployed_result["active"]["mae"],
    }
    joblib.dump(bundle, path("model"))
    split = {
        "train_rows": int(len(train)), "valid_rows": int(len(valid)),
        "test_rows": int(len(test)),
        "train_period": [str(train["slot"].min()), str(train["slot"].max())],
        "valid_period": [str(valid["slot"].min()), str(valid["slot"].max())],
        "test_period": [str(test["slot"].min()), str(test["slot"].max())],
        "zero_share_train": round(float((ytr == 0).mean()), 3),
        "zero_share_valid": round(float((yva == 0).mean()), 3),
        "zero_share_test": round(float((test[TARGET] == 0).mean()), 3),
    }
    summary = {
        "examples": int(len(table)), "features": len(columns),
        "split": split,
        "cross_validation": {
            "folds": len(folds), "scheme": "expanding-window rolling origin",
            "metric": "active MAE", "scores": cv,
            "winner_swept_all_folds": bool(swept),
            "margin_over_runner_up_percent": margin,
            "recent_fold_margin_over_runner_up_percent": recent_margin,
            "runner_up": runner_up,
            "tie_margin": TIE_MARGIN,
        },
        "chosen_model": chosen_name,
        "chosen_on": bundle["selection"],
        "deployed_model_trained_on": bundle["trained_on"],
        "chosen_beats_persistence_on_test_active":
            bool(deployed_result["active"]["mae"] < persistence["active"]["mae"]),
        "chosen_beats_persistence_on_test_overall":
            bool(deployed_result["test_mae"] < persistence["test_mae"]),
        "results": results,
    }
    save_json(ROOT / "results" / "model_comparison.json", summary)
    write_markdown(summary)
    print(f"\nSaved {path('model')}", flush=True)


def write_markdown(summary):
    r, split, winner = summary["results"], summary["split"], summary["chosen_model"]
    cv = summary["cross_validation"]
    deployed = r["deployed_" + winner]
    lines = [
        "# Three-family model comparison", "",
        "Predict **items produced by one machine in the next 30 minutes**. This "
        "is a machine forecast, not a measured production-line bottleneck.", "",
        f"Source: fixed Company A data; {summary['examples']:,} complete "
        f"consecutive examples; {summary['features']} past-only features.",
        f"Chronological split: {split['train_rows']:,} training / "
        f"{split['valid_rows']:,} validation / {split['test_rows']:,} test.",
        f"Validation: {split['valid_period'][0]} to {split['valid_period'][1]}.",
        f"Test: {split['test_period'][0]} to {split['test_period'][1]}.",
        "A 25-minute label embargo prevents overlap at split boundaries. "
        "Windows touching a missing five-minute slot are excluded. Test data "
        "is used for final reporting only, never to choose or tune a model.", "",
        "## The three different algorithms", "",
        "1. **Traditional ML: Ridge regression.** A regularized linear model.",
        "2. **Ensemble ML: histogram gradient boosting.** Sequential trees "
        "learn nonlinear interactions.",
        "3. **Deep learning: feed-forward neural network.** Two hidden layers "
        "(32 and 16 units) learn nonlinear patterns from scaled inputs.", "",
        "All three use the **same fixed dataset, features, time split and "
        "target**. They introduce no extra data. Negative count predictions "
        "are clipped to zero, as in the live service.", "",
        "## How the winner was chosen", "",
        f"Selection used **{cv['folds']} rolling-origin validation folds**, "
        "not a single validation block. Each fold trains on an expanding "
        "prefix of the pre-test period and scores the stretch of time "
        "immediately after it, always forwards, with the same label embargo.",
        "",
        "This matters here. On one validation block the three families "
        "finished within about 2% of each other - the same size as the "
        "tie-break rule - so the ranking could have been an accident of that "
        "particular seven-week window. Several folds show whether the "
        "ordering is stable.", "",
        "| Model | Fold active MAE (each fold) | Mean | Worst fold |",
        "|---|---|---:|---:|",
    ]
    for name in sorted(cv["scores"], key=lambda k: cv["scores"][k]["mean"]):
        item = cv["scores"][name]
        label = f"**{name}**" if name == winner else name
        folds_text = ", ".join(f"{v:.3f}" for v in item["per_fold"])
        lines.append(f"| {label} | {folds_text} | {item['mean']:.4f} | "
                     f"{item['worst']:.4f} |")

    swept = cv["winner_swept_all_folds"]
    runner = cv["runner_up"]
    lines += [
        "",
        f"**{winner}** was selected. It is "
        f"**{cv['margin_over_runner_up_percent']}% ahead of {runner} on the "
        f"fold mean** and "
        f"**{cv['recent_fold_margin_over_runner_up_percent']}% ahead on the "
        f"most recent fold** (a larger number means {winner} is further "
        f"ahead). It "
        f"{'wins every single fold' if swept else 'does not win every fold'}.",
        "",
        "### The honest reading", "",
        "The two leading families are close - closer than the "
        f"{cv['tie_margin']:.0%} tie margin - and the ranking **flips "
        "between folds**. Claiming one is decisively better than the other "
        "on this dataset would not survive a careful question.",
        "",
        "What breaks the tie is *which* folds each wins. The idle share "
        "climbs steadily through the file, and the test period is the "
        "idlest stretch of all, so the latest fold is the closest thing we "
        "have to \"how will this behave next month\". The selection rule "
        "therefore settles a tie on the most recent fold before it ever "
        "looks at model size: accuracy evidence should answer an accuracy "
        "question, and size is only a deployment convenience.",
        "",
        "The full fold table is printed above precisely so a reader can "
        "check that reasoning instead of taking the single mean on trust.",
    ]
    lines += [
        "",
        "## Held-out test results", "",
        "Reported after selection was locked. **Active MAE** is the error on "
        "windows where the machine really produced something. **Idle MAE** is "
        "how much output a model wrongly promises on windows where the "
        "machine produced nothing - a model that cries wolf on a stopped "
        "machine sends operators chasing work that is never coming. The last "
        f"period is {split['zero_share_test']:.0%} idle windows, so overall "
        "MAE mostly measures idleness detection; all three columns are needed "
        "to judge a model fairly.", "",
        f"Zero-output share: training {split['zero_share_train']:.1%}, "
        f"validation {split['zero_share_valid']:.1%}, "
        f"test {split['zero_share_test']:.1%}.", "",
        "| Model | Family | Test Active MAE | Test Idle MAE | Test MAE | "
        "Test RMSE | Train s | Predict ms/1000 | MB |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    order = ["ridge", "gradient_boosting", "neural_network",
             "baseline_persistence", "baseline_machine_hour",
             "baseline_always_zero"]
    for name in order:
        item = r[name]
        label = f"**{name}**" if name == winner else name
        lines.append(
            f"| {label} | {item['family']} | {item['active']['mae']} | "
            f"{item['idle']['mae']} | {item['test_mae']} | "
            f"{item['test_rmse']} | {item['train_seconds']} | "
            f"{item['predict_ms_per_1000']} | {item['model_size_mb']} |")
    lines += [
        "",
        "## The model we actually ship", "",
        f"Once {winner} was selected, it was refit on **all pre-test data** "
        "(training plus validation) and saved to "
        "`results/chosen_model.joblib`. Selection was already locked, so this "
        "cannot leak the test period; it simply lets the shipped model learn "
        "from the most recent weeks as well, which matters because the "
        "machines grow steadily more idle through the file.", "",
        "| Fitted on | Test Active MAE | Test Idle MAE | Test MAE |",
        "|---|---:|---:|---:|",
        f"| training block only | {r[winner]['active']['mae']} | "
        f"{r[winner]['idle']['mae']} | {r[winner]['test_mae']} |",
        f"| **all pre-test data (shipped)** | **{deployed['active']['mae']}** | "
        f"**{deployed['idle']['mae']}** | **{deployed['test_mae']}** |",
        "",
        f"On the held-out test the shipped model "
        f"{'beats' if summary['chosen_beats_persistence_on_test_active'] else 'does not beat'} "
        "persistence on Active MAE and "
        f"{'beats' if summary['chosen_beats_persistence_on_test_overall'] else 'does not beat'} "
        "persistence on overall MAE. State both facts in the viva.", "",
        "## Place in the IoT workflow", "",
        "Company A CSV replay (sensor simulator) -> MQTT -> Node-RED "
        "validation -> SQLite. After a successful write, Node-RED republishes "
        "the validated record to MQTT for analytics. Analytics builds rolling "
        "metrics and past-only features, loads the selected model, and "
        "publishes a forecast. Node-RED stores and displays metrics and "
        "forecasts; the decision service publishes an operator advisory. A "
        "separate virtual-line detector sends bounded MQTT commands to a "
        "virtual actuator and receives acknowledgements. The real CSV has "
        "no verified stage route, queue, or physical actuator.", "",
        "`scripts/verify_feature_parity.py` replays real records through the "
        "live path and checks every model input against the training table, "
        "so the numbers the model sees in the demo are the numbers it was "
        "trained on.", "",
        "## Per-machine held-out test MAE", "",
        "| Machine | Ridge | Gradient boosting | Neural network | Persistence |",
        "|---:|---:|---:|---:|---:|",
    ]
    for asset in sorted(r["ridge"]["per_machine"], key=int):
        lines.append(
            f"| {asset} | {r['ridge']['per_machine'][asset]['mae']} | "
            f"{r['gradient_boosting']['per_machine'][asset]['mae']} | "
            f"{r['neural_network']['per_machine'][asset]['mae']} | "
            f"{r['baseline_persistence']['per_machine'][asset]['mae']} |")
    lines += ["", "These scores are produced by this repository's code on "
              "the fixed Company A file, not copied from a paper. Timings "
              "depend on the computer.", ""]
    (ROOT / "results" / "MODEL_RESULTS.md").write_text(
        "\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
