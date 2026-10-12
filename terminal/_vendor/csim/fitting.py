"""Fit push/throw (and optionally coupling/damping) so projected paths match the actual chart.

Only windows whose real candles are already known are used, so fitting never looks at the
future of the launch you later apply the settings to.
"""

from dataclasses import dataclass, replace
import numpy as np
from scipy.optimize import least_squares
from .data.validate import contiguous
from .dynamics import simulate
from .forecast import run_forecast
from .initial import rescale_launch
from .surface import Surface

BOUNDS = {
    "push": (0.0, 3.0),
    "throw": (0.0, 3.0),
    "coupling": (0.0, 3.0),
    "damping": (0.0, 1.5),
    "dent_scale": (0.05, 10.0),
}
ALL = tuple(BOUNDS)
_GRID = (0.0, 0.5, 1.0, 1.5, 2.0)


@dataclass
class FitResult:
    params: dict  # all four values, fitted ones changed
    free: tuple
    launches: list  # launch indices used (newest first)
    before: float  # RMSE in launch-volatility units S, using the settings you had
    after: float
    flat: float  # RMSE of "price does not move"
    price_before: float
    price_after: float
    per_window: list  # one dict per window
    holdout: dict  # newest window predicted from older windows only (None if <2 windows)


class _Window:
    def __init__(self, df, m, cfg):
        # Unscaled launch (push = throw = 1); push/throw are applied afterwards.
        self.n = m
        self.forecast = run_forecast(df, m, replace(cfg, push=1.0, throw=1.0, dent_scale=1.0))
        launch = self.forecast.launch
        close = df.close.to_numpy()[m + 1 : m + cfg.horizon + 1]
        self.actual = (close - launch.price) / launch.scale
        self.scale = launch.scale
        self.time = df.time.iloc[m]


def _path(w, cfg, p):
    c = replace(
        cfg,
        coupling=p["coupling"],
        damping=p["damping"],
        push=p["push"],
        throw=p["throw"],
        rtol=1e-5,
        atol=1e-8,
        samples_per_bar=1,
        max_step=1.0,
    )
    s = w.forecast.surface
    surface = Surface(
        replace(s.sources, A=s.sources.A * p["dent_scale"]),
        c.coupling,
        s.background_k,
        s.background_y,
    )
    state = rescale_launch(w.forecast.launch, surface, c.damping, c.push, c.throw)
    return simulate(surface, state, c).y.to_numpy()[1:]


def _rmse(windows, cfg, p):
    err = np.concatenate([_path(w, cfg, p) - w.actual for w in windows])
    return float(np.sqrt(np.mean(err**2)))


def _fit(windows, cfg, p0, free, progress=None):
    """Coarse grid over push/throw, then bounded least squares from the best starts."""
    n_total = sum(len(w.actual) for w in windows)
    base = _rmse(windows, cfg, p0)
    lo = np.array([BOUNDS[k][0] for k in free])
    hi = np.array([BOUNDS[k][1] for k in free])
    width = hi - lo
    x0 = np.array([p0[k] for k in free], dtype=float)

    def make(x):
        p = dict(p0)
        p.update(zip(free, x))
        return p

    def residuals(x):
        p = make(x)
        r = np.concatenate([_path(w, cfg, p) - w.actual for w in windows]) / np.sqrt(n_total)
        # Tiny pull toward the starting values keeps flat directions from running to a bound.
        return np.concatenate([r, 0.05 * base * (x - x0) / width])

    starts = [x0]
    grid_keys = [i for i, k in enumerate(free) if k in ("push", "throw")]
    if grid_keys:
        import itertools

        scored = []
        combinations = list(itertools.product(_GRID, repeat=len(grid_keys)))
        for trial, combo in enumerate(combinations):
            if progress:
                progress(0.35 * trial / max(len(combinations), 1), "Checking push/throw grid")
            x = x0.copy()
            for i, v in zip(grid_keys, combo):
                x[i] = v
            scored.append((_rmse(windows, cfg, make(x)), tuple(x)))
        scored.sort()
        starts += [np.array(s[1]) for s in scored[:2]]
    best = None
    for trial, s in enumerate(starts):
        if progress:
            progress(0.35 + 0.6 * trial / len(starts), "Optimizing bounded surface parameters")
        sol = least_squares(
            residuals,
            np.clip(s, lo, hi),
            bounds=(lo, hi),
            x_scale=np.maximum(width / 4, 1e-3),
            max_nfev=40,
        )
        score = _rmse(windows, cfg, make(sol.x))
        if best is None or score < best[0]:
            best = (score, sol.x)
    fitted = {k: float(v) for k, v in make(best[1]).items()}
    # Never return something worse than the settings the user started with.
    return fitted if best[0] <= base else dict(p0)


def pick_launches(df, cfg, anchor, windows):
    """Newest-first launches whose full horizon of real candles is already known and contiguous."""
    h = cfg.horizon
    first = cfg.volatility_window + cfg.lookback
    m, out = min(anchor, len(df) - 1 - h), []
    while m >= first and len(out) < windows:
        if contiguous(df, m - cfg.lookback, m + h, cfg.bar_minutes):
            out.append(m)
        m -= h
    return out


def fit_launch(df, cfg, anchor, windows=3, free=("push", "throw"), launches=None, progress=None):
    free = tuple(k for k in free if k in BOUNDS)
    if not free:
        raise ValueError("Choose at least one parameter to fit")
    cfg.validate()
    launches = pick_launches(df, cfg, anchor, int(windows)) if launches is None else list(launches)
    if any(
        m < cfg.volatility_window
        or not contiguous(df, m - cfg.lookback, m + cfg.horizon, cfg.bar_minutes)
        for m in launches
    ):
        raise ValueError(
            "Fit windows must have enough history and a complete, gap-free actual path"
        )
    if not launches:
        raise ValueError(
            f"Not enough completed, gap-free candles: need about {cfg.volatility_window + cfg.lookback + cfg.horizon} "
            "bars before the launch plus the real future window. Load more bars or use a smaller window."
        )
    ws = [_Window(df, m, cfg) for m in launches]
    p0 = {k: float(getattr(cfg, k)) for k in ALL}
    fitted = _fit(
        ws, cfg, p0, free, (lambda f, m: progress(10 + int(60 * f), m)) if progress else None
    )
    flat = float(np.sqrt(np.mean(np.concatenate([w.actual for w in ws]) ** 2)))
    before, after = _rmse(ws, cfg, p0), _rmse(ws, cfg, fitted)
    mean_scale = float(np.mean([w.scale for w in ws]))
    rows = []
    for w in ws:
        rows.append(
            {
                "launch": w.n,
                "time": str(w.time)[:16],
                "before": float(np.sqrt(np.mean((_path(w, cfg, p0) - w.actual) ** 2))),
                "after": float(np.sqrt(np.mean((_path(w, cfg, fitted) - w.actual) ** 2))),
                "flat": float(np.sqrt(np.mean(w.actual**2))),
            }
        )
    holdout = None
    if len(ws) >= 2:
        # Honest check: fit on the older windows only, then score the newest one it has never seen.
        older = _fit(
            ws[1:],
            cfg,
            p0,
            free,
            (lambda f, m: progress(75 + int(20 * f), "Holdout · " + m)) if progress else None,
        )
        newest = ws[:1]
        holdout = {
            "launch": ws[0].n,
            "before": _rmse(newest, cfg, p0),
            "after": _rmse(newest, cfg, older),
            "flat": float(np.sqrt(np.mean(ws[0].actual ** 2))),
        }
    return FitResult(
        fitted,
        free,
        launches,
        before,
        after,
        flat,
        before * mean_scale,
        after * mean_scale,
        rows,
        holdout,
    )


def compare_to_actual(df, forecast, cfg):
    """Projected path vs the real closes that already exist inside the forecast window."""
    h, n = cfg.horizon, forecast.n
    known = max(0, min(h, len(df) - 1 - n))
    # Compare elapsed time, never compress missing bars/weekends into adjacent samples.
    for offset in range(1, known + 1):
        elapsed = (df.time.iloc[n + offset] - df.time.iloc[n]).total_seconds() / 60
        if elapsed != offset * cfg.bar_minutes:
            known = offset - 1
            break
    if known == 0:
        return {"known": 0, "horizon": h}
    launch = forecast.launch
    actual = (df.close.to_numpy()[n + 1 : n + known + 1] - launch.price) / launch.scale
    sim = np.interp(np.arange(1, known + 1), forecast.trajectory.x, forecast.trajectory.y)
    rmse = float(np.sqrt(np.mean((sim - actual) ** 2)))
    return {
        "known": known,
        "horizon": h,
        "rmse": rmse,
        "flat": float(np.sqrt(np.mean(actual**2))),
        "price_rmse": rmse * launch.scale,
        "end_error": float(sim[-1] - actual[-1]),
    }
