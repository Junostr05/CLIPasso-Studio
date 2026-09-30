"""Export of results: restyled SVG, PNG at any size, GIF / MP4 of the drawing process."""

from __future__ import annotations

import glob
import os
import re
import xml.etree.ElementTree as ET

from PIL import Image
from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ET.register_namespace("", "http://www.w3.org/2000/svg")


def restyle_svg(svg: str, stroke_color: str | None = None, width_scale: float = 1.0,
                background: str | None = None) -> str:
    """Change stroke colour / width and add a background to a CLIPasso SVG (no torch needed)."""
    root = ET.fromstring(svg)
    ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
    for el in root.iter(f"{ns}path"):
        if stroke_color:
            el.set("stroke", stroke_color)
        if width_scale != 1.0:
            try:
                w = float(el.get("stroke-width", "1"))
                el.set("stroke-width", f"{w * width_scale:.4g}")
            except ValueError:
                pass
    for old in [el for el in list(root) if el.tag == f"{ns}rect" and el.get("data-bg") == "1"]:
        root.remove(old)
    if background:
        rect = ET.Element(f"{ns}rect", {"width": "100%", "height": "100%", "fill": background, "data-bg": "1"})
        root.insert(0, rect)
    return ET.tostring(root, encoding="unicode")


def svg_to_qimage(svg: str, size: int, background: QColor | None) -> QImage:
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(background if background is not None else QColor(0, 0, 0, 0))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p, QRectF(0, 0, size, size))
    p.end()
    return img


def qimage_to_pil(img: QImage) -> Image.Image:
    img = img.convertToFormat(QImage.Format_RGBA8888)
    w, h = img.width(), img.height()
    data = bytes(img.constBits())[: w * h * 4]
    return Image.frombuffer("RGBA", (w, h), data, "raw", "RGBA", 0, 1).copy()


def export_svg(src_svg: str, dest: str, stroke_color: str | None = None, width_scale: float = 1.0,
               background: str | None = None) -> None:
    with open(src_svg, encoding="utf-8") as f:
        svg = f.read()
    with open(dest, "w", encoding="utf-8") as f:
        f.write(restyle_svg(svg, stroke_color, width_scale, background))


def single_layer_svg(svg: str, stroke_color: str | None = None, width_scale: float = 1.0) -> str:
    """All strokes as one path (one sub-path per stroke) in a single layer: no background, no
    element per stroke. Plotter / cutter software (Cricut, Silhouette, laser tools) imports this as
    one layer instead of one layer per stroke; Inkscape shows it as the layer "Strokes"."""
    root = ET.fromstring(svg)
    ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
    ds, widths = [], []
    for el in root.iter(f"{ns}path"):
        d = (el.get("d") or "").strip()
        if not d:
            continue
        ds.append(d)
        try:
            widths.append(float(el.get("stroke-width", "1")))
        except ValueError:
            pass
    width = (sorted(widths)[len(widths) // 2] if widths else 1.0) * width_scale
    w, h = root.get("width", "224"), root.get("height", "224")
    view = root.get("viewBox") or f"0 0 {w} {h}"
    ink = "http://www.inkscape.org/namespaces/inkscape"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="{ink}" version="1.1" '
        f'width="{w}" height="{h}" viewBox="{view}">\n'
        '  <g id="strokes" inkscape:groupmode="layer" inkscape:label="Strokes">\n'
        f'    <path d="{" ".join(ds)}" fill="none" stroke="{stroke_color or "#000000"}" '
        f'stroke-width="{width:.4g}" stroke-linecap="round" stroke-linejoin="round"/>\n'
        '  </g>\n'
        '</svg>\n'
    )


def export_single_layer_svg(src_svg: str, dest: str, stroke_color: str | None = None,
                            width_scale: float = 1.0) -> None:
    with open(src_svg, encoding="utf-8") as f:
        svg = f.read()
    with open(dest, "w", encoding="utf-8") as f:
        f.write(single_layer_svg(svg, stroke_color, width_scale))


def export_png(src_svg: str, dest: str, size: int = 1024, stroke_color: str | None = None,
               width_scale: float = 1.0, background: str | None = "#FFFFFF") -> None:
    with open(src_svg, encoding="utf-8") as f:
        svg = restyle_svg(f.read(), stroke_color, width_scale)
    bg = QColor(background) if background else None
    svg_to_qimage(svg, size, bg).save(dest)


def _iter_number(path: str) -> int:
    m = re.search(r"svg_iter(\d+)\.svg$", path)
    return int(m.group(1)) if m else -1


def animation_frames(run_dir: str, upto_best: bool = True) -> list[str]:
    frames = sorted(glob.glob(os.path.join(run_dir, "svg_logs", "svg_iter*.svg")), key=_iter_number)
    if upto_best:
        try:
            import json

            with open(os.path.join(run_dir, "config.json"), encoding="utf-8") as f:
                best = int(json.load(f).get("best_iter", 10 ** 9))
            frames = [fr for fr in frames if _iter_number(fr) <= best] or frames
        except (OSError, ValueError):
            pass
    return frames


def export_animation(run_dir: str, dest: str, size: int = 512, fps: int = 20, stroke_color: str | None = None,
                     width_scale: float = 1.0, background: str = "#FFFFFF", progress=None,
                     max_frames: int = 300) -> int:
    frames = animation_frames(run_dir)
    if not frames:
        raise FileNotFoundError("no intermediate SVGs (svg_logs) found")
    if len(frames) > max_frames:
        step = len(frames) / max_frames
        frames = [frames[int(i * step)] for i in range(max_frames)] + [frames[-1]]
    images = []
    for i, fr in enumerate(frames):
        with open(fr, encoding="utf-8") as f:
            svg = restyle_svg(f.read(), stroke_color, width_scale)
        images.append(qimage_to_pil(svg_to_qimage(svg, size, QColor(background))).convert("RGB"))
        if progress:
            progress(i + 1, len(frames))
    hold = max(fps, 1)  # keep the final sketch visible for ~1 s
    images += [images[-1]] * hold
    if dest.lower().endswith(".gif"):
        images[0].save(dest, save_all=True, append_images=images[1:], duration=int(1000 / fps), loop=0,
                       optimize=True)
    else:
        import imageio.v2 as imageio
        import numpy as np

        with imageio.get_writer(dest, fps=fps, codec="libx264", quality=8, macro_block_size=16) as w:
            for im in images:
                w.append_data(np.asarray(im))
    return len(images)


def make_transparent_background(color: QColor) -> bool:
    return color.alpha() == 0 or color == Qt.transparent
