"""Long file work in the background – moving the results or the models to another folder, unpacking an update –
with a progress strip in the main window instead of a window that blocks the whole app. Only what needs those files
waits: new jobs start when a move is done (the queue holds them), the gallery waits while the results move and
model downloads wait while the models move."""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, Signal

KINDS = ("output", "models", "update")
HOLD_JOBS = ("output", "models")  # work during which no job may start


class Work(QObject):
    changed = Signal()  # work started, made progress or ended
    ended = Signal(str, bool)  # (kind, it went well)

    def __init__(self):
        super().__init__()
        self.jobs: dict[str, dict] = {}  # kind -> {"text", "done", "total"}

    def busy(self, *kinds: str) -> bool:
        """Some work of these kinds (any kind when none is named) is running."""
        return any(k in self.jobs for k in (kinds or tuple(self.jobs)))

    def holds_jobs(self) -> bool:
        return self.busy(*HOLD_JOBS)

    def start(self, kind: str, text: str, fn, *args, on_done=None, on_error=None, **kwargs) -> bool:
        """Run ``fn(*args, progress=…, **kwargs)`` in the background (``dialogs.run_in_thread``); ``on_done(result)``
        and ``on_error(message)`` are called in the GUI thread. False: work of this kind is running already."""
        from . import dialogs

        if kind in self.jobs:
            return False
        self.jobs[kind] = {"text": text, "done": 0, "total": 0, "started": time.time()}
        self.changed.emit()
        dialogs.run_in_thread(self, fn, *args, on_progress=lambda d, t: self._progress(kind, d, t),
                              on_done=lambda r: self._end(kind, True, r, on_done),
                              on_error=lambda m: self._end(kind, False, m, on_error), **kwargs)
        return True

    def _progress(self, kind: str, done: int, total: int):
        if kind in self.jobs:
            self.jobs[kind].update(done=int(done), total=int(total))
            self.changed.emit()

    def _end(self, kind: str, ok: bool, arg, callback):
        self.jobs.pop(kind, None)
        self.changed.emit()
        if callback is not None:
            callback(arg)
        self.ended.emit(kind, ok)

    def fraction(self, kind: str) -> float | None:
        """How far the work is (0..1), None when it cannot be measured."""
        job = self.jobs.get(kind)
        if not job or job["total"] <= 0:
            return None
        return max(0.0, min(1.0, job["done"] / job["total"]))

    def wait(self, timeout: float = 60.0) -> bool:
        """Run the event loop until all work has ended (tests, and quitting the app)."""
        from PySide6.QtWidgets import QApplication

        end = time.time() + timeout
        while self.jobs and time.time() < end:
            QApplication.processEvents()
            time.sleep(0.01)
        return not self.jobs


_work: Work | None = None


def work() -> Work:
    global _work
    if _work is None:
        _work = Work()
    return _work
