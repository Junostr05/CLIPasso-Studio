"""How much detail a photo has – and the number of strokes that suits it.

The measure is the **edge density**: the share of pixels on a clear edge (Sobel on the softened brightness, at
256 px) inside the object – its bounding box when the object mask is known, else the whole picture. A plain object
on a calm background has few edges, a furry animal or a busy scene many.

The recommendation maps the density to a number of strokes per method. The limits were set with the quality
benchmark (``tools/benchmark.py --suite``): every picture sketched with 8, 16 and 32 strokes and graded by the
independent judge; the recommendation is the smallest number that comes close to the best grade."""

from __future__ import annotations

import numpy as np

SIDE = 256  # px: the photo is looked at this large
BLUR = 1.2  # px: softened first, so noise and fine texture are not edges
EDGE = 0.12  # Sobel magnitude (brightness 0..1) from which a pixel is on an edge

# per method: (density limits, the stroke counts between them) – fewer details, fewer strokes
LEVELS = ("few", "some", "many", "very_many")
RECOMMEND: dict[str, tuple[tuple[float, ...], tuple[int, ...]]] = {
    "clipasso": ((0.06, 0.11, 0.17), (8, 16, 24, 32)),
    "controlsketch": ((0.06, 0.11, 0.17), (16, 24, 32, 48)),
}
STROKE_KEY = {"clipasso": "num_paths", "controlsketch": "num_strokes"}


def _brightness(im, side: int = SIDE) -> np.ndarray:
    from PIL import Image, ImageFilter

    im = im.convert("L")
    im.thumbnail((side, side), Image.BILINEAR)
    im = im.filter(ImageFilter.GaussianBlur(BLUR))
    return np.asarray(im, dtype=np.float32) / 255.0


def _box(mask: np.ndarray | None, shape: tuple[int, int]) -> tuple[slice, slice]:
    """The region to look at: the object's bounding box (in the scaled picture), else everything."""
    if mask is None or not np.any(mask):
        return slice(None), slice(None)
    h, w = shape
    mh, mw = mask.shape
    rows, cols = np.flatnonzero(mask.any(axis=1)), np.flatnonzero(mask.any(axis=0))
    top, bottom = int(rows[0] * h / mh), int(np.ceil((rows[-1] + 1) * h / mh))
    left, right = int(cols[0] * w / mw), int(np.ceil((cols[-1] + 1) * w / mw))
    return slice(top, max(bottom, top + 2)), slice(left, max(right, left + 2))


def edge_density(im, mask: np.ndarray | None = None) -> float:
    """The share (0..1) of edge pixels of a PIL image, inside the object's box when ``mask`` (bool, any size of the
    same aspect) is given."""
    g = _brightness(im)
    if g.shape[0] < 3 or g.shape[1] < 3:
        return 0.0
    # Sobel, scaled so a step from black to white gives 1
    gx = (g[:-2, 2:] + 2 * g[1:-1, 2:] + g[2:, 2:] - g[:-2, :-2] - 2 * g[1:-1, :-2] - g[2:, :-2]) / 4.0
    gy = (g[2:, :-2] + 2 * g[2:, 1:-1] + g[2:, 2:] - g[:-2, :-2] - 2 * g[:-2, 1:-1] - g[:-2, 2:]) / 4.0
    edges = np.hypot(gx, gy) > EDGE
    rows, cols = _box(mask, edges.shape)
    region = edges[rows, cols]
    return float(region.mean()) if region.size else 0.0


def recommend(method: str, density: float) -> tuple[int, str] | None:
    """(strokes, level) for a method that has a free number of strokes, None otherwise (SwiftSketch: fixed;
    SceneSketch: its strokes per layer are set with the abstraction levels)."""
    if method not in RECOMMEND:
        return None
    limits, counts = RECOMMEND[method]
    i = int(np.searchsorted(np.asarray(limits), density, side="right"))
    return counts[i], LEVELS[i]


def analyse(path: str, mask: np.ndarray | None = None) -> float:
    """The edge density of a photo file."""
    from .imaging import load_rgb

    return edge_density(load_rgb(path), mask)
