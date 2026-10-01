"""File helpers without Qt and torch: folder sizes, free space before a download, moving folders."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Iterable
from pathlib import Path

from .engine.errors import UserError

SPACE_MARGIN = 1.05  # a little more than the files themselves (file system overhead, temp files)


def folder_size(path) -> int:
    total = 0
    for dirpath, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


def entry_size(path: Path) -> int:
    try:
        return folder_size(path) if path.is_dir() else path.stat().st_size
    except OSError:
        return 0


def free_space(folder) -> int:
    """Free bytes on the drive of ``folder`` (which may not exist yet); -1 when unknown."""
    probe = Path(folder)
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        return int(shutil.disk_usage(probe).free)
    except OSError:
        return -1


def ensure_space(folder, needed: int, what: str = "") -> None:
    """Raise a :class:`UserError` (``no_space``) when the drive of ``folder`` has less than ``needed``
    bytes (plus a margin) free – before a download starts instead of failing at 95 %."""
    free = free_space(folder)
    need = int(needed * SPACE_MARGIN)
    if 0 <= free < need:
        raise UserError("no_space", f"not enough free space in {folder}: {need / 1e9:.1f} GB needed, "
                                    f"{free / 1e9:.1f} GB free", folder=str(folder), need=f"{need / 1e9:.1f}",
                        free=f"{free / 1e9:.1f}", what=what)


def move_entries(src, dst, names: Iterable[str] | None = None,
                 progress: Callable[[int, int], None] | None = None) -> int:
    """Move the entries ``names`` of ``src`` (all when None) into ``dst``: a rename on the same drive,
    otherwise copy + delete. Folders that already exist in ``dst`` are merged. Returns the bytes moved."""
    src, dst = Path(src), Path(dst)
    dst.mkdir(parents=True, exist_ok=True)
    if names is None:
        entries = sorted(src.iterdir()) if src.is_dir() else []
    else:
        entries = [src / n for n in names if (src / n).exists()]
    sizes = [entry_size(e) for e in entries]
    total, done = sum(sizes) or 1, 0
    for e, size in zip(entries, sizes):
        target = dst / e.name
        if target.exists() and e.is_dir():
            shutil.copytree(e, target, dirs_exist_ok=True)
            shutil.rmtree(e)
        else:
            if target.exists():
                target.unlink()
            shutil.move(str(e), str(target))
        done += size
        if progress:
            progress(done, total)
    return done


def clear_folder(folder, keep: Iterable[str] = ()) -> int:
    """Delete what is in ``folder`` (the folder itself stays), except the files in ``keep``; files in
    use stay too. Returns the bytes freed."""
    keep_set = {os.path.normcase(os.path.abspath(k)) for k in keep if k}
    return _clear(Path(folder), keep_set)


def _clear(folder: Path, keep: set[str]) -> int:
    freed = 0
    try:
        children = list(folder.iterdir())
    except OSError:
        return 0
    for child in children:
        if child.is_dir() and not child.is_symlink():
            freed += _clear(child, keep)
            try:
                child.rmdir()  # only when empty
            except OSError:
                pass
            continue
        if os.path.normcase(os.path.abspath(child)) in keep:
            continue
        size = entry_size(child)
        try:
            child.unlink()
            freed += size
        except OSError:  # in use (e.g. by a running job): stays
            pass
    return freed
