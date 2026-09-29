"""ControlSketch (from the SwiftSketch paper, Arar et al., SIGGRAPH 2025) – SDS-based vector sketching.

Independent implementation of ``ControlSketch/object_sketching.py``: the masked input is reduced to
``object_size_ratio`` of the canvas, strokes start at attention-weighted K-means points, and the
control points are optimised with an SDS loss from Stable Diffusion 1.5 steered by a ControlNet
condition (depth by default) of the input. At the end the strokes are sorted (outline first, then by
attention) and the object is scaled back to its original size.

Deviations: U2Net matte instead of BRIA RMBG-1.4, BLIP instead of BLIP-2 for automatic captions,
CLIP attention as the default initialisation, the PyTorch rasterizer instead of diffvg; see
``conditions.py`` for the condition images.
"""

from __future__ import annotations

import json
import os
import time

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from torchvision import transforms

from .... import settings_schema as schema
from ... import imaging, masking, model_store
from ...jobs import SeedResult
from ...renderer import render_on_white
from . import painter as P
from .conditions import DETECTOR_MODELS

_cache: dict[tuple, object] = {}


def required_models(settings: dict) -> list[str]:
    s = schema.normalize({**settings, "method": "controlsketch"})
    needed = {"sd15", f"controlnet:{s['condition']}", model_store.clip_key("ViT-B/32"), "u2net"}
    if DETECTOR_MODELS.get(s["condition"]):
        needed.add(DETECTOR_MODELS[s["condition"]])
    if not schema.text_value(s["caption"]):
        needed.add("blip")
    if uses_sdxl(s):
        needed.add("sdxl")
    return sorted(needed)


def uses_sdxl(s: dict) -> bool:
    return bool(s["use_init_method"]) and s["attn_model"] == "diffusion" and bool(schema.text_value(s["object_name"]))


def release_models() -> None:
    _cache.clear()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


# ----------------------------------------------------------------------------- preparation


def prepare_input(s: dict, target: str, device):
    """``get_target``: masked input at render size, object reduced to object_size_ratio.

    -> dict(full=PIL, full_mask=tensor, canvas=PIL, mask=tensor, info=scale info or None)
    """
    from ...pipeline import load_rgb

    size = int(s["render_size"])
    image = load_rgb(target)
    matte = masking.u2net_soft_mask(device, image)
    image = masking.apply_soft_mask(image, matte)
    if s["fix_scale"]:
        image = imaging.fix_image_scale(image)
        h, w = matte.shape
        side = max(h, w) + 20
        padded = np.zeros((side, side), dtype=np.float32)
        y, x = side // 2 - h // 2, side // 2 - w // 2
        padded[y:y + h, x:x + w] = matte
        matte = padded
    image = image.resize((size, size), Image.BICUBIC)
    mask = F.interpolate(torch.from_numpy(matte)[None, None], (size, size))[0, 0]
    canvas_img, canvas_mask, info = P.shrink_object(image, mask, float(s["object_size_ratio"]))
    return {"full": image, "full_mask": mask, "canvas": canvas_img, "mask": canvas_mask, "info": info}


def _cached(key, fn):
    if key not in _cache:
        _cache[key] = fn()
    return _cache[key]


def _png_mask(mask: torch.Tensor) -> Image.Image:
    return Image.fromarray(((mask >= 0.5).float().cpu().numpy() * 255).astype(np.uint8), mode="L")


# ----------------------------------------------------------------------------- run


def run_single(settings, target, run_dir, seed, reporter=None, control=None, device=None) -> SeedResult:
    from ...pipeline import Cancelled, Control, Reporter, _png_bytes, resolve_device, score_run, set_seed
    from ...scoring import get_scorer
    from . import conditions, sds
    from .init import clip_attention, init_points

    reporter = reporter or Reporter()
    control = control or Control()
    s = schema.normalize({**settings, "method": "controlsketch"})
    if device is None:
        device, warning = resolve_device(s)
        if warning:
            code, _, text = warning.partition(":")
            reporter.event("warning", message=text, code=code)
    if device.type != "cuda":
        reporter.event("warning", code="controlsketch_cpu",
                       message="ControlSketch runs on the CPU – this takes hours; an NVIDIA GPU is recommended.")

    os.makedirs(run_dir, exist_ok=True)
    svg_logs = os.path.join(run_dir, "svg_logs")
    os.makedirs(svg_logs, exist_ok=True)
    run_name = os.path.basename(run_dir.rstrip("/\\"))
    set_seed(seed)
    size = int(s["render_size"])
    out_size = int(s["output_svg_size"])
    condition = s["condition"]
    stamp = (os.path.abspath(target), os.path.getmtime(target), str(device), s["fix_scale"], size,
             s["object_size_ratio"])

    # --------------------------------------------------------------- input
    reporter.event("stage", seed=seed, name="loading")
    inp = _cached(("input",) + stamp, lambda: prepare_input(s, target, device))
    inp["full"].save(os.path.join(run_dir, "input.png"))
    inp["canvas"].save(os.path.join(run_dir, "input_canvas.png"))
    mask_img = _png_mask(inp["full_mask"])
    mask_img.save(os.path.join(run_dir, "mask.png"))
    reporter.event("input", seed=seed, png=_png_bytes(inp["full"]), mask_png=_png_bytes(mask_img))

    # --------------------------------------------------------------- caption
    caption = schema.text_value(s["caption"])
    if not caption:
        reporter.event("stage", seed=seed, name="caption")
        from .caption import caption_image

        caption = _cached(("caption",) + stamp, lambda: caption_image(inp["canvas"], device))
    reporter.event("log", message=f"seed {seed}: SDS prompt: \"{caption}\"")

    # --------------------------------------------------------------- condition
    reporter.event("stage", seed=seed, name="condition")
    cond_img = _cached(("condition", condition) + stamp, lambda: conditions.masked_condition(
        conditions.create_condition(inp["canvas"], condition, device), inp["mask"], size))
    cond_img.save(os.path.join(run_dir, f"{condition}_condition.png"))
    reporter.event("condition", seed=seed, png=_png_bytes(cond_img), condition=condition)

    # --------------------------------------------------------------- stroke initialisation
    reporter.event("stage", seed=seed, name="init")
    target_t = transforms.ToTensor()(inp["canvas"]).unsqueeze(0).to(device)
    attn = None
    start = None
    if s["use_init_method"]:
        if uses_sdxl(s):
            from .sdxl_attention import sdxl_attention

            object_name = schema.text_value(s["object_name"])
            attn = _cached(("sdxl", object_name) + stamp, lambda: sdxl_attention(inp["canvas"], object_name, device,
                                                                                  size))
        else:
            attn = _cached(("clip-attn",) + stamp, lambda: clip_attention(target_t, size, device))
        points, _ = _cached(("points", int(s["num_strokes"]), s["attn_model"], schema.text_value(s["object_name"]))
                            + stamp, lambda: init_points(attn, inp["mask"], int(s["num_strokes"])))
        start = (points / size).tolist()
        shown = torch.pow(attn, 2) * inp["mask"]
        preview = imaging.attention_overlay(target_t, shown.cpu().numpy(), points[:, ::-1])
        preview.save(os.path.join(run_dir, "attention_map.png"))
        reporter.event("attention", seed=seed, png=_png_bytes(preview))
    painter = P.StrokePainter(int(s["num_strokes"]), int(s["num_segments"]), int(s["control_points_per_seg"]),
                              float(s["width"]), size, device, start)
    painter.init_strokes()

    # --------------------------------------------------------------- SDS loss
    reporter.event("stage", seed=seed, name="diffusion_models")

    def load_models():
        unet, controlnet, vae, tokenizer, text_encoder, alphas = sds.load_sd15(condition, device)
        return {"unet": unet, "controlnet": controlnet, "vae": vae, "tokenizer": tokenizer,
                "text_encoder": text_encoder, "alphas": alphas}

    for k in [k for k in _cache if k[0] == "sd" and k[1] != (condition, str(device))]:
        del _cache[k]  # another ControlNet / device: free the memory first
    models = _cached(("sd", (condition, str(device))), load_models)
    text, empty = _cached(("text", caption, str(device)),
                          lambda: sds.embed_text(models["tokenizer"], models["text_encoder"], caption, device))
    dtype = sds.model_dtype(device)
    loss_fn = sds.ControlSDSLoss(models["unet"], models["controlnet"], models["vae"], text, empty,
                                 conditions.condition_tensor(cond_img, size, device, dtype), models["alphas"],
                                 guidance_scale=s["diffusion_guidance_scale"],
                                 conditioning_scale=s["conditioning_scale"],
                                 diffusion_timesteps=s["diffusion_timesteps"], device=device)
    optimizer = torch.optim.Adam(painter.parameters(), lr=float(s["lr"]), betas=(0.9, 0.9), eps=1e-6)
    scorer = get_scorer(device)

    # --------------------------------------------------------------- optimisation
    reporter.event("stage", seed=seed, name="optimizing")
    total = int(s["num_iter"]) + 1
    interval = max(int(s["save_interval"]), 1)
    status = "done"
    counter = 0
    scores: list[tuple[int, float]] = []
    losses: list[float] = []
    start_time = time.time()
    active_time = 0.0
    try:
        for epoch in range(total):
            if control.should_stop():
                raise Cancelled()
            paused_at = time.time()
            control.wait_if_paused()
            start_time += time.time() - paused_at
            optimizer.zero_grad()
            sketch = painter.get_image().to(device)
            loss = loss_fn(sketch)
            loss.backward()
            optimizer.step()
            losses.append(float(loss.item()))
            svg_text = score = None
            if epoch % interval == 0 or epoch == total - 1:
                svg_text = P.output_svg(painter, inp["info"], out_size)
                with open(os.path.join(svg_logs, f"svg_iter{epoch}.svg"), "w", encoding="utf-8") as f:
                    f.write(svg_text)
                score = round(scorer.score_tensors(sketch.detach().float().cpu(), target_t.float().cpu()), 2)
                scores.append((epoch, score))
            counter += 1
            active_time = time.time() - start_time
            per_it = active_time / counter
            reporter.event("iteration", seed=seed, it=epoch, total=total, loss=losses[-1], loss_eval=None,
                           best_loss=None, best_iter=epoch, losses={"sds": losses[-1]}, score=score,
                           elapsed=active_time, eta=per_it * (total - counter))
            if svg_text is not None:
                reporter.event("preview", seed=seed, it=epoch, svg=svg_text)
    except Cancelled:
        status = "cancelled"

    # --------------------------------------------------------------- final sketch
    order = None
    if s["sort_final_sketch"]:
        order = P.sort_by_contour_and_attn(painter, inp["mask"], attn if attn is not None
                                           else torch.zeros(size, size))
    shapes, groups = P.output_scene(painter, inp["info"], out_size, order)
    from ... import svg_io

    svg_text = svg_io.scene_to_svg(out_size, out_size, shapes, groups)
    best_svg = os.path.join(run_dir, "best_iter.svg")
    for name in ("best_iter.svg", "final_svg.svg"):
        with open(os.path.join(run_dir, name), "w", encoding="utf-8") as f:
            f.write(svg_text)
    with torch.no_grad():
        png = imaging.tensor_to_pil(render_on_white(out_size, out_size, shapes, groups).permute(2, 0, 1))
    png.save(os.path.join(run_dir, "best_iter.png"))

    clip_sc = score_run(best_svg, inp["full"], device, reporter)
    best_loss = round(1.0 - clip_sc / 100.0, 4) if clip_sc is not None else 1.0
    config = {
        "method": "controlsketch", "target": target, "seed": seed, "output_dir": run_dir, "device": str(device),
        "caption": caption, "object_scale": inp["info"], "best_loss": best_loss, "best_iter": max(counter - 1, 0),
        "iterations_done": counter, "status": status, "seconds": active_time, "clip_score": clip_sc,
        "clip_scores": scores, "sds_loss": losses, "stroke_order": order, "settings": s,
    }
    with open(os.path.join(run_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, default=str)

    result = SeedResult(seed=seed, run_name=run_name, run_dir=run_dir, best_loss=best_loss,
                        best_iter=config["best_iter"], iterations_done=counter, best_svg=best_svg, status=status,
                        method="controlsketch", clip_score=clip_sc, seconds=round(active_time, 1))
    reporter.event("seed_done", seed=seed, best_loss=best_loss, best_iter=result.best_iter, status=status,
                   run_dir=run_dir, svg=svg_text, clip_score=clip_sc)
    del loss_fn, optimizer, painter
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return result
