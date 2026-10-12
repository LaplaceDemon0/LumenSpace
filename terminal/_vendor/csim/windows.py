"""New York wall-clock buckets, restarted at midnight on every local date."""

from dataclasses import dataclass, replace
import pandas as pd
from .data.validate import contiguous

ZONE = "America/New_York"


@dataclass(frozen=True)
class TimeWindow:
    start: pd.Timestamp
    end: pd.Timestamp
    first: int
    last: int
    expected: int
    complete: bool

    def to_dict(self):
        return dict(
            start=self.start.isoformat(),
            end=self.end.isoformat(),
            first=self.first,
            last=self.last,
            expected=self.expected,
            complete=self.complete,
        )


def bounds(timestamp, minutes):
    if minutes not in (14, 42):
        raise ValueError("Choose a 14 or 42 minute window")
    t = pd.Timestamp(timestamp).tz_convert(ZONE)
    minute = t.hour * 60 + t.minute
    a = (minute // minutes) * minutes
    # Localize wall-clock boundaries; repeated autumn hours keep the clicked offset.
    day = t.tz_localize(None).normalize()
    ambiguous = bool(t.dst())
    start = (day + pd.Timedelta(minutes=a)).tz_localize(
        ZONE, ambiguous=ambiguous, nonexistent="shift_forward"
    )
    end = (day + pd.Timedelta(minutes=min(a + minutes, 1440))).tz_localize(
        ZONE, ambiguous=ambiguous, nonexistent="shift_forward"
    )
    # A DST clock jump splits the containing wall-clock bucket. This keeps
    # repeated autumn hours disjoint, and never creates overlapping windows.
    if start.utcoffset() != end.utcoffset():
        timeline = pd.date_range(start.tz_convert("UTC"), end.tz_convert("UTC"), freq="min")
        offsets = [v.tz_convert(ZONE).utcoffset() for v in timeline]
        jump = next(
            (
                timeline[i].tz_convert(ZONE)
                for i in range(1, len(timeline))
                if offsets[i] != offsets[i - 1]
            ),
            None,
        )
        if jump is not None:
            if t < jump:
                end = min(end, jump)
            else:
                start = max(start, jump)
    return start, end


def select_window(df, index, minutes, bar_minutes=1):
    start, end = bounds(df.time.iloc[int(index)], int(minutes))
    if minutes % bar_minutes:
        raise ValueError(
            "14/42-minute windows require a bar interval that divides the window (use M1)"
        )
    times = pd.to_datetime(df.time, utc=True)
    ids = df.index[(times >= start) & (times < end)]
    if not len(ids):
        raise ValueError("No candles in this window")
    expected = int((end - start).total_seconds() // (bar_minutes * 60))
    first, last = int(ids[0]), int(ids[-1])
    complete = (
        len(ids) == expected
        and times.iloc[first] == start
        and times.iloc[last] + pd.Timedelta(minutes=bar_minutes) == end
        and contiguous(df, first, last, bar_minutes)
    )
    return TimeWindow(start, end, first, last, expected, complete)


def window_run(df, index, cfg, minutes, position="end"):
    w = select_window(df, index, minutes, cfg.bar_minutes)
    if not w.complete:
        raise ValueError(
            f"Incomplete New York window {w.start:%Y-%m-%d %H:%M %Z} – {w.end:%H:%M %Z}: "
            f"{w.last - w.first + 1}/{w.expected} bars. Select a complete window; gaps are not compressed."
        )
    if position == "start":
        n = w.first
        if w.first == 0:
            raise ValueError("Starting-candle launch needs a complete earlier source window")
        prior = select_window(df, w.first - 1, minutes, cfg.bar_minutes)
        if not prior.complete:
            raise ValueError("Starting-candle launch needs a complete earlier source window")
        conf = replace(
            cfg, lookback=prior.expected, include_launch=False, horizon=max(1, w.expected - 1)
        )
    else:
        n = w.last
        # Exactly this bucket builds the source surface, including its final candle.
        tomorrow = (w.end.tz_localize(None).normalize() + pd.Timedelta(days=1)).tz_localize(ZONE)
        next_end = min(w.end + pd.Timedelta(minutes=int(minutes)), tomorrow)
        if w.end.hour == 0 and w.end.minute == 0:
            next_end = w.end + pd.Timedelta(minutes=int(minutes))
        horizon = max(1, int((next_end - w.end).total_seconds() // (cfg.bar_minutes * 60)))
        conf = replace(cfg, lookback=max(1, w.expected - 1), include_launch=True, horizon=horizon)
    if n < cfg.volatility_window:
        raise ValueError(
            "This window has insufficient earlier candles for launch volatility. Select a later window."
        )
    return n, conf, w


def list_windows(df, minutes, bar_minutes=1):
    """Precalculate every midnight bucket on dates represented in the dataset.

    Empty buckets remain in the list, so missing sessions are visible. Search
    sorted timestamps rather than rescanning the dataset for each bucket.
    """
    if minutes not in (14, 42) or minutes % bar_minutes:
        raise ValueError("Choose 14/42 minutes with a compatible candle interval (M1 recommended)")
    times = pd.DatetimeIndex(pd.to_datetime(df.time, utc=True))
    if not times.is_monotonic_increasing:
        raise ValueError("Window listing requires sorted timestamps")
    days = times.tz_convert(ZONE).strftime("%Y-%m-%d").unique()
    result = []
    step = pd.Timedelta(minutes=bar_minutes)
    for day in days:
        cursor = pd.Timestamp(day).tz_localize(ZONE)
        stop = (pd.Timestamp(day) + pd.Timedelta(days=1)).tz_localize(ZONE)
        while cursor < stop:
            start, end = bounds(cursor, minutes)
            first = int(times.searchsorted(start))
            after = int(times.searchsorted(end))
            count = after - first
            expected = int((end - start).total_seconds() // (bar_minutes * 60))
            complete = bool(
                count == expected
                and count > 0
                and times[first] == start
                and times[after - 1] + step == end
                and contiguous(df, first, after - 1, bar_minutes)
            )
            result.append(
                dict(
                    day=day,
                    start=start.isoformat(),
                    end=end.isoformat(),
                    first=first if count else None,
                    last=after - 1 if count else None,
                    count=count,
                    expected=expected,
                    complete=complete,
                )
            )
            if end <= cursor:
                raise ValueError("Window boundaries did not advance")
            cursor = end
    return result
