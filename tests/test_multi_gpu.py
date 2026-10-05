"""Several graphics cards: the sketches of a job spread over them, one worker per card with its own ``gpunum``
(stand-in processes – no graphics card is needed), the setting and the time estimate."""

import multiprocessing as mp

import pytest

from clipasso_studio import settings_schema as schema
from clipasso_studio.engine import runner


def _s(method, **kw):
    return {**schema.default_settings(method), **kw}


def test_plan_workers_with_several_cards():
    hw = (8, 64e9)
    clip = _s("clipasso", num_sketches=3)
    assert runner.plan_workers(clip, 3, cuda=True, hw=hw, gpus=2) == 2
    assert runner.plan_workers(clip, 3, cuda=True, hw=hw, gpus=4) == 3  # (no more workers than sketches)
    assert runner.plan_workers(clip, 3, cuda=True, hw=hw, gpus=1) == 1
    assert runner.plan_workers(clip, 3, cuda=False, hw=hw, gpus=2) == 3  # (no GPU: the CPU rule)
    assert runner.plan_workers({**clip, "device": "cpu"}, 3, cuda=True, hw=hw, gpus=2) == 3
    assert runner.plan_workers(_s("controlsketch"), 2, cuda=True, hw=hw, gpus=2) == 2
    assert runner.plan_workers(_s("swiftsketch"), 4, cuda=True, hw=hw, gpus=2) == 2
    assert runner.plan_workers(_s("scenesketch"), 2, cuda=True, hw=hw, gpus=2) == 1  # cells build on each other
    turbo = _s("clipasso", num_sketches=3, turbo=True)
    assert schema.turbo_prunes(turbo) and runner.plan_workers(turbo, 3, cuda=True, hw=hw, gpus=2) == 1
    assert runner.spreads_over_gpus(clip, 3, True, 2) and not runner.spreads_over_gpus(clip, 1, True, 2)


class _FakeProcess:
    started: list = []

    def __init__(self, target=None, args=(), daemon=None):
        self.args = args

    def start(self):
        _FakeProcess.started.append(self.args)

    def is_alive(self):
        return False

    def join(self, timeout=None):
        pass

    def terminate(self):
        pass


class _Ctx:
    """The spawn context, but processes that only record their arguments."""

    def __init__(self):
        self._real = mp.get_context("spawn")

    def Process(self, **kw):  # noqa: N802
        return _FakeProcess(**kw)

    def __getattr__(self, name):
        return getattr(self._real, name)


@pytest.fixture
def fake_runner(tmp_path):
    _FakeProcess.started = []
    r = runner.JobRunner(keep_warm=True)
    r._ctx = _Ctx()
    return r


def test_one_worker_per_card(fake_runner, tmp_path):
    from clipasso_studio import paths

    sample = str(paths.resource("samples", "camel.png"))
    job = fake_runner.start(_s("clipasso", num_sketches=3), sample, str(tmp_path / "out"), cuda=True, gpus=(0, 2))
    assert job.parallel and len(_FakeProcess.started) == 2
    per_worker = [(args[1]["device"], args[1]["gpunum"], args[5]) for args in _FakeProcess.started]
    assert per_worker == [("cuda", 0, [0, 2000]), ("cuda", 2, [1000])]  # card 0 and card 2, the seeds dealt out

    _FakeProcess.started = []
    fake_runner.job = None
    fake_runner.start(_s("clipasso", num_sketches=3, multiprocess=True), sample, str(tmp_path / "out"), cuda=False)
    assert len(_FakeProcess.started) == 3 and all(args[1]["device"] == "auto" for args in _FakeProcess.started)


@pytest.fixture
def own_settings(qapp, user_data):
    from clipasso_studio.gui import app_settings as settings_module

    settings_module._instance = None
    yield
    settings_module._instance = None


def test_gui_side(own_settings):
    from clipasso_studio import __version__
    from clipasso_studio.gui import hardware, methods_ui
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.pages.other_pages import SettingsPage

    card = {"name": "RTX 3060", "memory_gb": 12.0, "supported": True}
    app_settings().set("hardware", {"version": __version__, "cuda": True, "runtime": "",
                                    "gpus": [card, {**card, "supported": False}, card]})
    assert hardware.usable_gpus() == (0, 2) and hardware.spread_gpus() == (0, 2)
    s = _s("controlsketch", num_sketches=2)
    two = methods_ui.estimate_seconds(s, gpu=True)
    app_settings().set("multi_gpu", False)
    assert hardware.spread_gpus() == ()
    one = methods_ui.estimate_seconds(s, gpu=True)
    assert two < one  # the two sketches at the same time

    page = SettingsPage()
    page.set_hardware(app_settings().get("hardware"))
    assert page.multi_gpu_box.isVisibleTo(page) and not page.multi_gpu.isChecked()
    page.multi_gpu.setChecked(True)
    assert app_settings().get("multi_gpu") is True
    page.set_hardware({"version": __version__, "cuda": True, "gpus": [card]})
    assert not page.multi_gpu_box.isVisibleTo(page)  # one card: nothing to choose
