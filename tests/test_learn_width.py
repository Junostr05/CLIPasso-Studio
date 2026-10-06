"""3.7: CLIPasso can learn every stroke's width (``learn_width``) – within limits around the set width, pulled back
towards it a little, and kept when an interrupted job continues."""

import os
import re
from types import SimpleNamespace

import pytest
import torch

from clipasso_studio import settings_schema as schema
from clipasso_studio.engine import model_store, painter

CAMEL = os.path.join(os.path.dirname(__file__), "..", "clipasso_studio", "resources", "samples", "camel.png")
CLIPASSO_MODELS = all(model_store.is_available(k) for k in ("clip:RN101", "clip:ViT-B/32", "u2net"))
SETTINGS = {"num_iter": 12, "num_sketches": 1, "num_paths": 4, "save_interval": 3, "eval_interval": 2,
            "device": "cpu"}


def _widths(svg_path: str) -> list[float]:
    with open(svg_path, encoding="utf-8") as f:
        return [float(w) for w in re.findall(r'stroke-width="([0-9.]+)"', f.read())]


def test_the_option_is_off_by_default():
    assert schema.default_settings("clipasso")["learn_width"] is False
    assert "learn_width" not in schema.default_settings("swiftsketch")


def test_clamp_and_pull_back():
    lo, hi = painter.WIDTH_RANGE
    widths = [torch.tensor(w, requires_grad=True) for w in (0.1, 2.0, 9.0)]
    stub = SimpleNamespace(width=2.0, width_vars=widths, device="cpu")
    painter.Painter.clamp_widths(stub)
    assert [round(float(w), 4) for w in widths] == [lo * 2.0, 2.0, hi * 2.0]
    # no pull at the set width; away from it the gradient points back
    stub.width_vars = [torch.tensor(2.0, requires_grad=True)]
    assert float(painter.Painter.width_penalty(stub)) == 0.0
    stub.width_vars = [torch.tensor(4.0, requires_grad=True), torch.tensor(1.0, requires_grad=True)]
    pen = painter.Painter.width_penalty(stub)
    assert float(pen) == pytest.approx(painter.WIDTH_REG * (1.0 + 0.25) / 2)
    pen.backward()
    assert stub.width_vars[0].grad > 0 > stub.width_vars[1].grad
    assert float(painter.Painter.width_penalty(SimpleNamespace(width_vars=[], device="cpu"))) == 0.0


@pytest.mark.skipif(not CLIPASSO_MODELS, reason="models not downloaded (run tools/fetch_models.py)")
def test_the_widths_are_learnt_and_kept_when_continuing(tmp_path):
    from clipasso_studio.engine import checkpoint, pipeline

    from .test_resume import _stop_after

    fixed = pipeline.run_job(SETTINGS, CAMEL, str(tmp_path / "fixed"))
    base = _widths(os.path.join(fixed["runs"][0]["run_dir"], "final_svg.svg"))
    assert len(set(base)) == 1  # (off: all strokes as wide as set)

    learn = {**SETTINGS, "learn_width": True}
    whole = pipeline.run_job(learn, CAMEL, str(tmp_path / "whole"))
    final = os.path.join(whole["runs"][0]["run_dir"], "final_svg.svg")
    widths = _widths(final)
    assert len(widths) == 4 and len(set(widths)) > 1  # every stroke its own width
    lo, hi = painter.WIDTH_RANGE
    assert all(lo * base[0] - 1e-3 <= w <= hi * base[0] + 1e-3 for w in widths)

    rec, stop = _stop_after(5)
    part = pipeline.run_job(learn, CAMEL, str(tmp_path / "part"), rec, stop)
    run_dir = part["runs"][0]["run_dir"]
    ck = checkpoint.load(run_dir)
    assert ck["width_optim"] is not None and len(ck["widths"]) == 4
    rec2, _ = _stop_after(10 ** 9)
    done = pipeline.run_job(learn, CAMEL, str(tmp_path), rec2, job_dir=os.path.dirname(part["best_svg"]),
                            resume=True)
    assert rec2.iterations == 12 - 5
    with open(final, encoding="utf-8") as a, open(os.path.join(done["runs"][0]["run_dir"], "final_svg.svg"),
                                                  encoding="utf-8") as b:
        assert a.read() == b.read()  # the same strokes and widths as without the interruption
