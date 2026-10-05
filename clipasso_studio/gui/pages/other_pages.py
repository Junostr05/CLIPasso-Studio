"""Queue, gallery, models, settings and about pages."""

from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path

from PySide6.QtCore import QFile, QStandardPaths, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox, QProgressBar, QScrollArea, QVBoxLayout, QWidget)

from ... import APP_NAME, __version__, paths
from ... import settings_schema as schema
from ...engine import imaging, jobs, model_store
from .. import crash, dialogs, icons, methods_ui, power, shortcuts, theme, thumbs
from ..drop import dropped_images, has_images, image_files  # noqa: F401 (image_files re-exported)
from ..app_settings import app_settings
from ..controller import JobController, QueuedJob
from ..i18n import AUTO, LANGUAGES, i18n, system_language, tr
from ..widgets.canvas import IMAGE_FILTER
from ..widgets.common import Card, SegmentedControl, ToggleSwitch, button, label, tool_button

try:
    from .. import _build_info  # generated at build time
    EDITION = _build_info.EDITION
except ImportError:  # running from source
    EDITION = "dev"


def _page_header(title_key: str, subtitle_key: str):
    lay = QVBoxLayout()
    lay.setSpacing(2)
    t = label(tr(title_key), "title")
    s = label(tr(subtitle_key), "muted", wrap=True)
    lay.addWidget(t)
    lay.addWidget(s)
    return lay, t, s


def _scroll(widget: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(widget)
    area.setFrameShape(QFrame.NoFrame)
    return area


def _status_role(status: str) -> str:
    return {"done": "badge-success", "failed": "badge-warning", "cancelled": "badge-warning"}.get(status, "badge")


def scan_jobs(unfinished: bool = False) -> list[tuple[str, dict]]:
    """Jobs in the output folder (job folder, summary), newest first: finished ones (job.json), and with
    ``unfinished`` also interrupted ones that have no job.json yet."""
    root = app_settings().get("output_dir")
    items = []
    if not root or not os.path.isdir(root):
        return items
    for name in os.listdir(root):
        d = os.path.join(root, name)
        if not os.path.isfile(os.path.join(d, "job.json")) and not (
                unfinished and os.path.isfile(os.path.join(d, jobs.STATE_FILE))):
            continue
        summary = jobs.job_summary(d)
        if summary is not None:
            items.append((d, summary))
    items.sort(key=lambda t: t[1].get("created", ""), reverse=True)
    return items




def job_method(summary: dict) -> str:
    return summary.get("method") or schema.method_of(summary.get("settings"))


def method_badge(method: str) -> QLabel:
    b = label(methods_ui.name(method), "badge")
    b.setToolTip(tr(f"method.{method}.tagline"))
    return b


# ====================================================================== queue
QUEUE_MIME = "application/x-clipasso-queue-job"


class QueueRow(Card):
    """One job of the queue: preview, name, progress, status and its controls. Waiting jobs can be
    dragged to another place; a click shows its details."""

    selected = Signal(int)

    def __init__(self, job: QueuedJob, controller: JobController, parent=None):
        super().__init__(parent, flat=True, margins=12, spacing=8)
        self.job = job
        self.controller = controller
        self._press = None
        row = QHBoxLayout()
        row.setSpacing(12)
        self.grip = QLabel()
        self.grip.setFixedWidth(16)
        row.addWidget(self.grip)
        thumb = QLabel()
        pm = thumbs.thumbnail(job.target, 56)  # decoded small and kept (rows are rebuilt often)
        if not pm.isNull():
            thumb.setPixmap(pm)
        thumb.setFixedSize(60, 60)
        thumb.setAlignment(Qt.AlignCenter)
        row.addWidget(thumb)
        info = QVBoxLayout()
        info.setSpacing(3)
        self.name = label(job.name, "h3")
        self.details = label("", "faint")
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name_row.addWidget(self.name)
        self.method = method_badge(schema.method_of(job.settings))
        name_row.addWidget(self.method)
        name_row.addStretch(1)
        info.addLayout(name_row)
        info.addWidget(self.details)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setFixedHeight(6)
        self.bar.setTextVisible(False)
        info.addWidget(self.bar)
        row.addLayout(info, 1)
        self.badge = label("", "badge")
        row.addWidget(self.badge, 0, Qt.AlignVCenter)
        self.pause = tool_button("pause", tr("ui.pause"))
        self.pause.clicked.connect(self._pause)
        self.cancel = tool_button("square", tr("ui.queue.cancel"))
        self.cancel.clicked.connect(self._cancel)
        self.retry = tool_button("rotate-ccw", tr("ui.queue.retry"))
        self.retry.clicked.connect(lambda: controller.retry(job.id))
        self.up = tool_button("chevron-up", tr("ui.queue.up"))
        self.up.clicked.connect(lambda: controller.move(job.id, -1))
        self.down = tool_button("chevron-down", tr("ui.queue.down"))
        self.down.clicked.connect(lambda: controller.move(job.id, 1))
        self.folder = tool_button("folder-open", tr("ui.open_folder"))
        self.folder.clicked.connect(self._open)
        self.remove = tool_button("trash-2", tr("ui.queue.remove"))
        self.remove.clicked.connect(lambda: controller.remove(job.id))
        for b in (self.pause, self.cancel, self.retry, self.up, self.down, self.folder, self.remove):
            row.addWidget(b)
        self.body.addLayout(row)
        self.setCursor(Qt.PointingHandCursor)
        self.refresh()

    def _open(self):
        if self.job.job_dir and os.path.isdir(self.job.job_dir):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.job.job_dir))

    def _pause(self):
        if self.job is self.controller.current:
            if self.job.status == "paused":
                self.controller.resume()
            else:
                self.controller.pause()

    def _cancel(self):
        if self.job is self.controller.current and QMessageBox.question(
                self, tr("ui.cancel_run"), tr("ui.cancel_run_question")) == QMessageBox.Yes:
            self.controller.cancel()

    def set_selected(self, on: bool):
        color = theme.current().accent if on else theme.current().border
        self.setStyleSheet(f"QFrame#CardFlat {{ border: {2 if on else 1}px solid {color}; }}")

    def refresh(self):
        j = self.job
        s = j.settings
        details = tr("ui.queue.details", strokes=schema.num_strokes(s), iters=methods_ui.iterations(s),
                     sketches=s["num_sketches"])
        if j.resume_dir and j.status == "queued":
            details += "  ·  " + tr("ui.queue.continues")
        self.details.setText(details)
        self.bar.setValue(int(j.progress * 1000) if j.status != "done" else 1000)
        self.badge.setText(tr(f"ui.jobstatus.{j.status}"))
        self.badge.setProperty("role", _status_role(j.status))
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)
        queued = j.status == "queued"
        live = j.status in ("running", "paused")
        # the grip only for waiting jobs (its place stays, so all rows line up)
        self.grip.setPixmap(icons.pixmap("grip-vertical", theme.current().faint, 16) if queued else QPixmap())
        self.up.setVisible(queued)
        self.down.setVisible(queued)
        self.pause.setVisible(live)
        self.cancel.setVisible(live)
        self.retry.setVisible(j.status in ("failed", "cancelled"))
        p = theme.current()
        self.pause.setIcon(icons.icon("play" if j.status == "paused" else "pause", p.muted, active_color=p.text))
        self.pause.setToolTip(tr("ui.resume") if j.status == "paused" else tr("ui.pause"))
        self.remove.setEnabled(not live)
        self.folder.setEnabled(bool(j.job_dir))
        self.details.setToolTip(j.message if j.message and j.status == "failed" else "")

    # drag a waiting job to another place; a click selects it
    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.LeftButton:
            self._press = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):  # noqa: N802
        if self._press is not None and self.job.status == "queued" and \
                (e.position().toPoint() - self._press).manhattanLength() >= QApplication.startDragDistance():
            self._press = None
            from PySide6.QtCore import QMimeData
            from PySide6.QtGui import QDrag

            drag = QDrag(self)
            data = QMimeData()
            data.setData(QUEUE_MIME, str(self.job.id).encode("ascii"))
            drag.setMimeData(data)
            drag.setPixmap(self.grab().scaledToWidth(min(self.width(), 420), Qt.SmoothTransformation))
            drag.exec(Qt.MoveAction)
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):  # noqa: N802
        if self._press is not None and e.button() == Qt.LeftButton:
            self.selected.emit(self.job.id)
        self._press = None
        super().mouseReleaseEvent(e)


class QueueDetails(Card):
    """The selected job: its settings that differ from the defaults, and what can be done with it."""

    load = Signal(int)  # load the job's image and settings into the studio
    replace = Signal(int)  # give the job the studio's current settings

    def __init__(self, parent=None):
        super().__init__(parent, margins=16, spacing=10)
        self.setFixedWidth(320)
        self.job: QueuedJob | None = None
        self.title = label("", "h2", wrap=True)
        self.status = label("", "muted", wrap=True)
        self.message = label("", "faint", wrap=True)
        self.heading = label("", "h3")
        self.changes = label("", "muted", wrap=True)
        self.changes.setTextFormat(Qt.PlainText)
        self.load_btn = button("", "brush", "primary", size="sm")
        self.load_btn.clicked.connect(lambda: self.job and self.load.emit(self.job.id))
        self.replace_btn = button("", "refresh-cw", "ghost", size="sm")
        self.replace_btn.clicked.connect(lambda: self.job and self.replace.emit(self.job.id))
        for w in (self.title, self.status, self.message, self.heading, self.changes, self.load_btn,
                  self.replace_btn):
            self.body.addWidget(w)
        self.body.addStretch(1)

    def show_job(self, job: QueuedJob | None):
        from ..widgets.param_panel import param_text_key

        self.job = job
        self.setVisible(job is not None)
        if job is None:
            return
        s = job.settings
        method = schema.method_of(s)
        self.title.setText(job.name)
        self.status.setText(f"{methods_ui.name(method)} · {tr(f'ui.jobstatus.{job.status}')}")
        self.message.setText(job.message if job.status == "failed" else "")
        self.message.setVisible(bool(self.message.text()))
        defaults = schema.default_settings(method)
        lines = []
        for key in schema.changed_keys(s):
            name = tr(param_text_key(method, key, "label"))
            value, default = s[key], defaults[key]
            if isinstance(value, bool):
                value, default = tr("ui.on") if value else tr("ui.off"), tr("ui.on") if default else tr("ui.off")
            lines.append(f"{name}: {value}  ({tr('ui.queue.default')} {default})")
        self.heading.setText(tr("ui.queue.changed_settings"))
        self.changes.setText("\n".join(lines) if lines else tr("ui.queue.all_defaults"))
        self.load_btn.setText(tr("ui.queue.load_in_studio"))
        self.replace_btn.setText(tr("ui.queue.replace_settings"))
        self.replace_btn.setToolTip(tr("ui.queue.replace_settings_tip"))
        self.replace_btn.setVisible(job.status == "queued" and not job.resume_dir)


class QueuePage(QWidget):
    open_in_studio = Signal(str)
    load_in_studio = Signal(str, dict)  # (image, settings) of a queued job
    toast = Signal(str, str)

    def __init__(self, controller: JobController, settings_provider, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)  # images and folders dropped onto the queue are added
        self.setObjectName("Page")
        self.controller = controller
        self.settings_provider = settings_provider
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)
        head = QHBoxLayout()
        lay, self.title, self.subtitle = _page_header("ui.queue.title", "ui.queue.subtitle")
        head.addLayout(lay, 1)
        self.add_btn = button("", "plus", "primary")
        self.add_btn.clicked.connect(self._add_images)
        self.folder_btn = button("", "folder-open")
        self.folder_btn.clicked.connect(self._add_folder)
        self.export_btn = button("", "file-down", "ghost")
        self.export_btn.clicked.connect(self._export_all)
        self.clear_btn = button("", "trash-2", "ghost")
        self.clear_btn.clicked.connect(controller.clear_finished)
        self.run_btn = button("", "play")
        self.run_btn.clicked.connect(lambda: controller.start_next())
        head.addWidget(self.clear_btn, 0, Qt.AlignBottom)
        head.addWidget(self.export_btn, 0, Qt.AlignBottom)
        head.addWidget(self.run_btn, 0, Qt.AlignBottom)
        head.addWidget(self.folder_btn, 0, Qt.AlignBottom)
        head.addWidget(self.add_btn, 0, Qt.AlignBottom)
        root.addLayout(head)
        opts = QHBoxLayout()
        self.auto_label = label("", "muted")
        self.auto = ToggleSwitch()
        self.auto.setChecked(True)
        self.auto.toggled.connect(lambda v: setattr(controller, "auto_start", v))
        opts.addWidget(self.auto)
        opts.addWidget(self.auto_label)
        opts.addStretch(1)
        self.total = label("", "muted")  # how long the whole queue still takes
        opts.addWidget(self.total)
        opts.addSpacing(16)
        # what the PC does when the last job is done (this session only – reset after it ran)
        self.done_label = label("", "muted")
        self.done_combo = QComboBox()
        for key in power.ACTIONS:
            self.done_combo.addItem("", key)
        self.done_combo.currentIndexChanged.connect(self._done_changed)
        self.ran_since_choice = False
        controller.job_started.connect(lambda _: setattr(self, "ran_since_choice", True))
        opts.addWidget(self.done_label)
        opts.addWidget(self.done_combo)
        self.done_label.setVisible(power.available())
        self.done_combo.setVisible(power.available())
        root.addLayout(opts)
        host = QWidget()
        host.setAcceptDrops(True)
        self.list_host = host
        self.list_lay = QVBoxLayout(host)
        self.list_lay.setContentsMargins(0, 0, 8, 0)
        self.list_lay.setSpacing(8)
        self.list_lay.addStretch(1)
        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(_scroll(host), 1)
        self.detail = QueueDetails()
        self.detail.load.connect(self._load_in_studio)
        self.detail.replace.connect(self._replace_settings)
        self.detail.setVisible(False)
        body.addWidget(self.detail)
        root.addLayout(body, 1)
        self.selected_id: int | None = None
        self._eta_timer = QTimer(self, interval=2000)  # the remaining time of the whole queue
        self._eta_timer.timeout.connect(self._update_total)
        self._eta_timer.start()
        self.empty = label("", "muted")
        self.empty.setAlignment(Qt.AlignCenter)
        root.addWidget(self.empty)
        self.rows: dict[int, QueueRow] = {}
        controller.queue_changed.connect(self.rebuild)
        controller.job_event.connect(self._on_event)
        i18n.language_changed.connect(lambda _: self.retranslate())
        self.retranslate()

    def _add_images(self):
        paths_, _ = QFileDialog.getOpenFileNames(self, tr("ui.choose_image"), os.path.expanduser("~"), IMAGE_FILTER)
        self.controller.enqueue_many(paths_, self.settings_provider(), start=not self.controller.is_busy())

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, tr("ui.queue.add_folder"), os.path.expanduser("~"))
        if not folder:
            return
        has_sub = any(e.is_dir() for e in os.scandir(folder))
        recursive = has_sub and QMessageBox.question(
            self, tr("ui.queue.add_folder"), tr("ui.queue.subfolders_q")) == QMessageBox.Yes
        n = self.add_folder(folder, recursive)
        if n == 0:
            QMessageBox.information(self, tr("ui.queue.add_folder"), tr("ui.queue.folder_empty"))

    def done_action(self) -> str:
        return self.done_combo.currentData() or "nothing"

    def set_done_action(self, action: str) -> None:
        self.done_combo.setCurrentIndex(max(self.done_combo.findData(action), 0))

    def _done_changed(self):
        # a job that is already running counts: its end is "the queue is done"
        self.ran_since_choice = self.controller.is_busy()

    def add_paths(self, paths: list[str]) -> int:
        """Queue images (dropped files / folders) with the current settings; returns their number."""
        self.controller.enqueue_many(list(paths), self.settings_provider(), start=not self.controller.is_busy())
        if paths:
            self.toast.emit(tr("ui.queue.added", n=len(paths)), "success")
        return len(paths)

    def dragEnterEvent(self, e):  # noqa: N802
        if has_images(e.mimeData()) or e.mimeData().hasFormat(QUEUE_MIME):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):  # noqa: N802
        if e.mimeData().hasFormat(QUEUE_MIME):
            e.acceptProposedAction()

    def drop_index(self, y: int) -> int:
        """Queue position for a job dropped at height ``y`` (in the list's coordinates)."""
        for i, job in enumerate(self.controller.jobs):
            row = self.rows.get(job.id)
            if row is not None and y < row.y() + row.height() / 2:
                return i
        return len(self.controller.jobs)

    def dropEvent(self, e):  # noqa: N802
        if e.mimeData().hasFormat(QUEUE_MIME):  # a waiting job moved to another place
            job_id = int(bytes(e.mimeData().data(QUEUE_MIME)).decode("ascii"))
            y = self.list_host.mapFrom(self, e.position().toPoint()).y()
            index = self.drop_index(y)
            old = next((i for i, j in enumerate(self.controller.jobs) if j.id == job_id), None)
            if old is not None and index > old:
                index -= 1
            self.controller.move_to(job_id, index)
            e.acceptProposedAction()
            return
        paths = dropped_images(e.mimeData())
        if paths:
            e.acceptProposedAction()
            self.add_paths(paths)
        else:
            self.toast.emit(tr("ui.queue.folder_empty"), "info")

    def add_folder(self, folder: str, recursive: bool = False) -> int:
        """Queue every image of a folder with the current settings (result folders of the app are
        skipped). Returns the number of images."""
        images = image_files(folder, recursive)
        self.controller.enqueue_many(images, self.settings_provider(), start=not self.controller.is_busy())
        return len(images)

    def finished_items(self) -> list[tuple[str, dict]]:
        items = []
        for j in self.controller.jobs:
            if j.status in ("done", "cancelled") and j.job_dir:
                summary = jobs.job_summary(j.job_dir)
                if summary and jobs.best_sketch(summary):
                    items.append((j.job_dir, summary))
        return items

    def _export_all(self):
        dialogs.export_many(self, self.finished_items())

    def rebuild(self):
        """Rows for the jobs of the queue, in its order – existing rows are kept (only new jobs get a row)."""
        ids = [job.id for job in self.controller.jobs]
        for job_id in [k for k in self.rows if k not in ids]:
            self.rows.pop(job_id).setParent(None)
        for i, job in enumerate(self.controller.jobs):
            row = self.rows.get(job.id)
            if row is None:
                row = self.rows[job.id] = QueueRow(job, self.controller)
                row.selected.connect(self.select_job)
            if self.list_lay.indexOf(row) != i:
                self.list_lay.insertWidget(i, row)
            row.refresh()
        if self.selected_id not in self.rows:
            self.selected_id = None
        self.select_job(self.selected_id)
        self._update_total()
        self.empty.setVisible(not self.controller.jobs)
        self.run_btn.setEnabled(bool(self.controller.pending()) and not self.controller.is_busy())
        self.export_btn.setEnabled(any(j.status in ("done", "cancelled") and j.job_dir for j in self.controller.jobs))

    def _on_event(self, job, kind, data):
        if kind in ("iteration", "seed_done", "job_done") and job.id in self.rows:
            self.rows[job.id].refresh()

    def select_job(self, job_id: int | None):
        """Show the details of a job (None: none)."""
        if job_id is not None and job_id == self.selected_id and self.detail.isVisible() and \
                self.sender() is not None and isinstance(self.sender(), QueueRow):
            job_id = None  # a second click closes the details
        self.selected_id = job_id
        for jid, row in self.rows.items():
            row.set_selected(jid == job_id)
        self.detail.show_job(next((j for j in self.controller.jobs if j.id == job_id), None))

    def _load_in_studio(self, job_id: int):
        job = next((j for j in self.controller.jobs if j.id == job_id), None)
        if job is not None:
            self.load_in_studio.emit(job.target, dict(job.settings))

    def _replace_settings(self, job_id: int):
        if self.controller.replace_settings(job_id, self.settings_provider()):
            self.toast.emit(tr("ui.queue.replaced"), "success")

    def _update_total(self):
        busy = any(j.status in ("queued", "running", "paused") for j in self.controller.jobs)
        self.total.setVisible(busy)
        if busy:
            self.total.setText(tr("ui.queue.total", time=imaging.eta_string(self.controller.remaining_seconds())))

    def retranslate(self):
        self.title.setText(tr("ui.queue.title"))
        self.subtitle.setText(tr("ui.queue.subtitle"))
        self.add_btn.setText(tr("ui.queue.add"))
        self.folder_btn.setText(tr("ui.queue.add_folder"))
        self.folder_btn.setToolTip(tr("ui.queue.add_folder_tip"))
        self.export_btn.setText(tr("ui.batch.export_all"))
        self.export_btn.setToolTip(tr("ui.batch.export_all_tip"))
        self.clear_btn.setText(tr("ui.queue.clear"))
        self.run_btn.setText(tr("ui.queue.run"))
        self.auto_label.setText(tr("ui.queue.auto"))
        self.done_label.setText(tr("ui.queue.when_done"))
        for i, key in enumerate(power.ACTIONS):
            self.done_combo.setItemText(i, tr(f"ui.queue.done_{key}"))
        self.done_combo.setToolTip(tr("ui.queue.when_done_tip"))
        self.empty.setText(tr("ui.queue.empty"))
        self.rebuild()


# ==================================================================== gallery
def move_to_trash(path: str) -> bool:
    """Move a file or folder to the recycle bin; False when the system does not allow it."""
    try:
        res = QFile.moveToTrash(path)
    except Exception:
        return False
    ok = res[0] if isinstance(res, tuple) else bool(res)
    return bool(ok) and not os.path.exists(path)


# ===================================================================== models
MODEL_PURPOSE = {
    "clip:RN101": "ui.models.purpose.rn101", "clip:ViT-B/32": "ui.models.purpose.vitb32",
    "u2net": "ui.models.purpose.u2net", "dino": "ui.models.purpose.dino", "vgg16": "ui.models.purpose.vgg16",
    "swiftsketch:diffusion": "ui.models.purpose.ss_diffusion", "swiftsketch:refine": "ui.models.purpose.ss_refine",
    "sd15": "ui.models.purpose.sd15", "dpt-hybrid": "ui.models.purpose.dpt", "hed": "ui.models.purpose.hed",
    "upernet": "ui.models.purpose.upernet", "blip": "ui.models.purpose.blip", "sdxl": "ui.models.purpose.sdxl",
    "lama": "ui.models.purpose.lama", "birefnet": "ui.models.purpose.birefnet",
    "birefnet-lite": "ui.models.purpose.birefnet-lite", "taesd": "ui.models.purpose.taesd",
}


def model_group(key: str) -> str:
    spec = model_store.SPECS[key]
    if spec.bundled:
        return "bundled"
    if key.startswith("birefnet"):
        return "masking"
    if key.startswith("clip:"):
        return "clipasso"
    if key.startswith("swiftsketch:"):
        return "swiftsketch"
    if key == "lama":
        return "scenesketch"
    return "controlsketch"


def _size_text(mb: float) -> str:
    return f"{mb / 1000:.1f} GB" if mb >= 1000 else f"{mb:.0f} MB"


def _bytes_text(n: int) -> str:
    return _size_text(n / 1e6) if n >= 1e6 else f"{n / 1e3:.0f} KB"


class ModelRow(Card):
    def __init__(self, key: str, page: "ModelsPage"):
        super().__init__(flat=True, margins=14, spacing=6)
        self.key = key
        self.page = page
        spec = model_store.SPECS[key]
        row = QHBoxLayout()
        row.setSpacing(12)
        ic = QLabel()
        ic.setPixmap(icons.pixmap("box", theme.current().accent_hover, 22))
        row.addWidget(ic)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.name = label(dialogs.model_display_name(key), "h3")
        self.desc = label("", "faint", wrap=True)
        col.addWidget(self.name)
        col.addWidget(self.desc)
        row.addLayout(col, 1)
        self.size = label(_size_text(spec.stored_size_mb), "muted")
        row.addWidget(self.size)
        self.state = label("", "badge")
        row.addWidget(self.state)
        self.import_btn = None
        if spec.kind == "swiftsketch":  # manual download when Google Drive refuses (quota)
            self.import_btn = tool_button("upload", "")
            self.import_btn.clicked.connect(self._import)
            row.addWidget(self.import_btn)
        self.action = button("", "download")
        self.action.clicked.connect(self._action)
        row.addWidget(self.action)
        self.body.addLayout(row)
        self.refresh()

    def refresh(self):
        spec = model_store.SPECS[self.key]
        found = model_store.find(self.key)
        bundled = found is not None and str(paths.bundled_models_dir()) in str(found)
        if self.key.startswith("controlnet:"):
            cond = self.key.split(":", 1)[1]
            self.desc.setText(tr("ui.models.purpose.controlnet", condition=tr(f"param.condition.choice.{cond}")))
        else:
            self.desc.setText(tr(MODEL_PURPOSE.get(self.key, "ui.models.purpose.clip_extra")))
        if self.import_btn is not None:
            self.import_btn.setToolTip(tr("ui.models.import_tip"))
            self.import_btn.setVisible(not found)
        if bundled:
            self.state.setText(tr("ui.models.bundled"))
            self.state.setProperty("role", "badge-success")
            self.action.setVisible(False)
        elif found:
            self.state.setText(tr("ui.models.installed"))
            self.state.setProperty("role", "badge-success")
            self.action.setVisible(True)
            self.action.setText(tr("ui.models.remove"))
            self.action.setIcon(icons.icon("trash-2", theme.current().text))
        else:
            self.state.setText(tr("ui.models.not_installed"))
            self.state.setProperty("role", "badge")
            self.action.setVisible(True)
            self.action.setText(tr("ui.download") + f" ({_size_text(spec.download_size / 1e6)})")
            self.action.setIcon(icons.icon("download", theme.current().text))
        self.state.style().unpolish(self.state)
        self.state.style().polish(self.state)

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("ui.models.import_tip"), os.path.expanduser("~"), "ZIP (*.zip)")
        if not path:
            return
        self.page.release_worker()  # a worker with loaded models keeps their files open (Windows)
        self.action.setEnabled(False)

        def done(_):
            self.action.setEnabled(True)
            self.page.refresh()

        def failed(msg):
            self.action.setEnabled(True)
            QMessageBox.warning(self, tr("ui.error"), msg)

        dialogs.run_in_thread(self, model_store.install_from_file, self.key, path, on_done=done, on_error=failed)

    def _action(self):
        if model_store.find(self.key):
            if QMessageBox.question(self, tr("ui.models.remove"), tr("ui.models.remove_q")) == QMessageBox.Yes:
                self.page.release_worker()
                model_store.uninstall(self.key)
        else:
            dialogs.ask_download_missing(self, [self.key])
        self.page.refresh()


class ModelsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        self.release_worker = lambda: None  # the main window: end the warm worker (it keeps model files open)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)
        lay, self.title, self.subtitle = _page_header("ui.models.title", "ui.models.subtitle")
        root.addLayout(lay)
        host = QWidget()
        self.list_lay = QVBoxLayout(host)
        self.list_lay.setContentsMargins(0, 0, 8, 0)
        self.list_lay.setSpacing(8)
        self.rows = []
        self.group_titles: dict[str, tuple[QLabel, QLabel]] = {}
        for group in ("bundled", "masking", "clipasso", "swiftsketch", "controlsketch", "scenesketch"):
            title = label("", "h2")
            hint = label("", "faint", wrap=True)
            if group != "bundled":
                self.list_lay.addSpacing(10)
            self.list_lay.addWidget(title)
            self.list_lay.addWidget(hint)
            self.group_titles[group] = (title, hint)
            for key in model_store.SPECS:
                if model_group(key) == group:
                    r = ModelRow(key, self)
                    self.rows.append(r)
                    self.list_lay.addWidget(r)
        self.location = label("", "faint", wrap=True)
        self.list_lay.addWidget(self.location)
        self.list_lay.addStretch(1)
        root.addWidget(_scroll(host), 1)
        i18n.language_changed.connect(lambda _: self.retranslate())
        self.retranslate()

    def refresh(self):
        for r in self.rows:
            r.refresh()

    def retranslate(self):
        self.title.setText(tr("ui.models.title"))
        self.subtitle.setText(tr("ui.models.subtitle"))
        for group, (title, hint) in self.group_titles.items():
            title.setText(tr(f"ui.models.group.{group}"))
            hint.setText(tr(f"ui.models.group_hint.{group}"))
        self.location.setText(tr("ui.models.location", path=str(paths.downloaded_models_dir())))
        self.refresh()


# =================================================================== settings
class SettingsPage(QWidget):
    theme_changed = Signal(str)
    models_dir_changed = Signal()
    keep_models_changed = Signal(bool)
    watch_changed = Signal()  # the watched folder was set up differently
    output_dir_changed = Signal(str, str, bool)  # (old, new, the results were moved along)
    check_updates_now = Signal()
    backup_restored = Signal(dict)  # the report of backup.restore (its queue entries are still to be queued)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy_check = lambda: False  # the main window: is a job running?
        self.waiting_files = lambda: []  # the main window: files the waiting jobs need (not cleared)
        self.release_worker = lambda: None  # the main window: end the warm worker
        self.setObjectName("Page")
        s = app_settings()
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)
        lay, self.title, self.subtitle = _page_header("ui.settings.title", "ui.settings.subtitle")
        root.addLayout(lay)
        host = QWidget()
        col = QVBoxLayout(host)
        col.setContentsMargins(0, 0, 8, 0)
        col.setSpacing(14)

        self.look = Card()
        self.look_title = label("", "h2")
        self.look.body.addWidget(self.look_title)
        self.lang_label = label("", None)
        self.lang = QComboBox()
        self.lang.addItem("", AUTO)  # text set in retranslate()
        for code, name in LANGUAGES.items():
            self.lang.addItem(name, code)
        self.lang.setCurrentIndex(max(self.lang.findData(s.get("language")), 0))
        self.lang.currentIndexChanged.connect(self._lang_changed)
        self.look.body.addLayout(self._row(self.lang_label, self.lang))
        self.theme_label = label("", None)
        self.theme_seg = SegmentedControl([("dark", ""), ("light", ""), ("system", "")])
        self.theme_seg.set_current(s.get("theme"))
        self.theme_seg.changed.connect(self._theme_changed)
        self.look.body.addLayout(self._row(self.theme_label, self.theme_seg))
        from ..app import UI_SCALES

        self.scale_label = label("", None)
        self.scale = QComboBox()
        for v in UI_SCALES:
            self.scale.addItem(f"{round(v * 100)} %", v)
        current = float(s.get("ui_scale", 1.0))
        self.scale.setCurrentIndex(min(range(len(UI_SCALES)), key=lambda i: abs(UI_SCALES[i] - current)))
        self.scale.currentIndexChanged.connect(self._scale_changed)
        self.look.body.addLayout(self._row(self.scale_label, self.scale))
        self.restart_row = QHBoxLayout()
        self.restart_hint = label("", "faint")
        self.restart_btn = button("", "refresh-cw", "primary", size="sm")
        self.restart_btn.clicked.connect(lambda: self.window().restart_app())
        self.restart_row.addWidget(self.restart_hint, 1)
        self.restart_row.addWidget(self.restart_btn)
        self.look.body.addLayout(self.restart_row)
        self._started_scale = current
        self._show_restart()
        col.addWidget(self.look)

        self.files = Card()
        self.files_title = label("", "h2")
        self.files.body.addWidget(self.files_title)
        self.out_label = label("", None)
        self.out_edit = QLineEdit(s.get("output_dir"))
        self.out_edit.setReadOnly(True)
        self.out_btn = button("", "folder-open")
        self.out_btn.clicked.connect(self._choose_out)
        r = QHBoxLayout()
        r.addWidget(self.out_edit, 1)
        r.addWidget(self.out_btn)
        self.files.body.addWidget(self.out_label)
        self.files.body.addLayout(r)
        # where downloaded models are stored (bundled ones stay with the app)
        self.models_label = label("", None)
        self.models_edit = QLineEdit(str(paths.downloaded_models_dir()))
        self.models_edit.setReadOnly(True)
        self.models_btn = button("", "folder-open")
        self.models_btn.clicked.connect(self.choose_models_dir)
        self.models_open = tool_button("external-link", "", 16)
        self.models_open.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(paths.downloaded_models_dir()))))
        self.models_hint = label("", "faint", wrap=True)
        r = QHBoxLayout()
        r.addWidget(self.models_edit, 1)
        r.addWidget(self.models_open)
        r.addWidget(self.models_btn)
        self.files.body.addWidget(self.models_label)
        self.files.body.addLayout(r)
        self.files.body.addWidget(self.models_hint)
        col.addWidget(self.files)

        self.behaviour = Card()
        self.behaviour_title = label("", "h2")
        self.behaviour.body.addWidget(self.behaviour_title)
        self.awake_label = label("", None)
        self.awake = ToggleSwitch()
        self.awake.setChecked(bool(s.get("keep_awake")))
        self.awake.toggled.connect(lambda v: s.set("keep_awake", v))
        self.behaviour.body.addLayout(self._row(self.awake_label, self.awake))
        self.notify_label = label("", None)
        self.notify = ToggleSwitch()
        self.notify.setChecked(bool(s.get("notify")))
        self.notify.toggled.connect(lambda v: s.set("notify", v))
        self.behaviour.body.addLayout(self._row(self.notify_label, self.notify))
        self.updates_label = label("", None)
        self.updates = ToggleSwitch()
        self.updates.setChecked(bool(s.get("check_updates")))
        self.updates.toggled.connect(lambda v: s.set("check_updates", v))
        self.check_now_btn = button("", "refresh-cw", "ghost", size="sm")
        self.check_now_btn.clicked.connect(self.check_updates_now.emit)
        r = QHBoxLayout()
        r.addWidget(self.updates_label)
        r.addStretch(1)
        r.addWidget(self.check_now_btn)
        r.addWidget(self.updates)
        self.behaviour.body.addLayout(r)
        self.warm_label = label("", None)
        self.warm = ToggleSwitch()  # the worker stays open between jobs with its models loaded
        self.warm.setChecked(bool(s.get("keep_models_loaded", True)))
        self.warm.toggled.connect(lambda v: (s.set("keep_models_loaded", v), self.keep_models_changed.emit(v)))
        self.behaviour.body.addLayout(self._row(self.warm_label, self.warm))
        self.parallel_label = label("", None)
        self.parallel = ToggleSwitch()  # several sketches of a job at the same time on a big CPU
        self.parallel.setChecked(s.get("parallel_sketches", "auto") == "auto")
        self.parallel.toggled.connect(lambda v: s.set("parallel_sketches", "auto" if v else "off"))
        self.behaviour.body.addLayout(self._row(self.parallel_label, self.parallel))
        self.multi_gpu_box = QWidget()  # (only with two or more graphics cards)
        self.multi_gpu_label = label("", None)
        self.multi_gpu = ToggleSwitch()  # the sketches of a job spread over the graphics cards
        self.multi_gpu.setChecked(bool(s.get("multi_gpu", True)))
        self.multi_gpu.toggled.connect(lambda v: s.set("multi_gpu", bool(v)))
        row = self._row(self.multi_gpu_label, self.multi_gpu)
        row.setContentsMargins(0, 0, 0, 0)
        self.multi_gpu_box.setLayout(row)
        self.behaviour.body.addWidget(self.multi_gpu_box)
        col.addWidget(self.behaviour)

        self._build_watch(col)
        from ..phone_ui import PhoneCard

        self.phone_card = PhoneCard()  # the phone page and Telegram (connected by the main window)
        col.addWidget(self.phone_card)
        self._build_storage(col)

        self.system = Card()
        self.system_title = label("", "h2")
        self.system.body.addWidget(self.system_title)
        self.system_info = label("", "mono", wrap=True)
        self.system_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.system.body.addWidget(self.system_info)
        self._build_gpu_runtime(self.system.body)
        self._build_sdxl_choice(self.system.body)
        self.logs_btn = button("", "folder-open", "ghost")
        self.logs_btn.clicked.connect(crash.open_logs_folder)
        self.diag_copy_btn = button("", "copy", "ghost")
        self.diag_copy_btn.clicked.connect(self.copy_diagnostics)
        self.diag_save_btn = button("", "download", "ghost")
        self.diag_save_btn.clicked.connect(self.save_diagnostics)
        row = QHBoxLayout()
        for b in (self.logs_btn, self.diag_copy_btn, self.diag_save_btn):
            row.addWidget(b)
        row.addStretch(1)
        self.system.body.addLayout(row)
        self.selftest_btn = button("", "circle-check", "ghost")
        self.selftest_btn.clicked.connect(self.run_selftest)
        self.report_btn = button("", "triangle-alert", "ghost")
        self.report_btn.clicked.connect(self.report_problem)
        row = QHBoxLayout()
        for b in (self.selftest_btn, self.report_btn):
            row.addWidget(b)
        row.addStretch(1)
        self.system.body.addLayout(row)
        # backup & move to another computer: settings, queue, gallery (and the models, if wanted) in one file
        self.backup_btn = button("", "download", "ghost")
        self.backup_btn.clicked.connect(self.make_backup)
        self.restore_btn = button("", "refresh-cw", "ghost")
        self.restore_btn.clicked.connect(lambda: self.restore_backup())
        row = QHBoxLayout()
        for b in (self.backup_btn, self.restore_btn):
            row.addWidget(b)
        row.addStretch(1)
        self.system.body.addLayout(row)
        col.addWidget(self.system)
        col.addStretch(1)
        root.addWidget(_scroll(host), 1)
        from .. import hardware

        self._hardware = hardware.cached()  # the main window probes again after the start
        i18n.language_changed.connect(lambda _: self.retranslate())
        self.retranslate()

    @staticmethod
    def _row(lbl, widget):
        r = QHBoxLayout()
        r.addWidget(lbl)
        r.addStretch(1)
        r.addWidget(widget)
        return r

    def _build_storage(self, col):
        """Disk space of caches and leftovers, each with a button to clear it."""
        from .. import storage

        self.storage_card = Card()
        self.storage_title = label("", "h2")
        self.storage_desc = label("", "faint", wrap=True)
        self.storage_card.body.addWidget(self.storage_title)
        self.storage_card.body.addWidget(self.storage_desc)
        self.storage_rows = {}
        for key in storage.AREAS:
            name, size = label("", None), label("", "faint")
            clear = button("", "trash-2", "ghost", size="sm")
            clear.clicked.connect(lambda _=False, k=key: self.clear_storage(k))
            r = QHBoxLayout()
            r.addWidget(name)
            r.addStretch(1)
            r.addWidget(size)
            r.addWidget(clear)
            self.storage_card.body.addLayout(r)
            self.storage_rows[key] = (name, size, clear)
        col.addWidget(self.storage_card)

    def refresh_storage(self) -> dict:
        from .. import storage

        sizes = storage.sizes()
        for key, (_, size, clear) in self.storage_rows.items():
            size.setText(_bytes_text(sizes[key]))
            clear.setEnabled(sizes[key] > 0)
        return sizes

    def clear_storage(self, key: str, confirm: bool = True) -> int:
        """Clear one area (asks first); pasted / edited images a waiting job needs stay."""
        from .. import storage

        if confirm and QMessageBox.question(self, tr("ui.storage.title"), tr(f"ui.storage.clear_q.{key}")) \
                != QMessageBox.Yes:
            return 0
        freed = storage.clear(key, self.waiting_files() if key == "inputs" else ())
        self.refresh_storage()
        return freed

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self.refresh_storage()
        self.refresh_sdxl_choice()  # (the studio may have remembered an answer)

    def _build_watch(self, col):
        """Watched folder: new images there are sketched by themselves and exported."""
        from .. import watch

        s = app_settings()
        cfg = watch.config()
        self.watch_card = Card()
        self.watch_title = label("", "h2")
        self.watch_desc = label("", "faint", wrap=True)
        self.watch_card.body.addWidget(self.watch_title)
        self.watch_card.body.addWidget(self.watch_desc)
        self.watch_on_label = label("", None)
        self.watch_on = ToggleSwitch()
        self.watch_on.setChecked(cfg["enabled"])
        self.watch_on.toggled.connect(lambda v: self._watch_set("watch_enabled", v))
        self.watch_card.body.addLayout(self._row(self.watch_on_label, self.watch_on))
        self.watch_folder_label = label("", None)
        self.watch_folder = QLineEdit(cfg["folder"])
        self.watch_folder.setReadOnly(True)
        self.watch_folder_btn = button("", "folder-open")
        self.watch_folder_btn.clicked.connect(lambda: self._watch_choose("watch_folder", self.watch_folder))
        r = QHBoxLayout()
        r.addWidget(self.watch_folder, 1)
        r.addWidget(self.watch_folder_btn)
        self.watch_card.body.addWidget(self.watch_folder_label)
        self.watch_card.body.addLayout(r)
        self.watch_preset_label = label("", None)
        self.watch_preset = QComboBox()
        self.watch_preset.addItem("", "studio")
        self.watch_preset.addItem("", "file")
        preset = cfg["preset"]
        if preset != "studio":
            self.watch_preset.addItem(os.path.basename(preset), preset)
            self.watch_preset.setCurrentIndex(2)
        self.watch_preset.activated.connect(self._watch_preset_chosen)
        self.watch_card.body.addLayout(self._row(self.watch_preset_label, self.watch_preset))
        self.watch_formats_label = label("", None)
        formats = QHBoxLayout()
        formats.setSpacing(12)
        self.watch_formats = {}
        for fmt in watch.FORMATS:
            box = QCheckBox({"svg": "SVG", "svg1": "", "png": "PNG", "pdf": "PDF"}[fmt])
            box.setChecked(fmt in cfg["formats"])
            box.toggled.connect(lambda _: self._watch_set("watch_formats", [f for f, b in self.watch_formats.items()
                                                                             if b.isChecked()]))
            self.watch_formats[fmt] = box
            formats.addWidget(box)
        formats.addStretch(1)
        self.watch_card.body.addWidget(self.watch_formats_label)
        self.watch_card.body.addLayout(formats)
        self.watch_export_label = label("", None)
        self.watch_export = QLineEdit(cfg["export_dir"])
        self.watch_export.setReadOnly(True)
        self.watch_export_btn = button("", "folder-open")
        self.watch_export_btn.clicked.connect(lambda: self._watch_choose("watch_export_dir", self.watch_export))
        r = QHBoxLayout()
        r.addWidget(self.watch_export, 1)
        r.addWidget(self.watch_export_btn)
        self.watch_card.body.addWidget(self.watch_export_label)
        self.watch_card.body.addLayout(r)
        self.watch_move_label = label("", None)
        self.watch_move = ToggleSwitch()
        self.watch_move.setChecked(cfg["move_done"])
        self.watch_move.toggled.connect(lambda v: self._watch_set("watch_move_done", v))
        self.watch_card.body.addLayout(self._row(self.watch_move_label, self.watch_move))
        col.addWidget(self.watch_card)
        del s

    def _watch_set(self, key: str, value) -> None:
        app_settings().set(key, value)
        self.watch_changed.emit()

    def _watch_choose(self, key: str, edit: QLineEdit, folder: str | None = None) -> None:
        if folder is None:
            start = edit.text() or os.path.expanduser("~")
            folder = QFileDialog.getExistingDirectory(self, tr("ui.watch.choose"), start)
        if folder:
            edit.setText(folder)
            self._watch_set(key, folder)

    def _watch_preset_chosen(self, index: int) -> None:
        data = self.watch_preset.itemData(index)
        if data == "file":
            path, _ = QFileDialog.getOpenFileName(self, tr("ui.watch.preset_file"), os.path.expanduser("~"),
                                                  "JSON (*.json)")
            if not path:
                self.watch_preset.setCurrentIndex(max(self.watch_preset.findData(app_settings().get(
                    "watch_preset") or "studio"), 0))
                return
            while self.watch_preset.count() > 2:
                self.watch_preset.removeItem(2)
            self.watch_preset.addItem(os.path.basename(path), path)
            self.watch_preset.setCurrentIndex(2)
            data = path
        self._watch_set("watch_preset", data)

    def _lang_changed(self, idx):
        code = self.lang.itemData(idx)
        app_settings().set("language", code)
        i18n.set_language(code)

    def _scale_changed(self, _index):
        app_settings().set("ui_scale", float(self.scale.currentData()))
        self._show_restart()

    def _show_restart(self):
        pending = abs(float(self.scale.currentData()) - self._started_scale) > 1e-3
        self.restart_hint.setVisible(pending)
        self.restart_btn.setVisible(pending)

    def _theme_changed(self, mode):
        app_settings().set("theme", mode)
        self.theme_changed.emit(mode)

    def _choose_out(self, folder: str | None = None, move: bool | None = None) -> bool:
        """Change the output folder; its results (job folders, pasted / edited images) can move along
        (``folder`` / ``move`` skip the dialogs, for tests)."""
        from ... import fileops
        from .. import storage

        old = app_settings().get("output_dir") or ""
        if folder is None:
            folder = QFileDialog.getExistingDirectory(self, tr("ui.settings.output"), self.out_edit.text())
            if not folder:
                return False
        new, cur = Path(folder).resolve(), Path(old).resolve() if old else None
        if cur is not None and new == cur:
            return False
        names = storage.result_entries(old) if old else []
        if names and move is not False:
            if self.busy_check():  # a running job writes into the old folder
                QMessageBox.information(self, tr("ui.settings.output"), tr("ui.settings.output_busy"))
                return False
            if any(Path(old, n).resolve() in (new, *new.parents) for n in names):
                QMessageBox.warning(self, tr("ui.settings.output"), tr("ui.settings.models_nested"))
                return False
            size = storage.results_size(old)
            if move is None:
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Question)
                box.setWindowTitle(tr("ui.settings.output"))
                box.setText(tr("ui.settings.output_move_q", n=len(names), size=_bytes_text(size)))
                move_btn = box.addButton(tr("ui.settings.output_move"), QMessageBox.AcceptRole)
                only_btn = box.addButton(tr("ui.settings.output_only"), QMessageBox.DestructiveRole)
                box.addButton(tr("ui.cancel"), QMessageBox.RejectRole)
                box.exec()
                if box.clickedButton() not in (move_btn, only_btn):
                    return False
                move = box.clickedButton() is move_btn
            if move:
                if cur.anchor.lower() != new.anchor.lower() and 0 <= fileops.free_space(new) < size * 1.02:
                    QMessageBox.warning(self, tr("ui.settings.output"),
                                        tr("ui.settings.models_no_space", size=_bytes_text(size)))
                    return False
                dlg = dialogs.BusyDialog(tr("ui.settings.output_moving"), self)
                dialogs.run_in_thread(dlg, storage.move_results, old, str(new), on_progress=dlg.progress,
                                      on_done=lambda _: dlg.accept(), on_error=dlg.fail)
                if not dlg.exec():
                    QMessageBox.warning(self, tr("ui.settings.output"), dlg.error or tr("ui.error"))
                    return False
        self.out_edit.setText(str(new))
        app_settings().set("output_dir", str(new))
        self.output_dir_changed.emit(old, str(new), bool(names and move))
        self.refresh_storage()
        return True

    def choose_models_dir(self, folder: str | None = None, move: bool | None = None) -> bool:
        """Change the folder of the downloaded models, moving them there if wanted (``folder`` /
        ``move`` skip the dialogs, for tests). Not while a job runs."""
        if self.busy_check():
            QMessageBox.information(self, tr("ui.settings.models_dir"), tr("ui.settings.models_busy"))
            return False
        self.release_worker()  # its loaded models keep their files open (Windows)
        old = paths.downloaded_models_dir()
        if folder is None:
            folder = QFileDialog.getExistingDirectory(self, tr("ui.settings.models_dir"), str(old))
            if not folder:
                return False
        new, cur = Path(folder).resolve(), old.resolve()
        if new == cur:
            return False
        if cur in new.parents or new in cur.parents:
            QMessageBox.warning(self, tr("ui.settings.models_dir"), tr("ui.settings.models_nested"))
            return False
        size = model_store.folder_size(cur)
        if size and move is None:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Question)
            box.setWindowTitle(tr("ui.settings.models_dir"))
            box.setText(tr("ui.settings.models_move_q", size=_size_text(size / 1e6)))
            move_btn = box.addButton(tr("ui.settings.models_move"), QMessageBox.AcceptRole)
            only_btn = box.addButton(tr("ui.settings.models_only"), QMessageBox.DestructiveRole)
            box.addButton(tr("ui.cancel"), QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() not in (move_btn, only_btn):
                return False
            move = box.clickedButton() is move_btn
        if size and move:
            new.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(new).free < size * 1.02 and cur.anchor.lower() != new.anchor.lower():
                QMessageBox.warning(self, tr("ui.settings.models_dir"), tr("ui.settings.models_no_space",
                                                                         size=_size_text(size / 1e6)))
                return False
            dlg = dialogs.BusyDialog(tr("ui.settings.models_moving"), self)
            dialogs.run_in_thread(dlg, model_store.move_models, cur, new, on_progress=dlg.progress,
                                  on_done=lambda _: dlg.accept(), on_error=dlg.fail)
            if not dlg.exec():
                QMessageBox.warning(self, tr("ui.settings.models_dir"), dlg.error or tr("ui.error"))
                return False
        default = paths.default_models_dir().resolve()
        app_settings().set("models_dir", "" if new == default else str(new))
        self._show_models_dir()
        self.models_dir_changed.emit()
        return True

    def _show_models_dir(self):
        folder = paths.downloaded_models_dir()
        self.models_edit.setText(str(folder))
        self.models_hint.setText(tr("ui.settings.models_hint", size=_size_text(model_store.folder_size(folder) / 1e6)))

    def copy_diagnostics(self) -> str:
        """Copy the diagnostics text (for a bug report) to the clipboard."""
        from .. import diagnostics

        text = diagnostics.report()
        QApplication.clipboard().setText(text)
        self.diag_copy_btn.setText(tr("ui.diag.copied"))
        QTimer.singleShot(2500, lambda: self.diag_copy_btn.setText(tr("ui.diag.copy")))
        return text

    def save_diagnostics(self, path: str = "") -> str:
        from .. import diagnostics

        if not path:
            folder = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or str(Path.home())
            start = os.path.join(folder, diagnostics.default_file_name())
            path, _ = QFileDialog.getSaveFileName(self, tr("ui.diag.save"), start, "Text (*.txt)")
            if not path:
                return ""
        try:
            diagnostics.save(path)
        except OSError as exc:
            QMessageBox.warning(self, tr("ui.diag.save"), str(exc))
            return ""
        return path

    def run_selftest(self) -> dict | None:
        from .. import selftest_ui

        return selftest_ui.run(self)

    def make_backup(self) -> str:
        from .. import backup_ui

        return backup_ui.make_backup(self)

    def restore_backup(self, path: str | None = None) -> dict | None:
        from .. import backup_ui

        if self.busy_check():
            QMessageBox.information(self, tr("ui.backup.restore_title"), tr("ui.backup.busy"))
            return None
        report = backup_ui.restore_backup(self, path)
        if report is not None:
            self.retranslate()
            self.backup_restored.emit(report)
        return report

    def report_problem(self) -> None:
        from .. import report

        report.ReportDialog(self).exec()

    def set_hardware(self, info: dict | None):
        """The answer of the hardware probe (gui/hardware.py)."""
        self._hardware = info
        self.retranslate()

    # ------------------------------------------------------- PyTorch for older GPUs
    def _build_gpu_runtime(self, body):
        """Older graphics cards (GTX 9xx / 10xx): the extra PyTorch with CUDA 12.6 (gpu_runtime) and the
        precision of the GPU."""
        from ... import gpu_runtime

        self.gpurt_box = QWidget()
        col = QVBoxLayout(self.gpurt_box)
        col.setContentsMargins(0, 6, 0, 2)
        col.setSpacing(6)
        self.gpurt_title = label("", "h3")
        self.gpurt_state = label("", "faint", wrap=True)
        col.addWidget(self.gpurt_title)
        col.addWidget(self.gpurt_state)
        row = QHBoxLayout()
        self.gpurt_load = button("", "download", "ghost")
        self.gpurt_load.clicked.connect(self._gpurt_download)
        self.gpurt_switch_label = label("", None)
        self.gpurt_switch = ToggleSwitch()
        self.gpurt_switch.toggled.connect(self._gpurt_switched)
        self.gpurt_remove = button("", "trash-2", "ghost")
        self.gpurt_remove.clicked.connect(self._gpurt_remove)
        for w in (self.gpurt_load, self.gpurt_switch_label, self.gpurt_switch, self.gpurt_remove):
            row.addWidget(w)
        row.addStretch(1)
        col.addLayout(row)
        self.gpu_precision_label = label("", None)
        self.gpu_precision = ToggleSwitch()  # off: float16 for the big networks (the default), on: float32
        self.gpu_precision.setChecked(app_settings().get("gpu_precision") == "fp32")
        self.gpu_precision.toggled.connect(lambda on: app_settings().set("gpu_precision", "fp32" if on else "auto"))
        col.addLayout(self._row(self.gpu_precision_label, self.gpu_precision))
        self.gpu_precision_desc = label("", "faint", wrap=True)
        col.addWidget(self.gpu_precision_desc)
        body.addWidget(self.gpurt_box)
        self._gpurt_rt = gpu_runtime.LEGACY

    def _build_sdxl_choice(self, body):
        """ControlSketch's SDXL on a graphics card with less than 8 GB: ask, on the CPU, or CLIP instead (the
        answer the studio remembered can be changed here)."""
        from .. import methods_ui

        self.sdxl_box = QWidget()
        col = QVBoxLayout(self.sdxl_box)
        col.setContentsMargins(0, 6, 0, 2)
        col.setSpacing(6)
        self.sdxl_label = label("", None)
        self.sdxl_choice = QComboBox()
        for value in ("", "offload", "cpu", "clip"):
            self.sdxl_choice.addItem("", value)
        self.sdxl_choice.setCurrentIndex(max(self.sdxl_choice.findData(
            app_settings().get(methods_ui.SDXL_SMALL_GPU) or ""), 0))
        self.sdxl_choice.currentIndexChanged.connect(
            lambda _: app_settings().set(methods_ui.SDXL_SMALL_GPU, self.sdxl_choice.currentData()))
        col.addLayout(self._row(self.sdxl_label, self.sdxl_choice))
        self.sdxl_desc = label("", "faint", wrap=True)
        col.addWidget(self.sdxl_desc)
        body.addWidget(self.sdxl_box)

    def refresh_sdxl_choice(self) -> None:
        from ...engine.methods.requirements import sdxl_on_cpu
        from .. import methods_ui

        info = self._hardware or {}
        small = any(g.get("supported", True) and sdxl_on_cpu(float(g.get("memory_gb") or 0))
                    for g in info.get("gpus") or [])
        value = app_settings().get(methods_ui.SDXL_SMALL_GPU) or ""
        self.sdxl_box.setVisible(small or bool(value))
        self.sdxl_choice.blockSignals(True)
        self.sdxl_choice.setCurrentIndex(max(self.sdxl_choice.findData(value), 0))
        self.sdxl_choice.blockSignals(False)
        self.sdxl_label.setText(tr("ui.settings.sdxl_small_gpu"))
        for i, key in enumerate(("ask", "offload", "cpu", "clip")):
            self.sdxl_choice.setItemText(i, tr(f"ui.settings.sdxl_small_gpu.{key}"))
        self.sdxl_desc.setText(tr("ui.settings.sdxl_small_gpu.tip"))

    def gpu_runtime_visible(self) -> bool:
        from ... import gpu_runtime
        from .. import gpu_runtime_ui

        return gpu_runtime_ui.available_here() or gpu_runtime.is_installed() or bool(gpu_runtime.active()) or \
            bool(gpu_runtime.helps(self._hardware))

    def refresh_gpu_runtime(self) -> str:
        from ... import gpu_runtime
        from .. import gpu_runtime_ui

        st = gpu_runtime_ui.state()
        rt = gpu_runtime.LEGACY
        self.gpurt_box.setVisible(self.gpu_runtime_visible())
        self.gpurt_title.setText(tr("ui.gpurt.row_title"))
        if st == "active":
            text = tr("ui.gpurt.state_active", torch=gpu_runtime.TORCH_VERSION, cuda=rt.cuda)
        elif st == "missing":
            text = tr("ui.gpurt.state_missing", download=gpu_runtime_ui.gb(rt.download_size))
        else:
            text = tr(f"ui.gpurt.state_{st}")
        self.gpurt_state.setText(text)
        self.gpurt_load.setVisible(st == "missing")
        self.gpurt_load.setText(tr("ui.gpurt.load_btn"))
        for w in (self.gpurt_switch_label, self.gpurt_switch, self.gpurt_remove):
            w.setVisible(st != "missing")
        self.gpurt_switch_label.setText(tr("ui.gpurt.switch"))
        self.gpurt_switch.blockSignals(True)
        self.gpurt_switch.setChecked(st in ("active", "restart"))
        self.gpurt_switch.blockSignals(False)
        self.gpurt_remove.setText(tr("ui.gpurt.remove_btn"))
        self.gpu_precision_label.setText(tr("ui.gpurt.precision_fp32"))
        self.gpu_precision_desc.setText(tr("ui.gpurt.precision_tip"))
        return st

    def _gpurt_download(self):
        from .. import gpu_runtime_ui

        gpu_runtime_ui.download(self)
        self.refresh_gpu_runtime()

    def _gpurt_switched(self, on: bool):
        from .. import gpu_runtime_ui

        gpu_runtime_ui.switch(on)
        self.refresh_gpu_runtime()
        gpu_runtime_ui.ask_restart(self)

    def _gpurt_remove(self, confirm: bool = True) -> bool:
        from ... import gpu_runtime
        from .. import gpu_runtime_ui

        rt = gpu_runtime.LEGACY
        if confirm and QMessageBox.question(self, tr("ui.gpurt.row_title"),
                                            tr("ui.gpurt.remove_q", disk=gpu_runtime_ui.gb(rt.unpacked))) \
                != QMessageBox.Yes:
            return False
        gpu_runtime_ui.switch(False)
        if not gpu_runtime.remove():  # in use by this app: deleted at the next start
            QMessageBox.information(self, tr("ui.gpurt.row_title"), tr("ui.gpurt.removed_later"))
        self.refresh_gpu_runtime()
        return True

    def _hardware_text(self) -> str:
        info = self._hardware
        if not info:
            return ""
        if info.get("error"):
            return f"PyTorch: {info['error']}"
        lines = [f"PyTorch {info.get('torch', '?')}"]
        for i, gpu in enumerate(info.get("gpus", [])):
            ok = "" if gpu.get("supported", True) else f"  ⚠ {tr('ui.settings.gpu_unsupported')}"
            lines.append(f"GPU {i}: {gpu.get('name', '?')} · {gpu.get('memory_gb', 0):.1f} GB{ok}")
        if not info.get("gpus"):
            lines.append(f"CUDA {info['cuda_build']}: {tr('ui.settings.gpu_none')}" if info.get("cuda_build")
                         else "CUDA: –")
        return "\n".join(lines)

    def retranslate(self):
        self.title.setText(tr("ui.settings.title"))
        self.subtitle.setText(tr("ui.settings.subtitle"))
        self.look_title.setText(tr("ui.settings.appearance"))
        self.lang_label.setText(tr("ui.settings.language"))
        self.lang.setItemText(0, tr("ui.settings.language_auto", lang=LANGUAGES[system_language()]))
        self.theme_label.setText(tr("ui.settings.theme"))
        self.scale_label.setText(tr("ui.settings.ui_scale"))
        self.scale.setToolTip(tr("ui.settings.ui_scale_tip"))
        self.restart_hint.setText(tr("ui.settings.restart_hint"))
        self.restart_btn.setText(tr("ui.settings.restart"))
        for k in ("dark", "light", "system"):
            self.theme_seg.set_text(k, tr(f"ui.theme.{k}"))
        self.files_title.setText(tr("ui.settings.files"))
        self.out_label.setText(tr("ui.settings.output"))
        self.out_btn.setText(tr("ui.change"))
        self.models_label.setText(tr("ui.settings.models_dir"))
        self.models_btn.setText(tr("ui.change"))
        self.models_open.setToolTip(tr("ui.open_folder"))
        self._show_models_dir()
        self.behaviour_title.setText(tr("ui.settings.behaviour"))
        self.awake_label.setText(tr("ui.settings.keep_awake"))
        self.notify_label.setText(tr("ui.settings.notify"))
        self.updates_label.setText(tr("ui.settings.check_updates"))
        self.check_now_btn.setText(tr("ui.update.check_now"))
        self.warm_label.setText(tr("ui.settings.keep_models"))
        self.warm_label.setToolTip(tr("ui.settings.keep_models_tip"))
        self.warm.setToolTip(tr("ui.settings.keep_models_tip"))
        self.parallel_label.setText(tr("ui.settings.parallel"))
        self.parallel_label.setToolTip(tr("ui.settings.parallel_tip"))
        self.parallel.setToolTip(tr("ui.settings.parallel_tip"))
        self.multi_gpu_label.setText(tr("ui.settings.multi_gpu"))
        self.multi_gpu_label.setToolTip(tr("ui.settings.multi_gpu_tip"))
        self.multi_gpu.setToolTip(tr("ui.settings.multi_gpu_tip"))
        gpus = [g for g in (self._hardware or {}).get("gpus") or [] if g.get("supported", True)]
        self.multi_gpu_box.setVisible(len(gpus) >= 2)
        self.watch_title.setText(tr("ui.watch.title"))
        self.phone_card.retranslate()
        self.watch_desc.setText(tr("ui.watch.desc"))
        self.watch_on_label.setText(tr("ui.watch.enabled"))
        self.watch_folder_label.setText(tr("ui.watch.folder"))
        self.watch_folder_btn.setText(tr("ui.change"))
        self.watch_preset_label.setText(tr("ui.watch.preset"))
        self.watch_preset.setItemText(0, tr("ui.watch.preset_studio"))
        self.watch_preset.setItemText(1, tr("ui.watch.preset_file"))
        self.watch_formats_label.setText(tr("ui.watch.formats"))
        self.watch_formats["svg1"].setText(tr("ui.export_svg1"))
        self.watch_export_label.setText(tr("ui.watch.export_dir"))
        self.watch_export.setPlaceholderText(tr("ui.watch.export_default"))
        self.watch_export_btn.setText(tr("ui.change"))
        self.watch_move_label.setText(tr("ui.watch.move_done"))
        self.storage_title.setText(tr("ui.storage.title"))
        self.storage_desc.setText(tr("ui.storage.desc"))
        for key, (name, _, clear) in self.storage_rows.items():
            name.setText(tr(f"ui.storage.{key}"))
            name.setToolTip(tr(f"ui.storage.{key}_tip"))
            clear.setText(tr("ui.storage.clear"))
        self.logs_btn.setText(tr("ui.crash.open_logs"))
        self.logs_btn.setToolTip(tr("ui.settings.logs_tip"))
        self.diag_copy_btn.setText(tr("ui.diag.copy"))
        self.diag_copy_btn.setToolTip(tr("ui.diag.tip"))
        self.diag_save_btn.setText(tr("ui.diag.save"))
        self.diag_save_btn.setToolTip(tr("ui.diag.tip"))
        self.selftest_btn.setText(tr("ui.selftest.button"))
        self.selftest_btn.setToolTip(tr("ui.selftest.desc"))
        self.backup_btn.setText(tr("ui.backup.button"))
        self.backup_btn.setToolTip(tr("ui.backup.tip"))
        self.restore_btn.setText(tr("ui.backup.restore_button"))
        self.restore_btn.setToolTip(tr("ui.backup.restore_tip"))
        self.report_btn.setText(tr("ui.report.button"))
        self.report_btn.setToolTip(tr("ui.report.tip"))
        self.system_title.setText(tr("ui.settings.system"))
        edition = tr(f"ui.edition.{EDITION}")
        info = [f"{APP_NAME} {__version__} · {edition}",
                f"{platform.system()} {platform.release()} · Python {platform.python_version()}",
                f"CPU: {os.cpu_count()} {tr('ui.threads')}"]
        hw = self._hardware_text()
        if hw:
            info.append(hw)
        info.append(f"{tr('ui.models.title')}: {paths.bundled_models_dir()}")
        self.system_info.setText("\n".join(info))
        self.refresh_gpu_runtime()
        self.refresh_sdxl_choice()


# ====================================================================== about
class AboutPage(QWidget):
    show_tour = Signal()
    show_whats_new = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)
        host = QWidget()
        col = QVBoxLayout(host)
        col.setContentsMargins(0, 0, 8, 0)
        col.setSpacing(14)
        hero = Card(margins=24)
        top = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QPixmap(str(paths.resource("app_icon.png"))).scaled(72, 72, Qt.KeepAspectRatio,
                                                                            Qt.SmoothTransformation))
        top.addWidget(logo)
        t = QVBoxLayout()
        self.name = label(APP_NAME, "title")
        self.version = label("", "muted")
        self.byline = label("", "faint")
        t.addWidget(self.name)
        t.addWidget(self.version)
        t.addWidget(self.byline)
        top.addLayout(t, 1)
        self.tour_btn = button("", "circle-help", "ghost")
        self.tour_btn.clicked.connect(self.show_tour.emit)
        self.whats_new_btn = button("", "sparkles", "ghost")
        self.whats_new_btn.clicked.connect(self.show_whats_new.emit)
        buttons = QVBoxLayout()
        buttons.addWidget(self.tour_btn)
        buttons.addWidget(self.whats_new_btn)
        buttons.addStretch(1)
        top.addLayout(buttons)
        hero.body.addLayout(top)
        self.desc = label("", None, wrap=True)
        hero.body.addWidget(self.desc)
        self.link_buttons = []
        for method, items in (("CLIPasso", (("ui.about.paper", "https://arxiv.org/abs/2202.05822"),
                                            ("ui.about.project", "https://clipasso.github.io/clipasso/"),
                                            ("ui.about.code", "https://github.com/yael-vinker/CLIPasso"))),
                              ("SwiftSketch · ControlSketch", (
                                  ("ui.about.paper", "https://arxiv.org/abs/2502.08642"),
                                  ("ui.about.project", "https://swiftsketch.github.io/"),
                                  ("ui.about.code", "https://github.com/swiftsketch/SwiftSketch"))),
                              ("SceneSketch", (("ui.about.paper", "https://arxiv.org/abs/2211.17256"),
                                               ("ui.about.project", "https://clipascene.github.io/CLIPascene/"),
                                               ("ui.about.code", "https://github.com/yael-vinker/SceneSketch")))):
            links = QHBoxLayout()
            name = label(method, "h3")
            name.setMinimumWidth(190)
            links.addWidget(name)
            for key, url in items:
                b = button(tr(key), "external-link", "ghost")
                b.clicked.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
                b.setProperty("i18n", key)
                links.addWidget(b)
                self.link_buttons.append(b)
            links.addStretch(1)
            hero.body.addLayout(links)
        col.addWidget(hero)

        self.credits = Card()
        self.credits_title = label("", "h2")
        self.credits_text = label("", "muted", wrap=True)
        self.credits_text.setTextFormat(Qt.RichText)
        self.credits_text.setOpenExternalLinks(True)
        self.credits.body.addWidget(self.credits_title)
        self.credits.body.addWidget(self.credits_text)
        col.addWidget(self.credits)

        self.keys = Card()
        self.keys_title = label("", "h2")
        self.keys.body.addWidget(self.keys_title)
        self.keys_grid = QGridLayout()
        self.keys_grid.setHorizontalSpacing(18)
        self.keys_grid.setVerticalSpacing(6)
        self.key_labels = []
        for row, (seq, _) in enumerate(shortcuts.SHORTCUTS):
            key = label(shortcuts.native(seq) + (" … 7" if seq == "Ctrl+1" else ""), "mono")
            text = label("", "muted")
            self.keys_grid.addWidget(key, row, 0)
            self.keys_grid.addWidget(text, row, 1)
            self.key_labels.append(text)
        self.keys_grid.setColumnStretch(1, 1)
        self.keys.body.addLayout(self.keys_grid)
        col.addWidget(self.keys)

        self.license = Card()
        self.license_title = label("", "h2")
        self.license_text = label("", "muted", wrap=True)
        self.license_text.setTextFormat(Qt.RichText)
        self.license_text.setOpenExternalLinks(True)
        self.license.body.addWidget(self.license_title)
        self.license.body.addWidget(self.license_text)
        col.addWidget(self.license)
        col.addStretch(1)
        root.addWidget(_scroll(host), 1)
        i18n.language_changed.connect(lambda _: self.retranslate())
        self.retranslate()

    def retranslate(self):
        self.version.setText(tr("ui.about.version", version=__version__, edition=tr(f"ui.edition.{EDITION}")))
        self.tour_btn.setText(tr("ui.tour.show"))
        self.whats_new_btn.setText(tr("ui.whatsnew.button_about", version=__version__))
        self.byline.setText(tr("ui.about.byline"))
        self.desc.setText(tr("ui.about.desc"))
        for b in self.link_buttons:
            b.setText(tr(b.property("i18n")))
        self.credits_title.setText(tr("ui.about.credits"))
        self.credits_text.setText(tr("ui.about.credits_text"))
        self.keys_title.setText(tr("ui.shortcuts"))
        for text, (_, key) in zip(self.key_labels, shortcuts.SHORTCUTS):
            text.setText(tr(key))
        self.license_title.setText(tr("ui.about.license"))
        self.license_text.setText(tr("ui.about.license_text"))

