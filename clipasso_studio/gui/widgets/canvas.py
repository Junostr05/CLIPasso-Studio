"""Live sketch canvas, before/after comparison, loss chart, image drop zone and seed thumbnails."""

from __future__ import annotations

import os

from PySide6.QtCore import QByteArray, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget

from .. import icons, theme
from ..i18n import tr

IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff)"
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff")


def svg_renderer(svg: str | bytes | None) -> QSvgRenderer | None:
    if not svg:
        return None
    data = svg.encode("utf-8") if isinstance(svg, str) else svg
    r = QSvgRenderer(QByteArray(data))
    return r if r.isValid() else None


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


class SketchCanvas(QWidget):
    """Paper-like canvas showing the sketch (SVG), the input, the attention map or the mask.

    In "compare" mode a draggable divider reveals the photo on the left and the sketch on the right.
    """

    MODES = ("sketch", "compare", "attention", "mask", "condition", "matrix")
    ERASER_REACH_PX = 6  # how close (screen pixels) the cursor has to be to a stroke

    erase_begin = Signal()  # eraser: mouse pressed (one undo step per press)
    erase = Signal(int)  # eraser: the stroke with this index is to be removed
    erase_end = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.mode = "sketch"
        self._svg = None
        self._renderer = None
        self._eraser = False
        self._erasing = False
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
        self._renderer = svg_renderer(svg)
        self._index = None
        self._set_hover(None)
        self.update()

    # ----------------------------------------------------------------- eraser
    def set_eraser(self, on: bool):
        self._eraser = bool(on)
        self._erasing = False
        self._set_hover(None)
        self._update_cursor()

    def eraser_active(self) -> bool:
        return self._eraser and self.mode == "sketch" and self._svg is not None

    def _update_cursor(self):
        if self.mode == "compare":
            self.setCursor(Qt.SplitHCursor)
        elif self._eraser and self.mode == "sketch":
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

            self._hover_renderer = svg_renderer(highlight(self._svg, index))
        self.update()

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
        x0, y0, w, h = self._box
        sx = x0 + (pos.x() - rect.left()) / max(rect.width(), 1) * w
        sy = y0 + (pos.y() - rect.top()) / max(rect.height(), 1) * h
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
        p.fillRect(rect, QColor(pal.paper))

        if self.mode == "attention" and self._attention:
            p.drawPixmap(rect.toRect(), self._attention)
        elif self.mode == "mask" and self._mask:
            p.drawPixmap(rect.toRect(), self._mask)
        elif self.mode == "condition" and self._condition:
            p.drawPixmap(rect.toRect(), self._condition)
        elif self.mode == "compare" and self._input:
            p.drawPixmap(rect.toRect(), self._input)
            x = rect.left() + rect.width() * self._split
            right = QRectF(x, rect.top(), rect.right() - x, rect.height())
            p.save()
            p.setClipRect(right, Qt.IntersectClip)
            p.fillRect(rect, QColor(pal.paper))
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
        elif self.eraser_active() and e.button() == Qt.LeftButton:
            self._erasing = True
            self.erase_begin.emit()
            hit = self.stroke_at(e.position())
            if hit is not None:
                self.erase.emit(hit)

    def mouseMoveEvent(self, e):  # noqa: N802
        if self._drag:
            self._update_split(e.position().x())
        elif self.eraser_active():
            hit = self.stroke_at(e.position())
            if self._erasing and hit is not None:
                self.erase.emit(hit)  # drag over strokes to remove several
                hit = self.stroke_at(e.position())
            self._set_hover(hit)

    def mouseReleaseEvent(self, e):  # noqa: N802
        self._drag = False
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
        self.selected: int | None = None
        self.best: int | None = None
        self.setCursor(Qt.PointingHandCursor)

    def set_layout(self, layers: list[int], levels: int):
        self.layers, self.levels = list(layers), int(levels)
        self._renderers.clear()
        self.selected = self.best = None
        self.update()

    def clear(self):
        self.set_layout([], 0)

    def set_cell(self, cell: int, svg: str | None):
        r = svg_renderer(svg)
        if r:
            self._renderers[int(cell)] = r
        self.update()

    def set_selected(self, cell: int | None):
        self.selected = cell
        self.update()

    def set_best(self, cell: int | None):
        self.best = cell
        self.update()

    _HEAD, _SIDE, _GAP = 22, 30, 8

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
        head = [str(level) for level in range(self.levels + 1)] if transposed else [f"L{l}" for l in self.layers]
        side = [f"L{l}" for l in self.layers] if transposed else [str(level) for level in range(self.levels + 1)]
        for i, text in enumerate(head):
            r = self._cell_rect(0, i) if transposed else self._cell_rect(i, 0)
            p.drawText(QRectF(r.left(), y0 - 20, r.width(), 18), Qt.AlignCenter, text)
        for i, text in enumerate(side):
            r = self._cell_rect(i, 0) if transposed else self._cell_rect(0, i)
            p.drawText(QRectF(r.left() - 34, r.top(), 28, r.height()), Qt.AlignRight | Qt.AlignVCenter, text)
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
        for i, (it, v) in enumerate(self.train):
            path.lineTo(pt(it, v)) if i else path.moveTo(pt(it, v))
        p.drawPath(path)
        if len(self.evals) > 1:
            p.setPen(QPen(QColor(pal.accent_hover), 2.2))
            path = QPainterPath()
            for i, (it, v) in enumerate(self.evals):
                path.lineTo(pt(it, v)) if i else path.moveTo(pt(it, v))
            p.drawPath(path)
        p.end()


class ImageDropZone(QFrame):
    """Drag & drop target that shows the chosen image."""

    image_dropped = Signal(str)
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(190)
        self._pix: QPixmap | None = None
        self._hover = False
        self.title = ""
        self.subtitle = ""

    def set_image(self, path: str | None):
        self._pix = QPixmap(path) if path and os.path.isfile(path) else None
        self.update()

    def dragEnterEvent(self, e):  # noqa: N802
        if self._accepts(e.mimeData()):
            self._hover = True
            e.acceptProposedAction()
            self.update()

    def dragLeaveEvent(self, e):  # noqa: N802
        self._hover = False
        self.update()

    def dropEvent(self, e):  # noqa: N802
        self._hover = False
        path = self._accepts(e.mimeData())
        if path:
            self.image_dropped.emit(path)
        self.update()

    def mouseReleaseEvent(self, e):  # noqa: N802
        if e.button() == Qt.LeftButton:
            self.clicked.emit()

    @staticmethod
    def _accepts(mime) -> str | None:
        if mime.hasUrls():
            for url in mime.urls():
                path = url.toLocalFile()
                if path.lower().endswith(IMAGE_EXT):
                    return path
        return None

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
            scaled = self._pix.scaled(inner.size().toSize(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x = inner.left() + (inner.width() - scaled.width()) / 2
            y = inner.top() + (inner.height() - scaled.height()) / 2
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(x, y, scaled.width(), scaled.height()), 8, 8)
            p.setClipPath(clip)
            p.drawPixmap(int(x), int(y), scaled)
        else:
            ic = icons.pixmap("image-plus", pal.accent_hover, 34)
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
        self.caption = QLabel(f"Seed {seed}")
        self.caption.setProperty("role", "faint")
        self.caption.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.view, 0, Qt.AlignHCenter)
        lay.addWidget(self.caption)
        self._selected = False
        self._best = False
        self.setToolTip(f"Seed {seed}")

    def set_svg(self, svg: str):
        self.view.set_svg(svg)

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
