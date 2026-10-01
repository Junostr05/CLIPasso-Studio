"""Watched folder: new images are queued once they are completely written, exported when done, and
not sketched again after a restart."""

import json
import os
import time

import pytest
from PySide6.QtCore import QObject, Signal


class FakeController(QObject):
    job_finished = Signal(object)

    def __init__(self):
        super().__init__()
        self.queued = []

    def is_busy(self):
        return True

    def enqueue(self, target, settings, start=True):
        job = type("Job", (), {"id": len(self.queued) + 1, "status": "queued", "job_dir": "", "target": target})()
        self.queued.append((target, settings, job))
        return job


@pytest.fixture
def setup(qapp, tmp_path, user_data, monkeypatch):
    from clipasso_studio.gui import app_settings as settings_module
    from clipasso_studio.gui import watch
    from clipasso_studio.gui.app_settings import app_settings

    settings_module._instance = None
    folder = tmp_path / "inbox"
    folder.mkdir()
    st = app_settings()
    st.data.update(watch_enabled=True, watch_folder=str(folder), watch_formats=["png", "svg"],
                   watch_export_dir=str(tmp_path / "exports"), watch_move_done=True, watch_preset="studio")
    monkeypatch.setattr(watch, "STABLE_S", 0.2)
    yield folder, tmp_path
    settings_module._instance = None


def _write(path, size=200):
    from PIL import Image

    Image.new("RGB", (size, size), "white").save(path)


def _settle(w, seconds=0.5):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        w._check_pending()
        time.sleep(0.05)


def test_new_images_are_queued_once(setup):
    from clipasso_studio.gui.watch import FolderWatcher

    folder, tmp_path = setup
    ctl = FakeController()
    studio = {"method": "clipasso", "num_paths": 8}
    w = FolderWatcher(ctl, lambda: studio)
    _write(folder / "a.png")
    (folder / "notes.txt").write_text("not an image")
    w.scan()
    assert ctl.queued == []  # not yet: it has to stay unchanged first
    _settle(w)
    assert [os.path.basename(t) for t, _, _ in ctl.queued] == ["a.png"] and ctl.queued[0][1] == studio
    w.scan()
    _settle(w)
    assert len(ctl.queued) == 1  # waiting in the queue: not twice

    w2 = FolderWatcher(FakeController(), lambda: studio)  # after a restart
    w2.scan()
    _settle(w2)
    assert w2.controller.queued == []
    _write(folder / "a.png", 300)  # a changed image is a new one
    w2.scan()
    _settle(w2)
    assert len(w2.controller.queued) == 1


def test_an_image_still_being_written_waits(setup, monkeypatch):
    from clipasso_studio.gui import watch

    folder, _ = setup
    monkeypatch.setattr(watch, "STABLE_S", 0.4)
    ctl = FakeController()
    w = watch.FolderWatcher(ctl, lambda: {"method": "clipasso"})
    path = folder / "big.png"
    path.write_bytes(b"\x89PNG partial")
    w.scan()
    for i in range(4):  # it keeps growing
        time.sleep(0.15)
        path.write_bytes(b"\x89PNG partial" + b"x" * (i + 1) * 100)
        w._check_pending()
    assert ctl.queued == []
    _settle(w, 0.8)
    assert len(ctl.queued) == 1


def test_export_and_move_when_done(setup):
    from clipasso_studio import settings_schema as schema
    from clipasso_studio.gui.watch import DONE_DIR, FolderWatcher

    folder, tmp_path = setup
    ctl = FakeController()
    w = FolderWatcher(ctl, lambda: {"method": "clipasso"})
    _write(folder / "cat.png")
    w.scan()
    _settle(w)
    target, settings, job = ctl.queued[0]
    job_dir = tmp_path / "out" / "cat_job"
    run = job_dir / "cat_run"
    run.mkdir(parents=True)
    (run / "best_iter.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="224" height="224">'
                                       '<path d="M 10 10 L 100 100" stroke="#000" fill="none"/></svg>')
    (job_dir / "job.json").write_text(json.dumps({
        "target": target, "settings": schema.default_settings("clipasso"), "method": "clipasso",
        "best_svg": str(run / "best_iter.svg"), "best_run": "cat_run",
        "runs": [{"seed": 0, "run_name": "cat_run", "run_dir": str(run), "best_svg": str(run / "best_iter.svg"),
                  "best_loss": 0.2}]}))
    messages = []
    w.message.connect(lambda key, params: messages.append((key, params)))
    job.status, job.job_dir = "done", str(job_dir)
    ctl.job_finished.emit(job)
    exports = sorted(os.listdir(tmp_path / "exports"))
    assert exports == ["cat_clipasso.png", "cat_clipasso.svg"]
    assert not (folder / "cat.png").exists() and (folder / DONE_DIR / "cat.png").exists()
    assert messages[-1] == ("ui.watch.done", {"name": "cat.png", "n": 2})
    w.scan()  # the "done" subfolder is not watched
    _settle(w)
    assert len(ctl.queued) == 1


def test_preset_file_and_switching_off(setup):
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.watch import FolderWatcher

    folder, tmp_path = setup
    preset = tmp_path / "preset.json"
    preset.write_text(json.dumps({"method": "swiftsketch", "guidance_param": 4.0}))
    app_settings().data["watch_preset"] = str(preset)
    ctl = FakeController()
    w = FolderWatcher(ctl, lambda: {"method": "clipasso"})
    _write(folder / "owl.png")
    w.scan()
    _settle(w)
    assert ctl.queued[0][1]["method"] == "swiftsketch" and ctl.queued[0][1]["guidance_param"] == 4.0
    app_settings().data["watch_enabled"] = False
    w.reconfigure()
    _write(folder / "fox.png")
    w.scan()
    _settle(w)
    assert len(ctl.queued) == 1 and not w._poll.isActive()


def test_settings_card(setup):
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.pages.other_pages import SettingsPage

    folder, tmp_path = setup
    page = SettingsPage()
    changed = []
    page.watch_changed.connect(lambda: changed.append(1))
    assert page.watch_on.isChecked() and page.watch_folder.text() == str(folder)
    page.watch_formats["pdf"].setChecked(True)
    assert app_settings().get("watch_formats") == ["svg", "png", "pdf"]
    page.watch_on.setChecked(False)
    assert app_settings().get("watch_enabled") is False and len(changed) == 2
    page._watch_choose("watch_export_dir", page.watch_export, str(tmp_path / "x"))
    assert app_settings().get("watch_export_dir") == str(tmp_path / "x")
