from datetime import timedelta, timezone
import math
import numpy as np
import pandas as pd


def zeller(timestamp):
    q, m, year = timestamp.day, timestamp.month, timestamp.year
    if m < 3:
        m, year = m + 12, year - 1
    K, J = year % 100, year // 100
    return int((q + 13 * (m + 1) // 5 + K + K // 4 + J // 4 - 2 * J) % 7)


def wilder_atr(df, period=14):
    prev = df.close.shift(1)
    tr = (
        pd.concat([df.high - df.low, (df.high - prev).abs(), (df.low - prev).abs()], axis=1)
        .max(axis=1)
        .to_numpy()
    )
    out = np.full(len(df), np.nan)
    if len(tr) >= period:
        out[period - 1] = np.mean(tr[:period])
        for i in range(period, len(tr)):
            out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out


def compute_levels(
    bars,
    W=14,
    timezone_offset_minutes=-330,
    quantum=0.25,
    mintick=0.01,
    alignment="1970-01-01T00:00:00Z",
):
    """Explicit UTC origin; validate origin against exported TradingView bars."""
    if W < 1 or quantum <= 0 or mintick <= 0:
        raise ValueError("Window, quantum and tick must be positive")
    d = bars.copy().reset_index(drop=True)
    d["time"] = pd.to_datetime(d.time, utc=True)
    origin = pd.Timestamp(alignment)
    origin = origin.tz_localize("UTC") if origin.tzinfo is None else origin.tz_convert("UTC")
    d["bucket"] = ((d.time - origin).dt.total_seconds() // (W * 60)).astype(int)
    atr = wilder_atr(d)
    tz = timezone(timedelta(minutes=timezone_offset_minutes))
    result = []
    for bucket, g in d.groupby("bucket", sort=True):
        i = int(g.index[-1])
        if len(g) != W or not (g.time.diff().iloc[1:].dt.total_seconds() == 60).all():
            continue
        previous_start = origin + pd.Timedelta(minutes=int(bucket) * W)
        if g.time.iloc[0] != previous_start or not np.isfinite(atr[i]):
            continue
        op, hi, lo, close = g.open.iloc[0], g.high.max(), g.low.min(), g.close.iloc[-1]
        U, D = max(hi - max(op, close), 0), max(min(op, close) - lo, 0)
        z = zeller(previous_start.tz_convert(tz)) / 6
        safe = max(atr[i], mintick)
        u, down = D / safe + z, U / safe + z
        rung = min(84, math.ceil(atr[i] / quantum))
        mu = quantum * rung
        tick = lambda p: math.floor(p / mintick + 0.5) * mintick
        ladder = [
            {
                "rung": j,
                "multiplier": quantum * j,
                "up": tick(close + u * quantum * j),
                "down": tick(close - down * quantum * j),
                "up_root": digital_root(close + u * quantum * j),
                "down_root": digital_root(close - down * quantum * j),
            }
            for j in range(85)
        ]
        result.append(
            {
                "launch": i,
                "start": previous_start + pd.Timedelta(minutes=W),
                "previous_start": previous_start,
                "W": W,
                "origin": float(close),
                "atr": float(atr[i]),
                "weekday_fraction": z,
                "u": u,
                "d": down,
                "mu": mu,
                "rung": rung,
                "up": tick(close + u * mu),
                "down": tick(close - down * mu),
                "ladder": ladder,
            }
        )
    return result


def digital_root(value):
    n = abs(int(value))
    return 0 if n == 0 else 1 + (n - 1) % 9


def window_levels(bars, window, atr=None, quantum=0.25, mintick=0.01):
    """Same GoldenShadow formula on an explicit complete NY window (no epoch buckets)."""
    if not window.complete:
        raise ValueError("GoldenShadow needs a complete source window")
    if quantum <= 0 or mintick <= 0 or not np.isfinite([quantum, mintick]).all():
        raise ValueError("GoldenShadow quantum and tick must be finite and positive")
    g = bars.iloc[window.first : window.last + 1]
    if not len(g) or window.last >= len(bars):
        raise ValueError("GoldenShadow source exceeds available history")
    value = float(wilder_atr(bars)[window.last] if atr is None else atr[window.last])
    if not np.isfinite(value):
        raise ValueError("GoldenShadow needs at least 14 earlier M1 candles for ATR")
    op, hi, lo, close = (
        float(g.open.iloc[0]),
        float(g.high.max()),
        float(g.low.min()),
        float(g.close.iloc[-1]),
    )
    upper, lower = max(hi - max(op, close), 0), max(min(op, close) - lo, 0)
    z = zeller(window.start) / 6
    safe = max(value, mintick)
    u, d = lower / safe + z, upper / safe + z
    rung = min(84, math.ceil(value / quantum))
    tick = lambda p: math.floor(p / mintick + 0.5) * mintick
    ladder = [
        {
            "rung": j,
            "multiplier": quantum * j,
            "up": tick(close + u * quantum * j),
            "down": tick(close - d * quantum * j),
            "up_root": digital_root(close + u * quantum * j),
            "down_root": digital_root(close - d * quantum * j),
        }
        for j in range(85)
    ]
    return {
        "launch": window.last,
        "start": window.end,
        "previous_start": window.start,
        "W": window.expected,
        "origin": close,
        "atr": value,
        "weekday_fraction": z,
        "u": u,
        "d": d,
        "mu": quantum * rung,
        "rung": rung,
        "up": ladder[rung]["up"],
        "down": ladder[rung]["down"],
        "ladder": ladder,
        "timezone": "America/New_York",
        "quantum": quantum,
        "mintick": mintick,
        "upper_shadow": upper,
        "lower_shadow": lower,
    }
