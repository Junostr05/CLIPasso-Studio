"""Detail brush and portrait mode: the map (stored per image, carried as a picture to a method's canvas), how it
weights the start strokes and softens the picture, the face detector (BlazeFace) and the painting dialog."""

import os
from types import SimpleNamespace

import numpy as np
import pytest
import torch
from PIL import Image

from clipasso_studio.engine import model_store

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "clipasso_studio", "resources", "samples")
HAS_FACE_MODEL = model_store.is_available("blazeface")


@pytest.fixture
def data_home(user_data):
    return user_data


def _photo(path, w=120, h=80):
    """Black and white stripes (sharp everywhere, so softening shows)."""
    arr = np.full((h, w, 3), 255, dtype=np.uint8)
    arr[:, ::4] = 0
    Image.fromarray(arr).save(path)
    return str(path)


def _left_more_right_less(h=80, w=120):
    v = np.zeros((h, w), dtype=np.float32)
    v[:, : w // 3] = 1.0
    v[:, 2 * w // 3:] = -1.0
    return v


# ----------------------------------------------------------------------------- the map
def test_map_as_a_picture_and_back():
    from clipasso_studio.engine import details

    v = np.linspace(-1, 1, 64, dtype=np.float32).reshape(8, 8)
    img = details.as_image(v)
    assert img.mode == "RGB" and img.getpixel((0, 0)) == (255, 0, 255)  # "less": no green
    assert img.getpixel((7, 7)) == (0, 255, 255)  # "more": no red
    assert np.allclose(details.from_image(img), v, atol=1 / 255 + 1e-6)
    assert np.allclose(details.from_image(Image.new("RGB", (5, 5), "white")), 0)  # padding stays normal
    assert details.from_image(img, size=(16, 4)).shape == (4, 16)


def test_gain_and_soften():
    from clipasso_studio.engine import details

    assert np.allclose(details.gain(np.array([-1.0, 0.0, 0.5, 1.0])), [0.25, 1.0, 2.0, 4.0])
    im = Image.open(_photo_buf()).convert("RGB")
    assert details.soften(im, np.zeros((80, 120), np.float32)) is im  # nothing "less": unchanged
    out = np.asarray(details.soften(im, _left_more_right_less()), dtype=np.float32)
    src = np.asarray(im, dtype=np.float32)
    assert np.array_equal(out[:, :40], src[:, :40])  # "more" and normal stay sharp
    assert out[:, 85:].std() < src[:, 85:].std() * 0.5  # "less" is blurred
    small = details.soften(im, _left_more_right_less(20, 30))  # a map of another size is scaled
    assert small.size == im.size


def _photo_buf():
    import io

    arr = np.full((80, 120, 3), 255, dtype=np.uint8)
    arr[:, ::4] = 0
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    buf.seek(0)
    return buf


def test_map_is_kept_per_image_and_goes_with_the_job(data_home, tmp_path):
    from clipasso_studio.engine import details, jobs

    path = _photo(tmp_path / "p.png")
    im = Image.open(path).convert("RGB")
    assert details.detail_map(im) is None and details.detail_stamp(path) == 0
    saved = details.save_detail_map(im, _left_more_right_less())
    assert saved is not None and saved.is_file() and details.detail_stamp(path) > 0
    v = details.detail_map(im)
    assert v.shape == (80, 120) and v[:, :30].min() > 0.99 and v[:, 90:].max() < -0.99
    copy = tmp_path / "copy.png"  # the same picture under another name: the same map
    im.save(copy)
    assert details.detail_map(Image.open(copy).convert("RGB")) is not None
    # uint8 grey as the dialog stores it
    grey = np.full((80, 120), details.NORMAL, np.uint8)
    grey[:10, :10] = 255
    details.save_detail_map(im, grey)
    assert details.detail_map(im)[:10, :10].min() > 0.99 and abs(details.detail_map(im)[40:, 40:]).max() == 0

    job = tmp_path / "job"
    job.mkdir()
    assert jobs.save_input(str(job), path) and (job / details.FILE).is_file()
    details.remove_detail_map(im)
    assert details.detail_map(im) is None
    assert details.restore_from_job(str(job), path) and details.detail_map(im) is not None
    # an all-normal map removes it
    assert details.save_detail_map(im, np.zeros((80, 120), np.float32)) is None
    assert details.detail_map(im) is None and not details.save_with_job(str(job), path)
    assert not details.restore_from_job(str(tmp_path), path)  # no copy in that folder


def test_a_map_of_another_size_is_ignored(data_home, tmp_path):
    from clipasso_studio.engine import details

    im = Image.open(_photo(tmp_path / "p.png")).convert("RGB")
    p = details.detail_path(im)
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.new("L", (10, 10), 255).save(p)
    assert details.detail_map(im) is None


# ----------------------------------------------------------------------------- CLIPasso and ControlSketch
def _args(path, **kw):
    a = dict(target=path, device="cpu", mask_object=False, mask_object_attention=False, fix_scale=True,
             image_scale=224, frame_object=False, mask_model="u2net")
    a.update(kw)
    return SimpleNamespace(**a)


def _no_mask(monkeypatch):
    from clipasso_studio.engine import masking

    def get_mask(device, im, model="u2net", net=None):
        return im.convert("RGB"), Image.new("L", im.size, 255)

    monkeypatch.setattr(masking, "get_mask", get_mask)


def test_clipasso_target_and_canvas_map(data_home, tmp_path, monkeypatch):
    from clipasso_studio.engine import details, pipeline

    _no_mask(monkeypatch)
    path = _photo(tmp_path / "p.png")
    args = _args(path)
    plain = pipeline.get_target(args)[0]
    assert args.detail_canvas is None
    details.save_detail_map(Image.open(path).convert("RGB"), _left_more_right_less())
    target = pipeline.get_target(args)[0]
    d = args.detail_canvas
    assert d.shape == (224, 224)
    # 120 × 80 padded to 140 × 140 (10 px margin), the photo's left third is "more", the right third "less"
    col = lambda x: int(round((10 + x) * 224 / 140))  # noqa: E731
    mid = slice(112 - 20, 112 + 20)
    assert d[mid, col(5):col(35)].min() > 0.9 and d[mid, col(85):col(115)].max() < -0.9
    assert abs(d[mid, col(45):col(75)]).max() < 0.1 and abs(d[:8]).max() < 0.05  # normal, and the padding
    right = (slice(None), slice(None), mid, slice(col(85), col(115)))
    left = (slice(None), slice(None), mid, slice(col(5), col(35)))
    assert target[right].std() < plain[right].std() * 0.6  # softened
    assert torch.allclose(target[left], plain[left], atol=1e-6)


def test_attention_of_the_start_strokes_is_weighted():
    from clipasso_studio.engine.painter import Painter

    detail = np.zeros((16, 16), np.float32)
    detail[:, :8] = 1.0
    detail[:, 12:] = -1.0
    me = SimpleNamespace(saliency_model="clip", clip_attn=lambda: np.ones((32, 32), np.float32), mask_object=False,
                         mask=None, args=SimpleNamespace(detail_canvas=detail))
    attn = Painter.set_attention_map(me)
    assert attn.shape == (32, 32) and attn[5, 2] == pytest.approx(4.0) and attn[5, 30] == pytest.approx(0.25)
    me.args.detail_canvas = None
    assert np.all(Painter.set_attention_map(me) == 1)
    # DINO: one map per head
    me = SimpleNamespace(saliency_model="dino", dino_attn=lambda: torch.ones(6, 16, 16), mask_object=True,
                         mask=torch.ones(16, 16), args=SimpleNamespace(detail_canvas=detail))
    attn = Painter.set_attention_map(me)
    assert attn.shape == (6, 16, 16) and torch.all(attn[:, :, 0] == 4) and torch.all(attn[:, :, 15] == 0.25)


def test_controlsketch_input_carries_the_map(data_home, tmp_path, monkeypatch):
    from clipasso_studio.engine import details, masking
    from clipasso_studio.engine.methods import controlsketch as cs

    monkeypatch.setattr(masking, "soft_mask", lambda device, im, model="u2net": np.ones((im.height, im.width),
                                                                                       np.float32))
    path = _photo(tmp_path / "p.png")
    s = {"render_size": 128, "fix_scale": True, "mask_object": False, "object_size_ratio": 0.8}
    assert cs.prepare_input(s, path, "cpu")["detail"] is None
    details.save_detail_map(Image.open(path).convert("RGB"), _left_more_right_less())
    inp = cs.prepare_input(s, path, "cpu")
    d = inp["detail"]
    assert d.shape == (128, 128) and d[64, 20] > 0.9 and d[64, 108] < -0.9 and abs(d[64, 64]) < 0.1
    s["mask_object"] = True  # the object is shrunk: the map with it
    inp = cs.prepare_input(s, path, "cpu")
    assert inp["detail"].shape == (128, 128) and inp["detail"].max() > 0.9 and inp["detail"].min() < -0.9


# ----------------------------------------------------------------------------- portrait mode
def test_anchors_decode_and_blend():
    from clipasso_studio.engine import portrait

    a = portrait.anchors()
    assert a.shape == (896, 2)
    assert torch.allclose(a[0], torch.tensor([1 / 32, 1 / 32])) and torch.allclose(a[512], torch.tensor([1 / 16,
                                                                                                         1 / 16]))
    boxes = torch.zeros(896, 16)
    boxes[:, 2:4] = 0.2 * portrait.SIZE  # 0.2 × 0.2 boxes around the anchors
    scores = torch.full((896,), -10.0)
    scores[[0, 1]] = torch.tensor([5.0, 3.0])  # two anchors at the same place: one face
    scores[600] = 4.0
    dets = portrait.decode(boxes, scores, a)
    assert dets.shape == (3, 17)
    faces = portrait.blend(dets)
    assert len(faces) == 2 and faces[0][16] == pytest.approx((torch.sigmoid(torch.tensor(5.0)) +
                                                               torch.sigmoid(torch.tensor(3.0))).item() / 2)
    assert faces[0][1] == pytest.approx(1 / 32 - 0.1)  # xmin


def _face(score=0.95, eyes_y=40.0, nose_y=55.0, mouth_y=70.0, gap=30.0):
    return {"box": (20.0, 20.0, 100.0, 100.0), "score": score,
            "points": {"right_eye": (45.0, eyes_y), "left_eye": (45.0 + gap, eyes_y), "nose": (60.0, nose_y),
                       "mouth": (60.0, mouth_y), "right_ear": (22.0, 50.0), "left_ear": (98.0, 50.0)}}


def test_plausible_faces_and_their_map():
    from clipasso_studio.engine import details, portrait

    assert portrait.plausible(_face())
    assert not portrait.plausible(_face(score=0.8))
    assert not portrait.plausible(_face(nose_y=30.0))  # the nose above the eyes
    assert not portrait.plausible(_face(gap=4.0))  # the eyes on top of each other
    m = portrait.detail_map((120, 120), [_face()])
    assert m.dtype == np.uint8 and m.shape == (120, 120)
    assert m[40, 45] == 255 and m[40, 75] == 255  # the eyes
    assert details.NORMAL < m[60, 40] < m[40, 45]  # a little more on the face
    assert m[5, 5] == details.NORMAL and m[115, 115] == details.NORMAL


@pytest.mark.skipif(not HAS_FACE_MODEL, reason="BlazeFace missing (run tools/fetch_models.py)")
def test_blazeface_finds_the_ballerina_but_not_the_horse():
    from clipasso_studio.engine import portrait

    net = portrait.load(str(model_store.find("blazeface")))
    ballerina = Image.open(os.path.join(SAMPLES, "ballerina.jpg")).convert("RGB")
    faces = [f for f in portrait.find_faces(ballerina, net) if portrait.plausible(f)]
    assert len(faces) == 1
    x0, y0, x1, y1 = faces[0]["box"]
    assert 0 <= x0 < x1 <= ballerina.width and 0 <= y0 < y1 <= ballerina.height
    ex, ey = faces[0]["points"]["right_eye"]
    assert x0 <= ex <= x1 and y0 <= ey <= y1
    for name in ("horse.png", "rose.jpeg", "camel.png"):
        im = Image.open(os.path.join(SAMPLES, name)).convert("RGB")
        assert not [f for f in portrait.find_faces(im, net) if portrait.plausible(f)], name


@pytest.mark.skipif(not HAS_FACE_MODEL, reason="BlazeFace missing (run tools/fetch_models.py)")
def test_portrait_detect_in_the_app():
    from clipasso_studio.gui import portrait

    ballerina = Image.open(os.path.join(SAMPLES, "ballerina.jpg")).convert("RGB")
    ballerina.thumbnail((512, 512))
    m = portrait.detect(ballerina)
    assert m.shape == (ballerina.height, ballerina.width) and m.max() == 255
    assert portrait.detect(Image.open(os.path.join(SAMPLES, "horse.png")).convert("RGB")) is None


# ----------------------------------------------------------------------------- the dialog
def test_detail_dialog_paint_undo_apply(qapp, data_home, tmp_path, monkeypatch):
    from clipasso_studio.engine import details
    from clipasso_studio.gui import detail_edit, portrait

    path = str(tmp_path / "big.png")
    Image.new("RGB", (2000, 1000), "white").save(path)
    dlg = detail_edit.DetailEditDialog(path)
    view = dlg.view
    assert view.map.shape == (512, 1024) and np.all(view.map == details.NORMAL)  # painted at most 1024 wide
    assert not dlg.undo_btn.isEnabled()
    view.brush = 40
    view.snapshot()
    view.dab(100, 100)
    view.changed.emit()
    assert view.map[100, 100] == 255 and view.map[300, 600] == details.NORMAL
    assert dlg.undo_btn.isEnabled() and "%" in dlg.info.text()
    dlg.set_tool("less")
    view.snapshot()
    view._line((600, 300), (800, 300))
    assert view.map[300, 700] == 0
    view.undo()
    assert view.map[300, 700] == details.NORMAL and view.map[100, 100] == 255
    view.redo()
    assert view.map[300, 700] == 0
    # portrait mode: merged with what is painted (the larger value wins)
    face = np.full_like(view.map, details.NORMAL)
    face[90:110, 90:110] = 200
    face[280:320, 690:710] = 255
    monkeypatch.setattr(portrait, "detail_for", lambda photo, parent=None: face)
    assert dlg.find_face() and view.map[300, 700] == 255 and view.map[100, 100] == 255
    monkeypatch.setattr(portrait, "detail_for", lambda photo, parent=None: None)
    assert not dlg.find_face() and dlg.info.text()
    dlg.apply()
    assert dlg.saved
    full = details.detail_map(Image.open(path).convert("RGB"))
    assert full.shape == (1000, 2000) and full[200, 200] > 0.99 and abs(full[900, 1900]) < 0.01
    # opened again: the map is there; cleared and applied: it is removed
    dlg = detail_edit.DetailEditDialog(path)
    assert dlg.view.map[100, 100] == 255
    dlg.clear()
    assert np.all(dlg.view.map == details.NORMAL) and dlg.view.undo_stack
    dlg.apply()
    assert details.detail_map(Image.open(path).convert("RGB")) is None
