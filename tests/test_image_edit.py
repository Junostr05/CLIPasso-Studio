"""Crop / rotate / flip the input image."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("appdata")
    env = pytest.MonkeyPatch()  # undone after the module: later tests use the real model folders
    env.setenv("XDG_DATA_HOME", str(tmp))
    env.setenv("LOCALAPPDATA", str(tmp))
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from clipasso_studio.gui import app_settings as settings_module
    from clipasso_studio.gui.app_settings import app_settings

    settings_module._instance = None
    app_settings().data["output_dir"] = str(tmp / "out")
    yield app
    env.undo()


@pytest.fixture
def image(tmp_path):
    from PIL import Image

    img = Image.new("RGB", (200, 100), "white")
    img.paste((255, 0, 0), (0, 0, 20, 20))  # red square top left – shows where the image went
    path = tmp_path / "photo.png"
    img.save(path)
    return str(path)


def test_crop_rotate_flip_and_save(qapp, image):
    from PIL import Image
    from PySide6.QtCore import QPointF, QRectF

    from clipasso_studio.gui.image_edit import ImageEditDialog

    dlg = ImageEditDialog(image)
    dlg.resize(700, 560)
    view = dlg.view
    assert view.crop == QRectF(0, 0, 200, 100)
    dlg.aspect.setCurrentIndex(1)  # square
    assert view.crop.width() == view.crop.height() == 100 and view.crop.center().x() == 100
    dlg.aspect.setCurrentIndex(0)
    view.crop = QRectF(0, 0, 200, 100)
    # drag the right edge in, then the whole rectangle
    view.drag_to("e", QPointF(120, 50), start=QRectF(0, 0, 200, 100), press=QPointF(200, 50))
    assert view.crop == QRectF(0, 0, 120, 100)
    view.drag_to("move", QPointF(150, 50), start=QRectF(0, 0, 120, 100), press=QPointF(60, 50))
    assert view.crop == QRectF(80, 0, 120, 100)  # stopped at the right border
    view.crop = QRectF(0, 0, 60, 40)
    dlg.rotate(90)  # clockwise: 100 x 200, the red corner goes to the top right
    assert (view.image.width(), view.image.height()) == (100, 200)
    assert view.crop == QRectF(60, 0, 40, 60)
    dlg.flip()
    assert view.crop == QRectF(0, 0, 40, 60)
    dlg.apply()
    assert dlg.result_path and os.path.dirname(dlg.result_path).endswith("_edited")
    out = Image.open(dlg.result_path).convert("RGB")
    assert out.size == (40, 60)
    assert out.getpixel((5, 5))[1] < 50  # the red corner after rotation + flip
    assert Image.open(image).size == (200, 100)  # the original is untouched


def test_aspect_keeps_its_ratio_while_resizing(qapp, image):
    from PySide6.QtCore import QPointF, QRectF

    from clipasso_studio.gui.image_edit import ImageEditDialog

    dlg = ImageEditDialog(image)
    view = dlg.view
    dlg.aspect.setCurrentIndex(2)  # 4:3
    start = QRectF(view.crop)
    assert abs(start.width() / start.height() - 4 / 3) < 1e-6
    view.drag_to("se", QPointF(start.left() + 60, 99), start=start, press=start.bottomRight())
    assert abs(view.crop.width() / view.crop.height() - 4 / 3) < 1e-6 and view.crop.width() == 60
    dlg.rotate(-90)  # the 4:3 frame becomes 3:4
    assert dlg.aspect.currentData() == pytest.approx(3 / 4)
    dlg.reset()
    assert view.crop == QRectF(0, 0, 200, 100) and view.aspect is None
