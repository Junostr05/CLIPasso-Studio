"""Queue, gallery, models, settings and about pages."""

from __future__ import annotations

import json
import os
import platform

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QProgressBar, QScrollArea, QVBoxLayout, QWidget)

from ... import APP_NAME, __version__, paths
from ...engine import model_store
from .. import dialogs, icons, theme
from ..app_settings import app_settings
from ..controller import JobController, QueuedJob
from ..i18n import LANGUAGES, i18n, tr
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
        self.details = label(tr("ui.queue.details", strokes=s["num_paths"], iters=s["num_iter"],
                                sketches=s["num_sketches"]), "faint")
        info.addWidget(self.name)
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

    def __init__(self, controller: JobController, settings_provider, parent=None):
        super().__init__(parent)
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
        self.clear_btn = button("", "trash-2", "ghost")
        self.clear_btn.clicked.connect(controller.clear_finished)
        self.run_btn = button("", "play")
        self.run_btn.clicked.connect(lambda: controller.start_next())
        head.addWidget(self.clear_btn, 0, Qt.AlignBottom)
        head.addWidget(self.run_btn, 0, Qt.AlignBottom)
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

    def _on_event(self, job, kind, data):
        if kind in ("iteration", "seed_done", "job_done") and job.id in self.rows:
            self.rows[job.id].refresh()

    def retranslate(self):
        self.title.setText(tr("ui.queue.title"))
        self.subtitle.setText(tr("ui.queue.subtitle"))
        self.add_btn.setText(tr("ui.queue.add"))
        self.clear_btn.setText(tr("ui.queue.clear"))
        self.run_btn.setText(tr("ui.queue.run"))
        self.auto_label.setText(tr("ui.queue.auto"))
        self.empty.setText(tr("ui.queue.empty"))
        self.rebuild()


# ==================================================================== gallery
class GalleryCard(Card):
    clicked = Signal(str)

    def __init__(self, job_dir: str, summary: dict, parent=None):
        super().__init__(parent, margins=12, spacing=8)
        self.job_dir = job_dir
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedWidth(220)
        view = SketchCanvas()
        view.setFixedSize(196, 196)
        try:
            with open(summary["best_svg"], encoding="utf-8") as f:
                view.set_svg(f.read())
        except (OSError, KeyError):
            pass
        self.body.addWidget(view)
        name = os.path.splitext(os.path.basename(summary.get("target", job_dir)))[0]
        self.body.addWidget(label(name, "h3"))
        s = summary.get("settings", {})
        runs = summary.get("runs", [])
        best = min((r.get("best_loss", 99) for r in runs), default=None)
        meta = tr("ui.gallery.meta", strokes=s.get("num_paths", "?"), date=summary.get("created", "")[:16])
        self.body.addWidget(label(meta, "faint"))
        if best is not None:
            self.body.addWidget(label(f"Loss {best:.3f}", "badge"), 0, Qt.AlignLeft)
        self.body.addStretch(1)
        self.setFixedHeight(self.sizeHint().height())

    def mouseReleaseEvent(self, e):  # noqa: N802
        self.clicked.emit(self.job_dir)


class GalleryPage(QWidget):
    open_job = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)
        head = QHBoxLayout()
        lay, self.title, self.subtitle = _page_header("ui.gallery.title", "ui.gallery.subtitle")
        head.addLayout(lay, 1)
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(220)
        self.search.textChanged.connect(self.refresh)
        self.folder_btn = button("", "folder-open", "ghost")
        self.folder_btn.clicked.connect(self._open_folder)
        self.refresh_btn = button("", "refresh-cw")
        self.refresh_btn.clicked.connect(self.refresh)
        head.addWidget(self.search, 0, Qt.AlignBottom)
        head.addWidget(self.folder_btn, 0, Qt.AlignBottom)
        head.addWidget(self.refresh_btn, 0, Qt.AlignBottom)
        root.addLayout(head)
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

    def scan(self) -> list[tuple[str, dict]]:
        root = app_settings().get("output_dir")
        items = []
        if not root or not os.path.isdir(root):
            return items
        for name in os.listdir(root):
            d = os.path.join(root, name)
            f = os.path.join(d, "job.json")
            if os.path.isfile(f):
                try:
                    with open(f, encoding="utf-8") as fh:
                        items.append((d, json.load(fh)))
                except (OSError, ValueError):
                    continue
        items.sort(key=lambda t: t[1].get("created", ""), reverse=True)
        return items

    def refresh(self):
        for c in self.cards:
            c.setParent(None)
        self.cards.clear()
        q = self.search.text().lower().strip()
        cols = max(1, (self.width() - 60) // 236)
        n = 0
        for job_dir, summary in self.scan():
            if q and q not in job_dir.lower():
                continue
            card = GalleryCard(job_dir, summary)
            card.clicked.connect(self.open_job.emit)
            self.grid.addWidget(card, n // cols, n % cols)
            self.cards.append(card)
            n += 1
        self.empty.setVisible(n == 0)

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
        self.folder_btn.setText(tr("ui.open_folder"))
        self.refresh_btn.setText(tr("ui.refresh"))
        self.empty.setText(tr("ui.gallery.empty"))


# ===================================================================== models
MODEL_PURPOSE = {
    "clip:RN101": "ui.models.purpose.rn101", "clip:ViT-B/32": "ui.models.purpose.vitb32",
    "u2net": "ui.models.purpose.u2net", "dino": "ui.models.purpose.dino", "vgg16": "ui.models.purpose.vgg16",
}


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
        self.size = label(f"{spec.stored_size_mb} MB", "muted")
        row.addWidget(self.size)
        self.state = label("", "badge")
        row.addWidget(self.state)
        self.action = button("", "download")
        self.action.clicked.connect(self._action)
        row.addWidget(self.action)
        self.body.addLayout(row)
        self.refresh()

    def refresh(self):
        spec = model_store.SPECS[self.key]
        found = model_store.find(self.key)
        bundled = found is not None and str(paths.bundled_models_dir()) in str(found)
        self.desc.setText(tr(MODEL_PURPOSE.get(self.key, "ui.models.purpose.clip_extra")))
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
            self.action.setText(tr("ui.download") + f" ({spec.download_size / 1e6:.0f} MB)")
            self.action.setIcon(icons.icon("download", theme.current().text))
        self.state.style().unpolish(self.state)
        self.state.style().polish(self.state)

    def _action(self):
        if model_store.find(self.key):
            if QMessageBox.question(self, tr("ui.models.remove"), tr("ui.models.remove_q")) == QMessageBox.Yes:
                model_store.uninstall(self.key)
        else:
            dialogs.ask_download_missing(self, [self.key])
        self.page.refresh()


class ModelsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)
        lay, self.title, self.subtitle = _page_header("ui.models.title", "ui.models.subtitle")
        root.addLayout(lay)
        host = QWidget()
        self.list_lay = QVBoxLayout(host)
        self.list_lay.setContentsMargins(0, 0, 8, 0)
        self.list_lay.setSpacing(8)
        self.bundled_title = label("", "h2")
        self.optional_title = label("", "h2")
        self.rows = []
        self.list_lay.addWidget(self.bundled_title)
        for key, spec in model_store.SPECS.items():
            if spec.bundled:
                r = ModelRow(key, self)
                self.rows.append(r)
                self.list_lay.addWidget(r)
        self.list_lay.addSpacing(10)
        self.list_lay.addWidget(self.optional_title)
        for key, spec in model_store.SPECS.items():
            if not spec.bundled:
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
        self.bundled_title.setText(tr("ui.models.bundled_title"))
        self.optional_title.setText(tr("ui.models.optional_title"))
        self.location.setText(tr("ui.models.location", path=str(paths.downloaded_models_dir())))
        self.refresh()


# =================================================================== settings
class SettingsPage(QWidget):
    theme_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
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
        col.addWidget(self.behaviour)

        self.system = Card()
        self.system_title = label("", "h2")
        self.system.body.addWidget(self.system_title)
        self.system_info = label("", "mono", wrap=True)
        self.system_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.system.body.addWidget(self.system_info)
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

    def _theme_changed(self, mode):
        app_settings().set("theme", mode)
        self.theme_changed.emit(mode)

    def _choose_out(self):
        d = QFileDialog.getExistingDirectory(self, tr("ui.settings.output"), self.out_edit.text())
        if d:
            self.out_edit.setText(d)
            app_settings().set("output_dir", d)

    def _probe_hardware(self):
        def probe(progress=None):
            import torch

            lines = [f"PyTorch {torch.__version__}"]
            if torch.cuda.is_available():
                for i in range(torch.cuda.device_count()):
                    prop = torch.cuda.get_device_properties(i)
                    lines.append(f"GPU {i}: {prop.name} · {prop.total_memory / 2 ** 30:.1f} GB")
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
        self.theme_label.setText(tr("ui.settings.theme"))
        for k in ("dark", "light", "system"):
            self.theme_seg.set_text(k, tr(f"ui.theme.{k}"))
        self.files_title.setText(tr("ui.settings.files"))
        self.out_label.setText(tr("ui.settings.output"))
        self.out_btn.setText(tr("ui.change"))
        self.behaviour_title.setText(tr("ui.settings.behaviour"))
        self.awake_label.setText(tr("ui.settings.keep_awake"))
        self.notify_label.setText(tr("ui.settings.notify"))
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
        t.addWidget(self.name)
        t.addWidget(self.version)
        top.addLayout(t, 1)
        hero.body.addLayout(top)
        self.desc = label("", None, wrap=True)
        hero.body.addWidget(self.desc)
        links = QHBoxLayout()
        for key, url in (("ui.about.paper", "https://arxiv.org/abs/2202.05822"),
                         ("ui.about.project", "https://clipasso.github.io/clipasso/"),
                         ("ui.about.code", "https://github.com/yael-vinker/CLIPasso")):
            b = button(tr(key), "external-link", "ghost")
            b.clicked.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            b.setProperty("i18n", key)
            links.addWidget(b)
        links.addStretch(1)
        self.links = links
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
        self.desc.setText(tr("ui.about.desc"))
        for i in range(self.links.count()):
            w = self.links.itemAt(i).widget()
            if w is not None and w.property("i18n"):
                w.setText(tr(w.property("i18n")))
        self.credits_title.setText(tr("ui.about.credits"))
        self.credits_text.setText(tr("ui.about.credits_text"))
        self.license_title.setText(tr("ui.about.license"))
        self.license_text.setText(tr("ui.about.license_text"))

