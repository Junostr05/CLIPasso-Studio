"""Background execution of sketch jobs in separate processes.

The GUI never imports torch for a run: it starts worker processes (``spawn``), receives
progress events through a queue and controls them with pause / stop events. With
``multiprocess`` the seeds of a job are distributed over several workers (like
``run_object_sketching.py --multiprocess 1``); the best sketch is selected afterwards.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import queue as queue_mod
import time
import traceback
from dataclasses import dataclass, field

from . import jobs

MAX_PARALLEL_WORKERS = 4


class _QueueReporter:
    def __init__(self, q, worker_id: int):
        self.q = q
        self.worker_id = worker_id

    def event(self, kind, **data):
        data["worker"] = self.worker_id
        self.q.put((kind, data))


class _EventControl:
    def __init__(self, stop_event, pause_event):
        self.stop_event = stop_event
        self.pause_event = pause_event

    def should_stop(self):
        return self.stop_event.is_set()

    def wait_if_paused(self):
        while self.pause_event.is_set() and not self.stop_event.is_set():
            time.sleep(0.1)


def _worker_main(worker_id, settings, target, output_root, job_dir, seeds, finish, q, stop_event, pause_event,
                 threads):
    """Entry point of a worker process."""
    reporter = _QueueReporter(q, worker_id)
    try:
        import torch

        if threads:
            torch.set_num_threads(int(threads))
        from . import pipeline
        from .model_store import ModelMissingError

        try:
            result = pipeline.run_job(settings, target, output_root, reporter, _EventControl(stop_event, pause_event),
                                      job_dir=job_dir, seeds=seeds, finish=finish)
            if not finish:
                reporter.event("worker_results", results=[r.__dict__ for r in result])
        except ModelMissingError as exc:
            reporter.event("error", message=str(exc), model=exc.spec_key, traceback="")
    except BaseException as exc:  # report everything, including MemoryError / KeyboardInterrupt
        reporter.event("error", message=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    finally:
        reporter.event("worker_exit")


@dataclass
class Job:
    settings: dict
    target: str
    output_root: str
    job_dir: str = ""
    workers: list = field(default_factory=list)
    finished_workers: int = 0
    seed_results: list = field(default_factory=list)
    started: float = 0.0
    parallel: bool = False
    failed: bool = False
    done: bool = False


class JobRunner:
    """Runs one job at a time. Call :meth:`poll` regularly (e.g. from a QTimer)."""

    def __init__(self):
        self._ctx = mp.get_context("spawn")
        self._queue = None
        self._stop = None
        self._pause = None
        self.job: Job | None = None

    # ----------------------------------------------------------------- control
    def start(self, settings: dict, target: str, output_root: str) -> Job:
        if self.is_running():
            raise RuntimeError("a job is already running")
        from .. import settings_schema as schema

        settings = schema.normalize(settings)
        os.makedirs(output_root, exist_ok=True)
        job = Job(settings=settings, target=target, output_root=output_root)
        job.job_dir = jobs.make_job_dir(output_root, target)
        job.started = time.time()
        self._queue = self._ctx.Queue()
        self._stop = self._ctx.Event()
        self._pause = self._ctx.Event()
        seeds = jobs.job_seeds(settings)
        n_workers = 1
        if settings.get("multiprocess") and len(seeds) > 1:
            n_workers = min(len(seeds), MAX_PARALLEL_WORKERS)
        job.parallel = n_workers > 1
        threads = int(settings.get("num_threads", 0))
        if job.parallel and not threads:
            threads = max(1, (os.cpu_count() or 2) // n_workers)
        chunks = [seeds[i::n_workers] for i in range(n_workers)]
        for wid, chunk in enumerate(chunks):
            p = self._ctx.Process(
                target=_worker_main,
                args=(wid, settings, target, output_root, job.job_dir, chunk, not job.parallel, self._queue,
                      self._stop, self._pause, threads),
                daemon=True,
            )
            p.start()
            job.workers.append(p)
        self.job = job
        return job

    def pause(self):
        if self._pause is not None:
            self._pause.set()

    def resume(self):
        if self._pause is not None:
            self._pause.clear()

    def is_paused(self) -> bool:
        return bool(self._pause is not None and self._pause.is_set())

    def cancel(self):
        if self._stop is not None:
            self._stop.set()
        if self._pause is not None:
            self._pause.clear()

    def kill(self):
        """Hard stop (e.g. when the app is closed)."""
        self.cancel()
        if self.job:
            for p in self.job.workers:
                if p.is_alive():
                    p.terminate()
            for p in self.job.workers:
                p.join(timeout=5)
            self.job.done = True

    def is_running(self) -> bool:
        return bool(self.job and not self.job.done)

    # ------------------------------------------------------------------ events
    def poll(self, max_events: int = 500) -> list[tuple[str, dict]]:
        """Drain pending events. Adds a final ('job_done' | 'job_failed') event when the job ends."""
        events = []
        if self.job is None or self._queue is None:
            return events
        job = self.job
        for _ in range(max_events):
            try:
                kind, data = self._queue.get_nowait()
            except queue_mod.Empty:
                break
            except (EOFError, OSError):
                break
            if kind == "worker_exit":
                job.finished_workers += 1
                continue
            if kind == "worker_results":
                job.seed_results.extend(data["results"])
                continue
            if kind == "error":
                job.failed = True
            if kind == "job_done":
                job.done = True
            events.append((kind, data))

        if not job.done:
            all_exited = job.finished_workers >= len(job.workers) or not any(p.is_alive() for p in job.workers)
            if all_exited and job.finished_workers < len(job.workers):
                # a worker died without saying goodbye (crash / out of memory): drain once more
                time.sleep(0.05)
                try:
                    while True:
                        kind, data = self._queue.get_nowait()
                        if kind == "worker_results":
                            job.seed_results.extend(data["results"])
                        elif kind not in ("worker_exit",):
                            events.append((kind, data))
                            if kind == "error":
                                job.failed = True
                except (queue_mod.Empty, EOFError, OSError):
                    pass
                job.finished_workers = len(job.workers)
                codes = [p.exitcode for p in job.workers]
                if any(c not in (0, None) for c in codes) and not job.failed:
                    job.failed = True
                    events.append(("error", {"message": f"worker process ended unexpectedly (exit codes {codes})",
                                             "traceback": ""}))
            if job.finished_workers >= len(job.workers):
                if job.parallel and job.seed_results and not job.failed:
                    results = [jobs.SeedResult(**r) for r in job.seed_results]
                    try:
                        summary = jobs.finish_job(job.job_dir, job.target, job.settings, results)
                        events.append(("job_done", {"job_dir": job.job_dir, "best_svg": summary["best_svg"],
                                                    "best_run": summary["best_run"], "runs": summary["runs"]}))
                    except Exception as exc:
                        job.failed = True
                        events.append(("error", {"message": str(exc), "traceback": traceback.format_exc()}))
                job.done = True
                if job.failed or not any(k == "job_done" for k, _ in events):
                    events.append(("job_failed" if job.failed else "job_ended", {"job_dir": job.job_dir}))
        return events
