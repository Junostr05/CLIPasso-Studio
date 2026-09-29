"""Job bookkeeping shared by the worker processes and the GUI (no torch import)."""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from .. import settings_schema as schema


class _NullReporter:
    def event(self, kind, **data):
        pass


@dataclass
class SeedResult:
    seed: int
    run_name: str
    run_dir: str
    best_loss: float
    best_iter: int
    iterations_done: int
    best_svg: str
    status: str  # done | cancelled
    method: str = "clipasso"
    clip_score: float | None = None  # CLIP ViT-B/32 similarity sketch <-> input in percent (higher = better)
    seconds: float = 0.0


def job_seeds(settings: dict) -> list[int]:
    """Seeds like run_object_sketching.py: 0, 1000, 2000, ... (offset by ``seed``)."""
    base = int(settings.get("seed", 0))
    return [base + i * 1000 for i in range(int(settings.get("num_sketches", 1)))]


def run_name_for(target: str, settings: dict, seed: int) -> str:
    """Run folder name; CLIPasso keeps the original naming (<name>_<N>strokes_seed<S>)."""
    test_name = os.path.splitext(os.path.basename(target))[0]
    method = schema.method_of(settings)
    prefix = test_name if method == "clipasso" else f"{test_name}_{method}"
    return f"{prefix}_{schema.num_strokes(settings)}strokes_seed{seed}"


def make_job_dir(output_root: str, target: str, method: str = "clipasso") -> str:
    test_name = os.path.splitext(os.path.basename(target))[0]
    if method != "clipasso":
        test_name = f"{test_name}_{method}"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = Path(output_root) / f"{test_name}_{stamp}"
    n = 1
    while path.exists():
        n += 1
        path = Path(output_root) / f"{test_name}_{stamp}-{n}"
    path.mkdir(parents=True)
    return str(path)


def finish_job(job_dir: str, target: str, settings: dict, results: list[SeedResult],
               reporter=None) -> dict:
    """Pick the best sketch and copy it to ``<run>_best.svg`` like the original.

    CLIPasso keeps its own criterion (lowest eval loss). SwiftSketch and ControlSketch have
    no such loss, so the sketch with the highest CLIP similarity to the input wins.
    """
    reporter = reporter or _NullReporter()
    results = [r for r in results if r is not None and os.path.isfile(r.best_svg)]
    if not results:
        raise RuntimeError("no sketch was produced")
    method = schema.method_of(settings)
    if method != "clipasso" and all(r.clip_score is not None for r in results):
        best = max(results, key=lambda r: r.clip_score)
    else:
        best = min(results, key=lambda r: r.best_loss)
    best_copy = os.path.join(job_dir, f"{best.run_name}_best.svg")
    shutil.copyfile(best.best_svg, best_copy)
    png = os.path.join(best.run_dir, "best_iter.png")
    if os.path.isfile(png):
        shutil.copyfile(png, os.path.join(job_dir, f"{best.run_name}_best.png"))
    try:
        shutil.copyfile(target, os.path.join(job_dir, "source" + os.path.splitext(target)[1].lower()))
    except OSError:
        pass
    summary = {
        "target": os.path.abspath(target),
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "settings": schema.normalize(settings),
        "method": method,
        "clip_score": best.clip_score,
        "seconds": round(sum(r.seconds for r in results), 1),
        "best_svg": best_copy,
        "best_run": best.run_name,
        "runs": [r.__dict__ for r in results],
    }
    with open(os.path.join(job_dir, "job.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    reporter.event("job_done", job_dir=job_dir, best_svg=best_copy, best_run=best.run_name, method=method,
                   clip_score=best.clip_score, runs=[r.__dict__ for r in results])
    return summary
