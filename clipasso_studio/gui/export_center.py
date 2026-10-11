"""4.0: *Exportieren …* – one dialog for every way out of the studio (design system: Export artboard). On the left the
formats in groups (*Bild*, *Animation*, *Weitergeben*), on the right the sketch and the options of the chosen format:
the options are the export dialog of 3.x (``dialogs.ExportDialog``) inside this one, so a format's options, its
remembered choices and its file stay what they were.

The studio's ``export_btns`` are the actions behind it (text, tooltip, enabled, visible) – the dialog lists the
visible ones; Ctrl+E opens it on the format used last."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QListWidget, QListWidgetItem, QVBoxLayout, QWidget)

from . import icons, theme
from .i18n import tr
from .widgets.common import button, label

GROUPS = (
    ("image", ("svg", "png", "pdf", "svg1", "svglayers", "matrix")),
    ("animation", ("gif", "mp4", "webp", "svganim", "lottie", "html")),
    ("share", ("copy", "print")),
)
DIRECT = ("copy", "print")  # no options: a button does it
ICONS = {"svg": "pen-tool", "png": "image-plus", "pdf": "file-down", "svg1": "pen-tool", "svglayers": "layers",
         "matrix": "layers", "gif": "film", "mp4": "film", "webp": "film", "svganim": "pencil-line",
         "lottie": "sparkles", "html": "globe", "copy": "copy", "print": "printer"}


class ExportCenter(QDialog):
    def __init__(self, studio, fmt: str = "svg", parent=None):
        super().__init__(parent or studio)
        self.studio = studio
        self.setObjectName("ExportCenter")
        self.setWindowTitle(tr("ui.export_center.title"))
        self.setMinimumSize(760, 520)
        self.saved_path = ""
        self.options = None  # the embedded ExportDialog of the chosen format
        outer = QVBoxLayout(self)
        theme.dialog_layout(outer)
        outer.addWidget(label(tr("ui.export_center.title"), "h2"))
        body = QHBoxLayout()
        body.setSpacing(theme.SPACE_XL)
        self.formats = QListWidget()
        self.formats.setObjectName("FormatList")
        self.formats.setFixedWidth(220)
        self.formats.setIconSize(QSize(16, 16))
        self.formats.currentItemChanged.connect(lambda cur, _prev: self._chosen(cur))
        body.addWidget(self.formats)
        right = QVBoxLayout()
        right.setSpacing(theme.SPACE_L)
        self.preview = self._preview()
        right.addWidget(self.preview)
        self.options_host = QWidget()
        self.options_layout = QVBoxLayout(self.options_host)
        self.options_layout.setContentsMargins(0, 0, 0, 0)
        right.addWidget(self.options_host, 1)
        body.addLayout(right, 1)
        outer.addLayout(body, 1)
        self.items: dict[str, QListWidgetItem] = {}
        self._fill()
        self.choose(fmt)

    # ------------------------------------------------------------------ parts
    def _preview(self) -> QWidget:
        from .widgets.canvas import SketchCanvas

        view = SketchCanvas()
        view.setFixedHeight(200)
        sel = self.studio._selected_run()
        if sel:
            with open(sel[0], encoding="utf-8") as f:
                view.set_svg(f.read())
        view.set_style(self.studio.canvas.style())
        return view

    def _fill(self) -> None:
        p = theme.current()
        for group, keys in GROUPS:
            shown = [k for k in keys if k in self.studio.export_btns and self.studio.export_btns[k].isVisible()]
            if not shown:
                continue
            head = QListWidgetItem(tr(f"ui.export_center.group_{group}"))
            head.setFlags(Qt.NoItemFlags)  # (a heading: not to choose)
            self.formats.addItem(head)
            for key in shown:
                act = self.studio.export_btns[key]
                item = QListWidgetItem(icons.icon(ICONS[key], p.muted, active_color=p.text), act.text())
                item.setData(Qt.UserRole, key)
                item.setToolTip(act.toolTip())
                if not act.isEnabled():
                    item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                self.formats.addItem(item)
                self.items[key] = item

    def choose(self, fmt: str) -> None:
        """Show ``fmt`` (the first format that can be chosen if it cannot)."""
        item = self.items.get(fmt)
        if item is None or not item.flags() & Qt.ItemIsEnabled:
            item = next((i for i in self.items.values() if i.flags() & Qt.ItemIsEnabled), None)
        if item is not None:
            self.formats.setCurrentItem(item)

    def current(self) -> str:
        item = self.formats.currentItem()
        return item.data(Qt.UserRole) if item is not None else ""

    def _chosen(self, item) -> None:
        if item is None or item.data(Qt.UserRole) is None:
            return
        fmt = item.data(Qt.UserRole)
        if self.options is not None:
            self.options.setParent(None)
            self.options.deleteLater()
            self.options = None
        while self.options_layout.count():
            w = self.options_layout.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        if fmt in DIRECT:
            self._direct(fmt)
            return
        dlg = self.studio.export_dialog(fmt)
        if dlg is None:
            return
        dlg.setWindowFlags(Qt.Widget)  # (inside this dialog)
        dlg.accepted.connect(lambda: self._saved(dlg))
        dlg.rejected.connect(self.reject)
        self.options = dlg
        self.options_layout.addWidget(dlg)
        dlg.show()

    def _direct(self, fmt: str) -> None:
        act = self.studio.export_btns[fmt]
        self.options_layout.addWidget(label(act.toolTip(), "muted", wrap=True))
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = button(tr("ui.cancel"), variant="ghost")
        cancel.clicked.connect(self.reject)
        do = button(act.text(), ICONS[fmt], "primary")
        do.clicked.connect(lambda: (self.accept(), act.trigger()))
        row.addWidget(cancel)
        row.addWidget(do)
        holder = QWidget()
        holder.setLayout(row)
        self.options_layout.addWidget(holder)
        self.options_layout.addStretch(1)

    def _saved(self, dlg) -> None:
        self.saved_path = getattr(dlg, "saved_path", "")
        self.accept()
