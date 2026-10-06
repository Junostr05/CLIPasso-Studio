"""The photo's detail (edge density) and the number of strokes recommended for it."""

import numpy as np
from PIL import Image, ImageDraw

from clipasso_studio.engine import complexity


def _plain() -> Image.Image:
    im = Image.new("RGB", (400, 400), "white")
    ImageDraw.Draw(im).ellipse((120, 120, 280, 280), fill=(60, 60, 60))
    return im


def _busy() -> Image.Image:
    im = Image.new("RGB", (400, 400), "white")
    d = ImageDraw.Draw(im)
    for x in range(0, 400, 12):  # dense stripes and dots: much detail
        d.line((x, 0, x + 60, 400), fill=(20, 20, 20), width=3)
    for i in range(300):
        x, y = (i * 37) % 400, (i * 91) % 400
        d.ellipse((x, y, x + 6, y + 6), fill=(200, 40, 40))
    return im


def test_more_detail_more_edges():
    plain, busy = complexity.edge_density(_plain()), complexity.edge_density(_busy())
    assert 0 < plain < 0.06 < 0.17 < busy <= 1
    assert complexity.edge_density(Image.new("RGB", (300, 200), "white")) == 0.0


def test_the_mask_limits_the_region():
    """Inside the object's box only: a busy photo with a plain object counts the object."""
    im = _busy()
    ImageDraw.Draw(im).rectangle((100, 100, 300, 300), fill=(128, 128, 128))  # a calm object in the middle
    mask = np.zeros((200, 200), bool)  # (another size than the photo: scaled)
    mask[55:145, 55:145] = True
    assert complexity.edge_density(im, mask) < 0.05 < complexity.edge_density(im)
    assert complexity.edge_density(im, np.zeros((10, 10), bool)) == complexity.edge_density(im)  # (empty: all)


def test_recommendation_per_method():
    assert complexity.recommend("clipasso", 0.02) == (8, "few")
    assert complexity.recommend("clipasso", 0.08) == (16, "some")
    assert complexity.recommend("clipasso", 0.14) == (24, "many")
    assert complexity.recommend("clipasso", 0.4) == (32, "very_many")
    assert complexity.recommend("controlsketch", 0.4)[0] > complexity.recommend("controlsketch", 0.02)[0]
    assert complexity.recommend("swiftsketch", 0.4) is None and complexity.recommend("scenesketch", 0.4) is None
    for method, (limits, counts) in complexity.RECOMMEND.items():
        assert list(limits) == sorted(limits) and list(counts) == sorted(counts)
        assert len(counts) == len(limits) + 1 == len(complexity.LEVELS)
        assert method in complexity.STROKE_KEY
