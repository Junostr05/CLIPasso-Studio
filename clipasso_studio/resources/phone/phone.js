// CLIPasso Studio – the phone page: the studio from the phone (gui/phone_api.py answers every request).
"use strict";

const CFG = JSON.parse(document.getElementById("cfg").textContent);
const T = CFG.texts || {};
const TOKEN = CFG.token;
const $ = (id) => document.getElementById(id);
const t = (key, fmt) => {
  let s = T[key] !== undefined ? String(T[key]) : key;
  for (const [k, v] of Object.entries(fmt || {})) s = s.split("{" + k + "}").join(String(v));
  return s;
};

function el(tag, attrs, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children) if (c !== null && c !== undefined) e.append(c);
  return e;
}

// ------------------------------------------------------------------ talking to the app
async function getJSON(path) {
  const r = await fetch(path, {cache: "no-store"});
  const data = await r.json().catch(() => ({ok: false, error: T.failed}));
  if (r.status === 503) throw new Error(T.busy);
  return data;
}

async function act(action, data) {
  const r = await fetch("/api/do", {method: "POST", headers: {"X-Access": TOKEN, "Content-Type": "application/json"},
                                    body: JSON.stringify(Object.assign({action}, data || {}))});
  const answer = await r.json().catch(() => ({ok: false, error: T.failed}));
  if (r.status === 503) answer.error = T.busy;
  if (answer.ok === false && answer.error && !answer.ask) toast(answer.error);
  schedule(150);
  return answer;
}

let toastTimer = 0;
function toast(text) {
  const box = $("toast");
  box.textContent = text;
  box.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { box.hidden = true; }, 3500);
}

// ------------------------------------------------------------------ texts and tabs
for (const node of document.querySelectorAll("[data-t]")) node.textContent = t(node.dataset.t);

let tab = "studio";
function showTab(name) {
  tab = name;
  for (const b of document.querySelectorAll("#tabs button")) b.classList.toggle("on", b.dataset.tab === name);
  for (const s of document.querySelectorAll("section.tab")) s.hidden = s.id !== "tab-" + name;
  if (name === "gallery") loadResults();
  if (name === "queue") loadQueue();
  window.scrollTo(0, 0);
}
for (const b of document.querySelectorAll("#tabs button")) b.onclick = () => showTab(b.dataset.tab);

// ------------------------------------------------------------------ state from the studio
let S = null;           // the latest studio state
let schemaOf = {};      // method -> its parameters
let builtFor = "";      // the method the parameter fields are built for
let lastSeen = {input: "", sketch: "", seeds: "", note: 0, details: -1};

let timer = 0;
function schedule(ms) {
  clearTimeout(timer);
  timer = setTimeout(refresh, ms);
}

async function refresh() {
  try {
    const s = await getJSON("/api/get/studio");
    if (s.ok === false) throw new Error(s.error || T.offline);
    S = s;
    await render();
    schedule(document.hidden ? 8000 : (s.busy ? 1500 : 3000));
  } catch (e) {
    $("status").textContent = e.message && e.message !== "Failed to fetch" ? e.message : T.offline;
    schedule(4000);
  }
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) schedule(50); });

async function render() {
  renderTop();
  renderPicture();
  renderMethods();
  await renderParams();
  renderDetails();
  renderSketch();
  if (S.note && S.note.id !== lastSeen.note) {
    lastSeen.note = S.note.id;
    toast(S.note.text);
  }
  if (tab === "queue") loadQueue();
}

function renderTop() {
  $("status").textContent = S.status || (S.busy ? T.running : T.idle);
  $("progress").style.width = Math.round(100 * (S.progress || 0)) + "%";
  $("pause").textContent = S.paused ? T.resume : T.pause;
  $("pause").disabled = $("cancel").disabled = !S.busy;
  $("cancel").textContent = T.cancel;
  $("estimate").textContent = S.estimate || "";
}

$("pause").onclick = () => fetch(S && S.paused ? "/api/resume" : "/api/pause",
                                 {method: "POST", headers: {"X-Access": TOKEN}}).then(() => schedule(100));
$("cancel").onclick = () => {
  if (confirm(T.cancel_ask)) fetch("/api/cancel", {method: "POST", headers: {"X-Access": TOKEN}}).then(() => schedule(100));
};

// ------------------------------------------------------------------ picture
function renderPicture() {
  const img = S.image;
  $("no-input").hidden = !!img;
  $("input-name").textContent = img ? img.name + " · " + img.size : "";
  if (img && img.rev !== lastSeen.input) {
    lastSeen.input = img.rev;
    $("input").src = "/api/file/input?v=" + encodeURIComponent(img.rev);
  } else if (!img) {
    $("input").removeAttribute("src");
    lastSeen.input = "";
  }
}

async function upload(file) {
  if (!file) return;
  $("upload-msg").textContent = T.uploading;
  try {
    const r = await fetch("/api/upload", {method: "POST", body: file, headers: {
      "X-Access": TOKEN, "X-Target": "studio", "X-Filename": encodeURIComponent(file.name || "photo.jpg")}});
    const a = await r.json();
    $("upload-msg").textContent = a.ok ? T.uploaded : (a.error || T.failed);
  } catch (e) {
    $("upload-msg").textContent = T.failed;
  }
  schedule(100);
}
$("camera").onchange = (e) => { upload(e.target.files[0]); e.target.value = ""; };
$("choose").onchange = (e) => { upload(e.target.files[0]); e.target.value = ""; };

$("from-pc").onclick = async () => {
  const box = $("pc-images");
  box.hidden = !box.hidden;
  if (box.hidden) return;
  const list = await getJSON("/api/get/images");
  for (const [src, key] of [["recent", "recent"], ["sample", "samples"]]) {
    const grid = $(key);
    grid.replaceChildren();
    for (const item of list[key] || []) {
      grid.append(el("button", {title: item.name, onclick: async () => {
        box.hidden = true;
        await act("image", {src, i: item.i});
      }}, el("img", {src: `/api/file/image?src=${src}&i=${item.i}`, alt: item.name, loading: "lazy"})));
    }
    if (!grid.children.length) grid.append(el("div", {class: "muted", text: T.empty}));
  }
};

// ------------------------------------------------------------------ method, presets, budget
function renderMethods() {
  const box = $("methods");
  if (box.dataset.sig !== JSON.stringify(S.methods) + S.method) {
    box.dataset.sig = JSON.stringify(S.methods) + S.method;
    box.replaceChildren();
    for (const m of S.methods) {
      box.append(el("button", {class: m.key === S.method ? "on" : "", onclick: () => act("method", {method: m.key})},
                    el("span", {text: m.name}), m.missing ? el("small", {text: T.missing_badge}) : null));
    }
  }
  $("missing").hidden = !S.missing.length;
  if (S.missing.length) $("missing").textContent = t("models_missing", {size: S.missing_mb});
}

$("budget").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-min]");
  if (b) act("budget", {minutes: Number(b.dataset.min)}).then((a) => { if (a.ok) toast(a.estimate); });
});
$("budget-go").onclick = () => {
  const n = Number($("budget-min").value);
  if (n > 0) act("budget", {minutes: n}).then((a) => { if (a.ok) toast(a.estimate); });
};

// ------------------------------------------------------------------ parameters
let showAdvanced = false;
$("advanced").onchange = (e) => { showAdvanced = e.target.checked; builtFor = ""; renderParams(); };
$("reset").onclick = () => { if (confirm(T.reset_ask)) act("reset"); };

async function renderParams() {
  if (!S) return;
  const key = S.method + "|" + showAdvanced;
  if (!schemaOf[S.method]) schemaOf[S.method] = await getJSON("/api/get/schema?method=" + S.method);
  const sc = schemaOf[S.method];
  if (builtFor !== key) {
    builtFor = key;
    buildParams(sc);
    const seg = $("presets");
    seg.replaceChildren();
    for (const p of sc.presets) seg.append(el("button", {"data-preset": p.key, text: p.label,
                                                         onclick: () => act("preset", {preset: p.key})}));
  }
  for (const b of $("presets").children) b.classList.toggle("on", b.dataset.preset === S.preset);
  syncParams();
}

const openGroups = new Set(["basics", "image"]);

function buildParams(sc) {
  const box = $("params");
  box.replaceChildren();
  for (const g of sc.groups) {
    const shown = g.params.filter((p) => showAdvanced || !p.advanced);
    if (!shown.length) continue;
    const det = el("details", {class: "group", open: openGroups.has(g.key)}, el("summary", {text: g.label}));
    det.addEventListener("toggle", () => { if (det.open) openGroups.add(g.key); else openGroups.delete(g.key); });
    for (const p of shown) det.append(buildField(p));
    box.append(det);
  }
}

function send(key, value) { act("set", {key, value}); }

function buildField(p) {
  const id = "p-" + p.key;
  const help = el("div", {class: "help", text: p.help, hidden: true});
  const head = el("div", {class: "head"}, el("label", {for: id, text: p.label}),
                  p.help ? el("button", {class: "help-btn", text: "?", onclick: () => { help.hidden = !help.hidden; }}) : null);
  const field = el("div", {class: "field", "data-key": p.key, "data-kind": p.kind}, head, help);
  let ctl;
  if (p.kind === "bool") {
    ctl = el("input", {id, type: "checkbox", onchange: (e) => send(p.key, e.target.checked)});
    head.append(ctl);
  } else if (p.kind === "int" || p.kind === "float") {
    const step = p.step || (p.kind === "int" ? 1 : Math.pow(10, -(p.decimals || 2)));
    const num = el("input", {id, type: "number", class: "num", step, min: p.min, max: p.max,
                             inputmode: p.kind === "int" ? "numeric" : "decimal",
                             onchange: (e) => send(p.key, e.target.value)});
    const row = el("div", {class: "ctl"});
    if (p.min !== null && p.max !== null && p.max > p.min) {
      const range = el("input", {type: "range", min: p.min, max: p.max, step,
                                 oninput: (e) => { num.value = e.target.value; },
                                 onchange: (e) => send(p.key, e.target.value)});
      row.append(range);
    }
    row.append(num);
    field.append(row);
  } else if (p.kind === "choice") {
    ctl = el("select", {id, onchange: (e) => send(p.key, e.target.value)},
             ...p.choices.map((c) => el("option", {value: c.value, text: c.label})));
    field.append(ctl);
  } else if (p.kind === "flags") {
    const row = el("div", {class: "flags"});
    for (const c of p.choices) {
      row.append(el("label", {class: "check"}, el("input", {type: "checkbox", value: c.value, onchange: () => {
        const on = [...row.querySelectorAll("input:checked")].map((i) => i.value);
        send(p.key, on.join("_") || "none");
      }}), el("span", {text: c.label})));
    }
    field.append(row);
  } else {  // text, layers
    ctl = el("input", {id, type: "text", onchange: (e) => send(p.key, e.target.value)});
    field.append(ctl);
  }
  return field;
}

function syncParams() {
  for (const field of document.querySelectorAll("#params .field")) {
    const key = field.dataset.key;
    if (!(key in S.settings)) continue;
    const value = S.settings[key];
    field.classList.toggle("off", S.enabled[key] === false);
    for (const input of field.querySelectorAll("input, select")) {
      if (input === document.activeElement) continue;  // (being edited)
      if (field.dataset.kind === "flags") {
        input.checked = String(value).split("_").includes(input.value);
      } else if (input.type === "checkbox") {
        input.checked = !!value;
      } else {
        const text = value === "none" && field.dataset.kind === "text" ? "" : String(value);
        if (input.value !== text) input.value = text;
      }
    }
  }
}

// ------------------------------------------------------------------ start
async function start(queue, memory) {
  $("start-msg").textContent = "";
  const a = await act("start", {queue, memory});
  if (a.ask) {
    $("memory").hidden = false;
    $("memory-text").textContent = t("memory_ask", {text: a.ask.text});
    $("mem-smaller").hidden = !a.ask.smaller;
    $("mem-smaller").textContent = t("use_smaller", {changes: a.ask.smaller});
    $("mem-smaller").onclick = () => { $("memory").hidden = true; start(queue, "smaller"); };
    $("mem-anyway").onclick = () => { $("memory").hidden = true; start(queue, "anyway"); };
    return;
  }
  if (a.ok) {
    $("start-msg").textContent = a.queued || queue ? T.added : T.started;
    if (!queue) showTab("sketch");
  }
}
$("start").onclick = () => start(false);
$("queue-add").onclick = () => start(true);

// ------------------------------------------------------------------ the detail brush
function renderDetails() {
  const d = S.details;
  $("details-state").textContent = (d.has ? T.details_has : T.details_none) + (d.used ? "" : " " + T.details_not_used);
  for (const id of ["paint", "face", "details-clear"]) $(id).disabled = !S.image;
  $("details-clear").disabled = !S.image || !d.has;
}
$("face").onclick = async () => { const a = await act("face"); if (a.ok) toast(T.face_busy); };
$("paint-face").onclick = async () => {
  const a = await act("face");
  if (!a.ok) return;
  $("paint-msg").textContent = T.face_busy;
  const rev = S ? S.details.rev : -1;
  for (let k = 0; k < 40; k++) {  // wait until the map changed, then show it
    await new Promise((r) => setTimeout(r, 700));
    const s = await getJSON("/api/get/studio").catch(() => null);
    if (s && s.details.rev !== rev) { S = s; $("paint-msg").textContent = ""; reloadMap(); return; }
  }
};
$("details-clear").onclick = () => act("clear_details");

const P = {canvas: $("paint-canvas"), map: null, photo: null, tool: 255, undo: [], dirty: false, drawing: false, last: null};

async function reloadMap() {
  const mapImg = new Image();
  mapImg.src = "/api/file/details?v=" + Date.now();
  await mapImg.decode().catch(() => {});
  snapshot();
  P.map.getContext("2d").drawImage(mapImg, 0, 0, P.map.width, P.map.height);
  draw();
}

$("paint").onclick = async () => {
  $("painter").hidden = false;
  $("paint-msg").textContent = "";
  const photo = new Image();
  const mapImg = new Image();
  const v = Date.now();
  photo.src = "/api/file/input?v=" + v;
  mapImg.src = "/api/file/details?v=" + v;
  await Promise.all([photo.decode(), mapImg.decode()]).catch(() => { $("paint-msg").textContent = T.failed; });
  P.photo = photo;
  const w = photo.naturalWidth, h = photo.naturalHeight;
  P.canvas.width = w;
  P.canvas.height = h;
  P.map = document.createElement("canvas");
  P.map.width = w;
  P.map.height = h;
  const m = P.map.getContext("2d");
  m.drawImage(mapImg, 0, 0, w, h);
  P.undo = [];
  P.brush = Number($("brush").value) / 100 * Math.max(w, h) / 2;
  draw();
};
$("paint-close").onclick = () => { $("painter").hidden = true; };
$("tools").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-tool]");
  if (!b) return;
  P.tool = Number(b.dataset.tool);
  for (const x of $("tools").children) x.classList.toggle("on", x === b);
});
$("brush").oninput = (e) => { if (P.photo) P.brush = Number(e.target.value) / 100 * Math.max(P.canvas.width, P.canvas.height) / 2; };

function snapshot() {
  const m = P.map.getContext("2d");
  P.undo.push(m.getImageData(0, 0, P.map.width, P.map.height));
  if (P.undo.length > 12) P.undo.shift();
}
$("paint-undo").onclick = () => {
  if (!P.undo.length) return;
  P.map.getContext("2d").putImageData(P.undo.pop(), 0, 0);
  draw();
};
$("paint-clear").onclick = () => {
  if (!P.map) return;
  snapshot();
  const m = P.map.getContext("2d");
  m.fillStyle = "rgb(128,128,128)";
  m.fillRect(0, 0, P.map.width, P.map.height);
  draw();
};

function dab(x, y) {
  const m = P.map.getContext("2d");
  const r = P.brush;
  const v = P.tool;
  const g = m.createRadialGradient(x, y, r * 0.6, x, y, r);
  g.addColorStop(0, `rgba(${v},${v},${v},1)`);
  g.addColorStop(1, `rgba(${v},${v},${v},0)`);
  m.fillStyle = g;
  m.beginPath();
  m.arc(x, y, r, 0, Math.PI * 2);
  m.fill();
}

function pos(e) {
  const r = P.canvas.getBoundingClientRect();
  return [(e.clientX - r.left) * P.canvas.width / r.width, (e.clientY - r.top) * P.canvas.height / r.height];
}
P.canvas.addEventListener("pointerdown", (e) => {
  if (!P.map) return;
  P.canvas.setPointerCapture(e.pointerId);
  snapshot();
  P.drawing = true;
  P.last = pos(e);
  dab(...P.last);
  requestDraw();
});
P.canvas.addEventListener("pointermove", (e) => {
  if (!P.drawing) return;
  const [x, y] = pos(e);
  const [lx, ly] = P.last;
  const dist = Math.hypot(x - lx, y - ly);
  const steps = Math.max(1, Math.ceil(dist / Math.max(P.brush * 0.3, 1)));
  for (let k = 1; k <= steps; k++) dab(lx + (x - lx) * k / steps, ly + (y - ly) * k / steps);
  P.last = [x, y];
  requestDraw();
});
for (const ev of ["pointerup", "pointercancel"]) P.canvas.addEventListener(ev, () => { P.drawing = false; requestDraw(); });

function requestDraw() {
  if (P.dirty) return;
  P.dirty = true;
  requestAnimationFrame(() => { P.dirty = false; draw(); });
}

function draw() {
  if (!P.photo) return;
  const c = P.canvas.getContext("2d");
  const w = P.canvas.width, h = P.canvas.height;
  c.drawImage(P.photo, 0, 0, w, h);
  const map = P.map.getContext("2d").getImageData(0, 0, w, h).data;
  const over = c.createImageData(w, h);
  const o = over.data;
  for (let i = 0; i < map.length; i += 4) {
    const v = (map[i] - 128) / 127;
    if (v > 0.03) { o[i] = 255; o[i + 1] = 140; o[i + 2] = 0; o[i + 3] = Math.round(v * 150); }
    else if (v < -0.03) { o[i] = 40; o[i + 1] = 120; o[i + 2] = 255; o[i + 3] = Math.round(-v * 150); }
  }
  const tmp = document.createElement("canvas");
  tmp.width = w;
  tmp.height = h;
  tmp.getContext("2d").putImageData(over, 0, 0);
  c.drawImage(tmp, 0, 0);
}

$("paint-save").onclick = () => {
  if (!P.map) return;
  $("paint-msg").textContent = T.sending;
  P.map.toBlob(async (blob) => {
    try {
      const r = await fetch("/api/details", {method: "POST", body: blob, headers: {"X-Access": TOKEN}});
      const a = await r.json();
      if (a.ok) { $("painter").hidden = true; toast(T.saved); } else $("paint-msg").textContent = a.error || T.failed;
    } catch (e) {
      $("paint-msg").textContent = T.failed;
    }
    schedule(100);
  }, "image/png");
};

// ------------------------------------------------------------------ the sketch
for (const [id, prefix] of [["style", "style_"], ["paper", "paper_"]]) {
  const sel = $(id);
  for (const k of Object.keys(T).filter((k) => k.startsWith(prefix))) {
    sel.append(el("option", {value: k.slice(prefix.length), text: T[k]}));
  }
  sel.onchange = (e) => act("style", {[id]: e.target.value});
}

function renderSketch() {
  const has = S.shown !== null && S.shown !== undefined && S.seeds.length > 0;
  $("no-sketch").hidden = has;
  $("no-sketch").textContent = S.running_here ? (S.status || T.running) : T.no_sketch;
  $("view-name").textContent = S.view || "";
  const sig = S.shown + ":" + S.live_rev + ":" + S.style + ":" + S.paper;
  if (has && sig !== lastSeen.sketch) {
    lastSeen.sketch = sig;
    $("sketch").src = `/api/file/sketch?seed=${S.shown}&full=1&v=${S.live_rev}&s=${S.style}&p=${S.paper}`;
  } else if (!has) {
    $("sketch").removeAttribute("src");
    lastSeen.sketch = "";
  }
  const seedsSig = JSON.stringify(S.seeds) + S.shown + S.style;
  if (seedsSig !== lastSeen.seeds) {
    lastSeen.seeds = seedsSig;
    const box = $("seeds");
    box.replaceChildren();
    if (S.seeds.length > 1) {
      for (const s of S.seeds) {
        box.append(el("button", {class: s.seed === S.shown ? "sel" : "", onclick: () => act("select", {seed: s.seed})},
                      el("img", {src: `/api/file/sketch?seed=${s.seed}&v=${s.rev}&s=${S.style}`, alt: ""}),
                      el("span", {text: s.caption || String(s.seed)})));
      }
    }
  }
  const stats = $("stats");
  stats.replaceChildren(...S.stats.map((x) => el("div", {}, el("b", {text: x.value}), el("span", {text: x.label}))));
  $("rate-card").hidden = !S.can_rate;
  $("up").classList.toggle("on", S.rating === 1);
  $("down").classList.toggle("on", S.rating === -1);
  $("taste").textContent = t("taste", {up: S.taste.up, down: S.taste.down, need: S.taste.need});
  if (document.activeElement !== $("style")) $("style").value = S.style;
  if (document.activeElement !== $("paper")) $("paper").value = S.paper;
  $("dl-svg").href = has ? `/api/file/download?fmt=svg&seed=${S.shown}` : "#";
  $("dl-png").href = has ? `/api/file/download?fmt=png&seed=${S.shown}` : "#";
  $("dl-svg").classList.toggle("off", !has);
  $("dl-png").classList.toggle("off", !has);
  $("continue").hidden = !S.can_continue;
}
$("continue").onclick = () => act("continue");
$("up").onclick = () => act("rate", {value: 1});
$("down").onclick = () => act("rate", {value: -1});

// ------------------------------------------------------------------ gallery and queue
async function loadResults() {
  const box = $("results");
  const list = await getJSON("/api/get/results").catch(() => ({results: []}));
  box.replaceChildren();
  for (const r of list.results || []) {
    box.append(el("button", {class: "result", onclick: async () => {
      const a = await act("open", {i: r.i});
      if (a.ok) showTab("sketch");
    }}, el("img", {src: `/api/file/result?i=${r.i}&d=${encodeURIComponent(r.dir)}`, alt: "", loading: "lazy"}),
       el("b", {text: (r.fav ? "★ " : "") + r.name}),
       el("span", {text: r.method + (r.score !== null ? " · " + r.score : "") + " · " + (r.created || "").slice(0, 16)})));
  }
  if (!box.children.length) box.append(el("div", {class: "muted", text: T.empty}));
}

async function loadQueue() {
  const box = $("jobs");
  const list = await getJSON("/api/get/queue").catch(() => ({jobs: []}));
  box.replaceChildren();
  for (const j of list.jobs || []) {
    const bar = el("div", {class: "bar"}, el("div", {style: `width:${Math.round(100 * j.progress)}%`}));
    box.append(el("div", {class: "job"},
      el("div", {class: "info"}, el("b", {text: j.name}),
         el("span", {class: "muted", text: j.method + " · " + (T["status_" + j.status] || j.status)}), bar),
      j.status === "queued" ? el("button", {class: "small", text: T.remove, onclick: () => act("remove", {id: j.id}).then(loadQueue)}) : null));
  }
  if (!box.children.length) box.append(el("div", {class: "muted", text: T.queue_empty}));
}

refresh();
