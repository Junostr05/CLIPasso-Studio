"""Folder import into the queue and batch export (queue, gallery)."""

import json
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="224" height="224" viewBox="0 0 224 224">'
       '<path d="M 10 10 C 60 60 120 60 200 200" stroke="rgb(0, 0, 0)" stroke-width="3" fill="none"/></svg>')


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

    settings_module._instance = None
    app_settings().data["output_dir"] = str(tmp / "out")
    theme.apply(app, "dark")
    from clipasso_studio.gui.main_window import MainWindow

    w = MainWindow()
    w.controller.start_next = lambda: None  # queue only, no sketching in these tests
    w.show()
    yield w
    w.controller.shutdown()
    w.close()
    env.undo()


def _job(out, name, method="swiftsketch", edited=False):
    job = os.path.join(out, f"{name}_{method}_x")
    run = os.path.join(job, "run")
    os.makedirs(run)
    for p in (os.path.join(run, "best_iter.svg"), os.path.join(job, "run_best.svg")):
        with open(p, "w") as f:
            f.write(SVG)
    if edited:
        with open(os.path.join(run, "edited.svg"), "w") as f:
            f.write(SVG.replace("rgb(0, 0, 0)", "rgb(0, 0, 255)"))
    summary = {"target": f"/photos/{name}.jpg", "created": "2026-10-01 10:00:00", "settings": {"method": method},
               "method": method, "best_svg": os.path.join(job, "run_best.svg"), "best_run": "run", "clip_score": 80.0,
               "runs": [{"seed": 0, "run_name": "run", "run_dir": run, "best_svg": os.path.join(run, "best_iter.svg")}]}
    with open(os.path.join(job, "job.json"), "w") as f:
        json.dump(summary, f)
    return job, summary


def test_image_files_skips_result_folders(tmp_path):
    from PIL import Image

    from clipasso_studio.gui.pages.other_pages import image_files

    for rel in ("b.png", "a.JPG", "notes.txt", "sub/c.webp", "sub/job/d.png", "_edited/e.png"):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if rel.endswith("txt"):
            path.write_text("x")
        else:
            Image.new("RGB", (8, 8)).save(path, format="PNG")
    (tmp_path / "sub" / "job" / "job.json").write_text("{}")
    names = lambda paths: [os.path.relpath(p, tmp_path) for p in paths]  # noqa: E731
    assert names(image_files(str(tmp_path))) == ["a.JPG", "b.png"]
    assert names(image_files(str(tmp_path), recursive=True)) == ["a.JPG", "b.png", os.path.join("sub", "c.webp")]


def test_export_batch(tmp_path, window):
    from PIL import Image

    from clipasso_studio.gui import export

    items = [_job(str(tmp_path / "jobs"), "rose"), _job(str(tmp_path / "jobs"), "rose", "clipasso"),
             _job(str(tmp_path / "jobs2"), "rose", edited=True)]
    out = tmp_path / "out"
    assert export.export_batch(items, str(out), fmt="svg", style="ink") == 3
    files = sorted(os.listdir(out))
    assert files == ["rose_clipasso.svg", "rose_swiftsketch.svg", "rose_swiftsketch_2.svg"]
    assert "rgb(0, 0, 255)" in (out / "rose_swiftsketch_2.svg").read_text()  # the touched-up sketch
    assert 'stroke="none"' in (out / "rose_clipasso.svg").read_text()  # ink style
    assert export.export_batch(items[:1], str(out), fmt="png", size=96) == 1
    assert Image.open(out / "rose_swiftsketch.png").size == (96, 96)
    assert export.export_batch(items[:1], str(out), fmt="svg1") == 1
    assert (out / "rose_swiftsketch_1layer.svg").is_file()


def test_batch_dialog_queue_and_gallery(window, tmp_path, monkeypatch):
    from PIL import Image
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

    from clipasso_studio.gui import dialogs
    from clipasso_studio.gui.app_settings import app_settings

    # dialog: exports in the background, then accepted
    items = [_job(str(tmp_path / "a"), "crab"), _job(str(tmp_path / "b"), "horse")]
    dlg = dialogs.BatchExportDialog(items)
    dlg.format.setCurrentIndex(2)  # PNG
    dlg.size.setValue(64)
    dlg.start(str(tmp_path / "export"))
    end = time.time() + 20
    while dlg.result() != QDialog.Accepted and time.time() < end:
        QApplication.processEvents()
        time.sleep(0.01)
    assert dlg.written == 2 and sorted(os.listdir(tmp_path / "export")) == ["crab_swiftsketch.png",
                                                                           "horse_swiftsketch.png"]
    # queue: a folder of images is added with the studio settings
    photos = tmp_path / "photos"
    photos.mkdir()
    for n in ("one.png", "two.png"):
        Image.new("RGB", (16, 16)).save(photos / n)
    queue = window.queue
    before = len(window.controller.jobs)
    assert queue.add_folder(str(photos)) == 2
    assert [os.path.basename(j.target) for j in window.controller.jobs[before:]] == ["one.png", "two.png"]
    for j in list(window.controller.jobs[before:]):
        window.controller.remove(j.id)
    # gallery: "Export shown" exports what the filters show
    out = app_settings().get("output_dir")
    _job(out, "rose", "clipasso")
    _job(out, "tulip")
    window.gallery.refresh()
    assert len(window.gallery.shown_items()) == 2
    window.gallery.filter.set_current("clipasso")
    window.gallery.refresh()
    assert [s["method"] for _, s in window.gallery.shown_items()] == ["clipasso"]
    exported = []
    monkeypatch.setattr(dialogs, "export_many", lambda parent, items: exported.append(items))
    window.gallery.export_btn.click()
    assert len(exported[0]) == 1
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    window.gallery.filter.set_current("all")
