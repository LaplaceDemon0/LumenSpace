# LumenSpace

**A local price-research terminal.** Load M1 candles, mark a window, and study the
same candles through four linked views: **recurrence, wavelet, candle surface and
phase space**. Everything runs on your machine in a quiet white interface.



> LumenSpace is a research tool. It never places trades. Forecasts and surface
> scenarios are experimental, and the evaluation panel reports held-out results
> instead of claiming that any transform predicts price. Screenshots use seeded
> synthetic data. See [feature status](docs/STATUS.md) for scope and limits.

## Features

| Area | What you get |
| --- | --- |
| **Price chart** | Candles or line, volume, wheel zoom, drag pan, price-axis scaling, crosshair with NY time, linear/log/percent scale, 1/5/15/60-minute display, free space to scroll into the **future** |
| **Source window** | Pick a 14m or 42m New York clock window, an exact start/end, or drag any 6–512 M1 bars. Selected candles turn teal (two green tones for up/down) with a **"SELECTED · N M1 CANDLES"** label at the bottom, and candles after the window fade |
| **Recurrence** | Recurrence map, row-density histogram, RR/DET/laminarity/entropy. The five strongest rows map back to exact candles as R1–R5 zones on the price chart |
| **Wavelet** | Morlet / Mexican-hat / complex Morlet scalogram, power-by-period curve against an AR(1) red-noise bar, dominant cycle, energy bursts, crest/trough marks and a plain-language readout. Descriptive, not a forecast |
| **Candle surface** | The original candle-physics engine: 3D surface, height map or trajectory, a dashed scenario path on the price chart, parameter fitting, optional ML future surface |
| **GoldenShadow** | ATR / shadow / Zeller reference levels on the chart and the full 85-rung ladder (JSON export). Reference levels, not probabilities |
| **Phase space** | Delay-embedded trajectory in 2D/3D, τ and dimension controls, MI/FNN estimation |
| **Drawings** | Trend line, ray, horizontal, vertical, rectangle, text. Anchored to time and price, with snap, undo/redo and per-symbol save |
| **Forecast lab** | Next-window direction and range model (Logistic/Ridge or ExtraTrees) with chronological validation, purged labels, a held-out test, four baselines, calibration and feature importance |
| **Data** | CSV import (auto-detects format) and live MetaTrader 5 on Windows, cached in SQLite |

## Install and run

**Windows.** Install Python 3.12 with "Add python.exe to PATH". Extract the project,
then double-click `start-windows.bat`. The first run installs dependencies and opens
**http://127.0.0.1:8765**.

**macOS / Linux.**

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python run.py
```

For MT5 (Windows only) install the extra: `python -m pip install -e ".[mt5]"`.
No Node.js, CDN, API key or web font is needed. The app makes no external requests.

## Using LumenSpace

### 1. Load data
Open **Data sources**.
- **CSV:** drop a file, or give a local path. Choose the file's timezone (default
  New York). Check the import report: bad rows, duplicates and gaps are counted.
- **MT5:** enter the broker's exact symbol, pick M1, and connect. Enable live
  polling for a refresh every 5 seconds. The forming candle is faded and never used
  for analysis or training. Leave **Broker server time** on *Auto-detect*.
- **Demo:** *Load synthetic demo data* to try everything without a file.

### 2. Choose a source window
Click **Choose window** (or press **W**), then pick one of:
- a completed **14m / 42m New York clock window**,
- an exact start and end time (end exclusive),
- a window on the chart: **right-click a candle → Find the time window of this
  candle → Select & highlight this window**.

To mark a custom range press **S** and drag (6–512 closed M1 bars). The selected
candles are teal, outlined, and labeled at the bottom with their count. All four
analysis charts fill in automatically. Press **Esc** or **Clear selected range ×**
to start over.

### 3. Explore the linked charts
Recurrence, wavelet, surface and phase space are always on screen, full width and
vertically resizable. Each supports wheel zoom, Pan, Zoom and Reset view, and 2D/3D
where offered. Hover a state or time map to light up the matching candle on the
price chart. Open **Parameters** to change input series, preprocessing, τ,
dimension, recurrence rate, wavelet and price scale.

### 4. Run the surface and GoldenShadow workflow
1. Open **Surface parameters**: horizon (1–120 min), physics, shape, filters,
   GoldenShadow quantum and the symbol's tick size.
2. **Fit parameters** calibrates on completed paths that end before your window.
   Review the before/after error, then **Use fitted parameters & simulate**.
3. **Apply parameters & simulate** draws the surface and the dashed path on the
   price chart. Later candles never leak into an earlier launch.
4. Toggle **GoldenShadow levels**; **View 85-rung ladder** lists and exports them.
5. Optional **Start surface learning** trains a future surface from the marked
   14m/42m window only.

### 5. Train and evaluate (optional)
Open the Research desk, set horizon, model and features, then **Start training**.
It needs at least 60 complete labeled examples. The forecast range appears on the
price chart and can be shown or hidden with the **Forecast range** layer checkbox.
Choosing a different window clears the result so you can train again. Read the final-test accuracy and
block interval against the baselines and export the evaluation JSON.

### 6. Draw and save
Pick a drawing tool, click-drag on the chart, then double-click a drawing to set
colour, width or lock. **Save workspace** stores selection, parameters, layout and
drawings in the browser; Export/Import moves them as JSON.

## Price chart controls

| Action | How |
| --- | --- |
| Zoom | Mouse wheel |
| Pan | Drag the chart. **Drag left to move into the future**: the last candle can travel almost to the left edge, leaving a large empty area on the right |
| Jump to latest | **↦ Latest** or double-click with no selection (leaves ~35% free space on the right) |
| Focus the selected window | Double-click while a window is selected |
| Scale price | Drag the price axis on the right |
| Layers | Independent checkboxes for GoldenShadow, forecast path, **forecast range** (appears after a training run), recurrence levels and wavelet cycle |
| Resize | Drag the handle under the price chart (or focus it and use ↑/↓) |
| Crosshair | Shows NY time and price, also in the future area. Hover shows O/H/L/C |

Shortcuts: **V** cursor · **S** select range · **W** choose window · **Delete**
remove drawing · **Ctrl+Z / Ctrl+Y** undo/redo · **Esc** clear selection.

Drawings can be placed in the future area, so you can sketch targets and
projections ahead of the last candle.

## Data and time

CSV headers are auto-detected (`time,open,high,low,close,volume`, MT5
`<DATE> <TIME> …`, Unix seconds or milliseconds, comma/tab/semicolon). Headerless
files must use time/open/high/low/close[/volume] order. Imports are limited to
32 MiB. **Keep CSV times in New York time** or choose the real timezone on import;
ambiguous DST stamps are excluded and reported. CSV rows are assumed closed, so
remove a forming row from a live export.

MT5 candle stamps are the broker's wall clock, not UTC. Auto-detect compares the
newest tick to your PC's UTC clock and picks UTC, GMT+2/+3 with US DST, EU DST or a
fixed offset. The status line shows MT5 server time next to NY time so you can
check it against Market Watch. Window grids reset at New York midnight and use each
date's own EST/EDT offset.

## Research and leakage rules

- Features are computed inside each source window; model scaling is fitted on
  training folds only.
- The final chronological 20% is excluded from fitting; training labels that reach
  into validation/test windows are purged.
- Random, previous-direction, majority-class and no-transform baselines are
  reported. Intervals are moving-block bootstrap and are not significance tests.
- A forecast belongs to the run that made it and is flagged stale when new closed
  bars arrive.

## Development

```bash
python -m pip install -e ".[dev,topology]"
python -m pytest -q
ruff check .
```

GitHub Actions runs the tests and lint on Python 3.11–3.13 with pandas 2.x and 3.x.
Optional Playwright scripts are in `tests/*.cjs`; see their headers.
Docs: [architecture](docs/ARCHITECTURE.md), [status](docs/STATUS.md),
[validation](docs/VALIDATION.md), [references](docs/REFERENCES.md).

## Publish to GitHub

```bash
git init && git add . && git commit -m "LumenSpace"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/lumenspace.git
git push -u origin main
```

`.gitignore` keeps caches, virtual environments and secrets out. Review any CSV or
screenshots you add before publishing.

## Troubleshooting

- **MT5 unavailable:** use Windows, install the `mt5` extra, log in to the terminal
  and check the exact symbol in Market Watch.
- **Window/timeframe mismatch:** 14m/42m need M1 source history.
- **Not enough training examples:** choose a longer period or import more history.
- **Port 8765 in use:** close the old session, or run
  `python -m uvicorn terminal.app:app --host 127.0.0.1 --port 8766`.

## License

MIT. The candle-surface engine in `terminal/_vendor/csim` and the GoldenShadow Pine
source in `docs/vendor` keep their own licenses. Plotly and the scientific
dependencies keep theirs.
