"""The warm worker: one-worker jobs run one after the other in a process that keeps its models."""

import os
import time

import pytest

from clipasso_studio.engine.runner import JobRunner
from tests.test_pipeline_smoke import SAMPLE

TINY = {"num_iter": 3, "num_sketches": 1, "num_paths": 4, "device": "cpu", "mask_model": "u2net",
        "save_interval": 1, "eval_interval": 1}


def _run(runner, settings, out, target=SAMPLE, cancel_after_iteration=False, timeout=300):
    runner.start(settings, target, str(out))
    kinds = []
    deadline = time.time() + timeout
    while runner.is_running() and time.time() < deadline:
        batch = [k for k, _ in runner.poll()]
        kinds += batch
        if cancel_after_iteration and "iteration" in kinds:
            runner.cancel()
        time.sleep(0.05)
    assert not runner.is_running(), "timed out"
    return kinds, runner.job.job_dir


def _best_svg(job_dir):
    from clipasso_studio.engine import jobs

    summary = jobs.job_summary(job_dir)
    with open(jobs.best_sketch(summary), encoding="utf-8") as f:
        return f.read()


@pytest.mark.timeout(1200)
def test_jobs_share_one_worker(tmp_path):
    runner = JobRunner(keep_warm=True)
    try:
        kinds, first = _run(runner, TINY, tmp_path / "a")
        assert "job_done" in kinds
        pid = runner.warm_pid()
        assert pid is not None
        # a cancelled job, then one that is not cancelled
        kinds, _ = _run(runner, {**TINY, "num_iter": 500}, tmp_path / "b", cancel_after_iteration=True)
        assert runner.warm_pid() == pid
        kinds, again = _run(runner, TINY, tmp_path / "c")
        assert "job_done" in kinds and "error" not in kinds and runner.warm_pid() == pid
        # the same sketch as in a fresh process (and as the first job)
        fresh = JobRunner(keep_warm=False)
        _, alone = _run(fresh, TINY, tmp_path / "d")
        assert _best_svg(first) == _best_svg(again) == _best_svg(alone)
        # a job that fails: the next one gets a new process
        kinds, _ = _run(runner, TINY, tmp_path / "e", target=str(tmp_path / "missing.png"))
        assert "error" in kinds
        kinds, _ = _run(runner, TINY, tmp_path / "f")
        assert "job_done" in kinds and runner.warm_pid() not in (None, pid)
        # idle for long enough: ended
        assert not runner.release_idle(3600) and runner.warm_pid() is not None
        assert runner.release_idle(0) and runner.warm_pid() is None
    finally:
        runner.kill()
    assert os.path.isdir(first)
