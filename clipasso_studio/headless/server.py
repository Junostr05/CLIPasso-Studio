"""The engine server of the Mac app: requests in JSON lines on stdin, answers and the job's events on stdout
(``protocol.py``). One job at a time runs in :class:`engine.runner.JobRunner`'s worker processes, exactly as in the
studio; this module only translates.

ops: hello · devices · schema · models · required_models · model_roles · rerun_cell · convert_model · encode_webp ·
stylize · mask · save_mask · remove_mask · detail · save_detail · phone_detail · remove_detail · portrait ·
importance · continue_sketch · start ·
pause · resume · cancel · shutdown
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
from . import detail_brush, export, masks
from .protocol import PROTOCOL_VERSION, IterationThrottle, ProtocolError, Writer, decode

TERMINAL = ("job_done", "job_failed", "job_ended")  # the last event of a job
WARM_IDLE = 300.0  # s – the waiting worker keeps its models this long after a job (like the studio)
REQUEST_WAIT = 0.05  # s – how long the loop waits for a request when no event is coming

_PROBE = ("import json, torch; mps = getattr(torch.backends, 'mps', None); "
          "print(json.dumps({'torch': torch.__version__.split('+')[0], 'cuda': bool(torch.cuda.is_available()), "
          "'mps': bool(mps is not None and mps.is_available())}))")


PIPE_POLL = 0.02  # s – how often a Windows pipe is looked at when nothing came


def _windows_pipe(inp) -> int | None:
    """The OS handle of ``inp`` when it is a pipe on Windows (else None)."""
    if sys.platform != "win32":
        return None
    try:
        import msvcrt

        import _winapi

        handle = msvcrt.get_osfhandle(inp.fileno())
        _winapi.PeekNamedPipe(handle, 0)
        return handle
    except (OSError, ValueError, AttributeError, ImportError):
        return None


def read_lines(inp, put: Callable[[bytes | None], None]) -> None:
    """Pass every line of ``inp`` to ``put``, then None at its end.

    On Windows a pipe is never read blockingly: while a thread waits in a synchronous read of a pipe, every other
    use of that pipe waits too – importing numpy in the main thread hung there (its DLLs look at the standard
    handles), as did child processes that got the pipe as their stdin. So the thread asks how much is there
    (PeekNamedPipe) and reads only that."""
    handle = _windows_pipe(inp)
    if handle is None:
        for line in iter(inp.readline, b""):
            put(line)
        put(None)
        return
    import _winapi

    fd, pending = inp.fileno(), b""
    while True:
        try:
            available = _winapi.PeekNamedPipe(handle, 0)[0]
        except OSError:  # the writer closed it (ERROR_BROKEN_PIPE): the end
            break
        if not available:
            time.sleep(PIPE_POLL)
            continue
        pending += os.read(fd, available)
        *complete, pending = pending.split(b"\n")
        for line in complete:
            put(line + b"\n")
    if pending:
        put(pending)
    put(None)


def probe_devices() -> dict:
    """Which devices PyTorch can use – asked in a child process, so this one does not hold PyTorch. The child gets
    no stdin: on Windows one that inherits this process's stdin pipe – which the request thread is reading – hangs
    when it starts until the next request comes (and the app waits for the answer)."""
    out = subprocess.run([sys.executable, "-c", _PROBE], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                         timeout=300)
    if out.returncode != 0:
        raise RuntimeError(f"device probe failed: {out.stderr.strip()[-2000:]}")
    return json.loads(out.stdout.strip().splitlines()[-1])


def importance_worker(run_dir: str, model: str, device: str, results) -> None:
    """The process of the studio's "Simplify" (headless.masks.Previews; ``--importance`` of the Windows studio): what
    each stroke of the run's sketch adds – ("done", {"path": importance.json}) or ("error", why)."""
    try:
        from ..engine import importance

        results.put(("done", {"path": importance.compute(run_dir, device)}))
    except Exception as exc:  # reported to the app
        results.put(("error", f"{type(exc).__name__}: {exc}"))


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
                 devices_probe: Callable[[], dict] = probe_devices, mask_work: Callable | None = None,
                 face_work: Callable | None = None, importance_work: Callable | None = None):
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
        # (the object masks: one computed at a time, in a process of its own; ``mask_work`` stands in for it in tests)
        notice = lambda kind, data: self.writer.send({"event": kind, "job": None, "data": data})  # noqa: E731
        self.masks = masks.Previews(notice, mask_work)
        # (portrait mode's faces, the same way: BlazeFace in a process of its own)
        self.faces = masks.Previews(notice, face_work, kind="portrait", worker=detail_brush.face_worker, result="map")
        # (Simplify's measuring of the strokes of a run's sketch, the same way)
        self.importance = masks.Previews(notice, importance_work, kind="importance", worker=importance_worker,
                                         result="path")

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

    def op_model_roles(self, args: dict) -> dict:
        """The models the studio's settings choose, by task (gui/model_roles.py, the models page): each role with the
        models its value needs and the models each of its choices would need; every model the settings need, the
        missing ones, and the missing ones of the other methods with their settings (``methods``)."""
        from .. import settings_schema as schema
        from ..engine import methods, model_store
        from ..gui import model_roles

        method, settings, others = args.get("method"), args.get("settings"), args.get("methods") or {}
        if method not in model_roles.ROLES:
            raise _Fail("bad_request", f"unknown method {method}")
        if not isinstance(settings, dict) or not isinstance(others, dict):
            raise _Fail("bad_request", "settings and methods are JSON objects")
        roles = []
        for row in model_roles.rows(method, settings):
            param = schema.param(method, row["key"])
            choices = [{"value": c, "experimental": any(model_roles.experimental(k) for k in
                                                        model_roles.choice_models(method, row["key"], c, settings))}
                       for c in (param.choices or ())] if param.kind == "choice" else []
            roles.append({**row, "choices": choices})

        def missing(values: dict) -> list[str]:
            return [k for k in methods.required_models(schema.normalize(values)) if not model_store.is_available(k)]

        return {"roles": roles, "in_use": sorted(model_roles.in_use(method, settings)),
                "missing": missing({**settings, "method": method}),
                "methods": {m: bool(missing({**(v if isinstance(v, dict) else {}), "method": m}))
                            for m, v in others.items() if m in model_roles.ROLES}}

    def op_rerun_cell(self, args: dict) -> dict:
        """SceneSketch: a cell of a job's matrix computed again with a new start (jobs.rerun_scene_cell) – the cell
        and the later levels of its layer, which start from it, are removed for the job to continue; ``dry`` only
        names the later levels (the question before)."""
        from ..engine import jobs

        job_dir = _text(args, "job_dir")
        try:
            cell = int(args.get("cell"))
        except (TypeError, ValueError):
            raise _Fail("bad_request", "cell is a number") from None
        state = jobs.read_state(job_dir)
        if not state or schema.method_of(state.get("settings")) != "scenesketch":
            raise _Fail("not_found", f"no SceneSketch job in {job_dir}")
        level = cell % 100
        later = [lv for lv in schema.scene_levels(state.get("settings") or {}) if lv > level]
        if args.get("dry"):
            return {"later": later}
        return {"later": later, "removed": jobs.rerun_scene_cell(job_dir, cell)}

    def op_convert_model(self, args: dict) -> dict:
        """A model the Mac app downloaded into ``dest_root``'s partial folder, converted (model_store)."""
        from pathlib import Path

        from ..engine import model_store

        key, root = _text(args, "key"), _text(args, "dest_root")
        if key not in model_store.SPECS:
            raise _Fail("not_found", f"unknown model {key}")
        return {"path": str(model_store.convert_downloaded(key, Path(root)))}

    def op_encode_webp(self, args: dict) -> dict:
        """An animated WebP of frames the Mac app drew (PNG files) – written with Pillow as export._encode writes
        it: lossless, repeating, each frame for its ``durations`` ms; ``background`` [r, g, b] or None
        (transparent)."""
        import os

        from PIL import Image

        frames, durations = args.get("frames"), args.get("durations")
        if (not isinstance(frames, list) or not frames or not all(isinstance(f, str) and f for f in frames)
                or not isinstance(durations, list) or len(durations) != len(frames)
                or not all(isinstance(d, (int, float)) and not isinstance(d, bool) and d > 0 for d in durations)):
            raise _Fail("bad_request", "frames are paths of PNG files and durations their milliseconds, as many")
        dest = _text(args, "dest")
        background = args.get("background")
        if background is not None and (not isinstance(background, list) or len(background) != 3
                                       or not all(isinstance(c, int) and 0 <= c <= 255 for c in background)):
            raise _Fail("bad_request", "background is [r, g, b] or null (transparent)")
        missing = [f for f in frames if not os.path.isfile(f)]
        if missing:
            raise _Fail("not_found", f"no frame {missing[0]}")
        images = []
        for path in frames:
            with Image.open(path) as image:
                images.append(image.convert("RGBA" if background is None else "RGB"))
        try:
            images[0].save(dest, format="WEBP", save_all=True, append_images=images[1:], duration=durations, loop=0,
                           lossless=True, method=4,
                           background=(0, 0, 0, 0) if background is None else (*background, 255))
        except BaseException:
            try:
                os.remove(dest)
            except OSError:
                pass
            raise
        return {"path": dest, "frames": len(images)}

    def op_stylize(self, args: dict) -> dict:
        """Sketches drawn in a brush style (gui/brush.stylize_svg, as every export of the studio draws them): the Mac
        app sends ``svgs`` restyled and framed and draws what comes back – the strokes become filled outlines,
        dashed grain, halos … in plain SVG. ``style`` is one of brush.STYLES ("plain": unchanged)."""
        import xml.etree.ElementTree as ET

        from ..gui import brush

        svgs, style = args.get("svgs"), args.get("style")
        if not isinstance(svgs, list) or not all(isinstance(svg, str) for svg in svgs):
            raise _Fail("bad_request", "svgs is a list of SVG texts")
        if style not in brush.STYLES:
            raise _Fail("bad_request", f"style is one of {', '.join(brush.STYLES)}")
        out = []
        for i, svg in enumerate(svgs):
            try:
                out.append(brush.stylize_svg(svg, style))
            except ET.ParseError as exc:
                raise _Fail("bad_request", f"svgs[{i}] is no SVG: {exc}") from None
        return {"svgs": out}

    def _image(self, args: dict) -> str:
        image = _text(args, "image")
        if not os.path.isfile(image):
            raise _Fail("not_found", f"no image {image}")
        return image

    def op_mask(self, args: dict) -> dict:
        """The object mask of an image (headless/masks.py): the model's probability from the mask cache and the
        user's edited mask as far as they are there; with ``compute`` the model's mask is computed when it is not –
        the event "mask_ready" or "mask_failed" follows."""
        image, model = self._image(args), args.get("model", schema.DEFAULT_MASK_MODEL)
        if model not in schema.MASK_MODELS:
            raise _Fail("bad_request", f"model is one of {', '.join(schema.MASK_MODELS)}")
        out = {**masks.status(image, model), "computing": False}
        if args.get("compute") and out["probability"] is None:
            self.masks.request(image, model, str(args.get("device") or "auto"))
            out["computing"] = True
        return out

    def op_save_mask(self, args: dict) -> dict:
        """The user's mask of an image (a PNG of its size the app painted) kept where every method finds it."""
        image, mask = self._image(args), _text(args, "mask")
        if not os.path.isfile(mask):
            raise _Fail("not_found", f"no mask {mask}")
        try:
            return {"path": masks.save(image, mask)}
        except ValueError as exc:
            raise _Fail("bad_request", str(exc)) from None

    def op_remove_mask(self, args: dict) -> dict:
        """The image back to the model's mask (the user's goes)."""
        masks.remove(self._image(args))
        return {}

    def op_detail(self, args: dict) -> dict:
        """The detail map of an image as the detail brush starts from it (headless/detail_brush.py)."""
        return detail_brush.status(self._image(args))

    def op_phone_detail(self, args: dict) -> dict:
        """The detail map as the phone paints on it (at most ``side`` pixels, the image's shape): a temporary PNG."""
        side = args.get("side", 900)
        if not isinstance(side, int) or isinstance(side, bool) or not 16 <= side <= 4096:
            raise _Fail("bad_request", "side is a whole number from 16 to 4096")
        return {"map": detail_brush.phone_map(self._image(args), side)}

    def op_remove_detail(self, args: dict) -> dict:
        """The image without its detail map."""
        detail_brush.remove(self._image(args))
        return {}

    def op_save_detail(self, args: dict) -> dict:
        """The painted detail map kept at the image's size (all normal: removed – then ``path`` is None)."""
        image, painted = self._image(args), _text(args, "map")
        if not os.path.isfile(painted):
            raise _Fail("not_found", f"no map {painted}")
        return {"path": detail_brush.save(image, painted)}

    def op_portrait(self, args: dict) -> dict:
        """Portrait mode: the faces of an image are looked for in the background – "portrait_ready" (its ``map``,
        None: no face) or "portrait_failed" follows. Without the face detector: ``missing_model``."""
        from ..engine import model_store

        image = self._image(args)
        if not model_store.is_available(detail_brush.FACE_MODEL):
            raise _Fail("missing_model", detail_brush.FACE_MODEL)
        self.faces.request(image, detail_brush.FACE_MODEL, "cpu")
        return {"computing": True}

    def op_importance(self, args: dict) -> dict:
        """Simplify (studio.open_simplify): what each stroke of a run's sketch (the edited one, if there is one) adds,
        as importance.json keeps it – ``rank`` (higher is kept longer) and ``order`` (from the least to the most
        important), None when it was not measured for this sketch; with ``compute`` it is then measured in a process
        of its own – "importance_ready" or "importance_failed" follows (its ``image`` is the run's folder)."""
        from ..engine import importance, jobs

        run_dir = _text(args, "run_dir")
        try:
            with open(jobs.sketch_file(run_dir), encoding="utf-8") as f:
                svg = f.read()
        except OSError:
            raise _Fail("not_found", f"no sketch in {run_dir}") from None
        rank = importance.read(run_dir, svg)
        computing = rank is None and bool(args.get("compute"))
        if computing:
            self.importance.request(run_dir, "", "cpu")
        return {"rank": rank, "order": None if rank is None else importance.order(rank), "computing": computing}

    def op_continue_sketch(self, args: dict) -> dict:
        """"Continue with CLIPasso" (gui/continuing.py): with ``dry`` what the dialog shows of the run's sketch (the
        edited one, if there is one) – its strokes, those drawn by hand, whether its input is there and the start
        values; else the job's picture and settings, prepared in output_dir/_continued (``new`` strokes,
        ``iterations``, ``keep`` the strokes drawn by hand, ``settings``: the studio's CLIPasso settings)."""
        from ..engine import jobs
        from ..gui import continuing, strokes

        run_dir = _text(args, "run_dir")
        try:
            with open(jobs.sketch_file(run_dir), encoding="utf-8") as f:
                svg = f.read()
        except OSError:
            raise _Fail("not_found", f"no sketch in {run_dir}") from None
        if args.get("dry"):
            return {"strokes": strokes.shape_count(svg), "fixed": strokes.fixed_count(svg),
                    "can_continue": continuing.can_continue(run_dir),
                    "new": continuing.NEW_STROKES, "iterations": continuing.ITERATIONS}
        if not continuing.can_continue(run_dir):
            raise _Fail("no_input", f"no input.png in {run_dir}")
        new, iterations, settings = args.get("new"), args.get("iterations"), args.get("settings")
        if not isinstance(new, int) or isinstance(new, bool) or not 0 <= new <= 128:
            raise _Fail("bad_request", "new is a whole number from 0 to 128")
        if not isinstance(iterations, int) or isinstance(iterations, bool) or not 1 <= iterations <= 20000:
            raise _Fail("bad_request", "iterations is a whole number from 1 to 20000")
        if not isinstance(settings, dict):
            raise _Fail("bad_request", "settings is a JSON object")
        image, prepared = continuing.prepare(run_dir, svg, new, iterations, bool(args.get("keep", True)), settings,
                                             _text(args, "output_dir"))
        return {"image": image, "settings": prepared}

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
        """Pass the job's new events (and a finished mask) on; returns how many came."""
        sent = self.masks.poll() + self.faces.poll() + self.importance.poll()
        if self.job is None:
            self.runner.release_idle(WARM_IDLE)
            return sent
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
                return len(events) + sent
        for job, item in self.throttle.due():
            if job == self.job:
                self._send("iteration", item)
        return len(events) + sent

    # ---------------------------------------------------------------------- loop
    def serve(self, inp: BinaryIO) -> int:
        """Answer requests from ``inp`` until ``shutdown`` or its end; the running job is stopped then (and marked
        interrupted, so it can be continued). Returns the exit code."""
        lines: queue.Queue = queue.Queue()
        threading.Thread(target=read_lines, args=(inp, lines.put), name="requests", daemon=True).start()
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
            self.masks.shutdown()
            self.faces.shutdown()
            self.importance.shutdown()
        return code
