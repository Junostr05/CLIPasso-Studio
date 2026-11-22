"""Where a job computes, measured while it runs (the Mac app's Analysis page, the MCP tool ``get_analysis``).

Each step of a sketch is split into parts, each timed with the device it ran on:

- ``draw``      – the strokes rasterised (renderer; on the Apple GPU drawn on the CPU, renderer.draw_device)
- ``clip``      – CLIP: image and text encoders (forward)
- ``model``     – a diffusion model or network of the method (SwiftSketch, ControlSketch's UNet and ControlNet)
- ``backward``  – the gradients (autograd: CLIP's on the GPU, the drawing's where it was drawn)
- ``optimizer`` – the optimiser's step
- the rest of the time: loading, preparing, saving, everything else (``seconds`` minus the parts)

On a GPU a part waits for the work sent before it and for its own (synchronise before and after): GPU time counts
where it is spent, not where Python next waits for it. Operations PyTorch runs on the CPU in place of the Apple GPU
(PYTORCH_ENABLE_MPS_FALLBACK) are listed from its warnings. A worker writes ``analysis/worker-<n>.json`` in the job
folder every few seconds and at its end; the app adds up the workers.
"""

from __future__ import annotations

import datetime as _dt
import functools
import json
import os
import sys
import threading
import time
import warnings

import torch

FORMAT = 1
WRITE_EVERY = 2.0  # s – at most this often while it runs
PARTS = ("draw", "clip", "model", "backward", "optimizer")

_local = threading.local()


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def _sync(device) -> None:
    kind = torch.device(device).type if device is not None else "cpu"
    try:
        if kind == "mps":
            torch.mps.synchronize()
        elif kind == "cuda":
            torch.cuda.synchronize()
    except Exception:  # noqa: BLE001 - a device that cannot wait: the time is what Python saw
        pass


def _device_of_module(module) -> torch.device | None:
    for p in module.parameters():
        return p.device
    return None


class Analysis:
    """The measurements of one worker process (one at a time: ``current()``)."""

    def __init__(self, worker: int = 0):
        self.worker = int(worker)
        self.started = time.perf_counter()
        self.started_at = _now()
        self.parts: dict[str, dict] = {k: {"seconds": 0.0, "calls": 0, "devices": set()} for k in PARTS}
        self.fallbacks: set[str] = set()
        self.job_dir: str | None = None
        self.method = ""
        self.device = ""
        self.optimizing_since: float | None = None
        self.optimizing = 0.0
        self.iterations: dict = {}  # seed -> last iteration
        self.last_write = 0.0
        self.finished = False

    def add(self, part: str, seconds: float, device) -> None:
        entry = self.parts[part]
        entry["seconds"] += seconds
        entry["calls"] += 1
        if device is not None:
            entry["devices"].add(torch.device(device).type)

    # -- the reporter's events -----------------------------------------------------------------------------
    def event(self, kind: str, data: dict) -> None:
        if kind == "job_start":
            self.job_dir = data.get("job_dir") or self.job_dir
            self.method = str(data.get("method") or self.method)
            self.device = str(data.get("device") or self.device)
        elif kind == "stage" and data.get("name") == "optimizing":
            self.optimizing_since = self.optimizing_since or time.perf_counter()
        elif kind == "iteration":
            self.iterations[data.get("seed")] = int(data.get("it") or 0) + 1
            if self.optimizing_since is None:
                self.optimizing_since = time.perf_counter()
        elif kind == "seed_done" and self.optimizing_since is not None:
            self.optimizing += time.perf_counter() - self.optimizing_since
            self.optimizing_since = None
        if kind in ("iteration", "seed_done", "job_start") and time.perf_counter() - self.last_write >= WRITE_EVERY:
            self.write()

    # -- the report ----------------------------------------------------------------------------------------
    def report(self) -> dict:
        now = time.perf_counter()
        optimizing = self.optimizing + (now - self.optimizing_since if self.optimizing_since is not None else 0.0)
        memory: dict = {"rss_peak": _peak_rss()}
        if torch.device(self.device or "cpu").type == "mps":
            try:
                memory["mps_allocated"] = int(torch.mps.current_allocated_memory())
                memory["mps_driver"] = int(torch.mps.driver_allocated_memory())
            except Exception:  # noqa: BLE001 - an older PyTorch
                pass
        from . import mps_ops, renderer

        device = self.device or "cpu"
        return {
            "format": FORMAT, "worker": self.worker, "pid": os.getpid(), "method": self.method, "device": device,
            "draw_device": str(renderer.draw_device(device)),
            "linear": mps_ops._chosen if torch.device(device).type == "mps" else "native",
            "torch": torch.__version__.split("+")[0], "threads": torch.get_num_threads(),
            "started": self.started_at, "updated": _now(), "finished": self.finished,
            "seconds": round(now - self.started, 3), "optimizing_seconds": round(optimizing, 3),
            "iterations": int(sum(self.iterations.values())),
            "parts": [{"key": k, "seconds": round(v["seconds"], 4), "calls": v["calls"],
                       "devices": sorted(self._devices(k))} for k, v in self.parts.items()],
            "fallbacks": sorted(self.fallbacks), "memory": memory,
        }

    def _devices(self, part: str) -> set:
        """Where a part ran – the gradients also where the strokes were drawn (the drawing's own backward)."""
        devices = set(self.parts[part]["devices"])
        if part == "backward" and devices and self.parts["draw"]["calls"]:
            devices |= self.parts["draw"]["devices"]
        return devices

    def write(self) -> None:
        self.last_write = time.perf_counter()
        if not self.job_dir:
            return
        folder = os.path.join(self.job_dir, "analysis")
        try:
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, f"worker-{self.worker}.json")
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.report(), f, indent=1)
            os.replace(tmp, path)
        except OSError:  # (a full drive or a folder that went: the job goes on without its analysis)
            pass


def _peak_rss() -> int:
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(peak if sys.platform == "darwin" else peak * 1024)  # (bytes on macOS, kB on Linux)
    except Exception:  # noqa: BLE001 - Windows
        return 0


_current: Analysis | None = None
_installed = False


def current() -> Analysis | None:
    return _current


def _timed(part: str, device_of):
    """``fn`` timed as ``part`` of the current analysis (not inside another part: a part's own parts count to it)."""

    def wrap(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            analysis = _current
            if analysis is None or getattr(_local, "busy", False):
                return fn(*args, **kwargs)
            try:
                device = device_of(*args, **kwargs)
            except Exception:  # noqa: BLE001 - not to be told: the CPU
                device = None
            _local.busy = True
            try:
                _sync(device)
                start = time.perf_counter()
                out = fn(*args, **kwargs)
                _sync(device)
                analysis.add(part, time.perf_counter() - start, device)
                return out
            finally:
                _local.busy = False

        inner.__wrapped_for_analysis__ = True
        return inner

    return wrap


def _patch(owner, name: str, part: str, device_of) -> None:
    fn = getattr(owner, name, None)
    if fn is None or getattr(fn, "__wrapped_for_analysis__", False):
        return
    setattr(owner, name, _timed(part, device_of)(fn))


def _install() -> None:
    """The timers – once per process; they cost nothing while no analysis runs."""
    global _installed
    if _installed:
        return
    _installed = True
    from . import renderer
    from .clip_ import model as clip_model

    def strokes(_w, _h, shapes, *_a, **_k):
        return renderer.draw_device(renderer._strokes_device(shapes))

    _patch(renderer, "_render", "draw", strokes)
    _patch(renderer, "_on_white", "draw", strokes)

    def module_device(self, *_a, **_k):
        return _device_of_module(self)

    _patch(clip_model.CLIP, "encode_text", "clip", module_device)
    for cls in (getattr(clip_model, "VisualTransformer", None), getattr(clip_model, "ModifiedResNet", None)):
        if cls is not None:
            _patch(cls, "forward", "clip", module_device)
    for module_name, cls_name in (("clipasso_studio.engine.methods.swiftsketch.model", "SwiftSketchNet"),
                                  ("diffusers.models.unets.unet_2d_condition", "UNet2DConditionModel"),
                                  ("diffusers.models.controlnets.controlnet", "ControlNetModel"),
                                  ("diffusers.models.controlnet", "ControlNetModel")):
        try:
            module = __import__(module_name, fromlist=[cls_name])
            _patch(getattr(module, cls_name), "forward", "model", module_device)
        except Exception:  # noqa: BLE001 - not installed or moved: that model's time counts as the rest
            pass

    def tensor_device(tensors, *_a, **_k):
        first = tensors[0] if isinstance(tensors, (list, tuple)) and tensors else tensors
        return getattr(first, "device", None)

    _patch(torch.autograd, "backward", "backward", tensor_device)  # (Tensor.backward calls it)

    # the optimiser's step: from its pre hook to its post hook
    def pre(optimizer, *_a):
        analysis = _current
        if analysis is None or getattr(_local, "busy", False):
            return
        device = next((p.device for g in optimizer.param_groups for p in g["params"]), None)
        _sync(device)
        _local.busy = True
        _local.step = (time.perf_counter(), device)

    def post(optimizer, *_a):
        analysis = _current
        step = getattr(_local, "step", None)
        if analysis is None or step is None:
            return
        _local.step = None
        _sync(step[1])
        _local.busy = False
        analysis.add("optimizer", time.perf_counter() - step[0], step[1])

    try:
        from torch.optim.optimizer import register_optimizer_step_post_hook, register_optimizer_step_pre_hook

        register_optimizer_step_pre_hook(pre)
        register_optimizer_step_post_hook(post)
    except ImportError:  # (an old PyTorch: the optimiser counts as the rest)
        pass


def _hook_warnings() -> None:
    """Operations PyTorch computes on the CPU in place of the Apple GPU: its warning names them, once each. Hooked
    again where something else (a library, a test) replaced the hook."""
    shown = warnings.showwarning
    if getattr(shown, "__analysis__", False):
        return

    def showwarning(message, category, filename, lineno, file=None, line=None):
        text = str(message)
        if _current is not None and "fall back to run on the CPU" in text:
            start = text.find("'")
            end = text.find("'", start + 1)
            _current.fallbacks.add(text[start + 1:end] if 0 <= start < end else text[:120])
        return shown(message, category, filename, lineno, file, line)

    showwarning.__analysis__ = True
    warnings.showwarning = showwarning


class Reporter:
    """A worker's reporter that also tells the analysis what happens (job_start, stages, iterations)."""

    def __init__(self, reporter, analysis: Analysis):
        self._reporter, self._analysis = reporter, analysis

    def event(self, kind, **data):
        self._analysis.event(kind, data)
        return self._reporter.event(kind, **data)

    def __getattr__(self, name):
        return getattr(self._reporter, name)


def begin(reporter, worker: int = 0):
    """Measure the job this worker runs from now on: the reporter to pass on."""
    global _current
    _install()
    _hook_warnings()
    _current = Analysis(worker)
    return Reporter(reporter, _current)


def end() -> None:
    """The job of this worker ended: the last report written."""
    global _current
    analysis = _current
    _current = None
    if analysis is not None:
        if analysis.optimizing_since is not None:
            analysis.optimizing += time.perf_counter() - analysis.optimizing_since
            analysis.optimizing_since = None
        analysis.finished = True
        analysis.write()


def read(job_dir: str) -> dict | None:
    """The analysis of a job: its workers added up (None when it has none)."""
    folder = os.path.join(job_dir, "analysis")
    reports = []
    try:
        for name in sorted(os.listdir(folder)):
            if name.startswith("worker-") and name.endswith(".json"):
                with open(os.path.join(folder, name), encoding="utf-8") as f:
                    reports.append(json.load(f))
    except (OSError, ValueError):
        return None
    if not reports:
        return None
    parts = {}
    for r in reports:
        for p in r.get("parts", []):
            entry = parts.setdefault(p["key"], {"key": p["key"], "seconds": 0.0, "calls": 0, "devices": set()})
            entry["seconds"] += p.get("seconds", 0.0)
            entry["calls"] += p.get("calls", 0)
            entry["devices"].update(p.get("devices", []))
    first = reports[0]
    return {
        "format": FORMAT, "workers": len(reports), "method": first.get("method", ""),
        "device": first.get("device", ""), "draw_device": first.get("draw_device", ""),
        "linear": first.get("linear", ""), "torch": first.get("torch", ""),
        "threads": first.get("threads", 0), "started": min(r.get("started", "") for r in reports),
        "updated": max(r.get("updated", "") for r in reports), "finished": all(r.get("finished") for r in reports),
        "seconds": max(r.get("seconds", 0.0) for r in reports),
        "optimizing_seconds": sum(r.get("optimizing_seconds", 0.0) for r in reports),
        "iterations": sum(r.get("iterations", 0) for r in reports),
        "parts": [dict(p, seconds=round(p["seconds"], 4), devices=sorted(p["devices"])) for p in parts.values()],
        "fallbacks": sorted({f for r in reports for f in r.get("fallbacks", [])}),
        "memory": {"rss_peak": max(r.get("memory", {}).get("rss_peak", 0) for r in reports),
                   "mps_driver": max(r.get("memory", {}).get("mps_driver", 0) for r in reports)},
    }


def build() -> str:
    """The engine's build: the commit written into the app when it was made (``BUILD`` next to this package's
    ``__init__``), else "dev"."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "BUILD")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip() or "dev"
    except OSError:
        return "dev"


def probe_extra(found: dict) -> dict:
    """What the device probe adds for the Analysis page: the engine's version and build, how the linear layer
    computes right on the Apple GPU (mps_ops.ensure_right), the methods "auto" computes there, where strokes on it
    are drawn, the cores and threads."""
    from .. import __version__, settings_schema
    from . import mps_ops, renderer

    out = {"engine": __version__, "build": build(), "cpu_count": os.cpu_count() or 0,
           "threads": torch.get_num_threads(), "mps_auto": list(settings_schema.MPS_AUTO),
           "draw_on_mps": str(renderer.draw_device("mps"))}
    if found.get("mps"):
        out["linear"] = mps_ops.ensure_right("mps")
    return out

