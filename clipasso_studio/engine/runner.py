"""Background execution of sketch jobs in separate processes.

The GUI never imports torch for a run: it starts worker processes (``spawn``), receives
progress events through a queue and controls them with pause / stop events. With
``multiprocess`` the seeds of a job are distributed over several workers (like
``run_object_sketching.py --multiprocess 1``); the best sketch is selected afterwards.

On a CPU with enough cores and memory the seeds of CLIPasso and SwiftSketch also run in parallel
automatically (:func:`plan_workers`): their networks are small and leave most cores idle. Each worker
then gets its share of the physical cores (hyper-threads would only compete for the same core).

With ``keep_warm`` a job with one worker runs in a worker that stays open for the next job, with its
models still loaded (torch, CLIP, Stable Diffusion … are not loaded again for every job of a queue).
Its events carry the job's token, so late events of an earlier job are ignored. It ends after an
error, after ``WARM_MAX_JOBS`` jobs, when the GUI is gone, or when :meth:`JobRunner.release_idle`
finds it idle for long enough.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import queue as queue_mod
import time
import traceback
from dataclasses import dataclass, field

from .. import logs
from . import jobs

MAX_PARALLEL_WORKERS = 4
WARM_MAX_JOBS = 20  # a fresh worker now and then (memory fragmentation)
AUTO_MIN_CORES = 6  # physical cores before the seeds of a job run in parallel automatically
RAM_PER_WORKER = {"clipasso": 2.5e9, "swiftsketch": 1.5e9}  # bytes a worker needs at most (about)
RAM_RESERVE = 2e9  # left for the app and the system


def hardware_info() -> tuple[int, int]:
    """(physical CPU cores, available memory in bytes) – without importing torch."""
    try:
        import psutil

        cores = psutil.cpu_count(logical=False) or max(1, (os.cpu_count() or 2) // 2)
        return int(cores), int(psutil.virtual_memory().available)
    except Exception:
        return max(1, (os.cpu_count() or 2) // 2), 0


def plan_workers(settings: dict, n_seeds: int, auto: bool = True, cuda: bool = False,
                 hw: tuple[int, int] | None = None) -> int:
    """How many worker processes compute the seeds of a job at the same time."""
    from .. import settings_schema as schema

    if n_seeds <= 1 or schema.turbo_prunes(settings):  # (turbo: the seeds are compared halfway)
        return 1
    if settings.get("multiprocess"):  # chosen in the settings: always (like the original scripts)
        return min(n_seeds, MAX_PARALLEL_WORKERS)
    method = schema.method_of(settings)
    device = settings.get("device", "auto")
    if not auto or method not in RAM_PER_WORKER or device == "cuda" or (device == "auto" and cuda):
        return 1
    cores, available = hw or hardware_info()
    if cores < AUTO_MIN_CORES:
        return 1
    by_memory = int((available - RAM_RESERVE) // RAM_PER_WORKER[method])
    return max(1, min(n_seeds, MAX_PARALLEL_WORKERS, cores // 2, by_memory))


class _QueueReporter:
    def __init__(self, q, worker_id: int, token: int = 0):
        self.q = q
        self.worker_id = worker_id
        self.token = token

    def event(self, kind, **data):
        data["worker"] = self.worker_id
        data["token"] = self.token
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


def is_out_of_memory(exc: BaseException) -> bool:
    """Did a run fail because the GPU (or the computer) ran out of memory?"""
    if isinstance(exc, MemoryError) or type(exc).__name__ == "OutOfMemoryError":
        return True
    text = str(exc).lower()
    return any(s in text for s in ("out of memory", "can't allocate memory", "not enough memory",
                                   "cudnn_status_alloc_failed", "failed to allocate"))


def _run_one(reporter, settings, target, output_root, job_dir, seeds, finish, stop_event, pause_event,
             resume) -> bool:
    """Run (the seeds of) a job in this worker; False after an unexpected exception."""
    try:
        from . import pipeline
        from .model_store import ModelMissingError

        try:
            result = pipeline.run_job(settings, target, output_root, reporter, _EventControl(stop_event, pause_event),
                                      job_dir=job_dir, seeds=seeds, finish=finish, resume=resume)
            if not finish:
                reporter.event("worker_results", results=[r.__dict__ for r in result])
        except ModelMissingError as exc:
            reporter.event("error", message=str(exc), model=exc.spec_key, traceback="")
        return True
    except BaseException as exc:  # report everything, including MemoryError / KeyboardInterrupt
        reporter.event("error", message=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc(),
                       oom=is_out_of_memory(exc))
        return False


def _worker_main(worker_id, settings, target, output_root, job_dir, seeds, finish, q, stop_event, pause_event,
                 threads, resume=False, share=1):
    """Entry point of a worker process. ``threads``: the number chosen in the settings (0 = automatic);
    ``share``: workers running at the same time, which divide the physical cores among them."""
    from .. import gpu_runtime

    gpu_runtime.activate()  # (normally done at the start of the process: packaging/launch.py, __main__)
    reporter = _QueueReporter(q, worker_id)
    fault_log = logs.start_worker_log()
    try:
        import torch

        # the same input sizes all the time: let cuDNN pick its fastest convolution algorithms
        torch.backends.cudnn.benchmark = True
        if threads:
            torch.set_num_threads(int(threads))
        elif share > 1:  # torch starts with one thread per physical core
            torch.set_num_threads(max(1, torch.get_num_threads() // int(share)))
        _run_one(reporter, settings, target, output_root, job_dir, seeds, finish, stop_event, pause_event, resume)
    except BaseException as exc:
        reporter.event("error", message=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    finally:
        reporter.event("worker_exit")
        logs.end_worker_log(fault_log)


def release_cached_models() -> None:
    """Free the networks a worker keeps between sketches (all methods, CLIP, masks, scorer)."""
    import gc
    import sys

    for name in ("methods.swiftsketch", "methods.controlsketch", "methods.scenesketch", "nets", "clip_.clip"):
        module = sys.modules.get(f"{__package__}.{name}")
        if module is not None and hasattr(module, "release_models"):
            module.release_models()
    for name, attr in (("scoring", "_scorers"), ("masking", "_cache")):
        module = sys.modules.get(f"{__package__}.{name}")
        if module is not None:
            getattr(module, attr).clear()
    gc.collect()
    torch = sys.modules.get("torch")
    if torch is not None and torch.cuda.is_available():
        torch.cuda.empty_cache()


def _warm_main(job_q, q, stop_event, pause_event):
    """A worker that runs one job after the other (see the module docstring)."""
    from .. import gpu_runtime

    gpu_runtime.activate()
    fault_log = logs.start_worker_log()
    try:
        _warm_loop(job_q, q, stop_event, pause_event)
    finally:
        logs.end_worker_log(fault_log)


def _warm_loop(job_q, q, stop_event, pause_event):
    import gc

    import torch

    from .. import settings_schema as schema

    torch.backends.cudnn.benchmark = True
    base_threads = torch.get_num_threads()
    parent = mp.parent_process()
    last_method = None
    for _ in range(WARM_MAX_JOBS):
        item = None
        while item is None:
            try:
                item = job_q.get(timeout=2)
            except queue_mod.Empty:
                if parent is not None and not parent.is_alive():
                    return  # the app is gone (e.g. killed): do not keep its memory
                continue
            if item == "quit":
                return
        token, settings, target, output_root, job_dir, seeds, threads, resume = item
        reporter = _QueueReporter(q, 0, token)
        method = schema.method_of(settings)
        if last_method is not None and method != last_method:
            release_cached_models()  # e.g. Stable Diffusion of ControlSketch before a CLIPasso job
        last_method = method
        torch.set_num_threads(int(threads) if threads else base_threads)
        ok = _run_one(reporter, settings, target, output_root, job_dir, seeds, True, stop_event, pause_event, resume)
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        reporter.event("worker_exit")
        if not ok:
            return  # after an unexpected error the next job gets a fresh process


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
    resumed: dict = field(default_factory=dict)  # seed -> SeedResult finished before a "Continue"
    token: int = 0  # runs in the warm worker: only its events with this token belong to it


class JobRunner:
    """Runs one job at a time. Call :meth:`poll` regularly (e.g. from a QTimer)."""

    def __init__(self, keep_warm: bool = False):
        self._ctx = mp.get_context("spawn")
        self._queue = None
        self._stop = None
        self._pause = None
        self.job: Job | None = None
        self.keep_warm = keep_warm  # one-worker jobs in a worker that stays open with its models
        self._warm: dict | None = None
        self._token = 0
        self._idle_since: float | None = None

    # -------------------------------------------------------------- warm worker
    def _warm_worker(self) -> dict:
        w = self._warm
        if w is not None and w["proc"].is_alive():
            return w
        self.shutdown_warm()
        w = {"job_q": self._ctx.Queue(), "q": self._ctx.Queue(), "stop": self._ctx.Event(),
             "pause": self._ctx.Event()}
        w["proc"] = self._ctx.Process(target=_warm_main, args=(w["job_q"], w["q"], w["stop"], w["pause"]),
                                      daemon=True)
        w["proc"].start()
        self._warm = w
        return w

    def warm_pid(self) -> int | None:
        w = self._warm
        return w["proc"].pid if w is not None and w["proc"].is_alive() else None

    def shutdown_warm(self, timeout: float = 5.0) -> None:
        """End the warm worker (its models are freed): before models are moved or removed, when it is
        idle for long, at exit. Not while it runs a job."""
        w = self._warm
        if w is None or (self.is_running() and self.job is not None and self.job.token):
            return
        self._warm = None
        try:
            w["job_q"].put("quit")
        except (OSError, ValueError):
            pass
        w["proc"].join(timeout=timeout)
        if w["proc"].is_alive():
            w["proc"].terminate()
            w["proc"].join(timeout=5)

    def release_idle(self, seconds: float) -> bool:
        """End the warm worker after ``seconds`` without a job; True if it was ended."""
        if self._warm is None or self.is_running() or self._idle_since is None:
            return False
        if time.time() - self._idle_since < seconds:
            return False
        self.shutdown_warm()
        return True

    # ----------------------------------------------------------------- control
    def start(self, settings: dict, target: str, output_root: str, job_dir: str = "", auto_parallel: bool = False,
              cuda: bool = False) -> Job:
        """Start a job; with ``job_dir`` an interrupted / cancelled job continues in its folder.
        ``auto_parallel``: run the seeds in parallel when the CPU is big enough (``cuda``: a GPU is there)."""
        if self.is_running():
            raise RuntimeError("a job is already running")
        from .. import settings_schema as schema

        settings = schema.normalize(settings)
        os.makedirs(output_root, exist_ok=True)
        job = Job(settings=settings, target=target, output_root=output_root)
        resume = bool(job_dir)
        if resume:
            job.job_dir = job_dir
            job.resumed = jobs.done_results(job_dir)
        else:
            job.job_dir = jobs.make_job_dir(output_root, target, schema.method_of(settings))
        if schema.method_of(settings) == "clipasso" and schema.text_value(settings.get("path_svg")):
            settings = {**settings, "path_svg": jobs.save_init_svg(job.job_dir, settings["path_svg"])}
            job.settings = settings
        jobs.write_state(job.job_dir, target, settings, "running")
        job.started = time.time()
        seeds = jobs.job_seeds(settings)
        if resume and schema.method_of(settings) != "scenesketch":
            seeds = [s for s in seeds if s not in job.resumed]
        n_workers = plan_workers(settings, len(seeds), auto=auto_parallel, cuda=cuda)
        job.parallel = n_workers > 1
        threads = int(settings.get("num_threads", 0))
        self._idle_since = None
        if n_workers == 1 and self.keep_warm:
            w = self._warm_worker()
            w["stop"].clear()  # a cancel that came after the previous job ended
            w["pause"].clear()
            self._token += 1
            job.token = self._token
            self._queue, self._stop, self._pause = w["q"], w["stop"], w["pause"]
            w["job_q"].put((job.token, settings, target, output_root, job.job_dir, seeds, threads, resume))
            job.workers.append(w["proc"])
            self.job = job
            return job
        self.shutdown_warm()  # its memory goes to the new workers
        self._queue = self._ctx.Queue()
        self._stop = self._ctx.Event()
        self._pause = self._ctx.Event()
        chunks = [seeds[i::n_workers] for i in range(n_workers)]
        for wid, chunk in enumerate(chunks):
            p = self._ctx.Process(
                target=_worker_main,
                args=(wid, settings, target, output_root, job.job_dir, chunk, not job.parallel, self._queue,
                      self._stop, self._pause, threads, resume and wid == 0, n_workers),
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
            if not self.job.done:  # continues from its last checkpoint (Gallery / next start: "Continue")
                jobs.set_status(self.job.job_dir, "interrupted")
            self.job.done = True
        w, self._warm = self._warm, None
        if w is not None and w["proc"].is_alive():
            w["proc"].terminate()
            w["proc"].join(timeout=5)

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
            if data.get("token", 0) != job.token:
                continue  # a late event of an earlier job in the warm worker
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
                        if data.get("token", 0) != job.token:
                            continue
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
                    stacks = "\n\n".join(t for t in (logs.read_worker_log(p.pid) for p in job.workers) if t)
                    events.append(("error", {"message": f"worker process ended unexpectedly (exit codes {codes})",
                                             "traceback": stacks}))
            if job.finished_workers >= len(job.workers):
                if job.parallel and (job.seed_results or job.resumed) and not job.failed:
                    results = jobs.merge_results(job.resumed, [jobs.SeedResult(**r) for r in job.seed_results])
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
                    stopped = self._stop is not None and self._stop.is_set()
                    state = jobs.read_state(job.job_dir)
                    if state and state.get("status") == "running":  # else finish_job has set it
                        jobs.set_status(job.job_dir, "cancelled" if stopped else "failed")
        if job.done and job.token and self._idle_since is None:
            self._idle_since = time.time()  # the warm worker waits for the next job
            w = self._warm
            if w is not None and (job.failed or not w["proc"].is_alive()):
                self._warm = None  # it ends itself after an error: the next job starts a fresh one
                w["proc"].join(timeout=10)
                if w["proc"].is_alive():
                    w["proc"].terminate()
        return events
