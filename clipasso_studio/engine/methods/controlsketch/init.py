"""Stroke initialisation of ControlSketch.

An attention map of the object (CLIP ViT-B/32 relevance, or SDXL cross-attention) is squared and
used as a weight; the object mask is split into 6 regions with a weighted K-means, every region
gets 3 strokes plus a share of the remaining strokes proportional to its attention, and the stroke
start points are the K-means centres of each region (``painter_params.get_points_smart_clustering``).

K-means is a small numpy implementation (k-means++ seeding, Lloyd iterations, best of ``n_init``)
instead of scikit-learn.
"""

from __future__ import annotations

import math

import numpy as np
import torch
import torch.nn.functional as F

NUM_REGIONS = 6


# ----------------------------------------------------------------------------- k-means


def _sqdist(x: np.ndarray, c: np.ndarray) -> np.ndarray:
    return np.maximum((x * x).sum(1)[:, None] - 2.0 * x @ c.T + (c * c).sum(1)[None, :], 0.0)


def _kmeans_pp(x: np.ndarray, k: int, rng: np.random.Generator) -> np.ndarray:
    """Greedy k-means++ seeding (2 + log k candidates per step, like scikit-learn)."""
    n = len(x)
    trials = 2 + int(math.log(k))
    centers = [x[rng.integers(n)]]
    closest = _sqdist(x, centers[0][None])[:, 0]
    for _ in range(1, k):
        pot = closest.sum()
        if pot <= 0:
            centers.append(x[rng.integers(n)])
            continue
        cand = np.searchsorted(np.cumsum(closest), rng.random(trials) * pot)
        cand = np.clip(cand, 0, n - 1)
        d = np.minimum(closest[:, None], _sqdist(x, x[cand]))
        best = int(np.argmin(d.sum(0)))
        centers.append(x[cand[best]])
        closest = d[:, best]
    return np.array(centers)


def kmeans(x: np.ndarray, k: int, n_init: int = 10, max_iter: int = 300, seed: int = 42):
    """-> (centers [k, D], labels [N], inertia)."""
    x = np.asarray(x, dtype=np.float64)
    k = max(1, min(k, len(x)))
    rng = np.random.default_rng(seed)
    tol = 1e-4 * float(x.var(axis=0).mean())
    best = None
    for _ in range(n_init):
        centers = _kmeans_pp(x, k, rng)
        for _ in range(max_iter):
            labels = _sqdist(x, centers).argmin(1)
            counts = np.bincount(labels, minlength=k)
            sums = np.stack([np.bincount(labels, weights=x[:, d], minlength=k) for d in range(x.shape[1])], 1)
            new =np.where(counts[:, None] > 0, sums / np.maximum(counts, 1)[:, None], centers)
            shift = float(((new - centers) ** 2).sum())
            centers = new
            if shift <= tol:
                break
        d = _sqdist(x, centers)
        labels = d.argmin(1)
        inertia = float(d[np.arange(len(x)), labels].sum())
        if best is None or inertia < best[2]:
            best = (centers, labels, inertia)
    return best


# ----------------------------------------------------------------------------- clustering


def weighted_segmentation(mask: np.ndarray, weights: np.ndarray, num_regions: int, spatial_weight: float = 1.0,
                          weight_scale: float = 0.5):
    """K-means on (x, y, weight) of the mask pixels -> (labels, pixel coords [N, 2] as x, y)."""
    ys, xs = np.nonzero(mask > 0)
    coords = np.column_stack((xs, ys))
    feats = np.hstack((coords * spatial_weight, weights[ys, xs][:, None] * weight_scale))
    _, labels, _ = kmeans(feats, num_regions)
    return labels, coords


def distribute_points(labels: np.ndarray, coords: np.ndarray, weights: np.ndarray, total: int) -> np.ndarray:
    """Split ``total`` points among the regions proportionally to their summed weight."""
    num_regions = int(labels.max()) + 1
    scores = np.array([weights[coords[labels == r, 1], coords[labels == r, 0]].sum() for r in range(num_regions)])
    if scores.sum() <= 0:
        scores = np.ones(num_regions)
    per_region = np.round(scores / scores.sum() * total).astype(int)
    while per_region.sum() < total:
        per_region[np.argmax(scores)] += 1
    while per_region.sum() > total:
        per_region[np.argmax(per_region)] -= 1
    return per_region


def region_points(region_coords: np.ndarray, num: int) -> np.ndarray:
    """``num`` evenly spread points inside a region (K-means centres, moved onto the region if a
    centre falls outside it – the original drops such points, which can leave strokes without a
    start point)."""
    if num <= 0 or len(region_coords) == 0:
        return np.zeros((0, 2))
    centers, _, _ = kmeans(region_coords.astype(np.float64), num)
    inside = {(int(x), int(y)) for x, y in region_coords}
    out = []
    for cx, cy in centers:
        if (int(cx), int(cy)) not in inside:
            j = int(np.argmin(((region_coords - (cx, cy)) ** 2).sum(1)))
            cx, cy = region_coords[j]
        out.append((cx, cy))
    while len(out) < num:  # fewer distinct pixels than points
        out.append(tuple(region_coords[len(out) % len(region_coords)]))
    return np.array(out, dtype=np.float64)


def smart_clustering(mask: np.ndarray, weights: np.ndarray, num_strokes: int):
    """-> (start points [num_strokes, 2] as pixel x, y; region label image [H, W] (-1 = background))."""
    mask = np.asarray(mask)
    if int((mask > 0).sum()) < max(num_strokes, NUM_REGIONS):
        mask = np.ones_like(mask)
    per = round(num_strokes / (2 * NUM_REGIONS))
    remain = num_strokes - per * NUM_REGIONS
    labels, coords = weighted_segmentation(mask, weights, NUM_REGIONS)
    counts = distribute_points(labels, coords, weights, remain) + per
    points = []
    for r, n in enumerate(counts):
        points.extend(region_points(coords[labels == r], int(n)))
    points = np.array(points, dtype=np.float64).reshape(-1, 2)
    if len(points) > num_strokes:  # only when num_strokes < number of regions
        points = points[:num_strokes]
    region_img = np.full(mask.shape, -1, dtype=np.int64)
    region_img[coords[:, 1], coords[:, 0]] = labels
    return points, region_img


# ----------------------------------------------------------------------------- attention


def clip_attention(target: torch.Tensor, size: int, device) -> torch.Tensor:
    """CLIP ViT-B/32 relevance of the input image ([1, 3, H, W] in [0, 1]) -> [size, size] in [0, 1]."""
    from ... import painter
    from ...clip_ import clip

    model, preprocess = clip.load("ViT-B/32", device=device)
    model.eval()
    x = preprocess.transforms[-1](target.to(device))
    x = F.interpolate(x, size=(224, 224), mode="bicubic", align_corners=False)
    with torch.no_grad():
        attn = painter.interpret(x, None, model, device=device)
    del model
    attn = torch.from_numpy(np.ascontiguousarray(attn, dtype=np.float32))
    return F.interpolate(attn[None, None], (size, size))[0, 0]


def init_points(attn: torch.Tensor, mask: torch.Tensor, num_strokes: int):
    """``set_attention_threshold_map``: weights = attn², mask pixels > 0 (after 8-bit quantisation)."""
    weights = torch.pow(attn, 2).float().cpu().numpy().astype(np.float32)
    m = mask.float().cpu()
    m = (m / m.max().clamp_min(1e-12) * 255).numpy().astype(np.uint8)
    return smart_clustering(m, weights, num_strokes)


def region_colors(region_img: np.ndarray) -> np.ndarray:
    """Label image -> RGB (white background) for the initialisation preview."""
    palette = np.array([[31, 119, 180], [255, 127, 14], [44, 160, 44], [214, 39, 40], [148, 103, 189],
                        [140, 86, 75], [227, 119, 194], [127, 127, 127], [188, 189, 34], [23, 190, 207]],
                       dtype=np.uint8)
    out = np.full(region_img.shape + (3,), 255, dtype=np.uint8)
    fg = region_img >= 0
    out[fg] = palette[region_img[fg] % len(palette)]
    return out
