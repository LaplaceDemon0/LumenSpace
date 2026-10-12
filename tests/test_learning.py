import numpy as np
import pandas as pd
import pytest

from terminal.data import demo_data, windows
from terminal.learning import build_examples, train
from terminal.transforms import metrics


def test_future_changes_cannot_change_past_features():
    df, _ = demo_data(180)
    altered = df.copy()
    altered.loc[100:, ["open", "high", "low", "close"]] *= 2
    for module in ["phase", "recurrence", "wavelet", "fourier", "laplace", "topology"]:
        before = [
            metrics(g, [module])
            for end, g in windows(df, 14, "rolling")
            if end <= df.time.iloc[100]
        ]
        after = [
            metrics(g, [module])
            for end, g in windows(altered, 14, "rolling")
            if end <= df.time.iloc[100]
        ]
        assert before == after


def test_targets_and_purge():
    df, _ = demo_data(1200)
    X, y, ranges, starts, ends, _ = build_examples(df, 14, "rolling", ["fourier"], "UTC")
    assert len(X) == len(df) - 27
    assert ends[0] == starts[0] + pd.Timedelta(minutes=28)
    assert y[0] == int(df.close.iloc[27] > df.open.iloc[14])
    assert ranges[0] == df.high.iloc[14:28].max() - df.low.iloc[14:28].min()
    cutoff = int(len(X) * 0.8)
    kept = [i for i in range(cutoff) if ends[i] <= starts[cutoff]]
    assert all(ends[i] <= starts[cutoff] for i in kept)
    assert len(kept) <= cutoff - 27


def test_train_evaluation_and_progress():
    df, _ = demo_data(1600)
    progress = []
    out = train(
        df, 14, "rolling", ["fourier", "wavelet"], "UTC", "linear", lambda n, m: progress.append(n)
    )
    assert progress[-1] == 100
    assert out["purged_examples"] >= 27
    assert 0 <= out["accuracy"] <= 1
    assert len(out["baselines"]) == 4
    assert np.array(out["confusion"]).sum() == out["test_examples"]
    assert out["forecast"]["asof"] == int((df.time.iloc[-1] + pd.Timedelta(minutes=1)).timestamp())
    assert out["forecast"]["until"] - out["forecast"]["asof"] == 840


@pytest.mark.parametrize("horizon", [14, 42])
def test_selected_short_window_forecast_uses_exact_candles_and_cutoff(horizon):
    df, _ = demo_data(4200)
    history = df.iloc[:3901].copy()
    source = history.iloc[-horizon:].copy()
    result = train(
        history,
        horizon,
        "aligned",
        ["wavelet"],
        "America/New_York",
        "linear",
        lambda *_: None,
        forecast_df=source,
    )
    forecast = result["forecast"]
    assert forecast["source_bars"] == horizon
    assert forecast["source_start"] == int(source.time.iloc[0].timestamp())
    assert forecast["source_end"] == int(source.time.iloc[-1].timestamp())
    assert forecast["training_cutoff"] == forecast["source_end"]
    assert forecast["asof"] == forecast["source_end"] + 60
    assert forecast["anchor"] == source.close.iloc[-1]
    assert forecast["until"] == forecast["asof"] + horizon * 60
