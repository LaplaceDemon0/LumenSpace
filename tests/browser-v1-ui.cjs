/**
 * Optional end-to-end verification (Node.js is needed only for this test):
 * npm install --no-save playwright
 * npx playwright install chromium
 * node tests/browser-smoke.cjs
 *
 * The script starts/stops its own local Python server. BROWSER_EXECUTABLE_PATH
 * and BROWSER_ARGS can optionally point to a preinstalled Chromium build.
 */
const assert = require("node:assert/strict");
const { spawn } = require("node:child_process");
const path = require("node:path");
const { chromium } = require("playwright");
const port = 8882;
const root = path.resolve(__dirname, "..");
const server = spawn(
  process.env.PYTHON || "python",
  [
    "-m",
    "uvicorn",
    "terminal.app:app",
    "--host",
    "127.0.0.1",
    "--port",
    String(port),
  ],
  { cwd: root, stdio: "ignore" },
);
let browser;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
(async () => {
  for (let i = 0; i < 60; i++) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/bars`);
      if (response.ok) break;
    } catch {}
    await sleep(250);
  }
  browser = await chromium.launch({
    headless: true,
    executablePath: process.env.BROWSER_EXECUTABLE_PATH || undefined,
    args: process.env.BROWSER_ARGS
      ? JSON.parse(process.env.BROWSER_ARGS)
      : ["--no-sandbox", "--enable-unsafe-swiftshader"],
  });
  const page = await browser.newPage({
    viewport: { width: 1512, height: 1050 },
  });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`http://127.0.0.1:${port}`);
  await page.waitForFunction(
    () =>
      S.bars.length > 100 &&
      document.querySelector("#nyFeedStatus").textContent,
  );
  assert.equal(await page.locator(".pane").count(), 4);
  assert.ok(await page.locator("#surfaceDesk").isHidden());
  await page.evaluate(() => post("/api/demo", {}));
  await page.reload();
  await page.waitForFunction(() => S.bars.length === 6000);
  await page.click("#chooseWindow");
  await page.waitForFunction(
    () => document.querySelector("#savedWindow")?.options.length > 2,
  );
  await page.selectOption(
    "#savedWindow",
    await page.locator("#savedWindow option").nth(2).getAttribute("value"),
  );
  await page.waitForFunction(
    () =>
      S.selection &&
      S.panes.length === 4 &&
      S.panes.every(
        (p) => p.result && document.querySelector("#plot-" + p.id)?.data,
      ),
  );
  assert.deepEqual(await page.evaluate(() => S.panes.map((p) => p.module)), [
    "recurrence",
    "wavelet",
    "surface",
    "phase",
  ]);
  assert.equal(await page.locator('[data-action="close"]').count(), 0);
  assert.ok(await page.locator("#surfaceDesk").isVisible());
  const width = (await page.locator(".price-card").boundingBox()).width;
  for (const el of await page.locator(".pane").all()) {
    const box = await el.boundingBox();
    assert.ok(Math.abs(box.width - width) < 2);
    assert.ok(box.height >= 440);
  }
  const recurrence = await page.evaluate(
    () => S.panes.find((p) => p.module === "recurrence").id,
  );
  const row = await page.evaluate(
    () =>
      S.panes.find((p) => p.module === "recurrence").result.potential_levels[0],
  );
  assert.ok(row.count > 0);
  await page.evaluate((id) => {
    const p = S.panes.find((p) => p.id === id),
      r = p.result;
    document.querySelector("#plot-" + id).emit("plotly_hover", {
      points: [
        {
          x: new Date(r.x[7] * 1000).toISOString(),
          y: new Date(r.y[12] * 1000).toISOString(),
          z: r.z[12][7],
        },
      ],
    });
  }, recurrence);
  assert.ok(
    (await page.locator("#readout-" + recurrence).innerText()).includes("NY"),
  );
  assert.equal(
    await page.evaluate(() => S.bars[S.cursor].time),
    await page.evaluate(() => S.panes[0].result.y[12]),
  );
  assert.equal(await page.evaluate(() => S.linkedTimes.length), 2);
  assert.ok(
    (await page.locator("#metrics-" + recurrence).innerText()).includes(
      "matches",
    ),
  );
  await page.click("#" + recurrence + ' [data-action="zoom"]');
  assert.equal(
    await page.evaluate(
      (id) => document.querySelector("#plot-" + id).layout.dragmode,
      recurrence,
    ),
    "zoom",
  );
  await page.click("#" + recurrence + ' [data-action="pan"]');
  await page.click("#" + recurrence + ' [data-action="home"]');
  assert.equal(
    await page.evaluate(
      (id) => document.querySelector("#plot-" + id).layout.dragmode,
      recurrence,
    ),
    "pan",
  );
  // Exercise real Plotly mouse events, wheel zoom and drag panning.
  const recPlot = page.locator("#plot-" + recurrence);
  await recPlot.scrollIntoViewIfNeeded();
  const plotBox = await recPlot.boundingBox();
  const size = await page.evaluate(
    (id) => document.querySelector("#plot-" + id)._fullLayout._size,
    recurrence,
  );
  const px = plotBox.x + size.l + size.w * 0.35,
    py = plotBox.y + size.t + size.h * 0.45;
  await page.mouse.move(px, py);
  await sleep(200);
  assert.equal(await page.evaluate(() => S.linkedTimes.length), 2);
  const originalRange = await page.evaluate(
    (id) => document.querySelector("#plot-" + id).layout.xaxis.range,
    recurrence,
  );
  await page.mouse.wheel(0, -160);
  await sleep(250);
  const zoomedRange = await page.evaluate(
    (id) => document.querySelector("#plot-" + id).layout.xaxis.range,
    recurrence,
  );
  assert.notDeepEqual(zoomedRange, originalRange);
  await page.mouse.down();
  await page.mouse.move(px + 65, py, { steps: 6 });
  await page.mouse.up();
  await sleep(200);
  assert.notDeepEqual(
    await page.evaluate(
      (id) => document.querySelector("#plot-" + id).layout.xaxis.range,
      recurrence,
    ),
    zoomedRange,
  );
  await page.click("#" + recurrence + ' [data-action="home"]');
  // Row histogram hover maps its source candle, without treating match counts as time.
  await page.evaluate((id) => {
    const p = S.panes.find((p) => p.id === id),
      row = p.result.row_scores[4],
      el = document.querySelector("#plot-" + id);
    el.emit("plotly_hover", {
      points: [
        {
          x: row.count,
          y: new Date(row.time * 1000).toISOString(),
          customdata: row.time,
          data: { xaxis: "x2" },
        },
      ],
    });
  }, recurrence);
  assert.equal(
    await page.evaluate(() => S.bars[S.cursor].time),
    await page.evaluate(() => S.panes[0].result.row_scores[4].time),
  );
  assert.ok(
    (await page.locator("#readout-" + recurrence).innerText()).includes(
      "Matches",
    ),
  );
  await page.evaluate(() => {
    const p = S.panes.find((p) => p.module === "phase");
    document.querySelector("#plot-" + p.id).emit("plotly_hover", {
      points: [
        {
          x: p.result.points[5][0],
          y: p.result.points[5][1],
          customdata: p.result.point_times[5],
        },
      ],
    });
  });
  assert.equal(
    await page.evaluate(() => S.bars[S.cursor].time),
    await page.evaluate(
      () => S.panes.find((p) => p.module === "phase").result.point_times[5],
    ),
  );
  // A price-chart cursor is reflected into time maps, surface, and phase state.
  await page.evaluate(() => linkCursor(S.panes[0].result.x[8]));
  assert.ok(
    await page.evaluate(() =>
      S.panes
        .filter((p) => ["wavelet", "surface"].includes(p.module))
        .every((p) =>
          document
            .querySelector("#plot-" + p.id)
            .layout.shapes.some((s) => s.name === "linked-cursor"),
        ),
    ),
  );
  // Continuous crosshair reports its own axes even between plotted points.
  const phaseId = await page.evaluate(
    () => S.panes.find((p) => p.module === "phase").id,
  );
  const phasePlot = page.locator("#plot-" + phaseId);
  await phasePlot.scrollIntoViewIfNeeded();
  const phaseBox = await phasePlot.boundingBox();
  const phaseSize = await page.evaluate(
    (id) => document.querySelector("#plot-" + id)._fullLayout._size,
    phaseId,
  );
  await page.mouse.move(
    phaseBox.x + phaseSize.l + phaseSize.w * 0.35,
    phaseBox.y + phaseSize.t + phaseSize.h * 0.25,
  );
  await sleep(150);
  const ownY = await page.locator("#plot-" + phaseId + " .chip-y").innerText();
  assert.ok(ownY.length > 0);
  await page.mouse.move(
    phaseBox.x + phaseSize.l + phaseSize.w * 0.35,
    phaseBox.y + phaseSize.t + phaseSize.h * 0.65,
  );
  await sleep(150);
  assert.notEqual(
    await page.locator("#plot-" + phaseId + " .chip-y").innerText(),
    ownY,
  );
  assert.ok(
    (await page.locator("#readout-" + phaseId).innerText()).includes(
      "Next state",
    ),
  );
  // Rails stay pinned while the user explores lower charts.
  assert.ok(Math.abs((await page.locator(".tool-rail").boundingBox()).y) < 2);
  assert.ok(Math.abs((await page.locator(".inspector").boundingBox()).y) < 2);
  // Independently controllable price overlays do not clear analysis results.
  await page.uncheck("#goldenToggle");
  await page.uncheck("#pathToggle");
  await page.uncheck("#recurrenceToggle");
  assert.deepEqual(
    await page.evaluate(() => [
      S.goldenEnabled,
      S.pathEnabled,
      S.recurrenceEnabled,
    ]),
    [false, false, false],
  );
  assert.ok(await page.evaluate(() => S.panes.every((p) => p.result)));
  await page.check("#goldenToggle");
  await page.check("#pathToggle");
  await page.check("#recurrenceToggle");
  await page.waitForFunction(() => S.goldenResult);
  // Price card grows via an actual drag on its explicit handle.
  const resize = page.locator(".price-resize-handle");
  await resize.scrollIntoViewIfNeeded();
  const resizeBox = await resize.boundingBox();
  const oldHeight = await page
    .locator(".canvas-wrap")
    .evaluate((el) => el.getBoundingClientRect().height);
  await page.mouse.move(resizeBox.x + resizeBox.width * 0.5, resizeBox.y + 10);
  await page.mouse.down();
  await page.mouse.move(
    resizeBox.x + resizeBox.width * 0.5,
    resizeBox.y + 130,
    { steps: 6 },
  );
  await page.mouse.up();
  assert.ok(
    (await page
      .locator(".canvas-wrap")
      .evaluate((el) => el.getBoundingClientRect().height)) >
      oldHeight + 100,
  );
  // One-shot drawing and reset remain supported with permanent charts.
  await page.click('[data-tool="line"]');
  await page.locator("#priceCanvas").scrollIntoViewIfNeeded();
  const chart = await page.locator("#priceCanvas").boundingBox();
  await page.mouse.move(chart.x + 220, chart.y + 160);
  await page.mouse.down();
  await page.mouse.move(chart.x + 420, chart.y + 120);
  await page.mouse.up();
  assert.equal(await page.evaluate(() => S.tool), "cursor");
  await page.evaluate(() => {
    S.surfaceParams.push = 0.3;
    S.surfaceFit = { parameters: { push: 0.3 } };
  });
  await page.click("#resetSurface");
  assert.equal(await page.evaluate(() => S.surfaceResult), null);
  assert.equal(await page.evaluate(() => S.surfaceParams.push), 1);
  await page.click("#applySurface");
  await page.waitForFunction(
    () => S.surfaceResult && !document.querySelector("#applySurface").disabled,
  );
  for (const count of [14, 42]) {
    await page.evaluate((count) => {
      S.window = count;
      S.selection = [S.bars[5500].time, S.bars[5500 + count - 1].time];
      updateSelection();
      focusMarkedWindow();
      refreshPanes();
    }, count);
    await page.waitForFunction(() => S.panes.every((p) => p.result));
    await page.click("#openTraining");
    assert.equal(
      await page.locator("#trainHorizon").inputValue(),
      String(count),
    );
    assert.equal(await page.locator("#trainHorizon").isDisabled(), true);
    await page.selectOption("#trainModel", "linear");
    await page.click("#startTraining");
    await page.waitForFunction(
      () =>
        !S.job &&
        S.forecast?.result?.forecast?.source_bars ===
          Math.round((S.selection[1] - S.selection[0]) / 60) + 1,
      {},
      { timeout: 120000 },
    );
    const forecast = await page.evaluate(() => S.forecast.result.forecast);
    assert.equal(forecast.source_bars, count);
    assert.equal(
      forecast.source_end,
      await page.evaluate(() => S.selection[1]),
    );
    assert.equal(forecast.asof, forecast.source_end + 60);
    assert.equal(forecast.training_cutoff, forecast.source_end);
  }
  // Legacy workspace extras are dropped and missing charts restored without losing selected range.
  await page.evaluate(() => {
    S.panes.push({ id: "old-fourier", module: "fourier", view: "spectrum" });
    makePanes();
  });
  assert.equal(await page.locator(".pane").count(), 4);
  await page.evaluate(() => refreshPanes());
  await page.waitForFunction(() =>
    S.panes.every(
      (p) => p.result && document.querySelector("#plot-" + p.id)?.data,
    ),
  );
  await page.uncheck("#goldenToggle");
  await page.uncheck("#pathToggle");
  await page.uncheck("#recurrenceToggle");
  const savedHeight = await page
    .locator(".canvas-wrap")
    .evaluate((el) => el.getBoundingClientRect().height);
  await page.click("#saveWorkspace");
  const selected = await page.evaluate(() => S.selection);
  await page.reload();
  await page.waitForFunction(
    () =>
      S.panes.length === 4 &&
      S.panes.every(
        (p) => p.result && document.querySelector("#plot-" + p.id)?.data,
      ),
  );
  assert.deepEqual(await page.evaluate(() => S.selection), selected);
  assert.deepEqual(
    await page.evaluate(() => [
      S.goldenEnabled,
      S.pathEnabled,
      S.recurrenceEnabled,
    ]),
    [false, false, false],
  );
  assert.equal(
    await page
      .locator(".canvas-wrap")
      .evaluate((el) => el.getBoundingClientRect().height),
    savedHeight,
  );
  await page.check("#goldenToggle");
  await page.check("#pathToggle");
  await page.check("#recurrenceToggle");
  await page.waitForFunction(() => S.goldenResult);
  await page.setViewportSize({ width: 390, height: 844 });
  await sleep(300);
  assert.ok(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  );
  await page.setViewportSize({ width: 1600, height: 1000 });
  await sleep(300);
  await page.evaluate(() =>
    document.querySelector("#toast").classList.add("hidden"),
  );
  await page.locator(".price-card").screenshot({
    path: path.join(root, "marketing", "01-selected-window.png"),
  });
  const surface = await page.evaluate(
    () => S.panes.find((p) => p.module === "surface").id,
  );
  await page.locator("#" + surface).screenshot({
    path: path.join(root, "marketing", "02-candle-surface.png"),
  });
  await page.locator("#panes").screenshot({
    path: path.join(root, "marketing", "03-linked-analysis.png"),
  });
  await page.screenshot({
    path: path.join(root, "marketing", "04-workspace.png"),
    fullPage: true,
  });
  assert.deepEqual(errors, []);
  console.log(
    "Version 1.0.1 browser passed: independent overlays and persisted sizes, own-axis continuous crosshairs, sticky rails, real chart resizing, 14/42-candle training cutoffs, linked views and mobile layout.",
  );
})()
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  })
  .finally(async () => {
    if (browser) await browser.close();
    server.kill();
  });
