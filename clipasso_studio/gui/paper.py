"""Paper for the sketches: textures made here from seeded noise (no image files, nothing to license), a colour
and a vignette – in the preview and in every export.

A paper is ``{"kind": one of KINDS, "vignette": 0..1}`` plus the background colour of the export (or the
kind's own colour). ``"none"`` without a vignette is the plain background colour as before. The texture is
computed at a size of its own (``REFERENCE`` px for the longer side, at most ``MAX_SIDE``) with features in
units of that size, so a preview and an export of any size look alike. No torch.
"""

from __future__ import annotations

import base64
import io
import math
import re
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

KINDS = ("none", "drawing", "watercolor", "kraft", "linen", "blackboard")
COLORS = {"none": "#FFFFFF", "drawing": "#FBFAF6", "watercolor": "#FAF7F0", "kraft": "#C9A97C",
          "linen": "#EFE9DD", "blackboard": "#2C3A33"}
REFERENCE = 768  # px: feature sizes are given for a texture of this size
MAX_SIDE = 1600  # px: larger pictures get the texture scaled up
SVG_SIDE = 1200  # px: the texture embedded in an SVG
VIGNETTE = 0.35  # the vignette of the "Vignette" switch of the preview
DARK = 0.42  # a paper darker than this (luminance 0..1) gets light strokes in the preview
LIGHT_STROKE = "#F2F2EC"


def normalize(paper: dict | None) -> dict | None:
    """``{"kind", "vignette"}`` with valid values, or None for no paper (plain colour, no vignette)."""
    if not paper:
        return None
    kind = paper.get("kind") or "none"
    kind = kind if kind in KINDS else "none"
    try:
        vignette = min(max(float(paper.get("vignette") or 0.0), 0.0), 1.0)
    except (TypeError, ValueError):
        vignette = 0.0
    if kind == "none" and vignette <= 0:
        return None
    return {"kind": kind, "vignette": vignette}


def color_of(paper: dict | None, background: str | None = None) -> str:
    """The paper colour: the background colour if there is one, else the kind's own colour."""
    if background and background != "transparent" and _rgb(background) is not None:
        return background
    return COLORS.get((paper or {}).get("kind") or "none", "#FFFFFF")


def _rgb(color: str) -> tuple[int, int, int] | None:
    c = (color or "").strip()
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", c)
    if m:
        h = m.group(1)
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    m = re.fullmatch(r"#?([0-9a-fA-F]{3})", c)
    if m:
        return tuple(int(ch * 2, 16) for ch in m.group(1))
    return None


def is_dark(color: str) -> bool:
    rgb = _rgb(color)
    if rgb is None:
        return False
    r, g, b = (v / 255 for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b < DARK


# ------------------------------------------------------------------ textures
def _noise(rng: np.random.Generator, h: int, w: int, cell: float) -> np.ndarray:
    """Smooth value noise with features about ``cell`` px apart (unit variance)."""
    gh, gw = max(2, int(h / max(cell, 1.0)) + 2), max(2, int(w / max(cell, 1.0)) + 2)
    grid = rng.standard_normal((gh, gw)).astype(np.float32)
    out = np.asarray(Image.fromarray(grid, mode="F").resize((w, h), Image.BICUBIC), dtype=np.float32)
    return out / (out.std() + 1e-6)


def _shade(height: np.ndarray) -> np.ndarray:
    """Light from the upper left on a height field (bumps of the paper), unit variance."""
    gy, gx = np.gradient(height)
    shade = -(gx + gy)
    return shade / (shade.std() + 1e-6)


def _fibers(rng: np.random.Generator, h: int, w: int, s: float, count: int, length: tuple[float, float]) -> np.ndarray:
    """Short darker and lighter fibres."""
    layer = Image.new("L", (w, h), 128)  # 128: no change
    draw = ImageDraw.Draw(layer)
    for _ in range(count):
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        a = rng.uniform(0, math.pi)
        n = rng.uniform(*length) * s
        bend = rng.uniform(-0.4, 0.4)
        pts = []
        for k in range(6):
            t = k / 5
            ang = a + bend * t
            pts.append((x + math.cos(ang) * n * t, y + math.sin(ang) * n * t))
        draw.line(pts, fill=int(128 + rng.choice((-1, 1)) * rng.uniform(64, 127)), width=max(1, round(0.8 * s)))
    return (np.asarray(layer.filter(ImageFilter.GaussianBlur(0.6 * s)), dtype=np.float32) - 128) / 127


@lru_cache(maxsize=12)
def texture(kind: str, w: int, h: int, seed: int = 7) -> np.ndarray:
    """Brightness change per pixel (in 0..255 units) of the paper ``kind`` at ``w`` x ``h``."""
    if kind not in KINDS or kind == "none":
        return np.zeros((h, w), dtype=np.float32)
    longer = max(w, h)
    side = min(longer, MAX_SIDE)
    gw, gh = max(1, round(w * side / longer)), max(1, round(h * side / longer))
    s = side / REFERENCE  # the feature sizes below are for a texture of REFERENCE px
    rng = np.random.default_rng([seed, KINDS.index(kind)])
    if kind == "drawing":  # fine tooth
        height = _noise(rng, gh, gw, 2.0 * s) + 0.5 * _noise(rng, gh, gw, 6 * s)
        t = 2.2 * _shade(height) + 2.0 * _noise(rng, gh, gw, 1.2 * s) + 1.2 * _noise(rng, gh, gw, 60 * s)
    elif kind == "watercolor":  # cold-pressed: soft bumps
        height = _noise(rng, gh, gw, 7 * s) + 0.6 * _noise(rng, gh, gw, 16 * s) + 0.3 * _noise(rng, gh, gw, 3 * s)
        t = 6.0 * _shade(height) + 2.5 * _noise(rng, gh, gw, 80 * s)
    elif kind == "kraft":  # brown, mottled, with fibres
        t = (4.5 * _noise(rng, gh, gw, 40 * s) + 3.5 * _noise(rng, gh, gw, 2 * s)
             + 22.0 * _fibers(rng, gh, gw, s, int(gw * gh / (900 * s * s)) + 1, (6, 26)))
    elif kind == "linen":  # woven threads
        p = 4.0 * s
        y, x = np.mgrid[0:gh, 0:gw].astype(np.float32)
        rows = rng.normal(0, 1, int(gh / p) + 2).astype(np.float32)
        cols = rng.normal(0, 1, int(gw / p) + 2).astype(np.float32)
        wobble = 0.6 * _noise(rng, gh, gw, 30 * s)
        warp = np.cos(2 * math.pi * (y + wobble) / p) * (1 + 0.35 * rows[(y / p).astype(int)])
        weft = np.cos(2 * math.pi * (x - wobble) / p) * (1 + 0.35 * cols[(x / p).astype(int)])
        t = 4.0 * (warp + weft) + 2.0 * _noise(rng, gh, gw, 1.5 * s) + 2.5 * _noise(rng, gh, gw, 70 * s)
    else:  # blackboard: wiped chalk dust
        wipes = np.clip(_noise(rng, gh, gw, 110 * s) + 0.5 * _noise(rng, gh, gw, 35 * s), 0, None)
        t = 7.0 * wipes + 2.2 * _noise(rng, gh, gw, 1.2 * s) + 1.5 * _noise(rng, gh, gw, 6 * s)
    t = t.astype(np.float32)
    if (gw, gh) != (w, h):
        t = np.asarray(Image.fromarray(t, mode="F").resize((w, h), Image.BICUBIC), dtype=np.float32)
    t.setflags(write=False)
    return t


def _vignette(w: int, h: int, strength: float) -> np.ndarray:
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    r = np.sqrt(((x + 0.5) / w - 0.5) ** 2 + ((y + 0.5) / h - 0.5) ** 2) / math.sqrt(0.5)  # 0 centre, 1 corner
    edge = np.clip((r - 0.35) / 0.65, 0, 1)
    return 1.0 - 0.55 * strength * edge * edge * (3 - 2 * edge)


def image(paper: dict | None, w: int, h: int, background: str | None = None) -> Image.Image:
    """The paper as an RGB picture of ``w`` x ``h`` px."""
    p = normalize(paper) or {"kind": "none", "vignette": 0.0}
    rgb = np.array(_rgb(color_of(p, background)) or (255, 255, 255), dtype=np.float32)
    out = rgb[None, None, :] + texture(p["kind"], w, h)[:, :, None]
    if p["vignette"] > 0:
        out = out * _vignette(w, h, p["vignette"])[:, :, None]
    return Image.fromarray(np.clip(out + 0.5, 0, 255).astype(np.uint8), "RGB")


def qimage(paper: dict | None, w: int, h: int, background: str | None = None):
    """The paper as a QImage (ARGB32)."""
    from PySide6.QtGui import QImage

    img = image(paper, w, h, background).convert("RGBA")
    data = img.tobytes()
    return QImage(data, w, h, 4 * w, QImage.Format_RGBA8888).convertToFormat(QImage.Format_ARGB32)


def svg_with_paper(svg: str, paper: dict | None, background: str | None = None, side: int = SVG_SIDE) -> str:
    """The SVG with the paper as its background picture (an embedded JPEG under the strokes, covering the
    viewBox); a former background rectangle is replaced."""
    p = normalize(paper)
    if p is None:
        return svg
    head = re.search(r"<svg\b[^>]*>", svg)
    if not head:
        return svg
    view = re.search(r'viewBox="([^"]+)"', head.group(0))
    if view:
        x0, y0, vw, vh = (float(v) for v in view.group(1).replace(",", " ").split())
    else:
        wm = re.search(r'width="([\d.]+)', head.group(0))
        hm = re.search(r'height="([\d.]+)', head.group(0))
        x0, y0, vw, vh = 0.0, 0.0, float(wm.group(1) if wm else 224), float(hm.group(1) if hm else 224)
    scale = side / max(vw, vh, 1e-6)
    pw, ph = max(1, round(vw * scale)), max(1, round(vh * scale))
    buf = io.BytesIO()
    image(p, pw, ph, background).save(buf, "JPEG", quality=88)
    href = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    body = re.sub(r'<rect\b[^>]*data-bg="1"[^>]*/>', "", svg[head.end():])
    tag = (f'<image data-bg="1" x="{x0:g}" y="{y0:g}" width="{vw:g}" height="{vh:g}" '
           f'preserveAspectRatio="none" href="{href}" xlink:href="{href}"/>')
    start = head.group(0)
    if "xmlns:xlink" not in start:
        start = start[:-1] + ' xmlns:xlink="http://www.w3.org/1999/xlink">'
    return svg[:head.start()] + start + tag + body
