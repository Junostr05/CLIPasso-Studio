"""Strokes, object scaling and stroke sorting of ControlSketch (``painter_params.py`` / ``sketch_utils.py``)
on top of the PyTorch rasterizer."""

from __future__ import annotations

import random

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

from ... import svg_io
from ...renderer import Path, ShapeGroup, render, render_on_white


class StrokePainter:
    """Black open Bézier strokes on a ``canvas`` x ``canvas`` canvas; the control points are optimised."""

    def __init__(self, num_strokes: int, num_segments: int, control_points_per_seg: int, width: float, canvas: int,
                 device, start_points=None):
        self.num_strokes = num_strokes
        self.num_segments = num_segments
        self.cps = int(control_points_per_seg)
        self.width = float(width)
        self.canvas = int(canvas)
        self.device = device
        self.start_points = start_points  # normalised (x, y) per stroke, or None for random starts
        self.shapes: list[Path] = []
        self.groups: list[ShapeGroup] = []

    def init_strokes(self) -> None:
        for i in range(self.num_strokes):
            self.shapes.append(self._path(i))
            self.groups.append(ShapeGroup(shape_ids=torch.tensor([i]), fill_color=None,
                                          stroke_color=torch.tensor([0.0, 0.0, 0.0, 1.0])))

    def _path(self, i: int) -> Path:
        if self.start_points is not None:
            p0 = tuple(float(v) for v in self.start_points[i])
        else:
            p0 = (random.random(), random.random())
        points = [p0]
        radius = 0.05
        for _ in range(self.num_segments):
            for _ in range(self.cps - 1):
                p1 = (p0[0] + radius * (random.random() - 0.5), p0[1] + radius * (random.random() - 0.5))
                points.append(p1)
                p0 = p1
        pts = torch.tensor(points, dtype=torch.float32) * self.canvas
        ncp = torch.zeros(self.num_segments, dtype=torch.int32) + (self.cps - 2)
        return Path(num_control_points=ncp, points=pts.to(self.device), stroke_width=torch.tensor(self.width),
                    is_closed=False)

    def parameters(self) -> list[torch.Tensor]:
        for s in self.shapes:
            s.points.requires_grad_(True)
        return [s.points for s in self.shapes]

    def get_image(self) -> torch.Tensor:
        """[1, 3, H, W] on white."""
        return render_on_white(self.canvas, self.canvas, self.shapes, self.groups).permute(2, 0, 1)[None]

    def points(self) -> list[torch.Tensor]:
        return [s.points.detach().clone() for s in self.shapes]


# ----------------------------------------------------------------------------- object scaling


def object_bbox(binary: np.ndarray):
    ys, xs = np.nonzero(binary)
    return int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())


def _resize(arr: np.ndarray, h: int, w: int) -> np.ndarray:
    """Bilinear resize with antialiasing (like ``skimage.transform.resize``)."""
    t = torch.from_numpy(np.ascontiguousarray(arr, dtype=np.float32)).permute(2, 0, 1)[None]
    out = F.interpolate(t, size=(max(h, 1), max(w, 1)), mode="bilinear", align_corners=False, antialias=True)
    return out[0].permute(1, 2, 0).numpy()


def cut_and_resize(im: np.ndarray, x0, x1, y0, y1, new_h: int, new_w: int, fill: float) -> np.ndarray:
    """Cut the object box out, resize it and paste it into the centre of an empty canvas."""
    obj = _resize(im[y0:y1, x0:x1], new_h, new_w)
    out = np.full(im.shape, fill, dtype=np.float64)
    sy = out.shape[0] // 2 - new_h // 2
    sx = out.shape[1] // 2 - new_w // 2
    out[sy: sy + obj.shape[0], sx: sx + obj.shape[1]] = obj
    return out


def shrink_object(image: Image.Image, mask: torch.Tensor, ratio: float):
    """Reduce the object to ``ratio`` of the canvas if it is larger (``get_target``).

    -> (image, mask, info) where info holds the scale / centre needed to restore the size, or None.
    """
    binary = (mask >= 0.5).float().numpy()
    if not binary.any():
        return image, mask, None
    w, h = image.size
    x0, x1, y0, y1 = object_bbox(binary)
    im_w, im_h = x1 - x0, y1 - y0
    target = int(w * ratio)
    if max(im_w, im_h) <= target or im_w <= 0 or im_h <= 0:
        return image, mask, None
    if im_w > im_h:
        new_w, new_h = target, int(target / im_w * im_h)
    else:
        new_w, new_h = int(target / im_h * im_w), target
    new_mask = cut_and_resize(np.stack([binary] * 3, -1), x0, x1, y0, y1, new_h, new_w, 0.0)[:, :, 0]
    im = np.asarray(image, dtype=np.float64)
    im = cut_and_resize(im / max(im.max(), 1e-12), x0, x1, y0, y1, new_h, new_w, 1.0)
    im = (im / max(im.max(), 1e-12) * 255).astype(np.uint8)
    info = {"scale_w": new_w / im_w, "scale_h": new_h / im_h,
            "center_x": (x0 + (x1 - x0) / 2) / w, "center_y": (y0 + (y1 - y0) / 2) / h}
    return Image.fromarray(im), torch.from_numpy(new_mask.astype(np.float32)), info


def restore_points(points: torch.Tensor, canvas: int, info: dict | None, out_size: int) -> torch.Tensor:
    """``increase_object_size`` + ``resize_svg``: canvas points -> output SVG coordinates."""
    p = points.detach().float().clone()
    if info:
        p = p / canvas * 2 - 1
        p[:, 0] /= info["scale_w"]
        p[:, 1] /= info["scale_h"]
        p = 0.5 * (p + 1.0) * canvas
        p[:, 0] += info["center_x"] * canvas - canvas / 2
        p[:, 1] += info["center_y"] * canvas - canvas / 2
    return p * (out_size / canvas)


def output_scene(painter: StrokePainter, info: dict | None, out_size: int, order=None):
    """Shapes/groups of the final sketch in output coordinates (stroke width scaled with the canvas)."""
    order = list(range(len(painter.shapes))) if order is None else list(order)
    shapes, groups = [], []
    scale = out_size / painter.canvas
    for j in order:
        s = painter.shapes[j]
        shapes.append(Path(s.num_control_points, restore_points(s.points, painter.canvas, info, out_size).cpu(),
                           torch.tensor(float(s.stroke_width) * scale), s.is_closed))
        groups.append(ShapeGroup(shape_ids=torch.tensor([len(shapes) - 1]), fill_color=None,
                                 stroke_color=painter.groups[j].stroke_color.detach().cpu()))
    return shapes, groups


def output_svg(painter: StrokePainter, info: dict | None, out_size: int, order=None) -> str:
    shapes, groups = output_scene(painter, info, out_size, order)
    return svg_io.scene_to_svg(out_size, out_size, shapes, groups)


# ----------------------------------------------------------------------------- stroke order


def thick_contour(mask: torch.Tensor, size: int) -> np.ndarray:
    """Band around the object outline: binary dilation (5x5) minus binary erosion (10x10)."""
    m = F.interpolate(mask.float()[None, None], size=(size, size), mode="bilinear", align_corners=False)
    m = (m >= 0.5).float()
    dilated = F.max_pool2d(m, 5, stride=1, padding=2)
    inv = F.pad(1 - m, (5, 4, 5, 4), value=1.0)  # outside the image counts as background
    eroded = 1 - F.max_pool2d(inv, 10, stride=1)
    return (dilated - eroded)[0, 0].numpy() > 0


def sort_by_contour_and_attn(painter: StrokePainter, mask: torch.Tensor, attn: torch.Tensor) -> list[int]:
    """Strokes touching the object outline first (most contour pixels first), then the others by
    their mean attention (``sort_by_contour_and_attn``)."""
    size = painter.canvas
    contour = thick_contour(mask, size)
    attn_map = F.interpolate(attn.float()[None, None].cpu(), size=(size, size), mode="bilinear",
                             align_corners=False)[0, 0].numpy()
    touching, others = [], []
    with torch.no_grad():
        for i, s in enumerate(painter.shapes):
            single = Path(s.num_control_points, s.points.detach().cpu(), s.stroke_width.detach().cpu(), s.is_closed)
            alpha = render(size, size, [single], [ShapeGroup(torch.tensor([0]))])[:, :, 3].numpy()
            count = int(np.logical_and(alpha >= 1.0 - 1e-6, contour).sum())  # fully covered pixels
            if count > 0:
                touching.append((i, count))
            else:
                core = alpha > 0.9
                n = int(core.sum())
                others.append((i, float((attn_map * core).sum() / n) if n else 0.0))
    touching.sort(key=lambda t: t[1], reverse=True)
    others.sort(key=lambda t: t[1], reverse=True)
    return [i for i, _ in touching] + [i for i, _ in others]
