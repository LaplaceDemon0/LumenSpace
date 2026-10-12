from dataclasses import dataclass, replace
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Sources:
    index: np.ndarray
    x: np.ndarray
    y: np.ndarray
    A: np.ndarray
    sx: np.ndarray
    sy: np.ndarray
    age: np.ndarray
    kernel: str = "gaussian"
    persistent: bool = False

    def take(self, mask):
        return replace(
            self, **{k: getattr(self, k)[mask] for k in ("index", "x", "y", "A", "sx", "sy", "age")}
        )

    def table(self, origin=0.0, scale=1.0):
        return pd.DataFrame(
            {
                "candle": self.index,
                "age": self.age,
                "x": self.x,
                "y": self.y,
                "anchor_price": origin + scale * self.y,
                "strength": self.A,
                "time_width": self.sx,
                "price_width": self.sy,
            }
        )


class Surface:
    def __init__(self, sources, k=0.15, background_k=0.0, background_y=0.0):
        self.sources, self.k = sources, k
        self.background_k, self.background_y = background_k, background_y

    def components(self, x, y):
        x, y = np.broadcast_arrays(np.asarray(x, dtype=float), np.asarray(y, dtype=float))
        s = self.sources
        dx, dy = x[..., None] - s.x, y[..., None] - s.y
        if s.persistent:
            g = np.ones_like(dx)
        elif s.kernel == "causal":
            g = np.exp(-np.maximum(dx, 0) / s.sx) * (dx >= 0)
        else:
            g = np.exp(-0.5 * (dx / s.sx) ** 2)
        return s.A * g * np.exp(-0.5 * (dy / s.sy) ** 2), dy

    def z(self, x, y):
        w, _ = self.components(x, y)
        bg = (
            0.5 * self.background_k / max(self.k, 1e-12) * (np.asarray(y) - self.background_y) ** 2
            if self.background_k
            else 0.0
        )
        return -w.sum(axis=-1) + bg

    def force_parts(self, x, y):
        w, dy = self.components(x, y)
        return -self.k * w * dy / self.sources.sy**2

    def force(self, x, y):
        return self.force_parts(x, y).sum(axis=-1) - self.background_k * (
            np.asarray(y) - self.background_y
        )

    def curvature(self, x, y):
        w, dy = self.components(x, y)
        return (w * (1 / self.sources.sy**2 - dy**2 / self.sources.sy**4)).sum(axis=-1) + (
            self.background_k / max(self.k, 1e-12) if self.background_k else 0.0
        )


def build_sources(history, features, indices, cfg, n, scale):
    from .features import anchor_prices

    i = np.asarray(indices, dtype=int)
    age = n - i
    strengths = np.full(len(i), cfg.strength, dtype=float)
    strengths[age > cfg.recent_window] *= cfg.ring_weight
    total = float(np.abs(strengths).sum())
    if cfg.depth > 0 and total > 0:
        # Weights sum to `depth`, so the summed Gaussian surface can never be deeper than `depth`,
        # however many candles are selected. Force stays the exact gradient of the surface.
        strengths = strengths * (cfg.depth / total)
    strengths *= cfg.dent_scale
    return Sources(
        i,
        i.astype(float) - n,
        (anchor_prices(history, cfg.anchor)[i] - history.close.iloc[n]) / scale,
        strengths,
        np.full(len(i), cfg.sigma_x),
        np.full(len(i), cfg.sigma_y),
        age,
        cfg.kernel,
    )
