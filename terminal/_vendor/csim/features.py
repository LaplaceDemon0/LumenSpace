import numpy as np


def compute_features(df, N):
    f = df.copy()
    f["range"] = f.high - f.low
    f["body"] = (f.close - f.open).abs()
    f["upper"] = f.high - f[["open", "close"]].max(axis=1)
    f["lower"] = f[["open", "close"]].min(axis=1) - f.low
    denom = f["range"].replace(0, np.nan)
    for c in ("body", "upper", "lower"):
        f[c + "_pct"] = 100 * f[c] / denom
    f["scale"] = f["range"].rolling(N, min_periods=N).mean()
    f["selection_scale"] = f.scale.shift(1)
    f["range_ratio"] = f["range"] / f.selection_scale.replace(0, np.nan)
    f["direction"] = np.sign(f.close - f.open)
    f["close_location"] = (f.close - f.low) / denom
    f["velocity"] = f.close.diff()
    f["acceleration"] = f.velocity.diff()
    if "tick_volume" in f:
        f["relative_volume"] = f.tick_volume / f.tick_volume.rolling(N).mean().shift(1).replace(
            0, np.nan
        )
    else:
        f["relative_volume"] = 1.0
    f["trend"] = (f.close - f.close.shift(N)) / f.selection_scale.replace(0, np.nan)
    return f


def anchor_prices(df, mode):
    if mode in ("close", "high", "low"):
        return df[mode].to_numpy()
    if mode == "body_mid":
        return ((df.open + df.close) / 2).to_numpy()
    if mode == "upper_mid":
        return ((df.high + df[["open", "close"]].max(axis=1)) / 2).to_numpy()
    if mode == "lower_mid":
        return ((df.low + df[["open", "close"]].min(axis=1)) / 2).to_numpy()
    raise ValueError("Unknown anchor")
