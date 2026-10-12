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
const port = 8881;
const root = path.resolve(__dirname, "..");
let server = spawn(
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
  await page.click("#openData");
  const base = Date.parse("2025-07-01T00:01:00Z");
  const rows = ["time,open,high,low,close,volume"];
  for (let i = 0; i < 600; i++) {
    const local = new Date(base + i * 60000)
      .toISOString()
      .slice(0, 19)
      .replace("T", " ");
    const price = 2600 + Math.sin(i / 10);
    rows.push(`${local},${price},${price + 1},${price - 1},${price + 0.1},100`);
  }
  await page.setInputFiles("#csvFile", {
    name: "history-ny.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(rows.join("\n")),
  });
  await page.click("#importCSV");
  await page.waitForFunction(() => S.bars.length === 600);
  const expected = Date.parse("2025-07-01T04:01:00Z") / 1000;
  assert.equal(await page.evaluate(() => S.bars[0].time), expected);
  // Restart Python so timestamps are reparsed from the actual SQLite cache under pandas 3.
  await new Promise((resolve) => {
    server.once("exit", resolve);
    server.kill();
  });
  server = spawn(
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
  for (let i = 0; i < 60; i++) {
    try {
      if ((await fetch(`http://127.0.0.1:${port}/api/bars`)).ok) break;
    } catch {}
    await sleep(250);
  }
  await page.reload();
  await page.waitForFunction(() => S.bars.length === 600);
  assert.equal(await page.evaluate(() => S.bars[0].time), expected);
  // Real right-click on an M1 chart candle after reloading the cached CSV.
  await page.evaluate(() => {
    S.left = 84;
    S.right = 160;
    paint();
  });
  let box = await page.locator("#priceCanvas").boundingBox();
  let x = await page.evaluate(() => xOfIndex(120));
  await page.mouse.click(box.x + x, box.y + 120, { button: "right" });
  await page.click("#findCandleWindow");
  await page.waitForSelector("#selectCandleWindow");
  assert.equal(await page.locator("#selectCandleWindow").isDisabled(), false);
  await page.click("#selectCandleWindow");
  await page.waitForFunction(() => S.selection);
  assert.ok(await page.evaluate(() => S.selection[0] > 1e9));
  await page.waitForFunction(
    () => S.panes.find((p) => p.module === "wavelet")?.result,
  );
  assert.ok(
    await page.evaluate(() =>
      S.panes[0].result.times.every(
        (t) => t >= S.selection[0] && t <= S.selection[1],
      ),
    ),
  );
  // First 5m bucket opens at midnight, while CSV begins at 00:01: it must resolve to its own source.
  await page.selectOption("#timeframe", "5");
  await page.waitForFunction(() => S.tf === 5 && S.bars.length < 130);
  await page.evaluate(() => {
    S.left = 0;
    S.right = 40;
    paint();
  });
  box = await page.locator("#priceCanvas").boundingBox();
  x = await page.evaluate(() => xOfIndex(0));
  await page.mouse.click(box.x + x, box.y + 120, { button: "right" });
  await page.click("#findCandleWindow");
  await page.waitForSelector("#selectCandleWindow");
  assert.ok(
    !(await page.locator("#chartContext").innerText()).includes("outside"),
  );
  assert.ok(
    (await page.locator("#chartContext").innerText()).includes("Incomplete"),
  );
  assert.equal(await page.locator("#selectCandleWindow").isDisabled(), true);
  await page.keyboard.press("Escape");
  // A complete aggregate bucket resolves and its highlighted interval can run analysis.
  x = await page.evaluate(() => xOfIndex(24));
  await page.mouse.click(box.x + x, box.y + 120, { button: "right" });
  await page.click("#findCandleWindow");
  await page.waitForSelector("#selectCandleWindow");
  assert.equal(await page.locator("#selectCandleWindow").isDisabled(), false);
  await page.click("#selectCandleWindow");
  await page.waitForFunction(
    () => S.selection && S.panes.every((p) => p.result),
  );
  assert.deepEqual(errors, []);
  console.log(
    "CSV/cache browser passed under pandas 3: actual NY CSV import, Python cache restart, correct chart dates, M1 right-click, selected-source wavelet, incomplete edge bucket and complete 5m bucket selection.",
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
