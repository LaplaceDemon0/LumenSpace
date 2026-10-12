"""Explicit learning on exactly one selected window; inference never trains.

Signed potential coefficients are regularized ML regression parameters. A small
fit search learns spatial width, damping and temporal decay rates. The learned
time functions continue forward from the training endpoint, without projecting
or reflecting candle locations. Single-window fit is not out-of-sample skill.
"""

from dataclasses import replace
import hashlib

import numpy as np
import pandas as pd
from scipy.integrate import trapezoid

from .config import Config
from .surface import Surface, Sources
from .initial import LaunchState
from .forecast import Forecast
from .dynamics import simulate
from .windows import bounds, select_window
from .levels.golden_shadow import window_levels, wilder_atr

VERSION = 2


def window_hash(d):
    return hashlib.sha256(
        pd.util.hash_pandas_object(d[["time", "open", "high", "low", "close"]], index=False)
        .to_numpy()
        .tobytes()
    ).hexdigest()


class WindowSurface(Surface):
    def __init__(self, sources, rates, offset=0):
        super().__init__(sources, 1.0)
        self.rates = np.asarray(rates, dtype=float)
        self.offset = float(offset)

    def components(self, x, y):
        x, y = np.broadcast_arrays(np.asarray(x, dtype=float), np.asarray(y, dtype=float))
        s = self.sources
        dy = y[..., None] - s.y
        t = np.maximum(0, x[..., None] + self.offset)
        safe = np.where(self.rates > 0, self.rates, 1.0)
        time = np.where(self.rates > 0, np.exp(-t / safe), 1.0)
        return s.A * time * np.exp(-0.5 * (dy / s.sy) ** 2), dy


def _sources(level, origin, scale, settings, T):
    r = level["rung"]
    indices = [max(1, round(r / 2)), max(1, r), min(84, max(1, round(1.5 * r)))]
    prices = [level["origin"]]
    for j in indices:
        prices.extend([level["ladder"][j]["down"], level["ladder"][j]["up"]])
    centers = np.repeat((np.asarray(prices) - origin) / scale, 3)
    rates = np.tile([0.0, settings["fast"], settings["slow"]], len(prices))
    count = len(centers)
    sources = Sources(
        -np.arange(1, count + 1),
        np.zeros(count),
        centers,
        np.ones(count),
        np.where(rates > 0, rates, max(T, 1.0)),
        np.full(count, settings["width"]),
        np.zeros(count),
        "causal",
    )
    return sources, rates


def _fit(d, level, scale, settings):
    T = len(d) - 1
    origin = float(d.close.iloc[0])
    target = (d.close.iloc[1:].to_numpy() - origin) / scale
    sources, rates = _sources(level, origin, scale, settings, T)
    surface = WindowSurface(sources, rates)
    t = np.linspace(0, T, T * 4 + 1)
    actual = np.interp(t, np.arange(T + 1), np.r_[0.0, target])
    forces = surface.force_parts(t, actual)
    c, tau = settings["damping"], settings["tau"]
    rows = []
    for j in range(1, T + 1):
        stop = j * 4 + 1
        lag = j - t[:stop]
        kernel = -np.expm1(-c * lag) / c
        rows.append(
            np.r_[
                trapezoid(kernel[:, None] * forces[:stop], t[:stop], axis=0),
                -np.expm1(-c * j) / c,
                trapezoid(kernel * np.exp(-t[:stop] / tau), t[:stop]),
            ]
        )
    X = np.asarray(rows)
    v = (float(d.close.iloc[1]) - origin) / scale
    prior_v = np.r_[np.zeros(len(sources.x)), 1.0, 0.0]
    X = np.vstack([X, 0.5 * prior_v])
    target = np.r_[target, 0.5 * v]
    penalty = np.r_[np.full(len(sources.x), settings["regularization"]), 0.1, 0.1]
    coef = np.linalg.solve(X.T @ X + np.diag(penalty), X.T @ target)
    surface = WindowSurface(replace(sources, A=coef[:-2]), rates)
    launch = LaunchState(
        origin,
        scale,
        float(coef[-2]),
        float(surface.force(0, 0) - c * coef[-2] + coef[-1]),
        float(coef[-1]),
    )
    cfg = replace(
        Config(), horizon=T, coupling=1.0, damping=c, tau=tau, projection="none", max_step=0.5
    )
    tr = simulate(surface, launch, cfg)
    pred = np.interp(np.arange(1, T + 1), tr.x, tr.y)
    truth = (d.close.iloc[1:].to_numpy() - origin) / scale
    mse = float(np.mean((pred - truth) ** 2))
    score = mse + 0.001 * float(np.mean(coef[:-2] ** 2))
    return score, coef, tr, mse


def learn_selected_window(
    selected, interval=42, quantum=0.25, mintick=0.01, progress=None, cancel=None
):
    """The worker receives only the selected rows, not a full CSV or earlier data."""

    def update(value, message):
        if cancel is not None and cancel.is_set():
            raise InterruptedError("Learning cancelled")
        if progress is not None:
            progress(value, message)

    d = selected.copy().reset_index(drop=True)
    d["time"] = pd.to_datetime(d.time, utc=True)
    update(2, "Checking selected window")
    if len(d) < 3:
        raise ValueError("Choose a complete window containing at least three M1 candles")
    w = select_window(d, 0, interval, 1)
    if not w.complete or w.first != 0 or w.last != len(d) - 1:
        raise ValueError(
            "Learning needs exactly one complete selected New York window; gaps are not compressed"
        )
    scale = float((d.high - d.low).mean())
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("Selected window has zero or invalid price range")
    period = min(14, len(d))
    level = window_levels(d, w, wilder_atr(d, period), quantum, mintick)
    level["atr_period"] = period
    level["atr_scope"] = "selected window only"
    update(10, "GoldenShadow levels calculated from selected candles only")
    T = len(d) - 1
    candidates = [
        {
            "width": width,
            "damping": damping,
            "fast": max(1.0, T * rate),
            "slow": max(2.0, T * rate * 3),
            "tau": max(1.0, T * rate),
            "regularization": 1.0,
        }
        for width in (0.7, 1.5)
        for damping in (0.15, 0.5)
        for rate in (0.25, 0.5)
    ]
    best = None
    trials = []
    for i, settings in enumerate(candidates):
        update(
            10 + int(70 * i / len(candidates)),
            f"Learning potential and motion · candidate {i + 1}/{len(candidates)}",
        )
        score, coef, tr, mse = _fit(d, level, scale, settings)
        trials.append({"settings": settings, "fit_rmse_S": float(np.sqrt(mse))})
        if best is None or score < best[0]:
            best = (score, coef, tr, mse, settings)
    update(82, "Selecting learned dynamics and building future surface")
    _, coef, tr, mse, settings = best
    model = {
        "version": VERSION,
        "method": "selected-window-potential-regression",
        "interval": interval,
        "start": w.start.isoformat(),
        "end": w.end.isoformat(),
        "first_time": d.time.iloc[0].isoformat(),
        "last_time": d.time.iloc[-1].isoformat(),
        "window_hash": window_hash(d),
        "rows": len(d),
        "scale": scale,
        "duration": T,
        "settings": settings,
        "coefficients": coef[:-2].tolist(),
        "endpoint_velocity": float(tr.velocity.iloc[-1]),
        "endpoint_q": float(tr.q.iloc[-1]),
        "endpoint_acceleration": float(tr.acceleration.iloc[-1]),
        "endpoint_fit_error_S": float(tr.y.iloc[-1] - (d.close.iloc[-1] - d.close.iloc[0]) / scale),
        "level": {
            k: (v.isoformat() if isinstance(v, pd.Timestamp) else v) for k, v in level.items()
        },
        "report": {
            "scope": "selected window only",
            "training_candles": len(d),
            "training_transitions": T,
            "start": w.start.isoformat(),
            "end": w.end.isoformat(),
            "fit_rmse_S": float(np.sqrt(mse)),
            "fit_price_rmse": float(np.sqrt(mse) * scale),
            "selected_settings": settings,
            "trials": trials,
            "atr_period": period,
            "note": "In-sample learning fit only. No independent test or calibrated uncertainty. One learned level potential spans past and future. Launch uses the observed last close, fitted endpoint velocity/acceleration, and memory conditioned on that price; no candle projection.",
        },
    }
    # Complete the job only after the future simulation succeeds too.
    update(90, "Simulating learned future price, Y speed and acceleration")
    selected_forecast(d, model)
    update(98, "Forecast ready; preparing result")
    return model


def model_matches(selected, model, interval, quantum, mintick):
    return bool(
        model
        and model.get("version") == VERSION
        and model.get("interval") == interval
        and model.get("level", {}).get("quantum") == quantum
        and model.get("level", {}).get("mintick") == mintick
        and window_hash(selected) == model.get("window_hash")
    )


def selected_forecast(df, model):
    """Rebuild a forecast with a learned model. Never starts learning."""
    times = pd.to_datetime(df.time, utc=True)
    ids = np.flatnonzero(
        (times >= pd.Timestamp(model["start"])) & (times < pd.Timestamp(model["end"]))
    )
    if not len(ids):
        raise ValueError("Learned window is absent from this dataset")
    d = df.iloc[ids].copy().reset_index(drop=True)
    if not model_matches(
        d, model, model["interval"], model["level"]["quantum"], model["level"]["mintick"]
    ):
        raise ValueError("Selected candles changed; click Start learning again")
    level = dict(model["level"])
    for name in ("start", "previous_start"):
        level[name] = pd.Timestamp(level[name])
    level["launch"] = int(ids[-1])
    p = float(d.close.iloc[-1])
    scale = model["scale"]
    settings = model["settings"]
    sources, rates = _sources(level, p, scale, settings, model["duration"])
    sources = replace(
        sources,
        A=np.asarray(model["coefficients"]),
        x=np.full(len(sources.x), -float(model["duration"])),
    )
    surface = WindowSurface(sources, rates, model["duration"])
    start, end = bounds(pd.Timestamp(model["end"]), model["interval"])
    horizon = max(1, int((end - start).total_seconds() // 60))
    cfg = replace(
        Config(),
        lookback=len(d),
        horizon=horizon,
        coupling=1.0,
        damping=settings["damping"],
        tau=settings["tau"],
        projection="none",
        price_mirror=False,
        background_k=0.0,
    )
    v = model["endpoint_velocity"]
    # Condition memory on the observed final close. Carrying q unchanged from
    # the fitted (possibly different) price silently changes acceleration.
    # This correction uses only the selected window and preserves fitted v/a.
    q = float(model["endpoint_acceleration"] - surface.force(0, 0) + cfg.damping * v)
    launch = LaunchState(p, scale, v, float(surface.force(0, 0) - cfg.damping * v + q), q)
    tr = simulate(surface, launch, cfg)
    tr["time"] = d.time.iloc[-1] + pd.to_timedelta(tr.x, unit="min")
    global_ids = ids.astype(int)
    historical = Sources(
        global_ids,
        global_ids.astype(float) - ids[-1],
        (d.close.to_numpy() - p) / scale,
        np.full(len(d), 3 / len(d)),
        np.full(len(d), 4.0),
        np.full(len(d), 2.0),
        ids[-1] - global_ids,
    )
    f = Forecast(int(ids[-1]), cfg, launch, historical, surface, tr, "prediction", len(sources.x))
    f.ml_report = model["report"]
    f.golden_level = level
    f.window_model = model
    # One learned potential for both sides of x=0. Historical candle kernels
    # remain available as data attribution, but are not spliced into this field.
    f.historical_surface = surface
    return f
