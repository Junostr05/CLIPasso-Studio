#!/usr/bin/env python3
# The app icon's strokes (macos/App/AppIcon.icon/Assets/strokes.svg) made from their centre lines – needs shapely:
#   python3 macos/scripts/icon_strokes.py macos/App/AppIcon.icon/Assets/strokes.svg
"""The icon's strokes as filled outlines: each open Bézier stroke (width 24, round caps and joins) buffered into a
closed polygon – the glass of an .icon closes an open path with a straight edge and lights that edge."""
import sys
import numpy as np
from shapely.geometry import LineString

WIDTH = 24
# the strokes of strokes.svg: a start point, then cubic segments (c1, c2, end) and lines (end)
STROKES = [
    [(304, 608), ("C", (300, 480), (400, 412), (520, 416)), ("C", (610, 419), (660, 470), (688, 492)),
     ("C", (708, 504), (720, 474), (720, 432)), ("L", (720, 382))],
    [(360, 632), ("C", (420, 676), (470, 684), (520, 680)), ("C", (600, 674), (660, 640), (712, 572))],
    [(464, 692), ("C", (452, 736), (430, 764), (392, 788))],
    [(584, 692), ("C", (594, 730), (616, 760), (656, 782))],
]


def points(stroke, n=64):
    out = [np.array(stroke[0], float)]
    for seg in stroke[1:]:
        p0 = out[-1]
        if seg[0] == "L":
            out.append(np.array(seg[1], float))
            continue
        c1, c2, p3 = (np.array(p, float) for p in seg[1:])
        for t in np.linspace(0, 1, n)[1:]:
            out.append((1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * c1 + 3 * (1 - t) * t ** 2 * c2 + t ** 3 * p3)
    return out


def ring(coords):
    pts = list(coords)
    return "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in pts[:-1]) + " Z"


paths = []
for stroke in STROKES:
    shape = LineString(points(stroke)).buffer(WIDTH / 2, quad_segs=16, cap_style="round", join_style="round")
    shape = shape.simplify(0.15)
    d = ring(shape.exterior.coords) + "".join(" " + ring(i.coords) for i in shape.interiors)
    paths.append(f'    <path d="{d}"/>')
svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">\n'
       '  <g fill="#24213A" fill-rule="evenodd">\n' + "\n".join(paths) + "\n  </g>\n</svg>\n")
open(sys.argv[1], "w").write(svg)
print(len(svg), "bytes")
