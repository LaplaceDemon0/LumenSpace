from dataclasses import replace
import numpy as np


def project_sources(
    sources, W, mode="reflect", seed=7, scale_factor=3.0, beta=0.5, price_mirror=False
):
    s = sources
    y = s.y.copy()
    if mode == "none":
        x = s.x.copy()
    elif mode == "reflect":
        x = s.age.astype(float)
    elif mode == "translate":
        x = W + 1 - s.age.astype(float)
    elif mode == "persist":
        x = np.ones(len(s.x))
    elif mode == "scramble":
        # Permute all window slots, then map each age, even if only a subset was selected.
        slots = np.random.default_rng(seed).permutation(np.arange(1, W + 1))
        x = slots[np.clip(s.age - 1, 0, W - 1)].astype(float)
    elif mode == "scale":
        x = scale_factor * s.age.astype(float)
        y *= scale_factor**beta
    else:
        raise ValueError("Unknown projection")
    if price_mirror:
        y = -y
    return replace(s, x=x, y=y, persistent=mode == "persist")
