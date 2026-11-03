"""The engine server of the Mac app (clipasso_studio/headless/server.py) with a fake job runner."""

from __future__ import annotations

import io
import json
import os
import threading
import time
from types import SimpleNamespace

from clipasso_studio import __version__
from clipasso_studio.headless.protocol import Writer, encode
from clipasso_studio.headless.server import EngineServer

TERMINAL = ("job_done", "job_failed", "job_ended")


class FakeRunner:
    """Plays a list of (kind, data) events back, ``per_poll`` at a time."""

    def __init__(self, events=(), per_poll=500):
        self.events = list(events)
        self.per_poll = per_poll
        self.started = []
        self.running = False
        self.paused = False
        self.cancelled = 0
        self.killed = 0

    def start(self, settings, target, output_root, job_dir="", auto_parallel=False, cuda=False, gpus=(), mps=False):
        self.started.append({"settings": settings, "target": target, "output_root": output_root,
                             "job_dir": job_dir, "auto_parallel": auto_parallel, "cuda": cuda, "mps": mps})
        self.running = True
        return SimpleNamespace(job_dir=job_dir or os.path.join(output_root, "job_1"))

    def poll(self, max_events=500):
        out, self.events = self.events[:self.per_poll], self.events[self.per_poll:]
        if any(kind in TERMINAL for kind, _ in out):
            self.running = False
        return [(kind, dict(data, token=1)) for kind, data in out]

    def is_running(self):
        return self.running

    def is_paused(self):
        return self.paused

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def cancel(self):
        self.cancelled += 1

    def kill(self):
        self.killed += 1
        self.running = False

    def release_idle(self, seconds):
        return False


class LockedBuffer(io.BytesIO):
    def lines(self) -> list[dict]:
        return [json.loads(line) for line in self.getvalue().split(b"\n") if line]


def _server(runner=None, mps=False, **kw):
    out = LockedBuffer()
    probe = lambda: {"torch": "2.11.0", "cuda": False, "mps": mps}  # noqa: E731
    return EngineServer(Writer(out), runner=runner or FakeRunner(), devices_probe=probe, **kw), out


def _req(i, op, **args):
    return {"id": i, "op": op, "args": args}


def _start_args(tmp_path):
    target = tmp_path / "Bild Ä.png"
    target.write_bytes(b"\x89PNG")
    return {"target": str(target), "settings": {"method": "clipasso"}, "output_root": str(tmp_path / "out")}


def test_hello():
    server, _ = _server()
    answer = server.handle(_req(1, "hello"))
    assert answer == {"id": 1, "ok": True, "result": {"protocol": 1, "app_version": __version__,
                                                       "python": answer["result"]["python"]}}


def test_devices_come_from_the_probe():
    server, _ = _server()
    assert server.handle(_req(1, "devices"))["result"] == {"torch": "2.11.0", "cuda": False, "mps": False}


def test_schema_and_models():
    server, _ = _server()
    assert server.handle(_req(1, "schema"))["result"]["format"] == 1
    assert server.handle(_req(2, "models"))["result"]["partial_dir"] == ".partial"


def test_required_models():
    server, _ = _server()
    result = server.handle(_req(1, "required_models", settings={"method": "clipasso"}))["result"]
    assert "clip:RN101" in result["required"] and set(result["missing"]) <= set(result["required"])


def test_start_streams_events_with_job_id(tmp_path):
    runner = FakeRunner([("job_start", {"seeds": [0]}), ("stage", {"seed": 0, "name": "init"})])
    server, out = _server(runner)
    answer = server.handle(_req(1, "start", **_start_args(tmp_path)))
    assert answer["ok"] and answer["result"] == {"job": "j1", "job_dir": str(tmp_path / "out" / "job_1")}
    assert runner.started[0]["auto_parallel"] is True and runner.started[0]["job_dir"] == ""
    server.pump()
    assert out.lines() == [{"event": "job_start", "job": "j1", "data": {"seeds": [0]}},
                           {"event": "stage", "job": "j1", "data": {"seed": 0, "name": "init"}}]


def test_start_continues_a_job_folder(tmp_path):
    runner = FakeRunner()
    server, _ = _server(runner)
    folder = tmp_path / "out" / "camel_20260101-120000"
    folder.mkdir(parents=True)
    answer = server.handle(_req(1, "start", resume_dir=str(folder), **_start_args(tmp_path)))
    assert answer["result"]["job_dir"] == str(folder) and runner.started[0]["job_dir"] == str(folder)


def test_start_passes_the_devices_found(tmp_path):
    for mps in (False, True):
        runner = FakeRunner()
        server, _ = _server(runner, mps=mps)
        server.handle(_req(1, "start", **_start_args(tmp_path)))
        assert runner.started[0]["mps"] is mps and runner.started[0]["cuda"] is False


def test_start_needs_the_image(tmp_path):
    server, _ = _server()
    args = dict(_start_args(tmp_path), target=str(tmp_path / "missing.png"))
    answer = server.handle(_req(1, "start", **args))
    assert answer["ok"] is False and answer["error"]["code"] == "not_found"
    assert server.handle(_req(2, "start", settings={}, output_root=""))["error"]["code"] == "bad_request"


def test_busy_while_running(tmp_path):
    server, _ = _server()
    assert server.handle(_req(1, "start", **_start_args(tmp_path)))["ok"]
    assert server.handle(_req(2, "start", **_start_args(tmp_path)))["error"]["code"] == "busy"


def test_pause_resume_cancel(tmp_path):
    runner = FakeRunner()
    server, _ = _server(runner)
    assert server.handle(_req(1, "pause"))["error"]["code"] == "no_job"
    server.handle(_req(2, "start", **_start_args(tmp_path)))
    assert server.handle(_req(3, "pause"))["result"] == {"paused": True}
    assert server.handle(_req(4, "resume"))["result"] == {"paused": False}
    assert server.handle(_req(5, "cancel"))["ok"] and runner.cancelled == 1


def test_job_done_flushes_last_iteration_and_ends_the_job(tmp_path):
    its = [("iteration", {"seed": 0, "it": i, "total": 100}) for i in range(3)]  # the 2nd and 3rd are held back
    runner = FakeRunner(its + [("seed_done", {"seed": 0}), ("job_done", {"job_dir": "x"})])
    server, out = _server(runner)
    server.handle(_req(1, "start", **_start_args(tmp_path)))
    server.pump()
    kinds = [(e["event"], e["data"].get("it")) for e in out.lines()]
    assert kinds == [("iteration", 0), ("iteration", 2), ("seed_done", None), ("job_done", None)]
    assert server.handle(_req(2, "pause"))["error"]["code"] == "no_job"


def test_bad_line_and_unknown_op_keep_serving():
    runner = FakeRunner()
    server, out = _server(runner)
    inp = io.BytesIO(b"garbage\n" + encode(_req(2, "fly")) + b"\n" + encode(_req(3, "hello")))
    assert server.serve(inp) == 0
    lines = out.lines()
    assert [(a["id"], a["ok"]) for a in lines] == [(None, False), (2, False), (3, True)]
    assert lines[0]["error"]["code"] == "bad_request" and lines[1]["error"]["code"] == "unknown_op"
    assert runner.killed == 1  # stdin ended: the job (if any) is stopped and marked interrupted


def test_shutdown_answers_then_ends():
    runner = FakeRunner()
    server, out = _server(runner)
    inp = io.BytesIO(encode(_req(1, "shutdown")) + encode(_req(2, "hello")))
    assert server.serve(inp) == 0
    assert out.lines() == [{"id": 1, "ok": True, "result": {}}] and runner.killed == 1


def test_requests_answered_during_event_flood(tmp_path):
    events = [("log", {"message": f"line {i}"}) for i in range(10_000)] + [("job_done", {"job_dir": "x"})]
    runner = FakeRunner(events, per_poll=100)
    server, out = _server(runner)
    r, w = os.pipe()
    with os.fdopen(r, "rb") as inp, os.fdopen(w, "wb", buffering=0) as feed:
        thread = threading.Thread(target=server.serve, args=(inp,), daemon=True)
        thread.start()
        feed.write(encode(_req(1, "start", **_start_args(tmp_path))))
        deadline = time.monotonic() + 10
        while not any(e.get("event") == "log" for e in out.lines()) and time.monotonic() < deadline:
            time.sleep(0.01)
        feed.write(encode(_req(2, "pause")))
        while not any(e.get("event") == "job_done" for e in out.lines()) and time.monotonic() < deadline:
            time.sleep(0.01)
    thread.join(timeout=10)
    lines = out.lines()
    pause_at = next(i for i, e in enumerate(lines) if e.get("id") == 2)
    done_at = next(i for i, e in enumerate(lines) if e.get("event") == "job_done")
    assert lines[pause_at]["ok"] and pause_at < done_at
    logs = [e["data"]["message"] for e in lines if e.get("event") == "log"]
    assert logs == [f"line {i}" for i in range(10_000)]


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_stdout_stays_clean():
    """After claim_stdout() only the protocol reaches stdout: print, a write to fd 1 and a child process (like the
    worker processes) end up on stderr."""
    import subprocess
    import sys

    code = ("import os, subprocess, sys\n"
            "from clipasso_studio.headless.__main__ import claim_stdout\n"
            "out = claim_stdout()\n"
            "print('noise from print')\n"
            "os.write(1, b'noise on fd 1\\n')\n"
            "subprocess.run([sys.executable, '-c', 'print(\"noise from a child\")'], check=True)\n"
            "out.write(b'{\"id\":1}\\n')\n")
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, cwd=ROOT, timeout=60)
    assert done.returncode == 0, done.stderr
    assert done.stdout == b'{"id":1}\n'
    for noise in (b"noise from print", b"noise on fd 1", b"noise from a child"):
        assert noise in done.stderr


def test_main_serves_over_pipes():
    import subprocess
    import sys

    env = dict(os.environ, PYTHONPATH=ROOT)
    proc = subprocess.Popen([sys.executable, "-m", "clipasso_studio.headless"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT, env=env)
    out, err = proc.communicate(encode(_req(1, "hello")) + encode(_req(2, "shutdown")), timeout=120)
    assert proc.returncode == 0, err
    answers = [json.loads(line) for line in out.splitlines()]
    assert [a["id"] for a in answers] == [1, 2] and answers[0]["result"]["protocol"] == 1


def test_probe_devices_asks_pytorch_in_a_child_process():
    import sys

    import torch

    from clipasso_studio.headless.server import probe_devices

    found = probe_devices()
    assert found == {"torch": torch.__version__.split("+")[0], "cuda": torch.cuda.is_available(),
                     "mps": bool(torch.backends.mps.is_available())}
    assert "torch" in sys.modules  # (this test imported it – the server itself does not)


def test_convert_model(monkeypatch, tmp_path):
    from clipasso_studio.engine import model_store
    from clipasso_studio.engine.errors import UserError

    calls = []

    def convert(key, root):
        calls.append((key, root))
        if key == "lama":
            raise UserError("not_downloaded", "lama is not downloaded", model=key)
        return root / "x.pt"

    monkeypatch.setattr(model_store, "convert_downloaded", convert)
    server, _ = _server()
    answer = server.handle(_req(1, "convert_model", key="clip:RN101", dest_root=str(tmp_path)))
    assert answer["result"] == {"path": str(tmp_path / "x.pt")} and calls == [("clip:RN101", tmp_path)]
    error = server.handle(_req(2, "convert_model", key="lama", dest_root=str(tmp_path)))["error"]
    assert error == {"code": "not_downloaded", "message": "lama is not downloaded", "model": "lama"}
    assert server.handle(_req(4, "convert_model", key="nope", dest_root=str(tmp_path)))["error"]["code"] == "not_found"
    assert server.handle(_req(3, "convert_model", key="", dest_root=""))["error"]["code"] == "bad_request"
