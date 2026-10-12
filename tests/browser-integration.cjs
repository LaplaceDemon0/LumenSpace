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
const port = 8878;
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
  assert.equal(await page.locator("#addSelectedAnalysis").isDisabled(), true);
  assert.ok(await page.locator("#surfaceDesk").isHidden());
  await page.click("#chooseWindow");
  await page.waitForFunction(
    () => document.querySelector("#savedWindow")?.options.length > 2,
  );
  const value = await page
    .locator("#savedWindow option")
    .nth(2)
    .getAttribute("value");
  await page.selectOption("#savedWindow", value);
  await page.waitForFunction(
    () => S.selection && S.goldenResult && S.panes.every((p) => p.result),
  );
  assert.equal(await page.locator("#addSelectedAnalysis").isDisabled(), false);
  assert.ok(
    (await page.locator("#chosenWindowTitle").innerText()).endsWith("NY"),
  );
  assert.ok(
    (await page.locator("#chosenWindowDetail").innerText()).includes(
      "42 closed M1",
    ),
  );
  for (const module of ["phase", "wavelet"]) {
    await page.waitForFunction(
      (module) => S.panes.find((p) => p.module === module)?.result,
      module,
    );
  }
  const selected = await page.evaluate(() => S.selection);
  assert.equal(selected[1] - selected[0], 41 * 60);
  await page.waitForFunction(
    () => S.panes.find((p) => p.module === "surface")?.result,
  );
  await page.click("#viewGolden");
  assert.equal(await page.locator("#modalBody tbody tr").count(), 85);
  await page.click("#closeModal");
  await page.click("#surfaceParameters");
  await page.fill("#surface-horizon", "8");
  await page.click("#saveSurfaceParameters");
  await page.click("#applySurface");
  await page.waitForFunction(
    () =>
      S.surfaceResult && document.querySelector('[id^="plot-surface-"]')?.data,
    {},
    { timeout: 60000 },
  );
  assert.equal(await page.evaluate(() => S.surfaceResult.source_bars), 42);
  const id = await page.evaluate(
    () => S.panes.find((p) => p.module === "surface").id,
  );
  for (const view of ["heatmap", "trajectory", "3d"]) {
    await page.selectOption("#" + id + " select", view);
    await page.waitForFunction(
      ({ id, view }) =>
        document.querySelector("#plot-" + id).data[0].type ===
        (view === "heatmap"
          ? "heatmap"
          : view === "3d"
            ? "surface"
            : "scatter"),
      { id, view },
    );
  }
  await page.click("#fitSurface");
  await page.fill("#fitWindowCount", "2");
  await page.uncheck("[name=fitParameter][value=throw]");
  await page.click("#startSurfaceFit");
  await page.waitForSelector("#applyFittedParameters", { timeout: 120000 });
  assert.ok(await page.evaluate(() => S.surfaceFit.holdout));
  await page.click("#applyFittedParameters");
  await page.waitForFunction(
    () => !document.querySelector("#applySurface").disabled && S.surfaceResult,
  );
  const physics = await page.evaluate(() => JSON.stringify(S.surfaceParams));
  await page.click("#learnSurface");
  await page.waitForFunction(() => S.surfaceModelId, {}, { timeout: 120000 });
  assert.equal(await page.evaluate(() => S.useSurfaceML), false);
  assert.equal(
    await page.evaluate(() => JSON.stringify(S.surfaceParams)),
    physics,
  );
  await page.check("#surfaceMLToggle");
  await page.click("#applySurface");
  await page.waitForFunction(
    () => !document.querySelector("#applySurface").disabled && S.surfaceResult,
  );
  assert.equal(await page.evaluate(() => S.useSurfaceML), true);
  await page.waitForFunction(() =>
    S.panes.every((p) => document.querySelector("#plot-" + p.id)?.data),
  );
  await page.click("#saveWorkspace");
  await sleep(5500);
  await page.screenshot({
    path: path.join(root, "docs", "screenshot.png"),
    fullPage: true,
  });
  await page.reload();
  await page.waitForFunction(() => S.selection && S.surfaceResult);
  assert.deepEqual(await page.evaluate(() => S.selection), selected);
  assert.equal(await page.evaluate(() => S.useSurfaceML), false);
  await page.click("#clearSelection");
  await page.waitForFunction(() => !S.selection && S.surfaceModelId === null);
  await page.setViewportSize({ width: 390, height: 844 });
  await sleep(400);
  assert.ok(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 2,
    ),
  );
  await page.screenshot({
    path: path.join(root, "docs", "screenshot-mobile.png"),
    fullPage: true,
  });
  assert.deepEqual(errors, []);
  console.log(
    "Surface browser passed: marked window, linked maps, 85-rung levels, three views, real fit/apply, manual surface learning, physics preservation, workspace restore, mobile layout.",
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
