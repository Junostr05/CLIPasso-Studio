"""Differentiable vector stroke rasterizer in pure PyTorch.

Drop-in replacement for the subset of ``pydiffvg`` (https://github.com/BachiLi/diffvg)
that CLIPasso uses: open or closed stroked paths made of linear / quadratic / cubic
Bézier segments, composited with the "over" operator on a transparent canvas.

Each path is flattened into a polyline; every pixel near the path gets the distance to the
closest polyline segment, which is turned into an antialiased coverage value
(``clamp(w/2 + 0.5 - d, 0, 1)``, i.e. a 1px box filter). Gradients with respect to the
control points, stroke width and stroke colour/opacity come from autograd. No compiled
extension is needed, and the same code runs on CPU and CUDA.
"""

from __future__ import annotations

import math
from functools import lru_cache

import torch
import torch.nn.functional as F

_EPS = 1e-8


class Path:
    """Same constructor as ``pydiffvg.Path``."""

    def __init__(self, num_control_points, points, stroke_width, is_closed=False, id=""):
        self.num_control_points = torch.as_tensor(num_control_points, dtype=torch.int32).flatten().cpu()
        self.points = points
        self.stroke_width = stroke_width if torch.is_tensor(stroke_width) else torch.tensor(float(stroke_width))
        self.is_closed = bool(is_closed)
        self.id = id


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


@lru_cache(maxsize=64)
def _bernstein(order: int, samples: int, device_str: str, dtype_str: str) -> torch.Tensor:
    """[samples, order+1] Bernstein basis evaluated on t in [0, 1]."""
    dtype = getattr(torch, dtype_str)
    t = torch.linspace(0.0, 1.0, samples, dtype=torch.float64)
    cols = [math.comb(order, i) * (1 - t) ** (order - i) * t ** i for i in range(order + 1)]
    return torch.stack(cols, dim=1).to(device=device_str, dtype=dtype)


def _segments(path: Path) -> list[tuple[int, torch.Tensor]]:
    """Split ``path.points`` into (order, control points) per segment, like diffvg."""
    pts = path.points
    n_pts = pts.shape[0]
    segs = []
    idx = 0
    ncp = path.num_control_points.tolist()
    for i, c in enumerate(ncp):
        c = int(c)
        count = c + 2
        if path.is_closed and i == len(ncp) - 1:
            seg = torch.cat([pts[idx: idx + count - 1], pts[0:1]], dim=0)
        else:
            if idx + count > n_pts:
                break
            seg = pts[idx: idx + count]
        segs.append((c + 1, seg))
        idx += count - 1
    return segs


def flatten_path(path: Path, tolerance: float = 1.5, min_samples: int = 4, max_samples: int = 96) -> torch.Tensor:
    """Polyline approximation of a path: [M, 2]."""
    polys = []
    for order, seg in _segments(path):
        if order == 1:
            poly = seg
        else:
            with torch.no_grad():
                length = (seg[1:] - seg[:-1]).norm(dim=1).sum().item()
            n = int(min(max(math.ceil(length / tolerance) + 1, min_samples), max_samples))
            basis = _bernstein(order, n, str(seg.device), str(seg.dtype).replace("torch.", ""))
            poly = basis @ seg
        if polys:
            poly = poly[1:]
        polys.append(poly)
    if not polys:
        return path.points[:1]
    return torch.cat(polys, dim=0)


def _path_coverage(poly: torch.Tensor, width: torch.Tensor, height_px: int, width_px: int):
    """Coverage of one stroke, restricted to its bounding box.

    Returns (coverage [h, w], (y0, y1, x0, x1)) or None if the stroke is off canvas.
    """
    half = width / 2
    with torch.no_grad():
        pad = float(half.detach()) + 1.5
        lo = poly.detach().min(dim=0).values - pad
        hi = poly.detach().max(dim=0).values + pad
        x0 = max(int(math.floor(lo[0].item())), 0)
        y0 = max(int(math.floor(lo[1].item())), 0)
        x1 = min(int(math.ceil(hi[0].item())) + 1, width_px)
        y1 = min(int(math.ceil(hi[1].item())) + 1, height_px)
    if x1 <= x0 or y1 <= y0:
        return None
    dev, dt = poly.device, poly.dtype
    ys = torch.arange(y0, y1, device=dev, dtype=dt) + 0.5
    xs = torch.arange(x0, x1, device=dev, dtype=dt) + 0.5
    gy, gx = torch.meshgrid(ys, xs, indexing="ij")
    pix = torch.stack([gx.reshape(-1), gy.reshape(-1)], dim=1)  # [P, 2]

    if poly.shape[0] == 1:
        d2 = ((pix - poly[0]) ** 2).sum(dim=1)
    else:
        a = poly[:-1]  # [S, 2]
        ab = poly[1:] - a
        ab2 = (ab ** 2).sum(dim=1).clamp_min(_EPS)  # [S]
        ap = pix[:, None, :] - a[None, :, :]  # [P, S, 2]
        t = ((ap * ab[None]).sum(dim=2) / ab2[None]).clamp(0.0, 1.0)  # [P, S]
        diff = ap - t[..., None] * ab[None]
        d2 = (diff ** 2).sum(dim=2).min(dim=1).values  # [P]
    dist = torch.sqrt(d2 + _EPS)
    max_cov = torch.clamp(width, max=1.0)
    cov = torch.minimum(torch.clamp(half + 0.5 - dist, min=0.0), max_cov)
    return cov.reshape(y1 - y0, x1 - x0), (y0, y1, x0, x1)


def render(canvas_width: int, canvas_height: int, shapes, shape_groups, samples: int = 1) -> torch.Tensor:
    """Render to an [H, W, 4] RGBA tensor (straight alpha), like ``pydiffvg.RenderFunction``.

    ``samples`` > 1 renders at a higher resolution and box-downsamples (supersampling).
    """
    s = max(int(samples), 1)
    width_px, height_px = int(canvas_width) * s, int(canvas_height) * s
    device = None
    dtype = torch.float32
    for shape in shapes:
        device = shape.points.device
        dtype = shape.points.dtype if shape.points.is_floating_point() else torch.float32
        break
    device = device or torch.device("cpu")

    alphas, colors = [], []
    for group in shape_groups:
        color = group.stroke_color
        if color is None:
            continue
        color = color.to(device=device, dtype=dtype)
        for sid in group.shape_ids.tolist():
            shape = shapes[int(sid)]
            pts = shape.points.to(dtype) * s
            scaled = Path(shape.num_control_points, pts, shape.stroke_width, shape.is_closed)
            width = shape.stroke_width.to(device=device, dtype=dtype) * s
            poly = flatten_path(scaled, tolerance=1.5 * s)
            res = _path_coverage(poly, width, height_px, width_px)
            if res is None:
                continue
            cov, (y0, y1, x0, x1) = res
            a = cov * color[3].clamp(0.0, 1.0)
            full = F.pad(a, (x0, width_px - x1, y0, height_px - y1))
            alphas.append(full)
            colors.append(color[:3])

    if not alphas:
        img = torch.zeros(height_px, width_px, 4, device=device, dtype=dtype)
    else:
        a = torch.stack(alphas, dim=0)  # [N, H, W]
        c = torch.stack(colors, dim=0)  # [N, 3]
        one_minus = 1.0 - a
        # transmittance of everything drawn on top of path i
        rev = torch.flip(torch.cumprod(torch.flip(one_minus, [0]), dim=0), [0])
        above = torch.cat([rev[1:], torch.ones_like(rev[:1])], dim=0)
        weight = a * above  # contribution of path i
        alpha = 1.0 - rev[0]
        premult = torch.einsum("nhw,nc->hwc", weight, c)
        rgb = premult / alpha.clamp_min(1e-6)[..., None]
        img = torch.cat([rgb, alpha[..., None]], dim=2)

    if s > 1:
        img = F.avg_pool2d(img.permute(2, 0, 1)[None], kernel_size=s)[0].permute(1, 2, 0)
    return img


def render_on_white(canvas_width, canvas_height, shapes, shape_groups, samples: int = 1) -> torch.Tensor:
    """[H, W, 3] image composited on white, as done throughout CLIPasso."""
    img = render(canvas_width, canvas_height, shapes, shape_groups, samples)
    alpha = img[:, :, 3:4]
    return alpha * img[:, :, :3] + (1 - alpha)
