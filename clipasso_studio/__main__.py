"""Entry point: ``python -m clipasso_studio`` / ``CLIPassoStudio.exe``.

    CLIPassoStudio.exe              start the GUI
    CLIPassoStudio.exe --cli ...    command line mode (arguments of the original scripts, --method X)
    CLIPassoStudio.exe --selftest   short end-to-end runs of all methods used by the build pipeline
"""

from __future__ import annotations

import multiprocessing
import os
import sys


def _attach_console() -> None:
    """A windowed exe has no console; attach to the parent's one for --cli / --selftest."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    try:
        import ctypes

        if ctypes.windll.kernel32.AttachConsole(-1):
            sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")
            sys.stderr = sys.stdout
    except Exception:
        pass


def _ensure_streams(log_name: str) -> None:
    """In a windowed exe stdout/stderr are None; send output to a log file instead."""
    if sys.stdout is None or sys.stderr is None:
        from . import paths

        log = open(paths.user_data_dir() / log_name, "a", encoding="utf-8", errors="replace")
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log


def _selftest_diffusion_methods(out_dir: str) -> dict:
    """SwiftSketch, ControlSketch and SceneSketch end to end with tiny random networks (no downloads);
    checks that every diffusers / transformers class the methods load is importable."""
    from . import paths
    from . import settings_schema as schema
    from .engine import pipeline
    from .engine import selftest_models as tiny
    from .engine.methods import controlsketch, swiftsketch
    from .engine.methods.controlsketch import sds

    sample = str(paths.resource("samples", "camel.png"))
    results = {}
    load_net = swiftsketch.load_net
    swiftsketch.load_net = lambda key, device: (
        tiny.swiftsketch_net(0 if key.endswith("diffusion") else 1,
                             cond_mask_prob=0.1 if key.endswith("diffusion") else 0.0).to(device),
        dict(tiny.SWIFT_ARGS, diffusion_steps=10))
    try:
        s = {**schema.default_settings("swiftsketch"), "num_sketches": 2, "save_diffusion_sketch": True,
             "mask_model": "u2net"}
        results["swiftsketch"] = pipeline.run_job(s, sample, out_dir, pipeline.PrintReporter())
    finally:
        swiftsketch.load_net = load_net
    load_sd15 = sds.load_sd15
    sds.load_sd15 = tiny.tiny_sd15_loader
    try:
        s = {**schema.default_settings("controlsketch"), "num_iter": 3, "save_interval": 1, "num_strokes": 8,
             "render_size": 256, "output_svg_size": 256, "condition": "canny", "caption": "a camel",
             "mask_model": "u2net"}
        results["controlsketch"] = pipeline.run_job(s, sample, out_dir, pipeline.PrintReporter())
    finally:
        sds.load_sd15 = load_sd15
        controlsketch.release_models()
    from .engine.methods.scenesketch import lama

    load_lama = lama.load_lama
    lama.load_lama = tiny.tiny_lama
    try:
        s = {**schema.default_settings("scenesketch"), "layers": "8", "simplicity_levels": 1, "num_sketches": 1,
             "num_iter": 4, "object_num_iter": 4, "simplify_num_iter": 3, "eval_interval": 2, "min_eval_iter": 2,
             "save_interval": 2, "num_strokes": 8, "mask_model": "u2net"}
        results["scenesketch"] = pipeline.run_job(s, str(paths.resource("samples", "ballerina.jpg")), out_dir,
                                                  pipeline.PrintReporter())
    finally:
        lama.load_lama = load_lama
    # classes that are only loaded with downloaded models
    from diffusers import DDIMScheduler, StableDiffusionXLPipeline  # noqa: F401
    from transformers import (BlipForConditionalGeneration, BlipProcessor, CLIPTextModel,  # noqa: F401
                              CLIPTextModelWithProjection, CLIPTokenizer, DPTForDepthEstimation,
                              UperNetForSemanticSegmentation)

    from .engine.methods.controlsketch import caption, conditions, sdxl_attention  # noqa: F401

    report = {}
    for method, summary in results.items():
        svg = summary["best_svg"]
        ok = os.path.isfile(svg) and "<path" in open(svg, encoding="utf-8").read()
        report[method] = {"ok": bool(ok and summary.get("clip_score") is not None),
                          "clip_score": summary.get("clip_score"), "best_svg": svg}
    return report


def _selftest_mask(out_dir: str) -> dict:
    """BiRefNet with random weights at a reduced input size: the operations of the port and the
    safetensors round trip of its weights work in the packaged app (the methods above use U2Net)."""
    from PIL import Image
    from safetensors.torch import load_file, save_file

    from . import paths
    from .engine import birefnet, masking
    from .engine import selftest_models as tiny

    size = birefnet.SIZE
    try:
        net = tiny.birefnet()
        path = os.path.join(out_dir, "birefnet-selftest.safetensors")
        save_file({k: v.contiguous() for k, v in net.state_dict().items()}, path)
        net.load_state_dict(load_file(path), strict=True)
        birefnet.SIZE = 256
        image = Image.open(paths.resource("samples", "camel.png")).convert("RGB")
        prob = masking.birefnet_probability("cpu", image, "birefnet-lite", net=net)
        ok = prob.shape == (image.height, image.width) and 0.0 <= float(prob.min()) <= float(prob.max()) <= 1.0
    except Exception as exc:  # reported, not raised: the other results still count
        print(f"selftest: mask ERROR {exc!r}", flush=True)
        ok = False
    finally:
        birefnet.SIZE = size
        masking._cache.clear()
    print(f"selftest: mask ok={ok}", flush=True)
    return {"ok": ok}


def _selftest_resume(out_dir: str) -> dict:
    """An interrupted CLIPasso job continues from its checkpoint (torch.save / load of the stroke and
    optimiser state in the packaged app)."""
    from . import paths
    from .engine import checkpoint, jobs, pipeline

    class Stop(pipeline.Control):
        n = 0

        def should_stop(self):
            Stop.n += 1
            return Stop.n > 3

    settings = {"num_iter": 6, "num_sketches": 1, "num_paths": 4, "save_interval": 1, "eval_interval": 1}
    sample = str(paths.resource("samples", "camel.png"))
    try:
        first = pipeline.run_job(settings, sample, os.path.join(out_dir, "resume"), control=Stop())
        job_dir = os.path.dirname(first["best_svg"])
        run_dir = first["runs"][0]["run_dir"]
        had_checkpoint = os.path.isfile(checkpoint.path(run_dir))
        done = pipeline.run_job(settings, sample, out_dir, job_dir=job_dir, resume=True)
        ok = (had_checkpoint and done["runs"][0]["status"] == "done" and done["runs"][0]["iterations_done"] == 6
              and jobs.read_state(job_dir)["status"] == "done" and not os.path.isfile(checkpoint.path(run_dir)))
    except Exception as exc:  # reported, not raised: the other results still count
        print(f"selftest: resume ERROR {exc!r}", flush=True)
        ok = False
    print(f"selftest: resume ok={ok}", flush=True)
    return {"ok": ok}


def selftest(out_dir: str | None = None) -> int:
    """Run tiny sketch jobs of all methods on a bundled sample image; exit code 0 = success."""
    import json
    import tempfile
    import time

    from . import paths
    from .engine import model_store

    out_dir = out_dir or tempfile.mkdtemp(prefix="clipasso_selftest_")
    print(f"selftest: models in {paths.bundled_models_dir()}", flush=True)
    for key, spec in model_store.SPECS.items():
        if spec.bundled and not model_store.is_available(key):
            print(f"selftest: missing bundled model {key}", flush=True)
            return 2
    start = time.time()
    settings = {"num_iter": 5, "num_sketches": 2, "num_paths": 8, "save_interval": 1, "eval_interval": 1,
                "mask_object": True, "mask_model": "u2net", "multiprocess": True}
    # same code path as the GUI: worker processes started by the JobRunner
    from .engine.runner import JobRunner

    runner = JobRunner()
    runner.start(settings, str(paths.resource("samples", "camel.png")), out_dir)
    summary = None
    deadline = time.time() + 1800
    while runner.is_running() and time.time() < deadline:
        for kind, data in runner.poll():
            if kind == "iteration":
                print(f"selftest: seed {data['seed']} iter {data['it'] + 1}/{data['total']} loss {data['loss']:.4f}",
                      flush=True)
            elif kind == "error":
                print("selftest: ERROR " + data.get("message", "") + "\n" + data.get("traceback", ""), flush=True)
            elif kind == "job_done":
                summary = data
            elif kind not in ("preview", "input", "attention", "seed_done", "stage"):
                print(f"selftest: {kind} {data}", flush=True)
        time.sleep(0.2)
    if runner.is_running():
        runner.kill()
    if summary is None:
        print("selftest: job did not finish", flush=True)
        return 1
    ok = os.path.isfile(summary["best_svg"]) and "<path" in open(summary["best_svg"], encoding="utf-8").read()
    # the GUI stack must import as well
    from PySide6 import QtSvg, QtWidgets  # noqa: F401

    from .gui import export  # noqa: F401

    report = {"ok": ok, "seconds": round(time.time() - start, 1), "best_svg": summary["best_svg"]}
    print("selftest: clipasso " + json.dumps(report), flush=True)
    methods = _selftest_diffusion_methods(out_dir)
    methods["resume"] = _selftest_resume(out_dir)
    methods["mask"] = _selftest_mask(out_dir)
    report = {"ok": ok and all(r["ok"] for r in methods.values()), "seconds": round(time.time() - start, 1),
              "clipasso": {"ok": ok, "best_svg": summary["best_svg"]}, **methods}
    print("selftest: " + json.dumps(report), flush=True)
    with open(os.path.join(out_dir, "selftest.json"), "w", encoding="utf-8") as f:
        json.dump(report, f)
    return 0 if report["ok"] else 1


class _Tee:
    """Write to several streams (console and the self-test log file)."""

    def __init__(self, *streams):
        self.streams = [st for st in streams if st is not None]

    def write(self, text):
        for st in self.streams:
            try:
                st.write(text)
                st.flush()
            except Exception:
                pass
        return len(text)

    def flush(self):
        for st in self.streams:
            try:
                st.flush()
            except Exception:
                pass


def _close_splash() -> None:
    try:
        import pyi_splash  # type: ignore  # only present in the PyInstaller onefile build

        pyi_splash.close()
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--cli" in argv or "--selftest" in argv:
        _close_splash()
    if "--cli" in argv:
        _attach_console()
        _ensure_streams("cli.log")
        argv.remove("--cli")
        from .cli import main as cli_main

        return cli_main(argv)
    if "--selftest" in argv:
        _attach_console()
        _ensure_streams("selftest.log")
        idx = argv.index("--selftest")
        out = argv[idx + 1] if len(argv) > idx + 1 and not argv[idx + 1].startswith("-") else None
        if out is None:
            import tempfile

            out = tempfile.mkdtemp(prefix="clipasso_selftest_")
        os.makedirs(out, exist_ok=True)
        # the console of a windowed exe is not captured by CI runners: keep a copy in <out>/selftest.log
        log = open(os.path.join(out, "selftest.log"), "a", encoding="utf-8", errors="replace")
        sys.stdout = _Tee(sys.stdout, log)
        sys.stderr = _Tee(sys.stderr, log)
        try:
            return selftest(out)
        except Exception:
            import traceback

            traceback.print_exc()
            return 1
    _ensure_streams("app.log")
    from .gui.app import run_gui

    return run_gui([sys.argv[0]] + argv)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
