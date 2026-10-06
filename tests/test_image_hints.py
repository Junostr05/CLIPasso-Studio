"""Quality hints about the studio's photo: no false alarm for good photos, a hint for clearly worse ones."""

import glob
import os

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from clipasso_studio.gui import image_hints

SAMPLES = sorted(glob.glob(os.path.join(os.path.dirname(image_hints.__file__), "..", "resources", "samples", "*")))


def _photo(size=(480, 400)) -> Image.Image:
    """A sharp picture: shapes and lines in several greys on a light ground."""
    im = Image.new("RGB", size, (235, 232, 225))
    d = ImageDraw.Draw(im)
    w, h = size
    d.ellipse((w * 0.2, h * 0.2, w * 0.7, h * 0.8), fill=(90, 70, 60), outline=(20, 20, 20), width=3)
    d.rectangle((w * 0.55, h * 0.1, w * 0.9, h * 0.45), fill=(160, 170, 190))
    for i in range(12):
        d.line((w * 0.05, h * (0.05 + 0.07 * i), w * 0.45, h * (0.1 + 0.06 * i)), fill=(30, 30, 30), width=2)
    return im


def _keys(im: Image.Image, tmp_path, name="p.png") -> list[str]:
    path = tmp_path / name
    im.save(path)
    return [h.key for h in image_hints.photo_hints(str(path))]


@pytest.mark.parametrize("path", SAMPLES, ids=[os.path.basename(p) for p in SAMPLES])
def test_no_hint_for_the_sample_pictures(path):
    assert SAMPLES and image_hints.photo_hints(path) == []


def test_worse_photos_get_their_hint(tmp_path):
    im = _photo()
    assert _keys(im, tmp_path) == []
    assert _keys(im.resize((160, 133)), tmp_path) == ["small"]
    assert _keys(ImageEnhance.Brightness(im).enhance(0.3), tmp_path) == ["dark"]
    assert _keys(ImageEnhance.Contrast(im).enhance(0.25), tmp_path) == ["flat"]
    assert _keys(im.filter(ImageFilter.GaussianBlur(4)), tmp_path) == ["blurry"]
    hints = image_hints.photo_hints(str(tmp_path / "p.png"))
    assert hints[0].action == ""  # (nothing in the app helps a blurred photo: the text says what does)
    small = image_hints.photo_hints(str(_save(im.resize((160, 133)), tmp_path)))[0]
    assert small.values == {"w": 160, "h": 133, "min": image_hints.MIN_SIDE}


def _save(im, tmp_path, name="s.png"):
    im.save(tmp_path / name)
    return tmp_path / name


def test_a_plain_grey_picture_is_flat_but_not_blurred(tmp_path):
    assert _keys(Image.new("RGB", (400, 400), (128, 128, 128)), tmp_path) == ["flat"]


def test_mask_hints():
    prob = np.zeros((200, 200), np.float32)
    assert [h.key for h in image_hints.mask_hints(prob)] == ["no_object"]
    assert image_hints.mask_hints(None) == []
    prob[90:110, 90:110] = 1.0  # 1 % of the picture
    (small,) = image_hints.mask_hints(prob)
    assert small.key == "small_object" and small.action == "crop" and small.values == {"percent": 1}
    thin = np.zeros((200, 200), np.float32)  # a long thin object (a rose on its stem): small area, large box
    thin[20:180, 98:102] = 1.0
    thin[20:50, 80:120] = 1.0
    assert image_hints.mask_hints(thin) == []
    soft = np.zeros((200, 200), np.float32)  # the model unsure about most of the object
    soft[40:160, 40:160] = 0.6
    soft[70:130, 70:130] = 1.0
    (unsure,) = image_hints.mask_hints(soft)
    assert unsure.key == "unsure_mask" and unsure.action == "mask" and unsure.values["percent"] == 75
    # the user's own mask: checked already – only the object's size counts
    assert image_hints.mask_hints(soft, edited=soft >= 0.5) == []
    assert [h.key for h in image_hints.mask_hints(soft, edited=prob >= 0.5)] == ["small_object"]


def test_shown_order_and_switched_off():
    hints = [image_hints.Hint(k) for k in ("flat", "small", "small_object", "blurry")]
    assert [h.key for h in image_hints.shown(hints)] == ["small_object", "small", "blurry", "flat"]
    assert [h.key for h in image_hints.shown(hints, ["small", "flat"])] == ["small_object", "blurry"]
