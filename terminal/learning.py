"""Manual training with chronological purging and a held-out final test."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier, ExtraTreesRegressor
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import accuracy_score, brier_score_loss, confusion_matrix, mean_absolute_error
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .data import windows
from .transforms import metrics


def build_examples(df, horizon, mode, selected, timezone, progress=lambda *_: None):
    groups = windows(df, horizon, mode, timezone)
    by_start = {g.time.iloc[0]: (end, g) for end, g in groups}
    rows, labels, ranges, starts, ends = [], [], [], [], []
    for i, (end, group) in enumerate(groups):
        nxt = by_start.get(end)
        if nxt is None:
            continue
        target_end, target = nxt
        feat = metrics(group, selected)
        if horizon == 42 and len(group) >= 42:
            for j in range(3):
                sub = metrics(group.iloc[j * 14 : (j + 1) * 14], selected)
                feat.update({f"third_{j + 1}_{k}": v for k, v in sub.items()})
        rows.append(feat)
        labels.append(int(target.close.iloc[-1] > target.open.iloc[0]))
        ranges.append(float(target.high.max() - target.low.min()))
        starts.append(group.time.iloc[0])
        ends.append(target_end)
        if i % 20 == 0:
            progress(5 + int(45 * i / max(len(groups), 1)), "Extracting causal window features")
    if len(rows) < 60:
        raise ValueError(
            f"Only {len(rows)} complete examples. Need at least 60; load more data or use rolling mode."
        )
    return pd.DataFrame(rows), np.array(labels), np.array(ranges), starts, ends, groups


def estimators(name):
    if name == "linear":
        return (
            make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000, random_state=7)),
            make_pipeline(StandardScaler(), Ridge(alpha=1)),
        )
    return (
        ExtraTreesClassifier(
            n_estimators=150, max_depth=6, min_samples_leaf=5, random_state=7, n_jobs=2
        ),
        ExtraTreesRegressor(
            n_estimators=150, max_depth=6, min_samples_leaf=5, random_state=7, n_jobs=2
        ),
    )


def probability(model, X):
    p = model.predict_proba(X)
    classes = model.classes_
    return p[:, list(classes).index(1)] if 1 in classes else np.zeros(len(X))


def block_interval(correct, block):
    rng = np.random.default_rng(19)
    n = len(correct)
    values = []
    block = min(block, n)
    for _ in range(500):
        starts = rng.integers(0, n, size=int(np.ceil(n / block)))
        idx = np.concatenate([(s + np.arange(block)) % n for s in starts])[:n]
        values.append(float(np.mean(correct[idx])))
    return np.quantile(values, [0.025, 0.975]).tolist()


def train(df, horizon, mode, selected, timezone, name, progress, forecast_df=None):
    X, y, ranges, starts, ends, groups = build_examples(
        df, horizon, mode, selected, timezone, progress
    )
    n = len(X)
    cutoff = int(n * 0.8)
    test_idx = np.arange(cutoff, n)
    fit_idx = np.array([i for i in range(cutoff) if ends[i] <= starts[cutoff]])
    if len(fit_idx) < 25 or len(np.unique(y[fit_idx])) < 2:
        raise ValueError(
            "Insufficient class diversity after purging. Expand the selected training range."
        )
    progress(55, "Walk-forward validation")
    folds = []
    for split in [0.4, 0.55, 0.7]:
        v0, v1 = int(cutoff * split), min(int(cutoff * (split + 0.15)), cutoff)
        tr = np.array([i for i in range(v0) if ends[i] <= starts[v0]])
        va = np.arange(v0, v1)
        if len(tr) < 15 or len(np.unique(y[tr])) < 2 or not len(va):
            continue
        model, _ = estimators(name)
        model.fit(X.iloc[tr], y[tr])
        folds.append(
            {
                "train_examples": len(tr),
                "validation_examples": len(va),
                "accuracy": float(accuracy_score(y[va], probability(model, X.iloc[va]) >= 0.5)),
            }
        )
    progress(72, "Fitting development model; final test remains held out")
    clf, reg = estimators(name)
    clf.fit(X.iloc[fit_idx], y[fit_idx])
    reg.fit(X.iloc[fit_idx], ranges[fit_idx])
    base, _ = estimators(name)
    base_cols = ["return", "range", "volatility"]
    base.fit(X.iloc[fit_idx][base_cols], y[fit_idx])
    progress(88, "Evaluating final test and probability calibration")
    p = probability(clf, X.iloc[test_idx])
    pred = (p >= 0.5).astype(int)
    truth = y[test_idx]
    correct = pred == truth
    block = horizon if mode == "rolling" else 3
    ci = block_interval(correct, block)
    previous = (X.iloc[test_idx]["return"].to_numpy() > 0).astype(int)
    baseline_pred = (probability(base, X.iloc[test_idx][base_cols]) >= 0.5).astype(int)
    random_pred = np.random.default_rng(7).integers(0, 2, len(truth))
    accuracy = float(correct.mean())
    baseline = {
        "Random (seed 7)": float(accuracy_score(truth, random_pred)),
        "Previous direction": float(accuracy_score(truth, previous)),
        "No transforms": float(accuracy_score(truth, baseline_pred)),
        "Majority training class": float(
            accuracy_score(truth, np.full(len(truth), int(y[fit_idx].mean() >= 0.5)))
        ),
    }
    calibration = []
    for lo in np.arange(0, 1, 0.2):
        mask = (p >= lo) & (p < (lo + 0.2) if lo < 0.8 else p <= 1)
        if mask.any():
            calibration.append(
                {
                    "predicted": float(p[mask].mean()),
                    "observed": float(truth[mask].mean()),
                    "n": int(mask.sum()),
                }
            )
    # Latest forecast never uses a forming bar, and only uses the captured run snapshot.
    asof, last = groups[-1]
    if forecast_df is not None:
        last = forecast_df.copy()
        if len(last) != horizon or not last.time.diff().dropna().eq(pd.Timedelta(minutes=1)).all():
            raise ValueError(
                "Forecast source must contain exactly the chosen number of consecutive M1 candles."
            )
        asof = last.time.iloc[-1] + pd.Timedelta(minutes=1)
        if df.time.iloc[-1] > last.time.iloc[-1]:
            raise ValueError("Training history must stop at the forecast source cutoff.")
    latest = metrics(last, selected)
    if horizon == 42 and len(last) >= 42:
        for j in range(3):
            latest.update(
                {
                    f"third_{j + 1}_{k}": v
                    for k, v in metrics(last.iloc[j * 14 : (j + 1) * 14], selected).items()
                }
            )
    future = pd.DataFrame([latest]).reindex(columns=X.columns)
    up = float(probability(clf, future)[0])
    range_pred = max(0, float(reg.predict(future)[0]))
    importance = getattr(clf, "feature_importances_", None)
    if importance is None:
        importance = abs(clf[-1].coef_[0])
    top = sorted(zip(X.columns, importance.tolist()), key=lambda a: a[1], reverse=True)[:12]
    progress(100, "Training complete")
    return {
        "horizon": horizon,
        "mode": mode,
        "model": name,
        "examples": n,
        "train_examples": len(fit_idx),
        "test_examples": len(test_idx),
        "purged_examples": cutoff - len(fit_idx),
        "accuracy": accuracy,
        "accuracy_interval": ci,
        "baselines": baseline,
        "confusion": confusion_matrix(truth, pred, labels=[0, 1]).tolist(),
        "brier_score": float(brier_score_loss(truth, p)),
        "calibration": calibration,
        "range_mae": float(mean_absolute_error(ranges[test_idx], reg.predict(X.iloc[test_idx]))),
        "range_baseline_mae": float(
            mean_absolute_error(
                ranges[test_idx], np.full(len(test_idx), np.median(ranges[fit_idx]))
            )
        ),
        "folds": folds,
        "importance": [{"feature": k, "importance": v} for k, v in top],
        "forecast": {
            "source_start": int(last.time.iloc[0].timestamp()),
            "source_end": int(last.time.iloc[-1].timestamp()),
            "source_bars": len(last),
            "training_cutoff": int(df.time.iloc[-1].timestamp()),
            "asof": int(asof.timestamp()),
            "until": int((asof + pd.Timedelta(minutes=horizon)).timestamp()),
            "up_probability": up,
            "direction": "Up" if up >= 0.5 else "Down",
            "range": range_pred,
            "anchor": float(last.close.iloc[-1]),
        },
        "assessment": "Research only; superiority is not established from this single run.",
        "interval_method": "500 moving-block bootstrap samples; dependence beyond the block length may remain.",
        "fit_policy": "Final model fitted to development data only; held-out test excluded from fitting.",
    }
