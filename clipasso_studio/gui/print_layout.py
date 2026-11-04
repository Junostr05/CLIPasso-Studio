"""Print layout: sketches on pages (A5 … poster) – one per page or many as a contact sheet, with margins, a title,
a signature and captions, in a brush style and on a paper; as a multi-page PDF or straight to a printer
(QtPrintSupport). The same painting serves the PDF, the printer and the preview of the dialog."""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QByteArray, QMarginsF, QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter
from PySide6.QtSvg import QSvgRenderer

from ..engine import framing
from . import paper as paper_mod
from .brush import stylize_svg
from .export import _framed, framing_for, restyle_svg

PAGES = ("a5", "a4", "a3", "letter", "poster")
POSTER_MM = (500.0, 700.0)
PER_PAGE = (1, 2, 4, 6, 9, 12, 16, 20)
GRIDS = {1: (1, 1), 2: (1, 2), 4: (2, 2), 6: (2, 3), 9: (3, 3), 12: (3, 4), 16: (4, 4), 20: (4, 5)}  # (cols, rows)
GAP_MM = 6.0
PDF_DPI = 600


@dataclass
class Layout:
    page: str = "a4"
    landscape: bool = False
    margin_mm: float = 15.0
    per_page: int = 1
    title: str = ""
    signature: str = ""
    captions: bool = False
    stroke_color: str | None = None
    width_scale: float = 1.0
    background: str | None = None
    style: str = "plain"
    paper: dict | None = None
    frame: str = "square"
    frame_margin: float = framing.DEFAULT_MARGIN


def page_size(layout: Layout) -> QPageSize:
    if layout.page == "poster":
        return QPageSize(QSizeF(*POSTER_MM), QPageSize.Unit.Millimeter, "Poster 50 x 70 cm",
                         QPageSize.SizeMatchPolicy.ExactMatch)
    ids = {"a5": QPageSize.PageSizeId.A5, "a4": QPageSize.PageSizeId.A4, "a3": QPageSize.PageSizeId.A3,
           "letter": QPageSize.PageSizeId.Letter}
    return QPageSize(ids.get(layout.page, QPageSize.PageSizeId.A4))


def page_layout(layout: Layout) -> QPageLayout:
    orientation = QPageLayout.Orientation.Landscape if layout.landscape else QPageLayout.Orientation.Portrait
    return QPageLayout(page_size(layout), orientation, QMarginsF(0, 0, 0, 0))


def page_mm(layout: Layout) -> tuple[float, float]:
    """Width and height of the page in mm (turned for landscape)."""
    size = page_size(layout).size(QPageSize.Unit.Millimeter)
    w, h = size.width(), size.height()
    return (max(w, h), min(w, h)) if layout.landscape else (min(w, h), max(w, h))


def grid(per_page: int, landscape: bool = False) -> tuple[int, int]:
    """Columns and rows of a page with ``per_page`` sketches (more columns on a landscape page)."""
    cols, rows = GRIDS.get(per_page) or (math.ceil(math.sqrt(per_page)), math.ceil(per_page / math.ceil(
        math.sqrt(per_page))))
    return (rows, cols) if landscape and rows > cols else (cols, rows)


def page_count(n: int, layout: Layout) -> int:
    return max(1, math.ceil(n / max(layout.per_page, 1))) if n else 0


def _sketch(svg_path: str, layout: Layout) -> str:
    with open(svg_path, encoding="utf-8") as f:
        raw = f.read()
    framed = _framed(restyle_svg(raw, layout.stroke_color, layout.width_scale),
                     framing_for(svg_path, layout.frame, layout.frame_margin, raw))
    return stylize_svg(framed, layout.style)


def text_colour(layout: Layout) -> str:
    """The colour of the heading, footer and captions: light on a dark paper or background, else dark grey."""
    bg = paper_mod.color_of(layout.paper, layout.background) if paper_mod.normalize(layout.paper) else \
        (layout.background or "#FFFFFF")
    return "#E8E8E2" if paper_mod.is_dark(bg if bg != "transparent" else "#FFFFFF") else "#3A3A3A"


Box = tuple[float, float, float, float]  # x, y, width, height


@dataclass
class PageBoxes:
    """Where the parts of a page go, in the device's units (y downwards, the page at 0, 0): the heading and the
    footer (signature right, page number left) with their font sizes in px, and per sketch its caption (None
    without) and the sketch fitted to its shape (None when the sketch could not be read)."""

    title: Box | None
    title_px: int
    footer: Box | None
    small_px: int
    captions: list[Box | None]
    sketches: list[Box | None]


def page_boxes(width: float, height: float, layout: Layout, captions: list[str], aspects: list[float | None],
               pages: int = 1) -> PageBoxes:
    """The page's layout (as QRectF works it out): the margin, the heading on top, the footer below, the grid of
    cells in between (a gap between them on a contact sheet), a caption at the foot of a cell and the sketch
    (``aspects``: width / height of each) as large as it fits, centred. Sizes are given in mm of the page, so
    every device (PDF, printer, preview) gets the same picture."""
    w_mm, _h_mm = page_mm(layout)
    mm = width / w_mm
    m = layout.margin_mm * mm
    x, y, w, h = m, m, width - m - m, height - m - m  # QRectF.adjusted(m, m, -m, -m)
    title_px = max(1, round(min(9.0, w_mm / 24) * mm))
    title = None
    if layout.title:
        title = (x, y, w, title_px * 1.6)
        diff = title_px * 1.6 + 3 * mm  # (setTop: the bottom stays)
        y, h = y + diff, h - diff
    small = max(1, round(min(4.0, w_mm / 50) * mm))
    footer = None
    if layout.signature or pages > 1:
        footer = (x, y + h - small * 1.8, w, small * 1.8)
        h = (y + h - small * 1.8 - 3 * mm) - y  # (setBottom)
    cols, rows = grid(layout.per_page, layout.landscape)
    gap = GAP_MM * mm if layout.per_page > 1 else 0.0
    cell_w = (w - gap * (cols - 1)) / cols
    cell_h = (h - gap * (rows - 1)) / rows
    caption_boxes: list[Box | None] = []
    sketch_boxes: list[Box | None] = []
    for k, aspect in enumerate(aspects[: cols * rows]):
        c, r = k % cols, k // cols
        cx, cy, cw, ch = x + c * (cell_w + gap), y + r * (cell_h + gap), cell_w, cell_h
        caption = None
        if layout.captions and k < len(captions) and captions[k]:
            caption = (cx, cy + ch - small * 1.6, cw, small * 1.6)
            ch = (caption[1] - 1.5 * mm) - cy
        caption_boxes.append(caption)
        if aspect is None:
            sketch_boxes.append(None)
            continue
        sw = min(cw, ch * aspect)
        sh = sw / aspect
        sketch_boxes.append((cx + cw / 2 - sw / 2, cy + ch / 2 - sh / 2, sw, sh))
    return PageBoxes(title, title_px, footer, small, caption_boxes, sketch_boxes)


def _renderer(svg_path: str, layout: Layout) -> QSvgRenderer | None:
    try:
        return QSvgRenderer(QByteArray(_sketch(svg_path, layout).encode("utf-8")))
    except (OSError, ValueError):
        return None


def _aspect(renderer: QSvgRenderer | None) -> float | None:
    if renderer is None:
        return None
    box = renderer.viewBoxF()
    return box.width() / box.height() if box.width() > 0 and box.height() > 0 else 1.0


def paint_page(p: QPainter, rect: QRectF, items: list[tuple[str, str]], layout: Layout, page: int = 1,
               pages: int = 1) -> None:
    """One page: ``items`` are (sketch file, caption) for this page, ``rect`` the whole page in the painter's
    units – laid out by page_boxes."""
    if paper_mod.normalize(layout.paper) is not None:
        side = min(2400, max(1, round(rect.width())))
        img = paper_mod.qimage(layout.paper, side, max(1, round(side * rect.height() / rect.width())),
                               layout.background)
        p.drawImage(rect, img)
    elif layout.background and layout.background != "transparent":
        p.fillRect(rect, QColor(layout.background))
    cols, rows = grid(layout.per_page, layout.landscape)
    shown = items[: cols * rows]
    renderers = [_renderer(svg_path, layout) for svg_path, _caption in shown]
    boxes = page_boxes(rect.width(), rect.height(), layout, [caption for _path, caption in shown],
                       [_aspect(r) for r in renderers], pages)

    def at(box: Box) -> QRectF:
        return QRectF(rect.left() + box[0], rect.top() + box[1], box[2], box[3])

    p.setPen(QColor(text_colour(layout)))
    font = QFont("Inter")
    if boxes.title:
        font.setPixelSize(boxes.title_px)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.drawText(at(boxes.title), Qt.AlignLeft | Qt.AlignVCenter, layout.title)
    font.setPixelSize(boxes.small_px)
    font.setWeight(QFont.Weight.Normal)
    p.setFont(font)
    if boxes.footer:
        if layout.signature:
            p.drawText(at(boxes.footer), Qt.AlignRight | Qt.AlignVCenter, layout.signature)
        if pages > 1:
            p.drawText(at(boxes.footer), Qt.AlignLeft | Qt.AlignVCenter, f"{page} / {pages}")
    for (_path, caption), renderer, caption_box, sketch_box in zip(shown, renderers, boxes.captions,
                                                                   boxes.sketches):
        if caption_box:
            p.drawText(at(caption_box), Qt.AlignHCenter | Qt.AlignVCenter, caption)
        if renderer is not None and sketch_box:
            renderer.render(p, at(sketch_box))


def _pages(items: list[tuple[str, str]], layout: Layout) -> list[list[tuple[str, str]]]:
    n = max(layout.per_page, 1)
    return [items[i:i + n] for i in range(0, len(items), n)]


def paint_pages(device, items: list[tuple[str, str]], layout: Layout, progress=None, cancel=None) -> int:
    """All pages on a paged device (QPdfWriter, QPrinter); returns the number of pages."""
    chunks = _pages(items, layout)
    p = QPainter(device)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    try:
        for i, chunk in enumerate(chunks):
            if cancel and cancel():
                raise InterruptedError("print cancelled")
            if i:
                device.newPage()
            rect = QRectF(0, 0, device.width(), device.height())
            paint_page(p, rect, chunk, layout, i + 1, len(chunks))
            if progress:
                progress(i + 1, len(chunks))
    finally:
        p.end()
    return len(chunks)


def export_pdf_pages(items: list[tuple[str, str]], dest: str, layout: Layout, progress=None, cancel=None) -> int:
    """A PDF with the sketches laid out on pages; returns the number of pages."""
    import os

    writer = QPdfWriter(dest)
    writer.setPageLayout(page_layout(layout))
    writer.setResolution(PDF_DPI)
    writer.setCreator("CLIPasso Studio")
    writer.setTitle(layout.title or os.path.splitext(os.path.basename(dest))[0])
    try:
        return paint_pages(writer, items, layout, progress, cancel)
    except BaseException:
        del writer
        try:
            os.remove(dest)
        except OSError:
            pass
        raise


def preview(items: list[tuple[str, str]], layout: Layout, width: int = 360, page: int = 1) -> QImage:
    """Page ``page`` as a picture ``width`` px wide (the preview of the print dialog)."""
    w_mm, h_mm = page_mm(layout)
    img = QImage(width, max(1, round(width * h_mm / w_mm)), QImage.Format_ARGB32)
    img.fill(QColor("#FFFFFF"))
    chunks = _pages(items, layout) or [[]]
    page = min(max(page, 1), len(chunks))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    paint_page(p, QRectF(0, 0, img.width(), img.height()), chunks[page - 1], layout, page, len(chunks))
    p.end()
    return img


def print_pages(parent, items: list[tuple[str, str]], layout: Layout) -> bool:
    """The printer dialog of the system, then the pages; False when it was cancelled."""
    from PySide6.QtPrintSupport import QPrintDialog, QPrinter

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setPageLayout(page_layout(layout))
    printer.setFullPage(True)
    printer.setDocName(layout.title or "CLIPasso Studio")
    dlg = QPrintDialog(printer, parent)
    if dlg.exec() != QPrintDialog.DialogCode.Accepted:
        return False
    paint_pages(printer, items, layout)
    return True
