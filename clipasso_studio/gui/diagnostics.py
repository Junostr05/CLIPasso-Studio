"""Diagnostics: one text with what a bug report needs (settings → "Copy / save diagnostics").

Version and edition, system, memory, what PyTorch sees (from the hardware probe, the app itself runs
without torch), the folders with their free space, the installed models, the newest crash logs and the
last lines of the app's log. Kept in English on purpose: it is read by whoever fixes the bug.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
import time
from pathlib import Path

from .. import APP_NAME, __version__, logs, paths

LOG_LINES = 50
SETTING_KEYS = ("language", "theme", "ui_scale", "canvas_style", "keep_models_loaded", "parallel_sketches",
                "watch_enabled", "check_updates", "gpu_runtime", "gpu_precision")


def _gb(n: float) -> str:
    return f"{n / 1e9:.1f} GB"


def edition() -> str:
    from .updates import build_info

    ed, mode = build_info()
    return ed if ed == "dev" else f"{ed}, {mode}"


def cpu_name() -> str:
    name = ""
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.startswith("model name"):
                        name = line.split(":", 1)[1].strip()
                        break
        except OSError:
            pass
    return name or platform.processor() or platform.machine() or "?"


def memory() -> tuple[int, int]:
    """(total, available) RAM in bytes; (0, 0) when unknown."""
    try:
        import psutil

        vm = psutil.virtual_memory()
        return int(vm.total), int(vm.available)
    except Exception:
        return 0, 0


def hardware_lines(info: dict | None) -> list[str]:
    """What PyTorch sees (the answer of ``hardware.probe``)."""
    if not info:
        return ["PyTorch: not checked yet"]
    if info.get("error"):
        return [f"PyTorch: {info['error']}"]
    runtime = f" · runtime {info['runtime']}" if info.get("runtime") else ""  # PyTorch for older GPUs
    lines = [f"PyTorch {info.get('torch', '?')} · CUDA build {info.get('cuda_build') or '–'}{runtime}"]
    for i, gpu in enumerate(info.get("gpus") or []):
        note = "" if gpu.get("supported", True) else " · NOT SUPPORTED by this PyTorch"
        cap = gpu.get("capability")
        cap = f" · compute {cap[0]}.{cap[1]}" if isinstance(cap, list) and len(cap) == 2 else ""
        lines.append(f"GPU {i}: {gpu.get('name', '?')} · {gpu.get('memory_gb', 0):.1f} GB{cap}{note}")
    if not info.get("gpus"):
        lines.append("GPU: none usable (CPU only)")
    return lines


def _hardware() -> dict | None:
    try:
        from . import hardware

        return hardware.cached()
    except Exception:
        return None


def header() -> str:
    """One line for the head of a crash log."""
    parts = [f"{APP_NAME} {__version__} ({edition()})", f"{platform.system()} {platform.release()}",
             f"Python {platform.python_version()}"]
    info = _hardware()
    if info and not info.get("error"):
        parts.append(f"torch {info.get('torch', '?')}")
        parts.append(f"CUDA {info.get('cuda_build') or '–'}")
        gpus = info.get("gpus") or []
        parts.append(" + ".join(f"{g.get('name', '?')} {g.get('memory_gb', 0):.0f} GB" for g in gpus) or "no GPU")
    return " · ".join(parts)


def _folder_line(label: str, folder) -> str:
    text = f"{label}: {folder}"
    try:
        probe = Path(folder)
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent
        text += f" ({_gb(shutil.disk_usage(probe).free)} free)"
    except (OSError, ValueError):
        pass
    return text


def model_lines() -> list[str]:
    try:
        from ..engine import model_store
    except Exception as exc:  # noqa: BLE001 - the report goes on without
        return [f"(cannot list: {exc})"]
    bundled = paths.bundled_models_dir()
    lines = []
    for key, spec in sorted(model_store.SPECS.items()):
        found = model_store.find(key)
        if found is None:
            continue
        where = "bundled" if bundled in found.parents else "downloaded"
        lines.append(f"{key} ({where}, ~{spec.stored_size_mb} MB)")
    return lines or ["(none)"]


def report() -> str:
    from .app_settings import app_settings

    s = app_settings()
    total, available = memory()
    cores_logical = os.cpu_count() or 0
    try:
        import psutil

        cores = psutil.cpu_count(logical=False) or 0
    except Exception:
        cores = 0
    out = [f"{APP_NAME} diagnostics · {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
    out += ["[App]", f"Version: {__version__} ({edition()})", f"Program: {sys.executable}",
            "Settings: " + ", ".join(f"{k}={s.get(k)!r}" for k in SETTING_KEYS), ""]
    out += ["[System]", f"OS: {platform.platform()}", f"Python: {platform.python_version()}",
            f"CPU: {cpu_name()} · {cores or '?'} cores / {cores_logical} threads",
            f"RAM: {_gb(total)}, {_gb(available)} available" if total else "RAM: ?", ""]
    out += ["[PyTorch]", *hardware_lines(_hardware()), ""]
    out += ["[Folders]", _folder_line("Data", paths.user_data_dir()),
            _folder_line("Output", s.get("output_dir")), _folder_line("Models", paths.downloaded_models_dir()),
            f"Bundled models: {paths.bundled_models_dir()}", ""]
    out += ["[Models]", *model_lines(), ""]
    crashes = sorted(logs.logs_dir().glob("crash-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:5]
    workers = [p.name for p in logs.logs_dir().glob("worker-*.log") if p.stat().st_size > 0]
    out += ["[Crash logs]", *([p.name for p in crashes] + workers or ["(none)"]), ""]
    lines = logs.tail(logs.logs_dir() / "app.log", LOG_LINES)
    out += [f"[app.log, last {LOG_LINES} lines]", *(lines or ["(empty)"])]
    return "\n".join(out) + "\n"


def save(path: str) -> None:
    Path(path).write_text(report(), encoding="utf-8")


def default_file_name() -> str:
    return f"clipasso-studio-diagnostics-{time.strftime('%Y%m%d-%H%M%S')}.txt"
