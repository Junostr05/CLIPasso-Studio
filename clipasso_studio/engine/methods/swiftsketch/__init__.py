"""SwiftSketch (Arar et al., SIGGRAPH 2025) – image-to-sketch generation with a diffusion model.

Independent implementation of the inference in ``SwiftSketch/generate.py``: the input is masked,
encoded with CLIP RN101 (``layer3`` output, 1024 x 14 x 14), 32 strokes are sampled in 50 DDPM steps
with classifier-free guidance and optionally polished by the refinement network. Every denoising
step's x0 prediction is reported as a live preview and saved to ``svg_logs`` (so the GIF/MP4 export
shows the sketch emerging).

Deviation from the original: the background matte comes from U2Net instead of BRIA RMBG-1.4.
"""

from __future__ import annotations

import json
import os
import time

import numpy as np
import torch
from PIL import Image
from torchvision import transforms

from .... import settings_schema as schema
from ... import imaging, masking, model_store, svg_io
from ...jobs import SeedResult
from ...renderer import Path, ShapeGroup, render_on_white
from .diffusion import Sampler
from .model import SwiftSketchNet

CANVAS = 224
DIFFUSION_KEY = "swiftsketch:diffusion"
REFINE_KEY = "swiftsketch:refine"

_cache: dict[tuple, object] = {}


def required_models(settings: dict) -> list[str]:
    s = schema.normalize({**settings, "method": "swiftsketch"})
    needed = {DIFFUSION_KEY, model_store.clip_key("RN101"), model_store.clip_key("ViT-B/32")}
    if s["use_refine"]:
        needed.add(REFINE_KEY)
    if s["mask_object"]:
        needed.add("u2net")
    return sorted(needed)


# ----------------------------------------------------------------------------- models


def load_net(spec_key: str, device) -> tuple[SwiftSketchNet, dict]:
    key = (spec_key, str(device))
    if key not in _cache:
        ckpt = model_store.load_state(spec_key)
        net = SwiftSketchNet.from_args(ckpt["args"])
        missing, unexpected = net.load_state_dict(ckpt["state_dict"], strict=False)
        missing = [k for k in missing if not k.endswith("sequence_pos_encoder.pe")]
        if missing or unexpected:
            raise RuntimeError(f"{spec_key}: checkpoint does not match the network "
                               f"(missing {missing[:3]}, unexpected {unexpected[:3]})")
        net.requires_grad_(False)
        _cache[key] = (net.to(device).eval(), ckpt["args"])
    return _cache[key]


class ClipMiddleFeatures:
    """Output of CLIP RN101 ``layer3`` (``CLIPMidlleFeutures(device, 3)`` in the original)."""

    def __init__(self, device):
        from ...clip_ import clip

        self.device = device
        model, preprocess = clip.load("RN101", device=device)
        self.visual = model.visual.eval()
        self.to_tensor = transforms.Compose([transforms.Resize((CANVAS, CANVAS)), transforms.ToTensor()])
        t = preprocess.transforms
        self.normalize = transforms.Compose([t[0], t[1], t[-1]])  # resize, center crop, normalize

    def __call__(self, image: Image.Image) -> torch.Tensor:
        m = self.visual
        x = self.normalize(self.to_tensor(image.convert("RGB"))).unsqueeze(0).to(self.device)
        with torch.no_grad():
            x = x.type(m.conv1.weight.dtype)
            for conv, bn in ((m.conv1, m.bn1), (m.conv2, m.bn2), (m.conv3, m.bn3)):
                x = m.relu(bn(conv(x)))
            x = m.avgpool(x)
            x = m.layer3(m.layer2(m.layer1(x)))
        return x.float()  # [1, 1024, 14, 14]


def _features_model(device) -> ClipMiddleFeatures:
    key = ("clip-middle", str(device))
    if key not in _cache:
        _cache[key] = ClipMiddleFeatures(device)
    return _cache[key]


def release_models() -> None:
    _cache.clear()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


# ----------------------------------------------------------------------------- input


def prepare_input(settings: dict, target: str, device) -> tuple[Image.Image, Image.Image]:
    """-> (network input image, mask image) like generate.py: mask -> masked image -> fix_scale."""
    from ...pipeline import load_rgb

    key = ("input", os.path.abspath(target), os.path.getmtime(target), bool(settings["mask_object"]),
           bool(settings["fix_scale"]))
    if key in _cache:  # same image for every seed of a job
        return _cache[key]
    for k in [k for k in _cache if k[0] == "input"]:
        del _cache[k]
    image = load_rgb(target)
    if settings["mask_object"]:
        matte = masking.u2net_soft_mask(device, image)
        image = masking.apply_soft_mask(image, matte)
        mask_img = Image.fromarray((matte * 255 + 0.5).astype(np.uint8), mode="L")
    else:
        mask_img = Image.new("L", image.size, 255)
    if settings["fix_scale"]:
        image = imaging.fix_image_scale(image)
        mask_img = imaging.fix_image_scale(mask_img, fill=0)
    _cache[key] = (image, mask_img)
    return image, mask_img


# ----------------------------------------------------------------------------- output


def denormalize(points: torch.Tensor, scaling_factor: float, size: int = CANVAS) -> torch.Tensor:
    """Network output ([-s, s]) -> canvas coordinates ([0, size])."""
    return (points / scaling_factor + 1) / 2 * size


def to_scene(points: torch.Tensor, width: float):
    """[strokes, 4, 2] canvas points -> (shapes, groups) of cubic Bézier strokes."""
    shapes, groups = [], []
    black = torch.tensor([0.0, 0.0, 0.0, 1.0])
    for i, cp in enumerate(points.detach().float().cpu()):
        shapes.append(Path(num_control_points=torch.tensor([2]), points=cp, stroke_width=torch.tensor(width)))
        groups.append(ShapeGroup(shape_ids=torch.tensor([i]), fill_color=None, stroke_color=black))
    return shapes, groups


def scene_svg(points: torch.Tensor, width: float) -> str:
    shapes, groups = to_scene(points, width)
    return svg_io.scene_to_svg(CANVAS, CANVAS, shapes, groups)


def render_png(points: torch.Tensor, width: float) -> Image.Image:
    shapes, groups = to_scene(points, width)
    with torch.no_grad():
        img = render_on_white(CANVAS, CANVAS, shapes, groups)
    return imaging.tensor_to_pil(img.permute(2, 0, 1))


def _write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# ----------------------------------------------------------------------------- run


def run_single(settings, target, run_dir, seed, reporter=None, control=None, device=None) -> SeedResult:
    from ...pipeline import Cancelled, Control, Reporter, _png_bytes, resolve_device, score_run, set_seed

    reporter = reporter or Reporter()
    control = control or Control()
    s = schema.normalize({**settings, "method": "swiftsketch"})
    if device is None:
        device, warning = resolve_device(s)
        if warning:
            code, _, text = warning.partition(":")
            reporter.event("warning", message=text, code=code)

    os.makedirs(run_dir, exist_ok=True)
    svg_logs = os.path.join(run_dir, "svg_logs")
    os.makedirs(svg_logs, exist_ok=True)
    run_name = os.path.basename(run_dir.rstrip("/\\"))
    set_seed(seed)
    width = float(s["width"])

    reporter.event("stage", seed=seed, name="loading")
    net, args = load_net(DIFFUSION_KEY, device)
    refine = load_net(REFINE_KEY, device)[0] if s["use_refine"] else None
    features_model = _features_model(device)

    image, mask_img = prepare_input(s, target, device)
    input_img = image.resize((CANVAS, CANVAS), Image.BICUBIC)
    input_img.save(os.path.join(run_dir, "input.png"))
    mask_img.save(os.path.join(run_dir, "mask.png"))
    reporter.event("input", seed=seed, png=_png_bytes(input_img), mask_png=_png_bytes(mask_img))

    reporter.event("stage", seed=seed, name="init")
    feats = features_model(image).to(device)
    scaling = float(args.get("scaling_factor", 2.0))
    num_paths = int(args.get("num_paths", 32))
    sampler = Sampler(int(args.get("diffusion_steps", 50)), float(args.get("cos_power", 0.4)))
    guidance = float(s["guidance_param"])
    total = sampler.steps + (1 if refine is not None else 0)
    shape = (1, num_paths, net.ncpoints, net.nfeats)
    generator = torch.Generator().manual_seed(int(seed))

    reporter.event("stage", seed=seed, name="optimizing")
    status = "done"
    counter = 0
    x = final = None
    start = time.time()
    active_time = 0.0

    def step_done(it: int, points_norm: torch.Tensor) -> None:
        nonlocal counter, active_time
        svg_text = scene_svg(denormalize(points_norm[0], scaling), width)
        _write(os.path.join(svg_logs, f"svg_iter{it}.svg"), svg_text)
        counter += 1
        active_time = time.time() - start
        per_it = active_time / counter
        reporter.event("iteration", seed=seed, it=it, total=total, loss=None, loss_eval=None, best_loss=None,
                       best_iter=it, losses={}, elapsed=active_time, eta=per_it * (total - counter))
        reporter.event("preview", seed=seed, it=it, svg=svg_text)

    try:
        with torch.no_grad():
            for i, x, x0 in sampler.sample(lambda xt, t: net.guided(xt, t, feats, guidance), shape, device,
                                           generator=generator):
                step_done(sampler.steps - 1 - i, x0)
                if control.should_stop():
                    raise Cancelled()
                paused_at = time.time()
                control.wait_if_paused()
                start += time.time() - paused_at
            final = x
            if s["save_diffusion_sketch"]:
                _write(os.path.join(run_dir, "diffusion_sketch.svg"), scene_svg(denormalize(x[0], scaling), width))
            if refine is not None:
                final = refine(x, torch.zeros(1, dtype=torch.long, device=device), feats)
                step_done(sampler.steps, final)
    except Cancelled:
        status = "cancelled"

    best_svg = os.path.join(run_dir, "best_iter.svg")
    result_pts = final if final is not None else x
    if result_pts is not None:
        pts = denormalize(result_pts[0], scaling)
        svg_text = scene_svg(pts, width)
        _write(best_svg, svg_text)
        _write(os.path.join(run_dir, "final_svg.svg"), svg_text)
        render_png(pts, width).save(os.path.join(run_dir, "best_iter.png"))

    clip_sc = score_run(best_svg, input_img, device, reporter) if os.path.isfile(best_svg) else None
    best_loss = round(1.0 - clip_sc / 100.0, 4) if clip_sc is not None else 1.0  # CLIP distance, lower = better
    config = {
        "method": "swiftsketch", "target": target, "seed": seed, "output_dir": run_dir, "device": str(device),
        "model_args": args, "num_paths": num_paths, "diffusion_steps": sampler.steps,
        "best_loss": best_loss, "best_iter": max(counter - 1, 0), "iterations_done": counter, "status": status,
        "seconds": active_time, "clip_score": clip_sc, "settings": s,
    }
    with open(os.path.join(run_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, default=str)

    result = SeedResult(seed=seed, run_name=run_name, run_dir=run_dir, best_loss=best_loss,
                        best_iter=config["best_iter"], iterations_done=counter, best_svg=best_svg, status=status,
                        method="swiftsketch", clip_score=clip_sc, seconds=round(active_time, 1))
    svg_out = open(best_svg, encoding="utf-8").read() if os.path.isfile(best_svg) else ""
    reporter.event("seed_done", seed=seed, best_loss=best_loss, best_iter=result.best_iter, status=status,
                   run_dir=run_dir, svg=svg_out, clip_score=clip_sc)
    return result
