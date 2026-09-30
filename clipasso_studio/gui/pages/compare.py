"""Compare page: sketch the current image with several methods and pick the best one."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QProgressBar, QVBoxLayout, QWidget

from ... import settings_schema as schema
from ...engine import imaging, jobs
from .. import dialogs, icons, methods_ui, theme
from ..controller import JobController, QueuedJob
from ..i18n import i18n, tr
from ..widgets.canvas import SketchCanvas
from ..widgets.common import Card, ToggleSwitch, button, label
from .other_pages import _page_header, _scroll, job_method, scan_jobs


def _same_image(summary: dict, image: str) -> bool:
    target = summary.get("target", "")
    return bool(target) and os.path.normcase(os.path.abspath(target)) == os.path.normcase(os.path.abspath(image))


class CompareCard(Card):
    open_job = Signal(str)

    def __init__(self, method: str, parent=None):
        super().__init__(parent, margins=16, spacing=10)
        self.method = method
        self.job_dir = ""
        self.best_svg = ""
        head = QHBoxLayout()
        head.setSpacing(8)
        self.icon = QLabel()
        head.addWidget(self.icon)
        self.name = label(methods_ui.name(method), "h2")
        head.addWidget(self.name)
        head.addStretch(1)
        self.best_badge = label("", "badge-success")
        self.best_badge.setVisible(False)
        head.addWidget(self.best_badge)
        self.body.addLayout(head)
        self.tagline = label("", "faint", wrap=True)
        self.body.addWidget(self.tagline)
        self.canvas = SketchCanvas()
        self.canvas.setMinimumSize(220, 220)
        self.body.addWidget(self.canvas, 1)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setFixedHeight(6)
        self.bar.setTextVisible(False)
        self.bar.setVisible(False)
        self.body.addWidget(self.bar)
        stats = QHBoxLayout()
        stats.setSpacing(18)
        self.stat_values = {}
        for key in ("score", "time", "strokes"):
            col = QVBoxLayout()
            col.setSpacing(0)
            v = label("–", "stat")
            c = label("", "faint")
            col.addWidget(v)
            col.addWidget(c)
            stats.addLayout(col)
            self.stat_values[key] = (v, c)
        stats.addStretch(1)
        self.body.addLayout(stats)
        self.state = label("", "faint", wrap=True)
        self.body.addWidget(self.state)
        row = QHBoxLayout()
        self.open_btn = button("", "brush", "ghost")
        self.open_btn.clicked.connect(lambda: self.open_job.emit(self.job_dir))
        self.export_btn = button("", "file-down", "ghost")
        self.export_btn.clicked.connect(self._export)
        row.addWidget(self.open_btn)
        row.addWidget(self.export_btn)
        row.addStretch(1)
        self.body.addLayout(row)
        self.set_result(None, None)
        self.retranslate()

    def set_result(self, job_dir: str | None, summary: dict | None) -> None:
        self.job_dir = job_dir or ""
        self.best_svg = (summary or {}).get("best_svg", "")
        self.sketch = jobs.best_sketch(summary) if summary else ""  # touched up with the eraser, if it was
        svg = None
        if self.sketch and os.path.isfile(self.sketch):
            with open(self.sketch, encoding="utf-8") as f:
                svg = f.read()
        self.canvas.set_svg(svg)
        score_v, time_v, strokes_v = (self.stat_values[k][0] for k in ("score", "time", "strokes"))
        if summary:
            runs = summary.get("runs", [])
            scores = [r["clip_score"] for r in runs if r.get("clip_score") is not None]
            score = summary.get("clip_score") or (max(scores) if scores else None)
            score_v.setText(f"{score:.1f}" if score is not None else "–")
            secs = summary.get("seconds") or sum(r.get("seconds", 0) or 0 for r in runs)
            time_v.setText(imaging.eta_string(secs) if secs else "–")
            strokes_v.setText(str(schema.num_strokes({**summary.get("settings", {}), "method": self.method})))
        else:
            for v in (score_v, time_v, strokes_v):
                v.setText("–")
        self.open_btn.setEnabled(bool(self.job_dir))
        self.export_btn.setEnabled(bool(svg))

    def score(self) -> float | None:
        try:
            return float(self.stat_values["score"][0].text())
        except ValueError:
            return None

    def set_best(self, best: bool) -> None:
        self.best_badge.setVisible(best)

    def set_state(self, text: str, progress: float | None = None) -> None:
        self.state.setText(text)
        self.bar.setVisible(progress is not None)
        if progress is not None:
            self.bar.setValue(int(progress * 1000))

    def _export(self):
        if not self.best_svg:
            return
        run_dir = os.path.dirname(self.best_svg)
        runs = [d for d in os.listdir(self.job_dir) if os.path.isdir(os.path.join(self.job_dir, d))]
        base = os.path.basename(self.best_svg).replace("_best.svg", "")
        if base in runs:
            run_dir = os.path.join(self.job_dir, base)
        dlg = dialogs.ExportDialog("png", self.sketch or self.best_svg, run_dir, base, self)
        dlg.exec()

    def retranslate(self):
        p = theme.current()
        self.icon.setPixmap(icons.pixmap(methods_ui.ICONS[self.method], p.accent_hover, 22))
        self.tagline.setText(tr(f"method.{self.method}.tagline"))
        self.best_badge.setText("★ " + tr("ui.compare.best"))
        self.stat_values["score"][1].setText(tr("ui.stat.score"))
        self.stat_values["time"][1].setText(tr("ui.compare.time"))
        self.stat_values["strokes"][1].setText(tr("ui.compare.strokes"))
        self.open_btn.setText(tr("ui.compare.open"))
        self.export_btn.setText(tr("ui.compare.export"))
        self.canvas.placeholder = tr("ui.compare.placeholder")
        self.canvas.update()


class ComparePage(QWidget):
    open_job = Signal(str)
    toast = Signal(str, str)

    def __init__(self, controller: JobController, studio, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        self.controller = controller
        self.studio = studio
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)
        head = QHBoxLayout()
        lay, self.title, self.subtitle = _page_header("ui.compare.title", "ui.compare.subtitle")
        head.addLayout(lay, 1)
        root.addLayout(head)

        setup = Card(margins=16)
        row = QHBoxLayout()
        row.setSpacing(16)
        self.thumb = QLabel()
        self.thumb.setFixedSize(84, 84)
        self.thumb.setAlignment(Qt.AlignCenter)
        row.addWidget(self.thumb)
        col = QVBoxLayout()
        col.setSpacing(4)
        self.image_name = label("", "h3")
        self.image_hint = label("", "faint", wrap=True)
        col.addWidget(self.image_name)
        col.addWidget(self.image_hint)
        toggles = QHBoxLayout()
        toggles.setSpacing(14)
        self.method_toggles: dict[str, ToggleSwitch] = {}
        self.method_labels: dict[str, QLabel] = {}
        for m in schema.METHODS:
            sw = ToggleSwitch()
            sw.setChecked(m != "scenesketch")  # scenes only; takes much longer
            lbl = label(methods_ui.name(m), None)
            toggles.addWidget(sw)
            toggles.addWidget(lbl)
            toggles.addSpacing(6)
            self.method_toggles[m] = sw
            self.method_labels[m] = lbl
        toggles.addStretch(1)
        col.addLayout(toggles)
        use_row = QHBoxLayout()
        self.use_studio = ToggleSwitch()
        self.use_studio_label = label("", "muted")
        use_row.addWidget(self.use_studio)
        use_row.addWidget(self.use_studio_label)
        use_row.addStretch(1)
        col.addLayout(use_row)
        row.addLayout(col, 1)
        self.start_btn = button("", "play", "primary", "lg")
        self.start_btn.clicked.connect(self.start)
        row.addWidget(self.start_btn, 0, Qt.AlignVCenter)
        setup.body.addLayout(row)
        root.addWidget(setup)

        host = QWidget()
        grid = QHBoxLayout(host)
        grid.setContentsMargins(0, 0, 8, 0)
        grid.setSpacing(14)
        self.cards: dict[str, CompareCard] = {}
        for m in schema.METHODS:
            c = CompareCard(m)
            c.open_job.connect(self.open_job.emit)
            grid.addWidget(c, 1)
            self.cards[m] = c
        root.addWidget(_scroll(host), 1)
        self.verdict = label("", "muted", wrap=True)
        root.addWidget(self.verdict)

        controller.queue_changed.connect(self._schedule_refresh)
        controller.job_finished.connect(lambda _: self._schedule_refresh())
        controller.job_event.connect(self._on_event)
        i18n.language_changed.connect(lambda _: self.retranslate())
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(150)
        self._refresh_timer.timeout.connect(self.refresh)
        self.retranslate()

    # ------------------------------------------------------------------ run
    def _settings(self, method: str) -> dict:
        if self.use_studio.isChecked():
            s = self.studio.params.settings_for(method)
        else:
            s = schema.apply_preset(schema.default_settings(method), "standard")
            device = self.studio.params.settings().get("device", "auto")
            s["device"] = device
        return schema.normalize(s)

    def start(self):
        image = self.studio.image_path
        methods = [m for m, sw in self.method_toggles.items() if sw.isChecked()]
        if not image or not methods:
            return
        settings = {m: self._settings(m) for m in methods}
        missing = sorted({k for s in settings.values() for k in methods_ui.missing_models(s)})
        if missing and not (dialogs.ask_download_missing(self, missing)
                            and not any(methods_ui.missing_models(s) for s in settings.values())):
            return
        if "controlsketch" in methods and not methods_ui.has_cuda():
            res = QMessageBox.question(self, methods_ui.name("controlsketch"), tr("ui.compare.cpu_warning"))
            if res != QMessageBox.Yes:
                methods.remove("controlsketch")
        if "scenesketch" in methods and not self.use_studio.isChecked() and not methods_ui.has_cuda():
            res = QMessageBox.question(self, methods_ui.name("scenesketch"), tr("ui.compare.scene_cpu_warning"))
            if res == QMessageBox.Yes:
                settings["scenesketch"] = schema.normalize(schema.apply_preset(settings["scenesketch"], "fast"))
        # fastest first, so the first results arrive early
        order = sorted(methods, key=lambda m: ("swiftsketch", "clipasso", "controlsketch", "scenesketch").index(m))
        for m in order:
            self.controller.enqueue(image, settings[m], start=not self.controller.is_busy())
        self.toast.emit(tr("ui.compare.queued", n=len(order)), "success")
        self.refresh()

    # -------------------------------------------------------------- display
    def _schedule_refresh(self):
        if self.isVisible():
            self._refresh_timer.start()

    def _jobs_for_image(self, image: str) -> dict[str, QueuedJob]:
        out = {}
        for j in self.controller.jobs:
            if j.status in ("queued", "running", "paused") and os.path.abspath(j.target) == os.path.abspath(image):
                out.setdefault(schema.method_of(j.settings), j)
        return out

    def refresh(self):
        image = self.studio.image_path
        pm = QPixmap(image) if image else QPixmap()
        if not pm.isNull():
            self.thumb.setPixmap(pm.scaled(84, 84, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.image_name.setText(os.path.basename(image))
        latest: dict[str, tuple[str, dict]] = {}
        if image:
            for job_dir, summary in scan_jobs():
                if _same_image(summary, image):
                    latest.setdefault(job_method(summary), (job_dir, summary))
        active = self._jobs_for_image(image) if image else {}
        for m, card in self.cards.items():
            res = latest.get(m)
            card.set_result(*(res if res else (None, None)))
            job = active.get(m)
            if job is not None and job.status in ("running", "paused"):
                card.set_state(tr("ui.compare.running"), job.progress)
            elif job is not None:
                card.set_state(tr("ui.compare.queued_one"))
            elif res:
                card.set_state(tr("ui.compare.from", date=res[1].get("created", "")[:16]))
            else:
                card.set_state(tr("ui.compare.none"))
        scored = {m: c.score() for m, c in self.cards.items() if c.score() is not None}
        best = max(scored, key=scored.get) if len(scored) > 1 else None
        for m, c in self.cards.items():
            c.set_best(m == best)
        if best:
            self.verdict.setText(tr("ui.compare.verdict", method=methods_ui.name(best), score=f"{scored[best]:.1f}"))
        else:
            self.verdict.setText(tr("ui.compare.verdict_none"))
        self.start_btn.setEnabled(bool(image))

    def _on_event(self, job, kind, data):
        if kind != "iteration" or not self.isVisible():
            return
        if os.path.abspath(job.target) != os.path.abspath(self.studio.image_path or ""):
            return
        card = self.cards.get(schema.method_of(job.settings))
        if card is not None:
            card.set_state(tr("ui.compare.running"), job.progress)

    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        QTimer.singleShot(0, self.refresh)

    def retranslate(self):
        self.title.setText(tr("ui.compare.title"))
        self.subtitle.setText(tr("ui.compare.subtitle"))
        self.image_hint.setText(tr("ui.compare.image_hint"))
        self.use_studio_label.setText(tr("ui.compare.use_studio"))
        self.use_studio.setToolTip(tr("ui.compare.use_studio_tip"))
        self.start_btn.setText(tr("ui.compare.start"))
        for m, lbl in self.method_labels.items():
            lbl.setToolTip(tr(f"method.{m}.tagline"))
        for c in self.cards.values():
            c.retranslate()
