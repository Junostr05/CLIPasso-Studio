"""Small curve helpers without torch: simplifying a drawn polyline and smoothing it into cubic Béziers.

Used by the pen of the studio (strokes drawn by hand) and the one-line mode of CLIPasso.
"""

from __future__ import annotations

import math

Point = tuple[float, float]


def simplify(points: list[Point], tolerance: float) -> list[Point]:
    """Ramer–Douglas–Peucker: the points that keep the polyline within ``tolerance``."""
    pts = [tuple(map(float, p)) for p in points]
    deduped = [pts[0]] if pts else []
    for p in pts[1:]:
        if p != deduped[-1]:
            deduped.append(p)
    if len(deduped) < 3:
        return deduped
    keep = [False] * len(deduped)
    keep[0] = keep[-1] = True
    stack = [(0, len(deduped) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = deduped[a], deduped[b]
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        best, index = -1.0, -1
        for i in range(a + 1, b):
            px, py = deduped[i]
            if length == 0:
                d = math.hypot(px - ax, py - ay)
            else:
                d = abs(dy * px - dx * py + bx * ay - by * ax) / length
            if d > best:
                best, index = d, i
        if index >= 0 and best > tolerance:
            keep[index] = True
            stack += [(a, index), (index, b)]
    return [p for p, k in zip(deduped, keep) if k]


def catmull_rom_bezier(points: list[Point]) -> list[tuple[Point, Point, Point, Point]]:
    """Cubic Bézier segments (p0, c1, c2, p1) of the Catmull–Rom spline through ``points``
    (the curve passes through every point; the ends are clamped)."""
    pts = [tuple(map(float, p)) for p in points]
    if len(pts) < 2:
        return []
    segments = []
    for i in range(len(pts) - 1):
        p0 = pts[max(i - 1, 0)]
        p1, p2 = pts[i], pts[i + 1]
        p3 = pts[min(i + 2, len(pts) - 1)]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        segments.append((p1, c1, c2, p2))
    return segments


def bezier_d(segments: list[tuple[Point, Point, Point, Point]], digits: int = 3) -> str:
    """SVG path data of connected cubic segments."""
    def f(v: float) -> str:
        text = f"{v:.{digits}f}".rstrip("0").rstrip(".")
        return "0" if text in ("-0", "") else text

    if not segments:
        return ""
    x, y = segments[0][0]
    parts = [f"M {f(x)} {f(y)}"]
    for _, c1, c2, p in segments:
        parts.append(f"C {f(c1[0])} {f(c1[1])} {f(c2[0])} {f(c2[1])} {f(p[0])} {f(p[1])}")
    return " ".join(parts)
