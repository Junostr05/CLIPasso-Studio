"""The CPU against the Apple GPU (MPS) or CUDA, per method, on this machine (tools/bench_device.py and the Mac app's
hardware test, engine op ``device_bench``): each method's "fast" preset with one sketch on each device – the time per
iteration and the sketch's CLIP score, also judged by the same scorer on the CPU so the devices compare – and which
device "auto" should use here (:func:`recommend`).

    python -m clipasso_studio.engine.device_bench --methods clipasso,swiftsketch --iters 40 --image PICTURE

prints its progress as JSON lines ({"event": "row" | "done", …}) – the engine passes them on to the app.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

# measured as the Mac app's engine computes: an operation without an Apple GPU kernel runs on the CPU (set before
# PyTorch is imported)
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

from .. import settings_schema as schema  # noqa: E402

FASTER = 0.8  # the GPU is chosen when it needs at most this share of the CPU's time …
WORSE = 3.0  # … and the CPU judge rates its sketches at most this many points lower


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

    from . import pipeline

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
    from . import pipeline
    from .model_store import ModelMissingError

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
        from . import imaging, scoring

        text = Path(best).read_text(encoding="utf-8")
        row["nan_in_svg"] = "nan" in text.lower()
        prepared = Path(best).parent / str(summary.get("best_run") or "") / "input.png"
        target = imaging.load_rgb(str(prepared if prepared.is_file() else image))
        row["cpu_clip_score"] = round(scoring.clip_score(best, target, device="cpu"), 2)
    return row


def clip_agreement(device: str, images: list[Path]) -> list[dict]:
    """How alike CLIP ViT-B/32 sees each image on ``device`` and on the CPU: the cosine of the two embeddings (1.0:
    the same; the scorer and CLIPasso's loss compute on the device) and, per device, how alike it sees the images to
    each other (the mean cosine of all pairs – near 1.0 means the embeddings collapsed)."""
    import torch
    from PIL import Image
    from torchvision import transforms

    from .scoring import ClipScorer

    if not available(device):
        return [{"check": "clip_embedding", "device": device, "error": "unavailable"}]
    tensors = [transforms.ToTensor()(Image.open(p).convert("RGB"))[None] for p in images]
    embeds = {}
    for dev in ("cpu", device):
        scorer = ClipScorer(dev)
        embeds[dev] = torch.cat([scorer._embed(t.float()).cpu() for t in tensors])
    rows = []
    for i, p in enumerate(images):
        rows.append({"check": "clip_embedding", "device": device, "image": p.name,
                     "cosine_to_cpu": round(float((embeds["cpu"][i] * embeds[device][i]).sum()), 4)})

    def mean_pair(e):
        n = len(e)
        sims = [float((e[i] * e[j]).sum()) for i in range(n) for j in range(i + 1, n)]
        return round(sum(sims) / len(sims), 4) if sims else None

    rows.append({"check": "clip_pairs", "device": device, "cpu_mean_pair": mean_pair(embeds["cpu"]),
                 "device_mean_pair": mean_pair(embeds[device])})
    return rows


def table(rows: list[dict]) -> str:
    head = ("| method | device | image | repeat | seconds | s/iter | iterations | CLIP score | CLIP score (CPU) | "
            "NaN | error |")
    lines = [head, "|" + "---|" * 11]
    for r in rows:
        cells = [r["method"], r["device"], r["image"], r["repeat"], r["seconds"], r["sec_per_iter"], r["iterations"],
                 r["clip_score"], r["cpu_clip_score"], r["nan_in_svg"], r["error"] or ""]
        lines.append("| " + " | ".join("" if c is None else str(c) for c in cells) + " |")
    return "\n".join(lines)


def _median(values: list[float]) -> float | None:
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def recommend(rows: list[dict], gpu: str = "mps") -> dict[str, dict]:
    """Per method measured on the CPU and on ``gpu``: the device "auto" should use – the GPU when it needs at most
    :data:`FASTER` of the CPU's time (per iteration, else per job) and the CPU judge rates its sketches at most
    :data:`WORSE` points lower without NaN; else the CPU. With the numbers it was decided on and why."""
    out: dict[str, dict] = {}
    for method in dict.fromkeys(r["method"] for r in rows):
        mine = [r for r in rows if r["method"] == method]
        cpu = [r for r in mine if r["device"] == "cpu" and not r.get("error")]
        dev = [r for r in mine if r["device"] == gpu and not r.get("error")]
        entry = {"device": "cpu", "cpu_seconds": None, "gpu_seconds": None, "speedup": None, "cpu_score": None,
                 "gpu_score": None, "reason": ""}
        errors = [r["error"] for r in mine if r.get("error")]
        if not cpu or not dev:
            entry["reason"] = errors[0] if errors else "not measured"
            out[method] = entry
            continue
        per_iter = all(r.get("sec_per_iter") for r in cpu + dev)
        key = "sec_per_iter" if per_iter else "seconds"
        c, g = _median([r[key] for r in cpu]), _median([r[key] for r in dev])
        cs, gs = _median([r.get("cpu_clip_score") for r in cpu]), _median([r.get("cpu_clip_score") for r in dev])
        entry.update(cpu_seconds=c, gpu_seconds=g, speedup=round(c / g, 2) if c and g else None, cpu_score=cs,
                     gpu_score=gs)
        if any(r.get("nan_in_svg") for r in dev):
            entry["reason"] = "nan"
        elif not (c and g and g <= FASTER * c):
            entry["reason"] = "slower"
        elif cs is not None and gs is not None and gs < cs - WORSE:
            entry["reason"] = "worse"
        else:
            entry.update(device=gpu, reason="faster")
        out[method] = entry
    return out


def run(methods: list[str], iters: int, image: Path, work: Path, emit=lambda event: None,
        devices: tuple[str, ...] = ("cpu", "mps")) -> dict:
    """Every method on every device once on ``image``; each row is emitted as it is done. -> {rows, checks,
    recommended}."""
    rows = []
    for method in methods:
        for device in devices:
            row = {"method": method, "device": device, "image": image.name, "repeat": 1,
                   **run_one(method, device, image, iters, work)}
            rows.append(row)
            emit({"event": "row", **{k: v for k, v in row.items() if k != "traceback"}})
    checks = []
    for device in devices:
        if device != "cpu":
            checks += clip_agreement(device, [image])
    gpu = next((d for d in devices if d != "cpu"), "mps")
    return {"rows": rows, "checks": checks, "recommended": recommend(rows, gpu)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--methods", default="clipasso,swiftsketch")
    parser.add_argument("--iters", type=int, default=40)
    parser.add_argument("--image", required=True)
    parser.add_argument("--work", default="")
    args = parser.parse_args(argv)
    methods = [m for m in args.methods.split(",") if m in schema.METHODS]
    work = Path(args.work) if args.work else Path(tempfile.mkdtemp(prefix="device_bench_"))

    def emit(event):
        print(json.dumps(event), flush=True)

    result = run(methods, args.iters, Path(args.image), work, emit)
    emit({"event": "done", **result})
    return 0


if __name__ == "__main__":
    sys.exit(main())
