"""Differentiable vector stroke rasterizer in pure PyTorch.

Drop-in replacement for the subset of ``pydiffvg`` (https://github.com/BachiLi/diffvg)
that CLIPasso uses: open or closed stroked paths made of linear / quadratic / cubic
Bézier segments, composited with the "over" operator on a transparent canvas.

Each path is flattened into a polyline; every pixel near the path gets the distance to the
closest polyline segment, which is turned into an antialiased coverage value
(``clamp(w/2 + 0.5 - d, 0, 1)``, i.e. a 1px box filter). Gradients with respect to the
control points, stroke width and stroke colour/opacity come from autograd. No compiled
extension is needed, and the same code runs on CPU and CUDA.

How it is kept fast (3.0; the strokes are drawn as before, see tests/test_renderer_equivalence.py):

- one device→host transfer per render: the sample counts of all curves, their bounding boxes,
  the widths and colours are read in a single ``tolist()`` (before: several ``.item()`` per stroke,
  each a GPU synchronisation);
- the closest polyline segment of each pixel is found without gradient, then the distance is
  computed with gradient for that segment only – the gradient of ``min`` goes to the closest
  segment anyway, but autograd now keeps O(pixels) instead of O(pixels × segments) values;
- every Bézier segment of a path has its own bounding box, so a long path that crosses the whole
  canvas (one-line drawings) only tests the pixels near each of its pieces;
- black strokes on white (all methods by default) are composited as a product of
  ``1 - alpha`` in each stroke's box with a small custom backward, instead of full-canvas layers.
"""

from __future__ import annotations

import math
from functools import lru_cache

import torch
import torch.nn.functional as F

_EPS = 1e-8
_CHUNK = 2_000_000  # pixel × segment pairs per block when looking for the closest segment


class Path:
    """Same constructor as ``pydiffvg.Path``; ``fixed``: a stroke drawn by hand that stays as it is."""

    def __init__(self, num_control_points, points, stroke_width, is_closed=False, id="", fixed=False):
        self.num_control_points = torch.as_tensor(num_control_points, dtype=torch.int32).flatten().cpu()
        self.points = points
        self.stroke_width = stroke_width if torch.is_tensor(stroke_width) else torch.tensor(float(stroke_width))
        self.is_closed = bool(is_closed)
        self.id = id
        self.fixed = bool(fixed)


class ShapeGroup:
    """Same constructor as ``pydiffvg.ShapeGroup`` (only stroke colour is rendered)."""

    def __init__(self, shape_ids, fill_color=None, stroke_color=None, use_even_odd_rule=True,
                 shape_to_canvas=None, id=""):
        self.shape_ids = torch.as_tensor(shape_ids).flatten()
        self.fill_color = fill_color
        self.stroke_color = stroke_color if stroke_color is not None else torch.tensor([0.0, 0.0, 0.0, 1.0])
        self.use_even_odd_rule = use_even_odd_rule
        self.shape_to_canvas = shape_to_canvas
        self.id = id


@lru_cache(maxsize=256)
def _bernstein(order: int, samples: int, device_str: str, dtype_str: str) -> torch.Tensor:
    """[samples, order+1] Bernstein basis evaluated on t in [0, 1]."""
    dtype = getattr(torch, dtype_str)
    t = torch.linspace(0.0, 1.0, samples, dtype=torch.float64)
    cols = [math.comb(order, i) * (1 - t) ** (order - i) * t ** i for i in range(order + 1)]
    return torch.stack(cols, dim=1).to(device=device_str, dtype=dtype)


def _segments(path: Path) -> list[tuple[int, torch.Tensor]]:
    """Split ``path.points`` into (order, control points) per segment, like diffvg."""
    return _segments_of(path.points, path.num_control_points.tolist(), path.is_closed)


def _segments_of(pts: torch.Tensor, ncp: list, closed: bool) -> list[tuple[int, torch.Tensor]]:
    n_pts = pts.shape[0]
    segs = []
    idx = 0
    for i, c in enumerate(ncp):
        c = int(c)
        count = c + 2
        if closed and i == len(ncp) - 1:
            seg = torch.cat([pts[idx: idx + count - 1], pts[0:1]], dim=0)
        else:
            if idx + count > n_pts:
                break
            seg = pts[idx: idx + count]
        segs.append((c + 1, seg))
        idx += count - 1
    return segs


def _samples_for(length: float, tolerance: float, min_samples: int = 4, max_samples: int = 96) -> int:
    return int(min(max(math.ceil(length / tolerance) + 1, min_samples), max_samples))


def flatten_path(path: Path, tolerance: float = 1.5, min_samples: int = 4, max_samples: int = 96) -> torch.Tensor:
    """Polyline approximation of a path: [M, 2]."""
    polys = []
    for order, seg in _segments(path):
        if order == 1:
            poly = seg
        else:
            with torch.no_grad():
                length = (seg[1:] - seg[:-1]).norm(dim=1).sum().item()
            n = _samples_for(length, tolerance, min_samples, max_samples)
            basis = _bernstein(order, n, str(seg.device), str(seg.dtype).replace("torch.", ""))
            poly = basis @ seg
        if polys:
            poly = poly[1:]
        polys.append(poly)
    if not polys:
        return path.points[:1]
    return torch.cat(polys, dim=0)


# ----------------------------------------------------------------------------- one render
class _Item:
    """One (shape, group) pair to draw, in drawing order, with the metadata read from the device:
    per Bézier segment its control polygon length and box, the half width and the colour's rgb."""

    __slots__ = ("segs", "first_point", "width", "color", "seg_meta", "point", "half", "rgb")

    def __init__(self, segs, first_point, width, color):
        self.segs, self.first_point, self.width, self.color = segs, first_point, width, color
        self.seg_meta, self.point, self.half, self.rgb = [], None, 0.0, (0.0, 0.0, 0.0)


def _prepare(shapes, shape_groups, s: int, device, dtype) -> list[_Item]:
    items = []
    for group in shape_groups:
        color = group.stroke_color
        if color is None:
            continue
        color = color.to(device=device, dtype=dtype)
        for sid in group.shape_ids.tolist():
            shape = shapes[int(sid)]
            pts = shape.points.to(device=device, dtype=dtype) * s  # (strokes made on another device, too)
            segs = _segments_of(pts, shape.num_control_points.tolist(), shape.is_closed)
            width = shape.stroke_width.to(device=device, dtype=dtype) * s
            items.append(_Item(segs, pts[:1], width, color))
    if not items:
        return items
    # all metadata in one transfer: per segment order the control polygon lengths and boxes
    by_order: dict[int, list] = {}
    where = []
    for it in items:
        refs = []
        for order, seg in it.segs:
            lst = by_order.setdefault(order, [])
            refs.append((order, len(lst)))
            lst.append(seg)
        where.append(refs)
    parts, offsets, pos = [], {}, 0
    for order, lst in by_order.items():
        stack = torch.stack(lst).detach()  # [K, order+1, 2]
        lengths = (stack[:, 1:] - stack[:, :-1]).norm(dim=2).sum(dim=1)
        boxes = torch.cat([stack.amin(dim=1), stack.amax(dim=1)], dim=1)  # [K, 4]: x0 y0 x1 y1
        parts += [lengths, boxes.reshape(-1)]
        offsets[order] = (pos, len(lst))
        pos += 5 * len(lst)
    parts.append(torch.stack([it.first_point.detach().reshape(-1)[:2] for it in items]).reshape(-1))
    parts.append(torch.stack([it.width.detach().reshape(()) for it in items]))
    parts.append(torch.stack([it.color.detach()[:3] for it in items]).reshape(-1))
    meta = torch.cat(parts).tolist()
    n = len(items)
    for i, it in enumerate(items):
        for order, j in where[i]:
            start, count = offsets[order]
            box = start + count + 4 * j
            it.seg_meta.append((meta[start + j], meta[box: box + 4]))
        it.point = meta[pos + 2 * i: pos + 2 * i + 2]
        it.half = meta[pos + 2 * n + i] / 2
        it.rgb = tuple(meta[pos + 3 * n + 3 * i: pos + 3 * n + 3 * i + 3])
    return items


def _box(lo_x, lo_y, hi_x, hi_y, pad, width_px, height_px):
    x0 = max(int(math.floor(lo_x - pad)), 0)
    y0 = max(int(math.floor(lo_y - pad)), 0)
    x1 = min(int(math.ceil(hi_x + pad)) + 1, width_px)
    y1 = min(int(math.ceil(hi_y + pad)) + 1, height_px)
    return x0, y0, x1, y1


def _pixels(x0, y0, x1, y1, device, dtype):
    ys = torch.arange(y0, y1, device=device, dtype=dtype) + 0.5
    xs = torch.arange(x0, x1, device=device, dtype=dtype) + 0.5
    gy, gx = torch.meshgrid(ys, xs, indexing="ij")
    return torch.stack([gx.reshape(-1), gy.reshape(-1)], dim=1)  # [P, 2]


def _closest(pix: torch.Tensor, a: torch.Tensor, ab: torch.Tensor, ab2: torch.Tensor):
    """(squared distance, index) of the closest of the segments a→a+ab for every pixel (no gradient)."""
    best_d2, best_i = [], []
    step = max(1, _CHUNK // max(a.shape[0], 1))
    for i in range(0, pix.shape[0], step):
        ap = pix[i: i + step, None, :] - a[None, :, :]  # [p, S, 2]
        t = ((ap * ab[None]).sum(dim=2) / ab2[None]).clamp(0.0, 1.0)
        diff = ap - t[..., None] * ab[None]
        d2, idx = (diff ** 2).sum(dim=2).min(dim=1)
        best_d2.append(d2)
        best_i.append(idx)
    return torch.cat(best_d2), torch.cat(best_i)


def _coverage(it: _Item, tolerance: float, width_px: int, height_px: int):
    """Coverage of one stroke in its bounding box: (coverage [h, w], (y0, y1, x0, x1)) or None."""
    pad = it.half + 1.5  # beyond this a pixel's coverage is 0 (and so is its gradient)
    dev, dt = it.first_point.device, it.first_point.dtype
    if not it.segs:  # no complete segment: a dot at the first point
        x0, y0, x1, y1 = _box(it.point[0], it.point[1], it.point[0], it.point[1], pad, width_px, height_px)
        if x1 <= x0 or y1 <= y0:
            return None
        pix = _pixels(x0, y0, x1, y1, dev, dt)
        return _finish(((pix - it.first_point[0]) ** 2).sum(dim=1), it.width, x0, y0, x1, y1)

    # the polyline and, per Bézier segment, its polyline segments and its box (from the control
    # points: the curve lies inside their convex hull)
    polys, ranges, boxes = [], [], []
    n_points = 0
    for (order, seg), (length, b) in zip(it.segs, it.seg_meta):
        if order == 1:
            poly = seg
        else:
            n = _samples_for(length, tolerance)
            poly = _bernstein(order, n, str(seg.device), str(seg.dtype).replace("torch.", "")) @ seg
        if polys:
            poly = poly[1:]
        first = max(n_points - 1, 0)
        polys.append(poly)
        n_points += poly.shape[0]
        ranges.append((first, n_points - 1))  # its polyline segments: first .. n_points-2
        boxes.append(_box(b[0], b[1], b[2], b[3], pad, width_px, height_px))
    inside = [bx for bx in boxes if bx[2] > bx[0] and bx[3] > bx[1]]
    if not inside:
        return None
    x0, y0 = min(bx[0] for bx in inside), min(bx[1] for bx in inside)
    x1, y1 = max(bx[2] for bx in inside), max(bx[3] for bx in inside)
    pix = _pixels(x0, y0, x1, y1, dev, dt)
    poly = torch.cat(polys, dim=0)
    if poly.shape[0] == 1:
        return _finish(((pix - poly[0]) ** 2).sum(dim=1), it.width, x0, y0, x1, y1)

    a_all = poly[:-1]
    ab_all = poly[1:] - a_all
    ab2_all = (ab_all ** 2).sum(dim=1).clamp_min(_EPS)  # [S]
    with torch.no_grad():
        a_d, ab_d, ab2_d = a_all.detach(), ab_all.detach(), ab2_all.detach()
        if len(boxes) == 1:
            _, best_i = _closest(pix, a_d, ab_d, ab2_d)
        else:  # each Bézier segment tests the pixels of its own box; on a tie the earlier one wins
            w = x1 - x0
            best_d2 = torch.full((pix.shape[0],), float("inf"), device=dev, dtype=dt)
            best_i = torch.zeros(pix.shape[0], device=dev, dtype=torch.long)
            for (first, last), (bx0, by0, bx1, by1) in zip(ranges, boxes):
                if bx1 <= bx0 or by1 <= by0 or last <= first:
                    continue
                rows = torch.arange(by0 - y0, by1 - y0, device=dev)[:, None] * w
                cols = torch.arange(bx0 - x0, bx1 - x0, device=dev)[None, :]
                sel = (rows + cols).reshape(-1)
                d2, idx = _closest(pix[sel], a_d[first:last], ab_d[first:last], ab2_d[first:last])
                old = best_d2[sel]
                better = d2 < old
                best_d2[sel] = torch.where(better, d2, old)
                best_i[sel] = torch.where(better, idx + first, best_i[sel])
    # the distance to the closest segment, with gradient (the same formula as the search)
    a = a_all[best_i]
    ab = ab_all[best_i]
    ap = pix - a
    t = ((ap * ab).sum(dim=1) / ab2_all[best_i]).clamp(0.0, 1.0)
    diff = ap - t[:, None] * ab
    return _finish((diff ** 2).sum(dim=1), it.width, x0, y0, x1, y1)


def _finish(d2, width, x0, y0, x1, y1):
    half = width / 2
    dist = torch.sqrt(d2 + _EPS)
    max_cov = torch.clamp(width, max=1.0)
    cov = torch.minimum(torch.clamp(half + 0.5 - dist, min=0.0), max_cov)
    return cov.reshape(y1 - y0, x1 - x0), (y0, y1, x0, x1)


def _layers(canvas_width, canvas_height, shapes, shape_groups, samples):
    """The alpha of every stroke in its box: ([(alpha, box, colour)], width px, height px, device,
    dtype, all strokes black without colour gradient, supersampling factor)."""
    s = max(int(samples), 1)
    width_px, height_px = int(canvas_width) * s, int(canvas_height) * s
    device = None
    dtype = torch.float32
    for shape in shapes:
        device = shape.points.device
        dtype = shape.points.dtype if shape.points.is_floating_point() else torch.float32
        break
    device = device or torch.device("cpu")
    layers = []
    black = True
    for it in _prepare(shapes, shape_groups, s, device, dtype):
        res = _coverage(it, 1.5 * s, width_px, height_px)
        if res is None:
            continue
        cov, box = res
        layers.append((cov * it.color[3].clamp(0.0, 1.0), box, it.color))
        black = black and not it.color.requires_grad and all(v == 0.0 for v in it.rgb)
    return layers, width_px, height_px, device, dtype, black, s


def _composite(layers, width_px, height_px, device, dtype) -> torch.Tensor:
    """[H, W, 4] straight-alpha RGBA of the layers drawn in order ("over")."""
    if not layers:
        return torch.zeros(height_px, width_px, 4, device=device, dtype=dtype)
    alphas = [F.pad(a, (x0, width_px - x1, y0, height_px - y1)) for a, (y0, y1, x0, x1), _ in layers]
    a = torch.stack(alphas, dim=0)  # [N, H, W]
    c = torch.stack([color[:3] for _, _, color in layers], dim=0)  # [N, 3]
    one_minus = 1.0 - a
    # transmittance of everything drawn on top of path i
    rev = torch.flip(torch.cumprod(torch.flip(one_minus, [0]), dim=0), [0])
    above = torch.cat([rev[1:], torch.ones_like(rev[:1])], dim=0)
    weight = a * above  # contribution of path i
    alpha = 1.0 - rev[0]
    premult = torch.einsum("nhw,nc->hwc", weight, c)
    rgb = premult / alpha.clamp_min(1e-6)[..., None]
    return torch.cat([rgb, alpha[..., None]], dim=2)


class _Transmittance(torch.autograd.Function):
    """prod_i (1 - a_i) over the canvas, where every a_i covers only its box – for black strokes on
    white this is the image. The gradient of a factor is the product of all the others, computed with
    the count of zero factors per pixel (an opaque stroke has 1 - a = 0)."""

    @staticmethod
    def forward(ctx, height, width, boxes, *alphas):
        a0 = alphas[0]
        nonzero = torch.ones(height, width, device=a0.device, dtype=a0.dtype)
        zeros = torch.zeros(height, width, device=a0.device, dtype=torch.int32)
        for a, (y0, y1, x0, x1) in zip(alphas, boxes):
            f = 1.0 - a
            z = f == 0
            nonzero[y0:y1, x0:x1] *= torch.where(z, torch.ones_like(f), f)
            zeros[y0:y1, x0:x1] += z.to(torch.int32)
        ctx.boxes = boxes
        ctx.save_for_backward(nonzero, zeros, *alphas)
        return torch.where(zeros > 0, torch.zeros_like(nonzero), nonzero)

    @staticmethod
    def backward(ctx, grad):
        nonzero, zeros, *alphas = ctx.saved_tensors
        grads = []
        for a, (y0, y1, x0, x1) in zip(alphas, ctx.boxes):
            f = 1.0 - a
            nz, z, g = nonzero[y0:y1, x0:x1], zeros[y0:y1, x0:x1], grad[y0:y1, x0:x1]
            opaque = f == 0
            others = torch.where(opaque, torch.where(z == 1, nz, torch.zeros_like(nz)),
                                 torch.where(z == 0, nz / torch.where(opaque, torch.ones_like(f), f),
                                             torch.zeros_like(nz)))
            grads.append(-g * others)
        return (None, None, None, *grads)


def render(canvas_width: int, canvas_height: int, shapes, shape_groups, samples: int = 1) -> torch.Tensor:
    """Render to an [H, W, 4] RGBA tensor (straight alpha), like ``pydiffvg.RenderFunction``.

    ``samples`` > 1 renders at a higher resolution and box-downsamples (supersampling).
    """
    layers, width_px, height_px, device, dtype, _, s = _layers(canvas_width, canvas_height, shapes, shape_groups,
                                                               samples)
    img = _composite(layers, width_px, height_px, device, dtype)
    if s > 1:
        img = F.avg_pool2d(img.permute(2, 0, 1)[None], kernel_size=s)[0].permute(1, 2, 0)
    return img


def render_on_white(canvas_width, canvas_height, shapes, shape_groups, samples: int = 1) -> torch.Tensor:
    """[H, W, 3] image composited on white, as done throughout CLIPasso."""
    layers, width_px, height_px, device, dtype, black, s = _layers(canvas_width, canvas_height, shapes,
                                                                   shape_groups, samples)
    if black:  # black strokes: the image is the product of (1 - alpha), no full-canvas layers
        if layers:
            t = _Transmittance.apply(height_px, width_px, [box for _, box, _ in layers], *[a for a, _, _ in layers])
        else:
            t = torch.ones(height_px, width_px, device=device, dtype=dtype)
        if s > 1:
            t = F.avg_pool2d(t[None, None], kernel_size=s)[0, 0]
        return t[..., None].expand(-1, -1, 3).contiguous()
    img = _composite(layers, width_px, height_px, device, dtype)
    if s > 1:
        img = F.avg_pool2d(img.permute(2, 0, 1)[None], kernel_size=s)[0].permute(1, 2, 0)
    alpha = img[:, :, 3:4]
    return alpha * img[:, :, :3] + (1 - alpha)
