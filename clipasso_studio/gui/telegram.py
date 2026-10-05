"""A Telegram message when a job is done or failed – the best sketch as a picture, its name and how long it took –
through the user's own bot (Telegram Bot API, only the standard library).

Setting it up: create a bot with @BotFather, paste its token, press "Connect" and send the bot /start; the app reads
the chat from the bot's updates. The token stays in the app settings of this computer (never in diagnostics or
problem reports). Messages are sent one after the other in a thread of their own, so a slow network never holds up
the app."""

from __future__ import annotations

import json
import queue
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from PySide6.QtCore import QObject, Signal

from .app_settings import app_settings

API = "https://api.telegram.org/bot{token}/{method}"
TIMEOUT = 20.0
CONNECT_SECONDS = 90  # how long "Connect" waits for /start
PHOTO_SIZE = 1024
TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")


class TelegramError(Exception):
    pass


def valid_token(token: str) -> bool:
    return bool(TOKEN_RE.match((token or "").strip()))


def _multipart(fields: dict, file_field: str, filename: str, data: bytes, mime: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    out = []
    for key, value in fields.items():
        out.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    out.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
               f"Content-Type: {mime}\r\n\r\n".encode() + data + b"\r\n")
    out.append(f"--{boundary}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={boundary}"


def call(token: str, method: str, params: dict | None = None, photo: bytes | None = None,
         timeout: float = TIMEOUT) -> object:
    """One Bot API call; its ``result``. Errors (also network errors) as TelegramError – without the token."""
    if not valid_token(token):
        raise TelegramError("invalid bot token")
    url = API.format(token=token.strip(), method=method)
    params = {k: v for k, v in (params or {}).items() if v is not None}
    if photo is not None:
        body, ctype = _multipart(params, "photo", "sketch.png", photo, "image/png")
    else:
        body, ctype = urllib.parse.urlencode(params).encode(), "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers={"Content-Type": ctype}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            data = json.loads(exc.read().decode("utf-8"))
        except (OSError, ValueError):
            raise TelegramError(f"HTTP {exc.code}") from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        raise TelegramError(f"network: {reason}") from None
    if not isinstance(data, dict) or not data.get("ok"):
        raise TelegramError(str((data or {}).get("description") or "Telegram refused the request"))
    return data.get("result")


def bot_name(token: str) -> str:
    """The bot's user name (checks the token)."""
    me = call(token, "getMe") or {}
    return str(me.get("username") or "")


def find_chat(token: str, seconds: float = CONNECT_SECONDS, cancel=None) -> tuple[str, str] | None:
    """Wait (long polling) until someone sends the bot /start; returns (chat id, name) – None after ``seconds``."""
    offset = None
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cancel and cancel():
            return None
        wait = max(1, min(20, int(end - time.monotonic())))
        updates = call(token, "getUpdates", {"timeout": wait, "offset": offset,
                                             "allowed_updates": json.dumps(["message"])}, timeout=wait + 10) or []
        for u in updates:
            offset = int(u.get("update_id", 0)) + 1
            msg = u.get("message") or {}
            if str(msg.get("text") or "").strip().startswith("/start"):
                chat = msg.get("chat") or {}
                name = chat.get("first_name") or chat.get("title") or chat.get("username") or ""
                if offset is not None:  # mark the updates as read
                    call(token, "getUpdates", {"offset": offset, "timeout": 0})
                return str(chat.get("id")), str(name)
    return None


def send(token: str, chat: str, text: str, png: bytes | None = None) -> None:
    if png:
        call(token, "sendPhoto", {"chat_id": chat, "caption": text[:1024]}, photo=png, timeout=60)
    else:
        call(token, "sendMessage", {"chat_id": chat, "text": text[:4096]})


def configured() -> bool:
    st = app_settings()
    return bool(st.get("telegram_on") and valid_token(st.get("telegram_token") or "") and st.get("telegram_chat"))


def _minutes(seconds: float) -> str:
    seconds = int(round(seconds or 0))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def job_message(job, summary: dict | None = None) -> tuple[str, str]:
    """(text, sketch file) of a finished or failed job ("" when it has no sketch)."""
    from . import methods_ui
    from .i18n import tr

    summary = summary or {}
    seconds = (job.finished - job.started) if job.finished and job.started else float(summary.get("seconds") or 0)
    method = methods_ui.name(summary.get("method") or job.settings.get("method") or "clipasso")
    if job.status == "done":
        score = summary.get("clip_score")
        text = tr("ui.telegram.msg_done", name=job.name, method=method, time=_minutes(seconds),
                  score=f"{score:.1f}" if isinstance(score, (int, float)) else "–")
    else:
        text = tr("ui.telegram.msg_failed", name=job.name, method=method, error=(job.message or job.status)[:300])
    sketch = job.best_svg or summary.get("best_svg") or ""
    return text, sketch


def sketch_png(svg_path: str, size: int = PHOTO_SIZE) -> bytes | None:
    """The sketch as a PNG in the brush style and on the paper of the export (GUI thread)."""
    import os

    if not svg_path or not os.path.isfile(svg_path):
        return None
    from . import export

    st = app_settings()
    try:
        vignette = int(st.get("export_vignette", 0) or 0) / 100
    except (TypeError, ValueError):
        vignette = 0.0
    background = st.get("export_background") or "#FFFFFF"
    background = "#FFFFFF" if background == "transparent" else background
    with open(svg_path, encoding="utf-8") as f:
        raw = f.read()
    stroke = st.get("export_stroke", "#000000")
    svg = export.stylize_svg(export.restyle_svg(raw, None if str(stroke).lower() == "#000000" else stroke,
                                                float(st.get("export_width", 1.0) or 1.0)),
                             st.get("export_style", "plain"))
    from PySide6.QtGui import QColor

    img = export.svg_to_qimage(svg, size, QColor(background),
                               paper={"kind": st.get("export_paper", "none"), "vignette": vignette})
    return export._png_bytes(img)


class Notifier(QObject):
    """Sends the messages in a thread of its own, one after the other; ``sent(ok, error)`` after each."""

    sent = Signal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None

    def _ensure_thread(self):
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, name="telegram", daemon=True)
            self._thread.start()

    def _run(self):
        while True:
            item = self._queue.get()
            if item is None:
                return
            token, chat, text, png = item
            try:
                send(token, chat, text, png)
                self.sent.emit(True, "")
            except TelegramError as exc:
                self.sent.emit(False, str(exc))

    def message(self, text: str, png: bytes | None = None, token: str | None = None, chat: str | None = None):
        st = app_settings()
        token = token or st.get("telegram_token") or ""
        chat = chat or st.get("telegram_chat") or ""
        if not (valid_token(token) and chat):
            return
        self._ensure_thread()
        self._queue.put((token, str(chat), text, png))

    def job_finished(self, job, summary: dict | None = None) -> bool:
        """A message for a finished or failed job, if Telegram is on and wanted for this outcome."""
        st = app_settings()
        if not configured():
            return False
        if job.status == "done" and not st.get("telegram_done", True):
            return False
        if job.status in ("failed",) and not st.get("telegram_failed", True):
            return False
        if job.status not in ("done", "failed"):
            return False
        text, sketch = job_message(job, summary)
        png = None
        if job.status == "done" and st.get("telegram_photo", True):
            try:
                png = sketch_png(sketch)
            except Exception:  # (a sketch that cannot be drawn: the text still goes)
                png = None
        self.message(text, png)
        return True

    def stop(self):
        if self._thread is not None and self._thread.is_alive():
            self._queue.put(None)
