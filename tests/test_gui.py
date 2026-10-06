import os

import pytest

from tests.helpers import fake_job


@pytest.fixture(scope="module")
def window(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("appdata")
    env = pytest.MonkeyPatch()  # undone after the module: later tests use the real model folders
    env.setenv("XDG_DATA_HOME", str(tmp))
    env.setenv("LOCALAPPDATA", str(tmp))
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from clipasso_studio.gui import app_settings as settings_module
    from clipasso_studio.gui import theme
    from clipasso_studio.gui.app_settings import app_settings

    settings_module._instance = None  # fresh settings: other test modules may have changed the shared ones

    app_settings().data["output_dir"] = str(tmp / "out")
    theme.load_fonts()
    theme.apply(app, "dark")
    from clipasso_studio.gui.main_window import MainWindow

    w = MainWindow()
    w.show()
    yield w
    w.controller.shutdown()
    w.close()
    env.undo()


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
    assert not m._geometry()[4]  # 2 layers x 3 levels in a tall view: layers are columns
    m.grab()  # paints without errors
    # one column of 5 levels in a wide, low view: shown as a row, with larger cells
    m.resize(600, 280)
    m.set_layout([8], 4)
    assert m._geometry()[4] and m._geometry()[2] >= 95  # (3.5: a little room went to the axis titles)
    assert m._cell_at(m._cell_rect(0, 3).center()) == 803
    assert m._cell_rect(0, 3).left() > m._cell_rect(0, 2).right()
    m.grab()


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
    assert studio.quick["mask_object"][1].isVisibleTo(studio)  # background removal can be switched off
    assert studio.quick["mask_object"][1].isChecked()  # on by default, like the original
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

    from clipasso_studio import settings_schema as schema

    job = tmp_path / "camel_swiftsketch_x"
    run = job / "camel_swiftsketch_32strokes_seed20"
    os.makedirs(run / "svg_logs")
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="224" height="224"><path d="M 10 10 C 20 20 30 30 40 40" ' \
          'stroke="rgb(0,0,0)" stroke-width="2" fill="none"/></svg>'
    (run / "best_iter.svg").write_text(svg)
    (job / "camel_swiftsketch_32strokes_seed20_best.svg").write_text(svg)
    (run / "config.json").write_text(json.dumps({"seconds": 4.2, "clip_score": 81.5}))
    from PIL import Image

    target = tmp_path / "horse.png"
    Image.new("RGB", (30, 20), "white").save(target)
    Image.new("RGB", (30, 20), "white").save(job / "source.png")
    settings = schema.default_settings("swiftsketch")
    summary = {"target": str(target), "created": "2026-09-29 12:00:00", "settings": settings, "method": "swiftsketch",
               "clip_score": 81.5, "best_svg": str(job / "camel_swiftsketch_32strokes_seed20_best.svg"),
               "best_run": run.name, "runs": [{"seed": 20, "run_name": run.name, "run_dir": str(run),
                                                "best_loss": 0.185, "best_iter": 50, "iterations_done": 51,
                                                "best_svg": str(run / "best_iter.svg"), "status": "done",
                                                "method": "swiftsketch", "clip_score": 81.5, "seconds": 4.2}]}
    (job / "job.json").write_text(json.dumps(summary))
    studio = window.studio
    studio.show_job_dir(str(job))
    assert studio.params.method() == "swiftsketch"
    assert studio.file_label.text().startswith("horse.png") and "30×20" in studio.file_label.text()
    assert studio.stat_loss.value.text() == "81.5"
    assert studio.stat_loss.caption.text() in ("CLIP-Score", "CLIP score")
    assert studio.thumbs[20].caption.text().endswith("81.5")
    assert not studio.chart.isVisibleTo(studio)


_fake_job = fake_job  # (in tests/helpers.py: the phone's browser tests use it, too)


def test_gallery_favourites_sorting_and_delete(window, tmp_path):
    import json

    from clipasso_studio.gui.app_settings import app_settings

    out = app_settings().get("output_dir")
    os.makedirs(out, exist_ok=True)
    for d in os.listdir(out):  # other tests' jobs
        import shutil

        shutil.rmtree(os.path.join(out, d), ignore_errors=True)
    a = _fake_job(out, "rose_swiftsketch_1", str(tmp_path / "rose.png"), 70.0, created="2026-09-29 12:00:00")
    b = _fake_job(out, "crab_swiftsketch_2", str(tmp_path / "crab.png"), 85.0, created="2026-09-29 13:00:00")
    gallery = window.gallery
    window.show_page("gallery")
    gallery.refresh()

    def shown():
        return [it.job_dir for it in gallery.items()]

    assert shown() == [b, a]  # newest first
    gallery.sort.setCurrentIndex(gallery.SORTS.index("score"))  # best CLIP score
    assert shown() == [b, a]
    gallery.sort.setCurrentIndex(gallery.SORTS.index("oldest"))
    assert shown() == [a, b]
    gallery.search.setText("rose")
    gallery._apply()  # (the search waits for a pause in typing)
    assert shown() == [a]
    gallery.search.setText("")
    gallery._apply()

    gallery.delegate.star_clicked.emit(gallery.model.row_of(a))  # favourite -> stored in meta.json
    with open(os.path.join(a, "meta.json")) as f:
        assert json.load(f)["favourite"] is True
    gallery.fav_btn.setChecked(True)
    assert shown() == [a]
    gallery.fav_btn.setChecked(False)
    gallery.sort.setCurrentIndex(0)

    # open a result whose original image is gone: the studio continues with the saved copy
    os.remove(str(tmp_path / "rose.png"))
    window.studio.show_job_dir(a)
    assert window.studio.image_path == os.path.join(a, "input", "rose.png")
    assert "rose.png" in window.studio.file_label.text() and window.studio.start_btn.isEnabled()

    # delete it from the gallery: the folder is gone and the studio forgets it
    assert gallery.delete_job(a, confirm=False)
    assert not os.path.exists(a)
    assert window.studio.view_dir == "" and window.studio.image_path == ""
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    assert shown() == [b]
    window.show_page("studio")


def test_shortcuts_and_paste(window, tmp_path):

    from PySide6.QtGui import QColor, QGuiApplication, QImage

    from clipasso_studio.gui.app_settings import app_settings

    studio = window.studio
    window.shortcuts["Ctrl+2"].activated.emit()
    assert window.stack.currentWidget() is window.compare
    clip = QGuiApplication.clipboard()
    img = QImage(64, 48, QImage.Format_RGB32)
    img.fill(QColor("white"))
    clip.setImage(img)
    window.shortcuts["Ctrl+V"].activated.emit()
    assert window.stack.currentWidget() is studio
    assert os.path.dirname(studio.image_path) == os.path.join(app_settings().get("output_dir"), "_pasted")
    assert QImage(studio.image_path).size() == img.size()
    other = tmp_path / "pasted path.png"
    img.save(str(other))
    clip.setText(f'"{other}"')  # a copied file path (Windows adds quotes)
    assert studio.paste_image() and studio.image_path == str(other)
    clip.setText("just some text")
    assert not studio.paste_image() and studio.image_path == str(other)
    assert "Ctrl+O" in studio.open_btn.toolTip() and "Ctrl+2" in window.nav_buttons["compare"].toolTip()
    keys = [lbl.text() for lbl in window.about.key_labels]
    assert len(keys) == 9 and all(keys) and "Ctrl+C" in window.shortcuts
    # undo / redo of sketch edits only act on the studio page
    calls = []
    studio.undo_edit, studio.redo_edit = (lambda: calls.append("undo")), (lambda: calls.append("redo"))
    try:
        window.show_page("gallery")
        window.shortcuts["Ctrl+Z"].activated.emit()
        window.shortcuts["Ctrl+Y"].activated.emit()
        assert calls == []
        window.show_page("studio")
        window.shortcuts["Ctrl+Z"].activated.emit()
        window.shortcuts["Ctrl+Shift+Z"].activated.emit()
        assert calls == ["undo", "redo"]
    finally:
        del studio.undo_edit, studio.redo_edit


def _interrupted_job(out, tmp_path):

    from PIL import Image

    from clipasso_studio import settings_schema as schema
    from clipasso_studio.engine import jobs

    target = str(tmp_path / "horse.png")
    Image.new("RGB", (40, 40), "white").save(target)
    settings = {**schema.default_settings("swiftsketch"), "num_sketches": 3}
    job = jobs.make_job_dir(out, target, "swiftsketch")
    jobs.write_state(job, target, settings)
    run = os.path.join(job, "horse_swiftsketch_32strokes_seed0")
    os.makedirs(run)
    with open(os.path.join(run, "best_iter.svg"), "w") as f:
        f.write('<svg xmlns="http://www.w3.org/2000/svg" width="224" height="224">'
                '<path d="M 10 10 L 100 100" stroke="black" fill="none"/></svg>')
    jobs.save_result(jobs.SeedResult(seed=jobs.job_seeds(settings)[0], run_name=os.path.basename(run), run_dir=run,
                                     best_loss=0.2,
                                     best_iter=0, iterations_done=51, best_svg=os.path.join(run, "best_iter.svg"),
                                     status="done", method="swiftsketch", clip_score=80.0))
    return job


def test_continue_an_interrupted_job(window, tmp_path, monkeypatch):
    import shutil

    from PySide6.QtWidgets import QMessageBox

    from clipasso_studio.engine import jobs
    from clipasso_studio.gui.app_settings import app_settings

    out = app_settings().get("output_dir")
    os.makedirs(out, exist_ok=True)
    for d in os.listdir(out):
        shutil.rmtree(os.path.join(out, d), ignore_errors=True)
    job = _interrupted_job(out, tmp_path)
    # the gallery lists it (no job.json yet) with its progress and a Continue button
    window.show_page("gallery")
    window.gallery.refresh()
    item = window.gallery.item(job)
    assert item.can_continue and item.summary["progress"][0] == 1
    from clipasso_studio.gui.pages.gallery import GalleryPage

    page, continued = GalleryPage(), []  # (not connected to the window, which would start the job)
    page.continue_job.connect(continued.append)
    page.refresh()
    page.delegate.continue_clicked.emit(page.model.row_of(job))
    assert continued == [job]
    # the studio shows the finished sketch and offers to continue
    window.studio.show_job_dir(job)
    assert window.studio.resume_banner.isVisibleTo(window.studio) and len(window.studio.thumbs) == 1
    # at the next start the user is asked once
    asked = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: asked.append(self.text()) or 0)
    assert window.check_interrupted_jobs() == [job] and asked
    assert jobs.read_state(job)["status"] == "interrupted" and window.check_interrupted_jobs() == []
    # continue: queued with its folder, not twice
    controller = window.controller
    queued = controller.continue_job(job, start=False)
    assert queued is not None and queued.resume_dir == job and queued.to_json()["resume_dir"] == job
    assert controller.continue_job(job, start=False) is None
    controller.remove(queued.id)
    window.show_page("studio")


def test_reopened_job_shows_the_processed_input(window, tmp_path):
    """The photo/sketch slider uses the image the method saw (framed / padded), not the cropped original."""
    from PIL import Image

    from clipasso_studio.gui.app_settings import app_settings

    out = app_settings().get("output_dir")
    os.makedirs(out, exist_ok=True)
    job = _fake_job(out, "processed_job", str(tmp_path / "wide.png"), 31.0)
    window.studio.show_job_dir(job)
    assert window.studio.canvas._input.width() == 20  # the 30×20 original, centre-cropped
    Image.new("RGB", (224, 224), "white").save(os.path.join(job, "processed_job_run", "input.png"))
    window.studio.show_job_dir(job)
    assert window.studio.canvas._input.width() == 224


def test_back_to_the_running_job(window, tmp_path):
    """A result opened from the gallery during a run: the running job can be shown and paused again."""
    from clipasso_studio import settings_schema as schema
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.controller import QueuedJob

    out = app_settings().get("output_dir")
    os.makedirs(out, exist_ok=True)
    target = str(tmp_path / "running.png")
    other = _fake_job(out, "other_job", str(tmp_path / "other.png"), 30.0)
    from PIL import Image

    Image.new("RGB", (40, 40), "white").save(target)
    studio, controller = window.studio, window.controller
    job = QueuedJob(target=target, settings=schema.default_settings("swiftsketch"), status="running",
                    job_dir=str(tmp_path / "running_job"))
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="224" height="224"><path d="M 5 5 L 90 90" '
           'stroke="black" stroke-width="2" fill="none"/></svg>')
    controller.current = job
    try:
        controller.job_started.emit(job)
        seed = job.seeds[0]
        controller.job_event.emit(job, "preview", {"seed": seed, "svg": svg})
        assert studio.view_job is job and studio.pause_btn.isEnabled()
        studio.show_job_dir(other)  # the gallery opens another result
        assert studio.view_job is None and not studio.pause_btn.isEnabled()
        assert studio.running_banner.isVisibleTo(studio) and "running.png" in studio.running_banner.text.text()
        controller.job_event.emit(job, "preview", {"seed": seed, "svg": svg.replace("90 90", "80 80")})
        studio.running_banner.button.click()
        assert studio.view_job is job and studio.pause_btn.isEnabled()
        assert "80 80" in studio.canvas.svg() and not studio.running_banner.isVisibleTo(studio)
    finally:
        controller.current = None
        studio._update_buttons()


def test_gallery_knows_the_running_job(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from clipasso_studio import settings_schema as schema
    from clipasso_studio.engine import jobs
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.controller import QueuedJob

    out = app_settings().get("output_dir")
    job_dir = _interrupted_job(out, tmp_path)
    jobs.set_status(job_dir, "running")  # as while it runs
    controller = window.controller
    job = QueuedJob(target=str(tmp_path / "x.png"), settings=schema.default_settings("clipasso"), status="running",
                    job_dir=job_dir)
    controller.jobs.append(job)
    controller.current = job
    try:
        window.show_page("gallery")
        window.gallery.refresh()
        item = window.gallery.item(job_dir)
        assert item.active and not item.can_continue
        told = []
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: told.append(a))
        assert not window.gallery.delete_job(job_dir) and told and os.path.isdir(job_dir)
    finally:
        controller.current = None
        controller.jobs.remove(job)
    window.gallery.refresh()
    item = window.gallery.item(job_dir)
    assert not item.active and item.can_continue
    window.show_page("studio")


def test_scenesketch_reset_goes_back_to_the_standard_preset(window):
    from clipasso_studio import settings_schema as schema

    panel = window.studio.params
    panel.set_method("scenesketch")
    standard = schema.apply_preset(schema.default_settings("scenesketch"), "standard")
    panel.fields["num_iter"].set_value(77, emit=True)
    panel.fields["num_iter"].reset()
    assert panel.settings()["num_iter"] == standard["num_iter"]
    panel.fields["num_iter"].set_value(77, emit=True)
    panel.reset_all_fields()
    s = panel.settings()
    assert s["num_iter"] == standard["num_iter"] and s["num_iter"] != schema.default_settings("scenesketch")["num_iter"]
    assert not panel.fields["num_iter"].reset_btn.isVisibleTo(panel)
    panel.set_method("clipasso")
    panel.reset_all_fields()
    assert panel.settings()["num_iter"] == schema.default_settings("clipasso")["num_iter"]


def test_save_step_is_in_the_basics_with_the_number_of_steps(window):
    panel = window.studio.params
    for method, steps in (("clipasso", 201), ("controlsketch", 21)):
        panel.set_method(method)
        panel.reset_all_fields()
        field = panel.fields["save_interval"]
        assert field.param.group == "basics" and str(steps) in field.warning.text()
        field.set_value(1, emit=True)
        assert str(panel.settings()["num_iter"] + 1) in field.warning.text()  # every iteration
        panel.reset_all_fields()
    panel.set_method("clipasso")


def test_turbo_switch_estimate_and_dropped_sketches(window):
    from clipasso_studio import settings_schema as schema
    from clipasso_studio.gui.i18n import tr

    studio = window.studio
    panel = studio.params
    for method, shown in (("clipasso", True), ("swiftsketch", False), ("controlsketch", True), ("scenesketch", True)):
        panel.set_method(method)
        studio._sync_quick()
        assert studio.quick["turbo"][1].isVisibleTo(studio) is shown, method
        if shown:
            assert studio.quick["turbo"][0].toolTip() == tr(f"param.{method}.turbo.help") or method == "clipasso"
    panel.set_method("clipasso")
    panel.reset_all_fields()
    studio._update_estimate()
    normal = studio.estimate.text()
    studio.quick["turbo"][1].setChecked(True)
    assert panel.settings()["turbo"] is True and schema.turbo_prunes(panel.settings())
    assert studio.estimate.text() != normal  # three sketches: two of them stop after a quarter
    studio.quick["turbo"][1].setChecked(False)
    assert panel.settings()["turbo"] is False

    studio.view_method = "clipasso"
    assert studio._seed_caption(0.25, None, 0, pruned=True) == tr("ui.seed_pruned", value="0.250")
    assert studio._seed_caption(0.25, None, 0) == "0.250"


def test_brush_style_in_the_canvas(window):
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.widgets.canvas import MatrixView, SeedThumb, SketchCanvas

    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100">'
           '<path d="M 10 10 C 30 30 60 30 90 90" fill="none" stroke="#000000" stroke-width="3"/>'
           '<path d="M 10 90 C 30 60 60 60 90 10" fill="none" stroke="#000000" stroke-width="3"/></svg>')
    canvas = SketchCanvas()
    canvas.resize(200, 200)
    canvas.set_svg(svg)
    plain = canvas.grab().toImage()
    canvas.set_style("ink")
    assert canvas.svg() == svg  # the eraser keeps working on the raw strokes
    assert canvas.grab().toImage() != plain
    canvas.set_eraser(True)
    canvas._set_hover(1)
    assert canvas._hover_renderer is not None  # the hovered stroke is highlighted in the same style
    assert canvas.grab().toImage() != plain
    canvas.set_eraser(False)
    canvas.set_style("plain")
    assert canvas.grab().toImage() == plain

    matrix = MatrixView()
    matrix.set_layout([8], 0)
    matrix.set_cell(800, svg)
    before = matrix._renderers[800]
    matrix.set_style("pencil")
    assert matrix._renderers[800] is not before and matrix._svgs[800] == svg

    studio = window.studio
    studio._ensure_thumbs([0, 1000])
    studio.style_actions["marker"].trigger()
    assert app_settings().get("canvas_style") == "marker" and app_settings().get("export_style") == "marker"
    assert studio.canvas.style() == "marker" and studio.matrix._style == "marker"
    assert all(t.view.style() == "marker" for t in studio.thumbs.values())
    studio._ensure_thumbs([2000])
    assert studio.thumbs[2000].view.style() == "marker"  # also for sketches that appear later
    assert isinstance(studio.thumbs[2000], SeedThumb) and "Marker" in studio.style_btn.toolTip()
    studio.set_canvas_style("plain")
    assert studio.style_actions["plain"].isChecked()
    # the paper of the preview; the export starts with it
    from clipasso_studio.gui.i18n import tr

    studio.paper_actions["kraft"].trigger()
    assert studio.canvas.paper() == {"kind": "kraft", "vignette": 0.0}
    assert app_settings().get("export_paper") == "kraft" and app_settings().get("export_background") == "#C9A97C"
    studio.vignette_action.trigger()
    assert studio.canvas.paper()["vignette"] > 0 and app_settings().get("export_vignette") == 35
    studio.set_canvas_paper(color="#e0d0b0")
    assert app_settings().get("export_background") == "#e0d0b0"
    studio.paper_actions["none"].trigger()
    studio.vignette_action.trigger()
    assert studio.canvas.paper() is None and studio.paper_actions["none"].isChecked()
    assert studio.paper_menu.title() == tr("ui.paper.label")


def test_pen_draws_strokes_and_continue_with_clipasso(window, tmp_path, monkeypatch):
    import json

    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from clipasso_studio.gui import strokes
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.widgets.canvas import SketchCanvas

    canvas = SketchCanvas()
    canvas.resize(240, 240)
    canvas.show()
    canvas.set_svg('<svg xmlns="http://www.w3.org/2000/svg" width="224" height="224" viewBox="0 0 224 224">'
                   '<path d="M 10 10 C 20 20 30 30 40 40" fill="none" stroke="#000" stroke-width="2"/></svg>')
    drawn = []
    canvas.pen_stroke.connect(drawn.append)
    canvas.set_pen(True)
    assert canvas.pen_active() and not canvas.eraser_active()
    QTest.mousePress(canvas, Qt.LeftButton, pos=QPoint(20, 20))
    for x in range(24, 220, 8):
        QTest.mouseMove(canvas, QPoint(x, 20 + x // 2))
    canvas.grab()  # the stroke being drawn is painted
    QTest.mouseRelease(canvas, Qt.LeftButton, pos=QPoint(220, 120))
    assert len(drawn) == 1 and len(drawn[0]) > 10
    x0, y0 = drawn[0][0]
    assert 10 < x0 < 20 and 10 < y0 < 20  # sketch coordinates (the paper is the canvas minus a margin)
    canvas.set_eraser(True)
    assert not canvas.pen_active()

    out = app_settings().get("output_dir")
    os.makedirs(out, exist_ok=True)
    job = _fake_job(out, "pen_job", str(tmp_path / "pen.png"), 30.0)
    with open(os.path.join(job, "job_state.json"), "w") as f:
        json.dump({"target": str(tmp_path / "pen.png"), "settings": {}, "status": "done"}, f)
    studio = window.studio
    studio.show_job_dir(job)
    seed = studio._editable_seed()
    assert seed is not None and studio.edit_tools.isVisibleTo(studio)
    studio.pen_btn.setChecked(True)
    assert studio.canvas.pen_active()
    studio.eraser_btn.setChecked(True)
    assert not studio.pen_btn.isChecked() and studio.canvas.eraser_active()
    studio.eraser_btn.setChecked(False)
    studio._pen_stroke([(100, 100), (120, 140), (150, 120)])
    edited = os.path.join(job, "pen_job_run", "edited.svg")
    assert os.path.isfile(edited) and strokes.fixed_count(open(edited).read()) == 1
    studio.undo_edit()
    assert not os.path.isfile(edited)
    studio.redo_edit()
    assert strokes.count(studio.seed_svgs[seed]) == 2

    from PIL import Image

    Image.new("RGB", (224, 224), "white").save(os.path.join(job, "pen_job_run", "input.png"))
    image, settings = studio.continue_job(seed, 3, 101, True)
    assert os.path.basename(image) == "pen.png" and os.path.isfile(image)
    assert os.path.dirname(os.path.dirname(image)) == os.path.join(out, "_continued")
    assert settings["method"] == "clipasso" and settings["num_paths"] == 2 + 3 and settings["num_iter"] == 101
    assert settings["num_sketches"] == 1 and not settings["mask_object"] and not settings["fix_scale"]
    assert strokes.fixed_count(open(settings["path_svg"]).read()) == 1
    _, loose = studio.continue_job(seed, 0, 101, False)
    assert strokes.fixed_count(open(loose["path_svg"]).read()) == 0

    from clipasso_studio.gui import dialogs

    dlg = dialogs.ContinueDialog(2, 1)
    assert dlg.keep.isChecked() and dlg.values() == (4, 501, True) and "6" in dlg.summary.text()
    assert not dialogs.ContinueDialog(2, 0).keep.isEnabled()
    queued = []
    monkeypatch.setattr(dialogs.ContinueDialog, "exec", lambda self: dialogs.QDialog.Accepted)
    monkeypatch.setattr(studio.controller, "enqueue", lambda image, settings, start: queued.append(settings))
    studio.continue_with_clipasso()
    assert queued and queued[0]["num_paths"] == 2 + 4
    studio.revert_edits()


def test_one_line_in_the_studio(window, tmp_path, monkeypatch):
    from clipasso_studio.gui.app_settings import app_settings

    studio = window.studio
    panel = studio.params
    panel.set_method("clipasso")
    panel.reset_all_fields()
    panel.fields["one_line"].set_value(True, emit=True)
    assert not panel.fields["num_paths"].title.isEnabled() and panel.fields["one_line_segments"].title.isEnabled()
    queued = []
    monkeypatch.setattr(studio.controller, "enqueue", lambda image, s, start=True: queued.append(s))
    monkeypatch.setattr(studio, "_check_models", lambda: True)
    studio.abstraction_series()
    assert [s["one_line_segments"] for s in queued] == [16, 32, 64, 128] and all(s["one_line"] for s in queued)
    panel.reset_all_fields()

    out = app_settings().get("output_dir")
    os.makedirs(out, exist_ok=True)
    job = _fake_job(out, "line_job", str(tmp_path / "line.png"), 30.0)
    studio.show_job_dir(job)
    assert studio.edit_tools.isVisibleTo(studio) and not studio.eraser_btn.isEnabled()  # a single stroke


def test_saved_steps_and_simplify_in_the_studio(window, tmp_path, monkeypatch):
    import json
    import sys

    from clipasso_studio.engine import importance
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.pages import studio as studio_mod

    out = app_settings().get("output_dir")
    os.makedirs(out, exist_ok=True)
    job = _fake_job(out, "steps_job", str(tmp_path / "steps.png"), 30.0)
    run = os.path.join(job, "steps_job_run")
    with open(os.path.join(run, "best_iter.svg")) as f:
        best = f.read()
    two = best.replace("</svg>", '<path d="M 100 100 L 200 200" stroke="rgb(0,0,0)" stroke-width="2" fill="none"/>'
                                  "</svg>")
    with open(os.path.join(run, "best_iter.svg"), "w") as f:
        f.write(two)
    for it, svg in ((0, best), (5, two)):
        with open(os.path.join(run, "svg_logs", f"svg_iter{it}.svg"), "w") as f:
            f.write(svg)
    studio = window.studio
    studio.show_job_dir(job)
    seed = studio._editable_seed()
    assert seed is not None
    assert studio.open_history() and studio.edit_bar.mode == "history"
    studio.edit_bar.slider.setValue(0)
    studio.edit_bar.apply_btn.click()
    edited = os.path.join(run, "edited.svg")
    assert open(edited).read() == best and studio.seed_svgs[seed] == best and studio.undo_btn.isEnabled()
    studio.undo_edit()
    assert studio.seed_svgs[seed] == two and not os.path.isfile(edited)

    # Simplify: the measuring process (here a stand-in that writes the file) – then the slider works
    script = ("import json, sys; from clipasso_studio.engine import importance as i, jobs; r = sys.argv[1]; "
              "s = open(jobs.sketch_file(r)).read(); "
              "json.dump({'sha1': i.digest(s), 'drops': [1.0, 0.1]}, open(r + '/' + i.FILE, 'w'))")
    monkeypatch.setattr(studio_mod, "importance_command", lambda r: (sys.executable, ["-c", script, r]))
    assert studio.open_simplify() and not studio.edit_bar.slider.isEnabled()
    proc = studio._importance_proc
    assert proc.waitForFinished(30000)
    window_app = __import__("PySide6.QtWidgets", fromlist=["QApplication"]).QApplication.instance()
    for _ in range(50):
        window_app.processEvents()
        if studio.edit_bar.slider.isEnabled():
            break
    assert studio.edit_bar.slider.isEnabled() and importance.read(run, two) == [1.0, 0.1]
    studio.edit_bar.slider.setValue(1)
    studio.edit_bar.apply_btn.click()
    assert "200 200" not in studio.seed_svgs[seed]  # the second, less important stroke went
    studio.revert_edits()
    assert studio.seed_svgs[seed] == two
    studio.open_simplify()  # measured already: ready at once
    assert studio.edit_bar.slider.isEnabled()
    studio.edit_bar.close_bar()
    assert json.loads(open(os.path.join(run, importance.FILE)).read())["drops"] == [1.0, 0.1]


def test_time_budget_in_the_studio(window, monkeypatch):
    from clipasso_studio.gui import methods_ui

    monkeypatch.setattr(methods_ui, "_cuda", False)
    studio = window.studio
    studio.picker.select("clipasso") if hasattr(studio.picker, "select") else None
    studio.params.fields["device"].set_value("cpu", emit=True)
    toasts = []
    studio.toast.connect(lambda text, kind: toasts.append(kind))
    changes = studio.fit_to_budget(15)
    s = studio.params.settings()
    assert all(s[k] == v for k, v in changes.items())
    assert methods_ui.estimate_seconds(s, False) <= 15 * 60 * 1.05 or toasts[-1] == "info"
    assert toasts and studio.budget_actions[60].text()
    studio.params.fields["device"].set_value("auto", emit=True)


def test_detail_brush_button_in_the_studio(window, tmp_path, monkeypatch):
    import numpy as np
    from PIL import Image

    from clipasso_studio.engine import details
    from clipasso_studio.gui import detail_edit
    from clipasso_studio.gui.i18n import tr

    studio = window.studio
    path = str(tmp_path / "face.png")
    Image.new("RGB", (64, 48), (200, 180, 160)).save(path)
    studio.set_image(path)
    assert studio.detail_btn.isEnabled() and tr("ui.detail.has") not in studio.detail_btn.toolTip()

    def fake_exec(dlg):
        dlg.view.set_map(np.full_like(dlg.view.map, 255))
        dlg.apply()
        return True

    monkeypatch.setattr(detail_edit.DetailEditDialog, "exec", fake_exec)
    assert studio.edit_details()
    assert details.detail_map(Image.open(path).convert("RGB")) is not None
    assert tr("ui.detail.has") in studio.detail_btn.toolTip()
    studio.params.set_method("swiftsketch")  # does not use the map: the tip says so
    assert tr("ui.detail.not_used") in studio.detail_btn.toolTip()
    studio.params.set_method("clipasso")
    assert tr("ui.detail.not_used") not in studio.detail_btn.toolTip()
    details.remove_detail_map(Image.open(path).convert("RGB"))


def test_thumbs_in_the_studio_and_the_taste_in_the_settings(window, tmp_path, monkeypatch):
    import sys

    import numpy as np
    from PySide6.QtWidgets import QApplication

    from clipasso_studio.engine import aesthetic, jobs
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.widgets import edit_bar

    out = app_settings().get("output_dir")
    os.makedirs(out, exist_ok=True)
    job = _fake_job(out, "thumbs_job", str(tmp_path / "thumbs.png"), 30.0)
    run = os.path.join(job, "thumbs_job_run")
    studio = window.studio
    studio.show_job_dir(job)
    assert studio._editable_seed() is not None and not studio.up_btn.isChecked()
    toasts = []
    studio.toast.connect(lambda text, kind: toasts.append(text))
    # a sketch from before 3.4 has no embedding: a process makes it (here a stand-in), then the rating counts
    script = ("import sys, numpy as np; from clipasso_studio.engine import aesthetic, jobs; r = sys.argv[1]; "
              "v = np.ones(512, np.float32) / np.sqrt(512); aesthetic.save_embedding(r, jobs.sketch_file(r), v)")
    monkeypatch.setattr(edit_bar, "tool_command", lambda flag, r: (sys.executable, ["-c", script, r]))
    studio.up_btn.click()
    assert studio.up_btn.isChecked() and not studio.down_btn.isChecked()
    assert jobs.read_meta(job)["ratings"] == {"thumbs_job_run": 1}
    assert studio._embed_proc.waitForFinished(30000)
    for _ in range(50):
        QApplication.instance().processEvents()
        if aesthetic.counts() != (0, 0):
            break
    assert aesthetic.counts() == (1, 0) and toasts and "9" in toasts[-1]
    studio.down_btn.click()  # changed its mind: the embedding is there now
    assert studio.down_btn.isChecked() and not studio.up_btn.isChecked() and aesthetic.counts() == (0, 1)
    studio.down_btn.click()  # taken back
    assert not studio.down_btn.isChecked() and "ratings" not in jobs.read_meta(job) and aesthetic.counts() == (0, 0)
    studio.up_btn.click()
    settings = window.settings
    assert settings.refresh_taste() == (1, 0) and settings.taste_forget.isEnabled()
    assert settings.forget_taste(confirm=False) and settings.refresh_taste() == (0, 0)
    assert np.allclose(np.linalg.norm(aesthetic.read_embedding(run)), 1, atol=1e-5)


def test_phone_controls_the_studio(window, tmp_path, monkeypatch):
    """Every action of the phone page against the real studio (``gui/phone_api.py``; the server is in
    test_phone)."""
    import io
    import json

    import numpy as np
    from PIL import Image

    from clipasso_studio import settings_schema as schema
    from clipasso_studio.engine import details, jobs
    from clipasso_studio.gui import resources
    from clipasso_studio.gui.app_settings import app_settings

    studio = window.studio
    api = window.phone.api
    call = api.handle
    assert call("open_folder", {}) == {"ok": False, "error": "unknown action"}  # (only get_/file_/do_ actions)
    assert call("do_nothing", {}) == {"ok": False, "error": "unknown action"}
    # parameters of every method, without files on the computer
    for method in schema.METHODS:
        sc = call("get_schema", {"method": method})
        keys = [p["key"] for g in sc["groups"] for p in g["params"]]
        assert keys and "path_svg" not in keys and sc["presets"]
        assert all(p["label"] for g in sc["groups"] for p in g["params"])
        choice = next(p for g in sc["groups"] for p in g["params"] if p["kind"] == "choice")
        assert all(c["label"] for c in choice["choices"])
    # method, a setting, a preset, the budget
    assert call("do_method", {"method": "clipasso"})["ok"] and studio.params.method() == "clipasso"
    assert call("do_set", {"key": "num_iter", "value": "301"})["ok"] and studio.params.settings()["num_iter"] == 301
    assert call("do_set", {"key": "mask_object", "value": True})["ok"] and studio.params.settings()["mask_object"]
    assert call("do_set", {"key": "num_iter", "value": "many"})["ok"] is False
    assert call("do_set", {"key": "path_svg", "value": "/etc/passwd"})["ok"] is False
    assert call("do_preset", {"preset": "fast"})["ok"] and studio.params._preset == "fast"
    assert call("do_budget", {"minutes": 15})["ok"]
    # a sample picture from the computer, then the studio's state
    images = call("get_images", {})
    assert images["samples"] and call("do_image", {"src": "sample", "i": 0})["ok"] and studio.image_path
    assert call("do_image", {"src": "sample", "i": 99})["ok"] is False
    assert call("do_image", {"src": "/", "i": 0})["ok"] is False
    st = call("get_studio", {})
    assert st["method"] == "clipasso" and st["image"]["name"] and st["settings"]["num_iter"] > 0
    assert len(st["methods"]) == len(schema.METHODS) and "path_svg" not in st["settings"]
    assert st["enabled"]["frame_object"] is True and st["estimate"]
    jpg = call("file_input", {})
    assert jpg["_type"] == "image/jpeg" and jpg["_bytes"][:2] == b"\xff\xd8"
    assert call("file_image", {"src": "sample", "i": 0})["_bytes"][:2] == b"\xff\xd8"
    # the detail brush: painted on the phone at the size of the picture it got
    shown = Image.open(io.BytesIO(jpg["_bytes"]))
    grey = np.full((shown.height, shown.width), 128, np.uint8)
    grey[: shown.height // 2] = 255
    buf = io.BytesIO()
    Image.fromarray(grey).convert("RGB").save(buf, "PNG")
    assert call("set_details", {"png": buf.getvalue()})["ok"]
    full = details.detail_map(Image.open(studio.image_path).convert("RGB"))
    assert full is not None and full[:5].min() > 0.9 and abs(full[-5:]).max() < 0.05
    back = Image.open(io.BytesIO(call("file_details", {})["_bytes"]))
    assert back.size == shown.size and np.asarray(back)[2, 2] > 250
    assert call("get_studio", {})["details"]["has"]
    assert call("do_clear_details", {})["ok"] and not call("get_studio", {})["details"]["has"]
    # start: memory short -> the phone is asked; then started (or queued)
    queued = []
    monkeypatch.setattr(studio.controller, "enqueue", lambda target, settings, start=True: queued.append(
        (target, settings, start)))
    monkeypatch.setattr(studio.params, "missing_models", lambda: [])
    monkeypatch.setattr(resources, "shortage", lambda s: ("RAM 30 GB, free 8 GB", {"num_sketches": 1}))
    answer = call("do_start", {})
    assert answer["ok"] is False and answer["ask"]["text"].startswith("RAM") and answer["ask"]["smaller"]
    assert not queued
    assert call("do_start", {"memory": "smaller"})["ok"] and queued[-1][1]["num_sketches"] == 1
    assert call("do_start", {"memory": "anyway", "queue": True})["ok"] and len(queued) == 2
    monkeypatch.setattr(resources, "shortage", lambda s: None)
    monkeypatch.setattr(studio.params, "missing_models", lambda: ["clip:RN101"])
    assert "MB" in call("do_start", {})["error"]
    # a recent result: opened in the studio, its sketches, a thumb, the look, downloads
    out = app_settings().get("output_dir")
    os.makedirs(out, exist_ok=True)
    job = _fake_job(out, "phone_job", str(tmp_path / "phone.png"), 31.0)
    results = call("get_results", {})["results"]
    i = next(r["i"] for r in results if r["dir"] == os.path.basename(job))
    assert b"<svg" in call("file_result", {"i": i})["_bytes"]
    from clipasso_studio.engine import aesthetic

    run = os.path.join(job, "phone_job_run")
    aesthetic.save_embedding(run, os.path.join(run, "best_iter.svg"), np.ones(512, np.float32) / np.sqrt(512))
    assert call("do_open", {"i": i})["ok"] and os.path.normpath(studio.view_dir) == os.path.normpath(job)
    st = call("get_studio", {})
    assert st["seeds"] and st["shown"] is not None and st["can_rate"] and st["view"] == "phone_job"
    assert call("do_select", {"seed": st["seeds"][0]["seed"]})["ok"]
    assert call("do_select", {"seed": 123456})["ok"] is False
    assert call("do_rate", {"value": 1})["ok"] and call("get_studio", {})["rating"] == 1
    assert call("do_rate", {"value": 5})["ok"] is False
    assert call("do_style", {"style": "pencil", "paper": "kraft"})["ok"]
    assert app_settings().get("canvas_style") == "pencil" and app_settings().get("canvas_paper") == "kraft"
    svg = call("file_sketch", {"full": "1"})
    assert svg["_type"] == "image/svg+xml" and b"<svg" in svg["_bytes"] and b"data:image/jpeg" in svg["_bytes"]
    png = call("file_download", {"fmt": "png", "size": "256"})
    assert png["_bytes"][:4] == b"\x89PNG" and png["_name"].endswith(".png")
    assert call("file_download", {"fmt": "svg"})["_name"].endswith(".svg")
    call("do_style", {"style": "plain", "paper": "none"})
    # the queue
    q = call("get_queue", {})
    assert isinstance(q["jobs"], list)
    assert call("do_remove", {"id": "x"})["ok"] is False
    assert jobs.read_meta(job)["ratings"]
    json.dumps(call("get_studio", {}))  # (all of it goes to the phone as JSON)


def test_phone_back_to_the_running_job_and_clean_queue(window, tmp_path, monkeypatch):
    """3.4.1: from a result of the gallery back to the running job; finished jobs leave the queue."""
    from PIL import Image

    from clipasso_studio import settings_schema as schema
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.controller import QueuedJob

    studio, c = window.studio, window.controller
    call = window.phone.api.handle
    assert call("do_live", {})["ok"] is False  # nothing runs
    image = str(tmp_path / "running.png")
    Image.new("RGB", (32, 32), "white").save(image)
    job = QueuedJob(image, schema.default_settings("clipasso"), status="running")
    job.seed_progress = {s: 0.5 for s in job.seeds}
    saved_jobs, saved_current = list(c.jobs), c.current
    monkeypatch.setattr(c, "is_busy", lambda: True)
    c.current = job
    try:
        out = app_settings().get("output_dir")
        os.makedirs(out, exist_ok=True)
        other = _fake_job(out, "gallery_job", str(tmp_path / "other.png"), 30.0)
        studio.show_job_dir(other)  # a result of the gallery is shown during the run
        st = call("get_studio", {})
        assert st["busy"] and not st["running_here"] and st["running"]["name"] == "running.png"
        assert st["running"]["progress"] == 0.5
        assert call("do_live", {})["ok"] and studio.view_job is job
        assert call("get_studio", {})["running_here"]
        # the queue: the finished, cancelled and failed ones go, the waiting ones stay
        c.jobs = [job] + [QueuedJob(image, schema.default_settings("clipasso"), status=s)
                          for s in ("done", "cancelled", "failed", "queued")]
        assert call("do_clear_queue", {}) == {"ok": True, "removed": 3}
        assert [j.status for j in c.jobs] == ["running", "queued"]
        assert [j["status"] for j in call("get_queue", {})["jobs"]] == ["running", "queued"]
    finally:
        c.current, c.jobs = saved_current, saved_jobs


def test_phone_deletes_gallery_results(window, tmp_path, monkeypatch):
    """3.4.1: a result of the gallery deleted from the phone (to the recycle bin, the gallery's way)."""
    from clipasso_studio.gui.app_settings import app_settings

    call = window.phone.api.handle
    out = app_settings().get("output_dir")
    os.makedirs(out, exist_ok=True)
    job = _fake_job(out, "to_delete_job", str(tmp_path / "del.png"), 29.0)
    results = call("get_results", {})["results"]
    r = next(x for x in results if x["dir"] == os.path.basename(job))
    other = next(x for x in results if x["dir"] != r["dir"]) if len(results) > 1 else None
    if other is not None:  # the list changed meanwhile: never another result
        assert call("do_delete", {"i": r["i"], "dir": other["dir"]})["ok"] is False and os.path.isdir(job)
    window.studio.show_job_dir(job)
    monkeypatch.setattr(window.controller, "active_dirs", lambda: {os.path.normcase(os.path.abspath(job))})
    answer = call("do_delete", {"i": r["i"], "dir": r["dir"]})
    assert answer["ok"] is False and "to_delete_job" in answer["error"] and os.path.isdir(job)  # the queue needs it
    monkeypatch.setattr(window.controller, "active_dirs", lambda: set())
    deleted = []
    window.gallery.job_deleted.connect(deleted.append)
    assert call("do_delete", {"i": r["i"], "dir": r["dir"]}) == {"ok": True}
    assert not os.path.exists(job) and deleted == [job]
    assert window.studio.view_dir == ""  # the studio no longer shows it
    assert all(x["dir"] != r["dir"] for x in call("get_results", {})["results"])


def test_phone_exports_every_format(window, tmp_path):
    """3.4.2: the exports of the studio's dialog from the phone – the options checked, the export in the background,
    the file sent from the disk; only the last few stay."""
    import json
    import time

    from PIL import Image
    from PySide6.QtWidgets import QApplication

    from clipasso_studio.gui import export_jobs
    from clipasso_studio.gui.app_settings import app_settings

    api = window.phone.api
    call = api.handle
    out = app_settings().get("output_dir")
    os.makedirs(out, exist_ok=True)
    job = _fake_job(out, "export_job", str(tmp_path / "exp.png"), 28.0)
    window.studio.show_job_dir(job)
    info = call("get_export_info", {})
    fmts = {f["fmt"]: f for f in info["formats"]}
    assert set(fmts) == set(export_jobs.FORMATS) - {"matrix", "svglayers"}  # (those only for SceneSketch)
    assert fmts["png"]["applies"]["transparent"] and not fmts["gif"]["applies"]["transparent"]
    assert not fmts["gif"]["applies"]["mode"] and fmts["gif"]["defaults"]["mode"] == "strokes"  # (no saved steps)
    assert all(f["desc"] and f["title"] for f in fmts.values())
    assert info["styles"] and info["papers"] and info["frames"] and info["name"] == "export_job_run"
    json.dumps(info)

    def export(fmt, options):
        a = call("do_export", {"fmt": fmt, "options": options})
        assert a["ok"], a
        end = time.time() + 60
        while call("get_export", {"id": a["id"]})["status"] == "running" and time.time() < end:
            QApplication.processEvents()
            time.sleep(0.02)
        return a["id"], call("get_export", {"id": a["id"]})

    eid, st = export("png", {"background": "transparent", "size": 128, "stroke": "#ff0000", "width": 2})
    assert st["status"] == "done" and st["name"] == "export_job_run.png" and st["size"] > 0
    f = call("file_export", {"id": eid})
    assert f["_type"] == "image/png" and f["_name"] == "export_job_run.png"
    im = Image.open(f["_path"])
    assert im.mode == "RGBA" and im.size == (128, 128) and im.getpixel((0, 0))[3] == 0  # no background
    assert app_settings().get("export_background") == "transparent"  # (remembered for the dialog, too)
    assert app_settings().get("export_last_format") == "png"
    eid, st = export("gif", {"length": 0.5, "hold": 0, "size": 64})
    assert st["status"] == "done" and Image.open(call("file_export", {"id": eid})["_path"]).format == "GIF"
    for fmt in ("svg", "svg1", "pdf", "svganim", "lottie", "html"):
        eid, st = export(fmt, {})
        assert st["status"] == "done", (fmt, st)
        assert call("file_export", {"id": eid})["_name"].endswith("." + export_jobs.extension(fmt))
    # cancelled: no file
    a = call("do_export", {"fmt": "gif", "options": {"length": 120, "size": 1024}})
    assert call("do_cancel_export", {"id": a["id"]})["ok"]
    end = time.time() + 60
    while call("get_export", {"id": a["id"]})["status"] == "running" and time.time() < end:
        QApplication.processEvents()
        time.sleep(0.02)
    assert call("get_export", {"id": a["id"]})["status"] == "cancelled"
    assert call("file_export", {"id": a["id"]})["ok"] is False
    # wrong requests
    assert call("do_export", {"fmt": "exe"})["ok"] is False
    assert call("get_export", {"id": "nope"})["ok"] is False and call("file_export", {"id": "nope"})["ok"] is False
    assert len(os.listdir(api.export_root())) <= 4  # (the last three and the newest)


def test_own_presets_in_studio_and_phone(window, monkeypatch, tmp_path):
    """3.4.2: own presets – saved in the studio (name asked) or from the phone, chosen from either, deleted."""
    from PySide6.QtWidgets import QInputDialog

    from clipasso_studio.gui import user_presets
    from clipasso_studio.gui.app_settings import app_settings

    p = window.studio.params
    call = window.phone.api.handle
    app_settings().data["user_presets"] = []
    p.set_method("clipasso")
    p.fields["num_iter"].set_value(777, emit=True)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("  Mein   Preset ", True))
    assert p.save_user_preset() == "Mein Preset" and p.user_preset() == "Mein Preset"
    assert "Mein Preset" in p.preset_hint.text() or p._preset != "custom"
    p.fields["num_iter"].set_value(500, emit=True)
    assert p.user_preset() == ""
    p._build_user_menu()
    assert "Mein Preset" in [a.text() for a in p.user_menu.actions()]
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("", False))
    assert p.save_user_preset() == ""  # (cancelled)
    # from the phone: listed, chosen (it switches the method back), saved, deleted
    st = call("get_studio", {})
    assert st["user_presets"] == [{"name": "Mein Preset", "method": "clipasso", "method_name": "CLIPasso"}]
    assert call("do_method", {"method": "swiftsketch"})["ok"]
    assert call("do_user_preset", {"name": "Mein Preset", "method": "clipasso"})["ok"]
    assert p.method() == "clipasso" and p.settings()["num_iter"] == 777
    assert call("get_studio", {})["user_preset"] == "Mein Preset"
    assert call("do_user_preset", {"name": "Gibt es nicht", "method": "clipasso"})["ok"] is False
    # a start SVG (a file of this computer) stays when a preset of the same method is chosen
    start = tmp_path / "start.svg"
    start.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    p.set_settings({**p.settings(), "path_svg": str(start)})
    assert p.apply_user_preset("Mein Preset") and p.settings()["path_svg"] == str(start)
    p.set_settings({**p.settings(), "path_svg": "none"})
    p.fields["num_iter"].set_value(900, emit=True)
    assert call("do_save_preset", {"name": "Vom Handy"}) == {"ok": True, "name": "Vom Handy"}
    assert [x["name"] for x in user_presets.all_presets()] == ["Mein Preset", "Vom Handy"]
    assert call("get_studio", {})["user_preset"] == "Vom Handy"
    assert call("do_save_preset", {"name": "   "})["ok"] is False
    assert call("do_delete_preset", {"name": "Vom Handy", "method": "clipasso"})["ok"]
    assert call("do_delete_preset", {"name": "Vom Handy", "method": "clipasso"})["ok"] is False
    assert call("get_studio", {})["user_preset"] == ""
    assert p.delete_user_preset("Mein Preset") and user_presets.all_presets() == []


def test_scenesketch_views_and_layers(window, tmp_path):
    """3.5: a SceneSketch job – the matrix with its axes, the layer switch, the attention map from the background's
    run, the layered export; on the phone the matrix, the background photo and the layers."""
    import io

    from PIL import Image

    from clipasso_studio.gui.app_settings import app_settings
    from tests.helpers import SCENE_BG, SCENE_OBJ, fake_scene_job

    studio = window.studio
    call = window.phone.api.handle
    out = app_settings().get("output_dir")
    os.makedirs(out, exist_ok=True)
    job = fake_scene_job(out, "scene_gui_job", str(tmp_path / "scene.png"))
    studio.show_job_dir(job)
    assert studio.view_method == "scenesketch" and studio.scene_layout == ([8], 1)
    assert studio.best_seed == 800 and 800 in studio.seed_attn  # (from runs/background_l8/seed0)
    studio.modes.set_current("matrix")
    studio.matrix.resize(500, 500)
    assert not studio.matrix.grab().isNull()  # (the axis titles are drawn without an error)
    studio.modes.set_current("sketch")
    assert studio.layer_btn.isVisibleTo(studio) and studio.layer_btn.isEnabled()
    assert studio.export_btns["svglayers"].isVisibleTo(studio) and studio.export_btns["svglayers"].isEnabled()
    studio.set_layer_part("object")
    assert studio._shown_svg(800).count("<path") == len(SCENE_OBJ)
    studio.eraser_btn.setChecked(True)  # the eraser works on the whole sketch
    assert studio.layer_part == "all"
    studio.eraser_btn.setChecked(False)
    # the phone
    st = call("get_studio", {})
    sc = st["scene"]
    assert sc["layers"] == [8] and sc["levels"] == 1 and sc["background"] and sc["layered"]
    assert [c["seed"] for c in sc["cells"]] == [800, 801] and all(c["has"] for c in sc["cells"])
    assert next(c for c in sc["cells"] if c["best"])["seed"] == 800
    jpg = call("file_background", {})
    assert jpg["_type"] == "image/jpeg" and Image.open(io.BytesIO(jpg["_bytes"])).size[0] > 0
    obj = call("file_sketch", {"seed": "800", "part": "object"})["_bytes"].decode()
    bg = call("file_sketch", {"seed": "800", "part": "background"})["_bytes"].decode()
    assert obj.count("<path") == len(SCENE_OBJ) and bg.count("<path") == len(SCENE_BG)
    fmts = [f["fmt"] for f in call("get_export_info", {})["formats"]]
    assert "svglayers" in fmts and "matrix" in fmts
    # another method: no SceneSketch block, no layer switch
    other = fake_job(out, "plain_gui_job", str(tmp_path / "plain.png"), 30.0)
    studio.show_job_dir(other)
    assert call("get_studio", {})["scene"] is None and not studio.layer_btn.isVisibleTo(studio)
    assert "svglayers" not in [f["fmt"] for f in call("get_export_info", {})["formats"]]
    assert call("do_export", {"fmt": "svglayers"})["ok"] is False
    assert call("file_background", {})["ok"] is False


def test_phone_gallery_queue_compare_download_crop(window, tmp_path, monkeypatch):
    """3.5: the phone's gallery (all results, search, filters, favourites), queue (move, again), compare, model
    downloads, crop and the mask."""
    import io
    import time

    from PIL import Image
    from PySide6.QtWidgets import QApplication

    from clipasso_studio import settings_schema as schema
    from clipasso_studio.engine import jobs, model_store
    from clipasso_studio.gui import methods_ui
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.controller import QueuedJob

    studio, c = window.studio, window.controller
    api = window.phone.api
    call = api.handle
    out = app_settings().get("output_dir")
    os.makedirs(out, exist_ok=True)
    a = fake_job(out, "phone_gal_alpha", str(tmp_path / "alpha.png"), 25.0, method="clipasso",
                 created="2026-10-01 10:00:00")
    fake_job(out, "phone_gal_beta", str(tmp_path / "beta.png"), 26.0, created="2026-10-01 11:00:00")
    jobs.write_meta(a, notes="ein Hund am Strand", tags=["tier"], albums=["Urlaub"])
    # search (name, notes, tags), filters, pages
    found = call("get_results", {"q": "strand"})
    assert [r["dir"] for r in found["results"]] == ["phone_gal_alpha"] and found["total"] == 1
    assert call("get_results", {"q": "TIER"})["total"] == 1
    assert call("get_results", {"album": "Urlaub"})["results"][0]["dir"] == "phone_gal_alpha"
    assert "Urlaub" in found["albums"] and {m["key"] for m in found["methods"]} == set(schema.METHODS)
    clip = call("get_results", {"method": "clipasso"})["results"]
    assert all(r["method_key"] == "clipasso" for r in clip) and any(r["dir"] == "phone_gal_alpha" for r in clip)
    total = call("get_results", {})["total"]
    page2 = call("get_results", {"offset": 1, "limit": 1})
    assert page2["total"] == total and len(page2["results"]) == 1 and page2["results"][0]["i"] == 1
    # a favourite, by folder name; the result itself by folder name
    assert call("do_fav", {"dir": "phone_gal_beta", "value": True})["ok"]
    assert jobs.read_meta(os.path.join(out, "phone_gal_beta"))["favourite"]
    assert [r["dir"] for r in call("get_results", {"fav": "1"})["results"]] == ["phone_gal_beta"]
    assert b"<svg" in call("file_result", {"d": "phone_gal_alpha"})["_bytes"]
    assert call("do_open", {"dir": "phone_gal_alpha"})["ok"] and studio.view_dir.endswith("phone_gal_alpha")
    assert call("do_fav", {"dir": "gone"})["ok"] is False
    # the queue: a waiting job to the top, a failed one again
    image = str(tmp_path / "q.png")
    Image.new("RGB", (32, 32), "white").save(image)
    saved = list(c.jobs)
    try:
        q = [QueuedJob(image, schema.default_settings("clipasso"), status=st) for st in ("queued", "queued", "failed")]
        c.jobs = list(q)
        monkeypatch.setattr(c, "start_next", lambda: None)
        assert call("do_move", {"id": q[1].id, "index": 0})["ok"] and c.jobs[0] is q[1]
        assert call("do_move", {"id": q[2].id, "index": 0})["ok"] is False  # (only waiting jobs move)
        assert call("do_retry", {"id": q[2].id})["ok"] and q[2].status == "queued"
        assert call("do_retry", {"id": q[2].id})["ok"] is False
        assert call("do_move", {"id": 999999, "index": 0})["ok"] is False
    finally:
        c.jobs = saved
    # compare: missing models, the questions of a computer without GPU, then queued
    studio.set_image(image)
    queued = []
    monkeypatch.setattr(c, "enqueue", lambda target, settings, start=True: queued.append(settings["method"]))
    monkeypatch.setattr(methods_ui, "missing_models", lambda s: ["clip:RN50"] if s["method"] == "swiftsketch" else [])
    monkeypatch.setattr(methods_ui, "has_cuda", lambda: False)
    answer = call("do_compare", {"methods": ["swiftsketch", "clipasso"]})
    assert answer["ok"] is False and answer["missing"] == ["clip:RN50"]
    answer = call("do_compare", {"methods": ["clipasso", "controlsketch", "scenesketch"]})
    assert answer["ok"] is False and {q["key"] for q in answer["asks"]} == {"controlsketch_cpu", "scene_fast"}
    answer = call("do_compare", {"methods": ["clipasso", "controlsketch", "scenesketch"], "controlsketch_cpu": False,
                                 "scene_fast": True})
    assert answer == {"ok": True, "queued": 2} and queued == ["clipasso", "scenesketch"]
    assert call("do_compare", {"methods": []})["ok"] is False
    overview = call("get_compare", {})
    assert overview["ok"] and [m["key"] for m in overview["methods"]] == list(schema.METHODS)
    # models downloaded on the phone's request (one after the other, with progress)
    installed = []

    def install(key, progress=None, cancel=None):
        progress(5, 10)
        installed.append(key)
        return key

    monkeypatch.setattr(model_store, "install", install)
    monkeypatch.setattr(model_store, "is_available", lambda k: k in installed)
    assert call("do_download_models", {"keys": ["clip:RN50", "nonsense"]})["ok"]
    end = time.time() + 20
    while (call("get_studio", {})["download"] or {}).get("status") == "running" and time.time() < end:
        QApplication.processEvents()
        time.sleep(0.02)
    assert call("get_studio", {})["download"]["status"] == "done" and installed == ["clip:RN50"]
    assert call("do_download_models", {"keys": ["clip:RN50"]})["ok"] is False  # (nothing missing any more)
    # crop: turned a quarter, the left half kept -> a new picture of half the turned width
    Image.new("RGB", (80, 40), "white").save(image)
    studio.set_image(image)
    assert call("do_crop", {"rotate": 90, "x": 0, "y": 0, "w": 0.5, "h": 1})["ok"]
    assert "-edited-" in studio.image_path and Image.open(studio.image_path).size == (20, 80)
    assert call("do_crop", {"rotate": 45})["ok"] is False and call("do_crop", {"w": 0.01, "h": 0.01})["ok"] is False
    # the mask: on the phone once the studio has it (the background veiled, the object outlined)
    import numpy as np

    from clipasso_studio.gui import mask_view

    monkeypatch.setattr(studio, "_mask_settings", lambda: (True, "u2net", {}))
    monkeypatch.setattr(studio, "_mask", None)
    assert call("get_studio", {})["mask"]["ready"] is False and call("file_mask", {})["ok"] is False
    prob = np.zeros((80, 20), np.float32)
    prob[20:60, 5:15] = 1.0
    monkeypatch.setattr(studio, "_mask", {"key": (studio.image_path, "u2net"), "prob": prob, "edited": False})
    monkeypatch.setattr(mask_view, "load_mask", lambda path, model: (None, prob, None))
    assert call("get_studio", {})["mask"]["ready"]
    jpg = call("file_mask", {})
    assert jpg["_type"] == "image/jpeg" and Image.open(io.BytesIO(jpg["_bytes"])).size == (20, 80)
