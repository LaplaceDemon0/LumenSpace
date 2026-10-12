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
const port = 8877;
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
  await page.selectOption(
    "#savedWindow",
    await page.locator("#savedWindow option").nth(2).getAttribute("value"),
  );
  await page.waitForFunction(() => S.selection && S.goldenResult);
  await page.screenshot({
    path: path.join(root, "docs", "screenshot.png"),
    fullPage: true,
  });
  await page.waitForFunction(() => S.panes.length === 4 && S.panes.every(p => p.result && document.querySelector("#plot-"+p.id)?.data));
  assert.equal(await page.locator(".pane").count(), 4);
  // Draw, undo, redo; positions remain anchored through zoom.
  await page.click('[data-tool="rectangle"]');
  const box = await page.locator("#priceCanvas").boundingBox();
  await page.mouse.move(box.x + 200, box.y + 100);
  await page.mouse.down();
  await page.mouse.move(box.x + 380, box.y + 170, { steps: 5 });
  await page.mouse.up();
  assert.equal(await page.locator("#drawingCount").innerText(), "1");
  await page.click("#undo");
  assert.equal(await page.locator("#drawingCount").innerText(), "0");
  await page.click("#redo");
  assert.equal(await page.locator("#drawingCount").innerText(), "1");
  const before = await page.evaluate(() => JSON.stringify(S.drawings));
  await page.mouse.move(box.x + 300, box.y + 150);
  await page.mouse.wheel(0, -180);
  assert.equal(await page.evaluate(() => JSON.stringify(S.drawings)), before);
  await page.click("#saveWorkspace");
  assert.ok(await page.evaluate(() => localStorage.getItem("lumenspace.workspace")));
  // Actual manual training and evaluation, not a mocked completed state.
  await page.click("#clearSelection");
  await page.click("#openTraining");
  await page.selectOption("#trainHorizon", "14");
  await page.selectOption("#trainModel", "linear");
  await page.click("#startTraining");
  await page.waitForSelector("#openEvaluation", { timeout: 120000 });
  await page.click("#openEvaluation");
  assert.ok(
    (await page.locator("#modalBody").innerText()).includes("No transforms"),
  );
  assert.ok(
    (await page.locator("#modalBody").innerText()).includes("Confusion matrix"),
  );
  await page.click("#closeModal");
  // Saved workspaces restore their panes and drawings after reload.
  await page.reload();
  await page.waitForFunction(() => S.bars.length > 100);
  assert.equal(await page.locator("#drawingCount").innerText(), "1");
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
    "Browser smoke passed: four permanent charts, drawings, zoom anchoring, workspace persistence, training/evaluation and mobile overflow.",
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
