"""Settings → System: make a backup of the app (settings, queue, gallery, models if wanted) and put one back."""

from __future__ import annotations

import os

from PySide6.QtWidgets import QCheckBox, QDialog, QFileDialog, QHBoxLayout, QMessageBox, QProgressBar, QVBoxLayout

from . import backup
from .app_settings import app_settings
from .dialogs import error_text, run_in_thread
from .i18n import tr
from .widgets.common import button, label


def _gb(n: int) -> str:
    return f"{n / 1e9:.2f} GB" if n >= 1e8 else f"{n / 1e6:.1f} MB"


class BackupDialog(QDialog):
    """``restore_from`` None: make a backup; a file: put that backup back."""

    def __init__(self, parent=None, restore_from: str | None = None):
        super().__init__(parent)
        self.restore_from = restore_from
        self.result_path = ""
        self.report: dict | None = None
        self.busy = False
        self._cancel = False
        restoring = restore_from is not None
        self.setWindowTitle(tr("ui.backup.restore_title" if restoring else "ui.backup.title"))
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(12)
        lay.addWidget(label(self.windowTitle(), "h2"))
        self.parts: dict[str, QCheckBox] = {}
        if restoring:
            self.manifest = backup.read_manifest(restore_from)
            m = self.manifest
            lay.addWidget(label(tr("ui.backup.restore_desc", created=m.get("created", "?"),
                                   version=m.get("version", "?")), "muted", wrap=True))
            texts = {"settings": tr("ui.backup.part_settings"),
                     "queue": tr("ui.backup.part_queue_n", n=m.get("queue", 0)),
                     "gallery": tr("ui.backup.part_gallery_n", n=m.get("jobs", 0)),
                     "models": tr("ui.backup.part_models")}
            for key in backup.PARTS:
                if key == "models" and not m.get("has_models"):
                    continue
                box = QCheckBox(texts[key])
                box.setChecked(True)
                lay.addWidget(box)
                self.parts[key] = box
            lay.addWidget(label(tr("ui.backup.restore_note"), "faint", wrap=True))
        else:
            sizes = backup.sizes()
            lay.addWidget(label(tr("ui.backup.desc"), "muted", wrap=True))
            lay.addWidget(label(tr("ui.backup.contents", jobs=sizes["jobs"], gallery=_gb(sizes["gallery"]),
                                   queue=_gb(sizes["queue"])), None, wrap=True))
            self.models = QCheckBox(tr("ui.backup.with_models", size=_gb(backup.models_size())))
            self.models.setToolTip(tr("ui.backup.with_models_tip"))
            lay.addWidget(self.models)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        lay.addWidget(self.progress)
        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_btn = button(tr("ui.cancel"), variant="ghost")
        self.cancel_btn.clicked.connect(self.reject)
        self.ok = button(tr("ui.backup.restore" if restoring else "ui.backup.save"),
                         "refresh-cw" if restoring else "download", "primary")
        self.ok.clicked.connect(self._restore if restoring else self._save)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.ok)
        lay.addLayout(row)

    def _progress(self, done, total):
        if total > 0:
            self.progress.setRange(0, 1000)
            self.progress.setValue(int(1000 * done / total))

    def _run(self, fn, *args, on_done, **kwargs):
        self.busy, self._cancel = True, False
        self.ok.setEnabled(False)
        self.progress.setRange(0, 0)
        self.progress.setVisible(True)

        def done(result):
            self.busy = False
            if self._cancel:
                super(BackupDialog, self).reject()
                return
            on_done(result)

        def failed(msg):
            self.busy = False
            if self._cancel:
                super(BackupDialog, self).reject()
                return
            self.ok.setEnabled(True)
            self.progress.setVisible(False)
            QMessageBox.warning(self, tr("ui.error"), msg)

        run_in_thread(self, fn, *args, cancel=lambda: self._cancel, on_progress=self._progress, on_done=done,
                      on_error=failed, **kwargs)

    def _save(self):
        folder = app_settings().get("export_dir") or os.path.expanduser("~")
        dest, _ = QFileDialog.getSaveFileName(self, tr("ui.backup.save"), os.path.join(folder, backup.default_name()),
                                              f"{tr('ui.backup.file_type')} (*{backup.EXTENSION})")
        if not dest:
            return
        if not dest.lower().endswith(backup.EXTENSION):
            dest += backup.EXTENSION

        def finished(_manifest):
            self.result_path = dest
            self.accept()

        self._run(backup.create, dest, include_models=self.models.isChecked(), on_done=finished)

    def _restore(self):
        parts = tuple(k for k, box in self.parts.items() if box.isChecked())
        if not parts:
            return

        def finished(report):
            self.report = report
            self.accept()

        self._run(backup.restore, self.restore_from, parts, on_done=finished)

    def reject(self):
        if self.busy:
            self._cancel = True
            self.cancel_btn.setEnabled(False)
            return
        super().reject()


def make_backup(parent) -> str:
    """Asks what to save and where; returns the backup file ("" when cancelled)."""
    dlg = BackupDialog(parent)
    dlg.exec()
    return dlg.result_path


def restore_backup(parent, path: str | None = None) -> dict | None:
    """Asks for a backup file and what to put back; returns the report of :func:`backup.restore` (None when
    cancelled). The caller adds the returned queue entries to the queue."""
    if path is None:
        folder = app_settings().get("export_dir") or os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(parent, tr("ui.backup.restore_title"), folder,
                                              f"{tr('ui.backup.file_type')} (*{backup.EXTENSION})")
        if not path:
            return None
    try:
        dlg = BackupDialog(parent, restore_from=path)
    except backup.BackupError as exc:
        QMessageBox.warning(parent, tr("ui.error"), error_text(exc))
        return None
    if dlg.exec() != QDialog.Accepted:
        return None
    report = dlg.report or {}
    QMessageBox.information(parent, tr("ui.backup.restore_title"), tr(
        "ui.backup.restored", jobs=report.get("jobs", 0), skipped=report.get("skipped_jobs", 0),
        queue=len(report.get("queue") or []), models=report.get("models", 0)))
    return report
