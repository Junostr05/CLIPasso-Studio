"""Turbo mode: fixed augmentations of the target, weaker seeds stopped early, plateau stop."""

import json
import os

import pytest

from clipasso_studio import settings_schema as schema
from clipasso_studio.engine import checkpoint, jobs, model_store, runner

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "clipasso_studio", "resources", "samples")
CAMEL = os.path.join(SAMPLES, "camel.png")
BALLERINA = os.path.join(SAMPLES, "ballerina.jpg")
CLIPASSO_MODELS = all(model_store.is_available(k) for k in ("clip:RN101", "clip:ViT-B/32", "u2net"))
needs_models = pytest.mark.skipif(not CLIPASSO_MODELS, reason="models not downloaded (run tools/fetch_models.py)")


def test_turbo_setting():
    for method in ("clipasso", "controlsketch", "scenesketch"):
        p = schema.param(method, "turbo")
        assert p.default is False and not p.advanced and p.group == "optim"
        assert schema.turbo({"method": method, "turbo": True})
        assert not schema.turbo({"method": method})
    assert "turbo" not in schema.default_settings("swiftsketch")
    assert not schema.turbo({"method": "swiftsketch", "turbo": True})
    s = {**schema.default_settings("clipasso"), "turbo": True}
    assert schema.to_cli_args(s) == ["--turbo", "1"]
    assert schema.turbo_prunes(s) and not schema.turbo_prunes({**s, "num_sketches": 1})
    assert schema.turbo_prunes({**schema.default_settings("scenesketch"), "turbo": True})
    assert not schema.turbo_prunes({**schema.default_settings("controlsketch"), "turbo": True, "num_sketches": 3})
    assert schema.turbo_prune_iter(2001) == 501 and schema.turbo_prune_iter(12) == 3
    assert schema.turbo_prune_iter(1) == 1


def test_turbo_runs_the_seeds_one_after_another():
    s = {**schema.default_settings("clipasso"), "num_sketches": 4}
    big = (32, 64e9)
    assert runner.plan_workers(s, 4, hw=big) == 4
    assert runner.plan_workers({**s, "turbo": True}, 4, hw=big) == 1  # compared after a quarter
    assert runner.plan_workers({**s, "turbo": True, "multiprocess": True}, 4, hw=big) == 1


def test_plateau():
    from clipasso_studio.engine.pipeline import plateaued

    falling = [1.0 - 0.01 * i for i in range(60)]  # still 1 % better every evaluation
    assert not plateaued(falling, 10, 0)
    flat = falling[:20] + [falling[19] * 0.999] * 40  # 0.1 % in the last 300 iterations
    assert plateaued(flat, 10, 0)
    assert not plateaued(flat[:30], 10, 0)  # not 300 iterations long yet
    assert not plateaued(flat, 10, 400)  # only the evaluations from iteration 400 on count
    assert not plateaued([], 10, 0)


def test_augment_bank():
    import torch

    from clipasso_studio.engine import losses

    a = losses.AugmentBank(3, 224, 0.8)
    b = losses.AugmentBank(3, 224, 0.8)
    c = losses.AugmentBank(4, 224, 0.8)
    assert len(a.params) == losses.AUG_BANK_SIZE
    assert str(a.params) == str(b.params) and str(a.params) != str(c.params)
    state = torch.random.get_rng_state()
    losses.AugmentBank(5, 224, 0.8)
    assert torch.equal(state, torch.random.get_rng_state())  # the run's random numbers are untouched

    target = torch.rand(1, 3, 224, 224)
    out = a.apply(target, 7)
    assert out.shape == (1, 3, 224, 224)
    assert torch.equal(out, a.apply(target, 7))

    def encode(batch):  # stands in for CLIP: two "layers" with the batch first
        return [batch.mean(dim=(2, 3)), batch[:, :, ::32, ::32].flatten(1)]

    base = torch.rand(1, 3, 224, 224)
    a.build(base, target, encode, chunk=5)
    picked = [7, 0, 63]
    got = a.targets(picked)
    want = encode(torch.cat([base] + [a.apply(target, i) for i in picked]))
    for g, w in zip(got, want):
        assert torch.allclose(g, w, atol=1e-6)
    torch.manual_seed(0)
    first = a.pick(4)
    torch.manual_seed(0)
    assert a.pick(4) == first and len(set(first)) == 4 and a.pick(0) == []


def test_augment_bank_memory_limit(monkeypatch):
    import torch

    from clipasso_studio.engine import losses

    monkeypatch.setattr(losses, "AUG_BANK_BYTES", 1)
    bank = losses.AugmentBank(0, 64, 0.8, crop=32)
    bank.build(torch.rand(1, 3, 32, 32), torch.rand(1, 3, 64, 64), lambda x: [x.flatten(1)])
    assert len(bank.params) == 8 and bank.features[0].shape[0] == 9
    empty = losses.AugmentBank(0, 64, 0.8, count=0, crop=32)
    empty.build(torch.rand(1, 3, 32, 32), torch.rand(1, 3, 64, 64), lambda x: [x.flatten(1)])
    assert empty.features[0].shape[0] == 1 and empty.pick(4) == []


def test_turbo_conv_loss_matches_the_features_of_the_bank():
    """The turbo loss compares the sketch with the kept target features exactly like the normal loss
    compares it with freshly computed ones (stand-in network, no download needed)."""
    import torch

    from clipasso_studio.engine import losses, pipeline

    class Net:
        def __call__(self, x):
            x = x.float()
            return x.mean(dim=(2, 3)), [x[:, :, ::7, ::7] * (k + 1) for k in range(5)]

    s = {**schema.default_settings("clipasso"), "turbo": True}
    args = pipeline.build_args(s, "x.png", 0, "/tmp/x", torch.device("cpu"))
    loss = losses.CLIPConvLoss.__new__(losses.CLIPConvLoss)
    torch.nn.Module.__init__(loss)
    loss.args, loss.device, loss.num_augs, loss.augment_both = args, torch.device("cpu"), 4, True
    loss.clip_model_name, loss.clip_conv_loss_type = "RN101", "L2"
    loss.distance_metrics = {"L2": losses.l2_layers}
    loss.clip_fc_loss_weight, loss.counter = 0.1, 0
    loss.normalize_transform = lambda x: x * 2
    loss.turbo, loss.bank, loss._weighted = True, None, [2, 3]
    net = Net()
    loss.forward_inspection_clip_resnet = net
    sketch, target = torch.rand(1, 3, 224, 224), torch.rand(1, 3, 224, 224)
    torch.manual_seed(1)
    got = loss(sketch, target)
    torch.manual_seed(1)
    picked = loss.bank.pick(4)
    xs = torch.cat([sketch * 2] + [loss.bank.apply(sketch, i) for i in picked])
    ys = torch.cat([target * 2] + [loss.bank.apply(target, i) for i in picked])
    (xf, xc), (yf, yc) = net(xs), net(ys)
    assert set(got) == {"clip_conv_loss_layer2", "clip_conv_loss_layer3", "fc"}
    for layer in (2, 3):
        want = torch.square(xc[layer] - yc[layer]).mean()
        assert torch.allclose(got[f"clip_conv_loss_layer{layer}"], want, rtol=1e-5)
    fc = (1 - torch.cosine_similarity(xf, yf, dim=1)).mean() * 0.1
    assert torch.allclose(got["fc"], fc, rtol=1e-5)
    ev = loss(sketch, target, mode="eval")
    plain = torch.square(net(sketch * 2)[1][2] - net(target * 2)[1][2]).mean()
    assert torch.allclose(ev["clip_conv_loss_layer2"], plain)


SETTINGS = {"num_iter": 12, "num_sketches": 3, "num_paths": 4, "save_interval": 3, "eval_interval": 2,
            "device": "cpu", "turbo": True}


def _recorder():
    from clipasso_studio.engine import pipeline

    class Rec(pipeline.Reporter):
        def __init__(self):
            self.iterations, self.done = [], {}

        def event(self, kind, **data):
            if kind == "iteration":
                self.iterations.append((data["seed"], data["it"], data.get("eta_job")))
            if kind == "seed_done":
                self.done[data["seed"]] = data.get("pruned")

    return Rec()


@needs_models
def test_turbo_continues_only_the_best_seed(tmp_path):
    from clipasso_studio.engine import pipeline

    rec = _recorder()
    summary = pipeline.run_job(SETTINGS, CAMEL, str(tmp_path), rec)
    job_dir = os.path.dirname(summary["best_svg"])
    runs = {r["seed"]: r for r in summary["runs"]}
    assert sorted(runs) == [0, 1000, 2000]
    winners = [s for s, r in runs.items() if not r["pruned"]]
    assert len(winners) == 1
    (winner,) = winners
    for seed, r in runs.items():
        assert r["status"] == "done"
        assert r["iterations_done"] == (12 if seed == winner else 3)
        assert not os.path.isfile(checkpoint.path(r["run_dir"]))
        cfg = json.loads(open(os.path.join(r["run_dir"], "config.json")).read())
        assert cfg["pruned"] == (seed != winner)
    assert summary["best_run"] == runs[winner]["run_name"]
    assert runs[winner]["best_loss"] <= min(r["best_loss"] for r in runs.values())
    assert len(rec.iterations) == 3 * 3 + 9 and all(eta for _, _, eta in rec.iterations)
    assert rec.done == {s: s != winner for s in runs}
    assert jobs.progress_of(job_dir) == (3, 3) and jobs.read_state(job_dir)["status"] == "done"
    assert jobs.job_summary(job_dir)["best_run"] == runs[winner]["run_name"]


@pytest.mark.slow
@needs_models
@pytest.mark.parametrize("stop_after", [3, 3 + 2, 3 + 3 + 3 + 4])  # at / in the first quarter, after the choice
def test_turbo_continues_exactly(tmp_path, stop_after):
    from clipasso_studio.engine import pipeline

    whole = pipeline.run_job(SETTINGS, CAMEL, str(tmp_path / "whole"))

    class Stop(pipeline.Control):
        def should_stop(self):
            return len(rec.iterations) >= stop_after

    rec = _recorder()
    part = pipeline.run_job(SETTINGS, CAMEL, str(tmp_path / "part"), rec, Stop())
    job_dir = os.path.dirname(part["best_svg"])
    assert jobs.can_continue(job_dir)
    done = pipeline.run_job(SETTINGS, CAMEL, str(tmp_path), _recorder(), job_dir=job_dir, resume=True)
    a = {r["seed"]: r for r in whole["runs"]}
    b = {r["seed"]: r for r in done["runs"]}
    assert sorted(a) == sorted(b)
    for seed in a:
        assert a[seed]["pruned"] == b[seed]["pruned"] and a[seed]["iterations_done"] == b[seed]["iterations_done"]
        with open(os.path.join(a[seed]["run_dir"], "final_svg.svg")) as fa, \
                open(os.path.join(b[seed]["run_dir"], "final_svg.svg")) as fb:
            assert fa.read() == fb.read()
    assert whole["best_run"] == done["best_run"]


BUNDLED = all(model_store.is_available(k) for k in ("clip:ViT-B/32", "u2net"))


@pytest.mark.skipif(not BUNDLED, reason="bundled models missing (run tools/fetch_models.py)")
def test_scenesketch_turbo_continues_the_best_seed(tmp_path, monkeypatch):
    from clipasso_studio.engine import pipeline
    from clipasso_studio.engine.methods.scenesketch import lama
    from clipasso_studio.engine.selftest_models import tiny_lama

    monkeypatch.setattr(lama, "load_lama", tiny_lama)
    s = {**schema.default_settings("scenesketch"), "mask_model": "u2net", "layers": "8", "simplicity_levels": 1,
         "num_sketches": 2, "num_iter": 8, "object_num_iter": 8, "simplify_num_iter": 3, "eval_interval": 2,
         "min_eval_iter": 2, "save_interval": 2, "num_strokes": 6, "device": "cpu", "turbo": True}
    # fidelity parts: the best seed 8 iterations, the other one a quarter (2); simplification: both seeds
    assert schema.scene_cell_iterations(s, 800) == 2 * (8 + 2)
    assert schema.scene_cell_iterations(s, 801) == 2 * 2 * 3
    iterations = []

    class Rec(pipeline.Reporter):
        def event(self, kind, **data):
            if kind == "iteration":
                iterations.append(data)

    summary = pipeline.run_job(s, BALLERINA, str(tmp_path / "a"), Rec())
    assert [r["status"] for r in summary["runs"]] == ["done", "done"]
    assert len(iterations) == sum(schema.scene_cell_iterations(s, c) for c in schema.scene_cells(s))
    assert iterations[-1]["it"] == iterations[-1]["total"] - 1
    job_dir = os.path.dirname(summary["best_svg"])
    for part in ("background_l8", "object_l8"):
        saved = [d for d in ("seed0", "seed1000") if os.path.isfile(os.path.join(job_dir, "runs", part, d, "part.pt"))]
        assert len(saved) == 1, part  # only the seed that was continued is kept
    again = pipeline.run_job(s, BALLERINA, str(tmp_path / "b"))
    for a, b in zip(summary["runs"], again["runs"]):  # the same choice and strokes every time
        with open(a["best_svg"]) as fa, open(b["best_svg"]) as fb:
            assert fa.read() == fb.read()


@pytest.mark.skipif(not BUNDLED, reason="bundled models missing (run tools/fetch_models.py)")
def test_controlsketch_turbo(monkeypatch, tmp_path):
    import torch

    from clipasso_studio.engine import pipeline, svg_io
    from clipasso_studio.engine.methods import controlsketch
    from clipasso_studio.engine.methods.controlsketch import sds
    from clipasso_studio.engine.selftest_models import tiny_sd15_loader, tiny_taesd

    used = {}
    real_init = sds.ControlSDSLoss.__init__

    def spy(self, unet, controlnet, vae, *args, **kwargs):
        used["vae"], used["bf16"] = type(vae).__name__, kwargs.get("bf16")
        real_init(self, unet, controlnet, vae, *args, **kwargs)

    monkeypatch.setattr(sds, "load_sd15", tiny_sd15_loader)
    monkeypatch.setattr(sds, "load_taesd", tiny_taesd)
    monkeypatch.setattr(sds, "cpu_bf16_fast", lambda: True)
    monkeypatch.setattr(sds.ControlSDSLoss, "__init__", spy)
    controlsketch.release_models()
    settings = {**schema.default_settings("controlsketch"), "num_iter": 2, "save_interval": 1, "num_strokes": 6,
                "condition": "canny", "caption": "a camel", "device": "cpu", "mask_model": "u2net", "turbo": True}
    assert "taesd" in controlsketch.required_models(settings)
    assert "taesd" not in controlsketch.required_models({**settings, "turbo": False})
    summary = pipeline.run_job(settings, CAMEL, str(tmp_path))
    assert used == {"vae": "AutoencoderTiny", "bf16": True}
    run_dir = summary["runs"][0]["run_dir"]
    cfg = json.loads(open(os.path.join(run_dir, "config.json")).read())
    assert cfg["canvas"] == 384 and cfg["settings"]["render_size"] == 512 and cfg["status"] == "done"
    from PIL import Image

    assert Image.open(os.path.join(run_dir, "input_canvas.png")).size == (384, 384)
    w, h, shapes, _ = svg_io.load_svg(summary["best_svg"])
    assert (w, h) == (512, 512) and len(shapes) == 6
    assert abs(float(shapes[0].stroke_width) - 2.5) < 1e-3  # looks like a sketch drawn at 512 px
    controlsketch.release_models()

    # the SDS loss takes the latents of TAESD as they are (scaling factor 1) and is differentiable
    vae = tiny_taesd()
    x = torch.rand(1, 3, 64, 64, requires_grad=True)
    unet, controlnet, _, _, _, alphas = tiny_sd15_loader("canny", "cpu")
    loss = sds.ControlSDSLoss(unet, controlnet, vae, torch.zeros(1, 77, 32), torch.zeros(1, 77, 32),
                              torch.rand(1, 3, 64, 64), alphas, bf16=True)
    assert loss.scaling == 1.0
    loss(x).backward()
    assert x.grad is not None and torch.isfinite(x.grad).all()
