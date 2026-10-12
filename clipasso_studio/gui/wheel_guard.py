"""4.2.2: the mouse wheel scrolls the page – it never changes a value by the way. Over a slider, a spin box or a
drop-down the wheel goes to the nearest column that can scroll (its vertical scroll bar); with none around it, it does
nothing. (Before, scrolling down the parameters changed every slider the pointer passed.)

Like the focus tracker it watches the input where it enters – the windows (``QWindow``) – and not every event of the
application (see ``focus_ring.FocusTracker``). ``install()`` once per app (each window calls it)."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPointF
from PySide6.QtGui import QGuiApplication, QWheelEvent
from PySide6.QtWidgets import (QAbstractScrollArea, QAbstractSlider, QAbstractSpinBox, QApplication, QComboBox,
                               QScrollBar, QWidget)

WATCHED = "_wheel_guard_watched"  # a property of the windows whose wheel the guard sees
VALUE_WIDGETS = (QAbstractSlider, QAbstractSpinBox, QComboBox)  # (a scroll bar is a slider, too – it keeps its wheel)
_DEPTH = 3  # the parts a value widget is made of (a spin box's text field …)

_guard: WheelGuard | None = None


def install(app: QApplication | None = None) -> WheelGuard:
    """The app's one guard (made on the first call)."""
    global _guard
    app = app or QApplication.instance()
    if _guard is None or _guard.parent() is not app:
        _guard = WheelGuard(app)
    return _guard


def value_widget(widget: QWidget | None) -> QWidget | None:
    """The slider, spin box or drop-down ``widget`` is (or is part of) – None for anything else."""
    for _ in range(_DEPTH):
        if widget is None:
            return None
        if isinstance(widget, VALUE_WIDGETS) and not isinstance(widget, QScrollBar):
            return widget
        widget = widget.parentWidget()
    return None


def scroll_bar_for(widget: QWidget) -> QScrollBar | None:
    """The vertical scroll bar of the nearest area around ``widget`` that can scroll."""
    w = widget.parentWidget()
    while w is not None:
        if isinstance(w, QAbstractScrollArea) and w.verticalScrollBar().maximum() > 0:
            return w.verticalScrollBar()
        w = w.parentWidget()
    return None


class WheelGuard(QObject):
    def __init__(self, app: QApplication):
        super().__init__(app)
        app.focusWindowChanged.connect(self.watch)
        self.watch(QGuiApplication.focusWindow())

    def watch(self, window) -> None:
        """See the wheel of ``window`` (a QWindow; once)."""
        if window is not None and not window.property(WATCHED):
            window.setProperty(WATCHED, True)
            window.installEventFilter(self)

    def eventFilter(self, obj, event):  # noqa: N802 - a window's events: keep it short
        if event.type() != QEvent.Wheel:
            return False
        target = value_widget(QApplication.widgetAt(event.globalPosition().toPoint()))
        if target is None:
            return False
        bar = scroll_bar_for(target)
        if bar is not None:  # (the same turn, to the column around it)
            QApplication.sendEvent(bar, QWheelEvent(QPointF(0, 0), event.globalPosition(), event.pixelDelta(),
                                                    event.angleDelta(), event.buttons(), event.modifiers(),
                                                    event.phase(), event.inverted()))
        return True
