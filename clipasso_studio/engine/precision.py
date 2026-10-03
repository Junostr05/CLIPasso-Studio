"""Half precision (float16) on the GPU for the big networks (Stable Diffusion, ControlNet, BLIP, BiRefNet) –
unless the app setting ``gpu_precision`` asks for ``"fp32"``, e.g. to compare speed and memory on an older
card (GTX 10xx: less memory with float16, but these cards do not compute faster with it)."""

from __future__ import annotations

import os

import torch

from .. import paths

SETTING = "gpu_precision"
ENV = "CLIPASSO_GPU_PRECISION"


def wanted() -> str:
    """ "auto" (float16 on the GPU) or "fp32"; read for every model load (the settings may change between
    jobs of the warm worker)."""
    value = os.environ.get(ENV) or (paths.read_settings_file() or {}).get(SETTING) or "auto"
    return "fp32" if value == "fp32" else "auto"


def half_precision(device) -> bool:
    return torch.device(device).type == "cuda" and wanted() != "fp32"


def gpu_dtype(device) -> torch.dtype:
    return torch.float16 if half_precision(device) else torch.float32
