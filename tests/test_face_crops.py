"""3.7: portraits – two of CLIPasso's CLIP augmentations become crops around the face BlazeFace finds."""

import os

import pytest
import torch
from PIL import Image

from clipasso_studio import settings_schema as schema
from clipasso_studio.engine import losses, model_store

BUNDLED = all(model_store.is_available(k) for k in ("clip:RN101", "clip:ViT-B/32", "blazeface"))
PORTRAIT = os.path.join(os.path.dirname(__file__), "..", "benchmarks", "images", "portrait", "peake.jpg")


def test_the_crop_box():
    box = (80.0, 60.0, 120.0, 110.0)  # 40 wide, 50 high: the face is 50
    top, left, side = losses.face_crop_box(box, 1.6, 224)
    assert side == 80 and (left + side / 2, top + side / 2) == (100, 85)
    # near the edge: moved inside the canvas; never larger than it
    top, left, side = losses.face_crop_box((0.0, 0.0, 30.0, 30.0), 2.6, 224)
    assert (top, left, side) == (0, 0, 78)
    assert losses.face_crop_box(box, 10.0, 224)[2] == 224
    top2, left2, _ = losses.face_crop_box(box, 1.6, 224, shift=(0.1, -0.1))
    assert (left2 - left, top2 - top) != (0, 0)


def _loss(turbo: bool, face: bool):
    from clipasso_studio.engine import pipeline

    s = {**schema.default_settings("clipasso"), "face_crops": face, "turbo": turbo, "device": "cpu"}
    args = pipeline.build_args(s, PORTRAIT, 0, "", torch.device("cpu"))
    loss = losses.Loss(args)
    if face:
        loss.set_face_box((80.0, 50.0, 140.0, 120.0))
    return loss.loss_mapper["clip_conv_loss"], args


@pytest.mark.skipif(not BUNDLED, reason="bundled models missing (run tools/fetch_models.py)")
@pytest.mark.parametrize("turbo", [False, True], ids=["plain", "turbo"])
def test_face_crops_take_the_place_of_two_augmentations(turbo, monkeypatch):
    conv, args = _loss(turbo, face=True)
    seen = []
    encode = conv._encode
    monkeypatch.setattr(conv, "_encode", lambda batch: (seen.append(batch.shape[0]), encode(batch))[1])
    if not turbo:  # (without turbo the batch goes to the ResNet directly)
        inspect = conv.forward_inspection_clip_resnet
        monkeypatch.setattr(conv, "forward_inspection_clip_resnet",
                            lambda batch: (seen.append(batch.shape[0]), inspect(batch))[1])
    assert conv._face_count("train") == 2 and conv._face_count("eval") == 0
    torch.manual_seed(0)
    x = torch.rand(1, 3, 224, 224, requires_grad=True)
    y = torch.rand(1, 3, 224, 224)
    out = conv(x, y, mode="train")
    total = sum(v for v in out.values())
    total.backward()
    assert x.grad is not None and torch.isfinite(total)
    assert seen[-1] == 1 + args.num_aug_clip  # (the plain sketch, two affine, two face crops: as many as before)
    crops = conv._face_crops(torch.cat([x.detach(), y]), 2, jitter=False)
    assert [tuple(c.shape) for c in crops] == [(2, 3, 224, 224)] * 2


@pytest.mark.skipif(not BUNDLED, reason="bundled models missing (run tools/fetch_models.py)")
def test_without_a_face_nothing_changes():
    conv, _ = _loss(False, face=False)
    assert conv.face_box is None and conv._face_count("train") == 0


@pytest.mark.skipif(not BUNDLED, reason="bundled models missing (run tools/fetch_models.py)")
def test_the_face_of_the_portrait_is_found():
    from clipasso_studio.engine import pipeline

    img = Image.open(PORTRAIT).convert("RGB")
    canvas = img.resize((224, 224))
    box = pipeline.face_box(canvas)
    assert box is not None
    x0, y0, x1, y1 = box
    assert 40 < (x0 + x1) / 2 < 180 and 20 < (y0 + y1) / 2 < 150 and 20 < x1 - x0 < 150
    assert pipeline.face_box(Image.new("RGB", (224, 224), "white")) is None
