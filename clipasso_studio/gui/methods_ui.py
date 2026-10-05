"""Sketching methods as the GUI presents them: names, icons, model status, hardware."""

from __future__ import annotations

import math

from .. import settings_schema as schema
from ..engine import model_store
from ..engine.methods.requirements import controlsketch_uses_sdxl

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
# ControlSketch's SDXL attention on the CPU, once per job: 100 network steps at 1024 px of about 45 s each
# (measured on 4 cores, it uses all of them: about that much faster with more); on a graphics card it is part
# of the setup
SDXL_CPU_SECONDS = 4500
SDXL_MEASURED_CORES = 4
# piece by piece through a small graphics card: not measured yet (about 9 s a step assumed: the weights cross the
# PCIe bus every step); the app measures it on the first run (``sec_per_it`` "sdxl:offload")
SDXL_OFFLOAD_SECONDS = 900
SDXL_STEPS = 100  # network steps of the SDXL attention (inversion + generation)
SDXL_SMALL_GPU = "sdxl_small_gpu"  # app setting: what to do when SDXL is chosen for a small graphics card

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
    from .hardware import spread_gpus

    gpus = len(spread_gpus()) if gpu else 0
    workers = runner.plan_workers(s, sketches, auto=app_settings().get("parallel_sketches", "auto") == "auto",
                                  cuda=gpu, gpus=gpus)
    if workers > 1 and runner.spreads_over_gpus(s, sketches, gpu, gpus):  # one graphics card each: x workers
        sketches = math.ceil(sketches / workers)
    elif workers > 1:  # in parallel (each worker has fewer cores: not quite workers x faster)
        sketches = math.ceil(sketches / workers) * 1.6
    secs = per_it * iterations(s) * sketches + SETUP_SECONDS[method] * s["num_sketches"]
    if schema.turbo_prunes(s) and method == "clipasso":  # one after another, the weaker ones stop early
        secs = per_it * total_iterations(s) + SETUP_SECONDS[method] * s["num_sketches"]
    if method == "scenesketch":
        secs = per_it * total_iterations(s) + SETUP_SECONDS[method] * len(schema.scene_cells(s))
    if method == "controlsketch" and controlsketch_uses_sdxl(s):
        if not gpu:
            secs += sdxl_seconds(s, "cpu")
        elif small_card_for_sdxl(s):
            secs += sdxl_seconds(s, s.get("sdxl_place", "offload"))
    return float(secs)


BUDGET_MINUTES = (5, 15, 60)  # the time budgets of the studio's input card (and "other …")


def _budget_grid(method: str, s: dict):
    """Variants of the settings a time budget may choose from (the knobs that cost time)."""
    sketches = int(s.get("num_sketches", 1))
    if method == "swiftsketch":
        for refine in (True, False):
            for n in range(max(sketches, 8), 0, -1):  # (more to choose the best from – but not a wall of them)
                yield {"num_sketches": n, "use_refine": refine}
    elif method == "clipasso":
        for turbo in (False, True):
            for n in sorted({sketches, 3, 2, 1}, reverse=True):
                for it in (2001, 1500, 1000, 700, 500, 300, 150):
                    for aug in (4, 2, 0):
                        yield {"turbo": turbo, "num_sketches": n, "num_iter": it, "num_aug_clip": aug}
    elif method == "controlsketch":
        for turbo in (False, True):
            for n in sorted({sketches, 2, 1}, reverse=True):
                for it in (2000, 1500, 1000, 600, 300, 150):
                    yield {"turbo": turbo, "num_sketches": n, "num_iter": it}
    else:  # SceneSketch: the matrix the user chose stays as long as it can
        levels = int(s.get("simplicity_levels", 8))
        for lv in sorted({levels, min(levels, 4), min(levels, 2), 0}, reverse=True):
            for turbo in (False, True):
                for n in sorted({sketches, 1}, reverse=True):
                    for it in (1501, 1000, 600, 300):
                        yield {"turbo": turbo, "num_sketches": n, "num_iter": it, "simplicity_levels": lv}


def _budget_quality(method: str, v: dict, s: dict) -> float:
    """How good a variant is expected to be (larger: better) – iterations count most, then more sketches to
    choose the best from; turbo costs a little, fewer abstraction levels change what SceneSketch makes."""
    q = 0.0
    if "num_iter" in v:
        q += 3.0 * math.log(max(int(v["num_iter"]), 1))
    q += 1.0 * math.log(1 + int(v.get("num_sketches", 1)))
    q += 0.5 * math.log(1 + int(v.get("num_aug_clip", 0)))
    q += 0.6 if v.get("use_refine") else 0.0
    q -= 0.3 if v.get("turbo") else 0.0
    if "simplicity_levels" in v:
        q += 10.0 * int(v["simplicity_levels"]) / max(int(s.get("simplicity_levels", 8)), 1)
    return q


def fit_to_budget(settings: dict, seconds: float, gpu: bool | None = None) -> tuple[dict, float]:
    """The changes to ``settings`` that give the best expected sketch within ``seconds`` (measured speed of this
    computer, see :func:`estimate_seconds`) and the expected time. Nothing fits: the quickest variant."""
    s = schema.normalize(settings)
    method = schema.method_of(s)
    best, best_q, quickest, quickest_secs = None, None, None, None
    for variant in _budget_grid(method, s):
        trial = {**s, **variant}
        secs = estimate_seconds(trial, gpu)
        if quickest_secs is None or secs < quickest_secs:
            quickest, quickest_secs = variant, secs
        if secs <= seconds:
            q = _budget_quality(method, variant, s)
            if best_q is None or q > best_q + 1e-9:
                best, best_q = (variant, secs), q
    variant, secs = best if best is not None else (quickest, quickest_secs)
    changes = {k: v for k, v in (variant or {}).items() if s.get(k) != v}
    return changes, float(secs or 0.0)


def sdxl_seconds(settings: dict, mode: str) -> float:
    """Expected time of the SDXL step piece by piece through a small graphics card ("offload") or on the CPU:
    measured on this computer (``sec_per_it`` "sdxl:<mode>", seconds per network step), else the measurement
    on 4 cores scaled by the cores it uses (CPU) or an assumption (offload)."""
    from ..engine import runner
    from .app_settings import app_settings

    rate = (app_settings().get("sec_per_it", {}) or {}).get(f"sdxl:{mode}")
    if rate:
        return float(rate) * SDXL_STEPS
    if mode == "offload":
        return float(SDXL_OFFLOAD_SECONDS)
    cores = int(settings.get("num_threads") or 0) or runner.hardware_info()[0]
    return SDXL_CPU_SECONDS * SDXL_MEASURED_CORES / max(cores, 1)


def sdxl_minutes(settings: dict, mode: str) -> int:
    """The same in minutes, rounded to 5."""
    return max(5, int(round(sdxl_seconds(settings, mode) / 300)) * 5)


def small_card_for_sdxl(settings: dict) -> dict | None:
    """The graphics card of a job with these settings when SDXL does not fit on it (the SDXL step then runs on
    the CPU, the rest of ControlSketch on the card); else None."""
    from ..engine.methods.requirements import sdxl_on_cpu
    from .hardware import job_gpu

    card = job_gpu(settings)
    return card if card and sdxl_on_cpu(float(card.get("memory_gb") or 0)) else None
