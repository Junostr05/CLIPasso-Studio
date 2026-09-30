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

from ..engine import jobs
from .brush import stylize_svg

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
               background: str | None = None, style: str = "plain") -> None:
    with open(src_svg, encoding="utf-8") as f:
        svg = f.read()
    with open(dest, "w", encoding="utf-8") as f:
        f.write(stylize_svg(restyle_svg(svg, stroke_color, width_scale, background), style))


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
               width_scale: float = 1.0, background: str | None = "#FFFFFF", style: str = "plain") -> None:
    with open(src_svg, encoding="utf-8") as f:
        svg = stylize_svg(restyle_svg(f.read(), stroke_color, width_scale), style)
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


MP4_FPS = 30
MIN_FRAME_MS = 20  # GIF / WebP: browsers slow shorter GIF frame delays down to 100 ms
MAX_FRAMES = 600
MAX_FRAME_BYTES = 300_000_000  # the drawn frames wait in memory (1 byte per pixel) until they are encoded
INK_LEVELS = 8  # palette steps from the background to the stroke colour (anti-aliased edges)
_BLACK = {"#000", "#000000", "black", "rgb(0,0,0)"}


def animation_plan(n: int, length: float | None = None, fps: float = 20.0, hold: float = 1.0,
                   fmt: str = "gif", size: int = 512) -> tuple[list[int], list[float]]:
    """Which of the ``n`` drawn frames an animation shows, and how long (ms) each one stays.

    The drawing takes ``length`` seconds (default: ``n / fps``) and the final sketch stays ``hold``
    seconds longer. GIF / WebP show each drawn frame for length / n – below 20 ms per frame the frames
    are thinned out; MP4 plays at 30 fps and repeats or skips drawn frames to fill the length."""
    if n <= 0:
        return [], []
    length = n / max(float(fps), 1e-3) if length is None else max(float(length), 0.1)
    hold = max(float(hold), 0.0)
    if fmt == "mp4":
        count = max(1, round(length * MP4_FPS))
        idx = [max(0, (i + 1) * n // count - 1) for i in range(count)]
        idx += [n - 1] * round(hold * MP4_FPS)
        return idx, [1000.0 / MP4_FPS] * len(idx)
    limit = min(int(length * 1000 // MIN_FRAME_MS), MAX_FRAMES, MAX_FRAME_BYTES // max(size * size, 1))
    k = max(1, min(n, limit))
    idx = [round(i * (n - 1) / (k - 1)) for i in range(k)] if k > 1 else [n - 1]
    step = 10 if fmt == "gif" else 1  # GIF stores delays in 1/100 s
    ends = [round(length * 1000 * (i + 1) / k / step) * step for i in range(k)]
    durations = [float(max(step, e - s)) for s, e in zip([0] + ends[:-1], ends)]
    durations[-1] += round(hold * 1000 / step) * step
    return idx, durations


def _one_colour(svg: str) -> bool:
    """All strokes black (every method draws black strokes; CLIPasso varies their opacity)."""
    colours = {c.replace(" ", "").lower() for c in re.findall(r'stroke="([^"]+)"', svg)} - {"none"}
    return colours <= _BLACK


def _ink(svg: str, size: int, width_scale: float, style: str = "plain"):
    """Rendered strokes as palette steps 0 (background) .. INK_LEVELS - 1 (full stroke colour)."""
    import numpy as np

    img = svg_to_qimage(stylize_svg(restyle_svg(svg, "#000000", width_scale), style), size, QColor("#FFFFFF"))
    grey = np.asarray(qimage_to_pil(img).convert("L"), dtype=np.uint16)
    return (((255 - grey) * (INK_LEVELS - 1) + 127) // 255).astype(np.uint8)


def _ink_palette(stroke: QColor, background: QColor | None) -> tuple[list[int], bytes | None]:
    """RGB palette (and alpha per entry for a transparent background) of the ink steps."""
    pal, alpha = [], []
    for i in range(INK_LEVELS):
        f = i / (INK_LEVELS - 1)
        if background is None:
            pal += [stroke.red(), stroke.green(), stroke.blue()]
            alpha.append(round(255 * f))
        else:
            pal += [round(b + (s - b) * f) for s, b in ((stroke.red(), background.red()),
                                                        (stroke.green(), background.green()),
                                                        (stroke.blue(), background.blue()))]
    return pal, (bytes(alpha) if background is None else None)


def export_animation(run_dir: str, dest: str, size: int = 512, fps: float = 20, stroke_color: str | None = None,
                     width_scale: float = 1.0, background: str | None = "#FFFFFF", progress=None, cancel=None,
                     length: float | None = None, hold: float = 1.0, style: str = "plain") -> int:
    """GIF / WebP / MP4 of the drawing process (format from the file extension); returns the number
    of frames. The drawing takes ``length`` seconds (default: one drawn frame per 1/``fps`` s) plus
    ``hold`` seconds on the final sketch. ``progress(i, n)`` per drawn frame, ``progress(0, 0)`` while
    the file is encoded; ``cancel()`` returning True stops (InterruptedError) and removes the file.
    A transparent ``background`` (None) is kept in WebP; GIF and MP4 fall back to white."""
    import numpy as np

    def check():
        if cancel and cancel():
            raise InterruptedError("export cancelled")

    fmt = os.path.splitext(dest)[1].lower().lstrip(".")
    frames = animation_frames(run_dir)
    if not frames:
        raise FileNotFoundError("no intermediate SVGs (svg_logs) found")
    idx, durations = animation_plan(len(frames), length, fps, hold, fmt, size)

    def read(i):
        with open(frames[i], encoding="utf-8") as f:
            return f.read()

    ink = stroke_color is not None or _one_colour(read(len(frames) - 1))
    bg = QColor(background) if background else None
    if bg is not None and bg.alpha() == 0:
        bg = None
    if bg is None and fmt != "webp":  # only WebP can be transparent here
        bg = QColor("#FFFFFF")
    pal, alpha = _ink_palette(QColor(stroke_color or "#000000"), bg)
    lut = np.array(pal, dtype=np.uint8).reshape(-1, 3)

    def render(i):
        svg = read(i)
        if ink:
            return _ink(svg, size, width_scale, style)
        img = svg_to_qimage(stylize_svg(restyle_svg(svg, stroke_color, width_scale), style), size, bg)
        return qimage_to_pil(img).convert("RGBA" if bg is None else "RGB")

    try:
        if fmt == "mp4":
            import imageio.v2 as imageio

            last, frame = None, None
            with imageio.get_writer(dest, fps=MP4_FPS, codec="libx264", quality=8, macro_block_size=16) as w:
                for n, i in enumerate(idx):
                    check()
                    if i != last:
                        img = render(i)
                        frame = lut[img] if ink else np.asarray(img.convert("RGB"))
                        last = i
                    w.append_data(frame)
                    if progress:
                        progress(n + 1, len(idx))
                if progress:
                    progress(0, 0)
        else:
            images = []
            for n, i in enumerate(idx):
                check()
                img = render(i)
                if ink:
                    img = Image.fromarray(img, "P")
                    img.putpalette(pal)
                    if alpha is not None:
                        img.info["transparency"] = alpha
                images.append(img)
                if progress:
                    progress(n + 1, len(idx))
            check()
            if progress:
                progress(0, 0)
            opts = {"save_all": True, "append_images": images[1:], "duration": durations, "loop": 0}
            if fmt == "gif":
                images[0].save(dest, format="GIF", optimize=not ink, disposal=1, **opts)
            elif fmt == "webp":
                images[0].save(dest, format="WEBP", lossless=True, method=4,
                               background=(0, 0, 0, 0) if bg is None else (bg.red(), bg.green(), bg.blue(), 255),
                               **opts)
            else:
                raise ValueError(f"unknown animation format: {fmt}")
        check()
    except BaseException:
        try:
            os.remove(dest)
        except OSError:
            pass
        raise
    return len(idx)


def _render_svg(svg: str, width: int, height: int, background: QColor | None) -> QImage:
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    img = QImage(width, height, QImage.Format_ARGB32)
    img.fill(background if background is not None else QColor(0, 0, 0, 0))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p, QRectF(0, 0, width, height))
    p.end()
    return img


def _png_bytes(img: QImage) -> bytes:
    from PySide6.QtCore import QBuffer, QIODevice

    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def _nested_svg(svg: str, x: float, y: float, size: float) -> str:
    """An SVG document as a nested <svg> element placed at (x, y) with the given size."""
    svg = re.sub(r"<\?xml[^>]*\?>", "", svg).strip()
    head = re.match(r"<svg\b[^>]*>", svg)
    if not head:
        return ""
    view = re.search(r'viewBox="([^"]+)"', head.group(0))
    if view:
        box = view.group(1)
    else:
        w = re.search(r'width="([\d.]+)', head.group(0))
        h = re.search(r'height="([\d.]+)', head.group(0))
        box = f"0 0 {w.group(1) if w else 224} {h.group(1) if h else 224}"
    inner = svg[head.end():svg.rfind("</svg>")]
    return (f'<svg x="{x:g}" y="{y:g}" width="{size:g}" height="{size:g}" viewBox="{box}">'
            f"{inner}</svg>")


def matrix_sheet_svg(cells: dict[int, str], cell: int = 224, gap: int = 16, text_color: str = "#555555",
                     background: str | None = "#FFFFFF") -> str:
    """Overview of a SceneSketch matrix: one column per fidelity layer, one row per simplicity level."""
    layers = sorted({c // 100 for c in cells})
    levels = max(c % 100 for c in cells) + 1
    side, head = 70, 34
    width = side + len(layers) * (cell + gap) + gap
    height = head + levels * (cell + gap) + gap
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="{width}" height="{height}" '
             f'viewBox="0 0 {width} {height}">']
    if background:
        parts.append(f'<rect width="100%" height="100%" fill="{background}"/>')
    font = f'font-family="sans-serif" font-size="16" fill="{text_color}"'
    for col, layer in enumerate(layers):
        x = side + gap + col * (cell + gap)
        parts.append(f'<text x="{x + cell / 2:g}" y="{head - 10}" text-anchor="middle" {font}>L{layer}</text>')
    for row in range(levels):
        y = head + gap + row * (cell + gap)
        parts.append(f'<text x="{side - 8}" y="{y + cell / 2 + 6:g}" text-anchor="end" {font}>{row}</text>')
    for c, svg in cells.items():
        col, row = layers.index(c // 100), c % 100
        parts.append(_nested_svg(svg, side + gap + col * (cell + gap), head + gap + row * (cell + gap), cell))
    parts.append("</svg>")
    return "\n".join(parts)


def export_matrix_zip(job_dir: str, dest: str, size: int = 1024, stroke_color: str | None = None,
                      width_scale: float = 1.0, background: str | None = "#FFFFFF", progress=None,
                      cancel=None, style: str = "plain") -> int:
    """SceneSketch: every sketch of the matrix as SVG and PNG plus the overview sheet (matrix.svg /
    matrix.png) in one ZIP file. Returns the number of sketches."""
    import json
    import zipfile

    with open(os.path.join(job_dir, "job.json"), encoding="utf-8") as f:
        summary = json.load(f)
    cells = {}
    for r in summary.get("runs", []):
        path = jobs.sketch_file(r.get("run_dir", ""), r.get("best_svg", ""))
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                cells[int(r["seed"])] = stylize_svg(restyle_svg(f.read(), stroke_color, width_scale), style)
    if not cells:
        raise FileNotFoundError("no sketches in this job")
    bg = QColor(background) if background else None
    try:
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            for n, (c, svg) in enumerate(sorted(cells.items())):
                if cancel and cancel():
                    raise InterruptedError("export cancelled")
                name = f"L{c // 100}_level{c % 100}"
                z.writestr(f"{name}.svg", restyle_svg(svg, None, 1.0, background))
                z.writestr(f"{name}.png", _png_bytes(svg_to_qimage(svg, size, bg)))
                if progress:
                    progress(n + 1, len(cells))
            if progress:
                progress(0, 0)
            sheet = matrix_sheet_svg(cells, background=background)
            z.writestr("matrix.svg", sheet)
            w, h = (int(v) for v in re.search(r'width="(\d+)" height="(\d+)"', sheet).groups())
            scale = max(1.0, min(4.0, size / 224))  # cells of the sheet about as large as the PNGs
            z.writestr("matrix.png", _png_bytes(_render_svg(sheet, int(w * scale), int(h * scale), bg)))
    except BaseException:
        try:
            os.remove(dest)
        except OSError:
            pass
        raise
    return len(cells)


BATCH_FORMATS = ("svg", "svg1", "png")


def _unique(path: str) -> str:
    base, ext = os.path.splitext(path)
    n, out = 2, path
    while os.path.exists(out):
        out = f"{base}_{n}{ext}"
        n += 1
    return out


def export_batch(items: list[tuple[str, dict]], folder: str, fmt: str = "svg", size: int = 1024,
                 stroke_color: str | None = None, width_scale: float = 1.0, background: str | None = None,
                 style: str = "plain", progress=None, cancel=None) -> int:
    """Export the best sketch (touched up, if it was) of several jobs into ``folder`` as
    ``<image>_<method>.<ext>``; returns the number of files written."""
    os.makedirs(folder, exist_ok=True)
    written = 0
    for n, (job_dir, summary) in enumerate(items):
        if cancel and cancel():
            raise InterruptedError("export cancelled")
        src = jobs.best_sketch(summary)
        if not src or not os.path.isfile(src):
            continue
        stem = os.path.splitext(os.path.basename(summary.get("target") or job_dir))[0]
        method = summary.get("method") or "clipasso"
        suffix = "_1layer" if fmt == "svg1" else ""
        ext = "png" if fmt == "png" else "svg"
        dest = _unique(os.path.join(folder, f"{stem}_{method}{suffix}.{ext}"))
        if fmt == "png":
            export_png(src, dest, size, stroke_color, width_scale, background, style)  # None: transparent
        elif fmt == "svg1":
            export_single_layer_svg(src, dest, stroke_color, width_scale)
        else:
            export_svg(src, dest, stroke_color, width_scale, background, style)
        written += 1
        if progress:
            progress(n + 1, len(items))
    return written


def make_transparent_background(color: QColor) -> bool:
    return color.alpha() == 0 or color == Qt.transparent
