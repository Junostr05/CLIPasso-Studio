"""Measure the speed of the compute devices per method – the CPU against the Apple GPU (MPS) on a Mac, or CUDA.

    python tools/bench_device.py --methods clipasso,swiftsketch --devices cpu,mps --repeats 3 \\
        --images benchmarks/images --iters 200 --out bench.json

Every (method, device, image, repeat) is one job of the method's "fast" preset with one sketch (``--iters``: the
iterations of the methods that optimise). Written as JSON rows ``{method, device, image, repeat, seconds,
sec_per_iter, iterations, clip_score, cpu_clip_score, nan_in_svg, error, traceback}`` and printed as a table;
``cpu_clip_score`` judges every sketch with the same scorer on the CPU, so the devices compare (``clip_score`` is the
one the job computed on its own device). A device that is not there is a row
with ``error: "unavailable"`` – it is never left out. ``settings_schema.MPS_AUTO`` (which methods "auto" computes on the
Apple GPU) is filled from these numbers, not from guesses.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clipasso_studio import settings_schema as schema  # noqa: E402

IMAGE_TYPES = (".png", ".jpg", ".jpeg")


def images_from(spec: str) -> list[Path]:
    """Files as given; for a folder the first image of each of its sub-folders (one per category), or its own."""
    out = []
    for part in [p for p in spec.split(",") if p]:
        path = Path(part)
        if path.is_file():
            out.append(path)
            continue
        groups = sorted(d for d in path.iterdir() if d.is_dir()) or [path]
        for group in groups:
            files = sorted(f for f in group.iterdir() if f.suffix.lower() in IMAGE_TYPES)
            if files:
                out.append(files[0])
    return out


def settings_for(method: str, device: str, iters: int) -> dict:
    s = schema.apply_preset(schema.default_settings(method), "fast")
    s.update(device=device, num_sketches=1)
    keys = {p.key for p in schema.params_for(method)}
    for key in ("num_iter", "object_num_iter", "simplify_num_iter"):
        if iters and key in keys:
            s[key] = iters
    if method == "scenesketch":
        s.update(simplicity_levels=0, min_eval_iter=0)
    return schema.normalize(s)


def available(device: str) -> bool:
    import torch

    from clipasso_studio.engine import pipeline

    if device == "cpu":
        return True
    if device == "cuda":
        return bool(torch.cuda.is_available())
    if device == "mps":
        return pipeline.mps_available()
    return False


class _Timer:
    """Collects the iterations of a run (the time without loading the models)."""

    def __init__(self):
        self.elapsed: list[float] = []

    def event(self, kind, **data):
        if kind == "iteration" and data.get("elapsed") is not None:
            self.elapsed.append(float(data["elapsed"]))


def run_one(method: str, device: str, image: Path, iters: int, work: Path) -> dict:
    from clipasso_studio.engine import pipeline
    from clipasso_studio.engine.model_store import ModelMissingError

    row = {"seconds": None, "sec_per_iter": None, "iterations": None, "clip_score": None, "cpu_clip_score": None,
           "nan_in_svg": None, "error": None, "traceback": None}
    if not available(device):
        row["error"] = "unavailable"
        return row
    timer = _Timer()
    started = time.perf_counter()
    try:
        summary = pipeline.run_job(settings_for(method, device, iters), str(image), str(work / f"{method}-{device}"),
                                   reporter=timer)
    except ModelMissingError as exc:
        row["error"] = f"model_missing: {exc.spec_key}"
        return row
    except Exception as exc:  # reported in the row (with where it happened), the other runs go on
        row["error"] = f"{type(exc).__name__}: {exc}"
        row["traceback"] = traceback.format_exc()[-6000:]
        return row
    row["seconds"] = round(time.perf_counter() - started, 2)
    row["iterations"] = len(timer.elapsed)
    if len(timer.elapsed) > 1:
        row["sec_per_iter"] = round((timer.elapsed[-1] - timer.elapsed[0]) / (len(timer.elapsed) - 1), 4)
    elif timer.elapsed:
        row["sec_per_iter"] = round(timer.elapsed[0], 4)
    score = summary.get("clip_score") if isinstance(summary, dict) else None
    row["clip_score"] = round(float(score), 2) if score is not None else None
    best = summary.get("best_svg") if isinstance(summary, dict) else None
    if best and Path(best).is_file():
        # the same judge for every device: CLIP on the CPU, against the input the run prepared (as the job's own score)
        from clipasso_studio.engine import imaging, scoring

        text = Path(best).read_text(encoding="utf-8")
        row["nan_in_svg"] = "nan" in text.lower()
        prepared = Path(best).parent / str(summary.get("best_run") or "") / "input.png"
        target = imaging.load_rgb(str(prepared if prepared.is_file() else image))
        row["cpu_clip_score"] = round(scoring.clip_score(best, target, device="cpu"), 2)
    return row


def table(rows: list[dict]) -> str:
    head = ("| method | device | image | repeat | seconds | s/iter | iterations | CLIP score | CLIP score (CPU) | "
            "NaN | error |")
    lines = [head, "|" + "---|" * 11]
    for r in rows:
        cells = [r["method"], r["device"], r["image"], r["repeat"], r["seconds"], r["sec_per_iter"], r["iterations"],
                 r["clip_score"], r["cpu_clip_score"], r["nan_in_svg"], r["error"] or ""]
        lines.append("| " + " | ".join("" if c is None else str(c) for c in cells) + " |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--methods", default="clipasso,swiftsketch,controlsketch,scenesketch")
    parser.add_argument("--devices", default="cpu,mps")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--images", default=str(ROOT / "benchmarks" / "images"))
    parser.add_argument("--iters", type=int, default=200, help="iterations of the optimising methods (0: preset)")
    parser.add_argument("--out", default="bench.json")
    parser.add_argument("--work", default="", help="folder for the jobs (default: a temporary one)")
    args = parser.parse_args(argv)
    methods = [m for m in args.methods.split(",") if m]
    unknown = set(methods) - set(schema.METHODS)
    if unknown:
        parser.error(f"unknown methods: {sorted(unknown)}")
    images = images_from(args.images)
    if not images:
        parser.error(f"no images in {args.images}")
    work = Path(args.work) if args.work else Path(tempfile.mkdtemp(prefix="bench_device_"))
    rows = []
    for method in methods:
        for device in [d for d in args.devices.split(",") if d]:
            for image in images:
                for repeat in range(1, args.repeats + 1):
                    row = {"method": method, "device": device, "image": image.name, "repeat": repeat,
                           **run_one(method, device, image, args.iters, work)}
                    rows.append(row)
                    print(json.dumps(row), file=sys.stderr, flush=True)
                    if row["error"] == "unavailable":
                        break  # (the same for every repeat)
    Path(args.out).write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(table(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
