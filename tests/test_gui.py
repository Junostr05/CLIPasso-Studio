import os

import pytest


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
    assert m._geometry()[4] and m._geometry()[2] > 100
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


def _fake_job(out, name, target, clip, method="swiftsketch", created="2026-09-29 12:00:00"):
    import json

    from PIL import Image

    from clipasso_studio import settings_schema as schema
    from clipasso_studio.engine import jobs

    job = os.path.join(out, name)
    run = os.path.join(job, f"{name}_run")
    os.makedirs(os.path.join(run, "svg_logs"))
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="224" height="224"><path d="M 10 10 C 20 20 30 30 40 40" ' \
          'stroke="rgb(0,0,0)" stroke-width="2" fill="none"/></svg>'
    for p in (os.path.join(run, "best_iter.svg"), os.path.join(job, f"{name}_run_best.svg")):
        with open(p, "w") as f:
            f.write(svg)
    if not os.path.isfile(target):
        Image.new("RGB", (30, 20), "white").save(target)
    jobs.save_input(job, target)
    summary = {"target": target, "created": created, "settings": schema.default_settings(method), "method": method,
               "clip_score": clip, "best_svg": os.path.join(job, f"{name}_run_best.svg"), "best_run": f"{name}_run",
               "runs": [{"seed": 0, "run_name": f"{name}_run", "run_dir": run, "best_loss": 0.2, "best_iter": 0,
                         "iterations_done": 1, "best_svg": os.path.join(run, "best_iter.svg"), "status": "done",
                         "method": method, "clip_score": clip, "seconds": 1.0}]}
    with open(os.path.join(job, "job.json"), "w") as f:
        json.dump(summary, f)
    return job


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
