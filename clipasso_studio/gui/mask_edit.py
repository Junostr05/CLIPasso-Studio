"""Touch up the object mask before sketching: click parts to remove or add them, or paint with a brush.

The edited mask is stored per image content (``masking.save_edited_mask``) and every method uses it
instead of the mask model.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import QDialog, QHBoxLayout, QSizePolicy, QSlider, QVBoxLayout, QWidget

from ..engine import masking
from ..engine.imaging import load_rgb
from . import theme
from .i18n import tr
from .mask_view import overlay
from .widgets.common import SegmentedControl, button, label, tool_button

CANDIDATE = 0.15  # probability from which a part the mask left out can be added with a click
PICK_SIDE = 512  # connected parts are found on a copy of at most this size
WAND_TOLERANCE = 54  # magic wand: summed RGB difference to the clicked colour
UNDO_STEPS = 30


def _grow_and_scale(part: np.ndarray, w: int, h: int) -> np.ndarray:
    grown = part.copy()  # one reduced pixel around it, so the edge is covered at full size
    grown[1:] |= part[:-1]
    grown[:-1] |= part[1:]
    grown[:, 1:] |= part[:, :-1]
    grown[:, :-1] |= part[:, 1:]
    return np.asarray(Image.fromarray(grown.astype(np.uint8) * 255).resize((w, h), Image.NEAREST)) == 255


def wand(photo: Image.Image, size: tuple[int, int], x: int, y: int, tolerance: int = WAND_TOLERANCE) -> np.ndarray:
    """Magic wand: the connected area of colours similar to the clicked one (on a reduced, slightly
    smoothed copy of the photo), as a mask of ``size`` (w, h)."""
    w, h = size
    f = min(1.0, PICK_SIDE / max(w, h))
    sw, sh = max(1, round(w * f)), max(1, round(h * f))
    small = photo.convert("RGB").resize((sw, sh), Image.BILINEAR).filter(ImageFilter.MedianFilter(3))
    sx, sy = min(sw - 1, int(x * f)), min(sh - 1, int(y * f))
    marker = (255, 0, 255) if small.getpixel((sx, sy)) != (255, 0, 255) else (0, 255, 0)
    before = np.asarray(small).copy()
    ImageDraw.floodfill(small, (sx, sy), marker, thresh=tolerance)
    after = np.asarray(small)
    part = np.any(after != before, axis=2)
    part[sy, sx] = True
    return _grow_and_scale(part, w, h)


def _component(mask: np.ndarray, x: int, y: int) -> np.ndarray:
    """The 4-connected part of ``mask`` (bool) containing pixel (x, y), found on a reduced copy and
    scaled back (slightly grown, so its edge is covered)."""
    h, w = mask.shape
    f = min(1.0, PICK_SIDE / max(h, w))
    sw, sh = max(1, round(w * f)), max(1, round(h * f))
    small = Image.fromarray(mask.astype(np.uint8) * 255).resize((sw, sh), Image.NEAREST)
    sx, sy = min(sw - 1, int(x * f)), min(sh - 1, int(y * f))
    if small.getpixel((sx, sy)) != 255:
        return np.zeros_like(mask)
    ImageDraw.floodfill(small, (sx, sy), 128)
    return _grow_and_scale(np.asarray(small) == 128, w, h)


class MaskCanvas(QWidget):
    """The photo with the excluded area veiled; click parts or paint to change the mask."""

    changed = Signal()
    missed = Signal()  # a click found nothing to add or remove

    def __init__(self, photo: QImage, mask: np.ndarray, candidate: np.ndarray, source: Image.Image | None = None,
                 parent=None):
        super().__init__(parent)
        self.source = source  # the photo for the magic wand (any size)
        self.setMinimumSize(420, 320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.photo = photo
        self.mask = mask.astype(bool)
        self.candidate = candidate.astype(bool) | self.mask
        self.tool = "part"
        self.brush = 40  # brush diameter in screen pixels
        self.undo_stack: list[bytes] = []
        self.redo_stack: list[bytes] = []
        self._painting = False
        self._last: QPointF | None = None
        self._hover: QPointF | None = None
        self._overlay = QImage()
        self._dirty = True
        self._refresh = QTimer(self)
        self._refresh.setSingleShot(True)
        self._refresh.setInterval(40)
        self._refresh.timeout.connect(self._rebuild)

    def sizeHint(self):  # noqa: N802
        return QSize(760, 560)

    # ------------------------------------------------------------- geometry
    def _view(self) -> tuple[QRectF, float]:
        m = 12
        s = min((self.width() - 2 * m) / self.photo.width(), (self.height() - 2 * m) / self.photo.height())
        w, h = self.photo.width() * s, self.photo.height() * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h), s

    def to_image(self, p: QPointF) -> tuple[float, float]:
        v, s = self._view()
        sx = self.mask.shape[1] / self.photo.width()  # the photo may be shown smaller than the mask
        return (p.x() - v.left()) / s * sx, (p.y() - v.top()) / s * sx

    def _radius(self) -> float:
        _, s = self._view()
        return self.brush / 2 / s * self.mask.shape[1] / self.photo.width()

    # ---------------------------------------------------------------- edits
    def _snapshot(self):
        self.undo_stack.append(np.packbits(self.mask).tobytes())
        del self.undo_stack[:-UNDO_STEPS]
        self.redo_stack.clear()

    def _restore(self, data: bytes) -> np.ndarray:
        bits = np.unpackbits(np.frombuffer(data, dtype=np.uint8), count=self.mask.size)
        return bits.reshape(self.mask.shape).astype(bool)

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(np.packbits(self.mask).tobytes())
            self.mask = self._restore(self.undo_stack.pop())
            self._changed()

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(np.packbits(self.mask).tobytes())
            self.mask = self._restore(self.redo_stack.pop())
            self._changed()

    def set_mask(self, mask: np.ndarray, undoable: bool = True):
        if undoable:
            self._snapshot()
        self.mask = mask.astype(bool)
        self._changed()

    def click_part(self, x: float, y: float) -> bool:
        """Inside the mask: remove the part under the cursor. Outside: add the part of the candidate
        map (what the mask model was less sure about) – or, where the model saw nothing, the area of
        similar colours (magic wand). False when there is nothing to change."""
        h, w = self.mask.shape
        xi, yi = int(x), int(y)
        if not (0 <= xi < w and 0 <= yi < h):
            return False
        if self.mask[yi, xi]:
            self._snapshot()
            self.mask &= ~_component(self.mask, xi, yi)
        elif self.candidate[yi, xi]:
            self._snapshot()
            self.mask |= _component(self.candidate, xi, yi) & self.candidate
        elif self.source is not None:
            self._snapshot()
            self.mask |= wand(self.source, (w, h), xi, yi)
        else:
            return False
        self._changed()
        return True

    def dab(self, x: float, y: float, value: bool):
        """One brush dab (a disc of the brush size) at image position (x, y)."""
        r = self._radius()
        h, w = self.mask.shape
        x0, x1 = max(0, int(x - r)), min(w, int(x + r) + 1)
        y0, y1 = max(0, int(y - r)), min(h, int(y + r) + 1)
        if x0 >= x1 or y0 >= y1:
            return
        yy, xx = np.ogrid[y0:y1, x0:x1]
        disc = (xx - x) ** 2 + (yy - y) ** 2 <= r * r
        self.mask[y0:y1, x0:x1][disc] = value

    def _line(self, a: tuple[float, float], b: tuple[float, float], value: bool):
        step = max(1.0, self._radius() / 2)
        n = max(1, int(np.hypot(b[0] - a[0], b[1] - a[1]) / step))
        for i in range(1, n + 1):
            t = i / n
            self.dab(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, value)

    def _changed(self):
        self._dirty = True
        self._refresh.start()
        self.changed.emit()

    def _rebuild(self):
        pal = theme.current()
        self._overlay = overlay(self.mask, QColor(150, 20, 40, 150), QColor(pal.accent), max_side=1200)
        self._dirty = False
        self.update()

    # ------------------------------------------------------------- painting
    def paintEvent(self, event):  # noqa: N802
        if self._dirty and not self._refresh.isActive():
            self._rebuild()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        v, s = self._view()
        p.drawImage(v, self.photo)
        if not self._overlay.isNull():
            p.drawImage(v, self._overlay)
        if self._hover is not None and self.tool in ("add", "erase"):
            p.setPen(QPen(QColor(255, 255, 255, 220), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(self._hover, self.brush / 2, self.brush / 2)
            p.setPen(QPen(QColor(0, 0, 0, 160), 1))
            p.drawEllipse(self._hover, self.brush / 2 + 1.5, self.brush / 2 + 1.5)
        p.end()

    # ---------------------------------------------------------------- mouse
    def mousePressEvent(self, e):  # noqa: N802
        if e.button() != Qt.LeftButton:
            return
        x, y = self.to_image(e.position())
        if self.tool == "part":
            if not self.click_part(x, y):
                self.missed.emit()
            return
        self._snapshot()
        self._painting = True
        self._last = QPointF(x, y)
        self.dab(x, y, self.tool == "add")
        self._changed()

    def mouseMoveEvent(self, e):  # noqa: N802
        self._hover = e.position()
        self.setCursor(Qt.PointingHandCursor if self.tool == "part" else Qt.BlankCursor)
        if self._painting and self._last is not None:
            x, y = self.to_image(e.position())
            self._line((self._last.x(), self._last.y()), (x, y), self.tool == "add")
            self._last = QPointF(x, y)
            self._changed()
        else:
            self.update()

    def mouseReleaseEvent(self, e):  # noqa: N802
        self._painting = False
        self._last = None

    def leaveEvent(self, e):  # noqa: N802
        self._hover = None
        self.update()


class MaskEditDialog(QDialog):
    """Edit the object mask of an image; *Apply* stores it (or removes the edit when it equals the
    automatic mask)."""

    def __init__(self, image_path: str, prob: np.ndarray, edited: np.ndarray | None = None, parent=None):
        super().__init__(parent)
        self.image = load_rgb(image_path)
        self.prob = prob
        self.auto = prob >= masking.OBJECT_THRESHOLD
        self.saved = False
        self.setWindowTitle(tr("ui.mask_edit.title"))
        self.setMinimumSize(700, 600)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(10)
        lay.addWidget(label(tr("ui.mask_edit.title"), "h2"))
        lay.addWidget(label(tr("ui.mask_edit.hint"), "faint", wrap=True))
        photo = self.image.copy()
        photo.thumbnail((1600, 1600))
        qphoto = QImage(photo.tobytes(), photo.width, photo.height, 3 * photo.width, QImage.Format_RGB888).copy()
        start = edited if edited is not None else self.auto
        self.view = MaskCanvas(qphoto, start, prob >= CANDIDATE, photo)
        self.view.changed.connect(self._update_info)
        self.view.missed.connect(lambda: self.info.setText(tr("ui.mask_edit.nothing_here")))
        lay.addWidget(self.view, 1)

        tools = QHBoxLayout()
        tools.setSpacing(8)
        self.tools = SegmentedControl([("part", tr("ui.mask_edit.tool_part")), ("add", tr("ui.mask_edit.tool_add")),
                                       ("erase", tr("ui.mask_edit.tool_erase"))])
        self.tools.changed.connect(self.set_tool)
        tools.addWidget(self.tools)
        self.size_label = label(tr("ui.mask_edit.brush"), "muted")
        tools.addWidget(self.size_label)
        self.size = QSlider(Qt.Horizontal)
        self.size.setRange(6, 160)
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
        self.reset_btn = button(tr("ui.mask_edit.reset"), None, "ghost")
        self.reset_btn.setToolTip(tr("ui.mask_edit.reset_tip"))
        self.reset_btn.clicked.connect(self.reset)
        tools.addWidget(self.reset_btn)
        tools.addStretch(1)
        lay.addLayout(tools)

        row = QHBoxLayout()
        self.info = label("", "faint")
        row.addWidget(self.info, 1)
        cancel = button(tr("ui.cancel"), None, "ghost")
        cancel.clicked.connect(self.reject)
        self.apply_btn = button(tr("ui.mask_edit.apply"), "check", "primary")
        self.apply_btn.clicked.connect(self.apply)
        row.addWidget(cancel)
        row.addWidget(self.apply_btn)
        lay.addLayout(row)
        for keys, fn in ((QKeySequence.Undo, self.view.undo), (QKeySequence.Redo, self.view.redo),
                         ("Ctrl+Shift+Z", self.view.redo), ("[", lambda: self._step(-1)), ("]", lambda: self._step(1)),
                         ("1", lambda: self.set_tool("part")), ("2", lambda: self.set_tool("add")),
                         ("3", lambda: self.set_tool("erase"))):
            QShortcut(QKeySequence(keys), self, activated=fn)
        self.set_tool("part")
        self._update_info()

    def set_tool(self, tool: str):
        self.view.tool = tool
        self.tools.set_current(tool)
        brush = tool in ("add", "erase")
        self.size_label.setEnabled(brush)
        self.size.setEnabled(brush)
        self.view.update()

    def _set_brush(self, value: int):
        self.view.brush = value
        self.view.update()

    def _step(self, direction: int):
        self.size.setValue(int(self.size.value() * (1.25 if direction > 0 else 0.8)) + direction)

    def _update_info(self):
        share = float(self.view.mask.mean())
        self.apply_btn.setEnabled(share > 0)
        self.undo_btn.setEnabled(bool(self.view.undo_stack))
        self.redo_btn.setEnabled(bool(self.view.redo_stack))
        self.info.setText(tr("ui.mask_edit.share", pct=f"{share * 100:.0f}") if share > 0
                          else tr("ui.mask_edit.empty"))

    def reset(self):
        self.view.set_mask(self.auto)

    def apply(self):
        if not self.view.mask.any():
            return
        if np.array_equal(self.view.mask, self.auto):
            masking.remove_edited_mask(self.image)
        else:
            masking.save_edited_mask(self.image, self.view.mask)
        self.saved = True
        self.accept()
