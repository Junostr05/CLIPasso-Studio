"""3.7, experimental sketch improvement (engine/sketch_guide.py): strokes along the photo's edges, even hatching at
45° in its dark areas – for CLIPasso and SceneSketch, switched on in the app's settings."""

import math
import os

import numpy as np
import pytest
import torch

from clipasso_studio import settings_schema as schema
from clipasso_studio.engine import model_store
from clipasso_studio.engine import sketch_guide as sg

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "clipasso_studio", "resources", "samples")
BALLERINA = os.path.join(SAMPLES, "ballerina.jpg")
CLIPASSO_MODELS = all(model_store.is_available(k) for k in ("clip:RN101", "clip:ViT-B/32", "u2net"))
BUNDLED = all(model_store.is_available(k) for k in ("clip:ViT-B/32", "u2net"))


def _half_dark(size=224):
    """Left half black, right half white: one vertical edge in the middle, a dark area on the left."""
    img = torch.ones(1, 3, size, size)
    img[..., : size // 2] = 0.0
    return img


def _line(centre, direction, length=20.0, points=4):
    d = np.asarray(direction, dtype=np.float64)
    d = d / np.linalg.norm(d)
    steps = np.linspace(-length / 2, length / 2, points)
    return torch.tensor(np.asarray(centre)[None] + steps[:, None] * d, dtype=torch.float32)[None]


def test_edges_and_the_dark_area():
    g = sg.Guide(_half_dark())
    assert g.has_edges and 0.3 < g.dark_share < 0.5  # (the dark half, minus a margin at the edge)
    assert g.region[:, :100].any() and not g.region[:, 112:].any()
    assert sg.Guide(torch.ones(1, 3, 64, 64)).hatch_count(32) == 0  # all white: nothing to hatch
    n = g.hatch_count(32)  # (in addition to the 32: the set strokes all stay for the edges)
    assert 0 < n <= int(32 * sg.MAX_HATCH_EXTRA)


def test_a_stroke_along_the_edge_costs_less_than_across_or_beside_it():
    g = sg.Guide(_half_dark())
    along = g.loss(_line((112, 112), (0, 1)), [sg.EDGE_ROLE], 3)
    across = g.loss(_line((112, 112), (1, 0)), [sg.EDGE_ROLE], 3)
    beside = g.loss(_line((115, 112), (0, 1)), [sg.EDGE_ROLE], 3)  # (close: snapped onto the edge)
    assert float(along) < float(across) and float(along) < float(beside)
    # far from every edge: no pull at all (CLIP decides where it goes)
    far = _line((200, 112), (0, 1)).requires_grad_(True)
    g.loss(far, [sg.EDGE_ROLE], 3).backward()
    assert float(far.grad.abs().sum()) < 1e-6


def test_hatch_strokes_stay_lines_at_45_degrees_in_the_dark():
    g = sg.Guide(_half_dark())
    bent = torch.tensor([[[40.0, 100.0], [50.0, 130.0], [60.0, 90.0], [70.0, 120.0]],
                         [[150.0, 50.0], [160.0, 60.0], [170.0, 50.0], [180.0, 60.0]]], requires_grad=True)
    straight = g.project(bent, [sg.HATCH_ROLE, sg.EDGE_ROLE])
    line = straight[0].detach().numpy()
    d = (line[-1] - line[0]) / np.linalg.norm(line[-1] - line[0])
    assert abs(d @ np.asarray(sg.HATCH_DIR) - 1) < 1e-5 and np.isclose(np.linalg.norm(line[-1] - line[0]), g.length)
    assert np.allclose(line.mean(axis=0), bent[0].detach().numpy().mean(axis=0), atol=1e-4)  # (through its centre)
    assert torch.equal(straight[1], bent[1])  # (other strokes as they are)
    straight[0].sum().backward()
    assert bent.grad is not None and torch.isfinite(bent.grad).all()  # (its position is still optimised)
    # in the dark costs less than outside it
    inside = g.loss(_line((50, 112), sg.HATCH_DIR), [sg.HATCH_ROLE], 3)
    outside = g.loss(_line((180, 112), sg.HATCH_DIR), [sg.HATCH_ROLE], 3)
    assert float(inside) < float(outside)
    pts = _line((150, 112), sg.HATCH_DIR).requires_grad_(True)
    g.loss(pts, [sg.HATCH_ROLE], 3).backward()
    assert pts.grad is not None and torch.isfinite(pts.grad).all()


def test_the_hatch_strokes_start_straight_parallel_and_spread():
    g = sg.Guide(_half_dark())
    strokes = g.init_hatch(10, 4, np.random.RandomState(0))
    assert len(strokes) == 10 and g.spacing > 0
    h = np.asarray(sg.HATCH_DIR)
    for s in strokes:
        d = (s[-1] - s[0]) / np.linalg.norm(s[-1] - s[0])
        assert abs(abs(d @ h) - 1) < 1e-6  # at 45°
        assert np.allclose(s[1] - s[0], s[2] - s[1])  # straight, evenly divided
        assert all(g.region[int(round(p[1])), int(round(p[0]))] for p in (s[0], s[-1]))  # in the dark
    mids = np.array([s.mean(axis=0) for s in strokes])
    gaps = [np.min(np.linalg.norm(np.delete(mids, i, axis=0) - mids[i], axis=1)) for i in range(len(mids))]
    assert min(gaps) > 0.5 * g.spacing  # (no two on top of each other)
    # even spacing: two hatch strokes side by side and too close are pushed apart
    close = torch.cat([_line((50, 112), sg.HATCH_DIR), _line((50 + 0.2 * g.spacing * math.sqrt(2), 112),
                                                               sg.HATCH_DIR)])
    apart = torch.cat([_line((50, 112), sg.HATCH_DIR), _line((50 + 1.5 * g.spacing * math.sqrt(2), 112),
                                                               sg.HATCH_DIR)])
    assert float(g._spacing(sg.bezier_samples(close, 3)[0])) > float(g._spacing(sg.bezier_samples(apart, 3)[0]))


def test_bezier_samples_of_lines_and_segments():
    line = torch.tensor([[[0.0, 0.0], [10.0, 0.0]]])
    pos, tan = sg.bezier_samples(line, 1)
    assert torch.allclose(pos[0, :, 1], torch.zeros(pos.shape[1])) and torch.allclose(tan[0, :, 0], torch.tensor(10.0))
    two = torch.tensor([[[0.0, 0.0], [1, 0], [2, 0], [3, 0], [4, 1], [5, 2], [6, 3]]])  # two cubic segments
    pos, tan = sg.bezier_samples(two, 3)
    assert pos.shape == (1, 16, 2) and float(pos[0, 0, 0]) < float(pos[0, -1, 0])


def test_the_setting_is_hidden_and_only_for_two_methods():
    for method in schema.METHODS:
        keys = {p.key for p in schema.params_for(method)}
        assert ("sketch_guide" in keys) == (method in schema.SKETCH_GUIDE_METHODS)
    assert schema.param("clipasso", "sketch_guide").hidden
    assert schema.default_settings("clipasso")["sketch_guide"] is False


@pytest.mark.skipif(not CLIPASSO_MODELS, reason="models not downloaded (run tools/fetch_models.py)")
def test_clipasso_with_the_guide_keeps_its_roles_when_continuing(tmp_path):
    from clipasso_studio.engine import checkpoint, pipeline

    from .test_resume import _stop_after

    s = {"num_iter": 10, "num_sketches": 1, "num_paths": 8, "save_interval": 3, "eval_interval": 2,
         "device": "cpu", "sketch_guide": True}
    whole = pipeline.run_job(s, BALLERINA, str(tmp_path / "whole"))
    final = os.path.join(whole["runs"][0]["run_dir"], "final_svg.svg")
    rec, stop = _stop_after(4)
    part = pipeline.run_job(s, BALLERINA, str(tmp_path / "part"), rec, stop)
    ck = checkpoint.load(part["runs"][0]["run_dir"])
    assert ck["roles"].count(sg.HATCH_ROLE) >= 1 and set(ck["roles"]) <= {sg.EDGE_ROLE, sg.HATCH_ROLE}
    assert ck["roles"].count(sg.EDGE_ROLE) == 8  # (the hatching comes in addition to the set strokes)
    widths = {round(float(w), 3) for w in ck["widths"]}
    assert widths == {1.5, round(1.5 * sg.HATCH_WIDTH, 3)}  # (finer hatch strokes)
    rec2, _ = _stop_after(10 ** 9)
    done = pipeline.run_job(s, BALLERINA, str(tmp_path), rec2, job_dir=os.path.dirname(part["best_svg"]),
                            resume=True)
    with open(final, encoding="utf-8") as a, open(os.path.join(done["runs"][0]["run_dir"], "final_svg.svg"),
                                                  encoding="utf-8") as b:
        assert a.read() == b.read()  # the same strokes as without the interruption


@pytest.mark.skipif(not BUNDLED, reason="bundled models missing (run tools/fetch_models.py)")
def test_scenesketch_with_the_guide(monkeypatch, tmp_path):
    from clipasso_studio.engine import pipeline
    from clipasso_studio.engine.methods.scenesketch import lama
    from clipasso_studio.engine.selftest_models import tiny_lama

    monkeypatch.setattr(lama, "load_lama", tiny_lama)
    s = {**schema.default_settings("scenesketch"), "layers": "8", "simplicity_levels": 1, "num_sketches": 1,
         "num_iter": 4, "object_num_iter": 4, "simplify_num_iter": 3, "eval_interval": 2, "min_eval_iter": 2,
         "save_interval": 2, "num_strokes": 12, "device": "cpu", "mask_model": "u2net", "sketch_guide": True}
    summary = pipeline.run_job(s, BALLERINA, str(tmp_path))
    job_dir = os.path.dirname(summary["best_svg"])
    parts = [os.path.join(root, f) for root, _, files in os.walk(os.path.join(job_dir, "runs")) for f in files
             if f == "part.pt"]
    roles = [torch.load(p, map_location="cpu", weights_only=False)["roles"] for p in parts]
    assert roles and all(r is not None and len(r) >= 12 for r in roles)
    assert any(sg.HATCH_ROLE in r for r in roles)  # (the ballerina's background has dark areas)
