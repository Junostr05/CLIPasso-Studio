"""The detail brush of an image for the Mac app (gui/detail_edit.py and portrait.py of the studio, without Qt).

The app paints the map at the size the studio paints it (the image at most ``EDIT_SIDE`` pixels, as
``Image.thumbnail`` makes it); the engine gives the stored map at that size and keeps a painted one at the image's
size (``details.save_detail_map``, by the image's content – an all-normal map removes it). Portrait mode finds the
faces with BlazeFace in a process of its own, so PyTorch never stays in the engine; "portrait_ready" brings the map
of the faces (None: no face the studio would trust) or "portrait_failed" why not.
"""

from __future__ import annotations

import os
import tempfile

# (numpy, Pillow and the engine's modules are imported where they are used: the engine starts without them)

EDIT_SIDE = 1024  # detail_edit.EDIT_SIDE: the map is painted at most this large
FACE_MODEL = "blazeface"  # portrait.KEY


def _photo(image: str):
    """The image upright and the studio's photo of the dialog (thumbnail to EDIT_SIDE)."""
    from ..engine.imaging import load_rgb

    im = load_rgb(image)
    photo = im.copy()
    photo.thumbnail((EDIT_SIDE, EDIT_SIDE))
    return im, photo


def _temp_png(picture) -> str:
    fd, path = tempfile.mkstemp(prefix="clipasso-detail-", suffix=".png")
    os.close(fd)
    picture.save(path, format="PNG")
    return path


def status(image: str) -> dict:
    """The map as the studio's dialog starts from it: the stored map (if it says anything) as an 8-bit grey PNG at
    the painting size (a temporary file the app removes; None: none), that size, whether a map is stored at all, and
    the value of "normal"."""
    import numpy as np
    from PIL import Image

    from ..engine import details

    im, photo = _photo(image)
    start = details.detail_map(im)
    path = None
    if start is not None:
        arr = np.clip(np.round(details.NORMAL + start * 127), 0, 255).astype(np.uint8)
        path = _temp_png(Image.fromarray(arr, mode="L").resize(photo.size, Image.BILINEAR))
    return {"map": path, "width": photo.width, "height": photo.height, "has": details.detail_path(im).is_file(),
            "normal": details.NORMAL}


def phone_map(image: str, side: int) -> str:
    """The map as the phone paints on it (phone_api.file_details): the image's size scaled to at most ``side``
    pixels (each side rounded), all normal where no map is kept – a temporary 8-bit grey PNG."""
    import numpy as np
    from PIL import Image

    from ..engine import details
    from ..engine.imaging import load_rgb

    im = load_rgb(image)
    w, h = im.size
    scale = min(1.0, side / max(w, h))
    size = (max(1, round(w * scale)), max(1, round(h * scale)))
    values = details.detail_map(im)
    arr = np.full((h, w), details.NORMAL, np.uint8) if values is None else \
        np.clip(np.round(details.NORMAL + values * 127), 0, 255).astype(np.uint8)
    return _temp_png(Image.fromarray(arr, mode="L").resize(size, Image.BILINEAR))


def remove(image: str) -> None:
    from ..engine import details
    from ..engine.imaging import load_rgb

    details.remove_detail_map(load_rgb(image))


def save(image: str, painted: str) -> str | None:
    """The painted map (8-bit grey, any size – the painting size) kept at the image's size, as the dialog's *Apply*
    does; None when it was all normal (then it is removed)."""
    import numpy as np
    from PIL import Image

    from ..engine import details
    from ..engine.imaging import load_rgb

    im = load_rgb(image)
    with Image.open(painted) as m:
        full = np.asarray(m.convert("L").resize(im.size, Image.BILINEAR))
    path = details.save_detail_map(im, full)
    return None if path is None else str(path)


def faces(image: str) -> str | None:
    """Portrait mode (portrait.detect): the map of the faces in the studio's photo (a temporary PNG at the painting
    size), None when there is no face the studio would trust."""
    from PIL import Image

    from ..engine import model_store, portrait

    _, photo = _photo(image)
    net = portrait.load(str(model_store.require(FACE_MODEL)))
    found = [f for f in portrait.find_faces(photo, net) if portrait.plausible(f)]
    if not found:
        return None
    return _temp_png(Image.fromarray(portrait.detail_map(photo.size, found), mode="L"))


def face_worker(image: str, model: str, device: str, results) -> None:
    """The process of portrait mode (headless.masks.Previews): ("done", {"path": map or None}) or ("error", why)."""
    try:
        results.put(("done", {"path": faces(image)}))
    except Exception as exc:  # reported to the app
        results.put(("error", f"{type(exc).__name__}: {exc}"))
