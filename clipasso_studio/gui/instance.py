"""Only one CLIPasso Studio at a time.

Two open apps would share settings.json (with the saved queue) and could both continue the same job.
A second start brings the open window to the front (Windows) or says that the app is already open,
and quits. The lock is a QLockFile in the app data folder: the lock of a crashed app is stale (its
process is gone) and is taken over.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QLockFile

_lock: QLockFile | None = None


def try_lock(path: str) -> QLockFile | None:
    lock = QLockFile(path)
    lock.setStaleLockTime(0)  # never stale by age, only when its process is gone
    return lock if lock.tryLock(300) else None


def owner_pid(path: str) -> int | None:
    try:
        info = QLockFile(path).getLockInfo()
    except Exception:
        return None
    pid = info[0] if isinstance(info, tuple) and info and isinstance(info[0], int) else None
    return pid if pid and pid > 0 else None


def lock_path() -> str:
    from .. import paths

    return str(paths.user_data_dir() / "app.lock")


def acquire() -> bool:
    """True if this is the only running app (the lock is held until :func:`release`)."""
    global _lock
    if _lock is not None:
        return True
    _lock = try_lock(lock_path())
    return _lock is not None


def release() -> None:
    global _lock
    if _lock is not None:
        _lock.unlock()
        _lock = None


def bring_to_front(pid: int | None) -> bool:
    """Restore and activate the main window of process ``pid`` (Windows); False if none was found."""
    if not pid or sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        found = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def visit(hwnd, _):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid and user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
                found.append(hwnd)
                return False
            return True

        user32.EnumWindows(visit, 0)
        for hwnd in found:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
        return bool(found)
    except Exception:
        return False


def tell_already_running() -> None:
    """The second start: show the open app, or say that it is open (e.g. only in the tray)."""
    if bring_to_front(owner_pid(lock_path())):
        return
    from PySide6.QtWidgets import QMessageBox

    from .. import APP_NAME
    from .i18n import tr

    QMessageBox.information(None, APP_NAME, tr("ui.already_running"))
