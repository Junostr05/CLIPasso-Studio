"""Names for screen readers: a button without text (a toggle switch, an icon button) is named by the label of its row –
the label becomes its buddy, which Qt's accessibility reads as the button's name (and which follows the label when
the language changes). Buttons with neither get a tooltip where they are made."""

from __future__ import annotations

from PySide6.QtWidgets import QAbstractButton, QComboBox, QLabel, QLayout, QLineEdit, QSpinBox, QWidget

SKIP_INSIDE = (QLineEdit, QComboBox, QSpinBox)  # (their own small buttons: clear, arrows)


def is_named(button: QAbstractButton) -> bool:
    """The button has something a screen reader can call it: its text, a name, a tooltip or a label (buddy)."""
    if button.text().strip() or button.accessibleName().strip() or button.toolTip().strip():
        return True
    parent = button.parentWidget()
    return parent is not None and any(lbl.buddy() is button and lbl.text().strip()
                                      for lbl in parent.findChildren(QLabel))


def needs_name(button: QAbstractButton) -> bool:
    parent = button.parentWidget()
    return not isinstance(parent, SKIP_INSIDE) and not is_named(button)


def _layout_of(layout: QLayout, widget: QWidget) -> list[QLayout]:
    """The chain of layouts from ``layout`` down to the one holding ``widget`` (empty: not in it)."""
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item.widget() is widget:
            return [layout]
        sub = item.layout()
        if sub is not None:
            chain = _layout_of(sub, widget)
            if chain:
                return [layout] + chain
    return []


def _labels(layout: QLayout) -> list[QLabel]:
    out = []
    for i in range(layout.count()):
        item = layout.itemAt(i)
        w, sub = item.widget(), item.layout()
        if isinstance(w, QLabel) and w.text().strip() and w.buddy() is None:
            out.append(w)
        elif sub is not None:
            out.extend(_labels(sub))
    return out


def _nearest(layout: QLayout, widget: QWidget) -> QLabel | None:
    """The free label next to ``widget`` in its own layout (the closest one; before it on a tie)."""
    items = [layout.itemAt(i).widget() for i in range(layout.count())]
    at = items.index(widget)
    free = [(abs(i - at), i > at, w) for i, w in enumerate(items)
            if isinstance(w, QLabel) and w.text().strip() and w.buddy() is None]
    return min(free, key=lambda t: t[:2])[2] if free else None


def label_for(button: QAbstractButton) -> QLabel | None:
    """The label of the button's row: the closest one in the layout that holds it, else one or two layouts
    further out."""
    parent = button.parentWidget()
    if parent is None or parent.layout() is None:
        return None
    chain = _layout_of(parent.layout(), button)
    if not chain:
        return None
    near = _nearest(chain[-1], button)
    if near is not None:
        return near
    for layout in reversed(chain[-3:-1]):
        found = _labels(layout)
        if found:
            return found[0]
    return None


def link_labels(root: QWidget) -> int:
    """Give every unnamed button under ``root`` the label of its row as its buddy; the number linked."""
    linked = 0
    for button in root.findChildren(QAbstractButton):
        if needs_name(button):
            lbl = label_for(button)
            if lbl is not None and lbl.parentWidget() is button.parentWidget():
                lbl.setBuddy(button)
                linked += 1
    return linked
