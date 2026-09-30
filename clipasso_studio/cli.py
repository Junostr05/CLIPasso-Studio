"""Command line interface compatible with the original scripts of all three methods.

    CLIPassoStudio.exe --cli --target_file camel.png --num_strokes 16 --mask_object 1
    CLIPassoStudio.exe --cli --method swiftsketch --input_data camel.png --guidance_param 2.5
    CLIPassoStudio.exe --cli --method controlsketch --target camel.png --condition depth
    CLIPassoStudio.exe --cli --method scenesketch --im_name ballerina --layers 2,8,11

``--method`` (default ``clipasso``) selects the method; every argument of the original
``run_object_sketching.py`` / ``config.py`` (CLIPasso), ``generate.py`` (SwiftSketch),
``ControlSketch/config.py`` and the SceneSketch scripts is accepted (except the Jupyter / Weights &
Biases ones, which are ignored), so commands from the original READMEs keep working.
``--method X --help`` lists the options of method X.
"""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__, paths
from . import settings_schema as schema

METHOD_TITLES = {
    "clipasso": "CLIPasso: semantically-aware object sketching",
    "swiftsketch": "SwiftSketch: a diffusion model for image-to-vector sketch generation",
    "controlsketch": "ControlSketch: SDS-based vector sketching with Stable Diffusion + ControlNet",
    "scenesketch": "SceneSketch (CLIPascene): scene sketching with different types and levels of abstraction",
}

# arguments of the original scripts that are accepted for compatibility and ignored
_IGNORED = {
    "clipasso": (("--display_logs", int), ("--use_wandb", int), ("--wandb_user", str), ("--wandb_name", str),
                 ("--wandb_project_name", str), ("--batch_size", int), ("--use_gpu", int)),
    "swiftsketch": (("--model_path", str), ("--refine_model_path", str), ("--generate_batch_size", int),
                    ("--save_svg", int), ("--save_final_sketch_in_dict", int), ("--batch_size", int),
                    ("--use_wandb", int), ("--wandb_user", str), ("--wandb_name", str),
                    ("--wandb_project_name", str), ("--experiment_name", str), ("--title", str)),
    "controlsketch": (("--save_svg_in_dict", int), ("--diffusion_model", str), ("--lr_scheduler", int),
                      ("--batch_size", int),
                      ("--use_wandb", int), ("--wandb_user", str), ("--wandb_name", str),
                      ("--wandb_project_name", str), ("--experiment_name", str)),
    "scenesketch": (("--output_pref", str), ("--test_name", str), ("--object_or_background", str),
                    ("--min_div", float), ("--divs", str), ("--mask_object", int), ("--mlp_train", int),
                    ("--width_optim", int), ("--gradnorm", int), ("--run_u2net", int), ("--top_path", str),
                    ("--use_gpu", int), ("--multiprocess", int), ("--display_logs", int), ("--use_wandb", int),
                    ("--wandb_user", str), ("--wandb_name", str), ("--wandb_project_name", str)),
}


def method_from_argv(argv: list[str] | None) -> str:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--method", choices=schema.METHODS, default=schema.DEFAULT_METHOD)
    ns, _ = pre.parse_known_args(argv)
    return ns.method


def _add_param(parser: argparse.ArgumentParser, p: schema.Param) -> None:
    flags = [f"--{p.cli or p.key}"]
    if p.cli and p.cli != p.key:
        flags.append(f"--{p.key}")
    kwargs = {"dest": p.key, "default": None}
    if p.key == "device":
        # auto / cpu / cuda, or a GPU index like SwiftSketch's --device <n>
        kwargs.update(type=str, metavar="{auto,cpu,cuda,<gpu index>}")
    elif p.kind in ("bool", "int"):
        kwargs["type"] = int
    elif p.kind == "float":
        kwargs["type"] = float
    elif p.kind == "choice":
        kwargs["type"] = type(p.choices[0])
        kwargs["choices"] = list(p.choices)
    else:
        kwargs["type"] = str
    parser.add_argument(*flags, **kwargs)


def build_parser(method: str = schema.DEFAULT_METHOD) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="CLIPassoStudio --cli", description=f"{METHOD_TITLES[method]} (CLI mode)")
    parser.add_argument("--method", choices=schema.METHODS, default=method,
                        help="sketching method (default: clipasso); --method X --help lists its options")
    parser.add_argument("--target_file", "--target", "--input_data", "--im_name", dest="target_file", required=True,
                        help="input image (path, or a file name inside ./target_images)")
    parser.add_argument("--output_dir", default=None, help="output folder (default: ./output_sketches)")
    parser.add_argument("-cpu", "--cpu", action="store_true", help="force CPU")
    parser.add_argument("--preset", choices=sorted(schema.METHOD_PRESETS[method]), help="start from a preset")
    parser.add_argument("--no_download", action="store_true",
                        help="fail instead of downloading missing models")
    parser.add_argument("--version", action="version", version=f"CLIPasso Studio {__version__}")
    if method == "clipasso":
        parser.add_argument("--num_strokes", type=int, dest="num_paths", help="alias of --num_paths")
    if method == "swiftsketch":
        parser.add_argument("--cuda", type=str, default=None, help=argparse.SUPPRESS)
    if method == "controlsketch":
        parser.add_argument("--use_cpu", type=int, default=None, help="1 = force CPU")
    if method == "scenesketch":
        parser.add_argument("--num_paths", type=int, dest="num_strokes", help="alias of --num_strokes")
        parser.add_argument("--layer_opt", type=int, default=None,
                            help="a single fidelity layer (like generate_fidelity_levels.py / run_ratio.py)")
    for p in schema.params_for(method):
        if method == "clipasso" and p.key == "num_paths":
            parser.add_argument("--num_paths", type=int, dest="num_paths")
            continue
        _add_param(parser, p)
    for flag in ("-colab", "-display"):
        parser.add_argument(flag, action="store_true", help=argparse.SUPPRESS)
    for flag, typ in _IGNORED[method]:
        parser.add_argument(flag, type=typ, help=argparse.SUPPRESS)
    return parser


def settings_from_args(ns: argparse.Namespace) -> dict:
    method = getattr(ns, "method", schema.DEFAULT_METHOD)
    settings = schema.default_settings(method)
    if ns.preset:
        settings = schema.apply_preset(settings, ns.preset)
    for p in schema.params_for(method):
        value = getattr(ns, p.key, None)
        if value is None:
            continue
        if p.key == "device" and str(value).isdigit():
            settings["gpunum"] = int(value)
            continue
        settings[p.key] = schema.coerce(p, value)
    if getattr(ns, "layer_opt", None) is not None:
        settings["layers"] = schema.coerce(schema.param(method, "layers"), str(ns.layer_opt))
    force_cpu = ns.cpu or getattr(ns, "use_gpu", None) == 0 or getattr(ns, "use_cpu", None) == 1
    if str(getattr(ns, "cuda", None)).lower() in ("0", "false", "no"):
        force_cpu = True
    if force_cpu:
        settings["device"] = "cpu"
    return schema.normalize(settings)


def resolve_target(name: str) -> str:
    if os.path.isfile(name):
        return name
    for candidate in (os.path.join(os.getcwd(), "target_images", name),
                      os.path.join(os.getcwd(), "target_images", "scene", f"{name}.png")):  # SceneSketch --im_name
        if os.path.isfile(candidate):
            return candidate
    raise SystemExit(f"{name} does not exist!")


def ensure_models(settings: dict, allow_download: bool = True) -> None:
    """Download the models the settings need (e.g. the SwiftSketch weights), printing progress."""
    from .engine import methods, model_store

    for key in methods.required_models(settings):
        if model_store.is_available(key):
            continue
        spec = model_store.SPECS.get(key)
        if not allow_download or spec is None:
            raise SystemExit(f"Model '{key}' is not installed (download it on the 'Models' page).")
        print(f"Downloading {key} (~{spec.download_size / 1e6:.0f} MB) …", flush=True)
        last = [-1]

        def progress(done, total, last=last):
            if total <= 0:  # downloaded, now checking / converting
                if last[0] != "busy":
                    last[0] = "busy"
                    print("  preparing …", flush=True)
                return
            pct = int(done * 100 / total)
            if pct != last[0] and pct % 5 == 0:
                last[0] = pct
                print(f"  {pct:3d}%  {done / 1e6:.0f} MB", flush=True)

        model_store.install(key, progress=progress)


def main(argv: list[str] | None = None) -> int:
    from .engine import pipeline

    argv = list(sys.argv[1:] if argv is None else argv)
    method = method_from_argv(argv)
    ns = build_parser(method).parse_args(argv)
    settings = settings_from_args(ns)
    target = resolve_target(ns.target_file)
    out = ns.output_dir or os.path.join(os.getcwd(), "output_sketches")
    os.makedirs(out, exist_ok=True)
    print(f"CLIPasso Studio {__version__} – {method} – processing {target}")
    print(f"models: {paths.bundled_models_dir()}")
    ensure_models(settings, allow_download=not ns.no_download)
    summary = pipeline.run_job(settings, target, out, pipeline.PrintReporter())
    print(f"Results: {os.path.dirname(summary['best_svg'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
