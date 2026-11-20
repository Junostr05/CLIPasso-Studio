"""``python -m clipasso_studio.headless [--export-schema PATH] [--export-models PATH]``

Without an option it serves the Mac app: requests on stdin, answers and events on stdout (server.py).
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import BinaryIO


def claim_stdout() -> BinaryIO:
    """Keep stdout for the protocol alone: the returned stream writes to the real stdout, while file descriptor 1 of
    this process – and so of every worker process started from it – goes to stderr, where a print() of a library
    cannot break a line of the protocol."""
    sys.stdout.flush()
    fd = os.dup(1)
    os.dup2(2, 1)
    if sys.platform == "win32":  # child processes inherit the Windows standard handle, not the C runtime's fd 1
        import ctypes
        import msvcrt

        ctypes.windll.kernel32.SetStdHandle(-11, msvcrt.get_osfhandle(2))  # STD_OUTPUT_HANDLE → stderr
    sys.stdout = sys.stderr
    return os.fdopen(fd, "wb", buffering=0)


def release_stdin_handle() -> None:
    """Windows: point the process's standard input handle at NUL; the requests are still read from fd 0. A thread
    blocked in a synchronous read of the stdin pipe makes every other query of that pipe wait – and CreateProcess
    queries the parent's standard handles when it starts a child that is given none (the workers of
    multiprocessing), so starting a job hung until the next request came."""
    if sys.platform != "win32":
        return
    import ctypes
    import msvcrt

    nul = os.open(os.devnull, os.O_RDONLY)  # (kept open for the life of the process)
    ctypes.windll.kernel32.SetStdHandle(-10, msvcrt.get_osfhandle(nul))  # STD_INPUT_HANDLE → NUL


def dump_when_hung() -> None:
    """With CLIPASSO_HANG_DUMP=seconds (the tests set it): every thread's stack to stderr after that long – so a
    hang in a CI run shows where it is."""
    seconds = os.environ.get("CLIPASSO_HANG_DUMP")
    if seconds:
        import faulthandler

        faulthandler.dump_traceback_later(float(seconds), exit=False, file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m clipasso_studio.headless",
                                     description="CLIPasso Studio's sketch engine for the Mac app")
    parser.add_argument("--export-schema", metavar="PATH", help="write the parameter schema as JSON and end")
    parser.add_argument("--export-models", metavar="PATH", help="write the model list as JSON and end")
    args = parser.parse_args(argv)
    if args.export_schema or args.export_models:
        from . import export

        if args.export_schema:
            export.write_json(args.export_schema, export.export_schema())
        if args.export_models:
            export.write_json(args.export_models, export.export_models())
        return 0
    # operations PyTorch has no Apple GPU (MPS) kernel for run on the CPU instead of failing (the workers inherit it)
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    from .protocol import Writer
    from .server import EngineServer

    out = claim_stdout()
    release_stdin_handle()
    dump_when_hung()
    return EngineServer(Writer(out)).serve(sys.stdin.buffer)


if __name__ == "__main__":
    sys.exit(main())
