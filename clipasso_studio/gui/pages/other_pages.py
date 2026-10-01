"""Queue, gallery, models, settings and about pages."""

from __future__ import annotations

import json
import os
import platform
import shutil
from pathlib import Path

from PySide6.QtCore import QFile, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMenu, QMessageBox, QProgressBar, QScrollArea, QVBoxLayout, QWidget)

from ... import APP_NAME, __version__, paths
from ... import settings_schema as schema
from ...engine import jobs, model_store
from .. import crash, dialogs, icons, methods_ui, power, shortcuts, theme
from ..drop import dropped_images, has_images, image_files  # noqa: F401 (image_files re-exported)
from ..app_settings import app_settings
from ..controller import JobController, QueuedJob
from ..i18n import AUTO, LANGUAGES, i18n, system_language, tr
from ..widgets.canvas import IMAGE_FILTER, SketchCanvas
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
class QueueRow(Card):
    def __init__(self, job: QueuedJob, controller: JobController, parent=None):
        super().__init__(parent, flat=True, margins=12, spacing=8)
        self.job = job
        self.controller = controller
        row = QHBoxLayout()
        row.setSpacing(12)
        thumb = QLabel()
        pm = QPixmap(job.target)
        if not pm.isNull():
            thumb.setPixmap(pm.scaled(56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        thumb.setFixedSize(60, 60)
        thumb.setAlignment(Qt.AlignCenter)
        row.addWidget(thumb)
        info = QVBoxLayout()
        info.setSpacing(3)
        self.name = label(job.name, "h3")
        s = job.settings
        self.details = label(tr("ui.queue.details", strokes=schema.num_strokes(s), iters=methods_ui.iterations(s),
                                sketches=s["num_sketches"]), "faint")
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name_row.addWidget(self.name)
        name_row.addWidget(method_badge(schema.method_of(s)))
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
        self.up = tool_button("chevron-up", tr("ui.queue.up"))
        self.up.clicked.connect(lambda: controller.move(job.id, -1))
        self.down = tool_button("chevron-down", tr("ui.queue.down"))
        self.down.clicked.connect(lambda: controller.move(job.id, 1))
        self.folder = tool_button("folder-open", tr("ui.open_folder"))
        self.folder.clicked.connect(self._open)
        self.remove = tool_button("trash-2", tr("ui.queue.remove"))
        self.remove.clicked.connect(lambda: controller.remove(job.id))
        for b in (self.up, self.down, self.folder, self.remove):
            row.addWidget(b)
        self.body.addLayout(row)
        self.refresh()

    def _open(self):
        if self.job.job_dir and os.path.isdir(self.job.job_dir):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.job.job_dir))

    def refresh(self):
        j = self.job
        self.bar.setValue(int(j.progress * 1000) if j.status != "done" else 1000)
        self.badge.setText(tr(f"ui.jobstatus.{j.status}"))
        self.badge.setProperty("role", _status_role(j.status))
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)
        queued = j.status == "queued"
        self.up.setEnabled(queued)
        self.down.setEnabled(queued)
        self.remove.setEnabled(j.status not in ("running", "paused"))
        self.folder.setEnabled(bool(j.job_dir))
        if j.message and j.status == "failed":
            self.details.setToolTip(j.message)


class QueuePage(QWidget):
    open_in_studio = Signal(str)
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
        self.list_lay = QVBoxLayout(host)
        self.list_lay.setContentsMargins(0, 0, 8, 0)
        self.list_lay.setSpacing(8)
        self.list_lay.addStretch(1)
        root.addWidget(_scroll(host), 1)
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
        for p in paths_:
            self.controller.enqueue(p, self.settings_provider(), start=not self.controller.is_busy())

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
        settings = self.settings_provider()
        for p in paths:
            self.controller.enqueue(p, settings, start=not self.controller.is_busy())
        if paths:
            self.toast.emit(tr("ui.queue.added", n=len(paths)), "success")
        return len(paths)

    def dragEnterEvent(self, e):  # noqa: N802
        if has_images(e.mimeData()):
            e.acceptProposedAction()

    def dropEvent(self, e):  # noqa: N802
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
        settings = self.settings_provider()
        for p in images:
            self.controller.enqueue(p, settings, start=not self.controller.is_busy())
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
        for r in self.rows.values():
            r.setParent(None)
        self.rows.clear()
        for job in self.controller.jobs:
            row = QueueRow(job, self.controller)
            self.list_lay.insertWidget(self.list_lay.count() - 1, row)
            self.rows[job.id] = row
        self.empty.setVisible(not self.controller.jobs)
        self.run_btn.setEnabled(bool(self.controller.pending()) and not self.controller.is_busy())
        self.export_btn.setEnabled(any(j.status in ("done", "cancelled") and j.job_dir for j in self.controller.jobs))

    def _on_event(self, job, kind, data):
        if kind in ("iteration", "seed_done", "job_done") and job.id in self.rows:
            self.rows[job.id].refresh()

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
def set_favourite(job_dir: str, value: bool) -> None:
    """Mark a job as favourite (stored in its job.json)."""
    path = os.path.join(job_dir, "job.json")
    with open(path, encoding="utf-8") as f:
        summary = json.load(f)
    if value:
        summary["favourite"] = True
    else:
        summary.pop("favourite", None)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)


def move_to_trash(path: str) -> bool:
    """Move a file or folder to the recycle bin; False when the system does not allow it."""
    try:
        res = QFile.moveToTrash(path)
    except Exception:
        return False
    ok = res[0] if isinstance(res, tuple) else bool(res)
    return bool(ok) and not os.path.exists(path)


def _job_matches(job_dir: str, summary: dict, query: str) -> bool:
    if not query:
        return True
    method = job_method(summary)
    hay = " ".join((os.path.basename(job_dir), os.path.basename(summary.get("target", "")), method,
                    methods_ui.name(method))).lower()
    return all(word in hay for word in query.split())


class GalleryCard(Card):
    clicked = Signal(str)
    action = Signal(str, str)  # (kind, job folder): "folder", "favourite", "delete"

    def __init__(self, job_dir: str, summary: dict, parent=None, active: bool = False):
        super().__init__(parent, margins=12, spacing=8)
        self.job_dir = job_dir
        self.active = active  # the queue is working on it
        self.favourite = bool(summary.get("favourite"))
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedWidth(220)
        view = SketchCanvas()
        view.setFixedSize(196, 196)
        try:
            with open(jobs.best_sketch(summary), encoding="utf-8") as f:
                view.set_svg(f.read())
        except (OSError, KeyError):
            pass
        self.body.addWidget(view)
        name = os.path.splitext(os.path.basename(summary.get("target", job_dir)))[0]
        title = label(name, "h3")
        title.setToolTip(job_dir)
        self.body.addWidget(title)
        s = summary.get("settings", {})
        method = job_method(summary)
        self.method = method
        runs = summary.get("runs", [])
        meta = tr("ui.gallery.meta", strokes=schema.num_strokes({**s, "method": method}),
                  date=summary.get("created", "")[:16])
        self.body.addWidget(label(meta, "faint"))
        badges = QHBoxLayout()
        badges.setSpacing(6)
        badges.addWidget(method_badge(method))
        scores = [r["clip_score"] for r in runs if r.get("clip_score") is not None]
        if summary.get("clip_score") is not None or scores:
            badges.addWidget(label(f"CLIP {summary.get('clip_score') or max(scores):.1f}", "badge"))
        elif runs:
            badges.addWidget(label(f"Loss {min(r.get('best_loss', 99) for r in runs):.3f}", "badge"))
        badges.addStretch(1)
        self.body.addLayout(badges)
        self.can_continue = jobs.summary_can_continue(summary) and not active
        self.state_label = None
        if active:
            self.state_label = label(tr("ui.gallery.state_active"), "badge")
            self.body.addWidget(self.state_label, 0, Qt.AlignLeft)
        elif self.can_continue:
            done, total = summary["progress"]
            self.state_label = label(tr(f"ui.gallery.state_{summary['state']}", done=done, total=total),
                                     "badge-warning")
            self.body.addWidget(self.state_label, 0, Qt.AlignLeft)
        tools = QHBoxLayout()
        tools.setSpacing(2)
        p = theme.current()
        self.star = tool_button("star", tr("ui.gallery.favourite"), 16, checkable=True)
        self.star.setIcon(icons.icon("star", p.muted, active_color=p.warning))
        self.star.setChecked(self.favourite)
        self.star.toggled.connect(lambda on: self.action.emit("favourite", self.job_dir))
        self.folder = tool_button("folder-open", tr("ui.gallery.show_folder"), 16)
        self.folder.clicked.connect(lambda: self.action.emit("folder", self.job_dir))
        self.delete = tool_button("trash-2", tr("ui.gallery.delete"), 16)
        self.delete.clicked.connect(lambda: self.action.emit("delete", self.job_dir))
        self.delete.setEnabled(not active)
        tools.addWidget(self.star)
        tools.addStretch(1)
        self.cont = None
        if self.can_continue:
            self.cont = button(tr("ui.continue"), "play", "primary", size="sm")
            self.cont.clicked.connect(lambda: self.action.emit("continue", self.job_dir))
            tools.addWidget(self.cont)
        tools.addWidget(self.folder)
        tools.addWidget(self.delete)
        self.body.addLayout(tools)
        self.body.addStretch(1)
        self.setFixedHeight(self.sizeHint().height())

    def mouseReleaseEvent(self, e):  # noqa: N802
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit(self.job_dir)

    def contextMenuEvent(self, e):  # noqa: N802
        menu = QMenu(self)
        menu.addAction(icons.icon("brush"), tr("ui.gallery.open"), lambda: self.clicked.emit(self.job_dir))
        if self.can_continue:
            menu.addAction(icons.icon("play"), tr("ui.continue"), lambda: self.action.emit("continue", self.job_dir))
        menu.addAction(icons.icon("folder-open"), tr("ui.gallery.show_folder"),
                       lambda: self.action.emit("folder", self.job_dir))
        menu.addAction(icons.icon("copy"), tr("ui.copy"), lambda: self.action.emit("copy", self.job_dir))
        menu.addAction(icons.icon("star"), tr("ui.gallery.unfavourite" if self.favourite else "ui.gallery.favourite"),
                       self.star.toggle)
        menu.addSeparator()
        delete = menu.addAction(icons.icon("trash-2", theme.current().danger), tr("ui.gallery.delete"),
                                lambda: self.action.emit("delete", self.job_dir))
        delete.setEnabled(not self.active)
        menu.exec(e.globalPos())


class GalleryPage(QWidget):
    open_job = Signal(str)
    job_deleted = Signal(str)
    continue_job = Signal(str)
    toast = Signal(str, str)

    SORTS = ("newest", "score")

    def __init__(self, controller=None, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        self.controller = controller
        if controller is not None:  # new and finished results appear without "Refresh"
            controller.job_started.connect(lambda _: self._refresh_if_shown())
            controller.job_finished.connect(lambda _: self._refresh_if_shown())
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)
        head = QHBoxLayout()
        lay, self.title, self.subtitle = _page_header("ui.gallery.title", "ui.gallery.subtitle")
        head.addLayout(lay, 1)
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(240)
        self.search.textChanged.connect(self.refresh)
        self.filter = SegmentedControl([("all", "")] + [(m, methods_ui.name(m)) for m in schema.METHODS])
        self.filter.changed.connect(lambda _: self.refresh())
        self.fav_btn = button("", "star", "ghost")
        self.fav_btn.setCheckable(True)
        self.fav_btn.toggled.connect(lambda _: self.refresh())
        self.sort = QComboBox()
        self.sort.currentIndexChanged.connect(lambda _: self.refresh())
        self.folder_btn = button("", "folder-open", "ghost")
        self.folder_btn.clicked.connect(self._open_folder)
        self.export_btn = button("", "file-down", "ghost")
        self.export_btn.clicked.connect(lambda: dialogs.export_many(self, self.shown_items()))
        self.refresh_btn = button("", "refresh-cw")
        self.refresh_btn.clicked.connect(self.refresh)
        head.addWidget(self.export_btn, 0, Qt.AlignBottom)
        head.addWidget(self.folder_btn, 0, Qt.AlignBottom)
        head.addWidget(self.refresh_btn, 0, Qt.AlignBottom)
        root.addLayout(head)
        tools = QHBoxLayout()
        tools.setSpacing(10)
        tools.addWidget(self.filter)
        tools.addWidget(self.fav_btn)
        tools.addWidget(self.sort)
        tools.addStretch(1)
        tools.addWidget(self.search)
        root.addLayout(tools)
        self.host = QWidget()
        self.grid = QGridLayout(self.host)
        self.grid.setContentsMargins(0, 0, 8, 0)
        self.grid.setSpacing(14)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        root.addWidget(_scroll(self.host), 1)
        self.empty = label("", "muted")
        self.empty.setAlignment(Qt.AlignCenter)
        root.addWidget(self.empty)
        self.cards: list[GalleryCard] = []
        i18n.language_changed.connect(lambda _: self.retranslate())
        self.retranslate()

    def _open_folder(self):
        folder = app_settings().get("output_dir")
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _refresh_if_shown(self):
        if self.isVisible():
            QTimer.singleShot(0, self.refresh)

    def _active(self) -> set[str]:
        return self.controller.active_dirs() if self.controller is not None else set()

    def scan(self) -> list[tuple[str, dict]]:
        return scan_jobs(unfinished=True)

    def refresh(self):
        for c in self.cards:
            c.setParent(None)
        self.cards.clear()
        q = self.search.text().lower().strip()
        cols = max(1, (self.width() - 60) // 236)
        wanted = self.filter.current() or "all"
        items = [(d, s) for d, s in self.scan()
                 if _job_matches(d, s, q) and (wanted == "all" or job_method(s) == wanted)
                 and (not self.fav_btn.isChecked() or s.get("favourite"))]
        if self.SORTS[max(self.sort.currentIndex(), 0)] == "score":
            items.sort(key=lambda it: it[1].get("clip_score") if it[1].get("clip_score") is not None
                       else float("-inf"), reverse=True)
        self._shown = [(d, s) for d, s in items if jobs.best_sketch(s)]
        self.export_btn.setEnabled(bool(self._shown))
        active = self._active()
        for n, (job_dir, summary) in enumerate(items):
            card = GalleryCard(job_dir, summary, active=os.path.normcase(os.path.abspath(job_dir)) in active)
            card.clicked.connect(self.open_job.emit)
            card.action.connect(self._card_action)
            self.grid.addWidget(card, n // cols, n % cols)
            self.cards.append(card)
        self.empty.setVisible(not items)

    def shown_items(self) -> list[tuple[str, dict]]:
        """The results the gallery shows right now (filter, favourites, search) that have a sketch."""
        return list(getattr(self, "_shown", []))

    def _card_action(self, kind: str, job_dir: str):
        if kind == "folder":
            QDesktopServices.openUrl(QUrl.fromLocalFile(job_dir))
        elif kind == "copy":
            summary = jobs.job_summary(job_dir)
            src = jobs.best_sketch(summary) if summary else None
            if src and os.path.isfile(src):
                dialogs.copy_sketch(src)
                self.toast.emit(tr("ui.copied"), "success")
        elif kind == "continue":
            self.continue_job.emit(job_dir)
        elif kind == "favourite":
            card = next((c for c in self.cards if c.job_dir == job_dir), None)
            value = card.star.isChecked() if card else True
            try:
                set_favourite(job_dir, value)
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, tr("ui.error"), str(exc))
                return
            if card:
                card.favourite = value
            if self.fav_btn.isChecked() and not value:
                QTimer.singleShot(0, self.refresh)
        elif kind == "delete":
            self.delete_job(job_dir)

    def delete_job(self, job_dir: str, confirm: bool = True) -> bool:
        name = os.path.basename(os.path.normpath(job_dir))
        if os.path.normcase(os.path.abspath(job_dir)) in self._active():
            QMessageBox.information(self, tr("ui.gallery.delete"), tr("ui.gallery.delete_active", name=name))
            return False
        if confirm and QMessageBox.question(self, tr("ui.gallery.delete"),
                                            tr("ui.gallery.delete_q", name=name)) != QMessageBox.Yes:
            return False
        if not move_to_trash(job_dir):
            if confirm and QMessageBox.question(self, tr("ui.gallery.delete"),
                                                tr("ui.gallery.delete_permanently_q", name=name)) != QMessageBox.Yes:
                return False
            try:
                shutil.rmtree(job_dir)
            except OSError as exc:
                QMessageBox.warning(self, tr("ui.error"), str(exc))
                return False
        self.job_deleted.emit(job_dir)
        QTimer.singleShot(0, self.refresh)  # not from within the card that asked
        return True

    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        QTimer.singleShot(0, self.refresh)

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        if self.cards:
            cols = max(1, (self.width() - 60) // 236)
            for i, c in enumerate(self.cards):
                self.grid.addWidget(c, i // cols, i % cols)

    def retranslate(self):
        self.title.setText(tr("ui.gallery.title"))
        self.subtitle.setText(tr("ui.gallery.subtitle"))
        self.search.setPlaceholderText(tr("ui.gallery.search"))
        self.filter.set_text("all", tr("ui.gallery.all"))
        self.fav_btn.setText(tr("ui.gallery.favourites"))
        self.fav_btn.setToolTip(tr("ui.gallery.favourites_tip"))
        index = max(self.sort.currentIndex(), 0)
        self.sort.blockSignals(True)
        self.sort.clear()
        self.sort.addItems([tr(f"ui.gallery.sort_{k}") for k in self.SORTS])
        self.sort.setCurrentIndex(index)
        self.sort.blockSignals(False)
        self.folder_btn.setText(tr("ui.open_folder"))
        self.export_btn.setText(tr("ui.batch.export_shown"))
        self.export_btn.setToolTip(tr("ui.batch.export_shown_tip"))
        self.refresh_btn.setText(tr("ui.refresh"))
        self.empty.setText(tr("ui.gallery.empty"))


# ===================================================================== models
MODEL_PURPOSE = {
    "clip:RN101": "ui.models.purpose.rn101", "clip:ViT-B/32": "ui.models.purpose.vitb32",
    "u2net": "ui.models.purpose.u2net", "dino": "ui.models.purpose.dino", "vgg16": "ui.models.purpose.vgg16",
    "swiftsketch:diffusion": "ui.models.purpose.ss_diffusion", "swiftsketch:refine": "ui.models.purpose.ss_refine",
    "sd15": "ui.models.purpose.sd15", "dpt-hybrid": "ui.models.purpose.dpt", "hed": "ui.models.purpose.hed",
    "upernet": "ui.models.purpose.upernet", "blip": "ui.models.purpose.blip", "sdxl": "ui.models.purpose.sdxl",
    "lama": "ui.models.purpose.lama", "birefnet": "ui.models.purpose.birefnet",
    "birefnet-lite": "ui.models.purpose.birefnet-lite",
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy_check = lambda: False  # the main window: is a job running?
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
        self.behaviour.body.addLayout(self._row(self.updates_label, self.updates))
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
        col.addWidget(self.behaviour)

        self.system = Card()
        self.system_title = label("", "h2")
        self.system.body.addWidget(self.system_title)
        self.system_info = label("", "mono", wrap=True)
        self.system_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.system.body.addWidget(self.system_info)
        self.logs_btn = button("", "folder-open", "ghost")
        self.logs_btn.clicked.connect(crash.open_logs_folder)
        self.system.body.addWidget(self.logs_btn, 0, Qt.AlignLeft)
        col.addWidget(self.system)
        col.addStretch(1)
        root.addWidget(_scroll(host), 1)
        self._gpu_text = ""
        i18n.language_changed.connect(lambda _: self.retranslate())
        self.retranslate()
        QTimer.singleShot(1500, self._probe_hardware)

    @staticmethod
    def _row(lbl, widget):
        r = QHBoxLayout()
        r.addWidget(lbl)
        r.addStretch(1)
        r.addWidget(widget)
        return r

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

    def _choose_out(self):
        d = QFileDialog.getExistingDirectory(self, tr("ui.settings.output"), self.out_edit.text())
        if d:
            self.out_edit.setText(d)
            app_settings().set("output_dir", d)

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

    def _probe_hardware(self):
        def probe(progress=None):
            import torch

            lines = [f"PyTorch {torch.__version__}"]
            if torch.cuda.is_available():
                from ...engine.pipeline import cuda_arch_supported

                for i in range(torch.cuda.device_count()):
                    prop = torch.cuda.get_device_properties(i)
                    ok = "" if cuda_arch_supported(i) else f"  ⚠ {tr('ui.settings.gpu_unsupported')}"
                    lines.append(f"GPU {i}: {prop.name} · {prop.total_memory / 2 ** 30:.1f} GB{ok}")
            elif torch.version.cuda:
                lines.append(f"CUDA {torch.version.cuda}: {tr('ui.settings.gpu_none')}")
            else:
                lines.append("CUDA: –")
            return "\n".join(lines)

        dialogs.run_in_thread(self, probe, on_done=self._set_gpu, on_error=self._set_gpu)

    def _set_gpu(self, text):
        self._gpu_text = text
        self.retranslate()

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
        self.warm_label.setText(tr("ui.settings.keep_models"))
        self.warm_label.setToolTip(tr("ui.settings.keep_models_tip"))
        self.warm.setToolTip(tr("ui.settings.keep_models_tip"))
        self.parallel_label.setText(tr("ui.settings.parallel"))
        self.parallel_label.setToolTip(tr("ui.settings.parallel_tip"))
        self.parallel.setToolTip(tr("ui.settings.parallel_tip"))
        self.logs_btn.setText(tr("ui.crash.open_logs"))
        self.logs_btn.setToolTip(tr("ui.settings.logs_tip"))
        self.system_title.setText(tr("ui.settings.system"))
        edition = tr(f"ui.edition.{EDITION}")
        info = [f"{APP_NAME} {__version__} · {edition}",
                f"{platform.system()} {platform.release()} · Python {platform.python_version()}",
                f"CPU: {os.cpu_count()} {tr('ui.threads')}"]
        if self._gpu_text:
            info.append(self._gpu_text)
        info.append(f"{tr('ui.models.title')}: {paths.bundled_models_dir()}")
        self.system_info.setText("\n".join(info))


# ====================================================================== about
class AboutPage(QWidget):
    show_tour = Signal()

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
        top.addWidget(self.tour_btn, 0, Qt.AlignTop)
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

