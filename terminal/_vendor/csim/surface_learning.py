"""Optional ML of the future potential only; ball physics remains user controlled."""

from dataclasses import replace
import numpy as np
import pandas as pd

from .surface import Surface, Sources
from .window_learning import WindowSurface, _sources, window_hash
from .windows import select_window
from .levels.golden_shadow import window_levels, wilder_atr

VERSION = 1
METHOD = "golden-shadow-surface-only"


def learn_selected_window(
    selected, interval=42, quantum=0.25, mintick=0.01, progress=None, cancel=None
):
    def update(value, message):
        if cancel is not None and cancel.is_set():
            raise InterruptedError("Learning cancelled")
        if progress is not None:
            progress(value, message)

    d = selected.copy().reset_index(drop=True)
    d["time"] = pd.to_datetime(d.time, utc=True)
    update(2, "Checking selected surface window")
    if len(d) < 3:
        raise ValueError("Choose a complete window with at least three M1 candles")
    w = select_window(d, 0, interval, 1)
    if not w.complete or w.first != 0 or w.last != len(d) - 1:
        raise ValueError("Learning needs exactly one complete selected NY window")
    scale = float((d.high - d.low).mean())
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("Invalid selected price range")
    period = min(14, len(d))
    T = len(d) - 1
    origin = float(d.close.iloc[0])
    level = window_levels(d, w, wilder_atr(d, period), quantum, mintick)
    level["atr_period"] = period
    level["atr_scope"] = "selected window only"
    update(10, "Calculating GoldenShadow basis for surface learning")
    centers = (d.close.to_numpy() - origin) / scale
    observed = Surface(
        Sources(
            np.arange(len(d)),
            np.arange(len(d), dtype=float),
            centers,
            np.full(len(d), 1 / len(d)),
            np.full(len(d), 4.0),
            np.full(len(d), 2.0),
            np.arange(len(d) - 1, -1, -1),
        )
    )
    xs = np.linspace(0, T, T * 2 + 1)
    ys = np.linspace(min(-4.0, centers.min() - 3), max(4.0, centers.max() + 3), 49)
    X, Y = np.meshgrid(xs, ys)
    target = -observed.z(X, Y).ravel()
    best = None
    trials = []
    candidates = [
        {"width": width, "fast": max(1.0, T * rate), "slow": max(2.0, T * rate * 3)}
        for width in (0.7, 1.5, 2.5)
        for rate in (0.25, 0.5)
    ]
    for i, settings in enumerate(candidates):
        update(
            10 + int(70 * i / len(candidates)),
            f"Learning surface kernels · {i + 1}/{len(candidates)}",
        )
        src, rates = _sources(level, origin, scale, settings, T)
        design = WindowSurface(src, rates).components(X, Y)[0].reshape(-1, len(src.x))
        # Ridge regression of potential height, never of projectile state or price.
        coef = np.linalg.solve(design.T @ design + 0.1 * np.eye(len(src.x)), design.T @ target)
        mse = float(np.mean((design @ coef - target) ** 2))
        score = mse + 0.00001 * float(np.mean(coef**2))
        trials.append({"settings": settings, "surface_fit_rmse": float(np.sqrt(mse))})
        if best is None or score < best[0]:
            best = (score, coef, settings, mse)
    update(90, "Preparing learned future surface; physics settings are unchanged")
    _, coef, settings, mse = best
    model = {
        "version": VERSION,
        "method": METHOD,
        "interval": interval,
        "start": w.start.isoformat(),
        "end": w.end.isoformat(),
        "last_time": d.time.iloc[-1].isoformat(),
        "window_hash": window_hash(d),
        "rows": len(d),
        "scale": scale,
        "duration": T,
        "settings": settings,
        "coefficients": coef.tolist(),
        "level": {
            k: (v.isoformat() if isinstance(v, pd.Timestamp) else v) for k, v in level.items()
        },
        "report": {
            "scope": "selected window only",
            "training_candles": len(d),
            "start": w.start.isoformat(),
            "end": w.end.isoformat(),
            "surface_fit_rmse": float(np.sqrt(mse)),
            "trials": trials,
            "note": "ML fits potential height only. No learned velocity, acceleration, damping, throw or price path. Surface extrapolation accuracy is unvalidated.",
        },
    }
    update(98, "Future surface ready")
    return model


def model_matches(selected, model, interval, quantum, mintick):
    return bool(
        model
        and model.get("method") == METHOD
        and model.get("version") == VERSION
        and model.get("interval") == interval
        and model.get("level", {}).get("quantum") == quantum
        and model.get("level", {}).get("mintick") == mintick
        and window_hash(selected) == model.get("window_hash")
    )


class JoinedSurface(Surface):
    """C2 blend of the original candle surface into a learned future potential."""

    def __init__(self, past, future, width):
        p, s = past.sources, future.sources
        sources = Sources(
            *[
                np.r_[getattr(p, k), getattr(s, k)]
                for k in ("index", "x", "y", "A", "sx", "sy", "age")
            ]
        )
        super().__init__(sources, past.k, past.background_k, past.background_y)
        self.past, self.future, self.width = past, future, max(float(width), 1.0)

    def components(self, x, y):
        x, y = np.broadcast_arrays(np.asarray(x, dtype=float), np.asarray(y, dtype=float))
        u = np.clip(x / self.width, 0, 1)
        blend = (u**3 * (10 - 15 * u + 6 * u * u))[..., None]
        a, ad = self.past.components(x, y)
        b, bd = self.future.components(x, y)
        return np.concatenate([a * (1 - blend), b * blend], axis=-1), np.concatenate(
            [ad, bd], axis=-1
        )


def future_surface(df, n, cfg, historical, scale, background_y, model):
    """Inference only. Only a model ending at this launch may be used."""
    times = pd.to_datetime(df.time, utc=True)
    ids = np.flatnonzero(
        (times >= pd.Timestamp(model["start"])) & (times < pd.Timestamp(model["end"]))
    )
    if not len(ids) or ids[-1] != n:
        raise ValueError(
            "ML surface applies after the learned window; keep the starting-candle launch for manual fitting"
        )
    rows = df.iloc[ids]
    if not model_matches(
        rows, model, model["interval"], model["level"]["quantum"], model["level"]["mintick"]
    ):
        raise ValueError("Surface model is stale; click Start learning again")
    settings = dict(model["settings"])
    settings["width"] *= model["scale"] / scale * cfg.sigma_y / 2.0
    settings["fast"] *= cfg.sigma_x / 4.0
    settings["slow"] *= cfg.sigma_x / 4.0
    src, rates = _sources(
        model["level"], float(df.close.iloc[n]), scale, settings, model["duration"]
    )
    # User depth/sign/dent multiplier remain the physical surface amplitude.
    amplitude = float(historical.A.sum())
    src = replace(
        src,
        A=np.asarray(model["coefficients"]) * amplitude,
        x=np.full(len(src.x), -float(model["duration"])),
    )
    future = WindowSurface(src, rates, model["duration"] * cfg.sigma_x / 4.0)
    past = Surface(historical, cfg.coupling, cfg.background_k, background_y)
    return JoinedSurface(past, future, cfg.sigma_x)
