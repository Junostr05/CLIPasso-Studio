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
from . import methods_ui
from .app_settings import app_settings

_ids = itertools.count(1)


def new_job_settings(settings: dict) -> dict:
    """The settings of a new job: normalised, with the switches of the app's settings (the experimental sketch
    improvement – kept with the job, so continuing it later does the same)."""
    s = schema.normalize(settings)
    if schema.method_of(s) in schema.SKETCH_GUIDE_METHODS:
        s["sketch_guide"] = bool(app_settings().get("experimental_sketch", False))
    return s


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
    devices: set = field(default_factory=set, repr=False, compare=False)  # one per worker (several graphics cards)
    resume_dir: str = ""  # "Continue": the interrupted job folder
    oom: bool = False  # failed because the memory (of the GPU) ran out
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
        if self.status in ("failed", "cancelled"):  # kept over a restart, to try again
            data.update(status=self.status, job_dir=self.job_dir, message=self.message)
        return data


WARM_IDLE_MINUTES = 5  # the waiting worker keeps its models this long after a job


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


def smaller_settings(settings: dict) -> dict | None:
    """Settings that need less memory (after "out of memory"); None when the method has none."""
    s = schema.normalize(settings)
    method = schema.method_of(s)
    if method == "controlsketch":
        return {"render_size": max(256, int(s["render_size"]) - 128), "turbo": True} \
            if int(s["render_size"]) > 256 or not s.get("turbo") else None
    if method in ("clipasso", "scenesketch"):
        out = {}
        if int(s["num_aug_clip"]) > 1:
            out["num_aug_clip"] = max(1, int(s["num_aug_clip"]) // 2)
        if method == "clipasso" and int(s["image_scale"]) > 224:
            out["image_scale"] = 224
        return out or None
    return None


class JobController(QObject):
    queue_changed = Signal()
    job_started = Signal(object)
    job_event = Signal(object, str, dict)
    job_finished = Signal(object)
    queue_idle = Signal(object)  # the queue ran out on its own (the last job, not cancelled by the user)
    held = Signal()  # a job waits: the results or the models are being moved (background.Work)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.runner = JobRunner(keep_warm=bool(app_settings().get("keep_models_loaded", True)))
        self.jobs: list[QueuedJob] = []
        self.current: QueuedJob | None = None
        self.auto_start = True
        self._held = False  # a job was to start while files were moving (background.Work)
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._poll)
        # the worker with the models of the last job ends after some minutes without a job
        self._idle = QTimer(self)
        self._idle.setInterval(30_000)
        self._idle.timeout.connect(self._release_idle)
        self._idle.start()
        from .background import work

        work().ended.connect(self._work_ended)  # (a method: disconnected when the controller is gone)
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
        # (continuing a job: its own settings as they were)
        settings = schema.normalize(settings) if resume_dir else new_job_settings(settings)
        job = QueuedJob(target=target, settings=settings, resume_dir=resume_dir)
        self.jobs.append(job)
        self._persist_queue()
        self.queue_changed.emit()
        if start and not self.is_busy():
            self.start_next()
        return job

    def enqueue_many(self, targets: list[str], settings: dict, start: bool = True) -> list[QueuedJob]:
        """Queue several images with the same settings – the queue is saved and shown once, not per image
        (a folder of hundreds of images)."""
        normalized = new_job_settings(settings)
        added = [QueuedJob(target=t, settings=dict(normalized)) for t in targets]
        self.jobs.extend(added)
        if added:
            self._persist_queue()
            self.queue_changed.emit()
            if start and not self.is_busy():
                self.start_next()
        return added

    def pending(self) -> list[QueuedJob]:
        return [j for j in self.jobs if j.status == "queued"]

    def remove(self, job_id: int) -> None:
        self.jobs = [j for j in self.jobs if not (j.id == job_id and j.status != "running")]
        self._persist_queue()
        self.queue_changed.emit()

    def move_to(self, job_id: int, index: int) -> None:
        """Put a job at position ``index`` of the queue (drag and drop)."""
        idx = next((i for i, j in enumerate(self.jobs) if j.id == job_id), None)
        if idx is None:
            return
        job = self.jobs.pop(idx)
        self.jobs.insert(min(max(int(index), 0), len(self.jobs)), job)
        self._persist_queue()
        self.queue_changed.emit()

    def retry(self, job_id: int, start: bool = True, overrides: dict | None = None,
              restart_unfinished: bool = False) -> QueuedJob | None:
        """A failed or cancelled job once more: it continues from its finished sketches and checkpoints
        when its folder allows that, otherwise it starts again. ``overrides``: changed settings (e.g. the
        CPU after "out of memory"); ``restart_unfinished``: the unfinished sketches start again (their
        checkpoints do not fit other sizes)."""
        job = next((j for j in self.jobs if j.id == job_id), None)
        if job is None or job.status not in ("failed", "cancelled"):
            return None
        if overrides:
            job.settings = schema.normalize({**job.settings, **overrides})
        if job.job_dir and jobs.read_state(job.job_dir) and jobs.remaining_seeds(job.job_dir):
            job.resume_dir = job.job_dir
            if restart_unfinished:
                jobs.drop_checkpoints(job.job_dir)
        job.status, job.message, job.eta, job.finished, job.oom = "queued", "", float("nan"), 0.0, False
        job.seed_progress, job.seed_best = {}, {}
        self._persist_queue()
        self.queue_changed.emit()
        if start and not self.is_busy():
            self.start_next()
        return job

    def replace_settings(self, job_id: int, settings: dict) -> bool:
        """Other settings for a waiting job (not for one that continues a started job)."""
        job = next((j for j in self.jobs if j.id == job_id), None)
        if job is None or job.status != "queued" or job.resume_dir:
            return False
        job.settings = new_job_settings(settings)
        self._persist_queue()
        self.queue_changed.emit()
        return True

    def remaining_seconds(self) -> float:
        """Time until the queue is done: the running job's own estimate plus estimates of the waiting ones."""
        total = 0.0
        for j in self.jobs:
            if j.status in ("running", "paused") and j.eta == j.eta:  # (not NaN)
                total += max(float(j.eta), 0.0)
            elif j.status in ("queued", "running", "paused"):
                secs = methods_ui.estimate_seconds(j.settings)
                if j.resume_dir:  # only what is left of it
                    done, all_ = jobs.progress_of(j.resume_dir)
                    secs *= 1 - done / max(all_, 1)
                total += secs
        return total

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
        self._persist_queue()
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

    def _work_ended(self, kind: str, _ok: bool):
        from .background import HOLD_JOBS

        if kind in HOLD_JOBS and self._held:
            self._held = False
            self.start_next()  # the job that was to start during the move

    def start_next(self) -> QueuedJob | None:
        from .background import work

        if self.is_busy():
            return None
        nxt = next((j for j in self.jobs if j.status == "queued"), None)
        if nxt is None:
            _keep_awake(False)
            return None
        if work().holds_jobs():  # the results / models are moving: it starts when that is done
            self._held = True
            self.held.emit()
            return None
        out = app_settings().get("output_dir")
        try:
            from .hardware import spread_gpus

            self.runner.start(nxt.settings, nxt.target, out, job_dir=nxt.resume_dir,
                              auto_parallel=app_settings().get("parallel_sketches", "auto") == "auto",
                              cuda=methods_ui.has_cuda(), gpus=spread_gpus())
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
        self._idle.stop()
        self.runner.kill()
        _keep_awake(False)

    def set_keep_models(self, on: bool) -> None:
        """Keep the worker (and its models) between jobs, or not."""
        self.runner.keep_warm = bool(on)
        if not on:
            self.runner.shutdown_warm()

    def release_worker(self) -> None:
        """End the waiting worker now (e.g. before models are moved or removed: it keeps their files open)."""
        self.runner.shutdown_warm()

    def _release_idle(self):
        self.runner.release_idle(float(app_settings().get("warm_idle_minutes", WARM_IDLE_MINUTES)) * 60)

    # ----------------------------------------------------------------- events
    def _poll(self):
        job = self.current
        if job is None:
            self._timer.stop()
            return
        for kind, data in self.runner.poll():
            if kind == "job_start":
                job.device = data.get("device", "")
                job.devices.add(job.device)
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
                job.oom = job.oom or bool(data.get("oom"))
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

    def relocate(self, old: str, new: str) -> None:
        """The output folder moved from ``old`` to ``new`` (with its results): follow it in the waiting
        jobs (their pasted / edited images, continued job folders) and the recent images."""
        from .storage import relocated

        for j in self.jobs:
            if j.status in ("running", "paused"):
                continue
            j.target = relocated(j.target, old, new)
            j.job_dir = relocated(j.job_dir, old, new)
            j.resume_dir = relocated(j.resume_dir, old, new)
            if isinstance(j.settings.get("path_svg"), str):
                j.settings["path_svg"] = relocated(j.settings["path_svg"], old, new)
        self._persist_queue()
        s = app_settings()
        s.set("recent_images", [relocated(p, old, new) for p in s.get("recent_images") or []])
        if s.get("last_image"):
            s.set("last_image", relocated(s.get("last_image"), old, new))
        self.queue_changed.emit()

    def waiting_files(self) -> list[str]:
        """Images and SVGs the waiting jobs still need (they stay when the app's image folders are cleared)."""
        files = []
        for j in self.jobs:
            if j.status in ("queued", "running", "paused", "failed", "cancelled"):
                files.append(j.target)
                if isinstance(j.settings.get("path_svg"), str):
                    files.append(j.settings["path_svg"])
        return files

    # ------------------------------------------------------------ persistence
    def _persist_queue(self):
        app_settings().set("queue", [j.to_json() for j in self.jobs if j.status in ("queued", "failed", "cancelled")])

    def _restore_queue(self):
        for item in app_settings().get("queue") or []:
            try:
                if os.path.isfile(item["target"]):
                    resume = item.get("resume_dir", "")
                    if resume and not os.path.isdir(resume):
                        continue
                    status = item.get("status", "queued")
                    self.jobs.append(QueuedJob(target=item["target"], settings=schema.normalize(item["settings"]),
                                               resume_dir=resume,
                                               status=status if status in ("failed", "cancelled") else "queued",
                                               job_dir=item.get("job_dir", "") or "",
                                               message=item.get("message", "") or ""))
            except (KeyError, TypeError, ValueError):
                continue
