"""Detail brush: paint over the photo where the sketch should have more detail (orange) or less (blue). CLIPasso and
ControlSketch put more start strokes where it is "more" and soften the picture where it is "less"
(``engine/details.py``). A face can be found and its eyes, nose and mouth marked by itself (portrait mode)."""

from __future__ import annotations

import numpy as np
from PIL import Image
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import QDialog, QHBoxLayout, QSizePolicy, QSlider, QVBoxLayout, QWidget

from ..engine import details
from ..engine.imaging import load_rgb
from .i18n import tr
from .widgets.common import SegmentedControl, button, label, tool_button

EDIT_SIDE = 1024  # the map is painted at most this large and scaled to the photo when it is saved
UNDO_STEPS = 30
TOOLS = {"more": 255, "normal": details.NORMAL, "less": 0}
MORE_RGB, LESS_RGB = (255, 140, 0), (40, 120, 255)


class DetailCanvas(QWidget):
    changed = Signal()

    def __init__(self, photo: Image.Image, values: np.ndarray | None = None, parent=None):
        super().__init__(parent)
        self.photo_pil = photo.convert("RGB")
        self.photo = QImage(self.photo_pil.tobytes(), photo.width, photo.height, 3 * photo.width,
                            QImage.Format_RGB888).copy()
        self.map = np.full((photo.height, photo.width), details.NORMAL, dtype=np.uint8) if values is None else \
            np.asarray(values, dtype=np.uint8).copy()
        self.tool = "more"
        self.brush = max(8, int(max(photo.size) * 0.06))
        self.undo_stack: list[bytes] = []
        self.redo_stack: list[bytes] = []
        self._hover: QPointF | None = None
        self._last: tuple[float, float] | None = None
        self._overlay = QImage()
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._rebuild()

    def sizeHint(self):  # noqa: N802
        return QSize(640, 480)

    def _view(self) -> tuple[QRectF, float]:
        s = min(self.width() / self.photo.width(), self.height() / self.photo.height())
        w, h = self.photo.width() * s, self.photo.height() * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h), s

    def to_image(self, p: QPointF) -> tuple[float, float]:
        v, s = self._view()
        return (p.x() - v.left()) / s, (p.y() - v.top()) / s

    # ------------------------------------------------------------------ editing
    def snapshot(self):
        self.undo_stack.append(self.map.tobytes())
        del self.undo_stack[:-UNDO_STEPS]
        self.redo_stack.clear()

    def _restore(self, data: bytes):
        self.map = np.frombuffer(data, dtype=np.uint8).reshape(self.map.shape).copy()
        self._rebuild()
        self.changed.emit()

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self.map.tobytes())
            self._restore(self.undo_stack.pop())

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self.map.tobytes())
            self._restore(self.redo_stack.pop())

    def set_map(self, values: np.ndarray, undoable: bool = True):
        if undoable:
            self.snapshot()
        self.map = np.asarray(values, dtype=np.uint8).copy()
        self._rebuild()
        self.changed.emit()

    def dab(self, x: float, y: float):
        """A round dab with a soft edge that moves the map towards the tool's value."""
        r = self.brush / 2
        h, w = self.map.shape
        x0, x1 = max(int(x - r - 1), 0), min(int(x + r + 2), w)
        y0, y1 = max(int(y - r - 1), 0), min(int(y + r + 2), h)
        if x0 >= x1 or y0 >= y1:
            return
        yy, xx = np.mgrid[y0:y1, x0:x1]
        d = np.sqrt((xx + 0.5 - x) ** 2 + (yy + 0.5 - y) ** 2) / max(r, 1e-6)
        a = np.clip((1.0 - d) / 0.35, 0.0, 1.0)  # full inside, a soft rim
        region = self.map[y0:y1, x0:x1].astype(np.float32)
        target = float(TOOLS[self.tool])
        moved = region + (target - region) * a
        self.map[y0:y1, x0:x1] = np.where(a > 0, np.round(moved), region).astype(np.uint8)

    def _line(self, a, b):
        dist = float(np.hypot(b[0] - a[0], b[1] - a[1]))
        steps = max(1, int(dist / max(self.brush * 0.25, 1)))
        for k in range(1, steps + 1):
            self.dab(a[0] + (b[0] - a[0]) * k / steps, a[1] + (b[1] - a[1]) * k / steps)

    def _rebuild(self):
        v = (self.map.astype(np.float32) - details.NORMAL) / 127.0
        more, less = np.clip(v, 0, 1), np.clip(-v, 0, 1)
        rgba = np.zeros(self.map.shape + (4,), dtype=np.uint8)
        for amount, rgb in ((more, MORE_RGB), (less, LESS_RGB)):
            on = amount > 0
            rgba[on, :3] = rgb
            rgba[on, 3] = np.round(amount[on] * 150).astype(np.uint8)
        self._overlay = QImage(rgba.tobytes(), rgba.shape[1], rgba.shape[0], 4 * rgba.shape[1],
                               QImage.Format_RGBA8888).copy()
        self.update()

    # ------------------------------------------------------------------ painting and mouse
    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        v, s = self._view()
        p.drawImage(v, self.photo)
        p.drawImage(v, self._overlay)
        if self._hover is not None:
            p.setPen(QPen(QColor(255, 255, 255, 220), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(self._hover, self.brush * s / 2, self.brush * s / 2)
            p.setPen(QPen(QColor(0, 0, 0, 160), 1))
            p.drawEllipse(self._hover, self.brush * s / 2 + 1.5, self.brush * s / 2 + 1.5)
        p.end()

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() != Qt.LeftButton:
            return
        self.snapshot()
        x, y = self.to_image(e.position())
        self.dab(x, y)
        self._last = (x, y)
        self._rebuild()
        self.changed.emit()

    def mouseMoveEvent(self, e):  # noqa: N802
        self._hover = e.position()
        if self._last is not None and e.buttons() & Qt.LeftButton:
            x, y = self.to_image(e.position())
            self._line(self._last, (x, y))
            self._last = (x, y)
            self._rebuild()
            self.changed.emit()
        self.update()

    def mouseReleaseEvent(self, e):  # noqa: N802
        self._last = None

    def leaveEvent(self, e):  # noqa: N802
        self._hover = None
        self.update()


class DetailEditDialog(QDialog):
    """Paint the detail map of an image; *Apply* stores it (an all-normal map removes it)."""

    def __init__(self, image_path: str, parent=None):
        super().__init__(parent)
        self.image = load_rgb(image_path)
        self.saved = False
        self.setWindowTitle(tr("ui.detail.title"))
        self.setMinimumSize(700, 600)
        photo = self.image.copy()
        photo.thumbnail((EDIT_SIDE, EDIT_SIDE))
        start = details.detail_map(self.image)
        values = None
        if start is not None:
            arr = np.clip(np.round(details.NORMAL + start * 127), 0, 255).astype(np.uint8)
            values = np.asarray(Image.fromarray(arr, mode="L").resize(photo.size, Image.BILINEAR))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(10)
        lay.addWidget(label(tr("ui.detail.title"), "h2"))
        lay.addWidget(label(tr("ui.detail.hint"), "faint", wrap=True))
        self.view = DetailCanvas(photo, values)
        self.view.changed.connect(self._update_info)
        lay.addWidget(self.view, 1)
        tools = QHBoxLayout()
        tools.setSpacing(8)
        self.tools = SegmentedControl([(k, tr(f"ui.detail.tool_{k}")) for k in TOOLS])
        self.tools.changed.connect(self.set_tool)
        tools.addWidget(self.tools)
        tools.addWidget(label(tr("ui.mask_edit.brush"), "muted"))
        self.size = QSlider(Qt.Horizontal)
        self.size.setRange(6, max(200, self.view.brush * 3))
        self.size.setValue(self.view.brush)
        self.size.setFixedWidth(130)
        self.size.valueChanged.connect(self._set_brush)
        tools.addWidget(self.size)
        self.undo_btn = tool_button("undo-2", tr("ui.eraser.undo"), 18)
        self.undo_btn.clicked.connect(self.view.undo)
        self.redo_btn = tool_button("redo-2", tr("ui.eraser.redo"), 18)
        self.redo_btn.clicked.connect(self.view.redo)
        tools.addWidget(self.undo_btn)
        tools.addWidget(self.redo_btn)
        self.face_btn = button(tr("ui.detail.face"), "scan", "ghost")
        self.face_btn.setToolTip(tr("ui.detail.face_tip"))
        self.face_btn.clicked.connect(self.find_face)
        tools.addWidget(self.face_btn)
        self.clear_btn = button(tr("ui.detail.clear"), None, "ghost")
        self.clear_btn.clicked.connect(self.clear)
        tools.addWidget(self.clear_btn)
        tools.addStretch(1)
        lay.addLayout(tools)
        row = QHBoxLayout()
        self.info = label("", "faint")
        row.addWidget(self.info, 1)
        cancel = button(tr("ui.cancel"), None, "ghost")
        cancel.clicked.connect(self.reject)
        self.apply_btn = button(tr("ui.detail.apply"), "check", "primary")
        self.apply_btn.clicked.connect(self.apply)
        row.addWidget(cancel)
        row.addWidget(self.apply_btn)
        lay.addLayout(row)
        for keys, fn in ((QKeySequence.Undo, self.view.undo), (QKeySequence.Redo, self.view.redo),
                         ("1", lambda: self.set_tool("more")), ("2", lambda: self.set_tool("normal")),
                         ("3", lambda: self.set_tool("less"))):
            QShortcut(QKeySequence(keys), self, activated=fn)
        self.set_tool("more")
        self._update_info()

    def set_tool(self, tool: str):
        self.view.tool = tool
        self.tools.set_current(tool)

    def _set_brush(self, value: int):
        self.view.brush = value
        self.view.update()

    def _update_info(self):
        v = self.view.map.astype(np.int16) - details.NORMAL
        more, less = float((v > 8).mean()), float((v < -8).mean())
        self.info.setText(tr("ui.detail.share", more=f"{more * 100:.0f}", less=f"{less * 100:.0f}"))
        self.undo_btn.setEnabled(bool(self.view.undo_stack))
        self.redo_btn.setEnabled(bool(self.view.redo_stack))

    def clear(self):
        self.view.set_map(np.full_like(self.view.map, details.NORMAL))

    def find_face(self) -> bool:
        """Portrait mode: the face is found and its eyes, nose and mouth are marked "more"."""
        from . import portrait

        values = portrait.detail_for(self.view.photo_pil, self)
        if values is None:
            self.info.setText(tr("ui.detail.no_face"))
            return False
        merged = np.maximum(self.view.map.astype(np.int16), values.astype(np.int16))
        self.view.set_map(merged.astype(np.uint8))
        return True

    def apply(self):
        full = np.asarray(Image.fromarray(self.view.map, mode="L").resize(self.image.size, Image.BILINEAR))
        details.save_detail_map(self.image, full)
        self.saved = True
        self.accept()
