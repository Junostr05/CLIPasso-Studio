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
    try:
        import torch

        info = {"torch": torch.__version__, "cuda_build": torch.version.cuda or "", "gpus": []}
        info["cuda"] = bool(torch.cuda.is_available() and torch.cuda.device_count() > 0)
        if info["cuda"]:
            from ..engine.pipeline import cuda_arch_supported

            for i in range(torch.cuda.device_count()):
                prop = torch.cuda.get_device_properties(i)
                info["gpus"].append({"name": prop.name, "memory_gb": round(prop.total_memory / 2 ** 30, 1),
                                     "supported": bool(cuda_arch_supported(i))})
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
    """The last answer of this app version, or None (not probed yet)."""
    info = app_settings().get("hardware")
    if isinstance(info, dict) and info.get("version") == __version__ and "error" not in info:
        return info
    return None


def has_cuda() -> bool:
    info = cached()
    return bool(info and info.get("cuda"))
