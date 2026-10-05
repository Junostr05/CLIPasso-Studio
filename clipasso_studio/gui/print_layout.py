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


def _text_colour(layout: Layout) -> QColor:
    bg = paper_mod.color_of(layout.paper, layout.background) if paper_mod.normalize(layout.paper) else \
        (layout.background or "#FFFFFF")
    return QColor("#E8E8E2") if paper_mod.is_dark(bg if bg != "transparent" else "#FFFFFF") else QColor("#3A3A3A")


def paint_page(p: QPainter, rect: QRectF, items: list[tuple[str, str]], layout: Layout, page: int = 1,
               pages: int = 1) -> None:
    """One page: ``items`` are (sketch file, caption) for this page, ``rect`` the whole page in the painter's
    units. Sizes are given in mm of the page, so every device (PDF, printer, preview) gets the same picture."""
    w_mm, _h_mm = page_mm(layout)
    mm = rect.width() / w_mm
    if paper_mod.normalize(layout.paper) is not None:
        side = min(2400, max(1, round(rect.width())))
        img = paper_mod.qimage(layout.paper, side, max(1, round(side * rect.height() / rect.width())),
                               layout.background)
        p.drawImage(rect, img)
    elif layout.background and layout.background != "transparent":
        p.fillRect(rect, QColor(layout.background))
    inner = rect.adjusted(layout.margin_mm * mm, layout.margin_mm * mm, -layout.margin_mm * mm,
                          -layout.margin_mm * mm)
    colour = _text_colour(layout)
    p.setPen(colour)
    font = QFont("Inter")
    if layout.title:
        font.setPixelSize(max(1, round(min(9.0, w_mm / 24) * mm)))
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        height = font.pixelSize() * 1.6
        p.drawText(QRectF(inner.left(), inner.top(), inner.width(), height), Qt.AlignLeft | Qt.AlignVCenter,
                   layout.title)
        inner.setTop(inner.top() + height + 3 * mm)
    small = max(1, round(min(4.0, w_mm / 50) * mm))
    if layout.signature or pages > 1:
        font.setPixelSize(small)
        font.setWeight(QFont.Weight.Normal)
        p.setFont(font)
        height = small * 1.8
        foot = QRectF(inner.left(), inner.bottom() - height, inner.width(), height)
        if layout.signature:
            p.drawText(foot, Qt.AlignRight | Qt.AlignVCenter, layout.signature)
        if pages > 1:
            p.drawText(foot, Qt.AlignLeft | Qt.AlignVCenter, f"{page} / {pages}")
        inner.setBottom(inner.bottom() - height - 3 * mm)
    cols, rows = grid(layout.per_page, layout.landscape)
    gap = GAP_MM * mm if layout.per_page > 1 else 0.0
    cell_w = (inner.width() - gap * (cols - 1)) / cols
    cell_h = (inner.height() - gap * (rows - 1)) / rows
    font.setPixelSize(small)
    font.setWeight(QFont.Weight.Normal)
    p.setFont(font)
    for k, (svg_path, caption) in enumerate(items[: cols * rows]):
        c, r = k % cols, k // cols
        cell = QRectF(inner.left() + c * (cell_w + gap), inner.top() + r * (cell_h + gap), cell_w, cell_h)
        if layout.captions and caption:
            text = QRectF(cell.left(), cell.bottom() - small * 1.6, cell.width(), small * 1.6)
            p.drawText(text, Qt.AlignHCenter | Qt.AlignVCenter, caption)
            cell.setBottom(text.top() - 1.5 * mm)
        try:
            renderer = QSvgRenderer(QByteArray(_sketch(svg_path, layout).encode("utf-8")))
        except (OSError, ValueError):
            continue
        box = renderer.viewBoxF()
        aspect = box.width() / box.height() if box.width() > 0 and box.height() > 0 else 1.0
        w = min(cell.width(), cell.height() * aspect)
        h = w / aspect
        renderer.render(p, QRectF(cell.center().x() - w / 2, cell.center().y() - h / 2, w, h))


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
