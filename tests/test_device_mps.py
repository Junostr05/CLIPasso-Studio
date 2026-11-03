"""The Apple GPU (``device = "mps"``): chosen on request, by "auto" only for the methods where it was measured faster,
the CPU with a warning when it is not there – and jobs from a Mac stay readable on Windows."""

from __future__ import annotations

import sys

import pytest
import torch

from clipasso_studio import settings_schema as schema
from clipasso_studio.engine import pipeline, runner


@pytest.fixture
def no_cuda(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(torch.cuda, "device_count", lambda: 0)


def _mps(monkeypatch, available: bool):
    """A Mac whose Apple GPU is (not) usable."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: available)


def test_mps_chosen_when_available(monkeypatch, no_cuda):
    _mps(monkeypatch, True)
    device, warning = pipeline.resolve_device({"method": "clipasso", "device": "mps"})
    assert device.type == "mps" and warning is None


def test_mps_falls_back_with_warning(monkeypatch, no_cuda):
    _mps(monkeypatch, False)
    device, warning = pipeline.resolve_device({"method": "clipasso", "device": "mps"})
    assert device.type == "cpu" and warning.startswith("mps_unavailable:")


def test_auto_uses_mps_only_for_measured_methods(monkeypatch, no_cuda):
    _mps(monkeypatch, True)
    monkeypatch.setattr(schema, "MPS_AUTO", ("swiftsketch",))
    assert pipeline.resolve_device({"method": "swiftsketch", "device": "auto"})[0].type == "mps"
    assert pipeline.resolve_device({"method": "clipasso", "device": "auto"})[0].type == "cpu"
    monkeypatch.setattr(schema, "MPS_AUTO", ())
    assert pipeline.resolve_device({"method": "swiftsketch", "device": "auto"}) == (torch.device("cpu"), None)


def test_cuda_still_wins_over_mps(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "device_count", lambda: 1)
    monkeypatch.setattr(pipeline, "cuda_arch_supported", lambda idx: True)
    _mps(monkeypatch, True)
    monkeypatch.setattr(schema, "MPS_AUTO", schema.METHODS)
    assert pipeline.resolve_device({"method": "clipasso", "device": "auto"})[0].type == "cuda"


def test_mps_is_one_worker(monkeypatch):
    settings = {"method": "clipasso", "device": "mps", "num_sketches": 4}
    assert runner.plan_workers(settings, 4, auto=True, cuda=False, hw=(16, 64e9)) == 1
    assert not runner.spreads_over_gpus(settings, 4, cuda=False, gpus=2)
    auto = dict(settings, device="auto")
    assert runner.plan_workers(auto, 4, auto=True, hw=(16, 64e9), mps=True) == 4  # not measured: the CPU, in parallel
    monkeypatch.setattr(schema, "MPS_AUTO", ("clipasso",))
    assert runner.plan_workers(auto, 4, auto=True, hw=(16, 64e9), mps=True) == 1
    assert runner.plan_workers(auto, 4, auto=True, hw=(16, 64e9), mps=False) == 4


def test_coerce_accepts_mps_everywhere():
    for method in schema.METHODS:
        assert "mps" in schema.param(method, "device").choices
        assert schema.normalize({"method": method, "device": "mps"})["device"] == "mps"


def test_mps_offered_only_on_macos(monkeypatch):
    device = schema.param("clipasso", "device")
    monkeypatch.setattr(sys, "platform", "win32")
    assert schema.offered_choices(device) == ("auto", "cpu", "cuda")
    monkeypatch.setattr(sys, "platform", "darwin")
    assert schema.offered_choices(device) == ("auto", "cpu", "cuda", "mps")
    other = schema.param("clipasso", "saliency_model")
    assert schema.offered_choices(other) == other.choices


def test_device_choice_hidden_off_macos_in_the_studio(qapp, monkeypatch):
    from clipasso_studio.gui.widgets.param_panel import ParamField

    monkeypatch.setattr(sys, "platform", "linux")
    field = ParamField(schema.param("clipasso", "device"))
    assert [field.combo.itemData(i) for i in range(field.combo.count())] == ["auto", "cpu", "cuda"]


def test_mps_texts_in_both_languages():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "clipasso_studio" / "resources" / "i18n"
    for lang in ("en", "de"):
        texts = json.loads((root / f"{lang}.json").read_text(encoding="utf-8"))
        assert texts["param.device.choice.mps"] and texts["ui.warn.mps_unavailable"]


def test_channels_last_only_where_measured():
    """CLIP's convolutions in channels-last layout were measured 1.4x faster on a CPU; on the Apple GPU its backward
    pass fails (\"view size is not compatible …\", seen on the macOS runner), so it is not used there."""
    from clipasso_studio.engine.clip_ import clip

    assert clip.channels_last_ok(torch.device("cpu")) and clip.channels_last_ok(torch.device("cuda", 0))
    assert not clip.channels_last_ok(torch.device("mps"))


def test_mps_job_on_another_computer_is_automatic(monkeypatch):
    """A job made on a Mac and continued on Windows (or Linux) asks for "mps": there it computes as "auto" would – on
    the NVIDIA card when there is one – without a warning."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "device_count", lambda: 1)
    monkeypatch.setattr(pipeline, "cuda_arch_supported", lambda idx: True)
    assert pipeline.resolve_device({"method": "clipasso", "device": "mps"}) == (torch.device("cuda:0"), None)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(torch.cuda, "device_count", lambda: 0)
    assert pipeline.resolve_device({"method": "clipasso", "device": "mps"}) == (torch.device("cpu"), None)
