# Validation record

Validated in the build environment:

- Python 3.12 scientific/data/API suite: **42 tests passed on pandas 2.2 and 3.0**.
- Ruff code checks and Python formatting: passed.
- JavaScript syntax check: passed.
- Actual Chromium browser smoke: all seven pane families rendered without
  JavaScript errors; rectangle creation, undo/redo, zoom-coordinate anchoring,
  workspace save/restore, manual model training and final evaluation worked.
- Surface tests verify marked endpoints, no future-data influence, original level
  formulas, all 85 rungs, separate physics/learning behavior, pre-launch calibration
  and newest-path holdout. Browser integration tests exercise window controls,
  three surface views, actual fitting/applying, manual learning and saved selection.
- Updated workflow starts empty, enables analysis after selection, labels exact
  NY endpoints/candle count, and colors the selected chart region.
- Time tests cover NY CSV defaults, winter/summer offsets, live tick/candle
  comparisons and retaining the original dates of stale market data.
- 390-pixel mobile viewport: no horizontal page overflow.
- 100,000-bar synthetic import loaded in Chromium without errors. A full-range
  canvas repaint took approximately 21 ms in this environment after suppressing
  subpixel window separators; this is a single environment measurement, not a
  universal performance guarantee.
- Desktop and mobile layouts were visually reviewed. Adding the surface
  pane retains the rendered transforms; this regression is browser-tested.
- Python wheel build succeeded with all vendored engine modules and static assets.

Tests use deterministic synthetic OHLCV data. These results confirm application
behavior, not real-market predictive accuracy. MT5 integration cannot be verified
on the Linux build environment; the platform guard and error response are tested.
The Windows launcher still needs a first run on the target machine.

A Starlette/httpx compatibility deprecation was emitted by the installed test
client version; it did not affect any test result. The runtime uses normal HTTP
and does not depend on that test-client adapter.

Selection regression checks cover older-window visibility after double-click,
initial reload and live data reload; saved selection restoration; right-click
preview/confirmation; direct chart picking; actual selected-source wavelet data;
and white-only restoration of legacy workspace settings. The API previews both
complete and incomplete candle windows with exact NY boundaries.

LumenSpace 0.2.1 package build passed. The launcher reports an occupied port
before opening a browser, preventing an older running app from being mistaken
for the updated build. Dark-mode controls and CSS are removed; legacy theme
settings restore into the white interface.

LumenSpace 0.2.2 fixes datetime export for second, millisecond, microsecond and
nanosecond storage resolutions. Bar and transform timestamps are explicitly
converted to Unix seconds. This includes cached CSV data reparsed at application
startup. Aggregated chart candles resolve to an actual M1 source candle inside
their bucket, including a first bucket beginning before the import's first row.
GitHub CI tests both pandas 2.x and 3.x.

0.2.3 browser checks verify one-shot drawing tools, pointer price/time tracking,
analysis coordinate readouts, surface-only control visibility, default reset
clearing the fit and rendered surface, explicit reapply and pane removal.
Four requested LinkedIn screenshots were captured from the running app using
synthetic demo data.

## Version 1.0

44 Python tests pass, including exact recurrence row-count and delayed-candle
provenance tests, stable tie ordering and self-match exclusion. The v1 browser
regression verifies four permanent full-width charts, row/column mapping, chart
navigation, linked cursors, surface reset/reapply, one-shot drawing, workspace
migration/restore and mobile layout. The screenshots in marketing reflect v1.0
using synthetic demo data. Earlier validation entries describe previous versions.

Additional v1 regression checks passed for surface fit/apply/learning, NY CSV import
and cache restart, right-click/window selection, drawings and training/evaluation.
Editable installation of lumenspace-terminal 1.0.0 succeeds with marketing excluded
from Python package discovery.

## Version 1.0.1

47 Python tests pass, including 14- and 42-candle forecast-source provenance
and API cutoff/source-boundary tests. Browser checks cover independent layer
toggles and restoration, continuous own-axis crosshair values between points,
sticky desktop rails, actual handle dragging and saved chart heights, and actual
Configure & train runs from both 14- and 42-candle windows.
