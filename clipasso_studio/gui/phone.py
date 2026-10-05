"""The phone side of the app: the remote page (gui/remote.py) and the Telegram messages (gui/telegram.py), wired to
the job controller – the main window makes one ``PhoneLink``."""

from __future__ import annotations

import math
import os

from PySide6.QtCore import QObject, Signal

from .. import settings_schema as schema
from ..engine import jobs
from . import methods_ui, remote, telegram
from .app_settings import app_settings
from .i18n import i18n, tr


def _eta(seconds: float) -> str:
    if seconds is None or (isinstance(seconds, float) and (math.isnan(seconds) or math.isinf(seconds))):
        return ""
    seconds = max(0, int(seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class PhoneLink(QObject):
    toast = Signal(str, str)

    def __init__(self, controller, settings_provider=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.settings_provider = settings_provider  # () -> the studio's settings (sketches sent from the phone)
        self.bridge = remote.RemoteBridge(self)
        self.server: remote.RemoteServer | None = None
        self.error = ""
        self.notifier = telegram.Notifier(self)
        self.bridge.pause.connect(controller.pause)
        self.bridge.resume.connect(controller.resume)
        self.bridge.cancel.connect(controller.cancel)
        self.bridge.upload.connect(self._upload)
        controller.queue_changed.connect(self._update)
        controller.job_started.connect(lambda _job: self._update())
        controller.job_event.connect(self._event)
        controller.job_finished.connect(self._finished)
        i18n.language_changed.connect(lambda _: self.retranslate())
        self.retranslate()
        self.apply_settings()

    # ------------------------------------------------------------------ remote server
    def apply_settings(self) -> str:
        """Start or stop the phone page as the settings say; returns an error text ("" when fine)."""
        st = app_settings()
        want = bool(st.get("remote_on"))
        port = int(st.get("remote_port", remote.DEFAULT_PORT) or remote.DEFAULT_PORT)
        if self.server is not None and (not want or self.server.port != port):
            self.server.stop()
            self.server = None
        self.error = ""
        if want and self.server is None:
            remote.token()  # (made here, in the GUI thread)
            try:
                self.server = remote.RemoteServer(self.bridge, port).start()
            except OSError as exc:
                self.error = tr("ui.phone.port_busy", port=port, error=str(exc))
                self.server = None
        return self.error

    def running(self) -> bool:
        return self.server is not None

    def retranslate(self):
        keys = ("pause", "resume", "cancel", "cancel_ask", "new", "send", "pick", "sending", "queued_ok", "failed",
                "running", "paused", "done", "idle", "eta", "queued", "offline")
        texts = {k: tr(f"ui.phone.page.{k}") for k in keys}
        texts.update({f"method_{m}": methods_ui.name(m) for m in remote.METHODS})
        texts["lang"] = i18n.lang
        self.bridge.texts = texts

    # ------------------------------------------------------------------ state for the page
    def _update(self):
        c = self.controller
        job = c.current if c.is_busy() else None
        waiting = sum(1 for j in c.jobs if j.status == "queued")
        self.bridge.set_state(
            busy=job is not None, paused=bool(job and job.status == "paused"), queue=waiting,
            job={"name": job.name, "method": methods_ui.name(job.settings.get("method", "clipasso")),
                 "progress": round(job.progress, 4), "eta": _eta(job.eta)} if job else None)

    def _event(self, job, kind, data):
        if kind == "preview" and isinstance(data, dict) and data.get("svg"):
            self.bridge.preview_svg = data["svg"]
        if kind in ("iteration", "preview"):
            self._update()

    def _finished(self, job):
        summary = jobs.job_summary(job.job_dir) if job.job_dir and os.path.isdir(job.job_dir) else None
        sketch = job.best_svg or (summary or {}).get("best_svg") or ""
        if job.status == "done" and sketch and os.path.isfile(sketch):
            try:
                with open(jobs.sketch_file(os.path.dirname(sketch), sketch), encoding="utf-8") as f:
                    self.bridge.preview_svg = f.read()
            except OSError:
                pass
        self.bridge.set_state(last={"name": job.name, "status": job.status})
        self._update()
        try:
            self.notifier.job_finished(job, summary)
        except Exception as exc:  # (a message must never disturb the queue)
            self.toast.emit(tr("ui.telegram.failed", error=str(exc)), "error")

    def _upload(self, path: str, method: str):
        """A photo from the phone: sketched with the studio's settings (or the method's own when it differs)."""
        studio = self.settings_provider() if self.settings_provider else None
        if studio and studio.get("method") == method:
            settings = dict(studio)
        else:
            settings = schema.default_settings(method)
        self.controller.enqueue(path, settings, start=True)
        self.toast.emit(tr("ui.phone.received", name=os.path.basename(path)), "success")

    def shutdown(self):
        if self.server is not None:
            self.server.stop()
            self.server = None
        self.notifier.stop()
