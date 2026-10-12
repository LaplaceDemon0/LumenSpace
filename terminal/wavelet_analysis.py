"""Interpretation layer for the wavelet view: dominant cycle, energy bursts, cycle phase.

Everything here is descriptive. It summarises what the wavelet transform shows inside the
selected closed bars; it does not forecast. The caller supplies the CWT as a callable so the
module has no hard dependency on PyWavelets.

Dominant-cycle rule: raw wavelet power of a price series is dominated by its slowest periods
(red noise). So the dominant cycle is the period whose global power stands furthest above an
AR(1) red-noise background built from surrogates with the same length and lag-1 correlation.
Significance uses the maximum over periods, so choosing the best period is not rewarded.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import lfilter

SURROGATES = 100
_BACKGROUND: dict = {}


def _alpha(x):
    x = np.asarray(x, float) - np.mean(x)
    denom = float(np.dot(x, x))
    if denom <= 1e-12 or len(x) < 3:
        return 0.0
    return float(np.clip(np.dot(x[:-1], x[1:]) / denom, 0.0, 0.99))


def _global_power(power):
    return power.mean(axis=1)


def _background(n, alpha, cwt, scale_count, key):
    """Median red-noise global power per period and the 95% threshold of its max ratio."""
    q = round(alpha * 20) / 20  # cache on a 0.05 grid of lag-1 correlation
    cache_key = (n, q, scale_count, key)
    if cache_key in _BACKGROUND:
        return _BACKGROUND[cache_key]
    rng = np.random.default_rng(1000 * n + int(q * 100))
    spectra = []
    for _ in range(SURROGATES):
        noise = rng.standard_normal(n + 50)
        s = lfilter([1.0], [1.0, -q], noise)[50:]  # AR(1) after a burn-in
        s = (s - s.mean()) / max(s.std(), 1e-12)
        spectra.append(_global_power(abs(cwt(s)) ** 2))
    spectra = np.array(spectra)
    background = np.median(spectra, axis=0)
    background = np.maximum(background, 1e-12)
    max_ratio = (spectra / background).max(axis=1)
    out = (background, float(np.quantile(max_ratio, 0.95)))
    if len(_BACKGROUND) > 64:
        _BACKGROUND.clear()
    _BACKGROUND[cache_key] = out
    return out


def _runs(mask):
    padded = np.r_[False, mask, False].astype(int)
    starts = np.flatnonzero(np.diff(padded) == 1)
    ends = np.flatnonzero(np.diff(padded) == -1)
    return list(zip(starts, ends))


def _sine_fit(t, y, period):
    """Least-squares c0 + c1 t + a cos(wt) + b sin(wt). Returns a, b and variance explained."""
    w = 2 * np.pi / period
    design = np.column_stack([np.ones_like(t), t, np.cos(w * t), np.sin(w * t)])
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)
    trend = design[:, :2] @ coef[:2]
    detrended = y - trend
    total = float(np.sum((detrended - detrended.mean()) ** 2))
    cycle = design[:, 2:] @ coef[2:]
    explained = 1 - float(np.sum((detrended - cycle) ** 2)) / total if total > 1e-12 else 0.0
    return float(coef[2]), float(coef[3]), float(np.clip(explained, 0.0, 1.0))


def analyse(x, times, dt, coeff, period, cwt, key="morl"):
    """Return structured findings; the front end turns them into New York clock sentences."""
    x = np.asarray(x, float)
    n = len(x)
    span = n * dt
    power = abs(np.asarray(coeff)) ** 2
    period = np.asarray(period, float)
    out = {"available": False}
    candidates = np.flatnonzero(period <= span / 2)  # at least two cycles must fit
    if len(candidates) < 3 or n < 12:
        out["reason"] = "Window too short: fewer than two cycles of any resolvable period fit."
        return out
    global_power = _global_power(power)
    alpha = _alpha(x)
    scale_count = len(period)
    background, threshold = _background(n, alpha, cwt, scale_count, key)
    ratio = global_power / background
    best = int(candidates[np.argmax(ratio[candidates])])
    wavelet_period = float(period[best])
    # The scale grid is coarse; refine the period by the best single-sinusoid fit nearby so the
    # phase and the crest/trough marks do not drift over several cycles.
    t = np.arange(n) * dt
    trials = np.linspace(wavelet_period / 1.2, min(wavelet_period * 1.2, span / 2), 61)
    fits = [_sine_fit(t, x, p)[2] for p in trials]
    p_star = float(trials[int(np.argmax(fits))])
    band = (period >= wavelet_period / 1.25) & (period <= wavelet_period * 1.25)
    share = float(global_power[band].sum() / max(global_power.sum(), 1e-12))

    secondary = []
    order = candidates[np.argsort(-ratio[candidates])]
    for s in order:
        if abs(period[s] - p_star) / p_star < 0.35 or ratio[s] < 1.5:
            continue
        if all(abs(period[s] - o["period"]) / o["period"] >= 0.35 for o in secondary):
            local = (s == 0 or ratio[s] >= ratio[s - 1]) and (
                s == len(ratio) - 1 or ratio[s] >= ratio[s + 1]
            )
            if local:
                secondary.append({"period": float(period[s]), "ratio": float(ratio[s])})
        if len(secondary) == 2:
            break

    # Energy at the dominant period through time; edges are discounted by half a period.
    raw_energy = power[band].mean(axis=0)
    # Wavelet energy ripples inside each cycle; average over one period to see the envelope.
    width = max(3, int(round(p_star / dt)))
    energy = np.convolve(np.pad(raw_energy, width, mode="edge"), np.ones(width) / width, "same")[
        width:-width
    ]
    edge = np.minimum(np.arange(n), np.arange(n)[::-1]) * dt
    interior = edge >= p_star / 2
    if interior.sum() < 5:
        interior = np.ones(n, bool)
    e = energy[interior]
    cut = float(e.mean() + 0.75 * e.std())
    bursts = []
    idx = np.flatnonzero(interior)
    merged = []
    for a, b in _runs(e > cut):
        if merged and a - merged[-1][1] <= max(2, width // 2):
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    for a, b in merged:
        if b - a < 2:
            continue
        lo, hi = int(idx[a]), int(idx[b - 1])
        peak = int(lo + np.argmax(energy[lo : hi + 1]))
        bursts.append(
            {
                "start": int(times[lo]),
                "end": int(times[hi] + dt * 60),
                "peak_time": int(times[peak]),
                "area": float(energy[lo : hi + 1].sum()),
            }
        )
    bursts = sorted(bursts, key=lambda r: -r["area"])[:3]
    for r in bursts:
        r.pop("area")
    third = max(1, len(e) // 3)
    early, late = float(e[:third].mean()), float(e[-third:].mean())
    ratio_late = late / max(early, 1e-12)
    trend = "rising" if ratio_late > 1.3 else "fading" if ratio_late < 0.77 else "steady"

    # Phase of the cycle at the window end from a sinusoid fitted at the dominant period.
    a, b, strength = _sine_fit(t, x, p_star)
    recent_n = int(min(n, np.ceil(2 * p_star / dt) + 1))
    recent = None
    if recent_n >= 8:
        recent = _sine_fit(t[-recent_n:] - t[-recent_n], x[-recent_n:], p_star)[2]
    w = 2 * np.pi / p_star
    phi = float(np.arctan2(b, a))
    psi = float((w * t[-1] - phi) % (2 * np.pi))
    falling = psi < np.pi
    wait = ((np.pi - psi) if falling else (2 * np.pi - psi)) / w
    marks = []
    k0 = int(np.floor((w * t[0] - phi) / (2 * np.pi))) - 1
    horizon = t[-1] + p_star
    for k in range(k0, k0 + int(horizon / p_star) + 4):
        for kind, offset in (("crest", 0.0), ("trough", np.pi)):
            tm = (phi + offset + 2 * np.pi * k) / w
            if t[0] <= tm <= horizon:
                marks.append(
                    {
                        "time": int(round(times[0] + tm * 60)),
                        "kind": kind,
                        "projected": bool(tm > t[-1]),
                    }
                )
    marks.sort(key=lambda m: m["time"])
    marks = [m for m in marks if not m["projected"]][-10:] + [m for m in marks if m["projected"]][:2]

    significant = bool(ratio[best] > threshold)
    out.update(
        available=True,
        dominant={
            "period": p_star,
            "wavelet_period": wavelet_period,
            "share": share,
            "cycles_in_window": float(span / p_star),
            "excess": float(ratio[best]),
            "threshold": threshold,
            "significant": significant,
            "strength": strength,
            "recent_strength": recent,
        },
        secondary=secondary,
        energy={
            "trend": trend,
            "late_vs_early": ratio_late,
            "bursts": sorted(bursts, key=lambda r: r["start"]),
        },
        phase={
            "state": "falling" if falling else "rising",
            "next_turn": "trough" if falling else "crest",
            "minutes_to_turn": float(wait),
            "next_turn_time": int(round(times[-1] + wait * 60)),
            "edge_affected": True,
        },
        marks=marks,
        spectrum={
            "period": period.tolist(),
            "power": global_power.tolist(),
            "background": background.tolist(),
            "threshold_power": (background * threshold).tolist(),
            "usable": (period <= span / 2).tolist(),
        },
        alpha=alpha,
        surrogates=SURROGATES,
        notes=[
            "Dominant cycle = the period whose power stands furthest above an AR(1) red-noise "
            f"background ({SURROGATES} surrogates, lag-1 correlation {alpha:.2f}); at least two "
            "cycles must fit in the window.",
            "Cycle fit % is the variance of the detrended series explained by one sinusoid at the "
            "dominant period. The phase and next turn use that sinusoid and are least reliable at "
            "the window edge. They describe the rhythm, not a price forecast.",
        ],
    )
    return out
