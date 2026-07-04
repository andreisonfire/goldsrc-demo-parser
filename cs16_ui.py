#!/usr/bin/env python3
"""
CS 1.6 demo killfeed — local web UI.

Run this file (or cs16_ui.exe), a browser tab opens at http://localhost:8765
with a drag-and-drop zone. Upload one or more .dem files, get a CSV back
formatted exactly like the user-provided template.

All processing happens locally. No data ever leaves your machine.
"""
import io
import json
import socket
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Allow imports whether run as .py, frozen .exe, or from another dir
_here = Path(__file__).resolve().parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from cs16_killfeed import parse_demo_full, build_csv_rows

HOST = "127.0.0.1"
PORT = 8765
MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB per request

# Single source of truth for the user-visible product version. Bump this
# string when shipping a new release; it appears in the browser tab title
# and in the page header. We deliberately do NOT compute it from git tags
# or anywhere else — keep one literal that's grep-able.
VERSION = "1.3"


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
const rowMeta = new Map();        // id -> { row: array, favorite: bool }
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

function favoritesCount() {
  let n = 0;
  for (const id of orderedIds) {
    if (rowMeta.get(id).favorite) n++;
  }
  return n;
}

function renderTable() {
  if (orderedIds.length === 0) {
    results.innerHTML = '<div class="empty">No highlights yet.</div>';
    clearBtn.disabled = true;
    exportBtn.disabled = true;
    exportMenu.classList.remove('open');
    setFavoritesUiState(false);
    return;
  }
  clearBtn.disabled = false;
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

  for (const id of orderedIds) {
    const meta = rowMeta.get(id);
    const r = meta.row;
    html += `<tr data-row-id="${id}">`;
    headers.forEach((h, i) => {
      const v = r[i] === null || r[i] === undefined ? '' : String(r[i]);
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

async function handleFiles(files) {
  if (!files || files.length === 0) return;
  const total = files.length;
  const startCount = orderedIds.length;
  let processed = 0;

  for (const f of files) {
    processed += 1;
    // Top-level progress counter — visible at all times, even if log is scrolled
    status.textContent = `Processing ${processed}/${total}: ${f.name}…`;

    // Add a placeholder line that we'll update in place when the demo finishes.
    // This keeps the "→ name (size)  ... processing" visible while waiting,
    // so the user can see what's currently being worked on.
    const lineSpan = logLine(
      `→ ${f.name} (${(f.size/1024/1024).toFixed(1)} MB)  … processing`,
      'pending'
    );

    const form = new FormData();
    form.append('demo', f);
    try {
      const resp = await fetch('/parse', { method: 'POST', body: form });
      const data = await resp.json();
      if (!resp.ok) {
        lineSpan.className = 'err';
        lineSpan.textContent = `→ ${f.name}: ERROR: ${data.error || resp.statusText}\n`;
        continue;
      }
      const added = data.rows.length;
      addRows(data.rows);
      // Replace the "processing" placeholder with the final result line
      if (data.modded_server) {
        // Demo parsed OK but uses an extended DeathMsg format we don't
        // support yet. Explain instead of leaving the user guessing.
        lineSpan.className = 'warn';
        lineSpan.textContent =
          `→ ${f.name}: kill events not supported `
          + `(modded server — ReHLDS/AMX plugins). No highlights extracted.\n`;
      } else {
        lineSpan.className = 'ok';
        lineSpan.textContent =
          `→ ${f.name}: ${added} highlight${added === 1 ? '' : 's'} `
          + `(${data.demo_type}, ${data.map})\n`;
      }
    } catch (e) {
      lineSpan.className = 'err';
      lineSpan.textContent = `→ ${f.name}: ERROR: ${e.message}\n`;
    }
    renderTable();
  }

  const totalHighlights = orderedIds.length - startCount;
  status.textContent =
    `Done! ${totalHighlights} highlight${totalHighlights === 1 ? '' : 's'} `
    + `from ${total} demo${total === 1 ? '' : 's'}.`;
}

// Note: <label class="drop"> already wraps the file input, so clicking
// anywhere on the label natively triggers the input's file picker.
// DO NOT add a manual click handler here — it would fire a SECOND click
// and the browser closes the first dialog before opening a new one,
// requiring the user to click twice.
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

function downloadBlob(blob, filename) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

function rowsForExport(format) {
  const cb = document.querySelector(
    `.export-row[data-format="${format}"] .fav-toggle input`);
  const favoritesOnly = cb && cb.checked && !cb.disabled;
  const out = [];
  for (const id of orderedIds) {
    const meta = rowMeta.get(id);
    if (favoritesOnly && !meta.favorite) continue;
    out.push(meta.row);
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
  const blob = new Blob(["\ufeff" + lines.join('\r\n')],
                       { type: 'text/csv;charset=utf-8' });
  downloadBlob(blob, 'gsdp_highlights.csv');
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
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
  downloadBlob(blob, 'gsdp_highlights.txt');
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

renderTable();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Minimal multipart/form-data parser (no deps).
# Only extracts the first file part — enough for our 1-file-at-a-time UI.
# ---------------------------------------------------------------------------
def parse_single_file_upload(body, content_type):
    if "multipart/form-data" not in content_type:
        raise ValueError("Expected multipart/form-data")
    idx = content_type.lower().find("boundary=")
    if idx < 0:
        raise ValueError("No boundary in Content-Type")
    boundary = content_type[idx + len("boundary="):].strip().strip('"')
    if ";" in boundary:
        boundary = boundary.split(";", 1)[0].strip()
    delim = b"--" + boundary.encode("ascii")

    parts = body.split(delim)
    for part in parts:
        if not part or part in (b"\r\n", b"--\r\n", b"--"):
            continue
        if part.startswith(b"\r\n"):
            part = part[2:]
        if part.endswith(b"\r\n"):
            part = part[:-2]
        sep = part.find(b"\r\n\r\n")
        if sep < 0:
            continue
        headers_raw = part[:sep].decode("latin-1", errors="replace")
        content = part[sep + 4:]
        filename = None
        for line in headers_raw.split("\r\n"):
            if line.lower().startswith("content-disposition"):
                for token in line.split(";"):
                    token = token.strip()
                    if token.startswith("filename="):
                        filename = token[len("filename="):].strip().strip('"')
                        break
        if filename:
            return filename, content
    raise ValueError("No file part found in upload")


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        # Silence default stdout spam; we do our own logging elsewhere.
        sys.stderr.write(f"  [http] {self.address_string()} {fmt % args}\n")

    def _send_json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            # Substitute the version placeholders before serving. Using
            # replace() rather than f-string interpolation so we don't
            # need to escape every JS ${...} template literal in the HTML.
            html = INDEX_HTML.replace("__VERSION__", VERSION)
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_POST(self):
        if self.path != "/parse":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                return self._send_json({"error": "Empty upload"}, 400)
            if length > MAX_UPLOAD_BYTES:
                return self._send_json(
                    {"error": f"File too large (> {MAX_UPLOAD_BYTES // 1024 // 1024} MB)"},
                    413,
                )
            body = self.rfile.read(length)
            ctype = self.headers.get("Content-Type", "")
            filename, content = parse_single_file_upload(body, ctype)

            tmp_dir = Path(_here) / "_uploads"
            tmp_dir.mkdir(exist_ok=True)
            # Use current time + filename to avoid collisions
            safe_name = "".join(c if c.isalnum() or c in "._-" else "_"
                                for c in filename)[:80]
            tmp_path = tmp_dir / f"{int(time.time() * 1000)}_{safe_name}"
            tmp_path.write_bytes(content)

            try:
                parsed = parse_demo_full(str(tmp_path))
                # replace the tmp filename with the one the user uploaded
                parsed["demo_name"] = filename
                rows = build_csv_rows(parsed)
                resp = {
                    "rows": rows,
                    "map": parsed["map_name"],
                    "demo_type": parsed["demo_type"],
                    "highlight_count": len(parsed["highlights"]),
                    "modded_server": parsed.get("modded_server", False),
                }
                return self._send_json(resp)
            finally:
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
        except Exception as e:
            sys.stderr.write("parse error:\n" + traceback.format_exc())
            return self._send_json({"error": str(e)}, 500)


# ---------------------------------------------------------------------------
# Server startup
# ---------------------------------------------------------------------------
def find_free_port(start=PORT, attempts=20):
    for p in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((HOST, p))
                return p
            except OSError:
                continue
    raise RuntimeError(f"No free port in range {start}..{start + attempts}")


def main():
    port = find_free_port()
    url = f"http://{HOST}:{port}/"
    server = ThreadingHTTPServer((HOST, port), Handler)

    print("=" * 56)
    print(f"  CS 1.6 Demo Highlights  —  local web UI")
    print("=" * 56)
    print(f"  URL: {url}")
    print(f"  Press Ctrl+C to stop.")
    print()

    # Open browser after a short delay (server needs a moment)
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
