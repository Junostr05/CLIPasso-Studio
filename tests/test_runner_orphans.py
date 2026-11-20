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
        # the worker notices within a second of its next iteration, then saves the sketch so far (with its CLIP
        # score) – on a busy machine that takes a while (seen: 10.6 s for two iterations), so the window is wide;
        # what counts is that it stops by itself instead of computing its 5000 iterations
        gone, alive = psutil.wait_procs(children, timeout=60)
        assert alive == [], [(p.pid, p.cmdline()) for p in alive]
        state = jobs.read_state(job_dir)
        assert state["status"] == "cancelled" and jobs.can_continue(job_dir)
        done = [r for r in jobs.saved_results(job_dir).values()]
        assert done and all(r.iterations_done < 100 for r in done), [r.iterations_done for r in done]
    finally:
        engine.close()
