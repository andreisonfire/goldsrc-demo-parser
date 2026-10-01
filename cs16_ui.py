#!/usr/bin/env python3
"""
CS 1.6 demo killfeed — desktop application.

Double-click cs16_ui.exe (or run this .py) and a native app window opens
with a drag-and-drop zone. Drop one or more .dem files, get a CSV back
formatted exactly like the user-provided template.

Everything runs locally. No data ever leaves your machine.

v2.1 rendered inside a native Windows window via pywebview (uses the
system's WebView2 runtime). The UI, the parser, and all selection rules
are identical to v1.3 — only the delivery mechanism changed.
"""
import base64
import json
import subprocess
import sys
import time
import traceback
from pathlib import Path

# Allow imports whether run as .py, frozen .exe, or from another dir
_here = Path(__file__).resolve().parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

import webview  # pywebview — pip install pywebview

from cs16_killfeed import parse_demo_full, build_csv_rows

MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB per file — matches v1.3 HTTP limit

# Single source of truth for the user-visible product version. Bump this
# string when shipping a new release; it appears in the window title bar
# and in the page header. We deliberately do NOT compute it from git tags
# or anywhere else — keep one literal that's grep-able.
VERSION = "2.1"


# ---------------------------------------------------------------------------
# HTML (inlined so the .exe is a single self-contained file)
# ---------------------------------------------------------------------------
INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>GSDP __VERSION__</title>
<style>
  :root {
    --bg:     #0d0f12;
    --panel:  #151a1f;
    --line:   #242a31;
    --ink:    #e7ecef;
    --muted:  #8b96a0;
    --accent: #ff7a1a;
    --good:   #4cd4a4;
    --warn:   #f0c674;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 2rem;
    background: var(--bg); color: var(--ink);
    font-family: 'Inter', -apple-system, 'Segoe UI', system-ui, sans-serif;
    font-size: 14px;
  }
  main {
    max-width: 1400px;
    margin: 0 auto;
  }
  h1 {
    font-size: 1.4rem; font-weight: 600; margin: 0 0 .25rem;
    letter-spacing: .02em;
  }
  .sub {
    color: var(--muted); margin-bottom: 2rem; font-size: .9rem;
  }
  .drop {
    display: block;
    width: 100%;
    border: 2px dashed var(--line);
    border-radius: 10px;
    padding: 2.5rem 2rem; text-align: center;
    background: var(--panel);
    transition: border-color .15s, background .15s;
    cursor: pointer;
  }
  .drop:hover, .drop.over {
    border-color: var(--accent);
    background: #181d22;
  }
  .drop p { margin: 0; }
  .drop .hint { color: var(--muted); font-size: .85rem; margin-top: .5rem; }
  input[type=file] { display: none; }
  .actions {
    display: flex; gap: .75rem; margin-top: 1rem;
    flex-wrap: wrap; align-items: center;
  }
  button {
    background: var(--accent); color: #0d0f12;
    border: 0; padding: .65rem 1.2rem;
    border-radius: 6px; cursor: pointer;
    font-weight: 600; font-size: .9rem;
    transition: filter .1s;
  }
  button:hover { filter: brightness(1.1); }
  button:disabled { opacity: .4; cursor: not-allowed; }
  button.secondary {
    background: transparent; color: var(--ink);
    border: 1px solid var(--line);
  }
  .export-wrap {
    position: relative;
    display: inline-block;
  }
  .export-btn::after {
    content: ' \25BE';   /* down-arrow ▾ */
    font-size: .7em;
    margin-left: .3em;
  }
  .export-menu {
    display: none;
    position: absolute;
    top: calc(100% + .35rem);
    left: 0;
    min-width: 220px;
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 6px;
    padding: .35rem 0;
    z-index: 10;
    box-shadow: 0 4px 12px rgba(0, 0, 0, .35);
  }
  .export-menu.open { display: block; }
  .export-row {
    display: flex; align-items: center; gap: .75rem;
    padding: .5rem .9rem;
    cursor: pointer;
    color: var(--ink);
    font-size: .85rem;
  }
  .export-row:hover { background: #1b2127; }
  .export-row .label { font-weight: 600; min-width: 38px; }
  .export-row .fav-toggle {
    margin-left: auto;
    display: inline-flex; align-items: center; gap: .35rem;
    color: var(--muted); font-size: .75rem;
    user-select: none;
  }
  .export-row .fav-toggle input {
    accent-color: var(--accent);
    cursor: pointer;
  }
  .export-row .fav-toggle.disabled {
    opacity: .4; cursor: not-allowed;
  }
  .status {
    color: var(--muted); font-size: .85rem; margin-left: auto;
  }
  .log {
    margin-top: 1rem; padding: .75rem 1rem;
    background: var(--panel); border: 1px solid var(--line);
    border-radius: 6px; font-family: 'JetBrains Mono', Consolas, monospace;
    font-size: .8rem; color: var(--muted);
    max-height: 160px; overflow-y: auto;
    white-space: pre-wrap;
  }
  .log .ok  { color: var(--good); }
  .log .err { color: #f07174; }
  .log .pending { color: #e0a458; font-style: italic; }
  .log .warn { color: #e0a458; }
  table {
    margin-top: 1.5rem; width: 100%;
    border-collapse: collapse;
    background: var(--panel);
    border: 1px solid var(--line); border-radius: 6px;
    overflow: hidden;
    font-family: 'JetBrains Mono', Consolas, monospace;
    font-size: .8rem;
  }
  th, td {
    text-align: left; padding: .55rem .75rem;
    border-bottom: 1px solid var(--line);
    vertical-align: top;
  }
  th {
    background: #1b2127; font-weight: 600;
    color: var(--muted); text-transform: uppercase;
    letter-spacing: .04em; font-size: .7rem;
  }
  tr:last-child td { border-bottom: 0; }
  td.highlight { white-space: pre; color: #cdd6df; }
  /* Column sizing — keep the highlight (kill log) flexible and give the
     info column enough room so labels like "4k with m4a1, usp" stay on
     one line instead of wrapping word-by-word. */
  td.col-demo, th.col-demo     { width: 180px; word-break: break-all; }
  td.col-map, th.col-map       { width: 90px; }
  td.col-player, th.col-player { width: 140px; word-break: break-word; }
  td.col-info, th.col-info {
    min-width: 220px; max-width: 320px;
    word-break: keep-all;        /* don't break inside short tokens */
    overflow-wrap: normal;        /* only wrap at natural word boundaries */
  }
  td.fav-cell {
    text-align: center;
    width: 1%;
    white-space: nowrap;
    cursor: pointer;
    user-select: none;
    font-size: 1.1rem;
    line-height: 1;
    color: var(--muted);
    transition: color .1s, transform .1s;
  }
  td.fav-cell:hover { color: var(--ink); transform: scale(1.15); }
  td.fav-cell.active { color: #f5c518; }   /* IMDb yellow */
  th.fav-th {
    width: 1%;
    text-align: center;
  }
  td.type-HLTV { color: var(--good); }
  td.type-POV  { color: var(--warn); }
  .empty { padding: 2rem; text-align: center; color: var(--muted); }
  .badge {
    display: inline-block; padding: .15rem .5rem; border-radius: 4px;
    background: #1b2127; color: var(--accent); font-size: .7rem;
    font-weight: 600; margin-left: .5rem;
  }
  .version-tag {
    font-size: .75rem;
    font-weight: 500;
    color: var(--muted);
    margin-left: .35rem;
    letter-spacing: .02em;
  }
</style>
</head>
<body>
<main>
  <style>
    /* Filter panel: category checkboxes + the server/demo clock switch. */
    .filters { display:none; gap:18px; align-items:flex-start; flex-wrap:wrap;
               margin:14px 0 4px; padding:12px 14px; border:1px solid #2a3142;
               border-radius:8px; background:#161b26; }
    .filters.visible { display:flex; }
    .filter-group { display:flex; flex-direction:column; gap:6px; }
    .filter-group > .filter-title { font-size:11px; letter-spacing:.08em;
               text-transform:uppercase; color:#7a8699; margin-bottom:2px; }
    .filter-opts { display:flex; gap:14px; flex-wrap:wrap; }
    .filter-opts label { display:flex; align-items:center; gap:5px;
               font-size:13px; color:#c6cede; cursor:pointer; user-select:none; }
    .filter-opts input { cursor:pointer; }
    .filter-count { margin-left:auto; align-self:center; font-size:12px;
               color:#7a8699; }
  </style>
  <h1>GoldSrc Demo Parser <span class="version-tag">v__VERSION__</span> <span class="badge">by THUNDERGOD</span></h1>
  <div class="sub">Drop .dem files below &mdash; output CSV matches your template.
    Everything runs on your PC. No uploads anywhere.</div>

  <label class="drop" id="drop">
    <input type="file" id="file" multiple accept=".dem">
    <p><strong>Click to pick .dem files</strong> or drag &amp; drop them here</p>
    <p class="hint">You can drop multiple demos at once.</p>
  </label>

  <div class="actions">
    <button id="clear" class="secondary" disabled>Clear</button>
    <span class="export-wrap">
      <button id="export-btn" class="export-btn" disabled>Export</button>
      <div id="export-menu" class="export-menu">
        <div class="export-row" data-format="csv">
          <span class="label">CSV</span>
          <label class="fav-toggle disabled">
            <input type="checkbox" data-format="csv" disabled>
            favorites only
          </label>
        </div>
        <div class="export-row" data-format="txt">
          <span class="label">TXT</span>
          <label class="fav-toggle disabled">
            <input type="checkbox" data-format="txt" disabled>
            favorites only
          </label>
        </div>
      </div>
    </span>
    <span class="status" id="status">Waiting for demos&hellip;</span>
  </div>

  <div class="log" id="log" style="display:none"></div>

  <div class="filters" id="filters">
  <div class="filter-group">
    <span class="filter-title">Highlight types</span>
    <div class="filter-opts" id="typeFilters">
      <label><input type="checkbox" data-type="ace" checked> ace</label>
      <label><input type="checkbox" data-type="4k" checked> 4k</label>
      <label><input type="checkbox" data-type="triple" checked> triple</label>
      <label><input type="checkbox" data-type="double" checked> double</label>
      <label><input type="checkbox" data-type="fast_3hs" checked> fast 3hs</label>
    </div>
  </div>
  <div class="filter-group">
    <span class="filter-title">Timestamps</span>
    <div class="filter-opts" id="timeFilters">
      <label><input type="radio" name="timebase" value="server" checked> server time</label>
      <label><input type="radio" name="timebase" value="demo"> demo time</label>
    </div>
  </div>
  <span class="filter-count" id="filterCount"></span>
</div>
<div id="results"></div>
</main>

<script>
const drop   = document.getElementById('drop');
const input  = document.getElementById('file');
const status = document.getElementById('status');
const log    = document.getElementById('log');
const clearBtn = document.getElementById('clear');
const exportBtn = document.getElementById('export-btn');
const exportMenu = document.getElementById('export-menu');
const results = document.getElementById('results');

function logLine(text, cls) {
  log.style.display = 'block';
  const span = document.createElement('span');
  if (cls) span.className = cls;
  span.textContent = text + "\n";
  log.appendChild(span);
  log.scrollTop = log.scrollHeight;
  return span;            // returned so the caller can update it in-place
}

// Each row gets a stable id assigned at insertion time so favorites
// survive table re-renders. Row indexes alone don't work because
// re-rendering builds new DOM nodes.
let nextRowId = 0;
const filtersEl = document.getElementById('filters');
const filterCountEl = document.getElementById('filterCount');
const rowMeta = new Map();        // id -> { row: array, favorite: bool }

// Filter state. Rows are parsed once and filtered here, so toggling a box
// never re-reads a demo — on a 100-demo batch a re-parse would take minutes.
const activeTypes = new Set(['ace', '4k', 'triple', 'double', 'fast_3hs']);
let timeBase = 'server';

// Row layout from build_csv_rows():
//   0 demo_name, 1 map, 2 player_name, 3 highlight (server clock),
//   4 info, 5 highlight (demo clock), 6 types
const COL_HIGHLIGHT_SERVER = 3;
const COL_HIGHLIGHT_DEMO = 5;
const COL_TYPES = 6;

// The highlight text to show, per the clock the user picked. Older parses
// without the demo column fall back to the server one.
function highlightText(r) {
  if (timeBase === 'demo' && r[COL_HIGHLIGHT_DEMO]) return r[COL_HIGHLIGHT_DEMO];
  return r[COL_HIGHLIGHT_SERVER];
}

// A row survives if ANY of its categories is ticked. A streak carries every
// category it contains, so an ace holding a one-shot triple matches "triple"
// too — ticking triple alone still surfaces it, as intended.
function rowPassesFilter(r) {
  const types = r[COL_TYPES];
  if (!Array.isArray(types) || types.length === 0) return true;
  return types.some(t => activeTypes.has(t));
}

function visibleIds() {
  return orderedIds.filter(id => {
    const meta = rowMeta.get(id);
    return meta && rowPassesFilter(meta.row);
  });
}
const orderedIds = [];            // insertion order, drives table rendering

function addRows(newRows) {
  for (const r of newRows) {
    const id = nextRowId++;
    rowMeta.set(id, { row: r, favorite: false });
    orderedIds.push(id);
  }
}

function clearAllRows() {
  rowMeta.clear();
  orderedIds.length = 0;
  // keep nextRowId increasing so old DOM listeners (if any) can't collide
}

// Counts only rows currently visible: a star hidden behind a filter shouldn't
// keep the "favourites only" export option alive.
function favoritesCount() {
  let n = 0;
  for (const id of visibleIds()) {
    if (rowMeta.get(id).favorite) n++;
  }
  return n;
}

function renderTable() {
  // The panel only makes sense once something has been parsed.
  filtersEl.classList.toggle('visible', orderedIds.length > 0);

  if (orderedIds.length === 0) {
    results.innerHTML = '<div class="empty">No highlights yet.</div>';
    clearBtn.disabled = true;
    exportBtn.disabled = true;
    exportMenu.classList.remove('open');
    setFavoritesUiState(false);
    return;
  }
  clearBtn.disabled = false;

  const shown = visibleIds();
  filterCountEl.textContent =
    shown.length === orderedIds.length
      ? `${orderedIds.length} highlight${orderedIds.length === 1 ? '' : 's'}`
      : `${shown.length} of ${orderedIds.length} shown`;

  // Nothing left after filtering isn't an error — say so and leave the panel
  // up so the user can widen the selection again.
  if (shown.length === 0) {
    results.innerHTML =
      '<div class="empty">No highlights match the selected types.</div>';
    exportBtn.disabled = true;
    exportMenu.classList.remove('open');
    setFavoritesUiState(false);
    return;
  }
  exportBtn.disabled = false;

  const headers = ['demo_name', 'map', 'player_name', 'highlight', 'info'];
  // Short class names — keep header text intact, just tag each cell with
  // its column for CSS targeting.
  const colClass = {
    demo_name:   'col-demo',
    map:         'col-map',
    player_name: 'col-player',
    highlight:   'highlight',
    info:        'col-info',
  };
  let html = '<table><thead><tr>';
  for (const h of headers) html += `<th class="${colClass[h]}">${h}</th>`;
  html += '<th class="fav-th"></th>';   // favorite column header
  html += '</tr></thead><tbody>';

  for (const id of shown) {
    const meta = rowMeta.get(id);
    const r = meta.row;
    html += `<tr data-row-id="${id}">`;
    headers.forEach((h, i) => {
      // The highlight column swaps between clocks; every other column is
      // read straight out of the row.
      const raw = (i === COL_HIGHLIGHT_SERVER) ? highlightText(r) : r[i];
      const v = raw === null || raw === undefined ? '' : String(raw);
      html += `<td class="${colClass[h]}">${escapeHtml(v)}</td>`;
    });
    const star = meta.favorite ? '\u2605' : '\u2606';   // ★ vs ☆
    const favCls = meta.favorite ? 'fav-cell active' : 'fav-cell';
    html += `<td class="${favCls}" data-fav-id="${id}" title="Toggle favorite">${star}</td>`;
    html += '</tr>';
  }
  html += '</tbody></table>';
  results.innerHTML = html;

  // Wire up star clicks
  results.querySelectorAll('[data-fav-id]').forEach(td => {
    td.addEventListener('click', () => {
      const id = Number(td.dataset.favId);
      const meta = rowMeta.get(id);
      if (!meta) return;
      meta.favorite = !meta.favorite;
      td.classList.toggle('active', meta.favorite);
      td.textContent = meta.favorite ? '\u2605' : '\u2606';
      setFavoritesUiState(favoritesCount() > 0);
    });
  });

  status.textContent = `${orderedIds.length} highlight${orderedIds.length === 1 ? '' : 's'} ready.`;
  setFavoritesUiState(favoritesCount() > 0);
}

// Enable/disable the "favorites only" checkboxes in the export dropdown
// based on whether there are any favorites at all. When disabled we also
// uncheck them so an empty filter doesn't slip through.
function setFavoritesUiState(hasFavorites) {
  const checkboxes = document.querySelectorAll('.export-row .fav-toggle input');
  const labels = document.querySelectorAll('.export-row .fav-toggle');
  checkboxes.forEach(cb => {
    cb.disabled = !hasFavorites;
    if (!hasFavorites) cb.checked = false;
  });
  labels.forEach(l => l.classList.toggle('disabled', !hasFavorites));
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

// Read a File as base64 using the browser's native encoder. Fallback path
// used only when we can't get a filesystem path — typically for drag-drop
// events where the browser hides the underlying path. Path-based flow
// (parse_demo_by_path) is preferred whenever it's available.
function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = reader.result;
      const idx = dataUrl.indexOf(',');
      resolve(idx >= 0 ? dataUrl.slice(idx + 1) : dataUrl);
    };
    reader.onerror = () => reject(new Error('File read failed'));
    reader.readAsDataURL(file);
  });
}

// Process one "job" — a job is either {path: '...'} or {file: FileObj}.
// Returns void; updates the UI/log directly.
async function processJob(job, processed, total) {
  const displayName = job.path
    ? job.path.split(/[\\/]/).pop()
    : job.file.name;
  const displaySize = job.file ? ` (${(job.file.size/1024/1024).toFixed(1)} MB)` : '';

  status.textContent = `Processing ${processed}/${total}: ${displayName}…`;
  const lineSpan = logLine(
    `→ ${displayName}${displaySize}  … processing`, 'pending'
  );

  try {
    let data;
    if (job.path) {
      // Path-based: Python opens the file on disk. No base64 in JS heap.
      data = await pywebview.api.parse_demo_by_path(job.path);
    } else {
      // Base64 fallback: renderer reads and encodes, then hands to Python.
      const b64 = await fileToBase64(job.file);
      data = await pywebview.api.parse_demo(job.file.name, b64);
    }
    if (data && data.error) {
      lineSpan.className = 'err';
      lineSpan.textContent = `→ ${displayName}: ERROR: ${data.error}\n`;
      return;
    }
    const added = data.rows.length;
    addRows(data.rows);
    if (data.modded_server) {
      lineSpan.className = 'warn';
      lineSpan.textContent =
        `→ ${displayName}: kill events not supported `
        + `(modded server — ReHLDS/AMX plugins). No highlights extracted.\n`;
    } else {
      lineSpan.className = 'ok';
      lineSpan.textContent =
        `→ ${displayName}: ${added} highlight${added === 1 ? '' : 's'} `
        + `(${data.demo_type}, ${data.map})\n`;
    }
  } catch (e) {
    lineSpan.className = 'err';
    lineSpan.textContent = `→ ${displayName}: ERROR: ${e.message || e}\n`;
  }
  renderTable();
}

async function handleJobs(jobs) {
  if (!jobs || jobs.length === 0) return;
  const total = jobs.length;
  const startCount = orderedIds.length;
  let processed = 0;

  for (const job of jobs) {
    processed += 1;
    await processJob(job, processed, total);
    // Yield to the event loop between files so the log paints, and GC
    // has a chance to reclaim any transient buffers.
    await new Promise(r => setTimeout(r, 0));
  }

  const totalHighlights = orderedIds.length - startCount;
  status.textContent =
    `Done! ${totalHighlights} highlight${totalHighlights === 1 ? '' : 's'} `
    + `from ${total} demo${total === 1 ? '' : 's'}.`;
  // Refresh the "favourites only" export option once the whole batch is in.
  // This used to call updateExportUI(), which was never defined — it threw a
  // ReferenceError at the end of every batch, surfacing as an unhandled
  // promise rejection.
  setFavoritesUiState(favoritesCount() > 0);
}

async function handleFiles(files) {
  if (!files || files.length === 0) return;

  // Turn the FileList into jobs. Prefer file.path (some WebView builds
  // expose it on drop events) over base64 read+transfer.
  const jobs = [];
  for (const f of files) {
    // File.path is a Chromium/Electron extension; if it's present and
    // non-empty we can skip base64 entirely.
    if (f.path && typeof f.path === 'string') {
      jobs.push({ path: f.path });
    } else {
      jobs.push({ file: f });
    }
  }

  await handleJobs(jobs);
}

// The drop zone <label> would normally auto-trigger the file input's
// built-in picker on click — but that gives us File objects with no
// filesystem path, forcing us to base64 the contents through the JS
// bridge. That's what blows up memory on large batches (100+ demos).
//
// Instead we intercept the click and ask pywebview to open a native
// "Open File(s)" dialog, which returns paths directly. Python can then
// read each file from disk without shipping tens of MB per demo through
// the bridge. Falls back to the input picker if pywebview isn't
// available (running the .py through a plain browser for debugging).
drop.addEventListener('click', e => {
  if (typeof pywebview !== 'undefined' && pywebview.api && pywebview.api.pick_files_dialog) {
    e.preventDefault();
    e.stopPropagation();
    pywebview.api.pick_files_dialog().then(result => {
      if (result && result.error) {
        logLine(`→ ERROR opening file dialog: ${result.error}\n`, 'err');
        return;
      }
      const paths = (result && result.paths) || [];
      if (!paths.length) return;
      // Wrap each path in a fake "File-like" so handleFiles can consume
      // both drag-drop FileList and picker paths uniformly.
      const jobs = paths.map(p => ({ path: p }));
      handleJobs(jobs);
    });
  }
  // If pywebview isn't available, let the label do its default thing
  // and the input's 'change' handler will pick it up.
});

// Fallback input change: still wired so browser-only debugging works.
input.addEventListener('change', e => handleFiles(e.target.files));

['dragenter','dragover'].forEach(ev => drop.addEventListener(ev, e => {
  e.preventDefault(); drop.classList.add('over');
}));
['dragleave','drop'].forEach(ev => drop.addEventListener(ev, e => {
  e.preventDefault(); drop.classList.remove('over');
}));
drop.addEventListener('drop', e => {
  handleFiles(e.dataTransfer.files);
});

// === Export system ===
// Two formats (CSV / TXT). The "favorites only" checkbox is wired up but
// disabled until favorites are implemented in the next step.

// In v1.3 export went through a Blob + `<a download>` trick. That works in
// a real browser but WebView2 (which powers pywebview on Windows) silently
// ignores the download attribute — the user clicks Export and nothing
// happens. In v2.0 we hand the string to Python, which shows a native
// Save As dialog and writes the file to whatever path the user picks.
async function saveViaPython(content, defaultFilename) {
  try {
    const result = await pywebview.api.save_file(defaultFilename, content);
    if (result && result.error) {
      status.textContent = `Save failed: ${result.error}`;
      return;
    }
    if (result && result.saved) {
      status.textContent = `Saved: ${result.path}`;
    } else {
      // User cancelled the dialog — say nothing loud, just clear the status.
      status.textContent = 'Save cancelled';
    }
  } catch (e) {
    status.textContent = `Save failed: ${e.message}`;
  }
}

function rowsForExport(format) {
  const cb = document.querySelector(
    `.export-row[data-format="${format}"] .fav-toggle input`);
  const favoritesOnly = cb && cb.checked && !cb.disabled;
  const out = [];
  // Export what's on screen: same filter, same clock. Whatever you narrowed
  // the table down to is what lands in the file.
  for (const id of visibleIds()) {
    const meta = rowMeta.get(id);
    if (favoritesOnly && !meta.favorite) continue;
    const r = meta.row.slice(0, 5);
    r[COL_HIGHLIGHT_SERVER] = highlightText(meta.row);
    out.push(r);
  }
  return out;
}

function exportCsv() {
  const headers = ['demo_name', 'map', 'player_name', 'highlight', 'info'];
  const escape = s => {
    s = String(s ?? '');
    if (/[",\r\n]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
    return s;
  };
  const data = rowsForExport('csv');
  const lines = [headers.join(',')];
  for (const r of data) lines.push(r.map(escape).join(','));
  // UTF-8 BOM so Excel opens Cyrillic / emoji correctly.
  const content = "\ufeff" + lines.join('\r\n');
  saveViaPython(content, 'gsdp_highlights.csv');
}

function exportTxt() {
  // Format: demo_name on its own line, then each kill line of the streak,
  // blank line between streaks. Demo name repeats before each streak so the
  // output is easy to copy-paste in chunks.
  const data = rowsForExport('txt');
  const blocks = data.map(r => {
    const demoName = r[0];
    const highlightLines = (r[3] || '').split('\n');
    return [demoName, ...highlightLines].join('\n');
  });
  const text = blocks.join('\n\n');
  saveViaPython(text, 'gsdp_highlights.txt');
}

// === Dropdown wiring ===

exportBtn.addEventListener('click', e => {
  e.stopPropagation();
  exportMenu.classList.toggle('open');
});

// Close dropdown when clicking outside
document.addEventListener('click', e => {
  if (!exportMenu.contains(e.target) && e.target !== exportBtn) {
    exportMenu.classList.remove('open');
  }
});

// Click on a row exports that format
exportMenu.querySelectorAll('.export-row').forEach(row => {
  row.addEventListener('click', e => {
    // Don't trigger export when clicking on the checkbox itself
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'LABEL'
        || e.target.closest('label')) {
      return;
    }
    const format = row.dataset.format;
    if (format === 'csv') exportCsv();
    else if (format === 'txt') exportTxt();
    exportMenu.classList.remove('open');
  });
});

clearBtn.addEventListener('click', () => {
  clearAllRows();
  log.innerHTML = '';
  log.style.display = 'none';
  status.textContent = 'Waiting for demos\u2026';
  renderTable();
});

// === Filter panel wiring ===

document.querySelectorAll('#typeFilters input').forEach(cb => {
  cb.addEventListener('change', () => {
    if (cb.checked) activeTypes.add(cb.dataset.type);
    else activeTypes.delete(cb.dataset.type);
    renderTable();
  });
});

document.querySelectorAll('#timeFilters input').forEach(rb => {
  rb.addEventListener('change', () => {
    if (rb.checked) timeBase = rb.value;
    renderTable();
  });
});

renderTable();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# pywebview bridge — replaces the v1.3 HTTP server.
#
# The UI is loaded into a native window and talks to Python through
# `pywebview.api.<method>()` calls. Files are transferred as base64-encoded
# strings because pywebview's JS↔Python bridge is JSON-only — no raw bytes
# or file handles. The overhead (~33% size inflation) is negligible for
# .dem files at this scale, and keeps the JS side simple: `await
# pywebview.api.parse_demo(name, b64content)` in place of the old
# `await fetch('/parse', ...)`.
# ---------------------------------------------------------------------------
def _reveal_in_file_manager(path):
    """Open the OS file manager with `path` selected, so the user can see
    where the export landed without hunting for it.

    Best-effort only: a failure here must never turn a successful save into a
    reported error, so every exception is swallowed. Windows is the shipping
    target; the other branches keep `python cs16_ui.py` usable while
    developing on Linux or macOS.
    """
    try:
        p = Path(path).resolve()
        if sys.platform == "win32":
            # /select, highlights the file inside its folder. explorer.exe
            # returns exit code 1 even when it succeeds, so don't check it.
            subprocess.Popen(["explorer", "/select,", str(p)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p.parent)])
    except Exception:
        sys.stderr.write("could not open file manager:\n" + traceback.format_exc())


class Api:
    """Methods on this class are callable from JS as `pywebview.api.<name>()`.

    Method signatures must be JSON-serializable in both directions.
    Returned dicts are the same shape as the v1.3 HTTP responses so the JS
    handling code needed no changes beyond swapping the call site.
    """

    def pick_files_dialog(self):
        """Open a native "Open File(s)" dialog for the user to pick .dem
        files. Returns {'paths': [...]} — a list of absolute paths on the
        local filesystem — or an empty list if the user cancelled.

        Using this path (instead of base64 transfer through the JS bridge)
        avoids piling megabytes of demo data into the renderer's memory,
        which is what causes 'Out of Memory' errors on large batches."""
        try:
            window = webview.windows[0]
            result = window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=True,
                file_types=("Demo files (*.dem)", "All files (*.*)"),
            )
            if not result:
                return {"paths": []}
            paths = list(result) if isinstance(result, (list, tuple)) else [result]
            return {"paths": paths}
        except Exception as e:
            sys.stderr.write("pick error:\n" + traceback.format_exc())
            return {"error": str(e), "paths": []}

    def parse_demo_by_path(self, path):
        """Parse a demo directly from a local filesystem path. Same output
        shape as parse_demo(name, b64_content), but without the base64
        round-trip through JS — Python opens the file on disk itself.

        This is the memory-efficient path for large batches. The base64
        path (parse_demo) is kept as a fallback for drag-drop cases where
        the browser hides the underlying filesystem path."""
        try:
            p = Path(path)
            if not p.is_file():
                return {"error": f"File not found: {path}"}
            if p.stat().st_size > MAX_UPLOAD_BYTES:
                mb = MAX_UPLOAD_BYTES // 1024 // 1024
                return {"error": f"File too large (> {mb} MB)"}
            parsed = parse_demo_full(str(p))
            parsed["demo_name"] = p.name
            rows = build_csv_rows(parsed)
            return {
                "rows": rows,
                "map": parsed["map_name"],
                "demo_type": parsed["demo_type"],
                "highlight_count": len(rows),
                "modded_server": parsed.get("modded_server", False),
            }
        except Exception as e:
            sys.stderr.write("parse error:\n" + traceback.format_exc())
            return {"error": str(e)}

    def parse_demo(self, filename, b64_content):
        """Decode + parse a demo. Returns the same dict shape v1.3 sent over
        HTTP: rows, map, demo_type, highlight_count, modded_server. On error
        returns {'error': str}."""
        try:
            content = base64.b64decode(b64_content)
        except Exception as e:
            return {"error": f"Bad base64 payload: {e}"}

        if len(content) > MAX_UPLOAD_BYTES:
            mb = MAX_UPLOAD_BYTES // 1024 // 1024
            return {"error": f"File too large (> {mb} MB)"}

        # Stage the bytes to a temp file — parse_demo_full expects a path.
        tmp_dir = Path(_here) / "_uploads"
        tmp_dir.mkdir(exist_ok=True)
        safe_name = "".join(
            c if c.isalnum() or c in "._-" else "_" for c in filename
        )[:80]
        tmp_path = tmp_dir / f"{int(time.time() * 1000)}_{safe_name}"
        tmp_path.write_bytes(content)

        try:
            parsed = parse_demo_full(str(tmp_path))
            parsed["demo_name"] = filename
            rows = build_csv_rows(parsed)
            return {
                "rows": rows,
                "map": parsed["map_name"],
                "demo_type": parsed["demo_type"],
                # Report the visible count (rows) rather than the raw
                # parser count. build_csv_rows drops streaks with 6+
                # kills (impossible in one round), and mismatched counts
                # in the log line would confuse the user.
                "highlight_count": len(rows),
                "modded_server": parsed.get("modded_server", False),
            }
        except Exception as e:
            sys.stderr.write("parse error:\n" + traceback.format_exc())
            return {"error": str(e)}
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass

    def save_file(self, default_filename, content):
        """Show a native "Save As" dialog and write `content` (a string) to
        the chosen path. Replaces the browser's `<a download>` blob trick,
        which WebView2 silently drops. Returns {'saved': True, 'path': ...}
        on success, {'saved': False} if the user cancelled, or {'error': ...}
        on any failure."""
        try:
            # Extension filter from the default filename
            ext = ""
            if "." in default_filename:
                ext = default_filename.rsplit(".", 1)[-1].lower()
            filter_map = {
                "csv": ("CSV files (*.csv)", "*.csv"),
                "txt": ("Text files (*.txt)", "*.txt"),
            }
            label, mask = filter_map.get(ext, ("All files (*.*)", "*.*"))
            file_types = (label, "All files (*.*)")

            window = webview.windows[0]
            result = window.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=default_filename,
                file_types=file_types,
            )
            # create_file_dialog returns a tuple/list of paths, or None if
            # cancelled. For SAVE_DIALOG it's a single-item container.
            if not result:
                return {"saved": False}
            path = result[0] if isinstance(result, (list, tuple)) else result

            # Write as UTF-8; content already carries the BOM if it's CSV.
            Path(path).write_text(content, encoding="utf-8", newline="")
            _reveal_in_file_manager(path)
            return {"saved": True, "path": path}
        except Exception as e:
            sys.stderr.write("save error:\n" + traceback.format_exc())
            return {"error": str(e)}


# ---------------------------------------------------------------------------
# App startup
# ---------------------------------------------------------------------------
def _icon_path():
    """Locate app_icon.ico regardless of whether we're running as a .py from
    source or as a PyInstaller-frozen .exe. Returns None if the icon isn't
    found — pywebview will use its default window chrome in that case.

    PyInstaller onefile extracts bundled data to sys._MEIPASS at runtime,
    so we check there first; otherwise fall back to the script's directory.
    """
    candidates = []
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / "app_icon.ico")
    candidates.append(_here / "app_icon.ico")
    for p in candidates:
        if p.is_file():
            return str(p)
    return None


def main():
    html = INDEX_HTML.replace("__VERSION__", VERSION)
    api = Api()
    icon = _icon_path()
    webview.create_window(
        title=f"GoldSrc Demo Parser v{VERSION}",
        html=html,
        js_api=api,
        width=1400,
        height=900,
        min_size=(1000, 600),
        # Enable text selection — off by default in pywebview because many
        # apps don't want it, but our UI is table-heavy (demo names, kill
        # timestamps, player names) and users need to copy that content.
        text_select=True,
    )
    # webview.start() is where the app-level icon goes in pywebview 4.x/6.x
    # (create_window() only takes per-window shape/behaviour options).
    # gui=None → pywebview auto-picks (edgechromium on Win 10+, mshtml as fallback)
    # debug=False → no dev tools by default; flip during development if needed
    start_kwargs = dict(gui=None, debug=False)
    if icon:
        start_kwargs["icon"] = icon
    webview.start(**start_kwargs)


if __name__ == "__main__":
    main()
