import pandas as pd
import pytest

from terminal.data import CsvSource, demo_data, normalize, resample, windows


def test_mt5_columns_and_report():
    content = b"<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\n2025.01.02\t09:00:00\t10\t12\t9\t11\t50\n2025.01.02\t09:02:00\t11\t13\t10\t12\t60\n2025.01.02\t09:02:00\t11\t14\t10\t13\t60\n2025.01.02\t09:03:00\t11\t8\t10\t12\t60\n"
    df, report = CsvSource(content, "America/New_York").load()
    assert str(df.time.dt.tz) == "UTC"
    assert df.time.iloc[0].hour == 14
    assert report["duplicates_removed"] == 1
    assert report["bad_rows"] == 1
    assert df.close.iloc[-1] == 13


def test_headerless_unix_semicolon():
    df, _ = CsvSource(b"1735776000;10;12;9;11;50\n1735776060;11;13;10;12;60\n").load()
    assert len(df) == 2
    assert df.time.iloc[0] == pd.Timestamp("2025-01-02", tz="UTC")


def test_windows_and_gaps():
    df, _ = demo_data(200)
    aligned = windows(df, 14, "aligned", "UTC")
    assert all(len(g) == 14 for _, g in aligned)
    assert all((g.time.iloc[0].hour * 60 + g.time.iloc[0].minute) % 14 == 0 for _, g in aligned)
    assert len(windows(df, 42, "rolling")) == 159
    df.loc[df.index[-1], "closed"] = False
    assert windows(df, 14, "rolling")[-1][0] == df.time.iloc[-1]
    for _, g in windows(df.drop(index=40), 14, "rolling"):
        assert (g.time.diff().dropna() == pd.Timedelta(minutes=1)).all()


def test_dst_reports_ambiguity():
    df = pd.DataFrame(
        {
            "time": ["2025-11-02 00:59", "2025-11-02 01:30", "2025-11-02 02:01"],
            "open": [10] * 3,
            "high": [12] * 3,
            "low": [9] * 3,
            "close": [11] * 3,
        }
    )
    _, report = normalize(df, "America/New_York")
    assert report["bad_rows"] == 1


def test_timeframe_incompatibility_and_resampling():
    df, _ = demo_data(100)
    with pytest.raises(ValueError, match="exact multiple"):
        windows(resample(df, 5), 14)
    df.loc[99, "closed"] = False
    out = resample(df, 5)
    assert out.open.iloc[0] == df.open.iloc[0]
    assert out.close.iloc[0] == df.close.iloc[4]
    assert out.high.iloc[0] == df.high.iloc[:5].max()
    assert not out.closed.iloc[-1]


def test_mt5_two_volume_columns():
    text = b"<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n2025.01.02\t09:00:00\t10\t12\t9\t11\t50\t0\t20\n2025.01.02\t09:01:00\t11\t13\t10\t12\t60\t0\t20\n"
    df, _ = CsvSource(text).load()
    assert df.volume.tolist() == [50, 60]


def test_mixed_timezone_instants_and_boolean_closed():
    df = pd.DataFrame(
        {
            "time": ["2025-01-02 09:00:00", "2025-01-02T14:01:00Z", "2025-01-02T17:32:00+03:30"],
            "open": [10] * 3,
            "high": [12] * 3,
            "low": [9] * 3,
            "close": [11] * 3,
            "closed": ["true", "true", "false"],
        }
    )
    out, _ = normalize(df, "America/New_York")
    assert out.time.dt.hour.tolist() == [14, 14, 14]
    assert out.time.dt.minute.tolist() == [0, 1, 2]
    assert out.closed.tolist() == [True, True, False]


def test_csv_default_ny_and_dst_preserves_instants():
    from terminal.data import ny_clock_status

    for date, utc_hour, offset in [("2025-01-02", 14, -18000), ("2025-07-02", 13, -14400)]:
        content = f"time,open,high,low,close\n{date} 09:00,10,12,9,11\n{date} 09:01,11,13,10,12\n".encode()
        df, report = CsvSource(content).load()
        assert df.time.iloc[0].hour == utc_hour
        assert report["input_timezone"] == "America/New_York"
        c = ny_clock_status(df, report, now=pd.Timestamp(date + "T15:00:00Z"))
        assert "T09:01:00" in c["latest_candle_ny"]
        assert c["latest_candle_offset_seconds"] == offset
        assert c["timestamp_correction_seconds"] == 0


def test_live_clock_does_not_shift_a_closed_market_to_now():
    from terminal.data import ny_clock_status

    d, _ = demo_data(100)
    now = pd.Timestamp("2025-07-07T14:30:00Z")
    c = ny_clock_status(
        d, {"source": "MT5 · XAUUSD", "latest_tick_utc": int(d.time.iloc[-1].timestamp())}, now
    )
    assert c["status"] == "feed delayed or market closed"
    assert c["latest_candle_utc"] == int(d.time.iloc[-1].timestamp())
    assert c["latest_candle_offset_seconds"] == -18000
    assert c["current_offset_seconds"] == -14400
    assert c["timestamp_correction_seconds"] == 0
    d = d.copy()
    d.loc[d.index[-1], "time"] = now - pd.Timedelta(seconds=30)
    live = ny_clock_status(
        d, {"source": "MT5 · XAUUSD", "latest_tick_utc": int(now.timestamp()) - 5}, now
    )
    assert live["status"] == "live" and live["tick_age_seconds"] == 5


@pytest.mark.parametrize("unit", ["ns", "us", "ms", "s"])
def test_chart_and_transform_timestamps_are_resolution_independent(unit):
    from terminal.data import records
    from terminal.transforms import compute

    d, _ = demo_data(100)
    d["time"] = d.time.dt.as_unit(unit)
    expected = [int(t.timestamp()) for t in d.time]
    assert [r["time"] for r in records(d)] == expected
    assert compute(d, "wavelet", {})["times"] == expected
