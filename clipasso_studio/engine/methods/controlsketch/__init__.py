"""ControlSketch (from the SwiftSketch paper, Arar et al., SIGGRAPH 2025) – SDS-based vector sketching.

Independent implementation of ``ControlSketch/object_sketching.py``: the masked input is reduced to
``object_size_ratio`` of the canvas, strokes start at attention-weighted K-means points, and the
control points are optimised with an SDS loss from Stable Diffusion 1.5 steered by a ControlNet
condition (depth by default) of the input. At the end the strokes are sorted (outline first, then by
attention) and the object is scaled back to its original size.

Deviations: BiRefNet (or U2Net) matte instead of BRIA RMBG-1.4, BLIP instead of BLIP-2 for automatic captions,
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
from ... import checkpoint, details, imaging, masking
from ...jobs import SeedResult
from ...renderer import render_on_white
from . import painter as P
from ..requirements import controlsketch as required_models  # noqa: F401
from ..requirements import controlsketch_uses_sdxl as uses_sdxl

_cache: dict[tuple, object] = {}
TURBO_RENDER = 384  # turbo mode: canvas of the optimisation instead of the default 512 (stroke width scaled)


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

    from ... import framing

    size = int(s["render_size"])
    image = load_rgb(target)
    frame = framing.photo_frame(image.size, pad=framing.fix_scale_pad(*image.size) if s["fix_scale"] else None)
    detail = details.detail_map(image)  # the detail brush, carried along as a picture through the same steps
    detail_img = details.as_image(detail) if detail is not None else None
    masked = bool(s.get("mask_object", True))
    if masked:
        matte = masking.soft_mask(device, image, s.get("mask_model", "u2net"))
        image = masking.apply_soft_mask(image, matte)
    else:  # the whole picture, background included
        matte = np.ones((image.height, image.width), dtype=np.float32)
    if detail is not None:  # less detail wanted: the picture is softened there
        image = details.soften(image, detail)
    if s["fix_scale"]:
        image = imaging.fix_image_scale(image)
        if detail_img is not None:
            detail_img = imaging.fix_image_scale(detail_img)
        h, w = matte.shape
        side = max(h, w) + 20
        padded = np.zeros((side, side), dtype=np.float32)
        y, x = side // 2 - h // 2, side // 2 - w // 2
        padded[y:y + h, x:x + w] = matte
        matte = padded
    image = image.resize((size, size), Image.BICUBIC)
    mask = F.interpolate(torch.from_numpy(matte)[None, None], (size, size))[0, 0]
    if detail_img is not None:
        detail_img = detail_img.resize((size, size), Image.BILINEAR)
    if not masked:  # no object to shrink: the picture fills the canvas
        return {"full": image, "full_mask": mask, "canvas": image, "mask": mask, "info": None, "frame": frame,
                "detail": details.from_image(detail_img) if detail_img is not None else None}
    canvas_img, canvas_mask, info = P.shrink_object(image, mask, float(s["object_size_ratio"]))
    if detail_img is not None:  # the same shrinking (around the same mask)
        detail_img = P.shrink_object(detail_img, mask, float(s["object_size_ratio"]))[0]
    return {"full": image, "full_mask": mask, "canvas": canvas_img, "mask": canvas_mask, "info": info,
            "frame": frame, "detail": details.from_image(detail_img) if detail_img is not None else None}


def _cached(key, fn):
    if key not in _cache:
        _cache[key] = fn()
    return _cache[key]


def _load_array(path: str) -> torch.Tensor | None:
    try:
        return torch.from_numpy(np.load(path))
    except (OSError, ValueError, EOFError):  # not there (or not complete)
        return None


def _save_array(path: str, t: torch.Tensor) -> None:
    with open(path + ".tmp", "wb") as f:
        np.save(f, t.float().cpu().numpy())
    os.replace(path + ".tmp", path)


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
    width = float(s["width"])
    turbo = schema.turbo(s)
    if turbo and size == 512:  # a smaller canvas; the output looks the same (widths scale with it)
        size, width = TURBO_RENDER, width * TURBO_RENDER / size
    out_size = int(s["output_svg_size"])
    condition = s["condition"]
    stamp = (os.path.abspath(target), os.path.getmtime(target), str(device), s["fix_scale"], size,
             s["object_size_ratio"], s["mask_object"], s.get("mask_model", "u2net"), masking.edited_stamp(target),
             details.detail_stamp(target))

    # --------------------------------------------------------------- input
    reporter.event("stage", seed=seed, name="mask" if s["mask_object"] and s.get("mask_model", "u2net") != "u2net"
                   else "loading")
    inp = _cached(("input",) + stamp, lambda: prepare_input({**s, "render_size": size}, target, device))
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
    reporter.event("log", message=f"seed {seed}: SDS prompt: \"{caption}\"", code="sds_prompt", seed=seed,
                   caption=caption)

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
        stopped = False
        if uses_sdxl(s):
            from .sdxl_attention import object_attention

            def tick(done, steps, mode, elapsed):  # SDXL piece by piece or on the CPU takes long: progress,
                if control.should_stop():  # pause and stop in between
                    raise Cancelled()
                control.wait_if_paused()
                if mode != "gpu":
                    reporter.event("stage", seed=seed, name=f"init_sdxl_{mode}", step=done, steps=steps,
                                   elapsed=round(elapsed, 1))

            def log(code, **params):
                reporter.event("log", message=f"seed {seed}: the SDXL attention does not fit on the graphics card "
                                              f"({code})", code=code, seed=seed, **params)

            object_name = schema.text_value(s["object_name"])
            saved = os.path.join(run_dir, "sdxl_attention.npy")  # continuing the run does not compute it again
            try:
                attn = _load_array(saved)
                if attn is None:
                    attn = _cached(("sdxl", object_name) + stamp, lambda: object_attention(
                        inp["canvas"], object_name, device, size, place=s["sdxl_place"], tick=tick, log=log))
                    _save_array(saved, attn)
            except Cancelled:  # stopped during it: the strokes start evenly, the run ends before its first step
                attn, stopped = torch.ones(size, size), True
        else:
            attn = _cached(("clip-attn",) + stamp, lambda: clip_attention(target_t, size, device))
        if inp.get("detail") is not None:  # the detail brush: more start strokes where more detail is wanted
            g = torch.from_numpy(details.gain(inp["detail"]))
            if tuple(g.shape) != tuple(attn.shape):
                g = F.interpolate(g[None, None], tuple(attn.shape))[0, 0]
            attn = attn * g.to(attn.device, attn.dtype)
        points_key = ("points", int(s["num_strokes"]), s["attn_model"], schema.text_value(s["object_name"])) + stamp
        points, _ = init_points(attn, inp["mask"], int(s["num_strokes"])) if stopped else \
            _cached(points_key, lambda: init_points(attn, inp["mask"], int(s["num_strokes"])))
        start = (points / size).tolist()
        shown = torch.pow(attn, 2) * inp["mask"]
        preview = imaging.attention_overlay(target_t, shown.cpu().numpy(), points[:, ::-1])
        preview.save(os.path.join(run_dir, "attention_map.png"))
        reporter.event("attention", seed=seed, png=_png_bytes(preview))
    painter = P.StrokePainter(int(s["num_strokes"]), int(s["num_segments"]), int(s["control_points_per_seg"]),
                              width, size, device, start)
    painter.init_strokes()

    # --------------------------------------------------------------- SDS loss
    reporter.event("stage", seed=seed, name="diffusion_models")

    def load_models():
        unet, controlnet, vae, tokenizer, text_encoder, alphas = sds.load_sd15(condition, device)
        return {"unet": unet, "controlnet": controlnet, "vae": vae, "tokenizer": tokenizer,
                "text_encoder": text_encoder, "alphas": alphas}

    dtype = sds.model_dtype(device)  # (the precision setting may change between jobs of the warm worker)
    sd_key = ("sd", (condition, str(device), str(dtype)))
    text_key = ("text", caption, str(device), str(dtype))
    for k in [k for k in _cache if k[0] == "sd" and k != sd_key]:
        del _cache[k]  # another ControlNet / device: free the memory first
    if text_key not in _cache and sd_key in _cache and _cache[sd_key]["text_encoder"] is None:
        del _cache[sd_key]  # a new caption needs the (released) text encoder again
    models = _cached(sd_key, load_models)
    if text_key not in _cache:
        _cache[text_key] = sds.embed_text(models["tokenizer"], models["text_encoder"], caption, device)
        models["text_encoder"] = None  # like the original: only the embeddings are needed afterwards
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    text, empty = _cache[text_key]
    vae = models["vae"]
    if turbo:
        vae = _cached(("taesd", str(device), str(dtype)), lambda: sds.load_taesd(device))
    loss_fn = sds.ControlSDSLoss(models["unet"], models["controlnet"], vae, text, empty,
                                 conditions.condition_tensor(cond_img, size, device, dtype), models["alphas"],
                                 guidance_scale=s["diffusion_guidance_scale"],
                                 conditioning_scale=s["conditioning_scale"],
                                 diffusion_timesteps=s["diffusion_timesteps"], device=device,
                                 bf16=turbo and device.type == "cpu" and sds.cpu_bf16_fast())
    optimizer = torch.optim.Adam(painter.parameters(), lr=float(s["lr"]), betas=(0.9, 0.9), eps=1e-6)
    scorer = get_scorer(device)

    # --------------------------------------------------------------- optimisation
    reporter.event("stage", seed=seed, name="optimizing")
    total = int(s["num_iter"]) + 1
    interval = max(int(s["save_interval"]), 1)
    score_every = checkpoint.score_interval(interval)  # the CLIP score about every 100 iterations
    status = "done"
    counter = 0
    scores: list[tuple[int, float]] = []
    losses: list[float] = []
    start_time = time.time()
    active_time = 0.0
    first_epoch = 0
    ck = checkpoint.load(run_dir)
    if ck is not None:  # continue an interrupted run where it stopped
        for shape, points in zip(painter.shapes, ck["points"]):
            shape.points = points.to(device)
        optimizer = torch.optim.Adam(painter.parameters(), lr=float(s["lr"]), betas=(0.9, 0.9), eps=1e-6)
        optimizer.load_state_dict(ck["optim"])
        counter, first_epoch = int(ck["counter"]), int(ck["epoch"]) + 1
        scores, losses = [tuple(x) for x in ck["scores"]], list(ck["losses"])
        active_time = float(ck["active_time"])
        start_time = time.time() - active_time
        checkpoint.set_rng_state(ck["rng"])
        reporter.event("log", message=f"seed {seed}: continuing at iteration {first_epoch}", code="resume_at",
                       seed=seed, it=first_epoch)

    def save_checkpoint(done_epoch: int, painter=painter, optimizer=optimizer):
        checkpoint.save(run_dir, {"epoch": done_epoch, "counter": counter, "points": painter.points(),
                                  "optim": optimizer.state_dict(), "scores": scores, "losses": losses,
                                  "active_time": active_time})

    saver = checkpoint.Timer()
    previews = checkpoint.Timer(checkpoint.PREVIEW_S, due_now=True)
    try:
        for epoch in range(first_epoch, total):
            if control.should_stop():
                if epoch > first_epoch or ck is not None:
                    save_checkpoint(epoch - 1)  # "Continue" goes on from here
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
                if epoch % score_every == 0 or epoch == total - 1:
                    score = round(scorer.score_tensors(sketch.detach().float().cpu(), target_t.float().cpu()), 2)
                    scores.append((epoch, score))
            counter += 1
            active_time = time.time() - start_time
            per_it = active_time / counter
            reporter.event("iteration", seed=seed, it=epoch, total=total, loss=losses[-1], loss_eval=None,
                           best_loss=None, best_iter=epoch, losses={"sds": losses[-1]}, score=score,
                           elapsed=active_time, eta=per_it * (total - counter))
            if svg_text is not None and (previews.due() or score is not None):
                reporter.event("preview", seed=seed, it=epoch, svg=svg_text)
            if saver.due():
                save_checkpoint(epoch)
    except Cancelled:
        status = "cancelled"
    if status == "done":
        checkpoint.remove(run_dir)

    # --------------------------------------------------------------- final sketch
    order = None
    if s["sort_final_sketch"]:
        # without a mask there is no object outline to start with: sorted by attention only
        outline = inp["mask"] if s["mask_object"] else torch.zeros_like(inp["mask"])
        order = P.sort_by_contour_and_attn(painter, outline, attn if attn is not None
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
        "caption": caption, "object_scale": inp["info"], "canvas": size, "photo_frame": inp.get("frame"),
        "best_loss": best_loss,
        "best_iter": max(counter - 1, 0),
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
