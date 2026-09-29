"""Sketch generation pipeline – port of ``painterly_rendering.py`` + ``run_object_sketching.py``.

The optimisation loop, evaluation, best-iteration tracking and early termination follow the
original code. Additions: progress reporting, pause/cancel, real multi-stage training and
JSON result files for the GUI.
"""

from __future__ import annotations

import io
import json
import math
import os
import random
import time
from types import SimpleNamespace
from typing import Any

import numpy as np
import torch
from PIL import Image
from torchvision import transforms
from torchvision.transforms import InterpolationMode

from .. import settings_schema as schema
from . import imaging, masking
from .jobs import SeedResult, finish_job, job_seeds, make_job_dir, run_name_for  # noqa: F401


class Cancelled(Exception):
    pass


class Reporter:
    """Receives progress events. The default implementation ignores everything."""

    def event(self, kind: str, **data: Any) -> None:  # pragma: no cover - interface
        pass


class PrintReporter(Reporter):
    def __init__(self):
        self._last = 0.0

    def event(self, kind, **data):
        if kind == "iteration":
            now = time.time()
            if now - self._last < 2 and data["it"] + 1 != data["total"]:
                return
            self._last = now
            print(f"[seed {data['seed']}] iter {data['it'] + 1}/{data['total']}  loss {data['loss']:.4f}  "
                  f"best {data['best_loss']:.4f}  ETA {imaging.eta_string(data['eta'])}", flush=True)
        elif kind in ("log", "warning"):
            print(data.get("message", ""), flush=True)
        elif kind == "seed_done":
            print(f"[seed {data['seed']}] done – best loss {data['best_loss']:.4f} at iter {data['best_iter']}",
                  flush=True)
        elif kind == "job_done":
            print(f"Best sketch: {data['best_svg']}", flush=True)


class Control:
    """Pause / cancel switches polled by the optimisation loop."""

    def should_stop(self) -> bool:
        return False

    def wait_if_paused(self) -> None:
        pass


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    os.environ['PYTHONHASHSEED'] = str(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def cuda_arch_supported(idx: int) -> bool:
    """False if the GPU's compute capability has no kernels in this PyTorch build."""
    try:
        major, minor = torch.cuda.get_device_capability(idx)
        archs = torch.cuda.get_arch_list()
    except Exception:
        return True
    if not archs:
        return True
    cap = major * 10 + minor
    for a in archs:
        kind, _, num = a.partition("_")
        if not num.isdigit():
            continue
        n = int(num)
        if kind == "sm" and n // 10 == major and n <= cap:
            return True  # binary compatible within the same major version
        if kind == "compute" and n <= cap:
            return True  # PTX can be JIT-compiled for newer GPUs
    return False


def resolve_device(settings: dict) -> tuple[torch.device, str | None]:
    """-> (device, warning)."""
    wanted = settings.get("device", "auto")
    if wanted == "cpu":
        return torch.device("cpu"), None
    if torch.cuda.is_available() and torch.cuda.device_count() > 0:
        idx = min(int(settings.get("gpunum", 0)), torch.cuda.device_count() - 1)
        if not cuda_arch_supported(idx):
            name = torch.cuda.get_device_name(idx)
            return torch.device("cpu"), (f"gpu_unsupported:The GPU '{name}' is not supported by this "
                                         "PyTorch build – running on the CPU instead.")
        return torch.device(f"cuda:{idx}"), None
    if wanted == "cuda":
        return torch.device("cpu"), ("cuda_unavailable:CUDA is not available – running on the CPU instead "
                                     "(much slower).")
    return torch.device("cpu"), None


def build_args(settings: dict, target: str, seed: int, run_dir: str, device: torch.device) -> SimpleNamespace:
    s = schema.normalize(settings)
    args = SimpleNamespace(**s)
    args.target = target
    args.seed = seed
    args.output_dir = run_dir
    args.device = device
    args.use_gpu = device.type == "cuda"
    args.clip_conv_layer_weights = schema.parse_layer_weights(s["clip_conv_layer_weights"])
    mode = s["mask_object_attention"]
    args.mask_object_attention = bool(s["mask_object"]) if mode == "auto" else mode == "on"
    for key in ("mask_object", "fix_scale", "attention_init", "xdog_intersec", "clip_conv_loss", "train_with_clip",
                "include_target_in_aug", "augment_both", "force_sparse", "lr_scheduler"):
        args.__dict__[key] = int(bool(getattr(args, key)))
    return args


def load_rgb(path: str) -> Image.Image:
    target = Image.open(path)
    if target.mode in ("RGBA", "LA") or (target.mode == "P" and "transparency" in target.info):
        target = target.convert("RGBA")
        new_image = Image.new("RGBA", target.size, "WHITE")
        new_image.paste(target, (0, 0), target)
        target = new_image
    return target.convert("RGB")


def _canvas_transform(size, scale: int, nearest: bool = False):
    interp = InterpolationMode.NEAREST if nearest else InterpolationMode.BICUBIC
    ts = []
    if size[0] != size[1]:
        ts.append(transforms.Resize((scale, scale), interpolation=interp))
    else:
        ts.append(transforms.Resize(scale, interpolation=interp))
        ts.append(transforms.CenterCrop(scale))
    ts.append(transforms.ToTensor())
    return transforms.Compose(ts)


def get_target(args, u2net=None):
    """-> (target tensor [1,3,S,S], mask tensor [S,S], masked PIL, mask PIL) like the original get_target."""
    target = load_rgb(args.target)
    masked_im, mask_img = masking.get_mask_u2net(args.device, target, net=u2net)
    if args.mask_object:
        target = masked_im
    if args.fix_scale:
        target = imaging.fix_image_scale(target)
        mask_img = imaging.fix_image_scale(mask_img, fill=0)

    target_ = _canvas_transform(target.size, args.image_scale)(target).unsqueeze(0).to(args.device)
    mask_t = _canvas_transform(mask_img.size, args.image_scale, nearest=True)(mask_img)[0]
    mask_t = (mask_t > 0.5).float()
    return target_, mask_t, mask_img


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def run_single(settings: dict, target: str, run_dir: str, seed: int, reporter: Reporter | None = None,
               control: Control | None = None, device: torch.device | None = None) -> SeedResult:
    """One optimisation run (one seed) – equivalent of ``painterly_rendering.py``."""
    from .losses import Loss
    from .painter import Painter, PainterOptimizer

    reporter = reporter or Reporter()
    control = control or Control()
    if device is None:
        device, warning = resolve_device(settings)
        if warning:
            code, _, text = warning.partition(":")
            reporter.event("warning", message=text, code=code)

    os.makedirs(run_dir, exist_ok=True)
    svg_logs = os.path.join(run_dir, "svg_logs")
    os.makedirs(svg_logs, exist_ok=True)
    args = build_args(settings, target, seed, run_dir, device)
    set_seed(seed)
    run_name = os.path.basename(run_dir.rstrip("/\\"))

    reporter.event("stage", seed=seed, name="loading")
    loss_func = Loss(args)
    inputs, mask, mask_img = get_target(args)
    input_img = imaging.tensor_to_pil(inputs)
    input_img.save(os.path.join(run_dir, "input.png"))
    mask_img.save(os.path.join(run_dir, "mask.png"))
    reporter.event("input", seed=seed, png=_png_bytes(input_img), mask_png=_png_bytes(mask_img))

    reporter.event("stage", seed=seed, name="init")
    renderer = Painter(num_strokes=args.num_paths, args=args, num_segments=args.num_segments,
                       imsize=args.image_scale, device=args.device, target_im=inputs, mask=mask)
    renderer = renderer.to(args.device)

    optimizer = PainterOptimizer(args, renderer)
    counter = 0
    configs_to_save = {"loss_eval": []}
    best_loss, best_fc_loss = 100, 100
    best_iter, best_iter_fc = 0, 0
    min_delta = 1e-5
    terminate = False

    renderer.set_random_noise(0)
    renderer.init_image(stage=0)
    optimizer.init_optimizers()

    stage_len = int(math.ceil(args.num_iter / max(args.num_stages, 1)))
    stage = 0
    status = "done"
    start = time.time()
    active_time = 0.0
    reporter.event("stage", seed=seed, name="optimizing")
    epoch = -1
    try:
        for epoch in range(args.num_iter):
            if control.should_stop():
                raise Cancelled()
            paused_at = time.time()
            control.wait_if_paused()
            start += time.time() - paused_at  # do not count pauses in the ETA
            if args.num_stages > 1 and epoch > 0 and epoch % stage_len == 0 and stage < args.num_stages - 1:
                stage += 1
                renderer.init_image(stage=stage)
                optimizer.init_optimizers()
                reporter.event("log", message=f"stage {stage + 1}/{args.num_stages}: +{args.num_paths} strokes")

            renderer.set_random_noise(epoch)
            if args.lr_scheduler:
                optimizer.update_lr(counter)

            optimizer.zero_grad_()
            sketches = renderer.get_image().to(args.device)
            losses_dict = loss_func(sketches, inputs.detach(), renderer.get_color_parameters(), renderer, counter,
                                    optimizer)
            loss = sum(list(losses_dict.values()))
            loss.backward()
            optimizer.step_()
            svg_text = None
            if epoch % args.save_interval == 0:
                svg_text = renderer.to_svg()
                with open(os.path.join(svg_logs, f"svg_iter{epoch}.svg"), "w", encoding="utf-8") as f:
                    f.write(svg_text)
            loss_eval_value = None
            if epoch % args.eval_interval == 0:
                with torch.no_grad():
                    losses_dict_eval = loss_func(sketches, inputs, renderer.get_color_parameters(),
                                                 renderer.get_points_parans(), counter, optimizer, mode="eval")
                    loss_eval = sum(list(losses_dict_eval.values()))
                    loss_eval_value = float(loss_eval.item())
                    configs_to_save["loss_eval"].append(loss_eval_value)
                    for k in losses_dict_eval.keys():
                        if k not in configs_to_save.keys():
                            configs_to_save[k] = []
                        configs_to_save[k].append(float(losses_dict_eval[k].item()))
                    if args.clip_fc_loss_weight and "fc" in losses_dict_eval:
                        if losses_dict_eval["fc"].item() < best_fc_loss:
                            best_fc_loss = losses_dict_eval["fc"].item() / args.clip_fc_loss_weight
                            best_iter_fc = epoch

                    cur_delta = loss_eval.item() - best_loss
                    if abs(cur_delta) > min_delta:
                        if cur_delta < 0:
                            best_loss = loss_eval.item()
                            best_iter = epoch
                            terminate = False
                            renderer.save_svg(run_dir, "best_iter")
                            imaging.tensor_to_pil(sketches).save(os.path.join(run_dir, "best_iter.png"))

                    if abs(cur_delta) <= min_delta:
                        if terminate:
                            reporter.event("log", message=f"seed {seed}: converged at iteration {epoch}")
                            break
                        terminate = True

            if counter == 0 and args.attention_init:
                preview = renderer.attention_preview()
                if preview is not None:
                    preview.save(os.path.join(run_dir, "attention_map.png"))
                    reporter.event("attention", seed=seed, png=_png_bytes(preview))

            counter += 1
            active_time = time.time() - start
            per_it = active_time / counter
            reporter.event("iteration", seed=seed, it=epoch, total=args.num_iter, loss=float(loss.item()),
                           loss_eval=loss_eval_value, best_loss=float(best_loss), best_iter=best_iter,
                           losses={k: float(v.item()) for k, v in losses_dict.items()},
                           elapsed=active_time, eta=per_it * (args.num_iter - counter))
            if svg_text is not None:
                reporter.event("preview", seed=seed, it=epoch, svg=svg_text)
    except Cancelled:
        status = "cancelled"

    renderer.save_svg(run_dir, "final_svg")
    best_svg = os.path.join(run_dir, "best_iter.svg")
    if not os.path.isfile(best_svg):
        renderer.save_svg(run_dir, "best_iter")

    final_config = {k: v for k, v in vars(args).items() if k != "device"}
    final_config["device"] = str(args.device)
    final_config.update(configs_to_save)
    final_config.update({
        "best_loss": float(best_loss), "best_iter": int(best_iter), "best_iter_fc": int(best_iter_fc),
        "iterations_done": counter, "status": status, "seconds": active_time,
        "settings": schema.normalize(settings),
    })
    with open(os.path.join(run_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(final_config, f, indent=2, default=str)

    result = SeedResult(seed=seed, run_name=run_name, run_dir=run_dir, best_loss=float(best_loss),
                        best_iter=int(best_iter), iterations_done=counter, best_svg=best_svg, status=status)
    reporter.event("seed_done", seed=seed, best_loss=result.best_loss, best_iter=result.best_iter,
                   status=status, run_dir=run_dir, svg=open(best_svg, encoding="utf-8").read())
    del loss_func, renderer, optimizer
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return result


def run_job(settings: dict, target: str, output_root: str, reporter: Reporter | None = None,
            control: Control | None = None, job_dir: str | None = None, seeds: list[int] | None = None,
            finish: bool = True) -> dict | list[SeedResult]:
    """Run the seeds of a job in this process (all seeds, or only ``seeds``).

    With ``finish=True`` the best sketch is selected afterwards (like run_object_sketching.py)
    and the job summary is returned; otherwise the list of seed results is returned.
    """
    reporter = reporter or Reporter()
    settings = schema.normalize(settings)
    if int(settings.get("num_threads", 0)) > 0:
        torch.set_num_threads(int(settings["num_threads"]))
    device, warning = resolve_device(settings)
    if warning:
        code, _, text = warning.partition(":")
        reporter.event("warning", message=text, code=code)
    job_dir = job_dir or make_job_dir(output_root, target)
    seeds = list(seeds) if seeds is not None else job_seeds(settings)
    reporter.event("job_start", job_dir=job_dir, device=str(device), seeds=seeds)
    results = []
    for seed in seeds:
        if control and control.should_stop():
            break
        run_dir = os.path.join(job_dir, run_name_for(target, settings, seed))
        results.append(run_single(settings, target, run_dir, seed, reporter, control, device))
    if not finish:
        return results
    return finish_job(job_dir, target, settings, results, reporter)
