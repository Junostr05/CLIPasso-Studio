"""More inputs: HEIC / AVIF / TIFF / GIF photos, EXIF rotation, recent images, webcam."""

import os

import pytest

DATA = os.path.join(os.path.dirname(__file__), "data")
pi_heif = pytest.importorskip("pi_heif")


def _avif(path, size=(50, 30)):
    from PIL import Image

    Image.new("RGB", size, "red").save(path, format="AVIF")


def test_engine_reads_the_new_formats(tmp_path):
    from PIL import Image

    from clipasso_studio.engine.imaging import load_rgb

    assert load_rgb(os.path.join(DATA, "sample.heic")).size == (64, 48)
    _avif(tmp_path / "x.avif")
    assert load_rgb(str(tmp_path / "x.avif")).size == (50, 30)
    frames = [Image.new("RGB", (20, 10), c) for c in ("blue", "green")]
    frames[0].save(tmp_path / "anim.gif", save_all=True, append_images=frames[1:])
    first = load_rgb(str(tmp_path / "anim.gif"))
    assert first.size == (20, 10) and first.getpixel((5, 5))[2] > 200  # the first frame
    Image.new("RGB", (30, 20), "white").save(tmp_path / "x.tiff")
    assert load_rgb(str(tmp_path / "x.tiff")).size == (30, 20)


def test_exif_rotation_like_the_preview(tmp_path, qapp):
    from PIL import Image

    from clipasso_studio.engine import framing
    from clipasso_studio.engine.imaging import load_rgb
    from clipasso_studio.gui import image_io

    im = Image.new("RGB", (60, 20), "white")
    exif = im.getexif()
    exif[0x0112] = 6  # rotate 90° when shown
    im.save(tmp_path / "phone.jpg", exif=exif)
    path = str(tmp_path / "phone.jpg")
    assert load_rgb(path).size == (20, 60)
    assert image_io.read_image(path).size().toTuple() == (20, 60)
    assert image_io.image_size(path).toTuple() == (20, 60)
    assert framing.photo_size(path) == (20, 60)


def test_gui_reads_heic_and_avif(tmp_path, qapp):
    from clipasso_studio.gui import image_io, thumbs
    from clipasso_studio.gui.drop import IMAGE_EXT, image_files
    from clipasso_studio.gui.widgets.canvas import IMAGE_FILTER, load_pixmap

    heic = os.path.join(DATA, "sample.heic")
    img = image_io.read_image(heic, 32)
    assert not img.isNull() and max(img.width(), img.height()) == 32
    assert image_io.image_size(heic).toTuple() == (64, 48)
    _avif(tmp_path / "x.avif")
    assert not load_pixmap(str(tmp_path / "x.avif"), 100).isNull()
    assert not thumbs.thumbnail(heic, 20).isNull()
    for ext in (".heic", ".heif", ".avif", ".gif", ".tif"):
        assert ext in IMAGE_EXT and f"*{ext}" in IMAGE_FILTER
    (tmp_path / "a.heic").write_bytes(open(heic, "rb").read())
    assert sorted(os.path.basename(p) for p in image_files(str(tmp_path))) == ["a.heic", "x.avif"]
    assert image_io.read_image(str(tmp_path / "missing.heic")).isNull()


def test_recent_images(qapp, tmp_path, user_data, monkeypatch):
    from PIL import Image

    from clipasso_studio import paths
    from clipasso_studio.gui import app_settings as settings_module
    from clipasso_studio.gui.app_settings import app_settings
    from clipasso_studio.gui.controller import JobController
    from clipasso_studio.gui.pages.studio import StudioPage

    settings_module._instance = None
    app_settings().data["output_dir"] = str(tmp_path / "out")
    controller = JobController()
    studio = StudioPage(controller)
    try:
        imgs = []
        for i in range(14):
            p = tmp_path / f"img{i}.png"
            Image.new("RGB", (10, 10), "white").save(p)
            imgs.append(str(p))
            studio.set_image(str(p))
        studio.set_image(str(paths.resource("samples", "camel.png")))  # samples are not "recent"
        studio.set_image(imgs[5])  # again: to the top, not twice
        recent = app_settings().get("recent_images")
        assert recent[0] == imgs[5] and len(recent) == studio.RECENT_MAX and recent.count(imgs[5]) == 1
        os.remove(imgs[13])
        studio._build_recent_menu()
        names = [a.text() for a in studio.recent_menu.actions()]
        assert names[0] == "img5.png" and "img13.png" not in names and imgs[13] not in app_settings().get(
            "recent_images")
        studio.recent_menu.actions()[1].trigger()
        assert studio.image_path == imgs[12]  # (img13 is gone)
    finally:
        studio.shutdown()
        controller.shutdown()
        settings_module._instance = None


def test_webcam_dialog_without_camera_and_taking_a_photo(qapp, tmp_path, user_data, monkeypatch):
    from PySide6.QtGui import QColor, QImage

    from clipasso_studio.gui import dialogs

    available, why = dialogs.webcam_available()
    dlg = dialogs.WebcamDialog(str(tmp_path / "_webcam"))
    if not available:
        assert not dlg.shoot.isEnabled() and dlg.view.text() == dialogs.tr(why)
    img = QImage(64, 48, QImage.Format_RGB32)
    img.fill(QColor("white"))
    img.setPixelColor(1, 1, QColor("black"))
    dlg.mirror.setChecked(True)
    dlg.show_image(img)
    assert dlg.take() and os.path.isfile(dlg.path) and os.path.dirname(dlg.path) == str(tmp_path / "_webcam")
    saved = QImage(dlg.path)
    assert saved.pixelColor(62, 1).black() > 200  # mirrored
    dlg2 = dialogs.WebcamDialog(str(tmp_path / "_webcam"))
    assert dlg2.take() is False  # nothing seen yet
