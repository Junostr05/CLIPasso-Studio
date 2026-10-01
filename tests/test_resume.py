"""Continuing interrupted jobs: checkpoints inside a seed, finished seeds / parts kept.

A continued run must take the same steps as an uninterrupted one (same strokes at the end), and
finished work must not be computed again.
"""

import json
import os

import pytest

from clipasso_studio import settings_schema as schema
from clipasso_studio.engine import checkpoint, jobs, model_store

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "clipasso_studio", "resources", "samples")
CAMEL = os.path.join(SAMPLES, "camel.png")
BALLERINA = os.path.join(SAMPLES, "ballerina.jpg")
CLIPASSO_MODELS = all(model_store.is_available(k) for k in ("clip:RN101", "clip:ViT-B/32", "u2net"))
BUNDLED = all(model_store.is_available(k) for k in ("clip:ViT-B/32", "u2net"))


def _stop_after(n_iterations):
    """A control that stops the job after ``n_iterations`` iterations (seen through the reporter)."""
    from clipasso_studio.engine import pipeline

    class Rec(pipeline.Reporter):
        iterations = 0
        restored = []

        def event(self, kind, **data):
            if kind == "iteration":
                Rec.iterations += 1
            if kind == "seed_done" and data.get("restored"):
                Rec.restored.append(data["seed"])

    class Stop(pipeline.Control):
        def should_stop(self):
            return Rec.iterations >= n_iterations

    return Rec(), Stop()


def _svg(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_job_state_helpers(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    settings = {**schema.default_settings("clipasso"), "num_sketches": 3}
    jobs.write_state(str(job), str(tmp_path / "camel.png"), settings)
    assert jobs.read_state(str(job))["seeds"] == [0, 1000, 2000]
    assert jobs.remaining_seeds(str(job)) == [0, 1000, 2000] and jobs.can_continue(str(job))
    run = job / "camel_16strokes_seed0"
    run.mkdir()
    (run / "best_iter.svg").write_text("<svg/>")
    jobs.save_result(jobs.SeedResult(seed=0, run_name=run.name, run_dir=str(run), best_loss=0.2, best_iter=3,
                                     iterations_done=4, best_svg=str(run / "best_iter.svg"), status="done"))
    assert jobs.progress_of(str(job)) == (1, 3) and jobs.remaining_seeds(str(job)) == [1000, 2000]
    jobs.set_status(str(job), "done")
    assert not jobs.can_continue(str(job))


@pytest.mark.skipif(not CLIPASSO_MODELS, reason="models not downloaded (run tools/fetch_models.py)")
def test_clipasso_continues_exactly_where_it_stopped(tmp_path):
    from clipasso_studio.engine import pipeline

    settings = {"num_iter": 12, "num_sketches": 2, "num_paths": 4, "save_interval": 3, "eval_interval": 2,
                "device": "cpu"}
    whole = pipeline.run_job(settings, CAMEL, str(tmp_path / "whole"))

    rec, stop = _stop_after(12 + 5)  # the first seed finishes, the second one stops after 5 iterations
    part = pipeline.run_job(settings, CAMEL, str(tmp_path / "part"), rec, stop)
    job_dir = os.path.dirname(part["best_svg"])
    assert [r["status"] for r in part["runs"]] == ["done", "cancelled"]
    second = part["runs"][1]["run_dir"]
    assert os.path.isfile(checkpoint.path(second))  # written on cancel
    assert not os.path.isfile(checkpoint.path(part["runs"][0]["run_dir"]))  # removed when finished
    assert jobs.read_state(job_dir)["status"] == "cancelled" and jobs.remaining_seeds(job_dir) == [1000]

    rec2, _ = _stop_after(10 ** 9)
    done = pipeline.run_job(settings, CAMEL, str(tmp_path), rec2, job_dir=job_dir, resume=True)
    assert rec2.iterations == 12 - 5  # only the rest of the second seed ran
    assert rec2.restored == [0]
    assert [r["status"] for r in done["runs"]] == ["done", "done"]
    assert jobs.read_state(job_dir)["status"] == "done" and not os.path.isfile(checkpoint.path(second))
    for a, b in zip(whole["runs"], done["runs"]):  # the same strokes as without the interruption
        assert _svg(os.path.join(a["run_dir"], "final_svg.svg")) == _svg(os.path.join(b["run_dir"], "final_svg.svg"))
        assert a["best_iter"] == b["best_iter"] and abs(a["best_loss"] - b["best_loss"]) < 1e-6


@pytest.mark.slow
@pytest.mark.skipif(not CLIPASSO_MODELS, reason="models not downloaded (run tools/fetch_models.py)")
def test_clipasso_multi_stage_continues(tmp_path):
    from clipasso_studio.engine import pipeline

    settings = {"num_iter": 8, "num_sketches": 1, "num_paths": 3, "num_stages": 2, "save_interval": 2,
                "eval_interval": 2, "device": "cpu"}
    whole = pipeline.run_job(settings, CAMEL, str(tmp_path / "whole"))
    rec, stop = _stop_after(6)  # stopped in the second stage
    part = pipeline.run_job(settings, CAMEL, str(tmp_path / "part"), rec, stop)
    job_dir = os.path.dirname(part["best_svg"])
    done = pipeline.run_job(settings, CAMEL, str(tmp_path), job_dir=job_dir, resume=True)
    a, b = whole["runs"][0]["run_dir"], done["runs"][0]["run_dir"]
    assert _svg(os.path.join(a, "final_svg.svg")) == _svg(os.path.join(b, "final_svg.svg"))
    assert _svg(os.path.join(b, "final_svg.svg")).count("<path") == 6


@pytest.mark.skipif(not BUNDLED, reason="bundled models missing (run tools/fetch_models.py)")
def test_controlsketch_continues_exactly_where_it_stopped(tmp_path, monkeypatch):
    pytest.importorskip("diffusers")
    from clipasso_studio.engine import pipeline
    from clipasso_studio.engine.methods import controlsketch
    from clipasso_studio.engine.methods.controlsketch import sds
    from clipasso_studio.engine.selftest_models import tiny_sd15_loader

    monkeypatch.setattr(sds, "load_sd15", tiny_sd15_loader)
    controlsketch.release_models()
    settings = {**schema.default_settings("controlsketch"), "mask_model": "u2net", "num_iter": 6, "save_interval": 2,
                "num_sketches": 1, "num_strokes": 6, "render_size": 256, "output_svg_size": 512, "condition": "canny",
                "caption": "a camel", "fix_scale": True, "device": "cpu"}
    whole = pipeline.run_job(settings, CAMEL, str(tmp_path / "whole"))
    controlsketch.release_models()
    rec, stop = _stop_after(3)
    part = pipeline.run_job(settings, CAMEL, str(tmp_path / "part"), rec, stop)
    job_dir = os.path.dirname(part["best_svg"])
    assert os.path.isfile(checkpoint.path(part["runs"][0]["run_dir"]))
    controlsketch.release_models()
    rec2, _ = _stop_after(10 ** 9)
    done = pipeline.run_job(settings, CAMEL, str(tmp_path), rec2, job_dir=job_dir, resume=True)
    assert rec2.iterations == 7 - 3
    a, b = whole["runs"][0]["run_dir"], done["runs"][0]["run_dir"]
    assert _svg(os.path.join(a, "final_svg.svg")) == _svg(os.path.join(b, "final_svg.svg"))
    cfg = json.load(open(os.path.join(b, "config.json")))
    assert cfg["status"] == "done" and cfg["iterations_done"] == 7
    controlsketch.release_models()


@pytest.mark.skipif(not BUNDLED, reason="bundled models missing (run tools/fetch_models.py)")
def test_scenesketch_keeps_finished_parts(tmp_path, monkeypatch):
    from clipasso_studio.engine import pipeline
    from clipasso_studio.engine.methods.scenesketch import lama
    from clipasso_studio.engine.selftest_models import tiny_lama

    monkeypatch.setattr(lama, "load_lama", tiny_lama)
    s = {**schema.default_settings("scenesketch"), "mask_model": "u2net", "layers": "8", "simplicity_levels": 2,
         "num_sketches": 1, "num_iter": 4, "object_num_iter": 4, "simplify_num_iter": 3, "eval_interval": 2,
         "min_eval_iter": 2, "save_interval": 2, "num_strokes": 6, "device": "cpu"}
    total = sum(schema.scene_cell_iterations(s, c) for c in schema.scene_cells(s))
    whole = pipeline.run_job(s, BALLERINA, str(tmp_path / "whole"))

    first = schema.scene_cell_iterations(s, 800)
    rec, stop = _stop_after(first + 2)  # the fidelity cell is finished, level 1 is interrupted
    part = pipeline.run_job(s, BALLERINA, str(tmp_path / "part"), rec, stop)
    job_dir = os.path.dirname(part["best_svg"])
    assert jobs.done_results(job_dir).keys() == {800}

    iterations, restored = [], []

    class Rec(pipeline.Reporter):
        def event(self, kind, **data):
            if kind == "iteration":
                iterations.append(data)
            if kind == "log" and "restored" in data.get("message", ""):
                restored.append(data["message"])

    done = pipeline.run_job(s, BALLERINA, str(tmp_path), Rec(), job_dir=job_dir, resume=True)
    assert [r["seed"] for r in done["runs"]] == [800, 801, 802]
    assert all(r["status"] == "done" for r in done["runs"])
    assert len(restored) == 2  # background and object of the fidelity cell
    assert iterations[-1]["it"] == iterations[-1]["total"] - 1  # progress of the last cell complete
    assert len(iterations) < total  # the restored parts were not trained again
    # the restored fidelity cell is the one computed before the interruption
    assert _svg(os.path.join(part["runs"][0]["run_dir"], "best_iter.svg")) == \
        _svg(os.path.join(done["runs"][0]["run_dir"], "best_iter.svg"))
    assert len(whole["runs"]) == len(done["runs"])


@pytest.mark.slow
@pytest.mark.skipif(not CLIPASSO_MODELS, reason="models not downloaded (run tools/fetch_models.py)")
def test_runner_kill_and_continue(tmp_path):
    """The app is closed during a job (worker processes killed) and the job is continued later."""
    import time

    from clipasso_studio.engine.runner import JobRunner

    settings = {"num_iter": 40, "num_sketches": 2, "num_paths": 4, "save_interval": 5, "eval_interval": 5,
                "device": "cpu"}
    runner = JobRunner()
    job = runner.start(settings, CAMEL, str(tmp_path))
    seen, end = [], time.time() + 300
    while time.time() < end and not any(k == "seed_done" for k, _ in seen):
        seen += runner.poll()
        time.sleep(0.2)
    assert any(k == "seed_done" for k, _ in seen)
    runner.kill()
    assert jobs.read_state(job.job_dir)["status"] == "interrupted"
    assert jobs.progress_of(job.job_dir) == (1, 2)

    job2 = runner.start(settings, CAMEL, str(tmp_path), job_dir=job.job_dir)
    events, end = [], time.time() + 300
    while runner.is_running() and time.time() < end:
        events += runner.poll()
        time.sleep(0.2)
    events += runner.poll()
    assert any(k == "job_done" for k, _ in events)
    restored = [d["seed"] for k, d in events if k == "seed_done" and d.get("restored")]
    assert restored == [0]
    summary = json.load(open(os.path.join(job2.job_dir, "job.json")))
    assert [r["seed"] for r in summary["runs"]] == [0, 1000] and all(r["status"] == "done" for r in summary["runs"])
    assert jobs.read_state(job2.job_dir)["status"] == "done"


def test_score_interval_follows_the_save_step():
    from clipasso_studio.engine import checkpoint

    assert checkpoint.score_interval(100) == 100  # the paper setting: unchanged
    assert checkpoint.score_interval(1) == 100  # every iteration saved, scored about every 100
    assert checkpoint.score_interval(30) == 120  # on a saved step
    assert checkpoint.score_interval(250) == 250
