"""The app's own files on the disk (settings → Storage): caches and leftovers that can be cleared, and
moving the results when the output folder changes."""

from __future__ import annotations

import os
from pathlib import Path

from .. import fileops, paths
from ..engine import jobs
from .app_settings import app_settings

AREAS = ("masks", "thumbs", "updates", "inputs")
INPUT_DIRS = ("_pasted", "_edited", "_webcam", "_continued")  # images made in the app, in the output folder


def folders(key: str) -> list[Path]:
    data = paths.user_data_dir()
    if key == "masks":
        return [data / "cache" / "masks"]
    if key == "thumbs":
        return [data / "cache" / "thumbs"]
    if key == "updates":
        return [data / "updates"]
    if key == "inputs":
        out = app_settings().get("output_dir") or ""
        return [Path(out) / d for d in INPUT_DIRS] if out else []
    raise KeyError(key)


def size(key: str) -> int:
    return sum(fileops.folder_size(f) for f in folders(key) if f.is_dir())


def sizes() -> dict[str, int]:
    return {key: size(key) for key in AREAS}


def clear(key: str, keep=()) -> int:
    """Empty an area; files in ``keep`` stay (e.g. pasted images that wait in the queue). Returns the
    bytes freed."""
    return sum(fileops.clear_folder(f, keep) for f in folders(key) if f.is_dir())


# ----------------------------------------------------------------------------- output folder


def result_entries(root) -> list[str]:
    """What moves with the output folder: job folders and the app's image folders – nothing else (the
    output folder may be a folder with other files of the user)."""
    names = []
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return names
    for name in entries:
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
        if name in INPUT_DIRS or os.path.isfile(os.path.join(path, "job.json")) or \
                os.path.isfile(os.path.join(path, jobs.STATE_FILE)):
            names.append(name)
    return names


def results_size(root) -> int:
    return sum(fileops.folder_size(os.path.join(root, n)) for n in result_entries(root))


def move_results(src, dst, progress=None) -> int:
    """Move the results (see :func:`result_entries`) from ``src`` to ``dst``; returns the bytes moved.
    The paths saved in the jobs are found again by :func:`jobs.rebase`."""
    return fileops.move_entries(src, dst, result_entries(src), progress=progress)


def relocated(path: str, old: str, new: str) -> str:
    """``path`` below the folder ``old`` → the same place below ``new``."""
    if not path:
        return path
    norm_old = os.path.normcase(os.path.abspath(old))
    norm = os.path.normcase(os.path.abspath(path))
    if norm == norm_old or norm.startswith(norm_old.rstrip("\\/") + os.sep):
        return os.path.join(new, os.path.relpath(os.path.abspath(path), os.path.abspath(old)))
    return path
