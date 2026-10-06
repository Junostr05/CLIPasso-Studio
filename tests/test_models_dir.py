"""Choosing the folder of the downloaded models (moved along, seen by worker processes)."""

import os
import subprocess
import sys

import pytest


@pytest.fixture
def data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    monkeypatch.delenv("CLIPASSO_DOWNLOADS_DIR", raising=False)
    from clipasso_studio.gui import app_settings as settings_module

    settings_module._instance = None
    yield tmp_path
    settings_module._instance = None


def test_paths_follow_the_setting(data_home):
    from clipasso_studio import paths
    from clipasso_studio.gui.app_settings import app_settings

    assert paths.downloaded_models_dir() == paths.default_models_dir()
    app_settings().set("models_dir", str(data_home / "big drive" / "models"))
    assert paths.downloaded_models_dir() == data_home / "big drive" / "models"
    assert (data_home / "big drive" / "models").is_dir()
    # a worker process reads the same settings file
    code = "from clipasso_studio import paths; print(paths.downloaded_models_dir())"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=dict(os.environ),
                         cwd=os.getcwd())
    assert out.stdout.strip() == str(data_home / "big drive" / "models")


def test_move_models_merges(tmp_path):
    from clipasso_studio.engine import model_store

    src, dst = tmp_path / "a", tmp_path / "b"
    (src / "masking" / "birefnet").mkdir(parents=True)
    (src / "masking" / "birefnet" / "model.safetensors").write_bytes(b"x" * 1000)
    (src / ".partial").mkdir()
    (src / ".partial" / "lama.part").write_bytes(b"y" * 10)
    (dst / "masking" / "other").mkdir(parents=True)
    seen = []
    assert model_store.move_models(src, dst, lambda d, t: seen.append((d, t))) == 1010
    assert (dst / "masking" / "birefnet" / "model.safetensors").stat().st_size == 1000
    assert (dst / "masking" / "other").is_dir() and (dst / ".partial" / "lama.part").is_file()
    assert not any(src.iterdir()) and seen[-1] == (1010, 1010)


def test_settings_page_moves_and_switches(data_home, monkeypatch):
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from clipasso_studio import paths
    from clipasso_studio.engine import model_store
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.pages.other_pages import SettingsPage

    old = paths.downloaded_models_dir()
    (old / "scenesketch").mkdir(parents=True, exist_ok=True)
    (old / "scenesketch" / "big-lama_fp16.pt").write_bytes(b"z" * 2048)
    page = SettingsPage()
    changed = []
    page.models_dir_changed.connect(lambda: changed.append(1))
    page.busy_check = lambda: True
    from PySide6.QtWidgets import QMessageBox

    told = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: told.append("info")))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: told.append("warning")))
    assert not page.choose_models_dir(str(data_home / "new"), move=True)  # not while a job runs
    page.busy_check = lambda: False
    from clipasso_studio.gui.background import work

    assert page.choose_models_dir(str(data_home / "new"), move=True)  # (in the background)
    assert work().wait()
    assert (data_home / "new" / "scenesketch" / "big-lama_fp16.pt").is_file() and changed == [1]
    assert model_store.find("lama") == data_home / "new" / "scenesketch" / "big-lama_fp16.pt"
    assert app_settings().get("models_dir") == str((data_home / "new").resolve())
    assert "new" in page.models_edit.text()
    assert page.choose_models_dir(str(paths.default_models_dir()), move=False)  # back, without moving
    assert app_settings().get("models_dir") == "" and model_store.find("lama") is None
    assert not page.choose_models_dir(str(paths.default_models_dir() / "inside"), move=False)
    assert told == ["info", "warning"]
