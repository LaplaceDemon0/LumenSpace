"""Normalize data sources to closed UTC OHLCV bars with an explicit import report."""

from __future__ import annotations

import io
import re
import sys
from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pandas as pd


class DataSource(Protocol):
    def load(self) -> tuple[pd.DataFrame, dict]: ...


def normalize(frame: pd.DataFrame, timezone: str = "UTC") -> tuple[pd.DataFrame, dict]:
    df = frame.copy()
    df.columns = [str(c).strip().lower().strip("<>").replace(" ", "_") for c in df.columns]
    df = df.rename(
        columns={
            "timestamp": "time",
            "datetime": "time",
            "tickvol": "volume",
            "tick_volume": "volume",
            "vol": "real_volume",
        }
    )
    if "volume" not in df and "real_volume" in df:
        df["volume"] = df["real_volume"]
    if df.columns.duplicated().any():
        raise ValueError(
            "Duplicate column names after normalization; provide one time and one volume series."
        )
    if "date" in df:
        df["time"] = (
            df["date"].astype(str)
            + " "
            + df.get("time", pd.Series("00:00:00", index=df.index)).astype(str)
        )
    required = ["time", "open", "high", "low", "close"]
    if any(c not in df for c in required):
        raise ValueError(
            "Required columns: time, open, high, low, close. Split DATE/TIME is supported."
        )
    original = len(df)
    if pd.api.types.is_numeric_dtype(df.time):
        valid_numbers = pd.to_numeric(df.time, errors="coerce")
        unit = "ms" if valid_numbers.median() > 1e11 else "s"
        times = pd.to_datetime(valid_numbers, unit=unit, utc=True, errors="coerce")
    else:
        text = df.time.astype(str)
        aware = text.str.contains(r"(?:Z|[+-]\d{2}:?\d{2})\s*$", case=False, regex=True)
        times = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns, UTC]")
        if aware.any():
            times.loc[aware] = pd.to_datetime(
                text.loc[aware], format="mixed", errors="coerce", utc=True
            )
        if (~aware).any():
            naive = pd.to_datetime(text.loc[~aware], format="mixed", errors="coerce")
            times.loc[~aware] = naive.dt.tz_localize(
                timezone, ambiguous="NaT", nonexistent="NaT"
            ).dt.tz_convert("UTC")
    df["time"] = times
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce") if col in df else 0.0
    invalid = df[required + ["volume"]].isna().any(axis=1)
    invalid |= ~np.isfinite(df[["open", "high", "low", "close", "volume"]]).all(axis=1)
    invalid |= df.high < df[["open", "close", "low"]].max(axis=1)
    invalid |= (df.low > df[["open", "close", "high"]].min(axis=1)) | (df.volume < 0)
    bad_rows = (np.flatnonzero(invalid.to_numpy()) + 2).tolist()
    df = df.loc[~invalid].sort_values("time", kind="stable")
    duplicates = int(df.duplicated("time").sum())
    df = df.drop_duplicates("time", keep="last")
    if len(df) < 2:
        raise ValueError("At least two valid, distinct bars are required.")
    delta = df.time.diff().dt.total_seconds()
    interval = int(delta.dropna().mode().iloc[0])
    gaps = df.loc[delta > interval * 1.5, "time"].astype(str).tolist()
    if "closed" in df:
        closed = df["closed"].astype(str).str.lower().str.strip()
        if not closed.isin(["true", "false", "1", "0"]).all():
            raise ValueError("closed column must contain true/false or 1/0")
        df["closed"] = closed.isin(["true", "1"])
    else:
        df["closed"] = True
    df = df[["time", "open", "high", "low", "close", "volume", "closed"]].reset_index(drop=True)
    return df, {
        "input_rows": original,
        "valid_rows": len(df),
        "bad_rows": len(bad_rows),
        "bad_row_examples": bad_rows[:20],
        "duplicates_removed": duplicates,
        "gaps": len(gaps),
        "gap_examples": gaps[:10],
        "interval_seconds": interval,
        "policy": "Invalid rows removed; duplicate timestamps keep the last row; sorted in UTC.",
    }


@dataclass
class CsvSource:
    content: bytes
    timezone: str = "America/New_York"

    def load(self):
        text = self.content.decode("utf-8-sig")
        first = text.splitlines()[0]
        has_header = any(
            key in first.lower() for key in ["open", "close", "timestamp", "date", "time"]
        )
        df = pd.read_csv(
            io.StringIO(text), sep=None, engine="python", header=0 if has_header else None
        )
        if not has_header:
            if df.shape[1] not in (5, 6):
                raise ValueError("Headerless CSV must have time, open, high, low, close[, volume].")
            df.columns = ["time", "open", "high", "low", "close", "volume"][: df.shape[1]]
        bars, report = normalize(df, self.timezone)
        report["input_timezone"] = self.timezone
        report["clock_policy"] = (
            "Naive CSV times use the selected timezone; explicit offsets and Unix times preserve their instant."
        )
        return bars, report


NY = "America/New_York"
SERVER_RULES = {
    "utc": "GMT+0 (UTC)",
    "ny_close": "GMT+2/+3 · New York close (follows US DST)",
    "eet": "GMT+2/+3 · Eastern Europe (follows EU DST)",
}
_FIXED = re.compile(r"^(?:utc|gmt)?\s*([+-])\s*(\d{1,2})(?::?(\d{2}))?$", re.I)


def _fixed_offset(rule: str) -> int | None:
    m = _FIXED.match(str(rule).strip())
    if not m:
        return None
    sign = -1 if m.group(1) == "-" else 1
    return sign * (int(m.group(2)) * 3600 + int(m.group(3) or 0) * 60)


def normalize_server_rule(rule: str | None) -> str:
    rule = (rule or "auto").strip()
    low = rule.lower()
    if low in ("auto", "utc", "ny_close", "eet"):
        return low
    fixed = _fixed_offset(rule)
    if fixed is None or abs(fixed) > 14 * 3600:
        raise ValueError(
            "Server time must be auto, utc, ny_close, eet or a fixed offset such as UTC+3."
        )
    return f"UTC{fixed / 3600:+g}" if fixed % 3600 == 0 else f"UTC{fixed // 3600:+d}:{abs(fixed) % 3600 // 60:02d}"


def server_label(rule: str) -> str:
    return SERVER_RULES.get(rule) or f"fixed {rule.replace('UTC', 'GMT')}"


def server_offset_seconds(rule: str, instant) -> int:
    """Seconds the broker's wall clock is ahead of UTC at a real UTC instant."""
    t = pd.Timestamp(instant)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    if rule == "utc":
        return 0
    fixed = _fixed_offset(rule)
    if fixed is not None:
        return fixed
    if rule == "ny_close":  # broker wall clock is always New York wall clock + 7 hours
        return int(t.tz_convert(NY).utcoffset().total_seconds()) + 7 * 3600
    if rule == "eet":
        return int(t.tz_convert("Europe/Athens").utcoffset().total_seconds())
    raise ValueError(f"Unknown server time rule: {rule}")


def server_to_utc(epochs: pd.Series, rule: str) -> pd.Series:
    """MT5 bar/tick stamps are broker wall-clock written as if they were UTC.

    Read them as naive wall-clock, then localize with the broker's real rule so each bar
    keeps its own DST offset. Wall-clock hours that do not exist or repeat (market closed
    on every FX/metal broker) become NaT and are reported as bad rows.
    """
    wall = pd.to_datetime(pd.to_numeric(epochs, errors="coerce"), unit="s")
    fixed = _fixed_offset(rule)
    if rule == "utc":
        return wall.dt.tz_localize("UTC")
    if fixed is not None:
        return (wall - pd.Timedelta(seconds=fixed)).dt.tz_localize("UTC")
    if rule == "ny_close":
        return (
            (wall - pd.Timedelta(hours=7))
            .dt.tz_localize(NY, ambiguous="NaT", nonexistent="NaT")
            .dt.tz_convert("UTC")
        )
    if rule == "eet":
        return wall.dt.tz_localize("Europe/Athens", ambiguous="NaT", nonexistent="NaT").dt.tz_convert(
            "UTC"
        )
    raise ValueError(f"Unknown server time rule: {rule}")


def _fx_market_closed(now: pd.Timestamp) -> bool:
    """Weekend window in which FX/metal quotes are stale, so a tick cannot reveal the clock."""
    ny = now.tz_convert(NY)
    minute = ny.hour * 60 + ny.minute
    return ny.weekday() == 5 or (ny.weekday() == 4 and minute >= 17 * 60) or (
        ny.weekday() == 6 and minute < 17 * 60
    )


def detect_server_rule(tick_time, now, previous=None):
    """Infer the broker clock from the newest tick. Returns (rule | None, how)."""
    now = pd.Timestamp(now).tz_convert("UTC")
    raw = float(tick_time) - now.timestamp()
    order = list(dict.fromkeys([r for r in (previous, "ny_close", "eet", "utc") if r]))
    for rule in order:
        if abs(raw - server_offset_seconds(rule, now)) <= 180:
            return rule, "tick"
    hours = round(raw / 3600)
    if abs(raw - hours * 3600) <= 180 and -12 <= hours <= 14 and not _fx_market_closed(now):
        return normalize_server_rule(f"UTC{hours:+d}"), "tick"
    return None, "unavailable"


def daily_break_check(df: pd.DataFrame, interval: int) -> dict | None:
    """FX/metal feeds pause at 17:00 New York. If converted bars disagree, the clock is off."""
    d = df.loc[df.closed, "time"].reset_index(drop=True)
    if len(d) < 3:
        return None
    gap = d.diff().dt.total_seconds()
    idx = gap.index[gap >= max(1200, interval * 5)]
    if not len(idx):
        return None
    starts = (d.loc[idx - 1].reset_index(drop=True) + pd.Timedelta(seconds=interval)).dt.tz_convert(NY)
    starts = starts[starts.dt.weekday < 4]  # Mon-Thu breaks; weekend breaks differ
    if len(starts) < 3:
        return None
    labels = starts.dt.strftime("%H:%M")
    top = labels.value_counts()
    share = float(top.iloc[0] / len(labels))
    return {
        "daily_break_ny": str(top.index[0]),
        "share": round(share, 3),
        "samples": int(len(labels)),
        "expected": "17:00",
        "ok": bool(top.index[0] == "17:00" and share >= 0.8),
    }


@dataclass
class Mt5Source:
    symbol: str = "XAUUSD"
    timeframe: str = "M1"
    count: int = 10000
    server_time: str = "auto"  # auto | ny_close | eet | utc | UTC+3 ...
    previous_rule: str | None = None  # last rule that was detected/accepted for this feed

    def load(self):
        if sys.platform != "win32":
            raise ValueError("MT5 requires Windows with the terminal installed and logged in.")
        try:
            import MetaTrader5 as mt5
        except ImportError as exc:
            raise ValueError('Install MT5 support with: pip install -e ".[mt5]"') from exc
        mode = normalize_server_rule(self.server_time)
        if not mt5.initialize():
            raise ValueError(f"Cannot connect to MT5: {mt5.last_error()}")
        try:
            if not mt5.symbol_select(self.symbol, True):
                raise ValueError(f"Symbol {self.symbol} is unavailable. Check Market Watch.")
            tick = mt5.symbol_info_tick(self.symbol)
            rates = mt5.copy_rates_from_pos(
                self.symbol, getattr(mt5, "TIMEFRAME_" + self.timeframe), 0, self.count
            )
            if rates is None or len(rates) < 2:
                raise ValueError(f"No history received: {mt5.last_error()}")
            tick_time = int(tick.time) if tick else None
            return self.build(rates, tick_time, mode)
        finally:
            mt5.shutdown()

    def build(self, rates, tick_time, mode=None, now=None):
        """Turn raw MT5 rates (broker wall-clock stamps) into closed/forming UTC bars."""
        mode = mode or normalize_server_rule(self.server_time)
        now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now).tz_convert("UTC")
        duration = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600}[self.timeframe]
        how, warning = "chosen", None
        if mode == "auto":
            rule = None
            if tick_time is not None:
                rule, how = detect_server_rule(tick_time, now, self.previous_rule)
            if rule is None and self.previous_rule:
                rule, how = self.previous_rule, "previous"
            if rule is None:
                rule, how = "ny_close", "assumed"
                warning = (
                    "Could not read the broker clock (market closed or PC clock off). Assumed "
                    "GMT+2/+3 New York-close time; pick the Server time manually if windows look shifted."
                )
        else:
            rule = mode
        df = pd.DataFrame(rates)
        df["time"] = server_to_utc(df.time, rule)
        df["time"] = (df.time - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds()
        # The broker's own newest tick is the best "now" for deciding which bar is still forming.
        tick_utc = None
        if tick_time is not None:
            tick_utc = float(
                server_to_utc(pd.Series([tick_time]), rule).map(
                    lambda t: t.timestamp() if pd.notna(t) else float("nan")
                ).iloc[0]
            )
        reference = now.timestamp()
        if tick_utc is not None and abs(tick_utc - reference) <= 300:
            reference = tick_utc
        bars, report = normalize(df)
        bars["closed"] = bars.time.map(lambda t: t.timestamp() + duration <= reference)
        offset = server_offset_seconds(rule, bars.time.iloc[-1])
        report["input_timezone"] = f"MT5 server ({server_label(rule)})"
        report["latest_tick_utc"] = int(tick_utc) if tick_utc is not None and tick_utc == tick_utc else None
        report["server_time"] = {
            "mode": mode,
            "rule": rule,
            "label": server_label(rule),
            "how": how,
            "offset_seconds": offset,
            "warning": warning,
        }
        report["clock_check"] = daily_break_check(bars, duration)
        report["clock_policy"] = (
            "MT5 stamps are broker server time, not UTC. They are converted with "
            f"{server_label(rule)} to UTC, then shown in America/New_York with date-specific DST."
        )
        return bars, report


def gap_summary(df: pd.DataFrame, interval: int):
    delta = df.time.diff().dt.total_seconds()
    gaps = df.loc[delta > interval * 1.5, "time"].astype(str).tolist()
    return len(gaps), gaps[:10]


def history_changed(old, new):
    """True only when closed bars the chart already had were altered or removed.

    New bars appended by live polling must not invalidate selections, surface fits or
    the right-click window finder, so they do not bump the version.
    """
    o, n = old.loc[old.closed], new.loc[new.closed]
    if o.empty or n.empty:
        return not (o.empty and n.empty)
    o = o.loc[o.time >= n.time.iloc[0]]  # rows trimmed off the front are not a change
    cols = ["open", "high", "low", "close", "volume"]
    joined = o.set_index("time")[cols].join(n.set_index("time")[cols], rsuffix="_new", how="left")
    if joined.empty or joined[[c + "_new" for c in cols]].isna().any().any():
        return True
    return not (joined[cols].to_numpy() == joined[[c + "_new" for c in cols]].to_numpy()).all()


def demo_data(n: int = 6000):
    rng = np.random.default_rng(31)
    close = 2640 + np.cumsum(rng.normal(0.005, 0.5, n)) + 2 * np.sin(np.arange(n) / 30)
    op = np.r_[close[0], close[:-1]]
    spread = rng.uniform(0.1, 0.8, n)
    return normalize(
        pd.DataFrame(
            {
                "time": pd.date_range("2025-02-03", periods=n, freq="min", tz="UTC"),
                "open": op,
                "high": np.maximum(op, close) + spread,
                "low": np.minimum(op, close) - spread,
                "close": close,
                "volume": rng.integers(50, 700, n),
            }
        )
    )


def records(df):
    out = df.copy()
    out["time"] = out.time.dt.as_unit("s").astype("int64")
    return out.to_dict("records")


def resample(df, minutes: int):
    if minutes == 1:
        return df
    return (
        df.set_index("time")
        .resample(f"{minutes}min", origin="start_day")
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
                "closed": "all",
            }
        )
        .dropna()
        .reset_index()
    )


def windows(df, minutes: int, mode: str = "aligned", timezone: str = "America/New_York"):
    """Yield full contiguous windows, labelled at their closing instant.

    Alignment resets at local midnight. A 14-minute grid does not divide a day;
    the short final daily fragment is intentionally discarded.
    """
    df = df.loc[df.closed].copy()
    if len(df) < 2:
        return []
    interval = int(df.time.diff().dt.total_seconds().dropna().mode().iloc[0])
    if minutes * 60 % interval:
        raise ValueError("Window must be an exact multiple of the source bar interval.")
    length = minutes * 60 // interval
    if length < 4:
        raise ValueError("Window has fewer than four bars. Use a smaller source timeframe.")
    groups = []
    if mode == "rolling":
        candidates = (df.iloc[i - length : i] for i in range(length, len(df) + 1))
    else:
        local = df.time.dt.tz_convert(timezone)
        seconds = local.dt.hour * 3600 + local.dt.minute * 60 + local.dt.second
        keys = local.dt.strftime("%Y-%m-%d") + ":" + (seconds // (minutes * 60)).astype(str)
        candidates = (group for _, group in df.groupby(keys, sort=False))
    for group in candidates:
        if len(group) != length:
            continue
        if not (group.time.diff().dropna().dt.total_seconds() == interval).all():
            continue
        if mode != "rolling":
            first = group.time.iloc[0].tz_convert(timezone)
            if (first.hour * 3600 + first.minute * 60 + first.second) % (minutes * 60):
                continue
        groups.append((group.time.iloc[-1] + pd.Timedelta(seconds=interval), group))
    return groups


def ny_clock_status(df, report, now=None):
    """Compare actual feed instants with now; never mistake feed age for a timezone shift."""
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now).tz_convert("UTC")
    last = df.time.iloc[-1]
    local = last.tz_convert("America/New_York")
    tick = report.get("latest_tick_utc")
    age = int(now.timestamp() - last.timestamp())
    tick_age = int(now.timestamp() - tick) if tick is not None else None
    live = str(report.get("source", "")).startswith("MT5")
    server = report.get("server_time") if live else None
    if server:
        server = {**server, "offset_seconds": server_offset_seconds(server["rule"], last)}
    fresh = (
        live
        and tick_age is not None
        and -30 <= tick_age <= 120
        and -30 <= age <= 2 * report.get("interval_seconds", 60) + 120
    )
    return {
        "now_utc": int(now.timestamp()),
        "now_ny": now.tz_convert("America/New_York").isoformat(),
        "latest_candle_utc": int(last.timestamp()),
        "latest_candle_ny": local.isoformat(),
        "display_timezone": "America/New_York",
        "input_timezone": report.get("input_timezone", "UTC"),
        "latest_candle_offset_seconds": int(local.utcoffset().total_seconds()),
        "current_offset_seconds": int(
            now.tz_convert("America/New_York").utcoffset().total_seconds()
        ),
        "candle_age_seconds": age,
        "tick_age_seconds": tick_age,
        "status": "live" if fresh else "feed delayed or market closed" if live else "historical",
        "timestamp_correction_seconds": server["offset_seconds"] if server else 0,
        "server_time": server,
        "latest_candle_server": (
            (last + pd.Timedelta(seconds=server["offset_seconds"])).strftime("%Y-%m-%d %H:%M")
            if server
            else None
        ),
        "clock_check": report.get("clock_check"),
        "policy": "Broker server stamps are converted to UTC with the chosen server-time rule, then each UTC instant to New York. Dates and feed gaps are preserved; old candles are never shifted to the current clock.",
    }
