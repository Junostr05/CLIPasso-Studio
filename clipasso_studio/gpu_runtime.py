"""An extra PyTorch build for graphics cards the bundled one has no kernels for (GTX 9xx / 10xx …).

The GPU edition bundles PyTorch with CUDA 12.8: compute capability 7.5 and newer (GTX 16xx, RTX 20xx up to
RTX 50xx). Maxwell and Pascal cards (e.g. a GTX 1060, capability 6.1) are only in PyTorch's CUDA 12.6 build.
For them the app downloads that build once – the official wheels of torch and torchvision, checked by their
SHA-256 – and unpacks them into ``<app data>/runtimes/<name>``. When it is switched on (app setting
``gpu_runtime``), :func:`activate` puts it in front of the bundled PyTorch at the start of every process
(the window, the hardware probe and the workers), before anything imports torch. The bundled PyTorch stays
in the app and is used again as soon as the runtime is switched off or does not match the app's PyTorch.

Without Qt and torch: it runs before both are imported.
"""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import json
import os
import shutil
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import paths

TORCH_VERSION = "2.11.0"  # the app's PyTorch (requirements/torch-gpu.txt): a runtime must be built for it
PACKAGES = ("torch", "torchgen", "functorch", "torchvision")  # imported from the runtime when it is on
SETTING = "gpu_runtime"  # app setting: the name of the runtime that is switched on ("" = off)
ENV = "CLIPASSO_GPU_RUNTIME"  # a runtime folder to use, whatever the settings say (CI, tests; set for workers)
MARKER = "runtime.json"
SYSTEM_LIBS = ("vcruntime", "msvcp", "concrt", "vcomp", "api-ms-", "ucrtbase", "libgomp", "libstdc++")  # shared
_PYTORCH = "https://download.pytorch.org/whl/cu126/"


@dataclass(frozen=True)
class Wheel:
    name: str
    url: str
    sha256: str
    size: int


@dataclass(frozen=True)
class Runtime:
    name: str
    cuda: str
    min_capability: tuple[int, int]  # the oldest cards it has kernels for
    below: tuple[int, int]  # the bundled PyTorch covers this capability and newer: no runtime needed
    wheels: tuple[Wheel, ...]
    unpacked: int  # bytes on the disk

    @property
    def download_size(self) -> int:
        return sum(w.size for w in self.wheels)


LEGACY = Runtime(
    name=f"torch-{TORCH_VERSION}-cu126",
    cuda="12.6",
    min_capability=(5, 0),
    below=(7, 5),
    wheels=(
        Wheel("torch-2.11.0+cu126-cp311-cp311-win_amd64.whl",
              _PYTORCH + "torch-2.11.0%2Bcu126-cp311-cp311-win_amd64.whl",
              "ce9aeead7950ae8eb48891568f9314a9a4130996b55e797c75e0c0d2846714ae", 2_596_413_186),
        Wheel("torchvision-0.26.0+cu126-cp311-cp311-win_amd64.whl",
              _PYTORCH + "torchvision-0.26.0%2Bcu126-cp311-cp311-win_amd64.whl",
              "67eb5dab7ae058e4a7ce44c682db8dbf28a9b381a658c7f778f08029d37574d4", 8_474_493),
    ),
    unpacked=4_160_000_000,
)

_state: dict = {"site": None}


# ----------------------------------------------------------------------------- where


def runtimes_root() -> Path:
    return paths.user_data_dir() / "runtimes"


def runtime_dir(rt: Runtime = LEGACY, root: Path | None = None) -> Path:
    return (root or runtimes_root()) / rt.name


def _marker(folder: Path) -> dict | None:
    try:
        data = json.loads((folder / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("complete") else None


def is_installed(rt: Runtime = LEGACY, root: Path | None = None) -> bool:
    data = _marker(runtime_dir(rt, root))
    return bool(data and data.get("name") == rt.name and data.get("torch") == TORCH_VERSION)


def setting() -> str:
    data = paths.read_settings_file() or {}
    value = data.get(SETTING)
    return value if isinstance(value, str) else ""


def wanted() -> Path | None:
    """The runtime folder this process should use, or None (the bundled PyTorch)."""
    forced = os.environ.get(ENV)
    if forced:  # (inherited by a new version started by an update: only for the same PyTorch)
        folder = Path(forced)
        data = _marker(folder)
        return folder if data and data.get("torch") == TORCH_VERSION else None
    if setting() == LEGACY.name and is_installed():
        return runtime_dir()
    return None


# ----------------------------------------------------------------------------- use


class _Finder(importlib.abc.MetaPathFinder):
    """Finds the packages of the runtime there first (before the bundled ones of the frozen app)."""

    def __init__(self, site: str):
        self.site = site

    def find_spec(self, fullname, path=None, target=None):
        if fullname in PACKAGES:
            return importlib.machinery.PathFinder.find_spec(fullname, [self.site])
        return None  # submodules follow their package's __path__, which lies in the runtime


def activate() -> Path | None:
    """Use the runtime in this process if it is switched on (call before anything imports torch)."""
    if _state["site"] is not None:
        return _state["site"]
    if any(name in sys.modules for name in PACKAGES):
        return None  # too late: the bundled PyTorch is loaded
    site = wanted()
    if site is None:
        return None
    sys.path.insert(0, str(site))
    sys.meta_path.insert(0, _Finder(str(site)))
    os.environ[ENV] = str(site)  # worker processes use the same PyTorch as the window
    _state["site"] = site
    return site


def active() -> Path | None:
    return _state["site"]


def forget_for_children() -> None:
    """Before starting the app again (restart, update): the new process follows the settings, not this one."""
    os.environ.pop(ENV, None)


def active_name() -> str:
    site = active()
    data = _marker(site) if site else None
    return str(data.get("name", "")) if data else ""


def helps(info: dict | None, rt: Runtime = LEGACY) -> list[str]:
    """The GPUs of a hardware probe (gui/hardware.py) that the bundled PyTorch cannot use but the
    runtime can."""
    names = []
    for gpu in (info or {}).get("gpus") or []:
        cap = tuple(gpu.get("capability") or ())
        if not gpu.get("supported", True) and len(cap) == 2 and rt.min_capability <= cap < rt.below:
            names.append(str(gpu.get("name", "GPU")))
    return names


# ----------------------------------------------------------------------------- install


def install(rt: Runtime = LEGACY, root: Path | None = None, progress=None, cancel=None, phase=None) -> Path:
    """Download (continuing an interrupted download), verify and unpack the runtime; returns its folder.
    ``phase`` is told "download", "check" and "unpack" (for the progress text)."""
    phase = phase or (lambda name: None)
    from .engine.errors import UserError
    from .engine.model_store import _download_url, _sha256
    from .fileops import ensure_space

    root = Path(root) if root else runtimes_root()
    part = root / ".partial"
    part.mkdir(parents=True, exist_ok=True)
    have = 0
    for w in rt.wheels:
        target = part / w.name
        if target.is_file():
            have += min(target.stat().st_size, w.size)
    ensure_space(root, rt.download_size - have + rt.unpacked, "gpu runtime")
    total, done = rt.download_size, 0
    phase("download")
    for w in rt.wheels:
        target = part / w.name
        ok = target.with_name(target.name + ".ok")
        if not (ok.is_file() and target.is_file() and target.stat().st_size == w.size):
            for attempt in range(4):
                offset = target.stat().st_size if target.is_file() and target.stat().st_size < w.size else 0
                if offset == 0 and target.exists():
                    target.unlink()
                prog = (lambda d, t, base=done: progress(base + d, total)) if progress else None
                try:
                    _download_url(w.url, target, prog, cancel, offset=offset)
                    break
                except InterruptedError:
                    raise  # cancelled: the partial file stays for the next try
                except Exception:
                    if attempt == 3:
                        raise
                    time.sleep(2 ** attempt)
            phase("check")
            if progress:
                progress(0, 0)  # checking
            if _sha256(target) != w.sha256:
                target.unlink()
                raise UserError("runtime_checksum", f"{w.name}: the checksum does not match – please try again",
                                file=w.name)
            ok.write_text(w.sha256, encoding="utf-8")
            phase("download")
        done += w.size
    phase("unpack")
    final, tmp = runtime_dir(rt, root), root / (rt.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    zips = [zipfile.ZipFile(part / w.name) for w in rt.wheels]
    try:
        base = os.path.normpath(tmp) + os.sep
        members = [(zf, m, os.path.normpath(os.path.join(tmp, m.filename))) for zf in zips for m in zf.infolist()
                   if not m.is_dir()]
        members = [(zf, m, dest) for zf, m, dest in members if dest.startswith(base)]  # none out of the folder
        size, unpacked = sum(m.file_size for _, m, _ in members) or 1, 0
        for zf, m, dest in members:
            if cancel and cancel():
                raise InterruptedError("cancelled")
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with zf.open(m) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)
            unpacked += m.file_size
            if progress:
                progress(unpacked, size)
    except BaseException:
        for zf in zips:
            zf.close()
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    for zf in zips:
        zf.close()
    (tmp / MARKER).write_text(json.dumps({"name": rt.name, "torch": TORCH_VERSION, "cuda": rt.cuda,
                                          "complete": True}), encoding="utf-8")
    if final.exists():
        shutil.rmtree(final)
    os.replace(tmp, final)
    shutil.rmtree(part, ignore_errors=True)
    return final


def remove(rt: Runtime = LEGACY, root: Path | None = None) -> bool:
    """Delete the runtime (True); while a process still uses it (Windows keeps its DLLs open), it is
    only marked and deleted by :func:`cleanup` at a later start (False)."""
    folder = runtime_dir(rt, root)
    if active() is not None and folder.resolve() == active().resolve():
        try:  # running jobs keep it until the end; not used again, deleted by cleanup() at the next start
            (folder / MARKER).unlink()
        except OSError:
            pass
        return False
    shutil.rmtree(folder, ignore_errors=True)
    return not folder.exists()


def cleanup(root: Path | None = None) -> int:
    """Remove what is not needed: runtimes of other app versions, half-unpacked or removed ones (never
    the one this process uses). Returns the folders removed."""
    root = Path(root) if root else runtimes_root()
    keep = {active().resolve()} if active() else set()
    if is_installed(LEGACY, root):
        keep.add(runtime_dir(LEGACY, root).resolve())
    removed = 0
    try:
        entries = list(root.iterdir())
    except OSError:
        return 0
    for entry in entries:
        if not entry.is_dir() or entry.name == ".partial" or entry.resolve() in keep:
            continue
        shutil.rmtree(entry, ignore_errors=True)
        removed += not entry.exists()
    return removed


# ----------------------------------------------------------------------------- check (CI)


def check() -> dict:
    """Which PyTorch this process loaded, and whether it is the wanted one (``--gpu-runtime-check``)."""
    import torch

    site = active()
    info = {"torch": torch.__version__, "cuda": torch.version.cuda, "file": torch.__file__,
            "runtime": str(site or ""), "outside": []}
    if site is not None:
        root = os.path.normcase(os.path.abspath(site))
        info["ok"] = os.path.normcase(os.path.abspath(torch.__file__)).startswith(root)
        lib = Path(site) / "torch" / "lib"  # every library the runtime has must be loaded from there
        names = {p.name.lower() for p in lib.iterdir() if p.is_file()} if lib.is_dir() else set()
        names = {n for n in names if n.endswith((".dll", ".so")) or ".so." in n}
        names -= {n for n in names if n.startswith(SYSTEM_LIBS)}
        try:
            import psutil

            loaded = set()
            for mm in psutil.Process().memory_maps():
                path = os.path.normcase(os.path.abspath(mm.path))
                name = os.path.basename(path).lower()
                if name in names:
                    if path.startswith(root):
                        loaded.add(name)
                    else:
                        info["outside"].append(mm.path)
            info["loaded"] = len(loaded)  # (none would mean the check saw nothing)
        except Exception as exc:  # noqa: BLE001 - reported
            info["maps_error"] = str(exc)
        info["ok"] = info["ok"] and not info["outside"] and (info.get("loaded", 0) > 0 or not names)
    else:
        info["ok"] = not os.environ.get(ENV)
    return info
