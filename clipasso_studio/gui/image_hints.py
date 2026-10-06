"""Quality hints for the studio's photo, before a run: too small, too dark, too flat, blurred – and, once its object
mask is there, an object that is very small in the picture, no object found or a mask that is unsure. Each hint
says what helps (crop, check the mask); the user can switch a kind off ("hints_off").

The limits are set on the sample pictures and real photos (COCO) and on worse copies of them (blurred, darker,
flatter): no hint for any of the originals, a hint for the clearly worse copies."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

MIN_SIDE = 224  # px: smaller photos are enlarged for CLIP (224 px) – the samples have 225 and more
DARK = 0.40  # the brightest parts (97th percentile of the brightness, 0..1) below: too dark
FLAT = 0.35  # brightness spread (97th − 3rd percentile) below: too little contrast
BLURRY = 0.30  # edge sharpness (99.5th percentile of the Laplacian) per brightness spread below: blurred
ANALYSIS_SIDE = 512  # px: the photo is looked at this large (sharpness is measured at this scale)
SMALL_OBJECT = 0.08  # the object's bounding box below this share of the picture: very small
NO_OBJECT = 0.002  # object share below: no object found (the whole picture is drawn)
UNSURE = 0.30  # share of the mask's pixels the model is unsure about (probability between 0.05 and 0.95)

ORDER = ("no_object", "small_object", "unsure_mask", "small", "blurry", "dark", "flat")  # the most helpful first
ACTIONS = {"no_object": "mask", "small_object": "crop", "unsure_mask": "mask"}  # what the hint's button does


@dataclass
class Hint:
    key: str
    values: dict = field(default_factory=dict)

    @property
    def action(self) -> str:
        return ACTIONS.get(self.key, "")


def _brightness(im) -> np.ndarray:
    from PIL import Image

    im = im.convert("RGB")
    im.thumbnail((ANALYSIS_SIDE, ANALYSIS_SIDE), Image.BILINEAR)
    a = np.asarray(im, dtype=np.float32) / 255.0
    return 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]


def measure(im) -> dict:
    """Brightness, contrast and sharpness of a PIL image (``photo_hints`` decides with them)."""
    g = _brightness(im)
    low, high = (float(v) for v in np.percentile(g, (3, 97)))
    spread = high - low
    if g.shape[0] > 2 and g.shape[1] > 2:
        lap = -4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
        edge = float(np.percentile(np.abs(lap), 99.5))
    else:
        edge = 0.0
    return {"bright": high, "spread": spread, "sharpness": edge / spread if spread > 1e-3 else 0.0}


def photo_hints(path: str, progress=None) -> list[Hint]:
    """The hints about the photo itself (``progress``: for ``dialogs.run_in_thread``)."""
    from ..engine.imaging import load_rgb
    from . import image_io

    size = image_io.image_size(path)
    w, h = size.width(), size.height()
    hints = []
    if 0 < min(w, h) < MIN_SIDE:
        hints.append(Hint("small", {"w": w, "h": h, "min": MIN_SIDE}))
    m = measure(load_rgb(path))
    if m["bright"] < DARK:
        hints.append(Hint("dark"))
    elif m["spread"] < FLAT:
        hints.append(Hint("flat"))
    if m["sharpness"] < BLURRY and m["spread"] >= 0.05:
        hints.append(Hint("blurry"))
    return hints


def mask_hints(prob: np.ndarray | None, edited: np.ndarray | None = None, threshold: float = 0.5) -> list[Hint]:
    """The hints about the object mask: its probability (the model's), or the user's edited mask (then only the
    object's size counts – the user has checked it)."""
    if prob is None and edited is None:
        return []
    mask = edited.astype(bool) if edited is not None else prob >= threshold
    share = float(mask.mean()) if mask.size else 0.0
    if share < NO_OBJECT:
        return [Hint("no_object")]
    hints = []
    rows, cols = np.flatnonzero(mask.any(axis=1)), np.flatnonzero(mask.any(axis=0))
    box = (rows[-1] - rows[0] + 1) * (cols[-1] - cols[0] + 1) / mask.size
    if box < SMALL_OBJECT:
        hints.append(Hint("small_object", {"percent": max(1, round(box * 100))}))
    if edited is None:
        seen = prob > 0.05
        unsure = float((seen & (prob < 0.95)).sum()) / max(int(seen.sum()), 1)
        if unsure > UNSURE:
            hints.append(Hint("unsure_mask", {"percent": round(unsure * 100)}))
    return hints


def shown(hints: list[Hint], off: list[str] | tuple = ()) -> list[Hint]:
    """The hints to show: the kinds not switched off, the most helpful first."""
    return sorted((h for h in hints if h.key not in off), key=lambda h: ORDER.index(h.key))
