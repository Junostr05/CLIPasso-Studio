"""Small previews of image files: decoded at the small size (JPEG decodes 8x smaller directly) and kept,
so lists with hundreds of images (queue, compare page) do not decode every full photo again."""

from __future__ import annotations

import os
from collections import OrderedDict

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImageReader, QPixmap

_cache: OrderedDict = OrderedDict()
KEEP = 512


def thumbnail(path: str, size: int) -> QPixmap:
    """The image at ``path`` fitted into ``size`` x ``size`` (an empty pixmap if it cannot be read)."""
    try:
        st = os.stat(path)
    except OSError:
        return QPixmap()
    key = (os.path.normcase(os.path.abspath(path)), st.st_mtime_ns, st.st_size, size)
    pm = _cache.get(key)
    if pm is not None:
        _cache.move_to_end(key)
        return pm
    reader = QImageReader(path)
    reader.setAutoTransform(True)  # EXIF orientation
    full = reader.size()
    if full.isValid() and full.width() > 0 and full.height() > 0:
        scaled = full.scaled(QSize(size * 2, size * 2), Qt.KeepAspectRatio)  # 2x for high-DPI screens
        if scaled.width() < full.width():
            reader.setScaledSize(scaled)
    img = reader.read()
    if img.isNull():
        return QPixmap()
    pm = QPixmap.fromImage(img).scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    _cache[key] = pm
    while len(_cache) > KEEP:
        _cache.popitem(last=False)
    return pm
