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


def default_settings() -> dict[str, Any]:
    return {p.key: copy.deepcopy(p.default) for p in PARAMS}


def apply_preset(settings: dict[str, Any], preset: str) -> dict[str, Any]:
    out = dict(settings)
    out.update(PRESETS[preset])
    return out


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
    """Fill in defaults, coerce types and drop unknown keys."""
    out = default_settings()
    for key, value in settings.items():
        if key in PARAMS_BY_KEY:
            out[key] = coerce(PARAMS_BY_KEY[key], value)
    return out


def is_enabled(param: Param, settings: dict[str, Any]) -> bool:
    return param.enabled_if is None or bool(param.enabled_if(settings))


def changed_keys(settings: dict[str, Any]) -> list[str]:
    defaults = default_settings()
    return [k for k in defaults if settings.get(k) != defaults[k]]


def to_cli_args(settings: dict[str, Any]) -> list[str]:
    """Command line (for ``CLIPassoStudio.exe --cli``) that reproduces ``settings``."""
    args: list[str] = []
    defaults = default_settings()
    for p in PARAMS:
        value = settings.get(p.key, p.default)
        if value == defaults[p.key]:
            continue
        flag = f"--{p.cli or p.key}"
        if p.kind == "bool":
            args += [flag, str(int(bool(value)))]
        else:
            args += [flag, str(value)]
    return args
