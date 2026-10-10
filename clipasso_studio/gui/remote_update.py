"""An update started from the phone (3.8): look for it, download and check it, install it and start again – without
a single question on the PC, which nobody may be sitting at.

The phone asks for the PIN once more before it installs (``remote.py`` checks it, with the brakes of the sign-in).
A running job is stopped and continued after the restart, together with the queue (``update_pending`` in the
settings); the phone page comes back by itself – the address, the access code and the PIN stay the same.

An installation for all users cannot update itself unattended: Windows asks for an administrator on the PC. Then
the phone only downloads the update, and the PC installs it with one click (its update bar)."""

from __future__ import annotations

import json
import os
import sys
import time

from PySide6.QtCore import QObject, QTimer, Signal

from .. import __version__
from . import background, updates
from .app_settings import app_settings
from .i18n import tr

# idle → checking → found | current | failed; found → downloading → (unpacking) → stopping → restarting;
# all users: found → downloading → downloaded (installed on the PC); cancelled / failed on the way
BUSY = ("checking", "downloading", "unpacking", "stopping", "restarting")
PENDING = "update_pending"  # setting: what to do after the restart ({"from", "to", "at", "resume", "run_queue"})
STOP_WAIT_S = 120  # at most this long for files being moved before the update gives up


class Updater(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.window = None  # the main window (it closes the app); set by it
        self.phase = "idle"
        self.release: dict | None = None
        self.done, self.total = 0, 0
        self.error = ""
        self.last: dict | None = None  # the update before this start: {"ok", "from", "to"} (shown on the phone)
        self._cancel = False
        self._download_only = False
        self._stop_until = 0.0

    # ------------------------------------------------------------------ state for the phone
    def _set(self, phase: str, error: str = "") -> None:
        self.phase, self.error = phase, error
        self.changed.emit()

    def install_mode(self) -> str:
        """How this app can update itself: "auto" (download, install and restart from the phone), "download" (only
        download – an installation for all users needs an administrator on the PC) or "none" (run from source)."""
        edition, mode = updates.build_info()
        if mode == "dev":
            return "none"
        if mode == "installed" and updates.all_users_install(os.path.dirname(sys.executable), edition):
            return "download"
        return "auto"

    def snapshot(self) -> dict:
        rel = self.release or {}
        return {"version": __version__, "phase": self.phase, "error": self.error,
                "latest": rel.get("tag", "").lstrip("v"), "notes": rel.get("body", ""),
                "can_install": bool(rel) and updates.can_install(rel), "mode": self.install_mode(),
                "done": self.done, "total": self.total, "last": self.last}

    def busy(self) -> bool:
        return self.phase in BUSY

    # ------------------------------------------------------------------ steps
    def check(self, url: str | None = None) -> bool:
        from . import dialogs

        if self.busy():
            return False
        self.release = None
        self._set("checking")

        def done(text: str):
            try:
                result = json.loads(text)
            except ValueError:
                result = {"status": "error"}
            if result.get("status") == "newer":
                self.release = result["release"]
                self._set("found")
            elif result.get("status") == "current":
                self._set("current")
            else:
                self._set("failed", tr("ui.update.check_failed"))

        dialogs.run_in_thread(self, updates.check_now, url=url, on_done=done,
                              on_error=lambda msg: self._set("failed", msg or tr("ui.update.check_failed")))
        return True

    def install(self) -> bool:
        """Download the update found by :meth:`check` and – unless an administrator is needed – install it."""
        if self.busy() or self.phase != "found" or not self.release:
            return False
        mode = self.install_mode()
        if mode == "none" or not updates.can_install(self.release):
            self._set("failed", tr("ui.remote_update.not_here"))
            return False
        if background.work().busy("update"):
            self._set("failed", tr("ui.remote_update.work_busy"))
            return False
        self._cancel, self._download_only = False, mode == "download"
        self.done = self.total = 0
        self._set("downloading")
        version = self.release["tag"].lstrip("v")
        return background.work().start(
            "update", tr("ui.remote_update.downloading", version=version), self._download, self.release,
            on_done=self._downloaded, on_error=self._failed)

    def cancel(self) -> bool:
        """Stop the download or unpacking (what is downloaded stays: it continues next time)."""
        if self.phase not in ("downloading", "unpacking"):
            return False
        self._cancel = True
        return True

    def _download(self, release: dict, progress=None) -> str:
        def prog(done, total):
            self.done, self.total = int(done), int(total)
            if progress is not None:
                progress(done, total)

        return updates.download_update(release, progress=prog, cancel=lambda: self._cancel)

    def _failed(self, message: str) -> None:
        if self._cancel:
            self._set("cancelled")
        else:
            self._set("failed", message or tr("ui.error"))

    def _downloaded(self, path: str) -> None:
        if self._cancel:
            self._set("cancelled")
            return
        if self._download_only:  # installed on the PC (its update bar offers it; the files are there and checked)
            self._set("downloaded")
            if self.window is not None:
                self.window.update_bar.show_release(self.release)
            return
        edition, mode = updates.build_info()
        version = self.release["tag"].lstrip("v")
        if mode in ("portable", "portable-zip"):
            self._set("unpacking")

            def place(progress=None):
                if mode == "portable":
                    return updates.place_portable(path, version)
                return updates.place_portable_zip(path, version, progress=progress)

            background.work().start("update", tr("ui.update.placing" if mode == "portable" else "ui.update.unpacking"),
                                    place, on_done=lambda placed: self._restart(placed, mode),
                                    on_error=self._failed)
            return
        self._restart(path, mode)

    def _restart(self, path: str, mode: str) -> None:
        """Stop the job (it continues after the restart), wait for files being moved, then install and restart."""
        if self._cancel:
            self._set("cancelled")
            return
        if not path or path == "None":
            self._set("failed", tr("ui.error"))
            return
        if self.phase != "stopping":
            self._set("stopping")
            self._stop_until = time.time() + STOP_WAIT_S
        if background.work().busy():  # a folder is being moved: it must not stay half-moved
            if time.time() > self._stop_until:
                self._set("failed", tr("ui.work.quit_wait"))
                return
            QTimer.singleShot(1000, lambda: self._restart(path, mode))
            return
        self._set("restarting")
        window = self.window
        if window is None:
            self._set("failed", tr("ui.error"))
            return
        QTimer.singleShot(400, lambda: window.restart_for_update(path, mode, self.release["tag"].lstrip("v")))

    # ------------------------------------------------------------------ after the restart
    def finish_pending(self, controller) -> dict | None:
        """At the start: an update from the phone happened before it – continue the queue where it was and keep the
        outcome for the phone ("updated to …" or "the update did not work")."""
        st = app_settings()
        pending = st.get(PENDING)
        if not isinstance(pending, dict):
            return None
        st.set(PENDING, None)
        from ..engine import jobs

        for job_dir in pending.get("resume") or []:  # (continued below – not asked about at the start)
            if isinstance(job_dir, str) and os.path.isdir(job_dir):
                jobs.mark_asked(job_dir)
        ok = updates.parse_version(__version__) > updates.parse_version(str(pending.get("from", "")) or "0")
        self.last = {"ok": ok, "from": pending.get("from", ""), "to": __version__ if ok else pending.get("to", "")}
        if pending.get("run_queue"):
            controller.start_next()
        self.changed.emit()
        return self.last


def write_pending(target_version: str, resume: list[str], run_queue: bool) -> None:
    app_settings().set(PENDING, {"from": __version__, "to": target_version, "at": time.time(), "resume": resume,
                                 "run_queue": bool(run_queue)})


_updater: Updater | None = None


def updater() -> Updater:
    """One for the app (it outlives a rebuilt main window, e.g. after a theme change)."""
    global _updater
    if _updater is None:
        _updater = Updater()
    return _updater
