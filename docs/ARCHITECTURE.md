# Architecture

The project intentionally avoids a separate frontend build pipeline. FastAPI
serves a static UI and the installed Plotly.js bundle; the main price chart is a
native canvas with time/price-coordinate drawings.

| File | Responsibility |
| --- | --- |
| `terminal/data.py` | DataSource protocol, CSV/MT5 adapters, normalization, windowing, OHLC aggregation |
| `terminal/transforms.py` | Transform registry, bounded computations and causal feature extraction |
| `terminal/embedding.py` | Histogram mutual information and false-nearest-neighbor helpers |
| `terminal/learning.py` | Targets, chronological purging, estimators, evaluation and snapshot forecasts |
| `terminal/app.py` | Loopback API, immutable snapshots, SQLite persistence and background jobs |
| `terminal/static/app.js` | Canvas rendering, coordinate drawings, cursor linking, dialogs, workspace persistence |
| `terminal/static/style.css` | Design tokens, white theme and responsive layouts |
| `run.py` | Browser + loopback server launcher |

## Extension contracts

A data source returns `(normalized_dataframe, import_report)`. The dataframe has
UTC `time`, `open`, `high`, `low`, `close`, `volume`, and boolean `closed` fields.
Downstream code never imports MT5 directly. Add adapters conforming to DataSource.

Transform rendering and training features are separate: `compute(df, module,
params)` creates bounded rich results; `metrics(df, selected)` creates a stable
causal feature recipe. Extend MODULES and the two functions, then add a frontend
renderer and tests. A plugin packaging/registration API is a future improvement;
the current registry has explicit, inspectable dispatch.

`estimators(name)` returns a classifier/regressor pair. Extend it for other
scikit-learn-compatible models. Preserve class-probability and fit/holdout rules.
Do not introduce global normalization, shuffled splits or transforms spanning a
label boundary.

## Concurrency and persistence

Sync transform endpoints execute in FastAPI's worker thread pool. Explicit ML
jobs use a bounded executor and progress polling. Immutable snapshots isolate a
run from concurrent imports/MT5 updates. Training is capped at 20,000 bars;
transform ranges at 512 and topology point clouds at 96. This bounds expensive
work but is not a CPU/process isolation system.

SQLite stores the current source dataset and import report. Repeated MT5 polls
merge same-symbol/same-interval history and retain up to 500,000 bars. Different
sources replace the active cache. Browser workspaces and drawings are localStorage
JSON; evaluation exports are explicit downloads. Models are not serialized in v0.2.

The server is a single-user loopback service; it has no account system or public
hosting configuration. Same-origin guards reject cross-origin requests. Keep the
launcher bound to 127.0.0.1. It can read a user-entered CSV path, so it is not an
appropriate unauthenticated public API.

## Time identity

Bar timestamps denote opens. A window's `asof` timestamp denotes its closing
instant. Delay embeddings use forward arrays internally but assign each vector
its latest constituent timestamp. Thus no vector at time t reads beyond t.
Time-axis plot coordinates remain UTC; tick labels and price readouts use the
selected display timezone. Spatial transforms have no meaningful global time
axis: state/pixel hovers provide linked provenance instead.

## UI rendering

Only visible candles are drawn. Large visible ranges use a pixel-dependent stride
for display; original data is retained and never reduced for analysis. This is a
performance compromise, not an OHLC aggregation of skipped candles. Use a coarser
display timeframe to inspect an entire large history faithfully.

Window separators are hidden when their spacing becomes smaller than five pixels.

Main-chart zoom changes the price view. Transform computation follows the selected
range or completed window; it does not recalculate on every wheel event. Hover
linking is throttled. Time-range selection is the explicit recomputation action.
All drawings retain source timestamps and real prices across zoom/scale changes.

## Surface integration

`surface_bridge.py` validates exact M1 source endpoints and cuts engine history
at the selected end. Earlier history supports launch scaling and ATR; sources
come only from the marked range. `_vendor/csim` retains the original numerical
engine; fitting adds progress callbacks without changing the optimization.
`static/integration.js` provides shared range controls, surface views, explicit
fit/apply/learn jobs and GoldenShadow overlays. Calibration paths finish before
the current launch. Surface learning receives only the marked clock window and
never fits launch velocity, acceleration, dents or motion parameters.
