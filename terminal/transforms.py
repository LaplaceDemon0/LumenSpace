"""Bounded transform plugins. Each result preserves source-time correspondence."""

from __future__ import annotations

import numpy as np
import pywt
from scipy import signal
from scipy.spatial.distance import cdist

from . import wavelet_analysis

MODULES = {
    "phase": "Phase space",
    "recurrence": "Recurrence",
    "wavelet": "Wavelet",
    "fourier": "Fourier",
    "laplace": "Laplace",
    "topology": "Topology",
}


def series(df, source="close", preprocessing="zscore"):
    if source == "typical":
        x = ((df.high + df.low + df.close) / 3).to_numpy()
    elif source == "return":
        if (df.close <= 0).any():
            raise ValueError("Log returns require positive prices.")
        x = np.r_[0.0, np.diff(np.log(df.close))]
    elif source == "range":
        x = (df.high - df.low).to_numpy()
    else:
        x = df[source].to_numpy(dtype=float)
    if preprocessing == "log":
        if np.any(x <= 0):
            raise ValueError("Log preprocessing requires positive values.")
        x = np.log(x)
    elif preprocessing == "detrend":
        x = signal.detrend(x)
    elif preprocessing == "zscore":
        x = (x - x.mean()) / max(x.std(), 1e-12)
    return x


def embed(x, tau=1, m=3):
    count = len(x) - (m - 1) * tau
    if count < 3:
        raise ValueError("Not enough bars for this delay and dimension. Select a longer range.")
    return np.column_stack([x[j * tau : j * tau + count] for j in range(m)])


def runs(a):
    padded = np.r_[False, a, False].astype(int)
    return np.flatnonzero(np.diff(padded) == -1) - np.flatnonzero(np.diff(padded) == 1)


def rqa(matrix):
    n = len(matrix)
    r = matrix.copy()
    np.fill_diagonal(r, False)
    diag = np.concatenate([runs(np.diag(r, k)) for k in range(-n + 1, n) if k])
    vert = np.concatenate([runs(col) for col in r.T])
    d = diag[diag >= 2]
    v = vert[vert >= 2]
    total = int(r.sum())
    _, freq = np.unique(d, return_counts=True)
    probs = freq / max(freq.sum(), 1)
    return {
        "Recurrence rate": total / max(n * (n - 1), 1),
        "Determinism": float(d.sum() / max(total, 1)),
        "Laminarity": float(v.sum() / max(total, 1)),
        "Mean diagonal": float(d.mean()) if len(d) else 0.0,
        "Diagonal entropy": float(-np.sum(probs * np.log(probs))) if len(probs) else 0.0,
    }


def metrics(df, selected=None):
    """Causal per-window feature vector. No global normalization or centred filters."""
    selected = list(MODULES) if selected is None else selected
    x = series(df)
    result = {
        "return": float(df.close.iloc[-1] / df.open.iloc[0] - 1),
        "range": float((df.high.max() - df.low.min()) / max(abs(df.close.iloc[-1]), 1e-12)),
        "volatility": float(np.std(np.diff(np.log(np.maximum(df.close, 1e-12))))),
    }
    if "phase" in selected:
        cloud = embed(x)
        result["phase_speed"] = float(np.linalg.norm(np.diff(cloud, axis=0), axis=1).mean())
        result["phase_spread"] = float(np.std(cloud))
    if "recurrence" in selected:
        cloud = embed(x)
        distances = cdist(cloud, cloud)
        epsilon = np.quantile(distances[~np.eye(len(cloud), dtype=bool)], 0.1)
        result.update(
            {"rqa_" + k.lower().replace(" ", "_"): v for k, v in rqa(distances <= epsilon).items()}
        )
    if "fourier" in selected:
        p = abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
        p[0] = 0
        p /= max(p.sum(), 1e-12)
        result["spectral_entropy"] = float(-np.sum(p * np.log(p + 1e-12)))
        result["dominant_frequency"] = float(np.fft.rfftfreq(len(x))[np.argmax(p)])
    if "wavelet" in selected:
        coeff, _ = pywt.cwt(x, [1, 2, 4], "morl")
        for i, energy in enumerate(np.mean(abs(coeff) ** 2, axis=1)):
            result[f"wavelet_energy_{i}"] = float(energy)
    if "laplace" in selected:
        # Bounded finite-window growth/decay responses, not physical system poles.
        t = np.arange(len(x)) / max(len(x) - 1, 1)
        result["laplace_decay"] = float(abs(np.dot(x, np.exp(-2 * t))) / len(x))
        result["laplace_growth"] = float(abs(np.dot(x, np.exp(2 * t))) / len(x))
    if "topology" in selected:
        from ripser import ripser

        h1 = ripser(embed(x)[:: max(1, len(x) // 64)], maxdim=1)["dgms"][1]
        lifetime = h1[:, 1] - h1[:, 0] if len(h1) else np.array([0.0])
        result["topology_total_persistence"] = float(lifetime.sum())
    return result


def compute(df, module, params):
    x = series(df, params.get("source", "close"), params.get("preprocessing", "zscore"))
    times = (df.time.dt.as_unit("s").astype("int64")).tolist()
    dt = float(df.time.diff().dt.total_seconds().dropna().median()) / 60
    tau, m = int(params.get("tau", 1)), int(params.get("dimension", 3))
    result = {"module": module, "times": times, "warnings": [], "metrics": {}}
    if len(x) > 512:
        raise ValueError("Transform range exceeds 512 bars; select a shorter range.")
    if len(x) < 6:
        raise ValueError("Select at least six closed bars.")
    if len(x) < 50:
        result["warnings"].append(
            "Short window: exploratory geometry only; statistical estimates are unstable."
        )
    if module in ("phase", "recurrence", "topology"):
        cloud = embed(x, tau, m)
        point_times = times[(m - 1) * tau :]
        result["point_times"] = point_times
        if module == "phase":
            result["points"] = cloud.tolist()
            result["metrics"] = {
                "Trajectory length": float(np.linalg.norm(np.diff(cloud, axis=0), axis=1).sum()),
                "Vectors": len(cloud),
            }
            result["warnings"].append(
                "Lyapunov and correlation-dimension estimates are deferred until a defensible long-window estimator is added."
            )
        elif module == "recurrence":
            distances = cdist(cloud, cloud)
            epsilon = np.quantile(
                distances[~np.eye(len(cloud), dtype=bool)],
                float(params.get("recurrence_rate", 0.1)),
            )
            rec = distances <= epsilon
            # Row density excludes the identity diagonal: a state always matches itself.
            counts = rec.sum(axis=1).astype(int) - 1
            offset = (m - 1) * tau
            row_scores = []
            for i, count in enumerate(counts):
                candle = df.iloc[offset + i]
                row_scores.append(
                    {
                        "row": i,
                        "time": point_times[i],
                        "count": int(count),
                        "density": float(count / max(len(cloud) - 1, 1)),
                        "low": float(candle.low),
                        "high": float(candle.high),
                        "close": float(candle.close),
                    }
                )
            ranked = sorted(row_scores, key=lambda row: (-row["count"], row["row"]))
            levels = []
            for row in ranked:
                if row["count"] <= 0:
                    continue
                if all(abs(row["row"] - prior["row"]) >= 3 for prior in levels):
                    levels.append(row)
                if len(levels) == 5:
                    break
            result.update(
                row_scores=row_scores,
                potential_levels=levels,
                level_method="Off-diagonal row count; top five, separated by at least three rows; candle low–high zones.",
                z=rec.astype(int).tolist(),
                x=point_times,
                y=point_times,
                metrics=rqa(rec),
                threshold=float(epsilon),
            )
        else:
            try:
                from ripser import ripser
            except ImportError as exc:
                raise ValueError(
                    'Topology is optional. Install: pip install -e ".[topology]"'
                ) from exc
            step = max(1, int(np.ceil(len(cloud) / 96)))
            diagrams = ripser(cloud[::step], maxdim=1)["dgms"]
            result["diagrams"] = [d[np.isfinite(d).all(axis=1)].tolist() for d in diagrams]
            h1 = diagrams[1]
            finite = h1[np.isfinite(h1).all(axis=1)]
            grid = np.linspace(0, max(float(np.max(cloud) - np.min(cloud)), 1), 128)
            tents = [np.maximum(0, np.minimum(grid - b, d - grid)) for b, d in finite]
            layers = np.sort(np.array(tents), axis=0)[::-1] if tents else np.zeros((1, len(grid)))
            landscape = layers[0]
            result.update(
                x=grid.tolist(),
                landscape=landscape.tolist(),
                metrics={
                    "H1 loops": len(finite),
                    "Landscape L1": float(np.sum(np.trapezoid(layers, grid, axis=1))),
                    "Landscape L2": float(np.sqrt(np.sum(np.trapezoid(layers**2, grid, axis=1)))),
                },
            )
            result["warnings"].append(
                "Landscape norms include all H1 layers; view shows the first. Cloud capped at 96 points."
            )
    elif module == "wavelet":
        scales = np.arange(1, min(64, len(x) // 2) + 1)
        coeff, freq = pywt.cwt(x, scales, params.get("wavelet", "morl"), sampling_period=dt)
        period = 1 / freq
        edge = np.minimum(np.arange(len(x)), np.arange(len(x))[::-1]) * dt
        result.update(
            z=(abs(coeff) ** 2).tolist(),
            x=times,
            y=period.tolist(),
            coi=(edge / np.sqrt(2)).tolist(),
        )
        levels = pywt.wavedec(x, "db2", level=min(3, pywt.dwt_max_level(len(x), "db2")))
        result["components"] = []
        for i in range(len(levels)):
            only = [np.zeros_like(c) for c in levels]
            only[i] = levels[i]
            result["components"].append(pywt.waverec(only, "db2")[: len(x)].tolist())
        wavelet_name = params.get("wavelet", "morl")

        def cwt(series_):
            return pywt.cwt(series_, scales, wavelet_name, sampling_period=dt, method="fft")[0]

        analysis = wavelet_analysis.analyse(x, times, dt, cwt(x), period, cwt, key=wavelet_name)
        result["analysis"] = analysis
        result["metrics"] = {
            "Dominant period (min)": analysis["dominant"]["period"]
            if analysis["available"]
            else float(period[np.argmax(np.mean(abs(coeff) ** 2, axis=1))])
        }
        if analysis["available"]:
            result["metrics"]["Energy share"] = analysis["dominant"]["share"]
            result["metrics"]["Cycle fit"] = analysis["dominant"]["strength"]
        result["warnings"].append(
            "Cone of influence is an approximate edge guide, not a significance test."
        )
        if analysis["available"]:
            result["warnings"].extend(analysis["notes"])
        else:
            result["warnings"].append(analysis["reason"])
    elif module == "fourier":
        win = signal.get_window(params.get("taper", "hann"), len(x))
        p = abs(np.fft.rfft(x * win)) ** 2
        freq = np.fft.rfftfreq(len(x), d=dt)
        result.update(x=freq.tolist(), power=p.tolist())
        f, t, z = signal.stft(
            x, fs=1 / dt, nperseg=min(16, len(x)), noverlap=min(12, len(x) - 1), boundary=None
        )
        result.update(
            z=(abs(z) ** 2).tolist(), spec_x=(times[0] + t * 60).tolist(), spec_y=f.tolist()
        )
        result["metrics"] = {"Dominant frequency (/min)": float(freq[np.argmax(p[1:]) + 1])}
    elif module == "laplace":
        t = np.arange(len(x)) * dt
        sigma = np.linspace(-2 / max(t[-1], 1), 2 / max(t[-1], 1), 48)
        omega = np.linspace(0, np.pi / dt, 64)
        s = sigma[:, None] + 1j * omega[None, :]
        z = abs(np.sum(x[None, None, :] * np.exp(-s[:, :, None] * t), axis=2) * dt)
        peak = np.unravel_index(np.argmax(z), z.shape)
        result.update(
            z=z.tolist(),
            x=omega.tolist(),
            y=sigma.tolist(),
            metrics={
                "Peak sigma (/min)": float(sigma[peak[0]]),
                "Peak omega (rad/min)": float(omega[peak[1]]),
            },
        )
        result["warnings"].append(
            "Finite-window Laplace magnitude depends on sigma weighting; peaks are not estimated poles."
        )
    else:
        raise ValueError("Unknown transform.")
    return result
