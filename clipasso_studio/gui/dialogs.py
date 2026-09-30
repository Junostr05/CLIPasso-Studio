"""Dialogs: export options and model download."""

from __future__ import annotations

import os

import shiboken6
from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
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


class _Relay(QObject):
    """One background job of :func:`run_in_thread`; calls its callbacks in the GUI thread.

    PySide calls a plain Python function connected to a signal in the thread that emits the signal –
    for the worker that is the background thread, and GUI calls from there (progress bars, closing a
    dialog, message boxes) froze and crashed the app at the end of exports and downloads. The relay
    lives in the GUI thread and receives the worker's signals as queued calls instead."""

    def __init__(self, thread: QThread, worker: _Worker, owner, on_progress, on_done, on_error):
        super().__init__()
        self.thread, self.worker, self.owner = thread, worker, owner
        self.on_progress, self.on_done, self.on_error = on_progress, on_done, on_error

    def _owner_alive(self) -> bool:
        return self.owner is None or shiboken6.isValid(self.owner)

    @Slot(int, int)
    def progress(self, done: int, total: int):
        if self.on_progress and self._owner_alive():
            self.on_progress(done, total)

    @Slot(str)
    def finished(self, result: str):
        self._end(self.on_done, result)

    @Slot(str)
    def failed(self, message: str):
        self._end(self.on_error, message)

    def _end(self, callback, arg):
        self.thread.wait(10000)  # the worker has returned; its thread ends right away
        _running.discard(self)
        _ended.append(self)  # released later, outside of this call (see _release_ended)
        if callback and self._owner_alive():
            callback(arg)


# Python owns the thread, worker and relay of every job: no deleteLater and no lambda connections.
# Deleting them through Qt's deferred delete ran PySide's Python cleanup in the GUI thread while the
# next job's thread was running Python code, which crashed PySide 6.11 (the second export in a row).
_running: set = set()
_ended: list = []


def _release_ended() -> None:
    """Drop finished jobs (their threads have ended) – from the GUI thread, never inside their slots."""
    _ended.clear()


def wait_for_threads(timeout_ms: int = 60000) -> None:
    """Wait for the background threads of :func:`run_in_thread` – Qt crashes when a still running
    QThread is destroyed, e.g. when the app quits while the hardware probe imports PyTorch."""
    for job in list(_running):
        try:
            if job.thread.isRunning():
                # the worker's finished -> quit call may not have happened yet
                job.thread.quit()
                job.thread.wait(timeout_ms)
        except RuntimeError:  # the C++ object is already gone
            pass
        _running.discard(job)
    _release_ended()


def run_in_thread(parent, fn, *args, on_progress=None, on_done=None, on_error=None, **kwargs):
    """Run ``fn(*args, progress=…, **kwargs)`` in a background thread. The callbacks are called in the
    GUI thread (and skipped when ``parent`` has been deleted meanwhile); a progress total of 0 means
    "busy, no measurable progress" (e.g. encoding)."""
    _release_ended()
    thread = QThread()
    worker = _Worker(fn, *args, **kwargs)
    worker.moveToThread(thread)
    job = _Relay(thread, worker, parent, on_progress, on_done, on_error)  # lives in the GUI thread
    thread.started.connect(worker.run)
    worker.progress.connect(job.progress)
    worker.finished.connect(job.finished)
    worker.failed.connect(job.failed)
    worker.finished.connect(thread.quit, Qt.DirectConnection)  # QThread.quit is thread-safe
    worker.failed.connect(thread.quit, Qt.DirectConnection)
    _running.add(job)
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
        # "svg1": all strokes as one path in one layer (for plotters / cutting machines)
        self.ext = "svg" if fmt == "svg1" else fmt
        title = tr("ui.export_svg1") if fmt == "svg1" else fmt.upper()
        self.setWindowTitle(tr("ui.export_title", fmt=title))
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(14)
        lay.addWidget(label(tr("ui.export_title", fmt=title), "h2"))
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
        if fmt != "svg1":
            form.addRow(tr("ui.background"), self.background)
        self.size = QSpinBox()
        self.size.setRange(64, 8192)
        self.size.setSingleStep(128)
        self.size.setValue(1024 if fmt == "png" else 512)
        self.size.setSuffix(" px")
        if fmt not in ("svg", "svg1"):
            form.addRow(tr("ui.size"), self.size)
        self.fps = QSpinBox()
        self.fps.setRange(1, 60)
        self.fps.setValue(20)
        self.fps.setSuffix(" fps")
        if fmt in ("gif", "mp4"):
            form.addRow(tr("ui.fps"), self.fps)
        lay.addLayout(form)

        self.phase = label("", "faint")
        self.phase.setVisible(False)
        lay.addWidget(self.phase)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        lay.addWidget(self.progress)
        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_btn = button(tr("ui.cancel"), variant="ghost")
        self.cancel_btn.clicked.connect(self.reject)
        self.ok = button(tr("ui.save_as"), "download", "primary")
        self.ok.clicked.connect(self._save)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.ok)
        lay.addLayout(row)
        self.busy = False  # an animation export is running in the background
        self._cancel = False

    def _save(self):
        ext = {"svg": "SVG (*.svg)", "png": "PNG (*.png)", "gif": "GIF (*.gif)", "mp4": "MP4 (*.mp4)"}[self.ext]
        suffix = "_1layer" if self.fmt == "svg1" else ""
        start = os.path.join(os.path.expanduser("~"), f"{self.default_name}{suffix}.{self.ext}")
        dest, _ = QFileDialog.getSaveFileName(self, tr("ui.save_as"), start, ext)
        if not dest:
            return
        if not dest.lower().endswith("." + self.ext):
            dest += "." + self.ext
        stroke = self.stroke.color()
        stroke = None if stroke.lower() == "#000000" else stroke
        bg = self.background.color()
        bg = None if bg == "transparent" else bg
        try:
            if self.fmt == "svg":
                export.export_svg(self.svg_path, dest, stroke, self.width_scale.value(), bg)
            elif self.fmt == "svg1":
                export.export_single_layer_svg(self.svg_path, dest, stroke, self.width_scale.value())
            elif self.fmt == "png":
                export.export_png(self.svg_path, dest, self.size.value(), stroke, self.width_scale.value(), bg)
            else:
                self.ok.setEnabled(False)
                self.progress.setRange(0, 1)
                self.progress.setValue(0)
                self.progress.setVisible(True)
                self.phase.setText(tr("ui.export_rendering"))
                self.phase.setVisible(True)
                self.busy, self._cancel = True, False

                def prog(a, b):
                    if self._cancel:
                        return
                    if b <= 0:  # all frames drawn, the file is being encoded
                        self.progress.setRange(0, 0)
                        self.phase.setText(tr("ui.export_encoding", fmt=self.ext.upper()))
                    else:
                        self.progress.setRange(0, b)
                        self.progress.setValue(a)

                run_in_thread(self, export.export_animation, self.run_dir, dest, size=self.size.value(),
                              fps=self.fps.value(), stroke_color=stroke, width_scale=self.width_scale.value(),
                              background=bg or "#FFFFFF", cancel=lambda: self._cancel, on_progress=prog,
                              on_done=lambda _: self._finished(dest), on_error=self._failed)
                return
        except Exception as exc:
            self._failed(str(exc))
            return
        self._finished(dest)

    def _finished(self, dest):
        self.busy = False
        if self._cancel:  # finished before the cancel request arrived: keep nothing half-wanted
            try:
                os.remove(dest)
            except OSError:
                pass
            super().reject()
            return
        self.saved_path = dest
        self.accept()

    def _failed(self, msg):
        self.busy = False
        if self._cancel:
            super().reject()
            return
        self.ok.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.phase.setVisible(False)
        QMessageBox.warning(self, tr("ui.error"), msg)

    def reject(self):
        if self.busy:  # stop the export; the dialog closes when the background work has ended
            self._cancel = True
            self.cancel_btn.setEnabled(False)
            self.progress.setRange(0, 0)
            self.phase.setText(tr("ui.cancelling"))
            return
        super().reject()


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
        self.busy = False  # a download is running in the background

    def reject(self):
        self._cancel = True
        if self.busy:  # the dialog closes when the download has stopped
            self.cancel_btn.setEnabled(False)
            self.status.setText(tr("ui.cancelling"))
            return
        super().reject()

    def _start(self):
        self.start_btn.setEnabled(False)
        self._next()

    def _next(self):
        if self._idx >= len(self.keys):
            self.accept()
            return
        key = self.keys[self._idx]
        name = model_display_name(key)
        self.status.setText(tr("ui.downloading", name=name))
        self.bar.setRange(0, 1)
        self.bar.setValue(0)

        def prog(a, b):
            if self._cancel:
                return
            if b <= 0:  # downloaded; checking and converting
                self.bar.setRange(0, 0)
                self.status.setText(tr("ui.preparing_model", name=name))
            else:
                self.bar.setRange(0, b)
                self.bar.setValue(a)

        def done(_):
            self.busy = False
            if self._cancel:
                super(ModelDownloadDialog, self).reject()
                return
            self._idx += 1
            self._next()

        self.busy = True
        run_in_thread(self, model_store.install, key, cancel=lambda: self._cancel, on_progress=prog, on_done=done,
                      on_error=self._error)

    def _error(self, msg):
        self.busy = False
        if self._cancel:
            super().reject()
            return
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        QMessageBox.warning(self, tr("ui.error"), msg)
        self.start_btn.setEnabled(True)


MODEL_NAMES = {
    "u2net": "U²-Net", "dino": "DINO ViT-S/8", "vgg16": "VGG16 (LPIPS)",
    "swiftsketch:diffusion": "SwiftSketch · Diffusion", "swiftsketch:refine": "SwiftSketch · Refinement",
    "sd15": "Stable Diffusion 1.5", "dpt-hybrid": "MiDaS DPT-Hybrid", "hed": "HED", "upernet": "UperNet ConvNeXt",
    "blip": "BLIP", "sdxl": "Stable Diffusion XL", "lama": "LaMa (big-lama)",
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


