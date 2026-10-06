"""Method switcher of the studio: one card per sketching method."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ... import settings_schema as schema
from .. import icons, methods_ui, theme
from ..i18n import tr
from .common import label


class MethodCard(QFrame):
    clicked = Signal(str)

    def __init__(self, method: str, parent=None):
        super().__init__(parent)
        self.method = method
        self.setObjectName("MethodCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setProperty("selected", False)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(10)
        self.icon = QLabel()
        self.icon.setFixedSize(34, 34)
        self.icon.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.icon, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.name = label(methods_ui.name(method), "h3")
        top.addWidget(self.name)
        top.addStretch(1)
        self.speed = label("", "badge")
        top.addWidget(self.speed)
        col.addLayout(top)
        self.tagline = label("", "faint", wrap=True)
        col.addWidget(self.tagline)
        self.status = label("", "faint")
        col.addWidget(self.status)
        lay.addLayout(col, 1)
        self.retranslate()

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)
        self._paint_icon()

    def _paint_icon(self):
        p = theme.current()
        color = p.accent_text if self.property("selected") else p.muted
        self.icon.setPixmap(icons.pixmap(methods_ui.ICONS[self.method], color, 26))

    def refresh_status(self, settings: dict | None = None) -> None:
        settings = settings or schema.default_settings(self.method)
        missing = methods_ui.missing_models(settings)
        p = theme.current()
        if missing:
            mb = methods_ui.download_mb(missing)
            size = f"{mb / 1000:.1f} GB" if mb >= 1000 else f"{mb:.0f} MB"
            self.status.setText(tr("ui.method.download_needed", size=size))
            self.status.setStyleSheet(f"color: {p.warning};")
        elif self.method == "controlsketch" and not methods_ui.has_cuda():
            self.status.setText(tr("ui.method.gpu_recommended"))
            self.status.setStyleSheet(f"color: {p.warning};")
        else:
            self.status.setText(tr("ui.method.ready"))
            self.status.setStyleSheet(f"color: {p.success};")

    def retranslate(self):
        self.tagline.setText(tr(f"method.{self.method}.tagline"))
        self.speed.setText(tr(f"method.{self.method}.speed"))
        self.setToolTip(f"<div style='max-width:340px'><b>{methods_ui.name(self.method)}</b><br>"
                        f"{tr(f'method.{self.method}.desc')}</div>")
        self._paint_icon()

    def mouseReleaseEvent(self, e):  # noqa: N802
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.method)


class MethodPicker(QWidget):
    changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.cards: dict[str, MethodCard] = {}
        for m in schema.METHODS:
            c = MethodCard(m)
            c.clicked.connect(self._clicked)
            lay.addWidget(c, 1)
            self.cards[m] = c
        self._current = schema.DEFAULT_METHOD
        self.set_current(self._current)

    def _clicked(self, method: str):
        if method != self._current:
            self.set_current(method)
            self.changed.emit(method)

    def current(self) -> str:
        return self._current

    def set_current(self, method: str) -> None:
        self._current = method
        for m, c in self.cards.items():
            c.set_selected(m == method)

    def refresh_status(self, settings_per_method: dict[str, dict]) -> None:
        for m, c in self.cards.items():
            c.refresh_status(settings_per_method.get(m))

    def retranslate(self):
        for c in self.cards.values():
            c.retranslate()
