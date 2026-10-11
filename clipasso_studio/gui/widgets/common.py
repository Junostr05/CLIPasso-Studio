"""Reusable UI building blocks."""

from __future__ import annotations

from PySide6.QtCore import (Property, QEasingCurve, QEvent, QObject, QPropertyAnimation, QRectF, QSize, Qt, QTimer,
                            Signal)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QFrame, QGraphicsOpacityEffect, QGridLayout, QHBoxLayout,
                               QLabel, QLayout, QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from .. import icons, theme


LABEL_SPACING = 0.66  # px: the 0.06 em letter spacing of the role "label" at 11 px


def label(text: str = "", role: str | None = None, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if role:
        lbl.setProperty("role", role)
    if role == "label":  # 4.0: step labels ("1 · BILD") – capitals and spacing, which a Qt style sheet cannot set
        font = lbl.font()
        font.setCapitalization(QFont.AllUppercase)
        font.setLetterSpacing(QFont.AbsoluteSpacing, LABEL_SPACING)
        lbl.setFont(font)
    lbl.setWordWrap(wrap)
    return lbl


class ElidedLabel(QLabel):
    """One line that ends in "…" when it does not fit (a status line, a name); the whole text is then its tooltip.
    Screen readers get the whole text (``text()``)."""

    def __init__(self, text: str = "", role: str | None = None, parent=None):
        super().__init__(text, parent)
        if role:
            self.setProperty("role", role)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, super().minimumSizeHint().height())

    def setText(self, text: str) -> None:  # noqa: N802
        super().setText(text)
        self._update_tip()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_tip()

    def _shown(self) -> str:
        return self.fontMetrics().elidedText(self.text(), Qt.ElideRight, max(0, self.contentsRect().width()))

    def _update_tip(self) -> None:
        self.setToolTip(self.text() if self.text() and self._shown() != self.text() else "")

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        self.style().drawItemText(p, self.contentsRect(), int(self.alignment()), self.palette(), self.isEnabled(),
                                  self._shown(), self.foregroundRole())


def set_role(widget: QWidget, role: str) -> None:
    set_prop(widget, "role", role)


def set_prop(widget: QWidget, name: str, value) -> None:
    """A dynamic property the style sheet styles (``role``, ``state``, ``changed`` …), applied at once."""
    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


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


def link_button(text: str = "", icon_name: str | None = None) -> QPushButton:
    """4.0: an action that reads as a link (*Anpassen*, *Details*, *Methoden vergleichen …*) – the accent as text."""
    btn = button(text, variant="link")
    if icon_name:
        btn.setIcon(icons.icon(icon_name, theme.current().accent_text))
        btn.setIconSize(QSize(14, 14))
    btn.setProperty("ring_radius", theme.RADIUS_PROGRESS)
    return btn


class RovingFocus(QObject):
    """4.0: one Tab stop for a group of choices (method cards, segments, sketches) – the keyboard pattern of a
    radio group. Tab reaches the chosen item (or the first one), the arrow keys, Home and End move to the
    neighbour and choose it (``choose(widget)``), Space and Enter choose the focused item. Items that are not
    buttons get the focus by Tab; buttons press themselves on Space."""

    NEXT = {Qt.Key_Right: 1, Qt.Key_Down: 1, Qt.Key_Left: -1, Qt.Key_Up: -1}

    def __init__(self, parent: QObject, choose):
        super().__init__(parent)
        self._choose = choose
        self.items: list[QWidget] = []
        self.current: QWidget | None = None

    def add(self, widget: QWidget) -> None:
        self.items.append(widget)
        widget.installEventFilter(self)
        self.update()

    def remove(self, widget: QWidget) -> None:
        if widget in self.items:
            self.items.remove(widget)
            widget.removeEventFilter(self)
        if self.current is widget:
            self.current = None
        self.update()

    def set_current(self, widget: QWidget | None) -> None:
        self.current = widget
        self.update()

    def reachable(self) -> list[QWidget]:
        return [w for w in self.items if not w.isHidden() and w.isEnabled()]

    def update(self) -> None:
        """Only the chosen item is a Tab stop (a click still focuses the others)."""
        reach = self.reachable()
        stop = self.current if self.current in reach else (reach[0] if reach else None)
        for w in self.items:
            w.setFocusPolicy(Qt.StrongFocus if w is stop else Qt.ClickFocus)

    def eventFilter(self, obj, event):  # noqa: N802
        t = event.type()
        if t == QEvent.KeyPress and obj in self.items and not (
                event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)):
            key = event.key()
            reach = self.reachable()
            if obj in reach and (key in self.NEXT or key in (Qt.Key_Home, Qt.Key_End)):
                if key == Qt.Key_Home:
                    target = reach[0]
                elif key == Qt.Key_End:
                    target = reach[-1]
                else:
                    target = reach[(reach.index(obj) + self.NEXT[key]) % len(reach)]
                if target is not obj:
                    self._choose(target)
                    target.setFocus(Qt.TabFocusReason)
                return True
            if key in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter) and not isinstance(obj, QAbstractButton):
                self._choose(obj)
                return True
        elif t in (QEvent.ShowToParent, QEvent.HideToParent, QEvent.EnabledChange) and obj in self.items:
            self.update()
        return False


class CountBadge(QLabel):
    """4.0: a number next to a name (*Warteschlange 2*): hidden at 0."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("role", "count")
        self.setAlignment(Qt.AlignCenter)
        self.set_count(0)

    def set_count(self, n: int) -> None:
        self.count = n
        self.setText(str(n) if n < 100 else "99+")
        self.setVisible(n > 0)


class Chip(QFrame):
    """4.0: a small piece of state with an icon – the hardware in the header (*Prozessor · 8 Kerne*), a running
    job. ``framed`` gives it a pill of its own; its text ends in "…" when it does not fit."""

    def __init__(self, icon_name: str | None = None, text: str = "", framed: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("Chip")
        self.setProperty("framed", "true" if framed else "false")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(*((10, 4, 10, 4) if framed else (0, 0, 0, 0)))
        lay.setSpacing(6)
        self.icon = QLabel()
        self.text = ElidedLabel(text, "muted")
        lay.addWidget(self.icon)
        lay.addWidget(self.text, 1)
        self.icon_name = None
        self.set_icon(icon_name)

    def set_icon(self, name: str | None, color: str | None = None) -> None:
        self.icon_name = name
        self.icon.setVisible(bool(name))
        if name:
            self.icon.setPixmap(icons.pixmap(name, color or theme.current().muted, 16))

    def set_text(self, text: str) -> None:
        self.text.setText(text)

    def sizeHint(self) -> QSize:  # noqa: N802 - the whole text when there is room (the label alone is elastic)
        m = self.layout().contentsMargins()
        w = self.text.fontMetrics().horizontalAdvance(self.text.text()) + m.left() + m.right() + 2
        if self.icon.isVisibleTo(self):
            w += 16 + self.layout().spacing()
        return QSize(w, super().sizeHint().height())


class StepHeader(QWidget):
    """4.0: the label of a numbered step in the left column – *1 · BILD* – with an optional action on the right."""

    def __init__(self, number: int, title: str = "", action: QWidget | None = None, parent=None):
        super().__init__(parent)
        self.number = number
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.SPACE_S)
        self.label = label("", "label")
        lay.addWidget(self.label)
        lay.addStretch(1)
        self.action = action
        if action is not None:
            lay.addWidget(action)
        self.set_title(title)

    def set_title(self, title: str) -> None:
        self.title = title
        self.label.setText(f"{self.number} · {title}")


class Column(QFrame):
    """4.0: a side column of the studio, gallery or settings – ``surface``, a 1 px line towards the middle,
    ``COLUMN_PADDING`` inside. ``body`` holds its parts."""

    def __init__(self, side: str = "left", width: int | None = None, spacing: int | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("Column")
        self.setProperty("side", side)
        pad = theme.COLUMN_PADDING
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(pad, pad, pad, pad)
        self.body.setSpacing(pad if spacing is None else spacing)
        if width:
            self.setFixedWidth(width)


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
        t = self._pos
        track = _mix(QColor(p.surface3), QColor(p.accent), t)
        edge = _mix(QColor(p.field), QColor(p.accent), t)  # 4.0: the off track's edge reaches 3 : 1 (field)
        knob = _mix(QColor(p.text), QColor(p.on_accent), t)
        if not self.isEnabled():
            track.setAlpha(110)
            edge.setAlpha(110)
            knob.setAlpha(170)
        painter.setPen(edge)
        painter.setBrush(track)
        r = theme.RADIUS_LARGE
        painter.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), r - 0.5, r - 0.5)
        painter.setPen(Qt.NoPen)
        painter.setBrush(knob)
        x = 3 + t * (self.width() - 22)
        painter.drawEllipse(QRectF(x, 3, 16, 16))


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(int(a.red() + (b.red() - a.red()) * t), int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t))


class SegmentedControl(QFrame):
    """A row (or, ``Qt.Vertical``, a column) of exclusive toggle buttons. One Tab stop: the arrow keys move
    the choice (:class:`RovingFocus`)."""

    changed = Signal(str)

    def __init__(self, items: list[tuple[str, str]], parent=None, orientation=Qt.Horizontal):
        super().__init__(parent)
        self.setObjectName("SegmentBar")
        self.orientation = orientation
        lay = QHBoxLayout(self) if orientation == Qt.Horizontal else QVBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        self._labels: dict[str, str] = {}
        self._icons: dict[str, str] = {}
        self._compact = False
        self.roving = RovingFocus(self, lambda b: b.click())
        for key, text in items:
            self._labels[key] = text
            b = QPushButton(text)
            b.setObjectName("Segment")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            if orientation != Qt.Horizontal:
                b.setProperty("align", "left")
            self._group.addButton(b)
            lay.addWidget(b)
            self._buttons[key] = b
            self._fit(b)
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
            b.toggled.connect(self._update_stop)
            self.roving.add(b)
        if items:
            self._buttons[items[0][0]].setChecked(True)
        if orientation == Qt.Horizontal:
            self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        else:
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

    def _update_stop(self, *_):
        self.roving.set_current(self._buttons.get(self.current()))

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
            self._labels[key] = text
            self._show(key)

    def set_icons(self, names: dict[str, str]) -> None:
        """Icons for the compact look (:meth:`set_compact`)."""
        self._icons = dict(names)

    def set_compact(self, compact: bool) -> None:
        """Icons with the label as tooltip instead of the labels – when the labels do not fit."""
        compact = compact and bool(self._icons)
        if compact == self._compact:
            return
        self._compact = compact
        for key in self._buttons:
            self._show(key)

    def is_compact(self) -> bool:
        return self._compact

    COMPACT_BUTTON = 38

    def full_width(self) -> int:
        """The width with the labels (also while compact)."""
        keys = [k for k, b in self._buttons.items() if not b.isHidden()]
        return self._frame_width(len(keys)) + sum(self._label_width(self._buttons[k], self._labels[k]) for k in keys)

    def compact_width(self) -> int:
        """The width with icons (labels without an icon keep their width)."""
        keys = [k for k, b in self._buttons.items() if not b.isHidden()]
        return self._frame_width(len(keys)) + sum(
            self.COMPACT_BUTTON if k in self._icons else self._label_width(self._buttons[k], self._labels[k])
            for k in keys)

    def _frame_width(self, n: int) -> int:
        lay = self.layout()
        m = lay.contentsMargins()
        return lay.spacing() * max(n - 1, 0) + m.left() + m.right() + 2

    def _show(self, key: str) -> None:
        b = self._buttons[key]
        if self._compact and key in self._icons:
            p = theme.current()
            b.setText("")
            b.setIcon(icons.icon(self._icons[key], p.muted, active_color=p.text))
            b.setIconSize(QSize(16, 16))
            b.setToolTip(self._labels[key])
            b.setMinimumWidth(self.COMPACT_BUTTON)
        else:
            b.setIcon(QIcon())
            b.setToolTip("")
            b.setText(self._labels[key])
            self._fit(b)

    @staticmethod
    def _label_width(b: QPushButton, text: str) -> int:
        """Wide enough for the label in the bold font of the checked state (padding 12 px each side)."""
        f = QFont(b.font())
        f.setWeight(QFont.Weight.DemiBold)
        return QFontMetrics(f).horizontalAdvance(text) + 28

    @classmethod
    def _fit(cls, b: QPushButton) -> None:
        b.setMinimumWidth(cls._label_width(b, b.text()))

    def set_enabled(self, key: str, enabled: bool) -> None:
        if key in self._buttons:
            self._buttons[key].setEnabled(enabled)

    def set_visible(self, key: str, visible: bool) -> None:
        if key in self._buttons:
            self._buttons[key].setVisible(visible)


class WrapRow(QWidget):
    """``first`` and ``second`` side by side when they fit, else ``second`` in a line below (e.g. the
    view tabs and the tools above the sketch: squeezed into one line, the tabs' labels overlapped).
    ``tail`` stays at the right end of the first line. A :class:`SegmentedControl` as ``first`` shows
    icons instead of its labels when even they alone do not fit (SceneSketch has six views)."""

    SPACING = 8

    def __init__(self, first: QWidget, second: QWidget, tail: QWidget | None = None, parent=None):
        super().__init__(parent)
        self._first, self._second, self._tail = first, second, tail
        self._grid = QGridLayout(self)
        self._grid.setSizeConstraint(QLayout.SetNoConstraint)  # the minimum: see minimumSizeHint
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(self.SPACING)
        self._grid.setVerticalSpacing(6)
        self._wrapped: bool | None = None
        for w in (first, second, tail):
            if w is not None:
                w.installEventFilter(self)  # shown / hidden / resized parts: check again
        self._place(False)

    def is_wrapped(self) -> bool:
        return bool(self._wrapped)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        """Narrow enough for the compact tabs over the tools (the parts adapt, see :meth:`_update`)."""
        first = self._first.compact_width() if hasattr(self._first, "compact_width") else \
            self._first.minimumSizeHint().width()
        widths = [first] + [w.minimumSizeHint().width() for w in (self._second, self._tail)
                            if w is not None and not w.isHidden()]
        return QSize(max(widths), super().minimumSizeHint().height())

    def _needed(self) -> int:
        parts = [w for w in (self._first, self._second, self._tail) if w is not None and not w.isHidden()]
        return sum(w.sizeHint().width() for w in parts) + self.SPACING * max(len(parts) - 1, 0)

    def _place(self, wrapped: bool) -> None:
        if wrapped == self._wrapped:
            return
        self._wrapped = wrapped
        g = self._grid
        for w in (self._first, self._second, self._tail):
            if w is not None:
                g.removeWidget(w)
        for c in range(3):
            g.setColumnStretch(c, 0)
        g.addWidget(self._first, 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
        if wrapped:
            g.addWidget(self._second, 1, 0, 1, 2, Qt.AlignLeft | Qt.AlignVCenter)
            tail_col = 1
        else:
            g.addWidget(self._second, 0, 1, Qt.AlignLeft | Qt.AlignVCenter)
            tail_col = 2
        g.setColumnStretch(tail_col, 1)
        if self._tail is not None:
            g.addWidget(self._tail, 0, tail_col, Qt.AlignRight | Qt.AlignVCenter)

    def _update(self) -> None:
        width = self.width()
        if width > 0 and hasattr(self._first, "set_compact"):  # labels that do not fit: icons
            self._first.set_compact(self._first.full_width() > width)
        self._place(width > 0 and self._needed() > width)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._update()

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() in (QEvent.Show, QEvent.Hide, QEvent.LayoutRequest):
            QTimer.singleShot(0, self, self._update)  # (dropped when the row is gone by then)
        return False


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
                       "warning": ("triangle-alert", p.warning)}.get(kind, ("info", p.accent_text))
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


class EmptyState(QWidget):
    """What an empty page shows: an icon, a title, what to do – and a button that does it."""

    action = Signal()

    def __init__(self, icon_name: str, parent=None):
        super().__init__(parent)
        self.icon_name = icon_name
        outer = QHBoxLayout(self)  # a centred column (a wrapped label keeps its height only without alignment)
        outer.setContentsMargins(24, 32, 24, 32)
        column = QWidget()
        column.setMaximumWidth(480)
        lay = QVBoxLayout(column)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addStretch(1)
        self.icon = QLabel()
        self.icon.setAlignment(Qt.AlignCenter)
        self.title = label("", "h2")
        self.title.setAlignment(Qt.AlignCenter)
        self.text = label("", "muted", wrap=True)
        self.text.setAlignment(Qt.AlignCenter)
        self.button = QPushButton()
        self.button.setProperty("variant", "primary")
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.clicked.connect(self.action.emit)
        self.button.hide()
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.button)
        row.addStretch(1)
        lay.addWidget(self.icon)
        lay.addWidget(self.title)
        lay.addWidget(self.text)
        lay.addSpacing(4)
        lay.addLayout(row)
        lay.addStretch(2)
        outer.addStretch(1)
        outer.addWidget(column, 4)
        outer.addStretch(1)

    def set_texts(self, title: str, text: str, button_text: str = "", button_icon: str | None = None) -> None:
        p = theme.current()
        self.icon.setPixmap(icons.pixmap(self.icon_name, p.faint, 44))
        self.title.setText(title)
        self.text.setText(text)
        self.button.setVisible(bool(button_text))
        self.button.setText(button_text)
        if button_icon:
            self.button.setIcon(icons.icon(button_icon, p.on_accent))


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
        self.icon.setPixmap(icons.pixmap(name, p.warning if warn else p.accent_text, 18))
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
