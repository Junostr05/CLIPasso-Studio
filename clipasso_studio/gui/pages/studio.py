"""Studio page: input, live canvas, parameters and results."""

from __future__ import annotations

import json
import math
import os
import sys

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication, QPixmap
from PySide6.QtWidgets import (QFileDialog, QFrame, QGridLayout, QHBoxLayout, QMenu, QMessageBox, QProgressBar,
                               QScrollArea, QSplitter, QVBoxLayout, QWidget)

from ... import paths
from ... import settings_schema as schema
from ...engine import imaging
from .. import dialogs, icons, theme
from ..app_settings import app_settings
from ..controller import JobController, QueuedJob
from ..i18n import i18n, tr
from ..widgets.canvas import IMAGE_FILTER, ImageDropZone, LossChart, SeedThumb, SketchCanvas
from ..widgets.common import Card, SegmentedControl, ToggleSwitch, button, label
from ..widgets.param_panel import ParamPanel

# rough seconds per iteration used for the time estimate before the first run
DEFAULT_SEC_PER_IT = {"cpu": 1.0, "cuda": 0.08}


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
        self.drop.clicked.connect(self.browse_image)
        self.input_card.body.addWidget(self.drop, 1)
        self.file_label = label("", "faint")
        self.file_label.setWordWrap(True)
        self.input_card.body.addWidget(self.file_label)
        row = QHBoxLayout()
        self.open_btn = button("", "folder-open")
        self.open_btn.clicked.connect(self.browse_image)
        self.samples_btn = button("", "images", "ghost")
        self.samples_menu = QMenu(self)
        self.samples_btn.setMenu(self.samples_menu)
        row.addWidget(self.open_btn)
        row.addWidget(self.samples_btn)
        row.addStretch(1)
        self.input_card.body.addLayout(row)
        # quick toggles mirrored from the parameter panel
        self.quick = {}
        for key in ("mask_object", "fix_scale"):
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
        splitter.addWidget(left_scroll)

        # ----------------------------------------------------------- center pane
        center = Card(margins=18, spacing=12)
        center.setMinimumWidth(420)
        top = QHBoxLayout()
        self.modes = SegmentedControl([(m, "") for m in SketchCanvas.MODES])
        self.modes.changed.connect(self._mode_changed)
        top.addWidget(self.modes)
        top.addStretch(1)
        self.stage_badge = label("", "badge")
        self.stage_badge.setVisible(False)
        top.addWidget(self.stage_badge)
        center.body.addLayout(top)
        self.canvas = SketchCanvas()
        center.body.addWidget(self.canvas, 1)

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
        last = s.get("last_params")
        if isinstance(last, dict):
            try:
                self.params.set_settings(last)
            except ValueError:
                pass
        self._sync_quick()
        self._build_samples_menu()
        last_img = s.get("last_image")
        if last_img and os.path.isfile(last_img):
            self.set_image(last_img)
        else:
            self.set_image(str(paths.resource("samples", "camel.png")))
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

    def browse_image(self):
        start = os.path.dirname(self.image_path) if self.image_path else os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(self, tr("ui.choose_image"), start, IMAGE_FILTER)
        if path:
            self.set_image(path)

    def set_image(self, path: str):
        if not path or not os.path.isfile(path):
            return
        self.image_path = path
        self.drop.set_image(path)
        pm = QPixmap(path)
        self.file_label.setText(f"{os.path.basename(path)}  ·  {pm.width()}×{pm.height()} px")
        app_settings().set("last_image", path)
        if not self.controller.is_busy():
            self._reset_view()
            self.canvas.set_input(self._square_input(pm))
        if pm.width() != pm.height() and not self.params.settings()["fix_scale"]:
            self.toast.emit(tr("ui.hint_fix_scale"), "info")
        self._update_buttons()

    @staticmethod
    def _square_input(pm: QPixmap) -> QPixmap:
        side = min(pm.width(), pm.height())
        if side <= 0:
            return pm
        return pm.copy((pm.width() - side) // 2, (pm.height() - side) // 2, side, side)

    def _quick_toggled(self, key, value):
        s = self.params.settings()
        if s[key] != value:
            self.params.fields[key].set_value(value, emit=True)

    def _sync_quick(self):
        s = self.params.settings()
        for key, (_, sw) in self.quick.items():
            if sw.isChecked() != bool(s[key]):
                sw.blockSignals(True)
                sw.setChecked(bool(s[key]))
                sw.blockSignals(False)

    def _settings_changed(self, settings: dict):
        self._sync_quick()
        app_settings().set("last_params", settings)
        self._update_estimate()

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
        self.canvas.clear()
        self.chart.reset(1)
        for t in self.thumbs.values():
            t.setParent(None)
        self.thumbs.clear()
        self.seed_svgs.clear()
        self.seed_attn.clear()
        self.seed_runs.clear()
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

    def _ensure_thumbs(self, seeds: list[int]):
        for seed in seeds:
            if seed in self.thumbs:
                continue
            t = SeedThumb(seed)
            t.clicked.connect(self.select_seed)
            self.thumb_row.insertWidget(self.thumb_row.count() - 1, t)
            self.thumbs[seed] = t
        self.thumb_area.setVisible(len(self.thumbs) > 1)
        if self.selected_seed is None and seeds:
            self.select_seed(seeds[0])

    def select_seed(self, seed: int):
        if seed != self.selected_seed and self.controller.is_busy():
            self.chart.reset(self.chart.total)  # the chart shows the selected sketch only
        self.selected_seed = seed
        for s, t in self.thumbs.items():
            t.set_selected(s == seed)
        self.canvas.set_svg(self.seed_svgs.get(seed))
        self.canvas.set_attention(self.seed_attn.get(seed))
        self._update_buttons()

    def _job_started(self, job: QueuedJob):
        self.view_job = job
        self._reset_view()
        self.view_dir = job.job_dir
        if job.target != self.image_path:
            self.image_path = job.target
            self.drop.set_image(job.target)
        self.canvas.set_input(self._square_input(QPixmap(job.target)))
        self.chart.reset(job.settings["num_iter"])
        self._ensure_thumbs(job.seeds)
        self._set_status("ui.status.starting")
        self._update_buttons()

    def _job_event(self, job: QueuedJob, kind: str, data: dict):
        if job is not self.view_job:
            return
        seed = data.get("seed")
        if kind == "job_start":
            self.device_badge.setText(self._device_text(data.get("device", "")))
        elif kind == "stage":
            n = job.seeds.index(seed) + 1 if seed in job.seeds else 1
            self._set_status(f"ui.status.{data['name']}", n=n, total=len(job.seeds))
        elif kind == "input":
            self.canvas.set_input(_pixmap_from_png(data["png"]))
            self.canvas.set_mask(_pixmap_from_png(data["mask_png"]))
        elif kind == "attention":
            self.seed_attn[seed] = _pixmap_from_png(data["png"])
            if seed == self.selected_seed:
                self.canvas.set_attention(self.seed_attn[seed])
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
            if seed == self.selected_seed:
                self.canvas.set_svg(data["svg"])
        elif kind == "seed_done":
            self.seed_svgs[seed] = data["svg"]
            self.seed_runs[seed] = data["run_dir"]
            if seed in self.thumbs:
                self.thumbs[seed].set_svg(data["svg"])
                self.thumbs[seed].set_caption(f"{data['best_loss']:.3f}")
            if seed == self.selected_seed:
                self.canvas.set_svg(data["svg"])
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
            if self.best_seed is not None:
                self.select_seed(self.best_seed)
        elif kind == "warning":
            key = f"ui.warn.{data.get('code', '')}"
            self.toast.emit(tr(key) if i18n.has(key) else data.get("message", ""), "warning")
        elif kind == "log":
            self.toast.emit(data.get("message", ""), "info")
        elif kind == "error":
            self._show_error(data)
        self._update_buttons()

    def _on_iteration(self, job, data):
        it, total = data["it"] + 1, data["total"]
        self.progress.setValue(int(job.progress * 1000))
        self.stat_iter.value.setText(f"{it}/{total}")
        self.stat_loss.value.setText(f"{data['loss']:.4f}")
        best = data["best_loss"]
        self.stat_best.value.setText(f"{best:.4f}" if best < 99 else "–")
        self.stat_time.value.setText(imaging.eta_string(data["elapsed"]))
        remaining_seeds = sum(1 for s in job.seeds if job.seed_progress.get(s, 0) < 1.0) - 1
        eta = data["eta"]
        if not job.settings.get("multiprocess") and remaining_seeds > 0:
            eta += remaining_seeds * data["elapsed"] / max(it, 1) * total
        self.stat_eta.value.setText(imaging.eta_string(eta))
        self.chart.total = total
        self.chart.add(it, data["loss"], data.get("loss_eval"))
        if it >= 5 and data["elapsed"] > 0:
            key = "cuda" if job.device.startswith("cuda") else "cpu"
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
            self._set_status("ui.status.optimizing", n=n, total=len(job.seeds))

    def _job_finished(self, job: QueuedJob):
        if job is not self.view_job:
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
        """Display a finished job from the gallery."""
        try:
            with open(os.path.join(job_dir, "job.json"), encoding="utf-8") as f:
                summary = json.load(f)
        except (OSError, ValueError):
            return
        if self.controller.is_busy():
            self.view_job = None
        self._reset_view()
        self.view_dir = job_dir
        target = summary.get("target", "")
        src = next((os.path.join(job_dir, f) for f in os.listdir(job_dir) if f.startswith("source.")), target)
        if os.path.isfile(src):
            self.image_path = target if os.path.isfile(target) else src
            self.drop.set_image(src)
            self.canvas.set_input(self._square_input(QPixmap(src)))
        runs = summary.get("runs", [])
        self._ensure_thumbs([r["seed"] for r in runs])
        for r in runs:
            seed = r["seed"]
            self.seed_runs[seed] = r["run_dir"]
            try:
                with open(r["best_svg"], encoding="utf-8") as f:
                    self.seed_svgs[seed] = f.read()
            except OSError:
                continue
            self.thumbs[seed].set_svg(self.seed_svgs[seed])
            self.thumbs[seed].set_caption(f"{r['best_loss']:.3f}")
            attn = os.path.join(r["run_dir"], "attention_map.png")
            if os.path.isfile(attn):
                self.seed_attn[seed] = QPixmap(attn)
            mask = os.path.join(r["run_dir"], "mask.png")
            if os.path.isfile(mask):
                self.canvas.set_mask(QPixmap(mask))
            if r["run_name"] == summary.get("best_run"):
                self.best_seed = seed
        for s, t in self.thumbs.items():
            t.set_best(s == self.best_seed)
            if s == self.best_seed:
                t.set_caption(f"★ {t.caption.text()}")
        if self.best_seed is not None:
            self.select_seed(self.best_seed)
        if isinstance(summary.get("settings"), dict):
            self.params.set_settings(summary["settings"])
        self.progress.setValue(1000)
        self._fill_stats_from_summary(summary)
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
        svg = os.path.join(run_dir, "best_iter.svg")
        return (svg, run_dir) if os.path.isfile(svg) else None

    def export(self, fmt: str):
        sel = self._selected_run()
        if not sel:
            return
        svg, run_dir = sel
        name = os.path.basename(run_dir)
        dlg = dialogs.ExportDialog(fmt, svg, run_dir, name, self)
        if dlg.exec():
            self.toast.emit(tr("ui.exported", path=getattr(dlg, "saved_path", "")), "success")

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
        for n in (4, 8, 16, 32):
            s = dict(base)
            s["num_paths"] = n
            s["path_svg"] = "none"
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
            self.params.set_settings({k: v for k, v in data.items() if k in schema.PARAMS_BY_KEY})
            self.params.settings_changed.emit(self.params.settings())
            self.toast.emit(tr("ui.preset_loaded"), "success")
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, tr("ui.error"), str(exc))

    def export_preset(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("ui.export"), "clipasso-preset.json", "JSON (*.json)")
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
        busy = key in ("ui.status.optimizing", "ui.status.loading", "ui.status.init", "ui.status.starting")
        self.stage_badge.setVisible(busy)
        if busy:
            self.stage_badge.setText(tr("ui.live"))

    def _update_estimate(self):
        s = self.params.settings()
        rates = app_settings().get("sec_per_it", {}) or {}
        dev = "cuda" if s["device"] == "cuda" or (s["device"] == "auto" and self.device_badge.text().startswith(
            "GPU")) else "cpu"
        per_it = rates.get(dev, DEFAULT_SEC_PER_IT[dev])
        per_it *= (1 + s["num_aug_clip"]) / 5
        if s["clip_model_name"] in ("RN50x4", "RN50x16", "ViT-B/16"):
            per_it *= 2
        sketches = s["num_sketches"]
        if s["multiprocess"] and sketches > 1:
            sketches = math.ceil(sketches / min(sketches, 4)) * 1.6
        secs = per_it * s["num_iter"] * sketches + 15 * s["num_sketches"]
        self.estimate.setText(tr("ui.estimate", time=imaging.eta_string(secs)))

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
        for b in (self.reuse_btn,):
            b.setEnabled(has_result)
        self.folder_btn.setEnabled(bool(self.view_dir) or bool(app_settings().get("output_dir")))
        self.result_hint.setText(tr("ui.result_hint_ready") if has_result else tr("ui.result_hint_empty"))

    def retranslate(self):
        self.title.setText(tr("ui.studio.title"))
        self.subtitle.setText(tr("ui.studio.subtitle"))
        if not self.device_badge.text():
            self.device_badge.setText(tr("ui.device_unknown"))
        self.input_title.setText(tr("ui.input"))
        self.drop.title = tr("ui.drop_title")
        self.drop.subtitle = tr("ui.drop_subtitle")
        self.drop.update()
        self.open_btn.setText(tr("ui.open"))
        self.samples_btn.setText(tr("ui.samples"))
        for key, (lbl, _) in self.quick.items():
            lbl.setText(tr(f"param.{key}.label"))
            lbl.setToolTip(tr(f"param.{key}.help"))
        self.result_title.setText(tr("ui.result"))
        self.folder_btn.setText(tr("ui.open_folder"))
        self.reuse_btn.setText(tr("ui.use_as_initial"))
        self.reuse_btn.setToolTip(tr("ui.use_as_initial_tip"))
        self.series_btn.setText(tr("ui.abstraction_series"))
        self.series_btn.setToolTip(tr("ui.abstraction_series_tip"))
        for m in SketchCanvas.MODES:
            self.modes.set_text(m, tr(f"ui.mode.{m}"))
        self.canvas.placeholder = tr("ui.canvas_placeholder")
        self.canvas.update()
        self.stat_iter.caption.setText(tr("ui.stat.iteration"))
        self.stat_loss.caption.setText(tr("ui.stat.loss"))
        self.stat_best.caption.setText(tr("ui.stat.best"))
        self.stat_time.caption.setText(tr("ui.stat.elapsed"))
        self.stat_eta.caption.setText(tr("ui.stat.eta"))
        self.cancel_btn.setText(tr("ui.cancel"))
        self.queue_btn.setText(tr("ui.add_to_queue"))
        key, fmt = self._status_key
        self.status.setText(tr(key, **fmt))
        self._update_estimate()
        self._update_buttons()

    def estimate_holder(self) -> QWidget:
        self.estimate = label("", "faint")
        self.estimate.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return self.estimate

    def _mode_changed(self, mode: str):
        self.canvas.set_mode(mode)

    def sizeHint(self):  # noqa: N802
        return QSize(1400, 860)

