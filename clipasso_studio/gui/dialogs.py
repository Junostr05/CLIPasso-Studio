"""Dialogs: export options and model download."""

from __future__ import annotations

import os

import shiboken6
from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QColorDialog, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QMessageBox, QProgressBar, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from ..engine import model_store
from . import brush, export, theme
from .app_settings import app_settings
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


ANIMATIONS = ("gif", "mp4", "webp")
EXTENSIONS = {"svg1": "svg", "matrix": "zip"}
FILTERS = {"svg": "SVG (*.svg)", "png": "PNG (*.png)", "gif": "GIF (*.gif)", "mp4": "MP4 (*.mp4)",
           "webp": "WebP (*.webp)", "zip": "ZIP (*.zip)"}


def default_animation_length(frames: int) -> float:
    """Seconds for the drawing: like the old 20 fps, but between 2 and 10 s."""
    return round(min(10.0, max(2.0, frames / 20)) * 2) / 2


class ExportDialog(QDialog):
    """Options for exporting a sketch (SVG, PNG, GIF, MP4, WebP) or a SceneSketch matrix (ZIP; then
    ``run_dir`` is the job folder)."""

    def __init__(self, fmt: str, svg_path: str, run_dir: str, default_name: str, parent=None):
        super().__init__(parent)
        self.fmt = fmt
        self.svg_path = svg_path
        self.run_dir = run_dir
        self.default_name = default_name
        # "svg1": all strokes as one path in one layer (for plotters / cutting machines)
        self.ext = EXTENSIONS.get(fmt, fmt)
        title = {"svg1": tr("ui.export_svg1"), "webp": "WebP", "matrix": tr("ui.export_matrix")}.get(fmt, fmt.upper())
        heading = tr("ui.export_matrix_title") if fmt == "matrix" else tr("ui.export_title", fmt=title)
        self.setWindowTitle(heading)
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(14)
        lay.addWidget(label(heading, "h2"))
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
        self.style = QComboBox()
        for key in brush.STYLES:
            self.style.addItem(tr(f"ui.brush.{key}"), key)
        self.style.setToolTip(tr("ui.brush.tip"))
        last = app_settings().get("export_style", "plain")
        self.style.setCurrentIndex(max(self.style.findData(last), 0))
        if fmt != "svg1":  # the plotter SVG stays plain lines
            form.addRow(tr("ui.brush.label"), self.style)
        self.background = ColorButton("#FFFFFF" if fmt != "svg" else "transparent", allow_transparent=fmt in
                                      ("svg", "png", "webp", "matrix"))
        if fmt != "svg1":
            form.addRow(tr("ui.background"), self.background)
        self.size = QSpinBox()
        self.size.setRange(64, 8192)
        self.size.setSingleStep(128)
        self.size.setValue(1024 if fmt in ("png", "matrix") else 512)
        self.size.setSuffix(" px")
        if fmt not in ("svg", "svg1"):
            form.addRow(tr("ui.size"), self.size)
        # animations: the length of the drawing is set, the frame rate follows from it
        self.frames = len(export.animation_frames(run_dir)) if fmt in ANIMATIONS else 0
        self.length = QDoubleSpinBox()
        self.length.setRange(0.5, 300.0)
        self.length.setSingleStep(0.5)
        self.length.setDecimals(1)
        self.length.setSuffix(" s")
        self.length.setValue(default_animation_length(self.frames))
        self.hold = QDoubleSpinBox()
        self.hold.setRange(0.0, 10.0)
        self.hold.setSingleStep(0.5)
        self.hold.setDecimals(1)
        self.hold.setSuffix(" s")
        self.hold.setValue(1.0)
        self.timing = label("", "faint")
        if fmt in ANIMATIONS:
            form.addRow(tr("ui.export_length"), self.length)
            form.addRow(tr("ui.export_hold"), self.hold)
            form.addRow("", self.timing)
            for w in (self.length, self.hold, self.size):
                w.valueChanged.connect(self._update_timing)
            self._update_timing()
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

    def _update_timing(self):
        idx, durations = export.animation_plan(self.frames, self.length.value(), hold=self.hold.value(),
                                               fmt=self.fmt, size=self.size.value())
        if not idx:
            self.timing.setText("")
            return
        fps = export.MP4_FPS if self.fmt == "mp4" else len(idx) / self.length.value()
        self.timing.setText(tr("ui.export_timing", fps=f"{fps:.0f}" if fps >= 10 else f"{fps:.1f}",
                               frames=len(idx), total=f"{sum(durations) / 1000:.1f}"))

    def _save(self):
        ext = FILTERS[self.ext]
        suffix = {"svg1": "_1layer", "matrix": "_matrix"}.get(self.fmt, "")
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
        style = self.style.currentData() if self.fmt != "svg1" else "plain"
        app_settings().set("export_style", self.style.currentData())
        try:
            if self.fmt == "svg":
                export.export_svg(self.svg_path, dest, stroke, self.width_scale.value(), bg, style)
            elif self.fmt == "svg1":
                export.export_single_layer_svg(self.svg_path, dest, stroke, self.width_scale.value())
            elif self.fmt == "png":
                export.export_png(self.svg_path, dest, self.size.value(), stroke, self.width_scale.value(), bg,
                                  style)
            else:  # animations and the matrix run in the background
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
                        self.phase.setText(tr("ui.export_encoding", fmt={"webp": "WebP"}.get(self.ext,
                                                                                          self.ext.upper())))
                    else:
                        self.progress.setRange(0, b)
                        self.progress.setValue(a)

                common = {"size": self.size.value(), "stroke_color": stroke, "width_scale": self.width_scale.value(),
                          "background": bg, "style": style, "cancel": lambda: self._cancel, "on_progress": prog,
                          "on_done": lambda _: self._finished(dest), "on_error": self._failed}
                if self.fmt == "matrix":
                    run_in_thread(self, export.export_matrix_zip, self.run_dir, dest, **common)
                else:
                    run_in_thread(self, export.export_animation, self.run_dir, dest, length=self.length.value(),
                                  hold=self.hold.value(), **common)
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


class BatchExportDialog(QDialog):
    """Export the best sketch of many jobs at once (queue, gallery) into one folder."""

    def __init__(self, items: list[tuple[str, dict]], parent=None):
        super().__init__(parent)
        self.items = items
        self.folder = ""
        self.written = 0
        self.busy = False
        self._cancel = False
        self.setWindowTitle(tr("ui.batch.title"))
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(14)
        lay.addWidget(label(tr("ui.batch.title"), "h2"))
        lay.addWidget(label(tr("ui.batch.desc", n=len(items)), "muted", wrap=True))
        form = QFormLayout()
        form.setSpacing(10)
        self.format = QComboBox()
        for key in export.BATCH_FORMATS:
            self.format.addItem({"svg": "SVG", "svg1": tr("ui.export_svg1"), "png": "PNG"}[key], key)
        self.format.currentIndexChanged.connect(self._format_changed)
        form.addRow(tr("ui.batch.format"), self.format)
        self.stroke = ColorButton("#000000")
        form.addRow(tr("ui.stroke_color"), self.stroke)
        self.width_scale = QDoubleSpinBox()
        self.width_scale.setRange(0.1, 10.0)
        self.width_scale.setSingleStep(0.1)
        self.width_scale.setValue(1.0)
        self.width_scale.setSuffix(" ×")
        form.addRow(tr("ui.stroke_width_scale"), self.width_scale)
        self.background = ColorButton("transparent", allow_transparent=True)
        self.bg_label = label(tr("ui.background"), None)
        form.addRow(self.bg_label, self.background)
        self.size = QSpinBox()
        self.size.setRange(64, 8192)
        self.size.setSingleStep(128)
        self.size.setValue(1024)
        self.size.setSuffix(" px")
        self.size_label = label(tr("ui.size"), None)
        form.addRow(self.size_label, self.size)
        self.style = QComboBox()
        for key in brush.STYLES:
            self.style.addItem(tr(f"ui.brush.{key}"), key)
        self.style.setCurrentIndex(max(self.style.findData(app_settings().get("export_style", "plain")), 0))
        self.style_label = label(tr("ui.brush.label"), None)
        form.addRow(self.style_label, self.style)
        lay.addLayout(form)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        lay.addWidget(self.progress)
        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_btn = button(tr("ui.cancel"), variant="ghost")
        self.cancel_btn.clicked.connect(self.reject)
        self.ok = button(tr("ui.batch.choose_folder"), "folder-open", "primary")
        self.ok.clicked.connect(self._choose)
        self.ok.setEnabled(bool(items))
        row.addWidget(self.cancel_btn)
        row.addWidget(self.ok)
        lay.addLayout(row)
        self._format_changed()

    def _format_changed(self):
        fmt = self.format.currentData()
        for w in (self.size, self.size_label):
            w.setVisible(fmt == "png")
        for w in (self.background, self.bg_label, self.style, self.style_label):
            w.setVisible(fmt != "svg1")

    def _choose(self):
        start = app_settings().get("batch_export_dir") or os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(self, tr("ui.batch.choose_folder"), start)
        if folder:
            self.start(folder)

    def start(self, folder: str):
        self.folder = folder
        app_settings().set("batch_export_dir", folder)
        fmt = self.format.currentData()
        stroke = self.stroke.color()
        stroke = None if stroke.lower() == "#000000" else stroke
        bg = self.background.color()
        bg = None if bg == "transparent" else bg
        self.busy, self._cancel = True, False
        self.ok.setEnabled(False)
        self.progress.setRange(0, max(len(self.items), 1))
        self.progress.setValue(0)
        self.progress.setVisible(True)

        def prog(a, b):
            if b > 0:
                self.progress.setValue(a)

        def done(result):
            self.busy = False
            self.written = int(result or 0)
            if self._cancel:
                super(BatchExportDialog, self).reject()
            else:
                self.accept()

        def failed(msg):
            self.busy = False
            if self._cancel:
                super(BatchExportDialog, self).reject()
                return
            self.ok.setEnabled(True)
            self.progress.setVisible(False)
            QMessageBox.warning(self, tr("ui.error"), msg)

        run_in_thread(self, export.export_batch, self.items, folder, fmt=fmt, size=self.size.value(),
                      stroke_color=stroke, width_scale=self.width_scale.value(), background=bg,
                      style=self.style.currentData() if fmt != "svg1" else "plain", cancel=lambda: self._cancel,
                      on_progress=prog, on_done=done, on_error=failed)

    def reject(self):
        if self.busy:
            self._cancel = True
            self.cancel_btn.setEnabled(False)
            return
        super().reject()


def export_many(parent, items: list[tuple[str, dict]]) -> int:
    """Batch export dialog; after it: a message with the folder. Returns the number of files."""
    if not items:
        info_box(parent, tr("ui.batch.title"), tr("ui.batch.nothing"))
        return 0
    dlg = BatchExportDialog(items, parent)
    if dlg.exec() != QDialog.Accepted:
        return 0
    box = QMessageBox(parent)
    box.setWindowTitle(tr("ui.batch.title"))
    box.setText(tr("ui.batch.done", n=dlg.written, folder=dlg.folder))
    open_btn = box.addButton(tr("ui.open_folder"), QMessageBox.ActionRole)
    box.addButton(QMessageBox.Close)
    box.exec()
    if box.clickedButton() is open_btn:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(dlg.folder))
    return dlg.written


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


