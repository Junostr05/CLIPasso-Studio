"""Small previews of image files: decoded at the small size (JPEG decodes 8x smaller directly) and kept,
so lists with hundreds of images (queue, compare page) do not decode every full photo again."""

from __future__ import annotations

import os
from collections import OrderedDict

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

_cache: OrderedDict = OrderedDict()
KEEP = 512


_sketches: OrderedDict = OrderedDict()


def sketch_thumbnail(svg_path: str, size: int, style: str = "plain") -> QPixmap:
    """A sketch file rendered at ``size`` px on white (2x for high-DPI screens) – kept in memory and on
    disk (``cache/thumbs`` in the app data), so a gallery of hundreds of results opens quickly."""
    import hashlib

    from PySide6.QtGui import QColor

    try:
        st = os.stat(svg_path)
    except OSError:
        return QPixmap()
    key = (os.path.normcase(os.path.abspath(svg_path)), st.st_mtime_ns, st.st_size, size, style)
    pm = _sketches.get(key)
    if pm is not None:
        _sketches.move_to_end(key)
        return pm
    from .. import paths

    folder = paths.user_data_dir() / "cache" / "thumbs"
    disk = folder / (hashlib.sha1(repr(key).encode("utf-8")).hexdigest() + ".png")
    pm = QPixmap(str(disk)) if disk.is_file() else QPixmap()
    if pm.isNull():
        from .widgets.canvas import render_svg_image, styled

        try:
            with open(svg_path, encoding="utf-8") as f:
                svg = styled(f.read(), style)
        except OSError:
            return QPixmap()
        img = render_svg_image(svg, size * 2, QColor("white"))
        try:
            folder.mkdir(parents=True, exist_ok=True)
            img.save(str(disk), "PNG")
        except OSError:
            pass
        pm = QPixmap.fromImage(img)
    _sketches[key] = pm
    while len(_sketches) > KEEP:
        _sketches.popitem(last=False)
    return pm


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
    from .image_io import read_image

    img = read_image(path, size * 2)  # 2x for high-DPI screens; HEIC / AVIF through Pillow
    if img.isNull():
        return QPixmap()
    pm = QPixmap.fromImage(img).scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    _cache[key] = pm
    while len(_cache) > KEEP:
        _cache.popitem(last=False)
    return pm
