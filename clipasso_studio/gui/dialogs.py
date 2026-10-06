"""Dialogs: export options and model download."""

from __future__ import annotations

import os

import shiboken6
from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QMessageBox, QProgressBar, QPushButton, QSpinBox, QVBoxLayout,
                               QWidget)

from ..engine import framing, model_store
from . import brush, export, paper, theme
from .app_settings import app_settings
from .i18n import i18n, tr
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


class PaperChoice(QWidget):
    """The paper of an export (``paper.KINDS``) and its vignette (0 – 100 %)."""

    kind_changed = Signal(str)

    def __init__(self, kind: str = "none", vignette: int = 0, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.combo = QComboBox()
        for key in paper.KINDS:
            self.combo.addItem(tr(f"ui.paper.{key}"), key)
        self.combo.setToolTip(tr("ui.paper.tip"))
        self.combo.setCurrentIndex(max(self.combo.findData(kind), 0))
        self.vignette = QSpinBox()
        self.vignette.setRange(0, 100)
        self.vignette.setSingleStep(5)
        self.vignette.setSuffix(" %")
        try:
            self.vignette.setValue(int(vignette or 0))
        except (TypeError, ValueError):
            self.vignette.setValue(0)
        self.vignette.setToolTip(tr("ui.paper.vignette_tip"))
        row.addWidget(self.combo, 1)
        row.addWidget(label(tr("ui.paper.vignette"), "faint"))
        row.addWidget(self.vignette)
        self.combo.currentIndexChanged.connect(lambda _=0: self.kind_changed.emit(self.kind()))

    def kind(self) -> str:
        return self.combo.currentData()

    def paper(self) -> dict | None:
        return paper.normalize({"kind": self.kind(), "vignette": self.vignette.value() / 100})


def paper_colours(kind: str | None, background: "ColorButton", stroke: "ColorButton") -> None:
    """Another paper brings its own colour (``kind`` None: only the background colour changed); on a dark
    background black strokes become light – and back to black on a light one."""
    if kind and kind != "none":
        background.set_color(paper.COLORS[kind])
    color = background.color()
    dark = color != "transparent" and paper.is_dark(color)
    if dark and stroke.color().lower() == "#000000":
        stroke.set_color(paper.LIGHT_STROKE)
    elif not dark and stroke.color().lower() == paper.LIGHT_STROKE.lower():
        stroke.set_color("#000000")


def error_text(exc: BaseException) -> str:
    """The message of an error in the app's language (engine.errors.UserError has a text key)."""
    code = getattr(exc, "code", None)
    if code and i18n.has(f"ui.err.{code}"):
        params = dict(getattr(exc, "params", {}) or {})
        if "model" in params:
            params.setdefault("name", model_display_name(params["model"]))
        try:
            return tr(f"ui.err.{code}", **params)
        except (KeyError, IndexError, ValueError):
            pass
    return str(exc)


def set_progress(bar: QProgressBar, done, total) -> None:
    """Show ``done`` of ``total`` on a bar in per mille (byte counts of big downloads do not fit the
    32-bit range of QProgressBar); a total <= 0 shows a busy bar."""
    if total > 0:
        bar.setRange(0, 1000)
        bar.setValue(max(0, min(1000, int(1000 * done / total))))
    else:
        bar.setRange(0, 0)


class _Worker(QObject):
    progress = Signal("qint64", "qint64")  # 64 bit: downloads over 2 GiB (SDXL, the GPU update)
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
            self.failed.emit(error_text(exc))


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

    @Slot("qint64", "qint64")
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
DRAWN = ("svganim", "lottie", "html")  # the finished strokes drawn one by one, in the browser or an app
TIMED = ANIMATIONS + DRAWN  # formats with a drawing length
EXTENSIONS = {"svg1": "svg", "svglayers": "svg", "matrix": "zip", "svganim": "svg", "lottie": "json", "html": "html"}
FILTERS = {"svg": "SVG (*.svg)", "png": "PNG (*.png)", "gif": "GIF (*.gif)", "mp4": "MP4 (*.mp4)",
           "webp": "WebP (*.webp)", "zip": "ZIP (*.zip)", "pdf": "PDF (*.pdf)", "json": "Lottie (*.json)",
           "html": "HTML (*.html)"}


class BusyDialog(QDialog):
    """A short "please wait" with a progress bar for work in ``run_in_thread``; ``exec()`` is
    accepted when the work is done, rejected with ``error`` set when it failed."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.error = ""
        self.setWindowTitle(text)
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.addWidget(label(text, "muted", wrap=True))
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        lay.addWidget(self.bar)

    def progress(self, done: int, total: int):
        if total > 0:
            set_progress(self.bar, done, total)

    def fail(self, message: str):
        self.error = message
        self.reject()

    def reject(self):  # not closable by Esc while the work runs
        if self.error:
            super().reject()


class CountdownDialog(QDialog):
    """"The queue is done – the PC goes to sleep / shuts down in 60 s" with Cancel and Now; accepted
    when the time is up or on Now."""

    SECONDS = 60

    def __init__(self, action: str, parent=None):
        super().__init__(parent)
        self.action = action
        self.left = self.SECONDS
        self.setWindowTitle(tr("ui.queue.done_title"))
        self.setMinimumWidth(400)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(12)
        lay.addWidget(label(tr("ui.queue.done_title"), "h2"))
        self.text = label("", "muted", wrap=True)
        lay.addWidget(self.text)
        self.bar = QProgressBar()
        self.bar.setRange(0, self.SECONDS)
        self.bar.setTextVisible(False)
        lay.addWidget(self.bar)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = button(tr("ui.cancel"), None, "ghost")
        cancel.clicked.connect(self.reject)
        now = button(tr(f"ui.queue.done_now_{action}"), None, "primary")
        now.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(now)
        lay.addLayout(row)
        cancel.setFocus()
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self._show()

    def _show(self):
        self.text.setText(tr(f"ui.queue.done_text_{self.action}", s=self.left))
        self.bar.setValue(self.SECONDS - self.left)

    def _tick(self):
        self.left -= 1
        self._show()
        if self.left <= 0:
            self.timer.stop()
            self.accept()

    def done(self, result):
        self.timer.stop()
        super().done(result)


def frame_combo(svg_path: str | None = None) -> QComboBox:
    """Choice of the export frame (square / like the photo / cropped to the strokes), set to the last
    choice; "like the photo" is greyed out for a sketch whose photo shape is not known."""
    combo = QComboBox()
    for key in framing.MODES:
        combo.addItem(tr(f"ui.frame.{key}"), key)
    combo.setToolTip(tr("ui.frame.tip"))
    if svg_path is not None:
        try:
            unknown = export.framing_for(svg_path, "photo") is None
        except Exception:
            unknown = True
        if unknown:
            item = combo.model().item(framing.MODES.index("photo"))
            item.setEnabled(False)
            item.setToolTip(tr("ui.frame.photo_unknown"))
    index = combo.findData(app_settings().get("export_frame", "square"))
    if index < 0 or not combo.model().item(index).isEnabled():
        index = 0
    combo.setCurrentIndex(index)
    return combo


def margin_spin() -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(0, 50)
    spin.setSuffix(" %")
    try:
        spin.setValue(int(app_settings().get("export_margin", 5)))
    except (TypeError, ValueError):
        spin.setValue(5)
    spin.setToolTip(tr("ui.frame.margin_tip"))
    return spin


def copy_sketch(svg_path: str) -> None:
    """Put a sketch on the clipboard with the choices of the last export (white instead of a
    transparent background – many programs paste transparency as black)."""
    st = app_settings()
    stroke = st.get("export_stroke", "#000000")
    background = st.get("export_background", "#FFFFFF")
    try:
        margin = int(st.get("export_margin", 5)) / 100
    except (TypeError, ValueError):
        margin = framing.DEFAULT_MARGIN
    try:
        vignette = int(st.get("export_vignette", 0) or 0) / 100
    except (TypeError, ValueError):
        vignette = 0.0
    data = export.sketch_mime(svg_path, 1024, None if str(stroke).lower() == "#000000" else stroke,
                              float(st.get("export_width", 1.0)),
                              "#FFFFFF" if background in (None, "", "transparent") else background,
                              st.get("export_style", "plain"), st.get("export_frame", "square"), margin,
                              paper={"kind": st.get("export_paper", "none"), "vignette": vignette})
    QGuiApplication.clipboard().setMimeData(data)


def release_clipboard() -> None:
    """At exit: a sketch copied by the app is replaced by a copy Qt owns (the image). Qt deletes the
    clipboard data after Python has shut down, and a QMimeData made in Python crashes then; the
    picture stays on the clipboard after the app is closed."""
    cb = QGuiApplication.clipboard()
    data = cb.mimeData()
    if data is not None and data.hasFormat(export.CLIPBOARD_MARK):
        image = cb.image()
        if image.isNull():
            cb.clear()
        else:
            cb.setImage(image)


def _stroke_count(svg_path: str) -> int:
    try:
        with open(svg_path, encoding="utf-8") as f:
            return f.read().count("<path")
    except OSError:
        return 0


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
        title = {"svg1": tr("ui.export_svg1"), "svglayers": tr("ui.export_svglayers"), "webp": "WebP",
                 "matrix": tr("ui.export_matrix"),
                 "svganim": tr("ui.export_svganim"), "lottie": "Lottie",
                 "html": tr("ui.export_html")}.get(fmt, fmt.upper())
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
        remembered = app_settings()  # the choices of the last export
        self.stroke = ColorButton(str(remembered.get("export_stroke", "#000000") or "#000000"))
        form.addRow(tr("ui.stroke_color"), self.stroke)
        self.width_scale = QDoubleSpinBox()
        self.width_scale.setRange(0.1, 10.0)
        self.width_scale.setSingleStep(0.1)
        try:
            self.width_scale.setValue(float(remembered.get("export_width", 1.0) or 1.0))
        except (TypeError, ValueError):
            self.width_scale.setValue(1.0)
        self.width_scale.setSuffix(" ×")
        form.addRow(tr("ui.stroke_width_scale"), self.width_scale)
        self.style = QComboBox()
        for key in brush.STYLES:
            self.style.addItem(tr(f"ui.brush.{key}"), key)
        self.style.setToolTip(tr("ui.brush.tip"))
        last = app_settings().get("export_style", "plain")
        self.style.setCurrentIndex(max(self.style.findData(last), 0))
        if fmt not in ("svg1", "lottie"):  # the plotter SVG and Lottie stay plain lines
            form.addRow(tr("ui.brush.label"), self.style)
        allow_transparent = fmt in ("svg", "svglayers", "png", "webp", "matrix", "svganim", "pdf", "lottie")
        bg = remembered.get("export_background") or ("#FFFFFF" if fmt not in ("svg", "svglayers", "svganim", "lottie")
                                                     else "transparent")
        if bg == "transparent" and not allow_transparent:
            bg = "#FFFFFF"
        self.background = ColorButton(bg, allow_transparent=allow_transparent)
        self.paper = PaperChoice(remembered.get("export_paper", "none"), remembered.get("export_vignette", 0))
        if fmt != "svg1":
            form.addRow(tr("ui.background"), self.background)
            form.addRow(tr("ui.paper.label"), self.paper)
            self.paper.kind_changed.connect(lambda k: paper_colours(k, self.background, self.stroke))
            self.background.changed.connect(lambda _c: paper_colours(None, self.background, self.stroke))
        # the shape of the picture: the square canvas, like the photo, or cropped to the strokes
        self.frame = frame_combo(svg_path if fmt != "matrix" else None)
        self.margin = margin_spin()
        self.margin_label = label(tr("ui.frame.margin"), None)
        if fmt != "matrix":
            form.addRow(tr("ui.frame.label"), self.frame)
            form.addRow(self.margin_label, self.margin)
        self.frame.currentIndexChanged.connect(self._frame_changed)
        self.size = QSpinBox()
        self.size.setRange(64, 8192)
        self.size.setSingleStep(128)
        self.size.setValue(1024 if fmt in ("png", "matrix") else 512)
        self.size.setSuffix(" px")
        self.size.setToolTip(tr("ui.size_longest"))
        if fmt not in ("svg", "svg1", "svglayers", "svganim", "pdf", "lottie", "html"):
            form.addRow(tr("ui.size"), self.size)
        self.width_cm = QDoubleSpinBox()  # PDF: the printed width
        self.width_cm.setRange(2.0, 200.0)
        self.width_cm.setSingleStep(1.0)
        self.width_cm.setDecimals(1)
        self.width_cm.setSuffix(" cm")
        self.width_cm.setValue(float(app_settings().get("export_pdf_width", export.PDF_WIDTH_CM)))
        if fmt == "pdf":
            form.addRow(tr("ui.export_pdf_width"), self.width_cm)
        # animations: the drawing process (optimisation history) or the finished strokes one by one
        self.process_frames = len(export.animation_frames(run_dir)) if fmt in ANIMATIONS else 0
        self.strokes = _stroke_count(svg_path) if fmt in TIMED else 0
        self.draw_length = export.drawing_length(svg_path) if fmt in TIMED else 2.0
        self.mode = QComboBox()
        self.mode.addItem(tr("ui.export_mode.process"), "process")
        self.mode.addItem(tr("ui.export_mode.strokes"), "strokes")
        self.mode.setToolTip(tr("ui.export_mode.tip"))
        # (one saved step is no process to show: then stroke by stroke)
        wanted = "strokes" if fmt in DRAWN or self.process_frames < 2 else \
            app_settings().get("export_anim_mode", "process")
        self.mode.setCurrentIndex(max(self.mode.findData(wanted), 0))
        if fmt in ANIMATIONS:
            form.addRow(tr("ui.export_mode.label"), self.mode)
            self.mode.setEnabled(self.process_frames > 1)
        self.frames = self._frames()
        self.length = QDoubleSpinBox()
        self.length.setRange(0.5, 300.0)
        self.length.setSingleStep(0.5)
        self.length.setDecimals(1)
        self.length.setSuffix(" s")
        self.length.setValue(self._default_length())
        self.hold = QDoubleSpinBox()
        self.hold.setRange(0.0, 10.0)
        self.hold.setSingleStep(0.5)
        self.hold.setDecimals(1)
        self.hold.setSuffix(" s")
        self.hold.setValue(1.0)
        self.timing = label("", "faint")
        # "drawing process": one frame for every saved step (fine animations, see the save step setting)
        self.every_step = button(tr("ui.export_every_step"), variant="ghost", size="sm")
        self.every_step.setToolTip(tr("ui.export_every_step_tip"))
        self.every_step.clicked.connect(self._every_step)
        length_row = QWidget()
        row_lay = QHBoxLayout(length_row)
        row_lay.setContentsMargins(0, 0, 0, 0)
        row_lay.addWidget(self.length, 1)
        row_lay.addWidget(self.every_step)
        if fmt in TIMED:
            form.addRow(tr("ui.export_length"), length_row)
            form.addRow(tr("ui.export_hold"), self.hold)
            form.addRow("", self.timing)
            for w in (self.length, self.hold, self.size):
                w.valueChanged.connect(self._update_timing)
            self.mode.currentIndexChanged.connect(self._mode_changed)
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
        self._frame_changed()

    def _frame_changed(self):
        content = self.frame.currentData() == "content" and self.fmt != "matrix"
        self.margin.setVisible(content)
        self.margin_label.setVisible(content)

    def _shape(self) -> dict:
        return {"frame": self.frame.currentData(), "margin": self.margin.value() / 100}

    def _drawing(self) -> bool:
        return self.fmt in DRAWN or self.mode.currentData() == "strokes"

    def _frames(self) -> int:
        if self._drawing():
            length = self.length.value() if hasattr(self, "length") else self.draw_length
            return max(2, round(length * export.DRAW_STEPS_PER_SECOND))
        return self.process_frames

    def _default_length(self) -> float:
        if self._drawing():
            return self.draw_length
        return default_animation_length(self.process_frames)

    def _every_step(self):
        """The length at which every saved step of the drawing process gets its own frame."""
        self.length.setValue(min(self.length.maximum(), export.every_step_length(self.process_frames, self.ext)))

    def _mode_changed(self):
        self.length.blockSignals(True)
        self.length.setValue(self._default_length())
        self.length.blockSignals(False)
        self._update_timing()

    def _update_timing(self):
        self.frames = self._frames()
        self.every_step.setVisible(self.fmt in ANIMATIONS and not self._drawing() and self.process_frames > 1)
        if self.fmt in DRAWN:
            self.timing.setText(tr("ui.export_timing_svg", strokes=self.strokes,
                                   total=f"{self.length.value() + self.hold.value():.1f}"))
            return
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
        suffix = {"svg1": "_1layer", "svglayers": "_layers", "matrix": "_matrix", "svganim": "_animated"}.get(
            self.fmt, "")
        folder = app_settings().get("export_dir") or ""
        if not os.path.isdir(folder):
            folder = os.path.expanduser("~")
        start = os.path.join(folder, f"{self.default_name}{suffix}.{self.ext}")
        dest, _ = QFileDialog.getSaveFileName(self, tr("ui.save_as"), start, ext)
        if not dest:
            return
        if not dest.lower().endswith("." + self.ext):
            dest += "." + self.ext
        app_settings().set("export_dir", os.path.dirname(os.path.abspath(dest)))
        app_settings().set("export_last_format", self.fmt)
        stroke = self.stroke.color()
        stroke = None if stroke.lower() == "#000000" else stroke
        bg = self.background.color()
        bg = None if bg == "transparent" else bg
        style = self.style.currentData() if self.fmt != "svg1" else "plain"
        app_settings().set("export_style", self.style.currentData())
        # remembered for "Copy" (Ctrl+C), which has no dialog
        app_settings().set("export_stroke", self.stroke.color())
        app_settings().set("export_width", self.width_scale.value())
        pp = self.paper.paper() if self.fmt != "svg1" else None
        if self.fmt != "svg1":
            app_settings().set("export_background", self.background.color())
            app_settings().data["export_vignette"] = self.paper.vignette.value()
            app_settings().set("export_paper", self.paper.kind())
        if self.fmt in ANIMATIONS and self.mode.isEnabled():
            app_settings().set("export_anim_mode", self.mode.currentData())
        shape = self._shape() if self.fmt != "matrix" else {}
        if shape:
            app_settings().data["export_margin"] = self.margin.value()
            app_settings().set("export_frame", shape["frame"])
        try:
            if self.fmt in ("svg", "svglayers"):
                write = export.export_svg if self.fmt == "svg" else export.export_layered_svg
                write(self.svg_path, dest, stroke, self.width_scale.value(), bg, style, **shape, paper=pp)
            elif self.fmt == "svg1":
                export.export_single_layer_svg(self.svg_path, dest, stroke, self.width_scale.value(), **shape)
            elif self.fmt in ("png", "pdf"):  # big images take a while: in the background
                if self.fmt == "pdf":
                    app_settings().set("export_pdf_width", self.width_cm.value())
                args = (self.svg_path, dest, self.size.value() if self.fmt == "png" else self.width_cm.value(),
                        stroke, self.width_scale.value(), bg, style)
                write = export.export_png if self.fmt == "png" else export.export_pdf

                def job(progress=None):
                    write(*args, **shape, paper=pp)
                    return dest

                self.ok.setEnabled(False)
                self.progress.setRange(0, 0)
                self.progress.setVisible(True)
                self.busy, self._cancel = True, False
                run_in_thread(self, job, on_done=lambda _: self._finished(dest), on_error=self._failed)
                return
            elif self.fmt == "lottie":
                export.export_lottie(self.svg_path, dest, self.length.value(), self.hold.value(), stroke,
                                     self.width_scale.value(), bg, **shape, paper=pp)
            elif self.fmt == "html":
                export.export_web_page(self.svg_path, dest, self.length.value(), self.hold.value(), stroke,
                                       self.width_scale.value(), bg, style, **shape, paper=pp)
            elif self.fmt == "svganim":
                export.export_animated_svg(self.svg_path, dest, self.length.value(), self.hold.value(), stroke,
                                           self.width_scale.value(), bg, style, **shape, paper=pp)
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
                          "background": bg, "style": style, "paper": pp, "cancel": lambda: self._cancel,
                          "on_progress": prog,
                          "on_done": lambda _: self._finished(dest), "on_error": self._failed}
                if self.fmt == "matrix":
                    run_in_thread(self, export.export_matrix_zip, self.run_dir, dest, **common)
                elif self._drawing():
                    run_in_thread(self, export.export_drawing, self.svg_path, dest, length=self.length.value(),
                                  hold=self.hold.value(), **common, **shape)
                else:
                    run_in_thread(self, export.export_animation, self.run_dir, dest, length=self.length.value(),
                                  hold=self.hold.value(), **common, **shape)
                return
        except Exception as exc:
            self._failed(error_text(exc))
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


class ContinueDialog(QDialog):
    """Continue a sketch with CLIPasso: how many new strokes, how long, and whether the strokes drawn by
    hand stay where they are."""

    NEW_STROKES = 4
    ITERATIONS = 501

    def __init__(self, strokes: int, fixed: int, parent=None):
        super().__init__(parent)
        self.strokes = strokes
        self.setWindowTitle(tr("ui.continue.title"))
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(14)
        lay.addWidget(label(tr("ui.continue.title"), "h2"))
        lay.addWidget(label(tr("ui.continue.desc"), "muted", wrap=True))
        form = QFormLayout()
        form.setSpacing(10)
        self.new = QSpinBox()
        self.new.setRange(0, 128)
        self.new.setValue(self.NEW_STROKES)
        self.new.valueChanged.connect(self._update)
        form.addRow(tr("ui.continue.new"), self.new)
        self.iterations = QSpinBox()
        self.iterations.setRange(1, 20000)
        self.iterations.setSingleStep(100)
        self.iterations.setValue(self.ITERATIONS)
        form.addRow(tr("ui.continue.iterations"), self.iterations)
        lay.addLayout(form)
        self.keep = QCheckBox(tr("ui.continue.keep", n=fixed))
        self.keep.setChecked(fixed > 0)
        self.keep.setEnabled(fixed > 0)
        self.keep.setToolTip(tr("ui.continue.keep_tip"))
        lay.addWidget(self.keep)
        self.summary = label("", "faint", wrap=True)
        lay.addWidget(self.summary)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = button(tr("ui.cancel"), variant="ghost")
        cancel.clicked.connect(self.reject)
        self.ok = button(tr("ui.continue.start"), "play", "primary")
        self.ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(self.ok)
        lay.addLayout(row)
        self._update()

    def _update(self):
        self.summary.setText(tr("ui.continue.summary", old=self.strokes, new=self.new.value(),
                                total=self.strokes + self.new.value()))

    def values(self) -> tuple[int, int, bool]:
        """(new strokes, iterations, keep the strokes drawn by hand)"""
        return self.new.value(), self.iterations.value(), self.keep.isChecked()


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
            self.format.addItem({"svg": "SVG", "svg1": tr("ui.export_svg1"), "png": "PNG", "pdf": "PDF"}[key], key)
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
        remembered = app_settings()
        self.paper = PaperChoice(remembered.get("export_paper", "none"), remembered.get("export_vignette", 0))
        if self.paper.kind() != "none":
            self.background.set_color(paper.color_of({"kind": self.paper.kind()},
                                                     remembered.get("export_background")))
        self.paper_label = label(tr("ui.paper.label"), None)
        form.addRow(self.paper_label, self.paper)
        self.paper.kind_changed.connect(lambda k: paper_colours(k, self.background, self.stroke))
        self.background.changed.connect(lambda _c: paper_colours(None, self.background, self.stroke))
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
        self.frame = frame_combo()  # "like the photo": sketches whose photo shape is not known stay square
        form.addRow(tr("ui.frame.label"), self.frame)
        self.margin = margin_spin()
        self.margin_label = label(tr("ui.frame.margin"), None)
        form.addRow(self.margin_label, self.margin)
        self.frame.currentIndexChanged.connect(self._format_changed)
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
        for w in (self.background, self.bg_label, self.style, self.style_label, self.paper, self.paper_label):
            w.setVisible(fmt != "svg1")
        for w in (self.margin, self.margin_label):
            w.setVisible(self.frame.currentData() == "content")

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
                      frame=self.frame.currentData(), margin=self.margin.value() / 100,
                      paper=self.paper.paper() if fmt != "svg1" else None,
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


class WhatsNewDialog(QDialog):
    """Release notes (Markdown): of a new release (GitHub) or of this version (after an update)."""

    def __init__(self, title: str, text: str, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QTextBrowser

        self.setWindowTitle(title)
        self.resize(640, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(12)
        self.title = label(title, "h2")
        lay.addWidget(self.title)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setMarkdown(text)
        lay.addWidget(self.browser, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        close = button(tr("ui.close"), None, "primary")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)


class UpdateDownloadDialog(QDialog):
    """Downloads and verifies an update (installer or portable exe) with progress and cancel."""

    def __init__(self, release: dict, parent=None, edition: str | None = None, mode: str | None = None,
                 dest_dir=None):
        super().__init__(parent)
        from . import updates

        self.release, self.edition, self.mode, self.dest_dir = release, edition, mode, dest_dir
        self.path = ""
        self.busy = False
        self._cancel = False
        files, _ = updates.update_files(release, *(updates.build_info() if edition is None else (edition, mode)))
        total = sum(f["size"] for f in files) / 1e6
        version = release.get("tag", "").lstrip("v")
        self.setWindowTitle(tr("ui.update.install_title", version=version))
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(12)
        lay.addWidget(label(tr("ui.update.install_title", version=version), "h2"))
        lay.addWidget(label(tr("ui.update.install_desc", mb=f"{total:.0f}"), "muted", wrap=True))
        self.status = label("", "faint")
        lay.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1)
        lay.addWidget(self.bar)
        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_btn = button(tr("ui.cancel"), variant="ghost")
        self.cancel_btn.clicked.connect(self.reject)
        row.addWidget(self.cancel_btn)
        lay.addLayout(row)

    def start(self):
        from . import updates

        self.busy = True
        self.status.setText(tr("ui.update.downloading"))

        def prog(a, b):
            set_progress(self.bar, a, b)
            if b <= 0:
                self.status.setText(tr("ui.update.checking"))
            else:
                self.status.setText(tr("ui.update.progress", done=f"{a / 1e6:.0f}", total=f"{b / 1e6:.0f}"))

        def done(path):
            self.busy = False
            self.path = path
            if self._cancel:
                super(UpdateDownloadDialog, self).reject()
            else:
                self.accept()

        def failed(msg):
            self.busy = False
            if self._cancel:
                super(UpdateDownloadDialog, self).reject()
                return
            QMessageBox.warning(self, tr("ui.error"), msg)
            super(UpdateDownloadDialog, self).reject()

        run_in_thread(self, updates.download_update, self.release, self.edition, self.mode, self.dest_dir,
                      cancel=lambda: self._cancel, on_progress=prog, on_done=done, on_error=failed)

    def exec(self):  # noqa: A003 – start the download together with the dialog
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, self.start)
        return super().exec()

    def reject(self):
        if self.busy:  # the download stops; files downloaded so far are kept for the next try
            self._cancel = True
            self.cancel_btn.setEnabled(False)
            self.status.setText(tr("ui.cancelling"))
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
        from .background import work

        if work().busy("models"):  # the models are moving to another folder: after that
            self.status.setText(tr("ui.work.models_locked"))
            return
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
            set_progress(self.bar, a, b)
            if b <= 0:  # downloaded; checking and converting
                self.status.setText(tr("ui.preparing_model", name=name))

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
    "birefnet": "BiRefNet", "birefnet-lite": "BiRefNet lite", "taesd": "TAESD", "blazeface": "BlazeFace",
    "semantic:openclip-b16": "OpenCLIP ViT-B/16 (LAION-2B)", "semantic:siglip-b16": "SigLIP B/16",
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




def webcam_available() -> tuple[bool, str]:
    """(can the webcam be used, why not): needs Qt Multimedia and at least one camera."""
    try:
        from PySide6.QtMultimedia import QMediaDevices
    except Exception:  # not installed, or its system libraries are missing
        return False, "ui.webcam.no_multimedia"
    if not QMediaDevices.videoInputs():
        return False, "ui.webcam.no_camera"
    return True, ""


class WebcamDialog(QDialog):
    """Take the input photo with a webcam: live preview, choice of camera, mirror, a 3-second countdown.
    The photo is saved in ``folder`` (``path`` after accept())."""

    COUNTDOWN = 3

    def __init__(self, folder: str, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QLabel

        self.folder = folder
        self.path = ""
        self._frame = None  # the latest camera image
        self._left = 0
        self.setWindowTitle(tr("ui.webcam.title"))
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(12)
        lay.addWidget(label(tr("ui.webcam.title"), "h2"))
        self.view = QLabel()
        self.view.setMinimumSize(512, 384)
        self.view.setAlignment(Qt.AlignCenter)
        self.view.setStyleSheet(f"background: {theme.current().surface2}; border-radius: 10px;")
        lay.addWidget(self.view, 1)
        row = QHBoxLayout()
        self.cameras = QComboBox()
        self.mirror = QCheckBox(tr("ui.webcam.mirror"))
        self.mirror.setChecked(bool(app_settings().get("webcam_mirror", True)))
        self.mirror.toggled.connect(lambda v: app_settings().set("webcam_mirror", v))
        row.addWidget(self.cameras, 1)
        row.addWidget(self.mirror)
        lay.addLayout(row)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = button(tr("ui.cancel"), variant="ghost")
        cancel.clicked.connect(self.reject)
        self.shoot = button(tr("ui.webcam.shoot"), "camera", "primary")
        self.shoot.clicked.connect(self._start_countdown)
        buttons.addWidget(cancel)
        buttons.addWidget(self.shoot)
        lay.addLayout(buttons)
        self._timer = QTimer(self, interval=1000)
        self._timer.timeout.connect(self._tick)
        self.camera = self.session = self.sink = None
        ok, why = webcam_available()
        self.available = ok
        if not ok:
            self.view.setText(tr(why))
            self.shoot.setEnabled(False)
            self.cameras.setEnabled(False)
            return
        from PySide6.QtMultimedia import QMediaCaptureSession, QMediaDevices, QVideoSink

        self._devices = QMediaDevices.videoInputs()
        for dev in self._devices:
            self.cameras.addItem(dev.description())
        self.session = QMediaCaptureSession(self)
        self.sink = QVideoSink(self)
        self.sink.videoFrameChanged.connect(self._frame_arrived)
        self.session.setVideoSink(self.sink)
        self.cameras.currentIndexChanged.connect(self._use_camera)
        self._use_camera(0)

    def _use_camera(self, index: int):
        from PySide6.QtMultimedia import QCamera

        if self.camera is not None:
            self.camera.stop()
        self.camera = QCamera(self._devices[index], self)
        self.session.setCamera(self.camera)
        self.camera.start()

    def _frame_arrived(self, frame):
        img = frame.toImage()
        if img.isNull():
            return
        self.show_image(img)

    def show_image(self, img):
        """A camera image: shown (mirrored if wanted) and kept for the photo."""
        from PySide6.QtGui import QPixmap

        if self.mirror.isChecked():
            img = img.flipped(Qt.Horizontal) if hasattr(img, "flipped") else img.mirrored(True, False)
        self._frame = img
        pm = QPixmap.fromImage(img).scaled(self.view.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if self._left:
            from PySide6.QtGui import QFont, QPainter

            p = QPainter(pm)
            font = QFont(p.font())
            font.setPointSize(64)
            font.setBold(True)
            p.setFont(font)
            p.setPen(QColor("white"))
            p.drawText(pm.rect(), Qt.AlignCenter, str(self._left))
            p.end()
        self.view.setPixmap(pm)

    def _start_countdown(self):
        self._left = self.COUNTDOWN
        self.shoot.setEnabled(False)
        self._timer.start()

    def _tick(self):
        self._left -= 1
        if self._left <= 0:
            self._timer.stop()
            self.take()

    def take(self) -> bool:
        """Save the latest camera image and close."""
        if self._frame is None or self._frame.isNull():
            self.shoot.setEnabled(True)
            return False
        import time

        os.makedirs(self.folder, exist_ok=True)
        path = os.path.join(self.folder, time.strftime("webcam-%Y%m%d-%H%M%S.png"))
        n = 1
        while os.path.exists(path):
            n += 1
            path = os.path.join(self.folder, time.strftime(f"webcam-%Y%m%d-%H%M%S-{n}.png"))
        if not self._frame.save(path):
            self.shoot.setEnabled(True)
            return False
        self.path = path
        self.accept()
        return True

    def done(self, result):
        self._timer.stop()
        if self.camera is not None:
            self.camera.stop()
        super().done(result)


def ask_out_of_memory(parent, name: str, on_gpu: bool, smaller: dict | None) -> str | None:
    """"Out of memory": "cpu" (compute it on the CPU), "smaller" (with settings that need less memory) or
    None. Finished sketches of the job are kept either way."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle(tr("ui.oom.title"))
    box.setText(tr("ui.oom.text", name=name))
    box.setInformativeText(tr("ui.oom.info"))
    cpu = box.addButton(tr("ui.oom.cpu"), QMessageBox.AcceptRole) if on_gpu else None
    small = None
    if smaller:
        small = box.addButton(tr("ui.oom.smaller"), QMessageBox.AcceptRole)
        details = ", ".join(f"{k} = {v}" for k, v in smaller.items())
        small.setToolTip(details)
    box.addButton(tr("ui.close"), QMessageBox.RejectRole)
    box.exec()
    clicked = box.clickedButton()
    if cpu is not None and clicked is cpu:
        return "cpu"
    if small is not None and clicked is small:
        return "smaller"
    return None
