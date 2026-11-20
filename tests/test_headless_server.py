"""The engine server of the Mac app (clipasso_studio/headless/server.py) with a fake job runner."""

from __future__ import annotations

import io
import json
import os
import threading
import time
from pathlib import Path
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


def test_model_roles():
    from clipasso_studio import settings_schema as schema
    from clipasso_studio.engine import methods, model_store
    from clipasso_studio.gui import model_roles

    server, _ = _server()
    settings = {"clip_model_name": "RN101", "semantic_model": "clip"}
    result = server.handle(_req(1, "model_roles", method="clipasso", settings=settings,
                                methods={"swiftsketch": {}, "nope": {}}))["result"]
    rows = model_roles.rows("clipasso", settings)
    assert [{k: v for k, v in r.items() if k != "choices"} for r in result["roles"]] == rows
    semantic = next(r for r in result["roles"] if r["key"] == "semantic_model")
    assert [c["value"] for c in semantic["choices"]] == list(schema.param("clipasso", "semantic_model").choices)
    assert any(c["experimental"] for c in semantic["choices"]) and not semantic["experimental"]
    assert result["in_use"] == sorted(model_roles.in_use("clipasso", settings))
    need = methods.required_models(schema.normalize({**settings, "method": "clipasso"}))
    assert result["missing"] == [k for k in need if not model_store.is_available(k)]
    assert set(result["methods"]) == {"swiftsketch"}
    assert server.handle(_req(2, "model_roles", method="nope", settings={}))["error"]["code"] == "bad_request"


def test_rerun_cell(tmp_path):
    """A SceneSketch cell computed again: it and the later levels of its layer are removed for the job to continue
    (jobs.rerun_scene_cell); dry only names the later levels; another method's job is refused."""
    import json as _json

    from clipasso_studio import settings_schema as schema
    from clipasso_studio.engine import jobs

    server, _ = _server()
    settings = {**schema.start_settings("scenesketch"), "layers": "8", "simplicity_levels": 3,
                "simplicity_pick": "1_2_3"}
    job = tmp_path / "Kamel_scene"
    job.mkdir()
    (job / jobs.STATE_FILE).write_text(_json.dumps({"settings": settings, "target": "/Bilder/Kamel.png",
                                                    "status": "done"}), encoding="utf-8")
    for level in (0, 1, 2, 3):
        (job / schema.scene_run_name("/Bilder/Kamel.png", 8, level)).mkdir()
    dry = server.handle(_req(1, "rerun_cell", job_dir=str(job), cell=801, dry=True))["result"]
    assert dry == {"later": [2, 3]} and (job / "Kamel_scenesketch_L8_level1").is_dir()
    done = server.handle(_req(2, "rerun_cell", job_dir=str(job), cell=801))["result"]
    assert done == {"later": [2, 3], "removed": [801, 802, 803]}
    assert (job / "Kamel_scenesketch_L8_level0").is_dir() and not (job / "Kamel_scenesketch_L8_level2").exists()
    assert jobs.read_cell_seeds(str(job)) == {"801": settings["seed"] + 1}
    (job / jobs.STATE_FILE).write_text(_json.dumps({"settings": {"method": "clipasso"}}), encoding="utf-8")
    assert server.handle(_req(3, "rerun_cell", job_dir=str(job), cell=801))["error"]["code"] == "not_found"


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


class FloodRunner(FakeRunner):
    """Sends log lines, ``per_poll`` at a time, for as long as it is not paused (at most ``limit``); after the pause
    one more batch and the job's end. So the flood is still under way whenever a request comes, however fast the
    computer – and it ends only when the server took a request in during it."""

    def __init__(self, per_poll=100, limit=2_000_000):
        super().__init__([], per_poll)
        self.sent, self.limit, self.ended = 0, limit, False

    def poll(self, max_events=500):
        if self.ended:
            return []
        batch = [("log", {"message": f"line {self.sent + i}"}) for i in range(self.per_poll)]
        self.sent += self.per_poll
        if self.paused or self.sent >= self.limit:
            batch.append(("job_done", {"job_dir": "x", "paused": self.paused}))
            self.ended, self.running = True, False
        return [(kind, dict(data, token=1)) for kind, data in batch]


def test_requests_answered_during_event_flood(tmp_path):
    runner = FloodRunner()
    server, out = _server(runner)
    r, w = os.pipe()
    with os.fdopen(r, "rb") as inp, os.fdopen(w, "wb", buffering=0) as feed:
        thread = threading.Thread(target=server.serve, args=(inp,), daemon=True)
        thread.start()
        feed.write(encode(_req(1, "start", **_start_args(tmp_path))))
        deadline = time.monotonic() + 30
        while not any(e.get("event") == "log" for e in out.lines()) and time.monotonic() < deadline:
            time.sleep(0.01)
        feed.write(encode(_req(2, "pause")))
        while not runner.ended and time.monotonic() < deadline:
            time.sleep(0.01)
    thread.join(timeout=10)
    lines = out.lines()
    pause_at = next(i for i, e in enumerate(lines) if e.get("id") == 2)
    done_at = next(i for i, e in enumerate(lines) if e.get("event") == "job_done")
    assert lines[pause_at]["ok"] and pause_at < done_at
    assert lines[done_at]["data"]["paused"] is True  # (the flood ended because of the pause, not at its limit)
    logs = [e["data"]["message"] for e in lines if e.get("event") == "log"]
    assert len(logs) >= 100 and logs == [f"line {i}" for i in range(len(logs))]  # every line, in order


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


def test_probe_gets_no_stdin(monkeypatch):
    """On Windows a child that inherits the engine's stdin pipe hangs at its start while the request thread reads
    that pipe – the first job never got its answer there."""
    import subprocess

    from clipasso_studio.headless import server

    seen = {}

    def run(cmd, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, stdout='{"torch": "2", "cuda": false, "mps": false}\n', stderr="")

    monkeypatch.setattr(server.subprocess, "run", run)
    assert server.probe_devices() == {"torch": "2", "cuda": False, "mps": False}
    assert seen["stdin"] is subprocess.DEVNULL


def test_devices_answer_while_the_app_waits(tmp_path):
    """The real engine answers ``devices`` (its probe a child process) with no further request coming – the app
    waits for the answer (on Windows the probe hung until the next line on stdin)."""
    from tests.headless_engine import Engine

    engine = Engine(tmp_path)
    try:
        answer = engine.request("devices", timeout=90)
        assert answer["ok"] and set(answer["result"]) == {"torch", "cuda", "mps"}, answer
    finally:
        engine.close()


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


def test_a_lost_stdout_still_stops_the_job():
    """When the app is gone, writing an answer fails (broken pipe): the job is stopped and marked interrupted anyway."""
    class Broken(io.BytesIO):
        def write(self, data):
            raise BrokenPipeError(32, "Broken pipe")

    runner = FakeRunner()
    server = EngineServer(Writer(Broken()), runner=runner, devices_probe=lambda: {"cuda": False, "mps": False})
    assert server.serve(io.BytesIO(encode(_req(1, "hello")))) == 1
    assert runner.killed == 1


def test_probe_runs_ahead_and_requests_do_not_wait():
    """The device probe (a child importing PyTorch – slow on a Mac's first start) begins when the server serves;
    hello is answered meanwhile, and devices waits for the probe under way instead of starting another."""
    started, release = threading.Event(), threading.Event()
    calls = []

    def probe():
        calls.append(1)
        started.set()
        release.wait(10)
        return {"torch": "2.11.0", "cuda": False, "mps": True}

    server = EngineServer(Writer(LockedBuffer()), runner=FakeRunner(), devices_probe=probe)
    server.begin_probe()
    assert started.wait(5)
    t0 = time.monotonic()
    assert server.handle(_req(1, "hello"))["ok"] and time.monotonic() - t0 < 1  # (not behind the probe)
    answers = []
    waiter = threading.Thread(target=lambda: answers.append(server.handle(_req(2, "devices"))))
    waiter.start()
    time.sleep(0.2)
    assert answers == []  # waits for the probe under way
    release.set()
    waiter.join(5)
    assert answers[0]["result"]["mps"] is True and calls == [1]  # one probe only


def test_a_failed_probe_is_answered_as_an_error():
    def probe():
        raise RuntimeError("device probe failed: no torch")

    server = EngineServer(Writer(LockedBuffer()), runner=FakeRunner(), devices_probe=probe)
    server.begin_probe()
    answer = server.handle(_req(1, "devices"))
    assert answer["ok"] is False and "no torch" in answer["error"]["message"]


def test_stdin_handle_released_only_on_windows(monkeypatch):
    """Elsewhere the standard input stays as it is (the Windows part runs in the Windows CI's end-to-end tests)."""
    import sys

    from clipasso_studio.headless import __main__ as entry

    monkeypatch.setattr(sys, "platform", "linux")
    before = os.fstat(0) if hasattr(os, "fstat") else None
    entry.release_stdin_handle()
    assert (os.fstat(0) if before is not None else None) == before


def test_hang_dump_is_armed_only_when_asked(monkeypatch):
    import faulthandler

    from clipasso_studio.headless import __main__ as entry

    armed = []
    monkeypatch.setattr(faulthandler, "dump_traceback_later", lambda t, **kw: armed.append(t))
    monkeypatch.delenv("CLIPASSO_HANG_DUMP", raising=False)
    entry.dump_when_hung()
    monkeypatch.setenv("CLIPASSO_HANG_DUMP", "100")
    entry.dump_when_hung()
    assert armed == [100.0]


def test_read_lines_gives_every_line_then_the_end():
    from clipasso_studio.headless.server import read_lines

    got = []
    read_lines(io.BytesIO(b'{"id": 1}\n{"id": 2}\nlast without newline'), got.append)
    assert got == [b'{"id": 1}\n', b'{"id": 2}\n', b"last without newline", None]


def test_read_lines_on_a_windows_pipe(monkeypatch):
    """On a Windows pipe the lines come from what PeekNamedPipe says is there – never a blocking read; pieces of a
    line are put together, the closed pipe is the end."""
    import sys
    import types

    from clipasso_studio.headless import server

    chunks = [b'{"id": 1}\n{"i', b'd": 2}\n', b"", b"tail"]
    sizes = [len(c) for c in chunks if c]
    reads = []
    fake_winapi = types.SimpleNamespace()

    def peek(handle, size):
        while chunks and chunks[0] == b"":
            chunks.pop(0)
            return (0, 0)
        if not chunks:
            raise BrokenPipeError(109, "the pipe has been ended")
        return (len(chunks[0]), 0)

    fake_winapi.PeekNamedPipe = peek
    monkeypatch.setitem(sys.modules, "_winapi", fake_winapi)
    monkeypatch.setattr(server, "_windows_pipe", lambda inp: 7)
    monkeypatch.setattr(server.os, "read", lambda fd, n: reads.append(n) or chunks.pop(0))
    monkeypatch.setattr(server, "PIPE_POLL", 0)

    class Inp:
        def fileno(self):
            return 3

    got = []
    server.read_lines(Inp(), got.append)
    assert got == [b'{"id": 1}\n', b'{"id": 2}\n', b"tail", None]
    assert reads == sizes  # exactly what was there each time


def test_encode_webp(tmp_path):
    """The Mac app draws an animation's frames and the engine writes them as an animated WebP with Pillow."""
    from PIL import Image

    paths = []
    for i, colour in enumerate(((255, 255, 255, 255), (0, 0, 0, 0), (20, 30, 40, 255))):
        path = tmp_path / f"frame_{i:05d}.png"
        Image.new("RGBA", (8, 6), colour).save(path)
        paths.append(str(path))
    server, _ = _server()
    dest = tmp_path / "Zeichnung ä.webp"
    answer = server.handle(_req(1, "encode_webp", frames=paths, durations=[100, 100.0, 1500], dest=str(dest),
                                background=None))
    assert answer["ok"] and answer["result"] == {"path": str(dest), "frames": 3}
    with Image.open(dest) as webp:
        assert webp.format == "WEBP" and webp.n_frames == 3 and webp.size == (8, 6)
        webp.seek(1)
        assert webp.convert("RGBA").getpixel((0, 0))[3] == 0  # (transparent stays transparent)
        webp.seek(2)
        webp.load()  # (Pillow reads a frame's duration with the frame)
        assert webp.info["duration"] == 1500
    opaque = tmp_path / "opaque.webp"
    assert server.handle(_req(2, "encode_webp", frames=paths, durations=[50, 50, 50], dest=str(opaque),
                              background=[255, 255, 255]))["ok"]
    with Image.open(opaque) as webp:
        webp.seek(1)
        assert webp.convert("RGBA").getpixel((0, 0))[3] == 255
    bad = [dict(frames=[], durations=[], dest=str(dest)), dict(frames=paths, durations=[1, 2], dest=str(dest)),
           dict(frames=paths, durations=[1, 2, 0], dest=str(dest)), dict(frames=paths, durations=[1, 2, 3], dest=""),
           dict(frames=paths, durations=[1, 2, 3], dest=str(dest), background=[1, 2])]
    for i, args in enumerate(bad):
        assert server.handle(_req(10 + i, "encode_webp", **args))["error"]["code"] == "bad_request", args
    gone = server.handle(_req(20, "encode_webp", frames=paths + [str(tmp_path / "nope.png")], durations=[1, 2, 3, 4],
                              dest=str(dest)))
    assert gone["error"]["code"] == "not_found"


def test_stylize():
    """The Mac app draws the brush styles: the engine turns its sketches into the style's plain SVG geometry, the
    same as the studio's exports (random offsets seeded: the same every time)."""
    from clipasso_studio.gui import brush

    sketch = ('<svg xmlns="http://www.w3.org/2000/svg" width="224" height="224" viewBox="0 0 224 224">'
              '<path d="M 10 10 C 60 0 120 80 200 40" fill="none" stroke="#000000" stroke-width="2"/></svg>')
    server, _ = _server()
    answer = server.handle(_req(1, "stylize", svgs=[sketch, sketch], style="charcoal"))
    assert answer["ok"]
    styled = answer["result"]["svgs"]
    assert styled == [brush.stylize_svg(sketch, "charcoal")] * 2
    assert styled[0].count("<path") == 9 and "stroke-dasharray" in styled[0]  # (a smudge and eight grainy streaks)
    plain = server.handle(_req(2, "stylize", svgs=[sketch], style="plain"))
    assert plain["result"]["svgs"] == [sketch]
    assert server.handle(_req(3, "stylize", svgs=[], style="ink"))["result"]["svgs"] == []
    for i, args in enumerate([dict(svgs=sketch, style="ink"), dict(svgs=[sketch], style="glitter"),
                              dict(svgs=[1], style="ink"), dict(svgs=["<svg"], style="ink")]):
        assert server.handle(_req(10 + i, "stylize", **args))["error"]["code"] == "bad_request", args


def test_masks(tmp_path, user_data):
    """The Mac app's object mask: what is known at once (the model's from the mask cache, the user's edited one),
    the model's computed in a process of its own (here a stand-in) – one at a time, the newest waiting – with
    "mask_ready" / "mask_failed", and the user's mask kept by the image's content."""
    import queue as queue_mod

    from PIL import Image

    from clipasso_studio.engine import masking
    from clipasso_studio.engine.imaging import load_rgb

    image, other = tmp_path / "Kamel ä.png", tmp_path / "zwei.png"
    Image.new("RGB", (40, 30), (200, 120, 60)).save(image)
    Image.new("RGB", (40, 30), (20, 120, 60)).save(other)
    started = []

    def work(path, model, device):
        started.append((path, model, device, queue_mod.Queue()))
        return started[-1][3], None

    server, out = _server(mask_work=work)
    first = server.handle(_req(1, "mask", image=str(image), model="u2net"))["result"]
    assert first == {"probability": None, "edited": None, "width": 40, "height": 30, "threshold": 0.5,
                     "computing": False}
    assert server.handle(_req(2, "mask", image=str(image), model="u2net", compute=True))["result"]["computing"]
    assert server.handle(_req(3, "mask", image=str(other), model="u2net", compute=True))["result"]["computing"]
    assert [s[:3] for s in started] == [(str(image), "u2net", "auto")]  # (the other one waits)
    assert server.pump() == 0
    started[0][3].put(("done", {"path": "/cache/u2net-key.png"}))
    assert server.pump() == 1
    assert out.lines()[-1] == {"event": "mask_ready", "job": None,
                               "data": {"image": str(image), "model": "u2net", "probability": "/cache/u2net-key.png"}}
    assert [s[0] for s in started] == [str(image), str(other)]  # (then the one that waited)
    started[1][3].put(("error", "RuntimeError: no memory"))
    server.pump()
    assert out.lines()[-1]["event"] == "mask_failed" and out.lines()[-1]["data"]["message"] == "RuntimeError: no memory"
    # the user's mask: the left half, kept by the image's content
    painted = tmp_path / "painted.png"
    mask = Image.new("L", (40, 30), 0)
    mask.paste(255, (0, 0, 20, 30))
    mask.save(painted)
    saved = server.handle(_req(4, "save_mask", image=str(image), mask=str(painted)))["result"]["path"]
    im = load_rgb(str(image))
    assert saved == str(masking.edited_mask_path(im))
    kept = masking.edited_mask(im)
    assert kept is not None and kept[:, :20].all() and not kept[:, 20:].any()
    assert server.handle(_req(5, "mask", image=str(image), model="u2net"))["result"]["edited"] == saved
    small = tmp_path / "small.png"
    Image.new("L", (10, 10), 255).save(small)
    assert server.handle(_req(6, "save_mask", image=str(image), mask=str(small)))["error"]["code"] == "bad_request"
    assert server.handle(_req(7, "remove_mask", image=str(image)))["ok"]
    assert masking.edited_mask(im) is None
    assert server.handle(_req(8, "mask", image=str(image), model="sam"))["error"]["code"] == "bad_request"
    assert server.handle(_req(9, "mask", image=str(tmp_path / "nope.png")))["error"]["code"] == "not_found"


def test_detail_brush(tmp_path, user_data, monkeypatch):
    """The Mac app's detail brush: the stored map at the size the studio paints it (the image at most 1024 pixels),
    a painted map kept at the image's size (all normal: removed), and portrait mode's faces found in a process of
    its own (here a stand-in) with "portrait_ready" / "portrait_failed" – without the detector: missing_model."""
    import queue as queue_mod

    import numpy as np
    from PIL import Image

    from clipasso_studio.engine import details, model_store
    from clipasso_studio.engine.imaging import load_rgb
    from clipasso_studio.gui import detail_edit, portrait
    from clipasso_studio.headless import detail_brush

    assert (detail_brush.EDIT_SIDE, detail_brush.FACE_MODEL) == (detail_edit.EDIT_SIDE, portrait.KEY)
    image, large = tmp_path / "Gesicht ü.png", tmp_path / "groß.png"
    Image.new("RGB", (40, 30), (200, 120, 60)).save(image)
    Image.new("RGB", (2048, 1001), (20, 120, 60)).save(large)
    started = []

    def work(path, model, device):
        started.append((path, model, device, queue_mod.Queue()))
        return started[-1][3], None

    server, out = _server(face_work=work)
    first = server.handle(_req(1, "detail", image=str(image)))["result"]
    assert first == {"map": None, "width": 40, "height": 30, "has": False, "normal": 128}
    photo = load_rgb(str(large))
    photo.thumbnail((1024, 1024))
    sized = server.handle(_req(2, "detail", image=str(large)))["result"]
    assert (sized["width"], sized["height"]) == photo.size == (1024, 501)
    # a painted map: the left half "more", at the painting size of the large image – kept at the image's size
    painted = np.full((501, 1024), 128, np.uint8)
    painted[:, :512] = 255
    path = tmp_path / "painted.png"
    Image.fromarray(painted, mode="L").save(path)
    saved = server.handle(_req(3, "save_detail", image=str(large), map=str(path)))["result"]["path"]
    im = load_rgb(str(large))
    assert saved == str(details.detail_path(im))
    kept = details.detail_map(im)
    assert kept is not None and kept.shape == (1001, 2048) and kept[:, :1000].min() > 0.99 and kept[:, 1040:].max() == 0
    again = server.handle(_req(4, "detail", image=str(large)))["result"]
    assert again["has"] and again["map"] is not None
    with Image.open(again["map"]) as m:
        start = np.asarray(m)
    os.remove(again["map"])
    assert start.shape == (501, 1024) and start[:, :500].min() == 255 and start[:, 530:].max() == 128
    Image.fromarray(np.full((501, 1024), 129, np.uint8), mode="L").save(path)  # (all but normal: removed)
    assert server.handle(_req(5, "save_detail", image=str(large), map=str(path)))["result"]["path"] is None
    assert not details.detail_path(im).is_file()
    assert server.handle(_req(6, "save_detail", image=str(large), map=str(tmp_path / "no.png")))["error"]["code"] \
        == "not_found"
    # the phone's map (phone_api.file_details: at most 900 px, each side rounded) and removing it
    Image.fromarray(painted, mode="L").save(path)
    server.handle(_req(60, "save_detail", image=str(large), map=str(path)))
    phone = server.handle(_req(61, "phone_detail", image=str(large), side=900))["result"]["map"]
    with Image.open(phone) as m:
        small = np.asarray(m)
    os.remove(phone)
    assert small.shape == (round(1001 * 900 / 2048), 900)
    assert small[:, :400].min() == 255 and small[:, 480:].max() == 128
    assert server.handle(_req(62, "phone_detail", image=str(large), side=True))["error"]["code"] == "bad_request"
    assert server.handle(_req(63, "remove_detail", image=str(large)))["ok"] and details.detail_map(im) is None
    plain = server.handle(_req(64, "phone_detail", image=str(image), side=900))["result"]["map"]
    with Image.open(plain) as m:
        assert m.size == (40, 30) and set(m.getdata()) == {128}  # (no map: all normal, never larger than the image)
    os.remove(plain)
    # portrait mode
    monkeypatch.setattr(model_store, "is_available", lambda key: False)
    missing = server.handle(_req(7, "portrait", image=str(image)))["error"]
    assert missing == {"code": "missing_model", "message": "blazeface"}
    monkeypatch.setattr(model_store, "is_available", lambda key: key == "blazeface")
    assert server.handle(_req(8, "portrait", image=str(image)))["result"] == {"computing": True}
    assert [s[:3] for s in started] == [(str(image), "blazeface", "cpu")]
    started[0][3].put(("done", {"path": None}))  # (no face)
    assert server.pump() == 1
    assert out.lines()[-1] == {"event": "portrait_ready", "job": None,
                               "data": {"image": str(image), "model": "blazeface", "map": None}}
    server.handle(_req(9, "portrait", image=str(image)))
    started[1][3].put(("done", {"path": "/tmp/faces.png"}))
    server.pump()
    assert out.lines()[-1]["data"]["map"] == str(Path("/tmp/faces.png"))
    server.handle(_req(10, "portrait", image=str(image)))
    started[2][3].put(("error", "RuntimeError: no torch"))
    server.pump()
    last = out.lines()[-1]
    assert last["event"] == "portrait_failed" and last["data"]["message"] == "RuntimeError: no torch"


def test_portrait_modes_map(tmp_path, monkeypatch):
    """The faces' map is the studio's: portrait.detail_map of the plausible faces in the studio's photo."""
    from PIL import Image

    from clipasso_studio.engine import model_store, portrait
    from clipasso_studio.headless import detail_brush

    image = tmp_path / "face.png"
    Image.new("RGB", (1600, 1200), (90, 90, 90)).save(image)
    face = {"box": (300.0, 200.0, 600.0, 560.0), "score": 0.95,
            "points": {"right_eye": (380.0, 320.0), "left_eye": (520.0, 320.0), "nose": (450.0, 400.0),
                       "mouth": (450.0, 470.0), "right_ear": (310.0, 340.0), "left_ear": (590.0, 340.0)}}
    seen = []
    monkeypatch.setattr(model_store, "require", lambda key: tmp_path / f"{key}.pt")
    monkeypatch.setattr(portrait, "load", lambda path, device="cpu": path)
    unsure = {**face, "score": 0.5}
    monkeypatch.setattr(portrait, "find_faces", lambda photo, net: seen.append(photo.size) or [face, unsure])
    path = detail_brush.faces(str(image))
    with Image.open(path) as m:
        got = m.copy()
    os.remove(path)
    assert seen == [(1024, 768)] and got.size == (1024, 768) and got.mode == "L"
    assert list(got.getdata()) == list(Image.fromarray(portrait.detail_map((1024, 768), [face]), mode="L").getdata())
    monkeypatch.setattr(portrait, "find_faces", lambda photo, net: [unsure])
    assert detail_brush.faces(str(image)) is None


def test_the_engine_starts_without_numpy():
    """The engine answers "hello" before any heavy library is loaded: the Mac app's tests start it in a Python with
    Pillow only, and the app waits for it at every start."""
    import subprocess
    import sys

    code = "import sys, clipasso_studio.headless.server; print(sorted({'numpy', 'torch'} & set(sys.modules)))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"
