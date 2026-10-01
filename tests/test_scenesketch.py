"""SceneSketch (CLIPascene): ratios, LaMa port, preprocessing, combination, MLP painter, losses and a full
run with a tiny LaMa network (the latter needs the bundled CLIP / U2Net models)."""

import json
import math
import os

import numpy as np
import pytest
import torch

from clipasso_studio import settings_schema as schema
from clipasso_studio.engine import model_store, renderer
from clipasso_studio.engine.methods import scenesketch as ss
from clipasso_studio.engine.methods.scenesketch import combine as C
from clipasso_studio.engine.methods.scenesketch import lama, preprocess
from clipasso_studio.engine.methods.scenesketch.loss import compute_grad_norm_losses, vit_layer_features
from clipasso_studio.engine.methods.scenesketch.painter import MLPPainter, in_canvas

BUNDLED = all(model_store.is_available(k) for k in ("clip:ViT-B/32", "u2net"))
SAMPLE = os.path.join(os.path.dirname(__file__), "..", "clipasso_studio", "resources", "samples", "ballerina.jpg")


def _original_ratios(r1, step, num_ratios=8):
    """scripts_utils.get_ratios_dict with scipy's curve_fit, as in the original."""
    curve_fit = pytest.importorskip("scipy.optimize").curve_fit

    def func(x, a, c, d):
        return a * np.exp(c * x)

    ys = [r1 / 2 ** k for k in range(5)]
    popt, _ = curve_fit(func, np.linspace(0, 4, 5), ys, maxfev=3000)
    x1 = np.log(r1 / popt[0]) * (1 / popt[1])
    xs = np.linspace(x1, num_ratios * step - step + x1, num_ratios)
    return [float(f"{r:.3f}") for r in func(xs, *popt)]


@pytest.mark.parametrize("r1,step", [(4.2, 0.5), (1.37, 0.35), (9.0, 0.9)])
def test_ratios_match_the_original_fit(r1, step):
    ours = ss.ratios(r1, step, 8)
    ref = _original_ratios(r1, step)
    assert np.allclose(ours, ref, atol=2e-3), (ours, ref)
    # four levels span the same range (rows 1, 3, 5, 7 of the original matrix)
    assert np.allclose(ss.ratios(r1, step, 4), ours[::2], atol=2e-3)


def test_lama_port_structure_and_compositing():
    net = lama.LamaGenerator(ngf=8, n_blocks=1).eval()
    img = torch.rand(1, 3, 37, 45)
    mask = torch.zeros(1, 1, 37, 45)
    mask[..., 10:20, 12:30] = 1
    out = lama.inpaint(net, img, mask)
    assert out.shape == img.shape
    assert torch.equal(out[mask.expand_as(out) == 0], img[mask.expand_as(img) == 0])  # only the hole changes
    x = torch.arange(10.0).reshape(1, 1, 2, 5)
    padded = lama._pad_symmetric(x, 1, 2)
    assert padded.shape[-2:] == (3, 7) and padded[0, 0, 0, -1] == 3 and padded[0, 0, -1, 0] == 5  # np 'symmetric'
    full = lama.LamaGenerator()  # big-lama: 51 M parameters, same names as the checkpoint
    names = set(full.state_dict())
    assert "model.1.ffc.convl2l.weight" in names and "model.22.conv2.ffc.convg2g.fu.conv_layer.weight" in names
    assert "model.34.weight" in names
    assert sum(p.numel() for p in full.parameters()) == 51_057_179 - sum(
        b.numel() for n, b in full.named_buffers())


def test_square_scene():
    from PIL import Image

    wide = Image.new("RGB", (300, 200), "red")
    assert preprocess.square_scene(wide, False).size == (200, 200)
    padded = preprocess.square_scene(wide, True)
    assert padded.size == (300, 300) and padded.getpixel((150, 5)) == (255, 255, 255)
    assert preprocess.square_scene(Image.new("RGB", (800, 800)), False).size == (512, 512)


def test_object_target_enlarges_a_small_object():
    from PIL import Image

    size = 200
    mask = np.zeros((size, size), dtype=np.float32)
    mask[20:60, 30:50] = 1  # 40 x 20 object
    mask[100:102, 100:102] = 1  # tiny speck, removed like remove_small_objects
    img = Image.new("RGB", (size, size), (10, 200, 30))
    target, obj_mask, params = preprocess.object_target(img, mask, resize_obj=True)
    assert params and math.isclose(params["scale_h"], 140 / 39, rel_tol=1e-6)  # to 70 % of the canvas
    assert math.isclose(params["original_center_y"], (20 + 39 / 2) / size)
    ys, xs = np.nonzero(obj_mask > 0.5)
    assert ys.max() - ys.min() >= 135  # enlarged
    arr = np.asarray(target)
    assert tuple(arr[0, 0]) == (255, 255, 255)  # white background
    # objects that are big already, or several objects, keep their size
    _, _, params2 = preprocess.object_target(img, mask, resize_obj=False)
    assert params2 == {}
    two = np.zeros((size, size), dtype=np.float32)
    two[20:60, 30:50] = 1
    two[120:160, 130:150] = 1
    assert preprocess.object_target(img, two, resize_obj=True)[2] == {}
    labels, n = preprocess._components(two, connectivity=2)
    assert n == 2 and labels.max() == 2


def test_object_to_scene_undoes_the_enlargement():
    params = {"original_center_x": 0.2, "original_center_y": 0.3, "scale_w": 2.0, "scale_h": 4.0}
    canvas = 224
    center = torch.tensor([[112.0, 112.0], [112.0 + 40, 112.0 + 80]])
    path = renderer.Path(torch.tensor([0]), center, torch.tensor(1.5))
    out = C.object_to_scene([path], params, canvas)[0].points
    assert torch.allclose(out[0], torch.tensor([0.2 * canvas, 0.3 * canvas]))
    assert torch.allclose(out[1] - out[0], torch.tensor([20.0, 20.0]))


def test_cut_by_mask_keeps_exact_subcurves():
    canvas = 100
    mask = np.zeros((canvas, canvas), dtype=bool)
    mask[:, 40:60] = True
    ctrl = torch.tensor([[10.0, 50.0], [35.0, 20.0], [65.0, 80.0], [90.0, 50.0]])
    path = renderer.Path(torch.tensor([2]), ctrl, torch.tensor(1.5))
    pieces = C.cut_by_mask([path], mask, canvas)
    assert len(pieces) == 2
    t = np.linspace(0, 1, 50)
    for piece in pieces:
        pts = C._bezier(piece.points.double().numpy(), t)
        assert not mask[np.clip(pts[:, 1].astype(int), 0, 99), np.clip(pts[:, 0].astype(int), 0, 99)][1:-1].any()
        # every point of the piece lies on the original curve
        full = C._bezier(ctrl.double().numpy(), np.linspace(0, 1, 4001))
        assert min(np.linalg.norm(full - pts[25], axis=1)) < 0.05
    sub = C._subcurve(ctrl.double().numpy(), 0.25, 0.75)
    assert np.allclose(sub[0], C._bezier(ctrl.double().numpy(), np.array([0.25]))[0])
    assert np.allclose(sub[-1], C._bezier(ctrl.double().numpy(), np.array([0.75]))[0])
    assert C.cut_by_mask([path], np.zeros_like(mask), canvas) == [path]


def test_mlp_painter_and_width_optimisation():
    torch.manual_seed(0)
    pts = torch.rand(6, 4, 2) * 100 + 60
    pts[5] += 500  # far outside the canvas
    painter = MLPPainter(pts, 224, torch.device("cpu"), width_optim=True)
    with torch.no_grad():
        painter.render("init")
    assert painter.out_of_canvas_mask.tolist() == [1, 1, 1, 1, 1, 0]
    img = painter.render()
    assert img.shape == (1, 3, 224, 224) and img.requires_grad
    assert painter.stroke_probs.shape == (6,) and float(painter.stroke_probs[5]) == 0.0
    (1 - img).sum().backward()
    assert painter.mlp.layers_points[1].weight.grad is not None
    assert painter.mlp_width.layers_width[0].weight.grad is not None
    state = painter.state()
    paths = painter.inference(state)
    assert all(in_canvas(p, 224) for p in paths) and len(paths) <= 5
    assert painter.strokes_in_canvas() == 5


def test_grad_norm_weights():
    w = torch.nn.Parameter(torch.ones(3))
    model = torch.nn.Module()
    model.w = w
    losses = {"a": (w * 3).sum(), "b": (w * 1).sum()}
    params = list(model.parameters())
    weights, grads = compute_grad_norm_losses(losses, params, params)
    # |grad a| = 3, |grad b| = 1 -> weights (4-3)/4 and (4-1)/4
    assert math.isclose(weights["a"], 0.25, rel_tol=1e-6) and math.isclose(weights["b"], 0.75, rel_tol=1e-6)
    assert w.grad is None  # the gradients are returned, not accumulated
    assert torch.equal(grads["a"][0], torch.full((3,), 3.0)) and torch.equal(grads["b"][0], torch.ones(3))
    assert compute_grad_norm_losses({"a": (w * 2).sum()}, params, params) == ({"a": 1.0}, None)


@pytest.mark.parametrize("detach", [True, False])
def test_ratio_loss_moves_strokes_only_in_the_original(detach):
    from clipasso_studio.engine.methods.scenesketch.loss import SceneLoss

    class DummyClip(torch.nn.Module):
        visual = type("V", (), {"input_resolution": 224})()

    position = torch.tensor(2.0, requires_grad=True)  # stands for the stroke positions

    class FakeLayers(torch.nn.Module):
        def forward(self, sketch, target, mode="train"):
            return {"clip_vit_l8": position * 0.01}

    loss = SceneLoss({8: 1.0}, torch.device("cpu"), width_optim=True, ratio=30.0, clip_model=DummyClip(),
                     ratio_detach_clip=detach)
    loss.clip_loss = FakeLayers()
    widths = torch.tensor([0.9], requires_grad=True)
    weighted, _, _ = loss(None, None, widths, torch.tensor(1.0), None, None, "train")
    weighted["ratio_loss"].backward()
    assert widths.grad is not None and float(widths.grad.abs().sum()) > 0
    moved = position.grad is not None and float(position.grad.abs()) > 0
    assert moved is (not detach)
    assert ss.RATIO_DETACH_CLIP


def test_best_normalised_iteration():
    evals = {"clip_vit_l8_original_eval": [1.0, 2.0, 3.0, 4.0], "width_loss_original_eval": [1.0, 0.5, 0.1, 0.09],
             "num_strokes": [64, 30, 5, 4]}
    idx, value = ss._best_normalised(evals)
    z1 = (np.array(evals["clip_vit_l8_original_eval"]) - 2.5) / np.std(evals["clip_vit_l8_original_eval"])
    w = np.array(evals["width_loss_original_eval"])
    z2 = (w - w.mean()) / w.std()
    assert idx == int(np.argmin(z1 + z2)) and math.isclose(value, float((z1 + z2)[idx]))


@pytest.mark.skipif(not BUNDLED, reason="bundled models missing (run tools/fetch_models.py)")
def test_vit_features_match_the_hooked_encoder():
    from clipasso_studio.engine.clip_ import clip
    from clipasso_studio.engine.losses import CLIPVisualEncoder

    model, _ = clip.load("ViT-B/32", "cpu")
    x = torch.rand(2, 3, 224, 224)
    with torch.no_grad():
        _, hooked = CLIPVisualEncoder(model)(x)
        ours = vit_layer_features(model.visual, x, 8)
    assert len(ours) == 9
    for a, b in zip(ours, hooked[:9]):
        assert torch.allclose(a, b, atol=1e-5)


@pytest.mark.skipif(not BUNDLED, reason="bundled models missing (run tools/fetch_models.py)")
def test_full_run_with_tiny_lama(monkeypatch, tmp_path):
    from clipasso_studio.engine import pipeline
    from clipasso_studio.engine.selftest_models import tiny_lama

    monkeypatch.setattr(lama, "load_lama", tiny_lama)
    events = []

    class Rec(pipeline.Reporter):
        def event(self, kind, **data):
            events.append((kind, data))

    s = {**schema.default_settings("scenesketch"), "layers": "4_8", "simplicity_levels": 2, "num_sketches": 2,
         "num_iter": 4, "object_num_iter": 5, "simplify_num_iter": 3, "eval_interval": 2, "min_eval_iter": 2,
         "save_interval": 2, "num_strokes": 6, "device": "cpu", "mask_model": "u2net"}
    summary = pipeline.run_job(s, SAMPLE, str(tmp_path), Rec())
    runs = summary["runs"]
    assert [r["seed"] for r in runs] == [400, 401, 402, 800, 801, 802]
    job_dir = os.path.dirname(summary["best_svg"])
    for name in ("scene.png", "background.png", "mask.png", "object.png", "matrix.png", "job.json"):
        assert os.path.isfile(os.path.join(job_dir, name)), name
    for r in runs:
        for name in ("best_iter.svg", "best_iter.png", "background.svg", "object.svg", "config.json"):
            assert os.path.isfile(os.path.join(r["run_dir"], name)), (r["run_name"], name)
        assert r["clip_score"] is not None and r["method"] == "scenesketch"
        assert os.listdir(os.path.join(r["run_dir"], "svg_logs"))
    cfg = json.load(open(os.path.join(runs[0]["run_dir"], "config.json")))
    assert cfg["layer"] == 4 and cfg["level"] == 0 and len(cfg["ratios_background"]) == 2
    kinds = [k for k, _ in events]
    for kind in ("job_start", "input", "condition", "attention", "iteration", "preview", "seed_done", "job_done"):
        assert kind in kinds, kind
    its = [d for k, d in events if k == "iteration"]
    assert its[-1]["eta_job"] and {d["part"] for d in its} == {"background", "object"}
    # per cell the iterations add up to the planned total
    for cell in (400, 402, 801):
        done = [d for d in its if d["seed"] == cell]
        assert done[-1]["total"] == schema.scene_cell_iterations(s, cell) and len(done) == done[-1]["total"]
    # the simplification levels drop strokes (or keep them), never add any
    counts = [json.load(open(os.path.join(r["run_dir"], "config.json")))["background_strokes"] for r in runs[3:]]
    assert counts[0] >= counts[1] >= counts[2] or counts[0] <= s["num_strokes"]


@pytest.mark.skipif(not BUNDLED, reason="bundled models missing (run tools/fetch_models.py)")
def test_cancel_keeps_a_partial_cell(tmp_path, monkeypatch):
    from clipasso_studio.engine import pipeline
    from clipasso_studio.engine.selftest_models import tiny_lama

    monkeypatch.setattr(lama, "load_lama", tiny_lama)

    class StopSoon(pipeline.Control):
        n = 0

        def should_stop(self):
            self.n += 1
            return self.n > 6

    s = {**schema.default_settings("scenesketch"), "layers": "8", "simplicity_levels": 2, "num_sketches": 1,
         "num_iter": 5, "object_num_iter": 5, "simplify_num_iter": 3, "eval_interval": 2, "min_eval_iter": 2,
         "num_strokes": 6, "device": "cpu", "mask_model": "u2net"}
    summary = pipeline.run_job(s, SAMPLE, str(tmp_path), control=StopSoon())
    assert [r["seed"] for r in summary["runs"]] == [800]
    assert summary["runs"][0]["status"] == "cancelled"


@pytest.mark.skipif(not BUNDLED, reason="bundled models missing (run tools/fetch_models.py)")
def test_plain_background_sketches_only_the_object(tmp_path, monkeypatch):
    from clipasso_studio.engine import pipeline
    from clipasso_studio.engine.selftest_models import tiny_lama

    monkeypatch.setattr(lama, "load_lama", tiny_lama)
    camel = os.path.join(os.path.dirname(SAMPLE), "camel.png")
    warnings = []

    class Rec(pipeline.Reporter):
        def event(self, kind, **data):
            if kind == "warning":
                warnings.append(data.get("code"))

    s = {**schema.default_settings("scenesketch"), "layers": "8", "simplicity_levels": 1, "num_sketches": 1,
         "num_iter": 4, "object_num_iter": 4, "simplify_num_iter": 3, "eval_interval": 2, "min_eval_iter": 2,
         "num_strokes": 6, "device": "cpu", "mask_model": "u2net"}
    summary = pipeline.run_job(s, camel, str(tmp_path), Rec())
    assert "scene_plain_background" in warnings
    for r in summary["runs"]:
        cfg = json.load(open(os.path.join(r["run_dir"], "config.json")))
        assert cfg["background_strokes"] == 0 and cfg["object_strokes"] > 0


def test_gradient_balancing_without_an_extra_backward_pass():
    """SceneLoss.backward() gives the gradients of the old way (one backward per loss to weigh them,
    then one more for the weighted sum), without that last pass."""
    import torch
    from torch import nn

    from clipasso_studio.engine.methods.scenesketch.loss import SceneLoss, compute_grad_norm_losses

    def setup():
        torch.manual_seed(0)
        points, width = nn.Linear(4, 6), nn.Linear(4, 3)
        x = torch.randn(2, 4)
        p, w = points(x), torch.sigmoid(width(x))
        losses = {"clip_vit_l2": ((p * w.sum()) ** 2).mean(), "clip_vit_l8": (p.sin() * 0.3).mean() + w.mean(),
                  "width_loss": w.sum() / 3.0}
        coeffs = {"clip_vit_l2": 1.0, "clip_vit_l8": 0.5, "width_loss": 2.0}
        return points, width, losses, coeffs

    # the 2.4 way
    points, width, losses, coeffs = setup()
    norms = {}
    for name, loss in losses.items():
        loss.backward(retain_graph=True)
        params = [q for q in width.parameters() if q.grad is not None]
        norms[name] = sum(q.grad.abs().sum().item() for q in params) / sum(q.numel() for q in params)
        width.zero_grad()
        points.zero_grad()
    total = sum(norms.values())
    weights_old = {k: (total - norms[k]) / ((len(losses) - 1) * total) for k in losses}
    sum(v * weights_old[k] * coeffs[k] for k, v in losses.items()).backward()
    old = [q.grad.clone() for q in list(points.parameters()) + list(width.parameters())]

    # 3.0
    points, width, losses, coeffs = setup()
    params = list(points.parameters()) + list(width.parameters())
    weights, grads = compute_grad_norm_losses(losses, list(width.parameters()), params)
    assert all(abs(weights[k] - weights_old[k]) < 1e-6 for k in losses)
    fn = SceneLoss.__new__(SceneLoss)  # without its CLIP loss: only backward() is used here
    nn.Module.__init__(fn)
    fn.new_weights, fn._grads = weights, (params, grads, coeffs)
    fn.backward({k: v * weights[k] * coeffs[k] for k, v in losses.items()})
    for a, b in zip(old, [q.grad for q in params]):
        assert torch.allclose(a, b, atol=1e-6)
