"""SceneSketch – scene sketches with two axes of abstraction (CLIPascene, Vinker et al., ICCV 2023).

Port of https://github.com/yael-vinker/SceneSketch (MIT licence). A scene is split into the
foreground object (U2Net mask) and the background (object area filled in by LaMa); both parts are
sketched separately and combined. Every sketch has 64 strokes whose positions come from an MLP.

* **Fidelity axis** (``generate_fidelity_levels.py``): one sketch per CLIP ViT-B/32 layer – shallow
  layers (2) follow the geometry closely, deep layers (11) keep only the semantics. Objects are
  trained with layer 4 as well (weight 0.5) and gradient-norm balancing.
* **Simplicity axis** (``run_ratio.py``): starting from a fidelity sketch, a second MLP learns which
  strokes to drop; each level halves the target ratio "share of strokes / CLIP loss" by a
  per-layer step (``min_div``) and continues from the previous level.
* **Combination** (``combine_matrix.py``): object strokes are scaled back from the enlarged object
  canvas and drawn over the background strokes, which are cut at the object outline.

The job's items ("seeds" for the rest of the app) are the cells of this matrix, numbered
``layer * 100 + level`` (level 0 = fidelity sketch). Deviations: PyTorch rasterizer instead of
diffvg, LaMa port with float16 weights, vector (instead of raster) combination, the ratio loss
does not move the strokes (``RATIO_DETACH_CLIP``), objects on a plain background skip the
background sketch, and the simplification levels can be fewer than 8 (they then span the same
range with larger steps).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from types import SimpleNamespace

import numpy as np
import torch
from PIL import Image
from torchvision import transforms
from torchvision.transforms import InterpolationMode

from .... import settings_schema as schema
from ... import checkpoint, imaging, model_store
from ...jobs import SeedResult
from . import combine as C
from .painter import MLPPainter, paths_to_svg, render_paths

CANVAS = 224  # image_scale of the original
SIMPLIFY_EVAL_INTERVAL = 100  # run_sketch.py defaults used by run_ratio.py
SIMPLIFY_MIN_EVAL_ITER = 100
PREVIEW_EVERY = 10  # live preview interval (iterations)
PLAIN_STD = 0.03  # a background with less variation than this is plain (only the object is sketched)
# The ratio loss (share of kept strokes vs. ratio x CLIP loss) only decides how many strokes remain. In the
# original its CLIP term also pushes the stroke positions: when a level lowers the target ratio, the quickest
# way to meet it is to make the sketch worse, and the strokes of objects visibly scramble (checked on the
# ballerina: CLIP layer-8 loss 0.015 -> 0.030 at level 2, versus 0.017 with a clean, sparser sketch here).
RATIO_DETACH_CLIP = True

_cache: dict = {}


def required_models(settings: dict) -> list[str]:
    s = schema.normalize({**settings, "method": "scenesketch"})
    needed = {model_store.clip_key("ViT-B/32")}
    if s["split_scene"]:
        needed.update(("lama", s["mask_model"]))
    if s["attention_init"]:
        if s["saliency_model"] == "dino":
            needed.add("dino")
        else:
            needed.add(model_store.clip_key(s["saliency_clip_model"]))
    return sorted(needed)


def release_models() -> None:
    _cache.clear()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def run_single(*_args, **_kwargs):  # pragma: no cover - SceneSketch jobs run as a whole (run_cells)
    raise NotImplementedError("SceneSketch runs all cells of a job together – use run_cells()")


# ----------------------------------------------------------------------------- configuration


def ratios(r1: float, div: float, levels: int) -> list[float]:
    """``get_ratios_dict``: r1 * 2^-x sampled at x = 0, step, 2*step, ... (the exponential fitted
    through r1, r1/2, ..., r1/16 is exactly r1 * 2^-x), rounded to 3 decimals like the original.
    With fewer than 8 levels the step grows so that the levels span the same range."""
    step = div * schema.SCENE_ORIGINAL_LEVELS / max(levels, 1)
    return [max(round(r1 * 2.0 ** (-k * step), 3), 0.001) for k in range(levels)]


@dataclass
class PartConfig:
    name: str  # "background" | "object"
    layer: int
    level: int
    target: torch.Tensor
    layer_weights: dict
    num_iter: int
    eval_interval: int
    min_eval_iter: int
    gradnorm: bool
    width_optim: bool = False
    ratio: float = 0.0
    init_points: torch.Tensor | None = None  # None: attention-based initial strokes
    states: dict | None = None  # MLP weights (and optimiser states) to start from
    load_optim: bool = False


@dataclass
class RunResult:
    seed: int
    run_dir: str
    points_init: torch.Tensor
    paths: list
    state: dict
    loss_eval: list = field(default_factory=list)
    evals: dict = field(default_factory=dict)
    best_eval_index: int = 0
    best_normalised_loss: float | None = None
    frames: list = field(default_factory=list)  # (iteration, paths) every save_interval
    seconds: float = 0.0


class _Ctx:
    """Everything a job needs: settings, device, reporting, prepared inputs, timing."""

    def __init__(self, s, target, job_dir, cells, reporter, control, device):
        self.s, self.target, self.job_dir, self.cells = s, target, job_dir, cells
        self.reporter, self.control, self.device = reporter, control, device
        self.layers = schema.scene_layers(s)
        self.levels = int(s["simplicity_levels"])
        self.total_iters = sum(schema.scene_cell_iterations(s, c) for c in cells)
        self.done_iters = 0
        self.active = 0.0  # seconds of computation (without pauses)
        self.cell = None  # id of the cell being computed
        self.cell_total = 1
        self.cell_done = 0
        self.preview_other = []  # strokes of the other part shown in the live preview (scene coords)
        self.preview_part = "background"
        self.scorer = None
        self.clip_model = None
        self.cancelled = False
        self.skip_background = False


# ----------------------------------------------------------------------------- inputs


def _prepare(ctx: _Ctx) -> dict:
    """Square scene, object mask, LaMa background, object target, 224px tensors."""
    from ...pipeline import load_rgb
    from . import preprocess as pre

    s, device = ctx.s, ctx.device
    key = ("inputs", os.path.abspath(ctx.target), os.path.getmtime(ctx.target), str(device), s["fix_scale"],
           s["split_scene"], s["resize_obj"], s.get("mask_model", "u2net"))
    if key in _cache:
        return _cache[key]
    scene = pre.square_scene(load_rgb(ctx.target), bool(s["fix_scale"]))
    size = scene.size[0]
    out = {"scene": scene, "object": None, "background": scene, "mask": None, "params": {}}
    if s["split_scene"]:
        ctx.reporter.event("stage", seed=ctx.cell, name="scene_mask")
        prob = pre.object_probability(scene, device, s.get("mask_model", "u2net"))
        obj_mask = pre.object_mask(prob, size)
        if obj_mask.sum() < 16:  # no foreground object found: sketch the whole scene as background
            ctx.reporter.event("warning", code="scene_no_object",
                               message="No foreground object found – the whole scene is sketched as one.")
        else:
            hole = pre.inpaint_mask(prob, size)
            outside = np.asarray(scene, dtype=np.float32)[hole < 0.5] / 255.0
            # object photos on a plain background (e.g. white): there is no background to sketch
            out["plain_background"] = outside.size > 0 and float(outside.std(axis=0).max()) < PLAIN_STD
            if not out["plain_background"]:
                ctx.reporter.event("stage", seed=ctx.cell, name="scene_inpaint")
                from .lama import load_lama

                lama = load_lama(device)
                out["background"] = pre.inpaint_background(scene, hole, device, lama)
                del lama
            obj_img, obj_canvas_mask, params = pre.object_target(scene, obj_mask, bool(s["resize_obj"]))
            out.update(object=obj_img, mask=obj_mask, object_mask=obj_canvas_mask, params=params)
    tf = transforms.Compose([transforms.Resize(CANVAS, interpolation=InterpolationMode.BICUBIC),
                             transforms.CenterCrop(CANVAS), transforms.ToTensor()])
    out["background_t"] = tf(out["background"]).unsqueeze(0).to(device)
    out["object_t"] = tf(out["object"]).unsqueeze(0).to(device) if out["object"] is not None else None
    out["scene_t"] = tf(scene).unsqueeze(0).to(device)
    out.setdefault("plain_background", False)
    out["mask_canvas"] = C.mask_for_canvas(out["mask"], CANVAS) if out["mask"] is not None else None
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    _cache.clear()
    _cache[key] = out
    return out


def _initial_strokes(ctx: _Ctx, target: torch.Tensor, mask_t: torch.Tensor | None):
    """Attention-based start points + short random strokes, exactly like CLIPasso's ``Painter``."""
    from ...painter import Painter

    s = ctx.s
    args = SimpleNamespace(
        width=float(s["width"]), control_points_per_seg=int(s["control_points_per_seg"]), force_sparse=0,
        num_stages=1, augemntations="affine", noise_thresh=0.5, softmax_temp=float(s["softmax_temp"]),
        color_vars_threshold=0.0, path_svg="none", attention_init=int(bool(s["attention_init"])),
        saliency_model=s["saliency_model"], xdog_intersec=int(bool(s["xdog_intersec"])),
        mask_object_attention=int(bool(s["mask_object_attention"]) and mask_t is not None),
        text_target="none", saliency_clip_model=s["saliency_clip_model"], num_iter=1, save_interval=1)
    painter = Painter(args, num_strokes=int(s["num_strokes"]), num_segments=1, imsize=CANVAS, device=ctx.device,
                      target_im=target, mask=mask_t)
    painter.init_image(stage=0)
    points = torch.stack([p.points.detach().float() for p in painter.shapes]).to(ctx.device)
    return points, painter.attention_preview()


# ----------------------------------------------------------------------------- training


def _progress(ctx: _Ctx, loss: float, score=None, part: str = "", count: bool = True):
    if count:
        ctx.done_iters += 1
        ctx.cell_done += 1
    per_it = ctx.active / max(ctx.done_iters, 1)
    ctx.reporter.event("iteration", seed=ctx.cell, it=min(ctx.cell_done, ctx.cell_total) - 1, total=ctx.cell_total,
                       loss=loss, loss_eval=None, best_loss=None, best_iter=ctx.cell_done - 1, losses={"loss": loss},
                       score=score, elapsed=ctx.active, eta=per_it * max(ctx.total_iters - ctx.done_iters, 0),
                       eta_job=True, part=part)


def _preview_paths(ctx: _Ctx, part: str, paths, inputs) -> list:
    """Current strokes of ``part`` together with the other part, in scene coordinates."""
    if part == "object":
        obj = C.object_to_scene(paths, inputs["params"], CANVAS)
        return C.combine(ctx.preview_other, obj, inputs["mask_canvas"], CANVAS)
    return C.combine(paths, ctx.preview_other, inputs["mask_canvas"], CANVAS)


PART_FILE = "part.pt"


def _paths_data(paths) -> list:
    return [{"ncp": p.num_control_points, "points": p.points.detach().cpu(), "width": p.stroke_width.detach().cpu(),
             "closed": p.is_closed} for p in paths]


def _paths_from(data, device) -> list:
    from ... import renderer

    return [renderer.Path(d["ncp"], d["points"].to(device), d["width"], is_closed=d["closed"]) for d in data]


def _save_part(res: RunResult) -> None:
    """A finished part (one optimisation of the background or the object of a cell): continuing an
    interrupted job loads it instead of computing it again."""
    data = {"seed": res.seed, "points_init": res.points_init.cpu(), "paths": _paths_data(res.paths),
            "state": res.state, "loss_eval": res.loss_eval, "evals": res.evals, "best_eval_index": res.best_eval_index,
            "best_normalised_loss": res.best_normalised_loss, "seconds": res.seconds,
            "frames": [(it, _paths_data(fr)) for it, fr in res.frames]}
    tmp = os.path.join(res.run_dir, PART_FILE + ".tmp")
    torch.save(data, tmp)
    os.replace(tmp, os.path.join(res.run_dir, PART_FILE))


def _load_part(run_dir: str, device) -> RunResult | None:
    path = os.path.join(run_dir, PART_FILE)
    if not os.path.isfile(path):
        return None
    try:
        d = torch.load(path, map_location="cpu", weights_only=False)
        return RunResult(seed=d["seed"], run_dir=run_dir, points_init=d["points_init"],
                         paths=_paths_from(d["paths"], device), state=checkpoint.to_device(d["state"], device),
                         loss_eval=d["loss_eval"], evals=d["evals"], best_eval_index=d["best_eval_index"],
                         best_normalised_loss=d["best_normalised_loss"], seconds=d["seconds"],
                         frames=[(it, _paths_from(fr, device)) for it, fr in d["frames"]])
    except Exception:  # unreadable (e.g. written by an older version): compute it again
        return None


def _train(ctx: _Ctx, cfg: PartConfig, seed: int, run_dir: str, inputs: dict) -> RunResult:
    """One optimisation (``painterly_rendering.py`` with the SceneSketch options)."""
    from ...pipeline import set_seed
    from .loss import SceneLoss

    s, device = ctx.s, ctx.device
    saved = _load_part(run_dir, device)
    if saved is not None:  # finished before the job was interrupted
        total = int(cfg.num_iter)
        ctx.done_iters += total
        ctx.cell_done += total
        ctx.reporter.event("log", message=f"SceneSketch: {os.path.basename(os.path.dirname(run_dir))} "
                                          f"(seed {seed}) restored")
        _progress(ctx, min(saved.loss_eval) if saved.loss_eval else 0.0, None, cfg.name, count=False)
        return saved
    os.makedirs(os.path.join(run_dir, "svg_logs"), exist_ok=True)
    set_seed(seed)
    if cfg.init_points is None:
        mask_t = None
        if cfg.name == "object" and inputs.get("object_mask") is not None:
            mask_t = torch.from_numpy(C.mask_for_canvas(inputs["object_mask"], CANVAS).astype(np.float32))
        points_init, preview = _initial_strokes(ctx, cfg.target, mask_t)
        if preview is not None:
            preview.save(os.path.join(run_dir, "attention_map.png"))
            if cfg.name == "background":
                from ...pipeline import _png_bytes

                ctx.reporter.event("attention", seed=ctx.cell, png=_png_bytes(preview))
    else:
        points_init = cfg.init_points
    painter = MLPPainter(points_init, CANVAS, device, width_optim=cfg.width_optim,
                         gumbel_temp=float(s["gumbel_temp"]), width=float(s["width"]))
    states = cfg.states or {}
    if states.get("mlp") is not None:
        painter.mlp.load_state_dict(states["mlp"])
    if cfg.width_optim and states.get("mlp_width") is not None:
        painter.mlp_width.load_state_dict(states["mlp_width"])
    if ctx.clip_model is None:
        from ...clip_ import clip

        ctx.clip_model, _ = clip.load("ViT-B/32", device, jit=False)
    loss_fn = SceneLoss(cfg.layer_weights, device, num_augs=int(s["num_aug_clip"]),
                        loss_type=s["clip_conv_loss_type"], width_optim=cfg.width_optim,
                        width_loss_weight=float(s["width_loss_weight"]), ratio=cfg.ratio, gradnorm=cfg.gradnorm,
                        clip_model=ctx.clip_model, ratio_detach_clip=RATIO_DETACH_CLIP)
    points_opt = torch.optim.Adam(painter.mlp.parameters(), lr=float(s["lr"]))
    width_opt = torch.optim.Adam(painter.mlp_width.parameters(), lr=float(s["width_lr"])) if cfg.width_optim else None
    if cfg.load_optim and states.get("points_opt") is not None:
        points_opt.load_state_dict(states["points_opt"])
    if width_opt is not None and states.get("width_opt") is not None:
        width_opt.load_state_dict(states["width_opt"])

    with torch.no_grad():
        painter.render("init")
    with open(os.path.join(run_dir, "svg_logs", "init_svg.svg"), "w", encoding="utf-8") as f:
        f.write(paths_to_svg([_path(p) for p in points_init], CANVAS))

    total = int(cfg.num_iter)
    min_eval = min(int(cfg.min_eval_iter), max(total - 1, 0))
    save_interval = max(int(s["save_interval"]), 1)
    best_loss, best_state, best_index = float("inf"), None, 0
    checkpoints: dict[int, dict] = {}
    loss_eval: list[float] = []
    evals: dict[str, list[float]] = {"num_strokes": []}
    frames = []
    started = time.time()
    for epoch in range(total):
        if ctx.control.should_stop():
            ctx.cancelled = True
            break
        paused_at = time.time()
        ctx.control.wait_if_paused()
        started += time.time() - paused_at
        t0 = time.time()
        points_opt.zero_grad()
        if width_opt is not None:
            width_opt.zero_grad()
        sketch = painter.render()
        weighted, _, _ = loss_fn(sketch, cfg.target, painter.stroke_probs, painter.strokes_in_canvas(),
                                 painter.mlp_width, painter.mlp, "train")
        loss = sum(weighted.values())
        loss.backward()
        points_opt.step()
        if width_opt is not None:
            width_opt.step()

        kept = None
        if epoch % save_interval == 0 or epoch == total - 1:
            kept = painter.kept_paths()
            frames.append((epoch, kept))
            with open(os.path.join(run_dir, "svg_logs", f"svg_iter{epoch}.svg"), "w", encoding="utf-8") as f:
                f.write(paths_to_svg(kept, CANVAS))
        if (epoch % int(cfg.eval_interval) == 0 and epoch >= min_eval) or (epoch == total - 1 and not loss_eval):
            if cfg.width_optim:
                checkpoints[len(loss_eval)] = _snapshot(painter, points_opt, width_opt)
            with torch.no_grad():
                w_eval, _, o_eval = loss_fn(sketch, cfg.target, painter.stroke_probs, painter.strokes_in_canvas(),
                                            painter.mlp_width, painter.mlp, "eval")
                value = float(sum(w_eval.values()).item())
            loss_eval.append(value)
            evals["num_strokes"].append(painter.strokes_count())
            for k, v in o_eval.items():
                evals.setdefault(f"{k}_original_eval", []).append(float(v.item()))
            if value < best_loss and abs(value - best_loss) > 1e-7:
                best_loss, best_index = value, len(loss_eval) - 1
                if not cfg.width_optim:
                    best_state = _snapshot(painter, points_opt, None)
        ctx.active += time.time() - t0
        score = None
        if epoch % PREVIEW_EVERY == 0 or kept is not None:
            shown = _preview_paths(ctx, cfg.name, kept if kept is not None else painter.kept_paths(), inputs)
            svg = paths_to_svg(shown, CANVAS)
            if kept is not None and epoch % save_interval == 0:
                score = _score_paths(ctx, shown, inputs)
            ctx.reporter.event("preview", seed=ctx.cell, it=ctx.cell_done, svg=svg)
        _progress(ctx, float(loss.item()), score, cfg.name)

    # ------------------------------------------------------------- choice of the final MLPs
    best_normalised = None
    if cfg.width_optim:
        index, best_normalised = _best_normalised(evals)
        chosen = checkpoints.get(index) or _snapshot(painter, points_opt, width_opt)
    else:
        chosen = best_state or _snapshot(painter, points_opt, None)
    paths = painter.inference(chosen)
    with open(os.path.join(run_dir, "best_iter.svg"), "w", encoding="utf-8") as f:
        f.write(paths_to_svg(paths, CANVAS))
    config = {"part": cfg.name, "layer": cfg.layer, "level": cfg.level, "seed": seed, "num_iter": total,
              "layer_weights": cfg.layer_weights, "gradnorm": cfg.gradnorm, "width_optim": cfg.width_optim,
              "ratio_loss": cfg.ratio, "loss_eval": loss_eval, **evals, "best_eval_index": best_index,
              "best_normalised_loss": best_normalised, "strokes": len(paths), "seconds": time.time() - started}
    with open(os.path.join(run_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    res = RunResult(seed=seed, run_dir=run_dir, points_init=points_init.detach(), paths=paths, state=chosen,
                    loss_eval=loss_eval, evals=evals, best_eval_index=best_index,
                    best_normalised_loss=best_normalised, frames=frames, seconds=config["seconds"])
    if not ctx.cancelled:
        _save_part(res)
    return res


def _path(points: torch.Tensor):
    from ... import renderer

    return renderer.Path(torch.tensor([points.shape[0] - 2]), points.detach(), torch.tensor(1.5), is_closed=False)


def _snapshot(painter: MLPPainter, points_opt, width_opt) -> dict:
    st = painter.state()
    st["points_opt"] = _clone(points_opt.state_dict())
    st["width_opt"] = _clone(width_opt.state_dict()) if width_opt is not None else None
    return st


def _clone(obj):
    if torch.is_tensor(obj):
        return obj.detach().clone()
    if isinstance(obj, dict):
        return {k: _clone(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clone(v) for v in obj]
    return obj


def _best_normalised(evals: dict) -> tuple[int, float]:
    """``log_best_normalised_sketch``: argmin of the summed z-scores of the unweighted eval losses."""
    total = None
    for k, values in evals.items():
        if not k.endswith("_original_eval") or "normalization" in k:
            continue
        arr = np.asarray(values, dtype=np.float64)
        std = arr.std()
        z = (arr - arr.mean()) / std if std > 0 else np.zeros_like(arr)
        total = z if total is None else total + z
    if total is None or not len(total):
        return 0, 0.0
    idx = int(np.argmin(total))
    return idx, float(total[idx])


def _score_paths(ctx: _Ctx, paths, inputs) -> float | None:
    try:
        if ctx.scorer is None:
            from ...scoring import get_scorer

            ctx.scorer = get_scorer(ctx.device)
        return round(ctx.scorer.score_tensors(render_paths(paths, CANVAS).float().cpu(),
                                              inputs["scene_t"].float().cpu()), 2)
    except Exception:
        return None


# ----------------------------------------------------------------------------- parts and cells


def _run_part(ctx: _Ctx, cfg: PartConfig, inputs: dict) -> RunResult:
    """``run_sketch.py``: all seeds, the best one wins (lowest eval loss, or lowest normalised loss
    when strokes are removed)."""
    tag = f"{cfg.name}_l{cfg.layer}" + (f"_level{cfg.level}" if cfg.level else "")
    ctx.reporter.event("stage", seed=ctx.cell, name=f"scene_{cfg.name}")
    results = []
    base = int(ctx.s["seed"])
    for j in range(int(ctx.s["num_sketches"])):
        seed = base + j * 1000
        results.append(_train(ctx, cfg, seed, os.path.join(ctx.job_dir, "runs", tag, f"seed{seed}"), inputs))
        if ctx.cancelled:
            break
    if cfg.width_optim:
        return min(results, key=lambda r: r.best_normalised_loss if r.best_normalised_loss is not None else 0.0)
    return min(results, key=lambda r: min(r.loss_eval) if r.loss_eval else float("inf"))


def _clip_layer_loss(run: RunResult, layer: int, part: str) -> float:
    """``get_clip_loss2``: the unweighted layer loss at the best evaluation (objects: + layer 4)."""
    values = run.evals.get(f"clip_vit_l{layer}_original_eval") or [1.0]
    i = min(run.best_eval_index, len(values) - 1)
    loss = values[i]
    if part == "object":
        l4 = run.evals.get("clip_vit_l4_original_eval") or [0.0]
        loss += l4[min(i, len(l4) - 1)]
    return max(float(loss), 1e-8)


def _fidelity_config(ctx: _Ctx, part: str, layer: int, inputs: dict) -> PartConfig:
    s = ctx.s
    weights = {layer: 1.0}
    if part == "object" and layer != 4:
        weights = {4: 0.5, layer: 1.0}
    if part == "object":
        num_iter = int(s["object_num_iter"]) if layer >= 8 else max(int(round(int(s["object_num_iter"]) * 0.6)), 1)
    else:
        num_iter = int(s["num_iter"])
    return PartConfig(name=part, layer=layer, level=0, target=inputs[f"{part}_t"], layer_weights=weights,
                      num_iter=num_iter, eval_interval=int(s["eval_interval"]), min_eval_iter=int(s["min_eval_iter"]),
                      gradnorm=part == "object" and layer != 4)


def _simplify_config(ctx: _Ctx, part: str, layer: int, level: int, ratio: float, prev: RunResult,
                     first: bool, inputs: dict) -> PartConfig:
    weights = {layer: 1.0}
    if part == "object" and layer != 4:
        weights = {4: 0.5, layer: 1.0}
    states = dict(prev.state)
    if first:  # from the fidelity sketch: its point MLP only, a new width MLP
        states = {"mlp": prev.state["mlp"]}
    return PartConfig(name=part, layer=layer, level=level, target=inputs[f"{part}_t"], layer_weights=weights,
                      num_iter=int(ctx.s["simplify_num_iter"]), eval_interval=SIMPLIFY_EVAL_INTERVAL,
                      min_eval_iter=SIMPLIFY_MIN_EVAL_ITER, gradnorm=True, width_optim=True, ratio=ratio,
                      init_points=prev.points_init, states=states, load_optim=not first)


def _write_cell(ctx: _Ctx, layer: int, level: int, bg: RunResult, obj: RunResult | None, inputs: dict,
                extra: dict, status: str = "done") -> SeedResult:
    from ...pipeline import score_run

    cell = schema.scene_cell_id(layer, level)
    run_name = schema.scene_run_name(ctx.target, layer, level)
    cell_dir = os.path.join(ctx.job_dir, run_name)
    logs = os.path.join(cell_dir, "svg_logs")
    os.makedirs(logs, exist_ok=True)
    mask = inputs["mask_canvas"]
    obj_paths = C.object_to_scene(obj.paths, inputs["params"], CANVAS) if obj is not None else []
    paths = C.combine(bg.paths, obj_paths, mask, CANVAS)
    svg = paths_to_svg(paths, CANVAS)
    for name, content in (("best_iter.svg", svg), ("final_svg.svg", svg),
                          ("background.svg", paths_to_svg(bg.paths, CANVAS))):
        with open(os.path.join(cell_dir, name), "w", encoding="utf-8") as f:
            f.write(content)
    if obj is not None:
        with open(os.path.join(cell_dir, "object.svg"), "w", encoding="utf-8") as f:
            f.write(paths_to_svg(obj_paths, CANVAS))
    # drawing process for the GIF / MP4 export: background first, then the object on top
    n = 0
    for _, fr in bg.frames:
        with open(os.path.join(logs, f"svg_iter{n}.svg"), "w", encoding="utf-8") as f:
            f.write(paths_to_svg(C.combine(fr, [], None, CANVAS) if obj is None else
                                 C.cut_by_mask(fr, mask, CANVAS), CANVAS))
        n += 1
    if obj is not None:
        base = C.cut_by_mask(bg.paths, mask, CANVAS)
        for _, fr in obj.frames:
            with open(os.path.join(logs, f"svg_iter{n}.svg"), "w", encoding="utf-8") as f:
                f.write(paths_to_svg(base + C.object_to_scene(fr, inputs["params"], CANVAS), CANVAS))
            n += 1
    big = [type(p)(p.num_control_points, p.points * 2, p.stroke_width * 2, is_closed=False) for p in paths]
    imaging.tensor_to_pil(render_paths(big, CANVAS * 2)).save(os.path.join(cell_dir, "best_iter.png"))
    inputs["scene"].save(os.path.join(cell_dir, "input.png"))
    clip_sc = score_run(os.path.join(cell_dir, "best_iter.svg"), inputs["scene"], ctx.device, ctx.reporter)
    seconds = bg.seconds + (obj.seconds if obj is not None else 0.0)
    config = {"method": "scenesketch", "target": ctx.target, "layer": layer, "level": level, "cell": cell,
              "strokes": len(paths), "background_strokes": len(bg.paths),
              "object_strokes": len(obj.paths) if obj is not None else 0, "clip_score": clip_sc,
              "background_run": bg.run_dir, "object_run": obj.run_dir if obj is not None else None,
              "resize_params": inputs["params"], "best_iter": 10 ** 9, "seconds": seconds,
              "settings": ctx.s, **extra}
    with open(os.path.join(cell_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, default=str)
    best_loss = round(1.0 - clip_sc / 100.0, 4) if clip_sc is not None else 1.0
    result = SeedResult(seed=cell, run_name=run_name, run_dir=cell_dir, best_loss=best_loss, best_iter=0,
                        iterations_done=ctx.cell_done, best_svg=os.path.join(cell_dir, "best_iter.svg"),
                        status=status, method="scenesketch", clip_score=clip_sc, seconds=round(seconds, 1))
    ctx.reporter.event("seed_done", seed=cell, best_loss=best_loss, best_iter=0, status=status, run_dir=cell_dir,
                       svg=svg, clip_score=clip_sc)
    return result


def _cell_iterations(ctx: _Ctx, cell: int) -> int:
    n = schema.scene_cell_iterations(ctx.s, cell)
    if ctx.skip_background:
        per_seed = int(ctx.s["num_iter"]) if cell % 100 == 0 else int(ctx.s["simplify_num_iter"])
        n -= int(ctx.s["num_sketches"]) * per_seed
    return max(n, 1)


def _start_cell(ctx: _Ctx, cell: int):
    ctx.cell = cell
    ctx.cell_total = _cell_iterations(ctx, cell)
    ctx.cell_done = 0


def _empty_run(ctx: _Ctx, name: str, layer: int, level: int) -> RunResult:
    """Stand-in for a part that is not sketched (plain background)."""
    return RunResult(seed=int(ctx.s["seed"]), run_dir="", points_init=torch.zeros(0, 4, 2), paths=[], state={},
                     evals={f"clip_vit_l{layer}_original_eval": [1.0]})


def run_cells(settings, target, job_dir, cells, reporter=None, control=None, device=None) -> list[SeedResult]:
    """Compute the requested cells (fidelity sketches first, then their simplification levels)."""
    from ...pipeline import Control, Reporter, _png_bytes, resolve_device

    reporter = reporter or Reporter()
    control = control or Control()
    s = schema.normalize({**settings, "method": "scenesketch"})
    if device is None:
        device, warning = resolve_device(s)
        if warning:
            code, _, text = warning.partition(":")
            reporter.event("warning", message=text, code=code)
    wanted = [int(c) for c in cells]
    ctx = _Ctx(s, target, job_dir, wanted, reporter, control, device)
    if not wanted:
        return []
    _start_cell(ctx, wanted[0])
    reporter.event("stage", seed=ctx.cell, name="loading")
    inputs = _prepare(ctx)
    inputs["scene"].save(os.path.join(job_dir, "scene.png"))
    inputs["background"].save(os.path.join(job_dir, "background.png"))
    mask_png = Image.fromarray(((inputs["mask"] if inputs["mask"] is not None else
                                 np.zeros(inputs["scene"].size[::-1])) * 255).astype(np.uint8), mode="L")
    mask_png.save(os.path.join(job_dir, "mask.png"))
    reporter.event("input", seed=ctx.cell, png=_png_bytes(inputs["scene"]), mask_png=_png_bytes(mask_png))
    reporter.event("condition", seed=ctx.cell, png=_png_bytes(inputs["background"]), condition="background")
    if inputs["object"] is not None:
        inputs["object"].save(os.path.join(job_dir, "object.png"))
    split = inputs["object"] is not None
    if inputs.get("plain_background"):
        ctx.skip_background = True
        ctx.total_iters = sum(_cell_iterations(ctx, c) for c in wanted)
        reporter.event("warning", code="scene_plain_background",
                       message="The background is plain – only the object is sketched.")
    bg_divs = schema.parse_scene_divs(s["background_divs"], schema.SCENE_BACKGROUND_DIVS)
    obj_divs = schema.parse_scene_divs(s["object_divs"], schema.SCENE_OBJECT_DIVS)

    results: list[SeedResult] = []
    cell_images: dict = {}

    def add(layer, level, bg, obj, extra):
        res = _write_cell(ctx, layer, level, bg, obj, inputs, extra, "cancelled" if ctx.cancelled else "done")
        results.append(res)
        cell_images[(layer, level)] = os.path.join(res.run_dir, "best_iter.png")

    for layer in ctx.layers:
        if not any(c // 100 == layer for c in wanted) or ctx.cancelled:
            continue
        # ---------------------------------------------------- fidelity (level 0)
        _start_cell(ctx, schema.scene_cell_id(layer, 0))
        ctx.preview_other = []
        if ctx.skip_background:
            bg = _empty_run(ctx, "background", layer, 0)
        else:
            bg = _run_part(ctx, _fidelity_config(ctx, "background", layer, inputs), inputs)
        obj = None
        if split and not ctx.cancelled:
            ctx.preview_other = C.cut_by_mask(bg.paths, inputs["mask_canvas"], CANVAS)
            obj = _run_part(ctx, _fidelity_config(ctx, "object", layer, inputs), inputs)
        rat_bg = ratios(1.0 / _clip_layer_loss(bg, layer, "background"), bg_divs[layer], ctx.levels)
        rat_obj = ratios(1.0 / _clip_layer_loss(obj, layer, "object"), obj_divs[layer], ctx.levels) \
            if obj is not None else []
        add(layer, 0, bg, obj, {"ratios_background": rat_bg, "ratios_object": rat_obj})
        # ---------------------------------------------------- simplicity levels
        prev_bg, prev_obj = bg, obj
        for level in range(1, ctx.levels + 1):
            if schema.scene_cell_id(layer, level) not in wanted or ctx.cancelled:
                break
            _start_cell(ctx, schema.scene_cell_id(layer, level))
            ctx.preview_other = C.object_to_scene(prev_obj.paths, inputs["params"], CANVAS) if prev_obj else []
            if ctx.skip_background:
                new_bg = _empty_run(ctx, "background", layer, level)
            else:
                new_bg = _run_part(ctx, _simplify_config(ctx, "background", layer, level, rat_bg[level - 1], prev_bg,
                                                         level == 1, inputs), inputs)
            new_obj = prev_obj
            if prev_obj is not None and not ctx.cancelled:
                ctx.preview_other = C.cut_by_mask(new_bg.paths, inputs["mask_canvas"], CANVAS)
                cfg = _simplify_config(ctx, "object", layer, level, rat_obj[level - 1], prev_obj, level == 1,
                                       inputs)
                new_obj = _run_part(ctx, cfg, inputs)
            add(layer, level, new_bg, new_obj, {"ratio_background": rat_bg[level - 1],
                                                "ratio_object": rat_obj[level - 1] if rat_obj else None})
            prev_bg, prev_obj = new_bg, new_obj
    if ctx.cancelled:
        reporter.event("log", message="SceneSketch: cancelled – the finished sketches are kept")
    if cell_images:
        C.matrix_image(cell_images, ctx.layers, ctx.levels).save(os.path.join(job_dir, "matrix.png"))
    ctx.clip_model = None
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return results
