"""Detail brush: a map the user paints over the input – more detail here, less there – used by CLIPasso and
ControlSketch: the start strokes go where there is more (their attention is weighted), and the picture is softened
where there should be less (the loss then cares less about it).

Like an edited mask it is kept per image content (``<app data>/masks/details/<image>.png``: 8-bit grey, 128 normal,
255 more, 0 less), so the queue, parallel workers and Continue find it, and a copy goes with each job.

On its way to a method's canvas the map is carried as a picture (``as_image``: red = less of "more", green = less of
"less", white = normal) through the same steps as the photo – crop, padding, scaling, a shrunk object – all of
which fill with white, so whatever lies outside the photo stays normal."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from .. import paths

NORMAL = 128
GAIN = 4.0  # attention × 4 where it is "more", ÷ 4 where it is "less"
SOFTEN = 0.012  # blur radius in "less" areas, as a share of the longer side of the picture
FILE = "detail.png"  # the copy in a job folder


def detail_dir() -> Path:
    return paths.user_data_dir() / "masks" / "details"


def detail_path(im: Image.Image, digest: str | None = None) -> Path:
    from .masking import image_key

    return detail_dir() / f"{image_key(im, digest)}.png"


def detail_map(im: Image.Image, digest: str | None = None) -> np.ndarray | None:
    """The user's map for this image: float32 in [-1, 1] (less … more) at the image size, or None."""
    try:
        with Image.open(detail_path(im, digest)) as m:
            if m.size != im.size:
                return None
            values = (np.asarray(m.convert("L"), dtype=np.float32) - NORMAL) / 127.0
    except (OSError, ValueError):
        return None
    values = np.clip(values, -1.0, 1.0)
    return values if np.abs(values).max() > 0.02 else None


def save_detail_map(im: Image.Image, values: np.ndarray, digest: str | None = None) -> Path | None:
    """Store a map (float in [-1, 1] or uint8 grey); an all-normal map removes it."""
    arr = np.asarray(values)
    if arr.dtype != np.uint8:
        arr = np.clip(np.round(NORMAL + np.clip(arr, -1, 1) * 127), 0, 255).astype(np.uint8)
    path = detail_path(im, digest)
    if np.abs(arr.astype(np.int16) - NORMAL).max() <= 2:
        path.unlink(missing_ok=True)
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + f".{os.getpid()}.tmp")
    Image.fromarray(arr, mode="L").save(tmp, format="PNG")
    os.replace(tmp, path)
    return path


def remove_detail_map(im: Image.Image, digest: str | None = None) -> None:
    detail_path(im, digest).unlink(missing_ok=True)


def detail_stamp(target: str) -> float:
    """Modification time of the input's map (0 = none) – for the input caches of the methods."""
    from .imaging import load_rgb

    try:
        return detail_path(load_rgb(target)).stat().st_mtime
    except OSError:
        return 0.0


def as_image(values: np.ndarray) -> Image.Image:
    """The map as a picture that may go through the photo's steps (white = normal)."""
    more = np.clip(values, 0, 1)
    less = np.clip(-values, 0, 1)
    rgb = np.stack([255 - more * 255, 255 - less * 255, np.full_like(values, 255)], axis=-1)
    return Image.fromarray(np.round(rgb).astype(np.uint8), mode="RGB")


def from_image(img: Image.Image, size: tuple[int, int] | None = None) -> np.ndarray:
    """The map back from such a picture (resized to ``size`` = (w, h) first)."""
    if size is not None and img.size != size:
        img = img.resize(size, Image.BILINEAR)
    arr = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    return (1.0 - arr[..., 0]) - (1.0 - arr[..., 1])


def gain(values: np.ndarray) -> np.ndarray:
    """The factor of the attention: GAIN ** detail."""
    return np.power(GAIN, values).astype(np.float32)


def soften(img: Image.Image, values: np.ndarray) -> Image.Image:
    """The picture blurred where it should have less detail (as strongly as the map says)."""
    less = np.clip(-values, 0, 1)
    if less.max() <= 0.02:
        return img
    if less.shape != (img.height, img.width):
        less = np.asarray(Image.fromarray(less.astype(np.float32), mode="F").resize(img.size, Image.BILINEAR))
    rgb = img.convert("RGB")
    blurred = rgb.filter(ImageFilter.GaussianBlur(max(1.0, SOFTEN * max(img.size))))
    a = np.asarray(rgb, dtype=np.float32)
    b = np.asarray(blurred, dtype=np.float32)
    out = a + (b - a) * less[..., None]
    return Image.fromarray(np.clip(np.round(out), 0, 255).astype(np.uint8), mode="RGB")


# ------------------------------------------------------------------ with the jobs


def save_with_job(job_dir: str, target: str) -> bool:
    """Copy the input's map into the job folder (the record; it brings the map back if the app data is lost)."""
    import shutil

    from .imaging import load_rgb

    try:
        src = detail_path(load_rgb(target))
        if src.is_file():
            shutil.copyfile(src, os.path.join(job_dir, FILE))
            return True
    except OSError:
        pass
    return False


def restore_from_job(job_dir: str, image_path: str) -> bool:
    import shutil

    from .imaging import load_rgb

    saved = os.path.join(job_dir, FILE)
    if not os.path.isfile(saved):
        return False
    try:
        dest = detail_path(load_rgb(image_path))
        if not dest.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(saved, dest)
        return True
    except OSError:
        return False
