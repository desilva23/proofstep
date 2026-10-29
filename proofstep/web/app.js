// proofstep viewer: one saved report at a time, read from the local server.

const LABEL = { verified: "Verified", missing: "Missing", cant_verify: "Can't verify" };

const $ = (id) => document.getElementById(id);
const video = $("video");
const canvas = $("overlay");
const ctx = canvas.getContext("2d");

const state = { detail: null, selected: null, duration: 0 };

function clock(t) {
  const s = Math.max(0, Math.floor(t));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const child of children.flat()) {
    if (child != null) node.append(child instanceof Node ? child : document.createTextNode(child));
  }
  return node;
}

function verdict(step, truth) {
  const label = truth && truth[step.id];
  if (!label) return null;
  if (step.status === "cant_verify") return { cls: "abstained", text: `Label: ${label.happened ? "done" : "skipped"}` };
  const right = (step.status === "verified") === label.happened;
  if (right) return { cls: "right", text: `Label: ${label.happened ? "done" : "skipped"} ✓` };
  return { cls: "wrong", text: `Label: ${label.happened ? "done" : "skipped"}, ${step.status === "verified" ? "false pass" : "false alarm"}` };
}

function seek(t, play = true) {
  video.currentTime = Math.max(0, t - 1);
  if (play) video.play().catch(() => {});
}

function select(id, { jump = false } = {}) {
  state.selected = id;
  document.querySelectorAll(".step, .row").forEach((n) => n.classList.toggle("active", n.dataset.id === id));
  revealCard(id);
  const step = state.detail.report.steps.find((s) => s.id === id);
  if (jump && step) {
    const t = step.look_at ?? step.spark.start;
    if (t != null) seek(t);
  }
  setHash();
  draw();
}

function revealCard(id) {
  // Scroll only the step list (it has its own scroll area on wide screens), never the page.
  const panel = document.querySelector(".steps");
  const card = document.querySelector(`.step[data-id="${id}"]`);
  if (!card || panel.scrollHeight <= panel.clientHeight) return;
  const top = card.offsetTop, bottom = top + card.offsetHeight;
  if (top < panel.scrollTop || bottom > panel.scrollTop + panel.clientHeight) {
    panel.scrollTop = Math.max(0, top - 8);
  }
}

function setHash() {
  const parts = [`run=${state.detail.name}`];
  if (state.selected) parts.push(`step=${state.selected}`);
  history.replaceState(null, "", `#${parts.join("&")}`);
}

function readHash() {
  return Object.fromEntries(location.hash.slice(1).split("&").filter(Boolean).map((p) => p.split("=")));
}

function renderSummary(report, truth) {
  const c = report.counts;
  const pills = [
    el("span", { class: "pill verified" }, `${c.verified} verified`),
    el("span", { class: "pill missing" }, `${c.missing} missing`),
    el("span", { class: "pill cant_verify" }, `${c.cant_verify} can't verify`),
  ];
  if (report.order_problems.length) pills.push(el("span", { class: "pill missing" }, `${report.order_problems.length} out of order`));
  if (truth) {
    let wrong = 0;
    for (const s of report.steps) {
      const v = verdict(s, truth);
      if (v && v.cls === "wrong") wrong += 1;
    }
    pills.push(el("span", { class: "pill plain truth-only" }, `${wrong} wrong vs human labels`));
  }
  pills.push(el("span", { class: "pill plain" }, report.procedure));
  $("summary").replaceChildren(...pills);
}

function renderTimeline(report, truth, boxes) {
  const d = state.duration || report.duration;
  const pct = (t) => `${(100 * Math.min(Math.max(t, 0), d)) / d}%`;
  const span = (a, b) => ({ left: pct(a), width: `${Math.max((100 * (Math.min(b, d) - Math.max(a, 0))) / d, 0.4)}%` });

  const rows = report.steps.map((s) => {
    const track = el("div", { class: "track" });
    const add = (cls, a, b, title) => {
      const bar = el("div", { class: `bar ${cls}`, title });
      Object.assign(bar.style, span(a, b));
      track.append(bar);
    };
    if (s.spark.start != null && s.spark.end != null) add(s.status, s.spark.start, s.spark.end, `${LABEL[s.status]}: Spark places it at ${clock(s.spark.start)}-${clock(s.spark.end)}`);
    else if (s.status === "verified" && s.at != null) add("verified", s.at - 2, s.at + 2, `Verified on a closer look at ${clock(s.at)}`);
    if (s.evidence) add("evidence", s.evidence.from, s.evidence.to, `SAM: ${s.evidence.found_as} in hand ${clock(s.evidence.from)}-${clock(s.evidence.to)}`);
    const label = truth && truth[s.id];
    if (label && label.happened) add("truth truth-only", label.start, label.end, `Human label: ${clock(label.start)}-${clock(label.end)}`);
    if (s.status === "missing") track.append(el("span", { class: "missing-note" }, "missing"));
    if (s.status === "cant_verify" && s.look_at != null) {
      const flag = el("div", { class: "flag", title: `Look at ${clock(s.look_at)}` });
      flag.style.left = pct(s.look_at);
      track.append(flag);
    }
    return el("div", { class: "row", "data-id": s.id }, el("span", { class: "sid" }, s.id), track);
  });

  const ticks = el("div", { class: "scale" });
  const step = d > 600 ? 120 : d > 240 ? 60 : 30;
  for (let t = 0; t <= d; t += step) {
    const tick = el("span", {}, clock(t));
    tick.style.left = pct(t);
    ticks.append(tick);
  }
  const playhead = el("div", { class: "playhead", id: "playhead" });
  $("timeline").replaceChildren(...rows, el("div", { class: "ticks" }, el("div"), ticks), playhead);
  placePlayhead();
}

function placePlayhead() {
  const head = $("playhead");
  const track = document.querySelector("#timeline .track");
  if (!head || !track || !state.duration) return;
  const box = $("timeline").getBoundingClientRect();
  const t = track.getBoundingClientRect();
  head.style.left = `${t.left - box.left + (t.width * video.currentTime) / state.duration}px`;
}

function renderSteps(report, truth) {
  const items = report.steps.map((s) => {
    const v = verdict(s, truth);
    const lookAt = s.look_at ?? (s.status !== "missing" ? s.spark.start : null);
    const foot = el("div", { class: "step-foot" },
      lookAt != null ? el("button", { class: "look", type: "button", onclick: (e) => { e.stopPropagation(); select(s.id); seek(lookAt); } },
        s.status === "cant_verify" ? `Look at ${clock(lookAt)}` : `Watch ${clock(lookAt)}`) : null,
      s.substitution ? el("span", { class: "sub" }, `Done with a substitution: ${s.substitution}`) : null,
      v ? el("span", { class: `verdict ${v.cls}` }, v.text) : null,
    );
    return el("li", { class: `step ${s.status}`, "data-id": s.id, tabindex: "0",
      onclick: () => select(s.id, { jump: true }),
      onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(s.id, { jump: true }); } } },
      el("div", { class: "step-head" },
        el("div", { class: "step-title" }, el("span", { class: "sid" }, s.id), s.text),
        el("span", { class: `pill ${s.status}` }, LABEL[s.status])),
      el("p", { class: "reason" }, s.reason),
      foot);
  });
  $("steps").replaceChildren(...items);

  const extras = [];
  if (report.order_problems.length) {
    extras.push(el("h2", {}, "Out of order"),
      el("ul", {}, report.order_problems.map((o) => el("li", { class: "order" }, o.reason))));
  }
  if (report.other_mistakes.length) {
    extras.push(el("h2", {}, "Also noticed by Spark (not checked)"),
      el("ul", {}, report.other_mistakes.map((m) => el("li", {}, `${m.time_sec != null ? clock(m.time_sec) + " · " : ""}${m.description}`))));
  }
  $("extras").className = "extras";
  $("extras").replaceChildren(...extras);
}

function sizeCanvas() {
  const r = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(r.width * dpr);
  canvas.height = Math.round(r.height * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function draw() {
  const r = canvas.getBoundingClientRect();
  ctx.clearRect(0, 0, r.width, r.height);
  if (!state.detail || !video.videoWidth) return;

  // The video is letterboxed inside the stage; boxes are in video coordinates.
  const scale = Math.min(r.width / video.videoWidth, r.height / video.videoHeight);
  const w = video.videoWidth * scale, h = video.videoHeight * scale;
  const ox = (r.width - w) / 2, oy = (r.height - h) / 2;
  const t = video.currentTime;
  const half = state.detail.box_interval / 2 + 0.05;

  const ids = state.selected ? [state.selected] : Object.keys(state.detail.boxes);
  for (const id of ids) {
    const entry = state.detail.boxes[id];
    if (!entry) continue;
    const near = entry.boxes.filter(([bt]) => Math.abs(bt - t) <= half).sort((p, q) => q[5] - p[5]);
    near.forEach(([, x1, y1, x2, y2, c], i) => {
      const x = ox + x1 * w, y = oy + y1 * h, bw = (x2 - x1) * w, bh = (y2 - y1) * h;
      ctx.lineWidth = 3;
      ctx.strokeStyle = "#2a6fdb";
      ctx.strokeRect(x, y, bw, bh);
      if (i > 0) return; // one label per step: on its most confident box
      const label = `${id} · ${entry.object} ${Math.round(c * 100)}%`;
      ctx.font = "600 12px ui-sans-serif, -apple-system, sans-serif";
      const tw = ctx.measureText(label).width + 10;
      ctx.fillStyle = "#2a6fdb";
      ctx.fillRect(x, Math.max(0, y - 18), tw, 18);
      ctx.fillStyle = "#fff";
      ctx.fillText(label, x + 5, Math.max(0, y - 18) + 13);
    });
  }
}

function frame() {
  placePlayhead();
  draw();
  if (!video.paused) requestAnimationFrame(frame);
}

async function load(name, stepId) {
  const res = await fetch(`/api/run/${encodeURIComponent(name)}`);
  if (!res.ok) {
    $("steps").replaceChildren(el("li", { class: "empty" }, "Couldn't load this report."));
    return;
  }
  const detail = await res.json();
  state.detail = detail;
  state.selected = null;
  state.duration = detail.report.duration;
  $("run").value = name;
  $("labels").disabled = !detail.truth;
  document.body.classList.toggle("show-truth", $("labels").checked && !!detail.truth);
  video.src = `/video/${encodeURIComponent(name)}`;
  renderSummary(detail.report, detail.truth);
  renderTimeline(detail.report, detail.truth, detail.boxes);
  renderSteps(detail.report, detail.truth);
  if (stepId) select(stepId, { jump: true });
  else setHash();
}

async function fillRuns() {
  const runs = await (await fetch("/api/runs")).json();
  const groups = {};
  for (const r of runs) (groups[r.procedure] ||= []).push(r);
  $("run").replaceChildren(...Object.entries(groups).map(([proc, list]) =>
    el("optgroup", { label: proc }, list.map((r) => el("option", { value: r.name },
      `${r.recording || r.name} · ${r.counts.verified}✓ ${r.counts.missing}✗ ${r.counts.cant_verify}?`)))));
  return runs;
}

async function init() {
  const runs = await fillRuns();
  if (!runs.length) {
    $("steps").replaceChildren(el("li", { class: "empty" }, "No reports yet. Use New check, or run python -m proofstep check."));
    return;
  }
  const hash = readHash();
  const first = runs.find((r) => r.name === hash.run) || runs.find((r) => r.name === "8_3_360p") || runs[0];
  await load(first.name, hash.step);
}

$("run").addEventListener("change", (e) => load(e.target.value));
$("labels").addEventListener("change", (e) => document.body.classList.toggle("show-truth", e.target.checked && !!state.detail?.truth));
$("timeline").addEventListener("click", (e) => {
  const track = document.querySelector("#timeline .track");
  if (!track || !state.duration) return;
  const t = track.getBoundingClientRect();
  const x = Math.min(Math.max(e.clientX - t.left, 0), t.width);
  video.currentTime = (x / t.width) * state.duration;
  const row = e.target.closest(".row");
  if (row) select(row.dataset.id);
});
video.addEventListener("loadedmetadata", () => {
  state.duration = video.duration || state.duration;
  if (video.currentTime === 0) video.currentTime = 0.01; // show the first frame instead of black
  sizeCanvas();
  renderTimeline(state.detail.report, state.detail.truth, state.detail.boxes);
  if (state.selected) select(state.selected);
});
video.addEventListener("play", () => requestAnimationFrame(frame));
video.addEventListener("seeked", () => { placePlayhead(); draw(); });
video.addEventListener("timeupdate", placePlayhead);
window.addEventListener("resize", () => { sizeCanvas(); placePlayhead(); draw(); });
new ResizeObserver(() => { sizeCanvas(); draw(); }).observe($("stage"));

init();

// New check: procedure, then video, then cost and consent, then a background job.

const wiz = { procedure: null, video: null, seconds: 0, job: null };

function wizStatus(id, text, error = false) {
  $(id).textContent = text;
  $(id).classList.toggle("error", error);
}

async function post(url, body) {
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function showProcedure(proc) {
  $("proc-view").replaceChildren(
    el("ol", {}, proc.steps.map((s) => el("li", {}, s.text))),
    proc.rules.length ? el("p", { class: "rules" }, `Must happen in order: ${proc.rules.map(([a, b]) => `${a} before ${b}`).join(", ")}`) : null);
}

async function fillProcedures(selected) {
  const list = await (await fetch("/api/procedures")).json();
  $("proc-pick").replaceChildren(el("option", { value: "" }, "Choose…"),
    ...list.map((p) => el("option", { value: p.file }, `${p.name} (${p.steps} steps)`)));
  if (selected) $("proc-pick").value = selected;
}

async function pickProcedure(file) {
  wiz.procedure = file || null;
  if (file) showProcedure(await (await fetch(`/api/procedure/${encodeURIComponent(file)}`)).json());
  else $("proc-view").replaceChildren();
  updateCost();
}

async function updateCost() {
  $("run-check").disabled = true;
  if (!wiz.procedure || !wiz.video) {
    $("cost").textContent = "Pick a procedure and a video to see the cost.";
    return;
  }
  try {
    const est = await post("/api/estimate", { procedure: wiz.procedure, video: wiz.video });
    $("cost").textContent = `About $${est.likely_usd.toFixed(2)} for a ${clock(wiz.seconds)} video, almost all of it SAM. A safety cap stops SAM's search if it would cost more than $${est.cap_usd.toFixed(2)}.`;
    $("run-check").disabled = !$("consent").checked;
  } catch (e) {
    $("cost").textContent = e.message;
  }
}

function upload(file) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/upload?name=${encodeURIComponent(file.name)}`);
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) $("upload-bar").style.width = `${(100 * e.loaded) / e.total}%`; };
    xhr.upload.onload = () => wizStatus("video-status", "Uploaded. Shrinking it to 360p…");
    xhr.onload = () => {
      const data = JSON.parse(xhr.responseText || "{}");
      xhr.status === 200 ? resolve(data) : reject(new Error(data.error || `HTTP ${xhr.status}`));
    };
    xhr.onerror = () => reject(new Error("upload failed"));
    xhr.send(file);
  });
}

async function pollJob() {
  if (!wiz.job) return;
  const info = await (await fetch(`/api/job/${wiz.job}`)).json();
  if (info.status === "running") {
    wizStatus("job-status", `${info.progress} (${clock(info.elapsed)})`);
    setTimeout(pollJob, 2000);
    return;
  }
  wiz.job = null;
  if (info.status === "failed") {
    wizStatus("job-status", `Failed: ${info.error || "see the log in runs/logs"}`, true);
    $("run-check").disabled = false;
    return;
  }
  wizStatus("job-status", "Done.");
  await fillRuns();
  $("wizard").close();
  await load(info.run);
}

$("new-check").addEventListener("click", async () => {
  await fillProcedures(wiz.procedure);
  $("wizard").showModal();
});
$("proc-pick").addEventListener("change", (e) => pickProcedure(e.target.value));
$("proc-make").addEventListener("click", async () => {
  const text = $("proc-text").value.trim();
  if (!text) return wizStatus("proc-status", "Type the instructions first.", true);
  $("proc-make").disabled = true;
  wizStatus("proc-status", "Spark is reading the instructions…");
  try {
    const out = await post("/api/procedure", { text });
    await fillProcedures(out.file);
    await pickProcedure(out.file);
    wizStatus("proc-status", `Saved as "${out.procedure.name}". Check the steps below.`);
  } catch (e) {
    wizStatus("proc-status", e.message, true);
  } finally {
    $("proc-make").disabled = false;
  }
});
$("video-file").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  wiz.video = null;
  document.querySelector(".progress").hidden = false;
  $("upload-bar").style.width = "0";
  wizStatus("video-status", `Uploading ${file.name}…`);
  try {
    const out = await upload(file);
    wiz.video = out.video;
    wiz.seconds = out.seconds;
    wizStatus("video-status", `Ready: ${clock(out.seconds)} long.`);
  } catch (err) {
    wizStatus("video-status", err.message, true);
  }
  updateCost();
});
$("consent").addEventListener("change", updateCost);
$("run-check").addEventListener("click", async () => {
  $("run-check").disabled = true;
  try {
    const out = await post("/api/check", { procedure: wiz.procedure, video: wiz.video });
    wiz.job = out.job;
    wizStatus("job-status", "Started. Spark watches first, then SAM; this takes a few minutes.");
    setTimeout(pollJob, 1500);
  } catch (e) {
    wizStatus("job-status", e.message, true);
    $("run-check").disabled = false;
  }
});

