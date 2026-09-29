"""Entry point: ``python -m clipasso_studio`` / ``CLIPassoStudio.exe``.

    CLIPassoStudio.exe              start the GUI
    CLIPassoStudio.exe --cli ...    command line mode (arguments of the original CLIPasso scripts)
    CLIPassoStudio.exe --selftest   short end-to-end run used by the build pipeline
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


def selftest(out_dir: str | None = None) -> int:
    """Run a tiny sketch job on a bundled sample image; exit code 0 = success."""
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
                "mask_object": True, "multiprocess": True}
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
    print("selftest: " + json.dumps(report), flush=True)
    with open(os.path.join(out_dir, "selftest.json"), "w", encoding="utf-8") as f:
        json.dump(report, f)
    return 0 if ok else 1


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
