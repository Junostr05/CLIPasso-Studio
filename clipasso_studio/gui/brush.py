"""Brush styles for exported sketches: the same strokes, drawn like ink, pencil, charcoal, neon …

Works on the stroke SVGs of every method (no torch): each ``<path>`` is sampled from its Bézier
segments and replaced by
- ``ink``: a filled outline that is thickest in the middle and tapers to the ends (brush pen),
- ``pencil``: three thin, slightly offset and see-through lines in graphite grey,
- ``charcoal``: several rough lines broken up into grain, over a soft smudge,
- ``chalk``: thin, dry lines with many small gaps (light chalk on a dark paper, or dark on a light one),
- ``ballpoint``: a thin blue line with uneven pressure and a faint second trace,
- ``marker``: a wide stroke with flat ends and some transparency (overlaps get darker),
- ``watercolor``: wide, see-through washes with a darker edge where the pigment dries,
- ``neon``: a glowing tube – wide transparent halos around a light core,
- ``calligraphy``: a broad nib held at a fixed angle – thick across it, thin along it.
Everything is plain SVG geometry (no filters), so Qt, browsers and PDF show the same picture. The random
offsets are seeded per stroke, so an export looks the same every time.
"""

from __future__ import annotations

import math
import random
import xml.etree.ElementTree as ET

from ..engine.svg_path import parse_path_d

STYLES = ("plain", "ink", "pencil", "charcoal", "chalk", "ballpoint", "marker", "watercolor", "neon",
          "calligraphy")
RECOLOURING = ("ballpoint", "watercolor", "neon")  # black strokes get a colour, a glow or a lighter core
SAMPLES_PER_SEGMENT = 16
GRAPHITE = "#3C3C3C"
CHARCOAL = "#1E1E1E"
BALLPOINT_BLUE = "#1D3F94"
WATERCOLOR_BLACK = "#34495E"  # black watercolour is a dark indigo grey
NEON_BLACK = "#18E0FF"
NIB_ANGLE = math.radians(40)  # calligraphy: the angle of the broad nib
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


def wobble(pts, width: float, rng: random.Random, offset: float, amp: float) -> list[tuple[float, float]]:
    """The stroke shifted sideways by ``offset`` with a slow random wave of ``amp`` (all in units of ``width``)."""
    ss = _arc_positions(pts)
    ns = _normals(pts)
    phase, freq = rng.uniform(0, 2 * math.pi), rng.uniform(0.8, 2.2)
    out = []
    for (x, y), (nx, ny), s in zip(pts, ns, ss):
        o = (offset + amp * math.sin(2 * math.pi * freq * s + phase)) * width
        out.append((x + nx * o, y + ny * o))
    return out


def grain(rng: random.Random, width: float, dash: tuple[float, float], gap: tuple[float, float],
          n: int = 12) -> str:
    """A random dash pattern (``stroke-dasharray``) that breaks a line into grain; lengths in units of ``width``."""
    parts = []
    for _ in range(n):
        parts += [rng.uniform(*dash) * width, rng.uniform(*gap) * width]
    return " ".join(_fmt(max(v, 0.05)) for v in parts)


def calligraphy_outline(pts, width: float, angle: float = NIB_ANGLE) -> str:
    """Filled outline of a broad nib held at ``angle``: the stroke is as wide as the nib across its direction
    and thin where it runs along the nib; slightly narrower at both ends."""
    ss = _arc_positions(pts)
    half = 1.5 * width
    nx, ny = math.cos(angle), -math.sin(angle)
    left, right = [], []
    for (x, y), s in zip(pts, ss):
        h = half * (0.45 + 0.55 * min(1.0, 6 * s, 6 * (1 - s)))
        left.append((x + nx * h, y + ny * h))
        right.append((x - nx * h, y - ny * h))
    return _poly(left + right[::-1], closed=True)


def lighter(color: str, share: float) -> str:
    """``color`` mixed with white (share 1: white); unknown colour names stay as they are."""
    c = color.strip().lower()
    rgb = None
    if c.startswith("#") and len(c) in (4, 7):
        h = c[1:] if len(c) == 7 else "".join(ch * 2 for ch in c[1:])
        try:
            rgb = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
        except ValueError:
            rgb = None
    elif c.startswith("rgb(") and c.endswith(")"):
        try:
            rgb = [int(float(v)) for v in c[4:-1].split(",")]
        except ValueError:
            rgb = None
    elif c in _BLACK:
        rgb = [0, 0, 0]
    if rgb is None or len(rgb) != 3:
        return color
    return "#" + "".join(f"{round(v + (255 - v) * share):02x}" for v in rgb)


def _strokes(style: str, ns: str, d: str, parts, color: str, width: float, opacity: float,
             rng: random.Random) -> list:
    """The elements that draw one stroke (``parts``: its sampled sub-paths) in ``style``."""
    black = color.replace(" ", "").lower() in _BLACK
    el = ET.Element
    out = []
    line = {"fill": "none", "stroke-linecap": "round", "stroke-linejoin": "round"}
    if style == "ink":
        for pts in parts:
            out.append(el(f"{ns}path", {"d": ink_outline(pts, width), "fill": color,
                                        "fill-opacity": _fmt(opacity), "stroke": "none"}))
    elif style == "pencil":
        graphite = GRAPHITE if black else color
        for pts in parts:
            for p in pencil_lines(pts, width, rng):
                out.append(el(f"{ns}path", {"d": p, **line, "stroke": graphite, "stroke-width": _fmt(0.55 * width),
                                            "stroke-opacity": _fmt(0.65 * opacity)}))
    elif style == "charcoal":
        c = CHARCOAL if black else color
        for pts in parts:
            out.append(el(f"{ns}path", {"d": ink_outline(pts, 1.6 * width), "fill": c,
                                        "fill-opacity": _fmt(0.16 * opacity), "stroke": "none"}))  # the smudge
            for k in range(8):  # thin streaks along the stroke whose gaps do not line up: grain
                off = (k - 3.5) * 0.24
                out.append(el(f"{ns}path", {
                    "d": _poly(wobble(pts, width, rng, off, 0.2)), "fill": "none", "stroke": c,
                    "stroke-width": _fmt(rng.uniform(0.2, 0.36) * width), "stroke-linecap": "butt",
                    "stroke-linejoin": "round", "stroke-opacity": _fmt(rng.uniform(0.45, 0.75) * opacity),
                    "stroke-dasharray": grain(rng, width, (0.6, 3.0), (0.08, 0.45), 24),
                    "stroke-dashoffset": _fmt(rng.uniform(0, 4) * width)}))
    elif style == "chalk":
        for pts in parts:
            for k in range(8):
                off = (k - 3.5) * 0.2
                out.append(el(f"{ns}path", {
                    "d": _poly(wobble(pts, width, rng, off, 0.15)), "fill": "none", "stroke": color,
                    "stroke-width": _fmt(rng.uniform(0.16, 0.3) * width), "stroke-linecap": "butt",
                    "stroke-linejoin": "round", "stroke-opacity": _fmt(rng.uniform(0.6, 0.9) * opacity),
                    "stroke-dasharray": grain(rng, width, (0.3, 1.8), (0.15, 0.9), 24),
                    "stroke-dashoffset": _fmt(rng.uniform(0, 3) * width)}))
    elif style == "ballpoint":
        c = BALLPOINT_BLUE if black else color
        w = _fmt(max(0.65 * width, 0.4))
        for pts in parts:
            step = 6  # the pressure changes every few samples; the overlaps of the pieces are darker dots
            for i in range(0, len(pts) - 1, step):
                piece = pts[i:i + step + 1]
                out.append(el(f"{ns}path", {"d": _poly(piece), **line, "stroke": c, "stroke-width": w,
                                            "stroke-opacity": _fmt(rng.uniform(0.72, 0.95) * opacity)}))
            out.append(el(f"{ns}path", {"d": _poly(wobble(pts, width, rng, 0.35, 0.15)), **line, "stroke": c,
                                        "stroke-width": _fmt(0.35 * width), "stroke-opacity": _fmt(0.22 * opacity)}))
    elif style == "watercolor":
        c = WATERCOLOR_BLACK if black else color
        for pts in parts:
            for k in range(3):
                wash = wobble(pts, width, rng, rng.uniform(-0.4, 0.4), 0.35)
                out.append(el(f"{ns}path", {"d": ink_outline(wash, rng.uniform(2.6, 3.4) * width), "fill": c,
                                            "fill-opacity": _fmt(0.15 * opacity), "stroke": "none"}))
                if k == 0:  # the pigment collects at the edge of the first wash
                    out.append(el(f"{ns}path", {"d": ink_outline(wash, 3.0 * width), "fill": "none", "stroke": c,
                                                "stroke-width": _fmt(0.3 * width),
                                                "stroke-opacity": _fmt(0.2 * opacity), "stroke-linejoin": "round"}))
    elif style == "neon":
        c = NEON_BLACK if black else color
        for scale, alpha, stroke in ((7.0, 0.05, c), (4.5, 0.1, c), (2.6, 0.24, c), (1.4, 0.7, lighter(c, 0.35)),
                                     (0.6, 0.95, lighter(c, 0.8))):
            out.append(el(f"{ns}path", {"d": d, **line, "stroke": stroke, "stroke-width": _fmt(scale * width),
                                        "stroke-opacity": _fmt(alpha * opacity)}))
    elif style == "calligraphy":
        for pts in parts:
            out.append(el(f"{ns}path", {"d": calligraphy_outline(pts, width), "fill": color,
                                        "fill-opacity": _fmt(opacity), "stroke": "none"}))
    else:  # marker
        out.append(el(f"{ns}path", {"d": d, "fill": "none", "stroke": color, "stroke-width": _fmt(2.4 * width),
                                    "stroke-opacity": _fmt(0.78 * opacity), "stroke-linecap": "butt",
                                    "stroke-linejoin": "round"}))
    return out


def recolour_black(svg: str, color: str) -> str:
    """The sketch with its black strokes in ``color`` (light strokes on a dark paper); other colours stay."""
    root = ET.fromstring(svg)
    ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
    for el in root.iter(f"{ns}path"):
        if (_attr(el, "stroke", "") or "").replace(" ", "").lower() in _BLACK:
            el.set("stroke", color)
            style = el.get("style")
            if style:
                el.set("style", ";".join(p for p in style.split(";") if p.split(":")[0].strip() != "stroke"))
    return ET.tostring(root, encoding="unicode")


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
            new = _strokes(style, ns, d, parts, color, width, opacity, random.Random(rng.random()))
            index = list(parent).index(el)
            parent.remove(el)
            for j, n in enumerate(new):
                parent.insert(index + j, n)
    return ET.tostring(root, encoding="unicode")
