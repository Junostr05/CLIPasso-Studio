"""Registry of the sketching methods.

Every method module provides::

    run_single(settings, target, run_dir, seed, reporter, control, device) -> SeedResult
    required_models(settings) -> list[str]        # model_store keys needed for these settings

SceneSketch, whose items (the cells of its abstraction matrix) build on each other, provides
``run_cells(settings, target, job_dir, cells, reporter, control, device) -> list[SeedResult]``
instead of ``run_single``.

All methods report the same events (``stage``, ``input``, ``attention``, ``iteration``,
``preview``, ``seed_done``), so the runner, the queue, the GUI and the exports work for all of them.
"""

from __future__ import annotations

from ... import settings_schema as schema


def get(method: str):
    # plain imports (not importlib) so that PyInstaller always bundles the method modules
    if method == "clipasso":
        from . import clipasso as module
    elif method == "swiftsketch":
        from . import swiftsketch as module
    elif method == "controlsketch":
        from . import controlsketch as module
    elif method == "scenesketch":
        from . import scenesketch as module
    else:
        raise ValueError(f"unknown method {method!r} (expected one of {schema.METHODS})")
    return module


def required_models(settings: dict) -> list[str]:
    from .requirements import BY_METHOD  # without importing the method (and PyTorch)

    return BY_METHOD[schema.method_of(settings)](settings)
