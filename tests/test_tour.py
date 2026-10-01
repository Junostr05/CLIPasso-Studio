"""First-start guide: shown once on a new installation, every step highlights a visible part."""

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def make_window(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from clipasso_studio.gui import app_settings as settings_module
    from clipasso_studio.gui import theme

    theme.apply(app, "dark")
    windows = []

    def make(existing_settings: dict | None = None):
        settings_module._instance = None
        if existing_settings is not None:
            folder = tmp_path / "CLIPassoStudio"
            folder.mkdir(exist_ok=True)
            (folder / "settings.json").write_text(json.dumps(existing_settings))
        from clipasso_studio.gui.main_window import MainWindow

        w = MainWindow()
        w.controller.start_next = lambda: None
        w.resize(1400, 900)
        w.show()
        app.processEvents()
        windows.append(w)
        return w

    yield make
    for w in windows:
        w.studio.shutdown()
        w.controller.shutdown()
        w.close()
    settings_module._instance = None


def test_first_start_shows_every_step(make_window):
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.tour import STEPS

    w = make_window()
    assert app_settings().get("tour_done") is False
    w.maybe_show_tour()
    tour = w.tour
    assert tour is not None and tour.isVisible()
    for i in range(len(STEPS)):
        assert tour.index == i
        target = tour.target_rect()
        assert not target.isNull() and w.rect().intersects(target), STEPS[i][0]
        assert not tour.card.geometry().intersects(target.adjusted(10, 10, -10, -10)), STEPS[i][0]
        assert w.rect().contains(tour.card.geometry()), STEPS[i][0]
        assert tour.title.text() and tour.text.text()
        tour.next()
    assert w.tour is None and app_settings().get("tour_done") is True
    w.maybe_show_tour()  # only once
    assert w.tour is None


def test_skip_and_back(make_window):
    from clipasso_studio.gui.app_settings import app_settings

    w = make_window()
    w.show_tour()
    tour = w.tour
    tour.back()
    assert tour.index == 0
    tour.next()
    tour.next()
    tour.back()
    assert tour.index == 1 and tour.back_btn.isEnabled()
    tour.skip_btn.click()
    assert w.tour is None and app_settings().get("tour_done") is True
    w.about.show_tour.emit()  # "Show the guide" on the About page
    assert w.tour is not None


def test_existing_installation_is_not_interrupted(make_window):
    from clipasso_studio.gui.app_settings import app_settings

    w = make_window({"output_dir": "x", "language": "en"})  # settings from 2.3
    assert app_settings().get("tour_done") is True
    w.maybe_show_tour()
    assert w.tour is None


def test_guide_texts_in_both_languages():
    with open(os.path.join("clipasso_studio", "resources", "i18n", "en.json"), encoding="utf-8") as f:
        en = json.load(f)
    with open(os.path.join("clipasso_studio", "resources", "i18n", "de.json"), encoding="utf-8") as f:
        de = json.load(f)
    from clipasso_studio.gui.tour import STEPS

    for key, _, _ in STEPS:
        for part in ("title", "text"):
            k = f"ui.tour.{key}.{part}"
            assert en.get(k) and de.get(k) and en[k] != de[k], k
