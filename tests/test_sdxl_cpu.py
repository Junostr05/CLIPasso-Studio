"""ControlSketch's SDXL attention on graphics cards with less than 8 GB: that step runs on the CPU, the rest on the
card; a card that runs out of memory hands the step to the CPU as well. Progress, pause and stop work during it,
a continued run does not compute it again, and the settings say so when the model is chosen."""

import os
from types import SimpleNamespace

import pytest
import torch

from clipasso_studio.engine import model_store
from clipasso_studio.engine.methods.controlsketch import sdxl_attention as S
from clipasso_studio.engine.methods.requirements import SDXL_MIN_VRAM_GB, sdxl_on_cpu

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "clipasso_studio", "resources", "samples", "camel.png")
BUNDLED = all(model_store.is_available(k) for k in ("clip:ViT-B/32", "u2net"))
GIB = 2 ** 30


def _card(monkeypatch, gib: float):
    monkeypatch.setattr(torch.cuda, "get_device_properties", lambda d: SimpleNamespace(total_memory=int(gib * GIB)))
    monkeypatch.setattr(torch.cuda, "empty_cache", lambda: None)


def test_the_rule():
    assert sdxl_on_cpu(6.0) and sdxl_on_cpu(3.0) and sdxl_on_cpu(7.4)
    assert not sdxl_on_cpu(8.0) and not sdxl_on_cpu(7.9) and not sdxl_on_cpu(24.0)
    assert not sdxl_on_cpu(0)  # not known: nothing is moved
    assert 7 < SDXL_MIN_VRAM_GB < 8


def test_run_device(monkeypatch):
    _card(monkeypatch, 6.0)  # GTX 1060
    assert S.run_device(torch.device("cuda", 0)) == torch.device("cpu")
    assert S.run_device("cpu") == torch.device("cpu")
    _card(monkeypatch, 7.99)  # an "8 GB" card
    assert S.run_device(torch.device("cuda", 0)) == torch.device("cuda", 0)


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake(image, object_name, device, size, pipe=None, steps=S.STEPS, tick=None):
        seen.append(torch.device(device))
        if callable(seen_error[0]) and torch.device(device).type == "cuda":
            raise seen_error[0]()
        return torch.zeros(size, size)

    seen_error = [None]
    monkeypatch.setattr(S, "sdxl_attention", fake)
    return seen, seen_error


def test_a_small_card_computes_it_on_the_cpu(monkeypatch, calls):
    seen, _ = calls
    logs = []
    _card(monkeypatch, 6.0)
    attn = S.object_attention(None, "camel", torch.device("cuda", 0), 32,
                              log=lambda code, **p: logs.append((code, p)))
    assert attn.shape == (32, 32) and seen == [torch.device("cpu")]
    assert logs == [("sdxl_cpu", {"gb": "6"})]


def test_a_big_card_computes_it_itself(monkeypatch, calls):
    seen, _ = calls
    logs = []
    _card(monkeypatch, 12.0)
    S.object_attention(None, "camel", torch.device("cuda", 0), 32, log=lambda code, **p: logs.append(code))
    assert seen == [torch.device("cuda", 0)] and logs == []
    seen.clear()
    S.object_attention(None, "camel", torch.device("cpu"), 32, log=lambda code, **p: logs.append(code))
    assert seen == [torch.device("cpu")] and logs == []  # the CPU edition: nothing to say


def test_out_of_graphics_memory_goes_on_on_the_cpu(monkeypatch, calls):
    seen, error = calls
    logs = []
    _card(monkeypatch, 8.0)
    error[0] = lambda: RuntimeError("CUDA out of memory. Tried to allocate 640.00 MiB")
    S.object_attention(None, "camel", torch.device("cuda", 0), 32, log=lambda code, **p: logs.append(code))
    assert seen == [torch.device("cuda", 0), torch.device("cpu")] and logs == ["sdxl_cpu_oom"]
    error[0] = lambda: ValueError("something else")
    with pytest.raises(ValueError):  # other errors are errors
        S.object_attention(None, "camel", torch.device("cuda", 0), 32)


@pytest.mark.skipif(not BUNDLED, reason="bundled models missing (run tools/fetch_models.py)")
def test_run_keeps_it_and_stops_during_it(monkeypatch, tmp_path):
    from clipasso_studio import settings_schema as schema
    from clipasso_studio.engine import pipeline
    from clipasso_studio.engine.methods import controlsketch
    from clipasso_studio.engine.methods.controlsketch import sds
    from clipasso_studio.engine.selftest_models import tiny_sd15_loader

    monkeypatch.setattr(sds, "load_sd15", tiny_sd15_loader)
    controlsketch.release_models()
    computed, events = [], []
    stop_at = [None]

    class Ctl(pipeline.Control):
        stop = False

        def should_stop(self):
            return self.stop

    control = Ctl()

    def fake(image, object_name, device, size, tick=None, log=None):
        computed.append(object_name)
        for done in range(4):
            control.stop = done == stop_at[0]
            tick(done, 4, True)
        attn = torch.zeros(size, size)
        attn[size // 4:3 * size // 4, size // 4:3 * size // 4] = 1
        return attn

    monkeypatch.setattr(S, "object_attention", fake)

    class Rec(pipeline.Reporter):
        def event(self, kind, **data):
            events.append((kind, data))

    settings = {**schema.default_settings("controlsketch"), "num_iter": 2, "save_interval": 2, "num_strokes": 6,
                "render_size": 128, "output_svg_size": 256, "condition": "canny", "caption": "a camel",
                "device": "cpu", "mask_model": "u2net", "attn_model": "diffusion", "object_name": "camel"}
    run_a, run_b = str(tmp_path / "a"), str(tmp_path / "b")
    a = controlsketch.run_single(settings, SAMPLE, run_a, 0, Rec(), control)
    b = controlsketch.run_single(settings, SAMPLE, run_b, 1000, Rec(), control)
    assert a.status == b.status == "done" and computed == ["camel"]  # once per input (the warm worker keeps it)
    assert all(os.path.isfile(os.path.join(r, "sdxl_attention.npy")) for r in (run_a, run_b))
    stages = [d for k, d in events if k == "stage" and d["name"] == "init_sdxl_cpu"]
    assert [(d["step"], d["steps"]) for d in stages] == [(i, 4) for i in range(4)]

    controlsketch.release_models()  # a new worker: continuing the run reads it from the run folder
    c = controlsketch.run_single(settings, SAMPLE, run_a, 0, Rec(), control)
    assert c.status == "done" and computed == ["camel"]

    controlsketch.release_models()
    stop_at[0] = 2  # stopped during the step: the run ends as cancelled, nothing of it is kept
    d = controlsketch.run_single(settings, SAMPLE, str(tmp_path / "d"), 0, Rec(), control)
    assert d.status == "cancelled" and computed == ["camel", "camel"]
    assert not os.path.exists(os.path.join(tmp_path / "d", "sdxl_attention.npy"))
    assert not [k for k in controlsketch._cache if k[0] in ("sdxl", "points")]
    controlsketch.release_models()


@pytest.fixture
def own_settings(qapp, user_data):
    from clipasso_studio.gui import app_settings as settings_module

    settings_module._instance = None
    yield
    settings_module._instance = None


def test_the_settings_say_so(own_settings, monkeypatch):
    from clipasso_studio import __version__
    from clipasso_studio import settings_schema as schema
    from clipasso_studio.gui import methods_ui
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.i18n import tr
    from clipasso_studio.gui.widgets import param_panel

    def card(gb):
        app_settings().set("hardware", {"version": __version__, "cuda": True, "runtime": "",
                                        "gpus": [{"name": "NVIDIA GeForce GTX 1060 6GB", "memory_gb": gb,
                                                  "supported": True, "capability": [6, 1]}]})

    card(6.0)
    panel = param_panel.ParamPanel()
    s = {**schema.default_settings("controlsketch"), "attn_model": "diffusion", "object_name": "camel"}
    panel.set_settings(s)  # (loaded settings: no question, only the hint)
    hint = panel.fields["attn_model"].warning
    minutes = methods_ui.sdxl_cpu_minutes(s)
    assert not hint.isHidden() and "6 GB" in hint.text() and str(minutes) in hint.text()
    panel.set_settings({**s, "attn_model": "clip"})
    assert hint.isHidden()
    panel.set_settings({**s, "device": "cpu"})  # everything on the CPU anyway
    assert hint.isHidden()
    no_sdxl = methods_ui.estimate_seconds({**s, "object_name": ""}, gpu=True)
    assert methods_ui.estimate_seconds(s, gpu=True) - no_sdxl == pytest.approx(methods_ui.sdxl_cpu_seconds(s))
    assert methods_ui.sdxl_cpu_seconds({"num_threads": 8}) == methods_ui.SDXL_CPU_SECONDS / 2  # all the cores

    asked, answer = [], [("clip", False)]
    monkeypatch.setattr(param_panel, "ask_sdxl_on_cpu", lambda parent, gb, minutes: asked.append(gb) or answer[0])

    def choose(value):  # as the user does
        combo = panel.fields["attn_model"].combo
        combo.setCurrentIndex(combo.findData(value))
        return panel.settings()["attn_model"]

    panel.set_settings({**s, "attn_model": "clip"})
    assert choose("diffusion") == "clip" and asked == ["6"]  # CLIP instead, not remembered
    assert not app_settings().get(methods_ui.SDXL_SMALL_GPU)
    answer[0] = ("cpu", True)
    assert choose("diffusion") == "diffusion" and app_settings().get(methods_ui.SDXL_SMALL_GPU) == "cpu"
    assert not hint.isHidden()
    choose("clip")
    assert choose("diffusion") == "diffusion" and len(asked) == 2  # remembered: not asked again
    app_settings().set(methods_ui.SDXL_SMALL_GPU, "clip")
    choose("clip")
    assert choose("diffusion") == "clip" and len(asked) == 2
    assert not hint.isHidden() and hint.text() == tr("ui.sdxl_clip_remembered")

    card(8.0)  # SDXL fits: no question, no hint
    panel.refresh_hints()
    assert choose("diffusion") == "diffusion" and len(asked) == 2 and hint.isHidden()
    assert methods_ui.estimate_seconds(s, gpu=True) == no_sdxl


def test_the_choice_in_the_settings(own_settings):
    from clipasso_studio import __version__
    from clipasso_studio.gui import methods_ui
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.pages.other_pages import SettingsPage

    page = SettingsPage()
    page.set_hardware({"version": __version__, "cuda": True, "gpus": [{"name": "RTX 4090", "memory_gb": 24.0}]})
    assert not page.sdxl_box.isVisibleTo(page)  # a big card: nothing to choose
    page.set_hardware({"version": __version__, "cuda": True, "gpus": [{"name": "GTX 1060", "memory_gb": 6.0}]})
    assert page.sdxl_box.isVisibleTo(page) and page.sdxl_choice.currentData() == ""  # ask
    page.sdxl_choice.setCurrentIndex(page.sdxl_choice.findData("clip"))
    assert app_settings().get(methods_ui.SDXL_SMALL_GPU) == "clip"
    app_settings().set(methods_ui.SDXL_SMALL_GPU, "cpu")  # answered in the studio
    page.refresh_sdxl_choice()
    assert page.sdxl_choice.currentData() == "cpu" and page.sdxl_desc.text()
