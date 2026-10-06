"""Export of results: restyled SVG, PNG at any size, GIF / MP4 of the drawing process."""

from __future__ import annotations

import glob
import json
import math
import os
import re
import xml.etree.ElementTree as ET

from PIL import Image
from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from ..engine import framing, jobs
from ..engine.errors import UserError
from . import paper as paper_mod
from .brush import RECOLOURING, stylize_svg

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


def _dims(renderer: QSvgRenderer, size: int) -> tuple[int, int]:
    box = renderer.viewBoxF()
    if box.width() <= 0 or box.height() <= 0:
        return size, size
    aspect = box.width() / box.height()
    return (size, max(1, round(size / aspect))) if aspect >= 1 else (max(1, round(size * aspect)), size)


def svg_dims(svg: str, size: int) -> tuple[int, int]:
    """Pixel size of a sketch rendered with its longer side ``size`` (in the shape of its viewBox)."""
    return _dims(QSvgRenderer(QByteArray(svg.encode("utf-8"))), size)


def _colour_name(background) -> str | None:
    """A background (QColor, colour name or None) as "#rrggbb"; None when it is transparent or not given."""
    if background is None:
        return None
    c = background if isinstance(background, QColor) else QColor(background)
    return c.name() if c.isValid() and c.alpha() > 0 else None


def svg_to_qimage(svg: str, size: int, background: QColor | None, canvas: tuple[int, int] | None = None,
                  paper: dict | None = None, base: QImage | None = None) -> QImage:
    """The sketch with its longer side ``size`` px; ``canvas``: a larger image it is centred on. ``paper``: drawn
    on that paper (in the ``background`` colour); ``base``: on a copy of this picture of the final size."""
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    w, h = _dims(renderer, size)
    cw, ch = canvas or (w, h)
    if base is None and paper_mod.normalize(paper) is not None:
        base = paper_mod.qimage(paper, cw, ch, _colour_name(background))
    if base is not None and (base.width(), base.height()) == (cw, ch):
        img = base.convertToFormat(QImage.Format_ARGB32)  # (a copy)
    else:
        img = QImage(cw, ch, QImage.Format_ARGB32)
        img.fill(background if background is not None else QColor(0, 0, 0, 0))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p, QRectF((cw - w) / 2, (ch - h) / 2, w, h))
    p.end()
    return img


def run_dir_of(svg_path: str) -> str:
    """The run folder a sketch file belongs to (also for the ``<run>_best.svg`` copy in the job folder)."""
    folder = os.path.dirname(os.path.abspath(svg_path))
    if os.path.isfile(os.path.join(folder, "config.json")):
        return folder
    summary = jobs.job_summary(folder) or {}
    for r in summary.get("runs", []):
        if r.get("run_name") == summary.get("best_run") and r.get("run_dir"):
            return r["run_dir"]
    return folder


def framing_for(svg_path: str, frame: str = "square", margin: float = framing.DEFAULT_MARGIN,
                svg: str | None = None):
    """The export frame of a sketch: "square" (None: as drawn), "photo" (the shape of the original photo;
    None when it is not known) or "content" (cropped to the strokes with ``margin``)."""
    if frame not in ("photo", "content"):
        return None
    if svg is None:
        with open(svg_path, encoding="utf-8") as f:
            svg = f.read()
    known = framing.run_frame(run_dir_of(svg_path)) if frame == "photo" else None
    return framing.make_framing(svg, frame, known, margin)


def _framed(svg: str, fr) -> str:
    return fr.apply(svg) if fr is not None else svg


def qimage_to_pil(img: QImage) -> Image.Image:
    img = img.convertToFormat(QImage.Format_RGBA8888)
    w, h = img.width(), img.height()
    data = bytes(img.constBits())[: w * h * 4]
    return Image.frombuffer("RGBA", (w, h), data, "raw", "RGBA", 0, 1).copy()


def export_svg(src_svg: str, dest: str, stroke_color: str | None = None, width_scale: float = 1.0,
               background: str | None = None, style: str = "plain", frame: str = "square",
               margin: float = framing.DEFAULT_MARGIN, paper: dict | None = None, svg: str | None = None) -> None:
    """``svg``: the sketch to write instead of the file's (framed like the file, e.g. its layers)."""
    if svg is None:
        with open(src_svg, encoding="utf-8") as f:
            svg = f.read()
    fr = framing_for(src_svg, frame, margin, svg)
    out = stylize_svg(_framed(restyle_svg(svg, stroke_color, width_scale, background), fr), style)
    with open(dest, "w", encoding="utf-8") as f:
        f.write(paper_mod.svg_with_paper(out, paper, background))


def export_layered_svg(src_svg: str, dest: str, stroke_color: str | None = None, width_scale: float = 1.0,
                       background: str | None = None, style: str = "plain", frame: str = "square",
                       margin: float = framing.DEFAULT_MARGIN, paper: dict | None = None) -> None:
    """A SceneSketch cell as an SVG with two layers, "Background" and "Object" (gui/scene_layers.py)."""
    from . import scene_layers
    from .i18n import tr

    with open(src_svg, encoding="utf-8") as f:
        svg = f.read()
    svg = scene_layers.layered(svg, run_dir_of(src_svg), (tr("ui.layer.background"), tr("ui.layer.object")))
    export_svg(src_svg, dest, stroke_color, width_scale, background, style, frame, margin, paper, svg=svg)


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
                            width_scale: float = 1.0, frame: str = "square",
                            margin: float = framing.DEFAULT_MARGIN) -> None:
    with open(src_svg, encoding="utf-8") as f:
        svg = f.read()
    with open(dest, "w", encoding="utf-8") as f:
        f.write(single_layer_svg(_framed(svg, framing_for(src_svg, frame, margin, svg)), stroke_color, width_scale))


def export_png(src_svg: str, dest: str, size: int = 1024, stroke_color: str | None = None,
               width_scale: float = 1.0, background: str | None = "#FFFFFF", style: str = "plain",
               frame: str = "square", margin: float = framing.DEFAULT_MARGIN, paper: dict | None = None) -> None:
    """PNG with its longer side ``size`` px (square unless ``frame`` gives it another shape)."""
    with open(src_svg, encoding="utf-8") as f:
        raw = f.read()
    svg = stylize_svg(_framed(restyle_svg(raw, stroke_color, width_scale), framing_for(src_svg, frame, margin, raw)),
                      style)
    bg = QColor(background) if background else None
    svg_to_qimage(svg, size, bg, paper=paper).save(dest)


PDF_WIDTH_CM = 15.0


PDF_PAPER_DPI = 200  # the paper texture under the vector strokes of a PDF
PDF_PAPER_MAX = 3000


def export_pdf(src_svg: str, dest: str, width_cm: float = PDF_WIDTH_CM, stroke_color: str | None = None,
               width_scale: float = 1.0, background: str | None = None, style: str = "plain",
               frame: str = "square", margin: float = framing.DEFAULT_MARGIN, paper: dict | None = None) -> None:
    """Vector PDF of the sketch (one page in the sketch's aspect ratio, ``width_cm`` wide) – for printing."""
    from PySide6.QtCore import QMarginsF, QSizeF
    from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter

    with open(src_svg, encoding="utf-8") as f:
        raw = f.read()
    svg = stylize_svg(_framed(restyle_svg(raw, stroke_color, width_scale), framing_for(src_svg, frame, margin, raw)),
                      style)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    box = renderer.viewBoxF()
    aspect = box.height() / box.width() if box.width() > 0 and box.height() > 0 else 1.0
    w_mm = max(float(width_cm), 1.0) * 10.0
    size = QPageSize(QSizeF(w_mm, w_mm * aspect), QPageSize.Unit.Millimeter, "Sketch",
                     QPageSize.SizeMatchPolicy.ExactMatch)
    writer = QPdfWriter(dest)
    writer.setPageLayout(QPageLayout(size, QPageLayout.Orientation.Portrait, QMarginsF(0, 0, 0, 0)))
    writer.setResolution(1200)
    writer.setCreator("CLIPasso Studio")
    writer.setTitle(os.path.splitext(os.path.basename(dest))[0])
    p = QPainter(writer)
    rect = QRectF(0, 0, writer.width(), writer.height())
    if paper_mod.normalize(paper) is not None:
        scale = min(PDF_PAPER_DPI / 25.4, PDF_PAPER_MAX / max(w_mm, w_mm * aspect))
        p.drawImage(rect, paper_mod.qimage(paper, max(1, round(w_mm * scale)), max(1, round(w_mm * aspect * scale)),
                                           background))
    elif background:
        p.fillRect(rect, QColor(background))
    renderer.render(p, rect)
    p.end()


CLIPBOARD_MARK = "application/x-clipasso-studio"  # recognises our own clipboard content


def sketch_mime(svg_path: str, size: int = 1024, stroke_color: str | None = None, width_scale: float = 1.0,
                background: str | None = "#FFFFFF", style: str = "plain", frame: str = "square",
                margin: float = framing.DEFAULT_MARGIN, paper: dict | None = None):
    """Clipboard content of a sketch: a PNG image and the SVG (``image/svg+xml``). No plain text –
    word processors would paste the SVG code instead of the picture."""
    from PySide6.QtCore import QMimeData

    with open(svg_path, encoding="utf-8") as f:
        raw = f.read()
    svg = stylize_svg(_framed(restyle_svg(raw, stroke_color, width_scale), framing_for(svg_path, frame, margin, raw)),
                      style)
    data = QMimeData()
    data.setImageData(svg_to_qimage(svg, size, QColor(background) if background else None, paper=paper))
    with_bg = stylize_svg(restyle_svg(svg, None, 1.0, background), "plain") if background else svg
    with_bg = paper_mod.svg_with_paper(with_bg, paper, background)
    data.setData("image/svg+xml", QByteArray(with_bg.encode("utf-8")))
    data.setData(CLIPBOARD_MARK, QByteArray(b"1"))
    return data


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
MAX_FRAMES = 5000  # e.g. every iteration of a CLIPasso sketch (save step 1)
MAX_FRAME_BYTES = 800_000_000  # the drawn frames wait in memory (1 byte per pixel) until they are encoded
INK_LEVELS = 8  # palette steps from the background to the stroke colour (anti-aliased edges)
_BLACK = {"#000", "#000000", "black", "rgb(0,0,0)"}


def every_step_length(n: int, fmt: str = "gif") -> float:
    """Seconds of a "drawing process" animation that shows each of its ``n`` saved steps once (as fast
    as the format allows: 50 frames a second for GIF / WebP, 30 for MP4)."""
    per_frame = 1.0 / MP4_FPS if fmt == "mp4" else MIN_FRAME_MS / 1000
    return round(max(n, 1) * per_frame + 0.049, 1)


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


def _ink(svg: str, size: int, width_scale: float, style: str = "plain", canvas: tuple[int, int] | None = None):
    """Rendered strokes as palette steps 0 (background) .. INK_LEVELS - 1 (full stroke colour)."""
    import numpy as np

    img = svg_to_qimage(stylize_svg(restyle_svg(svg, "#000000", width_scale), style), size, QColor("#FFFFFF"),
                        canvas)
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
                     length: float | None = None, hold: float = 1.0, style: str = "plain", frame: str = "square",
                     margin: float = framing.DEFAULT_MARGIN, paper: dict | None = None) -> int:
    """GIF / WebP / MP4 of the drawing process (format from the file extension); returns the number
    of frames. The drawing takes ``length`` seconds (default: one drawn frame per 1/``fps`` s) plus
    ``hold`` seconds on the final sketch. ``progress(i, n)`` per drawn frame, ``progress(0, 0)`` while
    the file is encoded; ``cancel()`` returning True stops (InterruptedError) and removes the file.
    A transparent ``background`` (None) is kept in WebP; GIF and MP4 fall back to white."""
    frames = animation_frames(run_dir)
    if not frames:
        raise UserError("export_no_logs", "no intermediate SVGs (svg_logs) found")
    final = jobs.sketch_file(run_dir)
    fr = framing_for(final if os.path.isfile(final) else frames[-1], frame, margin)  # the same for every frame

    def read(i):
        with open(frames[i], encoding="utf-8") as f:
            return _framed(f.read(), fr)

    return _encode(read, len(frames), dest, size, fps, stroke_color, width_scale, background, progress, cancel,
                   length, hold, style, paper)


def _encode(read, n: int, dest: str, size: int, fps: float, stroke_color: str | None, width_scale: float,
            background: str | None, progress, cancel, length: float | None, hold: float, style: str,
            paper: dict | None = None) -> int:
    """Render the drawn frames ``read(0 .. n-1)`` (SVG text) and encode them (see export_animation)."""
    import numpy as np

    def check():
        if cancel and cancel():
            raise InterruptedError("export cancelled")

    fmt = os.path.splitext(dest)[1].lower().lstrip(".")
    idx, durations = animation_plan(n, length, fps, hold, fmt, size)
    paper = paper_mod.normalize(paper)
    # one stroke colour on a plain background: palette steps instead of full colour frames
    ink = (stroke_color is not None or _one_colour(read(n - 1))) and style not in RECOLOURING and paper is None
    bg = QColor(background) if background else None
    if bg is not None and bg.alpha() == 0:
        bg = None
    if bg is None and fmt != "webp":  # only WebP can be transparent here
        bg = QColor("#FFFFFF")
    pal, alpha = _ink_palette(QColor(stroke_color or "#000000"), bg)
    lut = np.array(pal, dtype=np.uint8).reshape(-1, 3)
    w, h = svg_dims(read(n - 1), size)
    canvas = (w + (-w) % 16, h + (-h) % 16) if fmt == "mp4" else None  # the video codec wants multiples of 16
    # (the paper's colour: the background asked for – not the white that stands in for transparency in GIF / MP4)
    base = paper_mod.qimage(paper, *(canvas or (w, h)), _colour_name(background)) if paper is not None else None

    def render(i):
        svg = read(i)
        if ink:
            return _ink(svg, size, width_scale, style, canvas)
        img = svg_to_qimage(stylize_svg(restyle_svg(svg, stroke_color, width_scale), style), size, bg, canvas,
                            base=base)
        return qimage_to_pil(img).convert("RGBA" if bg is None else "RGB")

    try:
        if fmt == "mp4":
            import imageio.v2 as imageio

            last, frame = None, None
            with imageio.get_writer(dest, fps=MP4_FPS, codec="libx264", quality=8, macro_block_size=16) as w:
                for k, i in enumerate(idx):
                    check()
                    if i != last:
                        img = render(i)
                        frame = lut[img] if ink else np.asarray(img.convert("RGB"))
                        last = i
                    w.append_data(frame)
                    if progress:
                        progress(k + 1, len(idx))
                if progress:
                    progress(0, 0)
        else:
            images = []
            for k, i in enumerate(idx):
                check()
                img = render(i)
                if ink:
                    img = Image.fromarray(img, "P")
                    img.putpalette(pal)
                    if alpha is not None:
                        img.info["transparency"] = alpha
                images.append(img)
                if progress:
                    progress(k + 1, len(idx))
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


# --------------------------------------------------------------- stroke by stroke
DRAW_STEPS_PER_SECOND = 50  # drawn frames per second of the stroke-by-stroke timeline (thinned out later)
PEN_LIFT = 0.25  # time between two strokes, as a share of the mean stroke length


def run_method(run_dir: str) -> str:
    try:
        with open(os.path.join(run_dir, "config.json"), encoding="utf-8") as f:
            return str(json.load(f).get("method") or "clipasso")
    except (OSError, ValueError):
        return "clipasso"


def _length(pts) -> float:
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))


class Drawing:
    """The finished strokes of a sketch drawn one after another, like by hand: ``frame(t)`` is the
    SVG at progress ``t`` (0..1) – the strokes before it complete, the current one up to its share."""

    def __init__(self, svg: str, keep_order: bool = False):
        from .brush import sample

        root = ET.fromstring(svg)
        ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
        self.head = '<svg xmlns="http://www.w3.org/2000/svg" ' + " ".join(
            f'{k}="{v}"' for k, v in root.attrib.items() if not k.startswith("{")) + ">"
        strokes = []
        for el in root.iter(f"{ns}path"):
            subs = sample(el.get("d") or "")
            if not subs:
                continue
            attrs = {k: v for k, v in el.attrib.items() if k != "d" and not k.startswith("{")}
            whole = ET.tostring(el, encoding="unicode").replace(f' xmlns="{ns[1:-1]}"', "") if ns else \
                ET.tostring(el, encoding="unicode")
            strokes.append({"subs": subs, "attrs": attrs, "xml": whole, "len": sum(_length(p) for p in subs)})
        self.strokes = strokes if keep_order else self._route(strokes)
        mean = sum(st["len"] for st in self.strokes) / max(len(self.strokes), 1)
        lift = PEN_LIFT * mean
        self.spans, t = [], 0.0
        for st in self.strokes:
            self.spans.append((t, t + st["len"]))
            t += st["len"] + lift
        self.total = max(t - lift, 1e-9)
        try:
            from .strokes import view_box

            width = view_box(svg)[2]
        except (ValueError, ET.ParseError):
            width = 224.0
        # a sketch of one line (one-line mode): its length in canvas widths, for the duration of the drawing
        self.line = self.total / max(width, 1e-9) if len(self.strokes) == 1 else 0.0

    @staticmethod
    def _route(strokes: list[dict]) -> list[dict]:
        """Greedy route: the longest stroke first, then always the nearest stroke end (drawn from
        that end), so the "hand" moves naturally."""
        if not strokes:
            return []
        left = list(strokes)
        first = max(left, key=lambda st: st["len"])
        left.remove(first)
        route = [first]
        pen = first["subs"][-1][-1]
        while left:
            best, best_d, rev = None, None, False
            for st in left:
                a, b = st["subs"][0][0], st["subs"][-1][-1]
                for d, r in ((math.hypot(a[0] - pen[0], a[1] - pen[1]), False),
                             (math.hypot(b[0] - pen[0], b[1] - pen[1]), True)):
                    if best_d is None or d < best_d:
                        best, best_d, rev = st, d, r
            left.remove(best)
            if rev:
                best = {**best, "subs": [list(reversed(p)) for p in reversed(best["subs"])]}
            route.append(best)
            pen = best["subs"][-1][-1]
        return route

    def centreline(self, i: int) -> str:
        """Path data of stroke ``i`` in drawing direction (sampled)."""
        return " ".join("M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in pts) for pts in self.strokes[i]["subs"])

    def _partial(self, st: dict, dist: float) -> str:
        parts, left = [], dist
        for pts in st["subs"]:
            if left <= 0:
                break
            out = [pts[0]]
            for a, b in zip(pts, pts[1:]):
                seg = math.hypot(b[0] - a[0], b[1] - a[1])
                if seg >= left:
                    f = left / seg if seg else 0.0
                    out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
                    left = 0
                    break
                out.append(b)
                left -= seg
            if len(out) >= 2:
                parts.append("M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in out))
        if not parts:
            return ""
        attrs = " ".join(f'{k}="{v}"' for k, v in st["attrs"].items())
        return f'<path d="{" ".join(parts)}" {attrs} />'

    def frame(self, t: float) -> str:
        now = max(0.0, min(1.0, t)) * self.total
        body = []
        for st, (a, b) in zip(self.strokes, self.spans):
            if now >= b:
                body.append(st["xml"])
            elif now > a:
                body.append(self._partial(st, now - a))
                break
            else:
                break
        return self.head + "".join(body) + "</svg>"


def default_drawing_length(strokes: int, line: float = 0.0) -> float:
    """Seconds for a stroke-by-stroke drawing: about a quarter second per stroke, 2 – 12 s; a sketch of a
    single line (``line``: its length in canvas widths) about 0.6 s per canvas width."""
    seconds = line * 0.6 if strokes == 1 and line > 0 else strokes * 0.25
    return round(min(12.0, max(2.0, seconds)) * 2) / 2


def drawing_length(svg_path: str) -> float:
    """The default duration of the stroke-by-stroke drawing of a sketch file."""
    try:
        with open(svg_path, encoding="utf-8") as f:
            drawing = Drawing(f.read(), keep_order=True)
    except (OSError, ET.ParseError, ValueError):
        return default_drawing_length(0)
    return default_drawing_length(len(drawing.strokes), drawing.line)


def export_drawing(svg_path: str, dest: str, size: int = 512, stroke_color: str | None = None,
                   width_scale: float = 1.0, background: str | None = "#FFFFFF", progress=None, cancel=None,
                   length: float | None = None, hold: float = 1.0, style: str = "plain",
                   keep_order: bool | None = None, frame: str = "square",
                   margin: float = framing.DEFAULT_MARGIN, paper: dict | None = None) -> int:
    """GIF / WebP / MP4 in which the finished sketch (with eraser edits) is drawn stroke by stroke.
    ``keep_order``: draw in the order of the SVG (ControlSketch sorts its strokes outline first) –
    by default for ControlSketch runs, otherwise along a short route."""
    with open(svg_path, encoding="utf-8") as f:
        svg = f.read()
    svg = _framed(svg, framing_for(svg_path, frame, margin, svg))
    if keep_order is None:
        keep_order = run_method(os.path.dirname(svg_path)) == "controlsketch"
    drawing = Drawing(svg, keep_order)
    if not drawing.strokes:
        raise UserError("export_no_strokes", "the sketch has no strokes")
    length = default_drawing_length(len(drawing.strokes), drawing.line) if length is None else length
    n = max(2, round(length * DRAW_STEPS_PER_SECOND))
    return _encode(lambda i: drawing.frame((i + 1) / n), n, dest, size, n / length, stroke_color, width_scale,
                   background, progress, cancel, length, hold, style, paper)


def animated_svg(svg: str, length: float | None = None, hold: float = 1.0, stroke_color: str | None = None,
                 width_scale: float = 1.0, background: str | None = None, style: str = "plain",
                 keep_order: bool = False, paper: dict | None = None) -> str:
    """An SVG that draws itself in the browser (CSS animation, repeating): every stroke – in any
    brush style – is uncovered by a mask whose centre line grows along the stroke."""
    drawing = Drawing(svg, keep_order)
    n = len(drawing.strokes)
    length = default_drawing_length(n, drawing.line) if length is None else max(float(length), 0.1)
    cycle = length + max(float(hold), 0.0)
    styled = []
    for st in drawing.strokes:
        one = drawing.head + st["xml"] + "</svg>"
        one = stylize_svg(restyle_svg(one, stroke_color, width_scale), style)
        root = ET.fromstring(one)
        styled.append("".join(ET.tostring(el, encoding="unicode") for el in root
                              if not el.tag.endswith("rect")))
    css, defs, body = [], [], []
    for i, (st, (a, b)) in enumerate(zip(drawing.strokes, drawing.spans)):
        start = a / drawing.total * length / cycle * 100
        end = b / drawing.total * length / cycle * 100
        css.append(f"@keyframes d{i}{{0%,{start:.3f}%{{stroke-dashoffset:1}}{end:.3f}%,100%{{stroke-dashoffset:0}}}}"
                   f".d{i}{{animation:d{i} {cycle:.3f}s linear infinite}}")
        try:
            width = float(st["attrs"].get("stroke-width", "1")) * width_scale
        except ValueError:
            width = width_scale
        defs.append(f'<mask id="m{i}" maskUnits="userSpaceOnUse"><path class="d{i}" d="{drawing.centreline(i)}" '
                    f'fill="none" stroke="#fff" stroke-width="{4 * width + 2:.3g}" stroke-linecap="round" '
                    f'stroke-linejoin="round" pathLength="1" stroke-dasharray="1 1" stroke-dashoffset="1"/></mask>')
        body.append(f'<g mask="url(#m{i})">{styled[i]}</g>')
    bg = f'<rect width="100%" height="100%" fill="{background}"/>' if background else ""
    out = (drawing.head + "<style>" + "".join(css) + "</style><defs>" + "".join(defs) + "</defs>" + bg
           + "".join(body) + "</svg>")
    out = re.sub(r' xmlns(:ns\d+)?="http://www.w3.org/2000/svg"', "", out).replace(
        "<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1)
    return paper_mod.svg_with_paper(out, paper, background)


def export_animated_svg(svg_path: str, dest: str, length: float | None = None, hold: float = 1.0,
                        stroke_color: str | None = None, width_scale: float = 1.0, background: str | None = None,
                        style: str = "plain", keep_order: bool | None = None, frame: str = "square",
                        margin: float = framing.DEFAULT_MARGIN, paper: dict | None = None) -> None:
    with open(svg_path, encoding="utf-8") as f:
        svg = f.read()
    svg = _framed(svg, framing_for(svg_path, frame, margin, svg))
    if keep_order is None:
        keep_order = run_method(os.path.dirname(svg_path)) == "controlsketch"
    with open(dest, "w", encoding="utf-8") as f:
        f.write(animated_svg(svg, length, hold, stroke_color, width_scale, background, style, keep_order, paper))


# --------------------------------------------------------------- Lottie and a web page
LOTTIE_FPS = 30
LOTTIE_SIZE = 512  # px: the longer side of the Lottie composition


def _lottie_rgb(color: str) -> list[float]:
    c = QColor(color)
    if not c.isValid():
        c = QColor("#000000")
    return [round(c.redF(), 4), round(c.greenF(), 4), round(c.blueF(), 4), 1]


def _lottie_static(value) -> dict:
    return {"a": 0, "k": value}


def _lottie_transform(shape_group: bool = False) -> dict:
    if shape_group:
        return {"ty": "tr", "p": _lottie_static([0, 0]), "a": _lottie_static([0, 0]), "s": _lottie_static([100, 100]),
                "r": _lottie_static(0), "o": _lottie_static(100), "sk": _lottie_static(0), "sa": _lottie_static(0)}
    return {"o": _lottie_static(100), "r": _lottie_static(0), "p": _lottie_static([0, 0, 0]),
            "a": _lottie_static([0, 0, 0]), "s": _lottie_static([100, 100, 100])}


def lottie_paths(d: str, x0: float = 0.0, y0: float = 0.0, scale: float = 1.0) -> list[dict]:
    """The sub-paths of SVG path data as Lottie shapes: vertices (moved by -x0, -y0 and scaled) with their in and
    out tangents relative to them; quadratic curves become cubic ones."""
    from ..engine.svg_path import parse_path_d

    def pt(p):
        return [(float(p[0]) - x0) * scale, (float(p[1]) - y0) * scale]

    out = []
    for segs, closed in parse_path_d(d):
        v, ins, outs = [], [], []
        for seg in segs:
            pts = [pt(p) for p in seg]
            p0, p3 = pts[0], pts[-1]
            if len(pts) == 2:  # line
                c1, c2 = p0, p3
            elif len(pts) == 3:  # quadratic
                q = pts[1]
                c1 = [p0[0] + 2 / 3 * (q[0] - p0[0]), p0[1] + 2 / 3 * (q[1] - p0[1])]
                c2 = [p3[0] + 2 / 3 * (q[0] - p3[0]), p3[1] + 2 / 3 * (q[1] - p3[1])]
            else:
                c1, c2 = pts[1], pts[2]
            if not v:
                v.append(p0)
                ins.append([0, 0])
                outs.append([0, 0])
            outs[-1] = [c1[0] - p0[0], c1[1] - p0[1]]
            v.append(p3)
            ins.append([c2[0] - p3[0], c2[1] - p3[1]])
            outs.append([0, 0])
        if closed and len(v) > 2 and abs(v[0][0] - v[-1][0]) < 1e-6 and abs(v[0][1] - v[-1][1]) < 1e-6:
            ins[0] = ins.pop()
            v.pop()
            outs.pop()
        if len(v) >= 2:
            rnd = [[[round(c, 3) for c in p] for p in arr] for arr in (ins, outs, v)]
            out.append({"ty": "sh", "ks": _lottie_static({"i": rnd[0], "o": rnd[1], "v": rnd[2], "c": bool(closed)})})
    return out


def _reversed_shape(shape: dict) -> dict:
    """The same Lottie path drawn from its other end."""
    k = shape["ks"]["k"]
    return {"ty": "sh", "ks": _lottie_static({"i": k["o"][::-1], "o": k["i"][::-1], "v": k["v"][::-1], "c": k["c"]})}


def lottie(svg: str, length: float | None = None, hold: float = 1.0, stroke_color: str | None = None,
           width_scale: float = 1.0, background: str | None = None, keep_order: bool = False,
           paper: dict | None = None, name: str = "sketch", size: int = LOTTIE_SIZE) -> dict:
    """A Lottie animation (bodymovin JSON) that draws the sketch stroke by stroke like :func:`animated_svg`:
    one shape layer per stroke whose trim path grows along it. Plain strokes (Lottie has no brush styles);
    the background colour or the paper (an embedded picture) below them."""
    from .strokes import view_box

    drawing = Drawing(svg, keep_order)
    n = len(drawing.strokes)
    length = default_drawing_length(n, drawing.line) if length is None else max(float(length), 0.1)
    total = length + max(float(hold), 0.0)
    op = max(1, round(total * LOTTIE_FPS))
    x0, y0, vw, vh = view_box(svg)
    scale = size / max(vw, vh, 1e-9)
    w, h = max(1, round(vw * scale)), max(1, round(vh * scale))
    layers, assets = [], []
    for i, (st, (a, b)) in enumerate(zip(drawing.strokes, drawing.spans)):
        attrs = st["attrs"]
        m = re.search(r'\sd="([^"]*)"', st["xml"])
        shapes = lottie_paths(m.group(1) if m else drawing.centreline(i), x0, y0, scale)
        if not shapes:
            continue
        first = shapes[0]["ks"]["k"]["v"][0]
        start = [(st["subs"][0][0][0] - x0) * scale, (st["subs"][0][0][1] - y0) * scale]
        last = shapes[-1]["ks"]["k"]["v"][-1]
        if math.dist(start, last) < math.dist(start, first) - 1e-6:  # the route draws this stroke backwards
            shapes = [_reversed_shape(sh) for sh in reversed(shapes)]
        try:
            width = float(attrs.get("stroke-width", "1")) * width_scale * scale
            opacity = float(attrs.get("stroke-opacity", "1")) * 100
        except ValueError:
            width, opacity = width_scale * scale, 100.0
        f0 = round(a / drawing.total * length * LOTTIE_FPS, 2)
        f1 = max(round(b / drawing.total * length * LOTTIE_FPS, 2), f0 + 0.5)
        trim_end = {"a": 1, "k": [{"t": f0, "s": [0], "i": {"x": [1], "y": [1]}, "o": {"x": [0], "y": [0]}},
                                  {"t": f1, "s": [100]}]}
        stroke = {"ty": "st", "c": _lottie_static(_lottie_rgb(stroke_color or attrs.get("stroke", "#000000"))),
                  "o": _lottie_static(round(opacity, 2)), "w": _lottie_static(round(width, 3)), "lc": 2, "lj": 2,
                  "ml": 4, "nm": "stroke"}
        trim = {"ty": "tm", "s": _lottie_static(0), "e": trim_end, "o": _lottie_static(0), "m": 2, "nm": "draw"}
        layers.append({"ddd": 0, "ind": i + 1, "ty": 4, "nm": f"stroke {i + 1}", "sr": 1, "ks": _lottie_transform(),
                       "ao": 0, "shapes": [{"ty": "gr", "nm": f"stroke {i + 1}",
                                            "it": shapes + [stroke, trim, _lottie_transform(True)]}],
                       "ip": 0, "op": op, "st": 0, "bm": 0})
    layers.reverse()  # the first layer is drawn on top: the later strokes over the earlier ones
    ind = len(drawing.strokes) + 1
    if paper_mod.normalize(paper) is not None:
        import base64
        import io

        buf = io.BytesIO()
        paper_mod.image(paper, w, h, background).save(buf, "JPEG", quality=88)
        assets.append({"id": "paper", "w": w, "h": h, "u": "", "e": 1,
                       "p": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")})
        layers.append({"ddd": 0, "ind": ind, "ty": 2, "nm": "paper", "refId": "paper", "sr": 1,
                       "ks": _lottie_transform(), "ao": 0, "ip": 0, "op": op, "st": 0, "bm": 0})
    elif background:
        layers.append({"ddd": 0, "ind": ind, "ty": 1, "nm": "background", "sc": QColor(background).name(),
                       "sw": w, "sh": h, "sr": 1, "ks": _lottie_transform(), "ao": 0, "ip": 0, "op": op, "st": 0,
                       "bm": 0})
    return {"v": "5.7.4", "fr": LOTTIE_FPS, "ip": 0, "op": op, "w": w, "h": h, "nm": name, "ddd": 0,
            "assets": assets, "layers": layers, "markers": []}


def export_lottie(svg_path: str, dest: str, length: float | None = None, hold: float = 1.0,
                  stroke_color: str | None = None, width_scale: float = 1.0, background: str | None = None,
                  keep_order: bool | None = None, frame: str = "square", margin: float = framing.DEFAULT_MARGIN,
                  paper: dict | None = None, size: int = LOTTIE_SIZE) -> None:
    """Lottie JSON (for web pages and apps: lottie-web, LottieFiles, After Effects / Bodymovin)."""
    with open(svg_path, encoding="utf-8") as f:
        svg = f.read()
    svg = _framed(svg, framing_for(svg_path, frame, margin, svg))
    if keep_order is None:
        keep_order = run_method(os.path.dirname(svg_path)) == "controlsketch"
    data = lottie(svg, length, hold, stroke_color, width_scale, background, keep_order, paper,
                  os.path.splitext(os.path.basename(dest))[0], size)
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))


def web_page(animated: str, title: str = "Sketch", background: str | None = None) -> str:
    """A web page of its own (no other files) that shows an SVG drawing itself, with a button to draw it again."""
    from html import escape

    bg = QColor(background).name() if background and QColor(background).isValid() else "#ffffff"
    dark = paper_mod.is_dark(bg)
    fg, btn = ("#e8e8e8", "rgba(255,255,255,.12)") if dark else ("#333333", "rgba(0,0,0,.06)")
    body = re.sub(r"<\?xml[^>]*\?>", "", animated).strip()
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>
html, body {{ margin: 0; height: 100%; background: {bg}; color: {fg}; font-family: system-ui, sans-serif; }}
body {{ display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; }}
main {{ width: min(92vw, 86vh); }}
main svg {{ display: block; width: 100%; height: auto; }}
button {{ border: 0; border-radius: 999px; padding: 8px 18px; background: {btn}; color: inherit; font: inherit;
         cursor: pointer; }}
</style>
</head>
<body>
<main>{body}</main>
<button type="button" onclick="const s = document.querySelector('main svg'); s.replaceWith(s.cloneNode(true));"
 title="Draw again">&#8635;</button>
</body>
</html>
"""


def export_web_page(svg_path: str, dest: str, length: float | None = None, hold: float = 1.0,
                    stroke_color: str | None = None, width_scale: float = 1.0, background: str | None = None,
                    style: str = "plain", keep_order: bool | None = None, frame: str = "square",
                    margin: float = framing.DEFAULT_MARGIN, paper: dict | None = None) -> None:
    """An HTML page with the sketch drawing itself (the animated SVG in any brush style)."""
    with open(svg_path, encoding="utf-8") as f:
        svg = f.read()
    svg = _framed(svg, framing_for(svg_path, frame, margin, svg))
    if keep_order is None:
        keep_order = run_method(os.path.dirname(svg_path)) == "controlsketch"
    animated = animated_svg(svg, length, hold, stroke_color, width_scale, background, style, keep_order, paper)
    page_bg = paper_mod.color_of(paper, background) if paper_mod.normalize(paper) is not None else background
    with open(dest, "w", encoding="utf-8") as f:
        f.write(web_page(animated, os.path.splitext(os.path.basename(dest))[0], page_bg))


def _render_svg(svg: str, width: int, height: int, background: QColor | None, paper: dict | None = None) -> QImage:
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if paper_mod.normalize(paper) is not None:
        img = paper_mod.qimage(paper, width, height, _colour_name(background))
    else:
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
    levels = sorted({c % 100 for c in cells})  # (only the computed ones: some may have been left out)
    side, head = 70, 34
    width = side + len(layers) * (cell + gap) + gap
    height = head + len(levels) * (cell + gap) + gap
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="{width}" height="{height}" '
             f'viewBox="0 0 {width} {height}">']
    if background:
        parts.append(f'<rect width="100%" height="100%" fill="{background}"/>')
    font = f'font-family="sans-serif" font-size="16" fill="{text_color}"'
    for col, layer in enumerate(layers):
        x = side + gap + col * (cell + gap)
        parts.append(f'<text x="{x + cell / 2:g}" y="{head - 10}" text-anchor="middle" {font}>L{layer}</text>')
    for row, level in enumerate(levels):
        y = head + gap + row * (cell + gap)
        parts.append(f'<text x="{side - 8}" y="{y + cell / 2 + 6:g}" text-anchor="end" {font}>{level}</text>')
    for c, svg in cells.items():
        col, row = layers.index(c // 100), levels.index(c % 100)
        parts.append(_nested_svg(svg, side + gap + col * (cell + gap), head + gap + row * (cell + gap), cell))
    parts.append("</svg>")
    return "\n".join(parts)


def export_matrix_zip(job_dir: str, dest: str, size: int = 1024, stroke_color: str | None = None,
                      width_scale: float = 1.0, background: str | None = "#FFFFFF", progress=None,
                      cancel=None, style: str = "plain", paper: dict | None = None) -> int:
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
        raise UserError("export_no_sketches", "no sketches in this job")
    bg = QColor(background) if background else None
    try:
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            for n, (c, svg) in enumerate(sorted(cells.items())):
                if cancel and cancel():
                    raise InterruptedError("export cancelled")
                name = f"L{c // 100}_level{c % 100}"
                z.writestr(f"{name}.svg", paper_mod.svg_with_paper(restyle_svg(svg, None, 1.0, background), paper,
                                                                   background))
                z.writestr(f"{name}.png", _png_bytes(svg_to_qimage(svg, size, bg, paper=paper)))
                if progress:
                    progress(n + 1, len(cells))
            if progress:
                progress(0, 0)
            sheet = matrix_sheet_svg(cells, background=background)
            z.writestr("matrix.svg", paper_mod.svg_with_paper(sheet, paper, background))
            w, h = (int(v) for v in re.search(r'width="(\d+)" height="(\d+)"', sheet).groups())
            scale = max(1.0, min(4.0, size / 224))  # cells of the sheet about as large as the PNGs
            z.writestr("matrix.png", _png_bytes(_render_svg(sheet, int(w * scale), int(h * scale), bg, paper)))
    except BaseException:
        try:
            os.remove(dest)
        except OSError:
            pass
        raise
    return len(cells)


BATCH_FORMATS = ("svg", "svg1", "png", "pdf")


def _unique(path: str) -> str:
    base, ext = os.path.splitext(path)
    n, out = 2, path
    while os.path.exists(out):
        out = f"{base}_{n}{ext}"
        n += 1
    return out


def export_batch(items: list[tuple[str, dict]], folder: str, fmt: str = "svg", size: int = 1024,
                 stroke_color: str | None = None, width_scale: float = 1.0, background: str | None = None,
                 style: str = "plain", progress=None, cancel=None, frame: str = "square",
                 margin: float = framing.DEFAULT_MARGIN, paper: dict | None = None) -> int:
    """Export the best sketch (touched up, if it was) of several jobs into ``folder`` as
    ``<image>_<method>.<ext>``; returns the number of files written. ``frame``: see :func:`framing_for`
    (a sketch whose photo shape is not known stays square)."""
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
        ext = fmt if fmt in ("png", "pdf") else "svg"
        dest = _unique(os.path.join(folder, f"{stem}_{method}{suffix}.{ext}"))
        shape = {"frame": frame, "margin": margin}
        if fmt == "png":  # (background None: transparent)
            export_png(src, dest, size, stroke_color, width_scale, background, style, **shape, paper=paper)
        elif fmt == "pdf":
            export_pdf(src, dest, PDF_WIDTH_CM, stroke_color, width_scale, background, style, **shape, paper=paper)
        elif fmt == "svg1":
            export_single_layer_svg(src, dest, stroke_color, width_scale, **shape)
        else:
            export_svg(src, dest, stroke_color, width_scale, background, style, **shape, paper=paper)
        written += 1
        if progress:
            progress(n + 1, len(items))
    return written


def make_transparent_background(color: QColor) -> bool:
    return color.alpha() == 0 or color == Qt.transparent
