"""4.2.2: the mouse wheel scrolls the page – over a slider, a spin box or a drop-down it scrolls the column around
it and leaves the value as it is."""

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (QApplication, QComboBox, QScrollArea, QSlider, QSpinBox, QVBoxLayout, QWidget)


def _wheel(window, widget, steps=-1):
    """A turn of the wheel over ``widget``, as the window gets it."""
    local = QPointF(widget.width() / 2, widget.height() / 2)
    glob = QPointF(widget.mapToGlobal(local.toPoint()))
    pos = QPointF(window.mapFromGlobal(glob.toPoint()))
    ev = QWheelEvent(pos, glob, QPoint(0, 0), QPoint(0, 120 * steps), Qt.NoButton, Qt.NoModifier,
                     Qt.NoScrollPhase, False)
    QApplication.sendEvent(window.windowHandle(), ev)
    QApplication.processEvents()


def test_the_wheel_scrolls_the_column_not_the_values(qapp):
    from clipasso_studio.gui import wheel_guard

    guard = wheel_guard.install()
    window = QWidget()
    window.resize(320, 300)
    lay = QVBoxLayout(window)
    area = QScrollArea()
    area.setWidgetResizable(True)
    lay.addWidget(area)
    body = QWidget()
    col = QVBoxLayout(body)
    slider = QSlider(Qt.Horizontal)
    slider.setRange(0, 100)
    slider.setValue(50)
    spin = QSpinBox()
    spin.setValue(5)
    combo = QComboBox()
    combo.addItems(["a", "b", "c"])
    col.addWidget(slider)
    col.addWidget(spin)
    col.addWidget(combo)
    col.addSpacing(1500)  # (a long column: it scrolls)
    area.setWidget(body)
    window.show()
    QApplication.processEvents()
    guard.watch(window.windowHandle())
    bar = area.verticalScrollBar()
    assert bar.maximum() > 0 and bar.value() == 0
    try:
        for w in (slider, spin, combo):
            bar.setValue(0)  # (from the top: each one under the pointer)
            QApplication.processEvents()
            _wheel(window, w)
            assert bar.value() > 0, type(w).__name__  # the column moved down …
        assert slider.value() == 50 and spin.value() == 5 and combo.currentIndex() == 0  # … no value changed
        assert wheel_guard.value_widget(spin.lineEdit()) is spin  # (a spin box's text field is part of it)
        assert wheel_guard.value_widget(bar) is None  # (a scroll bar keeps its wheel)
        # nothing around that can scroll: the wheel does nothing to the value either
        lone = QSlider(Qt.Horizontal)
        lone.setRange(0, 100)
        lone.setValue(30)
        lone.resize(200, 30)
        lone.show()
        QApplication.processEvents()
        guard.watch(lone.windowHandle())
        _wheel(lone, lone)
        assert lone.value() == 30
        lone.close()
    finally:
        window.close()


def test_the_studio_has_the_guard(qapp):
    from clipasso_studio.gui import main_window, wheel_guard

    assert "wheel_guard.install()" in open(main_window.__file__, encoding="utf-8").read()
    assert wheel_guard.install() is wheel_guard.install()  # (one for the app)
