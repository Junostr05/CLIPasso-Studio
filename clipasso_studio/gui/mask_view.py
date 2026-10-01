"""The object mask in the studio: the preview process and the overlay drawn over the input image.

The mask is computed in a separate process (``engine/mask_preview.py``), so BiRefNet's memory never
stays in the app; the result goes into the mask cache, where the GUI reads it and the next run of
the same image finds it. A running preview is not interrupted when another image is chosen (it
holds the cache lock of its image) – the newest request waits and starts after it.
"""

from __future__ import annotations

import multiprocessing as mp
import queue as queue_mod

import numpy as np
from PIL import Image
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QColor, QImage

from ..engine import masking
from ..engine.imaging import load_rgb


def load_mask(path: str, model: str) -> tuple[Image.Image, np.ndarray | None, np.ndarray | None]:
    """(image, the model's probability from the cache or None, the user's edited mask or None)."""
    im = load_rgb(path)
    digest = masking.image_digest(im)
    return im, masking.cached_probability(im, model, digest), masking.edited_mask(im, digest)


def _erode(m: np.ndarray) -> np.ndarray:
    out = m.copy()
    out[1:] &= m[:-1]
    out[:-1] &= m[1:]
    out[:, 1:] &= m[:, :-1]
    out[:, :-1] &= m[:, 1:]
    return out


def _dilate(m: np.ndarray, r: int) -> np.ndarray:
    out = m.copy()
    for _ in range(r):
        o = out.copy()
        o[1:] |= out[:-1]
        o[:-1] |= out[1:]
        o[:, 1:] |= out[:, :-1]
        o[:, :-1] |= out[:, 1:]
        out = o
    return out


def overlay(mask: np.ndarray, veil: QColor, edge: QColor, max_side: int = 900) -> QImage:
    """ARGB image (at most ``max_side``) to draw over the photo: the background (mask 0) under a
    veil, the object outlined."""
    m = np.asarray(mask) > 0.5
    h, w = m.shape
    scale = min(1.0, max_side / max(h, w, 1))
    if scale < 1.0:
        small = Image.fromarray(m.astype(np.uint8) * 255).resize((max(1, round(w * scale)), max(1, round(h * scale))),
                                                                  Image.BILINEAR)
        m = np.asarray(small) >= 128
        h, w = m.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[~m] = (veil.red(), veil.green(), veil.blue(), veil.alpha())
    outline = _dilate(m & ~_erode(m), max(1, round(max(h, w) / 320)))
    rgba[outline] = (edge.red(), edge.green(), edge.blue(), 255)
    return QImage(rgba.data, w, h, 4 * w, QImage.Format_RGBA8888).copy()


class MaskPreviewer(QObject):
    """Computes the mask preview of an image in a separate process (one at a time)."""

    busy = Signal(bool)
    ready = Signal(str, str)  # image path, mask model
    failed = Signal(str, str, str)  # image path, mask model, message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ctx = mp.get_context("spawn")
        self._proc = None
        self._queue = None
        self._job: tuple[str, str, str] | None = None
        self._pending: tuple[str, str, str] | None = None
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(500)
        self._debounce.timeout.connect(self._start)
        self._poll = QTimer(self)
        self._poll.setInterval(200)
        self._poll.timeout.connect(self._check)

    def is_busy(self) -> bool:
        return self._proc is not None

    def request(self, path: str, model: str, device: str = "auto", delay: bool = True):
        self._pending = (path, model, device)
        if delay:
            self._debounce.start()
        else:
            self._start()

    def forget(self):
        """Nothing is wanted any more (the running preview still ends and fills the cache)."""
        self._pending = None
        self._debounce.stop()

    def _start(self):
        job, self._pending = self._pending, None
        if job is None:
            return
        if self._proc is not None:
            if self._job[:2] != job[:2]:
                self._pending = job  # after the running one
            return
        path, model, device = job
        try:
            _, prob, _ = load_mask(path, model)
        except OSError as exc:
            self.failed.emit(path, model, str(exc))
            return
        if prob is not None:
            self.ready.emit(path, model)
            return
        self._job = job
        self._queue = self._ctx.Queue()
        from ..engine import mask_preview

        self._proc = self._ctx.Process(target=mask_preview.worker_main, args=(path, model, device, self._queue),
                                       daemon=True)
        self._proc.start()
        self.busy.emit(True)
        self._poll.start()

    def _check(self):
        try:
            kind, data = self._queue.get_nowait()
        except queue_mod.Empty:
            if self._proc is not None and not self._proc.is_alive():
                job = self._end()
                self.failed.emit(job[0], job[1], "the preview process ended unexpectedly")
            return
        job = self._end()
        if kind == "done":
            self.ready.emit(job[0], job[1])
        else:
            self.failed.emit(job[0], job[1], str(data))

    def _end(self) -> tuple[str, str, str]:
        job = self._job
        self._poll.stop()
        if self._proc is not None:
            self._proc.join(timeout=2)
        self._proc = self._queue = self._job = None
        self.busy.emit(False)
        if self._pending is not None:
            QTimer.singleShot(0, self._start)
        return job

    def shutdown(self):
        """App exit: stop a running preview (and remove the cache lock it held)."""
        self._pending = None
        self._debounce.stop()
        self._poll.stop()
        if self._proc is None:
            return
        job = self._job
        self._proc.terminate()
        self._proc.join(timeout=3)
        self._proc = self._queue = self._job = None
        try:
            im = load_rgb(job[0])
            if job[1] != "u2net":
                masking.cache_path(im, job[1]).with_suffix(".lock").unlink(missing_ok=True)
        except OSError:
            pass
