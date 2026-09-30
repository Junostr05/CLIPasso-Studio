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


def test_language_setting_offers_auto(window):
    combo = window.pages["settings"].lang
    assert [combo.itemData(i) for i in range(combo.count())] == ["auto", "de", "en"]
    assert combo.currentData() == "auto"  # default: follow the system language
    assert "(" in combo.itemText(0)  # names the detected language


def test_scenesketch_in_the_studio(window):
    from clipasso_studio.gui.widgets.canvas import MatrixView

    studio = window.studio
    studio.params.set_method("scenesketch")
    assert studio.params.method() == "scenesketch"
    assert studio.params.settings()["layers"] == "8"  # starts with the standard preset, not the 3 x 9 matrix
    assert not studio.modes._buttons["matrix"].isHidden()
    assert studio.modes._buttons["condition"].text() == "Background" or studio.modes._buttons[
        "condition"].text() == "Hintergrund"
    assert studio.series_btn.isHidden()
    studio.modes.set_current("matrix")
    studio._mode_changed("matrix")
    assert studio.matrix.isVisibleTo(studio) and not studio.canvas.isVisibleTo(studio)
    studio.params.set_method("clipasso")
    assert studio.modes.current() == "sketch" and studio.modes._buttons["matrix"].isHidden()
    assert studio.canvas.isVisibleTo(studio)

    m = MatrixView()
    m.resize(300, 400)
    m.set_layout([2, 8], 2)
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="224" height="224" viewBox="0 0 224 224">'
           '<path d="M 10 10 L 200 200" stroke="black" fill="none"/></svg>')
    m.set_cell(801, svg)
    clicked = []
    m.clicked.connect(clicked.append)
    center = m._cell_rect(1, 1).center()
    assert m._cell_at(center) == 801 and m._cell_at(m._cell_rect(0, 2).center()) == 202
    m.grab()  # paints without errors


def test_single_layer_export_button(window):
    assert "svg1" in window.studio.export_btns
    assert window.studio.export_btns["svg1"].text() in ("SVG · 1 layer", "SVG · 1 Ebene")


def test_pages_switch(window):
    for key in ("compare", "queue", "gallery", "models", "settings", "about", "studio"):
        window.show_page(key)
        assert window.stack.currentWidget() is window.pages[key]


def test_search_filters_fields(window):
    panel = window.studio.params
    panel.search.setText("softmax")
    assert not panel.fields["num_paths"].isVisibleTo(panel)
    assert panel.fields["softmax_temp"].isVisibleTo(panel)
    panel.search.setText("")
    assert panel.fields["num_paths"].isVisibleTo(panel)


def test_method_switch_rebuilds_the_panel_and_remembers_settings(window):
    from clipasso_studio import settings_schema as schema

    studio = window.studio
    panel = studio.params
    studio.picker.cards["swiftsketch"].clicked.emit("swiftsketch")
    assert panel.method() == "swiftsketch" and panel.settings()["method"] == "swiftsketch"
    assert set(panel.fields) == {p.key for p in schema.SWIFT_PARAMS}
    assert panel.fields["num_sketches"].isVisibleTo(panel)
    assert not panel.pages["clipasso"].widget.isVisibleTo(panel)
    panel.fields["guidance_param"].set_value(4.0, emit=True)
    panel.apply_preset("quality")
    assert panel.settings()["num_sketches"] == 12
    assert studio.quick["mask_object"][1].isVisibleTo(studio)
    assert not studio.reuse_btn.isVisibleTo(studio) and not studio.series_btn.isVisibleTo(studio)

    studio.picker.cards["controlsketch"].clicked.emit("controlsketch")
    assert panel.method() == "controlsketch"
    assert set(panel.fields) == {p.key for p in schema.CONTROL_PARAMS}
    assert not studio.quick["mask_object"][1].isVisibleTo(studio)  # ControlSketch always masks
    assert studio.quick["fix_scale"][1].isVisibleTo(studio)
    assert panel.fields["caption"].warning.isVisibleTo(panel)  # empty caption -> BLIP hint

    studio.picker.cards["swiftsketch"].clicked.emit("swiftsketch")
    assert panel.settings()["guidance_param"] == 4.0  # remembered per method
    studio.picker.cards["clipasso"].clicked.emit("clipasso")
    assert panel.method() == "clipasso" and "num_paths" in panel.fields
    assert studio.picker.current() == "clipasso"


def test_missing_models_banner_and_cli(window):
    from PySide6.QtGui import QGuiApplication

    from clipasso_studio.engine import model_store

    studio = window.studio
    studio.params.set_method("swiftsketch")
    missing = not model_store.is_available("swiftsketch:diffusion")
    assert studio.banner.isVisibleTo(studio) == missing
    studio.copy_cli()
    assert "--method swiftsketch" in QGuiApplication.clipboard().text()
    studio.params.set_method("clipasso")
    assert not studio.banner.isVisibleTo(studio)


def test_compare_page_and_models_page(window):
    from clipasso_studio import settings_schema as schema
    from clipasso_studio.engine import model_store

    window.show_page("compare")
    window.compare.refresh()
    assert set(window.compare.cards) == set(schema.METHODS)
    assert window.compare.image_name.text()
    window.show_page("models")
    assert {r.key for r in window.models.rows} == set(model_store.SPECS)
    window.show_page("gallery")
    window.gallery.filter.changed.emit("swiftsketch")
    window.show_page("studio")


def test_loading_a_swiftsketch_result(window, tmp_path):
    import json
    import os

    from clipasso_studio import settings_schema as schema

    job = tmp_path / "camel_swiftsketch_x"
    run = job / "camel_swiftsketch_32strokes_seed20"
    os.makedirs(run / "svg_logs")
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="224" height="224"><path d="M 10 10 C 20 20 30 30 40 40" ' \
          'stroke="rgb(0,0,0)" stroke-width="2" fill="none"/></svg>'
    (run / "best_iter.svg").write_text(svg)
    (job / "camel_swiftsketch_32strokes_seed20_best.svg").write_text(svg)
    (run / "config.json").write_text(json.dumps({"seconds": 4.2, "clip_score": 81.5}))
    settings = schema.default_settings("swiftsketch")
    summary = {"target": "camel.png", "created": "2026-09-29 12:00:00", "settings": settings, "method": "swiftsketch",
               "clip_score": 81.5, "best_svg": str(job / "camel_swiftsketch_32strokes_seed20_best.svg"),
               "best_run": run.name, "runs": [{"seed": 20, "run_name": run.name, "run_dir": str(run),
                                                "best_loss": 0.185, "best_iter": 50, "iterations_done": 51,
                                                "best_svg": str(run / "best_iter.svg"), "status": "done",
                                                "method": "swiftsketch", "clip_score": 81.5, "seconds": 4.2}]}
    (job / "job.json").write_text(json.dumps(summary))
    studio = window.studio
    studio.show_job_dir(str(job))
    assert studio.params.method() == "swiftsketch"
    assert studio.stat_loss.value.text() == "81.5"
    assert studio.stat_loss.caption.text() in ("CLIP-Score", "CLIP score")
    assert studio.thumbs[20].caption.text().endswith("81.5")
    assert not studio.chart.isVisibleTo(studio)
