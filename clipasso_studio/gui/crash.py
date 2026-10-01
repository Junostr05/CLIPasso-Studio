"""Crash log: unexpected errors, hard crashes and Qt warnings are written to ``<app data>/logs``.

- an uncaught Python exception (also from a background thread) is logged and shown in a dialog –
  the app keeps running;
- a hard crash (segfault, abort) is caught by ``faulthandler``, which writes the Python stacks of all
  threads; the next start tells the user and points to the log;
- Qt warnings and errors go to ``qt.log`` (they explain crashes such as a destroyed running thread).
"""

from __future__ import annotations

import faulthandler
import os
import platform
import sys
import threading
import time
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QtMsgType, QUrl, Signal, Slot, qInstallMessageHandler
from PySide6.QtGui import QDesktopServices

from .. import APP_NAME, __version__, logs

KEEP_LOGS = 20
QT_LOG_MAX_BYTES = 1_000_000
FAULT_LOG = "faulthandler.log"

_state: dict = {"installed": False, "fault_file": None, "showing": False, "notifier": None, "previous": None,
                "fault_was_enabled": False}


def logs_dir() -> Path:
    return logs.logs_dir()


def _header() -> str:
    """Version, edition, system, torch / CUDA and GPU (from the hardware probe) and the time."""
    try:
        from .diagnostics import header

        head = header()
    except Exception:  # noqa: BLE001 - a crash log is written anyway
        head = (f"{APP_NAME} {__version__} · {platform.system()} {platform.release()} · "
                f"Python {platform.python_version()}")
    return f"{head} · {time.strftime('%Y-%m-%d %H:%M:%S')}"


def _prune(pattern: str = "crash-*.log", keep: int = KEEP_LOGS) -> None:
    logs = sorted(logs_dir().glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in logs[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


def write_log(text: str, kind: str = "error") -> Path:
    """Write a crash log and return its path."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = logs_dir() / f"crash-{stamp}-{kind}.log"
    n = 1
    while path.exists():
        n += 1
        path = logs_dir() / f"crash-{stamp}-{kind}-{n}.log"
    path.write_text(f"{_header()}\n\n{text}", encoding="utf-8")
    _prune()
    return path


def open_logs_folder() -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(logs_dir())))


class _Notifier(QObject):
    """Brings error reports from any thread to the dialog in the GUI thread (a slot of an object that
    lives there – a plain function connected to the signal would run in the reporting thread)."""

    report = Signal(str, str)  # (log path, details)

    @Slot(str, str)
    def show(self, log_path: str, details: str):
        _show_dialog(log_path, details)


def _show_dialog(log_path: str, details: str) -> None:
    from PySide6.QtWidgets import QApplication, QMessageBox

    from .i18n import tr

    if _state["showing"] or QApplication.instance() is None:
        return
    _state["showing"] = True
    try:
        box = QMessageBox(QApplication.activeWindow())
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(APP_NAME)
        box.setText(tr("ui.crash.title"))
        box.setInformativeText(tr("ui.crash.text", path=log_path))
        box.setDetailedText(details)
        folder = box.addButton(tr("ui.crash.open_logs"), QMessageBox.ActionRole)
        box.addButton(QMessageBox.Close)
        box.exec()
        if box.clickedButton() is folder:
            open_logs_folder()
    finally:
        _state["showing"] = False


def report(exc_type, exc, tb, where: str = "") -> Path | None:
    """Log an exception and show the error dialog (from any thread)."""
    details = "".join(traceback.format_exception(exc_type, exc, tb))
    if where:
        details = f"{where}\n{details}"
    try:
        path = write_log(details)
    except OSError:
        path = None
    try:
        if sys.__stderr__ is not None:  # None in the windowed exe
            sys.__stderr__.write(details)
    except Exception:
        pass
    notifier = _state["notifier"]
    if notifier is not None:
        notifier.report.emit(str(path or ""), details)  # queued to the GUI thread when needed
    return path


def _excepthook(exc_type, exc, tb):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    report(exc_type, exc, tb)


def _thread_excepthook(args):
    if args.exc_type is SystemExit:
        return
    report(args.exc_type, args.exc_value, args.exc_traceback,
           where=f"in thread {getattr(args.thread, 'name', '?')}")


def _qt_message(mode, context, message):
    if mode == QtMsgType.QtDebugMsg or mode == QtMsgType.QtInfoMsg:
        return
    if "propagateSizeHints" in message:  # harmless noise of some platform plugins
        return
    path = logs_dir() / "qt.log"
    try:
        if path.exists() and path.stat().st_size > QT_LOG_MAX_BYTES:
            os.replace(path, path.with_suffix(".log.1"))
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {mode.name}: {message}\n")
    except OSError:
        pass


def install() -> None:
    """Install the crash handlers (once, at the start of the GUI)."""
    if _state["installed"]:
        return
    _state["installed"] = True
    notifier = _Notifier()
    notifier.report.connect(notifier.show)
    _state["notifier"] = notifier
    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
    qInstallMessageHandler(_qt_message)
    fault = logs_dir() / FAULT_LOG
    try:
        # a non-empty file means the app crashed hard last time: keep it as a crash log
        if fault.exists() and fault.stat().st_size > 0:
            stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(fault.stat().st_mtime))
            previous = logs_dir() / f"crash-{stamp}-hard.log"
            previous.write_text(f"{APP_NAME}: hard crash (Python stacks of all threads)\n\n"
                                + fault.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
            _state["previous"] = previous
            _prune()
        f = open(fault, "w", encoding="utf-8")  # noqa: SIM115 – stays open for faulthandler
        _state["fault_was_enabled"] = faulthandler.is_enabled()
        faulthandler.enable(f, all_threads=True)
        _state["fault_file"] = f
    except OSError:
        pass


def previous_crash() -> Path | None:
    """The log of a hard crash during the last session (found by :func:`install`)."""
    return _state["previous"]


def show_previous_crash(parent=None) -> None:
    from PySide6.QtWidgets import QMessageBox

    from .i18n import tr

    path = previous_crash()
    if path is None:
        return
    _state["previous"] = None
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Information)
    box.setWindowTitle(APP_NAME)
    box.setText(tr("ui.crash.last_time"))
    box.setInformativeText(tr("ui.crash.last_time_text", path=str(path)))
    folder = box.addButton(tr("ui.crash.open_logs"), QMessageBox.ActionRole)
    box.addButton(QMessageBox.Close)
    box.exec()
    if box.clickedButton() is folder:
        open_logs_folder()


def uninstall() -> None:
    """Restore the default handlers (tests)."""
    if not _state["installed"]:
        return
    sys.excepthook = sys.__excepthook__
    threading.excepthook = threading.__excepthook__
    qInstallMessageHandler(None)
    try:
        faulthandler.disable()
        if _state["fault_was_enabled"] and sys.__stderr__ is not None:
            faulthandler.enable(sys.__stderr__, all_threads=True)
    except Exception:
        pass
    if _state["fault_file"] is not None:
        _state["fault_file"].close()
    _state.update(installed=False, fault_file=None, notifier=None)
