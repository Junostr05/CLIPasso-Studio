"""Studio page: input, live canvas, parameters and results."""

from __future__ import annotations

import json
import os
import shutil
import sys
import time

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QActionGroup, QColor, QDesktopServices, QGuiApplication, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QMenu, QMessageBox,
                               QProgressBar, QScrollArea, QSplitter, QToolButton, QVBoxLayout, QWidget)

from ... import paths
from ... import settings_schema as schema
from ...engine import imaging, jobs, masking, model_store
from .. import brush, dialogs, icons, image_hints, image_io, mask_view, methods_ui, paper, shortcuts, theme
from ..app_settings import app_settings
from ..controller import JobController, QueuedJob
from ..i18n import i18n, tr
from ..widgets.canvas import (DISPLAY_MAX, IMAGE_EXT, IMAGE_FILTER, ImageDropZone, LossChart, MatrixView, SeedThumb,
                              SheetView, SketchCanvas, load_pixmap)
from ..widgets.common import (Banner, Card, ElidedLabel, SegmentedControl, ToggleSwitch, WrapRow, button, label,
                              tool_button)
from ..widgets.edit_bar import EditBar, importance_command
from ..widgets.hint_box import HintBox
from ..widgets.method_picker import MethodPicker
from ..widgets.param_panel import ParamPanel, param_text_key


def _pixmap_from_png(data: bytes) -> QPixmap:
    pm = QPixmap()
    pm.loadFromData(data, "PNG")
    return pm


STATS_SPACING, STATS_SPACING_NARROW = 28, 12  # px between the numbers below the progress bar


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


def _scene_attention(job_dir: str, cell_dir: str) -> str:
    """The attention map of a SceneSketch cell: it lies in the run of its background part (also when the job
    folder has moved since)."""
    import json

    try:
        with open(os.path.join(cell_dir, "config.json"), encoding="utf-8") as f:
            run = json.load(f).get("background_run") or ""
    except (OSError, ValueError):
        return ""
    path = os.path.join(run, "attention_map.png")
    if not os.path.isfile(path):
        parts = os.path.normpath(run).split(os.sep)
        if "runs" in parts:
            path = os.path.join(job_dir, *parts[parts.index("runs"):], "attention_map.png")
    return path


class StudioPage(QWidget):
    toast = Signal(str, str)
    open_queue = Signal()
    open_settings = Signal()  # the badge of the experimental sketch improvement: to its switch
    focus_requested = Signal()  # the focus button: the main window shows only the canvas (full screen)

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
        # SceneSketch: the part being drawn ("background" / "object"), the layout of the matrix and the layer shown
        self.scene_part = ""
        self.scene_layout: tuple[list[int], list[int]] | None = None
        self.layer_part = "all"
        self._layers_ok: dict[str, bool] = {}
        self._status_key = ("ui.status.idle", {})

        root = QVBoxLayout(self)
        theme.page_layout(root)

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
        # quality hints about the photo (too small / dark / blurred, a tiny object, an unsure mask)
        self.hint_box = HintBox()
        self.hint_box.action.connect(self._hint_action)
        self.hint_box.dismissed.connect(self.dismiss_hint)
        self.input_card.body.addWidget(self.hint_box)
        self._photo_hints: list = []
        self._mask_hints: list = []
        # every earlier job of this picture (any method): a strip to open one again
        self.history_title = label("", "faint")
        self.history_strip = QWidget()
        self.history_layout = QHBoxLayout(self.history_strip)
        self.history_layout.setContentsMargins(0, 0, 0, 0)
        self.history_layout.setSpacing(6)
        self.history_layout.addStretch(1)
        self.history_scroll = QScrollArea()
        self.history_scroll.setWidget(self.history_strip)
        self.history_scroll.setWidgetResizable(True)
        self.history_scroll.setFrameShape(QFrame.NoFrame)
        self.history_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.history_scroll.setFixedHeight(96)
        for w in (self.history_title, self.history_scroll):
            w.hide()
            self.input_card.body.addWidget(w)
        self.history_jobs: list[str] = []
        self._history_cache = None
        self._history_timer = QTimer(self)
        self._history_timer.setSingleShot(True)
        self._history_timer.setInterval(120)
        self._history_timer.timeout.connect(self.refresh_history)
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
        self.detail_btn = button("", "sparkles", "ghost")  # detail brush (and portrait mode)
        self.detail_btn.clicked.connect(self.edit_details)
        self.recent_btn = button("", "clock", "ghost")  # the last images (icon only: the row is narrow)
        self.recent_menu = QMenu(self)
        self.recent_menu.aboutToShow.connect(self._build_recent_menu)
        self.recent_btn.setMenu(self.recent_menu)
        self.webcam_btn = button("", "camera", "ghost")
        self.webcam_btn.clicked.connect(self.take_webcam_photo)
        # (two groups: the tools go to a second line when the column is narrow – a small window)
        files, tools = QWidget(), QWidget()
        for box, buttons in ((files, (self.open_btn, self.samples_btn)),
                             (tools, (self.recent_btn, self.webcam_btn, self.edit_btn, self.detail_btn))):
            lay = QHBoxLayout(box)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(6)
            for b in buttons:
                lay.addWidget(b)
            lay.addStretch(1)
        self.input_buttons = WrapRow(files, tools)
        row.addWidget(self.input_buttons, 1)
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
        # time budget: the settings that give the best sketch in that time on this computer
        r = QHBoxLayout()
        self.budget_label = label("", None)
        self.budget_btn = button("", "clock", "ghost", size="sm")
        self.budget_menu = QMenu(self)
        self.budget_actions = {}
        for minutes in methods_ui.BUDGET_MINUTES:
            action = self.budget_menu.addAction("")
            action.triggered.connect(lambda _=False, m=minutes: self.fit_to_budget(m))
            self.budget_actions[minutes] = action
        self.budget_menu.addSeparator()
        self.budget_other = self.budget_menu.addAction("")
        self.budget_other.triggered.connect(lambda: self.fit_to_budget(None))
        self.budget_btn.setMenu(self.budget_menu)
        r.addWidget(self.budget_label)
        r.addStretch(1)
        r.addWidget(self.budget_btn)
        self.input_card.body.addLayout(r)
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
        # for web pages and apps: Lottie (lottie-web, LottieFiles) and a page of its own
        b = button("Lottie", "sparkles", "ghost")
        b.clicked.connect(lambda _=False: self.export("lottie"))
        grid.addWidget(b, 4, 0)
        self.export_btns["lottie"] = b
        b = button("", "globe", "ghost")
        b.clicked.connect(lambda _=False: self.export("html"))
        grid.addWidget(b, 4, 1)
        self.export_btns["html"] = b
        # SceneSketch: every sketch of the matrix at once
        b = button("", "layers", "ghost")
        b.clicked.connect(lambda _=False: self.export("matrix"))
        grid.addWidget(b, 5, 0)
        self.export_btns["matrix"] = b
        b = button("", "pen-tool", "ghost")  # the cell with background and object as two layers
        b.clicked.connect(lambda _=False: self.export("svglayers"))
        grid.addWidget(b, 5, 1)
        self.export_btns["svglayers"] = b
        b = button("", "copy", "ghost")  # the sketch on the clipboard (PNG + SVG)
        b.clicked.connect(lambda _=False: self.copy_sketch())
        grid.addWidget(b, 6, 0, 1, 2)
        self.export_btns["copy"] = b
        b = button("", "printer", "ghost")  # print layout: page, margins, title, signature – PDF or printer
        b.clicked.connect(lambda _=False: self.print_sketch())
        grid.addWidget(b, 7, 0, 1, 2)
        self.export_btns["print"] = b
        self.result_card.body.addLayout(grid)
        self.folder_btn = button("", "folder-open", "ghost")
        self.folder_btn.clicked.connect(self.open_folder)
        self.reuse_btn = button("", "refresh-cw", "ghost")
        self.reuse_btn.clicked.connect(self.use_as_initial_svg)
        self.series_btn = button("", "layers", "ghost")
        self.series_btn.clicked.connect(self.abstraction_series)
        for b in (self.folder_btn, self.reuse_btn, self.series_btn):
            b.setProperty("align", "left")
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
        self.center_card = center
        center.setMinimumWidth(380)
        self.modes = SegmentedControl([(m, "") for m in SketchCanvas.MODES])
        self.modes.set_icons({"sketch": "pen-tool", "compare": "flip-horizontal-2", "attention": "eye",
                              "mask": "scan", "condition": "mountain", "matrix": "layers",
                              "sheet": "images"})
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
        # a saved step as the result, and "Simplify" (the least important strokes go first): a bar below the canvas
        self.history_btn = tool_button("clock", "", 18)
        self.history_btn.clicked.connect(self.open_history)
        # time-lapse: the saved steps played on the canvas (click: play / pause; the arrow: the speed)
        self.play_btn = tool_button("play", "", 18)
        self.play_btn.setPopupMode(QToolButton.MenuButtonPopup)
        self.play_btn.clicked.connect(self.toggle_timelapse)
        self.speed_menu = QMenu(self)
        self.speed_group = QActionGroup(self)
        self.speed_actions = {}
        for speed in (0.5, 1.0, 2.0, 4.0):
            action = self.speed_menu.addAction(f"{speed:g}×")
            action.setCheckable(True)
            action.setChecked(speed == 1.0)
            action.triggered.connect(lambda _=False, v=speed: self.set_timelapse_speed(v))
            self.speed_group.addAction(action)
            self.speed_actions[speed] = action
        self.play_btn.setMenu(self.speed_menu)
        self._lapse = {"frames": [], "index": 0, "seed": None, "speed": 1.0}
        self._lapse_timer = QTimer(self)
        self._lapse_timer.timeout.connect(self._timelapse_step)
        self.simplify_btn = tool_button("sliders-horizontal", "", 18)
        self.simplify_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)  # (with its name: easy to find)
        self.simplify_btn.clicked.connect(self.open_simplify)
        # thumbs up / down: the user's own taste ("Best sketch: My taste" from 10 ratings on)
        self.up_btn = tool_button("thumbs-up", "", 18, checkable=True)
        self.up_btn.clicked.connect(lambda: self.rate_sketch(1))
        self.down_btn = tool_button("thumbs-down", "", 18, checkable=True)
        self.down_btn.clicked.connect(lambda: self.rate_sketch(-1))
        self._embed_proc = None
        self._closing = False
        for b in (self.eraser_btn, self.pen_btn, self.undo_btn, self.redo_btn, self.revert_btn, self.history_btn,
                  self.play_btn,
                  self.simplify_btn, self.continue_btn):
            et.addWidget(b)
        et.addSpacing(6)
        et.addWidget(self.up_btn)
        et.addWidget(self.down_btn)
        tools_row.addWidget(self.edit_tools)
        # SceneSketch: the whole cell, only its background or only its object (gui/scene_layers.py)
        self.layer_btn = tool_button("layers", "", 18)
        self.layer_btn.setPopupMode(QToolButton.InstantPopup)
        self.layer_menu = QMenu(self)
        self.layer_group = QActionGroup(self)
        self.layer_actions = {}
        for key in ("all", "background", "object"):
            action = self.layer_menu.addAction("")
            action.setCheckable(True)
            action.setChecked(key == "all")
            action.triggered.connect(lambda _=False, k=key: self.set_layer_part(k))
            self.layer_group.addAction(action)
            self.layer_actions[key] = action
        self.layer_btn.setMenu(self.layer_menu)
        self.layer_btn.setVisible(False)
        tools_row.addWidget(self.layer_btn)
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
        # the paper the sketches are shown on – the export starts with it, too
        self.style_menu.addSeparator()
        self.paper_menu = self.style_menu.addMenu("")
        self.paper_group = QActionGroup(self)
        self.paper_actions = {}
        for key in paper.KINDS:
            action = self.paper_menu.addAction("")
            action.setCheckable(True)
            action.triggered.connect(lambda _=False, k=key: self.set_canvas_paper(kind=k))
            self.paper_group.addAction(action)
            self.paper_actions[key] = action
        self.paper_menu.addSeparator()
        self.paper_color_action = self.paper_menu.addAction("")
        self.paper_color_action.triggered.connect(self._pick_paper_color)
        self.vignette_action = self.paper_menu.addAction("")
        self.vignette_action.setCheckable(True)
        self.vignette_action.triggered.connect(lambda on: self.set_canvas_paper(vignette=on))
        self.style_btn.setMenu(self.style_menu)
        tools_row.addWidget(self.style_btn)
        # focus mode: only the canvas, full screen (also F11; Esc ends it)
        self.focus_btn = tool_button("maximize-2", "", 18)
        self.focus_btn.clicked.connect(self.focus_requested.emit)
        tools_row.addWidget(self.focus_btn)
        self.focused = False
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
        self.edit_bar = EditBar()
        self.edit_bar.preview.connect(self.canvas.set_svg)
        self.edit_bar.apply.connect(self._edit_bar_apply)
        self.edit_bar.closed.connect(self._edit_bar_closed)
        self._importance_proc = None
        center.body.addWidget(self.edit_bar)
        self.matrix = MatrixView()  # SceneSketch: all cells of the abstraction matrix
        self.matrix.clicked.connect(self.select_seed)
        self.matrix.activated.connect(self._open_cell)
        self.matrix.menu_requested.connect(lambda cell, pos: self._matrix_menu_for(cell).exec(pos))
        self.matrix.setVisible(False)
        center.body.addWidget(self.matrix, 1)
        self.sheet = SheetView()  # every sketch of the job side by side (contact sheet)
        self.sheet.clicked.connect(self.select_seed)
        self.sheet.activated.connect(self._open_cell)
        self.sheet.menu_requested.connect(self._sheet_menu)
        self.sheet.setVisible(False)
        center.body.addWidget(self.sheet, 1)

        self.status = ElidedLabel("", "h3")  # (a long file name ends in "…", not in the middle of a word)
        status_row = QHBoxLayout()
        status_row.addWidget(self.status, 1)
        status_row.addWidget(self.estimate_holder())
        center.body.addLayout(status_row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        center.body.addWidget(self.progress)
        self.stats_row = QWidget()  # (narrow: closer together, then without the current loss and the time so far)
        self.stats_row.setMinimumWidth(0)
        self.stats_layout = QHBoxLayout(self.stats_row)
        self.stats_layout.setContentsMargins(0, 0, 0, 0)
        self.stats_layout.setSpacing(STATS_SPACING)
        self.stat_iter, self.stat_loss, self.stat_best, self.stat_time, self.stat_eta = (StatTile() for _ in range(5))
        for t in (self.stat_iter, self.stat_loss, self.stat_best, self.stat_time, self.stat_eta):
            self.stats_layout.addWidget(t)
        self.stats_layout.addStretch(1)
        self.stats_row.installEventFilter(self)
        center.body.addWidget(self.stats_row)
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
        run, more = QWidget(), QWidget()  # (the queue button to a second line when the canvas is narrow)
        self.action_run = run
        rl = QHBoxLayout(run)
        rl.setContentsMargins(0, 0, 0, 0)
        for b in (self.start_btn, self.pause_btn, self.cancel_btn):
            rl.addWidget(b)
        rl.addStretch(1)
        ml = QHBoxLayout(more)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.addStretch(1)
        ml.addWidget(self.queue_btn)
        self.action_row = WrapRow(run, more)
        self.action_row.installEventFilter(self)  # (too narrow even alone: Pause and Cancel as icons, see _fit_actions)
        actions.addWidget(self.action_row, 1)
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
        self.params.notify.connect(self.toast.emit)
        self.params.import_btn.clicked.connect(self.import_preset)
        self.params.export_btn.clicked.connect(self.export_preset)
        self.params.cli_btn.clicked.connect(self.copy_cli)
        # the experimental sketch improvement is on (switched in the settings): new jobs use it
        self.experimental_btn = button("", "wand-sparkles", "ghost", size="sm")
        self.experimental_btn.clicked.connect(self.open_settings.emit)
        self.experimental_btn.setVisible(False)
        right.body.addWidget(self.experimental_btn)
        right.body.addWidget(self.params)
        splitter.addWidget(right)
        self.right_pane = right
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
        self._apply_canvas_paper()
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

    def edit_details(self) -> bool:
        """Detail brush: paint where the sketch should have more or less detail (CLIPasso, ControlSketch)."""
        if not self.image_path or not os.path.isfile(self.image_path):
            return False
        from ..detail_edit import DetailEditDialog

        dlg = DetailEditDialog(self.image_path, self)
        if dlg.exec() and dlg.saved:
            self._update_detail_button()
            self.toast.emit(tr("ui.detail.saved"), "success")
            return True
        return False

    def _update_detail_button(self):
        from ...engine import details

        has = False
        if self.image_path and os.path.isfile(self.image_path):
            try:
                has = details.detail_path(imaging.load_rgb(self.image_path)).is_file()
            except OSError:
                has = False
        used = self.params.method() in ("clipasso", "controlsketch")
        self.detail_btn.setEnabled(bool(self.image_path))
        self.detail_btn.setToolTip(tr("ui.detail.tip") + ("\n" + tr("ui.detail.has") if has else "")
                                   + ("" if used else "\n" + tr("ui.detail.not_used")))

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
        self._photo_hints, self._mask_hints = [], []
        self.show_hints()
        self._check_photo(path)
        self._update_mask_preview()
        self._update_detail_button()
        self._update_buttons()
        self._history_timer.start()

    # ------------------------------------------------------------------ quality hints
    def _check_photo(self, path: str):
        """The hints about the photo itself, measured in the background (decoding a big photo takes a moment)."""
        found = {}  # (run_in_thread hands a result on as text)

        def measure(path, progress=None):
            found["hints"] = image_hints.photo_hints(path)

        def done(_, path=path):
            if path == self.image_path:
                self._photo_hints = found.get("hints", [])
                self.show_hints()

        dialogs.run_in_thread(self, measure, path, on_done=done, on_error=lambda _: None)

    def hints(self) -> list:
        """The hints shown (the kinds not switched off, the most helpful first)."""
        return image_hints.shown(self._photo_hints + self._mask_hints, app_settings().get("hints_off") or [])

    def show_hints(self):
        self.hint_box.set_hints(self.hints() if self.image_path else [])

    def _hint_action(self, action: str):
        if action == "crop":
            self.edit_image()
        elif action == "mask":
            if self._mask is not None:
                self.edit_mask()
            else:
                self.mask_eye.setChecked(True)

    def dismiss_hint(self, key: str):
        """Do not show this kind of hint again (the settings can show them all again)."""
        off = list(app_settings().get("hints_off") or [])
        if key not in off:
            app_settings().set("hints_off", off + [key])
        self.show_hints()
        self.toast.emit(tr("ui.hint.dismissed"), "info")

    # ------------------------------------------------------------------ earlier jobs of the picture
    def _same_picture(self, summary: dict, job_dir: str) -> bool:
        """The job was made from the studio's picture: the same file, or (the job keeps a copy of its picture)
        a file of the same name and size."""
        image = self.image_path
        target = summary.get("target") or ""
        if not image or not target:
            return False
        if os.path.normcase(os.path.abspath(target)) == os.path.normcase(os.path.abspath(image)):
            return True
        copy = os.path.join(job_dir, jobs.INPUT_DIR, os.path.basename(target))
        if os.path.normcase(os.path.abspath(copy)) == os.path.normcase(os.path.abspath(image)):
            return True
        try:
            return os.path.basename(target) == os.path.basename(image) and \
                os.path.getsize(copy) == os.path.getsize(image)
        except OSError:
            return False

    def refresh_history(self):
        """The strip of earlier jobs of the studio's picture, the newest first (the shown one marked)."""
        from ..pages.gallery import ScanCache

        if self._history_cache is None:
            self._history_cache = ScanCache()
        found = []
        if self.image_path:
            for job_dir, summary in self._history_cache.scan(app_settings().get("output_dir")):
                if os.path.isfile(os.path.join(job_dir, "job.json")) and self._same_picture(summary, job_dir):
                    found.append((job_dir, summary))
        found.sort(key=lambda t: str(t[1].get("created", "")), reverse=True)
        while self.history_layout.count() > 1:
            item = self.history_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        self.history_jobs = [d for d, _ in found]
        shown = os.path.normcase(os.path.abspath(self.view_dir)) if self.view_dir else ""
        tallest = 90
        for job_dir, summary in found:
            tile = self._history_button(job_dir, summary, shown)
            tallest = max(tallest, tile.height())
            self.history_layout.insertWidget(self.history_layout.count() - 1, tile)
        # the tiles and, below them, room for the scroll bar of many jobs
        self.history_scroll.setFixedHeight(tallest + self.history_scroll.horizontalScrollBar().sizeHint().height())
        self.history_title.setText(tr("ui.history.title", n=len(found)))
        for w in (self.history_title, self.history_scroll):
            w.setVisible(bool(found))

    def _history_button(self, job_dir: str, summary: dict, shown: str) -> QToolButton:
        from ...engine import imaging
        from ..widgets.canvas import svg_renderer

        method = summary.get("method") or schema.method_of(summary.get("settings"))
        b = QToolButton()
        b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        b.setCheckable(True)
        b.setChecked(os.path.normcase(os.path.abspath(job_dir)) == shown)
        b.setIconSize(QSize(64, 56))
        b.setCursor(Qt.PointingHandCursor)
        sketch = jobs.best_sketch(summary)
        pm = QPixmap(64, 56)
        pm.fill(QColor(theme.current().paper))
        renderer = None
        try:
            with open(sketch, encoding="utf-8") as f:
                renderer = svg_renderer(f.read())
        except OSError:
            pass
        if renderer:
            from PySide6.QtGui import QPainter

            p = QPainter(pm)
            renderer.render(p, QRectF(4, 0, 56, 56))
            p.end()
        b.setIcon(QIcon(pm))
        b.setText(f"{methods_ui.name(method)[:11]}\n{str(summary.get('created', ''))[5:10]}")
        b.setFixedSize(84, max(90, b.sizeHint().height()))  # (the two lines under the sketch are not cut)
        score = summary.get("clip_score")
        secs = summary.get("seconds") or 0
        b.setToolTip(tr("ui.history.tip", method=methods_ui.name(method), date=str(summary.get("created", ""))[:16],
                        score=f"{score:.1f}" if isinstance(score, (int, float)) else "–",
                        time=imaging.eta_string(secs) if secs else "–"))
        b.clicked.connect(lambda _=False, d=job_dir: self._open_history_job(d))
        return b

    def _open_history_job(self, job_dir: str):
        self.show_job_dir(job_dir)
        self._history_timer.start()

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
            if self._mask_hints:
                self._mask_hints = []
                self.show_hints()
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
        self._mask_hints = image_hints.mask_hints(prob, edited)
        self.show_hints()
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
        self._closing = True
        self.mask_preview.shutdown()
        from PySide6.QtCore import QProcess

        for proc in (self._embed_proc, self._importance_proc):
            if proc is not None and proc.state() != QProcess.NotRunning:
                proc.kill()
                proc.waitForFinished(2000)

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
        self._update_detail_button()
        self.update_experimental()

    def update_experimental(self) -> None:
        """The badge of the experimental sketch improvement: on, and a method it works for."""
        on = bool(app_settings().get("experimental_sketch", False))
        self.experimental_btn.setVisible(on and self.params.method() in schema.SKETCH_GUIDE_METHODS)

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
        self.modes.set_visible("sheet", not scene)  # (SceneSketch has its matrix)
        current = self.modes.current()
        allowed = {"sketch", "compare", "mask"} | ({"attention"} if method != "swiftsketch" else set()) | (
            {"condition"} if method in ("controlsketch", "scenesketch") else set()) | (
            {"matrix"} if scene else {"sheet"})
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
        settings = self._check_resources()
        if settings is None:
            return
        self.controller.enqueue(self.image_path, settings, start=True)
        if self.controller.current and self.controller.current.target != self.image_path:
            self.toast.emit(tr("ui.added_to_queue"), "info")

    def add_to_queue(self):
        if not self.image_path or not self._check_models():
            return
        settings = self._check_resources()
        if settings is None:
            return
        self.controller.enqueue(self.image_path, settings, start=not self.controller.is_busy())
        self.toast.emit(tr("ui.added_to_queue"), "success")

    def _check_resources(self) -> dict | None:
        """The settings to run with: as they are, the smaller ones the user accepted when memory is short, or
        None (cancelled)."""
        from .. import resources

        settings = self.params.settings()
        checked = resources.confirm(self, settings)
        if checked is not None and checked != settings:
            self.params.set_settings(checked)  # (the smaller settings are visible in the panel)
        return checked

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
        if self._lapse["seed"] is not None:
            self.stop_timelapse()
        self.resume_banner.hide()
        self._edit_undo.clear()
        self._edit_redo.clear()
        self.canvas.clear()
        self.matrix.clear()
        self.sheet.clear()
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
        self.scene_part, self.scene_layout = "", None
        self._layers_ok.clear()
        self.layer_part = "all"
        self.layer_actions["all"].setChecked(True)
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
        self._history_timer.start()
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
            self._photo_hints, self._mask_hints = [], []
            self.show_hints()
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
        if seed != self.selected_seed:
            self.edit_bar.close_bar()
            if self._lapse["seed"] is not None:
                self.stop_timelapse()
        if seed != self.selected_seed and self.controller.is_busy():
            self.chart.reset(self.chart.total)  # the chart shows the selected sketch only
        self.selected_seed = seed
        self.matrix.set_selected(seed)
        self.sheet.set_selected(seed)
        for s, t in self.thumbs.items():
            t.set_selected(s == seed)
        self.canvas.set_svg(self._shown_svg(seed))
        self.canvas.set_attention(self.seed_attn.get(seed))
        self._update_layer_btn()
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
            text = self._device_text(data.get("device", ""))
            n = len(getattr(job, "devices", ()) or ())
            self.device_badge.setText(f"{n}× {text}" if n > 1 else text)  # (one worker per graphics card)
        elif kind == "stage":
            n = job.seeds.index(seed) + 1 if seed in job.seeds else 1
            extra = {k: v for k, v in data.items() if k not in ("name", "seed", "n", "total")}  # e.g. step/steps
            self._set_status(f"ui.status.{data['name']}", n=n, total=len(job.seeds), **extra)
            if data["name"].startswith("init_sdxl_") and data.get("step", 0) >= 3 and data.get("elapsed"):
                rates = dict(app_settings().get("sec_per_it", {}) or {})  # SDXL piece by piece / on the CPU
                rates["sdxl:" + data["name"][len("init_sdxl_"):]] = data["elapsed"] / data["step"]
                app_settings().data["sec_per_it"] = rates
                if data["step"] % 10 == 0:
                    app_settings().set("sec_per_it", rates)
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
            self._cell(seed, data["svg"])
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
            self._cell(seed, data["svg"])
            if seed == self.selected_seed:
                self.canvas.set_svg(self._shown_svg(seed))
                self._update_layer_btn()
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
            self.sheet.set_best(self.best_seed)
            if self.best_seed is not None:
                self.select_seed(self.best_seed)
                self._simplify_tip()
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
            self.scene_part = part or ""
            self._set_status(f"ui.status.scene_{part}" if part else "ui.status.optimizing", n=n, total=len(job.seeds))

    def _job_finished(self, job: QueuedJob):
        self._history_timer.start()  # (a new job of the picture)
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
        send = box.addButton(tr("ui.report.button"), QMessageBox.ActionRole)
        box.addButton(QMessageBox.Close)
        box.exec()
        if box.clickedButton() is send:
            from .. import report

            report.offer(self, data.get("message", ""), data.get("traceback", ""))

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
            from ...engine import details

            details.restore_from_job(job_dir, src)
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
            self._cell(seed, self.seed_svgs[seed])
            if r.get("clip_score") is not None:
                self.seed_scores[seed] = r["clip_score"]
            cond = next((os.path.join(r["run_dir"], f) for f in os.listdir(r["run_dir"])
                         if f.endswith("_condition.png")), None) if os.path.isdir(r["run_dir"]) else None
            if self.view_method == "scenesketch" and os.path.isfile(os.path.join(job_dir, "background.png")):
                cond = os.path.join(job_dir, "background.png")
            if cond:
                self.canvas.set_condition(QPixmap(cond))
            attn = os.path.join(r["run_dir"], "attention_map.png")
            if self.view_method == "scenesketch" and not os.path.isfile(attn):
                attn = _scene_attention(job_dir, r["run_dir"])
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
        self.sheet.set_best(self.best_seed)
        if self.best_seed is not None:
            self.select_seed(self.best_seed)
        if isinstance(summary.get("settings"), dict):
            self.params.set_settings(summary["settings"])
        self._history_timer.start()
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

    def print_sketch(self) -> str:
        """The print layout dialog for the shown sketch."""
        from ..print_dialog import open_print

        sel = self._selected_run()
        if not sel:
            return ""
        saved = open_print(self, [(sel[0], os.path.basename(sel[1]))])
        if saved:
            self.toast.emit(tr("ui.exported", path=saved), "success")
        return saved

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
                       "ui.status.caption", "ui.status.condition", "ui.status.diffusion_models") or \
            key.startswith(("ui.status.scene_", "ui.status.init_sdxl_"))
        self.stage_badge.setVisible(busy)
        if busy:
            self.stage_badge.setText(tr("ui.live"))

    def hardware_known(self):
        """The hardware probe answered (GPU or not): estimates and hints follow it."""
        self._update_estimate()
        self._update_banner()
        self.params.refresh_hints()
        self.picker.refresh_status(self.params.all_settings())

    def fit_to_budget(self, minutes: int | None) -> dict | None:
        """Change the settings so the job takes about ``minutes`` (None: ask) with the best expected sketch."""
        from PySide6.QtWidgets import QInputDialog

        if minutes is None:
            minutes, ok = QInputDialog.getInt(self, tr("ui.budget.title"), tr("ui.budget.ask"), 30, 1, 24 * 60, 5)
            if not ok:
                return None
        s = self.params.settings()
        gpu = s["device"] == "cuda" or (s["device"] == "auto" and methods_ui.has_cuda())
        changes, secs = methods_ui.fit_to_budget(s, minutes * 60, gpu)
        for key, value in changes.items():
            if key in self.params.fields:
                self.params.fields[key].set_value(value, emit=True)
        self._update_estimate()
        if secs > minutes * 60 * 1.05:
            self.toast.emit(tr("ui.budget.too_short", time=imaging.eta_string(secs)), "info")
        elif changes:
            parts = []
            for key, value in changes.items():
                name = tr(param_text_key(self.params.method(), key, "label"))
                value = tr("ui.resources.on" if value else "ui.resources.off") if isinstance(value, bool) else value
                parts.append(f"{name}: {value}")
            self.toast.emit(tr("ui.budget.done", changes=", ".join(parts), time=imaging.eta_string(secs)), "success")
        else:
            self.toast.emit(tr("ui.budget.fits", time=imaging.eta_string(secs)), "success")
        return changes

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

    def set_focus(self, on: bool):
        """Focus mode: the panes beside the canvas go (the main window hides its own parts and goes full screen)."""
        self.focused = bool(on)
        self.left_scroll.setVisible(not self.focused)
        self.right_pane.setVisible(not self.focused)
        self.focus_btn.setIcon(icons.icon("minimize-2" if self.focused else "maximize-2", theme.current().muted,
                                          active_color=theme.current().text))
        self.focus_btn.setToolTip(tr("ui.focus.leave" if self.focused else "ui.focus.enter"))

    def _cell(self, seed: int, svg: str):
        """A sketch of the shown job changed: its cell in the matrix (SceneSketch) and on the contact sheet."""
        if self.view_method == "scenesketch":
            self.matrix.set_cell(seed, svg)
        thumb = self.thumbs.get(seed)
        self.sheet.set_cell(seed, svg, thumb.caption.text() if thumb and thumb.caption.text() else str(seed))

    def _sheet_menu(self, seed: int, pos):
        self._sheet_menu_for(seed).exec(pos)

    def _sheet_menu_for(self, seed: int) -> QMenu:
        """The contact sheet's menu: the sketch as the job's result, a thumb up or down, the sketch large."""
        menu = QMenu(self)
        menu.addAction(tr("ui.sheet.open"), lambda: self._open_cell(seed))
        best = menu.addAction(tr("ui.sheet.make_best"), lambda: self.choose_best(seed))
        best.setEnabled(seed != self.best_seed and self._can_choose_best(seed))
        menu.addSeparator()
        for value, key in ((1, "ui.rate.up"), (-1, "ui.rate.down")):
            act = menu.addAction(tr(key), lambda v=value: (self.select_seed(seed), self.rate_sketch(v)))
            act.setEnabled(self._can_choose_best(seed))
        return menu

    def _matrix_menu_for(self, cell: int) -> QMenu:
        """The matrix's menu: the contact sheet's, and computing a cell again (with a new start)."""
        menu = self._sheet_menu_for(cell)
        menu.addSeparator()
        again = menu.addAction(icons.icon("refresh-cw", theme.current().text), tr("ui.matrix.rerun"),
                               lambda: self.rerun_scene_cell(cell))
        again.setEnabled(self._can_choose_best(cell))
        return menu

    def rerun_scene_cell(self, cell: int, confirm: bool = True) -> bool:
        """SceneSketch: compute a cell of the shown job again with a new start value – and the later levels of its
        layer, which start from it. The job continues in the queue; the other cells stay."""
        if not self._can_choose_best(cell):
            return False
        state = jobs.read_state(self.view_dir) or {}
        layer, level = divmod(int(cell), 100)
        later = [lv for lv in schema.scene_levels(state.get("settings") or {}) if lv > level]
        if confirm and later and QMessageBox.question(
                self, tr("ui.matrix.rerun"), tr("ui.matrix.rerun_q", layer=layer, level=level,
                                                later=", ".join(str(lv) for lv in later))) != QMessageBox.Yes:
            return False
        job_dir = self.view_dir
        removed = jobs.rerun_scene_cell(job_dir, cell)
        for c in removed:
            self.seed_runs.pop(c, None)
        if self.controller.continue_job(job_dir) is None:
            return False
        self.toast.emit(tr("ui.matrix.rerun_queued", n=len(removed)), "info")
        return True

    def _can_choose_best(self, seed: int) -> bool:
        """A finished sketch of a job that is not running (shown from its folder)."""
        job = self.controller.current
        running = job is not None and self.controller.is_busy() and job is self.view_job
        return bool(self.view_dir) and not running and bool(self.seed_runs.get(seed))

    def choose_best(self, seed: int) -> bool:
        """Make ``seed`` the job's result (chosen by hand; the gallery, exports and the phone take it)."""
        if not self._can_choose_best(seed):
            return False
        name = os.path.basename(os.path.normpath(self.seed_runs[seed]))
        if not jobs.set_best_run(self.view_dir, name):
            return False
        old = self.best_seed
        self.best_seed = seed
        for s, t in self.thumbs.items():
            t.set_best(s == seed)
            text = t.caption.text().removeprefix("★ ")
            t.set_caption(f"★ {text}" if s == seed else text)
            self.sheet.set_caption(s, t.caption.text())
        self.matrix.set_best(seed)
        self.sheet.set_best(seed)
        if old != seed:
            self.toast.emit(tr("ui.sheet.best_set"), "success")
        return True

    def _setup_matrix(self, settings: dict):
        if schema.method_of(settings) == "scenesketch":
            self.scene_layout = (schema.scene_layers(settings), schema.scene_levels(settings))
            self.matrix.set_layout(*self.scene_layout)
        else:
            self.scene_layout = None
            self.matrix.clear()

    # ------------------------------------------------------------------ SceneSketch layers
    def layers_available(self, seed: int | None) -> bool:
        """The cell has its background and object as layers (finished; cached per cell folder)."""
        from .. import scene_layers

        run_dir = self.seed_runs.get(seed) if seed is not None else None
        if self.view_method != "scenesketch" or not run_dir:
            return False
        if run_dir not in self._layers_ok:
            self._layers_ok[run_dir] = scene_layers.available(run_dir)
        return self._layers_ok[run_dir]

    def _shown_svg(self, seed: int | None) -> str | None:
        """The sketch of ``seed`` as the canvas shows it: whole, or only the chosen layer of a SceneSketch cell."""
        svg = self.seed_svgs.get(seed)
        if svg and self.layer_part != "all" and self.layers_available(seed):
            from .. import scene_layers

            return scene_layers.part(svg, self.seed_runs.get(seed), self.layer_part)
        return svg

    def set_layer_part(self, part: str):
        """Show the whole SceneSketch cell, only its background or only its object (editing shows it whole)."""
        self.layer_part = part if part in ("all", "background", "object") else "all"
        self.layer_actions[self.layer_part].setChecked(True)
        if self.layer_part != "all":
            for b in (self.eraser_btn, self.pen_btn):
                if b.isChecked():
                    b.setChecked(False)
        seed = self.selected_seed if self.selected_seed is not None else self.best_seed
        if seed is not None and seed in self.seed_svgs:
            self.canvas.set_svg(self._shown_svg(seed))
        self._update_layer_btn()

    def _update_layer_btn(self):
        seed = self.selected_seed if self.selected_seed is not None else self.best_seed
        scene = self.view_method == "scenesketch"
        self.layer_btn.setVisible(scene and self.modes.current() == "sketch")
        self.layer_btn.setEnabled(self.layers_available(seed))
        self.layer_btn.setToolTip(tr("ui.layer.tip") if self.layer_btn.isEnabled() else tr("ui.layer.not_yet"))

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
        self.pause_btn.setProperty("full_text", tr("ui.resume") if paused else tr("ui.pause"))
        self.pause_btn.setIcon(icons.icon("play" if paused else "pause", p.text))
        self.start_btn.setText(tr("ui.start_queue") if busy else tr("ui.start"))
        self.start_btn.setIcon(icons.icon("list-plus" if busy else "play", p.on_accent))
        self.queue_btn.setVisible(not busy)
        self._fit_actions()
        has_result = self._selected_run() is not None
        for b in self.export_btns.values():
            b.setEnabled(has_result)
        self._update_edit_tools()
        self.export_btns["matrix"].setVisible(self.view_method == "scenesketch")
        self.export_btns["matrix"].setEnabled(self._matrix_exportable())
        self.export_btns["svglayers"].setVisible(self.view_method == "scenesketch")
        sel = self.selected_seed if self.selected_seed is not None else self.best_seed
        self.export_btns["svglayers"].setEnabled(self.layers_available(sel))
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
        self.sheet.set_style(style)
        for t in self.thumbs.values():
            t.set_style(style)
        self.style_actions[style].setChecked(True)
        self.style_btn.setToolTip(tr("ui.canvas_style.tip", style=tr(f"ui.brush.{style}")))

    def set_canvas_paper(self, kind: str | None = None, color: str | None = None, vignette: bool | None = None):
        """Show the sketches on another paper (remembered; the export dialog starts with it). Another paper
        brings its own colour."""
        st = app_settings()
        if kind is not None:
            st.data["canvas_paper"] = kind
            st.data["canvas_paper_color"] = ""
        if color is not None:
            st.data["canvas_paper_color"] = color
        if vignette is not None:
            st.data["canvas_vignette"] = bool(vignette)
        kind = st.get("canvas_paper", "none")
        st.data["export_paper"] = kind
        st.data["export_vignette"] = round(paper.VIGNETTE * 100) if st.get("canvas_vignette") else 0
        if kind != "none" or st.get("canvas_paper_color"):
            st.data["export_background"] = paper.color_of({"kind": kind}, st.get("canvas_paper_color") or None)
        st.save()
        self._apply_canvas_paper()

    def _pick_paper_color(self):
        from PySide6.QtWidgets import QColorDialog

        st = app_settings()
        current = paper.color_of({"kind": st.get("canvas_paper", "none")}, st.get("canvas_paper_color") or None)
        c = QColorDialog.getColor(QColor(current), self, tr("ui.paper.color"))
        if c.isValid():
            self.set_canvas_paper(color=c.name())

    def _apply_canvas_paper(self):
        st = app_settings()
        kind = st.get("canvas_paper", "none")
        kind = kind if kind in paper.KINDS else "none"
        color = st.get("canvas_paper_color") or None
        vignette = paper.VIGNETTE if st.get("canvas_vignette") else 0.0
        self.canvas.set_paper({"kind": kind, "vignette": vignette}, color)
        self.paper_actions[kind].setChecked(True)
        self.vignette_action.setChecked(vignette > 0)

    def retranslate(self):
        self.hint_box.retranslate()
        for key, action in self.style_actions.items():
            action.setText(tr(f"ui.brush.{key}"))
        self.paper_menu.setTitle(tr("ui.paper.label"))
        for key, action in self.paper_actions.items():
            action.setText(tr(f"ui.paper.{key}"))
        self.paper_color_action.setText(tr("ui.paper.color") + " …")
        self.vignette_action.setText(tr("ui.paper.vignette"))
        self.style_btn.setToolTip(tr("ui.canvas_style.tip", style=tr(f"ui.brush.{self.canvas.style()}")))
        self.focus_btn.setToolTip(tr("ui.focus.leave" if self.focused else "ui.focus.enter"))
        for key, action in self.layer_actions.items():
            action.setText(tr(f"ui.layer.{key}"))
        self._update_layer_btn()
        self.eraser_btn.setToolTip(tr("ui.eraser.tip"))
        self.history_btn.setToolTip(tr("ui.edit_bar.history_tip"))
        self._update_play_btn()
        self.up_btn.setToolTip(tr("ui.rate.up"))
        self.down_btn.setToolTip(tr("ui.rate.down"))
        self.simplify_btn.setText(tr("ui.edit_bar.simplify"))
        self.experimental_btn.setText(tr("ui.studio.experimental_badge"))
        self.experimental_btn.setToolTip(tr("ui.studio.experimental_tip"))
        self.simplify_btn.setToolTip(tr("ui.edit_bar.simplify_tip"))
        self.edit_bar.retranslate()
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
        self._update_detail_button()
        self.recent_btn.setToolTip(tr("ui.recent"))
        self.webcam_btn.setToolTip(tr("ui.webcam.tip"))
        for key, (lbl, _) in self.quick.items():
            lbl.setText(tr(param_text_key(self.params.method(), key, "label")))
            lbl.setToolTip(tr(param_text_key(self.params.method(), key, "help")))
        self.result_title.setText(tr("ui.result"))
        self.budget_label.setText(tr("ui.budget.label"))
        self.budget_btn.setText(tr("ui.budget.button"))
        self.budget_btn.setToolTip(tr("ui.budget.tip"))
        for minutes, action in self.budget_actions.items():
            action.setText(tr("ui.budget.minutes", n=minutes) if minutes < 60 else
                           tr("ui.budget.hours", n=minutes // 60))
        self.budget_other.setText(tr("ui.budget.other"))
        self.export_btns["svg1"].setText(tr("ui.export_svg1"))
        self.export_btns["svg1"].setToolTip(tr("ui.export_svg1_tip"))
        self.export_btns["webp"].setToolTip(tr("ui.export_webp_tip"))
        self.export_btns["svganim"].setText(tr("ui.export_svganim"))
        self.export_btns["pdf"].setToolTip(tr("ui.export_pdf_tip"))
        self.export_btns["copy"].setText(shortcuts.with_key(tr("ui.copy"), "Ctrl+C"))
        self.export_btns["copy"].setToolTip(tr("ui.copy_tip"))
        self.export_btns["print"].setText(tr("ui.print.button"))
        self.export_btns["print"].setToolTip(tr("ui.print.tip"))
        self.export_btns["svganim"].setToolTip(tr("ui.export_svganim_tip"))
        self.export_btns["lottie"].setToolTip(tr("ui.export_lottie_tip"))
        self.export_btns["html"].setText(tr("ui.export_html"))
        self.export_btns["html"].setToolTip(tr("ui.export_html_tip"))
        self.export_btns["matrix"].setText(tr("ui.export_matrix"))
        self.export_btns["matrix"].setToolTip(tr("ui.export_matrix_tip"))
        self.export_btns["svglayers"].setText(tr("ui.export_svglayers"))
        self.export_btns["svglayers"].setToolTip(tr("ui.export_svglayers_tip"))
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
        self.cancel_btn.setProperty("full_text", tr("ui.cancel"))
        self.queue_btn.setText(tr("ui.add_to_queue"))
        key, fmt = self._status_key
        self.status.setText(tr(key, **fmt))
        self._update_estimate()
        self._update_banner()
        self._update_buttons()

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QEvent.Resize and obj is self.action_row:
            self._fit_actions()
        elif event.type() in (QEvent.Resize, QEvent.LayoutRequest) and obj is self.stats_row:
            self._fit_stats()  # (also when a number grows during a run)
        return super().eventFilter(obj, event)

    def _fit_actions(self):
        """Pause and Cancel show only their icons when Start, Pause and Cancel do not fit side by side (a narrow
        canvas, long German words); their names stay as tooltip and screen-reader name."""
        if getattr(self, "_fitting", False) or not hasattr(self, "action_run"):
            return
        self._fitting = True
        try:
            small = (self.pause_btn, self.cancel_btn)
            for b in small:
                b.setText(b.property("full_text") or "")
            compact = self.action_run.sizeHint().width() > self.action_row.width() > 0
            for b in small:
                name = b.property("full_text") or ""
                b.setAccessibleName(name)
                b.setToolTip(name if compact else "")
                if compact:
                    b.setText("")
        finally:
            self._fitting = False

    def _fit_stats(self):
        """The numbers below the progress bar in a narrow canvas: closer together, then without the current loss
        (the best one stays) and the time so far (the time left stays)."""
        tiles = (self.stat_iter, self.stat_loss, self.stat_best, self.stat_time, self.stat_eta)
        width = self.stats_row.width()

        def needed(shown, spacing):
            return sum(t.sizeHint().width() for t in shown) + spacing * (len(shown) - 1)

        shown, spacing = list(tiles), STATS_SPACING
        if needed(shown, spacing) > width:
            spacing = STATS_SPACING_NARROW
        for drop in (self.stat_loss, self.stat_time):
            if needed(shown, spacing) > width:
                shown.remove(drop)
        self.stats_layout.setSpacing(spacing)
        for t in tiles:
            t.setVisible(t in shown)

    def estimate_holder(self) -> QWidget:
        self.estimate = label("", "faint")
        self.estimate.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return self.estimate

    def _mode_changed(self, mode: str):
        self.canvas.set_mode(mode)
        self.canvas.setVisible(mode not in ("matrix", "sheet"))
        self.matrix.setVisible(mode == "matrix")
        self.sheet.setVisible(mode == "sheet")
        self._update_edit_tools()
        self._update_layer_btn()

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
        if not show:
            self.edit_bar.close_bar()
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
            self._update_rating_buttons(seed)

    def _toggle_eraser(self, on: bool):
        if on and self.pen_btn.isChecked():
            self.pen_btn.setChecked(False)
        if on and self.layer_part != "all":  # (the eraser works on the whole sketch)
            self.set_layer_part("all")
        self.canvas.set_eraser(on)

    def _toggle_pen(self, on: bool):
        if on and self.eraser_btn.isChecked():
            self.eraser_btn.setChecked(False)
        if on and self.layer_part != "all":
            self.set_layer_part("all")
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
        self._cell(seed, svg)
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

    # ------------------------------------------------------- thumbs up / down
    def _rating_of(self, seed: int) -> tuple[str, str, int | None]:
        """(job folder, run name, rating) of a sketch."""
        run_dir = os.path.normpath(self.seed_runs[seed])
        job_dir, name = os.path.dirname(run_dir), os.path.basename(run_dir)
        value = (jobs.read_meta(job_dir).get("ratings") or {}).get(name)
        return job_dir, name, value if value in (1, -1) else None

    def _update_rating_buttons(self, seed: int):
        _, _, value = self._rating_of(seed)
        for btn, v in ((self.up_btn, 1), (self.down_btn, -1)):
            btn.blockSignals(True)
            btn.setChecked(value == v)
            btn.blockSignals(False)

    def rate_sketch(self, value: int) -> bool:
        """Thumb up (1) or down (-1) for the shown sketch – the same thumb again takes it back. Kept with the job
        (meta.json) and, with the sketch's CLIP embedding, in the user's taste (``engine/aesthetic.py``)."""
        from ...engine import aesthetic

        seed = self._editable_seed()
        if seed is None:
            return False
        job_dir, name, current = self._rating_of(seed)
        new = None if current == value else value
        ratings = dict(jobs.read_meta(job_dir).get("ratings") or {})
        if new is None:
            ratings.pop(name, None)
        else:
            ratings[name] = new
        jobs.write_meta(job_dir, ratings=ratings or None)
        self._update_rating_buttons(seed)
        key = f"{os.path.basename(job_dir)}/{name}"
        run_dir = self.seed_runs[seed]
        emb = aesthetic.read_embedding(run_dir)
        if new is not None and emb is None:  # a sketch from before 3.4: its embedding is made first (seconds)
            self._embed_then_rate(run_dir, key, new)
            return True
        self._taste_learnt(aesthetic.set_rating(key, emb, new), new)
        return True

    def _embed_then_rate(self, run_dir: str, key: str, value: int):
        from PySide6.QtCore import QProcess

        from ..widgets.edit_bar import tool_command

        proc = QProcess(self)
        program, args = tool_command("--embed", run_dir)

        def done(*_):
            from ...engine import aesthetic

            if self._closing:  # (the window closes: the process was ended)
                return
            emb = aesthetic.read_embedding(run_dir)
            if emb is None:
                self.toast.emit(tr("ui.rate.failed"), "error")
                return
            self._taste_learnt(aesthetic.set_rating(key, emb, value), value)

        proc.finished.connect(done)
        proc.errorOccurred.connect(lambda e: done() if e == QProcess.FailedToStart else None)  # (else: finished)
        self._embed_proc = proc
        proc.start(program, args)

    def _taste_learnt(self, data: dict, value: int | None):
        from ...engine import aesthetic

        up, down = aesthetic.counts(data)
        if value is None:
            self.toast.emit(tr("ui.rate.removed"), "info")
        elif data.get("model"):
            self.toast.emit(tr("ui.rate.learnt", n=up + down), "success")
        elif up + down < aesthetic.MIN_RATINGS:
            self.toast.emit(tr("ui.rate.progress", n=aesthetic.MIN_RATINGS - up - down), "info")
        else:
            self.toast.emit(tr("ui.rate.need_both"), "info")

    # ------------------------------------------------------- saved steps and "Simplify"
    def _start_edit_bar(self) -> int | None:
        seed = self._editable_seed()
        if seed is None:
            return None
        for b in (self.eraser_btn, self.pen_btn):
            b.setChecked(False)
        return seed

    # ------------------------------------------------------------------ time-lapse
    LAPSE_SECONDS = 6.0  # all saved steps at 1×

    def toggle_timelapse(self) -> bool:
        """Play the saved steps of the shown sketch on the canvas (again: pause / go on); it ends on the result."""
        if self._lapse_timer.isActive():
            self._lapse_timer.stop()
            self._update_play_btn()
            return False
        seed = self._editable_seed()
        if seed is None:
            return False
        from .. import export

        if self._lapse["seed"] != seed or not self._lapse["frames"] or \
                self._lapse["index"] >= len(self._lapse["frames"]):
            frames = export.animation_frames(self.seed_runs[seed])
            if len(frames) < 2:
                self.toast.emit(tr("ui.edit_bar.no_steps"), "info")
                return False
            self._lapse.update(frames=frames, index=0, seed=seed)
        self._lapse_timer.start(self._lapse_interval())
        self._update_play_btn()
        return True

    def _lapse_interval(self) -> int:
        n = max(len(self._lapse["frames"]), 1)
        return max(20, int(1000 * self.LAPSE_SECONDS / n / self._lapse["speed"]))

    def set_timelapse_speed(self, speed: float):
        self._lapse["speed"] = float(speed)
        self.speed_actions.get(float(speed), self.speed_actions[1.0]).setChecked(True)
        if self._lapse_timer.isActive():
            self._lapse_timer.setInterval(self._lapse_interval())

    def _timelapse_step(self):
        lapse = self._lapse
        if lapse["seed"] != (self.selected_seed if self.selected_seed is not None else self.best_seed):
            self.stop_timelapse()  # (another sketch was chosen meanwhile)
            return
        if lapse["index"] >= len(lapse["frames"]):
            self.stop_timelapse()
            return
        try:
            with open(lapse["frames"][lapse["index"]], encoding="utf-8") as f:
                self.canvas.set_svg(f.read())
        except OSError:
            pass
        lapse["index"] += 1

    def stop_timelapse(self):
        """End the time-lapse: the canvas shows the sketch again."""
        was = self._lapse_timer.isActive() or self._lapse["index"] > 0
        self._lapse_timer.stop()
        self._lapse.update(frames=[], index=0, seed=None)
        if was:
            seed = self.selected_seed if self.selected_seed is not None else self.best_seed
            if seed is not None and seed in self.seed_svgs:
                self.canvas.set_svg(self._shown_svg(seed))
        self._update_play_btn()

    def _update_play_btn(self):
        playing = self._lapse_timer.isActive()
        self.play_btn.setIcon(icons.icon("pause" if playing else "play", theme.current().muted,
                                         active_color=theme.current().text))
        self.play_btn.setToolTip(tr("ui.timelapse.pause" if playing else "ui.timelapse.play"))

    def open_history(self) -> bool:
        """A slider over the saved steps of the shown sketch; one of them can become the result."""
        seed = self._start_edit_bar()
        if seed is None:
            return False
        from .. import export

        frames = export.animation_frames(self.seed_runs[seed], upto_best=False)
        if not self.edit_bar.open_history(frames, self.seed_svgs[seed]):
            self.toast.emit(tr("ui.edit_bar.no_steps"), "info")
            return False
        return True

    def _simplify_tip(self) -> None:
        """Once, after the first finished sketch: where "Simplify" is (it was easy to miss)."""
        st = app_settings()
        if st.get("simplify_tip_shown") or self._editable_seed() is None:
            return
        st.set("simplify_tip_shown", True)
        self.toast.emit(tr("ui.edit_bar.simplify_hint"), "info")

    def open_simplify(self) -> bool:
        """A slider that leaves out the least important strokes first (measured with CLIP the first time)."""
        seed = self._start_edit_bar()
        if seed is None:
            return False
        from ...engine import importance

        run_dir, svg = self.seed_runs[seed], self.seed_svgs[seed]
        values = importance.read(run_dir, svg)
        self.edit_bar.open_simplify(svg, values)
        if values is None:
            self._measure_importance(run_dir, svg)
        return True

    def _measure_importance(self, run_dir: str, svg: str):
        from PySide6.QtCore import QProcess

        if self._importance_proc is not None and self._importance_proc.state() != QProcess.NotRunning:
            self._importance_proc.kill()
        proc = QProcess(self)
        program, args = importance_command(run_dir)
        proc.finished.connect(lambda code, _status: self._importance_done(run_dir, svg, code))
        proc.errorOccurred.connect(lambda _e: self._importance_done(run_dir, svg, -1))
        self._importance_proc = proc
        proc.start(program, args)

    def _importance_done(self, run_dir: str, svg: str, code: int):
        from ...engine import importance

        if self.edit_bar.mode != "simplify" or self.edit_bar._svg != svg:
            return  # (the bar was closed or shows another sketch)
        values = importance.read(run_dir, svg)
        self.edit_bar.set_importance(values, "" if values is not None else tr("ui.edit_bar.exit_code", code=code))

    def _edit_bar_apply(self, svg: str):
        seed = self._editable_seed()
        if seed is None or svg == self.seed_svgs[seed]:
            self._edit_bar_closed()
            return
        self._edit_undo.setdefault(seed, []).append(self.seed_svgs[seed])
        self._edit_redo[seed] = []
        self._show_edited(seed, svg)
        self._save_edit(seed)
        self._update_edit_tools()
        self.toast.emit(tr("ui.edit_bar.taken"), "success")

    def _edit_bar_closed(self):
        seed = self._editable_seed()
        if seed is not None:
            self.canvas.set_svg(self.seed_svgs[seed])

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

