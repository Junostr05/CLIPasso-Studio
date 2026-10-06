"""Live sketch canvas, before/after comparison, loss chart, image drop zone and seed thumbnails."""

from __future__ import annotations

import os

from PySide6.QtCore import QByteArray, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget

from .. import icons, theme
from ..drop import IMAGE_EXT, dropped_images, has_images  # noqa: F401 (IMAGE_EXT re-exported)
from ..i18n import tr

IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff *.gif *.heic *.heif *.avif)"


def svg_renderer(svg: str | bytes | None) -> QSvgRenderer | None:
    if not svg:
        return None
    data = svg.encode("utf-8") if isinstance(svg, str) else svg
    r = QSvgRenderer(QByteArray(data))
    return r if r.isValid() else None


def styled(svg: str | None, style: str, light: bool = False) -> str | None:
    """The sketch as it is shown in the brush ``style`` (the raw SVG if it cannot be styled); ``light``: black
    strokes light (on a dark paper)."""
    if not svg or (style == "plain" and not light):
        return svg
    from ..brush import recolour_black, stylize_svg
    from ..paper import LIGHT_STROKE

    try:
        return stylize_svg(recolour_black(svg, LIGHT_STROKE) if light else svg, style)
    except Exception:  # (an SVG the brush cannot parse is shown as it is)
        return svg


def render_svg_image(svg: str, size: int, background: QColor | None = QColor("white")) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(background if background is not None else Qt.transparent)
    r = svg_renderer(svg)
    if r:
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        r.render(p, QRectF(0, 0, size, size))
        p.end()
    return img


DISPLAY_MAX = 1600  # px: the longest side photos are decoded at for display


def load_pixmap(path: str, max_side: int) -> QPixmap:
    """An image file as a pixmap of at most ``max_side`` px (big photos are decoded smaller directly;
    HEIC / AVIF through Pillow)."""
    from ..image_io import read_image

    img = read_image(path, max_side)
    return QPixmap.fromImage(img) if not img.isNull() else QPixmap()


def _fitted(widget, pix: QPixmap, size: QSize, keep_aspect: bool = True) -> QPixmap:
    """``pix`` smoothly scaled to ``size`` – kept on the widget until the pixmap or the size changes."""
    key = (pix.cacheKey(), size.width(), size.height(), keep_aspect)
    cached = getattr(widget, "_scaled", None)
    if cached is not None and cached[0] == key:
        return cached[1]
    mode = Qt.KeepAspectRatio if keep_aspect else Qt.IgnoreAspectRatio
    scaled = pix.scaled(size, mode, Qt.SmoothTransformation)
    widget._scaled = (key, scaled)
    return scaled


class SketchCanvas(QWidget):
    """Paper-like canvas showing the sketch (SVG), the input, the attention map or the mask.

    In "compare" mode a draggable divider reveals the photo on the left and the sketch on the right.
    Brush styles (``set_style``) only change how the sketch is shown: ``svg()`` stays the raw sketch, which
    the eraser edits and hits.
    """

    MODES = ("sketch", "compare", "attention", "mask", "condition", "matrix", "sheet")
    ERASER_REACH_PX = 6  # how close (screen pixels) the cursor has to be to a stroke

    erase_begin = Signal()  # eraser: mouse pressed (one undo step per press)
    erase = Signal(int)  # eraser: the stroke with this index is to be removed
    erase_end = Signal()
    pen_stroke = Signal(list)  # pen: a stroke was drawn, [(x, y), ...] in sketch coordinates

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.mode = "sketch"
        self._svg = None
        self._style = "plain"
        self._paper: dict | None = None  # paper.normalize(...) of the preview, None: the theme's paper colour
        self._paper_color: str | None = None
        self._paper_pixmap = None  # (key, QPixmap)
        self._renderer = None
        self._eraser = False
        self._erasing = False
        self._pen = False
        self._drawing: list[QPointF] | None = None  # the stroke being drawn (widget positions)
        self._index = None  # strokes.StrokeIndex of the current SVG (built on demand)
        self._hover: int | None = None
        self._hover_renderer = None
        self._input: QPixmap | None = None
        self._attention: QPixmap | None = None
        self._mask: QPixmap | None = None
        self._condition: QPixmap | None = None
        self._split = 0.5
        self._drag = False
        self.placeholder = ""
        self.setMouseTracking(True)

    def set_mode(self, mode: str):
        self.mode = mode
        self._update_cursor()
        self.update()

    def set_svg(self, svg: str | None):
        self._svg = svg
        self._renderer = svg_renderer(self._shown(svg))
        self._index = None
        self._set_hover(None)
        self.update()

    def _light(self) -> bool:
        from ..paper import color_of, is_dark

        return self._paper is not None and is_dark(color_of(self._paper, self._paper_color))

    def _shown(self, svg: str | None) -> str | None:
        return styled(svg, self._style, self._light())

    def _restyle(self):
        self._renderer = svg_renderer(self._shown(self._svg))
        hover, self._hover = self._hover, None
        self._set_hover(hover)
        self.update()

    def set_style(self, style: str):
        """Brush style the sketch is shown in (``brush.STYLES``)."""
        if style == self._style:
            return
        self._style = style
        self._restyle()

    def style(self) -> str:
        return self._style

    def set_paper(self, paper: dict | None, color: str | None = None):
        """The paper the sketch is shown on (``paper.normalize``; None: the theme's paper colour) in ``color``
        (None: the paper's own colour). On a dark paper black strokes are shown light."""
        from ..paper import normalize

        paper = normalize(paper)
        if (paper, color or None) == (self._paper, self._paper_color):
            return
        self._paper, self._paper_color = paper, color or None
        self._paper_pixmap = None
        self._restyle()

    def paper(self) -> dict | None:
        return self._paper

    def _fill_paper(self, p: QPainter, rect: QRectF, fallback: str):
        if self._paper is None:
            p.fillRect(rect, QColor(fallback))
            return
        from ..paper import qimage

        key = (self._paper["kind"], self._paper["vignette"], self._paper_color, int(rect.width()), int(rect.height()))
        if self._paper_pixmap is None or self._paper_pixmap[0] != key:
            self._paper_pixmap = (key, QPixmap.fromImage(qimage(self._paper, max(1, key[3]), max(1, key[4]),
                                                                self._paper_color)))
        p.drawPixmap(rect.topLeft(), self._paper_pixmap[1])

    # ----------------------------------------------------------------- eraser
    def set_eraser(self, on: bool):
        self._eraser = bool(on)
        self._erasing = False
        if on:
            self._pen = False
        self._set_hover(None)
        self._update_cursor()

    def eraser_active(self) -> bool:
        return self._eraser and self.mode == "sketch" and self._svg is not None

    # ----------------------------------------------------------------- pen
    def set_pen(self, on: bool):
        """Draw own strokes into the sketch (``pen_stroke`` per stroke)."""
        self._pen = bool(on)
        self._drawing = None
        if on:
            self._eraser = self._erasing = False
            self._set_hover(None)
        self._update_cursor()
        self.update()

    def pen_active(self) -> bool:
        return self._pen and self.mode == "sketch" and self._svg is not None

    def _update_cursor(self):
        if self.mode == "compare":
            self.setCursor(Qt.SplitHCursor)
        elif (self._eraser or self._pen) and self.mode == "sketch":
            self.setCursor(Qt.CrossCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def _set_hover(self, index: int | None):
        if index == self._hover:
            return
        self._hover = index
        self._hover_renderer = None
        if index is not None and self._svg:
            from ..strokes import highlight

            self._hover_renderer = svg_renderer(self._shown(highlight(self._svg, index)))
        self.update()

    def to_sketch(self, pos) -> tuple[float, float]:
        """A widget position in the coordinates of the sketch (its viewBox)."""
        from ..strokes import view_box

        rect = self._paper_rect()
        x0, y0, w, h = view_box(self._svg) if self._svg else (0.0, 0.0, 1.0, 1.0)
        return (x0 + (pos.x() - rect.left()) / max(rect.width(), 1) * w,
                y0 + (pos.y() - rect.top()) / max(rect.height(), 1) * h)

    def stroke_at(self, pos) -> int | None:
        """Index of the stroke under a widget position (None: none / outside the sketch)."""
        if not self._svg:
            return None
        rect = self._paper_rect()
        if not rect.contains(pos):
            return None
        from ..strokes import StrokeIndex, view_box

        if self._index is None:
            try:
                self._index = StrokeIndex(self._svg)
                self._box = view_box(self._svg)
            except Exception:
                return None
        w = self._box[2]
        sx, sy = self.to_sketch(pos)
        return self._index.hit(sx, sy, self.ERASER_REACH_PX * w / max(rect.width(), 1))

    def svg(self) -> str | None:
        return self._svg

    def set_input(self, pm: QPixmap | None):
        self._input = pm
        self.update()

    def set_attention(self, pm: QPixmap | None):
        self._attention = pm
        self.update()

    def set_mask(self, pm: QPixmap | None):
        self._mask = pm
        self.update()

    def set_condition(self, pm: QPixmap | None):
        self._condition = pm
        self.update()

    def clear(self):
        self._svg = self._renderer = self._attention = self._mask = self._condition = None
        self.update()

    def _paper_rect(self) -> QRectF:
        side = min(self.width(), self.height()) - 8
        return QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)

    def paintEvent(self, event):  # noqa: N802
        pal = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = self._paper_rect()
        # soft shadow + paper
        for i, alpha in enumerate((18, 12, 6)):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, alpha))
            p.drawRoundedRect(rect.adjusted(-2 - i * 2, -1 - i, 2 + i * 2, 4 + i * 3), 14, 14)
        clip = QPainterPath()
        clip.addRoundedRect(rect, 12, 12)
        p.setClipPath(clip)
        self._fill_paper(p, rect, pal.paper)

        if self.mode == "attention" and self._attention:
            p.drawPixmap(rect.toRect(), self._attention)
        elif self.mode == "mask" and self._mask:
            p.drawPixmap(rect.toRect(), self._mask)
        elif self.mode == "condition" and self._condition:
            p.drawPixmap(rect.toRect(), self._condition)
        elif self.mode == "compare" and self._input:
            # scaled once per size, not on every move of the divider
            p.drawPixmap(rect.toRect(), _fitted(self, self._input, rect.toRect().size(), keep_aspect=False))
            x = rect.left() + rect.width() * self._split
            right = QRectF(x, rect.top(), rect.right() - x, rect.height())
            p.save()
            p.setClipRect(right, Qt.IntersectClip)
            self._fill_paper(p, rect, pal.paper)
            if self._renderer:
                self._renderer.render(p, rect)
            p.restore()
            p.setClipping(False)
            p.setPen(QPen(QColor(pal.accent), 2))
            p.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            p.setBrush(QColor(pal.accent))
            p.drawEllipse(QPointF(x, rect.center().y()), 9, 9)
            p.setPen(QPen(QColor("white"), 2))
            cy = rect.center().y()
            p.drawLine(QPointF(x - 4, cy), QPointF(x - 1, cy - 3))
            p.drawLine(QPointF(x - 4, cy), QPointF(x - 1, cy + 3))
            p.drawLine(QPointF(x + 4, cy), QPointF(x + 1, cy - 3))
            p.drawLine(QPointF(x + 4, cy), QPointF(x + 1, cy + 3))
        elif self._renderer:
            (self._hover_renderer if self.eraser_active() and self._hover_renderer else self._renderer).render(p, rect)
            if self._drawing and len(self._drawing) > 1:  # the stroke being drawn with the pen
                p.setPen(QPen(QColor(pal.accent), 2.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.drawPolyline(self._drawing)
        else:
            p.setClipping(False)
            p.setPen(QColor("#9AA3B4"))
            size = int(min(42, rect.width() * 0.22))
            if self.placeholder and rect.width() > 200:
                icon = icons.pixmap("brush", "#B8BECC", size)
                p.drawPixmap(int(rect.center().x() - size / 2), int(rect.center().y() - 40), icon)
                p.drawText(rect.adjusted(20, 40, -20, 0), Qt.AlignCenter | Qt.TextWordWrap, self.placeholder)
            else:
                icon = icons.pixmap("hourglass", "#C9CED8", size)
                p.drawPixmap(int(rect.center().x() - size / 2), int(rect.center().y() - size / 2), icon)
        p.end()

    def mousePressEvent(self, e):  # noqa: N802
        if self.mode == "compare":
            self._drag = True
            self._update_split(e.position().x())
        elif self.pen_active() and e.button() == Qt.LeftButton and self._paper_rect().contains(e.position()):
            self._drawing = [e.position()]
        elif self.eraser_active() and e.button() == Qt.LeftButton:
            self._erasing = True
            self.erase_begin.emit()
            hit = self.stroke_at(e.position())
            if hit is not None:
                self.erase.emit(hit)

    def mouseMoveEvent(self, e):  # noqa: N802
        if self._drag:
            self._update_split(e.position().x())
        elif self._drawing is not None:
            pos = e.position()
            last = self._drawing[-1]
            if abs(pos.x() - last.x()) + abs(pos.y() - last.y()) >= 1.5:
                self._drawing.append(pos)
                self.update()
        elif self.eraser_active():
            hit = self.stroke_at(e.position())
            if self._erasing and hit is not None:
                self.erase.emit(hit)  # drag over strokes to remove several
                hit = self.stroke_at(e.position())
            self._set_hover(hit)

    def mouseReleaseEvent(self, e):  # noqa: N802
        self._drag = False
        if self._drawing is not None:
            drawn, self._drawing = self._drawing, None
            self.update()
            if len(drawn) > 1:
                self.pen_stroke.emit([self.to_sketch(q) for q in drawn])
        if self._erasing:
            self._erasing = False
            self.erase_end.emit()

    def leaveEvent(self, e):  # noqa: N802
        self._set_hover(None)
        super().leaveEvent(e)

    def _update_split(self, x: float):
        rect = self._paper_rect()
        self._split = min(max((x - rect.left()) / max(rect.width(), 1), 0.0), 1.0)
        self.update()


class SheetView(QWidget):
    """A contact sheet: every sketch of a job side by side, as large as the view allows, with its caption. A click
    selects one, a double click opens it on the canvas, the context menu offers more (``menu_requested``)."""

    clicked = Signal(int)
    activated = Signal(int)
    menu_requested = Signal(int, object)  # (sketch, global position)
    _GAP, _CAPTION = 10, 20

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.items: list[int] = []
        self._svgs: dict[int, str] = {}
        self._renderers: dict[int, QSvgRenderer] = {}
        self._captions: dict[int, str] = {}
        self._style = "plain"
        self.selected: int | None = None
        self.best: int | None = None
        self.setCursor(Qt.PointingHandCursor)

    def clear(self):
        self.items, self.selected, self.best = [], None, None
        self._svgs.clear()
        self._renderers.clear()
        self._captions.clear()
        self.update()

    def set_cell(self, item: int, svg: str | None, caption: str | None = None):
        if item not in self.items:
            self.items = sorted(self.items + [item])
        r = svg_renderer(styled(svg, self._style))
        if r:
            self._renderers[item], self._svgs[item] = r, svg
        if caption is not None:
            self._captions[item] = caption
        self.update()

    def set_caption(self, item: int, caption: str):
        self._captions[item] = caption
        self.update()

    def set_style(self, style: str):
        if style == self._style:
            return
        self._style = style
        for item, svg in self._svgs.items():
            r = svg_renderer(styled(svg, style))
            if r:
                self._renderers[item] = r
        self.update()

    def set_selected(self, item: int | None):
        self.selected = item
        self.update()

    def set_best(self, item: int | None):
        self.best = item
        self.update()

    def _grid(self) -> tuple[int, float]:
        """(columns, cell size): the number of columns that gives the largest cells."""
        n = max(len(self.items), 1)
        best = (1, 0.0)
        for cols in range(1, n + 1):
            rows = -(-n // cols)
            size = min((self.width() - self._GAP * (cols + 1)) / cols,
                       (self.height() - self._GAP * (rows + 1) - self._CAPTION * rows) / rows)
            if size > best[1]:
                best = (cols, size)
        return best[0], max(best[1], 24.0)

    def cell_rect(self, index: int) -> QRectF:
        cols, size = self._grid()
        rows = -(-max(len(self.items), 1) // cols)
        total_w = cols * size + (cols + 1) * self._GAP
        total_h = rows * (size + self._CAPTION) + (rows + 1) * self._GAP
        x0, y0 = (self.width() - total_w) / 2, (self.height() - total_h) / 2
        col, row = index % cols, index // cols
        return QRectF(x0 + self._GAP + col * (size + self._GAP),
                      y0 + self._GAP + row * (size + self._CAPTION + self._GAP), size, size)

    def paintEvent(self, event):  # noqa: N802
        pal = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.items:
            p.setPen(QColor(pal.faint))
            p.drawText(self.rect(), Qt.AlignCenter | Qt.TextWordWrap, tr("ui.sheet.empty"))
            p.end()
            return
        for i, item in enumerate(self.items):
            r = self.cell_rect(i)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(pal.paper))
            p.drawRoundedRect(r, 8, 8)
            renderer = self._renderers.get(item)
            if renderer:
                p.save()
                p.setClipRect(r)
                renderer.render(p, r.adjusted(4, 4, -4, -4))
                p.restore()
            if item in (self.selected, self.best):
                color = pal.success if item == self.best and item != self.selected else pal.accent
                p.setPen(QPen(QColor(color), 2.5))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 8, 8)
            p.setPen(QColor(pal.text if item == self.selected else pal.muted))
            caption = self._captions.get(item, str(item))
            p.drawText(QRectF(r.left(), r.bottom() + 2, r.width(), self._CAPTION - 2), Qt.AlignCenter,
                       ("★ " if item == self.best and not caption.startswith("★") else "") + caption)
        p.end()

    def item_at(self, pos) -> int | None:
        for i, item in enumerate(self.items):
            if self.cell_rect(i).contains(pos):
                return item
        return None

    def mouseReleaseEvent(self, e):  # noqa: N802
        item = self.item_at(e.position())
        if item is not None and e.button() == Qt.LeftButton and item in self._renderers:
            self.clicked.emit(item)

    def mouseDoubleClickEvent(self, e):  # noqa: N802
        item = self.item_at(e.position())
        if item is not None and item in self._renderers:
            self.activated.emit(item)

    def contextMenuEvent(self, e):  # noqa: N802
        item = self.item_at(e.pos())
        if item is not None and item in self._renderers:
            self.menu_requested.emit(item, e.globalPos())


class MatrixView(QWidget):
    """SceneSketch's abstraction matrix: one column per fidelity layer, one row per simplicity level.
    Cells are identified like the job items (``layer * 100 + level``); a click selects one."""

    clicked = Signal(int)
    activated = Signal(int)  # double click

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.layers: list[int] = []
        self.levels = 0
        self._renderers: dict[int, QSvgRenderer] = {}
        self._svgs: dict[int, str] = {}  # the raw sketches (for another brush style)
        self._style = "plain"
        self.selected: int | None = None
        self.best: int | None = None
        self.setCursor(Qt.PointingHandCursor)

    def set_layout(self, layers: list[int], levels: int):
        self.layers, self.levels = list(layers), int(levels)
        self._renderers.clear()
        self._svgs.clear()
        self.selected = self.best = None
        self.update()

    def clear(self):
        self.set_layout([], 0)

    def set_cell(self, cell: int, svg: str | None):
        r = svg_renderer(styled(svg, self._style))
        if r:
            self._renderers[int(cell)] = r
            self._svgs[int(cell)] = svg
        self.update()

    def set_style(self, style: str):
        """Brush style of the cells (see :meth:`SketchCanvas.set_style`)."""
        if style == self._style:
            return
        self._style = style
        for cell, svg in self._svgs.items():
            r = svg_renderer(styled(svg, style))
            if r:
                self._renderers[cell] = r
        self.update()

    def set_selected(self, cell: int | None):
        self.selected = cell
        self.update()

    def set_best(self, cell: int | None):
        self.best = cell
        self.update()

    _HEAD, _SIDE, _GAP = 42, 52, 8  # (room for the cell labels and the axis titles)

    def _cell_size(self, cols: int, rows: int) -> float:
        return min((self.width() - self._SIDE - self._GAP * (cols + 1)) / cols,
                   (self.height() - self._HEAD - self._GAP * (rows + 1)) / rows)

    def _geometry(self):
        """(x0, y0, cell size, gap, transposed). Layers are columns and levels rows like in the paper,
        unless the grid is transposed because that gives larger cells (e.g. one tall column in a wide view)."""
        layers, levels = max(len(self.layers), 1), self.levels + 1
        transposed = self._cell_size(levels, layers) > self._cell_size(layers, levels)
        cols, rows = (levels, layers) if transposed else (layers, levels)
        size = max(self._cell_size(cols, rows), 16)
        total_w = self._SIDE + cols * size + (cols + 1) * self._GAP
        x0 = (self.width() - total_w) / 2 + self._SIDE
        y0 = self._HEAD + (self.height() - self._HEAD - rows * size - (rows + 1) * self._GAP) / 2
        return x0, y0, size, self._GAP, transposed

    def _cell_rect(self, layer_index: int, level: int) -> QRectF:
        x0, y0, size, gap, transposed = self._geometry()
        col, row = (level, layer_index) if transposed else (layer_index, level)
        return QRectF(x0 + gap + col * (size + gap), y0 + gap + row * (size + gap), size, size)

    def paintEvent(self, event):  # noqa: N802
        pal = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.layers:
            p.setPen(QColor(pal.faint))
            p.drawText(self.rect(), Qt.AlignCenter | Qt.TextWordWrap, tr("ui.matrix.empty"))
            p.end()
            return
        _, y0, _, _, transposed = self._geometry()
        p.setPen(QColor(pal.muted))
        layers = [f"L{layer}" for layer in self.layers]
        levels = [str(level) for level in range(self.levels + 1)]
        head, side = (levels, layers) if transposed else (layers, levels)
        for i, text in enumerate(head):
            r = self._cell_rect(0, i) if transposed else self._cell_rect(i, 0)
            p.drawText(QRectF(r.left(), y0 - 20, r.width(), 18), Qt.AlignCenter, text)
        for i, text in enumerate(side):
            r = self._cell_rect(i, 0) if transposed else self._cell_rect(0, i)
            p.drawText(QRectF(r.left() - 34, r.top(), 28, r.height()), Qt.AlignRight | Qt.AlignVCenter, text)
        # the axes: fidelity (CLIP layer) and simplicity – across and down, or the other way round when transposed
        across, down = (tr("ui.matrix.simplicity"), tr("ui.matrix.fidelity")) if transposed else (
            tr("ui.matrix.fidelity"), tr("ui.matrix.simplicity"))
        first = self._cell_rect(0, 0)
        last_col = self._cell_rect(0, self.levels) if transposed else self._cell_rect(len(self.layers) - 1, 0)
        last_row = self._cell_rect(len(self.layers) - 1, 0) if transposed else self._cell_rect(0, self.levels)
        p.setPen(QColor(pal.faint))
        p.drawText(QRectF(first.left(), y0 - 40, last_col.right() - first.left(), 18), Qt.AlignCenter, across + "  →")
        p.save()
        p.translate(first.left() - 40, (first.top() + last_row.bottom()) / 2)
        p.rotate(90)  # (read from the top down: the arrow points the way the levels go)
        span = last_row.bottom() - first.top()
        p.drawText(QRectF(-span / 2, -9, span, 18), Qt.AlignCenter, down + "  →")
        p.restore()
        for c, layer in enumerate(self.layers):
            for row in range(self.levels + 1):
                cell = layer * 100 + row
                r = self._cell_rect(c, row)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(pal.paper))
                p.drawRoundedRect(r, 6, 6)
                renderer = self._renderers.get(cell)
                if renderer:
                    p.save()
                    p.setClipRect(r)  # strokes may run past the edge of the scene
                    renderer.render(p, r.adjusted(2, 2, -2, -2))
                    p.restore()
                if cell in (self.selected, self.best):
                    color = pal.success if cell == self.best and cell != self.selected else pal.accent
                    p.setPen(QPen(QColor(color), 2))
                    p.setBrush(Qt.NoBrush)
                    p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 6, 6)
        p.end()

    def _cell_at(self, pos) -> int | None:
        for c, layer in enumerate(self.layers):
            for row in range(self.levels + 1):
                if self._cell_rect(c, row).contains(pos):
                    return layer * 100 + row
        return None

    def mouseReleaseEvent(self, e):  # noqa: N802
        cell = self._cell_at(e.position())
        if cell is not None and cell in self._renderers:
            self.clicked.emit(cell)

    def mouseDoubleClickEvent(self, e):  # noqa: N802
        cell = self._cell_at(e.position())
        if cell is not None and cell in self._renderers:
            self.activated.emit(cell)

    def mouseMoveEvent(self, e):  # noqa: N802
        cell = self._cell_at(e.position())
        self.setToolTip(tr("ui.cell_tip", layer=cell // 100, level=cell % 100) if cell is not None else "")


class LossChart(QWidget):
    """Minimal line chart of the training loss (thin) and eval loss (bold)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(70)
        self.train: list[tuple[int, float]] = []
        self.evals: list[tuple[int, float]] = []
        self.total = 1
        self.empty_text_key = "ui.loss_chart_empty"

    def reset(self, total: int = 1):
        self.train, self.evals, self.total = [], [], max(total, 1)
        self.update()

    def add(self, it: int, loss: float | None, loss_eval: float | None):
        """``loss`` (thin line) and ``loss_eval`` (bold line) – either may be None."""
        if loss is not None:
            self.train.append((it, loss))
        if loss_eval is not None:
            self.evals.append((it, loss_eval))
        if len(self.train) % 3 == 0 or loss_eval is not None:
            self.update()

    def paintEvent(self, event):  # noqa: N802
        pal = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(4, 6, self.width() - 8, self.height() - 12)
        p.setPen(QPen(QColor(pal.border), 1, Qt.DashLine))
        for k in range(3):
            y = r.top() + r.height() * k / 2
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        values = [v for _, v in self.train] + [v for _, v in self.evals]
        if len(values) < 2:
            p.setPen(QColor(pal.faint))
            p.drawText(r, Qt.AlignCenter, tr(self.empty_text_key))
            return
        lo, hi = min(values), max(values)
        if hi - lo < 1e-9:
            hi = lo + 1e-3

        def pt(it, v):
            return QPointF(r.left() + r.width() * it / self.total, r.bottom() - (v - lo) / (hi - lo) * r.height())

        c = QColor(pal.accent)
        c.setAlpha(90)
        p.setPen(QPen(c, 1))
        path = QPainterPath()
        step = max(1, len(self.train) // max(int(r.width()), 1))  # about one point per pixel column
        shown = self.train[::step] + ([self.train[-1]] if (len(self.train) - 1) % step else [])
        for i, (it, v) in enumerate(shown):
            path.lineTo(pt(it, v)) if i else path.moveTo(pt(it, v))
        p.drawPath(path)
        if len(self.evals) > 1:
            p.setPen(QPen(QColor(pal.accent_text), 2.2))
            path = QPainterPath()
            for i, (it, v) in enumerate(self.evals):
                path.lineTo(pt(it, v)) if i else path.moveTo(pt(it, v))
            p.drawPath(path)
        p.end()


class ImageDropZone(QFrame):
    """Drag & drop target that shows the chosen image."""

    image_dropped = Signal(str)
    images_dropped = Signal(list)  # several images, or a folder
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(190)
        self._pix: QPixmap | None = None
        self._hover = False
        self._overlay: QImage | None = None  # the object mask (see gui/mask_view.overlay)
        self.show_overlay = True
        self.title = ""
        self.subtitle = ""

    def set_image(self, path: str | None):
        # decoded at most at a screen-friendly size (a 24-megapixel photo is not needed here)
        self._pix = load_pixmap(path, DISPLAY_MAX) if path and os.path.isfile(path) else None
        self._scaled = None
        self._overlay = None
        self.update()

    def set_overlay(self, image: QImage | None):
        self._overlay = image
        self.update()

    def set_show_overlay(self, on: bool):
        self.show_overlay = on
        self.update()

    def dragEnterEvent(self, e):  # noqa: N802
        if has_images(e.mimeData()):
            self._hover = True
            e.acceptProposedAction()
            self.update()

    def dragLeaveEvent(self, e):  # noqa: N802
        self._hover = False
        self.update()

    def dropEvent(self, e):  # noqa: N802
        self._hover = False
        paths = dropped_images(e.mimeData())
        if len(paths) == 1:
            self.image_dropped.emit(paths[0])
        elif paths:
            self.images_dropped.emit(paths)
        self.update()

    def mouseReleaseEvent(self, e):  # noqa: N802
        if e.button() == Qt.LeftButton:
            self.clicked.emit()

    def paintEvent(self, event):  # noqa: N802
        pal = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        border = QColor(pal.accent if self._hover else pal.border)
        p.setPen(QPen(border, 1.5, Qt.SolidLine if self._pix else Qt.DashLine))
        bg = QColor(pal.accent_soft if self._hover else pal.surface2)
        p.setBrush(bg)
        p.drawRoundedRect(r, 12, 12)
        if self._pix and not self._pix.isNull():
            inner = r.adjusted(10, 10, -10, -10)
            scaled = _fitted(self, self._pix, inner.size().toSize())
            x = inner.left() + (inner.width() - scaled.width()) / 2
            y = inner.top() + (inner.height() - scaled.height()) / 2
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(x, y, scaled.width(), scaled.height()), 8, 8)
            p.setClipPath(clip)
            p.drawPixmap(int(x), int(y), scaled)
            if self._overlay is not None and self.show_overlay:
                p.drawImage(QRectF(int(x), int(y), scaled.width(), scaled.height()), self._overlay)
        else:
            ic = icons.pixmap("image-plus", pal.accent_text, 34)
            p.drawPixmap(int(r.center().x() - 17), int(r.center().y() - 44), ic)
            p.setPen(QColor(pal.text))
            f = p.font()
            f.setPointSizeF(f.pointSizeF() + 1)
            f.setWeight(f.Weight.DemiBold)
            p.setFont(f)
            p.drawText(r.adjusted(10, 20, -10, -r.height() / 2 + 34), Qt.AlignHCenter | Qt.AlignBottom, self.title)
            f.setWeight(f.Weight.Normal)
            f.setPointSizeF(f.pointSizeF() - 2)
            p.setFont(f)
            p.setPen(QColor(pal.muted))
            p.drawText(r.adjusted(16, r.height() / 2 + 12, -16, -8), Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap,
                       self.subtitle)
        p.end()


class SeedThumb(QFrame):
    """Small preview of one sketch (seed) with its status."""

    clicked = Signal(int)

    def __init__(self, seed: int, parent=None):
        super().__init__(parent)
        self.seed = seed
        self.setObjectName("CardFlat")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(QSize(84, 102))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(5, 5, 5, 4)
        lay.setSpacing(2)
        self.view = SketchCanvas()
        self.view.setMinimumSize(70, 70)
        self.view.setFixedSize(74, 74)
        self.caption = QLabel(tr("ui.seed", seed=seed))
        self.caption.setProperty("role", "faint")
        self.caption.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.view, 0, Qt.AlignHCenter)
        lay.addWidget(self.caption)
        self._selected = False
        self._best = False
        self.setToolTip(tr("ui.seed", seed=seed))

    def set_svg(self, svg: str):
        self.view.set_svg(svg)

    def set_style(self, style: str):
        self.view.set_style(style)

    def set_caption(self, text: str):
        self.caption.setText(text)

    def set_selected(self, selected: bool):
        self._selected = selected
        self._restyle()

    def set_best(self, best: bool):
        self._best = best
        self._restyle()

    def _restyle(self):
        pal = theme.current()
        color = pal.success if self._best else (pal.accent if self._selected else pal.border)
        width = 2 if (self._best or self._selected) else 1
        self.setStyleSheet(f"QFrame#CardFlat {{ border: {width}px solid {color}; }}")

    def mouseReleaseEvent(self, e):  # noqa: N802
        self.clicked.emit(self.seed)
