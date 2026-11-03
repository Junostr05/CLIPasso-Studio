"""The engine as the Mac app runs it – ``python -m clipasso_studio.headless`` as a child process with JSON lines –
for the end-to-end tests (test_headless_e2e.py, test_runner_orphans.py)."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "clipasso_studio" / "resources" / "samples" / "camel.png"


def tiny_settings(**changes) -> dict:
    """A small CLIPasso job on the CPU (no mask: the bundled models are enough)."""
    return {"method": "clipasso", "num_iter": 30, "num_sketches": 1, "device": "cpu", "mask_object": False,
            "save_interval": 10, **changes}


def image_in(folder: Path, name: str = "Bild Ä.png") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    shutil.copyfile(SAMPLE, target)
    return target


class Engine:
    def __init__(self, tmp_path: Path):
        env = dict(os.environ, PYTHONPATH=str(ROOT), XDG_DATA_HOME=str(tmp_path / "data"),
                   LOCALAPPDATA=str(tmp_path / "data"), PYTHONUNBUFFERED="1")
        if sys.platform == "darwin":  # (the app data lives under ~/Library there)
            env["HOME"] = str(tmp_path / "home")
        self.log_path = tmp_path / "engine-stderr.log"
        self._log = open(self.log_path, "wb")
        self.proc = subprocess.Popen([sys.executable, "-m", "clipasso_studio.headless"], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=self._log, cwd=ROOT, env=env)
        self.messages: queue.Queue = queue.Queue()
        self.events: list[dict] = []
        self.bad: list[bytes] = []  # stdout lines that were not JSON (must stay empty)
        self._id = 0
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in iter(self.proc.stdout.readline, b""):
            try:
                self.messages.put(json.loads(line))
            except ValueError:
                self.bad.append(line)
        self.messages.put(None)

    def _next(self, deadline: float) -> dict | None:
        try:
            msg = self.messages.get(timeout=max(0.0, deadline - time.monotonic()))
        except queue.Empty:
            raise TimeoutError(f"no message from the engine – its log:\n{self.stderr()[-4000:]}") from None
        if msg is not None and "event" in msg:
            self.events.append(msg)
        return msg

    def request(self, op: str, timeout: float = 120, **args) -> dict:
        self._id += 1
        rid = self._id
        self.proc.stdin.write(json.dumps({"id": rid, "op": op, "args": args}).encode("utf-8") + b"\n")
        self.proc.stdin.flush()
        deadline = time.monotonic() + timeout
        while True:
            msg = self._next(deadline)
            if msg is None:
                raise EOFError(f"the engine ended – its log:\n{self.stderr()[-4000:]}")
            if msg.get("id") == rid:
                return msg

    def wait_event(self, kind: str, timeout: float = 600, since: int = 0) -> dict:
        """The first event of ``kind`` from index ``since`` of :attr:`events` on (waiting for it if needed)."""
        deadline = time.monotonic() + timeout
        while True:
            for event in self.events[since:]:
                if event["event"] == kind:
                    return event
            if self._next(deadline) is None:
                raise EOFError(f"the engine ended before {kind} – its log:\n{self.stderr()[-4000:]}")

    def stderr(self) -> str:
        self._log.flush()
        return self.log_path.read_text(encoding="utf-8", errors="replace")

    def close(self, timeout: float = 30):
        if self.proc.poll() is None:
            try:
                self.proc.stdin.close()
            except OSError:
                pass
            try:
                self.proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self._log.close()
