# Feature status against the supplied brief

This is a complete runnable **v1.0.2 research project**, not a claim that every
advanced item in the broad terminal brief is finished.

| Area | Delivered | Remaining / limits |
| --- | --- | --- |
| CSV | Picker, drop zone, path field, delimiter/header detection, UTC normalization, bad-row/duplicate/gap report | 32 MiB import cap; no interactive row repair |
| MT5 | Official adapter, history, five-second live polling, reconnect attempts, faded forming bar, closed-bar exclusion, merged SQLite history | Windows integration requires testing on a logged-in user terminal; tick data and WebSocket streaming not implemented |
| Windows | NY chart/selection clock with date-specific DST, live clock/feed-age comparison, NY CSV default/note, NY-clock alignment or rolling, 14m/42m bands, full-window checks, source-interval validation | Exact custom start/end selection (6–512 M1 bars); alignment remains NY; daily fragments skipped |
| Main chart | Candles/line, volume, wheel zoom, pan (including free space to scroll into the future, with future time ticks, crosshair and drawings), bottom-anchored selection label, price-axis scaling, crosshair/OHLC, timeframe aggregation, display timezone, linear/log/percent, white only, independent overlay controls, resizable chart | Heikin-Ashi/bar styles absent; extreme zoom-out uses visual stride |
| Panes | Four permanent full-width charts, vertical resize, 2D/3D views, Pan/Zoom/Reset view, linked time/state hovers, choose-window → automatic-analysis workflow, colored exact source candles, selected-range recomputation, saved workspace JSON | Price zoom does not force all transform axes to zoom; spatial-domain drawing overlays not included; single active data source |
| Drawings | Lines/rays/H/V/rectangles/text, coordinate anchoring, labels, snap, move/second-handle resize, style, lock, delete, undo/redo, per-symbol/timeframe save, JSON | Fibonacci/channel tools and first-handle resizing not included |
| Phase space | 2D/3D trajectory, time color/provenance, tau/dimension parameters, MI/FNN helpers, trajectory length | MI/FNN needs ≥100 bars; only first 3 coordinates rendered; Lyapunov/correlation dimension and configurable trails deferred |
| Recurrence | Fixed target recurrence rate, linked map and row-density histogram, top-five separated candle zones, paired row/column source highlighting, RR/DET/laminarity/diagonal length/entropy | Fixed epsilon/max-distance threshold modes not included; no significance claims |
| Wavelet | CWT Morlet/Mexican-hat/complex Morlet, time/period energy, approximate edge guide, DWT components | MODWT, rigorous COI/significance and denoised main-chart overlay deferred |
| Learning | Manual-start progress, selected 14/42-candle forecast inputs with earlier-history cutoff, selected features, Logistic/Ridge or ExtraTrees, next-window direction/range, 42m third-window features on M1, chronological validation, label purging, held-out test, 4 baselines, range baseline, confusion/calibration/importance, moving-block interval, export | One horizon per run, no level-first-hit target, model serialization or automated tuning; no paired significance claim; visual params separate from feature recipe |
| Surface | Original candle-surface engine, selectable source, 3D/heatmap/trajectory, chart scenario, explicit fit/report/apply, manual selected-window future-surface learning | Experimental deterministic scenario; ML requires a complete 14m/42m NY clock window; no automatic learning |
| GoldenShadow | Original ATR/shadow/Zeller algorithm, chart target overlays, exact 85-rung ladder, quantum/tick settings, JSON export | Reference levels; not probabilities or trade signals |
| Forecast | Direction/range panel plus separate surface scenario, asof provenance, stale-run detection | No stochastic price-path distribution; no automatic retraining |
| Packaging | One-command Python launch, retryable Windows setup, tests, lint, GitHub CI, documentation, ZIP | No signed desktop executable or installer |
| Phase 2 | Extension contracts documented | EMD/Hilbert, GAF/MTF and path signatures deferred |

## Validation boundary

Scientific and API tests run on Linux with synthetic fixtures. MT5 intentionally
returns an actionable platform error on Linux. A real CSV/live MT5 acceptance
record still needs to be produced on the user's Windows machine. Synthetic model
scores must not be presented as evidence of trading performance.

Legacy Fourier/Laplace/topology computations remain available internally for API compatibility; they are not workspace charts in version 1.0.
