"""Studio page: input, live canvas, parameters and results."""

from __future__ import annotations

import json
import os
import shutil
import sys
import time

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QActionGroup, QColor, QDesktopServices, QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import (QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QMenu, QMessageBox,
                               QProgressBar, QScrollArea, QSplitter, QToolButton, QVBoxLayout, QWidget)

from ... import paths
from ... import settings_schema as schema
from ...engine import imaging, jobs, masking, model_store
from .. import brush, dialogs, icons, image_io, mask_view, methods_ui, shortcuts, theme
from ..app_settings import app_settings
from ..controller import JobController, QueuedJob
from ..i18n import i18n, tr
from ..widgets.canvas import (DISPLAY_MAX, IMAGE_EXT, IMAGE_FILTER, ImageDropZone, LossChart, MatrixView, SeedThumb,
                              SketchCanvas, load_pixmap)
from ..widgets.common import Banner, Card, SegmentedControl, ToggleSwitch, WrapRow, button, label, tool_button
from ..widgets.method_picker import MethodPicker
from ..widgets.param_panel import ParamPanel, param_text_key


def _pixmap_from_png(data: bytes) -> QPixmap:
    pm = QPixmap()
    pm.loadFromData(data, "PNG")
    return pm


class StatTile(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.value = label("–", "stat")
        self.caption = label("", "faint")
        lay.addWidget(self.value)
        lay.addWidget(self.caption)


class StudioPage(QWidget):
    toast = Signal(str, str)
    open_queue = Signal()

    def __init__(self, controller: JobController, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        self.controller = controller
        self.image_path: str = ""
        self.view_job: QueuedJob | None = None  # the job whose progress is displayed
        self.view_dir: str = ""  # job folder of the displayed result
        self.selected_seed: int | None = None
        self.thumbs: dict[int, SeedThumb] = {}
        self.seed_svgs: dict[int, str] = {}
        self.seed_attn: dict[int, QPixmap] = {}
        self.seed_runs: dict[int, str] = {}
        self.best_seed: int | None = None
        self.view_method = schema.DEFAULT_METHOD  # method of the displayed run
        self.seed_scores: dict[int, float] = {}
        self._status_key = ("ui.status.idle", {})

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        # ---------------------------------------------------------------- header
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title = label("", "title")
        self.subtitle = label("", "muted")
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        head.addLayout(titles)
        head.addStretch(1)
        self.device_badge = label("", "badge")
        head.addWidget(self.device_badge, 0, Qt.AlignVCenter)
        root.addLayout(head)
        self.picker = MethodPicker()
        root.addWidget(self.picker)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        # ------------------------------------------------------------- left pane
        left = QWidget()
        left.setMinimumHeight(560)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(14)
        self.input_card = Card()
        self.input_title = label("", "h2")
        self.input_card.body.addWidget(self.input_title)
        self.drop = ImageDropZone()
        self.drop.image_dropped.connect(self.set_image)
        self.drop.images_dropped.connect(self.images_dropped)
        self.drop.clicked.connect(self.browse_image)
        self.input_card.body.addWidget(self.drop, 1)
        self.file_label = label("", "faint")
        self.file_label.setWordWrap(True)
        self.input_card.body.addWidget(self.file_label)
        # the object mask, computed in the background as soon as an image is chosen
        self.mask_row = QWidget()
        mrow = QHBoxLayout(self.mask_row)
        mrow.setContentsMargins(0, 0, 0, 0)
        mrow.setSpacing(6)
        self.mask_eye = tool_button("eye", "", 16, checkable=True)
        self.mask_eye.setChecked(bool(app_settings().get("show_mask", True)))
        self.mask_eye.toggled.connect(self._toggle_mask_overlay)
        self.drop.set_show_overlay(self.mask_eye.isChecked())
        self.mask_status = label("", "faint")
        self.mask_dl_btn = button("", "download", "ghost", size="sm")
        self.mask_dl_btn.clicked.connect(self._download_mask_model)
        self.mask_edit_btn = tool_button("brush", "", 16)
        self.mask_edit_btn.clicked.connect(self.edit_mask)
        self.mask_reset_btn = tool_button("rotate-ccw", "", 16)
        self.mask_reset_btn.clicked.connect(self.reset_mask)
        mrow.addWidget(self.mask_eye)
        mrow.addWidget(self.mask_status, 1)
        mrow.addWidget(self.mask_dl_btn)
        mrow.addWidget(self.mask_edit_btn)
        mrow.addWidget(self.mask_reset_btn)
        self.mask_row.hide()
        self.input_card.body.addWidget(self.mask_row)
        self.mask_preview = mask_view.MaskPreviewer(self)
        self.mask_preview.busy.connect(lambda on: on and self._set_mask_status("busy"))
        self.mask_preview.ready.connect(self._mask_ready)
        self.mask_preview.failed.connect(self._mask_failed)
        self._mask: dict | None = None  # the mask shown: key (image, model), probability, edited
        row = QHBoxLayout()
        self.open_btn = button("", "folder-open")
        self.open_btn.clicked.connect(self.browse_image)
        self.samples_btn = button("", "images", "ghost")
        self.samples_menu = QMenu(self)
        self.samples_btn.setMenu(self.samples_menu)
        self.edit_btn = button("", "crop", "ghost")
        self.edit_btn.clicked.connect(self.edit_image)
        self.recent_btn = button("", "clock", "ghost")  # the last images (icon only: the row is narrow)
        self.recent_menu = QMenu(self)
        self.recent_menu.aboutToShow.connect(self._build_recent_menu)
        self.recent_btn.setMenu(self.recent_menu)
        self.webcam_btn = button("", "camera", "ghost")
        self.webcam_btn.clicked.connect(self.take_webcam_photo)
        row.addWidget(self.open_btn)
        row.addWidget(self.samples_btn)
        row.addWidget(self.recent_btn)
        row.addWidget(self.webcam_btn)
        row.addWidget(self.edit_btn)
        row.addStretch(1)
        self.input_card.body.addLayout(row)
        # quick toggles mirrored from the parameter panel
        self.quick = {}
        for key in ("mask_object", "fix_scale", "turbo"):
            r = QHBoxLayout()
            lbl = label("", None)
            sw = ToggleSwitch()
            sw.toggled.connect(lambda v, k=key: self._quick_toggled(k, v))
            r.addWidget(lbl)
            r.addStretch(1)
            r.addWidget(sw)
            self.input_card.body.addLayout(r)
            self.quick[key] = (lbl, sw)
        ll.addWidget(self.input_card, 3)

        self.result_card = Card()
        self.result_title = label("", "h2")
        self.result_card.body.addWidget(self.result_title)
        self.result_hint = label("", "faint", wrap=True)
        self.result_card.body.addWidget(self.result_hint)
        grid = QGridLayout()
        grid.setSpacing(8)
        self.export_btns = {}
        for i, (fmt, ic) in enumerate((("svg", "pen-tool"), ("png", "image-plus"), ("gif", "film"),
                                       ("mp4", "film"))):
            b = button(fmt.upper(), ic)
            b.clicked.connect(lambda _=False, f=fmt: self.export(f))
            grid.addWidget(b, i // 2, i % 2)
            self.export_btns[fmt] = b
        b = button("WebP", "film")
        b.clicked.connect(lambda _=False: self.export("webp"))
        grid.addWidget(b, 2, 0)
        self.export_btns["webp"] = b
        # an SVG that draws itself in the browser, stroke by stroke
        b = button("", "pencil-line")
        b.clicked.connect(lambda _=False: self.export("svganim"))
        grid.addWidget(b, 2, 1)
        self.export_btns["svganim"] = b
        # extra: plain single-layer SVG (one path with all strokes) for plotters / cutting machines
        b = button("", "pen-tool", "ghost")
        b.clicked.connect(lambda _=False: self.export("svg1"))
        grid.addWidget(b, 3, 0)
        self.export_btns["svg1"] = b
        b = button("PDF", "file-down", "ghost")  # vector PDF for printing
        b.clicked.connect(lambda _=False: self.export("pdf"))
        grid.addWidget(b, 3, 1)
        self.export_btns["pdf"] = b
        b = button("", "copy", "ghost")  # the sketch on the clipboard (PNG + SVG)
        b.clicked.connect(lambda _=False: self.copy_sketch())
        grid.addWidget(b, 5, 0, 1, 2)
        self.export_btns["copy"] = b
        # SceneSketch: every sketch of the matrix at once
        b = button("", "layers", "ghost")
        b.clicked.connect(lambda _=False: self.export("matrix"))
        grid.addWidget(b, 4, 0, 1, 2)
        self.export_btns["matrix"] = b
        self.result_card.body.addLayout(grid)
        self.folder_btn = button("", "folder-open", "ghost")
        self.folder_btn.clicked.connect(self.open_folder)
        self.reuse_btn = button("", "refresh-cw", "ghost")
        self.reuse_btn.clicked.connect(self.use_as_initial_svg)
        self.series_btn = button("", "layers", "ghost")
        self.series_btn.clicked.connect(self.abstraction_series)
        for b in (self.folder_btn, self.reuse_btn, self.series_btn):
            b.setStyleSheet("text-align: left;")
            self.result_card.body.addWidget(b)
        ll.addWidget(self.result_card, 2)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setWidget(left)
        left_scroll.setMinimumWidth(260)
        left_scroll.setMaximumWidth(370)
        self.left_pane, self.left_scroll = left, left_scroll
        splitter.addWidget(left_scroll)

        # ----------------------------------------------------------- center pane
        center = Card(margins=18, spacing=12)
        center.setMinimumWidth(420)
        self.modes = SegmentedControl([(m, "") for m in SketchCanvas.MODES])
        self.modes.set_icons({"sketch": "pen-tool", "compare": "flip-horizontal-2", "attention": "eye",
                              "mask": "scan", "condition": "mountain", "matrix": "layers"})
        self.modes.changed.connect(self._mode_changed)
        tools = QWidget()  # the edit tools and the brush style; below the view tabs when they do not fit
        tools_row = QHBoxLayout(tools)
        tools_row.setContentsMargins(0, 0, 0, 0)
        tools_row.setSpacing(2)
        # eraser: touch up the finished sketch (edited.svg, the original stays)
        self.edit_tools = QWidget()
        et = QHBoxLayout(self.edit_tools)
        et.setContentsMargins(8, 0, 0, 0)
        et.setSpacing(2)
        self.eraser_btn = tool_button("eraser", "", 18, checkable=True)
        self.eraser_btn.toggled.connect(self._toggle_eraser)
        self.pen_btn = tool_button("pencil-line", "", 18, checkable=True)  # draw own strokes
        self.pen_btn.toggled.connect(self._toggle_pen)
        self.undo_btn = tool_button("undo-2", "", 18)
        self.undo_btn.clicked.connect(self.undo_edit)
        self.redo_btn = tool_button("redo-2", "", 18)
        self.redo_btn.clicked.connect(self.redo_edit)
        self.revert_btn = tool_button("rotate-ccw", "", 18)
        self.revert_btn.clicked.connect(self.revert_edits)
        self.continue_btn = tool_button("wand-sparkles", "", 18)  # a new CLIPasso job from this sketch
        self.continue_btn.clicked.connect(self.continue_with_clipasso)
        for b in (self.eraser_btn, self.pen_btn, self.undo_btn, self.redo_btn, self.revert_btn, self.continue_btn):
            et.addWidget(b)
        tools_row.addWidget(self.edit_tools)
        # brush style the sketches are shown in – also while they are computed; the export starts with it
        self.style_btn = tool_button("palette", "", 18)
        self.style_btn.setPopupMode(QToolButton.InstantPopup)
        self.style_menu = QMenu(self)
        self.style_group = QActionGroup(self)
        self.style_actions = {}
        for key in brush.STYLES:
            action = self.style_menu.addAction("")
            action.setCheckable(True)
            action.triggered.connect(lambda _=False, k=key: self.set_canvas_style(k))
            self.style_group.addAction(action)
            self.style_actions[key] = action
        self.style_btn.setMenu(self.style_menu)
        tools_row.addWidget(self.style_btn)
        self._edit_undo: dict[int, list[str]] = {}
        self._edit_redo: dict[int, list[str]] = {}
        self._edit_changed = False
        self.stage_badge = label("", "badge")
        self.stage_badge.setVisible(False)
        self.canvas_header = WrapRow(self.modes, tools, self.stage_badge)
        center.body.addWidget(self.canvas_header)
        self.resume_banner = Banner()  # an interrupted / cancelled job is shown: "Continue"
        self.resume_banner.action.connect(self.continue_viewed_job)
        center.body.addWidget(self.resume_banner)
        self.running_banner = Banner()  # another result is shown while a job runs: back to it
        self.running_banner.action.connect(self.show_running_job)
        center.body.addWidget(self.running_banner)
        self.banner = Banner()
        self.banner.action.connect(self._download_missing)
        center.body.addWidget(self.banner)
        self.canvas = SketchCanvas()
        self.canvas.erase_begin.connect(self._erase_begin)
        self.canvas.erase.connect(self._erase_stroke)
        self.canvas.erase_end.connect(self._erase_end)
        self.canvas.pen_stroke.connect(self._pen_stroke)
        center.body.addWidget(self.canvas, 1)
        self.matrix = MatrixView()  # SceneSketch: all cells of the abstraction matrix
        self.matrix.clicked.connect(self.select_seed)
        self.matrix.activated.connect(self._open_cell)
        self.matrix.setVisible(False)
        center.body.addWidget(self.matrix, 1)

        self.status = label("", "h3")
        status_row = QHBoxLayout()
        status_row.addWidget(self.status, 1)
        status_row.addWidget(self.estimate_holder())
        center.body.addLayout(status_row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        center.body.addWidget(self.progress)
        stats = QHBoxLayout()
        stats.setSpacing(28)
        self.stat_iter, self.stat_loss, self.stat_best, self.stat_time, self.stat_eta = (StatTile() for _ in range(5))
        for t in (self.stat_iter, self.stat_loss, self.stat_best, self.stat_time, self.stat_eta):
            stats.addWidget(t)
        stats.addStretch(1)
        center.body.addLayout(stats)
        self.chart = LossChart()
        self.chart.setFixedHeight(74)
        center.body.addWidget(self.chart)

        self.thumb_area = QScrollArea()
        self.thumb_area.setFixedHeight(116)
        self.thumb_area.setWidgetResizable(True)
        self.thumb_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        thumbs_host = QWidget()
        self.thumb_row = QHBoxLayout(thumbs_host)
        self.thumb_row.setContentsMargins(0, 4, 0, 4)
        self.thumb_row.setSpacing(8)
        self.thumb_row.addStretch(1)
        self.thumb_area.setWidget(thumbs_host)
        self.thumb_area.setVisible(False)
        center.body.addWidget(self.thumb_area)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.start_btn = button("", "play", "primary", "lg")
        self.start_btn.clicked.connect(self.start)
        self.pause_btn = button("", "pause", None, "lg")
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.cancel_btn = button("", "square", "danger", "lg")
        self.cancel_btn.clicked.connect(self.cancel)
        self.queue_btn = button("", "list-plus", "ghost", "lg")
        self.queue_btn.clicked.connect(self.add_to_queue)
        self.queue_btn.setToolTip("")
        actions.addWidget(self.start_btn)
        actions.addWidget(self.pause_btn)
        actions.addWidget(self.cancel_btn)
        actions.addStretch(1)
        actions.addWidget(self.queue_btn)
        center.body.addLayout(actions)
        splitter.addWidget(center)

        # ------------------------------------------------------------ right pane
        right = Card(margins=16)
        right.setMinimumWidth(330)
        right.setMaximumWidth(460)
        self.params = ParamPanel()
        self.params.settings_changed.connect(self._settings_changed)
        self.params.method_changed.connect(self._method_changed)
        self.picker.changed.connect(self.params.set_method)
        self.params.import_btn.clicked.connect(self.import_preset)
        self.params.export_btn.clicked.connect(self.export_preset)
        self.params.cli_btn.clicked.connect(self.copy_cli)
        right.body.addWidget(self.params)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([290, 800, 380])

        # ---------------------------------------------------------------- wiring
        controller.job_started.connect(self._job_started)
        controller.job_event.connect(self._job_event)
        controller.job_finished.connect(self._job_finished)
        controller.queue_changed.connect(self._update_buttons)
        i18n.language_changed.connect(lambda _: self.retranslate())

        s = app_settings()
        per_method = s.get("last_params_by_method")
        last = s.get("last_params")
        if not isinstance(per_method, dict):
            per_method = {"clipasso": last} if isinstance(last, dict) else {}
        self.params.restore(per_method, s.get("last_method") or schema.method_of(last))
        self._method_changed(self.params.method())
        self._sync_quick()
        self._build_samples_menu()
        last_img = s.get("last_image")
        if last_img and os.path.isfile(last_img):
            self.set_image(last_img)
        else:
            self.set_image(str(paths.resource("samples", "camel.png")))
        self._apply_canvas_style(app_settings().get("canvas_style", "plain"))
        self.retranslate()
        self._update_buttons()

    # ================================================================== input
    def _build_samples_menu(self):
        self.samples_menu.clear()
        for f in sorted(paths.resource("samples").iterdir()):
            if f.suffix.lower() in (".png", ".jpg", ".jpeg"):
                act = self.samples_menu.addAction(QPixmap(str(f)).scaled(40, 40, Qt.KeepAspectRatio,
                                                                         Qt.SmoothTransformation), f.stem)
                act.triggered.connect(lambda _=False, p=str(f): self.set_image(p))

    RECENT_MAX = 12

    def _remember_recent(self, path: str):
        """The image heads the "recent" menu (not the bundled samples)."""
        if os.path.normcase(os.path.abspath(path)).startswith(os.path.normcase(str(paths.resource("samples")))):
            return
        st = app_settings()
        key = os.path.normcase(os.path.abspath(path))
        recent = [p for p in st.get("recent_images") or [] if os.path.normcase(os.path.abspath(p)) != key]
        st.set("recent_images", [path] + recent[: self.RECENT_MAX - 1])

    def _build_recent_menu(self):
        from .. import thumbs

        self.recent_menu.clear()
        st = app_settings()
        saved = list(st.get("recent_images") or [])
        recent = [p for p in saved if os.path.isfile(p)]
        if recent != saved:  # moved or deleted meanwhile
            st.set("recent_images", recent)
        for p in recent:
            act = self.recent_menu.addAction(thumbs.thumbnail(p, 40), os.path.basename(p))
            act.setToolTip(p)
            act.triggered.connect(lambda _=False, path=p: self.set_image(path))
        if not recent:
            self.recent_menu.addAction(tr("ui.recent_empty")).setEnabled(False)

    def take_webcam_photo(self):
        dlg = dialogs.WebcamDialog(os.path.join(app_settings().get("output_dir"), "_webcam"), self)
        if dlg.exec() == QDialog.Accepted and dlg.path:
            self.set_image(dlg.path)

    def browse_image(self):
        start = os.path.dirname(self.image_path) if self.image_path else os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(self, tr("ui.choose_image"), start, IMAGE_FILTER)
        if path:
            self.set_image(path)

    def edit_image(self):
        """Crop / rotate / flip the input; the result is saved as a new file and used as the input."""
        if not self.image_path or not os.path.isfile(self.image_path):
            return
        from ..image_edit import ImageEditDialog

        dlg = ImageEditDialog(self.image_path, self)
        if dlg.exec() and dlg.result_path:
            self.set_image(dlg.result_path)

    def images_dropped(self, paths: list[str]):
        """Several images (or a folder) dropped: the first is opened; all of them can go to the queue."""
        if not paths:
            return
        self.set_image(paths[0])
        if len(paths) == 1:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle(tr("ui.drop_many.title"))
        box.setText(tr("ui.drop_many.text", n=len(paths)))
        add = box.addButton(tr("ui.drop_many.queue", n=len(paths)), QMessageBox.AcceptRole)
        box.addButton(tr("ui.drop_many.first"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is add:
            self.queue_paths(paths)

    def queue_paths(self, paths: list[str]) -> int:
        self.controller.enqueue_many(list(paths), self.params.settings(), start=not self.controller.is_busy())
        self.toast.emit(tr("ui.queue.added", n=len(paths)), "success")
        return len(paths)

    def paste_image(self) -> bool:
        """Ctrl+V: an image, an image file or the path of an image from the clipboard. A pasted image is
        saved to <output folder>/_pasted first, so it stays available like any other input."""
        data = QGuiApplication.clipboard().mimeData()
        if data is not None:
            for url in data.urls() if data.hasUrls() else []:
                path = os.path.normpath(url.toLocalFile())
                if path.lower().endswith(IMAGE_EXT) and os.path.isfile(path):
                    self.set_image(path)
                    return True
            if data.hasImage():
                img = QImage(data.imageData())
                if not img.isNull():
                    folder = os.path.join(app_settings().get("output_dir"), "_pasted")
                    os.makedirs(folder, exist_ok=True)
                    path = os.path.join(folder, time.strftime("pasted-%Y%m%d-%H%M%S.png"))
                    if img.save(path):
                        self.set_image(path)
                        return True
            text = data.text().strip().strip('"') if data.hasText() else ""
            if text.lower().endswith(IMAGE_EXT) and os.path.isfile(text):
                self.set_image(text)
                return True
        self.toast.emit(tr("ui.paste_no_image"), "info")
        return False

    def set_image(self, path: str):
        if not path or not os.path.isfile(path):
            return
        self.image_path = path
        self._remember_recent(path)
        self.drop.set_image(path)
        full = image_io.image_size(path)  # from the file header: the photo is decoded once, small
        pm = load_pixmap(path, DISPLAY_MAX)
        self.file_label.setText(f"{os.path.basename(path)}  ·  {full.width()}×{full.height()} px")
        self.file_label.setToolTip(path)
        app_settings().set("last_image", path)
        if not self.controller.is_busy():
            self._reset_view()
            self.canvas.set_input(self._square_input(pm))
        if full.width() != full.height() and not self.params.settings()["fix_scale"]:
            self.toast.emit(tr("ui.hint_fix_scale"), "info")
        self._mask = None
        self._update_mask_preview()
        self._update_buttons()

    # ------------------------------------------------------------------ object mask
    def _mask_settings(self) -> tuple[bool, str, dict]:
        s = self.params.settings()
        return schema.uses_mask(self.params.method(), s), s.get("mask_model", "u2net"), s

    def _update_mask_preview(self):
        """Show the mask of the input (computed in the background) whenever the run will use one."""
        used, model, s = self._mask_settings()
        if not used or not self.image_path or not os.path.isfile(self.image_path):
            self.mask_preview.forget()
            self.mask_row.hide()
            self.drop.set_overlay(None)
            self._mask = None
            return
        self.mask_row.show()
        if self._mask is not None and self._mask["key"] == (self.image_path, model):
            return
        self._mask = None
        self.drop.set_overlay(None)
        if model != "u2net" and not model_store.is_available(model):
            self.mask_preview.forget()
            self._set_mask_status("missing", model)
            return
        self._set_mask_status("busy")
        self.mask_preview.request(self.image_path, model, s.get("device", "auto"))

    def _mask_ready(self, path: str, model: str):
        used, current, _ = self._mask_settings()
        if not used or path != self.image_path or model != current:
            return  # an earlier image or model
        try:
            _, prob, edited = mask_view.load_mask(path, model)
        except OSError as exc:
            self._mask_failed(path, model, str(exc))
            return
        if prob is None:
            self._mask_failed(path, model, tr("ui.mask.not_cached"))
            return
        self._mask = {"key": (path, model), "prob": prob, "edited": edited is not None}
        mask = edited if edited is not None else prob >= masking.OBJECT_THRESHOLD
        pal = theme.current()
        veil = QColor(pal.surface2)
        veil.setAlpha(215)
        self.drop.set_overlay(mask_view.overlay(mask, veil, QColor(pal.accent), max_side=700))
        self._set_mask_status("edited" if edited is not None else "ready", model)

    def _mask_failed(self, path: str, model: str, message: str):
        if path == self.image_path:
            self._set_mask_status("failed", model)
            self.mask_status.setToolTip(message)

    def _set_mask_status(self, state: str, model: str = ""):
        name = dialogs.model_display_name(model) if model else ""
        texts = {"busy": tr("ui.mask.busy"), "ready": tr("ui.mask.ready", model=name),
                 "edited": tr("ui.mask.edited"), "missing": tr("ui.mask.missing", model=name),
                 "failed": tr("ui.mask.failed")}
        self.mask_state = state
        self.mask_status.setText(texts[state])
        self.mask_status.setToolTip("")
        self.mask_dl_btn.setVisible(state == "missing")
        self.mask_eye.setEnabled(state in ("ready", "edited"))
        self.mask_edit_btn.setEnabled(state in ("ready", "edited"))
        self.mask_reset_btn.setVisible(state == "edited")

    def _toggle_mask_overlay(self, on: bool):
        app_settings().set("show_mask", on)
        self.drop.set_show_overlay(on)

    def _download_mask_model(self):
        _, model, _ = self._mask_settings()
        if dialogs.ModelDownloadDialog([model], self).exec():
            self._mask = None
            self._update_mask_preview()
            self.picker.refresh_status(self.params.all_settings())
            self._update_banner()

    def edit_mask(self):
        if self._mask is None or not self.image_path:
            return
        from ..mask_edit import MaskEditDialog

        path, model = self._mask["key"]
        _, prob, edited = mask_view.load_mask(path, model)
        if prob is None:
            return
        dlg = MaskEditDialog(path, prob, edited, self)
        if dlg.exec() and dlg.saved:
            self._mask = None
            self._update_mask_preview()

    def reset_mask(self):
        """Use the automatic mask again (the edit is removed)."""
        if not self.image_path:
            return
        masking.remove_edited_mask(imaging.load_rgb(self.image_path))
        self._mask = None
        self._update_mask_preview()

    def shutdown(self):
        self.mask_preview.shutdown()

    @staticmethod
    def _square_input(pm: QPixmap) -> QPixmap:
        side = min(pm.width(), pm.height())
        if side <= 0:
            return pm
        return pm.copy((pm.width() - side) // 2, (pm.height() - side) // 2, side, side)

    def _quick_toggled(self, key, value):
        s = self.params.settings()
        if key in s and s[key] != value:
            self.params.fields[key].set_value(value, emit=True)

    def _sync_quick(self):
        s = self.params.settings()
        for key, (lbl, sw) in self.quick.items():
            present = key in s
            lbl.setVisible(present)
            sw.setVisible(present)
            lbl.setToolTip(tr(param_text_key(self.params.method(), key, "help")))
            if present and sw.isChecked() != bool(s[key]):
                sw.blockSignals(True)
                sw.setChecked(bool(s[key]))
                sw.blockSignals(False)

    def _settings_changed(self, settings: dict):
        self._sync_quick()
        st = app_settings()
        st.data["last_params_by_method"] = self.params.all_settings()
        st.data["last_method"] = self.params.method()
        st.set("last_params", settings)
        self._update_estimate()
        self._update_banner()
        self.picker.cards[self.params.method()].refresh_status(settings)
        self._update_mask_preview()

    def _method_changed(self, method: str):
        self.picker.set_current(method)
        self.picker.refresh_status(self.params.all_settings())
        self._sync_quick()
        self.reuse_btn.setVisible(method == "clipasso")
        self.series_btn.setVisible(method in ("clipasso", "controlsketch"))
        if not self.controller.is_busy() and not self.view_dir:
            self._set_view_method(method)
        self._update_banner()
        self._update_estimate()
        self._update_mask_preview()

    def _set_view_method(self, method: str):
        """Adapt statistics, chart and canvas views to the method of the displayed run."""
        self.view_method = method
        loss = methods_ui.uses_loss(method)
        self.stat_loss.caption.setText(tr("ui.stat.loss") if loss else tr("ui.stat.score"))
        self.stat_best.caption.setText(tr("ui.stat.best") if loss else tr("ui.stat.best_score"))
        self.stat_iter.caption.setText(tr("ui.stat.step") if method == "swiftsketch" else tr("ui.stat.iteration"))
        self.chart.setVisible(method != "swiftsketch")
        self.chart.empty_text_key = "ui.loss_chart_empty" if loss else "ui.score_chart_empty"
        self.chart.update()
        scene = method == "scenesketch"
        self.modes.set_visible("attention", method != "swiftsketch")
        self.modes.set_visible("condition", method in ("controlsketch", "scenesketch"))
        self.modes.set_text("condition", tr("ui.mode.background") if scene else tr("ui.mode.condition"))
        self.modes.set_visible("matrix", scene)
        current = self.modes.current()
        allowed = {"sketch", "compare", "mask"} | ({"attention"} if method != "swiftsketch" else set()) | (
            {"condition"} if method in ("controlsketch", "scenesketch") else set()) | ({"matrix"} if scene else set())
        if current not in allowed:
            self.modes.set_current("sketch")
            self._mode_changed("sketch")

    def _update_banner(self):
        missing = self.params.missing_models()
        method = self.params.method()
        if missing:
            mb = methods_ui.download_mb(missing)
            size = f"{mb / 1000:.1f} GB" if mb >= 1000 else f"{mb:.0f} MB"
            names = ", ".join(dialogs.model_display_name(k) for k in missing)
            self.banner.show_message(tr("ui.banner.models_missing", method=methods_ui.name(method), names=names,
                                        size=size), button_text=tr("ui.download"), icon_name="download")
        elif method == "controlsketch" and not methods_ui.has_cuda():
            self.banner.show_message(tr("ui.banner.gpu_needed"), warn=True)
        else:
            self.banner.hide()

    def _download_missing(self):
        missing = self.params.missing_models()
        if missing and dialogs.ask_download_missing(self, missing):
            self.toast.emit(tr("ui.models_ready", method=methods_ui.name(self.params.method())), "success")
        self.params._after_change()
        self._update_banner()
        self.picker.refresh_status(self.params.all_settings())

    # ================================================================== run
    def _check_models(self) -> bool:
        missing = self.params.missing_models()
        if not missing:
            return True
        return dialogs.ask_download_missing(self, missing) and not self.params.missing_models()

    def start(self):
        if not self.image_path:
            self.browse_image()
            if not self.image_path:
                return
        if not self._check_models():
            return
        self.params._after_change()
        self.controller.enqueue(self.image_path, self.params.settings(), start=True)
        if self.controller.current and self.controller.current.target != self.image_path:
            self.toast.emit(tr("ui.added_to_queue"), "info")

    def add_to_queue(self):
        if not self.image_path or not self._check_models():
            return
        self.controller.enqueue(self.image_path, self.params.settings(), start=not self.controller.is_busy())
        self.toast.emit(tr("ui.added_to_queue"), "success")

    def toggle_pause(self):
        job = self.controller.current
        if not job:
            return
        if job.status == "paused":
            self.controller.resume()
        else:
            self.controller.pause()
        self._update_buttons()

    def cancel(self):
        if not self.controller.is_busy():
            return
        res = QMessageBox.question(self, tr("ui.cancel_run"), tr("ui.cancel_run_question"))
        if res == QMessageBox.Yes:
            self.controller.cancel()
            self._set_status("ui.status.cancelling")

    # ================================================================ events
    def _reset_view(self):
        self.resume_banner.hide()
        self._edit_undo.clear()
        self._edit_redo.clear()
        self.canvas.clear()
        self.matrix.clear()
        self.chart.reset(1)
        for t in self.thumbs.values():
            t.setParent(None)
        self.thumbs.clear()
        self.seed_svgs.clear()
        self.seed_attn.clear()
        self.seed_runs.clear()
        self.seed_scores.clear()
        self.best_seed = None
        self.selected_seed = None
        self.view_dir = ""
        self.thumb_area.setVisible(False)
        self.progress.setValue(0)
        for t in (self.stat_iter, self.stat_loss, self.stat_best, self.stat_time, self.stat_eta):
            t.value.setText("–")
        self.stage_badge.setVisible(False)
        self._set_status("ui.status.idle")
        self._update_buttons()

    def _update_resume_banner(self, summary: dict | None = None):
        job_dir = self.view_dir
        if summary is None and job_dir:
            summary = jobs.job_summary(job_dir)
        busy = any(j.status in ("queued", "running", "paused") and job_dir and os.path.normcase(
            os.path.abspath(j.resume_dir or j.job_dir or "-")) == os.path.normcase(os.path.abspath(job_dir))
            for j in self.controller.jobs)
        if not job_dir or summary is None or busy or not jobs.summary_can_continue(summary):
            self.resume_banner.hide()
            return
        done, total = summary["progress"]
        self.resume_banner.show_message(tr(f"ui.resume.{summary['state']}", done=done, total=total),
                                        warn=True, button_text=tr("ui.continue"), icon_name="clock")
        self.resume_banner.button.setIcon(icons.icon("play", theme.current().on_accent))

    def continue_viewed_job(self):
        if self.view_dir and self.controller.continue_job(self.view_dir) is not None:
            self.resume_banner.hide()
            self.toast.emit(tr("ui.resume.queued"), "info")

    def relocate(self, old: str, new: str):
        """The output folder moved with its results: show the same job and image from their new place."""
        from ..storage import relocated

        if self.view_dir:
            moved = relocated(self.view_dir, old, new)
            if moved != self.view_dir and os.path.isdir(moved):
                self.show_job_dir(moved)
        if self.image_path:
            self.image_path = relocated(self.image_path, old, new)

    def forget_job_dir(self, job_dir: str):
        """A job folder was deleted in the gallery: stop showing its results and its saved input."""
        root = os.path.normcase(os.path.abspath(job_dir))

        def inside(path: str) -> bool:
            return bool(path) and os.path.normcase(os.path.abspath(path)).startswith(root + os.sep)

        if self.view_dir and os.path.normcase(os.path.abspath(self.view_dir)) == root:
            self._reset_view()
        if inside(self.image_path):
            self.image_path = ""
            self.drop.set_image(None)
            self.file_label.setText("")
            self.file_label.setToolTip("")
            self.canvas.set_input(None)
            self._update_buttons()

    def _ensure_thumbs(self, seeds: list[int]):
        for seed in seeds:
            if seed in self.thumbs:
                continue
            t = SeedThumb(seed)
            t.set_style(self.canvas.style())
            t.clicked.connect(self.select_seed)
            if self.view_method == "scenesketch":
                t.set_caption(self._cell_label(seed))
                t.setToolTip(tr("ui.cell_tip", layer=seed // 100, level=seed % 100))
            self.thumb_row.insertWidget(self.thumb_row.count() - 1, t)
            self.thumbs[seed] = t
        self.thumb_area.setVisible(len(self.thumbs) > 1)
        if self.selected_seed is None and seeds:
            self.select_seed(seeds[0])

    def select_seed(self, seed: int):
        if seed != self.selected_seed and self.controller.is_busy():
            self.chart.reset(self.chart.total)  # the chart shows the selected sketch only
        self.selected_seed = seed
        self.matrix.set_selected(seed)
        for s, t in self.thumbs.items():
            t.set_selected(s == seed)
        self.canvas.set_svg(self.seed_svgs.get(seed))
        self.canvas.set_attention(self.seed_attn.get(seed))
        if not methods_ui.uses_loss(self.view_method) and seed in self.seed_scores:
            self.stat_loss.value.setText(f"{self.seed_scores[seed]:.1f}")
        self._update_buttons()

    def _job_started(self, job: QueuedJob):
        self.view_job = job
        self._reset_view()
        self.view_dir = job.job_dir
        if job.target != self.image_path:
            self.image_path = job.target
            self.drop.set_image(job.target)
        self.canvas.set_input(self._square_input(load_pixmap(job.target, DISPLAY_MAX)))
        self._set_view_method(schema.method_of(job.settings))
        self.chart.reset(methods_ui.iterations(job.settings))
        self._setup_matrix(job.settings)
        self._ensure_thumbs(job.seeds)
        self._set_status("ui.status.starting")
        self._update_buttons()

    @staticmethod
    def _record_live(job: QueuedJob, kind: str, data: dict):
        """Keep the latest previews of every job, so the studio can show it again (show_running_job)."""
        live = job.live
        seed = data.get("seed")
        if kind == "job_start":
            live["device"] = data.get("device", "")
        elif kind in ("input", "condition"):
            live[kind] = data
        elif kind == "attention":
            live.setdefault("attention", {})[seed] = data
        elif kind == "preview":
            live.setdefault("preview", {})[seed] = data
        elif kind == "seed_done":
            live.setdefault("seed_done", {})[seed] = data
            live.get("preview", {}).pop(seed, None)
        elif kind == "iteration":
            live.setdefault("iteration", {})[seed] = data

    def show_running_job(self):
        """Show the running job again (after a result of the gallery was opened during the run)."""
        job = self.controller.current
        if job is None or not self.controller.is_busy():
            return
        live = dict(job.live)
        self._job_started(job)
        if live.get("device"):
            self._job_event(job, "job_start", {"device": live["device"]})
        for kind in ("input", "condition"):
            if kind in live:
                self._job_event(job, kind, live[kind])
        for kind in ("attention", "preview", "seed_done"):
            for data in live.get(kind, {}).values():
                self._job_event(job, kind, data)
        last = live.get("iteration", {}).get(self.selected_seed)
        if last is not None:
            self._on_iteration(job, last)
        self._update_buttons()

    def _job_event(self, job: QueuedJob, kind: str, data: dict):
        self._record_live(job, kind, data)
        if job is not self.view_job:
            if kind in ("iteration", "seed_done") and self.running_banner.isVisible():
                self._update_running_banner()  # its progress
            return
        seed = data.get("seed")
        if kind == "job_start":
            self.device_badge.setText(self._device_text(data.get("device", "")))
        elif kind == "stage":
            n = job.seeds.index(seed) + 1 if seed in job.seeds else 1
            extra = {k: v for k, v in data.items() if k not in ("name", "seed", "n", "total")}  # e.g. step/steps
            self._set_status(f"ui.status.{data['name']}", n=n, total=len(job.seeds), **extra)
        elif kind == "input":
            self.canvas.set_input(_pixmap_from_png(data["png"]))
            self.canvas.set_mask(_pixmap_from_png(data["mask_png"]))
        elif kind == "attention":
            self.seed_attn[seed] = _pixmap_from_png(data["png"])
            if seed == self.selected_seed:
                self.canvas.set_attention(self.seed_attn[seed])
        elif kind == "condition":
            self.canvas.set_condition(_pixmap_from_png(data["png"]))
        elif kind == "iteration":
            follow = job.seed_progress.get(self.selected_seed, 0.0) >= 1.0 or self.selected_seed not in job.seeds
            if seed != self.selected_seed and follow and seed in self.thumbs:
                self.select_seed(seed)  # the previously shown sketch is finished: follow the running one
            if seed == self.selected_seed:
                self._on_iteration(job, data)
        elif kind == "preview":
            self.seed_svgs[seed] = data["svg"]
            if seed in self.thumbs:
                self.thumbs[seed].set_svg(data["svg"])
            if self.view_method == "scenesketch":
                self.matrix.set_cell(seed, data["svg"])
            if seed == self.selected_seed:
                self.canvas.set_svg(data["svg"])
        elif kind == "seed_done":
            self.seed_svgs[seed] = data["svg"]
            self.seed_runs[seed] = data["run_dir"]
            if data.get("clip_score") is not None:
                self.seed_scores[seed] = data["clip_score"]
            if seed in self.thumbs:
                self.thumbs[seed].set_svg(data["svg"])
                self.thumbs[seed].set_caption(self._seed_caption(data.get("best_loss"), data.get("clip_score"), seed,
                                                                 data.get("pruned", False)))
            if self.view_method == "scenesketch":
                self.matrix.set_cell(seed, data["svg"])
            if seed == self.selected_seed:
                self.canvas.set_svg(data["svg"])
            if not methods_ui.uses_loss(self.view_method) and self.seed_scores:
                self.stat_best.value.setText(f"{max(self.seed_scores.values()):.1f}")
                if seed == self.selected_seed and data.get("clip_score") is not None:
                    self.stat_loss.value.setText(f"{data['clip_score']:.1f}")
        elif kind == "job_done":
            best_run = data.get("best_run", "")
            for r in data.get("runs", []):
                self.seed_runs[r["seed"]] = r["run_dir"]
                if r["run_name"] == best_run:
                    self.best_seed = r["seed"]
            for s, t in self.thumbs.items():
                t.set_best(s == self.best_seed)
                if s == self.best_seed:
                    t.set_caption(f"★ {t.caption.text()}")
            self.matrix.set_best(self.best_seed)
            if self.best_seed is not None:
                self.select_seed(self.best_seed)
        elif kind == "warning":
            key = f"ui.warn.{data.get('code', '')}"
            self.toast.emit(tr(key) if i18n.has(key) else data.get("message", ""), "warning")
        elif kind == "log":
            key = f"ui.log.{data.get('code', '')}"
            params = {k: v for k, v in data.items() if k not in ("code", "message")}
            try:
                text = tr(key, **params) if i18n.has(key) else data.get("message", "")
            except (KeyError, IndexError, ValueError):
                text = data.get("message", "")
            self.toast.emit(text, "info")
        elif kind == "error":
            self._show_error(data)
        self._update_buttons()

    def _on_iteration(self, job, data):
        it, total = data["it"] + 1, data["total"]
        method = schema.method_of(job.settings)
        self.progress.setValue(int(job.progress * 1000))
        self.stat_iter.value.setText(f"{it}/{total}")
        if methods_ui.uses_loss(method):
            self.stat_loss.value.setText(f"{data['loss']:.4f}")
            best = data["best_loss"]
            self.stat_best.value.setText(f"{best:.4f}" if best < 99 else "–")
        elif data.get("score") is not None:
            self.stat_loss.value.setText(f"{data['score']:.1f}")
        self.stat_time.value.setText(imaging.eta_string(data["elapsed"]))
        remaining_seeds = sum(1 for s in job.seeds if job.seed_progress.get(s, 0) < 1.0) - 1
        eta = data["eta"]
        running = self.controller.runner.job
        parallel = running is not None and running.parallel
        if not data.get("eta_job") and not parallel and remaining_seeds > 0:
            eta += remaining_seeds * data["elapsed"] / max(it, 1) * total
        self.stat_eta.value.setText(imaging.eta_string(eta))
        self.chart.total = total
        if methods_ui.uses_loss(method):
            self.chart.add(it, data["loss"], data.get("loss_eval"))
        elif data.get("score") is not None:
            self.chart.add(it, None, data["score"])
        if it >= 5 and data["elapsed"] > 0:
            key = f"{method}:" + ("cuda" if job.device.startswith("cuda") else "cpu")
            if schema.turbo(job.settings):
                key += ":turbo"
            rates = dict(app_settings().get("sec_per_it", {}) or {})
            rates[key] = data["elapsed"] / it
            if it % 50 == 0:
                app_settings().set("sec_per_it", rates)
            else:
                app_settings().data["sec_per_it"] = rates
        if job.status == "paused":
            self._set_status("ui.status.paused")
        else:
            n = job.seeds.index(data["seed"]) + 1 if data["seed"] in job.seeds else 1
            part = data.get("part")
            self._set_status(f"ui.status.scene_{part}" if part else "ui.status.optimizing", n=n, total=len(job.seeds))

    def _job_finished(self, job: QueuedJob):
        if job is not self.view_job:
            self._update_running_banner()
            return
        self.progress.setValue(1000 if job.status == "done" else self.progress.value())
        if job.status == "done":
            self._set_status("ui.status.done", secs=imaging.eta_string(job.finished - job.started))
            self.toast.emit(tr("ui.toast_done", name=job.name), "success")
        elif job.status == "cancelled":
            self._set_status("ui.status.cancelled")
        else:
            self._set_status("ui.status.failed")
        self._update_buttons()

    def _show_error(self, data: dict):
        model = data.get("model")
        if model:
            if dialogs.ask_download_missing(self, [model]):
                self.toast.emit(tr("ui.model_installed_retry"), "success")
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle(tr("ui.error"))
        box.setText(tr("ui.run_failed"))
        box.setInformativeText(data.get("message", ""))
        if data.get("traceback"):
            box.setDetailedText(data["traceback"])
        box.exec()

    # ================================================================ results
    def show_job_dir(self, job_dir: str):
        """Display a job from the gallery (finished, or interrupted with the sketches done so far)."""
        current = self.controller.current
        if (self.controller.is_busy() and current.job_dir
                and os.path.normcase(os.path.abspath(current.job_dir)) == os.path.normcase(os.path.abspath(job_dir))):
            self.show_running_job()  # the running job itself: its live view
            return
        summary = jobs.job_summary(job_dir)
        if summary is None:
            return
        if self.controller.is_busy():
            self.view_job = None
        self._reset_view()
        self.view_dir = job_dir
        self._set_view_method(summary.get("method") or schema.method_of(summary.get("settings")))
        target = summary.get("target", "")
        src = jobs.reopen_input(job_dir, target)  # the original, or the copy saved with the job
        if src and os.path.isfile(src):
            self.image_path = src
            self.drop.set_image(src)
            jobs.restore_edited_mask(job_dir, src)
            self._mask = None
            self._update_mask_preview()
            pm = load_pixmap(src, DISPLAY_MAX)
            full = image_io.image_size(src)
            text = f"{os.path.basename(src)}  ·  {full.width()}×{full.height()} px"
            if os.path.normcase(os.path.abspath(src)) != os.path.normcase(os.path.abspath(target or "")):
                text += f"  ·  {tr('ui.saved_copy')}"
            self.file_label.setText(text)
            self.file_label.setToolTip(src)
            self.canvas.set_input(self._square_input(pm))
        runs = summary.get("runs", [])
        self._setup_matrix(summary.get("settings") or {})
        self._ensure_thumbs([r["seed"] for r in runs])
        for r in runs:
            seed = r["seed"]
            self.seed_runs[seed] = r["run_dir"]
            try:
                with open(jobs.sketch_file(r["run_dir"], r["best_svg"]), encoding="utf-8") as f:
                    self.seed_svgs[seed] = f.read()
            except OSError:
                continue
            self.thumbs[seed].set_svg(self.seed_svgs[seed])
            self.thumbs[seed].set_caption(self._seed_caption(r.get("best_loss"), r.get("clip_score"), seed,
                                                             r.get("pruned", False)))
            if self.view_method == "scenesketch":
                self.matrix.set_cell(seed, self.seed_svgs[seed])
            if r.get("clip_score") is not None:
                self.seed_scores[seed] = r["clip_score"]
            cond = next((os.path.join(r["run_dir"], f) for f in os.listdir(r["run_dir"])
                         if f.endswith("_condition.png")), None) if os.path.isdir(r["run_dir"]) else None
            if self.view_method == "scenesketch" and os.path.isfile(os.path.join(job_dir, "background.png")):
                cond = os.path.join(job_dir, "background.png")
            if cond:
                self.canvas.set_condition(QPixmap(cond))
            attn = os.path.join(r["run_dir"], "attention_map.png")
            if os.path.isfile(attn):
                self.seed_attn[seed] = QPixmap(attn)
            mask = os.path.join(r["run_dir"], "mask.png")
            if not os.path.isfile(mask):
                mask = os.path.join(job_dir, "mask.png")
            if os.path.isfile(mask):
                self.canvas.set_mask(QPixmap(mask))
            if r["run_name"] == summary.get("best_run"):
                self.best_seed = seed
        # the image as the method used it (masked, framed, padded): the photo/sketch slider lines up
        ordered = sorted(runs, key=lambda r: r.get("run_name") != summary.get("best_run"))
        processed = next((p for p in (os.path.join(r["run_dir"], "input.png") for r in ordered) if os.path.isfile(p)),
                         None)
        if processed:
            self.canvas.set_input(QPixmap(processed))
        for s, t in self.thumbs.items():
            t.set_best(s == self.best_seed)
            if s == self.best_seed:
                t.set_caption(f"★ {t.caption.text()}")
        self.matrix.set_best(self.best_seed)
        if self.best_seed is not None:
            self.select_seed(self.best_seed)
        if isinstance(summary.get("settings"), dict):
            self.params.set_settings(summary["settings"])
        done, total = summary.get("progress") or (1, 1)
        self.progress.setValue(int(1000 * done / max(total, 1)))
        self._fill_stats_from_summary(summary)
        self._update_resume_banner(summary)
        self._sync_quick()
        self._update_estimate()
        self._set_status("ui.status.loaded", name=os.path.basename(os.path.normpath(job_dir)))
        self._update_buttons()

    def _fill_stats_from_summary(self, summary: dict):
        runs = summary.get("runs", [])
        best = next((r for r in runs if r.get("run_name") == summary.get("best_run")), runs[0] if runs else None)
        if not best:
            return
        try:
            with open(os.path.join(best["run_dir"], "config.json"), encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, ValueError):
            cfg = {}
        method = schema.method_of(summary.get("settings"))
        if not methods_ui.uses_loss(method):
            total = methods_ui.iterations(summary.get("settings", {}))
            self.stat_iter.value.setText(f"{best.get('iterations_done', 0)}/{total}")
            if best.get("clip_score") is not None:
                self.stat_loss.value.setText(f"{best['clip_score']:.1f}")
                self.stat_best.value.setText(f"{best['clip_score']:.1f}")
            if cfg.get("seconds"):
                self.stat_time.value.setText(imaging.eta_string(cfg["seconds"]))
            self.chart.reset(max(int(total), 1))
            for it, score in cfg.get("clip_scores") or []:
                self.chart.add(it + 1, None, score)
            self.chart.update()
            return
        total = cfg.get("num_iter", best.get("iterations_done", 0))
        self.stat_iter.value.setText(f"{best.get('iterations_done', 0)}/{total}")
        self.stat_best.value.setText(f"{best.get('best_loss', 0):.4f}")
        if cfg.get("seconds"):
            self.stat_time.value.setText(imaging.eta_string(cfg["seconds"]))
        evals = cfg.get("loss_eval") or []
        interval = int(cfg.get("eval_interval", 10) or 10)
        self.chart.reset(max(int(total or 1), 1))
        for i, v in enumerate(evals):
            self.chart.add(i * interval, v, v)
        if evals:
            self.stat_loss.value.setText(f"{evals[-1]:.4f}")
        self.chart.update()

    def _selected_run(self) -> tuple[str, str] | None:
        seed = self.selected_seed if self.selected_seed is not None else self.best_seed
        run_dir = self.seed_runs.get(seed)
        if not run_dir:
            return None
        svg = jobs.sketch_file(run_dir)
        return (svg, run_dir) if os.path.isfile(svg) else None

    def _matrix_exportable(self) -> bool:
        return (self.view_method == "scenesketch" and len(self.seed_runs) > 1 and bool(self.view_dir)
                and os.path.isfile(os.path.join(self.view_dir, "job.json")))

    def export(self, fmt: str):
        sel = self._selected_run()
        if not sel:
            return
        svg, run_dir = sel
        name = os.path.basename(run_dir)
        if fmt == "matrix":
            if not self._matrix_exportable():
                return
            run_dir, name = self.view_dir, os.path.basename(os.path.normpath(self.view_dir))
        dlg = dialogs.ExportDialog(fmt, svg, run_dir, name, self)
        if dlg.exec():
            self.toast.emit(tr("ui.exported", path=getattr(dlg, "saved_path", "")), "success")

    def copy_sketch(self) -> bool:
        """Ctrl+C: the shown sketch as image + SVG on the clipboard, with the last export choices."""
        sel = self._selected_run()
        if not sel:
            return False
        dialogs.copy_sketch(sel[0])
        self.toast.emit(tr("ui.copied"), "success")
        return True

    def open_folder(self):
        folder = self.view_dir or app_settings().get("output_dir")
        if folder and os.path.isdir(folder):
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def use_as_initial_svg(self):
        sel = self._selected_run()
        if sel:
            self.params.fields["path_svg"].set_value(sel[0], emit=True)
            self.params.sections["strokes"].set_expanded(True)
            self.toast.emit(tr("ui.initial_svg_set"), "success")

    def abstraction_series(self):
        if not self.image_path or not self._check_models():
            return
        base = self.params.settings()
        method = self.params.method()
        if method == "swiftsketch":  # always 32 strokes
            return
        one_line = method == "clipasso" and base.get("one_line")
        for n in (16, 32, 64, 128) if one_line else (4, 8, 16, 32) if method == "clipasso" else (8, 16, 32, 64):
            s = dict(base)
            if one_line:  # one line with more and more turns
                s["one_line_segments"] = n
                s["path_svg"] = "none"
            elif method == "clipasso":
                s["num_paths"] = n
                s["path_svg"] = "none"
            else:
                s["num_strokes"] = n
            self.controller.enqueue(self.image_path, s, start=not self.controller.is_busy())
        self.toast.emit(tr("ui.series_added"), "success")
        self.open_queue.emit()

    # ================================================================ presets
    def import_preset(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("ui.import"), "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            data = data.get("settings", data) if isinstance(data, dict) else {}
            method = schema.method_of(data)
            keys = {p.key for p in schema.params_for(method)}
            self.params.set_settings({"method": method, **{k: v for k, v in data.items() if k in keys}})
            self.toast.emit(tr("ui.preset_loaded"), "success")
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, tr("ui.error"), str(exc))

    def export_preset(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("ui.export"), f"{self.params.method()}-preset.json",
                                              "JSON (*.json)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.params.settings(), f, indent=2)
            self.toast.emit(tr("ui.preset_saved"), "success")

    def copy_cli(self):
        target = self.image_path or "image.png"
        exe = f'"{sys.executable}"' if paths.is_frozen() else "python -m clipasso_studio"
        args = [exe, "--cli", "--target_file", f'"{target}"'] + schema.to_cli_args(
            self.params.settings())
        QGuiApplication.clipboard().setText(" ".join(args))
        self.toast.emit(tr("ui.cli_copied"), "success")

    # ================================================================ helpers
    @staticmethod
    def _device_text(device: str) -> str:
        return "GPU · CUDA" if device.startswith("cuda") else "CPU"

    def _set_status(self, key: str, **fmt):
        self._status_key = (key, fmt)
        self.status.setText(tr(key, **fmt))
        busy = key in ("ui.status.optimizing", "ui.status.loading", "ui.status.init", "ui.status.starting",
                       "ui.status.caption", "ui.status.condition", "ui.status.diffusion_models",
                       "ui.status.init_sdxl_cpu") or key.startswith("ui.status.scene_")
        self.stage_badge.setVisible(busy)
        if busy:
            self.stage_badge.setText(tr("ui.live"))

    def hardware_known(self):
        """The hardware probe answered (GPU or not): estimates and hints follow it."""
        self._update_estimate()
        self._update_banner()
        self.params.refresh_hints()
        self.picker.refresh_status(self.params.all_settings())

    def _update_estimate(self):
        s = self.params.settings()
        gpu = s["device"] == "cuda" or (s["device"] == "auto" and (self.device_badge.text().startswith("GPU")
                                                                  or methods_ui.has_cuda()))
        secs = methods_ui.estimate_seconds(s, gpu)
        self.estimate.setText(tr("ui.estimate", time=imaging.eta_string(secs)))

    def _seed_caption(self, best_loss, clip_score, seed: int | None = None, pruned: bool = False) -> str:
        if pruned:  # turbo mode: stopped after a quarter because another sketch was better
            return tr("ui.seed_pruned", value=self._seed_caption(best_loss, clip_score, seed))
        if self.view_method == "scenesketch" and seed is not None:
            score = f"  {clip_score:.0f}" if clip_score is not None else ""
            return self._cell_label(seed) + score
        if methods_ui.uses_loss(self.view_method) or clip_score is None:
            return f"{best_loss:.3f}" if best_loss is not None else ""
        return f"{clip_score:.1f}"

    @staticmethod
    def _cell_label(cell: int) -> str:
        return tr("ui.cell_caption", layer=cell // 100, level=cell % 100)

    def _setup_matrix(self, settings: dict):
        if schema.method_of(settings) == "scenesketch":
            self.matrix.set_layout(schema.scene_layers(settings), int(settings.get("simplicity_levels", 0)))
        else:
            self.matrix.clear()

    def _open_cell(self, cell: int):
        self.select_seed(cell)
        self.modes.set_current("sketch")
        self._mode_changed("sketch")

    def _update_buttons(self):
        busy = self.controller.is_busy()
        job = self.controller.current
        viewing_current = busy and job is self.view_job
        self.pause_btn.setEnabled(viewing_current)
        self.cancel_btn.setEnabled(viewing_current)
        self.start_btn.setEnabled(bool(self.image_path))
        paused = bool(job and job.status == "paused")
        p = theme.current()
        self.pause_btn.setText(tr("ui.resume") if paused else tr("ui.pause"))
        self.pause_btn.setIcon(icons.icon("play" if paused else "pause", p.text))
        self.start_btn.setText(tr("ui.start_queue") if busy else tr("ui.start"))
        self.start_btn.setIcon(icons.icon("list-plus" if busy else "play", p.on_accent))
        self.queue_btn.setVisible(not busy)
        has_result = self._selected_run() is not None
        for b in self.export_btns.values():
            b.setEnabled(has_result)
        self._update_edit_tools()
        self.export_btns["matrix"].setVisible(self.view_method == "scenesketch")
        self.export_btns["matrix"].setEnabled(self._matrix_exportable())
        for b in (self.reuse_btn,):
            b.setEnabled(has_result)
        self.folder_btn.setEnabled(bool(self.view_dir) or bool(app_settings().get("output_dir")))
        self._update_running_banner()
        self.result_hint.setText(tr("ui.result_hint_ready") if has_result else tr("ui.result_hint_empty"))

    def _update_running_banner(self):
        job = self.controller.current
        if self.controller.is_busy() and job is not self.view_job:
            self.running_banner.show_message(tr("ui.running_elsewhere", name=job.name, pct=f"{job.progress:.0%}"),
                                             button_text=tr("ui.show_running"), icon_name="play")
            self.running_banner.button.setIcon(icons.icon("eye", theme.current().on_accent))
        else:
            self.running_banner.hide()

    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        QTimer.singleShot(0, self._fit_left_column)  # sizes are known once the page is styled and shown

    def _fit_left_column(self):
        """The left column is at least as wide as its content plus a vertical scroll bar – otherwise
        the scroll bar (the column is taller than small windows) cuts off its right edge."""
        need = self.left_pane.minimumSizeHint().width() + self.left_scroll.verticalScrollBar().sizeHint().width() + 4
        self.left_scroll.setMinimumWidth(max(260, need))
        self.left_scroll.setMaximumWidth(max(370, need))

    def set_canvas_style(self, style: str):
        """Show the sketches in another brush style (remembered; the export dialog starts with it)."""
        st = app_settings()
        st.data["export_style"] = style
        st.set("canvas_style", style)
        self._apply_canvas_style(style)

    def _apply_canvas_style(self, style: str):
        if style not in brush.STYLES:
            style = "plain"
        self.canvas.set_style(style)
        self.matrix.set_style(style)
        for t in self.thumbs.values():
            t.set_style(style)
        self.style_actions[style].setChecked(True)
        self.style_btn.setToolTip(tr("ui.canvas_style.tip", style=tr(f"ui.brush.{style}")))

    def retranslate(self):
        for key, action in self.style_actions.items():
            action.setText(tr(f"ui.brush.{key}"))
        self.style_btn.setToolTip(tr("ui.canvas_style.tip", style=tr(f"ui.brush.{self.canvas.style()}")))
        self.eraser_btn.setToolTip(tr("ui.eraser.tip"))
        self.pen_btn.setToolTip(tr("ui.pen.tip"))
        self.continue_btn.setToolTip(tr("ui.continue.tip"))
        self.undo_btn.setToolTip(tr("ui.eraser.undo"))
        self.redo_btn.setToolTip(tr("ui.eraser.redo"))
        self.revert_btn.setToolTip(tr("ui.eraser.revert"))
        self.title.setText(tr("ui.studio.title"))
        self.subtitle.setText(tr("ui.studio.subtitle"))
        if not self.device_badge.text():
            self.device_badge.setText(tr("ui.device_unknown"))
        self.input_title.setText(tr("ui.input"))
        self.mask_eye.setToolTip(tr("ui.mask.show"))
        self.mask_dl_btn.setText(tr("ui.mask.download"))
        self.mask_edit_btn.setToolTip(tr("ui.mask.edit"))
        self.mask_reset_btn.setToolTip(tr("ui.mask.reset"))
        if self.mask_row.isVisible() and getattr(self, "mask_state", ""):
            _, model, _ = self._mask_settings()
            self._set_mask_status(self.mask_state, model)
        self.drop.title = tr("ui.drop_title")
        self.drop.subtitle = tr("ui.drop_subtitle")
        self.drop.update()
        self.open_btn.setText(tr("ui.open"))
        self.samples_btn.setText(tr("ui.samples"))
        self.edit_btn.setToolTip(tr("ui.edit_image.tip"))  # icon only: the row must fit the narrow column
        self.recent_btn.setToolTip(tr("ui.recent"))
        self.webcam_btn.setToolTip(tr("ui.webcam.tip"))
        for key, (lbl, _) in self.quick.items():
            lbl.setText(tr(param_text_key(self.params.method(), key, "label")))
            lbl.setToolTip(tr(param_text_key(self.params.method(), key, "help")))
        self.result_title.setText(tr("ui.result"))
        self.export_btns["svg1"].setText(tr("ui.export_svg1"))
        self.export_btns["svg1"].setToolTip(tr("ui.export_svg1_tip"))
        self.export_btns["webp"].setToolTip(tr("ui.export_webp_tip"))
        self.export_btns["svganim"].setText(tr("ui.export_svganim"))
        self.export_btns["pdf"].setToolTip(tr("ui.export_pdf_tip"))
        self.export_btns["copy"].setText(shortcuts.with_key(tr("ui.copy"), "Ctrl+C"))
        self.export_btns["copy"].setToolTip(tr("ui.copy_tip"))
        self.export_btns["svganim"].setToolTip(tr("ui.export_svganim_tip"))
        self.export_btns["matrix"].setText(tr("ui.export_matrix"))
        self.export_btns["matrix"].setToolTip(tr("ui.export_matrix_tip"))
        self.folder_btn.setText(tr("ui.open_folder"))
        self.reuse_btn.setText(tr("ui.use_as_initial"))
        self.reuse_btn.setToolTip(tr("ui.use_as_initial_tip"))
        self.series_btn.setText(tr("ui.abstraction_series"))
        self.series_btn.setToolTip(tr("ui.abstraction_series_tip"))
        for m in SketchCanvas.MODES:
            self.modes.set_text(m, tr(f"ui.mode.{m}"))
        self.canvas.placeholder = tr("ui.canvas_placeholder")
        self.canvas.update()
        self.picker.retranslate()
        self.picker.refresh_status(self.params.all_settings())
        self._set_view_method(self.view_method)
        self._fit_left_column()
        self.stat_time.caption.setText(tr("ui.stat.elapsed"))
        self.stat_eta.caption.setText(tr("ui.stat.eta"))
        self.cancel_btn.setText(tr("ui.cancel"))
        self.queue_btn.setText(tr("ui.add_to_queue"))
        key, fmt = self._status_key
        self.status.setText(tr(key, **fmt))
        self._update_estimate()
        self._update_banner()
        self._update_buttons()

    def estimate_holder(self) -> QWidget:
        self.estimate = label("", "faint")
        self.estimate.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return self.estimate

    def _mode_changed(self, mode: str):
        self.canvas.set_mode(mode)
        self.canvas.setVisible(mode != "matrix")
        self.matrix.setVisible(mode == "matrix")
        self._update_edit_tools()

    # ------------------------------------------------------------------ eraser
    def _editable_seed(self) -> int | None:
        """The shown sketch if it can be edited: finished, and not part of the running job."""
        seed = self.selected_seed if self.selected_seed is not None else self.best_seed
        if seed is None or seed not in self.seed_svgs or not self.seed_runs.get(seed):
            return None
        job = self.controller.current
        if job is not None and self.controller.is_busy() and job is self.view_job:
            return None
        if not os.path.isfile(os.path.join(self.seed_runs[seed], "best_iter.svg")):
            return None
        return seed

    def _update_edit_tools(self):
        seed = self._editable_seed()
        show = self.modes.current() == "sketch" and seed is not None
        self.edit_tools.setVisible(show)
        if not show and self.eraser_btn.isChecked():
            self.eraser_btn.setChecked(False)
        if not show and self.pen_btn.isChecked():
            self.pen_btn.setChecked(False)
        if seed is not None:
            from .. import strokes

            # a sketch of one line (one-line mode) has nothing to erase but the whole drawing
            try:
                single = strokes.count(self.seed_svgs[seed]) <= 1
            except Exception:
                single = False
            self.eraser_btn.setEnabled(not single)
            if single and self.eraser_btn.isChecked():
                self.eraser_btn.setChecked(False)
            self.undo_btn.setEnabled(bool(self._edit_undo.get(seed)))
            self.redo_btn.setEnabled(bool(self._edit_redo.get(seed)))
            self.revert_btn.setEnabled(os.path.isfile(os.path.join(self.seed_runs[seed], jobs.EDITED_FILE)))

    def _toggle_eraser(self, on: bool):
        if on and self.pen_btn.isChecked():
            self.pen_btn.setChecked(False)
        self.canvas.set_eraser(on)

    def _toggle_pen(self, on: bool):
        if on and self.eraser_btn.isChecked():
            self.eraser_btn.setChecked(False)
        self.canvas.set_pen(on)

    def _pen_stroke(self, points: list):
        """A stroke drawn by hand: added to the sketch (one undo step), marked to stay where it is when
        CLIPasso continues the sketch."""
        seed = self._editable_seed()
        if seed is None:
            return
        from .. import strokes

        svg = strokes.append_stroke(self.seed_svgs[seed], points)
        if svg == self.seed_svgs[seed]:
            return
        self._edit_undo.setdefault(seed, []).append(self.seed_svgs[seed])
        self._edit_redo[seed] = []
        self._show_edited(seed, svg)
        self._save_edit(seed)
        self._update_edit_tools()

    def continue_with_clipasso(self):
        """A new CLIPasso job that starts from the shown sketch: its strokes are optimised further (the ones
        drawn by hand stay where they are) and new strokes can be added."""
        seed = self._editable_seed()
        if seed is None:
            return
        from .. import strokes

        svg = self.seed_svgs[seed]
        if not os.path.isfile(os.path.join(self.seed_runs[seed], "input.png")):
            self.toast.emit(tr("ui.continue.no_input"), "error")
            return
        dlg = dialogs.ContinueDialog(strokes.shape_count(svg), strokes.fixed_count(svg), self)
        if dlg.exec() != QDialog.Accepted:
            return
        image, settings = self.continue_job(seed, *dlg.values())
        busy = self.controller.is_busy()
        self.controller.enqueue(image, settings, start=not busy)
        self.toast.emit(tr("ui.continue.queued" if busy else "ui.continue.started"), "success")

    def continue_job(self, seed: int, new: int, iterations: int, keep: bool) -> tuple[str, dict]:
        """(image, settings) of a CLIPasso job that continues the sketch ``seed``. Its image is the input as
        the sketch's method used it (masked, framed, padded), so the strokes line up without further steps."""
        from .. import strokes

        run_dir = self.seed_runs[seed]
        svg = self.seed_svgs[seed]
        state = jobs.read_state(os.path.dirname(os.path.normpath(run_dir))) or {}
        stem = os.path.splitext(os.path.basename(state.get("target") or ""))[0] or "sketch"
        base = os.path.join(app_settings().get("output_dir"), "_continued", time.strftime("%Y%m%d-%H%M%S"))
        folder, n = base, 1
        while os.path.exists(folder):
            n += 1
            folder = f"{base}-{n}"
        os.makedirs(folder)
        image = os.path.join(folder, f"{stem}.png")
        shutil.copyfile(os.path.join(run_dir, "input.png"), image)
        start = os.path.join(folder, f"{stem}-start.svg")
        with open(start, "w", encoding="utf-8") as f:
            f.write(svg if keep else strokes.unfix(svg))
        settings = dict(self.params.all_settings()["clipasso"])
        settings.update(method="clipasso", path_svg=start, num_paths=strokes.shape_count(svg) + int(new),
                        num_iter=int(iterations), num_sketches=1, num_stages=1, mask_object=False,
                        frame_object=False, fix_scale=False, multiprocess=False)
        return image, settings

    def _erase_begin(self):
        seed = self._editable_seed()
        if seed is None:
            return
        self._edit_undo.setdefault(seed, []).append(self.seed_svgs[seed])
        self._edit_redo[seed] = []
        self._edit_changed = False

    def _erase_stroke(self, index: int):
        seed = self._editable_seed()
        if seed is None:
            return
        from .. import strokes

        self._show_edited(seed, strokes.remove_strokes(self.seed_svgs[seed], [index]))
        self._edit_changed = True

    def _erase_end(self):
        seed = self._editable_seed()
        if seed is None:
            return
        if not self._edit_changed:  # clicked next to every stroke: no undo step
            stack = self._edit_undo.get(seed)
            if stack:
                stack.pop()
        else:
            self._save_edit(seed)
        self._update_edit_tools()

    def _show_edited(self, seed: int, svg: str):
        self.seed_svgs[seed] = svg
        if seed in self.thumbs:
            self.thumbs[seed].set_svg(svg)
        if self.view_method == "scenesketch":
            self.matrix.set_cell(seed, svg)
        if seed == (self.selected_seed if self.selected_seed is not None else self.best_seed):
            self.canvas.set_svg(svg)

    def _save_edit(self, seed: int):
        run_dir = self.seed_runs[seed]
        edited = os.path.join(run_dir, jobs.EDITED_FILE)
        with open(os.path.join(run_dir, "best_iter.svg"), encoding="utf-8") as f:
            original = f.read()
        if self.seed_svgs[seed] == original:
            if os.path.isfile(edited):
                os.remove(edited)
        else:
            with open(edited, "w", encoding="utf-8") as f:
                f.write(self.seed_svgs[seed])

    def undo_edit(self):
        seed = self._editable_seed()
        if seed is None or not self._edit_undo.get(seed):
            return
        self._edit_redo.setdefault(seed, []).append(self.seed_svgs[seed])
        self._show_edited(seed, self._edit_undo[seed].pop())
        self._save_edit(seed)
        self._update_edit_tools()

    def redo_edit(self):
        seed = self._editable_seed()
        if seed is None or not self._edit_redo.get(seed):
            return
        self._edit_undo.setdefault(seed, []).append(self.seed_svgs[seed])
        self._show_edited(seed, self._edit_redo[seed].pop())
        self._save_edit(seed)
        self._update_edit_tools()

    def revert_edits(self):
        """Back to the sketch as it was drawn (can be undone)."""
        seed = self._editable_seed()
        if seed is None:
            return
        with open(os.path.join(self.seed_runs[seed], "best_iter.svg"), encoding="utf-8") as f:
            original = f.read()
        if original == self.seed_svgs[seed]:
            return
        self._edit_undo.setdefault(seed, []).append(self.seed_svgs[seed])
        self._edit_redo[seed] = []
        self._show_edited(seed, original)
        self._save_edit(seed)
        self._update_edit_tools()

    def sizeHint(self):  # noqa: N802
        return QSize(1400, 860)

