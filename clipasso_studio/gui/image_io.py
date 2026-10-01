"""Reading photos for the GUI: Qt's own readers, and Pillow for the formats Qt cannot read (HEIC / HEIF from
phones, AVIF). EXIF rotation is applied like the engine does (``imaging.load_rgb``)."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QImageIOHandler, QImageReader

_registered = False


def register_formats() -> None:
    """Teach Pillow HEIC / HEIF (pi-heif) – once; without the package those files cannot be opened."""
    global _registered
    if _registered:
        return
    _registered = True
    try:
        import pi_heif

        pi_heif.register_heif_opener()
    except Exception:
        pass


def _pillow(path: str):
    from PIL import Image, ImageOps

    register_formats()
    im = Image.open(path)
    return ImageOps.exif_transpose(im)


def image_size(path: str) -> QSize:
    """Pixel size of a photo as it is shown (rotated by its EXIF orientation), read from its header."""
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and reader.canRead():
        if reader.transformation() & QImageIOHandler.Transformation.TransformationRotate90:
            return QSize(size.height(), size.width())
        return size
    try:
        with _pillow(path) as im:
            return QSize(*im.size)
    except Exception:
        return QSize()


def read_image(path: str, max_side: int | None = None) -> QImage:
    """A photo as a QImage (at most ``max_side`` px; big JPEGs are decoded smaller directly)."""
    reader = QImageReader(path)
    reader.setAutoTransform(True)  # EXIF orientation
    if reader.canRead():
        full = reader.size()
        if max_side and full.isValid() and max(full.width(), full.height()) > max_side:
            reader.setScaledSize(full.scaled(QSize(max_side, max_side), Qt.KeepAspectRatio))
        img = reader.read()
        if not img.isNull():
            return img
    try:
        im = _pillow(path)
        if max_side:
            im.thumbnail((max_side, max_side))
        im = im.convert("RGBA")
        data = im.tobytes("raw", "RGBA")
        return QImage(data, im.width, im.height, im.width * 4, QImage.Format_RGBA8888).copy()
    except Exception:
        return QImage()
