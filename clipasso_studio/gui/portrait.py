"""Portrait mode in the detail brush: find the face (BlazeFace, a 0.4 MB download the first time) and mark its eyes,
nose and mouth "more" – in a thread, so the dialog stays responsive while PyTorch loads."""

from __future__ import annotations

import numpy as np
from PIL import Image
from PySide6.QtCore import QEventLoop, Qt
from PySide6.QtWidgets import QApplication

from ..engine import model_store
from .i18n import tr

KEY = "blazeface"
_net = None


def available() -> bool:
    return model_store.is_available(KEY)


def detect(photo: Image.Image, progress=None) -> np.ndarray | None:
    """The detail map (uint8 at the photo size) for the faces in ``photo`` – None when there is no trustworthy
    face. Loads PyTorch and the detector (in the calling thread)."""
    global _net
    from ..engine import portrait

    if _net is None:
        _net = portrait.load(str(model_store.find(KEY)))
    faces = [f for f in portrait.find_faces(photo, _net) if portrait.plausible(f)]
    return portrait.detail_map(photo.size, faces) if faces else None


def detail_for(photo: Image.Image, parent=None) -> np.ndarray | None:
    """Download the detector if needed (asks), then find the face while the dialog waits (events keep flowing)."""
    from . import dialogs

    if not available() and (not dialogs.ask_download_missing(parent, [KEY]) or not available()):
        return None
    result: dict = {}
    loop = QEventLoop()

    def done(values):
        result["values"] = values
        loop.quit()

    def failed(msg):
        result["error"] = msg
        loop.quit()

    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        dialogs.run_in_thread(parent, detect, photo, on_done=done, on_error=failed)
        loop.exec()
    finally:
        QApplication.restoreOverrideCursor()
    if "error" in result:
        dialogs.info_box(parent, tr("ui.detail.title"), result["error"])
        return None
    return result.get("values")
