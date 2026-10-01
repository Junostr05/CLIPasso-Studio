"""The frame of an exported sketch, without torch: the square canvas of the method, the shape of the
original photo, or cropped to the strokes.

Every method draws on a square canvas made from the photo (padded, stretched, cropped or zoomed onto
the object). From 3.0 on the runs save where the photo lies on that canvas (``photo_frame`` in their
``config.json``); for older runs it is worked out from the settings. A new frame only changes the SVG's
``viewBox`` – the strokes stay vectors; a canvas that was stretched is stretched back by moving the
points (the stroke widths stay as they are).
"""

from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from .svg_path import parse_path_d

MODES = ("square", "photo", "content")
FRAME_KEY = "photo_frame"
DEFAULT_MARGIN = 0.05  # "content": free space around the strokes, as a share of their longer side

ET.register_namespace("", "http://www.w3.org/2000/svg")


# ----------------------------------------------------------------------------- photo -> canvas


def fix_scale_pad(width: int, height: int, margin: int = 10) -> tuple[int, int, int, int, int]:
    """(side, x, y, w, h) of ``imaging.fix_image_scale``: the image centred on a square with ``margin`` px."""
    side = max(width, height) + 2 * margin
    return side, side // 2 - width // 2, side // 2 - height // 2, width, height


def photo_frame(photo_size: tuple[int, int], region: tuple[float, float, float, float] | None = None,
                pad: tuple[int, int, int, int, int] | None = None) -> dict:
    """Where the photo lies on a method's square canvas: ``{"aspect": W / H, "rect": [x0, y0, x1, y1]}``,
    the rect in canvas units of 0..1 (beyond that when the canvas shows only a part of the photo).

    ``region``: (left, top, right, bottom) in photo pixels of the part the method's image shows (framing
    of a small object, crop); ``pad``: (side, x, y, w, h) – that image placed at (x, y) on a side × side
    square (``fix_scale``). Without ``pad`` the image is stretched onto the square canvas."""
    width, height = (float(v) for v in photo_size)
    left, top, right, bottom = region or (0.0, 0.0, width, height)
    if pad:
        side, ix, iy, iw, ih = (float(v) for v in pad)
        inner = (ix / side, iy / side, (ix + iw) / side, (iy + ih) / side)
    else:
        inner = (0.0, 0.0, 1.0, 1.0)
    part = (left / width, top / height, right / width, bottom / height)
    sx = (inner[2] - inner[0]) / max(part[2] - part[0], 1e-9)
    sy = (inner[3] - inner[1]) / max(part[3] - part[1], 1e-9)
    rect = [inner[0] - part[0] * sx, inner[1] - part[1] * sy, inner[0] + (1 - part[0]) * sx,
            inner[1] + (1 - part[1]) * sy]
    return {"aspect": round(width / height, 6), "rect": [round(v, 6) for v in rect]}


def guess_frame(method: str, settings: dict, photo_size: tuple[int, int]) -> dict | None:
    """The photo frame of a run from before 3.0, worked out from its settings – None when it cannot be
    known (a small object may have been zoomed onto, which was not recorded)."""
    w, h = photo_size
    s = settings or {}
    if method in ("clipasso", "swiftsketch") and s.get("mask_object") and s.get("frame_object"):
        return None
    if method == "scenesketch":
        if w == h:
            return photo_frame((w, h))
        if s.get("fix_scale"):
            side = max(w, h)
            return photo_frame((w, h), pad=(side, (side - w) // 2, (side - h) // 2, w, h))
        side = min(w, h)
        left, top = (w - side) // 2, (h - side) // 2
        return photo_frame((w, h), region=(left, top, left + side, top + side))
    if s.get("fix_scale"):
        return photo_frame((w, h), pad=fix_scale_pad(w, h))
    return photo_frame((w, h))


def photo_size(path: str) -> tuple[int, int] | None:
    """Size of an image as it is loaded (EXIF rotation applied), without decoding it."""
    try:
        from PIL import Image

        with Image.open(path) as im:
            w, h = im.size
            if im.getexif().get(0x0112) in (5, 6, 7, 8):  # rotated by 90°
                w, h = h, w
            return int(w), int(h)
    except Exception:
        return None


def run_frame(run_dir: str) -> dict | None:
    """The photo frame of a run: saved by the run, or worked out for an older one (None: unknown)."""
    try:
        with open(os.path.join(run_dir, "config.json"), encoding="utf-8") as f:
            config = json.load(f)
    except (OSError, ValueError):
        config = {}
    saved = config.get(FRAME_KEY)
    if isinstance(saved, dict) and len(saved.get("rect") or []) == 4 and saved.get("aspect"):
        return saved
    from . import jobs

    job_dir = os.path.dirname(os.path.normpath(run_dir))
    state = jobs.read_state(job_dir) or {}
    settings = state.get("settings") or config.get("settings") or {}
    method = state.get("method") or config.get("method") or "clipasso"
    target = state.get("target") or config.get("target") or ""
    image = target if target and os.path.isfile(target) else jobs.saved_input(job_dir, target)
    size = photo_size(image) if image else None
    return guess_frame(method, settings, size) if size else None


# ----------------------------------------------------------------------------- reframing


def _view_box(root) -> tuple[float, float, float, float]:
    box = root.get("viewBox")
    if box:
        vals = [float(v) for v in re.split(r"[\s,]+", box.strip())[:4]]
        if len(vals) == 4 and vals[2] > 0 and vals[3] > 0:
            return tuple(vals)

    def num(v, default):
        m = re.match(r"\s*([-+]?\d*\.?\d+)", v or "")
        return float(m.group(1)) if m else default

    return 0.0, 0.0, num(root.get("width"), 224.0), num(root.get("height"), 224.0)


def _paths(root):
    ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
    return list(root.iter(f"{ns}path"))


def _fmt(v: float) -> str:
    text = f"{v:.3f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def content_box(svg: str) -> tuple[float, float, float, float] | None:
    """(x0, y0, x1, y1) of all strokes in the sketch's units (control points, plus half their width)."""
    root = ET.fromstring(svg)
    box = None
    for el in _paths(root):
        try:
            half = float(el.get("stroke-width") or 1.0) / 2
            subpaths = parse_path_d(el.get("d") or "")
        except (ValueError, IndexError):
            continue
        for segs, _ in subpaths:
            for seg in segs:
                for x, y in seg:
                    b = (x - half, y - half, x + half, y + half)
                    box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]),
                                                 max(box[3], b[3]))
    return box


def _scaled_d(d: str, origin_y: float, factor: float) -> str:
    parts = []
    for segs, closed in parse_path_d(d):
        if not segs:
            continue
        x, y = segs[0][0]
        parts.append(f"M {_fmt(x)} {_fmt(origin_y + (y - origin_y) * factor)}")
        for seg in segs:
            cmd = {2: "L", 3: "Q", 4: "C"}.get(len(seg))
            if cmd is None:
                continue
            parts.append(cmd + " " + " ".join(f"{_fmt(px)} {_fmt(origin_y + (py - origin_y) * factor)}"
                                              for px, py in seg[1:]))
        if closed:
            parts.append("Z")
    return " ".join(parts)


@dataclass
class Framing:
    """A new frame for the sketches of one run: ``box`` is the new viewBox in the sketch's units; with
    ``y_scale`` != 1 the points are first moved vertically by that factor around ``origin_y``."""

    box: tuple[float, float, float, float]
    y_scale: float = 1.0
    origin_y: float = 0.0

    @property
    def aspect(self) -> float:
        return self.box[2] / max(self.box[3], 1e-9)

    def apply(self, svg: str) -> str:
        root = ET.fromstring(svg)
        vx, vy, vw, vh = _view_box(root)
        if abs(self.y_scale - 1.0) > 1e-6:
            for el in _paths(root):
                try:
                    el.set("d", _scaled_d(el.get("d") or "", self.origin_y, self.y_scale))
                except (ValueError, IndexError):
                    continue
        bx, by, bw, bh = self.box
        # keep the scale of the sketch: its user units stay as large as before
        try:
            px = float(re.sub(r"[^\d.]", "", root.get("width", "")) or vw) / vw
        except ValueError:
            px = 1.0
        root.set("viewBox", f"{_fmt(bx)} {_fmt(by)} {_fmt(bw)} {_fmt(bh)}")
        root.set("width", _fmt(bw * px))
        root.set("height", _fmt(bh * px))
        return ET.tostring(root, encoding="unicode")


def make_framing(svg: str, mode: str, frame: dict | None = None, margin: float = DEFAULT_MARGIN) -> Framing | None:
    """The frame for ``mode`` ("square": None, nothing changes); "photo" needs the run's ``frame`` (None
    when it is not known), "content" is measured on ``svg`` (the finished sketch)."""
    if mode not in ("photo", "content"):
        return None
    root = ET.fromstring(svg)
    vx, vy, vw, vh = _view_box(root)
    if mode == "content":
        box = content_box(svg)
        if box is None:
            return None
        pad = max(float(margin), 0.0) * max(box[2] - box[0], box[3] - box[1])
        return Framing((box[0] - pad, box[1] - pad, box[2] - box[0] + 2 * pad, box[3] - box[1] + 2 * pad))
    if not frame:
        return None
    x0, y0, x1, y1 = (float(v) for v in frame["rect"])
    left, top = vx + x0 * vw, vy + y0 * vh
    width, height = (x1 - x0) * vw, (y1 - y0) * vh
    wanted = width / max(float(frame["aspect"]), 1e-9)  # the height the photo's shape asks for
    factor = wanted / max(height, 1e-9)
    if abs(factor - 1.0) < 1e-3:  # padded / cropped / zoomed: the same scale in both directions
        return Framing((left, top, width, height))
    return Framing((left, top, width, wanted), y_scale=factor, origin_y=top)
