"""Report a problem on GitHub: a prepared issue (the error, its traceback, the diagnostics) that the user sees
and can edit first, opened in the browser. Paths with the user's name are shortened to ``~``; a text too long
for the address is cut there and copied to the clipboard in full."""

from __future__ import annotations

import os
import urllib.parse
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLineEdit, QPlainTextEdit, QVBoxLayout

from .. import __version__
from .i18n import tr
from .widgets.common import button, label

NEW_ISSUE = "https://github.com/Junostr05/CLIPasso-Studio/issues/new"
MAX_URL = 7000  # characters: browsers and GitHub take about 8 KB
CUT = "\n…\n(cut – the full text is in the clipboard)\n"


def anonymize(text: str) -> str:
    """The home folder (with the user's name) as ``~``, with either kind of slash."""
    homes = {str(Path.home()), os.path.expanduser("~")}
    for home in sorted({h for h in homes if len(h) > 3}, key=len, reverse=True):
        for variant in {home, home.replace("\\", "/"), home.replace("/", "\\")}:
            text = text.replace(variant, "~")
    return text


def issue_title(message: str = "") -> str:
    first = (message or "").strip().splitlines()[0][:100] if (message or "").strip() else ""
    return f"[{__version__}] {first}" if first else f"[{__version__}] "


def issue_body(message: str = "", traceback: str = "", diagnostics: str | None = None) -> str:
    """The prepared text (Markdown): what happened, the steps, the traceback and the diagnostics."""
    if diagnostics is None:
        from . import diagnostics as diag

        try:
            diagnostics = diag.report()
        except Exception as exc:  # noqa: BLE001 - the report goes on without
            diagnostics = f"(diagnostics failed: {exc})"
    parts = ["**What happened?**", (message or "").strip() or "…", "", "**What did you do before?**", "…", ""]
    if traceback.strip():
        parts += ["<details><summary>Traceback</summary>", "", "```", traceback.strip(), "```", "</details>", ""]
    parts += ["<details><summary>Diagnostics</summary>", "", "```", diagnostics.strip(), "```", "</details>"]
    return anonymize("\n".join(parts)) + "\n"


def issue_url(title: str, body: str, limit: int = MAX_URL) -> tuple[str, bool]:
    """-> (the address of a new issue with this title and text, whether the text had to be cut)."""
    def url(b: str) -> str:
        return NEW_ISSUE + "?" + urllib.parse.urlencode({"title": title, "body": b})

    full = url(body)
    if len(full) <= limit:
        return full, False
    lo, hi = 0, len(body)  # the longest start of the text that fits (with the note)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if len(url(body[:mid] + CUT)) <= limit:
            lo = mid
        else:
            hi = mid - 1
    return url(body[:lo] + CUT), True


class ReportDialog(QDialog):
    """Shows the prepared issue; "Report on GitHub" opens it in the browser (the full text also goes to the
    clipboard)."""

    def __init__(self, parent=None, message: str = "", traceback: str = "", diagnostics: str | None = None):
        super().__init__(parent)
        self.opened_url = ""
        self.setWindowTitle(tr("ui.report.title"))
        self.setMinimumSize(620, 520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(10)
        lay.addWidget(label(tr("ui.report.title"), "h2"))
        lay.addWidget(label(tr("ui.report.desc"), "muted", wrap=True))
        self.title_edit = QLineEdit(issue_title(message))
        lay.addWidget(self.title_edit)
        self.body_edit = QPlainTextEdit(issue_body(message, traceback, diagnostics))
        lay.addWidget(self.body_edit, 1)
        self.note = label("", "faint", wrap=True)
        lay.addWidget(self.note)
        row = QHBoxLayout()
        self.copy_btn = button(tr("ui.report.copy"), "copy", "ghost")
        self.copy_btn.clicked.connect(self.copy)
        row.addWidget(self.copy_btn)
        row.addStretch(1)
        cancel = button(tr("ui.cancel"), variant="ghost")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        self.send_btn = button(tr("ui.report.send"), "external-link", "primary")
        self.send_btn.clicked.connect(self.send)
        row.addWidget(self.send_btn)
        lay.addLayout(row)

    def copy(self) -> str:
        text = f"{self.title_edit.text()}\n\n{self.body_edit.toPlainText()}"
        QApplication.clipboard().setText(text)
        self.note.setText(tr("ui.report.copied"))
        return text

    def send(self) -> str:
        QApplication.clipboard().setText(self.body_edit.toPlainText())
        url, cut = issue_url(self.title_edit.text(), self.body_edit.toPlainText())
        self.opened_url = url
        QDesktopServices.openUrl(QUrl(url))
        self.note.setText(tr("ui.report.cut" if cut else "ui.report.opened"))
        return url


def offer(parent, message: str = "", traceback: str = "") -> None:
    ReportDialog(parent, message, traceback).exec()
