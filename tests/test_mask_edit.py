"""Mask preview & touch-up: edited masks in all methods, the editor tools, the preview process."""

import os

import numpy as np
import pytest
import torch
from PIL import Image

from tests.helpers import wait_until


@pytest.fixture
def data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    from clipasso_studio.engine import masking

    masking._cache.clear()
    yield tmp_path
    masking._cache.clear()


def _photo(path, w=120, h=90):
    """A grey background with a red square (left) and a green square (right)."""
    arr = np.full((h, w, 3), 128, dtype=np.uint8)
    arr[20:50, 10:40] = (220, 30, 30)
    arr[30:70, 70:110] = (30, 200, 60)
    Image.fromarray(arr).save(path)
    return str(path)


def _left_square(h=90, w=120):
    m = np.zeros((h, w), dtype=np.float32)
    m[20:50, 10:40] = 1
    return m


# ----------------------------------------------------------------------------- engine
def test_edited_mask_wins_in_every_mask_function(data_home, monkeypatch):
    from clipasso_studio.engine import masking

    def no_model(*a, **k):
        raise AssertionError("the mask model must not run when the user edited the mask")

    for name in ("birefnet_probability", "get_mask_u2net", "u2net_soft_mask"):
        monkeypatch.setattr(masking, name, no_model)
    im = Image.open(_photo(data_home / "p.png")).convert("RGB")
    assert masking.edited_mask(im) is None
    masking.save_edited_mask(im, _left_square())
    for model in ("birefnet", "birefnet-lite", "u2net"):
        masked, mask = masking.get_mask("cpu", im, model)
        assert np.array_equal(np.asarray(mask) > 0, _left_square() > 0)
        assert np.asarray(masked)[60, 90].tolist() == [255, 255, 255]  # the green square is background now
        assert np.array_equal(masking.soft_mask("cpu", im, model), _left_square())
    masking.remove_edited_mask(im)
    assert masking.edited_mask(im) is None


def test_edited_mask_is_found_by_content_not_by_file(data_home):
    from clipasso_studio.engine import masking
    from clipasso_studio.engine.imaging import load_rgb

    a = _photo(data_home / "a.png")
    b = data_home / "copy.png"
    Image.open(a).save(b)
    masking.save_edited_mask(load_rgb(a), _left_square())
    assert masking.edited_mask(load_rgb(str(b))) is not None  # same pixels, other file
    assert masking.edited_stamp(str(b)) > 0
    other = Image.open(a).convert("RGB")
    other.putpixel((0, 0), (0, 0, 0))
    assert masking.edited_mask(other) is None


def test_scenesketch_cuts_the_full_image_mask_like_the_scene(data_home):
    from clipasso_studio.engine import masking
    from clipasso_studio.engine.methods.scenesketch import preprocess as pre

    im = Image.open(_photo(data_home / "p.png")).convert("RGB")  # 120 x 90
    masking.save_edited_mask(im, _left_square())
    for fix_scale in (False, True):
        scene = pre.square_scene(im, fix_scale)
        prob = pre.object_probability(im, scene, "cpu", "birefnet", fix_scale)
        assert prob.shape == (scene.size[1], scene.size[0])
        expected = pre.square_mask(_left_square(), fix_scale)
        assert torch.equal(prob, torch.from_numpy(expected))
    crop = pre.square_mask(_left_square(), False)  # centre crop 90 x 90 from x = 15
    assert crop.shape == (90, 90) and crop[30, 0] == 1 and crop[30, 30] == 0
    pad = pre.square_mask(_left_square(), True)  # 120 x 120, the image 15 px from the top
    assert pad.shape == (120, 120) and pad[15 + 20, 10] == 1 and pad[0].sum() == 0
    big = pre.square_mask(np.ones((1000, 800), dtype=np.float32), False)
    assert big.shape == (512, 512)


def test_jobs_keep_and_restore_the_edited_mask(data_home):
    from clipasso_studio.engine import jobs, masking
    from clipasso_studio.engine.imaging import load_rgb

    src = _photo(data_home / "p.png")
    masking.save_edited_mask(load_rgb(src), _left_square())
    job = jobs.make_job_dir(str(data_home / "out"), src)
    assert os.path.isfile(os.path.join(job, jobs.EDITED_MASK_FILE))
    assert jobs.saved_input(job, src).endswith("p.png")  # the mask is not taken for the input copy
    masking.remove_edited_mask(load_rgb(src))  # app data lost
    assert jobs.restore_edited_mask(job, jobs.saved_input(job, src))
    assert masking.edited_mask(load_rgb(src)) is not None


# ---------------------------------------------------------------------------- editor
def test_component_wand_and_brush():
    from clipasso_studio.gui import mask_edit

    m = np.zeros((90, 120), dtype=bool)
    m[20:50, 10:40] = True
    m[60:80, 80:100] = True
    part = mask_edit._component(m, 20, 30)
    assert part[20:50, 10:40].all() and not part[60:80, 80:100].any()
    assert not mask_edit._component(m, 60, 10).any()  # not on the mask
    photo = Image.open(_photo_buffer())
    sel = mask_edit.wand(photo, (120, 90), 90, 50)  # inside the green square
    assert sel[32:68, 72:108].all() and not sel[0:15].any() and not sel[25:45, 15:35].any()


def _photo_buffer():
    import io

    buf = io.BytesIO()
    arr = np.full((90, 120, 3), 128, dtype=np.uint8)
    arr[20:50, 10:40] = (220, 30, 30)
    arr[30:70, 70:110] = (30, 200, 60)
    Image.fromarray(arr).save(buf, format="PNG")
    buf.seek(0)
    return buf


def test_canvas_click_paint_undo(qapp):
    from PySide6.QtGui import QImage

    from clipasso_studio.gui.mask_edit import MaskCanvas

    photo = Image.open(_photo_buffer()).convert("RGB")
    q = QImage(photo.tobytes(), 120, 90, 360, QImage.Format_RGB888).copy()
    mask = _left_square() > 0
    candidate = np.zeros_like(mask)
    candidate[60:80, 0:20] = True
    c = MaskCanvas(q, mask, candidate, photo)
    c.resize(240, 180)
    assert c.click_part(20, 30) and not c.mask.any()  # removes the left square
    c.undo()
    assert c.mask[30, 20]
    c.redo()
    assert not c.mask.any()
    assert c.click_part(5, 70) and c.mask[65:75, 5:15].all()  # adds the candidate part
    assert c.click_part(90, 50) and c.mask[40:60, 80:100].all()  # wand: the green square
    c.brush = 20
    before = c.mask.sum()
    c.dab(60, 10, True)
    assert c.mask.sum() > before and c.mask[10, 60]
    c.dab(60, 10, False)
    assert not c.mask[10, 60]
    assert len(c.undo_stack) == 3


def test_dialog_apply_saves_or_removes_the_edit(qapp, data_home):
    from clipasso_studio.engine import masking
    from clipasso_studio.engine.imaging import load_rgb
    from clipasso_studio.gui.mask_edit import MaskEditDialog

    src = _photo(data_home / "p.png")
    prob = _left_square()
    dlg = MaskEditDialog(src, prob)
    dlg.view.click_part(90, 50)  # add the green square
    dlg.apply()
    assert dlg.saved and masking.edited_mask(load_rgb(src))[50, 90] == 1
    dlg = MaskEditDialog(src, prob, masking.edited_mask(load_rgb(src)))
    dlg.reset()  # back to the automatic mask: the edit is removed on apply
    dlg.apply()
    assert masking.edited_mask(load_rgb(src)) is None
    dlg = MaskEditDialog(src, prob)
    dlg.view.click_part(20, 30)  # nothing left
    assert not dlg.apply_btn.isEnabled()


def test_overlay_veils_the_background(qapp):
    from PySide6.QtGui import QColor

    from clipasso_studio.gui.mask_view import overlay

    m = np.zeros((400, 600), dtype=np.float32)
    m[100:300, 200:400] = 1
    img = overlay(m, QColor(10, 20, 30, 200), QColor(255, 0, 0), max_side=300)
    assert (img.width(), img.height()) == (300, 200)
    assert img.pixelColor(10, 10).alpha() == 200  # background veiled
    assert img.pixelColor(150, 100).alpha() == 0  # object clear
    assert img.pixelColor(100, 100) == QColor(255, 0, 0)  # outline


# --------------------------------------------------------------------------- preview
def _wait(app, condition, timeout=120):
    wait_until(app, condition, timeout)


def test_preview_from_the_cache_needs_no_process(qapp, data_home):
    from clipasso_studio.engine import masking
    from clipasso_studio.engine.imaging import load_rgb
    from clipasso_studio.gui.mask_view import MaskPreviewer

    src = _photo(data_home / "p.png")
    im = load_rgb(src)
    masking._make_folder(masking.cache_dir())
    masking._write_cached(masking.cache_path(im, "birefnet"), (_left_square() * 65535).astype(np.uint16))
    pv = MaskPreviewer()
    got = []
    pv.ready.connect(lambda p, m: got.append((p, m)))
    pv.request(src, "birefnet", delay=False)
    assert got == [(src, "birefnet")] and not pv.is_busy()


@pytest.mark.skipif(not __import__("clipasso_studio.engine.model_store", fromlist=["x"]).is_available("u2net"),
                    reason="bundled U2Net missing")
def test_preview_process_with_u2net(qapp, data_home):
    from clipasso_studio.gui.mask_view import MaskPreviewer, load_mask

    src = _photo(data_home / "p.png")
    pv = MaskPreviewer()
    got, busy = [], []
    pv.ready.connect(lambda p, m: got.append(m))
    pv.failed.connect(lambda p, m, e: got.append("failed: " + e))
    pv.busy.connect(busy.append)
    pv.request(src, "u2net", "cpu", delay=False)
    assert pv.is_busy()
    _wait(qapp, lambda: got)
    assert got == ["u2net"] and busy == [True, False]
    _, prob, _ = load_mask(src, "u2net")
    assert prob is not None and prob.shape == (90, 120)


def test_studio_shows_mask_and_edit_state(qapp, data_home):
    from clipasso_studio.engine import masking
    from clipasso_studio.engine.imaging import load_rgb
    from clipasso_studio.gui import app_settings as settings_module
    from clipasso_studio.gui.controller import JobController
    from clipasso_studio.gui.pages.studio import StudioPage

    settings_module._instance = None
    src = _photo(data_home / "p.png")
    im = load_rgb(src)
    masking._make_folder(masking.cache_dir())
    masking._write_cached(masking.cache_path(im, "u2net"), (_left_square() * 65535).astype(np.uint16))
    page = StudioPage(JobController())
    page.params.set_method("swiftsketch")
    page.params.fields["mask_model"].set_value("u2net", emit=True)
    page.set_image(src)
    _wait(qapp, lambda: page._mask is not None, 10)
    assert page.mask_state == "ready" and page.drop._overlay is not None
    masking.save_edited_mask(im, np.ones((90, 120)))
    page._mask = None
    page._update_mask_preview()
    _wait(qapp, lambda: page._mask is not None, 10)
    assert page.mask_state == "edited" and page.mask_reset_btn.isVisibleTo(page)
    page.reset_mask()
    _wait(qapp, lambda: page._mask is not None, 10)
    assert page.mask_state == "ready" and masking.edited_mask(im) is None
    page.params.fields["mask_object"].set_value(False, emit=True)
    assert not page.mask_row.isVisibleTo(page) and page.drop._overlay is None
    page.shutdown()
    settings_module._instance = None


# ------------------------------------------------------------------------ auto-framing
def test_frame_object_geometry():
    from clipasso_studio.engine.imaging import FRAME_FILL, frame_object

    im = Image.new("RGB", (400, 300), "white")
    mask = Image.new("L", (400, 300), 0)
    mask.paste(255, (300, 40, 360, 100))  # a 60 px object near the right edge
    im.paste((200, 0, 0), (300, 40, 360, 100))
    out, out_mask, framed = frame_object(im, mask)
    side = round(60 / FRAME_FILL)
    assert framed and out.size == (side, side) and out_mask.size == (side, side)
    m = np.asarray(out_mask) > 127
    ys, xs = np.nonzero(m)
    assert (xs.max() - xs.min() + 1, ys.max() - ys.min() + 1) == (60, 60)
    assert abs((xs.min() + xs.max()) / 2 - side / 2) <= 1  # centred
    assert out.getpixel((side // 2, side // 2)) == (200, 0, 0)
    big = Image.new("L", (400, 300), 0)
    big.paste(255, (20, 20, 380, 280))  # already fills the picture
    assert frame_object(im, big)[2] is False
    assert frame_object(im, Image.new("L", (400, 300), 0))[2] is False
    edge = Image.new("L", (400, 300), 0)
    edge.paste(255, (0, 0, 40, 40))  # in the corner: the crop reaches outside, padded white / 0
    out, out_mask, framed = frame_object(im, edge)
    assert framed and out.getpixel((0, 0)) == (255, 255, 255) and out_mask.getpixel((0, 0)) == 0


def test_frame_object_in_clipasso_and_swiftsketch(data_home):
    from clipasso_studio import settings_schema as schema
    from clipasso_studio.engine import masking, pipeline
    from clipasso_studio.engine.imaging import load_rgb
    from clipasso_studio.engine.methods import swiftsketch

    src = str(data_home / "small.png")
    Image.new("RGB", (300, 200), (90, 90, 90)).save(src)
    m = np.zeros((200, 300), dtype=np.float32)
    m[50:90, 100:140] = 1  # a 40 px object
    masking.save_edited_mask(load_rgb(src), m)
    s = {**schema.default_settings("clipasso"), "mask_object": True}
    args = pipeline.build_args(s, src, 0, str(data_home / "run"), torch.device("cpu"))
    _, mask_t, mask_img = pipeline.get_target(args)
    assert mask_img.size == (47, 47) and float(mask_t.mean()) > 0.5  # framed: the object fills the canvas
    args = pipeline.build_args({**s, "frame_object": False}, src, 0, str(data_home / "run"), torch.device("cpu"))
    assert pipeline.get_target(args)[2].size == (300, 200)
    sw = {**schema.default_settings("swiftsketch"), "mask_model": "u2net"}
    image, mask_img = swiftsketch.prepare_input(sw, src, torch.device("cpu"))
    assert image.size == (47, 47)
    image, _ = swiftsketch.prepare_input({**sw, "frame_object": False}, src, torch.device("cpu"))
    assert image.size == (300, 200)


def test_frame_object_setting_and_old_jobs(tmp_path):
    import json

    from clipasso_studio import settings_schema as schema
    from clipasso_studio.engine import jobs

    for method in ("clipasso", "swiftsketch"):
        p = next(p for p in schema.params_for(method) if p.key == "frame_object")
        s = schema.default_settings(method)
        assert s["frame_object"] is True and not p.advanced
        assert p.enabled_if({**s, "mask_object": True}) and not p.enabled_if({**s, "mask_object": False})
    (tmp_path / jobs.STATE_FILE).write_text(json.dumps({"target": "x.png", "settings": {"method": "clipasso"}}))
    assert jobs.read_state(str(tmp_path))["settings"]["frame_object"] is False
