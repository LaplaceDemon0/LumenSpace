/* Existing surface engine + explicit shared window selection. ML stays optional. */
Object.assign(S, {
  surfaceParams: {
    push: 1,
    throw: 1,
    coupling: 0.15,
    damping: 0.15,
    dent_scale: 1,
    depth: 0,
    sigma_x: 2,
    sigma_y: 1,
    tau: 3,
    strength: 1,
    projection: "reflect",
    anchor: "close",
    kernel: "gaussian",
    background_k: 0,
    ring_weight: 1,
    rules: {
      body_min: 0,
      body_max: 100,
      upper_min: 0,
      upper_max: 100,
      lower_min: 0,
      lower_max: 100,
      range_min: 0,
      direction: "any",
      top_n: 0,
    },
  },
  surfaceHorizon: 42,
  surfaceResult: null,
  surfaceFit: null,
  surfaceModelId: null,
  useSurfaceML: false,
  goldenEnabled: true,
  pathEnabled: true,
  recurrenceEnabled: true,
  waveletEnabled: true,
  quantum: 0.25,
  mintick: 0.01,
  goldenResult: null,
});
const DEFAULT_SURFACE_PARAMETERS = structuredClone(S.surfaceParams);
let surfaceRevision = 0;
let selectedIntegrationKey = null,
  levelEpoch = 0;
function selectionKey() {
  return JSON.stringify([S.selection, S.window, S.mode, S.version]);
}
function surfaceRequest() {
  return {
    start: S.selection?.[0] ?? null,
    end: S.selection?.[1] ?? null,
    minutes: S.window,
    mode: S.mode,
    horizon: S.surfaceHorizon,
    parameters: S.surfaceParams,
    quantum: S.quantum,
    mintick: S.mintick,
    model_id: S.useSurfaceML ? S.surfaceModelId : null,
  };
}
function restoreIntegration(i) {
  if (i.surfaceParams && typeof i.surfaceParams === "object")
    S.surfaceParams = i.surfaceParams;
  if (
    Number.isInteger(i.surfaceHorizon) &&
    i.surfaceHorizon >= 1 &&
    i.surfaceHorizon <= 120
  )
    S.surfaceHorizon = i.surfaceHorizon;
  S.goldenEnabled = i.goldenEnabled !== false;
  S.pathEnabled = i.pathEnabled !== false;
  S.recurrenceEnabled = i.recurrenceEnabled !== false;
  S.waveletEnabled = i.waveletEnabled !== false;
  if (Number.isFinite(i.quantum) && i.quantum > 0) S.quantum = i.quantum;
  if (Number.isFinite(i.mintick) && i.mintick > 0) S.mintick = i.mintick;
  syncSurfaceControls();
}
const desk = document.createElement("section");
desk.className = "card surface-desk";
desk.id = "surfaceDesk";
desk.innerHTML = `<div class="surface-desk-heading"><div><div class="pane-kicker">SURFACE / FORECAST METHOD</div><h2>Fit the physics. Explore the future.</h2><p id="surfaceScope">Choose and mark a source window to link every view.</p></div><div class="surface-options"><label><input id="surfaceMLToggle" type="checkbox"> ML future surface</label></div></div><div class="surface-control-row"><button id="surfaceParameters" class="button small">Surface parameters</button><button id="fitSurface" class="button small">Fit parameters</button><button id="applySurface" class="button primary small">Apply parameters & simulate</button><button id="resetSurface" class="button small">Reset defaults</button><button id="learnSurface" class="button small">Start surface learning</button><button id="viewGolden" class="text-button">View 85-rung ladder ↗</button><button id="viewSurfaceFit" class="text-button hidden">Fit report ↗</button></div><div id="surfaceJob" class="hidden progress-area"><div class="progress-track"><span id="surfaceProgressBar"></span></div><div class="progress-caption"><span id="surfaceProgressMessage"></span><strong id="surfaceProgressPercent"></strong></div></div><div id="surfaceMessage" class="micro muted">Original surface physics. Fitting, applying and learning are separate actions.</div></section>`;
document.querySelector(".price-card").after(desk);
const overlayControls = document.createElement("div");
overlayControls.className = "chart-overlay-controls";
overlayControls.innerHTML =
  '<span>Price chart layers</span><label><input id="goldenToggle" type="checkbox" checked> GoldenShadow levels</label><label><input id="pathToggle" type="checkbox" checked> Forecast path</label><label id="rangeToggleLabel" class="hidden"><input id="rangeToggle" type="checkbox" checked> Forecast range</label><label><input id="recurrenceToggle" type="checkbox" checked> Recurrence levels</label><label><input id="waveletToggle" type="checkbox" checked> Wavelet cycle</label>';
document.querySelector(".canvas-wrap").before(overlayControls);
for (const [id, key] of [
  ["pathToggle", "pathEnabled"],
  ["rangeToggle", "forecastRangeEnabled"],
  ["recurrenceToggle", "recurrenceEnabled"],
  ["waveletToggle", "waveletEnabled"],
]) {
  $(id).onchange = (e) => {
    S[key] = e.target.checked;
    paintSoon();
  };
}

const workflow = document.createElement("section");
workflow.className = "card window-workflow";
workflow.innerHTML = `<div class="workflow-steps"><span class="done">1 · Load data</span><span id="windowStep" class="current">2 · Choose window</span><span id="analysisStep">3 · Explore linked charts</span></div><div class="chosen-window"><div><span id="windowBadge" class="window-badge">No window selected</span><h3 id="chosenWindowTitle">Choose the candles you want to study.</h3><p id="chosenWindowDetail">A colored region on the chart will show the exact source window.</p></div><div class="workflow-actions"><button class="button small" id="changeWindow">Choose window</button><button class="button primary small" id="addSelectedAnalysis" disabled>Explore charts</button></div></div><div class="ny-clock-row"><span>Chart · New York time</span><span id="nyClockNow"></span><span id="nyFeedStatus"></span></div>`;
document.querySelector(".price-card").before(workflow);
$("changeWindow").onclick = () => chooseWindow();
$("addSelectedAnalysis").onclick = () => $("addPane").click();
function nyTime(t) {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(t * 1000));
}
let clockSnapshot = null;
async function refreshNYClock() {
  try {
    clockSnapshot = await api("/api/time-status");
    renderNYClock();
  } catch {}
}
function renderNYClock() {
  if (!clockSnapshot) return;
  const c = clockSnapshot;
  $("nyClockNow").textContent = "NY now · " + nyTime(Date.now() / 1000);
  const shift = c.latest_candle_offset_seconds / 3600;
  const st = c.server_time;
  const server = st
    ? ` · MT5 server ${c.latest_candle_server} (GMT${st.offset_seconds < 0 ? "−" : "+"}${Math.abs(st.offset_seconds / 3600)}) →`
    : "";
  const check = c.clock_check && c.clock_check.ok === false
    ? ` · ⚠ daily break at ${c.clock_check.daily_break_ny} NY, expected 17:00`
    : "";
  $("nyFeedStatus").textContent =
    `Latest candle${server} ${nyTime(c.latest_candle_utc)} NY (UTC${shift < 0 ? "−" : "+"}${Math.abs(shift)}) · ${c.status}${check}`;
  $("nyFeedStatus").title = (st?.warning ? st.warning + " " : "") + c.policy;
}
setInterval(renderNYClock, 1000);
function syncWindowWorkflow() {
  const selected = !!S.selection;
  const surfaceAdded = S.panes.some((p) => p.module === "surface");
  desk.classList.toggle("hidden", !selected || !surfaceAdded);
  $("windowBadge").textContent = selected
    ? "TEAL · SELECTED SOURCE"
    : "No window selected";
  $("windowBadge").classList.toggle("selected", selected);
  $("chosenWindowTitle").textContent = selected
    ? `${nyTime(S.selection[0])} → ${nyTime(S.selection[1] + 60)} NY`
    : "Choose the candles you want to study.";
  $("chosenWindowDetail").textContent = selected
    ? `${Math.round((S.selection[1] - S.selection[0]) / 60) + 1} closed M1 candles · All four charts use this exact range.`
    : "A colored region on the chart will show the exact source window.";
  $("changeWindow").textContent = selected ? "Change window" : "Choose window";
  $("addSelectedAnalysis").disabled = !selected;
  $("refreshAnalysis").disabled = !selected;
  $("windowStep").className = selected ? "done" : "current";
  $("analysisStep").className = selected ? "current" : "";
  if ($("emptyHint"))
    $("emptyHint").textContent = selected
      ? "Your window is marked in teal. Explore the four linked charts below."
      : "Choose a time window above to begin.";
}
function syncSurfaceControls() {
  if ($("goldenToggle")) $("goldenToggle").checked = S.goldenEnabled;
  if ($("pathToggle")) $("pathToggle").checked = S.pathEnabled;
  if ($("recurrenceToggle"))
    $("recurrenceToggle").checked = S.recurrenceEnabled;
  if ($("waveletToggle")) $("waveletToggle").checked = S.waveletEnabled;
  if ($("surfaceMLToggle")) $("surfaceMLToggle").checked = S.useSurfaceML;
}
function updateIntegrationSelection() {
  syncWindowWorkflow();
  const key = selectionKey();
  if (key !== selectedIntegrationKey) {
    selectedIntegrationKey = key;
    S.surfaceResult = null;
    S.linkedTimes = [];
    S.analysisProbe = null;
    S.goldenResult = null;
    S.surfaceModelId = null;
    S.surfaceFit = null;
    $("viewSurfaceFit").classList.add("hidden");
    S.useSurfaceML = false;
    syncSurfaceControls();
    if (S.bars.length && S.selection) refreshGoldenLevels();
    else {
      levelEpoch++;
      S.goldenResult = null;
    }
  }
  if ($("surfaceScope"))
    $("surfaceScope").textContent = S.selection
      ? `Marked source: ${time(S.selection[0], true)} → ${time(S.selection[1] + 60, true)} · closed M1 bars`
      : `Source: latest complete ${S.window}m ${S.mode} window`;
}
async function refreshGoldenLevels() {
  if (!S.selection) return;
  const epoch = ++levelEpoch;
  if (!S.goldenEnabled) {
    S.goldenResult = null;
    paintSoon();
    return;
  }
  try {
    const result = await post("/api/golden-levels", surfaceRequest());
    if (epoch !== levelEpoch) return;
    S.goldenResult = result;
    $("surfaceMessage").textContent =
      `GoldenShadow · ATR ${fmt(result.selected.atr, 3)} · rung ${result.selected.rung}/84 · up ${fmt(result.selected.up)} · down ${fmt(result.selected.down)}`;
    paintSoon();
  } catch (e) {
    if (epoch === levelEpoch) {
      S.goldenResult = null;
      $("surfaceMessage").textContent = e.message;
      paintSoon();
    }
  }
}
$("goldenToggle").onchange = (e) => {
  S.goldenEnabled = e.target.checked;
  refreshGoldenLevels();
};
$("surfaceMLToggle").onchange = (e) => {
  if (e.target.checked && !S.surfaceModelId) {
    e.target.checked = false;
    toast("Click Start surface learning for this marked window first.");
    return;
  }
  S.useSurfaceML = e.target.checked;
  $("surfaceMessage").textContent = S.useSurfaceML
    ? "Learned future surface enabled. Click Apply parameters & simulate."
    : "Original surface physics selected. Click Apply parameters & simulate.";
};
function localDateInput(ts) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: S.timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date(ts * 1000));
  const get = (k) => parts.find((p) => p.type === k).value;
  return `${get("year")}-${get("month")}-${get("day")}T${get("hour")}:${get("minute")}`;
}
async function chooseWindow() {
  const end = S.selection?.[1] ?? S.bars.findLast((b) => b.closed)?.time;
  if (!end) return;
  modal(
    "Choose & mark the source window",
    `<p>The same marked source candles drive the transforms, surface and GoldenShadow levels. End time is exclusive.</p><div class="form-grid"><label><span class="field-label">Start (${esc(S.timezone)})</span><input id="windowStart" type="datetime-local" value="${localDateInput(S.selection?.[0] ?? end - (S.window - 1) * 60)}"></label><label><span class="field-label">End (${esc(S.timezone)})</span><input id="windowEnd" type="datetime-local" value="${localDateInput(end + 60)}"></label><label class="wide"><span class="field-label">Completed ${S.window}m New York windows</span><select class="box" id="savedWindow"><option value="">Loading…</option></select></label></div><p class="micro">Use an exact clock window from the list, enter a custom contiguous range (6–512 bars), or click “Pick window on chart” and click a candle. W is the chart-pick shortcut; S draws a custom range.</p><div class="modal-actions"><button class="button" id="pickChartWindow">Pick window on chart</button><button class="button primary" id="markWindow">Mark custom range</button></div><p id="windowMessage" class="micro"></p>`,
  );
  $("pickChartWindow").onclick = () => {
    $("modal").close();
    S.pickWindow = true;
    selectTool("cursor");
    toast(`Click a candle to mark its ${S.window}m ${S.mode} window.`);
  };
  $("markWindow").onclick = async () => {
    try {
      const result = await post("/api/select-window", {
        kind: "custom",
        start: $("windowStart").value,
        end: $("windowEnd").value,
        timezone: S.timezone,
      });
      await applyMarkedWindow(result);
      $("modal").close();
    } catch (e) {
      $("windowMessage").textContent = e.message;
    }
  };
  try {
    const output = await api("/api/windows?minutes=" + S.window);
    if (!$("savedWindow")) return;
    const rows = output.windows
      .filter((w) => w.complete && w.expected === S.window)
      .reverse();
    $("savedWindow").innerHTML =
      '<option value="">Choose a completed clock window</option>' +
      rows
        .map((w) => {
          const ts = Date.parse(w.start) / 1000;
          return `<option value="${ts}">${nyTime(ts)} → ${nyTime(Date.parse(w.end) / 1000)} NY (${w.count} bars)</option>`;
        })
        .join("");
    $("savedWindow").onchange = async (e) => {
      if (!e.target.value) return;
      try {
        const result = await post("/api/select-window", {
          kind: "aligned",
          minutes: S.window,
          timestamp: +e.target.value,
        });
        await applyMarkedWindow(result);
        $("modal").close();
      } catch (e) {
        $("windowMessage").textContent = e.message;
      }
    };
  } catch (e) {
    if ($("windowMessage")) $("windowMessage").textContent = e.message;
  }
}
function focusMarkedWindow(resetPrice = true) {
  if (!S.selection || !S.bars.length) return;
  const first = indexFor(S.selection[0]),
    last = indexFor(S.selection[1]);
  const pad = Math.max(6, Math.ceil((last - first + 1) * 0.18));
  S.left = Math.max(0, first - pad);
  S.right = last + 1 + pad;
  S.cursor = last;
  if (resetPrice) S.yFactor = 1;
  paint();
}
async function applyMarkedWindow(result) {
  S.timezone = "America/New_York";
  $("displayTimezone").value = S.timezone;
  if (["aligned", "rolling"].includes(result.kind)) {
    S.mode = result.kind;
    $("windowMode").value = S.mode;
    $("alignmentLabel").textContent =
      S.mode === "aligned" ? "New York clock" : "Trailing closed bars";
  }
  S.selection = [result.start, result.last];
  S.pickWindow = false;
  selectTool("cursor");
  focusMarkedWindow();
  updateSelection();
  paint();
  await refreshPanes();
}
$("chooseWindow").onclick = chooseWindow;
canvas.addEventListener(
  "pointerdown",
  async (e) => {
    if (e.button !== 0 || !S.pickWindow || !S.range) return;
    e.stopImmediatePropagation();
    S.pickWindow = false;
    const p = position(e);
    if (p.rawIndex < 0 || p.rawIndex >= S.bars.length) {
      toast("Click a loaded candle to find its window.");
      return;
    }
    try {
      const result = await post("/api/select-window", {
        kind: S.mode,
        minutes: S.window,
        timestamp: p.time,
      });
      await applyMarkedWindow(result);
    } catch (error) {
      toast(error.message);
    }
  },
  true,
);
document.addEventListener("keydown", (e) => {
  if (
    e.key.toLowerCase() === "w" &&
    !$("modal").open &&
    !["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName)
  ) {
    S.pickWindow = true;
    toast(`Click a candle to choose its ${S.window}m window.`);
  }
});
function paintWaveletLayer(plotW, priceH, legendBottom) {
  const pane = S.panes.find((p) => p.module === "wavelet"),
    an = pane?.result?.analysis;
  if (
    !S.waveletEnabled ||
    !S.selection ||
    !an?.available ||
    pane.sourceSelection !== JSON.stringify(S.selection) ||
    pane.sourceVersion !== S.version
  )
    return;
  const bursts = an.energy.bursts;
  ctx.setLineDash([]);
  for (const b of bursts) {
    const x1 = Math.max(0, xOfTime(b.start)),
      x2 = Math.min(plotW, xOfTime(b.end));
    if (x2 <= x1) continue;
    ctx.fillStyle = "rgba(91,127,149,.10)";
    ctx.fillRect(x1, 10, x2 - x1, priceH - 10);
    ctx.fillStyle = "rgba(60,95,115,.8)";
    ctx.fillText("energy", x1 + 4, 20);
  }
  for (const m of an.marks) {
    const x = xOfTime(m.time);
    if (x < 14 || x > plotW) continue;
    const crest = m.kind === "crest";
    ctx.strokeStyle = crest ? "rgba(31,111,120,.5)" : "rgba(160,98,70,.5)";
    ctx.fillStyle = crest ? "#1f6f78" : "#a0624a";
    ctx.setLineDash(m.projected ? [5, 4] : [1, 4]);
    ctx.beginPath();
    ctx.moveTo(x, 28);
    ctx.lineTo(x, priceH);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillText(crest ? "▲" : "▼", x - 4, 34);
  }
  const reading = waveletReading(an),
    left = Math.max(8, plotW - 194),
    top = legendBottom + 14;
  ctx.fillStyle = "rgba(255,255,255,.88)";
  ctx.fillRect(left - 6, top - 14, 190, 24 + reading.legend.length * 15);
  ctx.fillStyle = "#3c5f73";
  ctx.fillText("WAVELET · DOMINANT CYCLE", left, top);
  reading.legend.forEach((line, i) =>
    ctx.fillText(line, left, top + 18 + i * 15),
  );
}
function paintIntegrationLayers(plotW, priceH) {
  ctx.save();
  ctx.beginPath();
  ctx.rect(0, 10, plotW, priceH - 10);
  ctx.clip();
  if (S.goldenEnabled && S.goldenResult?.version === S.version) {
    let levels = [...S.goldenResult.history];
    const selected = S.goldenResult.selected;
    levels = levels.filter((v) => v.start !== selected.start);
    levels.push(selected);
    ctx.lineWidth = 1;
    ctx.strokeStyle = "#b59c67";
    ctx.fillStyle = "#a88e58";
    for (const level of levels) {
      const x1 = xOfTime(level.start),
        x2 = xOfTime(level.end);
      if (x2 < 14 || x1 > plotW) continue;
      for (const price of [level.up, level.down]) {
        const y = yOfPrice(price);
        ctx.setLineDash(level === selected ? [] : [3, 3]);
        ctx.globalAlpha = level === selected ? 0.8 : 0.32;
        ctx.beginPath();
        ctx.moveTo(x1, y);
        ctx.lineTo(x2, y);
        ctx.stroke();
        if (level === selected) {
          ctx.globalAlpha = 1;
          ctx.fillText(`GS ${fmt(price)}`, x1 + 5, y - 8);
        }
      }
    }
    ctx.globalAlpha = 1;
    ctx.setLineDash([]);
  }
  let legendBottom = 32;
  const recurrence = S.panes.find((p) => p.module === "recurrence");
  if (
    S.recurrenceEnabled &&
    recurrence?.sourceSelection === JSON.stringify(S.selection) &&
    recurrence?.sourceVersion === S.version &&
    S.selection
  ) {
    const levels = recurrence.result?.potential_levels || [];
    for (const level of levels) {
      const x = xOfTime(level.time),
        top = yOfPrice(level.high),
        bottom = yOfPrice(level.low);
      ctx.fillStyle = "rgba(164,135,77,.08)";
      ctx.fillRect(
        Math.max(0, x),
        Math.min(top, bottom),
        plotW - Math.max(0, x),
        Math.max(2, Math.abs(bottom - top)),
      );
      ctx.strokeStyle = "rgba(164,135,77,.4)";
      ctx.setLineDash([4, 5]);
      ctx.beginPath();
      ctx.moveTo(x, yOfPrice(level.close));
      ctx.lineTo(plotW, yOfPrice(level.close));
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "rgba(164,135,77,.25)";
      ctx.fillRect(
        x - 3,
        Math.min(top, bottom) - 3,
        6,
        Math.max(6, Math.abs(bottom - top) + 6),
      );
    }
  }
  if (
    S.recurrenceEnabled &&
    recurrence?.sourceVersion === S.version &&
    recurrence?.sourceSelection === JSON.stringify(S.selection)
  ) {
    const levels = recurrence.result?.potential_levels || [];
    if (levels.length) {
      const left = Math.max(8, plotW - 194),
        top = 46;
      ctx.fillStyle = "rgba(255,255,255,.88)";
      ctx.fillRect(left - 6, top - 14, 190, 24 + levels.length * 15);
      ctx.fillStyle = "#8c774e";
      ctx.fillText("RECURRENCE · POTENTIAL ZONES", left, top);
      levels.forEach((level, i) =>
        ctx.fillText(
          `R${i + 1}  ${fmt(level.close)} · ${level.count} matches`,
          left,
          top + 18 + i * 15,
        ),
      );
      legendBottom = top - 14 + 24 + levels.length * 15 + 8;
    }
  }
  paintWaveletLayer(plotW, priceH, legendBottom);
  for (const t of S.linkedTimes || []) {
    const candle = S.bars[indexFor(t)];
    if (!candle) continue;
    const x = xOfTime(t),
      top = yOfPrice(candle.high),
      bottom = yOfPrice(candle.low);
    ctx.fillStyle = "rgba(20,125,117,.17)";
    ctx.fillRect(
      x - 5,
      Math.min(top, bottom) - 5,
      10,
      Math.max(10, Math.abs(bottom - top) + 10),
    );
    ctx.strokeStyle = "rgba(20,125,117,.45)";
    ctx.setLineDash([3, 4]);
    ctx.beginPath();
    ctx.moveTo(x, 10);
    ctx.lineTo(x, priceH);
    ctx.stroke();
    ctx.setLineDash([]);
  }
  if (
    S.pathEnabled &&
    S.analysisProbe &&
    Number.isFinite(S.analysisProbe.price)
  ) {
    const probe = S.analysisProbe,
      x = xOfTime(probe.time),
      y = yOfPrice(probe.price);
    ctx.strokeStyle = "rgba(53,110,116,.65)";
    ctx.setLineDash([3, 4]);
    ctx.beginPath();
    ctx.moveTo(x, 10);
    ctx.lineTo(x, priceH);
    ctx.moveTo(0, y);
    ctx.lineTo(plotW, y);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#356e74";
    ctx.fillText(
      `${probe.time > probe.asof ? "Surface scenario" : "Surface source"} · ${time(probe.time)} NY · ${fmt(probe.price)}`,
      Math.max(5, Math.min(plotW - 270, x + 5)),
      Math.max(20, y - 10),
    );
  }
  const run = S.surfaceResult;
  if (S.pathEnabled && run?.version === S.version && run.grid) {
    const tr = run.trajectory;
    ctx.lineWidth = 1.8;
    ctx.strokeStyle = "#356e74";
    ctx.setLineDash([5, 3]);
    ctx.beginPath();
    tr.time.forEach((t, i) => {
      const x = xOfTime(t),
        y = yOfPrice(tr.price[i]);
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    });
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#356e74";
    ctx.fillText(
      "Surface scenario",
      xOfTime(run.asof) + 5,
      yOfPrice(tr.price[0]) - 17,
    );
  }
  ctx.restore();
}
function ensureSurfacePane() {
  if (!S.selection) throw Error("Choose and mark a window first.");
  let p = S.panes.find((p) => p.module === "surface");
  if (!p) {
    if (S.panes.length >= 8)
      throw Error("Remove a pane first; maximum eight panes.");
    p = { id: "surface-" + crypto.randomUUID(), module: "surface", view: "3d" };
    S.panes.push(p);
    makePanes();
    for (const existing of S.panes) {
      if (existing.result) renderPane(existing);
    }
  }
  return p;
}
$("applySurface").onclick = async () => {
  try {
    const p = ensureSurfacePane();
    $("applySurface").disabled = true;
    const request = surfaceRequest(),
      key = selectionKey(),
      revision = surfaceRevision;
    const result = await post("/api/surface", request);
    if (revision !== surfaceRevision) return;
    if (key !== selectionKey())
      throw Error(
        "Window changed while computing. Apply again for the current window.",
      );
    p.result = result;
    S.surfaceResult = result;
    await renderSurfacePane(p);
    S.right = Math.max(S.right, xIndexAt(result.until) + 7);
    paint();
    $("surfaceMessage").textContent =
      `${S.useSurfaceML ? "ML future surface + original physics" : "Original physics"} · ${result.source_bars} source bars · ${S.surfaceHorizon}m scenario`;
  } catch (e) {
    toast(e.message);
  } finally {
    $("applySurface").disabled = false;
  }
};
function xIndexAt(t) {
  return (
    indexFor(t) +
    (t > S.bars.at(-1).time ? (t - S.bars.at(-1).time) / (S.tf * 60) : 0)
  );
}
async function renderSurfacePane(pane) {
  const r = pane.result,
    el = $("plot-" + pane.id);
  if (!r || !el) return;
  const colors = themeColors(),
    g = r.grid,
    tr = r.trajectory;
  let traces,
    layout = {
      paper_bgcolor: colors.paper,
      plot_bgcolor: colors.paper,
      font: { size: 9, color: colors.muted },
      margin: { l: 45, r: 15, t: 8, b: 34 },
      showlegend: false,
      dragmode: "pan",
      xaxis: {
        type: "date",
        tickformat: "%H:%M",
        gridcolor: colors.line,
        showspikes: true,
        spikemode: "across",
        spikesnap: "cursor",
      },
      yaxis: {
        title: { text: "Price" },
        gridcolor: colors.line,
        showspikes: true,
        spikemode: "across",
        spikesnap: "cursor",
      },
      uirevision: JSON.stringify([r.asof, pane.view, r.parameters]),
    };
  if (pane.view === "3d") {
    traces = [
      {
        type: "surface",
        x: g.time.map((t) => (t - r.asof) / 60),
        y: g.price,
        z: g.z,
        colorscale: colorScale,
        showscale: false,
        opacity: 0.93,
      },
      {
        type: "scatter3d",
        mode: "lines",
        x: tr.time.map((t) => (t - r.asof) / 60),
        y: tr.price,
        z: tr.z,
        customdata: tr.time,
        line: { color: "#384f55", width: 4 },
        name: "Scenario",
      },
    ];
    layout.scene = {
      bgcolor: colors.paper,
      xaxis: { title: { text: "Minutes from launch" } },
      yaxis: { title: { text: "Price" } },
      zaxis: { title: { text: "Potential height" } },
      camera: { eye: { x: 1.5, y: 1.8, z: 1.1 } },
    };
    layout.margin = { l: 0, r: 0, t: 0, b: 0 };
  } else if (pane.view === "heatmap") {
    traces = [
      {
        type: "heatmap",
        x: toISO(g.time),
        y: g.price,
        z: g.z,
        colorscale: colorScale,
        showscale: false,
      },
      {
        type: "scatter",
        x: toISO(tr.time),
        y: tr.price,
        mode: "lines",
        line: { color: "#344d53", width: 2, dash: "dot" },
      },
    ];
    layout.shapes = [
      {
        type: "line",
        x0: new Date(r.asof * 1000).toISOString(),
        x1: new Date(r.asof * 1000).toISOString(),
        y0: 0,
        y1: 1,
        yref: "paper",
        line: { color: "#90aaa0", width: 1, dash: "dash" },
      },
    ];
  } else {
    traces = [
      {
        type: "scatter",
        x: toISO(tr.time),
        y: tr.price,
        mode: "lines",
        line: { color: "#356e74", width: 2, dash: "dash" },
      },
    ];
    for (const [key, label] of [
      ["up", "GS up"],
      ["down", "GS down"],
    ])
      traces.push({
        type: "scatter",
        x: toISO([r.asof, r.until]),
        y: [r.levels[key], r.levels[key]],
        mode: "lines",
        line: { color: "#b59c67", width: 1, dash: "dot" },
        name: label,
      });
  }
  if (pane.view !== "3d") {
    const x = traces[0].x.filter(
      (_, i, a) => i % Math.max(1, Math.ceil(a.length / 5)) === 0,
    );
    layout.xaxis.tickmode = "array";
    layout.xaxis.tickvals = x;
    layout.xaxis.ticktext = x.map((v) => time(Date.parse(v) / 1000));
  }
  await Plotly.react(el, traces, layout, {
    responsive: true,
    displayModeBar: false,
    scrollZoom: true,
  });
  installPaneCrosshair(pane, el);
  el.removeAllListeners("plotly_hover");
  el.on("plotly_hover", (e) => {
    const p = e.points[0];
    showAnalysisCoordinates(pane, p, el);
    S.crosshair = null;
    S.linkedTimes = [];
    const t =
      p.customdata ??
      (pane.view === "3d" ? r.asof + Number(p.x) * 60 : Date.parse(p.x) / 1000);
    if (Number.isFinite(t)) {
      S.analysisProbe = { time: t, price: Number(p.y), asof: r.asof };
      S.cursor = t <= r.asof ? indexFor(t) : null;
      paintSoon();
      linkCursor(t, pane.id);
    }
  });
  $("metrics-" + pane.id).innerHTML =
    `<span>Source candles <strong>${r.sources.length}</strong></span><span>End price <strong>${fmt(r.metrics["End price"])}</strong></span><button class="text-button" data-export-surface>Export scenario</button>`;
  $("metrics-" + pane.id).querySelector("[data-export-surface]").onclick = () =>
    download("lumenspace-surface-scenario.json", r);
}
function surfaceParameterDialog() {
  const fields = [
    ["push", "Push", 0, 3, 0.05],
    ["throw", "Throw", 0, 3, 0.05],
    ["coupling", "Coupling", 0, 3, 0.05],
    ["damping", "Damping", 0, 1.5, 0.01],
    ["dent_scale", "Dent multiplier", 0.05, 10, 0.05],
    ["depth", "Total depth (0 = original)", 0, 100, 0.1],
    ["sigma_x", "Time width", 0.1, 100, 0.1],
    ["sigma_y", "Price width", 0.1, 100, 0.1],
    ["tau", "Throw decay", 0.1, 100, 0.1],
    ["strength", "Candle strength", -10, 10, 0.1],
    ["background_k", "Background bowl", 0, 10, 0.01],
    ["ring_weight", "Older-candle weight", 0, 1, 0.05],
  ];
  const input = ([key, label, min, max, step]) =>
    `<label><span class="field-label">${label}</span><input id="surface-${key}" type="number" min="${min}" max="${max}" step="${step}" value="${S.surfaceParams[key]}"></label>`;
  const options = (key, labels) =>
    `<label><span class="field-label">${key}</span><select id="surface-${key}" class="box">${labels.map((v) => `<option ${S.surfaceParams[key] === v ? "selected" : ""}>${v}</option>`).join("")}</select></label>`;
  modal(
    "Surface physics & shape",
    `<p>These are the original engine parameters. Changing them does not train a model. Fit results are applied only when you choose to apply them.</p><div class="form-grid"><label><span class="field-label">Future horizon (minutes)</span><input id="surface-horizon" type="number" min="1" max="120" value="${S.surfaceHorizon}"></label>${fields.slice(0, 5).map(input).join("")}</div><details><summary>Surface shape and candle filters</summary><div class="form-grid">${fields.slice(5).map(input).join("")}${options("projection", ["reflect", "translate", "persist", "none", "scale", "scramble"])}${options("anchor", ["close", "high", "low", "body_mid", "upper_mid", "lower_mid"])}${options("kernel", ["gaussian", "causal"])}${options("direction", ["any", "bullish", "bearish"])}${["body", "upper", "lower"].flatMap((k) => ["min", "max"].map((bound) => `<label><span class="field-label">${k} ${bound} (%)</span><input type="number" id="rule-${k}_${bound}" value="${S.surfaceParams.rules[k + "_" + bound]}" min="0" max="100"></label>`)).join("")}<label><span class="field-label">Largest-range candles (0 = all)</span><input id="rule-top_n" type="number" min="0" max="512" value="${S.surfaceParams.rules.top_n}"></label><label><span class="field-label">Minimum range / prior scale</span><input id="rule-range_min" type="number" min="0" step=".1" value="${S.surfaceParams.rules.range_min}"></label></div></details><div class="form-grid"><label><span class="field-label">GoldenShadow quantum</span><input id="surface-quantum" type="number" min=".001" step=".01" value="${S.quantum}"></label><label><span class="field-label">Symbol tick size</span><input id="surface-mintick" type="number" min=".000001" step=".001" value="${S.mintick}"></label></div><div class="modal-actions"><button class="button primary" id="saveSurfaceParameters">Save parameters</button></div>`,
  );
  // Direction is a candle selection rule, not a dynamics field.
  $("surface-direction").value = S.surfaceParams.rules.direction;
  $("saveSurfaceParameters").onclick = () => {
    try {
      const newParams = { ...S.surfaceParams };
      for (const [key, , min, max] of fields) {
        const val = +$("surface-" + key).value;
        if (!Number.isFinite(val) || val < min || val > max)
          throw Error("Invalid " + key);
        newParams[key] = val;
      }
      for (const key of ["projection", "anchor", "kernel"])
        newParams[key] = $("surface-" + key).value;
      const rules = {
        ...S.surfaceParams.rules,
        direction: $("surface-direction").value,
      };
      for (const key of [
        "body_min",
        "body_max",
        "upper_min",
        "upper_max",
        "lower_min",
        "lower_max",
        "top_n",
        "range_min",
      ])
        rules[key] = +$("rule-" + key).value;
      for (const key of ["body", "upper", "lower"])
        if (rules[key + "_min"] > rules[key + "_max"])
          throw Error("Minimum exceeds maximum for " + key);
      newParams.rules = rules;
      const horizon = +$("surface-horizon").value;
      if (!Number.isInteger(horizon) || horizon < 1 || horizon > 120)
        throw Error("Horizon must be 1–120 whole minutes");
      const quantum = +$("surface-quantum").value,
        tick = +$("surface-mintick").value;
      if (!(quantum > 0 && tick > 0))
        throw Error("Quantum and tick size must be positive");
      if (quantum !== S.quantum || tick !== S.mintick) {
        S.surfaceModelId = null;
        S.useSurfaceML = false;
      }
      S.quantum = quantum;
      S.mintick = tick;
      S.surfaceHorizon = horizon;
      S.surfaceParams = newParams;
      S.surfaceResult = null;
      syncSurfaceControls();
      $("modal").close();
      refreshGoldenLevels();
      paint();
      toast("Parameters saved. Click Apply parameters & simulate.");
    } catch (e) {
      toast(e.message);
    }
  };
}
$("surfaceParameters").onclick = surfaceParameterDialog;
function fittingDialog() {
  modal(
    "Fit surface parameters",
    `<p>Fit the original physics against completed historical paths before the selected launch. This is separate from ML learning of the future surface.</p><div class="form-grid"><label><span class="field-label">Completed calibration windows</span><input id="fitWindowCount" type="number" min="1" max="8" value="3"></label><label><span class="field-label">Scenario horizon</span><input value="${S.surfaceHorizon} minutes" disabled></label></div><div class="check-list">${["push", "throw", "coupling", "damping", "dent_scale"].map((k) => `<label><input type="checkbox" name="fitParameter" value="${k}" ${["push", "throw"].includes(k) ? "checked" : ""}> ${k}</label>`).join("")}</div><p class="micro">Calibration source windows use the same surface lookback length. Their outcomes must end at or before the selected launch. With two or more windows, the newest calibration path is tested using parameters fitted on older paths only.</p><div class="modal-actions"><button id="startSurfaceFit" class="button primary">Start parameter fit</button></div>`,
  );
  $("startSurfaceFit").onclick = async () => {
    const request = {
      ...surfaceRequest(),
      model_id: null,
      fit_windows: +$("fitWindowCount").value,
      free: [...document.querySelectorAll("[name=fitParameter]:checked")].map(
        (b) => b.value,
      ),
    };
    await startSurfaceJob("fit", request);
  };
}
$("fitSurface").onclick = fittingDialog;
$("learnSurface").onclick = async () => {
  if (!S.selection) {
    toast("Choose and mark one complete 14m or 42m NY window first.");
    return;
  }
  await startSurfaceJob("learn", { ...surfaceRequest(), model_id: null });
};
async function startSurfaceJob(kind, request) {
  try {
    const output = await post("/api/surface-jobs/" + kind, request);
    const key = selectionKey();
    $("modal").close();
    for (const id of [
      "fitSurface",
      "applySurface",
      "learnSurface",
      "resetSurface",
    ])
      $(id).disabled = true;
    $("surfaceJob").classList.remove("hidden");
    $("surfaceProgressBar").style.width = "0%";
    const poll = async () => {
      try {
        const job = await api("/api/jobs/" + output.job_id);
        $("surfaceProgressBar").style.width = job.progress + "%";
        $("surfaceProgressPercent").textContent = job.progress + "%";
        $("surfaceProgressMessage").textContent = job.message;
        if (job.status === "running") {
          setTimeout(poll, 650);
          return;
        }
        for (const id of [
          "fitSurface",
          "applySurface",
          "learnSurface",
          "resetSurface",
        ])
          $(id).disabled = false;
        if (job.status === "failed") {
          toast(job.message);
          return;
        }
        $("surfaceJob").classList.add("hidden");
        if (key !== selectionKey()) {
          toast(
            "Job finished for the earlier window. Run it again for the current marked window.",
          );
          return;
        }
        if (kind === "fit") {
          S.surfaceFit = job.result;
          $("viewSurfaceFit").classList.remove("hidden");
          fitReportDialog();
        } else {
          S.surfaceModelId = job.result.model_id;
          S.useSurfaceML = false;
          syncSurfaceControls();
          $("surfaceMessage").textContent =
            `Future surface learned from ${job.result.report.training_candles} selected candles only. Enable ML future surface, then Apply.`;
          toast("Future surface ready. Physics parameters were not changed.");
        }
      } catch (e) {
        $("surfaceProgressMessage").textContent =
          "Connection interrupted; retrying…";
        setTimeout(poll, 2000);
      }
    };
    poll();
  } catch (e) {
    toast(e.message);
  }
}
function fitReportDialog() {
  const r = S.surfaceFit;
  if (!r) return;
  modal(
    "Surface fit report",
    `<div class="report-grid"><div>Before (normalized RMSE)<strong>${fmt(r.before_rmse, 3)}</strong></div><div>After (normalized RMSE)<strong>${fmt(r.after_rmse, 3)}</strong></div></div><p>Flat-price comparator RMSE: ${fmt(r.flat_rmse, 3)} · price-unit RMSE after fit: ${fmt(r.price_after_rmse, 3)}</p><table><tr><th>Parameter</th><th>Fitted value</th></tr>${Object.entries(
      r.parameters,
    )
      .map(([k, v]) => `<tr><td>${esc(k)}</td><td>${fmt(v, 4)}</td></tr>`)
      .join(
        "",
      )}</table><h3>Newest calibration holdout</h3><p>${r.holdout ? `Before ${fmt(r.holdout.before, 3)} · older-window fit ${fmt(r.holdout.after, 3)} · flat ${fmt(r.holdout.flat, 3)}` : "Need at least two calibration windows for a holdout."}</p><p class="micro">${esc(r.note)}</p><div class="modal-actions"><button class="button" id="exportSurfaceFit">Export fit</button><button class="button primary" id="applyFittedParameters">Use fitted parameters & simulate</button></div>`,
  );
  $("exportSurfaceFit").onclick = () =>
    download("lumenspace-surface-fit.json", r);
  $("applyFittedParameters").onclick = () => {
    Object.assign(S.surfaceParams, r.parameters);
    $("modal").close();
    $("applySurface").click();
  };
}
$("viewSurfaceFit").onclick = fitReportDialog;
$("viewGolden").onclick = () => {
  const r = S.goldenResult?.selected;
  if (!r) {
    toast("No GoldenShadow result for the selected window yet.");
    return;
  }
  modal(
    "GoldenShadow · 85-rung ladder",
    `<p>Source window closes at ${time(r.start, true)}. ATR ${fmt(r.atr, 4)} · weekday fraction ${fmt(r.weekday_fraction, 3)} · selected rung ${r.rung} · multiplier ${fmt(r.mu)}.</p><p class="micro">Exact original shadow/ATR + Zeller formula, tick-rounded. Target levels are reference levels, not probabilities.</p><table><thead><tr><th>Rung</th><th>Multiplier</th><th>Up</th><th>Down</th><th>Roots ↑ / ↓</th></tr></thead><tbody>${r.ladder.map((v) => `<tr ${v.rung === r.rung ? 'class="selected-rung"' : ""}><td>${v.rung}${v.rung === r.rung ? " ✓" : ""}</td><td>${fmt(v.multiplier)}</td><td>${fmt(v.up)}</td><td>${fmt(v.down)}</td><td>${v.up_root} / ${v.down_root}</td></tr>`).join("")}</tbody></table><div class="modal-actions"><button class="button" id="exportGolden">Export ladder</button></div>`,
  );
  $("exportGolden").onclick = () =>
    download("lumenspace-golden-shadow.json", r);
};

async function validateDraggedWindow() {
  const range = S.selection;
  try {
    const a = S.bars[indexFor(range[0])],
      b = S.bars[indexFor(range[1])];
    const result = await post("/api/select-window", {
      kind: "custom",
      start: new Date(a.time * 1000).toISOString(),
      end: new Date((b.time + S.tf * 60) * 1000).toISOString(),
      timezone: "America/New_York",
    });
    await applyMarkedWindow(result);
  } catch (e) {
    S.selection = null;
    updateSelection();
    await refreshPanes();
    toast(e.message);
    paint();
  }
}
syncWindowWorkflow();

const chartContext = document.createElement("div");
chartContext.id = "chartContext";
chartContext.className = "chart-context hidden";
chartContext.setAttribute("role", "menu");
document.body.append(chartContext);
let contextEpoch = 0;
function closeChartContext() {
  contextEpoch++;
  chartContext.classList.add("hidden");
}
document.addEventListener("pointerdown", (e) => {
  if (!chartContext.contains(e.target)) closeChartContext();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeChartContext();
});
window.addEventListener("scroll", closeChartContext, true);
canvas.addEventListener("contextmenu", async (e) => {
  e.preventDefault();
  if (!S.bars.length || !S.range) return;
  drag = null;
  S.pickWindow = false;
  const p = position(e);
  if (p.rawIndex < 0 || p.rawIndex >= S.bars.length) {
    closeChartContext();
    toast("Right-click a loaded candle to find its window.");
    return;
  }
  const bar = S.bars[p.i],
    epoch = ++contextEpoch;
  chartContext.innerHTML = `<div class="context-heading">Candle · ${nyTime(bar.time)} NY</div><p>Choose a time window for this candle.</p><button id="findCandleWindow" role="menuitem">Find the time window of this candle</button><p class="context-note">${S.window}m · New York clock</p>`;
  chartContext.classList.remove("hidden");
  chartContext.style.left =
    Math.max(12, Math.min(e.clientX, innerWidth - 302)) + "px";
  chartContext.style.top =
    Math.max(12, Math.min(e.clientY, innerHeight - 230)) + "px";
  $("findCandleWindow").onclick = async () => {
    $("findCandleWindow").disabled = true;
    try {
      const info = await post("/api/candle-window", {
        timestamp: bar.time,
        display_timeframe: S.tf,
        source_version: S.version,
        minutes: S.window,
        kind: "aligned",
      });
      if (epoch !== contextEpoch) return;
      chartContext.innerHTML = `<div class="context-heading">Detected ${info.minutes}m NY window</div><p><strong>${nyTime(info.start)} → ${nyTime(info.end)} NY</strong></p><p>${info.bars}/${info.expected} closed M1 candles · ${info.complete ? "Ready for analysis" : esc(info.reason)}</p><button id="selectCandleWindow" role="menuitem" ${info.complete ? "" : "disabled"}>Select & highlight this window</button>`;
      if (info.complete)
        $("selectCandleWindow").onclick = async () => {
          const result = {
            start: info.start,
            last: info.last,
            end: info.end,
            bars: info.bars,
            kind: "aligned",
          };
          closeChartContext();
          await applyMarkedWindow(result);
          toast("Window highlighted. All four research charts are ready.");
        };
    } catch (error) {
      if (epoch === contextEpoch)
        chartContext.innerHTML = `<div class="context-heading">Window unavailable</div><p>${esc(error.message)}</p>`;
    }
  };
});

$("resetSurface").onclick = () => {
  surfaceRevision++;
  S.surfaceParams = structuredClone(DEFAULT_SURFACE_PARAMETERS);
  S.surfaceHorizon = 42;
  S.surfaceFit = null;
  S.surfaceResult = null;
  S.analysisProbe = null;
  S.surfaceModelId = null;
  S.useSurfaceML = false;
  $("viewSurfaceFit").classList.add("hidden");
  syncSurfaceControls();
  for (const pane of S.panes.filter((p) => p.module === "surface")) {
    pane.result = null;
    const el = $("plot-" + pane.id);
    if (el?.data) Plotly.purge(el);
    if (el)
      el.innerHTML =
        '<div class="pane-error">Defaults restored. Apply parameters to generate a new surface.</div>';
    $("metrics-" + pane.id).textContent = "Previous fit and surface cleared";
    $("readout-" + pane.id).textContent = "Crosshair · X — · Y —";
  }
  $("surfaceMessage").textContent =
    "Default physics restored. Fitted parameters and the previous surface were removed.";
  paint();
  toast("Surface defaults restored.");
};
