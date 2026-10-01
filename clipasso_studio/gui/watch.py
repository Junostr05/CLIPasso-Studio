"""Watched folder: images saved into a chosen folder are sketched by themselves and exported.

A new image counts once its size has not changed for ``STABLE_S`` seconds (a copy or a camera upload
may still be writing it). It is queued with the studio's current settings or a saved preset; when its
job is done, its best sketch is exported in the chosen formats, and the image can be moved into the
subfolder ``done``. Images already handled are remembered (``watch_state.json`` in the app data), so a
restart does not sketch them again.
"""

from __future__ import annotations

import json
import os
import shutil
import time

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal

from .. import paths
from .. import settings_schema as schema
from ..engine import jobs
from .app_settings import app_settings
from .drop import IMAGE_EXT

STATE_FILE = "watch_state.json"
STABLE_S = 2.0
POLL_MS = 10_000  # also without a change notification (network drives, some sync tools)
CHECK_MS = 500
DONE_DIR = "done"
EXPORT_DIR = "sketches"
FORMATS = ("svg", "svg1", "png", "pdf")


def config() -> dict:
    s = app_settings()
    formats = s.get("watch_formats") or ["png"]
    return {"enabled": bool(s.get("watch_enabled", False)), "folder": s.get("watch_folder") or "",
            "preset": s.get("watch_preset") or "studio",
            "formats": [f for f in formats if f in FORMATS] or ["png"],
            "export_dir": s.get("watch_export_dir") or "", "move_done": bool(s.get("watch_move_done", False))}


def load_preset(path: str) -> dict:
    """Settings from a preset file (as the studio saves it)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("not a preset")
    return schema.normalize(data)


class FolderWatcher(QObject):
    message = Signal(str, dict)  # (text key, parameters) for a notice in the window

    def __init__(self, controller, settings_provider, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.settings_provider = settings_provider
        self._fs = QFileSystemWatcher(self)
        self._fs.directoryChanged.connect(lambda _: QTimer.singleShot(200, self.scan))
        self._poll = QTimer(self, interval=POLL_MS)
        self._poll.timeout.connect(self.scan)
        self._check = QTimer(self, interval=CHECK_MS)
        self._check.timeout.connect(self._check_pending)
        self._pending: dict[str, tuple[str, int, int, float]] = {}  # key -> (path, size, mtime, unchanged since)
        self.jobs: dict[int, str] = {}  # queued job id -> image
        self._state = self._load_state()
        controller.job_finished.connect(self._job_finished)
        self.reconfigure()

    # ------------------------------------------------------------------ state
    @staticmethod
    def state_path():
        return paths.user_data_dir() / STATE_FILE

    def _load_state(self) -> dict:
        try:
            with open(self.state_path(), encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_state(self) -> None:
        path = self.state_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(str(path) + ".tmp", "w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=1)
            os.replace(str(path) + ".tmp", path)
        except OSError:
            pass

    # ------------------------------------------------------------------ watching
    def active(self) -> bool:
        cfg = config()
        return cfg["enabled"] and os.path.isdir(cfg["folder"])

    def reconfigure(self) -> None:
        """Follow the settings (folder, on / off)."""
        if self._fs.directories():
            self._fs.removePaths(self._fs.directories())
        self._pending.clear()
        if not self.active():
            self._poll.stop()
            self._check.stop()
            return
        self._fs.addPath(config()["folder"])
        self._poll.start()
        self.scan()

    @staticmethod
    def _key(path: str) -> str:
        return os.path.normcase(os.path.abspath(path))

    def scan(self) -> None:
        """Note new or changed images of the folder (they are queued once they stay unchanged)."""
        if not self.active():
            return
        folder = config()["folder"]
        waiting = {self._key(p) for p in self.jobs.values()}
        now = time.monotonic()
        try:
            names = os.listdir(folder)
        except OSError:
            return
        for name in names:
            path = os.path.join(folder, name)
            if os.path.splitext(name)[1].lower() not in IMAGE_EXT or not os.path.isfile(path):
                continue
            key = self._key(path)
            try:
                st = os.stat(path)
            except OSError:
                continue
            stamp = (int(st.st_size), int(st.st_mtime_ns))
            if key in waiting or self._state.get(key) == list(stamp):
                continue  # queued, or handled before
            old = self._pending.get(key)
            if old is None or old[1:3] != stamp:
                self._pending[key] = (path, *stamp, now)
        if self._pending and not self._check.isActive():
            self._check.start()

    def _check_pending(self) -> None:
        now = time.monotonic()
        for key, (path, size, mtime, since) in list(self._pending.items()):
            try:
                st = os.stat(path)
            except OSError:
                del self._pending[key]  # gone again
                continue
            stamp = (int(st.st_size), int(st.st_mtime_ns))
            if stamp != (size, mtime) or stamp[0] == 0:
                self._pending[key] = (path, *stamp, now)  # still being written
            elif now - since >= STABLE_S:
                del self._pending[key]
                self._queue(path, stamp)
        if not self._pending:
            self._check.stop()

    def _settings(self) -> dict:
        preset = config()["preset"]
        if preset and preset != "studio":
            try:
                return load_preset(preset)
            except (OSError, ValueError):
                self.message.emit("ui.watch.preset_error", {"path": os.path.basename(preset)})
        return dict(self.settings_provider())

    def _queue(self, path: str, stamp: tuple[int, int]) -> None:
        job = self.controller.enqueue(path, self._settings(), start=not self.controller.is_busy())
        self.jobs[job.id] = path
        self._state[self._key(path)] = list(stamp)  # (also after a restart: not again)
        self._save_state()
        self.message.emit("ui.watch.queued", {"name": os.path.basename(path)})

    # ------------------------------------------------------------------ results
    def _job_finished(self, job) -> None:
        path = self.jobs.pop(job.id, None)
        if path is None or job.status != "done" or not job.job_dir:
            return
        cfg = config()
        summary = jobs.job_summary(job.job_dir)
        written = 0
        if summary is not None:
            from . import export

            folder = cfg["export_dir"] or os.path.join(cfg["folder"], EXPORT_DIR)
            for fmt in cfg["formats"]:
                try:
                    written += export.export_batch([(job.job_dir, summary)], folder, fmt=fmt)
                except Exception as exc:  # noqa: BLE001 - shown, the watching goes on
                    self.message.emit("ui.watch.export_error", {"name": os.path.basename(path), "error": str(exc)})
        if cfg["move_done"] and os.path.isfile(path):
            done = os.path.join(os.path.dirname(path), DONE_DIR)
            try:
                os.makedirs(done, exist_ok=True)
                dest = os.path.join(done, os.path.basename(path))
                stem, ext = os.path.splitext(dest)
                n = 1
                while os.path.exists(dest):
                    n += 1
                    dest = f"{stem}-{n}{ext}"
                shutil.move(path, dest)
            except OSError:
                pass
        self.message.emit("ui.watch.done", {"name": os.path.basename(path), "n": written})
