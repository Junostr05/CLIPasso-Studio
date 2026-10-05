"""The resource guard (gui/resources.py): the memory a job needs on the CPU or a graphics card, what is short,
the smaller settings it suggests and the question before the start."""

import pytest

from clipasso_studio import settings_schema as schema

GB = 1e9
GTX1060 = {"name": "NVIDIA GeForce GTX 1060 6GB", "memory_gb": 6.0, "supported": True}


@pytest.fixture
def res(qapp, user_data):
    from clipasso_studio.gui import app_settings as settings_module
    from clipasso_studio.gui import resources

    settings_module._instance = None
    yield resources
    settings_module._instance = None


def _s(method, **kw):
    return {**schema.default_settings(method), **kw}


def test_need_on_the_cpu(res):
    n = res.need(_s("clipasso", num_sketches=3), None, memory=(16 * GB, 32 * GB), cores=8)
    assert n.workers == 3 and n.ram == 3 * res.CPU_RAM["clipasso"] and not n.short  # sketches in parallel
    n = res.need(_s("clipasso", num_sketches=3), None, memory=(16 * GB, 32 * GB), cores=4)
    assert n.workers == 1  # (too few cores for parallel sketches)
    n = res.need(_s("controlsketch"), None, memory=(6 * GB, 8 * GB))
    assert n.short == ["ram"] and n.ram == res.CPU_RAM["controlsketch"]
    sdxl = _s("controlsketch", attn_model="diffusion", object_name="camel")
    assert res.need(sdxl, None, memory=(14 * GB, 16 * GB)).ram == res.SDXL_CPU_RAM


def test_need_on_a_graphics_card(res):
    s = _s("controlsketch")
    n = res.need(s, GTX1060, memory=(12 * GB, 16 * GB))
    assert not n.short and n.vram == res.VRAM["controlsketch"] and n.ram == res.GPU_RAM["controlsketch"]
    n32 = res.need(s, GTX1060, gpu_precision="fp32", memory=(12 * GB, 16 * GB))
    assert n32.short == ["vram"] and n32.vram == 2 * res.VRAM["controlsketch"]
    sdxl = {**s, "attn_model": "diffusion", "object_name": "camel"}
    small_sdxl = res.need(sdxl, GTX1060, memory=(12 * GB, 16 * GB))  # piece by piece through the 6 GB card
    assert not small_sdxl.short and small_sdxl.ram == res.SDXL_OFFLOAD_RAM
    small_sdxl = res.need({**sdxl, "sdxl_place": "cpu"}, GTX1060, memory=(12 * GB, 16 * GB))
    assert small_sdxl.short == ["ram"] and small_sdxl.ram == res.SDXL_CPU_RAM  # on the CPU next to the card
    big = {**GTX1060, "memory_gb": 24.0}
    assert not res.need({**s, "attn_model": "diffusion", "object_name": "camel"}, big,
                        memory=(12 * GB, 16 * GB)).short


def test_suggestions(res):
    s = _s("controlsketch", render_size=512)
    n = res.need(s, GTX1060, gpu_precision="fp32", memory=(12 * GB, 16 * GB))
    assert res.suggestion(s, n) == {"render_size": 384, "turbo": True}
    s = _s("clipasso", num_sketches=4, multiprocess=True)
    n = res.need(s, None, memory=(4 * GB, 8 * GB), cores=8)
    changes = res.suggestion(s, n)
    assert changes["multiprocess"] is False
    n = res.need(_s("swiftsketch"), {**GTX1060, "memory_gb": 1.0}, memory=(12 * GB, 16 * GB))
    assert res.suggestion(_s("swiftsketch"), n) == {"device": "cpu"}  # nothing smaller: the processor
    text = res.describe({"turbo": True, "device": "cpu", "render_size": 384})
    assert "384" in text and text.count(",") == 2


def _answer(monkeypatch, label_key, remember=False):
    from PySide6.QtWidgets import QMessageBox

    from clipasso_studio.gui.i18n import tr

    asked = []

    def fake_exec(box):
        asked.append(box.informativeText())
        if remember:
            box.checkBox().setChecked(True)
        for b in box.buttons():
            if b.text() == tr(label_key):
                b.click()
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    return asked


def test_confirm(res, monkeypatch):
    from clipasso_studio import __version__
    from clipasso_studio.gui.app_settings import app_settings

    s = _s("controlsketch", render_size=512)
    asked = _answer(monkeypatch, "ui.resources.use_smaller")
    assert res.confirm(None, s) is s and not asked  # the hardware is not known yet: no question
    app_settings().set("hardware", {"version": __version__, "cuda": True, "runtime": "", "gpus": [GTX1060]})
    app_settings().set("gpu_precision", "fp32")
    monkeypatch.setattr(res, "_memory", lambda: (12 * GB, 16 * GB))
    out = res.confirm(None, s)
    assert asked and out["render_size"] == 384 and out["turbo"] is True
    _answer(monkeypatch, "ui.cancel")
    assert res.confirm(None, s) is None
    asked = _answer(monkeypatch, "ui.resources.anyway", remember=True)
    assert res.confirm(None, s) is s and asked
    assert app_settings().get(res.SETTING) is False
    asked = _answer(monkeypatch, "ui.cancel")
    assert res.confirm(None, s) is s and not asked  # "don't ask again"
