"""Command line interface compatible with the original CLIPasso scripts.

    CLIPassoStudio.exe --cli --target_file camel.png --num_strokes 16 --mask_object 1

Accepts every argument of ``run_object_sketching.py`` and ``config.py`` (except the
Jupyter / Weights & Biases ones), so commands from the original README keep working.
"""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__, paths
from . import settings_schema as schema


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="CLIPassoStudio --cli",
                                     description="CLIPasso: semantically-aware object sketching (CLI mode)")
    parser.add_argument("--target_file", "--target", dest="target_file", required=True,
                        help="input image (path, or a file name inside ./target_images)")
    parser.add_argument("--output_dir", default=None, help="output folder (default: ./output_sketches)")
    parser.add_argument("--num_strokes", type=int, dest="num_paths", help="alias of --num_paths")
    parser.add_argument("-cpu", "--cpu", action="store_true", help="force CPU")
    parser.add_argument("--preset", choices=sorted(schema.PRESETS), help="start from a preset")
    parser.add_argument("--version", action="version", version=f"CLIPasso Studio {__version__}")
    for p in schema.PARAMS:
        flag = f"--{p.cli or p.key}"
        if p.key == "num_paths":
            parser.add_argument(flag, type=int, dest="num_paths")
            continue
        kwargs = {"dest": p.key, "default": None}
        if p.kind == "bool":
            kwargs["type"] = int
        elif p.kind == "int":
            kwargs["type"] = int
        elif p.kind == "float":
            kwargs["type"] = float
        elif p.kind == "choice":
            kwargs["type"] = type(p.choices[0])
            kwargs["choices"] = list(p.choices)
        else:
            kwargs["type"] = str
        parser.add_argument(flag, **kwargs)
    # accepted for compatibility, ignored
    for flag in ("-colab", "-display"):
        parser.add_argument(flag, action="store_true", help=argparse.SUPPRESS)
    for flag, typ in (("--display_logs", int), ("--use_wandb", int), ("--wandb_user", str), ("--wandb_name", str),
                      ("--wandb_project_name", str), ("--batch_size", int), ("--use_gpu", int)):
        parser.add_argument(flag, type=typ, help=argparse.SUPPRESS)
    return parser


def settings_from_args(ns: argparse.Namespace) -> dict:
    settings = schema.default_settings()
    if ns.preset:
        settings = schema.apply_preset(settings, ns.preset)
    for p in schema.PARAMS:
        value = getattr(ns, p.key, None)
        if value is not None:
            settings[p.key] = schema.coerce(p, value)
    if ns.cpu or ns.use_gpu == 0:
        settings["device"] = "cpu"
    return schema.normalize(settings)


def resolve_target(name: str) -> str:
    if os.path.isfile(name):
        return name
    candidate = os.path.join(os.getcwd(), "target_images", name)
    if os.path.isfile(candidate):
        return candidate
    raise SystemExit(f"{name} does not exist!")


def main(argv: list[str] | None = None) -> int:
    from .engine import pipeline

    ns = build_parser().parse_args(argv)
    settings = settings_from_args(ns)
    target = resolve_target(ns.target_file)
    out = ns.output_dir or os.path.join(os.getcwd(), "output_sketches")
    os.makedirs(out, exist_ok=True)
    print(f"CLIPasso Studio {__version__} – processing {target}")
    print(f"models: {paths.bundled_models_dir()}")
    summary = pipeline.run_job(settings, target, out, pipeline.PrintReporter())
    print(f"Results: {os.path.dirname(summary['best_svg'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
