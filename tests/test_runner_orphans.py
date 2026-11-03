"""Worker processes end by themselves when the process that started them is gone (killed, crashed) – they do not keep
computing (and holding memory) as orphans."""

from __future__ import annotations

import psutil

from clipasso_studio.engine import jobs

from tests.headless_engine import Engine, image_in, tiny_settings


def test_orphan_workers_stop(tmp_path):
    engine = Engine(tmp_path)
    try:
        answer = engine.request("start", target=str(image_in(tmp_path)), settings=tiny_settings(num_iter=5000),
                                output_root=str(tmp_path / "out"))
        job_dir = answer["result"]["job_dir"]
        engine.wait_event("iteration")
        children = psutil.Process(engine.proc.pid).children(recursive=True)
        assert children
        engine.proc.kill()  # SIGKILL / TerminateProcess: no chance to clean up
        engine.proc.wait(timeout=10)
        gone, alive = psutil.wait_procs(children, timeout=10)
        assert alive == [], [(p.pid, p.cmdline()) for p in alive]
        assert jobs.can_continue(job_dir)
    finally:
        engine.close()
