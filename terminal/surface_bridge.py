"""LumenSpace adapters around the existing candle-surface engine, not a replacement model."""

from dataclasses import replace

import numpy as np
import pandas as pd

from ._vendor.csim.config import Config, Rules
from ._vendor.csim.fitting import fit_launch
from ._vendor.csim.forecast import run_forecast
from ._vendor.csim.levels.golden_shadow import window_levels, wilder_atr
from ._vendor.csim.surface import Surface
from ._vendor.csim.surface_learning import learn_selected_window
from ._vendor.csim.windows import TimeWindow, list_windows, select_window

PARAMETERS = {
    "push",
    "throw",
    "coupling",
    "damping",
    "dent_scale",
    "depth",
    "sigma_x",
    "sigma_y",
    "tau",
    "strength",
    "projection",
    "anchor",
    "kernel",
    "background_k",
    "ring_weight",
    "initial_estimator",
    "price_mirror",
    "scale_factor",
    "scale_beta",
    "rules",
}


def checked_history(df):
    d = df.loc[df.closed].copy().reset_index(drop=True)
    if len(d) < 25:
        raise ValueError("Load at least 25 closed M1 bars, including earlier volatility history.")
    step = d.time.diff().dt.total_seconds().dropna().mode().iloc[0]
    if step != 60:
        raise ValueError("Surface and GoldenShadow use M1 source bars. Load M1 history.")
    return d


def selected_rows(df, start=None, end=None, minutes=42, mode="aligned"):
    """Internal endpoints are source candle opens, inclusive. Chart labels show the end close."""
    d = checked_history(df)
    if start is None:
        if mode == "rolling":
            ids = d.index[-minutes:]
        else:
            candidates = [
                w for w in list_windows(d, minutes) if w["complete"] and w["expected"] == minutes
            ]
            if not candidates:
                raise ValueError("No complete selected NY window is available.")
            row = candidates[-1]
            ids = d.index[row["first"] : row["last"] + 1]
    else:
        if end is None:
            raise ValueError("A selected window needs a start and end.")
        ids = d.index[
            (d.time >= pd.Timestamp(start, unit="s", tz="UTC"))
            & (d.time <= pd.Timestamp(end, unit="s", tz="UTC"))
        ]
    if not 6 <= len(ids) <= 512:
        raise ValueError("Select 6–512 closed M1 bars for a surface/transform window.")
    first, last = int(ids[0]), int(ids[-1])
    if start is not None and (
        int(d.time.iloc[first].timestamp()) != start or int(d.time.iloc[last].timestamp()) != end
    ):
        raise ValueError("Selected endpoints must match available closed M1 candle opens.")
    g = d.iloc[first : last + 1]
    if not (g.time.diff().dropna().dt.total_seconds() == 60).all():
        raise ValueError("The selected window contains missing bars. Select a contiguous period.")
    if last < 20:
        raise ValueError("Choose a later window: launch scaling requires earlier history.")
    # Historical data is cut at the selected end. Future rows never reach the engine.
    d = d.iloc[: last + 1].copy()
    return d, g, first, last


def make_config(parameters, size, horizon):
    unknown = set(parameters) - PARAMETERS
    if unknown:
        raise ValueError("Unknown surface parameters: " + ", ".join(sorted(unknown)))
    values = dict(parameters)
    if "rules" in values:
        values["rules"] = Rules(**values["rules"])
    cfg = replace(
        Config(),
        **values,
        lookback=size - 1,
        include_launch=True,
        horizon=horizon,
        max_sources=512,
        samples_per_bar=3,
        bar_minutes=1,
    )
    cfg.validate()
    return cfg


def explicit_window(d, g, first, last):
    start = g.time.iloc[0].tz_convert("America/New_York")
    return TimeWindow(start, g.time.iloc[-1] + pd.Timedelta(minutes=1), first, last, len(g), True)


def levels_for_selection(df, start, end, minutes, mode, quantum, mintick):
    d, g, first, last = selected_rows(df, start, end, minutes, mode)
    level = window_levels(d, explicit_window(d, g, first, last), quantum=quantum, mintick=mintick)
    return level


def serialize_level(level, horizon):
    obj = {k: (int(v.timestamp()) if isinstance(v, pd.Timestamp) else v) for k, v in level.items()}
    obj["end"] = obj["start"] + horizon * 60
    return obj


def history_levels(df, minutes=42, quantum=0.25, mintick=0.01, limit=80):
    d = checked_history(df)
    atr = wilder_atr(d)
    output = []
    for row in list_windows(d, minutes)[-limit * 2 :]:
        if not row["complete"] or row["expected"] != minutes or row["last"] < 13:
            continue
        w = select_window(d, row["first"], minutes)
        level = window_levels(d, w, atr, quantum, mintick)
        output.append(serialize_level(level, minutes))
    return output[-limit:]


def simulate_selection(
    df, start, end, minutes, mode, horizon, parameters, quantum, mintick, model=None
):
    d, g, first, last = selected_rows(df, start, end, minutes, mode)
    cfg = make_config(parameters, len(g), horizon)
    forecast = run_forecast(d, last, cfg, future_surface_model=model)
    level = window_levels(d, explicit_window(d, g, first, last), quantum=quantum, mintick=mintick)
    anchor = float(forecast.launch.price)
    scale = float(forecast.launch.scale)
    asof = int((g.time.iloc[-1] + pd.Timedelta(minutes=1)).timestamp())
    source_prices = forecast.historical.y
    ymin = min(
        float(source_prices.min()) - 3 if len(source_prices) else -3,
        float(forecast.trajectory.y.min()) - 2,
    )
    ymax = max(
        float(source_prices.max()) + 3 if len(source_prices) else 3,
        float(forecast.trajectory.y.max()) + 2,
    )
    # Bound the grid, never trim or rescale the numerical trajectory itself.
    ys = np.linspace(ymin, ymax, 64)
    xs = np.linspace(-(len(g) - 1), horizon, 100)
    X, Y = np.meshgrid(xs, ys)
    past = getattr(
        forecast,
        "historical_surface",
        Surface(forecast.historical, cfg.coupling, cfg.background_k, forecast.surface.background_y),
    )
    Z = np.where(X <= 0, past.z(X, Y), forecast.surface.z(X, Y))
    if not np.isfinite(Z).all():
        raise ValueError("Surface grid is nonfinite. Reduce extreme parameter values.")
    t = forecast.trajectory
    trajectory = {
        "time": (asof + t.x.to_numpy() * 60).tolist(),
        "price": t.price.tolist(),
        "z": t.Z.tolist(),
        "velocity": t.velocity.tolist(),
        "acceleration": t.acceleration.tolist(),
    }
    return {
        "method": "original-physics-with-ml-surface" if model else "original-physics",
        "source_start": int(g.time.iloc[0].timestamp()),
        "source_end": asof,
        "source_bars": len(g),
        "asof": asof,
        "until": asof + horizon * 60,
        "grid": {
            "time": (asof + xs * 60).tolist(),
            "price": (anchor + scale * ys).tolist(),
            "z": Z.tolist(),
        },
        "trajectory": trajectory,
        "levels": serialize_level(level, horizon),
        "parameters": cfg.to_dict(),
        "sources": forecast.historical.table(anchor, scale).to_dict("records"),
        "metrics": {
            "Source candles": len(forecast.historical.x),
            "Launch scale": scale,
            "End price": float(t.price.iloc[-1]),
        },
        "notes": [
            "Simulation is a model scenario, not a validated price forecast.",
            "Surface source candles are restricted to the marked window. Earlier data supplies launch volatility/velocity and ATR only.",
        ],
        "ml_report": model["report"] if model else None,
    }


def fit_parameters(df, start, end, minutes, mode, horizon, parameters, count, free, progress):
    d, g, _, last = selected_rows(df, start, end, minutes, mode)
    cfg = make_config(parameters, len(g), horizon)
    progress(5, "Selecting completed calibration paths ending before the selected launch")
    # The original fitter sees only data up to this launch; fitted paths have known outcomes.
    fit = fit_launch(d, cfg, last - horizon, windows=count, free=tuple(free), progress=progress)
    progress(100, "Parameters fitted; click Apply parameters & simulate to use them")
    return {
        "kind": "surface-fit",
        "parameters": fit.params,
        "free": list(fit.free),
        "before_rmse": fit.before,
        "after_rmse": fit.after,
        "flat_rmse": fit.flat,
        "price_before_rmse": fit.price_before,
        "price_after_rmse": fit.price_after,
        "per_window": fit.per_window,
        "holdout": fit.holdout,
        "calibration_launch_times": [int(d.time.iloc[n].timestamp()) for n in fit.launches],
        "selected_start": int(g.time.iloc[0].timestamp()),
        "selected_end": int(g.time.iloc[-1].timestamp()),
        "note": "Calibration uses completed earlier paths. In-sample fitting error is not forecast skill; the newest calibration holdout uses older calibration windows only.",
    }


def learn_surface(df, start, end, minutes, mode, quantum, mintick, progress):
    _, g, _, _ = selected_rows(df, start, end, minutes, mode)
    # Deliberately pass only the marked candles, never the full source history.
    model = learn_selected_window(g.copy(), minutes, quantum, mintick, progress=progress)
    return model
