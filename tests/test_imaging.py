import numpy as np
import pytest

from clipasso_studio.engine import imaging


def test_gaussian_filter_matches_scipy():
    ndimage = pytest.importorskip("scipy.ndimage")
    rng = np.random.default_rng(0)
    im = rng.random((40, 30))
    for sigma in (0.8, 3.0, 8.0):
        np.testing.assert_allclose(imaging.gaussian_filter(im, sigma), ndimage.gaussian_filter(im, sigma), atol=1e-6)


def test_otsu_matches_skimage():
    filters = pytest.importorskip("skimage.filters")
    rng = np.random.default_rng(1)
    im = np.concatenate([rng.normal(0.2, 0.05, 500), rng.normal(0.8, 0.1, 700)]).reshape(40, 30)
    assert imaging.threshold_otsu(im) == pytest.approx(filters.threshold_otsu(im))


def test_fix_image_scale_is_square():
    from PIL import Image

    im = Image.new("RGB", (50, 20), (10, 20, 30))
    out = imaging.fix_image_scale(im)
    assert out.size == (70, 70)
    assert out.getpixel((0, 0)) == (255, 255, 255)
    assert out.getpixel((35, 35)) == (10, 20, 30)
