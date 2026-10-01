"""CLIPasso (Vinker et al., SIGGRAPH 2022) – the optimisation in :mod:`..pipeline`."""

from __future__ import annotations

from .requirements import clipasso as required_models  # noqa: F401 (used by the dispatcher too)


def run_single(settings, target, run_dir, seed, reporter=None, control=None, device=None, **turbo):
    """``turbo``: ``stop_at`` / ``finalize`` / ``plan_left`` of :func:`..pipeline.run_single`."""
    from .. import pipeline

    return pipeline.run_single(settings, target, run_dir, seed, reporter, control, device, **turbo)


