"""Job queue on top of :class:`clipasso_studio.engine.runner.JobRunner` (Qt signals)."""

from __future__ import annotations

import itertools
import os
import sys
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QTimer, Signal

from .. import settings_schema as schema
from ..engine import jobs
from ..engine.runner import JobRunner
from .app_settings import app_settings

_ids = itertools.count(1)


@dataclass
class QueuedJob:
    target: str
    settings: dict
    id: int = field(default_factory=lambda: next(_ids))
    status: str = "queued"  # queued | running | paused | done | failed | cancelled
    job_dir: str = ""
    best_svg: str = ""
    message: str = ""
    seed_progress: dict = field(default_factory=dict)
    seed_best: dict = field(default_factory=dict)
    started: float = 0.0
    finished: float = 0.0
    eta: float = float("nan")
    device: str = ""
    resume_dir: str = ""  # "Continue": the interrupted job folder
    live: dict = field(default_factory=dict, repr=False, compare=False)  # latest previews (studio)

    @property
    def name(self) -> str:
        return os.path.basename(self.target)

    @property
    def seeds(self) -> list[int]:
        return jobs.job_seeds(self.settings)

    @property
    def progress(self) -> float:
        seeds = self.seeds
        if not seeds:
            return 0.0
        return sum(self.seed_progress.get(s, 0.0) for s in seeds) / len(seeds)

    def to_json(self) -> dict:
        data = {"target": self.target, "settings": self.settings}
        if self.resume_dir:
            data["resume_dir"] = self.resume_dir
        return data


def _keep_awake(on: bool) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        es_continuous, es_system_required = 0x80000000, 0x00000001
        flags = es_continuous | (es_system_required if on else 0)
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except Exception:
        pass


class JobController(QObject):
    queue_changed = Signal()
    job_started = Signal(object)
    job_event = Signal(object, str, dict)
    job_finished = Signal(object)
    queue_idle = Signal(object)  # the queue ran out on its own (the last job, not cancelled by the user)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.runner = JobRunner()
        self.jobs: list[QueuedJob] = []
        self.current: QueuedJob | None = None
        self.auto_start = True
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._poll)
        self._restore_queue()

    # ------------------------------------------------------------------ queue
    def continue_job(self, job_dir: str, start: bool = True) -> QueuedJob | None:
        """Queue an interrupted / cancelled job again: finished sketches are kept, the rest continues
        from its checkpoints. None when there is nothing to continue or it is already queued."""
        norm = os.path.normcase(os.path.abspath(job_dir))
        for j in self.jobs:
            if j.status in ("queued", "running", "paused") and norm in (
                    os.path.normcase(os.path.abspath(j.resume_dir or "-")),
                    os.path.normcase(os.path.abspath(j.job_dir or "-"))):
                return None
        state = jobs.read_state(job_dir)
        if not state or not jobs.remaining_seeds(job_dir):
            return None
        target = jobs.reopen_input(job_dir, state.get("target", ""))
        if not target:
            return None
        return self.enqueue(target, state["settings"], start=start, resume_dir=job_dir)

    def enqueue(self, target: str, settings: dict, start: bool = True, resume_dir: str = "") -> QueuedJob:
        job = QueuedJob(target=target, settings=schema.normalize(settings), resume_dir=resume_dir)
        self.jobs.append(job)
        self._persist_queue()
        self.queue_changed.emit()
        if start and not self.is_busy():
            self.start_next()
        return job

    def pending(self) -> list[QueuedJob]:
        return [j for j in self.jobs if j.status == "queued"]

    def remove(self, job_id: int) -> None:
        self.jobs = [j for j in self.jobs if not (j.id == job_id and j.status != "running")]
        self._persist_queue()
        self.queue_changed.emit()

    def move(self, job_id: int, delta: int) -> None:
        idx = next((i for i, j in enumerate(self.jobs) if j.id == job_id), None)
        if idx is None:
            return
        new = min(max(idx + delta, 0), len(self.jobs) - 1)
        self.jobs.insert(new, self.jobs.pop(idx))
        self._persist_queue()
        self.queue_changed.emit()

    def clear_finished(self) -> None:
        self.jobs = [j for j in self.jobs if j.status in ("queued", "running", "paused")]
        self.queue_changed.emit()

    def active_dirs(self) -> set[str]:
        """Job folders the queue is working on or will continue (normalised): not "interrupted" in the
        gallery, and not to be deleted."""
        out = set()
        for j in self.jobs:
            if j.status in ("running", "paused") or (j.status == "queued" and j.resume_dir):
                for d in (j.job_dir, j.resume_dir):
                    if d:
                        out.add(os.path.normcase(os.path.abspath(d)))
        return out

    def is_busy(self) -> bool:
        return self.current is not None and self.current.status in ("running", "paused")

    def start_next(self) -> QueuedJob | None:
        if self.is_busy():
            return None
        nxt = next((j for j in self.jobs if j.status == "queued"), None)
        if nxt is None:
            _keep_awake(False)
            return None
        out = app_settings().get("output_dir")
        try:
            self.runner.start(nxt.settings, nxt.target, out, job_dir=nxt.resume_dir)
        except Exception as exc:  # e.g. output folder not writable
            nxt.status = "failed"
            nxt.message = str(exc)
            self.queue_changed.emit()
            self.job_finished.emit(nxt)
            return None
        nxt.status = "running"
        nxt.job_dir = self.runner.job.job_dir
        nxt.started = time.time()
        self.current = nxt
        if app_settings().get("keep_awake"):
            _keep_awake(True)
        self._timer.start()
        self._persist_queue()
        self.queue_changed.emit()
        self.job_started.emit(nxt)
        return nxt

    # ---------------------------------------------------------------- control
    def pause(self):
        if self.current and self.current.status == "running":
            self.runner.pause()
            self.current.status = "paused"
            self.queue_changed.emit()

    def resume(self):
        if self.current and self.current.status == "paused":
            self.runner.resume()
            self.current.status = "running"
            self.queue_changed.emit()

    def cancel(self):
        if self.current and self.current.status in ("running", "paused"):
            self.current.message = "cancel"
            self.runner.cancel()
            self.queue_changed.emit()

    def shutdown(self):
        self._timer.stop()
        self.runner.kill()
        _keep_awake(False)

    # ----------------------------------------------------------------- events
    def _poll(self):
        job = self.current
        if job is None:
            self._timer.stop()
            return
        for kind, data in self.runner.poll():
            if kind == "job_start":
                job.device = data.get("device", "")
            elif kind == "iteration":
                seed = data["seed"]
                job.seed_progress[seed] = (data["it"] + 1) / max(data["total"], 1)
                job.eta = data.get("eta", float("nan"))
            elif kind == "seed_done":
                job.seed_progress[data["seed"]] = 1.0
                job.seed_best[data["seed"]] = data.get("best_loss")
            elif kind == "job_done":
                job.best_svg = data.get("best_svg", "")
                job.status = "cancelled" if job.message == "cancel" else "done"
            elif kind == "error":
                job.message = data.get("message", "")
            elif kind in ("job_failed", "job_ended"):
                if job.status not in ("done", "cancelled"):
                    job.status = "cancelled" if job.message == "cancel" else "failed"
            self.job_event.emit(job, kind, data)
        if not self.runner.is_running():
            if job.status in ("running", "paused"):
                job.status = "cancelled" if job.message == "cancel" else "failed"
            job.finished = time.time()
            self.current = None
            self._timer.stop()
            self._persist_queue()
            self.queue_changed.emit()
            self.job_finished.emit(job)
            if self.auto_start:
                self.start_next()
            if not self.is_busy():
                _keep_awake(False)
                if not self.pending() and job.status != "cancelled":
                    self.queue_idle.emit(job)

    # ------------------------------------------------------------ persistence
    def _persist_queue(self):
        app_settings().set("queue", [j.to_json() for j in self.jobs if j.status == "queued"])

    def _restore_queue(self):
        for item in app_settings().get("queue") or []:
            try:
                if os.path.isfile(item["target"]):
                    resume = item.get("resume_dir", "")
                    if resume and not os.path.isdir(resume):
                        continue
                    self.jobs.append(QueuedJob(target=item["target"], settings=schema.normalize(item["settings"]),
                                               resume_dir=resume))
            except (KeyError, TypeError, ValueError):
                continue
