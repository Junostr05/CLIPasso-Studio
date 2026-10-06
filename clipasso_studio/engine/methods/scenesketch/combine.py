"""Combining the object and background sketches of a scene (``scripts/combine_matrix.py``).

The original rasterises both sketches, whites out the object area in the background raster and
pastes the object strokes on top. Here the same is done with the vectors, so the combined scene
stays a plain stroke SVG: object strokes are scaled back from the enlarged object canvas
(``resize_params``), and background strokes are cut where they enter the object mask (the parts
outside are exact sub-curves of the original Bézier curves).
"""

from __future__ import annotations

import numpy as np
import torch
from PIL import Image

from ... import renderer


def object_to_scene(paths, params: dict, canvas: int):
    """``read_svg(..., resize_obj=True, params=...)``: undo the enlargement of the object."""
    if not params:
        return list(paths)
    out = []
    w, h = params["scale_w"], params["scale_h"]
    for path in paths:
        p = path.points.detach().clone().float() / canvas
        p = 2 * p - 1
        p[:, 0] /= w
        p[:, 1] /= h
        p = 0.5 * (p + 1.0) * canvas
        p[:, 0] += params["original_center_x"] * canvas - canvas / 2
        p[:, 1] += params["original_center_y"] * canvas - canvas / 2
        out.append(renderer.Path(path.num_control_points, p, path.stroke_width, is_closed=False))
    return out


def _bezier(ctrl: np.ndarray, t: np.ndarray) -> np.ndarray:
    n = len(ctrl) - 1
    from math import comb

    basis = np.stack([comb(n, i) * (1 - t) ** (n - i) * t ** i for i in range(n + 1)], axis=1)
    return basis @ ctrl


def _split(ctrl: np.ndarray, t: float) -> tuple[np.ndarray, np.ndarray]:
    """de Casteljau: the curve on [0, t] and on [t, 1]."""
    left, right = [ctrl[0]], [ctrl[-1]]
    pts = ctrl
    while len(pts) > 1:
        pts = (1 - t) * pts[:-1] + t * pts[1:]
        left.append(pts[0])
        right.append(pts[-1])
    return np.array(left), np.array(right[::-1])


def _subcurve(ctrl: np.ndarray, t0: float, t1: float) -> np.ndarray:
    if t1 < 1.0:
        ctrl, _ = _split(ctrl, t1)
    if t0 > 0.0:
        _, ctrl = _split(ctrl, t0 / t1 if t1 > 0 else 0.0)
    return ctrl


def mask_for_canvas(mask: np.ndarray, canvas: int) -> np.ndarray:
    """Binary object mask (any size) resized to the canvas."""
    img = Image.fromarray((np.asarray(mask) > 0.5).astype(np.uint8) * 255)
    return np.asarray(img.resize((canvas, canvas), Image.BILINEAR)) >= 128


def cut_by_mask(paths, mask: np.ndarray, canvas: int, samples: int = 160, min_length: float = 1.0):
    """Parts of the (single-segment) strokes outside ``mask`` ([canvas, canvas] bool)."""
    out = []
    t = np.linspace(0.0, 1.0, samples)
    for path in paths:
        ctrl = path.points.detach().cpu().double().numpy()
        pts = _bezier(ctrl, t)
        ix = np.clip(np.floor(pts[:, 0]).astype(int), 0, canvas - 1)
        iy = np.clip(np.floor(pts[:, 1]).astype(int), 0, canvas - 1)
        inside_canvas = (pts[:, 0] >= 0) & (pts[:, 0] < canvas) & (pts[:, 1] >= 0) & (pts[:, 1] < canvas)
        keep = ~(mask[iy, ix] & inside_canvas)
        if keep.all():
            out.append(path)
            continue
        # runs of kept samples -> parameter intervals (cut half way between samples)
        idx = np.flatnonzero(np.diff(np.concatenate([[0], keep.astype(int), [0]])))
        for start, stop in zip(idx[::2], idx[1::2]):
            t0 = 0.0 if start == 0 else (t[start - 1] + t[start]) / 2
            t1 = 1.0 if stop == samples else (t[stop - 1] + t[stop]) / 2
            if t1 - t0 <= 1e-6:
                continue
            sub = _subcurve(ctrl, t0, t1)
            if np.linalg.norm(np.diff(_bezier(sub, np.linspace(0, 1, 8)), axis=0), axis=1).sum() < min_length:
                continue
            # on the device of the stroke: the kept strokes stay on the graphics card, and the renderer
            # stacks all of them
            out.append(renderer.Path(path.num_control_points,
                                     torch.tensor(sub, dtype=torch.float32, device=path.points.device),
                                     path.stroke_width, is_closed=False))
    return out


def combine(background_paths, object_paths, mask_canvas: np.ndarray | None, canvas: int):
    """Background strokes outside the object + object strokes (already in scene coordinates)."""
    bg = list(background_paths)
    if mask_canvas is not None and object_paths:
        bg = cut_by_mask(bg, mask_canvas, canvas)
    return bg + list(object_paths)


def matrix_image(cells: dict, layers: list[int], levels, cell_px: int = 200, gap: int = 12) -> Image.Image:
    """Grid of the cell PNGs: one column per fidelity layer, one row per simplicity level (``levels``: the computed
    levels, or their number for 0 … levels)."""
    levels = list(range(levels + 1)) if isinstance(levels, int) else list(levels)
    rows, cols = len(levels), len(layers)
    img = Image.new("RGB", (cols * cell_px + (cols + 1) * gap, rows * cell_px + (rows + 1) * gap), "white")
    for c, layer in enumerate(layers):
        for r, level in enumerate(levels):
            path = cells.get((layer, level))
            if not path:
                continue
            try:
                tile = Image.open(path).convert("RGB").resize((cell_px, cell_px), Image.LANCZOS)
            except OSError:
                continue
            img.paste(tile, (gap + c * (cell_px + gap), gap + r * (cell_px + gap)))
    return img
