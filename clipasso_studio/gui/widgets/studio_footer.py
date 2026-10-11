"""4.0: the studio's footer (design system: JobFooter) – the job. Before a start: the status, the estimate and the
main action *Skizze erstellen* with *Zur Warteschlange*; while the shown job runs: its status, the time left,
*Details*, the progress of the whole job, *Pause* and *Abbrechen*.

The studio makes the controls (``status``, ``estimate``, ``progress`` and the buttons keep their names there, the
phone and the shortcuts use them); the footer only lays them out and switches between the two states."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout

from .. import icons, theme
from ..i18n import tr
from .common import link_button


class StudioFooter(QFrame):
    details_toggled = Signal(bool)

    def __init__(self, status, estimate, progress, start_btn, queue_btn, pause_btn, cancel_btn, parent=None):
        super().__init__(parent)
        self.setObjectName("Footer")
        self.setFixedHeight(theme.FOOTER_HEIGHT)
        self.status, self.estimate, self.progress = status, estimate, progress
        self.start_btn, self.queue_btn, self.pause_btn, self.cancel_btn = start_btn, queue_btn, pause_btn, cancel_btn
        lay = QHBoxLayout(self)
        lay.setContentsMargins(theme.COLUMN_PADDING, 0, theme.COLUMN_PADDING, 0)
        lay.setSpacing(theme.SPACE_XL)
        info = QVBoxLayout()
        info.setSpacing(theme.SPACE_S)
        info.addStretch(1)
        line = QHBoxLayout()
        line.setSpacing(theme.SPACE_L)
        line.addWidget(status, 1)
        line.addWidget(estimate)
        self.details_btn = link_button("")
        self.details_btn.setCheckable(True)
        self.details_btn.toggled.connect(self._details)
        line.addWidget(self.details_btn)
        info.addLayout(line)
        progress.setFixedHeight(6)
        info.addWidget(progress)
        info.addStretch(1)
        lay.addLayout(info, 1)
        actions = QHBoxLayout()
        actions.setSpacing(theme.SPACE_S)
        for b in (queue_btn, start_btn, pause_btn, cancel_btn):
            actions.addWidget(b, 0, Qt.AlignVCenter)
        lay.addLayout(actions)
        self.running = False
        self.retranslate()

    def show_actions(self, running_here: bool, busy: bool) -> None:
        """``running_here``: the shown job runs (Pause, Cancel); else the start (to the queue while another one
        runs) and – with nothing running – *Zur Warteschlange*."""
        self.running = running_here
        self.pause_btn.setVisible(running_here)
        self.cancel_btn.setVisible(running_here)
        self.start_btn.setVisible(not running_here)
        self.queue_btn.setVisible(not busy)
        self.progress.setVisible(running_here)  # (a finished result needs no full bar)

    def set_details_open(self, on: bool) -> None:
        self.details_btn.setChecked(on)

    def _details(self, on: bool) -> None:
        self._details_icon()
        self.details_toggled.emit(on)

    def _details_icon(self) -> None:
        name = "chevron-down" if self.details_btn.isChecked() else "chevron-up"
        self.details_btn.setIcon(icons.icon(name, theme.current().accent_text))

    def retranslate(self) -> None:
        self.details_btn.setText(tr("ui.footer.details"))
        self.details_btn.setToolTip(tr("ui.footer.details_tip"))
        self._details_icon()
