"""The quality hints under the studio's photo (``image_hints``): one row per hint with what helps and a button to
not show that kind again."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import icons, theme
from ..i18n import tr
from .common import button, label, tool_button

ACTION_ICONS = {"crop": "crop", "mask": "brush"}


class HintBox(QFrame):
    action = Signal(str)  # "crop" / "mask"
    dismissed = Signal(str)  # the kind of hint the user does not want to see again

    MAX_ROWS = 2  # (the most helpful ones; more would push the input card apart)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("BannerWarn")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(10, 6, 4, 6)
        self.lay.setSpacing(4)
        self.hints: list = []
        self.rows: list[QWidget] = []
        self.hide()

    def set_hints(self, hints: list) -> None:
        for row in self.rows:
            self.lay.removeWidget(row)
            row.hide()  # (gone at once: deleteLater waits for the event loop)
            row.deleteLater()
        self.hints = list(hints)[:self.MAX_ROWS]
        self.rows = [self._row(h) for h in self.hints]
        for row in self.rows:
            self.lay.addWidget(row)
        self.setVisible(bool(self.rows))

    def _row(self, hint) -> QWidget:
        pal = theme.current()
        w = QWidget()
        r = QHBoxLayout(w)
        r.setContentsMargins(0, 0, 0, 0)
        r.setSpacing(8)
        icon = QLabel()
        icon.setPixmap(icons.pixmap("triangle-alert", pal.warning, 16))
        text = label(tr(f"ui.hint.{hint.key}", **hint.values), None, wrap=True)
        text.setObjectName(f"hint-{hint.key}")
        r.addWidget(icon, 0, Qt.AlignTop)
        r.addWidget(text, 1)
        if hint.action:
            go = button(tr(f"ui.hint.action_{hint.action}"), ACTION_ICONS[hint.action], "ghost", size="sm")
            go.clicked.connect(lambda _=False, a=hint.action: self.action.emit(a))
            r.addWidget(go, 0, Qt.AlignVCenter)
        off = tool_button("x", tr("ui.hint.dismiss"), 14)
        off.setAccessibleName(tr("ui.hint.dismiss"))
        off.clicked.connect(lambda _=False, k=hint.key: self.dismissed.emit(k))
        r.addWidget(off, 0, Qt.AlignTop)
        w.hint_key = hint.key
        return w

    def keys(self) -> list[str]:
        return [h.key for h in self.hints]

    def retranslate(self) -> None:
        self.set_hints(self.hints)
