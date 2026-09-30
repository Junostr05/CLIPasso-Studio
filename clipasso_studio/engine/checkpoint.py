"""Checkpoints of a running optimisation, so an interrupted job can continue where it stopped.

A checkpoint is written to ``<run>/checkpoint.pt`` every :data:`INTERVAL_S` seconds and when a run
is cancelled; it holds everything the training loop needs to go on (stroke parameters, optimiser
states, counters, loss history and the random number generators), so a continued run takes the
same steps as an uninterrupted one. It is removed when the run has finished.
"""

from __future__ import annotations

import os
import random
import time

import numpy as np
import torch

FILENAME = "checkpoint.pt"
INTERVAL_S = 30.0


def path(run_dir: str) -> str:
    return os.path.join(run_dir, FILENAME)


def rng_state() -> dict:
    state = {"torch": torch.get_rng_state(), "numpy": np.random.get_state(), "random": random.getstate()}
    if torch.cuda.is_available():
        state["cuda"] = torch.cuda.get_rng_state_all()
    return state


def set_rng_state(state: dict) -> None:
    torch.set_rng_state(state["torch"])
    np.random.set_state(state["numpy"])
    random.setstate(state["random"])
    if state.get("cuda") is not None and torch.cuda.is_available():
        try:
            torch.cuda.set_rng_state_all(state["cuda"])
        except RuntimeError:  # another number of GPUs than when the checkpoint was written
            pass


def save(run_dir: str, data: dict) -> None:
    """Write atomically: a crash while writing leaves the previous checkpoint intact."""
    target = path(run_dir)
    tmp = target + ".tmp"
    torch.save({**data, "rng": rng_state(), "saved": time.time()}, tmp)
    os.replace(tmp, target)


def load(run_dir: str) -> dict | None:
    """The checkpoint of ``run_dir`` or None (none, or unreadable – then the run starts over)."""
    target = path(run_dir)
    if not os.path.isfile(target):
        return None
    try:
        return torch.load(target, map_location="cpu", weights_only=False)  # our own file (numpy RNG state)
    except Exception:
        return None


def remove(run_dir: str) -> None:
    for name in (path(run_dir), path(run_dir) + ".tmp"):
        try:
            os.remove(name)
        except OSError:
            pass


class Timer:
    """When the next checkpoint is due."""

    def __init__(self, interval: float = INTERVAL_S):
        self.interval = interval
        self.last = time.time()

    def due(self) -> bool:
        if time.time() - self.last >= self.interval:
            self.last = time.time()
            return True
        return False


def to_device(obj, device):
    """Move the tensors of an optimiser state dict (loaded on the CPU) to ``device``."""
    if torch.is_tensor(obj):
        return obj.to(device)
    if isinstance(obj, dict):
        return {k: to_device(v, device) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_device(v, device) for v in obj]
    return obj
