"""Reusable UI building blocks."""

from __future__ import annotations

from PySide6.QtCore import (Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, QTimer, Signal)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from .. import icons, theme


def label(text: str = "", role: str | None = None, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if role:
        lbl.setProperty("role", role)
    lbl.setWordWrap(wrap)
    return lbl


def set_role(widget: QWidget, role: str) -> None:
    widget.setProperty("role", role)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def button(text: str = "", icon_name: str | None = None, variant: str | None = None, size: str | None = None,
           icon_color: str | None = None) -> QPushButton:
    btn = QPushButton(text)
    if variant:
        btn.setProperty("variant", variant)
    if size:
        btn.setProperty("size", size)
    if icon_name:
        p = theme.current()
        color = icon_color or (p.on_accent if variant == "primary" else p.text)
        btn.setIcon(icons.icon(icon_name, color))
        btn.setIconSize(QSize(16, 16))
    btn.setCursor(Qt.PointingHandCursor)
    return btn


def tool_button(icon_name: str, tooltip: str = "", size: int = 16, checkable: bool = False,
                color: str | None = None) -> QToolButton:
    btn = QToolButton()
    btn.setIcon(icons.icon(icon_name, color or theme.current().muted, active_color=theme.current().text))
    btn.setIconSize(QSize(size, size))
    btn.setToolTip(tooltip)
    btn.setCheckable(checkable)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setAutoRaise(True)
    return btn


class Card(QFrame):
    def __init__(self, parent=None, flat: bool = False, margins: int = 16, spacing: int = 12):
        super().__init__(parent)
        self.setObjectName("CardFlat" if flat else "Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(margins, margins, margins, margins)
        self.body.setSpacing(spacing)


class Divider(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("Divider")
        self.setFrameShape(QFrame.NoFrame)


class ToggleSwitch(QAbstractButton):
    """Animated on/off switch."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(38, 22)
        self._pos = 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def _animate(self, checked: bool):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def setChecked(self, checked: bool) -> None:  # noqa: N802 - Qt API
        super().setChecked(checked)
        self._anim.stop()
        self._pos = 1.0 if checked else 0.0
        self.update()

    def get_knob(self) -> float:
        return self._pos

    def set_knob(self, value: float) -> None:
        self._pos = value
        self.update()

    knob = Property(float, get_knob, set_knob)

    def sizeHint(self):  # noqa: N802
        return QSize(38, 22)

    def paintEvent(self, event):  # noqa: N802
        p = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        track_off = QColor(p.surface3 if p.name == "dark" else "#C9CFDB")
        track_on = QColor(p.accent)
        t = self._pos
        track = QColor(
            int(track_off.red() + (track_on.red() - track_off.red()) * t),
            int(track_off.green() + (track_on.green() - track_off.green()) * t),
            int(track_off.blue() + (track_on.blue() - track_off.blue()) * t),
        )
        if not self.isEnabled():
            track.setAlpha(110)
        painter.setPen(Qt.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 11, 11)
        knob = QColor("#FFFFFF")
        if not self.isEnabled():
            knob.setAlpha(170)
        painter.setBrush(knob)
        x = 3 + t * (self.width() - 22)
        painter.drawEllipse(QRectF(x, 3, 16, 16))


class SegmentedControl(QFrame):
    """A row of exclusive toggle buttons."""

    changed = Signal(str)

    def __init__(self, items: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.setObjectName("SegmentBar")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for key, text in items:
            b = QPushButton(text)
            b.setObjectName("Segment")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self._group.addButton(b)
            lay.addWidget(b)
            self._buttons[key] = b
            self._fit(b)
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
        if items:
            self._buttons[items[0][0]].setChecked(True)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def set_current(self, key: str) -> None:
        if key in self._buttons:
            self._buttons[key].setChecked(True)

    def clear_selection(self) -> None:
        self._group.setExclusive(False)
        for b in self._buttons.values():
            b.setChecked(False)
        self._group.setExclusive(True)

    def current(self) -> str:
        for k, b in self._buttons.items():
            if b.isChecked():
                return k
        return ""

    def set_text(self, key: str, text: str) -> None:
        if key in self._buttons:
            self._buttons[key].setText(text)
            self._fit(self._buttons[key])

    @staticmethod
    def _fit(b: QPushButton) -> None:
        """Wide enough for the label in the bold font of the checked state (padding 12 px each side)."""
        f = QFont(b.font())
        f.setWeight(QFont.Weight.DemiBold)
        b.setMinimumWidth(QFontMetrics(f).horizontalAdvance(b.text()) + 28)

    def set_enabled(self, key: str, enabled: bool) -> None:
        if key in self._buttons:
            self._buttons[key].setEnabled(enabled)

    def set_visible(self, key: str, visible: bool) -> None:
        if key in self._buttons:
            self._buttons[key].setVisible(visible)


class CollapsibleSection(QWidget):
    """Header with chevron that shows/hides its content."""

    toggled = Signal(bool)

    def __init__(self, title: str, icon_name: str | None = None, expanded: bool = False, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.header = QPushButton()
        self.header.setObjectName("SectionHeader")
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        p = theme.current()
        self.header.setStyleSheet(
            f"QPushButton#SectionHeader {{ text-align: left; background: transparent; border: none;"
            f" padding: 10px 4px; font-weight: 600; font-size: 13px; }}"
            f"QPushButton#SectionHeader:hover {{ color: {p.accent_hover}; }}")
        self._icon_name = icon_name
        self.set_title(title)
        outer.addWidget(self.header)
        self.content = QWidget()
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(4, 2, 4, 12)
        self.body.setSpacing(12)
        outer.addWidget(self.content)
        self.content.setVisible(expanded)
        self.header.toggled.connect(self._on_toggle)
        self._update_icon()

    def set_title(self, title: str) -> None:
        self.header.setText("  " + title.replace("&", "&&"))

    def _update_icon(self):
        p = theme.current()
        name = "chevron-down" if self.header.isChecked() else "chevron-right"
        self.header.setIcon(icons.icon(name, p.muted))
        self.header.setIconSize(QSize(14, 14))

    def _on_toggle(self, checked: bool):
        self.content.setVisible(checked)
        self._update_icon()
        self.toggled.emit(checked)

    def set_expanded(self, expanded: bool) -> None:
        self.header.setChecked(expanded)


class Toast(QFrame):
    """Transient message in the bottom right corner of its parent."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("Card")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(10)
        self.icon = QLabel()
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setMaximumWidth(380)
        lay.addWidget(self.icon)
        lay.addWidget(self.text)
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(250)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._hide)
        self.hide()

    def show_message(self, text: str, kind: str = "info", msec: int = 4000) -> None:
        p = theme.current()
        name, color = {"success": ("circle-check", p.success), "error": ("circle-x", p.danger),
                       "warning": ("triangle-alert", p.warning)}.get(kind, ("info", p.accent_hover))
        self.icon.setPixmap(icons.pixmap(name, color, 18))
        self.text.setText(text)
        self.adjustSize()
        par = self.parentWidget()
        self.move(par.width() - self.width() - 24, par.height() - self.height() - 24)
        self.raise_()
        self.show()
        self._fade.stop()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._timer.start(msec)

    def _hide(self):
        self._fade.stop()
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self._after_fade)
        self._fade.start()

    def _after_fade(self):
        try:
            self._fade.finished.disconnect(self._after_fade)
        except (RuntimeError, TypeError):
            pass
        self.hide()


class Banner(QFrame):
    """Inline notice with an optional action button (missing models, hardware hints)."""

    action = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Banner")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 8, 8)
        lay.setSpacing(10)
        self.icon = QLabel()
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.button = QPushButton()
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.setProperty("variant", "primary")
        self.button.clicked.connect(self.action.emit)
        lay.addWidget(self.icon, 0, Qt.AlignTop)
        lay.addWidget(self.text, 1)
        lay.addWidget(self.button, 0, Qt.AlignVCenter)
        self.hide()

    def show_message(self, text: str, warn: bool = False, button_text: str | None = None,
                     icon_name: str | None = None) -> None:
        p = theme.current()
        self.setObjectName("BannerWarn" if warn else "Banner")
        self.style().unpolish(self)
        self.style().polish(self)
        name = icon_name or ("triangle-alert" if warn else "info")
        self.icon.setPixmap(icons.pixmap(name, p.warning if warn else p.accent_hover, 18))
        self.text.setText(text)
        self.button.setVisible(bool(button_text))
        if button_text:
            self.button.setText(button_text)
            self.button.setIcon(icons.icon("download", p.on_accent))
        self.show()


def hbox(*widgets, spacing: int = 8, margins=(0, 0, 0, 0), stretch_at: int | None = None) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    for i, w in enumerate(widgets):
        if stretch_at is not None and i == stretch_at:
            lay.addStretch(1)
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, QWidget):
            lay.addWidget(w)
        else:
            lay.addLayout(w)
    return lay


def vbox(*widgets, spacing: int = 8, margins=(0, 0, 0, 0)) -> QVBoxLayout:
    lay = QVBoxLayout()
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    for w in widgets:
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, QWidget):
            lay.addWidget(w)
        else:
            lay.addLayout(w)
    return lay
