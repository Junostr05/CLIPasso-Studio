"""Gallery: all results as a grid of painted tiles (model / view instead of one widget per result).

Many results stay quick: the job folders are read again only when they changed, the sketch previews
are kept on disk, and only the visible tiles are painted. Several results can be selected (Ctrl / Shift
/ rubber band) to delete, export or mark them; every result can get its own name, notes and tags
(``meta.json`` in its folder).
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

from PySide6.QtCore import (QAbstractListModel, QEvent, QItemSelectionModel, QModelIndex, QRect, QRectF, QSize, Qt,
                            QTimer, QUrl, Signal)
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLineEdit,
                               QListView, QMenu, QMessageBox, QPlainTextEdit, QStyle, QStyledItemDelegate,
                               QVBoxLayout, QWidget)

from ... import settings_schema as schema
from ...engine import jobs
from .. import dialogs, icons, methods_ui, theme, thumbs
from ..app_settings import app_settings
from ..i18n import i18n, tr
from ..widgets.common import SegmentedControl, button, label
from .other_pages import _page_header, job_method, move_to_trash

SORTS = ("newest", "oldest", "score", "duration", "strokes", "name")
TILE = QSize(212, 292)
THUMB = 188
ITEM_ROLE = Qt.UserRole + 1


def set_favourite(job_dir: str, value: bool) -> None:
    """Mark a job as favourite (``meta.json``; kept when the job is continued)."""
    jobs.write_meta(job_dir, favourite=bool(value))


@dataclass
class GalleryItem:
    job_dir: str
    summary: dict
    active: bool = False  # the queue is working on it

    @property
    def method(self) -> str:
        return job_method(self.summary)

    @property
    def name(self) -> str:
        title = str(self.summary.get("title") or "").strip()
        return title or os.path.splitext(os.path.basename(self.summary.get("target") or self.job_dir))[0]

    @property
    def favourite(self) -> bool:
        return bool(self.summary.get("favourite"))

    @property
    def tags(self) -> list[str]:
        tags = self.summary.get("tags") or []
        return [str(t) for t in tags] if isinstance(tags, list) else []

    @property
    def notes(self) -> str:
        return str(self.summary.get("notes") or "")

    @property
    def created(self) -> str:
        return str(self.summary.get("created") or "")

    @property
    def score(self) -> float | None:
        if self.summary.get("clip_score") is not None:
            return float(self.summary["clip_score"])
        scores = [r["clip_score"] for r in self.summary.get("runs", []) if r.get("clip_score") is not None]
        return max(scores) if scores else None

    @property
    def loss(self) -> float | None:
        losses = [r.get("best_loss", 99) for r in self.summary.get("runs", [])]
        return min(losses) if losses else None

    @property
    def seconds(self) -> float:
        if self.summary.get("seconds"):
            return float(self.summary["seconds"])
        return float(sum(r.get("seconds", 0) or 0 for r in self.summary.get("runs", [])))

    @property
    def strokes(self) -> int:
        return schema.num_strokes({**(self.summary.get("settings") or {}), "method": self.method})

    @property
    def sketch(self) -> str:
        return jobs.best_sketch(self.summary)

    @property
    def can_continue(self) -> bool:
        return jobs.summary_can_continue(self.summary) and not self.active

    def matches(self, words: list[str]) -> bool:
        hay = " ".join((self.name, os.path.basename(self.job_dir), os.path.basename(self.summary.get("target", "")),
                        self.method, methods_ui.name(self.method), " ".join(self.tags), self.notes)).lower()
        return all(w in hay for w in words)


class ScanCache:
    """The jobs of the output folder; a finished job is read again only when one of its files changed."""

    def __init__(self):
        self._entries: dict[str, tuple[tuple, dict]] = {}

    @staticmethod
    def _stamp(job_dir: str) -> tuple:
        out = []
        for name in ("job.json", jobs.STATE_FILE, jobs.META_FILE):
            try:
                st = os.stat(os.path.join(job_dir, name))
                out.append((st.st_mtime_ns, st.st_size))
            except OSError:
                out.append(None)
        return tuple(out)

    def scan(self, root: str) -> list[tuple[str, dict]]:
        items = []
        if not root or not os.path.isdir(root):
            return items
        seen = set()
        for name in os.listdir(root):
            d = os.path.join(root, name)
            stamp = self._stamp(d)
            if stamp[0] is None and stamp[1] is None:
                continue  # no job folder
            seen.add(d)
            cached = self._entries.get(d)
            # unfinished jobs (no job.json) are always read: their sketches appear one by one
            if cached is not None and cached[0] == stamp and stamp[0] is not None:
                summary = cached[1]
            else:
                summary = jobs.job_summary(d)
                if summary is None:
                    continue
                self._entries[d] = (stamp, summary)
            items.append((d, summary))
        for d in [d for d in self._entries if d not in seen]:
            del self._entries[d]
        return items


class GalleryModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[GalleryItem] = []

    def set_items(self, items: list[GalleryItem]) -> None:
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()

    def items(self) -> list[GalleryItem]:
        return list(self._items)

    def item(self, row: int) -> GalleryItem | None:
        return self._items[row] if 0 <= row < len(self._items) else None

    def row_of(self, job_dir: str) -> int:
        return next((i for i, it in enumerate(self._items) if it.job_dir == job_dir), -1)

    def changed(self, row: int) -> None:
        self.dataChanged.emit(self.index(row), self.index(row))

    def rowCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(self._items)

    def data(self, index, role=Qt.DisplayRole):
        it = self.item(index.row()) if index.isValid() else None
        if it is None:
            return None
        if role == Qt.DisplayRole:
            return it.name
        if role == Qt.ToolTipRole:
            return "\n".join(x for x in (it.job_dir, ", ".join(it.tags), it.notes) if x)
        if role == ITEM_ROLE:
            return it
        return None


class GalleryDelegate(QStyledItemDelegate):
    """Paints a result tile: the sketch, its name, details, badges, the favourite star and a "Continue"
    button for interrupted jobs."""

    star_clicked = Signal(int)
    continue_clicked = Signal(int)

    PAD = 10

    def sizeHint(self, option, index):  # noqa: N802
        return TILE

    def _rects(self, rect: QRect):
        r = rect.adjusted(4, 4, -4, -4)
        thumb = QRect(r.left() + self.PAD, r.top() + self.PAD, r.width() - 2 * self.PAD, THUMB)
        star = QRect(r.right() - self.PAD - 22, r.bottom() - self.PAD - 22, 22, 22)
        cont = QRect(r.left() + self.PAD, r.bottom() - self.PAD - 24, 96, 24)
        return r, thumb, star, cont

    def paint(self, painter: QPainter, option, index):
        it: GalleryItem = index.data(ITEM_ROLE)
        if it is None:
            return
        pal = theme.current()
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        r, thumb, star, cont = self._rects(option.rect)
        selected = bool(option.state & QStyle.State_Selected)
        hover = bool(option.state & QStyle.State_MouseOver)
        path = QPainterPath()
        path.addRoundedRect(QRectF(r), 12, 12)
        painter.fillPath(path, QColor(pal.surface2 if hover or selected else pal.surface))
        painter.setPen(QPen(QColor(pal.accent if selected else pal.border), 2 if selected else 1))
        painter.drawPath(path)
        # the sketch
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(thumb), 8, 8)
        painter.fillPath(clip, QColor(pal.paper))
        sketch = it.sketch
        if sketch and os.path.isfile(sketch):
            pm = thumbs.sketch_thumbnail(sketch, THUMB, app_settings().get("canvas_style", "plain"))
            if not pm.isNull():
                painter.save()
                painter.setClipPath(clip)
                painter.drawPixmap(thumb, pm)
                painter.restore()
        # name and details
        y = thumb.bottom() + 8
        font = QFont(painter.font())
        font.setBold(True)
        font.setPointSizeF(max(font.pointSizeF(), 9.0) + 1)
        painter.setFont(font)
        painter.setPen(QColor(pal.text))
        line = QRect(r.left() + self.PAD, y, r.width() - 2 * self.PAD, 22)
        painter.drawText(line, Qt.AlignLeft | Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(it.name, Qt.ElideRight, line.width()))
        font.setBold(False)
        font.setPointSizeF(font.pointSizeF() - 1.5)
        painter.setFont(font)
        painter.setPen(QColor(pal.faint))
        meta = tr("ui.gallery.meta_line", date=it.created[:16]) if it.strokes == 1 else \
            tr("ui.gallery.meta", strokes=it.strokes, date=it.created[:16])
        line = QRect(r.left() + self.PAD, y + 22, r.width() - 2 * self.PAD, 18)
        painter.drawText(line, Qt.AlignLeft | Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(meta, Qt.ElideRight, line.width()))
        # badges: method, score / loss, state
        x = r.left() + self.PAD
        badges = [(methods_ui.name(it.method), pal.accent_soft, pal.text)]
        if it.score is not None:
            badges.append((f"CLIP {it.score:.1f}", pal.surface3, pal.text))
        elif it.loss is not None:
            badges.append((f"Loss {it.loss:.3f}", pal.surface3, pal.text))
        if it.active:
            badges.append((tr("ui.gallery.state_active"), pal.accent, pal.on_accent))
        elif it.can_continue:
            done, total = it.summary.get("progress") or (0, 0)
            badges.append((tr(f"ui.gallery.state_{it.summary.get('state')}", done=done, total=total), pal.warning,
                           "#111111"))
        for tag in it.tags[:2]:
            badges.append((f"#{tag}", pal.surface3, pal.muted))
        fm = painter.fontMetrics()
        by = y + 44
        for text, bg, fg in badges:
            w = fm.horizontalAdvance(text) + 12
            if x + w > r.right() - self.PAD:
                break
            rect = QRectF(x, by, w, 20)
            badge = QPainterPath()
            badge.addRoundedRect(rect, 6, 6)
            painter.fillPath(badge, QColor(bg))
            painter.setPen(QColor(fg))
            painter.drawText(rect, Qt.AlignCenter, text)
            x += w + 6
        # continue button and favourite star
        if it.can_continue:
            button_path = QPainterPath()
            button_path.addRoundedRect(QRectF(cont), 7, 7)
            painter.fillPath(button_path, QColor(pal.accent))
            painter.setPen(QColor(pal.on_accent))
            painter.drawText(cont, Qt.AlignCenter, tr("ui.continue"))
        icon = icons.pixmap("star", pal.warning if it.favourite else pal.faint, 18)
        painter.drawPixmap(star.left() + 2, star.top() + 2, 18, 18, icon)
        painter.restore()

    def editorEvent(self, event, model, option, index):  # noqa: N802
        if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            _, _, star, cont = self._rects(option.rect)
            pos = event.position().toPoint()
            it = index.data(ITEM_ROLE)
            if star.contains(pos):
                self.star_clicked.emit(index.row())
                return True
            if it is not None and it.can_continue and cont.contains(pos):
                self.continue_clicked.emit(index.row())
                return True
        return super().editorEvent(event, model, option, index)


class GalleryView(QListView):
    open_requested = Signal(int)
    delete_requested = Signal()
    favourite_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setWrapping(True)
        self.setUniformItemSizes(True)
        self.setSpacing(6)
        self.setGridSize(QSize(TILE.width() + 6, TILE.height() + 6))
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionRectVisible(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(24)
        self.setMouseTracking(True)
        self.setFrameShape(QListView.NoFrame)
        self.setStyleSheet("QListView { background: transparent; }")
        self.doubleClicked.connect(lambda index: self.open_requested.emit(index.row()))

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and self.currentIndex().isValid():
            self.open_requested.emit(self.currentIndex().row())
        elif e.key() == Qt.Key_Delete:
            self.delete_requested.emit()
        elif e.key() == Qt.Key_F and not e.modifiers():
            self.favourite_requested.emit()
        else:
            super().keyPressEvent(e)


class JobInfoDialog(QDialog):
    """Name, tags and notes of a result."""

    def __init__(self, item: GalleryItem, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("ui.gallery.info_title"))
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(12)
        lay.addWidget(label(tr("ui.gallery.info_title"), "h2"))
        form = QFormLayout()
        form.setSpacing(10)
        self.name = QLineEdit(str(item.summary.get("title") or ""))
        self.name.setPlaceholderText(os.path.splitext(os.path.basename(item.summary.get("target") or ""))[0])
        form.addRow(tr("ui.gallery.info_name"), self.name)
        self.tags = QLineEdit(", ".join(item.tags))
        self.tags.setPlaceholderText(tr("ui.gallery.info_tags_hint"))
        form.addRow(tr("ui.gallery.info_tags"), self.tags)
        self.notes = QPlainTextEdit(item.notes)
        self.notes.setFixedHeight(110)
        form.addRow(tr("ui.gallery.info_notes"), self.notes)
        lay.addLayout(form)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = button(tr("ui.cancel"), variant="ghost")
        cancel.clicked.connect(self.reject)
        ok = button(tr("ui.save"), "check", "primary")
        ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)

    def values(self) -> dict:
        tags = []
        for t in self.tags.text().replace(";", ",").split(","):
            t = t.strip().lstrip("#")
            if t and t not in tags:
                tags.append(t)
        return {"title": self.name.text().strip() or None, "tags": tags or None,
                "notes": self.notes.toPlainText().strip() or None}


class GalleryPage(QWidget):
    open_job = Signal(str)
    job_deleted = Signal(str)
    continue_job = Signal(str)
    toast = Signal(str, str)

    SORTS = SORTS

    def __init__(self, controller=None, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        self.controller = controller
        self._cache = ScanCache()
        self._all: list[GalleryItem] = []
        if controller is not None:  # new and finished results appear without "Refresh"
            controller.job_started.connect(lambda _: self._refresh_if_shown())
            controller.job_finished.connect(lambda _: self._refresh_if_shown())
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)
        head = QHBoxLayout()
        lay, self.title, self.subtitle = _page_header("ui.gallery.title", "ui.gallery.subtitle")
        head.addLayout(lay, 1)
        self.folder_btn = button("", "folder-open", "ghost")
        self.folder_btn.clicked.connect(self._open_folder)
        self.export_btn = button("", "file-down", "ghost")
        self.export_btn.clicked.connect(self.export_items)
        self.refresh_btn = button("", "refresh-cw")
        self.refresh_btn.clicked.connect(self.refresh)
        for b in (self.export_btn, self.folder_btn, self.refresh_btn):
            head.addWidget(b, 0, Qt.AlignBottom)
        root.addLayout(head)

        tools = QHBoxLayout()
        tools.setSpacing(10)
        self.filter = SegmentedControl([("all", "")] + [(m, methods_ui.name(m)) for m in schema.METHODS])
        self.filter.changed.connect(lambda _: self._apply())
        self.fav_btn = button("", "star", "ghost")
        self.fav_btn.setCheckable(True)
        self.fav_btn.toggled.connect(lambda _: self._apply())
        self.tag_filter = QComboBox()
        self.tag_filter.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.tag_filter.currentIndexChanged.connect(lambda _: self._apply())
        self.sort = QComboBox()
        self.sort.currentIndexChanged.connect(lambda _: self._apply())
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(240)
        self._search_timer = QTimer(self, singleShot=True, interval=200)  # typing does not refilter every key
        self._search_timer.timeout.connect(self._apply)
        self.search.textChanged.connect(lambda _: self._search_timer.start())
        for w in (self.filter, self.fav_btn, self.tag_filter, self.sort):
            tools.addWidget(w)
        tools.addStretch(1)
        tools.addWidget(self.search)
        root.addLayout(tools)

        # actions for the selected results
        self.selection_bar = QWidget()
        sb = QHBoxLayout(self.selection_bar)
        sb.setContentsMargins(0, 0, 0, 0)
        sb.setSpacing(8)
        self.selection_label = label("", "muted")
        self.sel_fav_btn = button("", "star", "ghost", size="sm")
        self.sel_fav_btn.clicked.connect(self.toggle_favourite_selected)
        self.sel_export_btn = button("", "file-down", "ghost", size="sm")
        self.sel_export_btn.clicked.connect(lambda: self.export_items(self.selected_items()))
        self.sel_delete_btn = button("", "trash-2", "ghost", size="sm")
        self.sel_delete_btn.clicked.connect(self.delete_selected)
        sb.addWidget(self.selection_label)
        sb.addStretch(1)
        for b in (self.sel_fav_btn, self.sel_export_btn, self.sel_delete_btn):
            sb.addWidget(b)
        self.selection_bar.setVisible(False)
        root.addWidget(self.selection_bar)

        self.model = GalleryModel(self)
        self.view = GalleryView()
        self.view.setModel(self.model)
        self.delegate = GalleryDelegate(self.view)
        self.view.setItemDelegate(self.delegate)
        self.delegate.star_clicked.connect(self._star_clicked)
        self.delegate.continue_clicked.connect(lambda row: self.continue_job.emit(self.model.item(row).job_dir))
        self.view.open_requested.connect(lambda row: self.open_job.emit(self.model.item(row).job_dir))
        self.view.delete_requested.connect(self.delete_selected)
        self.view.favourite_requested.connect(self.toggle_favourite_selected)
        self.view.selectionModel().selectionChanged.connect(lambda *_: self._selection_changed())
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._context_menu)
        root.addWidget(self.view, 1)
        self.empty = label("", "muted")
        self.empty.setAlignment(Qt.AlignCenter)
        root.addWidget(self.empty)
        i18n.language_changed.connect(lambda _: self.retranslate())
        self.retranslate()

    # ------------------------------------------------------------------ data
    def _open_folder(self):
        folder = app_settings().get("output_dir")
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _refresh_if_shown(self):
        if self.isVisible():
            QTimer.singleShot(0, self.refresh)

    def _active(self) -> set[str]:
        return self.controller.active_dirs() if self.controller is not None else set()

    def refresh(self):
        """Read the output folder again (changed jobs only) and show the results."""
        active = self._active()
        self._all = [GalleryItem(d, s, os.path.normcase(os.path.abspath(d)) in active)
                     for d, s in self._cache.scan(app_settings().get("output_dir"))]
        self._update_tags()
        self._apply()

    def _update_tags(self):
        current = self.tag_filter.currentData()
        tags = sorted({t for it in self._all for t in it.tags}, key=str.lower)
        self.tag_filter.blockSignals(True)
        self.tag_filter.clear()
        self.tag_filter.addItem(tr("ui.gallery.all_tags"), "")
        for t in tags:
            self.tag_filter.addItem(f"#{t}", t)
        self.tag_filter.setCurrentIndex(max(self.tag_filter.findData(current or ""), 0))
        self.tag_filter.setVisible(bool(tags))
        self.tag_filter.blockSignals(False)

    def _apply(self):
        """Filter, search and sort the scanned results (no disk access)."""
        selected = {it.job_dir for it in self.selected_items()}
        words = self.search.text().lower().split()
        wanted = self.filter.current() or "all"
        tag = self.tag_filter.currentData() or ""
        items = [it for it in self._all
                 if it.matches(words) and (wanted == "all" or it.method == wanted)
                 and (not self.fav_btn.isChecked() or it.favourite) and (not tag or tag in it.tags)]
        sort = SORTS[max(self.sort.currentIndex(), 0)]
        if sort == "newest":
            items.sort(key=lambda it: it.created, reverse=True)
        elif sort == "oldest":
            items.sort(key=lambda it: it.created)
        elif sort == "score":
            items.sort(key=lambda it: (it.score is not None, it.score or 0.0), reverse=True)
        elif sort == "duration":
            items.sort(key=lambda it: it.seconds, reverse=True)
        elif sort == "strokes":
            items.sort(key=lambda it: it.strokes)
        else:
            items.sort(key=lambda it: it.name.lower())
        self.model.set_items(items)
        for row, it in enumerate(items):
            if it.job_dir in selected:
                self.view.selectionModel().select(self.model.index(row), QItemSelectionModel.Select)
        self.export_btn.setEnabled(bool(self.shown_items()))
        self.empty.setVisible(not items)
        self._selection_changed()

    def items(self) -> list[GalleryItem]:
        """The results shown right now, in their order."""
        return self.model.items()

    def item(self, job_dir: str) -> GalleryItem | None:
        row = self.model.row_of(job_dir)
        return self.model.item(row)

    def shown_items(self) -> list[tuple[str, dict]]:
        """The results the gallery shows right now (filter, favourites, search) that have a sketch."""
        return [(it.job_dir, it.summary) for it in self.items() if it.sketch]

    def selected_items(self) -> list[GalleryItem]:
        rows = sorted(i.row() for i in self.view.selectionModel().selectedIndexes())
        return [self.model.item(r) for r in rows if self.model.item(r) is not None]

    def select(self, job_dirs: list[str]) -> None:
        self.view.clearSelection()
        for d in job_dirs:
            row = self.model.row_of(d)
            if row >= 0:
                self.view.selectionModel().select(self.model.index(row), QItemSelectionModel.Select)

    def _selection_changed(self):
        n = len(self.view.selectionModel().selectedIndexes())
        self.selection_bar.setVisible(n > 1)
        self.selection_label.setText(tr("ui.gallery.selected", n=n))

    # ------------------------------------------------------------------ actions
    def _star_clicked(self, row: int):
        it = self.model.item(row)
        if it is not None:
            self.set_favourite([it.job_dir], not it.favourite)

    def set_favourite(self, job_dirs: list[str], value: bool) -> None:
        for d in job_dirs:
            try:
                set_favourite(d, value)
            except OSError as exc:
                QMessageBox.warning(self, tr("ui.error"), str(exc))
                return
            for it in self._all:
                if it.job_dir == d:
                    it.summary["favourite"] = bool(value)
            row = self.model.row_of(d)
            if row >= 0:
                self.model.changed(row)
        if self.fav_btn.isChecked() and not value:
            QTimer.singleShot(0, self._apply)

    def toggle_favourite_selected(self):
        chosen = self.selected_items()
        if chosen:
            self.set_favourite([it.job_dir for it in chosen], not all(it.favourite for it in chosen))

    def export_items(self, items: list[GalleryItem] | None = None):
        pairs = [(it.job_dir, it.summary) for it in items if it.sketch] if items else self.shown_items()
        dialogs.export_many(self, pairs)

    def edit_info(self, job_dir: str) -> bool:
        it = self.item(job_dir)
        if it is None:
            return False
        dlg = JobInfoDialog(it, self)
        if dlg.exec() != QDialog.Accepted:
            return False
        self.save_info(job_dir, **dlg.values())
        return True

    def save_info(self, job_dir: str, title=None, tags=None, notes=None) -> None:
        try:
            meta = jobs.write_meta(job_dir, title=title, tags=tags, notes=notes)
        except OSError as exc:
            QMessageBox.warning(self, tr("ui.error"), str(exc))
            return
        for it in self._all:
            if it.job_dir == job_dir:
                for key in ("title", "tags", "notes"):
                    it.summary.pop(key, None)
                it.summary.update({k: v for k, v in meta.items() if k in ("title", "tags", "notes")})
        self._update_tags()
        self._apply()

    def _context_menu(self, pos):
        index = self.view.indexAt(pos)
        if not index.isValid():
            return
        if not self.view.selectionModel().isSelected(index):
            self.view.selectionModel().select(index, QItemSelectionModel.ClearAndSelect)
        chosen = self.selected_items()
        it = self.model.item(index.row())
        menu = QMenu(self)
        if len(chosen) == 1:
            menu.addAction(icons.icon("brush"), tr("ui.gallery.open"), lambda: self.open_job.emit(it.job_dir))
            if it.can_continue:
                menu.addAction(icons.icon("play"), tr("ui.continue"), lambda: self.continue_job.emit(it.job_dir))
            menu.addAction(icons.icon("folder-open"), tr("ui.gallery.show_folder"),
                           lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(it.job_dir)))
            menu.addAction(icons.icon("copy"), tr("ui.copy"), lambda: self._copy(it))
            menu.addAction(icons.icon("pen-tool"), tr("ui.gallery.info"), lambda: self.edit_info(it.job_dir))
        fav = all(c.favourite for c in chosen)
        menu.addAction(icons.icon("star"), tr("ui.gallery.unfavourite" if fav else "ui.gallery.favourite"),
                       self.toggle_favourite_selected)
        menu.addAction(icons.icon("file-down"), tr("ui.gallery.export_selected", n=len(chosen)),
                       lambda: self.export_items(chosen))
        menu.addSeparator()
        delete = menu.addAction(icons.icon("trash-2", theme.current().danger),
                                tr("ui.gallery.delete") if len(chosen) == 1 else
                                tr("ui.gallery.delete_n", n=len(chosen)), self.delete_selected)
        delete.setEnabled(any(not c.active for c in chosen))
        menu.exec(self.view.viewport().mapToGlobal(pos))

    def _copy(self, it: GalleryItem):
        src = it.sketch
        if src and os.path.isfile(src):
            dialogs.copy_sketch(src)
            self.toast.emit(tr("ui.copied"), "success")

    def delete_selected(self):
        chosen = self.selected_items()
        if len(chosen) == 1:
            self.delete_job(chosen[0].job_dir)
        elif chosen:
            self.delete_jobs([it.job_dir for it in chosen])

    def delete_jobs(self, job_dirs: list[str], confirm: bool = True) -> int:
        active = self._active()
        free = [d for d in job_dirs if os.path.normcase(os.path.abspath(d)) not in active]
        if not free:
            return 0
        if confirm and QMessageBox.question(self, tr("ui.gallery.delete"),
                                            tr("ui.gallery.delete_n_q", n=len(free))) != QMessageBox.Yes:
            return 0
        deleted = sum(1 for d in free if self.delete_job(d, confirm=False, permanent_ok=not confirm, refresh=False))
        QTimer.singleShot(0, self.refresh)
        return deleted

    def delete_job(self, job_dir: str, confirm: bool = True, permanent_ok: bool = False,
                   refresh: bool = True) -> bool:
        name = os.path.basename(os.path.normpath(job_dir))
        if os.path.normcase(os.path.abspath(job_dir)) in self._active():
            QMessageBox.information(self, tr("ui.gallery.delete"), tr("ui.gallery.delete_active", name=name))
            return False
        if confirm and QMessageBox.question(self, tr("ui.gallery.delete"),
                                            tr("ui.gallery.delete_q", name=name)) != QMessageBox.Yes:
            return False
        if not move_to_trash(job_dir):
            if confirm and not permanent_ok and QMessageBox.question(
                    self, tr("ui.gallery.delete"), tr("ui.gallery.delete_permanently_q", name=name)) != QMessageBox.Yes:
                return False
            try:
                shutil.rmtree(job_dir)
            except OSError as exc:
                QMessageBox.warning(self, tr("ui.error"), str(exc))
                return False
        self.job_deleted.emit(job_dir)
        if refresh:
            QTimer.singleShot(0, self.refresh)
        return True

    # ------------------------------------------------------------------ Qt
    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        QTimer.singleShot(0, self.refresh)

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
        self.sort.addItems([tr(f"ui.gallery.sort_{k}") for k in SORTS])
        self.sort.setCurrentIndex(index)
        self.sort.blockSignals(False)
        if self.tag_filter.count():
            self.tag_filter.setItemText(0, tr("ui.gallery.all_tags"))
        self.folder_btn.setText(tr("ui.open_folder"))
        self.export_btn.setText(tr("ui.batch.export_shown"))
        self.export_btn.setToolTip(tr("ui.batch.export_shown_tip"))
        self.refresh_btn.setText(tr("ui.refresh"))
        self.sel_fav_btn.setText(tr("ui.gallery.favourite"))
        self.sel_export_btn.setText(tr("ui.gallery.export_short"))
        self.sel_delete_btn.setText(tr("ui.gallery.delete"))
        self.view.setToolTip(tr("ui.gallery.keys_tip"))
        self.empty.setText(tr("ui.gallery.empty"))
        self._selection_changed()
        self.view.viewport().update()
