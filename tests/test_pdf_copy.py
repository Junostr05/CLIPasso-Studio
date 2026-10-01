"""PDF export and copying a sketch to the clipboard."""

import os
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="224" height="112" viewBox="0 0 224 112">'
       '<path d="M 10 10 C 60 100 120 100 200 100" stroke="black" stroke-width="2" fill="none"/></svg>')


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def own_settings(tmp_path, monkeypatch):
    from clipasso_studio.gui import app_settings as settings_module

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    settings_module._instance = None
    yield
    settings_module._instance = None


def test_pdf_is_vector_with_the_sketch_shape(qapp, tmp_path):
    from clipasso_studio.gui import export

    src = tmp_path / "s.svg"
    src.write_text(SVG)
    dest = tmp_path / "s.pdf"
    export.export_pdf(str(src), str(dest), width_cm=20, background="#fff0e0", style="pencil")
    data = dest.read_bytes()
    assert data.startswith(b"%PDF")
    assert b"/Subtype /Image" not in data  # vector, no embedded raster
    box = [float(v) for v in re.search(rb"/MediaBox \[([^\]]+)\]", data).group(1).split()]
    assert abs(box[2] - 200 / 25.4 * 72) < 2 and abs(box[3] - box[2] / 2) < 2  # 20 cm wide, 2:1 like the sketch


def test_batch_export_pdf(qapp, tmp_path):
    import json

    from clipasso_studio.gui import export

    job = tmp_path / "job"
    run = job / "run"
    run.mkdir(parents=True)
    (run / "best_iter.svg").write_text(SVG)
    summary = {"target": "cat.png", "method": "clipasso", "best_svg": str(run / "best_iter.svg"),
               "runs": [{"seed": 0, "run_dir": str(run), "best_svg": str(run / "best_iter.svg")}]}
    (job / "job.json").write_text(json.dumps(summary))
    assert export.export_batch([(str(job), summary)], str(tmp_path / "out"), "pdf") == 1
    assert (tmp_path / "out" / "cat_clipasso.pdf").read_bytes().startswith(b"%PDF")


def test_clipboard_has_image_and_svg(qapp, tmp_path, own_settings):
    from PySide6.QtGui import QGuiApplication

    from clipasso_studio.gui import dialogs, export
    from clipasso_studio.gui.app_settings import app_settings

    src = tmp_path / "s.svg"
    src.write_text(SVG)
    data = export.sketch_mime(str(src), 256, "#123456", 1.0, "#ffffff", "plain")
    assert data.hasImage() and "image/svg+xml" in data.formats() and not data.hasText()
    assert "#123456" in bytes(data.data("image/svg+xml")).decode()
    app_settings().set("export_stroke", "#aa0000")
    app_settings().set("export_background", "transparent")  # pasted as white
    dialogs.copy_sketch(str(src))
    clip = QGuiApplication.clipboard().mimeData()
    svg = bytes(clip.data("image/svg+xml")).decode()
    assert "#aa0000" in svg and 'fill="#FFFFFF"' in svg
    img = clip.imageData()
    assert img.width() == 1024 and img.pixelColor(2, 2).name() == "#ffffff"


def test_studio_copy_and_pdf_button(qapp, tmp_path, own_settings):
    from PySide6.QtGui import QGuiApplication

    from clipasso_studio.gui.controller import JobController
    from clipasso_studio.gui.pages.studio import StudioPage

    run = tmp_path / "run"
    run.mkdir()
    (run / "best_iter.svg").write_text(SVG)
    page = StudioPage(JobController())
    assert not page.copy_sketch()  # nothing shown yet
    page.seed_runs = {0: str(run)}
    page.best_seed = 0
    toasts = []
    page.toast.connect(lambda text, kind: toasts.append(kind))
    assert page.copy_sketch() and toasts == ["success"]
    assert QGuiApplication.clipboard().mimeData().hasImage()
    assert "pdf" in page.export_btns and "Ctrl+C" in page.export_btns["copy"].text().replace("⌘", "Ctrl+")
    page.shutdown()
