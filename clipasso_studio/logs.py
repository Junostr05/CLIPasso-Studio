"""Log files in ``<app data>/logs``, without Qt and torch (also used by the worker processes).

- the windowed exe has no console: its output goes to ``app.log`` (``cli.log``, ``selftest.log``),
  which is rotated at ``MAX_BYTES`` (``app.log`` → ``app.log.1`` → ``app.log.2``);
- every worker process writes the Python stacks of a hard crash (segfault, abort) to
  ``worker-<pid>.log``; a worker that ends normally removes its file, so a file that is left over
  belongs to a crashed worker (the app shows it with the error).
"""

from __future__ import annotations

import faulthandler
import os
import sys
from pathlib import Path

from . import paths

MAX_BYTES = 5_000_000
BACKUPS = 2  # app.log + 2 older files
KEEP_WORKER_LOGS = 10
_fault_was_enabled = {"on": False}  # faulthandler was on before start_worker_log (it is put back to stderr)


def logs_dir() -> Path:
    d = paths.user_data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _rotate(path: Path, backups: int = BACKUPS) -> None:
    for i in range(backups, 0, -1):
        older = path.with_name(f"{path.name}.{i}")
        newer = path.with_name(f"{path.name}.{i - 1}") if i > 1 else path
        if newer.exists():
            try:
                os.replace(newer, older)
            except OSError:
                pass


class RotatingStream:
    """A text stream for ``sys.stdout`` / ``sys.stderr`` that starts a new file at ``max_bytes``."""

    encoding = "utf-8"
    errors = "replace"

    def __init__(self, path: Path, max_bytes: int = MAX_BYTES, backups: int = BACKUPS):
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.backups = backups
        if self.path.exists() and self.path.stat().st_size >= max_bytes:
            _rotate(self.path, backups)
        self._open()

    def _open(self) -> None:
        self._file = open(self.path, "a", encoding="utf-8", errors="replace")  # noqa: SIM115 - the stream
        self._size = self._file.tell()

    def write(self, text: str) -> int:
        if self._size >= self.max_bytes:
            try:
                self._file.close()
                _rotate(self.path, self.backups)
            finally:
                self._open()
        n = self._file.write(text)
        self._file.flush()  # the last lines are wanted most after a crash
        try:
            self._size = self._file.tell()  # the bytes on the disk (Windows writes "\r\n" for "\n")
        except (OSError, ValueError):
            self._size += len(text.encode("utf-8", "replace"))
        return n

    def flush(self) -> None:
        self._file.flush()

    def isatty(self) -> bool:
        return False

    def writable(self) -> bool:
        return True

    def close(self) -> None:
        self._file.close()


def open_log(name: str) -> RotatingStream:
    """``logs/<name>`` as a rotating stream; a log of an older version (in the app data folder itself,
    it grew without limit) is moved there first."""
    path = logs_dir() / name
    old = paths.user_data_dir() / name
    try:
        if old.is_file():
            if old.stat().st_size <= MAX_BYTES and not path.exists():
                os.replace(old, path)
            else:
                old.unlink()
    except OSError:
        pass
    return RotatingStream(path)


def tail(path: Path, lines: int = 50) -> list[str]:
    """The last ``lines`` lines of a log (with its previous file when the current one is short)."""
    path = Path(path)
    found: list[str] = []
    for p in (path, path.with_name(path.name + ".1")):
        try:
            with open(p, "rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - 200 * lines))
                text = f.read().decode("utf-8", "replace")
        except OSError:
            continue
        found = text.splitlines()[-(lines - len(found)):] + found
        if len(found) >= lines:
            break
    return found[-lines:]


# ----------------------------------------------------------------------------- worker processes


def worker_log_path(pid: int) -> Path:
    return logs_dir() / f"worker-{pid}.log"


def start_worker_log():
    """Let ``faulthandler`` of this (worker) process write to ``worker-<pid>.log``; returns the open
    file for :func:`end_worker_log` (None when the folder cannot be written)."""
    try:
        _prune_worker_logs()
        f = open(worker_log_path(os.getpid()), "w", encoding="utf-8")  # noqa: SIM115 - for faulthandler
        _fault_was_enabled["on"] = faulthandler.is_enabled()
        faulthandler.enable(f, all_threads=True)
        return f
    except (OSError, RuntimeError, ValueError):
        return None


def end_worker_log(f) -> None:
    """A clean end: no crash to keep (a faulthandler that was on before writes to stderr again – e.g. in a test)."""
    if f is None:
        return
    try:
        faulthandler.disable()
        if _fault_was_enabled["on"] and sys.__stderr__ is not None:
            faulthandler.enable(sys.__stderr__, all_threads=True)
        f.close()
        os.remove(f.name)
    except (OSError, ValueError, RuntimeError):
        pass


def read_worker_log(pid: int | None, max_chars: int = 20_000) -> str:
    """What a crashed worker wrote (its Python stacks), or ""."""
    if not pid:
        return ""
    try:
        text = worker_log_path(pid).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    return text[-max_chars:]


def _prune_worker_logs(keep: int = KEEP_WORKER_LOGS) -> None:
    logs = []
    for p in logs_dir().glob("worker-*.log"):
        try:
            st = p.stat()
        except OSError:
            continue
        if st.st_size == 0:  # killed (no stacks) or still running: nothing to keep
            if not _alive(p):
                _unlink(p)
            continue
        logs.append((st.st_mtime, p))
    for _, p in sorted(logs, reverse=True)[keep:]:
        _unlink(p)


def _alive(p: Path) -> bool:
    try:
        pid = int(p.stem.split("-", 1)[1])
    except (IndexError, ValueError):
        return False
    try:
        import psutil

        return psutil.pid_exists(pid)
    except Exception:
        return True  # do not remove a file a running worker may still need


def _unlink(p: Path) -> None:
    try:
        p.unlink()
    except OSError:
        pass
