"""Crop, rotate and flip the input image before sketching (the original file is not changed)."""

from __future__ import annotations

import os
import time

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QTransform
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from . import theme
from .app_settings import app_settings
from .i18n import tr
from .widgets.common import button, label, tool_button

ASPECTS = (("free", None), ("square", 1.0), ("landscape", 4 / 3), ("portrait", 3 / 4))
HANDLE = 9  # handle size in screen pixels
MIN_SIDE = 16  # smallest crop side in image pixels


class CropView(QWidget):
    """The image with a crop rectangle: drag inside to move it, drag the handles to resize it."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.image = QImage()
        self.crop = QRectF()
        self.aspect: float | None = None
        self._drag: str | None = None  # "move" or a handle name (n, s, e, w, ne, nw, se, sw)
        self._press = QPointF()
        self._start = QRectF()

    def sizeHint(self):  # noqa: N802
        return QSize(640, 480)

    # ---------------------------------------------------------------- model
    def set_image(self, image: QImage, keep_crop: bool = False):
        self.image = image
        if not keep_crop or self.crop.isNull():
            self.crop = QRectF(0, 0, image.width(), image.height())
        self._fit_aspect()
        self.update()
        self.changed.emit()

    def set_aspect(self, aspect: float | None):
        self.aspect = aspect
        self._fit_aspect()
        self.update()
        self.changed.emit()

    def _bounds(self) -> QRectF:
        return QRectF(0, 0, self.image.width(), self.image.height())

    def _fit_aspect(self):
        """The largest rectangle of the aspect ratio inside the current crop (centred)."""
        if self.aspect is None or self.image.isNull():
            self.crop = self.crop.intersected(self._bounds())
            return
        c = self.crop if not self.crop.isNull() else self._bounds()
        w, h = c.width(), c.height()
        if w / max(h, 1e-6) > self.aspect:
            w = h * self.aspect
        else:
            h = w / self.aspect
        self.crop = QRectF(c.center().x() - w / 2, c.center().y() - h / 2, w, h).intersected(self._bounds())

    # ------------------------------------------------------------- geometry
    def _view(self) -> tuple[QRectF, float]:
        """Where the image is drawn, and its scale."""
        if self.image.isNull():
            return QRectF(), 1.0
        m = 14
        s = min((self.width() - 2 * m) / self.image.width(), (self.height() - 2 * m) / self.image.height())
        w, h = self.image.width() * s, self.image.height() * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h), s

    def _to_view(self, r: QRectF) -> QRectF:
        v, s = self._view()
        return QRectF(v.left() + r.left() * s, v.top() + r.top() * s, r.width() * s, r.height() * s)

    def _to_image(self, p: QPointF) -> QPointF:
        v, s = self._view()
        return QPointF((p.x() - v.left()) / s, (p.y() - v.top()) / s)

    def _handles(self) -> dict[str, QPointF]:
        r = self._to_view(self.crop)
        points = {"nw": r.topLeft(), "ne": r.topRight(), "sw": r.bottomLeft(), "se": r.bottomRight()}
        if self.aspect is None:
            points.update({"n": QPointF(r.center().x(), r.top()), "s": QPointF(r.center().x(), r.bottom()),
                           "w": QPointF(r.left(), r.center().y()), "e": QPointF(r.right(), r.center().y())})
        return points

    def _handle_at(self, pos: QPointF) -> str | None:
        for name, p in self._handles().items():
            if abs(pos.x() - p.x()) <= HANDLE and abs(pos.y() - p.y()) <= HANDLE:
                return name
        if self._to_view(self.crop).contains(pos):
            return "move"
        return None

    # ------------------------------------------------------------- painting
    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        v, _ = self._view()
        if self.image.isNull():
            return
        p.drawImage(v, self.image)
        r = self._to_view(self.crop)
        dim = QColor(0, 0, 0, 150)  # everything outside the crop rectangle
        p.fillRect(QRectF(v.left(), v.top(), v.width(), r.top() - v.top()), dim)
        p.fillRect(QRectF(v.left(), r.bottom(), v.width(), v.bottom() - r.bottom()), dim)
        p.fillRect(QRectF(v.left(), r.top(), r.left() - v.left(), r.height()), dim)
        p.fillRect(QRectF(r.right(), r.top(), v.right() - r.right(), r.height()), dim)
        p.setPen(QPen(QColor(255, 255, 255, 110), 1))
        for i in (1, 2):  # rule of thirds
            x = r.left() + r.width() * i / 3
            y = r.top() + r.height() * i / 3
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        accent = QColor(theme.current().accent)
        p.setPen(QPen(accent, 2))
        p.setBrush(Qt.NoBrush)
        p.drawRect(r)
        p.setBrush(QColor("white"))
        p.setPen(QPen(accent, 2))
        for pt in self._handles().values():
            p.drawRect(QRectF(pt.x() - HANDLE / 2, pt.y() - HANDLE / 2, HANDLE, HANDLE))
        p.end()

    # ---------------------------------------------------------------- mouse
    def mousePressEvent(self, e):  # noqa: N802
        if e.button() != Qt.LeftButton or self.image.isNull():
            return
        self._drag = self._handle_at(e.position())
        self._press = self._to_image(e.position())
        self._start = QRectF(self.crop)

    def mouseMoveEvent(self, e):  # noqa: N802
        if self._drag is None:
            h = self._handle_at(e.position())
            cursors = {"move": Qt.SizeAllCursor, "n": Qt.SizeVerCursor, "s": Qt.SizeVerCursor,
                       "e": Qt.SizeHorCursor, "w": Qt.SizeHorCursor, "nw": Qt.SizeFDiagCursor,
                       "se": Qt.SizeFDiagCursor, "ne": Qt.SizeBDiagCursor, "sw": Qt.SizeBDiagCursor}
            self.setCursor(cursors.get(h, Qt.ArrowCursor))
            return
        self.drag_to(self._drag, self._to_image(e.position()))

    def mouseReleaseEvent(self, e):  # noqa: N802
        self._drag = None

    def drag_to(self, handle: str, point: QPointF, start: QRectF | None = None, press: QPointF | None = None):
        """Move / resize the crop rectangle like a drag of ``handle`` to ``point`` (image coordinates)."""
        start = QRectF(self._start if start is None else start)
        press = self._press if press is None else press
        b = self._bounds()
        if handle == "move":
            dx, dy = point.x() - press.x(), point.y() - press.y()
            r = start.translated(dx, dy)
            r.moveLeft(min(max(r.left(), 0), b.width() - r.width()))
            r.moveTop(min(max(r.top(), 0), b.height() - r.height()))
            self.crop = r
        else:
            x = min(max(point.x(), 0), b.width())
            y = min(max(point.y(), 0), b.height())
            left, top, right, bottom = start.left(), start.top(), start.right(), start.bottom()
            if "w" in handle:
                left = min(x, right - MIN_SIDE)
            if "e" in handle:
                right = max(x, left + MIN_SIDE)
            if "n" in handle:
                top = min(y, bottom - MIN_SIDE)
            if "s" in handle:
                bottom = max(y, top + MIN_SIDE)
            if self.aspect is not None:  # corners only: the height follows the width
                w = right - left
                h = w / self.aspect
                if "n" in handle:
                    top = bottom - h
                else:
                    bottom = top + h
                if top < 0 or bottom > b.height():  # too tall: limit by the height instead
                    h = (bottom - max(top, 0)) if top < 0 else (min(bottom, b.height()) - top)
                    w = h * self.aspect
                    if "n" in handle:
                        top = bottom - h
                    else:
                        bottom = top + h
                    if "w" in handle:
                        left = right - w
                    else:
                        right = left + w
            self.crop = QRectF(QPointF(left, top), QPointF(right, bottom)).intersected(b)
        self.update()
        self.changed.emit()


class ImageEditDialog(QDialog):
    """Crop / rotate / flip; *Apply* saves the result as a new file and returns its path."""

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path
        self.result_path = ""
        self.original = QImage(path)
        self.setWindowTitle(tr("ui.edit_image.title"))
        self.setMinimumSize(640, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(12)
        lay.addWidget(label(tr("ui.edit_image.title"), "h2"))
        self.view = CropView()
        self.view.changed.connect(self._update_info)
        lay.addWidget(self.view, 1)
        tools = QHBoxLayout()
        tools.setSpacing(6)
        self.aspect = QComboBox()
        for key, value in ASPECTS:
            self.aspect.addItem(tr(f"ui.edit_image.aspect_{key}"), value)
        self.aspect.currentIndexChanged.connect(lambda _: self.view.set_aspect(self.aspect.currentData()))
        tools.addWidget(self.aspect)
        self.rot_left = tool_button("rotate-ccw", tr("ui.edit_image.rotate_left"), 18)
        self.rot_left.clicked.connect(lambda: self.rotate(-90))
        self.rot_right = tool_button("rotate-ccw", tr("ui.edit_image.rotate_right"), 18)
        self.rot_right.setIcon(_mirrored(self.rot_right.icon()))
        self.rot_right.clicked.connect(lambda: self.rotate(90))
        self.flip_btn = tool_button("flip-horizontal-2", tr("ui.edit_image.flip"), 18)
        self.flip_btn.clicked.connect(self.flip)
        for b in (self.rot_left, self.rot_right, self.flip_btn):
            tools.addWidget(b)
        self.reset_btn = button(tr("ui.edit_image.reset"), None, "ghost")
        self.reset_btn.clicked.connect(self.reset)
        tools.addWidget(self.reset_btn)
        tools.addStretch(1)
        self.info = label("", "faint")
        tools.addWidget(self.info)
        lay.addLayout(tools)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = button(tr("ui.cancel"), None, "ghost")
        cancel.clicked.connect(self.reject)
        self.apply_btn = button(tr("ui.edit_image.apply"), "check", "primary")
        self.apply_btn.clicked.connect(self.apply)
        row.addWidget(cancel)
        row.addWidget(self.apply_btn)
        lay.addLayout(row)
        self.view.set_image(self.original)

    def _update_info(self):
        r = self.view.crop.toRect()
        self.info.setText(f"{r.width()} × {r.height()} px")

    def rotate(self, degrees: int):
        """Rotate the image and the crop rectangle with it."""
        img = self.view.image
        w, h = img.width(), img.height()
        c = self.view.crop
        if degrees == 90:
            crop = QRectF(h - c.bottom(), c.left(), c.height(), c.width())
        else:
            crop = QRectF(c.top(), w - c.right(), c.height(), c.width())
        self.view.crop = crop
        aspect = self.view.aspect
        self.view.aspect = 1 / aspect if aspect else None
        if aspect and aspect != 1.0:  # a 4:3 frame turns into 3:4
            self.aspect.blockSignals(True)
            self.aspect.setCurrentIndex(self.aspect.findData(self.view.aspect))
            self.aspect.blockSignals(False)
        self.view.set_image(img.transformed(QTransform().rotate(degrees)), keep_crop=True)

    def flip(self):
        img = self.view.image
        c = self.view.crop
        self.view.crop = QRectF(img.width() - c.right(), c.top(), c.width(), c.height())
        self.view.set_image(img.mirrored(True, False), keep_crop=True)

    def reset(self):
        self.aspect.setCurrentIndex(0)
        self.view.crop = QRectF()
        self.view.set_image(self.original)

    def edited_image(self) -> QImage:
        return self.view.image.copy(self.view.crop.toRect())

    def apply(self):
        folder = os.path.join(app_settings().get("output_dir"), "_edited")
        os.makedirs(folder, exist_ok=True)
        stem = os.path.splitext(os.path.basename(self.path))[0]
        path = os.path.join(folder, f"{stem}-edited-{time.strftime('%Y%m%d-%H%M%S')}.png")
        if not self.edited_image().save(path):
            return
        self.result_path = path
        self.accept()


def _mirrored(icon):
    from PySide6.QtGui import QIcon, QPixmap

    pm = icon.pixmap(36, 36)
    out = QIcon()
    out.addPixmap(QPixmap.fromImage(pm.toImage().mirrored(True, False)))
    return out
