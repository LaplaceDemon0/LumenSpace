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
const port = 8880;
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
  assert.ok((await page.title()).includes("LumenSpace"));
  await page.click("#chooseWindow");
  await page.waitForFunction(
    () => document.querySelector("#savedWindow")?.options.length > 12,
  );
  await page.selectOption(
    "#savedWindow",
    await page.locator("#savedWindow option").nth(12).getAttribute("value"),
  );
  await page.waitForFunction(() => S.selection && S.goldenResult);
  const selected = await page.evaluate(() => S.selection);
  assert.ok(await page.evaluate(() => S.right < S.bars.length - 200));
  const assertVisible = async () =>
    assert.ok(
      await page.evaluate(
        () =>
          xOfTime(S.selection[0]) >= 14 &&
          xOfTime(S.selection[1] + 60) <= W - 74,
      ),
    );
  await assertVisible();
  const box = await page.locator("#priceCanvas").boundingBox();
  await page.mouse.dblclick(box.x + 100, box.y + 100);
  await assertVisible();
  assert.deepEqual(await page.evaluate(() => S.selection), selected);
  await page.evaluate(() => loadBars(false));
  await assertVisible();
  assert.ok(await page.evaluate(() => S.right < S.bars.length - 200));
  await page.evaluate(() => loadBars(true));
  await assertVisible();
  await page.evaluate(() => {
    const w = workspace();
    w.theme = "dark";
    localStorage.setItem("lumenspace.workspace", JSON.stringify(w));
  });
  await page.reload();
  await page.waitForFunction(() => S.selection && S.bars.length > 100);
  await assertVisible();
  assert.deepEqual(await page.evaluate(() => S.selection), selected);
  assert.equal(
    await page.evaluate(() =>
      getComputedStyle(document.body).getPropertyValue("--paper").trim(),
    ),
    "#fff",
  );
  await page.click("#openSettings");
  assert.equal(await page.locator("#paramTheme").count(), 0);
  await page.click("#closeModal");
  // Right click must not pan or change the source before confirmation.
  const before = await page.evaluate(() => [S.left, S.right, S.selection]);
  const point = await page.evaluate(() => ({
    x: xOfTime(S.selection[0] + 20 * 60),
    y: 120,
  }));
  const chart = await page.locator("#priceCanvas").boundingBox();
  await page.mouse.click(chart.x + point.x, chart.y + point.y, {
    button: "right",
  });
  await page.waitForSelector("#findCandleWindow");
  assert.deepEqual(
    await page.evaluate(() => [S.left, S.right, S.selection]),
    before,
  );
  await page.keyboard.press("Escape");
  assert.deepEqual(await page.evaluate(() => S.selection), selected);
  await page.mouse.click(chart.x + point.x, chart.y + point.y, {
    button: "right",
  });
  await page.waitForSelector("#findCandleWindow");
  await page.click("#findCandleWindow");
  await page.waitForSelector("#selectCandleWindow");
  assert.ok(
    (await page.locator("#chartContext").innerText()).includes(
      "42/42 closed M1",
    ),
  );
  await page.click("#selectCandleWindow");
  await page.waitForFunction(() =>
    document.querySelector("#chartContext").classList.contains("hidden"),
  );
  await assertVisible();
  assert.deepEqual(await page.evaluate(() => S.selection), selected);
  // Picking by a direct chart click and the subsequent double-click event stays put.
  await page.click("#chooseWindow");
  await page.click("#pickChartWindow");
  await page.mouse.click(chart.x + point.x, chart.y + point.y);
  await page.waitForFunction(() => !S.pickWindow);
  await page.waitForTimeout(250);
  await page.mouse.dblclick(chart.x + point.x, chart.y + point.y);
  await assertVisible();
  // The detected interval drives actual analysis.
  await page.waitForFunction(
    () => S.panes.find((p) => p.module === "wavelet")?.result,
  );
  assert.ok(
    await page.evaluate(() => {
      const p = S.panes.find((p) => p.module === "wavelet");
      return p.result.times.every(
        (t) => t >= S.selection[0] && t <= S.selection[1],
      );
    }),
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await sleep(400);
  assert.ok(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 2,
    ),
  );
  assert.deepEqual(errors, []);
  console.log(
    "LumenSpace regression passed: older-window viewport, double-click, data reload/live polling, white-only restore, right-click preview/confirmation, direct pick, actual selected-source analysis and mobile layout.",
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
