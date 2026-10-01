"""The view tabs and tools above the sketch never overlap: the tools move into a second line, and the tabs
show icons (labels as tooltips) when even they alone do not fit."""

from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget


def _settle(qapp, n=5):
    for _ in range(n):
        qapp.processEvents()


def _row(qapp, width):
    from clipasso_studio.gui.widgets.common import SegmentedControl, WrapRow, tool_button

    tabs = SegmentedControl([("sketch", "Sketch"), ("compare", "Photo/sketch"), ("attention", "Attention"),
                             ("mask", "Mask"), ("condition", "Background"), ("matrix", "Matrix")])
    tabs.set_icons({"sketch": "pen-tool", "compare": "flip-horizontal-2", "attention": "eye", "mask": "scan",
                    "condition": "mountain", "matrix": "layers"})
    tools = QWidget()
    lay = QHBoxLayout(tools)
    lay.setContentsMargins(0, 0, 0, 0)
    for name in ("eraser", "pencil-line", "undo-2", "redo-2", "rotate-ccw", "wand-sparkles", "palette"):
        lay.addWidget(tool_button(name, "", 18))
    host = QWidget()
    outer = QHBoxLayout(host)
    outer.setContentsMargins(0, 0, 0, 0)
    row = WrapRow(tabs, tools, QLabel("stage 1"))
    outer.addWidget(row)
    host.resize(width, 120)
    host.show()
    _settle(qapp)
    return host, row, tabs, tools


def test_one_line_when_it_fits(qapp):
    host, row, tabs, tools = _row(qapp, 1400)
    assert not row.is_wrapped() and not tabs.is_compact()
    assert abs(tools.geometry().center().y() - tabs.geometry().center().y()) <= 2  # one line
    host.close()


def test_tools_wrap_then_tabs_turn_into_icons(qapp):
    host, row, tabs, tools = _row(qapp, 620)
    assert tabs.full_width() < 620 < tabs.full_width() + tools.sizeHint().width()
    assert row.is_wrapped() and not tabs.is_compact()  # the tabs alone fit
    assert tools.geometry().top() > tabs.geometry().bottom()
    for b in tabs._buttons.values():
        assert b.width() >= b.minimumWidth()  # no squeezed (overlapping) labels
    host.resize(300, 120)
    _settle(qapp)
    assert tabs.is_compact() and tabs.sizeHint().width() <= 300
    b = tabs._buttons["attention"]
    assert b.text() == "" and b.toolTip() == "Attention" and not b.icon().isNull()
    tabs.set_text("attention", "Aufmerksamkeit")  # a new language while compact
    assert b.toolTip() == "Aufmerksamkeit" and b.text() == ""
    host.resize(1400, 120)
    _settle(qapp)
    assert not tabs.is_compact() and not row.is_wrapped() and b.text() == "Aufmerksamkeit"
    host.close()


def test_hidden_tabs_count_no_more(qapp):
    host, row, tabs, tools = _row(qapp, 470)
    wide = tabs.full_width()
    for key in ("condition", "matrix", "attention"):  # e.g. SwiftSketch shows three views
        tabs.set_visible(key, False)
    _settle(qapp)
    assert tabs.full_width() < wide and not tabs.is_compact()
    host.close()


def test_studio_uses_it(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from clipasso_studio.gui import app_settings as settings_module

    settings_module._instance = None
    from clipasso_studio.gui.main_window import MainWindow
    from clipasso_studio.gui.widgets.common import WrapRow

    w = MainWindow()
    try:
        assert isinstance(w.studio.canvas_header, WrapRow)
        w.resize(1300, 860)
        w.show()
        w.studio.params.set_method("scenesketch")
        _settle(qapp, 10)
        for b in w.studio.modes._buttons.values():
            if b.isVisible():
                assert b.width() >= b.minimumWidth()
    finally:
        w.studio.shutdown()
        w.controller.shutdown()
        w.close()
        settings_module._instance = None
