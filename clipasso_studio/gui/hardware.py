"""What PyTorch sees of the hardware (GPUs, CUDA) – found in a short child process, because the app
itself starts without PyTorch (about 3 s faster). The answer is kept in the settings for the next start
(per app version: a new version may bring another PyTorch / CUDA)."""

from __future__ import annotations

import json
import multiprocessing as mp
import queue as queue_mod

from .. import __version__
from .app_settings import app_settings


def _probe_main(q) -> None:
    from .. import gpu_runtime

    gpu_runtime.activate()  # (normally done at the start of the process)
    try:
        import torch

        from .. import gpu_runtime

        info = {"torch": torch.__version__, "cuda_build": torch.version.cuda or "", "gpus": [],
                "runtime": gpu_runtime.active_name()}  # "": the bundled PyTorch, else the one for older GPUs
        info["cuda"] = bool(torch.cuda.is_available() and torch.cuda.device_count() > 0)
        if info["cuda"]:
            from ..engine.pipeline import cuda_arch_supported

            for i in range(torch.cuda.device_count()):
                prop = torch.cuda.get_device_properties(i)
                info["gpus"].append({"name": prop.name, "memory_gb": round(prop.total_memory / 2 ** 30, 1),
                                     "supported": bool(cuda_arch_supported(i)),
                                     "capability": [int(prop.major), int(prop.minor)]})
        q.put(info)
    except Exception as exc:  # no usable PyTorch: reported, the app still works
        q.put({"error": f"{type(exc).__name__}: {exc}"})


def probe(progress=None, timeout: float = 180.0) -> str:
    """Run the probe process and wait for its answer (for ``dialogs.run_in_thread``): JSON text."""
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    proc = ctx.Process(target=_probe_main, args=(q,), daemon=True)
    proc.start()
    try:
        info = q.get(timeout=timeout)
    except queue_mod.Empty:
        info = {"error": "no answer"}
    proc.join(timeout=10)
    if proc.is_alive():
        proc.terminate()
    info["version"] = __version__
    return json.dumps(info)


def store(text: str) -> dict:
    """Keep a probe's answer (JSON text) in the settings; returns it as a dict."""
    try:
        info = json.loads(text)
    except (TypeError, ValueError):
        info = {"error": str(text)}
    if "error" not in info:
        app_settings().set("hardware", info)
    return info


def cached() -> dict | None:
    """The last answer of this app version (and the same PyTorch for older GPUs), or None (not probed yet)."""
    from .. import gpu_runtime

    info = app_settings().get("hardware")
    if isinstance(info, dict) and info.get("version") == __version__ and "error" not in info and \
            info.get("runtime", "") == gpu_runtime.active_name():
        return info
    return None


def has_cuda() -> bool:
    """A GPU this PyTorch can compute on (one it has no kernels for does not count)."""
    info = cached()
    return bool(info and info.get("cuda") and any(g.get("supported", True) for g in info.get("gpus") or [{}]))


def usable_gpus() -> tuple[int, ...]:
    """The indices of the graphics cards this PyTorch can compute on (as the probe saw them)."""
    info = cached()
    if not info or not info.get("cuda"):
        return ()
    return tuple(i for i, g in enumerate(info.get("gpus") or []) if g.get("supported", True))


def spread_gpus() -> tuple[int, ...]:
    """The graphics cards the sketches of a job may be spread over: all usable ones with the setting
    "Use several graphics cards" (on by default), else none."""
    from .app_settings import app_settings

    gpus = usable_gpus()
    return gpus if len(gpus) >= 2 and app_settings().get("multi_gpu", True) else ()


def job_gpu(settings: dict) -> dict | None:
    """The graphics card (as the probe saw it) a job with these settings computes on, like
    ``pipeline.resolve_device``; None: the CPU, or not known yet."""
    info = cached()
    gpus = (info or {}).get("gpus") or []
    if settings.get("device") == "cpu" or not (info or {}).get("cuda") or not gpus:
        return None
    gpu = gpus[min(int(settings.get("gpunum") or 0), len(gpus) - 1)]
    return gpu if gpu.get("supported", True) else None
