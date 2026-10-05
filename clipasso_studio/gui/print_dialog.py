"""The print layout dialog: page, sketches per page, margins, title, signature, captions, brush style and paper –
with a preview of the first page; saves a PDF or prints."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox, QProgressBar, QVBoxLayout)

from . import brush, print_layout
from .app_settings import app_settings
from .dialogs import ColorButton, PaperChoice, error_text, paper_colours, run_in_thread
from .i18n import tr
from .widgets.common import button, label

PREVIEW_WIDTH = 300


class PrintDialog(QDialog):
    """``items``: (sketch file, caption) in the order they are placed."""

    def __init__(self, items: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.items = items
        self.saved_path = ""
        self.busy = False
        self._cancel = False
        st = app_settings()
        self.setWindowTitle(tr("ui.print.title"))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(14)
        lay.addWidget(label(tr("ui.print.title"), "h2"))
        lay.addWidget(label(tr("ui.print.desc", n=len(items)), "muted", wrap=True))
        body = QHBoxLayout()
        body.setSpacing(18)
        form = QFormLayout()
        form.setSpacing(9)
        self.page = QComboBox()
        for key in print_layout.PAGES:
            self.page.addItem(tr(f"ui.print.page.{key}"), key)
        self.page.setCurrentIndex(max(self.page.findData(st.get("print_page", "a4")), 0))
        form.addRow(tr("ui.print.page_label"), self.page)
        self.orientation = QComboBox()
        self.orientation.addItem(tr("ui.print.portrait"), False)
        self.orientation.addItem(tr("ui.print.landscape"), True)
        self.orientation.setCurrentIndex(1 if st.get("print_landscape", False) else 0)
        form.addRow(tr("ui.print.orientation"), self.orientation)
        self.per_page = QComboBox()
        for n in print_layout.PER_PAGE:
            self.per_page.addItem(tr("ui.print.per_page_n", n=n), n)
        default = st.get("print_per_page", 6) if len(items) > 1 else 1
        self.per_page.setCurrentIndex(max(self.per_page.findData(default), 0))
        form.addRow(tr("ui.print.per_page"), self.per_page)
        self.margin = QDoubleSpinBox()
        self.margin.setRange(0.0, 60.0)
        self.margin.setSingleStep(5.0)
        self.margin.setDecimals(0)
        self.margin.setSuffix(" mm")
        self.margin.setValue(float(st.get("print_margin", 15.0) or 0.0))
        form.addRow(tr("ui.print.margin"), self.margin)
        self.title = QLineEdit()
        self.title.setPlaceholderText(tr("ui.print.title_placeholder"))
        form.addRow(tr("ui.print.heading"), self.title)
        self.signature = QLineEdit(str(st.get("print_signature", "") or ""))
        self.signature.setPlaceholderText(tr("ui.print.signature_placeholder"))
        form.addRow(tr("ui.print.signature"), self.signature)
        self.captions = QCheckBox(tr("ui.print.captions"))
        self.captions.setChecked(bool(st.get("print_captions", False)))
        form.addRow("", self.captions)
        self.style = QComboBox()
        for key in brush.STYLES:
            self.style.addItem(tr(f"ui.brush.{key}"), key)
        self.style.setCurrentIndex(max(self.style.findData(st.get("export_style", "plain")), 0))
        form.addRow(tr("ui.brush.label"), self.style)
        self.stroke = ColorButton(str(st.get("export_stroke", "#000000") or "#000000"))
        form.addRow(tr("ui.stroke_color"), self.stroke)
        bg = st.get("export_background") or "#FFFFFF"
        self.background = ColorButton("#FFFFFF" if bg == "transparent" else bg)
        form.addRow(tr("ui.background"), self.background)
        self.paper = PaperChoice(st.get("export_paper", "none"), st.get("export_vignette", 0))
        form.addRow(tr("ui.paper.label"), self.paper)
        self.paper.kind_changed.connect(lambda k: paper_colours(k, self.background, self.stroke))
        self.background.changed.connect(lambda _c: paper_colours(None, self.background, self.stroke))
        body.addLayout(form, 1)
        side = QVBoxLayout()
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumWidth(PREVIEW_WIDTH + 8)
        side.addWidget(self.preview)
        self.pages_label = label("", "faint")
        self.pages_label.setAlignment(Qt.AlignCenter)
        side.addWidget(self.pages_label)
        side.addStretch(1)
        body.addLayout(side)
        lay.addLayout(body)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        lay.addWidget(self.progress)
        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_btn = button(tr("ui.cancel"), variant="ghost")
        self.cancel_btn.clicked.connect(self.reject)
        self.print_btn = button(tr("ui.print.print"), "printer")
        self.print_btn.clicked.connect(self._print)
        self.pdf_btn = button(tr("ui.print.save_pdf"), "file-down", "primary")
        self.pdf_btn.clicked.connect(self._save_pdf)
        for b in (self.cancel_btn, self.print_btn, self.pdf_btn):
            row.addWidget(b)
        lay.addLayout(row)
        # the preview follows every change (a moment later: typing a title does not paint for every letter)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._update_preview)
        for combo in (self.page, self.orientation, self.per_page, self.style, self.paper.combo):
            combo.currentIndexChanged.connect(self._timer.start)
        for spin in (self.margin, self.paper.vignette):
            spin.valueChanged.connect(self._timer.start)
        for edit in (self.title, self.signature):
            edit.textChanged.connect(self._timer.start)
        self.captions.toggled.connect(self._timer.start)
        for b in (self.stroke, self.background):
            b.changed.connect(self._timer.start)
        self.pdf_btn.setEnabled(bool(items))
        self.print_btn.setEnabled(bool(items))
        self._update_preview()

    def layout_choice(self) -> print_layout.Layout:
        stroke = self.stroke.color()
        return print_layout.Layout(
            page=self.page.currentData(), landscape=bool(self.orientation.currentData()),
            margin_mm=self.margin.value(), per_page=int(self.per_page.currentData()), title=self.title.text().strip(),
            signature=self.signature.text().strip(), captions=self.captions.isChecked(),
            stroke_color=None if stroke.lower() == "#000000" else stroke, background=self.background.color(),
            style=self.style.currentData(), paper=self.paper.paper(),
            frame=app_settings().get("export_frame", "square"))

    def _update_preview(self):
        lay = self.layout_choice()
        self.preview.setPixmap(QPixmap.fromImage(print_layout.preview(self.items, lay, PREVIEW_WIDTH)))
        self.pages_label.setText(tr("ui.print.pages", n=print_layout.page_count(len(self.items), lay)))

    def _remember(self, lay: print_layout.Layout):
        st = app_settings()
        st.data.update({"print_page": lay.page, "print_landscape": lay.landscape, "print_margin": lay.margin_mm,
                        "print_signature": lay.signature, "print_captions": lay.captions})
        if len(self.items) > 1:
            st.data["print_per_page"] = lay.per_page
        st.save()

    def _print(self):
        lay = self.layout_choice()
        self._remember(lay)
        try:
            if print_layout.print_pages(self, self.items, lay):
                self.accept()
        except Exception as exc:
            QMessageBox.warning(self, tr("ui.error"), error_text(exc))

    def _save_pdf(self):
        lay = self.layout_choice()
        folder = app_settings().get("export_dir") or ""
        if not os.path.isdir(folder):
            folder = os.path.expanduser("~")
        name = lay.title or (os.path.splitext(os.path.basename(self.items[0][0]))[0] if self.items else "sketches")
        dest, _ = QFileDialog.getSaveFileName(self, tr("ui.save_as"), os.path.join(folder, f"{name}.pdf"),
                                              "PDF (*.pdf)")
        if not dest:
            return
        if not dest.lower().endswith(".pdf"):
            dest += ".pdf"
        app_settings().set("export_dir", os.path.dirname(os.path.abspath(dest)))
        self._remember(lay)
        self.busy, self._cancel = True, False
        for b in (self.pdf_btn, self.print_btn):
            b.setEnabled(False)
        self.progress.setRange(0, max(print_layout.page_count(len(self.items), lay), 1))
        self.progress.setValue(0)
        self.progress.setVisible(True)

        def prog(a, b):
            if b > 0:
                self.progress.setValue(a)

        def done(_):
            self.busy = False
            if self._cancel:
                super(PrintDialog, self).reject()
                return
            self.saved_path = dest
            self.accept()

        def failed(msg):
            self.busy = False
            if self._cancel:
                super(PrintDialog, self).reject()
                return
            for b in (self.pdf_btn, self.print_btn):
                b.setEnabled(True)
            self.progress.setVisible(False)
            QMessageBox.warning(self, tr("ui.error"), msg)

        run_in_thread(self, print_layout.export_pdf_pages, self.items, dest, lay, cancel=lambda: self._cancel,
                      on_progress=prog, on_done=done, on_error=failed)

    def reject(self):
        if self.busy:
            self._cancel = True
            self.cancel_btn.setEnabled(False)
            return
        super().reject()


def open_print(parent, items: list[tuple[str, str]]) -> str:
    """The print layout dialog; the saved PDF ("" when printed or cancelled)."""
    items = [(path, caption) for path, caption in items if path and os.path.isfile(path)]
    if not items:
        QMessageBox.information(parent, tr("ui.print.title"), tr("ui.batch.nothing"))
        return ""
    dlg = PrintDialog(items, parent)
    dlg.exec()
    return dlg.saved_path
