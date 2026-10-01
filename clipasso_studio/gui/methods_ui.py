"""Sketching methods as the GUI presents them: names, icons, model status, hardware."""

from __future__ import annotations

import math

from .. import settings_schema as schema
from ..engine import model_store

NAMES = {"clipasso": "CLIPasso", "swiftsketch": "SwiftSketch", "controlsketch": "ControlSketch",
         "scenesketch": "SceneSketch"}
ICONS = {"clipasso": "pencil-line", "swiftsketch": "zap", "controlsketch": "wand-sparkles", "scenesketch": "mountain"}
# typical seconds per iteration / denoising step (used until the app has measured its own speed)
DEFAULT_SEC_PER_IT = {
    ("clipasso", "cpu"): 1.0, ("clipasso", "cuda"): 0.08,
    ("swiftsketch", "cpu"): 0.08, ("swiftsketch", "cuda"): 0.02,
    ("controlsketch", "cpu"): 16.0, ("controlsketch", "cuda"): 0.2,
    ("scenesketch", "cpu"): 1.1, ("scenesketch", "cuda"): 0.1,
}
# time per iteration in turbo mode relative to the normal mode, until a turbo run was measured (CPU: measured
# on 4 cores, CLIPasso 1.02 -> 0.70 s, ControlSketch 15.1 -> 2.3 s; GPU: estimated)
TURBO_SPEED = {
    ("clipasso", "cpu"): 0.7, ("clipasso", "cuda"): 0.75,
    ("controlsketch", "cpu"): 0.2, ("controlsketch", "cuda"): 0.5,
    ("scenesketch", "cpu"): 0.75, ("scenesketch", "cuda"): 0.8,
}
# seconds for loading models / preparing the input, per sketch
SETUP_SECONDS = {"clipasso": 15, "swiftsketch": 10, "controlsketch": 60, "scenesketch": 5}

_cuda: bool | None = None


def name(method: str) -> str:
    return NAMES.get(method, method)


def required_models(settings: dict) -> list[str]:
    from ..engine import methods

    return methods.required_models(settings)


def missing_models(settings: dict) -> list[str]:
    return [k for k in required_models(settings) if not model_store.is_available(k)]


def download_mb(keys) -> float:
    return sum(model_store.SPECS[k].download_size for k in keys) / 1e6


def has_cuda() -> bool:
    """A usable NVIDIA GPU, as the last hardware probe found it (gui/hardware.py; False until then)."""
    if _cuda is not None:  # set by tests
        return _cuda
    from . import hardware

    return hardware.has_cuda()


def iterations(settings: dict) -> int:
    """Iterations (denoising steps) of one sketch (SceneSketch: of the first matrix cell)."""
    method = schema.method_of(settings)
    if method == "scenesketch":
        cells = schema.scene_cells(settings)
        return schema.scene_cell_iterations(settings, cells[0]) if cells else 1
    if method == "swiftsketch":
        return 50 + (1 if settings.get("use_refine", True) else 0)
    if method == "controlsketch":
        return int(settings.get("num_iter", 2000)) + 1
    return int(settings.get("num_iter", 2001))


def total_iterations(settings: dict) -> int:
    """Iterations of a whole job (all sketches / all matrix cells; in turbo mode the weaker sketches
    stop after a quarter)."""
    if schema.method_of(settings) == "scenesketch":
        return sum(schema.scene_cell_iterations(settings, c) for c in schema.scene_cells(settings))
    n = int(settings.get("num_sketches", 1))
    if schema.turbo_prunes(settings):
        return iterations(settings) + (n - 1) * schema.turbo_prune_iter(iterations(settings))
    return iterations(settings) * n


def uses_loss(method: str) -> bool:
    """CLIPasso optimises a CLIP loss it reports; the other methods are judged by the CLIP score."""
    return method == "clipasso"


def estimate_seconds(settings: dict, gpu: bool | None = None) -> float:
    """Expected run time of a job with these settings: measured seconds per iteration of earlier runs
    (``sec_per_it``) or defaults, parallel sketches and turbo mode taken into account."""
    from ..engine import runner
    from .app_settings import app_settings

    s = schema.normalize(settings)
    method = schema.method_of(s)
    if gpu is None:
        gpu = s["device"] == "cuda" or (s["device"] == "auto" and has_cuda())
    rates = app_settings().get("sec_per_it", {}) or {}
    dev = "cuda" if gpu else "cpu"
    legacy = rates.get(dev) if method == "clipasso" else None  # measured by version 1.x
    per_it = rates.get(f"{method}:{dev}", legacy or DEFAULT_SEC_PER_IT[(method, dev)])
    if schema.turbo(s):
        per_it = rates.get(f"{method}:{dev}:turbo", per_it * TURBO_SPEED[(method, dev)])
    if method == "clipasso":
        per_it *= (1 + s["num_aug_clip"]) / 5
        if s["clip_model_name"] in ("RN50x4", "RN50x16", "ViT-B/16"):
            per_it *= 2
    sketches = s["num_sketches"]
    workers = runner.plan_workers(s, sketches, auto=app_settings().get("parallel_sketches", "auto") == "auto",
                                  cuda=gpu)
    if workers > 1:  # in parallel (each worker has fewer cores: not quite workers x faster)
        sketches = math.ceil(sketches / workers) * 1.6
    secs = per_it * iterations(s) * sketches + SETUP_SECONDS[method] * s["num_sketches"]
    if schema.turbo_prunes(s) and method == "clipasso":  # one after another, the weaker ones stop early
        secs = per_it * total_iterations(s) + SETUP_SECONDS[method] * s["num_sketches"]
    if method == "scenesketch":
        secs = per_it * total_iterations(s) + SETUP_SECONDS[method] * len(schema.scene_cells(s))
    return float(secs)
