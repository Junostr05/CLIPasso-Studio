"""The engine server of the Mac app: requests in JSON lines on stdin, answers and the job's events on stdout
(``protocol.py``). One job at a time runs in :class:`engine.runner.JobRunner`'s worker processes, exactly as in the
studio; this module only translates.

ops: hello · devices · schema · models · required_models · convert_model · start · pause · resume · cancel · shutdown
"""

from __future__ import annotations

import json
import os
import platform
import queue
import subprocess
import sys
import threading
import time
import traceback
from typing import BinaryIO, Callable

from .. import __version__
from .. import settings_schema as schema
from ..engine.errors import UserError
from . import export
from .protocol import PROTOCOL_VERSION, IterationThrottle, ProtocolError, Writer, decode

TERMINAL = ("job_done", "job_failed", "job_ended")  # the last event of a job
WARM_IDLE = 300.0  # s – the waiting worker keeps its models this long after a job (like the studio)
REQUEST_WAIT = 0.05  # s – how long the loop waits for a request when no event is coming

_PROBE = ("import json, torch; mps = getattr(torch.backends, 'mps', None); "
          "print(json.dumps({'torch': torch.__version__.split('+')[0], 'cuda': bool(torch.cuda.is_available()), "
          "'mps': bool(mps is not None and mps.is_available())}))")


def probe_devices() -> dict:
    """Which devices PyTorch can use – asked in a child process, so this one does not hold PyTorch. The child gets
    no stdin: on Windows one that inherits this process's stdin pipe – which the request thread is reading – hangs
    when it starts until the next request comes (and the app waits for the answer)."""
    out = subprocess.run([sys.executable, "-c", _PROBE], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                         timeout=300)
    if out.returncode != 0:
        raise RuntimeError(f"device probe failed: {out.stderr.strip()[-2000:]}")
    return json.loads(out.stdout.strip().splitlines()[-1])


class _Fail(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _text(args: dict, key: str, required: bool = True) -> str:
    value = args.get(key, "")
    if not isinstance(value, str) or (required and not value):
        raise _Fail("bad_request", f"{key} is a text (a path)")
    return value


class EngineServer:
    def __init__(self, writer: Writer, runner=None, clock: Callable[[], float] = time.monotonic,
                 devices_probe: Callable[[], dict] = probe_devices):
        if runner is None:
            from ..engine.runner import JobRunner

            runner = JobRunner(keep_warm=True)
        self.writer = writer
        self.runner = runner
        self.throttle = IterationThrottle(clock=clock)
        self.job: str | None = None  # the id of the running job ("j1", "j2", …)
        self._count = 0
        self._probe = devices_probe
        self._devices: dict | None = None
        self._probe_error: BaseException | None = None
        self._probe_thread: threading.Thread | None = None
        self._probe_lock = threading.Lock()
        self._stopping = False

    # ------------------------------------------------------------------ requests
    def handle(self, req: dict) -> dict:
        rid = req.get("id")
        fn = getattr(self, f"op_{req.get('op')}", None)
        try:
            if fn is None:
                raise _Fail("unknown_op", f"unknown op {req.get('op')!r}")
            return {"id": rid, "ok": True, "result": fn(req.get("args") or {})}
        except _Fail as exc:
            return {"id": rid, "ok": False, "error": {"code": exc.code, "message": exc.message}}
        except UserError as exc:  # (the app shows its text ui.err.<code> with the params)
            return {"id": rid, "ok": False, "error": {"code": exc.code, "message": str(exc), **exc.params}}
        except Exception as exc:  # a fault here must not end the server
            traceback.print_exc(file=sys.stderr)
            return {"id": rid, "ok": False, "error": {"code": "internal", "message": f"{type(exc).__name__}: {exc}"}}

    def op_hello(self, args: dict) -> dict:
        return {"protocol": PROTOCOL_VERSION, "app_version": __version__, "python": platform.python_version()}

    def begin_probe(self) -> None:
        """Ask for the devices in the background (a child that imports PyTorch – slow on a Mac's first start, when
        macOS checks every library), so the first job does not wait for it in the request loop."""
        with self._probe_lock:
            if self._probe_thread is not None or self._devices is not None:
                return

            def run():
                try:
                    self._devices = self._probe()
                except BaseException as exc:  # (answered as an error by devices / start)
                    self._probe_error = exc

            self._probe_thread = threading.Thread(target=run, name="device-probe", daemon=True)
            self._probe_thread.start()

    def op_devices(self, args: dict) -> dict:
        self.begin_probe()
        thread = self._probe_thread
        if thread is not None:
            thread.join(timeout=600)
        if self._devices is None:
            raise RuntimeError(str(self._probe_error or "the device probe did not finish"))
        return dict(self._devices)

    def op_schema(self, args: dict) -> dict:
        return export.export_schema()

    def op_models(self, args: dict) -> dict:
        return export.export_models()

    def op_required_models(self, args: dict) -> dict:
        from ..engine import methods, model_store

        settings = args.get("settings")
        if not isinstance(settings, dict):
            raise _Fail("bad_request", "settings is a JSON object")
        required = list(methods.required_models(schema.normalize(settings)))
        return {"required": required, "missing": [k for k in required if not model_store.is_available(k)]}

    def op_convert_model(self, args: dict) -> dict:
        """A model the Mac app downloaded into ``dest_root``'s partial folder, converted (model_store)."""
        from pathlib import Path

        from ..engine import model_store

        key, root = _text(args, "key"), _text(args, "dest_root")
        if key not in model_store.SPECS:
            raise _Fail("not_found", f"unknown model {key}")
        return {"path": str(model_store.convert_downloaded(key, Path(root)))}

    def op_start(self, args: dict) -> dict:
        settings = args.get("settings")
        if not isinstance(settings, dict):
            raise _Fail("bad_request", "settings is a JSON object")
        target, output_root = _text(args, "target"), _text(args, "output_root")
        resume_dir = _text(args, "resume_dir", required=False)
        if self.job is not None or self.runner.is_running():
            raise _Fail("busy", "a job is already running")
        if not os.path.isfile(target):
            raise _Fail("not_found", f"the image does not exist: {target}")
        if resume_dir and not os.path.isdir(resume_dir):
            raise _Fail("not_found", f"the job folder does not exist: {resume_dir}")
        devices = self.op_devices({})
        job = self.runner.start(settings, target, output_root, job_dir=resume_dir,
                                auto_parallel=bool(args.get("auto_parallel", True)), cuda=bool(devices.get("cuda")),
                                mps=bool(devices.get("mps")))
        self._count += 1
        self.job = f"j{self._count}"
        return {"job": self.job, "job_dir": job.job_dir}

    def _running(self) -> None:
        if self.job is None:
            raise _Fail("no_job", "no job is running")

    def op_pause(self, args: dict) -> dict:
        self._running()
        self.runner.pause()
        return {"paused": self.runner.is_paused()}

    def op_resume(self, args: dict) -> dict:
        self._running()
        self.runner.resume()
        return {"paused": self.runner.is_paused()}

    def op_cancel(self, args: dict) -> dict:
        self._running()
        self.runner.cancel()
        return {"paused": self.runner.is_paused()}

    def op_shutdown(self, args: dict) -> dict:
        self._stopping = True
        return {}

    # -------------------------------------------------------------------- events
    def _send(self, kind: str, data: dict) -> None:
        self.writer.send({"event": kind, "job": self.job, "data": data})

    def pump(self) -> int:
        """Pass the job's new events on; returns how many came."""
        if self.job is None:
            self.runner.release_idle(WARM_IDLE)
            return 0
        events = self.runner.poll()
        for kind, data in events:
            data = {k: v for k, v in data.items() if k != "token"}
            if kind == "iteration":
                for item in self.throttle.offer(self.job, data):
                    self._send(kind, item)
                continue
            # a sketch's held back iteration comes before its next event (all of them before the job's end)
            if kind in TERMINAL or data.get("seed") is not None:
                for item in self.throttle.flush(self.job, None if kind in TERMINAL else data.get("seed")):
                    self._send("iteration", item)
            self._send(kind, data)
            if kind in TERMINAL:
                self.job = None
                return len(events)
        for job, item in self.throttle.due():
            if job == self.job:
                self._send("iteration", item)
        return len(events)

    # ---------------------------------------------------------------------- loop
    def serve(self, inp: BinaryIO) -> int:
        """Answer requests from ``inp`` until ``shutdown`` or its end; the running job is stopped then (and marked
        interrupted, so it can be continued). Returns the exit code."""
        lines: queue.Queue = queue.Queue()

        def read():
            for line in iter(inp.readline, b""):
                lines.put(line)
            lines.put(None)

        threading.Thread(target=read, name="requests", daemon=True).start()
        self.begin_probe()
        busy = False
        code = 0
        try:
            while True:
                try:
                    line = lines.get_nowait() if busy else lines.get(timeout=REQUEST_WAIT)
                except queue.Empty:
                    line = b""
                if line is None:
                    break
                if line.strip():
                    try:
                        self.writer.send(self.handle(decode(line)))
                    except ProtocolError as exc:
                        self.writer.send({"id": exc.request_id, "ok": False,
                                          "error": {"code": exc.code, "message": exc.message}})
                    if self._stopping:
                        break
                    continue  # requests first: an answer never waits behind a flood of events
                busy = self.pump() > 0
        except BrokenPipeError:  # the app is gone (stdout closed)
            code = 1
        finally:
            self.runner.kill()  # the job stops and is marked interrupted, whatever ended the loop
        return code
