from dataclasses import dataclass
import numpy as np
from .features import compute_features
from .selection import select_sources
from .surface import Surface, build_sources
from .symmetry import project_sources
from .initial import initial_state
from .dynamics import simulate


@dataclass
class Forecast:
    n: int
    config: object
    launch: object
    historical: object
    surface: object
    trajectory: object
    mode: str
    active_sources: int


def run_forecast(df, n, cfg, mode="prediction", future_surface_model=None):
    cfg.validate()
    if not 0 <= n < len(df):
        raise ValueError("Launch index out of bounds")
    if mode not in ("prediction", "exploration"):
        raise ValueError("Unknown mode")
    # The initial state and all forecast features can only see this slice.
    history = df.iloc[: n + 1].copy().reset_index(drop=True)
    f = compute_features(history, cfg.volatility_window)
    scale = float(f.scale.iloc[-1])
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("Not enough nonzero launch volatility history")
    idx = select_sources(f, cfg.rules, n, cfg.lookback, cfg.include_launch, cfg.max_sources)
    historical = build_sources(history, f, idx, cfg, n, scale)
    proj = (
        historical
        if future_surface_model is not None
        else project_sources(
            historical,
            cfg.lookback,
            cfg.projection,
            cfg.seed,
            cfg.scale_factor,
            cfg.scale_beta,
            cfg.price_mirror,
        )
    )
    if mode == "exploration":
        # Explicit hindsight mode; future candles add sources and are never evaluated as forecasts.
        from dataclasses import replace

        full = compute_features(df.reset_index(drop=True), cfg.volatility_window)
        ids = select_sources(
            full,
            cfg.rules,
            min(len(df) - 1, n + cfg.horizon),
            cfg.lookback + cfg.horizon,
            True,
            cfg.max_sources,
        )
        proj = build_sources(df, full, ids, cfg, n, scale)
        proj = replace(proj, persistent=False)
    bg_y = (history.close.tail(cfg.background_window).mean() - history.close.iloc[-1]) / scale
    surface = Surface(proj, cfg.coupling, cfg.background_k, bg_y)
    if future_surface_model is not None:
        if mode != "prediction":
            raise ValueError("ML future surfaces require Prediction mode")
        from .surface_learning import future_surface

        surface = future_surface(df, n, cfg, historical, scale, bg_y, future_surface_model)
    state = initial_state(history, f, surface, cfg)
    tr = simulate(surface, state, cfg)
    tr["time"] = history.time.iloc[-1] + __import__("pandas").to_timedelta(
        tr.x * cfg.bar_minutes, unit="min"
    )
    active = (
        int((np.abs(surface.components(0, surface.sources.y)[0].diagonal()) > 1e-4).sum())
        if len(surface.sources.x)
        else 0
    )
    result = Forecast(n, cfg, state, historical, surface, tr, mode, active)
    if future_surface_model is not None:
        result.surface_model = future_surface_model
        result.ml_report = future_surface_model["report"]
        result.historical_surface = surface.past
    return result
