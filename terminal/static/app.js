/* LumenSpace terminal. Native canvas for price/drawings; Plotly for research spaces. */
"use strict";
const $ = (id) => document.getElementById(id);
const names = {
  phase: "Phase space",
  recurrence: "Recurrence",
  wavelet: "Wavelet",
  surface: "Candle surface",
};
const descriptions = {
  phase: "Delay-embedded price trajectories.",
  recurrence: "Repeated states and diagonal structure.",
  wavelet: "Energy across time and scale.",
  surface: "Original candle physics, fitted parameters and future scenarios.",
};
const S = {
  bars: [],
  version: 0,
  report: {},
  symbol: "XAUUSD",
  tf: 1,
  window: 42,
  bands: 42,
  mode: "aligned",
  timezone: "America/New_York",
  params: {
    source: "close",
    preprocessing: "zscore",
    tau: 1,
    dimension: 3,
    wavelet: "morl",
    taper: "hann",
    recurrence_rate: 0.1,
  },
  panes: [],
  left: 0,
  right: 180,
  cursor: null,
  crosshair: null,
  selection: null,
  tool: "cursor",
  drawings: [],
  undo: [],
  redo: [],
  magnet: false,
  selectedDrawing: null,
  forecast: null,
  job: null,
  live: null,
  liveSettings: null,
  scale: "linear",
  yFactor: 1,
  range: null,
  theme: "light",
};
const canvas = $("priceCanvas"),
  ctx = canvas.getContext("2d");
let W = 0,
  H = 0,
  drag = null,
  requestEpoch = 0,
  drawRequest = null;
function toast(message) {
  $("toast").textContent = message;
  $("toast").classList.remove("hidden");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => $("toast").classList.add("hidden"), 5000);
}
function esc(value) {
  return String(value).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
}
function fmt(n, d = 2) {
  return Number(n).toLocaleString("en-US", {
    minimumFractionDigits: d,
    maximumFractionDigits: d,
  });
}
function time(t, long = false) {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: S.timezone,
    month: long ? "short" : undefined,
    day: long ? "numeric" : undefined,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(t * 1000));
}
async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let e;
    try {
      e = await response.json();
    } catch {
      e = { detail: response.statusText };
    }
    throw Error(
      typeof e.detail === "string" ? e.detail : JSON.stringify(e.detail),
    );
  }
  return response.json();
}
const post = (path, body) =>
  api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
function modal(title, html) {
  $("modalTitle").textContent = title;
  $("modalBody").innerHTML = html;
  if (!$("modal").open) $("modal").showModal();
}
$("closeModal").onclick = () => $("modal").close();
$("modal").addEventListener("click", (e) => {
  if (e.target === $("modal") && e.offsetX < 0) $("modal").close();
});
function download(name, data) {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: "application/json",
  });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
function drawingKey() {
  return `lumenspace.drawings.${S.symbol}.${S.tf}`;
}
function saveDrawings() {
  try {
    localStorage.setItem(drawingKey(), JSON.stringify(S.drawings));
  } catch {
    toast("Browser storage is full. Export your drawings.");
  }
  $("drawingCount").textContent = S.drawings.length;
}
function restoreDrawings() {
  try {
    const d = JSON.parse(
      localStorage.getItem(drawingKey()) ||
        localStorage.getItem(`lumen.drawings.${S.symbol}.${S.tf}`) ||
        "[]",
    );
    S.drawings = validDrawings(d) ? d : [];
  } catch {
    S.drawings = [];
  }
  S.undo = [];
  S.redo = [];
  S.selectedDrawing = null;
  $("drawingCount").textContent = S.drawings.length;
}
function remember() {
  S.undo.push(JSON.stringify(S.drawings));
  if (S.undo.length > 100) S.undo.shift();
  S.redo = [];
}
function history(back) {
  const from = back ? S.undo : S.redo,
    to = back ? S.redo : S.undo;
  if (!from.length) return;
  to.push(JSON.stringify(S.drawings));
  S.drawings = JSON.parse(from.pop());
  S.selectedDrawing = null;
  saveDrawings();
  paint();
}
$("undo").onclick = () => history(true);
$("redo").onclick = () => history(false);
function selectTool(tool) {
  S.tool = tool;
  document
    .querySelectorAll("[data-tool]")
    .forEach((b) => b.classList.toggle("active", b.dataset.tool === tool));
  canvas.style.cursor = tool === "cursor" ? "crosshair" : "crosshair";
}
document
  .querySelectorAll("[data-tool]")
  .forEach((b) => (b.onclick = () => selectTool(b.dataset.tool)));
$("magnet").onclick = () => {
  S.magnet = !S.magnet;
  $("magnet").classList.toggle("active", S.magnet);
};
$("deleteDrawing").onclick = () => {
  if (S.selectedDrawing !== null) {
    remember();
    S.drawings.splice(S.selectedDrawing, 1);
    S.selectedDrawing = null;
    saveDrawings();
    paint();
  }
};
$("exportDrawings").onclick = () =>
  download(`${S.symbol}-drawings.json`, {
    symbol: S.symbol,
    timeframe: S.tf,
    drawings: S.drawings,
  });
function validDrawings(d) {
  return (
    Array.isArray(d) &&
    d.length <= 1000 &&
    d.every(
      (v) =>
        ["line", "ray", "horizontal", "vertical", "rectangle", "text"].includes(
          v.type,
        ) &&
        ["t1", "p1", "t2", "p2"].every((k) => Number.isFinite(v[k])) &&
        (!v.text || typeof v.text === "string"),
    )
  );
}
function readJSON(action) {
  $("jsonFile").value = "";
  $("jsonFile").onchange = async () => {
    try {
      const file = $("jsonFile").files[0];
      if (file.size > 2e6) throw Error("JSON limit: 2 MB");
      action(JSON.parse(await file.text()));
    } catch (e) {
      toast(e.message);
    }
  };
  $("jsonFile").click();
}
$("importDrawings").onclick = () =>
  readJSON((value) => {
    if (!validDrawings(value.drawings)) throw Error("Invalid drawing file");
    remember();
    S.drawings = value.drawings;
    saveDrawings();
    paint();
    toast("Drawings imported");
  });
function themeColors() {
  const c = getComputedStyle(document.body);
  return {
    paper: c.getPropertyValue("--paper").trim(),
    ink: c.getPropertyValue("--ink").trim(),
    line: c.getPropertyValue("--line").trim(),
    muted: c.getPropertyValue("--muted").trim(),
  };
}
function paintSoon() {
  if (!drawRequest)
    drawRequest = requestAnimationFrame(() => {
      drawRequest = null;
      paint();
    });
}
function indexFor(t) {
  if (!S.bars.length) return 0;
  let lo = 0,
    hi = S.bars.length - 1;
  while (lo < hi) {
    const m = (lo + hi) >> 1;
    if (S.bars[m].time < t) lo = m + 1;
    else hi = m;
  }
  if (
    lo > 0 &&
    Math.abs(S.bars[lo - 1].time - t) < Math.abs(S.bars[lo].time - t)
  )
    lo--;
  return lo;
}
function priceValue(p) {
  if (S.scale === "log") return Math.log(Math.max(p, 1e-10));
  if (S.scale === "percent")
    return (p / S.bars[Math.max(0, Math.floor(S.left))].close - 1) * 100;
  return p;
}
function inversePrice(v) {
  if (S.scale === "log") return Math.exp(v);
  if (S.scale === "percent")
    return S.bars[Math.max(0, Math.floor(S.left))].close * (1 + v / 100);
  return v;
}
function xOfIndex(i) {
  return 14 + ((i - S.left) / (S.right - S.left)) * (W - 88);
}
function xOfTime(t) {
  const bars = S.bars;
  let i = indexFor(t);
  if (t > bars.at(-1).time)
    i = bars.length - 1 + (t - bars.at(-1).time) / (S.tf * 60);
  else if (t < bars[i].time && i > 0)
    i -= (bars[i].time - t) / (bars[i].time - bars[i - 1].time);
  else if (t > bars[i].time && i < bars.length - 1)
    i += (t - bars[i].time) / (bars[i + 1].time - bars[i].time);
  return xOfIndex(i);
}

function yOfPrice(p) {
  return (
    20 +
    ((S.range.max - priceValue(p)) / (S.range.max - S.range.min)) * (H - 102)
  );
}
function position(event, snap = S.magnet) {
  const r = canvas.getBoundingClientRect(),
    x = event.clientX - r.left,
    y = event.clientY - r.top;
  const i = Math.round(S.left + ((x - 14) / (W - 88)) * (S.right - S.left));
  const idx = Math.max(0, Math.min(S.bars.length - 1, i));
  let price = inversePrice(
    S.range.max - ((y - 20) / (H - 102)) * (S.range.max - S.range.min),
  );
  if (snap) {
    const bar = S.bars[idx];
    price = [bar.open, bar.high, bar.low, bar.close].sort(
      (a, b) => Math.abs(a - price) - Math.abs(b - price),
    )[0];
  }
  const lastIdx = S.bars.length - 1,
    stepSeconds = S.tf * 60,
    pointerTime =
      i > lastIdx
        ? S.bars[lastIdx].time + (i - lastIdx) * stepSeconds
        : S.bars[idx].time;
  return { x, y, i: idx, rawIndex: i, time: pointerTime, price };
}
function clampView() {
  const n = S.bars.length;
  // Pan into the future until only a few candles remain at the left edge.
  const span = Math.min(Math.max(S.right - S.left, 15), Math.max(n * 1.5, 15));
  S.left = Math.max(0, Math.min(S.left, n - 8));
  S.right = S.left + span;
}
function latest() {
  const span = Math.min(180, S.bars.length);
  S.left = Math.max(0, S.bars.length - span);
  const future = Math.max(
    Math.round(span * 0.35),
    S.pathEnabled !== false && S.surfaceResult
      ? S.surfaceHorizon / S.tf + 5
      : 0,
  );
  S.right = S.bars.length + future;
  S.yFactor = 1;
  paint();
}
function paint() {
  if (!S.bars.length || !W) return;
  const colors = themeColors();
  ctx.clearRect(0, 0, W, H);
  const visible = S.bars.slice(
    Math.max(0, Math.floor(S.left)),
    Math.min(S.bars.length, Math.ceil(S.right) + 1),
  );
  if (!visible.length) return;
  let min = Math.min(...visible.map((b) => priceValue(b.low))),
    max = Math.max(...visible.map((b) => priceValue(b.high)));
  if (S.pathEnabled !== false && S.surfaceResult?.version === S.version) {
    const prices = S.surfaceResult.trajectory.price.map(priceValue);
    min = Math.min(min, ...prices);
    max = Math.max(max, ...prices);
  }
  const mid = (max + min) / 2,
    span = (Math.max(max - min, 1e-6) * 1.16) / S.yFactor;
  S.range = { min: mid - span / 2, max: mid + span / 2 };
  const plotW = W - 74,
    priceH = H - 82;
  ctx.lineWidth = 1;
  ctx.font = "10px -apple-system, sans-serif";
  ctx.textBaseline = "middle";
  for (let k = 0; k < 6; k++) {
    const value = S.range.max - ((S.range.max - S.range.min) * k) / 5,
      y = 20 + ((H - 102) * k) / 5;
    ctx.strokeStyle = colors.line;
    ctx.beginPath();
    ctx.moveTo(14, y);
    ctx.lineTo(plotW, y);
    ctx.stroke();
    ctx.fillStyle = colors.muted;
    ctx.fillText(
      S.scale === "percent" ? fmt(value) + "%" : fmt(inversePrice(value)),
      plotW + 8,
      y,
    );
  }
  const timeTicks = 6;
  for (let k = 0; k < timeTicks; k++) {
    const idx = Math.round(S.left + ((S.right - S.left) * k) / (timeTicks - 1)),
      last = S.bars.length - 1,
      tickTime =
        idx > last
          ? S.bars[last].time + (idx - last) * S.tf * 60
          : S.bars[idx]?.time;
    if (tickTime === undefined) continue;
    const x = xOfIndex(idx);
    ctx.strokeStyle = colors.line;
    ctx.beginPath();
    ctx.moveTo(x, 15);
    ctx.lineTo(x, H - 27);
    ctx.stroke();
    ctx.fillStyle = colors.muted;
    ctx.fillText(time(tickTime), Math.max(6, x - 15), H - 14);
  }
  // Clock bands reset at midnight in the selected alignment timezone.
  if (
    S.mode === "aligned" &&
    ((W - 88) * 14) / (S.tf * (S.right - S.left)) > 5
  ) {
    const widths = S.bands === "both" ? [14, 42] : [S.bands];
    const dateFormat = new Intl.DateTimeFormat("en-GB", {
      timeZone: "America/New_York",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
    widths.forEach((minutes) => {
      let previous = null;
      visible.forEach((bar, k) => {
        const parts = dateFormat
            .format(bar.time * 1000)
            .split(":")
            .map(Number),
          key = Math.floor((parts[0] * 60 + parts[1]) / minutes);
        const x = xOfIndex(Math.floor(S.left) + k);
        if (previous !== null && previous !== key) {
          ctx.strokeStyle = minutes === 42 ? "#b8d5cf" : "#dce9e5";
          ctx.setLineDash(minutes === 42 ? [3, 3] : [1, 4]);
          ctx.beginPath();
          ctx.moveTo(x, 10);
          ctx.lineTo(x, priceH);
          ctx.stroke();
          ctx.setLineDash([]);
        }
        previous = key;
      });
    });
  }
  ctx.save();
  ctx.beginPath();
  ctx.rect(13, 9, plotW - 13, H - 35);
  ctx.clip();
  const width = Math.max(
      1,
      Math.min(11, ((W - 88) / (S.right - S.left)) * 0.68),
    ),
    stride = Math.max(1, Math.floor((S.right - S.left) / (plotW * 1.5))),
    maxVolume = Math.max(...visible.map((b) => b.volume), 1);
  if (S.selection) {
    ctx.fillStyle = "#0f766e20";
    ctx.fillRect(
      xOfTime(S.selection[0]),
      10,
      xOfTime(S.selection[1] + (S.report.interval_seconds || 60)) -
        xOfTime(S.selection[0]),
      H - 28 - 10,
    );
  }
  if ($("chartStyle").value === "line") {
    ctx.strokeStyle = "#327c72";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    visible.forEach((b, k) => {
      const x = xOfIndex(Math.floor(S.left) + k),
        y = yOfPrice(b.close);
      k ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    });
    ctx.stroke();
  }
  for (
    let idx = Math.max(0, Math.floor(S.left));
    idx < Math.min(S.bars.length, Math.ceil(S.right));
    idx += stride
  ) {
    const b = S.bars[idx],
      x = xOfIndex(idx),
      up = b.close >= b.open;
    const afterWindow = S.selection && b.time > S.selection[1];
    ctx.globalAlpha = !b.closed ? 0.4 : afterWindow ? 0.3 : 1;
    const marked =
      S.selection && b.time >= S.selection[0] && b.time <= S.selection[1];
    ctx.strokeStyle = marked
      ? up
        ? "#087f75"
        : "#315b59"
      : up
        ? "#4fae9a"
        : "#e0806f";
    ctx.fillStyle = ctx.strokeStyle;
    if ($("chartStyle").value === "candles") {
      ctx.beginPath();
      ctx.moveTo(x, yOfPrice(b.high));
      ctx.lineTo(x, yOfPrice(b.low));
      ctx.stroke();
      ctx.fillRect(
        x - width / 2,
        Math.min(yOfPrice(b.open), yOfPrice(b.close)),
        width,
        Math.max(1, Math.abs(yOfPrice(b.open) - yOfPrice(b.close))),
      );
    }
    ctx.globalAlpha = afterWindow ? 0.08 : 0.2;
    ctx.fillRect(
      x - width / 2,
      H - 30 - (b.volume / maxVolume) * 34,
      width,
      (b.volume / maxVolume) * 34,
    );
    ctx.globalAlpha = 1;
  }
  if (S.selection) {
    const x1 = xOfTime(S.selection[0]),
      x2 = xOfTime(S.selection[1] + (S.report.interval_seconds || 60));
    ctx.strokeStyle = "#087f75";
    ctx.lineWidth = 2;
    ctx.strokeRect(x1, 10, x2 - x1, H - 28 - 10);
    const count = Math.round((S.selection[1] - S.selection[0]) / 60) + 1,
      text = `SELECTED · ${count} M1 CANDLES`;
    ctx.font = "600 10px Arial";
    const labelW = ctx.measureText(text).width + 16,
      labelH = 20,
      labelY = H - 28 - labelH,
      labelX = Math.max(
        16,
        Math.min(plotW - labelW - 4, (x1 + x2) / 2 - labelW / 2),
      );
    ctx.fillStyle = "#087f75";
    ctx.fillRect(labelX, labelY, labelW, labelH);
    ctx.fillStyle = "#fff";
    ctx.fillText(text, labelX + 8, labelY + labelH / 2 + 0.5);
    ctx.lineWidth = 1;
  }
  if (
    S.forecastRangeEnabled !== false &&
    S.forecast &&
    S.forecast.version === S.version
  ) {
    const f = S.forecast.result.forecast,
      x1 = xOfTime(f.asof),
      x2 = xOfTime(f.until),
      y1 = yOfPrice(f.anchor + f.range / 2),
      y2 = yOfPrice(f.anchor - f.range / 2);
    ctx.fillStyle = "#0f766e0c";
    ctx.fillRect(x1, y1, x2 - x1, y2 - y1);
    ctx.strokeStyle = "#78a99e";
    ctx.setLineDash([5, 4]);
    ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
    ctx.setLineDash([]);
    ctx.fillStyle = "#6e968c";
    ctx.fillText("Range estimate · illustrative", x1 + 5, y1 + 10);
  }
  S.drawings.forEach((d, i) => {
    ctx.strokeStyle = d.color || "#78918b";
    ctx.fillStyle = ctx.strokeStyle;
    ctx.lineWidth = i === S.selectedDrawing ? 2.5 : d.width || 1.3;
    ctx.setLineDash(d.locked ? [3, 3] : []);
    let x1 = xOfTime(d.t1),
      x2 = xOfTime(d.t2),
      y1 = yOfPrice(d.p1),
      y2 = yOfPrice(d.p2);
    ctx.beginPath();
    if (d.type === "horizontal") {
      ctx.moveTo(14, y1);
      ctx.lineTo(plotW, y1);
    } else if (d.type === "vertical") {
      ctx.moveTo(x1, 10);
      ctx.lineTo(x1, priceH);
    } else if (d.type === "rectangle") {
      ctx.globalAlpha = 0.05;
      ctx.fillRect(x1, y1, x2 - x1, y2 - y1);
      ctx.globalAlpha = 1;
      ctx.rect(x1, y1, x2 - x1, y2 - y1);
      ctx.fillText(
        `${fmt(Math.abs(d.p2 - d.p1))} · ${Math.round(Math.abs(d.t2 - d.t1) / 60)}m · ${Math.round(Math.abs(d.t2 - d.t1) / (S.tf * 60))} bars`,
        Math.min(x1, x2) + 5,
        Math.min(y1, y2) + 10,
      );
    } else if (d.type === "text") {
      ctx.fillText(d.text || "Note", x1, y1);
    } else {
      if (d.type === "ray" && Math.abs(x2 - x1) > 1) {
        const slope = (y2 - y1) / (x2 - x1);
        y2 = y1 + slope * (plotW - x1);
        x2 = plotW;
      }
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
    }
    ctx.stroke();
    if (i === S.selectedDrawing) {
      ctx.setLineDash([]);
      ctx.fillRect(x1 - 3, y1 - 3, 6, 6);
      ctx.fillRect(x2 - 3, y2 - 3, 6, 6);
    }
  });
  if (typeof paintIntegrationLayers === "function")
    paintIntegrationLayers(plotW, priceH);
  ctx.restore();
  ctx.setLineDash([]);
  ctx.lineWidth = 1;
  if (S.cursor !== null) {
    const bar = S.bars[S.cursor];
    if (bar) {
      const crossPrice =
        S.crosshair?.time === bar.time ? S.crosshair.price : bar.close;
      const inFuture = S.crosshair && S.crosshair.time > S.bars.at(-1).time,
        x = inFuture ? xOfTime(S.crosshair.time) : xOfIndex(S.cursor),
        y = yOfPrice(crossPrice);
      ctx.strokeStyle = "#a3b0b4";
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(x, 10);
      ctx.lineTo(x, H - 28);
      ctx.moveTo(14, y);
      ctx.lineTo(plotW, y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "#1f6f78";
      ctx.fillRect(plotW + 2, y - 9, 69, 18);
      ctx.fillStyle = "white";
      ctx.fillText(fmt(crossPrice), plotW + 7, y);
      const label =
        time(inFuture ? S.crosshair.time : bar.time, true) +
        (inFuture ? " NY · future" : " NY");
      ctx.font = "10px Arial";
      const labelW = ctx.measureText(label).width + 14;
      const labelX = Math.max(14, Math.min(plotW - labelW, x - labelW / 2));
      ctx.fillStyle = "#304b46";
      ctx.fillRect(labelX, H - 26, labelW, 20);
      ctx.fillStyle = "#fff";
      ctx.fillText(label, labelX + 7, H - 12);
      $("ohlc").textContent =
        `O ${fmt(bar.open)}  H ${fmt(bar.high)}  L ${fmt(bar.low)}  C ${fmt(bar.close)}${bar.closed ? "" : " · FORMING"}`;
    }
  }
  $("rangeLabel").textContent =
    `${time(visible[0].time, true)} — ${time(visible.at(-1).time, true)}`;
}
const resizePrice = document.createElement("button");
resizePrice.className = "price-resize-handle";
resizePrice.textContent = "↕ Drag to resize price chart";
resizePrice.setAttribute("aria-label", "Resize price chart");
canvas.parentElement.after(resizePrice);
resizePrice.onpointerdown = (event) => {
  const startY = event.clientY,
    startHeight = canvas.parentElement.getBoundingClientRect().height;
  resizePrice.setPointerCapture(event.pointerId);
  resizePrice.onpointermove = (e) => {
    canvas.parentElement.style.height =
      Math.max(300, Math.min(1600, startHeight + e.clientY - startY)) + "px";
  };
  resizePrice.onpointerup = () => {
    resizePrice.onpointermove = null;
  };
};
resizePrice.onkeydown = (event) => {
  if (!["ArrowUp", "ArrowDown"].includes(event.key)) return;
  event.preventDefault();
  canvas.parentElement.style.height =
    Math.max(
      300,
      Math.min(
        1600,
        canvas.parentElement.getBoundingClientRect().height +
          (event.key === "ArrowDown" ? 40 : -40),
      ),
    ) + "px";
};
new ResizeObserver(() => {
  const r = canvas.parentElement.getBoundingClientRect();
  W = r.width;
  H = r.height;
  const dpr = devicePixelRatio || 1;
  canvas.width = W * dpr;
  canvas.height = H * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  paintSoon();
}).observe(canvas.parentElement);
function hitDrawing(p) {
  for (let i = S.drawings.length - 1; i >= 0; i--) {
    const d = S.drawings[i],
      x1 = xOfTime(d.t1),
      x2 = xOfTime(d.t2),
      y1 = yOfPrice(d.p1),
      y2 = yOfPrice(d.p2);
    if (d.type === "horizontal" && Math.abs(p.y - y1) < 7) return i;
    if (d.type === "vertical" && Math.abs(p.x - x1) < 7) return i;
    if (d.type === "text" && Math.hypot(p.x - x1, p.y - y1) < 30) return i;
    if (
      d.type === "rectangle" &&
      p.x >= Math.min(x1, x2) - 7 &&
      p.x <= Math.max(x1, x2) + 7 &&
      p.y >= Math.min(y1, y2) - 7 &&
      p.y <= Math.max(y1, y2) + 7
    )
      return i;
    const vx = x2 - x1,
      vy = y2 - y1,
      len = vx * vx + vy * vy,
      u = len ? ((p.x - x1) * vx + (p.y - y1) * vy) / len : 0;
    if (
      u >= 0 &&
      (u <= 1 || d.type === "ray") &&
      Math.hypot(p.x - x1 - u * vx, p.y - y1 - u * vy) < 7
    )
      return i;
  }
  return null;
}
canvas.addEventListener("pointerdown", (e) => {
  if (e.button !== 0 || !S.bars.length || !S.range) return;
  const p = position(e);
  canvas.setPointerCapture(e.pointerId);
  if (S.tool === "cursor") {
    const hit = hitDrawing(p);
    S.selectedDrawing = hit;
    if (hit !== null) {
      const d = S.drawings[hit];
      if (d.locked) {
        paint();
        return;
      }
      remember();
      const endpoint =
        Math.hypot(p.x - xOfTime(d.t2), p.y - yOfPrice(d.p2)) < 12;
      drag = {
        type: endpoint ? "resize" : "move",
        p,
        original: { ...d },
        index: hit,
      };
    } else if (p.x > W - 74) {
      drag = { type: "scale", p, factor: S.yFactor };
    } else {
      drag = { type: "pan", p, left: S.left, right: S.right };
    }
  } else if (S.tool === "select") {
    drag = { type: "select", p };
    S.selection = [p.time, p.time];
  } else {
    remember();
    const d = {
      type: S.tool,
      t1: p.time,
      p1: p.price,
      t2: p.time,
      p2: p.price,
      color: "#678e84",
      width: 1.3,
      locked: false,
    };
    if (S.tool === "text") {
      d.text = prompt("Text note", "Observation") || "Observation";
    }
    S.drawings.push(d);
    S.selectedDrawing = S.drawings.length - 1;
    drag = { type: "draw", p, index: S.selectedDrawing };
  }
  paintSoon();
});
let lastLink = 0;
canvas.addEventListener("pointermove", (e) => {
  if (!S.range) return;
  const p = position(e);
  S.cursor = p.i;
  S.crosshair = { time: p.time, price: p.price };
  if (drag) {
    if (drag.type === "pan") {
      const shift = ((p.x - drag.p.x) / (W - 88)) * (drag.right - drag.left);
      S.left = drag.left - shift;
      S.right = drag.right - shift;
      clampView();
    } else if (drag.type === "scale") {
      S.yFactor = Math.max(
        0.3,
        Math.min(6, drag.factor * Math.exp((p.y - drag.p.y) / 150)),
      );
    } else if (drag.type === "select") {
      S.selection = [
        Math.min(p.time, drag.p.time),
        Math.max(p.time, drag.p.time),
      ];
    } else if (drag.type === "draw" || drag.type === "resize") {
      Object.assign(S.drawings[drag.index], { t2: p.time, p2: p.price });
    } else if (drag.type === "move") {
      const d = drag.original,
        dt = p.time - drag.p.time,
        dp = p.price - drag.p.price;
      Object.assign(S.drawings[drag.index], {
        t1: d.t1 + dt,
        t2: d.t2 + dt,
        p1: d.p1 + dp,
        p2: d.p2 + dp,
      });
    }
  } else if (Date.now() - lastLink > 150) {
    lastLink = Date.now();
    S.linkedTimes = [];
    S.analysisProbe = null;
    linkCursor(p.time);
  }
  paintSoon();
});
canvas.addEventListener("pointerup", () => {
  if (!drag) return;
  const type = drag.type;
  drag = null;
  saveDrawings();
  if (type === "draw") selectTool("cursor");
  if (type === "select") {
    if (S.selection[0] === S.selection[1]) S.selection = null;
    if (S.selection && typeof validateDraggedWindow === "function")
      validateDraggedWindow();
    else {
      updateSelection();
      refreshPanes();
    }
  }
  paintSoon();
});
canvas.addEventListener("dblclick", (e) => {
  const p = position(e),
    hit = hitDrawing(p);
  if (hit !== null) {
    editDrawing(hit);
    return;
  }
  if (S.selection && typeof focusMarkedWindow === "function")
    focusMarkedWindow();
  else latest();
});
canvas.addEventListener(
  "wheel",
  (e) => {
    e.preventDefault();
    if (!S.bars.length) return;
    const rect = canvas.getBoundingClientRect(),
      fraction = Math.max(
        0,
        Math.min(1, (e.clientX - rect.left - 14) / (W - 88)),
      );
    const span = S.right - S.left,
      anchor = S.left + span * fraction,
      newSpan = Math.max(
        15,
        Math.min(S.bars.length, span * Math.exp(e.deltaY * 0.0015)),
      );
    S.left = anchor - newSpan * fraction;
    S.right = S.left + newSpan;
    clampView();
    paintSoon();
  },
  { passive: false },
);
function editDrawing(i) {
  const d = S.drawings[i];
  modal(
    "Drawing style",
    `<div class="form-grid"><label>Color<input type="color" id="drawingColor" value="${esc(d.color || "#678e84")}"></label><label>Line width<input type="number" id="drawingWidth" min="1" max="5" value="${d.width || 1}"></label></div><p><label><input type="checkbox" id="drawingLocked" ${d.locked ? "checked" : ""}> Lock drawing</label></p><p class="micro">Drag a drawing to move it. Drag its second handle to resize it.</p><div class="modal-actions"><button class="button primary" id="applyDrawing">Apply</button></div>`,
  );
  $("applyDrawing").onclick = () => {
    remember();
    Object.assign(d, {
      color: $("drawingColor").value,
      width: Math.max(1, Math.min(5, +$("drawingWidth").value)),
      locked: $("drawingLocked").checked,
    });
    saveDrawings();
    paint();
    $("modal").close();
  };
}
document.addEventListener("keydown", (e) => {
  if (
    ["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName) ||
    $("modal").open
  )
    return;
  if ((e.ctrlKey || e.metaKey) && e.key === "z") {
    e.preventDefault();
    history(true);
  } else if ((e.ctrlKey || e.metaKey) && e.key === "y") {
    e.preventDefault();
    history(false);
  } else if (e.key === "Delete") $("deleteDrawing").click();
  else if (e.key.toLowerCase() === "s") selectTool("select");
  else if (e.key.toLowerCase() === "v") selectTool("cursor");
  else if (e.key === "Escape") {
    if (
      typeof closeChartContext === "function" &&
      !$("chartContext").classList.contains("hidden")
    ) {
      closeChartContext();
      return;
    }
    S.selection = null;
    selectTool("cursor");
    updateSelection();
    refreshPanes();
    paint();
  }
});
function selectionKey() {
  return S.selection ? S.selection.join(":") : "";
}
function resetForecast() {
  S.forecast = null;
  $("forecastResult").classList.add("hidden");
  $("forecastResult").innerHTML = "";
  $("forecastEmpty").classList.remove("hidden");
  $("openTraining").textContent = "Configure & train";
  if ($("rangeToggleLabel")) $("rangeToggleLabel").classList.add("hidden");
}
function updateSelection() {
  if (S.forecast && S.forecast.sel !== selectionKey()) resetForecast();
  if (typeof updateIntegrationSelection === "function")
    updateIntegrationSelection();
  $("clearSelection").classList.toggle("hidden", !S.selection);
  $("selectionLabel").textContent = S.selection
    ? `${time(S.selection[0], true)} → ${time(S.selection[1] + (S.report.interval_seconds || 60), true)}`
    : "Scroll to zoom · drag to pan · S to select";
  $("analysisRange").textContent = S.selection
    ? "Computed from the selected closed-bar range"
    : "Choose a source window, then add analysis.";
}
$("clearSelection").onclick = () => {
  S.selection = null;
  updateSelection();
  refreshPanes();
  paint();
};
$("followLive").onclick = latest;
$("chartStyle").onchange = paint;
function paneViews(module) {
  return {
    surface: [
      ["3d", "3D surface"],
      ["heatmap", "Height map"],
      ["trajectory", "Price scenario"],
    ],
    phase: [
      ["3d", "3D trajectory"],
      ["2d", "2D trajectory"],
    ],
    recurrence: [["heatmap", "Recurrence map"]],
    wavelet: [
      ["heatmap", "Scalogram"],
      ["components", "DWT components"],
    ],
    fourier: [
      ["spectrum", "Spectrum"],
      ["heatmap", "Spectrogram"],
    ],
    laplace: [
      ["heatmap", "Magnitude map"],
      ["3d", "3D surface"],
    ],
    topology: [
      ["diagram", "Persistence"],
      ["barcode", "Barcodes"],
      ["landscape", "Landscape"],
    ],
    metrics: [
      ["fourier", "Fourier"],
      ["phase", "Phase"],
      ["recurrence", "RQA"],
      ["wavelet", "Wavelet"],
      ["laplace", "Laplace"],
      ["topology", "Topology"],
    ],
  }[module];
}
const RESEARCH_MODULES = ["recurrence", "wavelet", "surface", "phase"];
const DEFAULT_VIEWS = {
  recurrence: "heatmap",
  wavelet: "heatmap",
  surface: "heatmap",
  phase: "2d",
};
function makePanes() {
  // Migrate saved workspaces and keep exactly one of each permanent research view.
  S.panes = RESEARCH_MODULES.map((module) => {
    const existing = S.panes.find((p) => p.module === module);
    return (
      existing || {
        id: module + "-" + crypto.randomUUID(),
        module,
        view: DEFAULT_VIEWS[module],
      }
    );
  });
  const host = $("panes");
  host.innerHTML = S.panes.length
    ? ""
    : `<div class="analysis-empty"><span class="pane-kicker">YOUR RESEARCH WORKSPACE</span><h3>Start with a window. Build your views.</h3><p id="emptyHint">Choose a time window above to begin.</p></div>`;
  for (const pane of S.panes) {
    const el = document.createElement("section");
    el.className = "card pane";
    el.id = pane.id;
    if (Number.isFinite(pane.height))
      el.style.height = Math.max(380, Math.min(1600, pane.height)) + "px";
    el.innerHTML = `<div class="pane-head"><div><div class="pane-kicker">${pane.module === "metrics" ? "WINDOW FEATURES" : "TRANSFORM / " + esc(pane.module.toUpperCase())}</div><h3>${names[pane.module]}</h3></div><div class="pane-actions"><select aria-label="Analysis view">${paneViews(
      pane.module,
    )
      .map(
        ([v, n]) =>
          `<option value="${v}" ${pane.view === v ? "selected" : ""}>${n}</option>`,
      )
      .join(
        "",
      )}</select><button data-action="pan" title="Drag to pan">Pan</button><button data-action="zoom" title="Drag to zoom">Zoom</button><button data-action="home" title="Reset chart view">Reset view</button></div></div><div class="plot" id="plot-${pane.id}"></div><div class="chart-readout" id="readout-${pane.id}">Crosshair · X — · Y —</div><div class="pane-footer" id="metrics-${pane.id}"><span>Preparing analysis…</span></div>`;
    host.append(el);
    el.querySelector("select").onchange = (e) => {
      pane.view = e.target.value;
      if (pane.module === "metrics") refreshPanes();
      else renderPane(pane);
    };
    el.querySelector("[data-action=pan]").onclick = () =>
      setPaneMode(pane, "pan");
    el.querySelector("[data-action=zoom]").onclick = () =>
      setPaneMode(pane, "zoom");
    el.querySelector("[data-action=home]").onclick = () => {
      const plot = $("plot-" + pane.id);
      if (!plot?.data) return;
      Plotly.relayout(plot, {
        "xaxis.autorange": true,
        "yaxis.autorange": true,
        "scene.camera": { eye: { x: 1.5, y: 1.8, z: 1.1 } },
      });
    };
    new ResizeObserver(() => {
      pane.height = el.getBoundingClientRect().height;
      const plot = $("plot-" + pane.id);
      if (plot?.data) Plotly.Plots.resize(plot);
    }).observe(el);
  }
  $("paneCount").textContent = S.panes.length;
  if (typeof syncWindowWorkflow === "function") syncWindowWorkflow();
}
function setPaneMode(pane, mode) {
  const plot = $("plot-" + pane.id);
  if (!plot?.data) return;
  Plotly.relayout(plot, {
    dragmode: mode,
    "scene.dragmode": mode === "pan" ? "pan" : "orbit",
  });
  $(pane.id)
    .querySelectorAll("[data-action=pan], [data-action=zoom]")
    .forEach((b) => b.classList.toggle("active", b.dataset.action === mode));
}
function toISO(times) {
  return times.map((t) => new Date(t * 1000).toISOString());
}
const colorScale = [
  [0, "#f4f8f7"],
  [0.2, "#deece7"],
  [0.5, "#94bcae"],
  [0.8, "#397d70"],
  [1, "#164c44"],
];
async function renderPane(pane) {
  if (pane.module === "surface") return renderSurfacePane(pane);
  const result = pane.result,
    el = $("plot-" + pane.id);
  if (!result || !el) return;
  const colors = themeColors();
  let traces = [],
    layout = {
      paper_bgcolor: colors.paper,
      plot_bgcolor: colors.paper,
      font: {
        family: "-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif",
        size: 11,
        color: colors.muted,
      },
      margin: { l: 43, r: 15, t: 8, b: 34 },
      xaxis: {
        gridcolor: colors.line,
        zeroline: false,
        tickfont: { size: 10 },
        showspikes: true,
        spikemode: "across",
        spikesnap: "cursor",
        spikecolor: "#638d82",
        spikethickness: 1,
      },
      yaxis: {
        gridcolor: colors.line,
        zeroline: false,
        tickfont: { size: 10 },
        showspikes: true,
        spikemode: "across",
        spikesnap: "cursor",
        spikecolor: "#638d82",
        spikethickness: 1,
      },
      showlegend: false,
      hovermode: "closest",
      dragmode: "pan",
      uirevision: JSON.stringify([
        S.version,
        S.selection,
        S.window,
        S.params,
        pane.view,
      ]),
    };
  const heat = (x, y, z) => ({
    type: "heatmap",
    x,
    y,
    z,
    colorscale: colorScale,
    showscale: false,
    hovertemplate: "x %{x}<br>y %{y}<br>value %{z:.3f}<extra></extra>",
  });
  if (pane.module === "phase") {
    const p = result.points,
      t = result.point_times;
    const scatter = {
      type: pane.view === "3d" ? "scatter3d" : "scatter",
      mode: "lines+markers",
      x: p.map((v) => v[0]),
      y: p.map((v) => v[1]),
      customdata: t,
      marker: {
        size: pane.view === "3d" ? 3 : 4,
        color: t,
        colorscale: colorScale,
      },
      line: { width: 1.5, color: "#5c9384" },
      hovertemplate: "State %{x:.3f}, %{y:.3f}<extra></extra>",
    };
    if (pane.view === "3d") {
      scatter.z = p.map((v) => v[2] || 0);
      layout.scene = {
        xaxis: {
          title: { text: `x(t − ${S.params.dimension - 1}τ)` },
          gridcolor: colors.line,
        },
        yaxis: {
          title: { text: `x(t − ${S.params.dimension - 2}τ)` },
          gridcolor: colors.line,
        },
        zaxis: {
          title: {
            text:
              S.params.dimension > 2
                ? `x(t − ${S.params.dimension - 3}τ)`
                : "(2D embedding)",
          },
          gridcolor: colors.line,
        },
        bgcolor: colors.paper,
        aspectmode: "cube",
        camera: { eye: { x: 1.5, y: 1.5, z: 1.1 } },
      };
      layout.margin = { l: 0, r: 0, t: 0, b: 0 };
    } else {
      layout.xaxis.title = { text: "Delayed state" };
      layout.yaxis.title = { text: "Next state" };
    }
    traces = [scatter];
  } else if (pane.module === "recurrence") {
    const selectedRows = new Set(
      (result.potential_levels || []).map((row) => row.row),
    );
    traces = [
      heat(toISO(result.x), toISO(result.y), result.z),
      {
        type: "bar",
        orientation: "h",
        xaxis: "x2",
        x: result.row_scores.map((row) => row.count),
        y: toISO(result.y),
        customdata: result.row_scores.map((row) => row.time),
        width: result.y.map((t, i, a) => (a[1] - a[0]) * 1000 * 0.8),
        marker: {
          color: result.row_scores.map((row) =>
            selectedRows.has(row.row) ? "#a4874d" : "#d5e5e0",
          ),
        },
        hovertemplate: "%{x} off-diagonal matches<br>%{y}<extra></extra>",
      },
    ];
    layout.xaxis.domain = [0, 0.82];
    layout.xaxis2 = {
      domain: [0.87, 1],
      title: { text: "Matches" },
      zeroline: false,
      showgrid: false,
      fixedrange: true,
      tickfont: { size: 10 },
    };
    layout.xaxis.type = "date";
    layout.yaxis.type = "date";
    layout.yaxis.title = { text: "Source candle · New York time" };
    layout.xaxis.title = { text: "Matching candle · New York time" };
    layout.shapes = (result.potential_levels || []).map((row) => ({
      type: "line",
      xref: "paper",
      x0: 0,
      x1: 1,
      y0: new Date(row.time * 1000).toISOString(),
      y1: new Date(row.time * 1000).toISOString(),
      line: { color: "rgba(164,135,77,.45)", width: 1, dash: "dot" },
    }));
    layout.xaxis.tickformat = "%H:%M";
  } else if (pane.module === "wavelet") {
    if (pane.view === "components") {
      traces = result.components.map((c, i) => ({
        type: "scatter",
        mode: "lines",
        x: toISO(result.times),
        y: c.map((v) => v + i * 3),
        name: i === 0 ? "Approximation" : `Detail ${i}`,
        line: {
          width: 1.2,
          color: ["#3a7b6e", "#8ca69e", "#b5c2bc", "#606e75"][i % 4],
        },
      }));
      layout.yaxis.title = { text: "DWT components (offset)" };
    } else {
      traces = [
        heat(toISO(result.x), result.y, result.z),
        {
          type: "scatter",
          x: toISO(result.times),
          y: result.coi,
          mode: "lines",
          line: { color: "#bfb4a0", width: 1, dash: "dot" },
          hoverinfo: "skip",
        },
      ];
      layout.yaxis.title = { text: "Period / min" };
      const an = result.analysis;
      if (an?.available) {
        const sp = an.spectrum,
          near = sp.period.reduce(
            (b, p, i) =>
              Math.abs(p - an.dominant.wavelet_period) <
              Math.abs(sp.period[b] - an.dominant.wavelet_period)
                ? i
                : b,
            0,
          ),
          iso = (t) => new Date(t * 1000).toISOString(),
          firstUnusable = sp.usable.indexOf(false);
        traces.push(
          {
            type: "scatter",
            mode: "lines",
            xaxis: "x2",
            x: sp.power,
            y: sp.period,
            line: { color: "#397d70", width: 1.4 },
            hovertemplate: "%{y:.1f} min<br>power %{x:.3f}<extra>observed</extra>",
          },
          {
            type: "scatter",
            mode: "lines",
            xaxis: "x2",
            x: sp.threshold_power,
            y: sp.period,
            line: { color: "#b59c67", width: 1, dash: "dot" },
            hovertemplate: "%{y:.1f} min<br>%{x:.3f}<extra>red-noise 95% bar</extra>",
          },
          {
            type: "scatter",
            mode: "markers",
            xaxis: "x2",
            x: [sp.power[near]],
            y: [sp.period[near]],
            marker: { size: 7, color: "#a4874d" },
            hoverinfo: "skip",
          },
        );
        layout.xaxis.domain = [0, 0.78];
        layout.xaxis2 = {
          domain: [0.83, 1],
          title: { text: "Power by period" },
          zeroline: false,
          showgrid: false,
          fixedrange: true,
          tickfont: { size: 10 },
        };
        layout.shapes = [
          {
            type: "line",
            xref: "paper",
            x0: 0,
            x1: 1,
            yref: "y",
            y0: an.dominant.wavelet_period,
            y1: an.dominant.wavelet_period,
            line: { color: "rgba(164,135,77,.7)", width: 1, dash: "dot" },
          },
          ...an.energy.bursts.map((b) => ({
            type: "rect",
            xref: "x",
            yref: "paper",
            x0: iso(b.start),
            x1: iso(b.end),
            y0: 0,
            y1: 1,
            fillcolor: "rgba(91,127,149,.13)",
            line: { width: 0 },
            layer: "above",
          })),
        ];
        if (firstUnusable > 0)
          layout.shapes.push({
            type: "rect",
            xref: "paper",
            yref: "y",
            x0: 0,
            x1: 0.78,
            y0: sp.period[firstUnusable],
            y1: sp.period[sp.period.length - 1],
            fillcolor: "rgba(150,150,150,.10)",
            line: { width: 0 },
            layer: "above",
          });
      }
    }
    layout.xaxis.type = "date";
    layout.xaxis.tickformat = "%H:%M";
  } else if (pane.module === "fourier") {
    if (pane.view === "heatmap") {
      traces = [heat(toISO(result.spec_x), result.spec_y, result.z)];
      layout.xaxis.type = "date";
      layout.xaxis.tickformat = "%H:%M";
      layout.yaxis.title = { text: "Cycles / minute" };
    } else {
      traces = [
        {
          type: "scatter",
          mode: "lines",
          x: result.x,
          y: result.power,
          line: { color: "#397d70", width: 1.5 },
          fill: "tozeroy",
          fillcolor: "#397d7012",
        },
      ];
      layout.xaxis.title = { text: "Cycles / minute" };
      layout.yaxis.title = { text: "Power" };
    }
  } else if (pane.module === "laplace") {
    traces = [
      pane.view === "3d"
        ? {
            type: "surface",
            x: result.x,
            y: result.y,
            z: result.z,
            colorscale: colorScale,
            showscale: false,
          }
        : heat(result.x, result.y, result.z),
    ];
    if (pane.view === "3d") {
      layout.scene = {
        xaxis: { title: { text: "ω / rad·min⁻¹" } },
        yaxis: { title: { text: "σ / min⁻¹" } },
        zaxis: { title: { text: "Magnitude" } },
        bgcolor: colors.paper,
      };
      layout.margin = { l: 0, r: 0, t: 0, b: 0 };
    } else {
      layout.xaxis.title = { text: "ω / rad·min⁻¹" };
      layout.yaxis.title = { text: "σ / min⁻¹" };
    }
  } else if (pane.module === "topology") {
    if (pane.view === "landscape") {
      traces = [
        {
          type: "scatter",
          x: result.x,
          y: result.landscape,
          fill: "tozeroy",
          line: { color: "#397d70", width: 1.5 },
        },
      ];
      layout.xaxis.title = { text: "Filtration" };
      layout.yaxis.title = { text: "First landscape" };
    } else if (pane.view === "barcode") {
      let row = 0;
      for (let dim = 0; dim < 2; dim++)
        for (const [birth, death] of result.diagrams[dim])
          traces.push({
            type: "scatter",
            mode: "lines",
            x: [birth, death],
            y: [row, row++],
            line: { color: dim ? "#367a6a" : "#bac9c4", width: 3 },
            hovertemplate: `H${dim} lifetime<extra></extra>`,
          });
      layout.xaxis.title = { text: "Filtration" };
      layout.yaxis.title = { text: "Feature" };
    } else {
      traces = result.diagrams.map((d, i) => ({
        type: "scatter",
        mode: "markers",
        x: d.map((v) => v[0]),
        y: d.map((v) => v[1]),
        name: "H" + i,
        marker: { color: i ? "#367a6a" : "#bac9c4", size: 6 },
      }));
      layout.showlegend = true;
      layout.xaxis.title = { text: "Birth" };
      layout.yaxis.title = { text: "Death" };
    }
  } else if (pane.module === "metrics") {
    const points = result.points;
    if (points.length) {
      const keys = Object.keys(points[0].values).filter(
        (k) => !["return", "range", "volatility"].includes(k),
      );
      traces = keys.map((key, i) => {
        const vals = points.map((p) => p.values[key]),
          mean = vals.reduce((a, b) => a + b, 0) / vals.length,
          std =
            Math.sqrt(
              vals.reduce((s, v) => s + (v - mean) ** 2, 0) / vals.length,
            ) || 1;
        return {
          type: "scatter",
          mode: "lines",
          name: key,
          x: toISO(points.map((p) => p.time)),
          y: vals.map((v) => (v - mean) / std),
          line: {
            width: 1.2,
            color: ["#397d70", "#abbcaf", "#6c7e88", "#c2b7a0", "#8ca99b"][
              i % 5
            ],
          },
        };
      });
      layout.xaxis.type = "date";
      layout.xaxis.tickformat = "%H:%M";
      layout.yaxis.title = { text: "Display z-score" };
      layout.showlegend = true;
      layout.legend = { orientation: "h", font: { size: 7 } };
    }
  }
  if (layout.xaxis.type === "date" && traces[0]?.x?.length) {
    const vals = traces[0].x.filter(
      (_, i, a) => i % Math.max(1, Math.ceil(a.length / 5)) === 0,
    );
    layout.xaxis.tickmode = "array";
    layout.xaxis.tickvals = vals;
    layout.xaxis.ticktext = vals.map((v) => time(Date.parse(v) / 1000));
  }
  if (pane.module === "recurrence") {
    const vals = traces[0].y.filter(
      (_, i, a) => i % Math.max(1, Math.ceil(a.length / 4)) === 0,
    );
    layout.yaxis.tickmode = "array";
    layout.yaxis.tickvals = vals;
    layout.yaxis.ticktext = vals.map((v) => time(Date.parse(v) / 1000));
  }
  await Plotly.react(el, traces, layout, {
    responsive: true,
    displayModeBar: false,
    scrollZoom: true,
  });
  installPaneCrosshair(pane, el);
  el.removeAllListeners("plotly_hover");
  el.on("plotly_hover", (e) => {
    const point = e.points[0];
    showAnalysisCoordinates(pane, point, el);
    S.crosshair = null;
    S.analysisProbe = null;
    S.linkedTimes =
      pane.module === "recurrence" && !Number.isFinite(point.customdata)
        ? [Date.parse(point.x) / 1000, Date.parse(point.y) / 1000].filter(
            Number.isFinite,
          )
        : [];
    let ts = point.customdata;
    if (
      (!ts && ["wavelet", "recurrence", "metrics"].includes(pane.module)) ||
      (!ts && pane.module === "fourier" && pane.view === "heatmap")
    )
      ts = Date.parse(pane.module === "recurrence" ? point.y : point.x) / 1000;
    if (pane.module === "recurrence" && Number.isFinite(ts)) {
      const row = result.row_scores.find((row) => row.time === ts);
      if (row)
        $("readout-" + pane.id).textContent +=
          ` · Row: ${row.count} matches / ${Math.round(row.density * 100)}% · Candle ${fmt(row.low)}–${fmt(row.high)}`;
    }
    if (Number.isFinite(ts)) {
      S.cursor = indexFor(ts);
      paintSoon();
      linkCursor(ts, pane.id);
    }
  });
  const metricValues = result.metrics || {};
  const footer = $("metrics-" + pane.id);
  footer.innerHTML =
    Object.entries(metricValues)
      .slice(0, 3)
      .map(([k, v]) => `<span>${esc(k)} <strong>${fmt(v, 3)}</strong></span>`)
      .join("") || "<span>Hover to inspect · drag to explore</span>";
  if (pane.module === "recurrence") {
    const levels = result.potential_levels || [];
    const summary = document.createElement("span");
    summary.className = "recurrence-level-summary";
    summary.textContent = levels.length
      ? "Potential zones · " +
        levels
          .map(
            (row) =>
              `${time(row.time)} NY: ${row.count} matches (${Math.round(row.density * 100)}%) · ${fmt(row.low)}–${fmt(row.high)}`,
          )
          .join(" / ")
      : "No off-diagonal matches for potential zones.";
    summary.title = result.level_method;
    footer.append(summary);
  }
  if (pane.module === "wavelet" && result.analysis) {
    const reading = waveletReading(result.analysis),
      box = document.createElement("span");
    box.className = "wavelet-reading";
    box.innerHTML =
      `<strong>${esc(reading.title)}</strong>` +
      reading.lines.map((l) => `<p>${esc(l)}</p>`).join("");
    footer.append(box);
  }
  if (result.warnings?.length) {
    const b = document.createElement("button");
    b.className = "text-button";
    b.textContent = "ⓘ Notes";
    b.onclick = () =>
      modal(
        names[pane.module] + " · interpretation",
        result.warnings.map((w) => `<p>${esc(w)}</p>`).join(""),
      );
    footer.append(b);
  }
}
function waveletReading(an) {
  if (!an?.available)
    return {
      title: "Wavelet reading unavailable",
      lines: [an?.reason || "No wavelet reading for this range."],
      legend: [],
    };
  const d = an.dominant,
    pct = (v) => Math.round(v * 100) + "%",
    lines = [],
    legend = [];
  lines.push(
    `Dominant cycle ≈ ${fmt(d.period, 1)} min, holding ${pct(d.share)} of the wavelet energy; ${fmt(d.cycles_in_window, 1)} cycles fit in this window.`,
  );
  lines.push(
    d.significant
      ? `It stands above red noise (${fmt(d.excess, 1)}× the background; the 95% bar is ${fmt(d.threshold, 1)}×).`
      : `It does not clearly stand above red noise (${fmt(d.excess, 1)}× vs a ${fmt(d.threshold, 1)}× bar): treat it as a weak rhythm, not a cycle.`,
  );
  const recent = d.recent_strength;
  lines.push(
    `One sine at that period explains ${pct(d.strength)} of the detrended movement` +
      (recent == null
        ? "."
        : ` (${pct(recent)} over the last two cycles${recent < d.strength - 0.2 ? ", so it is loosening at the edge" : recent > d.strength + 0.2 ? ", so it is tightening at the edge" : ""}).`),
  );
  for (const sec of an.secondary || [])
    lines.push(
      `Secondary rhythm ≈ ${fmt(sec.period, 1)} min (${fmt(sec.ratio, 1)}× background).`,
    );
  const e = an.energy;
  if (e.bursts.length)
    lines.push(
      `Cycle energy is concentrated ${e.bursts.map((b) => `${time(b.start)}–${time(b.end)}`).join(", ")} NY.`,
    );
  lines.push(
    e.trend === "steady"
      ? "Cycle energy is steady across the window."
      : `Cycle energy is ${e.trend === "rising" ? "building" : "fading"} toward the window end (×${fmt(e.late_vs_early, 2)} vs the start).`,
  );
  const ph = an.phase;
  lines.push(
    `At the window end the fitted cycle is ${ph.state}, heading for a ${ph.next_turn} in about ${fmt(ph.minutes_to_turn, 1)} min (${time(ph.next_turn_time)} NY). Edge estimate, lowest reliability; it describes the rhythm, it is not a forecast.`,
  );
  legend.push(`${fmt(d.period, 1)} min · ${pct(d.share)} energy`);
  legend.push(
    `${d.significant ? "above" : "not above"} red noise · fit ${pct(d.strength)}`,
  );
  legend.push(`Energy ${e.trend}`);
  legend.push(`Next ${ph.next_turn} ≈ ${time(ph.next_turn_time)}`);
  return { title: "Wavelet reading", lines, legend };
}
function installPaneCrosshair(pane, el) {
  el.querySelector(".analysis-crosshair")?.remove();
  const overlay = document.createElement("div");
  overlay.className = "analysis-crosshair";
  overlay.innerHTML =
    '<i class="cross-line cross-x"></i><i class="cross-line cross-y"></i><span class="cross-chip chip-x"></span><span class="cross-chip chip-y"></span>';
  el.append(overlay);
  el.onpointermove = (event) => {
    const layout = el._fullLayout;
    if (
      !layout ||
      el.data?.[0]?.type === "surface" ||
      el.data?.[0]?.type === "scatter3d"
    )
      return;
    const rect = el.getBoundingClientRect(),
      x = event.clientX - rect.left,
      y = event.clientY - rect.top;
    const axes = [layout.xaxis, layout.xaxis2].filter(Boolean);
    const xa = axes.find((a) => x >= a._offset && x <= a._offset + a._length),
      ya = layout.yaxis;
    if (!xa || !ya || y < ya._offset || y > ya._offset + ya._length) {
      overlay.style.display = "none";
      return;
    }
    const xv = xa.p2d(x - xa._offset),
      yv = ya.p2d(y - ya._offset);
    const format = (axis, v) =>
      axis.type === "date"
        ? time(typeof v === "number" ? v / 1000 : Date.parse(v) / 1000, true) +
          " NY"
        : Number(v).toLocaleString("en-US", { maximumSignificantDigits: 6 });
    const xs = format(xa, xv),
      ys = format(ya, yv);
    overlay.style.display = "block";
    Object.assign(overlay.querySelector(".cross-x").style, {
      left: x + "px",
      top: ya._offset + "px",
      height: ya._length + "px",
    });
    Object.assign(overlay.querySelector(".cross-y").style, {
      left: xa._offset + "px",
      top: y + "px",
      width: xa._length + "px",
    });
    const xc = overlay.querySelector(".chip-x"),
      yc = overlay.querySelector(".chip-y");
    xc.textContent = xs;
    yc.textContent = ys;
    Object.assign(xc.style, {
      left: Math.max(0, Math.min(rect.width - 160, x - 60)) + "px",
      top: Math.min(rect.height - 22, ya._offset + ya._length) + "px",
    });
    Object.assign(yc.style, {
      right: "3px",
      top: Math.max(0, Math.min(rect.height - 22, y - 10)) + "px",
    });
    $("readout-" + pane.id).textContent =
      `${xa.title?.text || "X"} ${xs} · ${ya.title?.text || "Y"} ${ys}`;
  };
  el.onpointerleave = () => {
    overlay.style.display = "none";
  };
}
function showAnalysisCoordinates(pane, point, el) {
  const out = $("readout-" + pane.id);
  if (!out) return;
  const scene = el._fullLayout?.scene;
  const axis = (k) => {
    const ref = point.data?.[k + "axis"] || k;
    const key = k + "axis" + (ref.length > 1 ? ref.slice(1) : "");
    return scene?.[k + "axis"] || el._fullLayout?.[key];
  };
  const format = (k, v) => {
    if (axis(k)?.type === "date" || v instanceof Date) {
      const t = Date.parse(v) / 1000;
      return Number.isFinite(t) ? time(t, true) + " NY" : String(v);
    }
    return typeof v === "number"
      ? Number(v.toPrecision(6)).toLocaleString("en-US", {
          maximumSignificantDigits: 6,
        })
      : String(v);
  };
  out.textContent = ["x", "y", "z"]
    .filter((k) => point[k] != null)
    .map(
      (k) =>
        (axis(k)?.title?.text || k.toUpperCase()) + " " + format(k, point[k]),
    )
    .join(" · ");
}
function linkCursor(ts, exclude) {
  S.panes.forEach((p) => {
    if (p.id === exclude || !p.result) return;
    const el = $("plot-" + p.id);
    if (!el?.data) return;
    const timeBased =
      ["wavelet", "recurrence", "metrics"].includes(p.module) ||
      (p.module === "surface" && p.view !== "3d") ||
      (p.module === "fourier" && p.view === "heatmap");
    if (timeBased) {
      const x = new Date(ts * 1000).toISOString();
      Plotly.relayout(el, {
        shapes: [
          ...(el.layout.shapes || []).filter(
            (shape) => shape.name !== "linked-cursor",
          ),
          {
            name: "linked-cursor",
            type: "line",
            x0: x,
            x1: x,
            y0: 0,
            y1: 1,
            yref: "paper",
            line: { color: "#8cab9f", width: 1, dash: "dot" },
          },
        ],
      });
    } else if (p.module === "phase") {
      const times = p.result.point_times,
        i = times.reduce(
          (best, t, k) =>
            Math.abs(t - ts) < Math.abs(times[best] - ts) ? k : best,
          0,
        );
      const count = times.length,
        sizes = Array(count).fill(p.view === "3d" ? 3 : 4);
      sizes[i] = p.view === "3d" ? 7 : 9;
      Plotly.restyle(el, { "marker.size": [sizes] }, [0]);
    }
  });
}
async function refreshPanes() {
  const epoch = ++requestEpoch;
  updateSelection();
  if (!S.selection) {
    S.surfaceResult = null;
    for (const pane of S.panes) {
      const el = $("plot-" + pane.id);
      if (el?.data) Plotly.purge(el);
      if (el)
        el.innerHTML =
          '<div class="pane-error">Choose a source window to show this view.</div>';
      pane.result = null;
    }
    return;
  }
  await Promise.all(
    S.panes.map(async (pane) => {
      const plot = $("plot-" + pane.id);
      if (!plot) return;
      plot.classList.add("busy");
      try {
        const surfaceGeneration =
          typeof surfaceRevision === "number" ? surfaceRevision : 0;
        const result =
          pane.module === "surface"
            ? await post("/api/surface", surfaceRequest())
            : pane.module === "metrics"
              ? await api(
                  `/api/metrics?module=${pane.view}&minutes=${S.window}&mode=${S.mode}&timezone=America%2FNew_York${S.selection ? "&start=" + S.selection[0] + "&end=" + S.selection[1] : ""}`,
                )
              : await post("/api/transform", {
                  module: pane.module,
                  minutes: S.window,
                  mode: S.mode,
                  timezone: "America/New_York",
                  start: S.selection?.[0] ?? null,
                  end: S.selection?.[1] ?? null,
                  params: S.params,
                });
        if (
          epoch !== requestEpoch ||
          (pane.module === "surface" && surfaceGeneration !== surfaceRevision)
        )
          return;
        pane.result = result;
        pane.sourceSelection = JSON.stringify(S.selection);
        pane.sourceVersion = S.version;
        if (pane.module === "recurrence") paintSoon();
        if (pane.module === "surface") {
          S.surfaceResult = result;
          paintSoon();
        }
        await renderPane(pane);
      } catch (e) {
        if (epoch === requestEpoch) {
          plot.innerHTML = `<div class="pane-error">${esc(e.message)}</div>`;
          pane.result = null;
          $("metrics-" + pane.id).textContent =
            "Analysis unavailable for this range";
        }
      } finally {
        plot.classList.remove("busy");
      }
    }),
  );
}
$("refreshAnalysis").onclick = refreshPanes;
$("addPane").onclick = () =>
  $("panes").scrollIntoView({ behavior: "smooth", block: "start" });
async function loadBars(keepView = false) {
  const out = await api("/api/bars?timeframe=" + S.tf);
  const oldLast = S.bars.at(-1)?.time,
    following = S.right >= S.bars.length - 2;
  S.bars = out.bars;
  S.version = out.version;
  S.report = out.report;
  if (typeof refreshNYClock === "function") refreshNYClock();
  S.trainingStart = out.training_start;
  $("barCount").textContent = fmt(S.bars.filter((b) => b.closed).length, 0);
  $("sourceLabel").textContent =
    out.report.source || "Synthetic demo · not real market data";
  const last = S.bars.at(-1),
    prev = S.bars.at(-2);
  $("quote").textContent = fmt(last.close);
  $("quoteChange").textContent =
    `${last.close >= prev.close ? "+" : ""}${fmt(last.close - prev.close)} / latest bar`;
  $("qualitySummary").innerHTML =
    `<p class="quality-good">${out.report.bad_rows ? "Imported with reported exclusions" : "Data normalized"}</p><div class="desk-row"><span>Gap intervals</span><strong>${out.report.gaps}</strong></div><div class="desk-row"><span>Duplicates removed</span><strong>${out.report.duplicates_removed}</strong></div><div class="desk-row"><span>Source interval</span><strong>${out.report.interval_seconds}s</strong></div>`;
  if (S.selection) {
    if (!keepView && typeof focusMarkedWindow === "function")
      focusMarkedWindow();
    else {
      clampView();
      paint();
    }
  } else if (!keepView || following) latest();
  else {
    clampView();
    paint();
  }
  if (out.truncated) toast("Chart shows the most recent 100,000 bars.");
  if (S.forecast && S.forecast.version !== S.version)
    $("forecastResult").querySelector(".forecast-caption").textContent =
      "Data changed — this result belongs to the earlier run.";
  if (!keepView || oldLast !== last.time) refreshPanes();
}
$("timeframe").onchange = async (e) => {
  S.tf = +e.target.value;
  S.selection = null;
  restoreDrawings();
  try {
    await loadBars();
  } catch (e) {
    toast(e.message);
  }
};
$("symbolButton").onclick = () => {
  const symbol = prompt(
    "Workspace symbol (chart label only; connect MT5 to change its data)",
    S.symbol,
  );
  if (symbol && /^[a-zA-Z0-9._/-]{1,40}$/.test(symbol)) {
    S.symbol = symbol;
    $("symbolButton").innerHTML = esc(symbol) + " <span>⌄</span>";
    restoreDrawings();
    paint();
  }
};
document.querySelectorAll("[data-window]").forEach(
  (b) =>
    (b.onclick = () => {
      S.bands = b.dataset.window === "both" ? "both" : +b.dataset.window;
      S.window = S.bands === "both" ? 42 : S.bands;
      document
        .querySelectorAll("[data-window]")
        .forEach((v) => v.classList.toggle("active", v === b));
      $("activeWindow").innerHTML = `${S.window}<span>minutes</span>`;
      refreshPanes();
      paint();
    }),
);
$("windowMode").onchange = (e) => {
  S.mode = e.target.value;
  $("alignmentLabel").textContent =
    S.mode === "aligned" ? "New York clock" : "Trailing closed bars";
  refreshPanes();
  paint();
};
$("displayTimezone").onchange = (e) => {
  S.timezone = e.target.value;
  paint();
  refreshPanes();
};
function settings() {
  modal(
    "Transform parameters",
    `<p>Parameters apply to all transform panes. Analysis always uses closed bars.</p><div class="form-grid"><label><span class="field-label">Input series</span><select class="box" id="paramSource">${["close", "typical", "return", "range", "volume"].map((v) => `<option ${S.params.source === v ? "selected" : ""}>${v}</option>`).join("")}</select></label><label><span class="field-label">Preprocessing</span><select class="box" id="paramPre">${["zscore", "detrend", "none", "log"].map((v) => `<option ${S.params.preprocessing === v ? "selected" : ""}>${v}</option>`).join("")}</select></label><label><span class="field-label">Delay τ (bars)</span><input id="paramTau" type="number" min="1" max="32" value="${S.params.tau}"></label><label><span class="field-label">Embedding dimension</span><input id="paramDim" type="number" min="2" max="6" value="${S.params.dimension}"></label><label><span class="field-label">Target recurrence rate</span><input id="paramRR" type="number" min="0.01" max="0.5" step="0.01" value="${S.params.recurrence_rate}"></label><label><span class="field-label">Wavelet</span><select class="box" id="paramWave">${["morl", "mexh", "cmor1.5-1.0"].map((v) => `<option ${S.params.wavelet === v ? "selected" : ""}>${v}</option>`).join("")}</select></label><label><span class="field-label">Price scale</span><select class="box" id="paramScale">${["linear", "log", "percent"].map((v) => `<option ${S.scale === v ? "selected" : ""}>${v}</option>`).join("")}</select></label></div><div class="modal-actions"><button class="button" id="embeddingHelper">Estimate τ / dimension</button><button class="button primary" id="applyParams">Apply parameters</button></div>`,
  );
  $("embeddingHelper").onclick = async () => {
    try {
      const result = await post("/api/embedding-helpers", {
        module: "phase",
        start: S.selection?.[0] ?? null,
        end: S.selection?.[1] ?? null,
        params: S.params,
      });
      modal(
        "Embedding suggestions",
        `<p>${esc(result.note)}</p><div class="inline-note">Suggested delay: ${result.suggested_tau} bars · suggested dimension: ${result.suggested_dimension}</div><div id="helperMI" style="height:190px"></div><div id="helperFNN" style="height:190px"></div><div class="modal-actions"><button class="button primary" id="useEmbedding">Use suggestions</button></div>`,
      );
      const layout = {
        margin: { l: 45, r: 15, t: 20, b: 35 },
        font: { size: 10 },
        xaxis: { title: { text: "Delay / bars" } },
        yaxis: { title: { text: "Mutual information" } },
      };
      Plotly.newPlot(
        $("helperMI"),
        [
          {
            x: result.lags,
            y: result.mutual_information,
            mode: "lines+markers",
            line: { color: "#397d70" },
          },
        ],
        layout,
        { displayModeBar: false },
      );
      Plotly.newPlot(
        $("helperFNN"),
        [
          {
            x: result.dimensions,
            y: result.false_neighbor_fraction,
            mode: "lines+markers",
            line: { color: "#397d70" },
          },
        ],
        {
          ...layout,
          xaxis: { title: { text: "Dimension" } },
          yaxis: { title: { text: "False-neighbor fraction" } },
        },
        { displayModeBar: false },
      );
      $("useEmbedding").onclick = () => {
        S.params.tau = result.suggested_tau;
        S.params.dimension = result.suggested_dimension;
        $("modal").close();
        refreshPanes();
      };
    } catch (e) {
      toast(e.message);
    }
  };
  $("applyParams").onclick = () => {
    S.params = {
      source: $("paramSource").value,
      preprocessing: $("paramPre").value,
      tau: +$("paramTau").value,
      dimension: +$("paramDim").value,
      recurrence_rate: +$("paramRR").value,
      wavelet: $("paramWave").value,
      taper: S.params.taper,
    };
    S.scale = $("paramScale").value;

    $("inputLabel").textContent =
      S.params.source + " · " + S.params.preprocessing;
    $("modal").close();
    paint();
    refreshPanes();
  };
}
$("openSettings").onclick = settings;
$("parametersButton").onclick = settings;
function dataDialog() {
  modal(
    "Connect your data",
    `<p>Import a CSV or connect a local MetaTrader 5 terminal. Your data stays on your computer.</p><h3>CSV history</h3><div class="inline-note"><strong>Have your CSV in New York time.</strong> For local date/time columns, use America/New_York (default). If your file uses another timezone, select that timezone below. Explicit offsets and Unix timestamps keep their actual instant.</div><div class="form-grid"><label><span class="field-label">File timezone</span><select class="box" id="fileZone"><option value="America/New_York">New York (recommended)</option><option>UTC</option><option>Asia/Tehran</option><option>Europe/London</option></select></label><label><span class="field-label">Optional local CSV path</span><input id="csvPath" placeholder="C:\\Data\\XAUUSD.csv"></label></div><div class="upload-zone" id="dropZone">Drop an OHLCV CSV here<input type="file" id="csvFile" accept=".csv,.tsv,.txt"><div class="micro">Auto-detected comma, tab or semicolon · maximum 32 MiB</div></div><div class="modal-actions"><button class="button" id="loadPath">Load local path</button><button class="button primary" id="importCSV">Import CSV</button></div><h3>MetaTrader 5</h3><p class="micro">Windows only. Install the optional MT5 package and sign in to the terminal first.</p><div class="form-grid"><label><span class="field-label">Broker symbol</span><input id="mtSymbol" value="${esc(S.liveSettings?.symbol || S.symbol)}"></label><label><span class="field-label">Source timeframe</span><select id="mtTF" class="box"><option>M1</option><option>M5</option><option>M15</option><option>H1</option></select></label><label><span class="field-label">History bars</span><input id="mtCount" type="number" min="100" max="100000" value="10000"></label><label><span class="field-label">Broker server time</span><select id="mtServer" class="box"><option value="auto">Auto-detect (recommended)</option><option value="ny_close">GMT+2/+3 · NY close (most FX/gold brokers)</option><option value="eet">GMT+2/+3 · Eastern Europe DST</option><option value="utc">GMT+0 (UTC)</option><option value="UTC+1">Fixed GMT+1</option><option value="UTC+2">Fixed GMT+2</option><option value="UTC+3">Fixed GMT+3</option></select></label><label><span class="field-label">Live updates</span><input id="mtLive" type="checkbox" ${S.live ? "checked" : ""}> Poll every 5 seconds</label></div><div class="modal-actions"><button class="button" id="stopLive">Disconnect live</button><button class="button primary" id="connectMT">Connect MT5</button></div><p id="dataMessage" class="micro"></p><div class="modal-actions"><button class="text-button" id="loadDemo">Load synthetic demo data</button></div>`,
  );
  let chosen = null;
  $("csvFile").onchange = (e) => (chosen = e.target.files[0]);
  $("dropZone").ondragover = (e) => e.preventDefault();
  $("dropZone").ondrop = (e) => {
    e.preventDefault();
    chosen = e.dataTransfer.files[0];
    $("dataMessage").textContent = chosen?.name || "";
  };
  async function importAction(path = false) {
    const button = path ? $("loadPath") : $("importCSV");
    try {
      button.disabled = true;
      let result;
      if (path) {
        result = await post("/api/import-path", {
          path: $("csvPath").value,
          timezone: $("fileZone").value,
        });
      } else {
        if (!chosen) throw Error("Choose a CSV file first.");
        const data = new FormData();
        data.append("file", chosen);
        data.append("timezone", $("fileZone").value);
        result = await api("/api/import", { method: "POST", body: data });
      }
      stopLive();
      S.selection = null;
      await loadBars();
      $("modal").close();
      reportDialog(result);
    } catch (e) {
      $("dataMessage").textContent = e.message;
      $("dataMessage").className = "file-error micro";
    } finally {
      button.disabled = false;
    }
  }
  $("importCSV").onclick = () => importAction();
  $("loadPath").onclick = () => importAction(true);
  $("connectMT").onclick = async () => {
    const cfg = {
        symbol: $("mtSymbol").value,
        timeframe: $("mtTF").value,
        count: +$("mtCount").value,
        server_time: $("mtServer").value,
      },
      live = $("mtLive").checked;
    try {
      $("connectMT").disabled = true;
      const report = await post("/api/mt5", cfg);
      stopLive();
      S.liveSettings = cfg;
      S.symbol = cfg.symbol;
      $("symbolButton").innerHTML = esc(S.symbol) + " <span>⌄</span>";
      restoreDrawings();
      await loadBars();
      if (live) startLive();
      $("modal").close();
      const st = report.server_time;
      toast(
        st
          ? `MT5 loaded · server clock ${st.label} (${st.how})`
          : "MT5 history loaded",
      );
      if (st?.warning || report.clock_check?.ok === false)
        setTimeout(
          () =>
            toast(
              st?.warning ||
                `Daily break appears at ${report.clock_check.daily_break_ny} NY (expected 17:00). Check Broker server time.`,
            ),
          2600,
        );
    } catch (e) {
      $("dataMessage").textContent = e.message;
      $("connectMT").disabled = false;
    }
  };
  $("stopLive").onclick = () => {
    stopLive();
    toast("Live polling stopped");
  };
  $("loadDemo").onclick = async () => {
    try {
      stopLive();
      await post("/api/demo", {});
      S.selection = null;
      await loadBars();
      $("modal").close();
      toast("Synthetic demo loaded");
    } catch (e) {
      toast(e.message);
    }
  };
}
function stopLive() {
  clearTimeout(S.live);
  S.live = null;
  $("connection").textContent = "Local session";
}
function startLive() {
  stopLive();
  let busy = false;
  const poll = async () => {
    if (busy) return;
    busy = true;
    try {
      await post("/api/mt5", S.liveSettings);
      await loadBars(true);
      $("connection").textContent = "MT5 · live";
    } catch (e) {
      $("connection").textContent = "MT5 · reconnecting";
      $("footerStatus").textContent = e.message + " — retrying in 5 seconds";
    } finally {
      busy = false;
      S.live = setTimeout(poll, 5000);
    }
  };
  S.live = setTimeout(poll, 5000);
  $("connection").textContent = "MT5 · live";
}
$("openData").onclick = dataDialog;
function reportDialog(report = S.report) {
  modal(
    "Import report",
    `<p>${esc(report.source || "Synthetic demo history")}</p><div class="report-grid">${[
      ["Input rows", report.input_rows],
      ["Accepted rows", report.valid_rows],
      ["Invalid rows removed", report.bad_rows],
      ["Duplicate times removed", report.duplicates_removed],
      ["Gap intervals", report.gaps],
      ["Source interval (seconds)", report.interval_seconds],
    ]
      .map(([k, v]) => `<div>${k}<strong>${fmt(v, 0)}</strong></div>`)
      .join(
        "",
      )}</div><p>${esc(report.policy)}</p><p class="micro">Bad row examples: ${esc((report.bad_row_examples || []).join(", ") || "None")}<br>Gap examples: ${esc((report.gap_examples || []).join(" · ") || "None")}</p><p class="inline-note">CSV bars are treated as historical closed bars. Remove a forming candle before importing live exports.</p>`,
  );
}
$("viewReport").onclick = () => reportDialog();
function trainingDialog() {
  const selectedCount = S.selection
    ? Math.round((S.selection[1] - S.selection[0]) / 60) + 1
    : 0;
  const shortWindow = [14, 42].includes(selectedCount);
  const forecastHorizon = shortWindow ? selectedCount : S.window;
  modal(
    "Configure a training run",
    `<p>The model predicts the next window’s direction and high–low range. It trains only after you click Start training.</p><div class="inline-note">${S.selection ? `Forecast input: ${time(S.selection[0], true)} — ${time(S.selection[1] + 60, true)} NY. Training uses earlier loaded history up to this cutoff` : "Scope: the most recent 20,000 closed source bars, or all history if fewer."}<br>Forming bars are excluded. Training features use fixed per-window parameters, independently of visualization settings.</div><div class="form-grid"><label><span class="field-label">Forecast horizon</span><select id="trainHorizon" class="box" ${shortWindow ? "disabled" : ""}><option value="14" ${forecastHorizon === 14 ? "selected" : ""}>Next 14 minutes</option><option value="42" ${forecastHorizon === 42 ? "selected" : ""}>Next 42 minutes</option></select></label><label><span class="field-label">Model</span><select id="trainModel" class="box"><option value="trees">ExtraTrees</option><option value="linear">Logistic + Ridge</option></select></label><label><span class="field-label">Window sampling</span><select id="trainMode" class="box"><option value="aligned" ${S.mode === "aligned" ? "selected" : ""}>NY-clock aligned</option><option value="rolling" ${S.mode === "rolling" ? "selected" : ""}>Rolling (purged overlap)</option></select></label></div><span class="field-label">Transform features</span><div class="check-list">${Object.keys(
      names,
    )
      .filter((v) => !["topology", "metrics", "surface"].includes(v))
      .map(
        (v) =>
          `<label><input type="checkbox" name="feature" value="${v}" checked> ${names[v]}</label>`,
      )
      .join(
        "",
      )}</div><p class="micro">80% development / 20% final test · chronological walk-forward checks · labels crossing a split are purged · baseline comparisons and moving-block intervals. At least 60 complete examples are required.</p><div class="modal-actions"><button class="button primary" id="startTraining">Start training</button></div>`,
  );
  $("startTraining").onclick = async () => {
    try {
      $("startTraining").disabled = true;
      const recent = S.bars[Math.max(0, S.bars.length - 20000)];
      const run = {
        horizon: +$("trainHorizon").value,
        mode: $("trainMode").value,
        model: $("trainModel").value,
        selected: [...document.querySelectorAll("[name=feature]:checked")].map(
          (e) => e.value,
        ),
        timezone: "America/New_York",
        start: shortWindow
          ? null
          : (S.selection?.[0] ?? S.trainingStart ?? recent.time),
        forecast_start: shortWindow ? S.selection[0] : null,
        end: S.selection?.[1] ?? S.bars.at(-1).time,
      };
      const out = await post("/api/train", run);
      S.job = out.job_id;
      S.jobSel = selectionKey();
      $("modal").close();
      $("jobProgress").classList.remove("hidden");
      $("openTraining").disabled = true;
      pollJob();
    } catch (e) {
      toast(e.message);
      $("startTraining").disabled = false;
    }
  };
}
$("openTraining").onclick = () => {
  if (!S.job) trainingDialog();
};
async function pollJob() {
  try {
    const job = await api("/api/jobs/" + S.job);
    $("progressBar").style.width = job.progress + "%";
    $("progressPercent").textContent = job.progress + "%";
    $("progressMessage").textContent = job.message;
    if (job.status === "running") {
      setTimeout(pollJob, 650);
      return;
    }
    S.job = null;
    $("openTraining").disabled = false;
    if (job.status === "failed") {
      toast(job.message);
      $("progressMessage").textContent = job.message;
      return;
    }
    if (S.jobSel !== selectionKey()) {
      $("jobProgress").classList.add("hidden");
      toast("The chosen window changed during training, so that result was discarded.");
      return;
    }
    job.sel = S.jobSel;
    S.forecast = job;
    S.forecastRangeEnabled = true;
    if ($("rangeToggle")) $("rangeToggle").checked = true;
    if ($("rangeToggleLabel")) $("rangeToggleLabel").classList.remove("hidden");
    showForecast();
    paint();
    toast(
      "Training complete. Open evaluation to inspect the held-out results.",
    );
  } catch (e) {
    $("progressMessage").textContent = "Connection interrupted. Retrying…";
    setTimeout(pollJob, 2000);
  }
}
function showForecast() {
  const r = S.forecast.result,
    f = r.forecast;
  $("forecastEmpty").classList.add("hidden");
  $("forecastResult").classList.remove("hidden");
  $("forecastResult").innerHTML =
    `<div class="forecast-number">${f.direction} <span style="font-size:15px">${fmt(Math.max(f.up_probability, 1 - f.up_probability) * 100, 1)}%</span></div><div class="forecast-caption">${r.horizon}m forecast · ${time(f.asof, true)}</div><div class="desk-row"><span>Range estimate</span><strong>${fmt(f.range)}</strong></div><div class="desk-row"><span>Held-out accuracy</span><strong>${fmt(r.accuracy * 100, 1)}%</strong></div><div class="desk-row"><span>95% block interval</span><strong>${r.accuracy_interval.map((v) => fmt(v * 100, 1)).join("–")}%</strong></div><button class="text-button" id="openEvaluation">Review evaluation ↗</button><p class="micro muted">Research estimate. A single run does not establish predictive value. The ghost band illustrates total range, not price quantiles.</p>`;
  $("openEvaluation").onclick = evaluationDialog;
  $("openTraining").textContent = "Configure another run";
  $("jobProgress").classList.add("hidden");
}
function evaluationDialog() {
  const r = S.forecast.result;
  modal(
    "Held-out evaluation",
    `<div class="report-grid"><div>Direction accuracy<strong>${fmt(r.accuracy * 100, 1)}%</strong></div><div>Probability Brier score<strong>${fmt(r.brier_score, 3)}</strong></div></div><p>${r.train_examples} training examples · ${r.test_examples} final-test examples · ${r.purged_examples} purged examples</p><table><thead><tr><th>Comparator</th><th>Held-out accuracy</th></tr></thead><tbody><tr><td>${esc(r.model)} + selected transforms</td><td>${fmt(r.accuracy * 100, 1)}%</td></tr>${Object.entries(
      r.baselines,
    )
      .map(
        ([k, v]) => `<tr><td>${esc(k)}</td><td>${fmt(v * 100, 1)}%</td></tr>`,
      )
      .join(
        "",
      )}</tbody></table><p class="micro">95% accuracy interval: ${r.accuracy_interval.map((v) => fmt(v * 100, 1)).join("–")}%. ${esc(r.interval_method)}</p><h3>Range error</h3><p>Model MAE: ${fmt(r.range_mae)} · training-median baseline MAE: ${fmt(r.range_baseline_mae)}</p><h3>Confusion matrix</h3><table><tr><th>Actual / predicted</th><th>Down</th><th>Up</th></tr><tr><td>Down</td><td>${r.confusion[0][0]}</td><td>${r.confusion[0][1]}</td></tr><tr><td>Up</td><td>${r.confusion[1][0]}</td><td>${r.confusion[1][1]}</td></tr></table><h3>Calibration (up probability)</h3><table><tr><th>Mean predicted</th><th>Observed up rate</th><th>Count</th></tr>${r.calibration.map((c) => `<tr><td>${fmt(c.predicted, 2)}</td><td>${fmt(c.observed, 2)}</td><td>${c.n}</td></tr>`).join("")}</table><h3>Walk-forward checks</h3><table><tr><th>Training examples</th><th>Validation examples</th><th>Accuracy</th></tr>${r.folds.map((f) => `<tr><td>${f.train_examples}</td><td>${f.validation_examples}</td><td>${fmt(f.accuracy * 100, 1)}%</td></tr>`).join("")}</table><h3>Feature importance</h3><table>${r.importance.map((v) => `<tr><td>${esc(v.feature)}</td><td>${fmt(v.importance, 3)}</td></tr>`).join("")}</table><p class="micro">Importance is model-specific and does not establish causality. ${esc(r.fit_policy)}</p><div class="inline-note">${esc(r.assessment)}</div><div class="modal-actions"><button class="button" id="exportEvaluation">Export evaluation JSON</button></div>`,
  );
  $("exportEvaluation").onclick = () =>
    download("lumenspace-evaluation.json", S.forecast);
}
function workspace() {
  return {
    schema: 1,
    name: $("workspaceName").value,
    symbol: S.symbol,
    timeframe: S.tf,
    window: S.window,
    bands: S.bands,
    mode: S.mode,
    timezone: S.timezone,
    params: S.params,
    theme: S.theme,
    scale: S.scale,
    priceHeight: canvas.parentElement.getBoundingClientRect().height,
    panes: S.panes.map(({ id, module, view, height }) => ({
      id,
      module,
      view,
      height,
    })),
    drawings: S.drawings,
    selection: S.selection,
    integration: {
      surfaceParams: S.surfaceParams,
      surfaceHorizon: S.surfaceHorizon,
      goldenEnabled: S.goldenEnabled,
      pathEnabled: S.pathEnabled,
      recurrenceEnabled: S.recurrenceEnabled,
      waveletEnabled: S.waveletEnabled,
      quantum: S.quantum,
      mintick: S.mintick,
    },
  };
}
$("saveWorkspace").onclick = () => {
  try {
    localStorage.setItem("lumenspace.workspace", JSON.stringify(workspace()));
    saveDrawings();
    toast("Workspace saved in this browser");
  } catch {
    toast("Could not save. Export the workspace JSON.");
  }
};
$("exportWorkspace").onclick = () =>
  download("lumenspace-workspace.json", workspace());
async function applyWorkspace(w) {
  if (
    w.schema !== 1 ||
    !Array.isArray(w.panes) ||
    w.panes.length > 8 ||
    w.panes.some(
      (p) =>
        !names[p.module] || !paneViews(p.module).some((v) => v[0] === p.view),
    ) ||
    !validDrawings(w.drawings) ||
    ![1, 5, 15, 60].includes(w.timeframe) ||
    ![14, 42].includes(w.window) ||
    !["aligned", "rolling"].includes(w.mode) ||
    !["linear", "log", "percent"].includes(w.scale) ||
    typeof w.symbol !== "string" ||
    !w.params
  )
    throw Error("Invalid workspace file");
  for (const p of w.panes) p.id = p.module + "-" + crypto.randomUUID();
  Object.assign(S, {
    symbol: w.symbol,
    tf: w.timeframe,
    window: w.window,
    bands: w.bands,
    mode: w.mode,
    timezone: "America/New_York",
    params: w.params,
    theme: "light",
    scale: w.scale,
    panes: w.panes,
    drawings: w.drawings,
  });
  if (Number.isFinite(w.priceHeight))
    canvas.parentElement.style.height =
      Math.max(300, Math.min(1600, w.priceHeight)) + "px";
  $("workspaceName").value = w.name || "Workspace";
  $("timeframe").value = S.tf;
  $("windowMode").value = S.mode;
  $("displayTimezone").value = S.timezone;
  $("symbolButton").innerHTML = esc(S.symbol) + " <span>⌄</span>";
  $("activeWindow").innerHTML = `${S.window}<span>minutes</span>`;
  $("alignmentLabel").textContent =
    S.mode === "aligned" ? "New York clock" : "Trailing closed bars";
  $("inputLabel").textContent =
    S.params.source + " · " + S.params.preprocessing;
  document
    .querySelectorAll("[data-window]")
    .forEach((b) =>
      b.classList.toggle("active", b.dataset.window === String(S.bands)),
    );

  if (
    w.selection &&
    Array.isArray(w.selection) &&
    w.selection.length === 2 &&
    w.selection.every(Number.isFinite)
  )
    S.selection = w.selection;
  if (w.integration && typeof restoreIntegration === "function")
    restoreIntegration(w.integration);
  saveDrawings();
  makePanes();
  await loadBars();
}
$("loadWorkspace").onclick = () =>
  readJSON((w) => applyWorkspace(w).catch((e) => toast(e.message)));
$("openHelp").onclick = () =>
  modal(
    "A quick guide to LumenSpace",
    `<p><strong>1. Load history.</strong> Import an OHLCV CSV in Data sources, or connect MT5 on Windows. The included demo is synthetic and only demonstrates the interface.</p><p><strong>2. Choose your perspective.</strong> Set 14m or 42m, select aligned or rolling windows, inspect the four permanent research charts. Choose window marks the exact source candles in teal. All four charts use the marked window; fit or apply the surface when ready. Select a range with the shaded-square tool or the S shortcut to inspect another period (6–512 source bars).</p><p><strong>3. Link the views.</strong> Hover the price chart, a trajectory point or a time-based heatmap to highlight the corresponding time. On spatial transforms, coordinates are states rather than timestamps.</p><p><strong>4. Draw your observations.</strong> Pick a tool, drag two points, and release. In cursor mode, drag drawings to move them or their second handle to resize. Double-click a drawing to edit its style and lock. Ctrl+Z / Ctrl+Y undo and redo.</p><p><strong>5. Test a hypothesis.</strong> For a selected 14- or 42-candle window, Configure & train uses earlier loaded history up to that window’s end and forecasts from its exact candles. At least 60 historical examples are needed. Evaluation includes chronological splits, overlap purging, baselines, calibration and confidence intervals.</p><p><strong>6. Save your workspace.</strong> Save in the browser or export JSON. CSV data is cached in SQLite by the backend. No trading orders or account credentials are collected.</p><div class="inline-note">14- and 42-minute windows are short. Transform geometry can be useful to inspect, but patterns and model scores require independent validation. See docs/STATUS.md for exact scope and deferred features.</div>`,
  );
async function init() {
  try {
    const saved =
      localStorage.getItem("lumenspace.workspace") ||
      localStorage.getItem("lumen.workspace");
    if (saved) {
      await applyWorkspace(JSON.parse(saved));
    } else {
      restoreDrawings();
      makePanes();
      await loadBars();
    }
  } catch (e) {
    toast(e.message);
    makePanes();
    await loadBars().catch((e) => toast(e.message));
  }
}
if (document.readyState !== "complete")
  document.addEventListener("DOMContentLoaded", init, { once: true });
else init();
