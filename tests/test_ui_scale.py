"""Interface size: stored in the settings, applied at the start, restart from the settings page."""

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)
    from clipasso_studio.gui import app_settings as settings_module

    settings_module._instance = None
    yield settings_module.app_settings()
    settings_module._instance = None


def test_scale_is_applied_before_the_application_starts(settings, monkeypatch):
    from clipasso_studio.gui import app

    assert app.apply_ui_scale() == 1.0 and "QT_SCALE_FACTOR" not in os.environ
    settings.data["ui_scale"] = 1.25
    assert app.apply_ui_scale() == 1.25 and os.environ["QT_SCALE_FACTOR"] == "1.25"
    monkeypatch.setenv("QT_SCALE_FACTOR", "2")  # set by the user: kept
    assert app.apply_ui_scale() == 1.25 and os.environ["QT_SCALE_FACTOR"] == "2"


def test_restart_command():
    from clipasso_studio.gui.app import restart_command

    program, args = restart_command()
    assert program == sys.executable and args[:2] == ["-m", "clipasso_studio"]


def test_settings_page_and_restart(settings, tmp_path, monkeypatch):
    from PySide6.QtCore import QProcess
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    settings.data["output_dir"] = str(tmp_path / "out")
    from clipasso_studio.gui.main_window import MainWindow

    w = MainWindow()
    w.show()
    page = w.settings
    assert page.scale.currentData() == 1.0 and not page.restart_btn.isVisibleTo(page)
    page.scale.setCurrentIndex(page.scale.findData(1.5))
    assert settings.get("ui_scale") == 1.5 and page.restart_btn.isVisibleTo(page)
    started, quit_called = [], []
    monkeypatch.setattr(QProcess, "startDetached", staticmethod(lambda prog, args: started.append((prog, args))))
    monkeypatch.setattr(QApplication, "quit", staticmethod(lambda: quit_called.append(True)))
    page.restart_btn.click()
    assert started and started[0][1][:2] == ["-m", "clipasso_studio"] and quit_called
    assert not w.isVisible()
    w.controller.shutdown()
    del app
