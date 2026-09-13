/* spectro-web – Frontend ohne Build-Schritt, reines ES2020. */
"use strict";

const $ = (id) => document.getElementById(id);
const state = {
  cfg: null,
  root: null,
  path: "",
  a: null,          // {root, path, name}
  b: null,
  compare: false,
  boxes: [],        // Plotgeometrie des aktuellen Bildes
  zoom: null,       // {start, duration, fmin, fmax}
  view: null,       // Zeitfenster des aktuellen Bildes
  objectUrl: null,
};

/* ------------------------------------------------------------- Sprache */
function applyStaticTexts() {
  document.documentElement.lang = window.LANG;
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = T(el.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-title]").forEach((el) => {
    el.title = T(el.dataset.i18nTitle);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    el.placeholder = T(el.dataset.i18nPlaceholder);
  });
  const hint = $("drop-hint");
  if (hint) {
    hint.innerHTML = T("sidebar.dropHint", {
      link: `<a href="#" id="pick">${esc(T("sidebar.pick"))}</a>`,
    });
  }
  const sel = $("lang");
  if (sel) sel.value = window.LANG;
}

function switchLanguage(code) {
  const url = new URL(location.href);
  url.searchParams.set("lang", code);
  location.href = url.toString();
}

/* ---------------------------------------------------------------- Helfer */
const fmtSize = (n) => n > 1e9 ? (n / 1e9).toFixed(2) + " GB"
  : n > 1e6 ? (n / 1e6).toFixed(1) + " MB" : (n / 1e3).toFixed(0) + " kB";
const fmtTime = (s) => {
  s = Math.max(0, s || 0);
  const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = Math.floor(s % 60);
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")}`
           : `${m}:${String(x).padStart(2, "0")}`;
};
const num = (v, digits = 1) =>
  Number(v).toFixed(digits).replace(".", window.LANG === "de" ? "," : ".");
const esc = (v) => String(v ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtHz = (f) => f == null ? "–" : f >= 1000 ? (f / 1000).toFixed(1) + " kHz" : f.toFixed(0) + " Hz";

async function jget(url) {
  const r = await fetch(url);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (e) {}
    throw new Error(msg);
  }
  return r.json();
}

/* ------------------------------------------------------------ Parameter */
function figureWidth() {
  // Die Bildbreite in Zoll an die Anzeigebreite koppeln: sonst schrumpfen
  // Achsenbeschriftung und Titel auf schmalen Displays zur Unlesbarkeit.
  const stage = $("stage");
  const px = (stage ? stage.clientWidth : window.innerWidth) || 1200;
  return Math.round(Math.max(6, Math.min(18, px / 100)) * 10) / 10;
}

function params() {
  const p = {
    nfft: $("nfft").value,
    overlap: $("overlap").value,
    window: $("window").value,
    channels: $("channels").value,
    scale: $("scale").value,
    db_range: $("db_range").value,
    cmap: $("cmap").value,
    height: $("height").value,
    width: figureWidth(),
    theme: "dark",
    lang: window.LANG,
  };
  if ($("fmin").value) p.fmin = $("fmin").value;
  if ($("fmax").value) p.fmax = $("fmax").value;
  if (state.zoom) {
    if (state.zoom.start != null) p.start = state.zoom.start.toFixed(3);
    if (state.zoom.duration != null) p.duration = state.zoom.duration.toFixed(3);
    if (state.zoom.fmin != null) p.fmin = state.zoom.fmin.toFixed(0);
    if (state.zoom.fmax != null) p.fmax = state.zoom.fmax.toFixed(0);
  }
  return p;
}

const PRESETS = {
  lossy:     { nfft: 2048, overlap: 0.75, scale: "linear", db_range: 120, cmap: "magma", channels: "mix", fmin: "", fmax: "" },
  detail:    { nfft: 8192, overlap: 0.875, scale: "linear", db_range: 100, cmap: "inferno", channels: "mix" },
  vinyl:     { nfft: 8192, overlap: 0.75, scale: "log", db_range: 90, cmap: "viridis", channels: "mix", fmin: 10, fmax: 2000 },
  mastering: { nfft: 4096, overlap: 0.75, scale: "log", db_range: 100, cmap: "magma", channels: "side" },
  overview:  { nfft: 1024, overlap: 0.5, scale: "linear", db_range: 100, cmap: "magma", channels: "mix", fmin: "", fmax: "" },
};

function applyPreset(name) {
  const p = PRESETS[name];
  if (!p) return;
  for (const [k, v] of Object.entries(p)) {
    const el = $(k);
    if (el) el.value = v;
  }
  render();
}

/* --------------------------------------------------------- Dateibrowser */
async function loadConfig() {
  state.cfg = await jget("/api/config");
  const rootSel = $("root");
  rootSel.innerHTML = "";
  for (const r of state.cfg.roots) {
    const o = document.createElement("option");
    o.value = r.key; o.textContent = r.label;
    rootSel.appendChild(o);
  }
  $("window").innerHTML = state.cfg.windows
    .map((w) => `<option${w === "hann" ? " selected" : ""}>${w}</option>`).join("");
  $("cmap").innerHTML = state.cfg.cmaps
    .map((c) => `<option${c === "magma" ? " selected" : ""}>${c}</option>`).join("");
  const first = state.cfg.roots.find((r) => r.key !== "uploads") || state.cfg.roots[0];
  state.root = first ? first.key : "uploads";
  rootSel.value = state.root;
}

async function browse(path = "") {
  const list = $("listing");
  list.innerHTML = `<div class="hint">${esc(T("sidebar.loading"))}</div>`;
  let data;
  try {
    data = await jget(`/api/browse?root=${encodeURIComponent(state.root)}&path=${encodeURIComponent(path)}`);
  } catch (e) {
    list.innerHTML = `<div class="hint">${esc(T("scan.error", { msg: e.message }))}</div>`;
    return;
  }
  state.path = data.path;
  crumbs(data);

  const frag = document.createDocumentFragment();
  if (data.parent !== null && data.path) {
    frag.appendChild(row({ name: "..", path: data.parent }, "dir"));
  }
  data.dirs.forEach((d) => frag.appendChild(row(d, "dir")));
  data.files.forEach((f) => frag.appendChild(row(f, "file")));
  if (!data.dirs.length && !data.files.length) {
    const e = document.createElement("div");
    e.className = "hint";
    e.textContent = T("sidebar.empty");
    frag.appendChild(e);
  }
  list.innerHTML = "";
  list.appendChild(frag);
  // Markierungen verwerfen, die es nach dem Neuladen nicht mehr gibt
  const vorhanden = new Set(data.files.map((f) => f.path));
  [...auswahl].forEach((p) => { if (!vorhanden.has(p)) auswahl.delete(p); });
  auswahlLeiste();
  filterList();
  markSelection();
}

function crumbs(data) {
  const c = $("crumbs");
  c.innerHTML = "";
  const parts = data.path ? data.path.split("/") : [];
  const mk = (label, p) => {
    const a = document.createElement("a");
    a.textContent = label;
    a.onclick = () => browse(p);
    return a;
  };
  c.appendChild(mk(state.cfg.roots.find((r) => r.key === state.root).label, ""));
  let acc = "";
  parts.forEach((p) => {
    acc = acc ? acc + "/" + p : p;
    c.appendChild(document.createTextNode("/"));
    c.appendChild(mk(p, acc));
  });
}

function row(entry, kind) {
  const el = document.createElement("div");
  el.className = "item " + kind;
  el.dataset.path = entry.path;
  el.dataset.path = entry.path;
  el.dataset.kind = kind;
  const nm = document.createElement("div");
  nm.className = "nm";
  nm.textContent = entry.name;
  el.appendChild(nm);

  if (kind === "dir") {
    el.onclick = () => browse(entry.path);
  } else {
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = `${entry.ext} · ${fmtSize(entry.size)}`;
    el.appendChild(meta);

    const pick = document.createElement("div");
    pick.className = "pick";
    const bA = document.createElement("button");
    bA.textContent = "A";
    bA.onclick = (ev) => { ev.stopPropagation(); select("a", entry); };
    pick.appendChild(bA);
    if (state.compare) {
      const bB = document.createElement("button");
      bB.textContent = "B";
      bB.onclick = (ev) => { ev.stopPropagation(); select("b", entry); };
      pick.appendChild(bB);
    }
    if (state.root === "uploads") {
      const box = document.createElement("input");
      box.type = "checkbox";
      box.className = "upsel";
      box.checked = auswahl.has(entry.path);
      box.title = T("uploads.select");
      box.onclick = (ev) => {
        ev.stopPropagation();
        if (box.checked) auswahl.add(entry.path);
        else auswahl.delete(entry.path);
        auswahlLeiste();
      };
      el.prepend(box);

      const del = document.createElement("button");
      del.textContent = "✕";
      del.title = T("sidebar.deleteUpload");
      del.onclick = async (ev) => {
        ev.stopPropagation();
        if (!confirm(T("sidebar.confirmDelete", { name: entry.name }))) return;
        await fetch(`/api/upload?path=${encodeURIComponent(entry.path)}&lang=${window.LANG}`,
                    { method: "DELETE" });
        auswahl.delete(entry.path);
        browse(state.path);
      };
      pick.appendChild(del);
    }
    el.appendChild(pick);
    el.onclick = () => select(state.compare && state.a && !state.b ? "b" : "a", entry);
  }
  return el;
}

/* --------------------------------------------- Uploads auswählen/löschen */
const auswahl = new Set();          // Pfade markierter Uploads

function auswahlLeiste() {
  const alt = document.getElementById("uploadbar");
  if (alt) alt.remove();
  if (state.root !== "uploads") return;
  const dateien = [...document.querySelectorAll("#listing .item.file")];
  if (!dateien.length) return;

  const leiste = document.createElement("div");
  leiste.id = "uploadbar";
  leiste.className = "uploadbar";
  const anzahl = auswahl.size;
  leiste.innerHTML = `
    <label class="chk"><input type="checkbox" id="up-all"
      ${anzahl && anzahl === dateien.length ? "checked" : ""}>
      <span>${esc(T("uploads.selectAll"))}</span></label>
    <span class="spacer"></span>
    <span>${esc(T("uploads.selected", { n: anzahl }))}</span>
    <button class="ghost" id="up-del" ${anzahl ? "" : "disabled"}>
      ${esc(T("uploads.deleteSelected"))}</button>
    <button class="ghost" id="up-clear">${esc(T("uploads.clearAll"))}</button>`;
  $("listing").prepend(leiste);

  document.getElementById("up-all").onchange = (ev) => {
    auswahl.clear();
    if (ev.target.checked) {
      dateien.forEach((el) => auswahl.add(el.dataset.path));
    }
    document.querySelectorAll("#listing .upsel").forEach((c) => {
      c.checked = auswahl.has(c.closest(".item").dataset.path);
    });
    auswahlLeiste();
  };
  document.getElementById("up-del").onclick = () => loescheUploads([...auswahl]);
  document.getElementById("up-clear").onclick = () => loescheUploads(null);
}

async function loescheUploads(pfade) {
  const anzahl = pfade ? pfade.length : null;
  const frage = pfade
    ? T("uploads.confirmSelected", { n: anzahl })
    : T("uploads.confirmAll");
  if (!confirm(frage)) return;
  try {
    if (pfade) {
      const q = new URLSearchParams();
      pfade.forEach((p) => q.append("path", p));
      q.set("lang", window.LANG);
      await fetch("/api/upload?" + q, { method: "DELETE" });
    } else {
      await fetch("/api/uploads?lang=" + window.LANG, { method: "DELETE" });
    }
  } catch (e) {
    $("upstatus").textContent = T("msg.uploadFailed", { msg: e.message });
  }
  auswahl.clear();
  browse(state.path);
}

function filterList() {
  const q = $("filter").value.toLowerCase();
  document.querySelectorAll("#listing .item").forEach((el) => {
    el.style.display = !q || el.querySelector(".nm").textContent.toLowerCase().includes(q)
      ? "" : "none";
  });
}

function select(slot, entry) {
  state[slot] = { root: state.root, path: entry.path, name: entry.name };
  state.zoom = null;
  markSelection();
  render();
}

function markSelection() {
  document.querySelectorAll("#listing .item").forEach((el) => {
    el.classList.remove("sel-a", "sel-b");
    if (el.dataset.kind !== "file") return;
    if (state.a && state.a.root === state.root && state.a.path === el.dataset.path) el.classList.add("sel-a");
    if (state.b && state.b.root === state.root && state.b.path === el.dataset.path) el.classList.add("sel-b");
  });
  $("slot-a").querySelector("b").textContent = state.a ? state.a.name : "–";
  $("slot-b").querySelector("b").textContent = state.b ? state.b.name : "–";
}

/* ---------------------------------------------------------------- Upload */
async function upload(fileList) {
  const files = [...fileList];
  if (!files.length) return;
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f));
  $("upstatus").textContent = T("msg.uploading", { n: files.length });
  try {
    const r = await fetch("/api/upload?lang=" + window.LANG,
                          { method: "POST", body: fd });
    const res = await r.json();
    const msgs = [];
    if (res.saved && res.saved.length) msgs.push(T("msg.uploaded", { n: res.saved.length }));
    (res.errors || []).forEach((e) => msgs.push(`${e.name}: ${e.error}`));
    $("upstatus").textContent = msgs.join(" · ");
    if (res.saved && res.saved.length) {
      state.root = "uploads";
      $("root").value = "uploads";
      await browse("");
      const last = res.saved[res.saved.length - 1];
      select(state.compare && state.a && !state.b ? "b" : "a",
             { name: last.name, path: last.path });
    }
  } catch (e) {
    $("upstatus").textContent = T("msg.uploadFailed", { msg: e.message });
  }
}

/* -------------------------------------------------------------- Rendern */
function buildUrl(kind) {
  const q = new URLSearchParams(params());
  if (kind === "compare") {
    q.set("a_root", state.a.root); q.set("a", state.a.path);
    q.set("b_root", state.b.root); q.set("b", state.b.path);
    q.set("align", $("align").checked ? "1" : "0");
    q.set("diff", $("diff").checked ? "1" : "0");
    q.set("diff_range", $("diff_range").value);
    return "/api/compare.png?" + q;
  }
  q.set("root", state.a.root); q.set("path", state.a.path);
  return "/api/spectrogram.png?" + q;
}

let renderToken = 0;
async function render() {
  const compare = state.compare && state.a && state.b;
  if (!state.a) return;
  const token = ++renderToken;
  $("error").hidden = true;
  $("busy").hidden = false;
  $("render").disabled = true;

  const url = buildUrl(compare ? "compare" : "single");
  try {
    const r = await fetch(url);
    if (!r.ok) {
      let msg = r.statusText;
      try { msg = (await r.json()).detail || msg; } catch (e) {}
      throw new Error(msg);
    }
    const blob = await r.blob();
    if (token !== renderToken) return;
    state.boxes = JSON.parse(r.headers.get("X-Plot-Box") || "[]");
    if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
    state.objectUrl = URL.createObjectURL(blob);
    $("spec").src = state.objectUrl;
    $("dl").href = state.objectUrl;
    $("dl").download = (compare ? "vergleich_" : "") +
      (state.a.name.replace(/\.[^.]+$/, "")) + ".png";
    $("placeholder").hidden = true;
    $("viewer").hidden = false;
    state.view = state.boxes.length
      ? { t0: state.boxes[0].t0, t1: state.boxes[0].t1 } : null;
    stopAudio();
    updateZoomInfo();
    loadReport(compare);
  } catch (e) {
    if (token === renderToken) {
      $("error").hidden = false;
      $("error").textContent = T("msg.analysisFailed", { msg: e.message });
    }
  } finally {
    if (token === renderToken) {
      $("busy").hidden = true;
      $("render").disabled = false;
    }
  }
}

function updateZoomInfo() {
  const z = state.zoom;
  $("reset-zoom").hidden = !z;
  $("zoominfo").textContent = z
    ? T("msg.zoomRange", { from: fmtTime(z.start || 0),
                           to: fmtTime((z.start || 0) + (z.duration || 0)) })
      + (z.fmax ? ` · ${fmtHz(z.fmin || 0)}–${fmtHz(z.fmax)}` : "")
    : "";
}

/* ------------------------------------------------------- Zoom per Maus  */
function boxAt(fx, fy) {
  return state.boxes.find((b) => fx >= b.x0 && fx <= b.x1 && fy >= b.y0 && fy <= b.y1)
      || state.boxes[0];
}
const rowToFreq = (frac, b) => {
  const lo = b.scale === "log" ? Math.max(b.fmin, 20) : b.fmin;
  if (b.scale === "linear") return lo + (b.fmax - lo) * frac;
  if (b.scale === "log") return lo * Math.pow(b.fmax / lo, frac);
  const mel = (f) => 2595 * Math.log10(1 + f / 700);
  const m = mel(lo) + (mel(b.fmax) - mel(lo)) * frac;
  return 700 * (Math.pow(10, m / 2595) - 1);
};

function initZoom() {
  const wrap = $("imgwrap"), sel = $("sel"), cur = $("cursor");
  let drag = null;
  const rel = (ev) => {
    const r = wrap.getBoundingClientRect();
    return { x: (ev.clientX - r.left) / r.width, y: (ev.clientY - r.top) / r.height, r };
  };

  wrap.addEventListener("pointerdown", (ev) => {
    if (!state.boxes.length || ev.button !== 0) return;
    ev.preventDefault();          // sonst startet der Browser ein Bild-Drag
    const { x, y } = rel(ev);
    drag = { x0: x, y0: y, box: boxAt(x, y) };
    wrap.setPointerCapture(ev.pointerId);
    sel.hidden = false;
  });

  wrap.addEventListener("pointermove", (ev) => {
    const { x, y, r } = rel(ev);
    if (!drag) {
      if (!state.boxes.length) return;
      const b = boxAt(x, y);
      if (x >= b.x0 && x <= b.x1 && y >= b.y0 && y <= b.y1) {
        cur.style.display = "block";
        cur.style.left = x * r.width + "px";
        cur.style.top = b.y0 * r.height + "px";
        cur.style.height = (b.y1 - b.y0) * r.height + "px";
        const t = b.t0 + (b.t1 - b.t0) * (x - b.x0) / (b.x1 - b.x0);
        const f = rowToFreq(1 - (y - b.y0) / (b.y1 - b.y0), b);
        $("postime").textContent = `${fmtTime(t)} · ${fmtHz(Math.max(f, 0))}`;
      } else {
        cur.style.display = "none";
      }
      return;
    }
    const L = Math.min(drag.x0, x) * r.width, R = Math.max(drag.x0, x) * r.width;
    const T = Math.min(drag.y0, y) * r.height, B = Math.max(drag.y0, y) * r.height;
    Object.assign(sel.style, { left: L + "px", top: T + "px",
      width: (R - L) + "px", height: (B - T) + "px" });
  });

  wrap.addEventListener("pointerup", (ev) => {
    if (!drag) return;
    const d = drag;
    drag = null;
    sel.hidden = true;
    const { x, y } = rel(ev);
    const dx = Math.abs(x - d.x0), dy = Math.abs(y - d.y0);
    if (dx < 0.012 && dy < 0.012) return;          // Klick, kein Aufziehen

    const b = d.box;
    const fx = (v) => (Math.min(Math.max(v, b.x0), b.x1) - b.x0) / (b.x1 - b.x0);
    const fy = (v) => 1 - (Math.min(Math.max(v, b.y0), b.y1) - b.y0) / (b.y1 - b.y0);
    const z = state.zoom ? { ...state.zoom } : {};
    if (dx >= 0.012) {
      const ta = b.t0 + (b.t1 - b.t0) * fx(d.x0);
      const tb = b.t0 + (b.t1 - b.t0) * fx(x);
      z.start = Math.min(ta, tb);
      z.duration = Math.max(0.05, Math.abs(tb - ta));
    }
    if (dy >= 0.012) {
      const fa = rowToFreq(fy(d.y0), b), fb = rowToFreq(fy(y), b);
      z.fmin = Math.max(0, Math.min(fa, fb));
      z.fmax = Math.max(fa, fb);
    }
    state.zoom = z;
    render();
  });

  wrap.addEventListener("pointercancel", () => { drag = null; sel.hidden = true; });
  wrap.addEventListener("pointerleave", () => { cur.style.display = "none"; });
  wrap.addEventListener("dblclick", () => { if (state.zoom) { state.zoom = null; render(); } });
  wrap.classList.add("crosshair");
}

/* ------------------------------------------------------------ Anhören   */
const audio = $("audio");
function stopAudio() {
  audio.pause();
  audio.removeAttribute("src");
  $("playhead").hidden = true;
  $("play").textContent = T("player.play");
}

function playSegment() {
  if (!state.a || !state.boxes.length) return;
  if (!audio.paused) { audio.pause(); $("play").textContent = T("player.resume"); return; }
  if (!audio.src) {
    const b = state.boxes[0];
    const q = new URLSearchParams({ root: state.a.root, path: state.a.path,
      start: (b.t0 || 0).toFixed(3), duration: Math.max(b.t1 - b.t0, 0.2).toFixed(3) });
    audio.src = "/api/audio?" + q;
  }
  audio.play().then(() => { $("play").textContent = T("player.pause"); })
    .catch((e) => {
      $("error").hidden = false;
      $("error").textContent = T("msg.playback", { msg: e.message });
    });
}

audio.addEventListener("timeupdate", () => {
  const b = state.boxes[0];
  if (!b) return;
  const span = Math.max(b.t1 - b.t0, 1e-6);
  const frac = Math.min(audio.currentTime / span, 1);
  const wrap = $("imgwrap").getBoundingClientRect();
  const ph = $("playhead");
  ph.hidden = false;
  ph.style.left = (b.x0 + (b.x1 - b.x0) * frac) * wrap.width + "px";
  ph.style.top = b.y0 * wrap.height + "px";
  const last = state.boxes[state.boxes.length - 1];
  ph.style.height = (last.y1 - b.y0) * wrap.height + "px";
  $("postime").textContent = fmtTime(b.t0 + audio.currentTime * 1);
});
audio.addEventListener("ended", () => { $("play").textContent = T("player.play"); });

/* ------------------------------------------------------------- Bericht  */
async function loadReport(compare) {
  const rep = $("report");
  rep.innerHTML = `<div class="card"><h3>${esc(T("card.file"))}</h3><div class="hint">${esc(T("card.measuring"))}</div></div>`;
  try {
    if (compare) {
      const q = new URLSearchParams(params());
      q.set("a_root", state.a.root); q.set("a", state.a.path);
      q.set("b_root", state.b.root); q.set("b", state.b.path);
      q.set("align", $("align").checked ? "1" : "0");
      const st = await jget("/api/compare.json?" + q);
      rep.innerHTML = "";
      rep.appendChild(cmpCard("A", st.a));
      rep.appendChild(cmpCard("B", st.b));
      rep.appendChild(diffCard(st));
    } else {
      const q = new URLSearchParams(params());
      q.set("root", state.a.root); q.set("path", state.a.path);
      const r = await jget("/api/report?" + q);
      rep.innerHTML = "";
      rep.appendChild(fileCard(r));
      rep.appendChild(loudCard(r));
      rep.appendChild(bandCard(r));
      const lc = lowCard(r);
      if (lc) rep.appendChild(lc);
      const tc = toneCard(r);
      if (tc) rep.appendChild(tc);
    }
  } catch (e) {
    rep.innerHTML = `<div class="card"><h3>${esc(T("card.error"))}</h3><div class="hint">${esc(e.message)}</div></div>`;
  }
}

function card(title, kv, extra) {
  const c = document.createElement("div");
  c.className = "card";
  c.innerHTML = `<h3>${esc(title)}</h3><div class="kv">` +
    kv.filter(Boolean).map(([k, v]) => `<span>${esc(k)}</span><span>${esc(v)}</span>`).join("") + "</div>";
  if (extra) c.insertAdjacentHTML("beforeend", extra);
  return c;
}

const verdictHtml = (v) => v
  ? `<div class="verdict ${esc(v.level)}">${esc(v.text)}</div>` : "";

const patternName = (p) => T("pattern." + p);

function fileCard(r) {
  const f = r.file, b = r.band || {};
  return card(T("card.file"), [
    [T("f.name"), f.name],
    [T("f.codec"), f.codec_long || f.codec],
    [T("f.rate"), `${(f.sample_rate / 1000).toFixed(1)} kHz`],
    [T("f.channels"), f.channels + (f.channel_layout ? ` (${f.channel_layout})` : "")],
    f.bits && [T("f.depth"), f.bits + " bit"],
    f.bit_rate && [T("f.bitrate"), Math.round(f.bit_rate / 1000) + " kbit/s"],
    f.duration && [T("f.duration"), fmtTime(f.duration)],
    f.size && [T("f.size"), fmtSize(f.size)],
    [T("f.bandwidth"), fmtHz(b.signal_bandwidth_hz ?? r.cutoff_hz)],
    b.edge_hz != null && [T("f.edge"), `${fmtHz(b.edge_hz)} (−${b.edge_drop_db} dB)`],
    b.edge_hz != null && [T("f.sections"),
      T("of", { a: b.blocks_with_edge, b: b.blocks })],
    b.pattern && [T("f.pattern"), patternName(b.pattern)],
  ], verdictHtml(r.verdict));
}

function loudCard(r) {
  const l = r.loudness || {}, s = r.stereo || {};
  const kv = [
    l.lufs_integrated != null && [T("f.loudness"), l.lufs_integrated.toFixed(1) + " LUFS"],
    l.lra != null && [T("f.lra"), l.lra.toFixed(1) + " LU"],
    l.true_peak_dbfs != null && [T("f.truepeak"), l.true_peak_dbfs.toFixed(2) + " dBTP"],
    l.peak_dbfs != null && [T("f.peak"), l.peak_dbfs.toFixed(2) + " dBFS"],
    l.rms_dbfs != null && [T("f.rms"), l.rms_dbfs.toFixed(2) + " dBFS"],
    l.crest_db != null && [T("f.crest"), l.crest_db.toFixed(1) + " dB"],
    l.noise_floor_dbfs != null && [T("f.noisefloor"), l.noise_floor_dbfs.toFixed(1) + " dBFS"],
    l.bit_depth_effective != null && [T("f.realdepth"),
      T("of", { a: l.bit_depth_effective,
                b: (l.bit_depth_container ?? l.bit_depth_effective) + " bit" })],
    l.bit_depth_used != null && [T("f.useddepth"), l.bit_depth_used + " bit"],
    l.abs_peak_count != null && [T("f.peaksamples"), l.abs_peak_count.toFixed(0)],
    l.flat_factor != null && [T("f.flat"), l.flat_factor.toFixed(2)],
    l.dc_offset != null && [T("f.dc"), l.dc_offset.toFixed(5)],
    s.correlation != null && [T("f.correlation"), s.correlation.toFixed(3)],
    s.side_ratio_db != null && [T("f.side"), s.side_ratio_db.toFixed(1) + " dB"],
  ];
  let extra = "";
  if (l.bit_depth_effective != null && l.bit_depth_container != null
      && l.bit_depth_container - l.bit_depth_effective >= 2)
    extra += `<div class="verdict warn">${esc(T("warn.fakeDepth", {
      used: l.bit_depth_effective, container: l.bit_depth_container }))}</div>`;
  if (s.identical_channels)
    extra += `<div class="verdict warn">${esc(T("warn.mono"))}</div>`;
  else if (s.correlation != null && s.correlation < -0.4)
    extra += `<div class="verdict warn">${esc(T("warn.negativeCorr"))}</div>`;
  // Übersteuerung beurteilt der Analysekern, damit Oberfläche, CLI und API
  // dieselbe Aussage treffen
  if (r.clipping) extra += verdictHtml(r.clipping);
  if (r.dynamics) extra += verdictHtml(r.dynamics);
  return card(T("card.levels"), kv, extra);
}

function lowCard(r) {
  const l = r.lowfreq;
  if (!l) return null;
  const kv = [
    [T("f.below20"), `${l.subsonic_db.toFixed(0)} dBFS (${l.subsonic_rel_db.toFixed(0)} dB)`],
    [T("f.bass"), `${l.bass_db.toFixed(0)} dBFS`],
  ];
  (l.hum || []).slice(0, 4).forEach((h) =>
    kv.push([`${h.hz.toFixed(0)} Hz`,
             `${h.level_db.toFixed(0)} dBFS (+${h.prominence_db.toFixed(0)} dB)`]));
  return card(T("card.lowfreq"), kv, verdictHtml(l.verdict));
}

function toneCard(r) {
  const tones = r.tones || [];
  if (!tones.length) return null;
  const kv = tones.map((x) => [fmtHz(x.hz), T("tones.detail", {
    prom: x.prominence_db.toFixed(0), level: x.level_db.toFixed(0) })]);
  return card(T("card.tones"), kv,
    `<div class="verdict warn">${esc(T("warn.tones"))}</div>`);
}

function bandCard(r) {
  const bars = (r.bands || []).map((b) => {
    const label = esc(`${b.lo >= 1000 ? (b.lo / 1000) + "k" : b.lo}–${b.hi >= 1000 ? (b.hi / 1000).toFixed(0) + "k" : b.hi}`);
    const pct = (b.share * 100);
    return `<div class="bar"><span>${label} Hz</span><i style="width:${Math.max(pct, 0.4)}%"></i>
            <span>${pct < 0.1 ? "&lt;" + num(0.1) : num(pct)} %</span></div>`;
  }).join("");
  return card(T("card.energy"), [[T("f.analysed"), fmtTime(r.analysed_duration)],
    [T("f.columns"), r.columns]], `<div class="bars">${bars}</div>`);
}

function cmpCard(tag, s) {
  return card(`${tag}: ${s.name}`, [
    [T("f.codec"), s.codec],
    [T("f.rate"), `${(s.sample_rate / 1000).toFixed(1)} kHz`],
    [T("f.channels"), s.channels],
    s.bit_rate && [T("f.bitrate"), Math.round(s.bit_rate / 1000) + " kbit/s"],
    [T("f.edge"), fmtHz((s.band && s.band.edge_hz) || s.cutoff)],
    s.band && s.band.pattern && [T("f.pattern"), patternName(s.band.pattern)],
  ], verdictHtml(s.verdict));
}

function diffCard(st) {
  const d = st.diff || {};
  let hint = "";
  if (d.p90_abs_db != null) {
    const key = d.p90_abs_db < 2 ? "diff.identical"
      : d.p90_abs_db < 8 ? "diff.moderate"
      : d.p90_abs_db < 15 ? "diff.strong" : "diff.veryStrong";
    const stufe = (key === "diff.identical" || key === "diff.moderate") ? "ok" : "warn";
    hint = `<div class="verdict ${stufe}">${esc(T(key))}</div>`;
  }
  return card(T("card.diff"), [
    [T("f.timeoffset"), (st.offset_s >= 0 ? "+" : "") + st.offset_s.toFixed(3) + " s"],
    d.band_hz && [T("f.band"), fmtHz(d.band_hz)],
    d.median_db != null && [T("f.median"), d.median_db.toFixed(2) + " dB"],
    d.mean_abs_db != null && [T("f.meanabs"), d.mean_abs_db.toFixed(2) + " dB"],
    d.p90_abs_db != null && [T("f.p90"), d.p90_abs_db.toFixed(2) + " dB"],
    d.max_abs_db != null && [T("f.maxabs"), d.max_abs_db.toFixed(2) + " dB"],
  ], hint);
}

/* ------------------------------------------------------- Sammlungs-Scan */
let scanData = null;
let scanSort = { key: "cutoff_hz", dir: 1 };

let scanQuelle = null;

function scanFolder(opts = {}) {
  const out = $("scanout");
  out.hidden = false;
  if (scanQuelle) { scanQuelle.close(); scanQuelle = null; }

  const q = new URLSearchParams({ root: state.root, path: state.path,
                                  recursive: "1", lang: window.LANG });
  if (opts.refresh) q.set("refresh", "1");

  // Ereignisstrom statt einer langen Anfrage: bei tausenden Dateien wäre die
  // Verbindung längst abgelaufen, bevor das erste Ergebnis da ist.
  scanData = { root: state.root, path: state.path, count: 0, warnings: 0,
               computed: 0, from_index: 0, index: false, truncated: false,
               files: [], laufend: true, total: 0, done: 0 };
  drawScan();

  const es = new EventSource("/api/scan/stream?" + q);
  scanQuelle = es;

  es.addEventListener("start", (ev) => {
    const d = JSON.parse(ev.data);
    Object.assign(scanData, { total: d.total, index: d.index,
                              truncated: d.truncated });
    drawScan();
  });

  let letzteZeichnung = 0;
  es.addEventListener("file", (ev) => {
    const d = JSON.parse(ev.data);
    scanData.files.push(d.file);
    scanData.count = d.done;
    scanData.done = d.done;
    if (!d.file.cached) scanData.computed += 1; else scanData.from_index += 1;
    if ((d.file.verdict || {}).level === "warn") scanData.warnings += 1;
    // nicht bei jeder Datei neu zeichnen, sonst flackert es bei großen Ordnern
    const jetzt = Date.now();
    if (jetzt - letzteZeichnung > 400 || d.done === d.total) {
      letzteZeichnung = jetzt;
      drawScan();
    }
  });

  es.addEventListener("done", (ev) => {
    Object.assign(scanData, JSON.parse(ev.data), { laufend: false });
    es.close();
    scanQuelle = null;
    drawScan();
  });

  es.onerror = () => {
    es.close();
    scanQuelle = null;
    if (scanData) {
      scanData.laufend = false;
      scanData.fehler = true;
      drawScan();
    }
  };
}

function stopScan() {
  if (scanQuelle) { scanQuelle.close(); scanQuelle = null; }
  if (scanData) { scanData.laufend = false; drawScan(); }
}

function drawScan() {
  const d = scanData;
  if (!d) return;
  const cols = [
    ["name", T("scan.col.name"), (f) => f.name, "file"],
    ["codec", T("scan.col.codec"), (f) => f.codec || "–"],
    ["sample_rate", T("scan.col.rate"), (f) => f.sample_rate ? (f.sample_rate / 1000).toFixed(1) + " kHz" : "–", "num"],
    ["channels", T("scan.col.channels"), (f) => f.channels ?? "–", "num"],
    ["bit_rate", T("scan.col.bitrate"), (f) => f.bit_rate ? Math.round(f.bit_rate / 1000) + "k" : "–", "num"],
    ["duration", T("scan.col.duration"), (f) => f.duration ? fmtTime(f.duration) : "–", "num"],
    ["cutoff_hz", T("scan.col.edge"), (f) => fmtHz(f.cutoff_hz), "num"],
    ["pattern", T("scan.col.pattern"), (f) => f.pattern ? patternName(f.pattern) : "–"],
    ["verdict", T("scan.col.verdict"), (f) => f.error ? T("scan.error", { msg: f.error }) : (f.verdict ? f.verdict.text : "–")],
  ];
  const rows = [...d.files].sort((a, b) => {
    const k = scanSort.key;
    const va = k === "verdict" ? ((a.verdict || {}).level || "z") : (a[k] ?? -1);
    const vb = k === "verdict" ? ((b.verdict || {}).level || "z") : (b[k] ?? -1);
    return (va > vb ? 1 : va < vb ? -1 : 0) * scanSort.dir;
  });

  const head = cols.map(([k, label]) =>
    `<th data-k="${esc(k)}">${esc(label)}${scanSort.key === k ? (scanSort.dir > 0 ? " ▲" : " ▼") : ""}</th>`).join("");
  const body = rows.map((f) => {
    const cls = f.error ? "err" : (f.verdict && f.verdict.level === "warn" ? "warn" : "");
    const tds = cols.map(([k, l, get, td]) =>
      `<td class="${td || ""}" ${td === "file" ? `data-path="${esc(encodeURIComponent(f.path))}"` : ""}>${esc(get(f))}</td>`).join("");
    return `<tr class="${cls}">${tds}</tr>`;
  }).join("");

  const fortschritt = d.laufend
    ? `<span class="progress"><i style="width:${d.total ? (d.done / d.total * 100).toFixed(1) : 0}%"></i></span>
       <span>${esc(T("scan.progress", { done: d.done, total: d.total }))}</span>
       <button class="ghost" id="scan-stop">${esc(T("scan.stop"))}</button>`
    : (d.fehler ? `<span>${esc(T("scan.aborted"))}</span>` : "");

  $("scanout").innerHTML = `
    <div class="scanhead">
      <b>${esc(T("scan.checked", { n: d.count }))}</b>
      ${fortschritt}
      <span>${esc(T("scan.flagged", { n: d.warnings }))}</span>
      ${d.index ? `<span>${esc(T("scan.index", { computed: d.computed, cached: d.from_index }))}</span>` : ""}
      ${d.truncated ? `<span>${esc(T("scan.truncated"))}</span>` : ""}
      <span class="spacer"></span>
      <button class="ghost" id="scan-refresh">${esc(T("scan.refresh"))}</button>
      <button class="ghost" id="scan-csv">${esc(T("scan.csv"))}</button>
      <button class="ghost" id="scan-close">${esc(T("scan.close"))}</button>
    </div>
    <table class="scan"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;

  $("scanout").querySelectorAll("th").forEach((th) => th.onclick = () => {
    const k = th.dataset.k;
    scanSort = { key: k, dir: scanSort.key === k ? -scanSort.dir : 1 };
    drawScan();
  });
  $("scanout").querySelectorAll("td.file").forEach((td) => td.onclick = () => {
    const path = decodeURIComponent(td.dataset.path);
    select(state.compare && state.a && !state.b ? "b" : "a",
           { name: path.split("/").pop(), path });
  });
  $("scan-close").onclick = () => { stopScan(); $("scanout").hidden = true; };
  $("scan-refresh").onclick = () => scanFolder({ refresh: true });
  const stopBtn = document.getElementById("scan-stop");
  if (stopBtn) stopBtn.onclick = stopScan;
  $("scan-csv").onclick = () => {
    const head2 = ["name", "path", "codec", "rate", "channels", "bitrate",
                   "duration", "edge", "pattern", "verdict", "note"]
      .map((k) => T("scan.col." + k, {}) || k);
    const csvq = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const lines = [head2.join(";")].concat(rows.map((f) => [
      f.name, f.path, f.codec, f.sample_rate, f.channels, f.bit_rate,
      f.duration != null ? f.duration.toFixed(1) : "", f.cutoff_hz,
      f.pattern ? patternName(f.pattern) : "",
      (f.verdict || {}).level || (f.error ? "error" : ""),
      f.error || (f.verdict || {}).text || "",
    ].map(csvq).join(";")));
    const url = URL.createObjectURL(new Blob(["\ufeff" + lines.join("\r\n")],
      { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url; a.download = "spectro-scan.csv"; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  };
}

/* ------------------------------------------------------------ Nullprobe */
async function runNullTest() {
  if (!state.a || !state.b) return;
  const btn = $("nulltest");
  btn.disabled = true;
  btn.textContent = T("clicks.searching");
  const rep = $("report");
  try {
    const q = new URLSearchParams(params());
    q.set("a_root", state.a.root); q.set("a", state.a.path);
    q.set("b_root", state.b.root); q.set("b", state.b.path);
    const n = await jget("/api/nulltest?" + q);
    const old = document.getElementById("nullcard");
    if (old) old.remove();
    const c = card(T("card.nulltest"), [
      [T("f.nulldepth"), n.residual_db.toFixed(2) + " dB"],
      [T("f.peakRes"), n.residual_peak_db.toFixed(2) + " dBFS"],
      [T("f.correlation"), n.correlation.toFixed(4)],
      [T("f.offset"), n.offset_ms.toFixed(2) + " ms"],
      [T("f.gain"), (n.gain_db >= 0 ? "+" : "") + n.gain_db.toFixed(2) + " dB"],
      [T("f.analysed"), fmtTime(n.analysed_seconds)],
    ], verdictHtml(n.verdict));
    c.id = "nullcard";
    rep.appendChild(c);
  } catch (e) {
    const c = card(T("card.nulltest"), [[T("card.error"), e.message]]);
    c.id = "nullcard";
    rep.appendChild(c);
  } finally {
    btn.disabled = false;
    btn.textContent = T("ctl.nulltest");
  }
}

/* --------------------------------------------------------------- Residual */
async function makeResidual() {
  if (!state.a || !state.b) return;
  const btn = $("residual");
  btn.disabled = true;
  btn.textContent = T("residual.calculating");
  try {
    const q = new URLSearchParams(params());
    q.set("a_root", state.a.root); q.set("a", state.a.path);
    q.set("b_root", state.b.root); q.set("b", state.b.path);
    const r = await jget("/api/residual.json?" + q);
    const old = document.getElementById("rescard");
    if (old) old.remove();
    const c = card(T("card.residual"), [
      [T("f.level"), `${r.residual_db.toFixed(1)} dB`],
      [T("f.peakRes"), `${r.residual_peak_db.toFixed(1)} dBFS`],
      [T("f.crest"), `${r.crest_db.toFixed(0)} dB (${r.source_crest_db.toFixed(0)} dB)`],
      r.quiet_rel_db != null && [T("f.quiet"), `${r.quiet_rel_db.toFixed(1)} dB`],
      r.loud_rel_db != null && [T("f.loud"), `${r.loud_rel_db.toFixed(1)} dB`],
      r.shape_correlation != null && [T("f.shape"), r.shape_correlation.toFixed(2)],
      [T("f.offset"), `${r.offset_ms.toFixed(2)} ms`],
      [T("f.duration"), fmtTime(r.seconds)],
    ], verdictHtml(r.verdict) +
      `<div class="events"><audio controls preload="none" style="width:100%;margin-top:8px"
         src="/api/residual?${q}"></audio></div>
       <div class="events"><a class="ghost" download href="/api/residual?${q}">${esc(T("residual.save"))}</a></div>`);
    c.id = "rescard";
    $("report").appendChild(c);
  } catch (e) {
    const c = card(T("card.residual"), [[T("card.error"), e.message]]);
    c.id = "rescard";
    $("report").appendChild(c);
  } finally {
    btn.disabled = false;
    btn.textContent = T("ctl.residual");
  }
}

/* -------------------------------------------------------- Störungssuche */
async function findClicks() {
  if (!state.a) return;
  const btn = $("clicks");
  btn.disabled = true;
  btn.textContent = T("clicks.searching");
  try {
    const q = new URLSearchParams(params());
    q.set("root", state.a.root);
    q.set("path", state.a.path);
    const r = await jget("/api/clicks?" + q);
    const old = document.getElementById("clickcard");
    if (old) old.remove();
    const c = card(T("card.impulses"), [
      [T("f.found"), r.count],
      [T("f.perMinute"), r.per_minute],
      [T("f.strong"), r.strong_count],
      [T("f.analysed"), fmtTime(r.analysed_seconds)],
    ], verdictHtml(r.verdict) + (r.events.length
      ? '<div class="events" id="events"></div>' : ""));
    c.id = "clickcard";
    $("report").appendChild(c);

    // Zeitmarken anklickbar: springt an die Stelle und zoomt hinein
    const box = document.getElementById("events");
    if (box) {
      r.events.slice(0, 60).forEach((e) => {
        const b = document.createElement("button");
        b.textContent = `${fmtTime(e.t)} · ${e.db.toFixed(0)} dB`;
        if (e.db >= 25) b.className = "strong";
        b.title = T("clicks.hint", { ms: e.ms });
        b.onclick = () => {
          state.zoom = { start: Math.max(0, e.t - 0.25), duration: 0.5 };
          render();
        };
        box.appendChild(b);
      });
    }
  } catch (e) {
    const c = card(T("card.impulses"), [[T("card.error"), e.message]]);
    c.id = "clickcard";
    $("report").appendChild(c);
  } finally {
    btn.disabled = false;
    btn.textContent = T("ctl.clicks");
  }
}

/* ---------------------------------------------------------- Gleichlauf */
async function measureWow() {
  if (!state.a) return;
  const btn = $("wow");
  btn.disabled = true;
  btn.textContent = T("clicks.searching");
  try {
    const q = new URLSearchParams(params());
    q.set("root", state.a.root);
    q.set("path", state.a.path);
    const r = await jget("/api/wowflutter?" + q);
    const old = document.getElementById("wowcard");
    if (old) old.remove();
    const c = card(T("card.wow"), [
      [T("f.carrier"), `${r.carrier_hz.toFixed(2)} Hz`],
      r.nominal_hz != null && [T("f.nominal"), `${r.nominal_hz.toFixed(0)} Hz`],
      r.speed_deviation_pct != null
        && [T("f.speed"), `${r.speed_deviation_pct.toFixed(2)} %`],
      [T("f.wow"), `${r.wow_pct.toFixed(3)} %`],
      [T("f.flutter"), `${r.flutter_pct.toFixed(3)} %`],
      [T("f.modulation"), `${r.dominant_mod_hz.toFixed(2)} Hz`],
      [T("f.analysed"), fmtTime(r.analysed_seconds)],
    ], verdictHtml(r.verdict));
    c.id = "wowcard";
    $("report").appendChild(c);
  } catch (e) {
    const c = card(T("card.wow"), [[T("card.error"), e.message]]);
    c.id = "wowcard";
    $("report").appendChild(c);
  } finally {
    btn.disabled = false;
    btn.textContent = T("ctl.wow");
  }
}

/* ------------------------------------------------- Frequenzgang/Trennung */
async function measureSweep() {
  if (!state.a) return;
  const btn = $("sweep");
  btn.disabled = true;
  btn.textContent = T("clicks.searching");
  try {
    const q = new URLSearchParams(params());
    q.set("root", state.a.root);
    q.set("path", state.a.path);
    const r = await jget("/api/sweep?" + q);
    const old = document.getElementById("sweepcard");
    if (old) old.remove();
    const kv = [[T("f.steps"), r.steps.length]];
    if (r.channel_separation_db != null)
      kv.push([T("f.separation"),
               `${r.channel_separation_db.toFixed(0)} dB (min ${r.channel_separation_min_db.toFixed(0)})`]);
    let balken = "";
    for (const [kanal, kurve] of Object.entries(r.response || {})) {
      const zeilen = kurve.map((k) => {
        const breite = Math.max(2, 50 + k.db * 3);   // 0 dB in der Mitte
        return `<div class="bar"><span>${esc(fmtHz(k.hz))}</span>
                <i style="width:${Math.min(100, breite)}%"></i>
                <span>${k.db >= 0 ? "+" : ""}${num(k.db)} dB</span></div>`;
      }).join("");
      balken += `<h3 style="margin-top:10px">${esc(T("f.channel"))} ${esc(kanal)}</h3>
                 <div class="bars">${zeilen}</div>`;
    }
    const c = card(T("card.sweep"), kv, verdictHtml(r.verdict) + balken);
    c.id = "sweepcard";
    c.classList.add("wide");
    $("report").appendChild(c);
  } catch (e) {
    const c = card(T("card.sweep"), [[T("card.error"), e.message]]);
    c.id = "sweepcard";
    $("report").appendChild(c);
  } finally {
    btn.disabled = false;
    btn.textContent = T("ctl.sweep");
  }
}

/* ------------------------------------------------------------ Permalink */
function writeHash() {
  const o = { ...params(), mode: state.compare ? "cmp" : "one", lang: window.LANG };
  if (state.a) { o.ar = state.a.root; o.ap = state.a.path; }
  if (state.b) { o.br = state.b.root; o.bp = state.b.path; }
  location.hash = new URLSearchParams(o).toString();
}

async function readHash() {
  if (!location.hash.length) return false;
  const q = new URLSearchParams(location.hash.slice(1));
  ["nfft", "overlap", "window", "channels", "scale", "db_range", "cmap", "height",
   "fmin", "fmax"].forEach((k) => { if (q.get(k) && $(k)) $(k).value = q.get(k); });
  if (q.get("mode") === "cmp") setMode(true);
  const qs = parseFloat(q.get("start")), qd = parseFloat(q.get("duration"));
  if (Number.isFinite(qs)) {
    state.zoom = { start: qs };
    if (Number.isFinite(qd) && qd > 0) state.zoom.duration = qd;
  }
  if (q.get("ap")) state.a = { root: q.get("ar"), path: q.get("ap"), name: q.get("ap").split("/").pop() };
  if (q.get("bp")) state.b = { root: q.get("br"), path: q.get("bp"), name: q.get("bp").split("/").pop() };
  markSelection();
  if (state.a) { await render(); return true; }
  return false;
}

/* ----------------------------------------------------------------- Init */
function setMode(compare) {
  state.compare = compare;
  document.body.classList.toggle("compare", compare);
  $("mode-single").classList.toggle("active", !compare);
  $("mode-compare").classList.toggle("active", compare);
  browse(state.path);
}

function initEvents() {
  $("lang").onchange = (e) => switchLanguage(e.target.value);
  $("root").onchange = () => { state.root = $("root").value; browse(""); };
  $("reload").onclick = () => browse(state.path);
  $("scan").onclick = scanFolder;
  $("nulltest").onclick = runNullTest;
  $("clicks").onclick = findClicks;
  $("wow").onclick = measureWow;
  $("sweep").onclick = measureSweep;
  $("residual").onclick = makeResidual;
  $("filter").oninput = filterList;
  $("mode-single").onclick = () => setMode(false);
  $("mode-compare").onclick = () => setMode(true);
  $("swap").onclick = () => {
    if (!state.a || !state.b) return;      // sonst bliebe ein leerer Slot zurück
    [state.a, state.b] = [state.b, state.a];
    state.zoom = null;
    markSelection();
    render();
  };
  $("render").onclick = () => render();
  $("preset").onchange = (e) => applyPreset(e.target.value);
  $("reset-zoom").onclick = () => { state.zoom = null; render(); };
  $("play").onclick = playSegment;
  $("permalink").onclick = async () => {
    writeHash();
    try {
      await navigator.clipboard.writeText(location.href);
      $("permalink").textContent = T("player.linkCopied");
    } catch (e) {
      $("permalink").textContent = T("player.linkFallback");
    }
    setTimeout(() => { $("permalink").textContent = T("player.link"); }, 2000);
  };
  ["nfft", "overlap", "window", "channels", "scale", "db_range", "cmap", "height",
   "align", "diff", "diff_range"].forEach((id) => {
    $(id).addEventListener("change", () => state.a && render());
  });
  ["fmin", "fmax"].forEach((id) => $(id).addEventListener("change", () => {
    if (state.zoom) { state.zoom.fmin = state.zoom.fmax = null; }
    state.a && render();
  }));

  const drop = $("drop");
  // "pick" entsteht erst beim Einsetzen der Texte, deshalb delegiert
  drop.addEventListener("click", (e) => {
    if (e.target.id === "pick") { e.preventDefault(); $("file-input").click(); }
  });
  $("file-input").onchange = (e) => upload(e.target.files);
  ["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => {
    e.preventDefault(); drop.classList.add("over");
  }));
  ["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => {
    e.preventDefault(); drop.classList.remove("over");
  }));
  drop.addEventListener("drop", (e) => upload(e.dataTransfer.files));
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
    if (e.key === " ") { e.preventDefault(); playSegment(); }
    if (e.key === "Escape" && state.zoom) { state.zoom = null; render(); }
    if (e.key === "Enter") render();
  });
  window.addEventListener("resize", () => { $("playhead").hidden = true; });
}

(async function main() {
  applyStaticTexts();
  await loadConfig();
  initEvents();
  initZoom();
  const restored = await readHash();
  await browse("");
  if (restored) markSelection();
})();
