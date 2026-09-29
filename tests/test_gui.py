import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def window(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("appdata")
    os.environ["XDG_DATA_HOME"] = str(tmp)
    os.environ["LOCALAPPDATA"] = str(tmp)
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from clipasso_studio.gui import theme
    from clipasso_studio.gui.app_settings import app_settings

    app_settings().data["output_dir"] = str(tmp / "out")
    theme.load_fonts()
    theme.apply(app, "dark")
    from clipasso_studio.gui.main_window import MainWindow

    w = MainWindow()
    w.show()
    yield w
    w.controller.shutdown()
    w.close()


def test_every_parameter_has_a_field(window):
    from clipasso_studio import settings_schema as schema

    assert set(window.studio.params.fields) == {p.key for p in schema.PARAMS}


def test_presets_and_quick_toggles(window):
    panel = window.studio.params
    panel.apply_preset("fast")
    assert panel.settings()["num_iter"] == 501 and panel.settings()["num_sketches"] == 1
    panel.apply_preset("standard")
    assert panel.settings()["num_iter"] == 2001
    lbl, switch = window.studio.quick["mask_object"]
    switch.setChecked(True)
    assert panel.settings()["mask_object"] is True
    panel.fields["mask_object"].set_value(False, emit=True)
    assert switch.isChecked() is False


def test_layer_weights_follow_clip_model(window):
    panel = window.studio.params
    panel.fields["clip_model_name"].set_value("ViT-B/32", emit=True)
    assert len(panel.settings()["clip_conv_layer_weights"].split(",")) == 12
    panel.fields["clip_model_name"].set_value("RN101", emit=True)
    assert len(panel.settings()["clip_conv_layer_weights"].split(",")) == 5


def test_language_switch(window):
    from clipasso_studio.gui.i18n import i18n

    i18n.set_language("en")
    assert window.nav_buttons["gallery"].text() == "Gallery"
    assert window.studio.params.fields["num_paths"].title.text() == "Number of strokes"
    i18n.set_language("de")
    assert window.nav_buttons["gallery"].text() == "Galerie"


def test_pages_switch(window):
    for key in ("queue", "gallery", "models", "settings", "about", "studio"):
        window.show_page(key)
        assert window.stack.currentWidget() is window.pages[key]


def test_search_filters_fields(window):
    panel = window.studio.params
    panel.search.setText("softmax")
    assert not panel.fields["num_paths"].isVisibleTo(panel)
    assert panel.fields["softmax_temp"].isVisibleTo(panel)
    panel.search.setText("")
    assert panel.fields["num_paths"].isVisibleTo(panel)
