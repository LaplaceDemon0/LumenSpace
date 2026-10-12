"""Local API. Run on loopback only; this is not a hosted multi-user service."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from urllib.parse import urlparse
from fastapi.staticfiles import StaticFiles
from plotly.offline import get_plotlyjs
from pydantic import BaseModel, Field

from .data import (
    CsvSource,
    Mt5Source,
    daily_break_check,
    demo_data,
    gap_summary,
    history_changed,
    ny_clock_status,
    records,
    resample,
)
from .learning import train
from .transforms import MODULES, compute, metrics

STATIC = Path(__file__).parent / "static"
CACHE = Path(".cache")
CACHE.mkdir(exist_ok=True)
POOL = ThreadPoolExecutor(max_workers=2)
LOCK = threading.RLock()
DATA, REPORT = demo_data()
VERSION = 1
JOBS = {}
SURFACE_MODELS = {}
app = FastAPI(title="LumenSpace Terminal", version="1.0.1")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def loopback_origin_guard(request, call_next):
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != request.headers.get("host"):
        return JSONResponse(
            {"detail": "This local API only accepts same-origin requests."}, status_code=403
        )
    return await call_next(request)


class TransformRequest(BaseModel):
    module: str
    start: int | None = None
    end: int | None = None
    minutes: int = Field(42, ge=4, le=512)
    params: dict = Field(default_factory=dict)
    mode: str = "rolling"
    timezone: str = "America/New_York"


class TrainRequest(BaseModel):
    horizon: int = Field(14, ge=4, le=120)
    mode: str = "aligned"
    selected: list[str] = Field(
        default_factory=lambda: ["phase", "recurrence", "wavelet", "fourier", "laplace"]
    )
    timezone: str = "America/New_York"
    model: str = "trees"
    start: int | None = None
    end: int | None = None
    forecast_start: int | None = None


class PathRequest(BaseModel):
    path: str
    timezone: str = "America/New_York"


class Mt5Request(BaseModel):
    symbol: str = Field("XAUUSD", min_length=1, max_length=40)
    timeframe: str = "M1"
    count: int = Field(10000, ge=100, le=100000)
    server_time: str = "auto"


def snapshot(start=None, end=None):
    with LOCK:
        df = DATA.copy()
    if start is not None:
        df = df.loc[df.time >= pd.Timestamp(start, unit="s", tz="UTC")]
    if end is not None:
        df = df.loc[df.time <= pd.Timestamp(end, unit="s", tz="UTC")]
    return df


def persist(df, report):
    global DATA, REPORT, VERSION
    with LOCK:
        if history_changed(DATA, df):
            VERSION += 1
        DATA, REPORT = df, report
        with sqlite3.connect(CACHE / "bars.sqlite") as db:
            copy = df.copy()
            copy["time"] = copy.time.astype(str)
            copy.to_sql("bars", db, if_exists="replace", index=False)
            db.execute("CREATE TABLE IF NOT EXISTS meta (report TEXT)")
            db.execute("DELETE FROM meta")
            db.execute("INSERT INTO meta VALUES (?)", (json.dumps(report),))


# Restore real history only when a previous explicit import/MT5 connection cached it.
try:
    if (CACHE / "bars.sqlite").exists():
        with sqlite3.connect(CACHE / "bars.sqlite") as db:
            DATA = pd.read_sql("SELECT * FROM bars", db)
            DATA["time"] = pd.to_datetime(DATA.time, utc=True)
            DATA["closed"] = DATA.closed.astype(bool)
            REPORT = json.loads(db.execute("SELECT report FROM meta LIMIT 1").fetchone()[0])
except (sqlite3.Error, ValueError, TypeError):
    DATA, REPORT = demo_data()


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/vendor/plotly.js")
def plotly_bundle():
    return Response(
        get_plotlyjs(),
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/api/bars")
def bars(timeframe: int = 1):
    if timeframe not in [1, 5, 15, 60]:
        raise HTTPException(400, "Unsupported display timeframe")
    df = resample(snapshot(), timeframe)
    return {
        "bars": records(df.tail(100000)),
        "report": REPORT,
        "version": VERSION,
        "modules": MODULES,
        "truncated": len(df) > 100000,
        "training_start": int(snapshot().iloc[max(0, len(DATA) - 20000)].time.timestamp()),
    }


@app.get("/api/time-status")
def time_status():
    with LOCK:
        return ny_clock_status(DATA, REPORT)


@app.post("/api/import")
async def import_csv(file: UploadFile = File(...), timezone: str = Form("America/New_York")):
    content = await file.read(32 * 1024 * 1024 + 1)
    if len(content) > 32 * 1024 * 1024:
        raise HTTPException(413, "CSV limit: 32 MiB")
    try:
        df, report = await __import__("asyncio").to_thread(CsvSource(content, timezone).load)
        report["source"] = file.filename
        persist(df, report)
        return report
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/import-path")
def import_path(request: PathRequest):
    try:
        path = Path(request.path).expanduser()
        if (
            path.suffix.lower() not in [".csv", ".tsv", ".txt"]
            or path.stat().st_size > 32 * 1024 * 1024
        ):
            raise ValueError("Choose a CSV/TSV/text file under 32 MiB")
        df, report = CsvSource(path.read_bytes(), request.timezone).load()
        report["source"] = path.name
        persist(df, report)
        return report
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/demo")
def demo():
    df, report = demo_data()
    report["source"] = "Synthetic demo · not real market history"
    persist(df, report)
    return report


@app.post("/api/mt5")
def mt5(request: Mt5Request):
    if request.timeframe not in ["M1", "M5", "M15", "H1"]:
        raise HTTPException(400, "Unsupported MT5 timeframe")
    try:
        source = "MT5 · " + request.symbol
        with LOCK:
            same_feed = REPORT.get("source") == source
            previous = (REPORT.get("server_time") or {}).get("rule") if same_feed else None
        df, report = Mt5Source(
            request.symbol, request.timeframe, request.count, request.server_time, previous
        ).load()
        report["source"] = source
        with LOCK:
            # Merge polls only when both loads used the same broker-clock rule; stamps from an
            # old (UTC-assumed) cache or a different rule would duplicate or misplace bars.
            same_clock = (REPORT.get("server_time") or {}).get("rule") == report["server_time"]["rule"]
            if (
                same_feed
                and same_clock
                and REPORT.get("interval_seconds") == report["interval_seconds"]
            ):
                df = (
                    pd.concat([DATA, df])
                    .drop_duplicates("time", keep="last")
                    .sort_values("time")
                    .tail(500000)
                    .reset_index(drop=True)
                )
                report["valid_rows"] = len(df)
                report["gaps"], report["gap_examples"] = gap_summary(df, report["interval_seconds"])
                report["clock_check"] = daily_break_check(df, report["interval_seconds"])
        persist(df, report)
        return report
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/transform")
def transform(request: TransformRequest):
    try:
        if request.module not in MODULES:
            raise ValueError("Unknown module")
        if request.mode not in ["rolling", "aligned"]:
            raise ValueError("Unknown window mode")
        df = snapshot(request.start, request.end)
        df = df.loc[df.closed]
        if request.start is None:
            from .data import windows

            groups = windows(df, request.minutes, request.mode, request.timezone)
            if not groups:
                raise ValueError("No complete window is available.")
            df = groups[-1][1]
        tau = int(request.params.get("tau", 1))
        m = int(request.params.get("dimension", 3))
        if not 1 <= tau <= 32 or not 2 <= m <= 6:
            raise ValueError("Delay must be 1–32; dimension 2–6")
        if not 0.01 <= float(request.params.get("recurrence_rate", 0.1)) <= 0.5:
            raise ValueError("Recurrence rate must be between 0.01 and 0.5")
        if request.params.get("source", "close") not in [
            "close",
            "typical",
            "return",
            "range",
            "volume",
        ]:
            raise ValueError("Unknown input series")
        return compute(df, request.module, request.params)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/embedding-helpers")
def embedding_helpers(request: TransformRequest):
    from .embedding import estimate
    from .transforms import series

    try:
        df = snapshot(request.start, request.end).loc[lambda d: d.closed].tail(512)
        return estimate(
            series(
                df,
                request.params.get("source", "close"),
                request.params.get("preprocessing", "zscore"),
            )
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/metrics")
def metric_history(
    module: str = "fourier",
    minutes: int = 42,
    mode: str = "aligned",
    timezone: str = "America/New_York",
    start: int | None = None,
    end: int | None = None,
):
    try:
        from .data import windows

        if module not in MODULES or minutes not in [14, 42] or mode not in ["rolling", "aligned"]:
            raise ValueError("Invalid metric history settings")
        groups = windows(snapshot(start, end).tail(2000), minutes, mode, timezone)[-150:]
        return {
            "points": [
                {"time": int(end.timestamp()), "values": metrics(group, [module])}
                for end, group in groups
            ]
        }
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


def run_job(job_id, df, request, version):
    def progress(value, message):
        with LOCK:
            JOBS[job_id].update(progress=value, message=message)

    try:
        result = train(
            df,
            request.horizon,
            request.mode,
            request.selected,
            request.timezone,
            request.model,
            progress,
            forecast_df=(
                df.loc[df.time >= pd.Timestamp(request.forecast_start, unit="s", tz="UTC")]
                if request.forecast_start is not None
                else None
            ),
        )
        with LOCK:
            JOBS[job_id].update(status="complete", result=result, version=version)
    except Exception as exc:
        with LOCK:
            JOBS[job_id].update(status="failed", message=str(exc))


@app.post("/api/train")
def start_training(request: TrainRequest):
    if request.mode not in ["aligned", "rolling"] or request.model not in ["linear", "trees"]:
        raise HTTPException(400, "Invalid model or window mode")
    if any(s not in MODULES for s in request.selected):
        raise HTTPException(400, "Unknown feature module")
    with LOCK:
        if any(j["status"] == "running" for j in JOBS.values()):
            raise HTTPException(409, "A training job is already running.")
        if len(JOBS) >= 20:
            del JOBS[next(iter(JOBS))]
        job_id = uuid.uuid4().hex
        JOBS[job_id] = {
            "status": "running",
            "progress": 0,
            "message": "Preparing immutable data snapshot",
            "version": VERSION,
        }
        df = snapshot(request.start, request.end).loc[lambda d: d.closed]
        if request.forecast_start is not None:
            if request.end is None or request.horizon not in (14, 42):
                JOBS.pop(job_id)
                raise HTTPException(
                    400, "Selected-window forecasting requires an end and 14 or 42 candles."
                )
            df = snapshot(end=request.end).loc[lambda d: d.closed].tail(20000)
            source = df.loc[df.time >= pd.Timestamp(request.forecast_start, unit="s", tz="UTC")]
            if (
                len(source) != request.horizon
                or source.time.iloc[0] != pd.Timestamp(request.forecast_start, unit="s", tz="UTC")
                or source.time.iloc[-1] != pd.Timestamp(request.end, unit="s", tz="UTC")
                or not source.time.diff().dropna().eq(pd.Timedelta(minutes=1)).all()
            ):
                JOBS.pop(job_id)
                raise HTTPException(
                    400,
                    "Forecast source must contain exactly 14 or 42 consecutive closed M1 candles.",
                )
        version = VERSION
    if len(df) > 20000:
        with LOCK:
            JOBS.pop(job_id)
        raise HTTPException(400, "Select at most 20,000 bars for a training run.")
    POOL.submit(run_job, job_id, df, request, version)
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def job(job_id: str):
    with LOCK:
        if job_id not in JOBS:
            raise HTTPException(404, "Job not found")
        return dict(JOBS[job_id])


class SelectionRequest(BaseModel):
    display_timeframe: int = Field(1, ge=1, le=60)
    source_version: int | None = None
    kind: str = "aligned"
    minutes: int = Field(42, ge=14, le=42)
    timestamp: int | None = None
    start: str | None = None
    end: str | None = None
    timezone: str = "America/New_York"


class SurfaceRequest(BaseModel):
    start: int | None = None
    end: int | None = None
    minutes: int = 42
    mode: str = "aligned"
    horizon: int = Field(42, ge=1, le=120)
    parameters: dict = Field(default_factory=dict)
    quantum: float = Field(0.25, gt=0, le=100)
    mintick: float = Field(0.01, gt=0, le=100)
    model_id: str | None = None
    fit_windows: int = Field(3, ge=1, le=8)
    free: list[str] = Field(default_factory=lambda: ["push", "throw"])


def valid_surface_request(request):
    if request.minutes not in [14, 42] or request.mode not in ["rolling", "aligned"]:
        raise ValueError("Choose 14/42 minutes and aligned/rolling source windows")


@app.get("/api/windows")
def available_windows(minutes: int = 42):
    from .surface_bridge import checked_history, list_windows

    try:
        if minutes not in [14, 42]:
            raise ValueError("Choose 14 or 42 minutes")
        d = checked_history(snapshot())
        return {"windows": list_windows(d.tail(20000).reset_index(drop=True), minutes)[-250:]}
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/candle-window")
def candle_window(request: SelectionRequest):
    from ._vendor.csim.windows import bounds

    try:
        if request.minutes not in (14, 42) or request.timestamp is None:
            raise ValueError("Choose a candle and a 14m/42m window")
        with LOCK:
            d = snapshot()
            version = VERSION
        if request.source_version is not None and request.source_version != version:
            raise ValueError(
                "History changed since this chart was loaded. Refresh the chart and choose the candle again."
            )
        if request.display_timeframe not in (1, 5, 15, 60):
            raise ValueError("Unsupported chart display timeframe")
        interval = d.time.diff().dt.total_seconds().dropna().mode().iloc[0]
        if interval != 60:
            raise ValueError("Load M1 source history to find exact clock windows")
        anchor = pd.Timestamp(request.timestamp, unit="s", tz="UTC")
        source_bar = d.loc[
            (d.time >= anchor) & (d.time < anchor + pd.Timedelta(minutes=request.display_timeframe))
        ]
        if source_bar.empty:
            raise ValueError(
                "No source candles belong to that chart candle. Refresh the chart and try again."
            )
        # Display buckets can begin before their first actual M1 candle, especially at import edges.
        # Use an actual source candle inside that bucket, never an arbitrary nearest candle.
        resolved = source_bar.time.iloc[0]
        a, b = bounds(resolved, request.minutes)
        g = d.loc[(d.time >= a) & (d.time < b) & d.closed]
        expected = int((b - a).total_seconds() / 60)
        complete = (
            expected == request.minutes
            and len(g) == expected
            and g.time.iloc[0] == a
            and g.time.iloc[-1] + pd.Timedelta(minutes=1) == b
            and (g.time.diff().dropna().dt.total_seconds() == 60).all()
        )
        return {
            "start": int(a.timestamp()),
            "end": int(b.timestamp()),
            "last": int(g.time.iloc[-1].timestamp()) if len(g) else None,
            "bars": len(g),
            "expected": expected,
            "minutes": request.minutes,
            "complete": bool(complete),
            "candle": request.timestamp,
            "source_candle": int(resolved.timestamp()),
            "version": version,
            "reason": ""
            if complete
            else "Incomplete window: missing or forming candles; wait for its close or choose another window.",
        }
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/select-window")
def select_chart_window(request: SelectionRequest):
    from .surface_bridge import checked_history, select_window

    try:
        d = checked_history(snapshot())
        if request.kind == "custom":
            if not request.start or not request.end:
                raise ValueError("Enter both start and end times")

            def instant(value):
                t = pd.Timestamp(value)
                return (
                    t.tz_localize(request.timezone, ambiguous="raise", nonexistent="raise")
                    if t.tzinfo is None
                    else t
                ).tz_convert("UTC")

            a, b = instant(request.start), instant(request.end)
            if b <= a:
                raise ValueError("End must be after start (end is exclusive)")
            g = d.loc[(d.time >= a) & (d.time < b)]
            if len(g) and (g.time.iloc[0] != a or g.time.iloc[-1] + pd.Timedelta(minutes=1) != b):
                raise ValueError("Both endpoints must match available closed M1 bars")
        else:
            if request.minutes not in [14, 42] or request.kind not in ["aligned", "rolling"]:
                raise ValueError("Choose aligned, rolling, or custom")
            anchor = (
                pd.Timestamp(request.timestamp, unit="s", tz="UTC")
                if request.timestamp
                else d.time.iloc[-1]
            )
            idx = int(d.time.searchsorted(anchor, side="right")) - 1
            if idx < 0 or anchor > d.time.iloc[-1] + pd.Timedelta(minutes=1):
                raise ValueError("Clicked time is outside the available history")
            if request.kind == "rolling":
                g = d.iloc[max(0, idx - request.minutes + 1) : idx + 1]
                if len(g) != request.minutes:
                    raise ValueError("Insufficient earlier bars for this rolling window")
            else:
                w = select_window(d, idx, request.minutes)
                if not w.complete or w.expected != request.minutes:
                    raise ValueError(
                        "That clock window is incomplete. Choose a complete window from the list."
                    )
                g = d.iloc[w.first : w.last + 1]
        if not 6 <= len(g) <= 512 or not (g.time.diff().dropna().dt.total_seconds() == 60).all():
            raise ValueError("Select 6–512 contiguous closed M1 bars")
        return {
            "start": int(g.time.iloc[0].timestamp()),
            "last": int(g.time.iloc[-1].timestamp()),
            "end": int((g.time.iloc[-1] + pd.Timedelta(minutes=1)).timestamp()),
            "bars": len(g),
            "kind": request.kind,
        }
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/surface")
def simulate_surface(request: SurfaceRequest):
    from .surface_bridge import simulate_selection

    try:
        valid_surface_request(request)
        with LOCK:
            d = snapshot()
            version = VERSION
            model = SURFACE_MODELS.get(request.model_id) if request.model_id else None
        if request.model_id and model is None:
            raise ValueError(
                "Learn the selected future surface first; the saved model is unavailable"
            )
        result = simulate_selection(
            d,
            request.start,
            request.end,
            request.minutes,
            request.mode,
            request.horizon,
            request.parameters,
            request.quantum,
            request.mintick,
            model,
        )
        result["version"] = version
        return result
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/golden-levels")
def golden_levels(request: SurfaceRequest):
    from .surface_bridge import levels_for_selection, serialize_level, history_levels

    try:
        valid_surface_request(request)
        with LOCK:
            d = snapshot()
            version = VERSION
        if request.end is not None:
            d = d.loc[d.time <= pd.Timestamp(request.end, unit="s", tz="UTC")]
        level = levels_for_selection(
            d,
            request.start,
            request.end,
            request.minutes,
            request.mode,
            request.quantum,
            request.mintick,
        )
        return {
            "selected": serialize_level(level, request.horizon),
            "history": history_levels(d, request.minutes, request.quantum, request.mintick),
            "version": version,
        }
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


def run_surface_job(job_id, df, request, version, kind):
    from .surface_bridge import fit_parameters, learn_surface

    def progress(value, message):
        with LOCK:
            JOBS[job_id].update(progress=max(JOBS[job_id]["progress"], int(value)), message=message)

    try:
        if kind == "fit":
            result = fit_parameters(
                df,
                request.start,
                request.end,
                request.minutes,
                request.mode,
                request.horizon,
                request.parameters,
                request.fit_windows,
                request.free,
                progress,
            )
        else:
            model = learn_surface(
                df,
                request.start,
                request.end,
                request.minutes,
                request.mode,
                request.quantum,
                request.mintick,
                progress,
            )
            model_id = uuid.uuid4().hex
            with LOCK:
                if len(SURFACE_MODELS) >= 20:
                    del SURFACE_MODELS[next(iter(SURFACE_MODELS))]
                SURFACE_MODELS[model_id] = model
            result = {"kind": "surface-learning", "model_id": model_id, "report": model["report"]}
        with LOCK:
            JOBS[job_id].update(
                status="complete", progress=100, message="Complete", result=result, version=version
            )
    except Exception as exc:
        with LOCK:
            JOBS[job_id].update(status="failed", message=str(exc))


@app.post("/api/surface-jobs/{kind}")
def start_surface_job(kind: str, request: SurfaceRequest):
    if kind not in ["fit", "learn"]:
        raise HTTPException(400, "Choose fit or learn")
    try:
        valid_surface_request(request)
        from .surface_bridge import selected_rows, make_config

        with LOCK:
            if any(j["status"] == "running" for j in JOBS.values()):
                raise ValueError("A job is already running. Wait for it to finish.")
            df = snapshot()
            version = VERSION
        d, g, _, _ = selected_rows(df, request.start, request.end, request.minutes, request.mode)
        make_config(request.parameters, len(g), request.horizon)
        if kind == "fit" and (
            not request.free
            or any(
                k not in ["push", "throw", "coupling", "damping", "dent_scale"]
                for k in request.free
            )
        ):
            raise ValueError("Choose valid parameters to fit")
        with LOCK:
            if any(j["status"] == "running" for j in JOBS.values()):
                raise ValueError("A job is already running")
            if len(JOBS) >= 20:
                del JOBS[next(iter(JOBS))]
            job_id = uuid.uuid4().hex
            JOBS[job_id] = {
                "status": "running",
                "progress": 0,
                "message": "Preparing selected-window snapshot",
                "version": version,
            }
        POOL.submit(run_surface_job, job_id, d, request, version, kind)
        return {"job_id": job_id}
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
