"""ControlSketch's SDXL attention on graphics cards with less than 8 GB: that step runs on the CPU, the rest on the
card; a card that runs out of memory hands the step to the CPU as well. Progress, pause and stop work during it,
a continued run does not compute it again, and the settings say so when the model is chosen."""

import os
from pathlib import Path
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


def test_run_mode(monkeypatch):
    _card(monkeypatch, 6.0)  # GTX 1060
    assert S.run_mode(torch.device("cuda", 0)) == "offload"
    assert S.run_mode(torch.device("cuda", 0), place="cpu") == "cpu"
    assert S.run_mode("cpu") == "cpu"
    _card(monkeypatch, 7.99)  # an "8 GB" card
    assert S.run_mode(torch.device("cuda", 0)) == "gpu"


@pytest.fixture
def calls(monkeypatch):
    seen, fail = [], {}  # fail: mode -> the error it raises

    def fake(image, object_name, device, size, pipe=None, steps=S.STEPS, tick=None, offload=False):
        mode = "cpu" if torch.device(device).type == "cpu" else "offload" if offload else "gpu"
        seen.append(mode)
        if mode in fail:
            raise fail[mode]()
        return torch.zeros(size, size)

    monkeypatch.setattr(S, "sdxl_attention", fake)
    return seen, fail


def _logs():
    out = []
    return out, lambda code, **p: out.append((code, p))


def test_a_small_card_computes_it_piece_by_piece_or_on_the_cpu(monkeypatch, calls):
    seen, _ = calls
    _card(monkeypatch, 6.0)
    logs, log = _logs()
    attn = S.object_attention(None, "camel", torch.device("cuda", 0), 32, log=log)
    assert attn.shape == (32, 32) and seen == ["offload"] and logs == [("sdxl_offload", {"gb": "6"})]
    seen.clear()
    logs, log = _logs()
    S.object_attention(None, "camel", torch.device("cuda", 0), 32, place="cpu", log=log)
    assert seen == ["cpu"] and logs == [("sdxl_cpu", {"gb": "6"})]


def test_a_big_card_computes_it_itself(monkeypatch, calls):
    seen, _ = calls
    _card(monkeypatch, 12.0)
    logs, log = _logs()
    S.object_attention(None, "camel", torch.device("cuda", 0), 32, log=log)
    assert seen == ["gpu"] and logs == []
    seen.clear()
    S.object_attention(None, "camel", torch.device("cpu"), 32, log=log)
    assert seen == ["cpu"] and logs == []  # the CPU edition: nothing to say


def test_out_of_graphics_memory_goes_on_piece_by_piece_then_on_the_cpu(monkeypatch, calls):
    seen, fail = calls
    _card(monkeypatch, 8.0)
    oom = lambda: RuntimeError("CUDA out of memory. Tried to allocate 640.00 MiB")  # noqa: E731
    fail["gpu"] = oom
    logs, log = _logs()
    S.object_attention(None, "camel", torch.device("cuda", 0), 32, log=log)
    assert seen == ["gpu", "offload"] and [c for c, _ in logs] == ["sdxl_offload_oom"]
    seen.clear()
    fail["offload"] = oom
    logs, log = _logs()
    S.object_attention(None, "camel", torch.device("cuda", 0), 32, log=log)
    assert seen == ["gpu", "offload", "cpu"] and [c for c, _ in logs] == ["sdxl_offload_oom", "sdxl_cpu_oom"]
    fail.clear()
    fail["gpu"] = lambda: ValueError("something else")
    with pytest.raises(ValueError):  # other errors are errors
        S.object_attention(None, "camel", torch.device("cuda", 0), 32)
    fail.clear()
    fail["cpu"] = oom
    _card(monkeypatch, 6.0)
    with pytest.raises(RuntimeError):  # (the CPU is the end of the chain)
        S.object_attention(None, "camel", torch.device("cuda", 0), 32, place="cpu")


def test_offload_loads_the_pipeline_piece_by_piece(monkeypatch):
    """``load_pipeline(offload=True)``: the networks in the RAM, the (small) VAE on the card as a whole."""
    import diffusers

    from clipasso_studio.engine import model_store

    calls = {}

    class FakePipe:
        _exclude_from_cpu_offload = []

        def set_progress_bar_config(self, **kw):
            pass

        def enable_sequential_cpu_offload(self, gpu_id=None):
            calls["offload"] = (gpu_id, list(self._exclude_from_cpu_offload))

        def to(self, device):
            calls["to"] = str(device)
            return self

    monkeypatch.setattr(diffusers.StableDiffusionXLPipeline, "from_pretrained",
                        classmethod(lambda cls, *a, **k: FakePipe()))
    monkeypatch.setattr(model_store, "model_dir", lambda key: Path("/nowhere"))
    S.load_pipeline(torch.device("cuda", 1), offload=True)
    assert calls == {"offload": (1, ["vae"])} and FakePipe._exclude_from_cpu_offload == []  # (not the class's)
    S.load_pipeline(torch.device("cuda", 0))
    assert calls["to"] == "cuda:0"


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

    def fake(image, object_name, device, size, place="offload", tick=None, log=None):
        computed.append(object_name)
        for done in range(4):
            control.stop = done == stop_at[0]
            tick(done, 4, "cpu", 2.0 * done)
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
    assert s["sdxl_place"] == "offload"
    panel.set_settings(s)  # (loaded settings: no question, only the hint)
    hint = panel.fields["attn_model"].warning
    assert not hint.isHidden() and "6 GB" in hint.text() and str(methods_ui.sdxl_minutes(s, "offload")) in hint.text()
    assert hint.text() == tr("ui.sdxl_offload_hint", gb="6", minutes=methods_ui.sdxl_minutes(s, "offload"))
    panel.set_settings({**s, "sdxl_place": "cpu"})
    assert hint.text() == tr("ui.sdxl_cpu_hint", gb="6", minutes=methods_ui.sdxl_minutes(s, "cpu"))
    panel.set_settings({**s, "attn_model": "clip"})
    assert hint.isHidden()
    panel.set_settings({**s, "device": "cpu"})  # everything on the CPU anyway
    assert hint.isHidden()
    no_sdxl = methods_ui.estimate_seconds({**s, "object_name": ""}, gpu=True)
    assert methods_ui.estimate_seconds(s, gpu=True) - no_sdxl == pytest.approx(methods_ui.SDXL_OFFLOAD_SECONDS)
    assert methods_ui.estimate_seconds({**s, "sdxl_place": "cpu"}, gpu=True) - no_sdxl == pytest.approx(
        methods_ui.sdxl_seconds(s, "cpu"))
    assert methods_ui.sdxl_seconds({"num_threads": 8}, "cpu") == methods_ui.SDXL_CPU_SECONDS / 2  # all the cores
    app_settings().set("sec_per_it", {"sdxl:offload": 3.0})  # measured on this computer
    assert methods_ui.sdxl_seconds(s, "offload") == 300 and methods_ui.sdxl_minutes(s, "offload") == 5

    asked, answer = [], [("clip", False)]
    monkeypatch.setattr(param_panel, "ask_sdxl_place",
                        lambda parent, gb, minutes: asked.append((gb, sorted(minutes))) or answer[0])

    def choose(value):  # as the user does
        combo = panel.fields["attn_model"].combo
        combo.setCurrentIndex(combo.findData(value))
        return panel.settings()["attn_model"]

    panel.set_settings({**s, "attn_model": "clip"})
    assert choose("diffusion") == "clip" and asked == [("6", ["cpu", "offload"])]  # CLIP instead, not remembered
    assert not app_settings().get(methods_ui.SDXL_SMALL_GPU)
    answer[0] = ("cpu", False)
    assert choose("diffusion") == "diffusion" and panel.settings()["sdxl_place"] == "cpu"
    assert not hint.isHidden() and not app_settings().get(methods_ui.SDXL_SMALL_GPU)
    choose("clip")
    answer[0] = ("offload", True)
    assert choose("diffusion") == "diffusion" and panel.settings()["sdxl_place"] == "offload"
    assert app_settings().get(methods_ui.SDXL_SMALL_GPU) == "offload"
    choose("clip")
    assert choose("diffusion") == "diffusion" and len(asked) == 3  # remembered: not asked again
    app_settings().set(methods_ui.SDXL_SMALL_GPU, "cpu")  # (remembered by 3.1)
    choose("clip")
    assert choose("diffusion") == "diffusion" and panel.settings()["sdxl_place"] == "cpu" and len(asked) == 3
    app_settings().set(methods_ui.SDXL_SMALL_GPU, "clip")
    choose("clip")
    assert choose("diffusion") == "clip" and len(asked) == 3
    assert not hint.isHidden() and hint.text() == tr("ui.sdxl_clip_remembered")

    card(8.0)  # SDXL fits: no question, no hint
    panel.refresh_hints()
    assert choose("diffusion") == "diffusion" and len(asked) == 3 and hint.isHidden()
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
    assert [page.sdxl_choice.itemData(i) for i in range(page.sdxl_choice.count())] == ["", "offload", "cpu", "clip"]
    page.sdxl_choice.setCurrentIndex(page.sdxl_choice.findData("clip"))
    assert app_settings().get(methods_ui.SDXL_SMALL_GPU) == "clip"
    app_settings().set(methods_ui.SDXL_SMALL_GPU, "cpu")  # answered in the studio
    page.refresh_sdxl_choice()
    assert page.sdxl_choice.currentData() == "cpu" and page.sdxl_desc.text()
