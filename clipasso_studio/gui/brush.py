"""Brush styles for exported sketches: the same strokes, drawn like ink, pencil or marker.

Works on the stroke SVGs of every method (no torch): each ``<path>`` is sampled from its Bézier
segments and replaced by
- ``ink``: a filled outline that is thickest in the middle and tapers to the ends (brush pen),
- ``pencil``: three thin, slightly offset and see-through lines in graphite grey,
- ``marker``: a wide stroke with flat ends and some transparency (overlaps get darker).
The random offsets of the pencil are seeded per stroke, so an export looks the same every time.
"""

from __future__ import annotations

import math
import random
import xml.etree.ElementTree as ET

from ..engine.svg_path import parse_path_d

STYLES = ("plain", "ink", "pencil", "marker")
SAMPLES_PER_SEGMENT = 16
GRAPHITE = "#3C3C3C"
_BLACK = {"#000", "#000000", "black", "rgb(0,0,0)"}

ET.register_namespace("", "http://www.w3.org/2000/svg")


def _bezier(seg, t):
    n = len(seg)
    if n == 2:
        (x0, y0), (x1, y1) = seg
        return x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
    if n == 3:
        (x0, y0), (x1, y1), (x2, y2) = seg
        u = 1 - t
        return u * u * x0 + 2 * u * t * x1 + t * t * x2, u * u * y0 + 2 * u * t * y1 + t * t * y2
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = seg[:4]
    u = 1 - t
    a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
    return a * x0 + b * x1 + c * x2 + d * x3, a * y0 + b * y1 + c * y2 + d * y3


def sample(d: str, per_segment: int = SAMPLES_PER_SEGMENT) -> list[list[tuple[float, float]]]:
    """Points along each sub-path of an SVG path."""
    out = []
    for segs, _closed in parse_path_d(d):
        pts = []
        for seg in segs:
            steps = per_segment  # straight segments too, so they can taper / wobble
            start = 1 if pts else 0
            pts += [_bezier(seg, i / (steps - 1)) for i in range(start, steps)]
        dedup = [pts[0]] if pts else []
        for p in pts[1:]:
            if abs(p[0] - dedup[-1][0]) > 1e-6 or abs(p[1] - dedup[-1][1]) > 1e-6:
                dedup.append(p)
        if len(dedup) >= 2:
            out.append(dedup)
    return out


def _normals(pts):
    ns = []
    for i in range(len(pts)):
        a = pts[max(i - 1, 0)]
        b = pts[min(i + 1, len(pts) - 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy) or 1.0
        ns.append((-dy / length, dx / length))
    return ns


def _arc_positions(pts):
    acc = [0.0]
    for a, b in zip(pts, pts[1:]):
        acc.append(acc[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    total = acc[-1] or 1.0
    return [v / total for v in acc]


def _fmt(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _poly(pts, closed=False) -> str:
    d = "M " + " L ".join(f"{_fmt(x)} {_fmt(y)}" for x, y in pts)
    return d + " Z" if closed else d


def ink_outline(pts, width: float) -> str:
    """Filled outline with a width profile that tapers from the middle to both ends."""
    ss = _arc_positions(pts)
    ns = _normals(pts)
    left, right = [], []
    for (x, y), (nx, ny), s in zip(pts, ns, ss):
        half = width * 0.7 * (0.22 + 0.78 * math.sin(math.pi * s) ** 0.6)
        left.append((x + nx * half, y + ny * half))
        right.append((x - nx * half, y - ny * half))
    return _poly(left + right[::-1], closed=True)


def pencil_lines(pts, width: float, rng: random.Random, copies: int = 3) -> list[str]:
    """A few thin lines wobbling slightly around the stroke."""
    ss = _arc_positions(pts)
    ns = _normals(pts)
    amp = 0.35 * width + 0.25
    lines = []
    for k in range(copies):
        phase, freq = rng.uniform(0, 2 * math.pi), rng.uniform(1.0, 2.5)
        offset = (k - (copies - 1) / 2) * 0.45 * width
        pts_k = []
        for (x, y), (nx, ny), s in zip(pts, ns, ss):
            o = offset + amp * math.sin(2 * math.pi * freq * s + phase) + rng.uniform(-0.12, 0.12) * width
            pts_k.append((x + nx * o, y + ny * o))
        lines.append(_poly(pts_k))
    return lines


def _style_of(el) -> dict:
    style = {}
    for part in (el.get("style") or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            style[k.strip()] = v.strip()
    return style


def _attr(el, name, default=None):
    return el.get(name) or _style_of(el).get(name) or default


def stylize_svg(svg: str, style: str = "plain", seed: int = 0) -> str:
    """The sketch with every stroke drawn in ``style`` (see the module docstring)."""
    if style == "plain" or style not in STYLES:
        return svg
    root = ET.fromstring(svg)
    ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
    rng = random.Random(seed)
    for parent in list(root.iter()):
        for i, el in enumerate(list(parent)):
            if el.tag != f"{ns}path":
                continue
            d = el.get("d") or ""
            color = _attr(el, "stroke", "#000000")
            if color == "none":
                continue
            try:
                width = float(_attr(el, "stroke-width", "1"))
                opacity = float(_attr(el, "stroke-opacity", "1"))
            except ValueError:
                width, opacity = 1.0, 1.0
            try:
                parts = sample(d)
            except (ValueError, IndexError):
                continue
            new = []
            if style == "ink":
                for pts in parts:
                    new.append(ET.Element(f"{ns}path", {"d": ink_outline(pts, width), "fill": color,
                                                        "fill-opacity": _fmt(opacity), "stroke": "none"}))
            elif style == "pencil":
                graphite = GRAPHITE if color.replace(" ", "").lower() in _BLACK else color
                stroke_rng = random.Random(rng.random())
                for pts in parts:
                    for line in pencil_lines(pts, width, stroke_rng):
                        new.append(ET.Element(f"{ns}path", {
                            "d": line, "fill": "none", "stroke": graphite, "stroke-width": _fmt(0.55 * width),
                            "stroke-opacity": _fmt(0.65 * opacity), "stroke-linecap": "round",
                            "stroke-linejoin": "round"}))
            else:  # marker
                new.append(ET.Element(f"{ns}path", {
                    "d": d, "fill": "none", "stroke": color, "stroke-width": _fmt(2.4 * width),
                    "stroke-opacity": _fmt(0.78 * opacity), "stroke-linecap": "butt", "stroke-linejoin": "round"}))
            index = list(parent).index(el)
            parent.remove(el)
            for j, n in enumerate(new):
                parent.insert(index + j, n)
    return ET.tostring(root, encoding="unicode")
