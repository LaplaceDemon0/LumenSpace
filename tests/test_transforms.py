import numpy as np
import pytest

from terminal.data import demo_data
from terminal.transforms import MODULES, compute, embed, metrics, rqa


def test_embedding_alignment():
    embedded = embed(np.arange(10), tau=2, m=3)
    assert embedded[0].tolist() == [0, 2, 4]
    assert embedded[-1].tolist() == [5, 7, 9]
    df, _ = demo_data(14)
    out = compute(df, "phase", {"tau": 2, "dimension": 3})
    assert len(out["points"]) == len(out["point_times"]) == 10
    assert out["point_times"][0] == int(df.time.iloc[4].timestamp())


@pytest.mark.parametrize("module", list(MODULES))
def test_all_transforms_finite(module):
    df, _ = demo_data(42)
    out = compute(df, module, {})
    assert all(np.isfinite(v) for v in out["metrics"].values())
    if "z" in out:
        assert np.isfinite(out["z"]).all()


def test_constant_and_recurrence():
    df, _ = demo_data(14)
    df["close"] = 10
    assert all(np.isfinite(v) for v in metrics(df).values())
    m = rqa(np.ones((6, 6), dtype=bool))
    assert m["Recurrence rate"] == 1
    assert 0 <= m["Determinism"] <= 1


def test_limits_and_invalid_log():
    df, _ = demo_data(600)
    with pytest.raises(ValueError, match="512"):
        compute(df, "recurrence", {})
    df = df.iloc[:14].copy()
    df["close"] = -1
    with pytest.raises(ValueError, match="positive"):
        compute(df, "fourier", {"preprocessing": "log"})


def test_recurrence_levels_map_rows_to_exact_source_candles():
    df, _ = demo_data(42)
    out = compute(df, "recurrence", {"tau": 2, "dimension": 3})
    matrix = np.array(out["z"])
    assert len(out["row_scores"]) == 38
    for row in out["row_scores"]:
        i = row["row"]
        candle = df.iloc[i + 4]
        assert row["count"] == int(matrix[i].sum()) - 1
        assert row["density"] == pytest.approx(row["count"] / 37)
        assert row["time"] == int(candle.time.timestamp())
        assert (row["low"], row["high"], row["close"]) == (candle.low, candle.high, candle.close)
    levels = out["potential_levels"]
    assert 0 < len(levels) <= 5
    assert levels[0]["count"] == max(row["count"] for row in out["row_scores"])
    assert all(abs(a["row"] - b["row"]) >= 3 for i, a in enumerate(levels) for b in levels[i + 1 :])
    assert all(a["count"] >= b["count"] for a, b in zip(levels, levels[1:]))


def test_constant_recurrence_excludes_self_matches_and_ties_are_stable():
    df, _ = demo_data(14)
    df["close"] = 10.0
    out = compute(df, "recurrence", {})
    assert all(row["count"] == 11 for row in out["row_scores"])
    assert all(row["density"] == 1.0 for row in out["row_scores"])
    assert [row["row"] for row in out["potential_levels"]] == [0, 3, 6, 9]
