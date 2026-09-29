"""Registry of the sketching methods.

Every method module provides::

    run_single(settings, target, run_dir, seed, reporter, control, device) -> SeedResult
    required_models(settings) -> list[str]        # model_store keys needed for these settings

All methods report the same events (``stage``, ``input``, ``attention``, ``iteration``,
``preview``, ``seed_done``), so the runner, the queue, the GUI and the exports work for all of them.
"""

from __future__ import annotations

import importlib

from ... import settings_schema as schema

_MODULES = {
    "clipasso": "clipasso_studio.engine.methods.clipasso",
    "swiftsketch": "clipasso_studio.engine.methods.swiftsketch",
    "controlsketch": "clipasso_studio.engine.methods.controlsketch",
}


def get(method: str):
    if method not in _MODULES:
        raise ValueError(f"unknown method {method!r} (expected one of {schema.METHODS})")
    return importlib.import_module(_MODULES[method])


def required_models(settings: dict) -> list[str]:
    return get(schema.method_of(settings)).required_models(settings)
