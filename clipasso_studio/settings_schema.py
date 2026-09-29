"""Single source of truth for every CLIPasso option.

Each :class:`Param` mirrors one argument of the original ``run_object_sketching.py`` /
``config.py`` (same key and CLI flag), plus UI metadata. The GUI builds its parameter
panel from this list and the CLI builds its argparse parser from it, so every option of
the original tool is reachable in both.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable, Iterable

CLIP_MODELS = ("RN50", "RN101", "RN50x4", "RN50x16", "ViT-B/32", "ViT-B/16")

GROUPS = (
    "basics",
    "image",
    "strokes",
    "init",
    "loss",
    "optim",
    "augment",
    "hardware",
)


@dataclass(frozen=True)
class Param:
    key: str
    default: Any
    kind: str  # int | float | bool | choice | text | path | layers | flags
    group: str
    cli: str | None = None  # original command line flag (without dashes)
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    decimals: int = 2
    choices: tuple = ()
    advanced: bool = True
    # enabled only when ``enabled_if(settings)`` is true (UI greys the field out)
    enabled_if: Callable[[dict], bool] | None = None


def _on(key: str) -> Callable[[dict], bool]:
    return lambda s: bool(s.get(key))


PARAMS: tuple[Param, ...] = (
    # ------------------------------------------------------------------ basics
    Param("num_paths", 16, "int", "basics", cli="num_paths", minimum=1, maximum=256, advanced=False),
    Param("num_iter", 2001, "int", "basics", cli="num_iter", minimum=1, maximum=20000, step=100, advanced=False),
    Param("num_sketches", 3, "int", "basics", cli="num_sketches", minimum=1, maximum=16, advanced=False),
    Param("seed", 0, "int", "basics", cli="seed", minimum=0, maximum=10_000_000, advanced=False),
    # ------------------------------------------------------------------- image
    Param("mask_object", False, "bool", "image", cli="mask_object", advanced=False),
    Param("fix_scale", False, "bool", "image", cli="fix_scale", advanced=False),
    Param("image_scale", 224, "int", "image", cli="image_scale", minimum=64, maximum=1024, step=32),
    # ----------------------------------------------------------------- strokes
    Param("width", 1.5, "float", "strokes", cli="width", minimum=0.1, maximum=20.0, step=0.1, decimals=2),
    Param("num_segments", 1, "int", "strokes", cli="num_segments", minimum=1, maximum=16),
    Param("control_points_per_seg", 4, "choice", "strokes", cli="control_points_per_seg", choices=(2, 3, 4)),
    Param("path_svg", "none", "path", "strokes", cli="path_svg"),
    # -------------------------------------------------------------------- init
    Param("attention_init", True, "bool", "init", cli="attention_init"),
    Param("saliency_model", "clip", "choice", "init", cli="saliency_model", choices=("clip", "dino"),
          enabled_if=_on("attention_init")),
    Param("saliency_clip_model", "ViT-B/32", "choice", "init", cli="saliency_clip_model", choices=CLIP_MODELS,
          enabled_if=lambda s: bool(s.get("attention_init")) and s.get("saliency_model") == "clip"),
    Param("xdog_intersec", True, "bool", "init", cli="xdog_intersec",
          enabled_if=lambda s: bool(s.get("attention_init")) and s.get("saliency_model") == "clip"),
    Param("mask_object_attention", "auto", "choice", "init", cli="mask_object_attention",
          choices=("auto", "on", "off"), enabled_if=_on("attention_init")),
    Param("softmax_temp", 0.3, "float", "init", cli="softmax_temp", minimum=0.01, maximum=10.0, step=0.05,
          decimals=2, enabled_if=lambda s: bool(s.get("attention_init")) and s.get("saliency_model") == "clip"),
    Param("text_target", "none", "text", "init", cli="text_target"),
    # -------------------------------------------------------------------- loss
    Param("clip_model_name", "RN101", "choice", "loss", cli="clip_model_name", choices=CLIP_MODELS),
    Param("clip_conv_loss", True, "bool", "loss", cli="clip_conv_loss"),
    Param("clip_conv_loss_type", "L2", "choice", "loss", cli="clip_conv_loss_type", choices=("L2", "Cos", "L1"),
          enabled_if=_on("clip_conv_loss")),
    Param("clip_conv_layer_weights", "0,0,1.0,1.0,0", "layers", "loss", cli="clip_conv_layer_weights",
          minimum=0.0, maximum=10.0, step=0.1, enabled_if=_on("clip_conv_loss")),
    Param("clip_fc_loss_weight", 0.1, "float", "loss", cli="clip_fc_loss_weight", minimum=0.0, maximum=10.0,
          step=0.05, decimals=3, enabled_if=_on("clip_conv_loss")),
    Param("train_with_clip", False, "bool", "loss", cli="train_with_clip"),
    Param("clip_weight", 0.0, "float", "loss", cli="clip_weight", minimum=0.0, maximum=10.0, step=0.1,
          decimals=3, enabled_if=_on("train_with_clip")),
    Param("start_clip", 0, "int", "loss", cli="start_clip", minimum=0, maximum=20000,
          enabled_if=_on("train_with_clip")),
    Param("include_target_in_aug", False, "bool", "loss", cli="include_target_in_aug",
          enabled_if=_on("train_with_clip")),
    Param("clip_text_guide", 0.0, "float", "loss", cli="clip_text_guide", minimum=0.0, maximum=10.0, step=0.1,
          decimals=3),
    Param("percep_loss", "none", "choice", "loss", cli="percep_loss", choices=("none", "L2", "LPIPS")),
    Param("perceptual_weight", 0.0, "float", "loss", cli="perceptual_weight", minimum=0.0, maximum=10.0,
          step=0.1, decimals=3, enabled_if=lambda s: s.get("percep_loss", "none") != "none"),
    # ------------------------------------------------------------------- optim
    Param("lr", 1.0, "float", "optim", cli="lr", minimum=0.0001, maximum=20.0, step=0.1, decimals=4),
    Param("lr_scheduler", False, "bool", "optim", cli="lr_scheduler"),
    Param("force_sparse", False, "bool", "optim", cli="force_sparse"),
    Param("color_lr", 0.01, "float", "optim", cli="color_lr", minimum=0.0, maximum=1.0, step=0.005, decimals=4,
          enabled_if=_on("force_sparse")),
    Param("color_vars_threshold", 0.0, "float", "optim", cli="color_vars_threshold", minimum=0.0, maximum=1.0,
          step=0.05, decimals=2, enabled_if=_on("force_sparse")),
    Param("num_stages", 1, "int", "optim", cli="num_stages", minimum=1, maximum=16),
    Param("eval_interval", 10, "int", "optim", cli="eval_interval", minimum=1, maximum=1000),
    Param("save_interval", 10, "int", "optim", cli="save_interval", minimum=1, maximum=1000),
    # ----------------------------------------------------------------- augment
    Param("augemntations", "affine", "flags", "augment", cli="augemntations", choices=("affine", "noise")),
    Param("num_aug_clip", 4, "int", "augment", cli="num_aug_clip", minimum=0, maximum=32),
    Param("augment_both", True, "bool", "augment", cli="augment_both"),
    Param("aug_scale_min", 0.8, "float", "augment", cli="aug_scale_min", minimum=0.1, maximum=1.0, step=0.05,
          decimals=2),
    Param("noise_thresh", 0.5, "float", "augment", cli="noise_thresh", minimum=0.0, maximum=1.0, step=0.05,
          decimals=2, enabled_if=lambda s: "noise" in str(s.get("augemntations", ""))),
    # ---------------------------------------------------------------- hardware
    Param("device", "auto", "choice", "hardware", choices=("auto", "cpu", "cuda"), advanced=False),
    Param("gpunum", 0, "int", "hardware", cli="gpunum", minimum=0, maximum=15,
          enabled_if=lambda s: s.get("device") != "cpu"),
    Param("multiprocess", False, "bool", "hardware", cli="multiprocess"),
    Param("num_threads", 0, "int", "hardware", minimum=0, maximum=256),
)

PARAMS_BY_KEY: dict[str, Param] = {p.key: p for p in PARAMS}

# Arguments of the original scripts that intentionally have no equivalent setting.
EXCLUDED_ORIGINAL_ARGS: dict[str, str] = {
    "target_file": "input image is chosen in the GUI / passed as --target_file to the CLI",
    "target": "input image is chosen in the GUI / passed as --target_file to the CLI",
    "num_strokes": "alias of num_paths (kept as CLI alias)",
    "output_dir": "application setting (output folder)",
    "use_gpu": "replaced by 'device'",
    "cpu": "replaced by 'device' (kept as CLI alias -cpu)",
    "colab": "Jupyter/Colab display only",
    "display": "Jupyter display only; the GUI shows live progress",
    "display_logs": "Jupyter display only",
    "use_wandb": "Weights & Biases online logging is not part of the desktop app",
    "wandb_user": "Weights & Biases online logging is not part of the desktop app",
    "wandb_name": "run folder name is generated like the original (<name>_<N>strokes_seed<S>)",
    "wandb_project_name": "Weights & Biases online logging is not part of the desktop app",
    "batch_size": "unused by the original code (always a single image)",
}

# Documented deviations from the original defaults (see README).
DEFAULT_DEVIATIONS = {
    # The original parser default is 0.7 but the code hard-codes a crop scale of 0.8.
    "aug_scale_min": "0.8 matches the crop scale the original code actually used",
    # run_object_sketching.py passes 2001 while config.py alone defaults to 500.
    "num_iter": "2001 like run_object_sketching.py",
}

PRESETS: dict[str, dict[str, Any]] = {
    "fast": {"num_iter": 501, "num_sketches": 1},
    "standard": {"num_iter": 2001, "num_sketches": 3},
    "quality": {"num_iter": 3001, "num_sketches": 5},
}


def _hardware(default_multiprocess: bool = False) -> tuple[Param, ...]:
    return (
        Param("device", "auto", "choice", "hardware", choices=("auto", "cpu", "cuda"), advanced=False),
        Param("gpunum", 0, "int", "hardware", cli="gpunum", minimum=0, maximum=15,
              enabled_if=lambda s: s.get("device") != "cpu"),
        Param("multiprocess", default_multiprocess, "bool", "hardware", cli="multiprocess"),
        Param("num_threads", 0, "int", "hardware", minimum=0, maximum=256),
    )


# ------------------------------------------------------------------------ SwiftSketch
# Options of SwiftSketch/generate.py (github.com/swiftsketch/SwiftSketch). Model, diffusion
# and sketch options (layers, num_paths=32, diffusion_steps=50, ...) are read from the
# checkpoint's args.json and therefore not user settings.
SWIFT_PARAMS: tuple[Param, ...] = (
    Param("num_sketches", 1, "int", "basics", minimum=1, maximum=32, advanced=False),
    Param("seed", 20, "int", "basics", cli="seed", minimum=0, maximum=10_000_000, advanced=False),
    Param("mask_object", True, "bool", "image", advanced=False),
    Param("fix_scale", False, "bool", "image", cli="fix_scale", advanced=False),
    Param("guidance_param", 2.5, "float", "diffusion", cli="guidance_param", minimum=1.0, maximum=10.0, step=0.1,
          decimals=2),
    Param("use_refine", True, "bool", "diffusion", cli="use_refine"),
    Param("save_diffusion_sketch", False, "bool", "diffusion", cli="save_diffusion_sketch_in_dict"),
    Param("width", 2.0, "float", "strokes", minimum=0.1, maximum=20.0, step=0.1, decimals=2),
) + _hardware()

SWIFT_GROUPS = ("basics", "image", "diffusion", "strokes", "hardware")

SWIFT_EXCLUDED_ARGS: dict[str, str] = {
    "model_path": "the app manages the checkpoints (Models page)",
    "refine_model_path": "the app manages the checkpoints (Models page)",
    "input_data": "input image is chosen in the GUI / passed as --target_file to the CLI",
    "output_dir": "application setting (output folder)",
    "generate_batch_size": "the app generates num_sketches samples per image",
    "save_final_sketch_in_dict": "npy/npz dataset dictionaries are not used by the app",
    "save_svg": "the SVG is always saved",
    "cuda": "replaced by 'device' (--cuda False is accepted by the CLI)",
    "device": "GPU index – replaced by 'gpunum' (--device <n> is accepted by the CLI)",
    "batch_size": "training option, unused by generate.py",
    "use_wandb": "Weights & Biases online logging is not part of the desktop app",
    "wandb_user": "Weights & Biases online logging is not part of the desktop app",
    "wandb_name": "Weights & Biases online logging is not part of the desktop app",
    "wandb_project_name": "Weights & Biases online logging is not part of the desktop app",
    "experiment_name": "Weights & Biases online logging is not part of the desktop app",
    "title": "Weights & Biases online logging is not part of the desktop app",
}

SWIFT_PRESETS: dict[str, dict[str, Any]] = {
    "fast": {"num_sketches": 1},
    "standard": {"num_sketches": 4},
    "quality": {"num_sketches": 12},
}

# ---------------------------------------------------------------------- ControlSketch
# Options of ControlSketch/config.py (github.com/swiftsketch/SwiftSketch).
CONTROL_CONDITIONS = ("depth", "canny", "hed", "scribble", "seg", "normal")

CONTROL_PARAMS: tuple[Param, ...] = (
    Param("num_strokes", 32, "int", "basics", cli="num_strokes", minimum=1, maximum=256, advanced=False),
    Param("num_iter", 2000, "int", "basics", cli="num_iter", minimum=1, maximum=20000, step=100, advanced=False),
    Param("num_sketches", 1, "int", "basics", minimum=1, maximum=16, advanced=False),
    Param("seed", 0, "int", "basics", cli="seed", minimum=0, maximum=10_000_000, advanced=False),
    Param("caption", "none", "text", "basics", cli="caption", advanced=False),
    Param("fix_scale", False, "bool", "image", cli="fix_scale", advanced=False),
    Param("object_size_ratio", 0.75, "float", "image", cli="object_size_ratio", minimum=0.1, maximum=1.0, step=0.05,
          decimals=2),
    Param("render_size", 512, "int", "image", cli="render_size", minimum=256, maximum=1024, step=64),
    Param("output_svg_size", 512, "int", "image", cli="output_svg_size", minimum=64, maximum=4096, step=64),
    Param("width", 2.5, "float", "strokes", cli="width", minimum=0.1, maximum=20.0, step=0.1, decimals=2),
    Param("num_segments", 1, "int", "strokes", cli="num_segments", minimum=1, maximum=16),
    Param("control_points_per_seg", 4, "choice", "strokes", cli="control_points_per_seg", choices=(2, 3, 4)),
    Param("sort_final_sketch", True, "bool", "strokes", cli="sort_final_sketch"),
    Param("use_init_method", True, "bool", "init", cli="use_init_method"),
    Param("attn_model", "clip", "choice", "init", cli="attn_model", choices=("clip", "diffusion"),
          enabled_if=_on("use_init_method")),
    Param("object_name", "none", "text", "init", cli="object_name",
          enabled_if=lambda s: bool(s.get("use_init_method")) and s.get("attn_model") == "diffusion"),
    Param("condition", "depth", "choice", "sds", cli="condition", choices=CONTROL_CONDITIONS),
    Param("conditioning_scale", 0.15, "float", "sds", cli="conditioning_scale", minimum=0.0, maximum=2.0, step=0.05,
          decimals=2),
    Param("diffusion_guidance_scale", 100, "int", "sds", cli="diffusion_guidance_scale", minimum=1, maximum=200),
    Param("diffusion_timesteps", 1000, "int", "sds", cli="diffusion_timesteps", minimum=100, maximum=1000, step=50),
    Param("lr", 0.8, "float", "optim", cli="lr", minimum=0.0001, maximum=20.0, step=0.1, decimals=4),
    Param("save_interval", 100, "int", "optim", cli="save_interval", minimum=1, maximum=1000),
) + _hardware()

CONTROL_GROUPS = ("basics", "image", "strokes", "init", "sds", "optim", "hardware")

CONTROL_EXCLUDED_ARGS: dict[str, str] = {
    "target": "input image is chosen in the GUI / passed as --target_file to the CLI",
    "save_svg_in_dict": "npy/npz dataset dictionaries are not used by the app",
    "output_dir": "application setting (output folder)",
    "use_cpu": "replaced by 'device' (--use_cpu 1 is accepted by the CLI)",
    "use_wandb": "Weights & Biases online logging is not part of the desktop app",
    "wandb_user": "Weights & Biases online logging is not part of the desktop app",
    "wandb_name": "run folder name is generated by the app",
    "wandb_project_name": "Weights & Biases online logging is not part of the desktop app",
    "experiment_name": "Weights & Biases online logging is not part of the desktop app",
    "batch_size": "always a single image",
    "diffusion_model": "not used by the original code (Stable Diffusion 1.5 is hard-coded)",
    "lr_scheduler": "not used by the original code (constant learning rate)",
}

# ControlSketch defaults that differ from config.py (documented in the README).
CONTROL_DEFAULT_DEVIATIONS = {
    "attn_model": "'clip' (bundled) instead of 'diffusion' (needs the 7 GB SDXL download)",
}

CONTROL_PRESETS: dict[str, dict[str, Any]] = {
    "fast": {"num_iter": 500, "num_sketches": 1},
    "standard": {"num_iter": 2000, "num_sketches": 1},
    "quality": {"num_iter": 3000, "num_sketches": 3},
}

# ---------------------------------------------------------------------------- methods
METHODS = ("clipasso", "swiftsketch", "controlsketch")
DEFAULT_METHOD = "clipasso"

METHOD_PARAMS: dict[str, tuple[Param, ...]] = {
    "clipasso": PARAMS,
    "swiftsketch": SWIFT_PARAMS,
    "controlsketch": CONTROL_PARAMS,
}
METHOD_GROUPS: dict[str, tuple[str, ...]] = {
    "clipasso": GROUPS,
    "swiftsketch": SWIFT_GROUPS,
    "controlsketch": CONTROL_GROUPS,
}
METHOD_PRESETS: dict[str, dict[str, dict[str, Any]]] = {
    "clipasso": PRESETS,
    "swiftsketch": SWIFT_PRESETS,
    "controlsketch": CONTROL_PRESETS,
}
_BY_KEY: dict[str, dict[str, Param]] = {m: {p.key: p for p in ps} for m, ps in METHOD_PARAMS.items()}


def method_of(settings: dict[str, Any] | None) -> str:
    m = (settings or {}).get("method", DEFAULT_METHOD)
    return m if m in METHODS else DEFAULT_METHOD


def params_for(method: str) -> tuple[Param, ...]:
    return METHOD_PARAMS[method]


def param(method: str, key: str) -> Param:
    return _BY_KEY[method][key]


def default_settings(method: str = DEFAULT_METHOD) -> dict[str, Any]:
    out = {p.key: copy.deepcopy(p.default) for p in METHOD_PARAMS[method]}
    out["method"] = method
    return out


def apply_preset(settings: dict[str, Any], preset: str) -> dict[str, Any]:
    out = dict(settings)
    out.update(METHOD_PRESETS[method_of(settings)][preset])
    return out


def num_strokes(settings: dict[str, Any]) -> int:
    """Number of strokes a run will produce (per stage for CLIPasso)."""
    method = method_of(settings)
    if method == "clipasso":
        return int(settings.get("num_paths", 16))
    if method == "controlsketch":
        return int(settings.get("num_strokes", 32))
    return 32  # SwiftSketch checkpoints are trained for 32 strokes


def text_value(value: Any) -> str:
    """'' for unset text parameters (stored as 'none' like in the original CLIPasso)."""
    return "" if value in (None, "", "none") else str(value)


def parse_layer_weights(value: str | Iterable[float]) -> list[float]:
    if isinstance(value, str):
        items = [v.strip() for v in value.replace(";", ",").split(",") if v.strip()]
        return [float(v) for v in items]
    return [float(v) for v in value]


def format_layer_weights(weights: Iterable[float]) -> str:
    return ",".join(f"{float(w):g}" for w in weights)


def num_conv_layers(clip_model_name: str) -> int:
    """Number of intermediate feature maps the conv loss can weight."""
    return 12 if clip_model_name.startswith("ViT") else 5


def coerce(param: Param, value: Any) -> Any:
    """Convert a raw value (e.g. from JSON or the CLI) into the parameter's type."""
    if param.kind == "bool":
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if param.kind == "int":
        value = int(float(value))
    elif param.kind == "float":
        value = float(value)
    elif param.kind == "choice":
        if param.choices and isinstance(param.choices[0], int):
            value = int(value)
        else:
            value = str(value)
        if value not in param.choices:
            raise ValueError(f"{param.key}: {value!r} is not one of {param.choices}")
        return value
    elif param.kind == "layers":
        return format_layer_weights(parse_layer_weights(value))
    elif param.kind == "flags":
        parts = [p for p in str(value).replace(",", "_").split("_") if p]
        return "_".join(p for p in param.choices if p in parts) or "none"
    else:
        value = "none" if value is None or str(value).strip() == "" else str(value)
        return value
    if param.minimum is not None and value < param.minimum:
        value = type(value)(param.minimum)
    if param.maximum is not None and value > param.maximum:
        value = type(value)(param.maximum)
    return value


def normalize(settings: dict[str, Any]) -> dict[str, Any]:
    """Fill in defaults, coerce types and drop unknown keys (for the settings' method)."""
    method = method_of(settings)
    out = default_settings(method)
    by_key = _BY_KEY[method]
    for key, value in settings.items():
        if key in by_key:
            out[key] = coerce(by_key[key], value)
    return out


def is_enabled(param: Param, settings: dict[str, Any]) -> bool:
    return param.enabled_if is None or bool(param.enabled_if(settings))


def changed_keys(settings: dict[str, Any]) -> list[str]:
    defaults = default_settings(method_of(settings))
    return [k for k in defaults if settings.get(k) != defaults[k]]


def to_cli_args(settings: dict[str, Any]) -> list[str]:
    """Command line (for ``CLIPassoStudio.exe --cli``) that reproduces ``settings``."""
    method = method_of(settings)
    args: list[str] = [] if method == DEFAULT_METHOD else ["--method", method]
    defaults = default_settings(method)
    for p in METHOD_PARAMS[method]:
        value = settings.get(p.key, p.default)
        if value == defaults[p.key]:
            continue
        flag = f"--{p.key}"
        if p.kind == "bool":
            args += [flag, str(int(bool(value)))]
        else:
            args += [flag, str(value)]
    return args
