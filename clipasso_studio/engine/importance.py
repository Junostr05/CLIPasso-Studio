"""How much each stroke of a sketch adds – for the "Simplify" slider of the studio, which hides the least
important strokes first.

4.1: **outlines before areas.** CLIP alone (``ClipScorer.stroke_importance``: how far the score falls without a
stroke) often kept the strokes that fill a dark area and let the outline go – the sketch lost its shape. The order
now weighs, for every stroke,

- its rank by CLIP (0..1),
- how much of it lies on an edge of the picture and runs along it (``outline``: kept much longer –
  ``OUTLINE_WEIGHT``; strongly preferred, not strictly),
- how much of it lies in a dark area that other strokes cover too (``fill`` × crowding: goes first – and the
  crowding is counted again after every stroke that goes, so an area is thinned evenly instead of emptied).

Measured in a process of its own (``--importance RUN_DIR``, a few seconds), and kept in ``importance.json`` of the
run with a hash of the sketch it belongs to (an erased or edited sketch is measured again) and its ``VERSION`` (a
file of 4.0 is measured again). Reading needs no torch."""

from __future__ import annotations

import hashlib
import json
import math
import os

FILE = "importance.json"
VERSION = 2  # 4.1: "rank" (outlines before areas); 1 (no version): CLIP's drops only
OUTLINE_WEIGHT = 1.5  # an outline stroke against CLIP's rank (0..1): strongly preferred, not strictly
FILL_WEIGHT = 1.0  # a stroke in a crowded dark area
OUTLINE_REACH = 0.03  # share of the side: a stroke this close to an edge lies on it
SIZE = 112  # px: the canvas the strokes are compared on (the longer side)
SAMPLES = 16  # points along a stroke where its place and direction are looked at


def digest(svg: str) -> str:
    return hashlib.sha1(svg.encode("utf-8")).hexdigest()


def read(run_dir: str, svg: str) -> list[float] | None:
    """The importance of every stroke of ``svg`` – higher is kept longer (``order`` sorts by it); None when it was
    not measured for this sketch, or by an older version."""
    try:
        with open(os.path.join(run_dir, FILE), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("sha1") != digest(svg) or data.get("version") != VERSION:
        return None
    rank = data.get("rank")
    return [float(v) for v in rank] if isinstance(rank, list) else None


def order(values: list[float]) -> list[int]:
    """Stroke indices from the least to the most important."""
    return sorted(range(len(values)), key=lambda i: (values[i], i))


def ranking(drops, coverage, samples, gray) -> list[int]:
    """The step at which every stroke goes when the sketch is simplified (0: first) – greedy, one stroke at a time:
    the one with the lowest worth goes, then the crowding is counted again.

    ``drops``: CLIP's drop per stroke; ``coverage`` [N, H, W] (0..1): where each stroke lies; ``samples``: per stroke
    the positions and tangents [S, 2] along it (pixels of that canvas); ``gray`` [H, W] (0..1): the picture."""
    import numpy as np

    from .sketch_guide import edge_maps

    n = len(drops)
    if n == 0:
        return []
    e = edge_maps(np.asarray(gray, dtype=np.float32))
    h, w = e["dist"].shape
    reach = OUTLINE_REACH * e["side"]
    outline = np.zeros(n)
    for i, (pos, tan) in enumerate(samples):
        pos, tan = np.asarray(pos, dtype=np.float64), np.asarray(tan, dtype=np.float64)
        if not len(pos):
            continue
        x = np.clip(np.round(pos[:, 0]).astype(int), 0, w - 1)
        y = np.clip(np.round(pos[:, 1]).astype(int), 0, h - 1)
        near = np.clip(1.0 - e["dist"][y, x] / reach, 0.0, 1.0)
        t = tan / (np.linalg.norm(tan, axis=1, keepdims=True) + 1e-9)
        align = 0.5 + 0.5 * (e["cos2"][y, x] * (t[:, 0] ** 2 - t[:, 1] ** 2) + e["sin2"][y, x] * 2 * t[:, 0] * t[:, 1])
        clarity = e["clarity"][y, x]
        outline[i] = float(np.mean(near * ((1 - clarity) + clarity * align)))  # (no clear direction: no penalty)
    cov = np.asarray(coverage, dtype=np.float64).reshape(n, -1)
    mass = cov.sum(axis=1) + 1e-9
    fill = (cov * e["dark"].ravel()).sum(axis=1) / mass
    order_by_clip = sorted(range(n), key=lambda i: (float(drops[i]), i))
    clip_rank = np.zeros(n)
    clip_rank[order_by_clip] = np.arange(n) / max(n - 1, 1)
    worth = clip_rank + OUTLINE_WEIGHT * outline
    alive = np.ones(n, dtype=bool)
    total = cov.sum(axis=0)
    rank = [0] * n
    for step in range(n):
        crowd = (cov * (total - cov)).sum(axis=1) / mass  # the other strokes on this one's pixels
        score = np.where(alive, worth - FILL_WEIGHT * fill * crowd / (1.0 + crowd), np.inf)
        i = int(np.argmin(score))
        rank[i] = step
        alive[i] = False
        total -= cov[i]
    return rank


def _samples(path, count: int = SAMPLES):
    """Positions and tangents [S, 2] along a ``renderer.Path`` (lines, quadratic and cubic segments)."""
    import numpy as np

    pts = path.points.detach().cpu().numpy().astype(np.float64)
    ncp = path.num_control_points.tolist()
    if path.is_closed:
        pts = np.concatenate([pts, pts[:1]])
    per = max(count // max(len(ncp), 1), 2)
    t = (np.arange(per) + 0.5) / per
    pos, tan, at = [], [], 0
    for k in ncp:
        order = int(k) + 1
        ctrl = pts[at: at + order + 1]
        at += order
        if len(ctrl) < order + 1:
            break
        b = np.stack([math.comb(order, j) * (1 - t) ** (order - j) * t ** j for j in range(order + 1)], 1)
        d = np.stack([math.comb(order - 1, j) * (1 - t) ** (order - 1 - j) * t ** j for j in range(order)], 1)
        pos.append(b @ ctrl)
        tan.append(order * (d @ (ctrl[1:] - ctrl[:-1])))
    if not pos:
        return np.zeros((0, 2)), np.zeros((0, 2))
    return np.concatenate(pos), np.concatenate(tan)


def _geometry(svg_path: str, target):
    """Every stroke's coverage and samples on a canvas of ``SIZE`` and the picture's brightness on it."""
    import numpy as np
    import torch

    from . import svg_io
    from .renderer import Path, render_on_white

    w, h, shapes, groups = svg_io.load_svg(svg_path)
    s = SIZE / max(w, h)
    shapes = [Path(p.num_control_points, p.points * s, p.stroke_width * s, is_closed=p.is_closed) for p in shapes]
    cw, ch = max(1, round(w * s)), max(1, round(h * s))
    coverage, samples = [], []
    with torch.no_grad():
        for g in groups:
            img = render_on_white(cw, ch, shapes, [g]).cpu().numpy()  # [H, W, 3]
            coverage.append(1.0 - img.mean(axis=2))
            parts = [_samples(shapes[int(j)]) for j in g.shape_ids.tolist()]
            samples.append((np.concatenate([p for p, _ in parts]), np.concatenate([t for _, t in parts])))
    gray = np.asarray(target.convert("L").resize((cw, ch)), dtype=np.float32) / 255.0
    return np.stack(coverage) if coverage else np.zeros((0, ch, cw)), samples, gray


def compute(run_dir: str, device: str = "cpu") -> str:
    """Measure the strokes of the run's sketch (the edited one, if there is one) and write ``importance.json``;
    returns its path."""
    from PIL import Image

    from . import jobs
    from .scoring import get_scorer

    svg_path = jobs.sketch_file(run_dir)
    with open(svg_path, encoding="utf-8") as f:
        svg = f.read()
    target = os.path.join(run_dir, "input.png")
    if not os.path.isfile(target):
        raise FileNotFoundError(f"no input picture in {run_dir}")
    with Image.open(target) as img:
        img = img.convert("RGB")
        base, drops = get_scorer(device).stroke_importance(svg_path, img)
        coverage, samples, gray = _geometry(svg_path, img)
    rank = ranking(drops, coverage, samples, gray)
    out = os.path.join(run_dir, FILE)
    with open(out + ".tmp", "w", encoding="utf-8") as f:
        json.dump({"version": VERSION, "sha1": digest(svg), "base": round(base, 3),
                   "drops": [round(d, 4) for d in drops], "rank": rank}, f)
    os.replace(out + ".tmp", out)
    return out
