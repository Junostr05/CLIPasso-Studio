"""Settings → System → "Run self-test": the app's own ``--selftest`` (short runs of every method, continuing,
the mask, the warm worker …) in a separate process, with its progress and a result per part.

The windowed exe has no console, so the progress is read from ``<out>/selftest.log``, which the self-test
writes as well; the result is ``<out>/selftest.json``."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from PySide6.QtCore import QProcess, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPlainTextEdit, QProgressBar, QVBoxLayout

from .. import logs
from .i18n import tr
from .widgets.common import button, label

PARTS = ("clipasso", "swiftsketch", "controlsketch", "scenesketch", "resume", "mask", "warm", "inputs",
         "gpu_runtime")


def selftest_command(out_dir: str) -> tuple[str, list[str]]:
    """The program and arguments that run the self-test of this app (the exe itself, or the package)."""
    if getattr(sys, "frozen", False):
        return sys.executable, ["--selftest", out_dir]
    return sys.executable, ["-m", "clipasso_studio", "--selftest", out_dir]


def new_out_dir() -> str:
    path = logs.logs_dir() / "selftest" / time.strftime("%Y%m%d-%H%M%S")
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def status_line(line: str) -> str | None:
    """What a line of the self-test log says, for the status ("" lines and noise: None)."""
    line = line.strip()
    if line.startswith("selftest: seed ") and " iter " in line:
        return "CLIPasso: " + line.split(" iter ", 1)[1].split(" loss", 1)[0]
    if line.startswith("Best sketch:"):
        return None
    if line.startswith("selftest: ") and not line.startswith("selftest: {"):
        head = line[len("selftest: "):].split(" ", 1)[0]
        return tr(f"ui.selftest.part.{head}") if head in PARTS else None
    return None


class SelftestDialog(QDialog):
    """Runs the self-test and shows its result; ``result`` is the parsed selftest.json (None while running)."""

    def __init__(self, parent=None, out_dir: str | None = None):
        super().__init__(parent)
        self.out_dir = out_dir or new_out_dir()
        self.result: dict | None = None
        self.proc: QProcess | None = None
        self._pos = 0
        self._started = 0.0
        self.setWindowTitle(tr("ui.selftest.title"))
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(10)
        lay.addWidget(label(tr("ui.selftest.title"), "h2"))
        lay.addWidget(label(tr("ui.selftest.desc"), "muted", wrap=True))
        self.status = label(tr("ui.selftest.starting"), "faint", wrap=True)
        lay.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)  # busy
        lay.addWidget(self.bar)
        self.results = QPlainTextEdit()
        self.results.setReadOnly(True)
        self.results.setVisible(False)
        self.results.setMinimumHeight(170)
        lay.addWidget(self.results)
        row = QHBoxLayout()
        self.log_btn = button(tr("ui.selftest.open_log"), "folder-open", "ghost")
        self.log_btn.clicked.connect(self.open_log)
        row.addWidget(self.log_btn)
        row.addStretch(1)
        self.close_btn = button(tr("ui.cancel"), variant="ghost")
        self.close_btn.clicked.connect(self.reject)
        row.addWidget(self.close_btn)
        lay.addLayout(row)
        self._timer = QTimer(self)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._read_log)

    @property
    def log_path(self) -> Path:
        return Path(self.out_dir) / "selftest.log"

    def start(self) -> None:
        program, args = selftest_command(self.out_dir)
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(lambda: self.proc.readAllStandardOutput())  # (the log has it)
        self.proc.finished.connect(self._finished)
        self._started = time.time()
        self.proc.start(program, args)
        self._timer.start()

    def exec(self):  # noqa: A003 – the self-test starts with the dialog
        QTimer.singleShot(0, self.start)
        return super().exec()

    def _read_log(self) -> None:
        try:
            with open(self.log_path, encoding="utf-8", errors="replace") as f:
                f.seek(self._pos)
                text = f.read()
                self._pos = f.tell()
        except OSError:
            return
        for line in text.splitlines():
            shown = status_line(line)
            if shown:
                self.status.setText(tr("ui.selftest.running", what=shown, secs=int(time.time() - self._started)))

    def _finished(self, code: int, _status=None) -> None:
        self._timer.stop()
        self._read_log()
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        try:
            self.result = json.loads((Path(self.out_dir) / "selftest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.result = {"ok": False, "error": f"exit code {code}"}
        self.results.setPlainText(summary_text(self.result))
        self.results.setVisible(True)
        ok = bool(self.result.get("ok"))
        self.status.setText(tr("ui.selftest.ok" if ok else "ui.selftest.failed",
                               secs=int(self.result.get("seconds") or time.time() - self._started)))
        self.close_btn.setText(tr("ui.close"))

    def open_log(self) -> None:
        target = self.log_path if self.log_path.is_file() else Path(self.out_dir)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def reject(self):
        if self.proc is not None and self.proc.state() != QProcess.NotRunning:
            self.proc.kill()
            self.proc.waitForFinished(3000)
        self._timer.stop()
        super().reject()


def summary_text(result: dict) -> str:
    """One line per part: ✓ / ✗, its name and (if any) its CLIP score or error."""
    lines = []
    for part in PARTS:
        r = result.get(part)
        if not isinstance(r, dict):
            continue
        extra = f" · CLIP {r['clip_score']:.1f}" if isinstance(r.get("clip_score"), (int, float)) else ""
        lines.append(f"{'✓' if r.get('ok') else '✗'}  {tr(f'ui.selftest.part.{part}')}{extra}")
    if result.get("error"):
        lines.append(f"✗  {result['error']}")
    return "\n".join(lines) or "–"


def run(parent) -> dict | None:
    """Ask the controller to let the worker go, then run the self-test; the result (None: nothing ran)."""
    controller = getattr(parent.window(), "controller", None)
    if controller is not None:
        if controller.is_busy():
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.information(parent, tr("ui.selftest.title"), tr("ui.selftest.busy"))
            return None
        controller.release_worker()
    dlg = SelftestDialog(parent)
    dlg.exec()
    return dlg.result
