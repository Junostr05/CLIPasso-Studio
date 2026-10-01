"""Editing the strokes of a finished sketch (the eraser and the pen of the studio), without torch.

Strokes are the ``<path>`` elements of the sketch SVG, numbered in document order.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET

from .brush import sample

ET.register_namespace("", "http://www.w3.org/2000/svg")
EDITED = "edited.svg"
HIGHLIGHT = "#EF4444"


def view_box(svg: str) -> tuple[float, float, float, float]:
    root = ET.fromstring(svg)
    box = root.get("viewBox")
    if box:
        vals = [float(v) for v in re.split(r"[\s,]+", box.strip())[:4]]
        if len(vals) == 4:
            return tuple(vals)
    w = float(re.sub(r"[^\d.]", "", root.get("width", "224")) or 224)
    h = float(re.sub(r"[^\d.]", "", root.get("height", "224")) or 224)
    return 0.0, 0.0, w, h


def _paths(root):
    ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
    return [el for el in root.iter(f"{ns}path")]


class StrokeIndex:
    """The strokes of one SVG as polylines, for hit tests."""

    def __init__(self, svg: str):
        self.svg = svg
        root = ET.fromstring(svg)
        self.lines: list[list[list[tuple[float, float]]]] = []
        self.widths: list[float] = []
        for el in _paths(root):
            try:
                self.lines.append(sample(el.get("d") or "", per_segment=12))
            except (ValueError, IndexError):
                self.lines.append([])
            try:
                self.widths.append(float(el.get("stroke-width") or 1.0))
            except ValueError:
                self.widths.append(1.0)

    def __len__(self):
        return len(self.lines)

    def hit(self, x: float, y: float, tolerance: float) -> int | None:
        """The stroke nearest to (x, y) within ``tolerance`` (+ half its width), or None."""
        best, best_d = None, float("inf")
        for i, subpaths in enumerate(self.lines):
            reach = tolerance + self.widths[i] / 2
            for pts in subpaths:
                for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                    d = _segment_distance(x, y, x0, y0, x1, y1)
                    if d < best_d and d <= reach:
                        best, best_d = i, d
        return best


def _segment_distance(px, py, x0, y0, x1, y1) -> float:
    dx, dy = x1 - x0, y1 - y0
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / length2))
    return math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))


def remove_strokes(svg: str, indices) -> str:
    """The sketch without the strokes ``indices``."""
    drop = set(int(i) for i in indices)
    root = ET.fromstring(svg)
    parents = {c: p for p in root.iter() for c in p}
    for i, el in enumerate(_paths(root)):
        if i in drop:
            parents[el].remove(el)
    return ET.tostring(root, encoding="unicode")


def highlight(svg: str, index: int, color: str = HIGHLIGHT) -> str:
    """The sketch with stroke ``index`` drawn in ``color`` (hover feedback of the eraser)."""
    root = ET.fromstring(svg)
    for i, el in enumerate(_paths(root)):
        if i == index:
            el.set("stroke", color)
            el.set("stroke-opacity", "1")
            style = el.get("style")
            if style:
                el.set("style", re.sub(r"stroke\s*:[^;]*;?", "", style))
    return ET.tostring(root, encoding="unicode")


def count(svg: str) -> int:
    return len(_paths(ET.fromstring(svg)))


FIXED_ATTR = "data-fixed"  # a stroke drawn by hand: kept as it is when CLIPasso continues the sketch
PEN_TOLERANCE = 0.004  # simplification of a drawn stroke, as a share of the sketch size


def _widths(root) -> list[float]:
    out = []
    for el in _paths(root):
        try:
            out.append(float(el.get("stroke-width") or 1.0))
        except ValueError:
            continue
    return out


def append_stroke(svg: str, points, width: float | None = None, fixed: bool = True) -> str:
    """The sketch with a stroke drawn through ``points`` (sketch coordinates): the polyline is simplified
    and smoothed into cubic Béziers; the width is the median of the sketch's strokes (``fixed``: marked
    to stay as it is when CLIPasso continues the sketch)."""
    from ..curves import bezier_d, catmull_rom_bezier, simplify

    root = ET.fromstring(svg)
    _, _, w, h = view_box(svg)
    pts = simplify(list(points), PEN_TOLERANCE * max(w, h))
    if len(pts) < 2:
        return svg
    if width is None:
        widths = sorted(_widths(root))
        width = widths[len(widths) // 2] if widths else 1.5 * max(w, h) / 224
    ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
    attrs = {"d": bezier_d(catmull_rom_bezier(pts)), "fill": "none", "stroke": "rgb(0, 0, 0)",
             "stroke-opacity": "1", "stroke-width": f"{float(width):.3f}".rstrip("0").rstrip("."),
             "stroke-linecap": "round", "stroke-linejoin": "round"}
    if fixed:
        attrs[FIXED_ATTR] = "1"
    paths = _paths(root)
    parents = {c: p for p in root.iter() for c in p}
    parent = parents.get(paths[-1], root) if paths else root
    ET.SubElement(parent, f"{ns}path", attrs)
    return ET.tostring(root, encoding="unicode")


def fixed_count(svg: str) -> int:
    """Strokes drawn by hand (marked as fixed)."""
    return sum(1 for el in _paths(ET.fromstring(svg)) if el.get(FIXED_ATTR) in ("1", "true"))


def unfix(svg: str) -> str:
    """The sketch with all strokes free again (CLIPasso may move every stroke)."""
    root = ET.fromstring(svg)
    for el in _paths(root):
        el.attrib.pop(FIXED_ATTR, None)
    return ET.tostring(root, encoding="unicode")


def shape_count(svg: str) -> int:
    """Strokes as CLIPasso loads them: every subpath of a ``<path>`` is one stroke."""
    n = 0
    for el in _paths(ET.fromstring(svg)):
        try:
            n += len(sample(el.get("d") or "", per_segment=2))
        except (ValueError, IndexError):
            continue
    return n
