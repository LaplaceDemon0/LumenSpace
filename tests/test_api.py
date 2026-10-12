import sys

import pandas as pd

from fastapi.testclient import TestClient

from terminal.app import app

client = TestClient(app)


def test_home_and_local_plotly():
    assert client.get("/").status_code == 200
    assert "LumenSpace" in client.get("/").text
    assert client.get("/vendor/plotly.js").status_code == 200


def test_bars_transform_and_invalid_parameters():
    bars = client.get("/api/bars").json()
    assert len(bars["bars"]) >= 100
    out = client.post(
        "/api/transform", json={"module": "laplace", "minutes": 42, "mode": "rolling"}
    )
    assert out.status_code == 200
    assert len(out.json()["y"]) == 48
    assert (
        client.post("/api/transform", json={"module": "phase", "params": {"tau": -1}}).status_code
        == 400
    )
    assert client.get("/api/jobs/not-found").status_code == 404
    assert client.get("/api/bars?timeframe=7").status_code == 400


def test_mt5_actionable_platform_error():
    if sys.platform != "win32":
        out = client.post("/api/mt5", json={})
        assert out.status_code == 400
        assert "Windows" in out.json()["detail"]


def test_same_origin_and_embedding_helpers():
    assert (
        client.post("/api/demo", headers={"Origin": "https://unrelated.example"}).status_code == 403
    )
    out = client.post("/api/embedding-helpers", json={"module": "phase", "params": {}})
    assert out.status_code == 200
    assert 1 <= out.json()["suggested_tau"] <= 32
    assert 2 <= out.json()["suggested_dimension"] <= 6


def test_mark_custom_window_and_linked_surface_levels():
    bars = client.get("/api/bars").json()["bars"]
    a, b = bars[100]["time"], bars[141]["time"]
    import pandas as pd

    out = client.post(
        "/api/select-window",
        json={
            "kind": "custom",
            "start": pd.Timestamp(a, unit="s", tz="UTC").isoformat(),
            "end": pd.Timestamp(b + 60, unit="s", tz="UTC").isoformat(),
        },
    )
    assert out.status_code == 200
    assert out.json()["bars"] == 42
    assert out.json()["last"] == b
    request = {"start": a, "end": b, "horizon": 8}
    result = client.post("/api/surface", json=request)
    assert result.status_code == 200
    assert result.json()["source_start"] == a
    assert result.json()["source_end"] == b + 60
    levels = client.post("/api/golden-levels", json=request)
    assert levels.status_code == 200
    assert len(levels.json()["selected"]["ladder"]) == 85


def test_window_list_and_surface_errors():
    assert client.get("/api/windows?minutes=14").status_code == 200
    assert client.post("/api/surface", json={"model_id": "unavailable"}).status_code == 400
    assert client.post("/api/surface-jobs/invalid", json={}).status_code == 400


def test_candle_window_preview_matches_selected_clock_interval():
    client.post("/api/demo")
    candle = client.get("/api/bars").json()["bars"][1000]["time"]
    r = client.post("/api/candle-window", json={"timestamp": candle, "minutes": 42})
    assert r.status_code == 200
    w = r.json()
    assert w["complete"] and w["bars"] == 42
    assert w["start"] <= candle < w["end"]
    assert w["end"] - w["start"] == 42 * 60
    selected = client.post("/api/select-window", json={"timestamp": candle, "minutes": 42}).json()
    assert [w["start"], w["last"], w["end"]] == [
        selected["start"],
        selected["last"],
        selected["end"],
    ]


def test_candle_window_preview_explains_incomplete_and_outside_history():
    client.post("/api/demo")
    bars = client.get("/api/bars").json()["bars"]
    w = client.post(
        "/api/candle-window", json={"timestamp": bars[-1]["time"], "minutes": 42}
    ).json()
    assert not w["complete"] and w["bars"] < w["expected"]
    assert "Incomplete" in w["reason"]
    assert w["start"] <= bars[-1]["time"] < w["end"]
    assert (
        client.post("/api/candle-window", json={"timestamp": 0, "minutes": 42}).status_code == 400
    )


def test_microsecond_cache_chart_click_matches_source(monkeypatch):
    import terminal.app as backend
    from terminal.data import demo_data

    d, report = demo_data(400)
    d["time"] = d.time.dt.as_unit("us")
    monkeypatch.setattr(backend, "DATA", d)
    monkeypatch.setattr(backend, "REPORT", report)
    chart = client.get("/api/bars").json()
    t = chart["bars"][200]["time"]
    assert t == int(d.time.iloc[200].timestamp())
    r = client.post("/api/candle-window", json={"timestamp": t, "source_version": chart["version"]})
    assert r.status_code == 200 and r.json()["complete"]
    assert r.json()["start"] <= t < r.json()["end"]


def test_aggregated_chart_bucket_before_first_source_candle(monkeypatch):
    import terminal.app as backend
    from terminal.data import demo_data

    d, report = demo_data(400)
    d["time"] = d.time + pd.Timedelta(minutes=1)
    monkeypatch.setattr(backend, "DATA", d)
    monkeypatch.setattr(backend, "REPORT", report)
    chart = client.get("/api/bars?timeframe=5").json()
    t = chart["bars"][0]["time"]
    assert t < int(d.time.iloc[0].timestamp())
    r = client.post("/api/candle-window", json={"timestamp": t, "display_timeframe": 5})
    assert r.status_code == 200
    assert r.json()["source_candle"] == int(d.time.iloc[0].timestamp())
    assert r.json()["start"] <= r.json()["source_candle"] < r.json()["end"]


def test_selected_window_training_snapshot_uses_only_history_before_cutoff(monkeypatch):
    import importlib
    from terminal.data import demo_data

    api = importlib.import_module("terminal.app")
    df, _ = demo_data(4200)
    monkeypatch.setattr(api, "DATA", df)
    monkeypatch.setattr(api, "JOBS", {})
    submitted = []
    monkeypatch.setattr(api.POOL, "submit", lambda *args: submitted.append(args))
    end = int(df.time.iloc[3000].timestamp())
    start = int(df.time.iloc[2987].timestamp())
    response = client.post(
        "/api/train",
        json={"horizon": 14, "forecast_start": start, "end": end, "selected": ["wavelet"]},
    )
    assert response.status_code == 200
    training = submitted[0][2]
    assert len(training) == 3001
    assert training.time.iloc[-1] == df.time.iloc[3000]
    assert training.time.max() < df.time.iloc[3001]
    api.JOBS.clear()
    response = client.post(
        "/api/train",
        json={"horizon": 14, "forecast_start": start + 30, "end": end, "selected": ["wavelet"]},
    )
    assert response.status_code == 400
    assert not api.JOBS
