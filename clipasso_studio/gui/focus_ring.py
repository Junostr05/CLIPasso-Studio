"""4.0: the keyboard focus ring – 2 px in ``focus``, 2 px outside the focused control.

Qt style sheets cannot draw an outline outside a widget (``outline: 0`` stays, so Fusion does not draw its own
dotted one), so one transparent overlay per window paints the ring and follows the focused widget. It shows
while the keyboard is in use (Tab, arrows) and hides after a click, as ``:focus-visible`` does in a browser.
Text fields, spin boxes and drop-downs keep their own focus border (``:focus`` in the style sheet).

``install()`` once per app (each window calls it; a theme change builds a new window, the tracker stays).
A widget can set the property ``ring_radius`` (its own corner radius, px); the ring then runs parallel to it.
``focus_ring`` = False on a widget: no ring around it (it shows its focus itself).
"""

from __future__ import annotations

import shiboken6
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen, QRegion
from PySide6.QtWidgets import (QAbstractButton, QAbstractScrollArea, QAbstractSpinBox, QApplication, QCheckBox,
                               QComboBox, QLineEdit, QPlainTextEdit, QTextEdit, QWidget)

from . import theme

WIDTH = 2  # px, the design system's focus-width
OFFSET = 2  # px between the control and the ring (focus-offset)
MARGIN = WIDTH + OFFSET

# keys that only modify another key: no keyboard use on their own (Alt shows the mnemonics, Ctrl+wheel zooms)
_MODIFIER_KEYS = {Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_AltGr, Qt.Key_CapsLock}
_KEY_PRESS = QEvent.KeyPress
_POINTER = {QEvent.MouseButtonPress, QEvent.MouseButtonDblClick, QEvent.TouchBegin, QEvent.TabletPress}
WATCHED = "_focus_ring_watched"  # a property of the windows (QWindow) whose input the tracker sees
_FOLLOW = {QEvent.Move, QEvent.Resize, QEvent.Show, QEvent.Hide, QEvent.ParentChange, QEvent.ZOrderChange}
_OWN_BORDER = (QLineEdit, QAbstractSpinBox, QComboBox, QPlainTextEdit, QTextEdit)  # :focus in the style sheet

_tracker: FocusTracker | None = None


def install(app: QApplication | None = None) -> FocusTracker:
    """The app's one tracker (made on the first call)."""
    global _tracker
    app = app or QApplication.instance()
    if _tracker is None or _tracker.parent() is not app:
        _tracker = FocusTracker(app)
    return _tracker


def tracker() -> FocusTracker | None:
    return _tracker


def wants_ring(widget: QWidget | None) -> bool:
    """Whether the ring is drawn around ``widget`` when it has the keyboard focus."""
    if widget is None or isinstance(widget, (FocusRing, *_OWN_BORDER)) or widget.isWindow():
        return False
    if widget.property("focus_ring") is False:
        return False
    return widget.window().windowType() != Qt.Popup  # menus and drop-down lists show their own highlight


def ring_radius(widget: QWidget) -> float:
    """The control's own corner radius (px): its ``ring_radius`` or the one its kind has in the style sheet."""
    r = widget.property("ring_radius")
    if r is not None:
        return float(r)
    if isinstance(widget, QCheckBox):
        return theme.RADIUS_PROGRESS
    if widget.objectName() == "Segment":
        return theme.RADIUS_SEGMENT
    if isinstance(widget, QAbstractButton) and widget.property("size") == "lg":
        return theme.RADIUS_LARGE
    return theme.RADIUS_CONTROL


class FocusTracker(QObject):
    """Was the keyboard or the pointer used last? It shows the ring of the focused widget's window.

    It watches the input where it enters: the windows (``QWindow``, one per top-level widget, a dialog, a menu)
    get every key and mouse press before their widgets do. (Not an event filter on the whole application: that
    sees every event of every object – also of widgets Python is just collecting, which it must not touch.)"""

    def __init__(self, app: QApplication):
        super().__init__(app)
        self.keyboard = False
        self._ring: FocusRing | None = None  # the ring of the window that had the focus last
        self._queued = False
        app.focusChanged.connect(self._focus_changed)
        app.focusWindowChanged.connect(self.watch)
        self.watch(QGuiApplication.focusWindow())

    def watch(self, window) -> None:
        """See the input of ``window`` (a QWindow; once)."""
        if window is not None and not window.property(WATCHED):
            window.setProperty(WATCHED, True)
            window.installEventFilter(self)

    def eventFilter(self, obj, event):  # noqa: N802 - a window's events: keep it short
        t = event.type()
        if t == _KEY_PRESS:
            if not self.keyboard and event.key() not in _MODIFIER_KEYS:
                self.set_keyboard(True)
        elif t in _POINTER:
            if self.keyboard:
                self.set_keyboard(False)
        return False

    def set_keyboard(self, on: bool) -> None:
        self.keyboard = on
        self.refresh()

    def _focus_changed(self, _old, _new) -> None:
        # Nothing is touched while Qt reports the change: it also reports the focus of a widget that is being
        # destroyed – with its window half gone (that crashed the app). The ring follows right after.
        if QGuiApplication.mouseButtons() != Qt.NoButton:
            self.keyboard = False  # (focus by a click)
        if not self._queued:
            self._queued = True
            QTimer.singleShot(0, self, self.refresh)

    def refresh(self) -> None:
        """The ring around the widget that has the focus now – or none."""
        self._queued = False
        new = QApplication.focusWidget()
        show = new is not None and self.keyboard and wants_ring(new)
        ring = FocusRing.of(new.window(), create=show) if new is not None else None
        if ring is not None:
            if show and ring.target is new:
                ring.sync()
            else:
                ring.follow(new if show else None)
        last, self._ring = self._ring, ring
        if last is not None and last is not ring and not _deleted(last):  # (gone with its window: nothing to do)
            last.follow(None)


def _deleted(obj) -> bool:
    try:
        obj.objectName()
        return False
    except RuntimeError:  # the C++ object is gone
        return True


def _address(obj: QObject) -> int:
    return shiboken6.getCppPointer(obj)[0]


class FocusRing(QWidget):
    """The overlay of one window: as large as the ring around the focused control, never in the way of the mouse.

    It follows the control and its parents (they move, resize, scroll) through event filters – and keeps no
    reference to the parents: one of them may go without Python knowing (a viewport made by Qt), and a reference
    can keep a widget alive, whose end then calls back into what is being taken down. A filter that is no longer
    needed goes with the next event of its widget."""

    def __init__(self, window: QWidget):
        super().__init__(window)
        self.setObjectName("FocusRing")
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.NoFocus)
        self.target: QWidget | None = None
        self._chain: set[int] = set()  # the C++ addresses of the target and its parents up to the window
        self._gone = None  # the connection to the target's destroyed signal
        self._pending = False
        self.hide()

    @classmethod
    def of(cls, window: QWidget, create: bool = True) -> FocusRing | None:
        ring = window.findChild(FocusRing, "FocusRing", Qt.FindDirectChildrenOnly)
        if ring is None and create:
            ring = FocusRing(window)
        return ring

    def follow(self, widget: QWidget | None) -> None:
        """Draw the ring around ``widget`` (None: none) and keep it there while the widget moves or scrolls."""
        if self._gone is not None:
            QObject.disconnect(self._gone)
            self._gone = None
        self.target = widget
        self._chain = set()
        if widget is not None:
            w = widget
            while w is not None and w is not self.parentWidget():
                w.installEventFilter(self)  # (once per widget: installing it again only moves it to the front)
                self._chain.add(_address(w))
                w = w.parentWidget()
            self._gone = widget.destroyed.connect(self._target_gone)
        self.sync()

    def _target_gone(self, *_):
        # (in the middle of the target's end: only forget it – the ring goes away right after)
        self._gone = None
        self.target = None
        self._chain = set()
        QTimer.singleShot(0, self, self.sync)

    def eventFilter(self, obj, event):  # noqa: N802
        if _address(obj) not in self._chain:
            obj.removeEventFilter(self)  # (a parent of a control followed before)
            return False
        t = event.type()
        if t in _FOLLOW and not self._pending:
            self._pending = True  # (one update after the layout has settled)
            QTimer.singleShot(0, self, self.sync)
        if t == QEvent.ParentChange and obj is self.target:
            QTimer.singleShot(0, self, lambda: self.follow(self.target))
        return False

    def visible_rect(self) -> QRect:
        """Where the ring may be drawn in the window: inside every scroll area it sits in."""
        win = self.parentWidget()
        area = win.rect()
        w = self.target.parentWidget() if self.target is not None else None
        while w is not None and w is not win:
            parent = w.parentWidget()
            if isinstance(parent, QAbstractScrollArea) and w is parent.viewport():
                area = area.intersected(QRect(w.mapTo(win, QPoint(0, 0)), w.size()))
            w = parent
        return area

    def sync(self) -> None:
        self._pending = False
        t = self.target
        if t is None or not t.isVisibleTo(self.parentWidget()) or not self.parentWidget().isVisible():
            self.hide()
            return
        box = QRect(t.mapTo(self.parentWidget(), QPoint(0, 0)), t.size()).adjusted(-MARGIN, -MARGIN, MARGIN, MARGIN)
        shown = box.intersected(self.visible_rect())
        if shown.isEmpty():
            self.hide()
            return
        self.setGeometry(box)
        self.setMask(QRegion(shown.translated(-box.topLeft())))
        siblings = [c for c in self.parentWidget().children() if isinstance(c, QWidget) and not c.isHidden()]
        if siblings and siblings[-1] is not self:  # above everything else in the window (once: raising moves it)
            self.raise_()
        self.show()
        self.update()

    def paintEvent(self, event):  # noqa: N802
        if self.target is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(theme.current().focus), WIDTH))
        p.setBrush(Qt.NoBrush)
        half = WIDTH / 2
        r = ring_radius(self.target) + OFFSET + half
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(half, half, -half, -half), r, r)
        p.drawPath(path)
        p.end()
