"""MT5 stamps are broker wall-clock, not UTC. These tests pin the conversion to New York."""

import numpy as np
import pandas as pd

from terminal.data import (
    Mt5Source,
    daily_break_check,
    detect_server_rule,
    history_changed,
    ny_clock_status,
    server_offset_seconds,
    windows,
)

NY = "America/New_York"


def rates_for(ny_start, ny_end, wall_shift_hours=7, gaps=()):
    """Bars whose NY wall time is [ny_start, ny_end); MT5 stamps = NY wall + shift as 'UTC'."""
    ny = pd.date_range(ny_start, ny_end, freq="min", tz=NY, inclusive="left")
    ny = ny.delete([i for i in gaps])
    wall = ny.tz_localize(None) + pd.Timedelta(hours=wall_shift_hours)
    stamp = ((wall - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1)).to_numpy()
    n = len(stamp)
    close = 2600 + np.cumsum(np.random.default_rng(1).normal(0, 0.3, n))
    return pd.DataFrame(
        {
            "time": stamp,
            "open": close - 0.1,
            "high": close + 0.3,
            "low": close - 0.3,
            "close": close,
            "tick_volume": 100,
        }
    ).to_records(index=False)


def server_stamp(utc_text, rule="ny_close"):
    t = pd.Timestamp(utc_text)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    return int(t.timestamp()) + server_offset_seconds(rule, t)


def test_summer_and_winter_offsets_follow_us_dst():
    assert server_offset_seconds("ny_close", "2026-10-12T14:00Z") == 3 * 3600
    assert server_offset_seconds("ny_close", "2026-12-01T14:00Z") == 2 * 3600
    # EU and US DST differ for a few weeks each spring/autumn
    assert server_offset_seconds("eet", "2026-03-20T14:00Z") == 2 * 3600
    assert server_offset_seconds("ny_close", "2026-03-20T14:00Z") == 3 * 3600


def test_live_mt5_bars_land_on_ny_clock_and_latest_hours_stay_closed():
    now = pd.Timestamp("2026-10-12T14:30:20Z")  # 10:30:20 New York (EDT)
    rates = rates_for("2026-10-12 08:00", "2026-10-12 10:31")  # last bar opens 10:30 NY
    src = Mt5Source("XAUUSD", "M1", 1000)
    bars, report = src.build(rates, server_stamp(now), now=now)
    assert report["server_time"]["rule"] == "ny_close" and report["server_time"]["how"] == "tick"
    assert report["server_time"]["offset_seconds"] == 3 * 3600
    first = bars.time.iloc[0].tz_convert(NY)
    assert (first.hour, first.minute) == (8, 0)
    # The 10:30 bar is still forming; everything before it is closed (old code lost ~3 hours).
    assert not bars.closed.iloc[-1] and bars.closed.iloc[:-1].all()
    assert report["latest_tick_utc"] == int(now.timestamp())


def test_windows_are_found_after_live_load_in_both_dst_seasons():
    for now, rule in [("2026-10-12T14:30:20Z", "ny_close"), ("2026-12-01T20:10:05Z", "ny_close")]:
        now = pd.Timestamp(now)
        ny_now = now.tz_convert(NY).floor("min").tz_localize(None)
        rates = rates_for(ny_now.normalize() + pd.Timedelta(hours=1), ny_now + pd.Timedelta(minutes=1))
        bars, _ = Mt5Source("XAUUSD", "M1", 5000).build(rates, server_stamp(now, rule), now=now)
        for minutes in (14, 42):
            found = windows(bars, minutes, "aligned", NY)
            assert found, f"no {minutes}m window for {now}"
            for end, group in found:
                start = group.time.iloc[0].tz_convert(NY)
                assert (start.hour * 60 + start.minute) % minutes == 0
            # newest complete window ends within one window length of the live edge
            assert (now - found[-1][0]).total_seconds() <= (minutes + 1) * 60


def test_auto_detects_eet_fixed_and_utc_brokers():
    now = pd.Timestamp("2026-03-20T14:30:00Z")
    assert detect_server_rule(server_stamp(now, "utc"), now) == ("utc", "tick")
    assert detect_server_rule(server_stamp(now, "eet"), now) == ("eet", "tick")
    # During the spring weeks where EU and US DST disagree, the previous choice breaks ties
    assert detect_server_rule(server_stamp(now, "eet"), now, previous="eet")[0] == "eet"
    assert detect_server_rule(int(now.timestamp()) + 4 * 3600, now) == ("UTC+4", "tick")


def test_stale_weekend_tick_falls_back_to_previous_rule_not_a_wrong_guess():
    now = pd.Timestamp("2026-10-10T12:00:00Z")  # Saturday
    stale_tick = server_stamp("2026-10-09T20:59:00Z")  # Friday close
    rates = rates_for("2026-10-09 15:00", "2026-10-09 17:00")
    src = Mt5Source("XAUUSD", "M1", 100, previous_rule="ny_close")
    bars, report = src.build(rates, stale_tick, now=now)
    assert report["server_time"]["how"] == "previous"
    assert bars.closed.all()
    bars, report = Mt5Source("XAUUSD", "M1", 100).build(rates, stale_tick, now=now)
    assert report["server_time"]["how"] == "assumed" and report["server_time"]["warning"]


def test_manual_rule_overrides_detection_and_daily_break_check_flags_wrong_clock():
    # Continuous sessions with the normal 17:00-18:00 New York pause each day
    rates = np.concatenate(
        [
            rates_for("2026-10-12 09:00", "2026-10-12 17:00"),
            rates_for("2026-10-12 18:00", "2026-10-13 17:00"),
            rates_for("2026-10-13 18:00", "2026-10-14 17:00"),
            rates_for("2026-10-14 18:00", "2026-10-14 19:00"),
        ]
    )
    now = pd.Timestamp("2026-10-15T12:00:00Z")
    good, report = Mt5Source("XAUUSD", "M1", 5000).build(rates, None, mode="ny_close", now=now)
    assert report["server_time"]["how"] == "chosen"
    assert report["clock_check"]["daily_break_ny"] == "17:00" and report["clock_check"]["ok"]
    wrong, report = Mt5Source("XAUUSD", "M1", 5000).build(rates, None, mode="utc", now=now)
    assert not report["clock_check"]["ok"]
    assert daily_break_check(good, 60)["ok"]


def test_live_appends_do_not_change_history_version_but_edits_do():
    a, _ = Mt5Source("X", "M1", 100).build(
        rates_for("2026-10-12 08:00", "2026-10-12 09:00"), None, mode="ny_close",
        now=pd.Timestamp("2026-10-12T20:00Z"),
    )
    b, _ = Mt5Source("X", "M1", 100).build(
        rates_for("2026-10-12 08:00", "2026-10-12 09:05"), None, mode="ny_close",
        now=pd.Timestamp("2026-10-12T20:00Z"),
    )
    assert not history_changed(a, b)  # new closed bars appended
    assert not history_changed(a, b.iloc[10:].reset_index(drop=True))  # trimmed at the front
    edited = b.copy()
    edited.loc[5, "close"] += 1
    assert history_changed(a, edited)
    assert history_changed(a, b.drop(index=20).reset_index(drop=True))


def test_clock_status_reports_server_and_ny_time():
    now = pd.Timestamp("2026-10-12T14:30:20Z")
    rates = rates_for("2026-10-12 09:00", "2026-10-12 10:31")
    bars, report = Mt5Source("XAUUSD", "M1", 1000).build(rates, server_stamp(now), now=now)
    report["source"] = "MT5 · XAUUSD"
    status = ny_clock_status(bars, report, now)
    assert status["status"] == "live"
    assert status["latest_candle_ny"].startswith("2026-10-12T10:30:00-04:00")
    assert status["latest_candle_server"] == "2026-10-12 17:30"
    assert status["server_time"]["offset_seconds"] == 3 * 3600
