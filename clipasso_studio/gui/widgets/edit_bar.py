"""Below the studio's canvas: a slider over the saved steps of a sketch ("take a step as the result") or over its
strokes ("Simplify": leave out the least important ones first). It only previews – the studio takes the result
through the eraser's way of saving (one undo step; the original stays)."""

from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QSlider, QVBoxLayout

from ..i18n import tr
from .common import button, label


def tool_command(flag: str, run_dir: str) -> tuple[str, list[str]]:
    """The program and arguments of a measuring process for a run (``--importance``: the strokes; ``--embed``: the
    sketch's CLIP embedding) – the exe itself or the package."""
    import sys

    if getattr(sys, "frozen", False):
        return sys.executable, [flag, run_dir]
    return sys.executable, ["-m", "clipasso_studio", flag, run_dir]


def importance_command(run_dir: str) -> tuple[str, list[str]]:
    return tool_command("--importance", run_dir)


def _iter_of(path: str) -> int:
    m = re.search(r"svg_iter(\d+)\.svg$", path)
    return int(m.group(1)) if m else -1


class EditBar(QFrame):
    preview = Signal(str)  # the SVG to show
    apply = Signal(str)  # the SVG to take as the result
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = ""  # "history" | "simplify" | ""
        self._frames: list[str] = []
        self._svg = ""
        self._order: list[int] | None = None  # strokes from the least to the most important
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(4)
        row = QHBoxLayout()
        self.title = label("", "h3")
        self.info = label("", "muted")
        row.addWidget(self.title)
        row.addWidget(self.info, 1)
        self.apply_btn = button("", "check", "primary", size="sm")
        self.apply_btn.clicked.connect(self._apply)
        self.cancel_btn = button("", "x", "ghost", size="sm")
        self.cancel_btn.clicked.connect(self.close_bar)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.apply_btn)
        lay.addLayout(row)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.valueChanged.connect(self._changed)
        lay.addWidget(self.slider)
        self.note = label("", "faint", wrap=True)
        lay.addWidget(self.note)
        self.setVisible(False)

    # ------------------------------------------------------------------ history
    def open_history(self, frames: list[str], current: str) -> bool:
        """``frames``: the saved steps (SVG files, in order); shows the last one first."""
        if len(frames) < 2:
            return False
        self.mode, self._frames, self._svg = "history", list(frames), current
        self.title.setText(tr("ui.edit_bar.history"))
        self.note.setText(tr("ui.edit_bar.history_note"))
        self.apply_btn.setText(tr("ui.edit_bar.take"))
        self.slider.blockSignals(True)
        self.slider.setRange(0, len(frames) - 1)
        self.slider.setValue(len(frames) - 1)
        self.slider.setEnabled(True)
        self.slider.blockSignals(False)
        self.setVisible(True)
        self._changed(self.slider.value())
        return True

    # ------------------------------------------------------------------ simplify
    def open_simplify(self, svg: str, values: list[float] | None) -> None:
        """``values``: how much each stroke adds (None: still being measured)."""
        from .. import strokes

        self.mode, self._svg = "simplify", svg
        n = strokes.count(svg)
        self.title.setText(tr("ui.edit_bar.simplify"))
        self.apply_btn.setText(tr("ui.edit_bar.apply"))
        self.slider.blockSignals(True)
        self.slider.setRange(1, max(n, 1))
        self.slider.setValue(n)
        self.slider.blockSignals(False)
        self.setVisible(True)
        self.set_importance(values)

    def set_importance(self, values: list[float] | None, error: str = "") -> None:
        from ...engine import importance
        from .. import strokes

        if self.mode != "simplify":
            return
        n = strokes.count(self._svg)
        ok = values is not None and len(values) == n
        self._order = importance.order(values) if ok else None
        self.slider.setEnabled(ok and n > 1)
        self.apply_btn.setEnabled(False)
        if error:
            self.note.setText(tr("ui.edit_bar.measure_failed", error=error))
        else:
            self.note.setText(tr("ui.edit_bar.simplify_note") if ok else tr("ui.edit_bar.measuring"))
        self._changed(self.slider.value())

    def kept_svg(self, keep: int) -> str:
        """The sketch with only its ``keep`` most important strokes."""
        from .. import strokes

        if self._order is None:
            return self._svg
        drop = self._order[: max(0, len(self._order) - keep)]
        return strokes.remove_strokes(self._svg, sorted(drop)) if drop else self._svg

    # ------------------------------------------------------------------ common
    def _current(self) -> str:
        if self.mode == "history":
            try:
                with open(self._frames[self.slider.value()], encoding="utf-8") as f:
                    return f.read()
            except (OSError, IndexError):
                return self._svg
        return self.kept_svg(self.slider.value())

    def _changed(self, value: int):
        if self.mode == "history":
            it = _iter_of(self._frames[value]) if 0 <= value < len(self._frames) else -1
            self.info.setText(tr("ui.edit_bar.step", n=value + 1, total=len(self._frames), it=max(it, 0)))
            self.apply_btn.setEnabled(True)
        elif self.mode == "simplify":
            total = self.slider.maximum()
            self.info.setText(tr("ui.edit_bar.strokes", n=value, total=total))
            self.apply_btn.setEnabled(self._order is not None and value < total)
        if self.mode:
            self.preview.emit(self._current())

    def _apply(self):
        svg = self._current()
        self.mode = ""
        self.setVisible(False)
        self.apply.emit(svg)

    def close_bar(self):
        if not self.mode:
            return
        self.mode = ""
        self.setVisible(False)
        self.closed.emit()

    def retranslate(self):
        self.cancel_btn.setText(tr("ui.cancel"))
