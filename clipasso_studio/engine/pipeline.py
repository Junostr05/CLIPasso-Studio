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
from . import checkpoint, imaging, jobs, masking
from .imaging import load_rgb  # noqa: F401 (used by the methods as pipeline.load_rgb)
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
            loss = "" if data.get("loss") is None else f"  loss {data['loss']:.4f}"
            if data.get("best_loss") is not None:
                loss += f"  best {data['best_loss']:.4f}"
            if data.get("score") is not None:
                loss += f"  CLIP score {data['score']:.2f}"
            print(f"[seed {data['seed']}] iter {data['it'] + 1}/{data['total']}{loss}  "
                  f"ETA {imaging.eta_string(data['eta'])}", flush=True)
        elif kind in ("log", "warning"):
            print(data.get("message", ""), flush=True)
        elif kind == "seed_done":
            score = "" if data.get("clip_score") is None else f", CLIP score {data['clip_score']:.2f}"
            print(f"[seed {data['seed']}] done – best loss {data['best_loss']:.4f} at iter {data['best_iter']}"
                  f"{score}", flush=True)
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
    # an unused mask is only shown in the mask view: the bundled U2Net, as before
    model = getattr(args, "mask_model", "u2net") if args.mask_object or args.mask_object_attention else "u2net"
    masked_im, mask_img = masking.get_mask(args.device, target, model, net=u2net if model == "u2net" else None)
    if args.mask_object:
        target = masked_im
        if getattr(args, "frame_object", False):  # small objects fill the canvas
            target, mask_img, _ = imaging.frame_object(target, mask_img)
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


def score_run(svg_path: str, target_img: Image.Image, device, reporter: Reporter | None = None) -> float | None:
    """CLIP similarity of a finished sketch to its input (see :mod:`.scoring`)."""
    try:
        from .scoring import get_scorer

        return round(get_scorer(device).score_svg(svg_path, target_img), 2)
    except Exception as exc:  # scoring is informative only
        if reporter:
            reporter.event("log", message=f"CLIP score unavailable: {exc}", code="clip_score_unavailable",
                           error=str(exc))
        return None


def plateaued(loss_eval: list[float], eval_interval: int, since: int) -> bool:
    """Turbo mode: the eval loss improved by less than ``TURBO_PLATEAU`` (relative) during the last
    ``TURBO_PLATEAU_ITERS`` iterations. Only evaluations from iteration ``since`` on count (evaluation i
    is iteration i * eval_interval), so the check needs no state of its own."""
    eval_interval = max(int(eval_interval), 1)
    window = max(2, schema.TURBO_PLATEAU_ITERS // eval_interval)
    values = loss_eval[-(-int(since) // eval_interval):]
    if len(values) <= window:
        return False
    before, recent = min(values[:-window]), min(values[-window:])
    return recent > before - schema.TURBO_PLATEAU * abs(before)


def run_single(settings: dict, target: str, run_dir: str, seed: int, reporter: Reporter | None = None,
               control: Control | None = None, device: torch.device | None = None, stop_at: int | None = None,
               finalize: bool = False, plan_left: int | None = None) -> SeedResult:
    """One optimisation run (one seed) – equivalent of ``painterly_rendering.py``.

    For the turbo mode's pruning: ``stop_at`` runs only the first iterations and keeps the checkpoint
    (status "partial", nothing is finished or saved), ``finalize`` finishes a run from its checkpoint
    without optimising further (the sketch is marked ``pruned``). ``plan_left``: iterations of the job
    that follow this run, for a time estimate of the whole job.
    """
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
    if (args.mask_object or args.mask_object_attention) and args.mask_model != "u2net":
        reporter.event("stage", seed=seed, name="mask")  # BiRefNet takes a few seconds on a CPU
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
    first_epoch = 0
    ck = checkpoint.load(run_dir)
    if ck is not None:  # continue an interrupted run where it stopped
        for s in range(1, int(ck["stage"]) + 1):
            renderer.init_image(stage=s)  # the strokes added by later stages (positions come from the checkpoint)
        for path, points in zip(renderer.shapes, ck["points"]):
            path.points = points.to(args.device)
        for group, color in zip(renderer.shape_groups, ck["colors"]):
            group.stroke_color = color.to(group.stroke_color.device)
        renderer.optimize_flag = list(ck["optimize_flag"])
        optimizer.init_optimizers()
        optimizer.points_optim.load_state_dict(ck["points_optim"])
        if ck.get("color_optim") is not None and optimizer.optim_color:
            optimizer.color_optim.load_state_dict(ck["color_optim"])
        stage, counter, first_epoch = int(ck["stage"]), int(ck["counter"]), int(ck["epoch"]) + 1
        best_loss, best_iter = ck["best_loss"], ck["best_iter"]
        best_fc_loss, best_iter_fc, terminate = ck["best_fc_loss"], ck["best_iter_fc"], ck["terminate"]
        configs_to_save = ck["configs"]
        active_time = float(ck["active_time"])
        start = time.time() - active_time
        checkpoint.set_rng_state(ck["rng"])
        if first_epoch < (stop_at or args.num_iter) and not finalize:
            reporter.event("log", message=f"seed {seed}: continuing at iteration {first_epoch}", code="resume_at",
                           seed=seed, it=first_epoch)

    def save_checkpoint(done_epoch: int, renderer=renderer, optimizer=optimizer):
        checkpoint.save(run_dir, {
            "epoch": done_epoch, "counter": counter, "stage": stage,
            "points": [p.points.detach().cpu() for p in renderer.shapes],
            "colors": [g.stroke_color.detach().cpu() for g in renderer.shape_groups],
            "optimize_flag": list(renderer.optimize_flag),
            "points_optim": optimizer.points_optim.state_dict(),
            "color_optim": optimizer.color_optim.state_dict() if optimizer.optim_color else None,
            "best_loss": best_loss, "best_iter": best_iter, "best_fc_loss": best_fc_loss,
            "best_iter_fc": best_iter_fc, "terminate": terminate, "configs": configs_to_save,
            "active_time": active_time})

    saver = checkpoint.Timer()
    previews = checkpoint.Timer(checkpoint.PREVIEW_S, due_now=True)
    reporter.event("stage", seed=seed, name="optimizing")
    turbo = schema.turbo(settings)
    plateau_from = schema.turbo_prune_iter(args.num_iter) if schema.turbo_prunes(settings) else 0
    end = args.num_iter if stop_at is None else min(int(stop_at), args.num_iter)
    if finalize:
        end = first_epoch
    partial = False
    epoch = first_epoch - 1
    try:
        for epoch in range(first_epoch, end):
            if control.should_stop():
                if epoch > first_epoch or ck is not None:
                    save_checkpoint(epoch - 1)  # "Continue" goes on from here
                raise Cancelled()
            paused_at = time.time()
            control.wait_if_paused()
            start += time.time() - paused_at  # do not count pauses in the ETA
            if args.num_stages > 1 and epoch > 0 and epoch % stage_len == 0 and stage < args.num_stages - 1:
                stage += 1
                renderer.init_image(stage=stage)
                optimizer.init_optimizers()
                reporter.event("log", message=f"stage {stage + 1}/{args.num_stages}: +{args.num_paths} strokes",
                               code="stage", stage=stage + 1, stages=args.num_stages, n=args.num_paths)

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
                            reporter.event("log", message=f"seed {seed}: converged at iteration {epoch}",
                                           code="converged", seed=seed, it=epoch)
                            break
                        terminate = True
                    last_stage = stage == args.num_stages - 1
                    if turbo and last_stage and plateaued(configs_to_save["loss_eval"], args.eval_interval,
                                                          max(stage * stage_len, plateau_from)):
                        reporter.event("log", message=f"seed {seed}: no more progress – stopped at iteration "
                                                      f"{epoch}", code="plateau", seed=seed, it=epoch)
                        break

            if counter == 0 and args.attention_init:
                preview = renderer.attention_preview()
                if preview is not None:
                    preview.save(os.path.join(run_dir, "attention_map.png"))
                    reporter.event("attention", seed=seed, png=_png_bytes(preview))

            counter += 1
            active_time = time.time() - start
            per_it = active_time / counter
            job_eta = {} if plan_left is None else {"eta_job": True}
            reporter.event("iteration", seed=seed, it=epoch, total=args.num_iter, loss=float(loss.item()),
                           loss_eval=loss_eval_value, best_loss=float(best_loss), best_iter=best_iter,
                           losses={k: float(v.item()) for k, v in losses_dict.items()}, elapsed=active_time,
                           eta=per_it * (end - counter + (plan_left or 0)), **job_eta)
            if svg_text is not None and (previews.due() or epoch == args.num_iter - 1):
                reporter.event("preview", seed=seed, it=epoch, svg=svg_text)
            if saver.due():
                save_checkpoint(epoch)
        else:
            partial = end < args.num_iter and not finalize
    except Cancelled:
        status = "cancelled"
    if partial:  # the first part of a turbo run: kept for later, nothing is finished yet
        if epoch >= first_epoch:
            save_checkpoint(epoch)
        best_svg = os.path.join(run_dir, "best_iter.svg")
        result = SeedResult(seed=seed, run_name=run_name, run_dir=run_dir, best_loss=float(best_loss),
                            best_iter=int(best_iter), iterations_done=counter, best_svg=best_svg, status="partial",
                            method="clipasso", seconds=round(active_time, 1))
        del loss_func, renderer, optimizer
        return result
    if status == "done":
        checkpoint.remove(run_dir)

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
        "settings": schema.normalize(settings), "pruned": bool(finalize),
    })
    with open(os.path.join(run_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(final_config, f, indent=2, default=str)

    clip_sc = score_run(best_svg, input_img, device, reporter)
    if clip_sc is not None:
        final_config["clip_score"] = clip_sc
        with open(os.path.join(run_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(final_config, f, indent=2, default=str)

    result = SeedResult(seed=seed, run_name=run_name, run_dir=run_dir, best_loss=float(best_loss),
                        best_iter=int(best_iter), iterations_done=counter, best_svg=best_svg, status=status,
                        method="clipasso", clip_score=clip_sc, seconds=round(active_time, 1), pruned=bool(finalize))
    with open(best_svg, encoding="utf-8") as f:
        best_text = f.read()
    reporter.event("seed_done", seed=seed, best_loss=result.best_loss, best_iter=result.best_iter,
                   status=status, run_dir=run_dir, svg=best_text, clip_score=clip_sc, pruned=result.pruned)
    del loss_func, renderer, optimizer
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return result


def run_job(settings: dict, target: str, output_root: str, reporter: Reporter | None = None,
            control: Control | None = None, job_dir: str | None = None, seeds: list[int] | None = None,
            finish: bool = True, resume: bool = False) -> dict | list[SeedResult]:
    """Run the seeds of a job in this process (all seeds, or only ``seeds``).

    With ``finish=True`` the best sketch is selected afterwards (like run_object_sketching.py)
    and the job summary is returned; otherwise the list of seed results is returned.
    With ``resume`` (an existing ``job_dir``) finished seeds are kept, the others continue from
    their checkpoints, and the summary covers all of them.
    """
    reporter = reporter or Reporter()
    settings = schema.normalize(settings)
    if int(settings.get("num_threads", 0)) > 0:
        torch.set_num_threads(int(settings["num_threads"]))
    device, warning = resolve_device(settings)
    if warning:
        code, _, text = warning.partition(":")
        reporter.event("warning", message=text, code=code)
    from . import methods

    method = schema.method_of(settings)
    impl = methods.get(method)
    job_dir = job_dir or make_job_dir(output_root, target, method)
    if jobs.read_state(job_dir) is None:
        jobs.write_state(job_dir, target, settings)
    old: dict[int, SeedResult] = {}
    if resume:
        jobs.set_status(job_dir, "running")
        # the input the job started with (U2Net, no framing for jobs from before 2.4), so the rest matches
        saved = (jobs.read_state(job_dir) or {}).get("settings") or {}
        for key in ("mask_model", "frame_object"):
            if key in settings:
                settings[key] = saved.get(key, settings[key])
        old = jobs.done_results(job_dir)
        if seeds is None:
            seeds = [s for s in job_seeds(settings) if s not in old]
        for r in old.values():  # the finished sketches, as if they had just been drawn
            with open(jobs.sketch_file(r.run_dir, r.best_svg), encoding="utf-8") as f:
                svg = f.read()
            reporter.event("seed_done", seed=r.seed, best_loss=r.best_loss, best_iter=r.best_iter, status=r.status,
                           run_dir=r.run_dir, svg=svg, clip_score=r.clip_score, restored=True)
    seeds = list(seeds) if seeds is not None else job_seeds(settings)
    reporter.event("job_start", job_dir=job_dir, device=str(device), seeds=seeds, method=method)
    results = []
    if hasattr(impl, "run_cells"):  # SceneSketch: the items depend on each other and run together
        # finished cells are rebuilt from their saved parts in seconds, so all cells up to the last one run
        cells = job_seeds(settings) if resume else seeds
        results = impl.run_cells(settings, target, job_dir, cells, reporter, control, device)
        for r in results:
            jobs.save_result(r)
    if schema.turbo_prunes(settings) and not hasattr(impl, "run_cells") and len(seeds) > 1:
        results = _run_pruned(impl, settings, target, job_dir, seeds, old, reporter, control, device)
        seeds = []
    for seed in seeds if not hasattr(impl, "run_cells") else ():
        if control and control.should_stop():
            break
        run_dir = os.path.join(job_dir, run_name_for(target, settings, seed))
        result = impl.run_single(settings, target, run_dir, seed, reporter, control, device)
        jobs.save_result(result)
        results.append(result)
    if not finish:
        return results
    return finish_job(job_dir, target, settings, jobs.merge_results(old, results), reporter)


def _run_pruned(impl, settings: dict, target: str, job_dir: str, seeds: list[int], old: dict[int, SeedResult],
                reporter: Reporter, control: Control | None, device) -> list[SeedResult]:
    """Turbo mode: every seed runs to ``TURBO_PRUNE_AT`` of its iterations, then only the best one goes on;
    the others are finished as they are (``pruned``). The choice follows from the saved checkpoints and
    results, so a continued job makes the same one."""
    total = int(settings["num_iter"])
    stop = schema.turbo_prune_iter(total)
    results: list[SeedResult] = []
    partial: dict[int, SeedResult] = {}

    def run_dir(seed):
        return os.path.join(job_dir, run_name_for(target, settings, seed))

    def stopped() -> list[SeedResult]:
        """Cancelled: the seeds that wait at the quarter count as cancelled (they continue from there)."""
        handled = {r.seed for r in results}
        for seed, r in partial.items():
            if seed not in handled:
                r.status = "cancelled"
                jobs.save_result(r)
                results.append(r)
        return results

    for k, seed in enumerate(seeds):
        if control and control.should_stop():
            return stopped()
        left = stop * (len(seeds) - k - 1) + (total - stop)
        r = impl.run_single(settings, target, run_dir(seed), seed, reporter, control, device, stop_at=stop,
                            plan_left=left)
        if r.status == "partial":
            partial[seed] = r
        else:  # finished early (converged) or cancelled
            jobs.save_result(r)
            results.append(r)
            if r.status == "cancelled":
                return stopped()
    finished = [r for r in list(old.values()) + results if r.status == "done" and not r.pruned]
    best = min(list(partial.values()) + finished, key=lambda r: r.best_loss, default=None)
    for seed in partial:
        if best is not None and seed == best.seed:
            continue
        if control and control.should_stop():
            return stopped()
        r = impl.run_single(settings, target, run_dir(seed), seed, reporter, control, device, finalize=True)
        jobs.save_result(r)
        results.append(r)
    if best is not None and best.status == "partial":
        if control and control.should_stop():
            return stopped()
        r = impl.run_single(settings, target, run_dir(best.seed), best.seed, reporter, control, device, plan_left=0)
        jobs.save_result(r)
        results.append(r)
    return results
