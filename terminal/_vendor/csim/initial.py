from dataclasses import dataclass, replace
import numpy as np


@dataclass(frozen=True)
class LaunchState:
    price: float
    scale: float
    v0: float
    a0: float
    q0: float
    y0: float = 0.0


def initial_state(history, features, surface, cfg):
    if len(history) < max(3, cfg.volatility_window):
        raise ValueError("Insufficient launch history")
    scale = float(features.scale.iloc[-1])
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("Launch volatility must be finite and positive")
    c = history.close.to_numpy()
    v, a = (c[-1] - c[-2]) / scale, (c[-1] - 2 * c[-2] + c[-3]) / scale
    if cfg.initial_estimator == "kalman":
        from .physics.kalman import filter_state

        mean, _ = filter_state((c[-min(len(c), 200) :] - c[-1]) / scale)
        v, a = mean[1:]
    a = (
        float(np.clip(a, -cfg.acceleration_clip, cfg.acceleration_clip))
        if cfg.acceleration_clip
        else float(a)
    )
    v, a = float(v) * cfg.push, a * cfg.throw
    q = a - float(surface.force(0, 0)) + cfg.damping * v
    return LaunchState(float(c[-1]), scale, float(v), a, q)


def rescale_launch(base, surface, damping, push=1.0, throw=1.0):
    """Re-apply push/throw to an unscaled launch state, keeping the launch acceleration matched."""
    v, a = base.v0 * push, base.a0 * throw
    return replace(base, v0=v, a0=a, q0=a - float(surface.force(0, 0)) + damping * v)
