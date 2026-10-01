"""Object mask: the BiRefNet port, the mask model setting of all methods, U2Net for old jobs."""

import json

import numpy as np
import pytest
import torch
from PIL import Image


class Disc(torch.nn.Module):
    """Stand-in for BiRefNet: logits of a centred disc (radius 0.5 of the half size), or of nothing
    (``empty``); records its inputs."""

    def __init__(self, empty=False):
        super().__init__()
        self.empty = empty
        self.inputs = []

    def forward(self, x):
        self.inputs.append(x.detach().clone())
        h, w = x.shape[-2:]
        yy, xx = torch.meshgrid(torch.linspace(-1, 1, h), torch.linspace(-1, 1, w), indexing="ij")
        logits = torch.full_like(xx, -10.0) if self.empty else 20 * (0.5 - (xx ** 2 + yy ** 2).sqrt())
        return logits[None, None].expand(x.shape[0], 1, h, w)


@pytest.fixture
def disc(monkeypatch, tmp_path):
    from clipasso_studio.engine import masking, nets

    monkeypatch.setattr(masking, "cache_dir", lambda: tmp_path / "mask-cache")
    loads = []
    net = Disc()

    def load(device, key="birefnet"):
        loads.append(key)
        return net

    monkeypatch.setattr(nets, "load_birefnet", load)
    masking._cache.clear()
    yield net, loads
    masking._cache.clear()


def _image(w=160, h=120):
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    arr[..., 0] = np.linspace(0, 255, w, dtype=np.uint8)[None]
    arr[..., 2] = 200
    return Image.fromarray(arr)


# ----------------------------------------------------------------------------- the port
def test_cpu_deform_conv_matches_torchvision():
    from torchvision.ops import deform_conv2d

    from clipasso_studio.engine.birefnet import deform_conv2d_cpu

    torch.manual_seed(0)
    for k, hw in ((1, 9), (3, 16), (7, 21)):
        x = torch.randn(2, 5, hw, hw + 3)
        offset = torch.randn(2, 2 * k * k, hw, hw + 3) * 3  # also samples outside the image
        mask = torch.rand(2, k * k, hw, hw + 3) * 2
        weight = torch.randn(4, 5, k, k)
        ref = deform_conv2d(x, offset, weight, None, padding=(k // 2, k // 2), mask=mask)
        out = deform_conv2d_cpu(x, offset, weight, mask, k // 2)
        assert torch.allclose(out, ref, atol=1e-4, rtol=1e-4), k


def test_image2patches_is_the_einops_rearrange():
    from clipasso_studio.engine.birefnet import image2patches

    x = torch.arange(2 * 3 * 8 * 12, dtype=torch.float32).view(2, 3, 8, 12)
    out = image2patches(x, torch.zeros(1, 1, 2, 3))  # 4 x 4 grid of 2 x 3 patches
    assert out.shape == (2, 3 * 16, 2, 3)
    for c in range(3):
        for i in range(4):
            for j in range(4):  # 'b c (hg h) (wg w) -> b (c hg wg) h w'
                assert torch.equal(out[:, c * 16 + i * 4 + j], x[:, c, i * 2:(i + 1) * 2, j * 3:(j + 1) * 3])


@pytest.mark.parametrize("variant, params", [("lite", 44), ("general", 220)])
def test_birefnet_structure(variant, params):
    """Parameter count and names of the checkpoints (ZhengPeng7/BiRefNet_lite: 44 M, BiRefNet: 220 M)."""
    from clipasso_studio.engine.birefnet import build

    net = build(variant)
    n = sum(p.numel() for p in net.parameters()) / 1e6
    assert abs(n - params) < 1.5, n
    keys = set(net.state_dict())
    for k in ("bb.layers.0.blocks.0.attn.relative_position_index", "bb.norm3.weight",
              "squeeze_module.0.dec_att.aspp_deforms.2.atrous_conv.offset_conv.weight",
              "decoder.ipt_blk5.conv1.weight", "decoder.gdt_convs_attn_2.0.bias", "decoder.conv_out1.0.weight",
              "decoder.conv_ms_spvn_4.weight", "decoder.gdt_convs_pred_3.0.weight"):
        assert k in keys, k


def test_birefnet_forward_small_input():
    from clipasso_studio.engine.birefnet import build

    torch.manual_seed(0)
    net = build("lite").eval()
    with torch.inference_mode():
        out = net(torch.randn(1, 3, 64, 96))
    assert out.shape == (1, 1, 64, 96) and torch.isfinite(out).all()


# ------------------------------------------------------------------------- mask functions
def test_birefnet_probability_at_the_image_size_and_cached(disc):
    from clipasso_studio.engine import birefnet, masking

    net, loads = disc
    img = _image()
    prob = masking.birefnet_probability("cpu", img, "birefnet")
    assert prob.shape == (120, 160) and prob.dtype == np.float32
    assert 0.0 <= prob.min() and prob.max() <= 1.0
    assert prob[60, 80] > 0.99 and prob[0, 0] < 0.01  # disc in the middle
    x = net.inputs[0]
    assert x.shape == (1, 3, birefnet.SIZE, birefnet.SIZE)
    blue = (200 / 255 - birefnet.MEAN[2]) / birefnet.STD[2]  # ImageNet normalisation
    assert abs(float(x[0, 2].mean()) - blue) < 1e-4
    masking.birefnet_probability("cpu", img, "birefnet")  # the next seed: from the cache
    assert loads == ["birefnet"]
    masking.birefnet_probability("cpu", img, "birefnet-lite")
    assert loads == ["birefnet", "birefnet-lite"]


def test_masks_are_cached_on_disk_for_other_processes(disc, tmp_path):
    from clipasso_studio.engine import masking

    net, loads = disc
    img = _image()
    first = masking.birefnet_probability("cpu", img, "birefnet")
    (cached,) = (tmp_path / "mask-cache").glob("birefnet-160x120-*.png")
    masking._cache.clear()  # another process: only the disk cache
    again = masking.birefnet_probability("cpu", img, "birefnet")
    assert loads == ["birefnet"] and np.array_equal(first, again)  # the cached mask is the fresh one
    assert np.allclose(first, np.round(first * 65535) / 65535)
    masking._cache.clear()
    other = _image(161, 120)
    masking.birefnet_probability("cpu", other, "birefnet")
    assert loads == ["birefnet", "birefnet"] and len(list((tmp_path / "mask-cache").glob("*.png"))) == 2
    # an explicit network (the self-test's random one) never uses or fills the cache
    masking._cache.clear()
    random = Disc(empty=True)
    assert masking.birefnet_probability("cpu", img, "birefnet", net=random).max() < 0.01
    assert np.array_equal(masking.birefnet_probability("cpu", img, "birefnet"), first)


def test_mask_cache_keeps_the_most_recent(disc, tmp_path, monkeypatch):
    from clipasso_studio.engine import masking

    monkeypatch.setattr(masking, "CACHE_KEEP", 2)
    for w in (100, 101, 102):
        masking._cache.clear()
        masking.birefnet_probability("cpu", _image(w, 50), "birefnet-lite")
    names = sorted(f.name.split("-")[2] for f in (tmp_path / "mask-cache").glob("*.png"))
    assert names == ["101x50", "102x50"]


def test_mask_lock_waits_for_the_other_process_and_expires(tmp_path):
    import threading
    import time

    from clipasso_studio.engine import masking

    lock = tmp_path / "m.lock"
    order = []
    with masking._locked(lock):
        assert lock.exists()

        def second():
            with masking._locked(lock):
                order.append("second")

        t = threading.Thread(target=second)
        t.start()
        time.sleep(0.5)
        order.append("first")
    t.join(5)
    assert order == ["first", "second"] and not lock.exists()
    lock.write_text("")  # left behind by a killed process
    old = time.time() - 60
    import os
    os.utime(lock, (old, old))
    start = time.time()
    with masking._locked(lock, stale=30):
        pass
    assert time.time() - start < 2 and not lock.exists()


def test_get_mask_and_soft_mask_with_birefnet(disc):
    from clipasso_studio.engine import masking

    img = _image()
    masked, mask = masking.get_mask("cpu", img, "birefnet")
    m = np.asarray(mask)
    assert set(np.unique(m)) == {0, 255} and m[60, 80] == 255 and m[0, 0] == 0
    assert np.asarray(masked)[0, 0].tolist() == [255, 255, 255]  # background white
    soft = masking.soft_mask("cpu", img, "birefnet")
    assert soft.shape == (120, 160) and abs(float(soft.max()) - 1.0) < 1e-5 and float(soft.min()) < 1e-5


def test_no_object_found_keeps_the_whole_picture(monkeypatch, tmp_path):
    from clipasso_studio.engine import masking, nets

    monkeypatch.setattr(masking, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(nets, "load_birefnet", lambda device, key="birefnet": Disc(empty=True))
    masking._cache.clear()
    img = _image()
    _, mask = masking.get_mask("cpu", img, "birefnet")
    assert np.asarray(mask).min() == 255
    assert float(masking.soft_mask("cpu", img, "birefnet").min()) == 1.0
    masking._cache.clear()


def test_u2net_stays_available(monkeypatch):
    from clipasso_studio.engine import masking

    calls = []
    monkeypatch.setattr(masking, "get_mask_u2net", lambda device, im, net=None: calls.append("hard") or ("m", "k"))
    monkeypatch.setattr(masking, "u2net_soft_mask", lambda device, im, net=None: calls.append("soft") or "s")
    assert masking.get_mask("cpu", _image(), "u2net") == ("m", "k")
    assert masking.soft_mask("cpu", _image(), "u2net") == "s"
    assert calls == ["hard", "soft"]


def test_scenesketch_uses_birefnet_on_the_whole_image(disc):
    from clipasso_studio.engine.methods.scenesketch import preprocess as pre

    image = _image(256, 256)
    scene = pre.square_scene(image, False)
    prob = pre.object_probability(image, scene, "cpu", "birefnet")
    assert prob.shape == (256, 256)
    net, _ = disc
    assert net.inputs[-1].shape[-1] == 1024  # BiRefNet saw the whole image
    wide = _image(400, 256)
    assert pre.object_probability(wide, pre.square_scene(wide, False), "cpu", "birefnet").shape == (256, 256)
    obj = pre.object_mask(prob, 256)
    hole = pre.inpaint_mask(prob, 256)
    assert obj[128, 128] == 1 and obj[0, 0] == 0
    assert hole.sum() > obj.sum()  # dilated for the inpainting
    grow = (hole.sum() - obj.sum()) / obj.sum()
    small = pre.inpaint_mask(torch.nn.functional.interpolate(prob[None, None], size=(320, 320), mode="bilinear")[0, 0],
                             256)
    assert abs(grow - (small.sum() - obj.sum()) / obj.sum()) < 0.15  # the dilation scales with the map size


# ------------------------------------------------------------------------------- settings
def test_mask_model_setting_of_all_methods():
    from clipasso_studio import settings_schema as schema

    for method in schema.METHODS:
        s = schema.default_settings(method)
        assert s["mask_model"] == "birefnet", method
        p = next(p for p in schema.params_for(method) if p.key == "mask_model")
        assert p.choices == ("birefnet", "birefnet-lite", "u2net") and not p.advanced
        with pytest.raises(ValueError):
            schema.normalize({**s, "mask_model": "rmbg"})
    swift = schema.default_settings("swiftsketch")
    p = next(p for p in schema.params_for("swiftsketch") if p.key == "mask_model")
    assert p.enabled_if(swift) and not p.enabled_if({**swift, "mask_object": False})
    clip = schema.default_settings("clipasso")
    p = next(p for p in schema.params_for("clipasso") if p.key == "mask_model")
    assert not p.enabled_if(clip)  # CLIPasso does not mask by default
    assert p.enabled_if({**clip, "mask_object": True}) and p.enabled_if({**clip, "mask_object_attention": "on"})


def test_required_models_follow_the_mask_model():
    from clipasso_studio import settings_schema as schema
    from clipasso_studio.engine import methods

    for method, on in (("clipasso", {"mask_object": True}), ("swiftsketch", {}), ("controlsketch", {}),
                       ("scenesketch", {})):
        impl = methods.get(method)
        s = {**schema.default_settings(method), **on}
        assert "birefnet" in impl.required_models(s), method
        assert "birefnet-lite" in impl.required_models({**s, "mask_model": "birefnet-lite"}), method
        assert not {"birefnet", "birefnet-lite"} & set(impl.required_models({**s, "mask_model": "u2net"})), method
    off = {"clipasso": {"mask_object": False}, "swiftsketch": {"mask_object": False},
           "controlsketch": {"mask_object": False}, "scenesketch": {"split_scene": False}}
    for method, s in off.items():
        needed = methods.get(method).required_models({**schema.default_settings(method), **s})
        assert "birefnet" not in needed, method


def test_cli_accepts_mask_model():
    from clipasso_studio import cli

    for method in ("clipasso", "swiftsketch", "controlsketch", "scenesketch"):
        ns = cli.build_parser(method).parse_args(["--target_file", "x.png", "--mask_model", "u2net"])
        assert cli.settings_from_args(ns)["mask_model"] == "u2net"


def test_jobs_from_before_2_4_continue_with_u2net(tmp_path):
    from clipasso_studio.engine import jobs

    job = tmp_path / "job"
    job.mkdir()
    (job / jobs.STATE_FILE).write_text(json.dumps({"target": "x.png", "status": "interrupted", "seeds": [0],
                                                   "settings": {"method": "clipasso", "mask_object": True}}))
    assert jobs.read_state(str(job))["settings"]["mask_model"] == "u2net"
    jobs.write_state(str(job), "x.png", {"method": "clipasso", "mask_object": True, "mask_model": "birefnet"})
    assert jobs.read_state(str(job))["settings"]["mask_model"] == "birefnet"


def test_model_specs():
    from clipasso_studio.engine import model_store

    for key, repo in (("birefnet", "ZhengPeng7/BiRefNet"), ("birefnet-lite", "ZhengPeng7/BiRefNet_lite")):
        spec = model_store.SPECS[key]
        assert spec.kind == "hf" and not spec.bundled and spec.extra["repo"] == repo
        (f,) = spec.extra["files"]
        assert f.local == "model.safetensors" and f.fp16 and f.size


@pytest.mark.skipif(not __import__("clipasso_studio.engine.model_store", fromlist=["x"]).is_available("birefnet-lite"),
                    reason="BiRefNet lite not downloaded")
def test_real_birefnet_lite_finds_the_camel():
    from clipasso_studio import paths
    from clipasso_studio.engine import masking

    masking._cache.clear()
    img = Image.open(paths.resource("samples", "camel.png")).convert("RGB")
    _, mask = masking.get_mask("cpu", img, "birefnet-lite")
    m = np.asarray(mask) > 0
    assert 0.2 < m.mean() < 0.6 and not m[0, 0]
    masking._cache.clear()


def test_masked_images_are_computed_in_blocks_without_changing_them():
    """_on_white / apply_soft_mask work on blocks of rows (big photos no longer need gigabytes):
    the result is the same as the whole-image float64 version of 2.4."""
    import numpy as np
    from PIL import Image

    from clipasso_studio.engine import masking

    def old_on_white(pil_im, mask):
        mask3 = np.repeat(mask[:, :, None], 3, axis=2)
        im_np = np.array(pil_im).astype(np.float64)
        im_np = im_np / max(im_np.max(), 1e-12)
        im_np = mask3 * im_np
        im_np[mask3 == 0] = 1
        return (im_np / max(im_np.max(), 1e-12) * 255).astype(np.uint8), (mask * 255).astype(np.uint8)

    def old_soft(pil_im, mask):
        im = np.asarray(pil_im.convert("RGB")).astype(np.float64)
        im = im / max(im.max(), 1e-12)
        im = mask[:, :, None] * im
        im[mask < mask.mean()] = 1
        return (im / max(im.max(), 1e-12) * 255).astype(np.uint8)

    rng = np.random.default_rng(0)
    for h, w in ((700, 530), (256, 256), (1, 9), (513, 1)):
        im = Image.fromarray(rng.integers(0, 256, (h, w, 3), dtype=np.uint8))
        mask = (rng.random((h, w)) > 0.4).astype(np.float64)
        a, am = old_on_white(im, mask)
        b, bm = masking._on_white(im, mask)
        assert np.array_equal(a, np.asarray(b)) and np.array_equal(am, np.asarray(bm))
        assert np.array_equal(a, np.asarray(masking._on_white(im, mask > 0.5)[0]))  # a boolean mask
        soft = rng.random((h, w)).astype(np.float32)
        assert np.array_equal(old_soft(im, soft), np.asarray(masking.apply_soft_mask(im, soft)))
