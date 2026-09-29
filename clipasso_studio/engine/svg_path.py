"""Minimal SVG path-data parser (no scipy dependency).

``parse_path_d`` returns subpaths as ``(segments, closed)``; each segment is a list of
(x, y) points: 2 points = line, 3 = quadratic, 4 = cubic Bézier. Arcs are converted to
cubic Béziers.
"""

from __future__ import annotations

import math
import re

_TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_ARGS = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}


def _arc_to_cubics(p0, rx, ry, phi_deg, large_arc, sweep, p1):
    """Endpoint arc parameterisation -> list of cubic segments (SVG spec F.6)."""
    x1, y1 = p0
    x2, y2 = p1
    if rx == 0 or ry == 0 or (x1 == x2 and y1 == y2):
        return [[p0, p1]]
    rx, ry = abs(rx), abs(ry)
    phi = math.radians(phi_deg % 360)
    cos_p, sin_p = math.cos(phi), math.sin(phi)
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    x1p = cos_p * dx + sin_p * dy
    y1p = -sin_p * dx + cos_p * dy
    lam = (x1p / rx) ** 2 + (y1p / ry) ** 2
    if lam > 1:
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coef = math.sqrt(max(num / den, 0.0)) if den else 0.0
    if large_arc == sweep:
        coef = -coef
    cxp = coef * rx * y1p / ry
    cyp = -coef * ry * x1p / rx
    cx = cos_p * cxp - sin_p * cyp + (x1 + x2) / 2
    cy = sin_p * cxp + cos_p * cyp + (y1 + y2) / 2

    def angle(ux, uy, vx, vy):
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a

    theta1 = angle(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dtheta = angle((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and dtheta > 0:
        dtheta -= 2 * math.pi
    elif sweep and dtheta < 0:
        dtheta += 2 * math.pi

    n = max(int(math.ceil(abs(dtheta) / (math.pi / 2) - 1e-9)), 1)
    delta = dtheta / n
    t = 4 / 3 * math.tan(delta / 4)

    def point(th):
        x = rx * math.cos(th)
        y = ry * math.sin(th)
        return (cos_p * x - sin_p * y + cx, sin_p * x + cos_p * y + cy)

    def deriv(th):
        x = -rx * math.sin(th)
        y = ry * math.cos(th)
        return (cos_p * x - sin_p * y, sin_p * x + cos_p * y)

    segs = []
    th = theta1
    start = p0
    for i in range(n):
        th2 = th + delta
        end = p1 if i == n - 1 else point(th2)
        d1, d2 = deriv(th), deriv(th2)
        c1 = (start[0] + t * d1[0], start[1] + t * d1[1])
        c2 = (end[0] - t * d2[0], end[1] - t * d2[1])
        segs.append([start, c1, c2, end])
        start = end
        th = th2
    return segs


def parse_path_d(d: str):
    tokens = _TOKEN.findall(d)
    i = 0
    cmd = None
    cur = (0.0, 0.0)
    start = (0.0, 0.0)
    last_ctrl = None  # for S/T reflections
    last_cmd = None
    subpaths = []
    segs: list = []
    closed = False

    def flush():
        nonlocal segs, closed
        if segs:
            subpaths.append((segs, closed))
        segs = []
        closed = False

    while i < len(tokens):
        tok = tokens[i]
        if tok.isalpha():
            cmd = tok
            i += 1
            if cmd in "Zz":
                if segs:
                    if cur != start:
                        segs.append([cur, start])
                    closed = True
                    flush()
                cur = start
                last_ctrl, last_cmd = None, "Z"
                continue
        elif cmd is None:
            raise ValueError("path data must start with a command")
        n = _ARGS[cmd.upper()]
        args = [float(v) for v in tokens[i:i + n]]
        if len(args) < n:
            break
        i += n
        rel = cmd.islower()
        up = cmd.upper()
        ox, oy = cur if rel else (0.0, 0.0)

        if up == "M":
            flush()
            cur = (ox + args[0], oy + args[1])
            start = cur
            cmd = "l" if rel else "L"  # subsequent pairs are implicit line-tos
            last_ctrl = None
        elif up == "L":
            p = (ox + args[0], oy + args[1])
            segs.append([cur, p])
            cur, last_ctrl = p, None
        elif up == "H":
            p = ((cur[0] if rel else 0.0) + args[0], cur[1])
            segs.append([cur, p])
            cur, last_ctrl = p, None
        elif up == "V":
            p = (cur[0], (cur[1] if rel else 0.0) + args[0])
            segs.append([cur, p])
            cur, last_ctrl = p, None
        elif up == "C":
            c1 = (ox + args[0], oy + args[1])
            c2 = (ox + args[2], oy + args[3])
            p = (ox + args[4], oy + args[5])
            segs.append([cur, c1, c2, p])
            cur, last_ctrl = p, c2
        elif up == "S":
            c1 = (2 * cur[0] - last_ctrl[0], 2 * cur[1] - last_ctrl[1]) if last_cmd in "CcSs" and last_ctrl else cur
            c2 = (ox + args[0], oy + args[1])
            p = (ox + args[2], oy + args[3])
            segs.append([cur, c1, c2, p])
            cur, last_ctrl = p, c2
        elif up == "Q":
            c = (ox + args[0], oy + args[1])
            p = (ox + args[2], oy + args[3])
            segs.append([cur, c, p])
            cur, last_ctrl = p, c
        elif up == "T":
            c = (2 * cur[0] - last_ctrl[0], 2 * cur[1] - last_ctrl[1]) if last_cmd in "QqTt" and last_ctrl else cur
            p = (ox + args[0], oy + args[1])
            segs.append([cur, c, p])
            cur, last_ctrl = p, c
        elif up == "A":
            p = (ox + args[5], oy + args[6])
            segs.extend(_arc_to_cubics(cur, args[0], args[1], args[2], bool(args[3]), bool(args[4]), p))
            cur, last_ctrl = p, None
        last_cmd = cmd
    flush()
    return subpaths
