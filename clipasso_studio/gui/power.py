"""Sleep or shut down the PC when the queue is done (Windows; elsewhere nothing happens)."""

from __future__ import annotations

import subprocess
import sys

ACTIONS = ("nothing", "sleep", "shutdown")


def available() -> bool:
    return sys.platform == "win32"


def run(action: str) -> bool:
    """Put the PC to sleep or shut it down; False when that is not possible here."""
    if not available() or action not in ("sleep", "shutdown"):
        return False
    try:
        if action == "sleep":
            import ctypes

            # SetSuspendState(hibernate=False, force=False, wakeup events disabled=False)
            return bool(ctypes.windll.powrprof.SetSuspendState(0, 0, 0))
        subprocess.Popen(["shutdown", "/s", "/t", "0"], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    except Exception:
        return False
