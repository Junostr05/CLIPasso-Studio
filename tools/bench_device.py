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
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# measured as the Mac app's engine computes (clipasso_studio/headless/__main__.py): an operation without an Apple GPU
# kernel (e.g. the backward pass of antialiased resizing in CLIPasso's augmentations) runs on the CPU – set before
# PyTorch is imported
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

from clipasso_studio import settings_schema as schema  # noqa: E402

from clipasso_studio.engine.device_bench import (  # noqa: E402,F401 (the measuring lives in the package)
    IMAGE_TYPES, available, clip_agreement, images_from, run_one, settings_for, table)

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
    checks = []
    for device in [d for d in args.devices.split(",") if d and d != "cpu"]:
        checks += clip_agreement(device, images)
    for row in checks:
        print(json.dumps(row), file=sys.stderr, flush=True)
    Path(args.out).write_text(json.dumps(rows + checks, indent=1), encoding="utf-8")
    print(table(rows))
    if checks:
        print("\nCLIP ViT-B/32 on the device against the CPU (cosine of the embeddings; 1.0 = the same):\n")
        for row in checks:
            print("- " + ", ".join(f"{k}: {v}" for k, v in row.items() if k != "check"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
