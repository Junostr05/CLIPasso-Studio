"""First-start guide: a short tour that dims the window except one part at a time and explains it.

Shown once after a new installation; "Show the guide" on the About page opens it again.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPainterPath, QPen, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QWidget

from . import theme
from .i18n import tr
from .widgets.common import Card, button, label

# (text key, page to show first or None, the widgets to highlight)
STEPS = (
    ("methods", "studio", lambda w: [w.studio.picker]),
    ("input", "studio", lambda w: [w.studio.input_card]),
    ("params", "studio", lambda w: [w.studio.params]),
    ("start", "studio", lambda w: [w.studio.start_btn, w.studio.queue_btn]),
    ("result", "studio", lambda w: [w.studio.result_card]),
    ("gallery", None, lambda w: [w.nav_buttons["gallery"], w.nav_buttons["queue"]]),
    ("models", None, lambda w: [w.nav_buttons["models"], w.nav_buttons["settings"]]),
)
PAD = 8  # space around the highlighted part
GAP = 16  # between the highlight and the card


class Tour(QWidget):
    """The overlay over the main window; ``finished(completed)`` when it closes."""

    finished = Signal(bool)

    def __init__(self, window):
        super().__init__(window)
        self.window_ = window
        self.index = 0
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setFocusPolicy(Qt.StrongFocus)
        self.card = Card(self, margins=18, spacing=10)
        self.card.setFixedWidth(360)
        self.step_label = label("", "faint")
        self.title = label("", "h2")
        self.text = label("", "muted", wrap=True)
        self.card.body.addWidget(self.step_label)
        self.card.body.addWidget(self.title)
        self.card.body.addWidget(self.text)
        row = QHBoxLayout()
        self.skip_btn = button(tr("ui.tour.skip"), None, "ghost")
        self.skip_btn.clicked.connect(lambda: self.close_tour(False))
        self.back_btn = button(tr("ui.tour.back"), None, "ghost")
        self.back_btn.clicked.connect(self.back)
        self.next_btn = button("", None, "primary")
        self.next_btn.clicked.connect(self.next)
        row.addWidget(self.skip_btn)
        row.addStretch(1)
        row.addWidget(self.back_btn)
        row.addWidget(self.next_btn)
        self.card.body.addLayout(row)
        for keys, fn in (("Escape", lambda: self.close_tour(False)), ("Right", self.next), ("Left", self.back),
                         ("Return", self.next)):
            QShortcut(QKeySequence(keys), self, activated=fn)
        window.installEventFilter(self)
        self.setGeometry(window.rect())
        self.show()
        self.raise_()
        self.setFocus()
        self.go(0)

    # ------------------------------------------------------------------ steps
    def go(self, index: int):
        self.index = max(0, min(index, len(STEPS) - 1))
        key, page, _ = STEPS[self.index]
        if page:
            self.window_.show_page(page)
        self.step_label.setText(tr("ui.tour.step", n=self.index + 1, total=len(STEPS)))
        self.title.setText(tr(f"ui.tour.{key}.title"))
        self.text.setText(tr(f"ui.tour.{key}.text"))
        last = self.index == len(STEPS) - 1
        self.next_btn.setText(tr("ui.tour.done") if last else tr("ui.tour.next"))
        self.back_btn.setEnabled(self.index > 0)
        self.card.adjustSize()
        self._place()

    def next(self):
        if self.index >= len(STEPS) - 1:
            self.close_tour(True)
        else:
            self.go(self.index + 1)

    def back(self):
        self.go(self.index - 1)

    def close_tour(self, completed: bool):
        self.window_.removeEventFilter(self)
        self.hide()
        self.finished.emit(completed)
        self.deleteLater()

    # --------------------------------------------------------------- geometry
    def target_rect(self) -> QRect:
        """The highlighted area in the window's coordinates (empty if nothing is visible)."""
        rect = QRect()
        for wdg in STEPS[self.index][2](self.window_):
            if wdg is not None and wdg.isVisible() and wdg.width() > 0:
                rect = rect.united(QRect(wdg.mapTo(self.window_, QPoint(0, 0)), wdg.size()))
        return rect.adjusted(-PAD, -PAD, PAD, PAD) if not rect.isNull() else rect

    def _place(self):
        self.setGeometry(self.window_.rect())
        target, area = self.target_rect(), self.rect().adjusted(12, 12, -12, -12)
        w, h = self.card.width(), self.card.sizeHint().height()
        self.card.resize(w, h)
        if target.isNull():
            pos = QPoint(area.center().x() - w // 2, area.center().y() - h // 2)
        elif target.right() + GAP + w <= area.right():  # right of it
            pos = QPoint(target.right() + GAP, target.top())
        elif target.left() - GAP - w >= area.left():  # left of it
            pos = QPoint(target.left() - GAP - w, target.top())
        elif target.bottom() + GAP + h <= area.bottom():  # below
            pos = QPoint(target.left(), target.bottom() + GAP)
        else:  # above, or over it
            pos = QPoint(target.left(), max(area.top(), target.top() - GAP - h))
        pos.setX(min(max(pos.x(), area.left()), area.right() - w))
        pos.setY(min(max(pos.y(), area.top()), area.bottom() - h))
        self.card.move(pos)
        self.update()

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self.window_ and event.type() in (QEvent.Resize, QEvent.LayoutRequest):
            self._place()
        return False

    # ------------------------------------------------------------- painting
    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        shade = QPainterPath()
        shade.setFillRule(Qt.OddEvenFill)
        shade.addRect(QRectF(self.rect()))
        target = self.target_rect()
        if not target.isNull():
            shade.addRoundedRect(QRectF(target), theme.RADIUS_CARD, theme.RADIUS_CARD)
        p.fillPath(shade, QColor(0, 0, 0, 165))
        if not target.isNull():
            p.setPen(QPen(QColor(theme.current().accent), 2))
            p.drawRoundedRect(QRectF(target), theme.RADIUS_CARD, theme.RADIUS_CARD)
        p.end()

    def mousePressEvent(self, e):  # noqa: N802
        e.accept()  # the window below waits until the guide is closed
