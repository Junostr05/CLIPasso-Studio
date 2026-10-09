import numpy as np
import pytest

from clipasso_studio.engine import imaging


def test_gaussian_filter_matches_scipy():
    ndimage = pytest.importorskip("scipy.ndimage")
    rng = np.random.default_rng(0)
    im = rng.random((40, 30))
    for sigma in (0.8, 3.0, 8.0):
        np.testing.assert_allclose(imaging.gaussian_filter(im, sigma), ndimage.gaussian_filter(im, sigma), atol=1e-6)


def test_sobel_and_distance_transform_match_scipy():
    """3.8.1: the sketch guide used scipy's – which the app build leaves out (ModuleNotFoundError)."""
    ndimage = pytest.importorskip("scipy.ndimage")
    rng = np.random.default_rng(2)
    im = rng.random((37, 29))
    for axis in (0, 1):
        np.testing.assert_allclose(imaging.sobel(im, axis), ndimage.sobel(im, axis=axis), atol=1e-12)
    for share in (0.01, 0.2, 0.7):
        fg = rng.random((41, 33)) > share
        fg[0, 0] = False  # (at least one zero pixel)
        np.testing.assert_allclose(imaging.distance_transform_edt(fg), ndimage.distance_transform_edt(fg),
                                   atol=1e-9)
    edge = np.ones((224, 224), dtype=bool)
    edge[:, 111] = False
    np.testing.assert_allclose(imaging.distance_transform_edt(edge), ndimage.distance_transform_edt(edge))


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
