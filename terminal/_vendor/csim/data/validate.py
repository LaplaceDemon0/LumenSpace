from dataclasses import asdict, dataclass
import numpy as np
import pandas as pd


@dataclass
class ValidationReport:
    rows: int
    reordered: bool
    zero_range: int
    gaps: list
    time_convention: str = "UTC; naive CSV timestamps assumed UTC"

    def to_dict(self):
        return asdict(self)


def validate(df, bar_minutes=1):
    d = df.copy()
    d.columns = [str(c).strip().lower() for c in d.columns]
    required = ["time", "open", "high", "low", "close"]
    if not set(required).issubset(d.columns):
        raise ValueError(f"Required CSV columns: {', '.join(required)}")
    if len(d) < 3:
        raise ValueError("At least three candles are required")
    if pd.api.types.is_numeric_dtype(d.time):
        d["time"] = pd.to_datetime(d.time, unit="s", utc=True, errors="raise")
    else:
        d["time"] = pd.to_datetime(d.time, utc=True, errors="raise")
    if d.time.isna().any() or d.time.duplicated().any():
        raise ValueError("Missing or duplicated timestamps; repair the source explicitly")
    reordered = not d.time.is_monotonic_increasing
    d = d.sort_values("time").reset_index(drop=True)
    ohlc = ["open", "high", "low", "close"]
    d[ohlc] = d[ohlc].apply(pd.to_numeric, errors="raise")
    if not np.isfinite(d[ohlc].to_numpy()).all() or (d[ohlc] <= 0).any().any():
        raise ValueError("OHLC values must be finite and positive")
    invalid = (
        (d.high < d[["open", "close"]].max(axis=1))
        | (d.low > d[["open", "close"]].min(axis=1))
        | (d.high < d.low)
    )
    if invalid.any():
        raise ValueError(f"Inconsistent OHLC at rows {list(d.index[invalid][:10])}")
    delta = d.time.diff().dt.total_seconds() / 60
    gaps = []
    for i in d.index[(delta.notna()) & (delta != bar_minutes)]:
        a, b = d.time.iloc[i - 1], d.time.iloc[i]
        days = pd.date_range(a.normalize(), b.normalize(), freq="D")
        kind = (
            "possible_weekend_or_session"
            if any(x.weekday() >= 5 for x in days)
            else "missing_or_session"
        )
        gaps.append(
            {
                "row": int(i),
                "minutes": float(delta.iloc[i]),
                "kind": kind,
                "from": a.isoformat(),
                "to": b.isoformat(),
            }
        )
    return d, ValidationReport(len(d), reordered, int((d.high == d.low).sum()), gaps)


def contiguous(df, start, end, bar_minutes=1):
    if start < 0 or end >= len(df):
        return False
    t = pd.to_datetime(df.iloc[start : end + 1].time, utc=True)
    return bool((t.diff().iloc[1:].dt.total_seconds() == bar_minutes * 60).all())
