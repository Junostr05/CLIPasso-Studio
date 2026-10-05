"""Control from a phone in the home network: a small web page (status, live preview, pause / cancel, take a photo
and sketch it) served by the app itself – standard library only, off by default.

Safety: only addresses of the local network may connect; every request needs the access code of the QR code (on
the first visit it becomes a cookie); changes (pause, upload) also need it as a header, so other web pages cannot
send them; uploads are limited in size and must be pictures. The server runs in threads of its own and talks to
the app through Qt signals (``RemoteBridge``)."""

from __future__ import annotations

import hmac
import html
import ipaddress
import json
import os
import secrets
import socket
import threading
import time
import urllib.parse
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PySide6.QtCore import QObject, Signal

from .app_settings import app_settings

DEFAULT_PORT = 8765
MAX_UPLOAD = 25 * 1024 * 1024
COOKIE = "cs_access"
UPLOAD_DIR = "_remote"  # in the output folder (cleared with the other pictures of the app)
METHODS = ("clipasso", "swiftsketch", "controlsketch", "scenesketch")


def new_token() -> str:
    return secrets.token_urlsafe(18)


def token() -> str:
    """The access code (made on first use)."""
    st = app_settings()
    t = st.get("remote_token") or ""
    if len(t) < 16:
        t = new_token()
        st.set("remote_token", t)
    return t


def local_address() -> str:
    """The address of this computer in the home network (no packet is sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # (TEST-NET: only picks the outgoing interface)
            ip = s.getsockname()[0]
            if not ip.startswith("0."):
                return ip
    except OSError:
        pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "127.0.0.1"


def url(port: int | None = None, address: str | None = None) -> str:
    port = port or int(app_settings().get("remote_port", DEFAULT_PORT) or DEFAULT_PORT)
    return f"http://{address or local_address()}:{port}/?t={token()}"


def allowed_client(ip: str) -> bool:
    """Only the home network (private, link-local and loopback addresses)."""
    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return addr.is_private or addr.is_loopback or addr.is_link_local


def qr_png(text: str, scale: int = 6) -> bytes:
    """The QR code of ``text`` as a PNG (segno)."""
    import io

    import segno

    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="png", scale=scale, border=2)
    return buf.getvalue()


class RemoteBridge(QObject):
    """Between the server threads and the app: requests come in as signals (handled in the GUI thread); the app
    keeps ``state`` up to date (a dict replaced as a whole, read by the server threads)."""

    pause = Signal()
    resume = Signal()
    cancel = Signal()
    upload = Signal(str, str)  # (saved picture, method)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state: dict = {"busy": False, "paused": False, "job": None, "queue": 0, "last": None}
        self.preview_svg = ""
        self.texts: dict = {}

    def set_state(self, **changes):
        self.state = {**self.state, **changes}


def page(texts: dict, access: str) -> str:
    """The phone page (one file; light and dark)."""
    t = {k: html.escape(str(v)) for k, v in texts.items()}
    options = "".join(f'<option value="{m}">{html.escape(texts.get("method_" + m, m))}</option>' for m in METHODS)
    return f"""<!doctype html>
<html lang="{t.get('lang', 'en')}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CLIPasso Studio</title>
<style>
:root {{ --bg: #f4f5f7; --card: #ffffff; --text: #1d2129; --muted: #6b7280; --accent: #6d5efc; --line: #e3e5ea; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg: #14161b; --card: #1d2027; --text: #e8e9ed; --muted: #9aa0ab; --accent: #8b7fff; --line: #2b2f38; }}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; padding: 16px; background: var(--bg); color: var(--text); font: 16px/1.4 system-ui, sans-serif; }}
h1 {{ font-size: 20px; margin: 4px 0 14px; }}
.card {{ background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 14px;
         margin-bottom: 12px; }}
.muted {{ color: var(--muted); font-size: 14px; }}
.bar {{ height: 8px; background: var(--line); border-radius: 4px; overflow: hidden; margin: 10px 0 4px; }}
.bar > div {{ height: 100%; width: 0; background: var(--accent); transition: width .4s; }}
.preview {{ background: #fff; border-radius: 10px; aspect-ratio: 1; display: flex; align-items: center;
           justify-content: center; overflow: hidden; }}
.preview img {{ width: 100%; height: 100%; object-fit: contain; }}
.preview img:not([src]) {{ visibility: hidden; }}
select {{ width: 100%; }}
.row {{ display: flex; gap: 8px; margin-top: 10px; }}
button, select {{ font: inherit; border-radius: 10px; border: 1px solid var(--line); padding: 10px 14px;
                 background: var(--card); color: var(--text); }}
button.primary {{ background: var(--accent); color: #fff; border-color: var(--accent); flex: 1; }}
button {{ flex: 1; }}
input[type=file] {{ width: 100%; margin: 8px 0; }}
#msg {{ min-height: 1.4em; }}
</style>
</head>
<body>
<h1>CLIPasso Studio</h1>
<div class="card">
  <div id="state" class="muted">…</div>
  <div class="bar"><div id="progress"></div></div>
  <div id="eta" class="muted"></div>
  <div class="row"><button id="pause">{t.get('pause', 'Pause')}</button>
    <button id="cancel">{t.get('cancel', 'Cancel')}</button></div>
</div>
<div class="card"><div class="preview"><img id="preview" alt=""></div></div>
<div class="card">
  <b>{t.get('new', 'New sketch')}</b>
  <input id="file" type="file" accept="image/*" capture="environment">
  <select id="method">{options}</select>
  <div class="row"><button class="primary" id="send">{t.get('send', 'Sketch it')}</button></div>
  <div id="msg" class="muted"></div>
</div>
<script>
const TOKEN = {json.dumps(access)};
const T = {json.dumps(texts)};
const $ = (id) => document.getElementById(id);
let paused = false, shown = "";
async function post(path, body, headers) {{
  const all = Object.assign({{"X-Access": TOKEN}}, headers || {{}});
  const r = await fetch(path, {{method: "POST", body: body || "", headers: all}});
  return r.json();
}}
async function refresh() {{
  try {{
    const s = await (await fetch("/api/status")).json();
    paused = s.paused;
    $("pause").textContent = paused ? T.resume : T.pause;
    $("pause").disabled = $("cancel").disabled = !s.busy;
    if (s.job) {{
      $("state").textContent = (s.paused ? T.paused : T.running) + " · " + s.job.name + " · " + s.job.method;
      $("progress").style.width = Math.round(100 * s.job.progress) + "%";
      $("eta").textContent = s.job.eta ? T.eta + " " + s.job.eta : "";
    }} else {{
      $("state").textContent = s.last ? T.done + " · " + s.last.name : T.idle;
      $("progress").style.width = s.last ? "100%" : "0";
      $("eta").textContent = s.queue ? T.queued + " " + s.queue : "";
    }}
    if (s.preview && s.preview !== shown) {{
      shown = s.preview;
      $("preview").src = "/api/preview.svg?v=" + encodeURIComponent(s.preview);
    }}
  }} catch (e) {{ $("state").textContent = T.offline; }}
}}
$("pause").onclick = () => post(paused ? "/api/resume" : "/api/pause").then(refresh);
$("cancel").onclick = () => {{ if (confirm(T.cancel_ask)) post("/api/cancel").then(refresh); }};
$("send").onclick = async () => {{
  const f = $("file").files[0];
  if (!f) {{ $("msg").textContent = T.pick; return; }}
  $("msg").textContent = T.sending;
  try {{
    const head = {{"X-Filename": encodeURIComponent(f.name || "photo.jpg"), "X-Method": $("method").value}};
    const r = await post("/api/upload", f, head);
    $("msg").textContent = r.ok ? T.queued_ok : (r.error || T.failed);
    if (r.ok) $("file").value = "";
  }} catch (e) {{ $("msg").textContent = T.failed; }}
  refresh();
}};
refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>
"""


class _Handler(BaseHTTPRequestHandler):
    server_version = "CLIPassoStudio"
    bridge: RemoteBridge = None  # set per server
    upload_dir: str = ""

    def log_message(self, fmt, *args):  # (quiet: no lines on stderr)
        pass

    # ------------------------------------------------------------------ helpers
    def _send(self, code: int, body: bytes, ctype: str, headers: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data: dict, code: int = 200):
        self._send(code, json.dumps(data).encode("utf-8"), "application/json; charset=utf-8")

    def _cookie_token(self) -> str:
        jar = SimpleCookie(self.headers.get("Cookie") or "")
        return jar[COOKIE].value if COOKIE in jar else ""

    def _authorised(self, header: bool = False) -> bool:
        expected = token()
        given = self.headers.get("X-Access", "") if header else self._cookie_token()
        return bool(given) and hmac.compare_digest(given, expected)

    def _check_client(self) -> bool:
        if not allowed_client(self.client_address[0]):
            self._send(403, b"only from the home network", "text/plain")
            return False
        return True

    # ------------------------------------------------------------------ requests
    def do_GET(self):  # noqa: N802
        if not self._check_client():
            return
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        if parsed.path == "/":
            given = (query.get("t") or [""])[0]
            if given and hmac.compare_digest(given, token()):  # first visit from the QR code: remember it
                self._send(303, b"", "text/plain", {
                    "Location": "/", "Set-Cookie": f"{COOKIE}={token()}; Path=/; HttpOnly; SameSite=Strict; "
                                                   "Max-Age=31536000"})
                return
            if not self._authorised():
                self._send(403, b"No access code: scan the QR code in CLIPasso Studio.", "text/plain")
                return
            self._send(200, page(self.bridge.texts, token()).encode("utf-8"), "text/html; charset=utf-8")
            return
        if not self._authorised():
            self._json({"ok": False, "error": "no access"}, 403)
            return
        if parsed.path == "/api/status":
            state = dict(self.bridge.state)
            state["preview"] = str(hash(self.bridge.preview_svg)) if self.bridge.preview_svg else ""
            self._json(state)
        elif parsed.path == "/api/preview.svg":
            svg = self.bridge.preview_svg or '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>'
            self._send(200, svg.encode("utf-8"), "image/svg+xml",
                       {"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})
        else:
            self._json({"ok": False, "error": "not found"}, 404)

    def do_POST(self):  # noqa: N802
        if not self._check_client():
            return
        if not self._authorised(header=True):
            self._json({"ok": False, "error": "no access"}, 403)
            return
        path = urllib.parse.urlparse(self.path).path
        if path in ("/api/pause", "/api/resume", "/api/cancel"):
            getattr(self.bridge, path.rsplit("/", 1)[1]).emit()
            self._json({"ok": True})
        elif path == "/api/upload":
            self._upload()
        else:
            self._json({"ok": False, "error": "not found"}, 404)

    def _upload(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_UPLOAD:
            self._json({"ok": False, "error": "the picture is empty or larger than 25 MB"}, 413)
            return
        data = self.rfile.read(length)
        method = self.headers.get("X-Method", "clipasso")
        method = method if method in METHODS else "clipasso"
        name = os.path.basename(urllib.parse.unquote(self.headers.get("X-Filename") or "photo.jpg"))
        stem, ext = os.path.splitext(name)
        stem = "".join(c for c in stem if c.isalnum() or c in "-_ ")[:40].strip() or "photo"
        ext = ext.lower() if ext.lower() in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp") else ".jpg"
        os.makedirs(self.upload_dir, exist_ok=True)
        dest = os.path.join(self.upload_dir, f"{time.strftime('%Y%m%d-%H%M%S')}_{stem}{ext}")
        with open(dest, "wb") as f:
            f.write(data)
        if not _is_picture(dest):
            os.remove(dest)
            self._json({"ok": False, "error": "not a picture"}, 415)
            return
        self.bridge.upload.emit(dest, method)
        self._json({"ok": True})

    do_HEAD = do_GET  # noqa: N815


def _is_picture(path: str) -> bool:
    """A picture the app can open (also HEIC from an iPhone)."""
    try:
        from .image_io import read_image

        return not read_image(path, 64).isNull()
    except Exception:
        return False


class RemoteServer:
    """The web server of the phone page (threads of its own)."""

    def __init__(self, bridge: RemoteBridge, port: int = DEFAULT_PORT, host: str = "0.0.0.0",
                 upload_dir: str | None = None):
        out = app_settings().get("output_dir") or "."
        handler = type("Handler", (_Handler,), {"bridge": bridge,
                                                 "upload_dir": upload_dir or os.path.join(out, UPLOAD_DIR)})
        self.httpd = ThreadingHTTPServer((host, int(port)), handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="remote", daemon=True)

    def start(self) -> "RemoteServer":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
