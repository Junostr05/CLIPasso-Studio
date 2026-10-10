"""The gallery's large view: one result at a time as large as the window allows – arrow keys or the buttons go
through the results, the mouse wheel zooms (around the cursor), dragging moves the zoomed sketch, a slideshow
goes on by itself. Two marked results are compared on top of each other with a divider to drag."""

from __future__ import annotations

import os

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from . import icons, methods_ui, theme
from .app_settings import app_settings
from .i18n import tr
from .widgets.canvas import styled, svg_renderer
from .widgets.common import button, label

INTERVALS = (2, 3, 5, 10)  # s: slideshow
ZOOM_MAX = 16.0  # times the fitted size
WHEEL_STEP = 1.0015  # per 1/8° of the wheel (one notch: 1.2x)


def read_sketch(item) -> str | None:
    try:
        with open(item.sketch, encoding="utf-8") as f:
            return f.read()
    except (OSError, TypeError):
        return None


def describe(item) -> str:
    """Method · score · strokes · time · date of a result (one line)."""
    parts = [methods_ui.name(item.method)]
    if item.score is not None:
        parts.append(f"CLIP {item.score:.1f}")
    elif item.loss is not None:
        parts.append(f"Loss {item.loss:.3f}")
    if item.strokes > 1:
        parts.append(tr("ui.viewer.strokes", n=item.strokes))
    if item.seconds:
        seconds = int(round(item.seconds))
        parts.append(f"{seconds // 60}:{seconds % 60:02d} min" if seconds >= 60 else f"{seconds} s")
    if item.created:
        parts.append(item.created[:16].replace("T", " "))
    return " · ".join(parts)


class ZoomSvgView(QWidget):
    """A sketch on its paper, fitted into the view. The wheel zooms around the cursor, dragging moves the zoomed
    sketch, a double click fits it again."""

    zoom_changed = Signal(float)
    MARGIN = 18

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(240, 240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._renderer = None
        self._style = "plain"
        self.zoom = 1.0
        self.offset = QPointF(0, 0)  # px: the sketch's centre from the view's centre
        self._grab: QPointF | None = None
        self.placeholder = ""

    # ---------------------------------------------------------------- content
    def set_svg(self, svg: str | None, style: str = "plain"):
        self._style = style
        self._renderer = svg_renderer(styled(svg, style))
        self.fit()

    def has_sketch(self) -> bool:
        return self._renderer is not None

    def _aspect(self) -> float:
        r = self._renderer
        box = r.viewBoxF() if r is not None else QRectF()
        return box.width() / box.height() if box.width() > 0 and box.height() > 0 else 1.0

    # ---------------------------------------------------------------- geometry
    def base_rect(self) -> QRectF:
        """Where the sketch is drawn when it is fitted into the view."""
        w, h = max(self.width() - 2 * self.MARGIN, 1), max(self.height() - 2 * self.MARGIN, 1)
        aspect = self._aspect()
        if w / h > aspect:
            w = h * aspect
        else:
            h = w / aspect
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def sketch_rect(self) -> QRectF:
        base = self.base_rect()
        w, h = base.width() * self.zoom, base.height() * self.zoom
        c = QPointF(self.width() / 2, self.height() / 2) + self.offset
        return QRectF(c.x() - w / 2, c.y() - h / 2, w, h)

    def fit(self):
        self.zoom, self.offset = 1.0, QPointF(0, 0)
        self.zoom_changed.emit(self.zoom)
        self.update()

    def zoom_at(self, factor: float, pos: QPointF | None = None):
        """Zoom by ``factor``, the point under ``pos`` (default: the view's centre) staying where it is."""
        zoom = min(max(self.zoom * factor, 1.0), ZOOM_MAX)
        if zoom == self.zoom:
            return
        if zoom == 1.0:
            self.fit()
            return
        pos = QPointF(self.width() / 2, self.height() / 2) if pos is None else QPointF(pos)
        r = self.sketch_rect()
        u = QPointF((pos.x() - r.left()) / r.width(), (pos.y() - r.top()) / r.height())  # (in the sketch)
        base = self.base_rect()
        w, h = base.width() * zoom, base.height() * zoom
        centre = QPointF(pos.x() - u.x() * w + w / 2, pos.y() - u.y() * h + h / 2)
        self.zoom = zoom
        self.offset = centre - QPointF(self.width() / 2, self.height() / 2)
        self._keep_inside()
        self.zoom_changed.emit(self.zoom)
        self.update()

    def _keep_inside(self):
        """The zoomed sketch is not moved further than its edge to the view's centre."""
        r = self.sketch_rect()
        limit_x, limit_y = r.width() / 2, r.height() / 2
        self.offset = QPointF(min(max(self.offset.x(), -limit_x), limit_x),
                              min(max(self.offset.y(), -limit_y), limit_y))

    # ---------------------------------------------------------------- input
    def wheelEvent(self, e):  # noqa: N802
        steps = e.angleDelta().y()
        if steps:
            self.zoom_at(WHEEL_STEP ** steps, e.position())
            e.accept()

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.LeftButton and self.zoom > 1.0:
            self._grab = e.position() - self.offset
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):  # noqa: N802
        if self._grab is not None:
            self.offset = e.position() - self._grab
            self._keep_inside()
            self.update()

    def mouseReleaseEvent(self, e):  # noqa: N802
        if self._grab is not None:
            self._grab = None
            self.unsetCursor()

    def mouseDoubleClickEvent(self, e):  # noqa: N802
        if self.zoom > 1.0:
            self.fit()
        else:
            self.zoom_at(2.5, e.position())

    def resizeEvent(self, e):  # noqa: N802
        self._keep_inside()
        super().resizeEvent(e)

    # ---------------------------------------------------------------- painting
    def _paint_paper(self, p: QPainter, r: QRectF):
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.current().paper))
        p.drawRoundedRect(r, theme.RADIUS_CONTROL, theme.RADIUS_CONTROL)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self._renderer is None:
            p.setPen(QColor(theme.current().faint))
            p.drawText(self.rect(), Qt.AlignCenter | Qt.TextWordWrap, self.placeholder)
            p.end()
            return
        r = self.sketch_rect()
        self._paint_paper(p, r)
        p.setClipRect(r)  # (strokes reaching over the sketch's edge are cut there, as on the canvas)
        self._renderer.render(p, r)
        p.end()


class SplitView(ZoomSvgView):
    """Two sketches on top of each other: the first left of the divider, the second right of it. Dragging moves the
    divider (with zoom: dragging near the divider; elsewhere it moves the sketches)."""

    split_changed = Signal(float)
    GRIP = 14  # px: how close to the divider a press takes it

    def __init__(self, parent=None):
        super().__init__(parent)
        self._second = None
        self.split = 0.5  # of the sketch's width
        self.captions = ("", "")
        self._dragging = False
        self.setMouseTracking(True)

    def set_pair(self, first: str | None, second: str | None, style: str = "plain",
                 captions: tuple[str, str] = ("", "")):
        self._second = svg_renderer(styled(second, style))
        self.captions = captions
        self.set_svg(first, style)

    def has_sketch(self) -> bool:
        return self._renderer is not None and self._second is not None

    def set_split(self, value: float):
        self.split = min(max(float(value), 0.0), 1.0)
        self.split_changed.emit(self.split)
        self.update()

    def divider_x(self) -> float:
        r = self.sketch_rect()
        return r.left() + self.split * r.width()

    def _near_divider(self, pos: QPointF) -> bool:
        return abs(pos.x() - self.divider_x()) <= self.GRIP

    def _split_at(self, pos: QPointF):
        r = self.sketch_rect()
        self.set_split((pos.x() - r.left()) / max(r.width(), 1.0))

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() != Qt.LeftButton:
            return
        if self.zoom > 1.0 and not self._near_divider(e.position()):
            super().mousePressEvent(e)
            return
        self._dragging = True
        self._split_at(e.position())

    def mouseMoveEvent(self, e):  # noqa: N802
        if self._dragging:
            self._split_at(e.position())
        elif self._grab is not None:
            super().mouseMoveEvent(e)
        else:
            self.setCursor(Qt.SplitHCursor if self._near_divider(e.position()) or self.zoom == 1.0
                           else Qt.OpenHandCursor)

    def mouseReleaseEvent(self, e):  # noqa: N802
        self._dragging = False
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):  # noqa: N802
        if not self._near_divider(e.position()):
            super().mouseDoubleClickEvent(e)

    def keyPressEvent(self, e):  # noqa: N802
        step = {Qt.Key_Left: -0.05, Qt.Key_Right: 0.05}.get(e.key())
        if step is not None and e.modifiers() & Qt.ShiftModifier:
            self.set_split(self.split + step)
        else:
            super().keyPressEvent(e)

    def paintEvent(self, event):  # noqa: N802
        if not self.has_sketch():
            super().paintEvent(event)
            return
        pal = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.sketch_rect()
        self._paint_paper(p, r)
        x = self.divider_x()
        for renderer, clip in ((self._renderer, QRectF(r.left(), r.top(), x - r.left(), r.height())),
                               (self._second, QRectF(x, r.top(), r.right() - x, r.height()))):
            p.save()
            p.setClipRect(clip)
            renderer.render(p, r)
            p.restore()
        top, bottom = max(r.top(), 0.0), min(r.bottom(), float(self.height()))
        p.setPen(QPen(QColor(pal.accent), 2))
        p.drawLine(QPointF(x, top), QPointF(x, bottom))
        mid = QPointF(x, (top + bottom) / 2)
        p.setBrush(QColor(pal.accent))
        p.drawEllipse(mid, 11, 11)
        p.setPen(QPen(QColor(pal.on_accent), 2))
        for sign in (-1, 1):  # (two small arrows: ‹ ›)
            p.drawLine(mid + QPointF(sign * 2, -4), mid + QPointF(sign * 6, 0))
            p.drawLine(mid + QPointF(sign * 6, 0), mid + QPointF(sign * 2, 4))
        # the names in the upper corners
        font = QFont(p.font())
        font.setBold(True)
        p.setFont(font)
        fm = p.fontMetrics()
        for i, text in enumerate(self.captions):
            if not text:
                continue
            text = fm.elidedText(text, Qt.ElideRight, int(max(r.width() / 2 - 24, 40)))
            w, h = fm.horizontalAdvance(text) + 16, fm.height() + 8
            left = max(r.left(), 0.0) + 8 if i == 0 else min(r.right(), float(self.width())) - 8 - w
            box = QRectF(left, max(r.top(), 0.0) + 8, w, h)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 150))
            p.drawRoundedRect(box, theme.RADIUS_SEGMENT, theme.RADIUS_SEGMENT)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(box, Qt.AlignCenter, text)
        p.end()


class GalleryViewer(QDialog):
    """The large view over ``items`` (gallery results, the shown order), starting at ``index``. With ``pair`` (two
    results) it can also compare them (``compare``)."""

    open_job = Signal(str)

    def __init__(self, items: list, index: int = 0, pair: list | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("ui.viewer.title"))
        self.items = [it for it in items if it.sketch and os.path.isfile(it.sketch)]
        self.index = min(max(index, 0), max(len(self.items) - 1, 0))
        self.pair = list(pair or [])[:2] if pair and len(pair) >= 2 else []
        self.comparing = False
        self.style_name = app_settings().get("canvas_style", "plain")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(10)

        head = QHBoxLayout()
        names = QVBoxLayout()
        names.setSpacing(2)
        self.name_label = label("", "h2")
        self.info_label = label("", "muted")
        names.addWidget(self.name_label)
        names.addWidget(self.info_label)
        head.addLayout(names, 1)
        self.position_label = label("", "faint")
        head.addWidget(self.position_label, 0, Qt.AlignTop)
        lay.addLayout(head)

        self.view = ZoomSvgView()
        self.view.placeholder = tr("ui.viewer.missing")
        self.split = SplitView()
        self.split.setVisible(False)
        for v in (self.view, self.split):
            v.zoom_changed.connect(self._update_zoom)
            lay.addWidget(v, 1)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.prev_btn = button("", "chevron-left", "ghost")
        self.prev_btn.clicked.connect(self.previous)
        self.next_btn = button("", "chevron-right", "ghost")
        self.next_btn.clicked.connect(self.next)
        self.play_btn = button("", "play", "ghost")
        self.play_btn.setCheckable(True)
        self.play_btn.toggled.connect(self.set_slideshow)
        self.interval = QComboBox()
        for s in INTERVALS:
            self.interval.addItem(f"{s} s", s)
        self.interval.setCurrentIndex(INTERVALS.index(3))
        self.interval.currentIndexChanged.connect(lambda _: self._timer.setInterval(self.seconds() * 1000))
        self.compare_btn = button("", "git-compare", "ghost")
        self.compare_btn.setCheckable(True)
        self.compare_btn.toggled.connect(self.set_compare)
        self.compare_btn.setVisible(bool(self.pair))
        self.zoom_label = label("", "faint")
        self.fit_btn = button("", "scan", "ghost")
        self.fit_btn.clicked.connect(lambda: self.current_view().fit())
        self.open_btn = button("", "brush")
        self.open_btn.clicked.connect(self._open)
        self.close_btn = button("", "x", "ghost")
        self.close_btn.clicked.connect(self.close)
        for w in (self.prev_btn, self.play_btn, self.interval, self.next_btn, self.compare_btn):
            bar.addWidget(w)
        bar.addStretch(1)
        for w in (self.zoom_label, self.fit_btn, self.open_btn, self.close_btn):
            bar.addWidget(w)
        lay.addLayout(bar)

        self._timer = QTimer(self, interval=self.seconds() * 1000)
        self._timer.timeout.connect(lambda: self.next(wrap=True))
        self.shortcuts: dict[str, QShortcut] = {}
        for keys, slot in ((("Left", "PgUp"), self.previous),
                           (("Right", "PgDown"), self.next),
                           (("Space",), lambda: self.play_btn.toggle()),
                           (("Home",), lambda: self.show_index(0)),
                           (("End",), lambda: self.show_index(len(self.items) - 1)),
                           (("+", "="), lambda: self.current_view().zoom_at(1.25)),
                           (("-",), lambda: self.current_view().zoom_at(0.8)),
                           (("0",), lambda: self.current_view().fit())):
            for key in keys:
                self.shortcuts[key] = QShortcut(QKeySequence(key), self, activated=slot)
        self.retranslate()
        if parent is not None and parent.window() is not None:
            size = parent.window().size()
            self.resize(QSize(max(int(size.width() * 0.9), 640), max(int(size.height() * 0.9), 520)))
        else:
            self.resize(1000, 760)
        self.show_index(self.index)

    # ---------------------------------------------------------------- state
    def seconds(self) -> int:
        return int(self.interval.currentData() or 3)

    def current(self):
        return self.items[self.index] if self.items else None

    def current_view(self) -> ZoomSvgView:
        return self.split if self.comparing else self.view

    def show_index(self, index: int):
        if not self.items:
            self.name_label.setText(tr("ui.viewer.none"))
            self.info_label.setText("")
            self.position_label.setText("")
            self.view.set_svg(None)
            self._update_buttons()
            return
        self.index = min(max(index, 0), len(self.items) - 1)
        it = self.items[self.index]
        self.view.set_svg(read_sketch(it), self.style_name)
        if not self.comparing:
            self.name_label.setText(it.name)
            self.info_label.setText(describe(it))
        self.position_label.setText(f"{self.index + 1} / {len(self.items)}")
        if self._timer.isActive():
            self._timer.start()  # (a step by hand: the next one a full interval later)
        self._update_buttons()

    def next(self, wrap: bool = False):
        if self.comparing or not self.items:
            return
        if self.index + 1 < len(self.items):
            self.show_index(self.index + 1)
        elif wrap or self._timer.isActive():
            self.show_index(0)

    def previous(self):
        if self.comparing or not self.items:
            return
        if self.index > 0:
            self.show_index(self.index - 1)
        elif self._timer.isActive():
            self.show_index(len(self.items) - 1)

    def set_slideshow(self, on: bool):
        on = bool(on) and len(self.items) > 1 and not self.comparing
        if self.play_btn.isChecked() != on:
            self.play_btn.blockSignals(True)
            self.play_btn.setChecked(on)
            self.play_btn.blockSignals(False)
        if on:
            self._timer.start(self.seconds() * 1000)
        else:
            self._timer.stop()
        self._update_buttons()

    def slideshow_running(self) -> bool:
        return self._timer.isActive()

    def set_compare(self, on: bool):
        """The two marked results on top of each other, with the divider (``pair``)."""
        on = bool(on) and len(self.pair) == 2
        if on:
            self.set_slideshow(False)
        self.comparing = on
        if self.compare_btn.isChecked() != on:
            self.compare_btn.blockSignals(True)
            self.compare_btn.setChecked(on)
            self.compare_btn.blockSignals(False)
        if on:
            a, b = self.pair
            self.split.set_pair(read_sketch(a), read_sketch(b), self.style_name, (a.name, b.name))
            self.split.set_split(0.5)
            self.name_label.setText(tr("ui.viewer.compare_title", a=a.name, b=b.name))
            self.info_label.setText(f"◀ {describe(a)}    ▶ {describe(b)}")
            self.position_label.setText("")
        self.view.setVisible(not on)
        self.split.setVisible(on)
        if not on:
            self.show_index(self.index)
        self._update_zoom(self.current_view().zoom)
        self._update_buttons()

    def _update_zoom(self, zoom: float):
        self.zoom_label.setText(f"{zoom * 100:.0f} %" if zoom > 1.0 else tr("ui.viewer.fitted"))

    def _update_buttons(self):
        many = len(self.items) > 1 and not self.comparing
        for w in (self.prev_btn, self.next_btn, self.play_btn, self.interval):
            w.setEnabled(many)
        running = self._timer.isActive()
        self.play_btn.setIcon(icons.icon("pause" if running else "play", theme.current().text))
        self.play_btn.setText(tr("ui.viewer.pause" if running else "ui.viewer.slideshow"))
        self.open_btn.setEnabled(self.current() is not None and not self.comparing)

    def _open(self):
        it = self.current()
        if it is not None:
            self.open_job.emit(it.job_dir)
            self.close()

    def closeEvent(self, e):  # noqa: N802
        self._timer.stop()
        super().closeEvent(e)

    def retranslate(self):
        self.prev_btn.setToolTip(tr("ui.viewer.previous") + "  (←)")
        self.next_btn.setToolTip(tr("ui.viewer.next") + "  (→)")
        self.play_btn.setToolTip(tr("ui.viewer.slideshow_tip"))
        self.interval.setToolTip(tr("ui.viewer.interval_tip"))
        self.compare_btn.setText(tr("ui.viewer.compare"))
        self.compare_btn.setToolTip(tr("ui.viewer.compare_tip"))
        self.fit_btn.setToolTip(tr("ui.viewer.fit") + "  (0)")
        self.open_btn.setText(tr("ui.gallery.open"))
        self.close_btn.setToolTip(tr("ui.viewer.close") + "  (Esc)")
        for b, key in ((self.prev_btn, "ui.viewer.previous"), (self.next_btn, "ui.viewer.next"),
                       (self.fit_btn, "ui.viewer.fit"), (self.close_btn, "ui.viewer.close")):
            b.setAccessibleName(tr(key))
        self.view.setToolTip(tr("ui.viewer.zoom_tip"))
        self.split.setToolTip(tr("ui.viewer.split_tip"))
        self._update_buttons()
