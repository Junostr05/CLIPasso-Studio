"""SwiftSketch: sampler, network, checkpoint conversion, Google Drive download and a full run.

The full run uses randomly initialised networks of the real architecture, so it needs only the
bundled CLIP / U2Net models, not the SwiftSketch download.
"""

import io
import json
import os
import zipfile

import pytest
import torch

from clipasso_studio.engine import model_store
from clipasso_studio.engine.methods.swiftsketch.diffusion import Sampler, cosine_betas
from clipasso_studio.engine.methods.swiftsketch.model import SwiftSketchNet

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "clipasso_studio", "resources", "samples", "camel.png")

ARGS = {"latent_dim": 64, "layers": 2, "heads": 4, "image_features_type": "CLIPMiddle_layer4",
        "normalize_model_output": 1, "scaling_factor": 2.0, "cond_mask_prob": 0.1, "num_paths": 32,
        "diffusion_steps": 50, "cos_power": 0.4}


def small_net(seed=0, **overrides):
    torch.manual_seed(seed)
    return SwiftSketchNet.from_args({**ARGS, **overrides}).eval()


def test_cosine_schedule():
    betas = cosine_betas(50, 0.4)
    assert betas.shape == (50,)
    assert (betas > 0).all() and (betas <= 0.999).all()
    assert (betas[1:] >= betas[:-1]).all()  # noise increases over time


def test_sampler_ends_on_the_prediction_and_is_reproducible():
    sampler = Sampler(50, 0.4)
    target = torch.full((1, 32, 4, 2), 0.3)
    steps = list(sampler.sample(lambda x, t: target, (1, 32, 4, 2), "cpu", generator=torch.Generator().manual_seed(1)))
    assert [i for i, _, _ in steps] == list(range(49, -1, -1))
    assert torch.allclose(steps[-1][1], target)  # the last step returns x0 itself

    def run(seed):
        net = small_net()
        feats = torch.randn(1, 1024, 14, 14, generator=torch.Generator().manual_seed(0))
        out = None
        for _, x, _ in Sampler(5, 0.4).sample(lambda x, t: net.guided(x, t, feats, 2.5), (1, 32, 4, 2), "cpu",
                                               generator=torch.Generator().manual_seed(seed)):
            out = x
        return out

    assert torch.equal(run(3), run(3))
    assert not torch.equal(run(3), run(4))


def test_network_shapes_and_guidance():
    net = small_net()
    x = torch.randn(2, 32, 4, 2)
    t = torch.tensor([10, 0])
    feats = torch.randn(2, 1024, 14, 14)
    with torch.no_grad():
        out = net(x, t, feats)
        assert out.shape == (2, 32, 4, 2)
        assert out.abs().max() <= 2.0  # tanh * scaling_factor
        g = net.guided(x, t, feats, 2.5)
        cond, uncond = net(x, t, feats), net(x, t, feats, uncond=True)
        assert torch.allclose(g, uncond + 2.5 * (cond - uncond), atol=1e-5)
        memories = net.guided_memories(feats, 2.5)  # computed once per sketch, reused every step
        assert len(memories) == 2 and torch.allclose(net.guided(x, t, feats, 2.5, memories), g, atol=1e-6)
        refine = small_net(cond_mask_prob=0)
        assert torch.allclose(refine.guided(x, t, feats, 2.5), refine(x, t, feats))


@pytest.mark.skipif(not model_store.is_available("swiftsketch:diffusion"), reason="SwiftSketch weights not downloaded")
def test_official_checkpoints_load_strictly():
    from clipasso_studio.engine.methods import swiftsketch

    for key in (swiftsketch.DIFFUSION_KEY, swiftsketch.REFINE_KEY):
        if not model_store.is_available(key):
            continue
        ckpt = model_store.load_state(key)
        net = SwiftSketchNet.from_args(ckpt["args"])
        missing, unexpected = net.load_state_dict(ckpt["state_dict"], strict=False)
        assert not unexpected
        assert all(k.endswith("sequence_pos_encoder.pe") for k in missing)


def _fake_checkpoint_zip(path):
    net = small_net()
    buf = io.BytesIO()
    torch.save(net.state_dict(), buf)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("sketch-diffusion/", "")
        zf.writestr("sketch-diffusion/args.json", json.dumps(ARGS))
        zf.writestr("sketch-diffusion/model000000100.pt", b"old")  # an older step is ignored
        zf.writestr("sketch-diffusion/model000450000.pt", buf.getvalue())
        zf.writestr("sketch-diffusion/opt000450000.pt", b"optimizer state")
    return net


def test_checkpoint_conversion(tmp_path):
    raw = tmp_path / "download.bin"
    net = _fake_checkpoint_zip(raw)
    dest = tmp_path / "out" / "sketch_diffusion.pt"
    model_store.convert(model_store.SPECS["swiftsketch:diffusion"], raw, dest)
    ckpt = torch.load(dest, weights_only=True)
    assert ckpt["args"] == ARGS
    assert not any(k.endswith(".pe") for k in ckpt["state_dict"])
    loaded = SwiftSketchNet.from_args(ckpt["args"])
    missing, unexpected = loaded.load_state_dict(ckpt["state_dict"], strict=False)
    assert not unexpected and all(k.endswith(".pe") for k in missing)
    x, t, f = torch.randn(1, 32, 4, 2), torch.tensor([3]), torch.randn(1, 1024, 14, 14)
    with torch.no_grad():
        assert torch.allclose(loaded.eval()(x, t, f), net(x, t, f))


class _FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, ctype: str):
        super().__init__(body)
        self.headers = {"Content-Type": ctype, "Content-Length": str(len(body))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def test_google_drive_virus_scan_page_is_followed(monkeypatch, tmp_path):
    page = (b'<html><form id="download-form" action="https://drive.usercontent.google.com/download" method="get">'
            b'<input type="hidden" name="id" value="ABC"><input type="hidden" name="export" value="download">'
            b'<input type="hidden" name="confirm" value="t"><input type="hidden" name="uuid" value="u-1&amp;2">'
            b'</form></html>')
    opened = []

    def fake_open(url):
        opened.append(url)
        if len(opened) == 1:
            return _FakeResponse(page, "text/html; charset=utf-8")
        return _FakeResponse(b"PK\x03\x04payload", "application/octet-stream")

    monkeypatch.setattr(model_store, "_open", fake_open)
    dest = tmp_path / "f.bin"
    progress = []
    model_store._download_url("gdrive:ABC", dest, lambda d, t: progress.append((d, t)), None)
    assert dest.read_bytes() == b"PK\x03\x04payload"
    assert "id=ABC" in opened[0] and "export=download" in opened[0]
    assert "confirm=t" in opened[1] and "uuid=u-1%262" in opened[1]
    assert progress[-1] == (11, 11)

    monkeypatch.setattr(model_store, "_open", lambda url: _FakeResponse(b"<html>Quota exceeded</html>", "text/html"))
    with pytest.raises(RuntimeError, match="quota"):
        model_store._download_url("gdrive:ABC", dest, None, None)


@pytest.mark.skipif(not all(model_store.is_available(k) for k in ("clip:RN101", "clip:ViT-B/32", "u2net")),
                    reason="models not downloaded (run tools/fetch_models.py)")
def test_full_run_with_random_networks(monkeypatch, tmp_path):
    from clipasso_studio import settings_schema as schema
    from clipasso_studio.engine import pipeline
    from clipasso_studio.engine.methods import swiftsketch

    nets = {swiftsketch.DIFFUSION_KEY: small_net(0), swiftsketch.REFINE_KEY: small_net(1, cond_mask_prob=0)}
    monkeypatch.setattr(swiftsketch, "load_net", lambda key, device: (nets[key], {**ARGS, "diffusion_steps": 6}))
    events = []

    class Rec(pipeline.Reporter):
        def event(self, kind, **data):
            events.append((kind, data))

    settings = {**schema.default_settings("swiftsketch"), "num_sketches": 2, "fix_scale": True,
                "save_diffusion_sketch": True, "device": "cpu", "mask_model": "u2net"}
    summary = pipeline.run_job(settings, SAMPLE, str(tmp_path), Rec())
    assert summary["method"] == "swiftsketch"
    assert os.path.basename(summary["best_svg"]).startswith("camel_swiftsketch_32strokes_seed")
    runs = summary["runs"]
    assert [r["seed"] for r in runs] == [20, 1020]
    assert all(r["clip_score"] is not None for r in runs)
    assert summary["clip_score"] == max(r["clip_score"] for r in runs)
    run_dir = runs[0]["run_dir"]
    for name in ("input.png", "mask.png", "best_iter.svg", "best_iter.png", "final_svg.svg", "config.json",
                 "diffusion_sketch.svg"):
        assert os.path.isfile(os.path.join(run_dir, name)), name
    assert len(os.listdir(os.path.join(run_dir, "svg_logs"))) == 7  # 6 denoising steps + refinement
    cfg = json.loads(open(os.path.join(run_dir, "config.json")).read())
    assert cfg["status"] == "done" and cfg["iterations_done"] == 7
    iters = [d for k, d in events if k == "iteration"]
    assert iters[0]["total"] == 7 and iters[0]["loss"] is None
    assert [d["it"] for d in iters[:7]] == list(range(7))
    for kind in ("job_start", "input", "iteration", "preview", "seed_done", "job_done"):
        assert kind in [k for k, _ in events]
    # the sketch has 32 cubic strokes
    from clipasso_studio.engine import svg_io

    _, _, shapes, _ = svg_io.load_svg(summary["best_svg"])
    assert len(shapes) == 32


@pytest.mark.skipif(not all(model_store.is_available(k) for k in ("clip:RN101", "clip:ViT-B/32", "u2net")),
                    reason="models not downloaded (run tools/fetch_models.py)")
def test_cancel_keeps_the_current_sketch(monkeypatch, tmp_path):
    from clipasso_studio.engine import pipeline
    from clipasso_studio.engine.methods import swiftsketch

    monkeypatch.setattr(swiftsketch, "load_net", lambda key, device: (small_net(0), dict(ARGS)))

    class StopAfter3(pipeline.Control):
        n = 0

        def should_stop(self):
            self.n += 1
            return self.n > 3

    res = swiftsketch.run_single({"method": "swiftsketch", "device": "cpu", "mask_model": "u2net"}, SAMPLE,
                                 str(tmp_path / "run"), 0,
                                 control=StopAfter3(), device=torch.device("cpu"))
    assert res.status == "cancelled"
    assert os.path.isfile(res.best_svg)
    assert res.iterations_done == 4
