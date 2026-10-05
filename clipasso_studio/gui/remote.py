"""Control from a phone in the home network: a web page served by the app itself with most of the studio – the
picture (camera, files, recent pictures), method, presets, every parameter, the detail brush, start / queue / pause /
cancel, the live sketches, thumbs and downloads, the recent results and the queue (``gui/phone_api.py``; the page is
``resources/phone/``). Standard library only, off by default.

Safety: only addresses of the local network may connect (and, if switched on, the devices of the user's tailnet);
every request needs the access code of the QR code (on the first visit it becomes a cookie); changes (pause, upload)
also need it as a header, so other web pages cannot send them; uploads are limited in size and must be pictures;
nothing on the computer is read by a path the phone names. The server runs in threads of its own and talks to the
app through Qt signals (``RemoteBridge``)."""

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

from .. import paths

from .app_settings import app_settings

DEFAULT_PORT = 8765
MAX_UPLOAD = 25 * 1024 * 1024
MAX_JSON = 64 * 1024
STATIC = {"phone.js": "text/javascript; charset=utf-8", "phone.css": "text/css; charset=utf-8"}
CALL_TIMEOUT = 20.0
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


# Tailscale gives the devices of a tailnet addresses from the shared range 100.64.0.0/10 (IPv6: fd7a:115c:a1e0::/48,
# which counts as private anyway) – not private addresses, so they are let in only when the user switches it on
TAILNET_V4 = ipaddress.ip_network("100.64.0.0/10")


def allowed_client(ip: str, tailscale: bool = False) -> bool:
    """Only the home network (private, link-local and loopback addresses) – and the tailnet when ``tailscale``."""
    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    if addr.is_private or addr.is_loopback or addr.is_link_local:
        return True
    return bool(tailscale) and isinstance(addr, ipaddress.IPv4Address) and addr in TAILNET_V4


def tailscale_address() -> str:
    """This computer's address in a tailnet (100.x.y.z), or "" when Tailscale is not running here."""
    try:
        from PySide6.QtNetwork import QAbstractSocket, QNetworkInterface

        for iface in QNetworkInterface.allInterfaces():
            flags = iface.flags()
            if not (flags & QNetworkInterface.IsUp and flags & QNetworkInterface.IsRunning):
                continue
            for entry in iface.addressEntries():
                ip = entry.ip()
                if ip.protocol() == QAbstractSocket.IPv4Protocol and ipaddress.ip_address(ip.toString()) in TAILNET_V4:
                    return ip.toString()
    except Exception:  # (no QtNetwork: the address of the host name below)
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            if ipaddress.ip_address(info[4][0]) in TAILNET_V4:
                return info[4][0]
    except (OSError, ValueError):
        pass
    return ""


def qr_png(text: str, scale: int = 6) -> bytes:
    """The QR code of ``text`` as a PNG (segno)."""
    import io

    import segno

    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="png", scale=scale, border=2)
    return buf.getvalue()


class RemoteBridge(QObject):
    """Between the server threads and the app: requests come in as signals (handled in the GUI thread); the app
    keeps ``state`` up to date (a dict replaced as a whole, read by the server threads). ``call`` asks the app's
    ``handler`` (``PhoneApi.handle``) and waits for the answer."""

    pause = Signal()
    resume = Signal()
    cancel = Signal()
    upload = Signal(str, str)  # (saved picture, method) – sketched right away
    _request = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state: dict = {"busy": False, "paused": False, "job": None, "queue": 0, "last": None}
        self.preview_svg = ""
        self.texts: dict = {}
        self.handler = None  # (action, data) -> answer, called in the GUI thread
        self._request.connect(self._run)

    def set_state(self, **changes):
        self.state = {**self.state, **changes}

    def _run(self, box: dict):
        try:
            box["result"] = self.handler(box["action"], box["data"])
        except Exception as exc:  # (an error of one request must not end the server)
            box["error"] = str(exc) or type(exc).__name__
        finally:
            box["done"].set()

    def call(self, action: str, data: dict | None = None, timeout: float | None = None):
        """Run ``handler(action, data)`` in the GUI thread and return its answer (from a server thread)."""
        if self.handler is None:
            raise LookupError("the studio is not connected")
        box = {"action": action, "data": data or {}, "done": threading.Event()}
        self._request.emit(box)
        if not box["done"].wait(CALL_TIMEOUT if timeout is None else timeout):
            raise TimeoutError("the app does not answer")
        if "error" in box:
            raise RuntimeError(box["error"])
        return box["result"]


def _resource(name: str) -> bytes:
    return paths.resource("phone", name).read_bytes()


def page(texts: dict, access: str) -> str:
    """The phone page (``resources/phone/index.html``) with its texts and the access code (as JSON data, read by
    ``phone.js``; nothing runs inline)."""
    cfg = json.dumps({"token": access, "texts": texts, "lang": texts.get("lang", "en")})
    cfg = cfg.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    body = _resource("index.html").decode("utf-8")
    return body.replace("{{lang}}", html.escape(str(texts.get("lang", "en")))).replace("{{config}}", cfg)


PAGE_CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; "
            "connect-src 'self'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'")
SVG_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"


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
        if not allowed_client(self.client_address[0], bool(app_settings().get("remote_tailscale"))):
            self._send(403, b"only from the home network", "text/plain")
            return False
        return True

    def _answer(self, action: str, data: dict):
        """Ask the app (``PhoneApi``) and send its answer: JSON, or a file (``_bytes``)."""
        if not all(c.isalnum() or c == "_" for c in action):
            self._json({"ok": False, "error": "not found"}, 404)
            return
        try:
            result = self.bridge.call(action, data)
        except TimeoutError:
            self._json({"ok": False, "error": "busy"}, 503)
            return
        except Exception as exc:
            self._json({"ok": False, "error": str(exc)}, 500)
            return
        if isinstance(result, dict) and "_bytes" in result:
            headers = {}
            if result.get("_type") == "image/svg+xml":
                headers["Content-Security-Policy"] = SVG_CSP
            if result.get("_name"):
                quoted = urllib.parse.quote(result["_name"])
                headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quoted}"
            self._send(200, result["_bytes"], result["_type"], headers)
        else:
            self._json(result if isinstance(result, dict) else {"ok": True, "result": result},
                       200 if not (isinstance(result, dict) and result.get("ok") is False) else 400)

    def _body(self, limit: int) -> bytes | None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > limit:
            return None
        return self.rfile.read(length)

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
            self._send(200, page(self.bridge.texts, token()).encode("utf-8"), "text/html; charset=utf-8",
                       {"Content-Security-Policy": PAGE_CSP})
            return
        if not self._authorised():
            self._json({"ok": False, "error": "no access"}, 403)
            return
        name = parsed.path.lstrip("/")
        if name in STATIC:
            self._send(200, _resource(name), STATIC[name])
        elif name in ("icon.png", "favicon.ico"):
            self._send(200, paths.resource("app_icon.png").read_bytes(), "image/png")
        elif parsed.path.startswith("/api/get/"):
            self._answer("get_" + parsed.path.rsplit("/", 1)[1], {k: v[0] for k, v in query.items()})
        elif parsed.path.startswith("/api/file/"):
            self._answer("file_" + parsed.path.rsplit("/", 1)[1], {k: v[0] for k, v in query.items()})
        elif parsed.path == "/api/status":
            state = dict(self.bridge.state)
            state["preview"] = str(hash(self.bridge.preview_svg)) if self.bridge.preview_svg else ""
            self._json(state)
        elif parsed.path == "/api/preview.svg":
            svg = self.bridge.preview_svg or '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>'
            self._send(200, svg.encode("utf-8"), "image/svg+xml", {"Content-Security-Policy": SVG_CSP})
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
        elif path == "/api/do":
            raw = self._body(MAX_JSON)
            try:
                data = json.loads(raw or b"")
            except ValueError:
                data = None
            if not isinstance(data, dict) or not isinstance(data.get("action"), str):
                self._json({"ok": False, "error": "bad request"}, 400)
                return
            self._answer("do_" + data["action"], data)
        elif path == "/api/details":
            raw = self._body(MAX_UPLOAD)
            if raw is None or not raw.startswith(b"\x89PNG"):
                self._json({"ok": False, "error": "not a picture"}, 415)
                return
            self._answer("set_details", {"png": raw})
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
        if self.headers.get("X-Target") == "studio":  # the picture of the studio (the phone sets it up)
            self._answer("set_image", {"path": dest})
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
