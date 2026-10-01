"""Images from a drop or a folder: files are taken as they are, folders with everything in them."""

from __future__ import annotations

import os

from ..engine import jobs

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff", ".gif", ".heic", ".heif", ".avif")


def image_files(folder: str, recursive: bool = False) -> list[str]:
    """Images in a folder, sorted by name; folders of the app's own results are skipped."""
    out = []
    for dirpath, dirnames, filenames in os.walk(folder):
        if os.path.isfile(os.path.join(dirpath, "job.json")) or os.path.isfile(os.path.join(dirpath, jobs.STATE_FILE)):
            dirnames[:] = []
            continue
        skip = (".", "_edited", "_pasted", "_webcam", "_continued")
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(skip))
        out += [os.path.join(dirpath, f) for f in sorted(filenames, key=str.lower) if f.lower().endswith(IMAGE_EXT)]
        if not recursive:
            break
    return out


def dropped_paths(mime) -> list[str]:
    """Local files and folders of a drop (QMimeData), as the system writes paths (Qt gives "C:/x/y.png"
    on Windows; joined with folder contents that would become "C:/x\\y.png")."""
    if mime is None or not mime.hasUrls():
        return []
    return [os.path.normpath(u.toLocalFile()) for u in mime.urls() if u.isLocalFile() and u.toLocalFile()]


def has_images(mime) -> bool:
    """A drop the app can use: an image file or a folder."""
    return any(os.path.isdir(p) or p.lower().endswith(IMAGE_EXT) for p in dropped_paths(mime))


def dropped_images(mime) -> list[str]:
    """The images of a drop: image files, and every image in dropped folders (with subfolders)."""
    out: list[str] = []
    for p in dropped_paths(mime):
        if os.path.isdir(p):
            out += image_files(p, recursive=True)
        elif p.lower().endswith(IMAGE_EXT) and os.path.isfile(p):
            out.append(p)
    seen = set()
    return [p for p in out if not (p in seen or seen.add(p))]
