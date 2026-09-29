"""Dialogs: export options and model download."""

from __future__ import annotations

import os

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QColorDialog, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QMessageBox, QProgressBar, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from ..engine import model_store
from . import export, theme
from .i18n import tr
from .widgets.common import button, label


class ColorButton(QPushButton):
    changed = Signal(str)

    def __init__(self, color: str = "#000000", allow_transparent: bool = False):
        super().__init__()
        self._color = color
        self.allow_transparent = allow_transparent
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(self._pick)
        self._refresh()

    def color(self) -> str:
        return self._color

    def set_color(self, c: str):
        self._color = c
        self._refresh()
        self.changed.emit(c)

    def _pick(self):
        initial = QColor(self._color) if self._color != "transparent" else QColor("white")
        c = QColorDialog.getColor(initial, self, "", QColorDialog.ShowAlphaChannel if self.allow_transparent
                                  else QColorDialog.ColorDialogOption(0))
        if c.isValid():
            self.set_color("transparent" if c.alpha() == 0 else c.name())

    def _refresh(self):
        p = theme.current()
        if self._color == "transparent":
            bg = "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ffffff, stop:0.49 #ffffff, stop:0.5 #cccccc, " \
                 "stop:1 #cccccc)"
            self.setText(tr("ui.transparent"))
        else:
            bg = self._color
            self.setText(self._color.upper())
        fg = "#000000" if self._color == "transparent" or QColor(self._color).lightness() > 140 else "#FFFFFF"
        self.setStyleSheet(f"QPushButton {{ background: {bg}; color: {fg}; border: 1px solid {p.border};"
                           f" border-radius: 8px; padding: 6px 12px; font-weight: 600; }}")


class _Worker(QObject):
    progress = Signal(int, int)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.cancelled = False

    def run(self):
        try:
            result = self.fn(*self.args, progress=lambda a, b: self.progress.emit(int(a), int(b)), **self.kwargs)
            self.finished.emit(str(result))
        except Exception as exc:
            self.failed.emit(str(exc))


def run_in_thread(parent, fn, *args, on_progress=None, on_done=None, on_error=None, **kwargs):
    thread = QThread(parent)
    worker = _Worker(fn, *args, **kwargs)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    if on_progress:
        worker.progress.connect(on_progress)
    if on_done:
        worker.finished.connect(on_done)
    if on_error:
        worker.failed.connect(on_error)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread._worker = worker  # keep a reference
    thread.start()
    return thread


class ExportDialog(QDialog):
    """Options for exporting a sketch (SVG, PNG, GIF, MP4)."""

    def __init__(self, fmt: str, svg_path: str, run_dir: str, default_name: str, parent=None):
        super().__init__(parent)
        self.fmt = fmt
        self.svg_path = svg_path
        self.run_dir = run_dir
        self.default_name = default_name
        self.setWindowTitle(tr("ui.export_title", fmt=fmt.upper()))
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(14)
        lay.addWidget(label(tr("ui.export_title", fmt=fmt.upper()), "h2"))
        lay.addWidget(label(tr(f"ui.export_desc.{fmt}"), "muted", wrap=True))

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignLeft)
        self.stroke = ColorButton("#000000")
        form.addRow(tr("ui.stroke_color"), self.stroke)
        self.width_scale = QDoubleSpinBox()
        self.width_scale.setRange(0.1, 10.0)
        self.width_scale.setSingleStep(0.1)
        self.width_scale.setValue(1.0)
        self.width_scale.setSuffix(" ×")
        form.addRow(tr("ui.stroke_width_scale"), self.width_scale)
        self.background = ColorButton("#FFFFFF" if fmt != "svg" else "transparent", allow_transparent=fmt in
                                      ("svg", "png"))
        form.addRow(tr("ui.background"), self.background)
        self.size = QSpinBox()
        self.size.setRange(64, 8192)
        self.size.setSingleStep(128)
        self.size.setValue(1024 if fmt == "png" else 512)
        self.size.setSuffix(" px")
        if fmt != "svg":
            form.addRow(tr("ui.size"), self.size)
        self.fps = QSpinBox()
        self.fps.setRange(1, 60)
        self.fps.setValue(20)
        self.fps.setSuffix(" fps")
        if fmt in ("gif", "mp4"):
            form.addRow(tr("ui.fps"), self.fps)
        lay.addLayout(form)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        lay.addWidget(self.progress)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = button(tr("ui.cancel"), variant="ghost")
        cancel.clicked.connect(self.reject)
        self.ok = button(tr("ui.save_as"), "download", "primary")
        self.ok.clicked.connect(self._save)
        row.addWidget(cancel)
        row.addWidget(self.ok)
        lay.addLayout(row)

    def _save(self):
        ext = {"svg": "SVG (*.svg)", "png": "PNG (*.png)", "gif": "GIF (*.gif)", "mp4": "MP4 (*.mp4)"}[self.fmt]
        start = os.path.join(os.path.expanduser("~"), f"{self.default_name}.{self.fmt}")
        dest, _ = QFileDialog.getSaveFileName(self, tr("ui.save_as"), start, ext)
        if not dest:
            return
        if not dest.lower().endswith("." + self.fmt):
            dest += "." + self.fmt
        stroke = self.stroke.color()
        stroke = None if stroke.lower() == "#000000" else stroke
        bg = self.background.color()
        bg = None if bg == "transparent" else bg
        try:
            if self.fmt == "svg":
                export.export_svg(self.svg_path, dest, stroke, self.width_scale.value(), bg)
            elif self.fmt == "png":
                export.export_png(self.svg_path, dest, self.size.value(), stroke, self.width_scale.value(), bg)
            else:
                self.ok.setEnabled(False)
                self.progress.setVisible(True)

                def prog(a, b):
                    self.progress.setMaximum(b)
                    self.progress.setValue(a)

                run_in_thread(self, export.export_animation, self.run_dir, dest, size=self.size.value(),
                              fps=self.fps.value(), stroke_color=stroke, width_scale=self.width_scale.value(),
                              background=bg or "#FFFFFF", on_progress=prog,
                              on_done=lambda _: self._finished(dest),
                              on_error=lambda msg: self._failed(msg))
                return
        except Exception as exc:
            self._failed(str(exc))
            return
        self._finished(dest)

    def _finished(self, dest):
        self.saved_path = dest
        self.accept()

    def _failed(self, msg):
        self.ok.setEnabled(True)
        self.progress.setVisible(False)
        QMessageBox.warning(self, tr("ui.error"), msg)


class ModelDownloadDialog(QDialog):
    """Downloads one or more optional models with a progress bar."""

    def __init__(self, spec_keys: list[str], parent=None):
        super().__init__(parent)
        self.keys = list(spec_keys)
        self.setWindowTitle(tr("ui.download_models"))
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(12)
        lay.addWidget(label(tr("ui.download_models"), "h2"))
        total = sum(model_store.SPECS[k].download_size for k in self.keys) / 1e6
        names = ", ".join(model_display_name(k) for k in self.keys)
        lay.addWidget(label(tr("ui.download_models_desc", names=names, mb=f"{total:.0f}"), "muted", wrap=True))
        self.status = label("", "faint")
        lay.addWidget(self.status)
        self.bar = QProgressBar()
        lay.addWidget(self.bar)
        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_btn = button(tr("ui.cancel"), variant="ghost")
        self.cancel_btn.clicked.connect(self.reject)
        self.start_btn = button(tr("ui.download"), "download", "primary")
        self.start_btn.clicked.connect(self._start)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.start_btn)
        lay.addLayout(row)
        self._idx = 0
        self._cancel = False

    def reject(self):
        self._cancel = True
        super().reject()

    def _start(self):
        self.start_btn.setEnabled(False)
        self._next()

    def _next(self):
        if self._idx >= len(self.keys):
            self.accept()
            return
        key = self.keys[self._idx]
        self.status.setText(tr("ui.downloading", name=model_display_name(key)))

        def prog(a, b):
            self.bar.setMaximum(max(b, 1))
            self.bar.setValue(a)

        def done(_):
            self._idx += 1
            self._next()

        run_in_thread(self, model_store.install, key, cancel=lambda: self._cancel, on_progress=prog, on_done=done,
                      on_error=lambda msg: self._error(msg))

    def _error(self, msg):
        if self._cancel:
            return
        QMessageBox.warning(self, tr("ui.error"), msg)
        self.start_btn.setEnabled(True)


MODEL_NAMES = {
    "u2net": "U²-Net", "dino": "DINO ViT-S/8", "vgg16": "VGG16 (LPIPS)",
    "swiftsketch:diffusion": "SwiftSketch · Diffusion", "swiftsketch:refine": "SwiftSketch · Refinement",
    "sd15": "Stable Diffusion 1.5", "dpt-hybrid": "MiDaS DPT-Hybrid", "hed": "HED", "upernet": "UperNet ConvNeXt",
    "blip": "BLIP", "sdxl": "Stable Diffusion XL",
}


def model_display_name(key: str) -> str:
    if key.startswith("clip:"):
        return f"CLIP {key.split(':', 1)[1]}"
    if key.startswith("controlnet:"):
        return f"ControlNet · {key.split(':', 1)[1]}"
    return MODEL_NAMES.get(key, key)


def ask_download_missing(parent: QWidget, keys: list[str]) -> bool:
    dlg = ModelDownloadDialog(keys, parent)
    return dlg.exec() == QDialog.Accepted


def info_box(parent, title: str, text: str) -> None:
    QMessageBox.information(parent, title, text)


