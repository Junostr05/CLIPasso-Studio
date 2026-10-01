"""End-to-end smoke tests (need the bundled models; skipped when they are not downloaded)."""

import json
import os
import time

import pytest

from clipasso_studio.engine import model_store

pytestmark = pytest.mark.skipif(
    not all(model_store.is_available(k) for k in ("clip:RN101", "clip:ViT-B/32", "u2net")),
    reason="models not downloaded (run tools/fetch_models.py)")

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "clipasso_studio", "resources", "samples", "camel.png")


def test_pipeline_runs_and_picks_best(tmp_path):
    from clipasso_studio.engine import pipeline

    events = []

    class Rec(pipeline.Reporter):
        def event(self, kind, **data):
            events.append(kind)

    settings = {"num_iter": 6, "num_sketches": 2, "num_paths": 4, "mask_object": True, "fix_scale": True,
                "save_interval": 2, "eval_interval": 2, "device": "cpu", "mask_model": "u2net"}
    summary = pipeline.run_job(settings, SAMPLE, str(tmp_path), Rec())
    assert os.path.isfile(summary["best_svg"])
    assert summary["best_svg"].endswith("_best.svg")
    assert len(summary["runs"]) == 2
    run_dir = summary["runs"][0]["run_dir"]
    for name in ("input.png", "mask.png", "attention_map.png", "best_iter.svg", "final_svg.svg", "config.json"):
        assert os.path.isfile(os.path.join(run_dir, name)), name
    assert os.path.isfile(os.path.join(run_dir, "svg_logs", "svg_iter0.svg"))
    cfg = json.loads(open(os.path.join(run_dir, "config.json")).read())
    assert cfg["loss_eval"] and cfg["status"] == "done"
    for kind in ("job_start", "input", "attention", "iteration", "preview", "seed_done", "job_done"):
        assert kind in events


@pytest.mark.slow
@pytest.mark.parametrize("overrides", [
    {"saliency_model": "dino", "num_stages": 2, "force_sparse": True, "color_vars_threshold": 0.1},
    {"clip_model_name": "ViT-B/32", "clip_conv_loss_type": "Cos",
     "clip_conv_layer_weights": "0,0,1,1,0,0,0,0,0,0,0,1"},
    {"clip_conv_loss_type": "Cos", "train_with_clip": True, "clip_weight": 1.0, "include_target_in_aug": True,
     "clip_text_guide": 0.5, "text_target": "a camel", "percep_loss": "L2", "perceptual_weight": 1.0,
     "augemntations": "affine_noise", "augment_both": False, "lr_scheduler": True},
    {"percep_loss": "LPIPS", "perceptual_weight": 1.0, "attention_init": False, "control_points_per_seg": 3,
     "num_segments": 2},
    {"saliency_clip_model": "RN101", "text_target": "a camel", "image_scale": 256, "xdog_intersec": False},
])
def test_all_options_run(tmp_path, overrides):
    from clipasso_studio.engine import pipeline

    settings = {"num_iter": 3, "num_sketches": 1, "num_paths": 4, "save_interval": 1, "eval_interval": 1,
                "device": "cpu", **overrides}
    summary = pipeline.run_job(settings, SAMPLE, str(tmp_path))
    assert os.path.isfile(summary["best_svg"])


@pytest.mark.slow
def test_initial_svg(tmp_path):
    from clipasso_studio.engine import pipeline

    first = pipeline.run_job({"num_iter": 2, "num_sketches": 1, "num_paths": 3, "device": "cpu"}, SAMPLE,
                             str(tmp_path / "a"))
    second = pipeline.run_job({"num_iter": 2, "num_sketches": 1, "num_paths": 5, "device": "cpu",
                               "path_svg": first["best_svg"]}, SAMPLE, str(tmp_path / "b"))
    assert open(second["best_svg"]).read().count("<path") == 5


@pytest.mark.slow
def test_runner_parallel_and_cancel(tmp_path):
    from clipasso_studio.engine.runner import JobRunner

    runner = JobRunner()
    runner.start({"num_iter": 4, "num_sketches": 2, "num_paths": 4, "multiprocess": True, "device": "cpu"},
                 SAMPLE, str(tmp_path / "par"))
    kinds = []
    deadline = time.time() + 300
    while runner.is_running() and time.time() < deadline:
        kinds += [k for k, _ in runner.poll()]
        time.sleep(0.1)
    assert "job_done" in kinds, kinds
    assert kinds.count("seed_done") == 2

    runner.start({"num_iter": 500, "num_sketches": 1, "num_paths": 4, "device": "cpu"}, SAMPLE,
                 str(tmp_path / "cancel"))
    kinds = []
    deadline = time.time() + 300
    while runner.is_running() and time.time() < deadline:
        batch = runner.poll()
        kinds += [k for k, _ in batch]
        if "iteration" in kinds:
            runner.cancel()
        time.sleep(0.1)
    assert "job_done" in kinds
