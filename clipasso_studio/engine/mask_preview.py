"""Object mask preview for the studio.

The GUI runs :func:`worker_main` in a separate process, so BiRefNet's memory (up to ~4 GB on a CPU)
never stays in the app. The result lands in the mask cache of :mod:`.masking`, where the GUI reads
it and where the next run of the same image finds it.
"""

from __future__ import annotations


def compute(target: str, model: str, device: str = "auto") -> dict:
    import torch

    from . import masking
    from .imaging import load_rgb

    im = load_rgb(target)
    use_cuda = device in ("auto", "cuda") and torch.cuda.is_available()
    dev = torch.device("cuda" if use_cuda else "cpu")
    try:
        masking.preview_probability(dev, im, model)
    except RuntimeError:  # e.g. CUDA out of memory while a job uses the GPU
        if dev.type != "cuda":
            raise
        masking.preview_probability(torch.device("cpu"), im, model)
    return {"path": str(masking.cache_path(im, model)), "key": masking.image_key(im)}


def worker_main(target: str, model: str, device: str, queue) -> None:
    try:
        queue.put(("done", compute(target, model, device)))
    except Exception as exc:  # reported to the GUI
        queue.put(("error", f"{type(exc).__name__}: {exc}"))
