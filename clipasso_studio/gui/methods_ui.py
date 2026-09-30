"""Sketching methods as the GUI presents them: names, icons, model status, hardware."""

from __future__ import annotations

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
    global _cuda
    if _cuda is None:
        try:
            import torch

            _cuda = bool(torch.cuda.is_available() and torch.cuda.device_count() > 0)
        except Exception:
            _cuda = False
    return _cuda


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
    """Iterations of a whole job (all sketches / all matrix cells)."""
    if schema.method_of(settings) == "scenesketch":
        return sum(schema.scene_cell_iterations(settings, c) for c in schema.scene_cells(settings))
    return iterations(settings) * int(settings.get("num_sketches", 1))


def uses_loss(method: str) -> bool:
    """CLIPasso optimises a CLIP loss it reports; the other methods are judged by the CLIP score."""
    return method == "clipasso"
