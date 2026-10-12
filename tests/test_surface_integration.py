import numpy as np
import pandas as pd
import pytest

from terminal.data import demo_data
from terminal.surface_bridge import (
    checked_history,
    explicit_window,
    fit_parameters,
    learn_surface,
    levels_for_selection,
    make_config,
    selected_rows,
    simulate_selection,
)
from terminal._vendor.csim.forecast import run_forecast
from terminal._vendor.csim.levels.golden_shadow import window_levels, wilder_atr


@pytest.fixture
def case():
    d, _ = demo_data(400)
    d["time"] = pd.date_range(
        "2025-02-04", periods=400, freq="min", tz="America/New_York"
    ).tz_convert("UTC")
    a, b = int(d.time.iloc[84].timestamp()), int(d.time.iloc[97].timestamp())
    return d, a, b


def test_surface_source_is_exact_selected_window_and_future_invariant(case):
    d, a, b = case
    request = (a, b, 14, "aligned", 8, {}, 0.25, 0.01)
    result = simulate_selection(d, *request)
    assert [s["candle"] for s in result["sources"]] == list(range(84, 98))
    assert result["asof"] == b + 60
    assert result["trajectory"]["price"][0] == d.close.iloc[97]
    assert result["trajectory"]["time"][-1] == b + 60 + 8 * 60
    changed = d.copy()
    changed.loc[98:, ["open", "high", "low", "close"]] += 1000
    altered = simulate_selection(changed, *request)
    assert result["trajectory"] == altered["trajectory"]
    assert result["grid"] == altered["grid"]
    assert result["levels"] == altered["levels"]


def test_parameters_change_scenario_and_do_not_train(case, monkeypatch):
    import terminal._vendor.csim.surface_learning as learning

    monkeypatch.setattr(
        learning, "learn_selected_window", lambda *args, **kw: pytest.fail("Automatic ML training")
    )
    d, a, b = case
    original = simulate_selection(d, a, b, 14, "aligned", 8, {}, 0.25, 0.01)
    changed = simulate_selection(
        d, a, b, 14, "aligned", 8, {"push": 0.2, "throw": 0.3, "dent_scale": 2}, 0.25, 0.01
    )
    assert not np.allclose(original["trajectory"]["price"], changed["trajectory"]["price"])
    np.testing.assert_allclose(
        np.array([s["strength"] for s in changed["sources"]]),
        2 * np.array([s["strength"] for s in original["sources"]]),
    )


def test_original_golden_formula_and_85_rungs(case):
    d, a, b = case
    got = levels_for_selection(d, a, b, 14, "aligned", 0.25, 0.01)
    hist, g, f, last = selected_rows(d, a, b, 14, "aligned")
    expected = window_levels(hist, explicit_window(hist, g, f, last), wilder_atr(hist), 0.25, 0.01)
    assert got == expected
    assert len(got["ladder"]) == 85
    assert got["up"] == got["ladder"][got["rung"]]["up"]
    assert got["down"] == got["ladder"][got["rung"]]["down"]
    assert got["mu"] == got["rung"] * 0.25


def test_missing_candles_and_incompatible_source_rejected(case):
    d, a, b = case
    with pytest.raises(ValueError, match="missing bars"):
        simulate_selection(d.drop(index=90), a, b, 14, "aligned", 8, {}, 0.25, 0.01)
    with pytest.raises(ValueError, match="M1"):
        checked_history(d.iloc[::5])


def test_learning_receives_only_marked_rows_and_never_ball_state(case, monkeypatch):
    d, a, b = case
    import terminal._vendor.csim.dynamics as dynamics
    import terminal._vendor.csim.initial as initial

    monkeypatch.setattr(
        dynamics,
        "simulate",
        lambda *args, **kw: pytest.fail("Surface ML must not fit a price path"),
    )
    monkeypatch.setattr(
        initial,
        "initial_state",
        lambda *args, **kw: pytest.fail("Surface ML must not learn launch dynamics"),
    )
    progress = []
    model = learn_surface(d, a, b, 14, "aligned", 0.25, 0.01, lambda n, m: progress.append(n))
    assert model["rows"] == 14
    assert model["report"]["training_candles"] == 14
    assert model["start"] == d.time.iloc[84].tz_convert("America/New_York").isoformat()
    assert not {"push", "throw", "damping", "tau"} & model["settings"].keys()
    assert progress[-1] == 98


def test_optional_ml_keeps_physics_and_continuous_boundary(case):
    d, a, b = case
    model = learn_surface(d, a, b, 14, "aligned", 0.25, 0.01, lambda *_: None)
    hist, g, _, n = selected_rows(d, a, b, 14, "aligned")
    cfg = make_config({}, len(g), 8)
    plain = run_forecast(hist, n, cfg)
    ml = run_forecast(hist, n, cfg, future_surface_model=model)
    assert ml.config == plain.config
    assert ml.launch.v0 == plain.launch.v0
    assert ml.launch.a0 == plain.launch.a0
    np.testing.assert_array_equal(plain.historical.A, ml.historical.A)
    y = np.linspace(-3, 3, 15)
    eps = 1e-6
    for attr in ("z", "force", "curvature"):
        fn = getattr(ml.surface, attr)
        np.testing.assert_allclose(fn(-eps, y), fn(eps, y), atol=1e-5)
    assert ml.surface.force(3, 0.7) == pytest.approx(
        -cfg.coupling * (ml.surface.z(3, 0.7 + eps) - ml.surface.z(3, 0.7 - eps)) / (2 * eps),
        rel=1e-5,
    )


def test_fit_paths_end_before_selected_launch(case):
    d, a, b = case
    progress = []
    result = fit_parameters(
        d, a, b, 14, "aligned", 4, {}, 2, ["push"], lambda n, m: progress.append(n)
    )
    assert progress[-1] == 100
    assert result["after_rmse"] <= result["before_rmse"] + 1e-8
    assert all(t + 4 * 60 <= b for t in result["calibration_launch_times"])
    assert result["holdout"] is not None
