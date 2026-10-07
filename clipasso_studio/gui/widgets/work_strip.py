"""The background work (``background.Work``: moving the results or the models, unpacking an update) as a slim strip
at the top of the main window – what is being done and how far it is; the window stays usable."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar

from .. import icons, theme
from ..background import work
from ..i18n import tr
from .common import button, label


class WorkStrip(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Banner")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(10)
        self.icon = QLabel()
        self.text = label("", None)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedWidth(220)
        self.bar.setMaximumHeight(8)
        self.percent = label("", "faint")
        self.cancel_btn = button(tr("ui.cancel"), variant="ghost", size="sm")  # (the update from the phone)
        self.cancel_btn.clicked.connect(self._cancel)
        self.cancel_btn.hide()
        lay.addWidget(self.icon)
        lay.addWidget(self.text, 1)
        lay.addWidget(self.bar)
        lay.addWidget(self.percent)
        lay.addWidget(self.cancel_btn)
        work().changed.connect(self.refresh)
        self.hide()

    def refresh(self) -> None:
        w = work()
        if not w.jobs:
            self.hide()
            return
        kind = next(iter(w.jobs))
        more = len(w.jobs) - 1
        self.icon.setPixmap(icons.pixmap("hourglass", theme.current().accent_text, 16))
        self.text.setText(w.jobs[kind]["text"] + (f"  (+{more})" if more else ""))
        self.setToolTip(tr(f"ui.work.tip_{kind}"))
        from ..remote_update import updater

        self.cancel_btn.setText(tr("ui.cancel"))
        self.cancel_btn.setVisible(kind == "update" and updater().phase in ("downloading", "unpacking"))
        fraction = w.fraction(kind)
        if fraction is None:
            self.bar.setRange(0, 0)
            self.percent.setText("")
        else:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(fraction * 1000))
            self.percent.setText(f"{fraction * 100:.0f} %")
        self.show()

    def _cancel(self) -> None:
        from ..remote_update import updater

        updater().cancel()
