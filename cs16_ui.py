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


# ---------------------------------------------------------------------------
# HTML (inlined so the .exe is a single self-contained file)
# ---------------------------------------------------------------------------
INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>GSDP</title>
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
    max-width: 1200px;
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
  td.type-HLTV { color: var(--good); }
  td.type-POV  { color: var(--warn); }
  .empty { padding: 2rem; text-align: center; color: var(--muted); }
  .badge {
    display: inline-block; padding: .15rem .5rem; border-radius: 4px;
    background: #1b2127; color: var(--accent); font-size: .7rem;
    font-weight: 600; margin-left: .5rem;
  }
</style>
</head>
<body>
<main>
  <h1>GoldSrc Demo Parser <span class="badge">by THUNDERGOD</span></h1>
  <div class="sub">Drop .dem files below &mdash; output CSV matches your template.
    Everything runs on your PC. No uploads anywhere.</div>

  <label class="drop" id="drop">
    <input type="file" id="file" multiple accept=".dem">
    <p><strong>Click to pick .dem files</strong> or drag &amp; drop them here</p>
    <p class="hint">You can drop multiple demos at once.</p>
  </label>

  <div class="actions">
    <button id="clear" class="secondary" disabled>Clear</button>
    <button id="download" disabled>Download CSV</button>
    <span class="status" id="status">Waiting for demos&hellip;</span>
  </div>

  <div class="log" id="log" style="display:none"></div>

  <div id="results"></div>
</main>

<script>
const rows = [];
const drop   = document.getElementById('drop');
const input  = document.getElementById('file');
const status = document.getElementById('status');
const log    = document.getElementById('log');
const clearBtn = document.getElementById('clear');
const dlBtn  = document.getElementById('download');
const results = document.getElementById('results');

function logLine(text, cls) {
  log.style.display = 'block';
  const span = document.createElement('span');
  if (cls) span.className = cls;
  span.textContent = text + "\n";
  log.appendChild(span);
  log.scrollTop = log.scrollHeight;
}

function renderTable() {
  if (rows.length === 0) {
    results.innerHTML = '<div class="empty">No highlights yet.</div>';
    clearBtn.disabled = true;
    dlBtn.disabled = true;
    return;
  }
  clearBtn.disabled = false;
  dlBtn.disabled = false;

  const headers = ['demo_name', 'map', 'player_name', 'highlight', 'info'];
  let html = '<table><thead><tr>';
  for (const h of headers) html += `<th>${h}</th>`;
  html += '</tr></thead><tbody>';

  for (const r of rows) {
    html += '<tr>';
    headers.forEach((h, i) => {
      const v = r[i] === null || r[i] === undefined ? '' : String(r[i]);
      const cls = (h === 'highlight') ? 'highlight' : '';
      html += `<td class="${cls}">${escapeHtml(v)}</td>`;
    });
    html += '</tr>';
  }
  html += '</tbody></table>';
  results.innerHTML = html;
  status.textContent = `${rows.length} highlight${rows.length === 1 ? '' : 's'} ready.`;
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

async function handleFiles(files) {
  if (!files || files.length === 0) return;
  status.textContent = `Processing ${files.length} demo${files.length === 1 ? '' : 's'}…`;

  for (const f of files) {
    logLine(`→ ${f.name} (${(f.size/1024/1024).toFixed(1)} MB)`);
    const form = new FormData();
    form.append('demo', f);
    try {
      const resp = await fetch('/parse', { method: 'POST', body: form });
      const data = await resp.json();
      if (!resp.ok) {
        logLine(`   ERROR: ${data.error || resp.statusText}`, 'err');
        continue;
      }
      const added = data.rows.length;
      rows.push(...data.rows);
      logLine(`   ok: ${added} highlight${added === 1 ? '' : 's'} `
              + `(${data.demo_type}, ${data.map}, ${data.total_kills} total kills)`, 'ok');
    } catch (e) {
      logLine(`   ERROR: ${e.message}`, 'err');
    }
    renderTable();
  }
  status.textContent = `${rows.length} highlight${rows.length === 1 ? '' : 's'} ready.`;
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

clearBtn.addEventListener('click', () => {
  rows.length = 0;
  log.innerHTML = '';
  log.style.display = 'none';
  status.textContent = 'Waiting for demos\u2026';
  renderTable();
});

dlBtn.addEventListener('click', () => {
  const headers = ['demo_name', 'map', 'player_name', 'highlight', 'info'];
  const escape = s => {
    s = String(s ?? '');
    if (/[",\r\n]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
    return s;
  };
  const lines = [headers.join(',')];
  for (const r of rows) lines.push(r.map(escape).join(','));
  // UTF-8 BOM so Excel opens Cyrillic / emoji correctly
  const blob = new Blob(["\ufeff" + lines.join('\r\n')],
                       { type: 'text/csv;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'cs16_highlights.csv';
  a.click();
  URL.revokeObjectURL(a.href);
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
            body = INDEX_HTML.encode("utf-8")
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
                total_kills = sum(len(s) for s in parsed["highlights"])
                resp = {
                    "rows": rows,
                    "map": parsed["map_name"],
                    "demo_type": parsed["demo_type"],
                    "total_kills": total_kills,
                    "highlight_count": len(parsed["highlights"]),
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
