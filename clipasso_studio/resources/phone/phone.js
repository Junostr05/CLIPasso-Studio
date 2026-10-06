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
    if (k === "style") throw new Error("inline styles are blocked by the page's CSP – set e.style instead");
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children) if (c !== null && c !== undefined) e.append(c);
  return e;
}

// ------------------------------------------------------------------ talking to the app
function signedOut(r, data) {
  // the sign-in is gone (a new access code on the PC): load the page again – it asks for the PIN
  if (r.status === 403 && data && data.error === "no access") location.replace("/");
}

async function getJSON(path) {
  const r = await fetch(path, {cache: "no-store"});
  const data = await r.json().catch(() => ({ok: false, error: T.failed}));
  signedOut(r, data);
  if (r.status === 503) throw new Error(T.busy);
  return data;
}

async function act(action, data) {
  const r = await fetch("/api/do", {method: "POST", headers: {"X-Access": TOKEN, "Content-Type": "application/json"},
                                    body: JSON.stringify(Object.assign({action}, data || {}))});
  const answer = await r.json().catch(() => ({ok: false, error: T.failed}));
  signedOut(r, answer);
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
  if (name === "sketch" && S) renderSketch();
  if (name === "queue") loadQueue();
  window.scrollTo(0, 0);
}
for (const b of document.querySelectorAll("#tabs button")) b.onclick = () => showTab(b.dataset.tab);

// ------------------------------------------------------------------ state from the studio
let S = null;           // the latest studio state
let schemaOf = {};      // method -> its parameters
let builtFor = "";      // the method the parameter fields are built for
let lastSeen = {input: "", sketch: "", seeds: "", note: 0, details: -1, bg: ""};

let timer = 0;
let lastRefresh = 0;
function schedule(ms) {
  clearTimeout(timer);
  timer = setTimeout(refresh, ms);
}

// live updates: the PC says when something changed (server-sent events); asking every few seconds only when that
// stream is quiet for too long (no "ping" for 20 s – e.g. blocked on the way)
let live = null;
let heard = 0;
const isLive = () => live !== null && Date.now() - heard < 20000;
function listen() {
  if (!window.EventSource || live) return;
  live = new EventSource("/api/events");
  live.addEventListener("changed", () => {
    heard = Date.now();
    schedule(Math.max(60, lastRefresh + 400 - Date.now()));  // (at most every 0.4 s while a sketch is drawn)
  });
  live.addEventListener("ping", () => { heard = Date.now(); });
  live.onerror = () => {
    if (live && live.readyState === EventSource.CLOSED) { live = null; }  // (refused, e.g. signed out: polling)
  };
}
function unlisten() {
  if (live) { live.close(); live = null; }
}

async function refresh() {
  lastRefresh = Date.now();
  try {
    const s = await getJSON("/api/get/studio");
    if (s.ok === false) throw new Error(s.error || T.offline);
    S = s;
    await render();
    schedule(document.hidden ? 8000 : (isLive() ? 15000 : (s.busy ? 1500 : 3000)));
  } catch (e) {
    $("status").textContent = e.message && e.message !== "Failed to fetch" ? e.message : T.offline;
    schedule(4000);
  }
}
document.addEventListener("visibilitychange", () => {
  if (document.hidden) { unlisten(); return; }  // (no stream while the page is not seen: the battery)
  listen();
  schedule(50);
});

async function render() {
  renderTop();
  renderPicture();
  renderMethods();
  renderUserPresets();
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
  // a result of the gallery is shown while a job runs: the bar follows the running job, a button leads back to it
  const away = S.busy && !S.running_here && S.running;
  $("status").textContent = S.status || (S.busy ? T.running : T.idle);
  $("progress").style.width = Math.round(100 * ((away ? S.running.progress : S.progress) || 0)) + "%";
  $("to-live").hidden = !away;
  if (away) $("to-live").textContent = "▶ " + t("to_live", {name: S.running.name, pct: Math.round(100 * S.running.progress)});
  $("pause").textContent = S.paused ? T.resume : T.pause;
  $("pause").disabled = $("cancel").disabled = !S.busy;
  $("cancel").textContent = T.cancel;
  $("estimate").textContent = S.estimate || "";
}

$("to-live").onclick = async () => {
  const a = await act("live");
  if (a.ok) showTab("sketch");
};

$("pause").onclick = () => fetch(S && S.paused ? "/api/resume" : "/api/pause",
                                 {method: "POST", headers: {"X-Access": TOKEN}}).then(() => schedule(100));
$("cancel").onclick = () => {
  if (confirm(T.cancel_ask)) fetch("/api/cancel", {method: "POST", headers: {"X-Access": TOKEN}}).then(() => schedule(100));
};

// ------------------------------------------------------------------ picture
let showMask = false;
function renderPicture() {
  const img = S.image;
  $("no-input").hidden = !!img;
  $("input-name").textContent = img ? img.name + " · " + img.size : "";
  const m = S.mask || {};
  if (!m.ready) showMask = false;
  const want = img ? (showMask ? "mask:" : "") + img.rev + ":" + (m.text || "") : "";
  if (img && want !== lastSeen.input) {
    lastSeen.input = want;
    $("input").src = (showMask ? "/api/file/mask?v=" : "/api/file/input?v=") + encodeURIComponent(want);
  } else if (!img) {
    $("input").removeAttribute("src");
    lastSeen.input = "";
  }
  $("crop").disabled = !img;
  $("mask").hidden = !(img && m.used);
  $("mask").disabled = !m.ready;
  $("mask").textContent = showMask ? T.mask_hide : T.mask_show;
  $("mask-state").textContent = img && m.used ? m.text : "";
}
$("mask").onclick = () => { showMask = !showMask; renderPicture(); };

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
  const dl = S.download;
  const loading = !!(dl && dl.status === "running");
  $("missing").hidden = !S.missing.length || loading;
  if (S.missing.length) {
    $("missing-text").textContent = t("models_missing", {size: S.missing_mb});
    $("download").textContent = t("download_models", {size: S.missing_mb});
  }
  $("downloading").hidden = !dl || dl.status === "done" && !S.missing.length;
  if (dl) {
    const part = dl.total > 0 ? dl.done / dl.total : 0;
    $("download-text").textContent = loading ? t("downloading", {name: dl.name, i: dl.index, n: dl.count,
                                                                  pct: Math.round(100 * part)})
      : dl.status === "failed" ? t("download_failed", {error: dl.error}) : T["download_" + dl.status] || "";
    $("download-bar").style.width = Math.round(100 * (loading ? part : (dl.status === "done" ? 1 : 0))) + "%";
    $("download-cancel").hidden = !loading;
  }
}
$("download").onclick = () => act("download_models");
$("download-cancel").onclick = () => act("cancel_download");

$("budget").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-min]");
  if (b) act("budget", {minutes: Number(b.dataset.min)}).then((a) => { if (a.ok) toast(a.estimate); });
});
$("budget-go").onclick = () => {
  const n = Number($("budget-min").value);
  if (n > 0) act("budget", {minutes: n}).then((a) => { if (a.ok) toast(a.estimate); });
};

// own presets (the same as in the studio's "My presets" menu): one of another method switches to it
function renderUserPresets() {
  const list = S.user_presets || [];
  const box = $("user-presets");
  const sig = JSON.stringify(list) + S.method + "|" + S.user_preset;
  if (box.dataset.sig === sig) return;
  box.dataset.sig = sig;
  const input = $("preset-name");
  if (S.user_preset && document.activeElement !== input) input.value = S.user_preset;  // (to update it)
  box.replaceChildren();
  const ordered = list.filter((p) => p.method === S.method).concat(list.filter((p) => p.method !== S.method));
  for (const p of ordered) {
    const on = p.method === S.method && p.name === S.user_preset;
    const choose = async () => {
      const a = await act("user_preset", {name: p.name, method: p.method});
      if (a.ok) {
        toast(t("preset_applied", {name: p.name}));
        $("preset-name").value = p.name;  // (change something, save: the preset is updated)
      }
    };
    const remove = async () => {
      if (!confirm(t("preset_delete_ask", {name: p.name}))) return;
      const a = await act("delete_preset", {name: p.name, method: p.method});
      if (a.ok) toast(T.preset_deleted);
    };
    box.append(el("div", {class: "mine-row"},
      el("button", {class: "mine-name" + (on ? " on" : ""), onclick: choose},
         el("span", {text: p.name}), p.method !== S.method ? el("small", {text: p.method_name}) : null),
      el("button", {class: "small", title: T.delete, "aria-label": T.delete, text: "🗑", onclick: remove})));
  }
  if (!list.length) box.append(el("div", {class: "muted small-text", text: T.no_presets}));
}
// a new own preset: everything set on this page (method, preset, every parameter) under a name – made here or on the
// PC alike; the name of a preset chosen here is filled in, so saving again updates it
$("preset-name").placeholder = T.preset_placeholder;
$("preset-name").setAttribute("aria-label", T.preset_placeholder);
$("preset-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("preset-name");
  const name = input.value.replace(/\s+/g, " ").trim();
  if (!name || !S) { input.focus(); return; }
  const taken = (S.user_presets || []).some((p) => p.name === name && p.method === S.method);
  if (taken && !confirm(t("preset_replace_ask", {name}))) return;
  input.blur();
  const a = await act("save_preset", {name});
  if (a.ok) toast(t("preset_saved", {name: a.name}));
});
$("to-preset").onclick = () => {  // (from the parameters up to the name of the preset)
  $("preset-form").scrollIntoView({block: "center", behavior: "smooth"});
  $("preset-name").focus({preventScroll: true});
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

// SceneSketch: the views (the sketch, the background LaMa filled in behind the object, the matrix) and the layers
// of a finished cell (whole, only the background, only the object)
let sceneView = "sketch";
let layerPart = "all";
document.querySelector(".axis-x").textContent = (T.matrix_fidelity || "") + "  →";
document.querySelector(".axis-y").textContent = (T.matrix_simplicity || "") + "  →";
$("scene-views").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-view]");
  if (!b) return;
  sceneView = b.dataset.view;
  renderScene();
});
$("layer-switch").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-part]");
  if (!b) return;
  layerPart = b.dataset.part;
  renderSketch();
});

function renderScene() {
  const sc = S && S.scene;
  if (!sc) sceneView = "sketch";
  $("scene-views").hidden = !sc;
  for (const b of $("scene-views").children) b.classList.toggle("on", b.dataset.view === sceneView);
  $("sketch-box").hidden = sceneView !== "sketch";
  $("background-box").hidden = sceneView !== "background";
  $("matrix-box").hidden = sceneView !== "matrix";
  $("scene-part").hidden = !(sc && sc.part);
  if (sc && sc.part) $("scene-part").textContent = "✎ " + (T["scene_part_" + sc.part] || "");
  const layered = !!(sc && sc.layered);
  if (!layered) layerPart = "all";
  $("layer-switch").hidden = !layered || sceneView !== "sketch";
  for (const b of $("layer-switch").children) b.classList.toggle("on", b.dataset.part === layerPart);
  if (!sc) return;
  if (sceneView === "background") {
    $("no-bg").hidden = sc.background;
    if (sc.background && lastSeen.bg !== sc.background_rev) {
      lastSeen.bg = sc.background_rev;
      $("scene-bg").src = "/api/file/background?v=" + encodeURIComponent(sc.background_rev);
    } else if (!sc.background) {
      $("scene-bg").removeAttribute("src");
      lastSeen.bg = "";
    }
  }
  if (sceneView === "matrix") renderMatrix(sc);
}

function renderMatrix(sc) {
  const box = $("matrix");
  const sig = JSON.stringify(sc.cells) + S.shown + S.style;
  if (box.dataset.sig === sig) return;
  box.dataset.sig = sig;
  box.style.gridTemplateColumns = `22px repeat(${sc.layers.length}, minmax(0, 140px))`;  // (the CSSOM: CSP)
  const items = [el("div")];
  for (const layer of sc.layers) items.push(el("div", {class: "head", text: "L" + layer}));
  for (let level = 0; level <= sc.levels; level++) {
    items.push(el("div", {class: "head", text: String(level)}));
    for (const layer of sc.layers) {
      const c = sc.cells.find((x) => x.layer === layer && x.level === level);
      if (!c || !c.has) {
        items.push(el("div", {class: "cell empty", title: t("cell", {layer, level})}));
        continue;
      }
      items.push(el("button", {
        class: "cell" + (c.best ? " best" : "") + (c.seed === S.shown ? " sel" : ""), title: t("cell", {layer, level}),
        onclick: async () => {
          const a = await act("select", {seed: c.seed});
          if (a.ok) { sceneView = "sketch"; renderScene(); }
        }}, el("img", {src: `/api/file/sketch?seed=${c.seed}&v=${c.rev}&s=${S.style}`, alt: "", loading: "lazy"})));
    }
  }
  box.replaceChildren(...items);
}

function renderSketch() {
  renderScene();
  const has = S.shown !== null && S.shown !== undefined && S.seeds.length > 0;
  $("no-sketch").hidden = has;
  $("no-sketch").textContent = S.running_here ? (S.status || T.running) : T.no_sketch;
  $("view-name").textContent = S.view || "";
  const sig = S.shown + ":" + S.live_rev + ":" + S.style + ":" + S.paper + ":" + layerPart;
  if (has && sig !== lastSeen.sketch) {
    lastSeen.sketch = sig;
    const part = layerPart !== "all" ? "&part=" + layerPart : "";
    $("sketch").src = `/api/file/sketch?seed=${S.shown}&full=1&v=${S.live_rev}&s=${S.style}&p=${S.paper}${part}`;
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
  $("export-card").hidden = !has || !X.info;
  if (has && tab === "sketch") loadExportInfo(false);
}
$("continue").onclick = () => act("continue");
$("up").onclick = () => act("rate", {value: 1});
$("down").onclick = () => act("rate", {value: -1});

// ------------------------------------------------------------------ export: every format of the studio's dialog
const X = {info: null, fmt: "", opts: {}, sig: "", job: null, bg: "#FFFFFF"};

async function loadExportInfo(force) {
  // the formats and the remembered choices – again when another sketch is shown
  const sig = S.view + ":" + S.shown;
  if (!force && X.sig === sig) return;
  X.sig = sig;
  const info = await getJSON("/api/get/export_info").catch(() => null);
  if (!info) X.sig = "";  // (no answer: ask again next time)
  if (!info || info.ok === false) { X.info = null; $("export-card").hidden = true; return; }
  X.info = info;
  X.opts = {};
  const known = (f) => info.formats.some((x) => x.fmt === f);
  if (!known(X.fmt)) X.fmt = known(info.last) ? info.last : "png";
  buildExport();
  $("export-card").hidden = false;
}

function exportFormat() { return X.info.formats.find((x) => x.fmt === X.fmt); }

function buildExport() {
  const f = exportFormat();
  $("formats").replaceChildren(...X.info.formats.map((x) => el("button", {
    class: x.fmt === X.fmt ? "on" : "", title: x.desc, text: x.title,
    onclick: () => { X.fmt = x.fmt; buildExport(); }})));
  $("fmt-desc").textContent = f.desc;
  $("export-go").textContent = t("export_go", {fmt: f.title});
  if (!X.opts[X.fmt]) X.opts[X.fmt] = Object.assign({}, f.defaults);
  const o = X.opts[X.fmt];
  const a = f.applies;
  if (o.background !== "transparent") X.bg = o.background;
  const field = (label, wide, ...ctl) => el("div", {class: "field" + (wide ? " wide" : "")},
    el("div", {class: "head"}, el("label", {text: label})), el("div", {class: "ctl"}, ...ctl));
  const number = (key, min, max, step) => el("input", {type: "number", class: "num", min, max, step, value: o[key],
    inputmode: step < 1 ? "decimal" : "numeric", onchange: (e) => {
      const v = Number(e.target.value);
      if (Number.isFinite(v)) o[key] = Math.min(max, Math.max(min, v));
      e.target.value = o[key];
    }});
  const select = (key, items) => el("select", {onchange: (e) => { o[key] = e.target.value; }},
    ...items.map((i) => el("option", {value: i.key, text: i.label, selected: i.key === o[key], disabled: i.ok === false})));
  const out = [];
  if (a.mode) {
    out.push(field(T.x_mode, true, el("div", {class: "seg"}, ...["process", "strokes"].map((m) => el("button", {
      class: o.mode === m ? "on" : "", text: T["x_mode_" + m], onclick: () => {
        o.mode = m;  // (the length follows, as in the dialog)
        o.length = m === "strokes" ? X.info.sketch.draw_length : X.info.sketch.process_length;
        buildExport();
      }})))));
  }
  const colour = el("input", {type: "color", value: o.stroke, onchange: (e) => { o.stroke = e.target.value; }});
  out.push(field(T.x_stroke, false, colour));
  out.push(field(T.x_width, false, number("width", 0.1, 10, 0.1)));
  if (a.style) out.push(field(T.x_style, true, select("style", X.info.styles)));
  if (a.background) {
    const bg = el("input", {type: "color", value: o.background === "transparent" ? X.bg : o.background,
      disabled: o.background === "transparent", onchange: (e) => { o.background = X.bg = e.target.value; }});
    out.push(field(T.x_background, false, bg));
    if (a.transparent) {
      out.push(el("label", {class: "check wide"}, el("input", {type: "checkbox", checked: o.background === "transparent",
        onchange: (e) => {
          o.background = e.target.checked ? "transparent" : X.bg;
          bg.disabled = e.target.checked;
        }}), el("span", {text: T.no_background})));
    }
  }
  if (a.paper) {
    out.push(field(T.x_paper, false, select("paper", X.info.papers)));
    out.push(field(T.x_vignette + " (%)", false, number("vignette", 0, 100, 5)));
  }
  if (a.frame) {
    out.push(field(T.x_frame, false, select("frame", X.info.frames)));
    out.push(field(T.x_margin + " (%)", false, number("margin", 0, 50, 1)));
  }
  if (a.size) out.push(field(T.x_size + " (px)", true, number("size", 64, 4096, 64)));
  if (a.width_cm) out.push(field(T.x_width_cm + " (cm)", true, number("width_cm", 2, 200, 0.5)));
  if (a.length) {
    out.push(field(T.x_length + " (s)", false, number("length", 0.5, 300, 0.5)));
    out.push(field(T.x_hold + " (s)", false, number("hold", 0, 10, 0.5)));
  }
  $("export-opts").replaceChildren(...out);
}

function exportShow(text, part) {
  $("export-state").hidden = false;
  $("export-msg").textContent = text;
  $("export-progress").style.width = Math.round(100 * part) + "%";  // (the CSSOM: no inline styles)
}

function exportEnd(text, part) {
  X.job = null;
  $("export-go").disabled = false;
  $("export-cancel").hidden = true;
  exportShow(text, part);
}

function sizeText(n) {
  return n >= 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB";
}

$("export-go").onclick = async () => {
  if (X.job || !X.info) return;
  $("export-dl").hidden = true;
  $("export-go").disabled = true;
  const a = await act("export", {fmt: X.fmt, options: X.opts[X.fmt]});
  if (!a.ok) { $("export-go").disabled = false; return; }
  X.job = a.id;
  $("export-cancel").hidden = false;
  exportShow(t("export_running", {pct: 0}), 0);
  pollExport(a.id, 0);
};
$("export-cancel").onclick = () => { if (X.job) act("cancel_export", {id: X.job}); };

async function pollExport(id, misses) {
  if (X.job !== id) return;
  const e = await getJSON("/api/get/export?id=" + encodeURIComponent(id)).catch(() => null);
  if (X.job !== id) return;
  if (!e) {  // (no answer: the app is busy or the phone was away – ask again)
    if (misses < 40) setTimeout(() => pollExport(id, misses + 1), 1500);
    else exportEnd(T.offline, 0);
    return;
  }
  if (e.ok === false) { exportEnd(e.error || T.failed, 0); return; }
  if (e.status === "running") {
    const part = e.total ? e.done / e.total : 0;
    exportShow(t("export_running", {pct: Math.round(100 * part)}), part);
    setTimeout(() => pollExport(id, 0), 700);
    return;
  }
  if (e.status === "done") {
    exportEnd(t("export_ready", {name: e.name, size: sizeText(e.size)}), 1);
    const dl = $("export-dl");
    dl.href = "/api/file/export?id=" + encodeURIComponent(id);
    dl.setAttribute("download", e.name);
    dl.textContent = "⬇ " + T.export_download;
    dl.hidden = false;
  } else {
    exportEnd(e.status === "cancelled" ? T.export_cancelled : t("export_failed", {error: e.error || "?"}), 0);
  }
}

// ------------------------------------------------------------------ gallery and queue
// the gallery: every result, searched and filtered, page by page; a result large (swipe to the next one)
const G = {items: [], total: 0, q: "", method: "", album: "", fav: false, at: -1, busy: false};
$("search").placeholder = T.search;
$("filter-method").title = T.filter_method;
$("filter-album").title = T.filter_album;
$("filter-fav").title = T.filter_fav;
let searchTimer = 0;
$("search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { G.q = $("search").value.trim(); loadResults(); }, 300);
});
$("filter-method").onchange = (e) => { G.method = e.target.value; loadResults(); };
$("filter-album").onchange = (e) => { G.album = e.target.value; loadResults(); };
$("filter-fav").onclick = () => { G.fav = !G.fav; loadResults(); };
$("more").onclick = () => loadResults(true);

function fillSelect(sel, items, all, current) {
  const sig = JSON.stringify(items);
  if (sel.dataset.sig !== sig) {
    sel.dataset.sig = sig;
    sel.replaceChildren(el("option", {value: "", text: all}),
                        ...items.map((i) => el("option", {value: i.key, text: i.name})));
  }
  sel.value = current;
  sel.hidden = !items.length;
}

async function loadResults(more) {
  if (G.busy) return;
  G.busy = true;
  const q = new URLSearchParams({q: G.q, method: G.method, album: G.album, fav: G.fav ? "1" : "",
                                 offset: more ? G.items.length : 0});
  const list = await getJSON("/api/get/results?" + q).catch(() => null);
  G.busy = false;
  if (!list || list.ok === false) return;
  G.items = more ? G.items.concat(list.results) : list.results;
  G.total = list.total;
  fillSelect($("filter-method"), list.methods, T.all_methods, G.method);
  fillSelect($("filter-album"), list.albums.map((a) => ({key: a, name: a})), T.all_albums, G.album);
  $("filter-fav").textContent = G.fav ? "★" : "☆";
  $("filter-fav").classList.toggle("on", G.fav);
  renderResults();
}

function renderResults() {
  const box = $("results");
  box.replaceChildren(...G.items.map((r, k) => el("div", {class: "result", onclick: () => openViewer(k)},
    el("button", {class: "fav" + (r.fav ? " on" : ""), title: T.filter_fav, "aria-label": T.filter_fav,
                  text: r.fav ? "★" : "☆", onclick: (e) => { e.stopPropagation(); toggleFav(r); }}),
    el("button", {class: "del", title: T.delete, "aria-label": T.delete, text: "🗑",
                  onclick: (e) => { e.stopPropagation(); removeResult(r); }}),
    el("img", {src: `/api/file/result?d=${encodeURIComponent(r.dir)}`, alt: "", loading: "lazy"}),
    el("b", {text: r.name}),
    el("span", {text: r.method + (r.score !== null ? " · " + r.score : "") + " · " + (r.created || "").slice(0, 16)}))));
  if (!G.items.length) box.append(el("div", {class: "muted", text: T.empty}));
  $("results-count").textContent = G.total ? t("results_count", {n: G.items.length, total: G.total}) : "";
  $("more").hidden = G.items.length >= G.total;
}

async function toggleFav(r) {
  const a = await act("fav", {dir: r.dir, value: !r.fav});
  if (a.ok) { r.fav = !r.fav; renderResults(); renderViewer(); }
}

async function removeResult(r) {
  if (!confirm(t("delete_ask", {name: r.name}))) return;
  const a = await act("delete", {dir: r.dir});
  if (a.ok) toast(T.deleted);
  closeViewer();
  loadResults();
}

let viewerZoom = null;
function openViewer(k) {
  G.at = k;
  $("viewer").hidden = false;
  renderViewer();
}
function renderViewer() {
  const r = G.items[G.at];
  if ($("viewer").hidden || !r) return;
  $("viewer-name").textContent = r.name;
  $("viewer-info").textContent = [r.method, r.score !== null ? "CLIP " + r.score : "", (r.created || "").slice(0, 16),
                                  t("of", {i: G.at + 1, n: G.total})].filter(Boolean).join(" · ");
  const src = `/api/file/result?d=${encodeURIComponent(r.dir)}`;
  if ($("viewer-img").dataset.src !== src) {
    $("viewer-img").dataset.src = src;
    $("viewer-img").src = src;
    if (viewerZoom) viewerZoom.reset();
  }
  $("viewer-fav").textContent = r.fav ? "★" : "☆";
  $("viewer-fav").classList.toggle("on", r.fav);
}
function closeViewer() { $("viewer").hidden = true; G.at = -1; }
async function stepViewer(d) {
  const k = G.at + d;
  if (k >= G.items.length && G.items.length < G.total) await loadResults(true);
  if (k < 0 || k >= G.items.length) return;
  G.at = k;
  renderViewer();
}
$("viewer-close").onclick = closeViewer;
$("viewer-fav").onclick = () => { const r = G.items[G.at]; if (r) toggleFav(r); };
$("viewer-delete").onclick = () => { const r = G.items[G.at]; if (r) removeResult(r); };
$("viewer-open").onclick = async () => {
  const r = G.items[G.at];
  if (!r) return;
  const a = await act("open", {dir: r.dir});
  if (a.ok) { closeViewer(); showTab("sketch"); }
};

let dragging = null;  // (a waiting job being dragged: the list is not rebuilt meanwhile)
async function loadQueue() {
  if (dragging) return;
  const box = $("jobs");
  const list = await getJSON("/api/get/queue").catch(() => ({jobs: []}));
  if (dragging) return;
  const jobs = list.jobs || [];
  // only the bars move while a job runs: the rows stay (a tap on a button that is rebuilt meanwhile is lost)
  const sig = JSON.stringify(jobs.map((j) => [j.id, j.name, j.status, j.method]));
  if (box.dataset.sig === sig) {
    for (const j of jobs) {
      const fill = box.querySelector(`.job[data-id="${j.id}"] .bar > div`);
      if (fill) fill.style.width = Math.round(100 * j.progress) + "%";
    }
    return;
  }
  box.dataset.sig = sig;
  box.replaceChildren();
  jobs.forEach((j, index) => {
    const fill = el("div");
    fill.style.width = Math.round(100 * j.progress) + "%";  // (through the CSSOM: the page allows no inline styles)
    const bar = el("div", {class: "bar"}, fill);
    const live = j.status === "running" || j.status === "paused";
    const buttons = [];
    if (live) {
      buttons.push(el("button", {class: "small", text: j.status === "paused" ? T.resume : T.pause, onclick: () =>
        fetch(j.status === "paused" ? "/api/resume" : "/api/pause", {method: "POST", headers: {"X-Access": TOKEN}})
          .then(() => schedule(100))}));
      buttons.push(el("button", {class: "small", text: T.cancel, onclick: () => {
        if (confirm(T.cancel_ask)) fetch("/api/cancel", {method: "POST", headers: {"X-Access": TOKEN}}).then(() => schedule(100));
      }}));
    } else if (j.status === "queued") {
      buttons.push(el("button", {class: "small", text: T.remove, onclick: () => act("remove", {id: j.id}).then(loadQueue)}));
    } else if (j.status === "failed" || j.status === "cancelled") {
      buttons.push(el("button", {class: "small", text: T.retry, onclick: () => act("retry", {id: j.id}).then(loadQueue)}));
    }
    const handle = j.status === "queued" ? el("span", {class: "handle", title: T.drag, "aria-label": T.drag, text: "☰"}) : null;
    const row = el("div", {class: "job", "data-id": j.id, "data-index": index}, handle,
      el("div", {class: "info"}, el("b", {text: j.name}),
         el("span", {class: "muted", text: j.method + " · " + (T["status_" + j.status] || j.status)}), bar),
      ...buttons);
    if (handle) dragRow(handle, row);
    box.append(row);
  });
  if (!box.children.length) box.append(el("div", {class: "muted", text: T.queue_empty}));
  $("clear-queue").hidden = !jobs.some((j) => ["done", "failed", "cancelled"].includes(j.status));
}

function dragRow(handle, row) {
  // drag a waiting job up or down by its handle; dropped, it takes the place of the job it is over
  handle.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    handle.setPointerCapture(e.pointerId);
    dragging = {row, y0: e.clientY, dy: 0};
    row.classList.add("dragging");
  });
  handle.addEventListener("pointermove", (e) => {
    if (!dragging || dragging.row !== row) return;
    dragging.dy = e.clientY - dragging.y0;
    row.style.transform = `translateY(${dragging.dy}px)`;
  });
  const drop = async () => {
    if (!dragging || dragging.row !== row) return;
    const mid = row.getBoundingClientRect().top + row.offsetHeight / 2;
    const rows = [...$("jobs").querySelectorAll(".job")].filter((r) => r !== row);
    let index = rows.filter((r) => r.getBoundingClientRect().top + r.offsetHeight / 2 < mid).length;
    row.style.transform = "";
    row.classList.remove("dragging");
    const moved = Math.abs(dragging.dy) > 12;
    dragging = null;
    if (moved && index !== Number(row.dataset.index)) await act("move", {id: Number(row.dataset.id), index});
    $("jobs").dataset.sig = "";
    loadQueue();
  };
  handle.addEventListener("pointerup", drop);
  handle.addEventListener("pointercancel", drop);
}

$("many").onchange = async (e) => {
  // several photos at once: each one into the queue, with the studio's settings
  const files = [...e.target.files];
  e.target.value = "";
  let ok = 0;
  for (let k = 0; k < files.length; k++) {
    $("many-msg").textContent = t("uploading_n", {i: k + 1, n: files.length});
    try {
      const r = await fetch("/api/upload", {method: "POST", body: files[k], headers: {
        "X-Access": TOKEN, "X-Method": S ? S.method : "clipasso",
        "X-Filename": encodeURIComponent(files[k].name || "photo.jpg")}});
      if (r.ok) ok++;
    } catch (err) { /* (counted as not sent) */ }
  }
  $("many-msg").textContent = t("uploaded_n", {ok, n: files.length});
  loadQueue();
};
$("clear-queue").onclick = async () => {
  const a = await act("clear_queue");
  if (a.ok) { toast(t("cleared", {n: a.removed})); loadQueue(); }
};

// ------------------------------------------------------------------ compare the methods (the studio's picture)
let C = null;
$("compare-card").addEventListener("toggle", () => { if ($("compare-card").open) loadCompare(); });
async function loadCompare() {
  const c = await getJSON("/api/get/compare").catch(() => null);
  if (!c || c.ok === false) return;
  const first = C === null;
  C = c;
  const box = $("compare-methods");
  if (first || box.dataset.sig !== JSON.stringify(c.methods.map((m) => m.key))) {
    box.dataset.sig = JSON.stringify(c.methods.map((m) => m.key));
    box.replaceChildren(...c.methods.map((m) => el("label", {class: "check"},
      el("input", {type: "checkbox", value: m.key, checked: m.default}), el("span", {text: m.name}))));
  }
  $("compare-results").replaceChildren(...c.methods.filter((m) => m.state !== "none").map((m) => {
    const fill = el("div");
    fill.style.width = Math.round(100 * m.progress) + "%";
    const state = m.state === "running" ? el("div", {class: "bar"}, fill)
      : el("span", {class: "muted small-text", text: m.state === "queued" ? T.status_queued : m.created});
    return el("div", {class: "compare-item" + (m.best ? " best" : ""), onclick: async () => {
      if (!m.dir) return;
      const a = await act("open", {dir: m.dir});
      if (a.ok) showTab("sketch");
    }}, el("b", {text: (m.best ? "★ " : "") + m.name}),
      m.dir ? el("img", {src: `/api/file/result?d=${encodeURIComponent(m.dir)}`, alt: "", loading: "lazy"}) : null,
      el("span", {class: "small-text", text: [m.score !== null ? "CLIP " + m.score.toFixed(1) : "", m.time,
                                              m.strokes ? t("strokes", {n: m.strokes}) : ""].filter(Boolean).join(" · ")}),
      state);
  }));
  const best = c.methods.find((m) => m.best);
  $("compare-verdict").textContent = best ? t("compare_best", {name: best.name}) : "";
  $("compare-go").disabled = !c.image;
}
async function startCompare(extra) {
  const methods = [...$("compare-methods").querySelectorAll("input:checked")].map((i) => i.value);
  const a = await act("compare", Object.assign({methods, use_studio: $("compare-studio").checked}, extra || {}));
  if (a.asks) {
    const answers = Object.assign({}, extra || {});
    for (const q of a.asks) answers[q.key] = confirm(q.text);
    return startCompare(answers);
  }
  if (a.missing && confirm(T.download_ask)) {
    await act("download_models", {keys: a.missing});
    showTab("studio");
    return;
  }
  if (a.ok) { toast(a.queued === 1 ? T.compare_queued_one : t("compare_queued", {n: a.queued})); loadCompare(); }
}
$("compare-go").onclick = () => startCompare();

// ------------------------------------------------------------------ crop / turn / mirror the picture
const K = {canvas: $("crop-canvas"), img: null, rot: 0, flip: false, box: null, drag: null};
$("crop").onclick = async () => {
  $("cropper").hidden = false;
  $("crop-msg").textContent = "";
  const img = new Image();
  img.src = "/api/file/input?v=" + Date.now();
  await img.decode().catch(() => { $("crop-msg").textContent = T.failed; });
  K.img = img;
  K.rot = 0;
  K.flip = false;
  K.box = {x: 0, y: 0, w: 1, h: 1};
  drawCrop(true);
};
$("crop-close").onclick = () => { $("cropper").hidden = true; };
$("crop-left").onclick = () => { K.rot = (K.rot + 270) % 360; K.box = {x: 0, y: 0, w: 1, h: 1}; drawCrop(true); };
$("crop-right").onclick = () => { K.rot = (K.rot + 90) % 360; K.box = {x: 0, y: 0, w: 1, h: 1}; drawCrop(true); };
$("crop-flip").onclick = () => { K.flip = !K.flip; K.box.x = 1 - K.box.x - K.box.w; drawCrop(); };
$("crop-reset").onclick = () => { K.rot = 0; K.flip = false; K.box = {x: 0, y: 0, w: 1, h: 1}; drawCrop(true); };

function sizeCrop() {
  // the canvas in the picture's (turned) shape, as large as fits: its box is the picture, so touches map straight
  const c = K.canvas, iw = K.img.naturalWidth, ih = K.img.naturalHeight;
  const turned = K.rot % 180 !== 0;
  c.width = turned ? ih : iw;
  c.height = turned ? iw : ih;
  const fit = Math.min((c.parentElement.clientWidth || c.width) / c.width, window.innerHeight * 0.6 / c.height);
  c.style.width = Math.round(c.width * fit) + "px";  // (the CSSOM: the page's CSP allows no inline styles)
  c.style.height = Math.round(c.height * fit) + "px";
}

function drawCrop(resize) {
  if (!K.img) return;
  if (resize) sizeCrop();
  const c = K.canvas, iw = K.img.naturalWidth, ih = K.img.naturalHeight;
  const g = c.getContext("2d");
  g.save();
  g.translate(c.width / 2, c.height / 2);
  if (K.flip) g.scale(-1, 1);  // (the mirror after the turn, as the app does it)
  g.rotate(K.rot * Math.PI / 180);
  g.drawImage(K.img, -iw / 2, -ih / 2);
  g.restore();
  const b = K.box, x = b.x * c.width, y = b.y * c.height, w = b.w * c.width, h = b.h * c.height;
  g.fillStyle = "rgba(0,0,0,0.55)";
  g.fillRect(0, 0, c.width, y);
  g.fillRect(0, y + h, c.width, c.height - y - h);
  g.fillRect(0, y, x, h);
  g.fillRect(x + w, y, c.width - x - w, h);
  g.strokeStyle = "#ffffff";
  g.lineWidth = Math.max(2, c.width / 300);
  g.strokeRect(x, y, w, h);
  const r = Math.max(8, c.width / 40);
  g.fillStyle = "#ffffff";
  for (const [px, py] of [[x, y], [x + w, y], [x, y + h], [x + w, y + h]]) g.fillRect(px - r / 2, py - r / 2, r, r);
}

function cropPos(e) {
  const r = K.canvas.getBoundingClientRect();
  const clamp = (v) => Math.min(1, Math.max(0, v));
  return [clamp((e.clientX - r.left) / r.width), clamp((e.clientY - r.top) / r.height), 28 / r.width, 28 / r.height];
}
// (the touches go to the area around the picture, too: a corner is grabbed also a little outside of it)
const cropArea = K.canvas.parentElement;
cropArea.addEventListener("pointerdown", (e) => {
  if (!K.box) return;
  const [px, py, tx, ty] = cropPos(e);
  const b = K.box;
  const corners = {nw: [b.x, b.y], ne: [b.x + b.w, b.y], sw: [b.x, b.y + b.h], se: [b.x + b.w, b.y + b.h]};
  const corner = Object.keys(corners).find((k) => Math.abs(corners[k][0] - px) < tx && Math.abs(corners[k][1] - py) < ty);
  const inside = px > b.x && px < b.x + b.w && py > b.y && py < b.y + b.h;
  if (!corner && !inside) return;
  e.preventDefault();
  cropArea.setPointerCapture(e.pointerId);
  K.drag = {corner, px, py, box: Object.assign({}, b)};
});
cropArea.addEventListener("pointermove", (e) => {
  if (!K.drag) return;
  const [px, py] = cropPos(e);
  const d = K.drag, o = d.box, dx = px - d.px, dy = py - d.py, min = 0.05;
  let {x, y, w, h} = o;
  if (!d.corner) {
    x = Math.min(1 - w, Math.max(0, o.x + dx));
    y = Math.min(1 - h, Math.max(0, o.y + dy));
  } else {
    if (d.corner.includes("w")) { x = Math.min(o.x + o.w - min, Math.max(0, o.x + dx)); w = o.x + o.w - x; }
    if (d.corner.includes("e")) { w = Math.min(1 - o.x, Math.max(min, o.w + dx)); }
    if (d.corner.includes("n")) { y = Math.min(o.y + o.h - min, Math.max(0, o.y + dy)); h = o.y + o.h - y; }
    if (d.corner.includes("s")) { h = Math.min(1 - o.y, Math.max(min, o.h + dy)); }
  }
  K.box = {x, y, w, h};
  requestAnimationFrame(() => drawCrop());
});
for (const ev of ["pointerup", "pointercancel"]) cropArea.addEventListener(ev, () => { K.drag = null; });
$("crop-apply").onclick = async () => {
  $("crop-msg").textContent = T.sending;
  const a = await act("crop", Object.assign({rotate: K.rot, flip: K.flip}, K.box));
  if (a.ok) { $("cropper").hidden = true; toast(T.cropped); } else $("crop-msg").textContent = a.error || T.failed;
};

// ------------------------------------------------------------------ gestures: zoom and swipe, pull to refresh
function zoomable(img, onSwipe) {
  // one finger: swipe to the next / previous (or move the picture when zoomed); two fingers: zoom; double tap: 1×
  const st = {pts: new Map(), scale: 1, x: 0, y: 0, start: null, pinch: null, tap: 0};
  img.classList.add("zoomable");
  img.draggable = false;  // (a mouse would drag the picture away instead of swiping)
  img.addEventListener("dragstart", (e) => e.preventDefault());
  const apply = () => {
    img.style.transform = st.scale === 1 ? "" : `translate(${st.x}px, ${st.y}px) scale(${st.scale})`;
    img.classList.toggle("zoomed", st.scale > 1);
  };
  const begin = () => {
    const p = [...st.pts.values()][0];
    st.start = p ? {x: p.x, y: p.y, tx: st.x, ty: st.y, t: Date.now()} : null;
  };
  img.addEventListener("pointerdown", (e) => {
    if (e.pointerType === "mouse") e.preventDefault();
    img.setPointerCapture(e.pointerId);
    st.pts.set(e.pointerId, {x: e.clientX, y: e.clientY});
    if (st.pts.size === 1) begin();
    if (st.pts.size === 2) {
      const [a, b] = [...st.pts.values()];
      st.pinch = {d: Math.hypot(a.x - b.x, a.y - b.y) || 1, scale: st.scale};
      st.start = null;
    }
  });
  img.addEventListener("pointermove", (e) => {
    if (!st.pts.has(e.pointerId)) return;
    st.pts.set(e.pointerId, {x: e.clientX, y: e.clientY});
    if (st.pts.size === 2 && st.pinch) {
      const [a, b] = [...st.pts.values()];
      st.scale = Math.min(6, Math.max(1, st.pinch.scale * Math.hypot(a.x - b.x, a.y - b.y) / st.pinch.d));
      if (st.scale === 1) st.x = st.y = 0;
      apply();
    } else if (st.pts.size === 1 && st.scale > 1 && st.start) {
      st.x = st.start.tx + e.clientX - st.start.x;
      st.y = st.start.ty + e.clientY - st.start.y;
      apply();
    }
  });
  const up = (e) => {
    if (!st.pts.has(e.pointerId)) return;
    const single = st.pts.size === 1;
    st.pts.delete(e.pointerId);
    if (single && st.start && st.scale === 1 && e.type === "pointerup") {
      const dx = e.clientX - st.start.x, dy = e.clientY - st.start.y;
      if (Math.abs(dx) > 60 && Math.abs(dy) < 60 && Date.now() - st.start.t < 800) onSwipe(dx < 0 ? 1 : -1);
    }
    if (single && e.type === "pointerup" && st.start && Math.abs(e.clientX - st.start.x) < 10
        && Math.abs(e.clientY - st.start.y) < 10) {
      if (Date.now() - st.tap < 320) { st.scale = 1; st.x = st.y = 0; apply(); }
      st.tap = Date.now();
    }
    if (st.pts.size < 2) st.pinch = null;
    begin();
  };
  img.addEventListener("pointerup", up);
  img.addEventListener("pointercancel", up);
  return {reset() { st.scale = 1; st.x = st.y = 0; apply(); }};
}

const sketchZoom = zoomable($("sketch"), async (d) => {
  // the next / previous sketch of the job
  if (!S || !S.seeds.length) return;
  const seeds = S.seeds.map((x) => x.seed);
  const k = seeds.indexOf(S.shown) + d;
  if (k >= 0 && k < seeds.length) { sketchZoom.reset(); await act("select", {seed: seeds[k]}); }
});
viewerZoom = zoomable($("viewer-img"), (d) => stepViewer(d));

(function pullToRefresh() {
  let y0 = null, pulled = 0;
  const sheetOpen = () => [...document.querySelectorAll(".sheet")].some((x) => !x.hidden);
  window.addEventListener("touchstart", (e) => {
    y0 = window.scrollY <= 0 && e.touches.length === 1 && !sheetOpen() ? e.touches[0].clientY : null;
    pulled = 0;
  }, {passive: true});
  window.addEventListener("touchmove", (e) => {
    if (y0 === null) return;
    pulled = e.touches[0].clientY - y0;
    $("pull").hidden = pulled < 24;
    $("pull").classList.toggle("ready", pulled > 90);
  }, {passive: true});
  window.addEventListener("touchend", () => {
    if (y0 !== null && pulled > 90) {
      schedule(0);
      if (tab === "gallery") loadResults();
      if (tab === "queue") loadQueue();
      if ($("compare-card").open) loadCompare();
    }
    y0 = null;
    $("pull").hidden = true;
  });
})();

listen();
refresh();
