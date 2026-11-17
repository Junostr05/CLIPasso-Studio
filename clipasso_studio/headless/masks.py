"""The object mask of an image for the Mac app (gui/mask_view.py and mask_edit.py of the studio, without Qt).

What is known of a mask at once – the model's probability from the mask cache (a 16-bit PNG) and the user's edited
mask (an 8-bit PNG kept per image content) – and the model's mask computed in a process of its own
(``engine.mask_preview``), so BiRefNet's memory never stays in the engine; "mask_ready" or "mask_failed" tells the
app when it is done. The app paints, the engine keeps: an edited mask is stored where every method finds it
(``masking.save_edited_mask``, by the image's content).
"""

from __future__ import annotations

import multiprocessing as mp
import queue as queue_mod
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PIL import Image

from ..engine import masking
from ..engine.imaging import load_rgb


def status(image: str, model: str) -> dict:
    """The mask of ``image`` as far as it is known: the model's probability (None: not computed yet) and the
    user's edited mask (None: none), the image's size (the masks are of that size, the picture turned upright)."""
    im = load_rgb(image)
    digest = masking.image_digest(im)
    cached, edited = masking.cache_path(im, model, digest), masking.edited_mask_path(im, digest)
    return {"probability": str(cached) if cached.is_file() else None,
            "edited": str(edited) if edited.is_file() else None, "width": im.width, "height": im.height}


def save(image: str, mask: str) -> str:
    """The user's mask (a picture of the image's size, white the object) kept for this image content."""
    im = load_rgb(image)
    with Image.open(mask) as m:
        if m.size != im.size:
            raise ValueError(f"the mask is {m.size[0]}×{m.size[1]}, the image {im.width}×{im.height}")
        values = (np.asarray(m.convert("L")) >= 128).astype(np.float32)
    return str(masking.save_edited_mask(im, values))


def remove(image: str) -> None:
    masking.remove_edited_mask(load_rgb(image))


def _worker(image: str, model: str, device: str, results) -> None:
    from ..engine import mask_preview

    mask_preview.worker_main(image, model, device, results)


class Previews:
    """One mask computed at a time; asked for another while one runs, the newest waits (and replaces one waiting).
    ``send(kind, data)`` passes the events on; ``start`` (tests) begins the work and gives its result queue."""

    def __init__(self, send: Callable[[str, dict], None], start: Callable | None = None):
        self._send = send
        self._start_work = start or self._process
        self._running: tuple | None = None  # (image, model, results, process or None)
        self._waiting: tuple[str, str, str] | None = None

    @staticmethod
    def _process(image: str, model: str, device: str):
        ctx = mp.get_context("spawn")
        results = ctx.Queue()
        proc = ctx.Process(target=_worker, args=(image, model, device, results), daemon=True)
        proc.start()
        return results, proc

    def request(self, image: str, model: str, device: str = "auto") -> None:
        if self._running is not None:
            if self._running[:2] != (image, model):
                self._waiting = (image, model, device)
            return
        results, proc = self._start_work(image, model, device)
        self._running = (image, model, results, proc)

    @property
    def busy(self) -> bool:
        return self._running is not None

    def poll(self) -> int:
        """Pass a finished mask on (and start the one waiting); returns how many events went."""
        if self._running is None:
            return 0
        image, model, results, proc = self._running
        try:
            kind, data = results.get_nowait()
        except queue_mod.Empty:
            if proc is None or proc.is_alive():
                return 0
            kind, data = "error", "the mask process ended unexpectedly"
        if proc is not None:
            proc.join(timeout=2)
        self._running = None
        if kind == "done":
            self._send("mask_ready", {"image": image, "model": model, "probability": str(Path(data["path"]))})
        else:
            self._send("mask_failed", {"image": image, "model": model, "message": str(data)})
        if self._waiting is not None:
            waiting, self._waiting = self._waiting, None
            self.request(*waiting)
        return 1

    def shutdown(self) -> None:
        if self._running is not None and self._running[3] is not None and self._running[3].is_alive():
            self._running[3].terminate()
        self._running = self._waiting = None
