"""ControlSketch: initialisation, geometry, conditions, SDS loss and a full run.

The diffusion parts run with tiny randomly initialised diffusers / transformers models, so these
tests need no Stable Diffusion download (CLIP ViT-B/32 and U2Net are bundled with the app).
"""

import json
import os

import numpy as np
import pytest
import torch
from PIL import Image

from clipasso_studio.engine import model_store
from clipasso_studio.engine.methods.controlsketch import conditions as C
from clipasso_studio.engine.methods.controlsketch import init as I
from clipasso_studio.engine.methods.controlsketch import painter as P

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "clipasso_studio", "resources", "samples", "camel.png")
BUNDLED = all(model_store.is_available(k) for k in ("clip:ViT-B/32", "u2net"))

diffusers = pytest.importorskip("diffusers")


# ----------------------------------------------------------------------------- initialisation


def test_kmeans_finds_separated_clusters():
    rng = np.random.default_rng(0)
    centers = np.array([[10.0, 10.0], [100.0, 20.0], [50.0, 90.0]])
    x = np.concatenate([c + rng.normal(0, 2, (200, 2)) for c in centers])
    found, labels, inertia = I.kmeans(x, 3)
    for c in centers:
        assert np.min(np.linalg.norm(found - c, axis=1)) < 1.0
    assert len(set(labels[:200])) == 1 and inertia > 0


def test_smart_clustering_places_every_stroke_on_the_object():
    mask = np.zeros((128, 128), np.uint8)
    mask[20:100, 30:90] = 255
    weights = np.zeros((128, 128), np.float32)
    weights[20:40, 30:50] = 1.0  # high attention in one corner
    for n in (32, 16, 7, 3):
        points, regions = I.smart_clustering(mask, weights, n)
        assert points.shape == (n, 2)
        assert all(mask[int(y), int(x)] for x, y in points)
    points, _ = I.smart_clustering(mask, weights, 32)
    corner = sum(1 for x, y in points if x < 50 and y < 40)
    assert corner >= 4  # the attended region gets extra strokes
    # an empty mask falls back to the whole canvas
    points, _ = I.smart_clustering(np.zeros((64, 64), np.uint8), np.ones((64, 64), np.float32), 8)
    assert points.shape == (8, 2)


# ----------------------------------------------------------------------------- geometry


def test_shrink_and_restore_object():
    size = 256
    img = np.full((size, size, 3), 255, np.uint8)
    img[16:240, 40:200] = (200, 80, 20)
    mask = torch.zeros(size, size)
    mask[16:240, 40:200] = 1
    small, small_mask, info = P.shrink_object(Image.fromarray(img), mask, 0.5)
    assert info is not None
    ys, xs = np.nonzero(small_mask.numpy() >= 0.5)
    assert max(ys.max() - ys.min(), xs.max() - xs.min()) <= int(size * 0.5) + 1
    # the centre and the corners of the small object map back onto the original object box
    cy, cx = (ys.min() + ys.max()) / 2, (xs.min() + xs.max()) / 2
    pts = torch.tensor([[cx, cy], [xs.min(), ys.min()], [xs.max(), ys.max()]], dtype=torch.float32)
    back = P.restore_points(pts, size, info, size)
    assert torch.allclose(back[0], torch.tensor([119.5, 127.5]), atol=3)
    assert torch.allclose(back[1], torch.tensor([40.0, 16.0]), atol=4)
    assert torch.allclose(back[2], torch.tensor([199.0, 239.0]), atol=4)
    assert torch.allclose(P.restore_points(pts, size, None, 2 * size), pts * 2)
    # small objects stay as they are
    img2, mask2, info2 = P.shrink_object(Image.fromarray(img), mask, 0.95)
    assert info2 is None and torch.equal(mask2, mask)


def test_thick_contour_matches_scipy():
    ndimage = pytest.importorskip("scipy.ndimage")
    rng = np.random.default_rng(1)
    m = np.zeros((64, 64), np.float32)
    m[8:50, 12:40] = 1
    m[30:60, 30:62] = 1
    m[rng.random((64, 64)) > 0.97] = 1
    ref = ndimage.binary_dilation(m, structure=np.ones((5, 5))).astype(np.uint8) - \
        ndimage.binary_erosion(m, structure=np.ones((10, 10))).astype(np.uint8)
    ours = P.thick_contour(torch.from_numpy(m), 64)
    assert np.array_equal(ours, ref > 0)


def test_sort_puts_outline_strokes_first():
    painter = P.StrokePainter(3, 1, 4, 2.5, 128, "cpu", start_points=[(0.5, 0.5)] * 3)
    painter.init_strokes()
    with torch.no_grad():
        painter.shapes[0].points[:] = torch.tensor([[60.0, 60], [62, 62], [64, 64], [66, 66]])  # inside
        painter.shapes[1].points[:] = torch.tensor([[20.0, 30], [20, 50], [20, 70], [20, 90]])  # on the outline
        painter.shapes[2].points[:] = torch.tensor([[40.0, 40], [42, 42], [44, 44], [46, 46]])  # inside, attended
    mask = torch.zeros(128, 128)
    mask[20:108, 20:108] = 1
    attn = torch.zeros(128, 128)
    attn[36:50, 36:50] = 1
    assert P.sort_by_contour_and_attn(painter, mask, attn) == [1, 2, 0]


# ----------------------------------------------------------------------------- conditions


def test_canny_matches_opencv():
    cv2 = pytest.importorskip("cv2")
    img = np.asarray(Image.open(SAMPLE).convert("RGB").resize((256, 256)))
    ref = cv2.Canny(img, 100, 200)
    ours = C.canny(img)
    assert (ref == ours).mean() > 0.999


def test_normal_map_matches_opencv_sobel():
    cv2 = pytest.importorskip("cv2")
    rng = np.random.default_rng(0)
    depth = rng.random((40, 50)).astype(np.float32) * 10
    for dx, dy in ((1, 0), (0, 1)):
        assert np.allclose(C._sobel(depth, dx, dy), cv2.Sobel(depth, cv2.CV_32F, dx, dy, ksize=3), atol=1e-4)
    n = C.normal_from_depth(depth)
    assert n.shape == (40, 50, 3) and n.dtype == np.uint8


def test_masked_condition_keeps_the_object_only():
    cond = Image.fromarray(np.full((64, 64, 3), 200, np.uint8))
    mask = torch.zeros(64, 64)
    mask[10:30, 10:30] = 1
    out = np.asarray(C.masked_condition(cond, mask, 128))
    assert out.shape == (128, 128, 3)
    assert out[40, 40].max() == 255 and out[100, 100].max() == 0


def test_hed_network_matches_the_checkpoint():
    net = C.ControlNetHED()
    x = torch.rand(1, 3, 64, 64) * 255
    outs = net(x)
    assert [o.shape[-1] for o in outs] == [64, 32, 16, 8, 4]
    if model_store.is_available("hed"):
        net = C.load_hed("cpu")  # strict load of lllyasviel/Annotators ControlNetHED.pth
        edges = C.hed_edges(Image.open(SAMPLE), net, "cpu")
        assert edges.dtype == np.uint8 and edges.max() > 128


# ----------------------------------------------------------------------------- SDS


def tiny_sd(seed=0):
    from clipasso_studio.engine.selftest_models import tiny_sd as make

    return make(seed)


def test_alphas_cumprod_matches_diffusers():
    from diffusers import DDPMScheduler

    from clipasso_studio.engine.methods.controlsketch.sds import alphas_cumprod_from_config

    cfg = {"beta_start": 0.00085, "beta_end": 0.012, "beta_schedule": "scaled_linear", "num_train_timesteps": 1000}
    ref = DDPMScheduler(**cfg).alphas_cumprod
    assert torch.allclose(alphas_cumprod_from_config(cfg), ref, atol=1e-6)


def test_sds_loss_backpropagates_into_the_sketch():
    from clipasso_studio.engine.methods.controlsketch.sds import ControlSDSLoss, alphas_cumprod_from_config

    unet, controlnet, vae = tiny_sd()
    text, empty = torch.randn(1, 77, 32), torch.zeros(1, 77, 32)
    loss_fn = ControlSDSLoss(unet, controlnet, vae, text, empty, torch.rand(1, 3, 64, 64),
                             alphas_cumprod_from_config({}), guidance_scale=100, conditioning_scale=0.15)
    painter = P.StrokePainter(4, 1, 4, 2.5, 64, "cpu")
    painter.init_strokes()
    params = painter.parameters()
    torch.manual_seed(0)
    loss = loss_fn(painter.get_image())
    assert torch.isfinite(loss)
    loss.backward()
    assert all(p.grad is not None and torch.isfinite(p.grad).all() for p in params)
    assert any(p.grad.abs().sum() > 0 for p in params)


# ----------------------------------------------------------------------------- full run


@pytest.mark.skipif(not BUNDLED, reason="bundled models missing (run tools/fetch_models.py)")
def test_full_run_with_tiny_models(monkeypatch, tmp_path):
    from clipasso_studio import settings_schema as schema
    from clipasso_studio.engine import pipeline
    from clipasso_studio.engine.methods import controlsketch
    from clipasso_studio.engine.methods.controlsketch import sds
    from clipasso_studio.engine.selftest_models import tiny_sd15_loader

    monkeypatch.setattr(sds, "load_sd15", tiny_sd15_loader)
    controlsketch.release_models()
    events = []

    class Rec(pipeline.Reporter):
        def event(self, kind, **data):
            events.append((kind, data))

    settings = {**schema.default_settings("controlsketch"), "num_iter": 4, "save_interval": 2, "num_sketches": 2,
                "num_strokes": 8, "render_size": 256, "output_svg_size": 512, "condition": "canny",
                "caption": "a camel", "fix_scale": True, "device": "cpu", "mask_model": "u2net"}
    summary = pipeline.run_job(settings, SAMPLE, str(tmp_path), Rec())
    assert summary["method"] == "controlsketch"
    runs = summary["runs"]
    assert [r["seed"] for r in runs] == [0, 1000] and all(r["clip_score"] is not None for r in runs)
    run_dir = runs[0]["run_dir"]
    for name in ("input.png", "input_canvas.png", "mask.png", "canny_condition.png", "attention_map.png",
                 "best_iter.svg", "best_iter.png", "final_svg.svg", "config.json"):
        assert os.path.isfile(os.path.join(run_dir, name)), name
    assert sorted(os.listdir(os.path.join(run_dir, "svg_logs"))) == ["svg_iter0.svg", "svg_iter2.svg",
                                                                    "svg_iter4.svg"]
    cfg = json.loads(open(os.path.join(run_dir, "config.json")).read())
    assert cfg["status"] == "done" and cfg["iterations_done"] == 5 and cfg["caption"] == "a camel"
    assert sorted(cfg["stroke_order"]) == list(range(8))
    from clipasso_studio.engine import svg_io

    w, h, shapes, _ = svg_io.load_svg(summary["best_svg"])
    assert (w, h) == (512, 512) and len(shapes) == 8
    assert abs(float(shapes[0].stroke_width) - 5.0) < 1e-3  # width scaled with the output size
    iters = [d for k, d in events if k == "iteration"]
    assert iters[0]["total"] == 5 and iters[0]["score"] is not None and iters[1]["score"] is None
    kinds = {k for k, _ in events}
    assert {"input", "condition", "attention", "iteration", "preview", "seed_done", "job_done"} <= kinds
    controlsketch.release_models()


@pytest.mark.skipif(not BUNDLED, reason="bundled models missing (run tools/fetch_models.py)")
def test_required_models():
    from clipasso_studio import settings_schema as schema
    from clipasso_studio.engine.methods import controlsketch

    s = schema.default_settings("controlsketch")
    assert controlsketch.required_models(s) == sorted(
        ["sd15", "controlnet:depth", "clip:ViT-B/32", "birefnet", "dpt-hybrid", "blip"])
    s.update(condition="canny", caption="a camel", attn_model="diffusion", object_name="camel")
    assert controlsketch.required_models(s) == sorted(["sd15", "controlnet:canny", "clip:ViT-B/32", "birefnet",
                                                       "sdxl"])
    s.update(condition="scribble", use_init_method=False)
    assert "hed" in controlsketch.required_models(s) and "sdxl" not in controlsketch.required_models(s)


# ----------------------------------------------------------------------------- SDXL attention


@pytest.mark.skipif(not model_store.is_available("sd15"), reason="needs a CLIP tokenizer (installed with sd15)")
def test_sdxl_attention_with_a_tiny_pipeline():
    from diffusers import AutoencoderKL, DDIMScheduler, StableDiffusionXLPipeline, UNet2DConditionModel
    from transformers import CLIPTextConfig, CLIPTextModel, CLIPTextModelWithProjection, CLIPTokenizer

    from clipasso_studio.engine.methods.controlsketch import sdxl_attention as S

    torch.manual_seed(0)
    unet = UNet2DConditionModel(block_out_channels=(32, 64), layers_per_block=1, sample_size=16, in_channels=4,
                                out_channels=4, down_block_types=("DownBlock2D", "CrossAttnDownBlock2D"),
                                up_block_types=("CrossAttnUpBlock2D", "UpBlock2D"), attention_head_dim=(2, 4),
                                use_linear_projection=True, addition_embed_type="text_time",
                                addition_time_embed_dim=8, transformer_layers_per_block=(1, 2),
                                projection_class_embeddings_input_dim=80, cross_attention_dim=64,
                                norm_num_groups=8)
    vae = AutoencoderKL(block_out_channels=(32, 64), in_channels=3, out_channels=3, latent_channels=4,
                        down_block_types=("DownEncoderBlock2D",) * 2, up_block_types=("UpDecoderBlock2D",) * 2,
                        norm_num_groups=8, sample_size=32)
    cfg = CLIPTextConfig(bos_token_id=49406, eos_token_id=49407, pad_token_id=49407, hidden_size=32,
                         intermediate_size=37, num_attention_heads=4, num_hidden_layers=2, vocab_size=49408,
                         projection_dim=32, hidden_act="gelu")
    tok = CLIPTokenizer.from_pretrained(str(model_store.model_dir("sd15") / "tokenizer"))
    sched = DDIMScheduler(beta_start=0.00085, beta_end=0.012, beta_schedule="scaled_linear", clip_sample=False,
                          set_alpha_to_one=False)
    pipe = StableDiffusionXLPipeline(vae=vae, text_encoder=CLIPTextModel(cfg),
                                     text_encoder_2=CLIPTextModelWithProjection(cfg), tokenizer=tok, tokenizer_2=tok,
                                     unet=unet, scheduler=sched)
    pipe.set_progress_bar_config(disable=True)
    img = Image.open(SAMPLE).convert("RGB")
    ticks = []
    attn = S.sdxl_attention(img, "camel", "cpu", 48, pipe=pipe, steps=3, tick=lambda *a: ticks.append(a))
    assert attn.shape == (48, 48)
    assert float(attn.min()) >= 0 and abs(float(attn.max()) - 1) < 1e-5
    assert S.token_index(tok, "a portrait of a camel") == 5
    assert ticks == [(i, 6, True) for i in range(7)]  # before every step: 3 of the inversion, 3 of the generation

    class Stop(Exception):
        pass

    def stop_in_the_generation(done, steps, on_cpu):
        if done == 4:
            raise Stop()

    with pytest.raises(Stop):  # (how a stop request of the job ends it)
        S.sdxl_attention(img, "camel", "cpu", 48, pipe=pipe, steps=3, tick=stop_in_the_generation)
    assert not any(isinstance(p, S._StoreProcessor) for p in pipe.unet.attn_processors.values())


def test_without_background_removal_the_whole_picture_is_sketched(tmp_path, monkeypatch):
    from clipasso_studio import settings_schema as schema
    from clipasso_studio.engine import masking
    from clipasso_studio.engine.methods import controlsketch

    img = Image.new("RGB", (120, 80), (30, 120, 200))  # a "background" colour everywhere
    path = tmp_path / "scene.png"
    img.save(path)

    def no_mask(*a, **k):
        raise AssertionError("no mask model may run without background removal")

    for name in ("soft_mask", "u2net_soft_mask", "birefnet_probability"):
        monkeypatch.setattr(masking, name, no_mask)
    s = schema.normalize({**schema.default_settings("controlsketch"), "mask_object": False, "render_size": 256})
    inp = controlsketch.prepare_input(s, str(path), torch.device("cpu"))
    assert inp["info"] is None and inp["canvas"].size == (256, 256)
    assert float(inp["mask"].min()) == 1.0  # everything counts as "object"
    r, g, b = inp["canvas"].getpixel((128, 128))
    assert abs(r - 30) < 3 and abs(b - 200) < 3  # the background is kept, not whitened
    assert schema.default_settings("controlsketch")["mask_object"] is True  # default: like the original


def test_mask_toggle_in_the_parameters():
    from clipasso_studio import settings_schema as schema

    p = next(p for p in schema.params_for("controlsketch") if p.key == "mask_object")
    assert p.default is True and not p.cli and not p.advanced
    ratio = next(p for p in schema.params_for("controlsketch") if p.key == "object_size_ratio")
    assert ratio.enabled_if({"mask_object": True}) and not ratio.enabled_if({"mask_object": False})
