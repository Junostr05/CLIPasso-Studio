"""3.8.1: "RuntimeError: FIND was unable to find an engine to execute this computation" on a GTX 1060 – cuDNN found
no way to run a convolution and the job ended. The worker now goes on with a simpler way of computing (first without
cuDNN's search for the fastest algorithm, then without cuDNN), keeping the sketches finished before."""

import pytest
import torch

from clipasso_studio.engine import jobs, pipeline, runner

FIND = "FIND was unable to find an engine to execute this computation"


@pytest.fixture
def cudnn(monkeypatch):
    """cuDNN as a worker starts it (the test restores the process's flags afterwards)."""
    monkeypatch.setattr(torch.backends.cudnn, "benchmark", True)
    monkeypatch.setattr(torch.backends.cudnn, "enabled", True)
    return torch.backends.cudnn


class Rec:
    def __init__(self):
        self.events = []

    def event(self, kind, **data):
        self.events.append((kind, data))

    def of(self, kind):
        return [d for k, d in self.events if k == kind]


def _result(job_dir, seed):
    run_dir = job_dir / f"run_{seed}"
    run_dir.mkdir(parents=True, exist_ok=True)
    svg = run_dir / "best.svg"
    svg.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    return jobs.SeedResult(seed=seed, run_name=run_dir.name, run_dir=str(run_dir), best_loss=0.1, best_iter=5,
                           iterations_done=10, best_svg=str(svg), status="done")


def test_the_error_is_recognised():
    assert runner.is_cudnn_engine_error(RuntimeError(FIND))
    assert runner.is_cudnn_engine_error(RuntimeError("GET was unable to find an engine to execute this computation"))
    assert not runner.is_cudnn_engine_error(RuntimeError("shape mismatch"))
    assert not runner.is_cudnn_engine_error(ValueError(FIND))


def test_the_job_goes_on_without_the_search_then_without_cudnn(monkeypatch, cudnn):
    calls = []

    def run_job(settings, target, output_root, reporter, control, job_dir=None, seeds=None, finish=True,
                resume=False):
        calls.append((cudnn.benchmark, cudnn.enabled, seeds, resume))
        if cudnn.enabled:
            raise RuntimeError(FIND)
        return {"best_svg": "best.svg"}

    monkeypatch.setattr(pipeline, "run_job", run_job)
    rec = Rec()
    assert runner._run_one(rec, {}, "x.png", "/tmp", "", [0, 1000], True, None, None, False) is True
    assert calls == [(True, True, [0, 1000], False), (False, True, [0, 1000], False),
                     (False, False, [0, 1000], False)]
    assert [w["code"] for w in rec.of("warning")] == ["cudnn_no_benchmark", "cudnn_off"]
    assert FIND in rec.of("warning")[0]["message"] and rec.of("error") == []
    from clipasso_studio.gui.i18n import i18n

    for lang in ("de", "en"):  # (the studio shows ui.warn.<code>)
        i18n.set_language(lang)
        assert all(i18n.has(f"ui.warn.{w['code']}") for w in rec.of("warning")), lang
    i18n.set_language("en")
    # the worker keeps the simpler way for its next jobs (the warm worker)
    assert runner.cudnn_step_back() is None


def test_without_a_step_left_the_error_is_reported(monkeypatch, cudnn):
    cudnn.benchmark, cudnn.enabled = False, False

    def run_job(*a, **k):
        raise RuntimeError(FIND)

    monkeypatch.setattr(pipeline, "run_job", run_job)
    rec = Rec()
    assert runner._run_one(rec, {}, "x.png", "/tmp", "", [0], True, None, None, False) is False
    assert FIND in rec.of("error")[0]["message"] and rec.of("warning") == []


def test_other_errors_are_not_run_again(monkeypatch, cudnn):
    calls = []

    def run_job(*a, **k):
        calls.append(1)
        raise RuntimeError("shape mismatch")

    monkeypatch.setattr(pipeline, "run_job", run_job)
    rec = Rec()
    assert runner._run_one(rec, {}, "x.png", "/tmp", "", [0], True, None, None, False) is False
    assert calls == [1] and cudnn.benchmark and cudnn.enabled


@pytest.mark.parametrize("finish", [False, True])
def test_the_sketches_finished_before_are_kept(monkeypatch, cudnn, tmp_path, finish):
    """A parallel worker (finish=False) reports them with the others; a job with one worker continues (resume), so
    its summary covers them."""
    job_dir = tmp_path / "job"
    calls = []

    def run_job(settings, target, output_root, reporter, control, job_dir=None, seeds=None, finish=True,
                resume=False):
        calls.append((list(seeds), resume))
        if len(calls) == 1:  # the first sketch is finished, the second one meets the error
            jobs.save_result(_result(tmp_path / "job", 0))
            reporter.event("seed_done", seed=0, status="done")
            raise RuntimeError(FIND)
        results = [_result(tmp_path / "job", s) for s in seeds]
        return results if not finish else {"best_svg": "best.svg"}

    monkeypatch.setattr(pipeline, "run_job", run_job)
    rec = Rec()
    assert runner._run_one(rec, {}, "x.png", str(tmp_path), str(job_dir), [0, 1000], finish, None, None, False)
    assert calls == [([0, 1000], False), ([1000], finish)]
    if not finish:
        assert [r["seed"] for r in rec.of("worker_results")[0]["results"]] == [0, 1000]
