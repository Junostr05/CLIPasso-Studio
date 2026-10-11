"""4.0: the keyboard focus ring and the keyboard on the studio's choices (method cards, segments, sketches)."""

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget

from clipasso_studio.gui import focus_ring, theme
from clipasso_studio.gui.focus_ring import FocusRing, FocusTracker


@pytest.fixture
def tracker(qapp):
    if not qapp.styleSheet():  # (once: restyling every widget of the test session takes seconds)
        theme.apply(qapp, "dark")
    t = focus_ring.install(qapp)
    t.set_keyboard(False)
    yield t
    t.set_keyboard(False)


def _window(*widgets, scroll: bool = False):
    win = QWidget()
    lay = QVBoxLayout(win)
    if scroll:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFixedHeight(120)
        host = QWidget()
        inner = QVBoxLayout(host)
        for w in widgets:
            inner.addWidget(w)
        area.setWidget(host)
        lay.addWidget(area)
        win.area = area
    else:
        for w in widgets:
            lay.addWidget(w)
    win.resize(320, 240 if scroll else 200)
    win.show()
    win.activateWindow()
    QTest.qWaitForWindowExposed(win)
    QTest.qWait(10)
    return win


def _settle():
    QTest.qWait(10)  # the ring follows after the layout (a zero timer)


def _ring(win) -> FocusRing | None:
    return FocusRing.of(win, create=False)


def test_tab_shows_the_ring_and_a_click_hides_it(tracker):
    """4.0: Tab shows the ring around the focused button, 2 px outside it; a click hides it again. (The keys and
    the click come through the window, as a user's do.)"""
    a, b = QPushButton("A"), QPushButton("B")
    win = _window(a, b)
    try:
        a.setFocus(Qt.MouseFocusReason)
        _settle()
        assert not tracker.keyboard and (_ring(win) is None or not _ring(win).isVisible())
        QTest.keyClick(win.windowHandle(), Qt.Key_Tab)
        _settle()
        ring = _ring(win)
        assert tracker.keyboard and b.hasFocus() and ring.isVisible() and ring.target is b
        box = b.geometry().adjusted(-focus_ring.MARGIN, -focus_ring.MARGIN, focus_ring.MARGIN, focus_ring.MARGIN)
        assert ring.geometry() == box
        QTest.keyClick(win.windowHandle(), Qt.Key_Shift)  # a modifier alone changes nothing
        assert tracker.keyboard
        QTest.mouseClick(win.windowHandle(), Qt.LeftButton, Qt.NoModifier, a.geometry().center())
        _settle()
        assert not tracker.keyboard and not ring.isVisible() and a.hasFocus()
    finally:
        win.close()


def test_dropped_windows_are_safe_with_the_tracker(tracker):
    """4.0: windows that are only garbage-collected (never closed) while the ring follows one of their buttons –
    the tracker watches windows, not every object, so nothing touches a widget Python is collecting."""
    import gc

    tracker.set_keyboard(True)
    for i in range(60):
        b = QPushButton(f"B{i}")
        win = _window(QPushButton("A"), b)
        b.setFocus(Qt.TabFocusReason)
        QTest.qWait(1)
        win.cycle = win  # (only the cycle collector frees it)
        del win, b
        if i % 5 == 0:
            gc.collect()
    gc.collect()
    QTest.qWait(10)


def test_the_ring_is_drawn_in_the_focus_colour(tracker, monkeypatch):
    """4.0: the ring is ``focus`` of the current palette, also after switching the theme (it reads the palette
    when it paints)."""
    tracker.set_keyboard(True)  # (as after a key press)
    a, b = QPushButton("A"), QPushButton("B")
    win = _window(a, b)
    try:
        for palette in (theme.DARK, theme.LIGHT):
            monkeypatch.setattr(theme, "_current", palette)
            b.setFocus(Qt.TabFocusReason)
            _settle()
            ring = _ring(win)
            img = ring.grab().toImage()
            mid = img.pixelColor(img.width() // 2, 0)  # the ring's top edge, between the rounded corners
            assert mid.alpha() > 0 and mid.name().lower() == QColor(palette.focus).name().lower(), palette.name
            a.setFocus(Qt.TabFocusReason)
            _settle()
    finally:
        win.close()


def test_one_tracker_for_the_app(tracker, qapp):
    """4.0: every window installs the tracker – it stays one (a theme change builds a new window)."""
    assert focus_ring.install() is tracker and focus_ring.install(qapp) is tracker
    assert len(qapp.findChildren(FocusTracker)) == 1


def test_text_fields_keep_their_own_border(tracker):
    """4.0: a text field shows its focus by its border (``:focus``), not by the ring."""
    tracker.set_keyboard(True)  # (as after a key press)
    a, edit = QPushButton("A"), QLineEdit()
    win = _window(a, edit)
    try:
        edit.setFocus(Qt.MouseFocusReason)
        a.setFocus(Qt.TabFocusReason)
        _settle()
        assert _ring(win).isVisible()
        edit.setFocus(Qt.TabFocusReason)
        _settle()
        assert edit.hasFocus() and not _ring(win).isVisible()
    finally:
        win.close()


def test_the_ring_follows_when_scrolling(tracker):
    """4.0: the ring moves with its control when the column scrolls – and stays inside the scroll area."""
    tracker.set_keyboard(True)  # (as after a key press)
    buttons = [QPushButton(f"B{i}") for i in range(12)]
    win = _window(*buttons, scroll=True)
    try:
        target = buttons[1]
        target.setFocus(Qt.TabFocusReason)
        _settle()
        ring = _ring(win)
        before = ring.geometry().top()
        bar = win.area.verticalScrollBar()
        bar.setValue(20)
        _settle()
        assert ring.geometry().top() == before - 20
        assert ring.geometry().topLeft() == target.mapTo(win, QPoint(0, 0)) - QPoint(focus_ring.MARGIN,
                                                                                      focus_ring.MARGIN)
        bar.setValue(bar.maximum())  # scrolled out of view: no ring
        _settle()
        assert not ring.isVisible()
        bar.setValue(20)
        _settle()
        assert ring.isVisible()
        viewport = win.area.viewport()
        shown = ring.mask().boundingRect().translated(ring.pos())
        assert viewport.geometry().translated(viewport.parentWidget().mapTo(win, QPoint(0, 0))).contains(shown)
    finally:
        win.close()


def test_a_deleted_target_takes_the_ring_along(tracker):
    tracker.set_keyboard(True)  # (as after a key press)
    a, b = QPushButton("A"), QPushButton("B")
    win = _window(a, b)
    try:
        b.setFocus(Qt.TabFocusReason)
        _settle()
        ring = _ring(win)
        assert ring.isVisible()
        b.deleteLater()
        QTest.qWait(20)
        assert ring.target is not b and (not ring.isVisible() or ring.target is a)
    finally:
        win.close()


def test_a_dialog_destroyed_while_one_of_its_buttons_has_the_focus(tracker):
    """4.0: a dialog (like the queue's countdown) that is destroyed while its button has the keyboard focus – Qt
    then reports the focus change of a widget that is half gone. The ring never touches it (it crashed the app):
    the ring of the dialog goes with it, the window's ring shows again."""
    import gc

    from PySide6.QtWidgets import QDialog

    tracker.set_keyboard(True)  # (as after a key press)
    a = QPushButton("A")
    win = _window(a)
    try:
        for i in range(20):
            dlg = QDialog(win)
            lay = QVBoxLayout(dlg)
            cancel, ok = QPushButton("Cancel"), QPushButton("OK")
            lay.addWidget(cancel)
            lay.addWidget(ok)
            dlg.show()
            dlg.activateWindow()
            QTest.qWaitForWindowExposed(dlg)
            cancel.setFocus(Qt.TabFocusReason)
            _settle()
            assert _ring(dlg).isVisible() and _ring(dlg).target is cancel
            if i % 2:
                dlg.deleteLater()  # (destroyed with the focus inside)
            else:
                dlg.setParent(None)  # (Python frees it: the last reference goes)
                dlg.cycle = dlg
                del dlg, cancel, ok
                gc.collect()
            QTest.qWait(5)
        win.activateWindow()
        a.setFocus(Qt.TabFocusReason)
        _settle()
        assert _ring(win).isVisible() and _ring(win).target is a
    finally:
        win.close()


def test_the_ring_moves_to_the_window_with_the_focus(tracker):
    """4.0: one ring at a time – when the focus goes to another window, the ring of the first one goes away."""
    tracker.set_keyboard(True)  # (as after a key press)
    a, b = QPushButton("A"), QPushButton("B")
    first, second = _window(a), _window(b)
    try:
        first.activateWindow()
        a.setFocus(Qt.TabFocusReason)
        _settle()
        assert _ring(first).isVisible()
        second.activateWindow()
        b.setFocus(Qt.TabFocusReason)
        _settle()
        assert _ring(second).isVisible() and not _ring(first).isVisible() and _ring(first).target is None
    finally:
        first.close()
        second.close()


def test_a_parent_made_by_qt_may_go_before_the_ring_moves_on(tracker):
    """4.0: the ring follows a control and its parents – also ones Qt made (a scroll area's viewport) that Python
    cannot see go. When such a parent is destroyed first, the ring lets go of it without touching it."""
    tracker.set_keyboard(True)  # (as after a key press)
    buttons = [QPushButton(f"B{i}") for i in range(3)]
    other = QPushButton("other")
    win = _window(*buttons, scroll=True)
    win.layout().addWidget(other)
    try:
        target = buttons[0]
        target.setFocus(Qt.TabFocusReason)
        _settle()
        ring = _ring(win)
        assert ring.target is target
        target.setParent(win)  # out of the scroll area …
        area = win.area
        area.setParent(None)
        del area, win.area  # … which goes at once, with its viewport (made by Qt), before the ring moves on
        other.setFocus(Qt.TabFocusReason)
        _settle()
        assert ring.target is other and ring.isVisible()
    finally:
        win.close()


def test_the_method_cards_are_a_radio_group(tracker):
    """4.0: the method cards are one Tab stop; the arrow keys, Home and End choose, the ring follows."""
    tracker.set_keyboard(True)  # (as after a key press)
    from clipasso_studio import settings_schema as schema
    from clipasso_studio.gui.widgets.method_picker import MethodPicker

    picker = MethodPicker()
    chosen = []
    picker.changed.connect(chosen.append)
    win = _window(QPushButton("before"), picker)
    try:
        cards = [picker.cards[m] for m in schema.METHODS]
        stops = [c for c in cards if c.focusPolicy() & Qt.TabFocus]
        assert stops == [picker.cards[picker.current()]]
        first = cards[0]
        picker.set_current(first.method)
        first.setFocus(Qt.TabFocusReason)
        QTest.keyClick(first, Qt.Key_Down)
        _settle()
        assert picker.current() == cards[1].method and cards[1].hasFocus() and chosen == [cards[1].method]
        assert _ring(win).target is cards[1]
        QTest.keyClick(cards[1], Qt.Key_End)
        assert picker.current() == cards[-1].method
        QTest.keyClick(cards[-1], Qt.Key_Right)  # around to the first one, as in a radio group
        assert picker.current() == first.method and first.hasFocus()
        assert [c for c in cards if c.focusPolicy() & Qt.TabFocus] == [first]
        cards[2].setFocus(Qt.TabFocusReason)
        QTest.keyClick(cards[2], Qt.Key_Space)
        assert picker.current() == cards[2].method
        assert all(c.accessibleName() for c in cards)
    finally:
        win.close()


def test_segments_are_one_tab_stop_with_arrows(tracker):
    """4.0: a segmented control – also a vertical one – is one Tab stop; the arrows move the choice."""
    from clipasso_studio.gui.widgets.common import SegmentedControl

    for orientation in (Qt.Horizontal, Qt.Vertical):
        seg = SegmentedControl([("a", "Alle"), ("b", "Bilder"), ("c", "Alben")], orientation=orientation)
        seen = []
        seg.changed.connect(seen.append)
        win = _window(seg)
        try:
            buttons = [seg._buttons[k] for k in "abc"]
            assert [b for b in buttons if b.focusPolicy() & Qt.TabFocus] == [buttons[0]]
            buttons[0].setFocus(Qt.TabFocusReason)
            QTest.keyClick(buttons[0], Qt.Key_Down if orientation == Qt.Vertical else Qt.Key_Right)
            assert seg.current() == "b" and buttons[1].hasFocus() and seen == ["b"]
            assert [b for b in buttons if b.focusPolicy() & Qt.TabFocus] == [buttons[1]]
            seg.set_visible("c", False)  # hidden choices are skipped
            QTest.keyClick(buttons[1], Qt.Key_Right)
            assert seg.current() == "a"
            if orientation == Qt.Vertical:
                assert seg.layout().direction() in (QVBoxLayout.TopToBottom, QVBoxLayout.BottomToTop)
        finally:
            win.close()


def test_sketches_and_the_drop_zone_by_keyboard(tracker):
    """4.0: the drop zone opens an image with Space; the sketches are one Tab stop, the arrows choose."""
    from clipasso_studio.gui.widgets.canvas import ImageDropZone, SeedThumb
    from clipasso_studio.gui.widgets.common import RovingFocus

    drop = ImageDropZone()
    drop.set_texts("Bild hierher ziehen", "oder klicken")
    opened = []
    drop.clicked.connect(lambda: opened.append(True))
    host = QWidget()
    row = QVBoxLayout(host)
    thumbs = [SeedThumb(s) for s in (0, 1, 2)]
    chosen = []
    group = RovingFocus(host, lambda t: (chosen.append(t.seed), group.set_current(t)))
    for t in thumbs:
        row.addWidget(t)
        group.add(t)
    win = _window(drop, host)
    try:
        assert drop.focusPolicy() & Qt.TabFocus and drop.accessibleName() == "Bild hierher ziehen"
        drop.setFocus(Qt.TabFocusReason)
        QTest.keyClick(drop, Qt.Key_Space)
        assert opened == [True]
        assert [t for t in thumbs if t.focusPolicy() & Qt.TabFocus] == [thumbs[0]]
        thumbs[0].setFocus(Qt.TabFocusReason)
        QTest.keyClick(thumbs[0], Qt.Key_Right)
        assert chosen == [1] and thumbs[1].hasFocus()
        assert [t for t in thumbs if t.focusPolicy() & Qt.TabFocus] == [thumbs[1]]
        QTest.keyClick(thumbs[1], Qt.Key_Return)
        assert chosen == [1, 1]
        assert thumbs[2].accessibleName()
    finally:
        win.close()


def test_the_new_building_blocks(qapp):
    """4.0: link button, count badge, step header, chip and column use the design system's roles."""
    from PySide6.QtGui import QFont

    from clipasso_studio.gui.widgets.common import Chip, Column, CountBadge, StepHeader, link_button

    link = link_button("Anpassen")
    assert link.property("variant") == "link" and link.text() == "Anpassen"
    badge = CountBadge()
    assert badge.isHidden() and badge.property("role") == "count"
    badge.set_count(3)
    assert not badge.isHidden() and badge.text() == "3"
    badge.set_count(140)
    assert badge.text() == "99+"
    step = StepHeader(1, "Bild", action=link)
    assert step.label.text() == "1 · Bild" and step.label.property("role") == "label"
    assert step.label.font().capitalization() == QFont.AllUppercase
    step.set_title("Image")
    assert step.label.text() == "1 · Image"
    chip = Chip("cpu", "Prozessor · 8 Kerne", framed=True)
    assert chip.property("framed") == "true" and chip.text.text() == "Prozessor · 8 Kerne"
    assert chip.sizeHint().width() > chip.text.fontMetrics().horizontalAdvance("Prozessor · 8 Kerne")
    col = Column("left", theme.LEFT_COLUMN)
    m = col.body.contentsMargins()
    assert col.width() == theme.LEFT_COLUMN or col.minimumWidth() == theme.LEFT_COLUMN
    assert {m.left(), m.top(), m.right(), m.bottom()} == {theme.COLUMN_PADDING}
    assert col.property("side") == "left" and col.objectName() == "Column"
