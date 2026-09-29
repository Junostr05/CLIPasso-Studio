"""Lucide icons (ISC licence), tinted to the current theme."""

from __future__ import annotations

import hashlib
import tempfile
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .. import paths

_TMP = Path(tempfile.gettempdir()) / "clipasso_studio_icons"


@lru_cache(maxsize=None)
def _svg_source(name: str) -> str:
    return paths.resource("icons", f"{name}.svg").read_text(encoding="utf-8")


def tinted_svg(name: str, color: str, stroke_width: float | None = None) -> bytes:
    svg = _svg_source(name).replace("currentColor", color)
    if stroke_width is not None:
        svg = svg.replace('stroke-width="2"', f'stroke-width="{stroke_width}"')
    return svg.encode("utf-8")


def pixmap(name: str, color: str, size: int = 18, dpr: float = 2.0) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(tinted_svg(name, color)))
    img = QImage(int(size * dpr), int(size * dpr), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size * dpr, size * dpr))
    painter.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, color: str | None = None, size: int = 18, active_color: str | None = None) -> QIcon:
    from . import theme

    color = color or theme.current().text
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size), QIcon.Normal, QIcon.Off)
    ic.addPixmap(pixmap(name, theme.current().faint, size), QIcon.Disabled, QIcon.Off)
    if active_color:
        ic.addPixmap(pixmap(name, active_color, size), QIcon.Normal, QIcon.On)
    return ic


def tinted_icon_file(name: str, color: str) -> str:
    """Path of a tinted SVG on disk (for use in style sheets)."""
    _TMP.mkdir(parents=True, exist_ok=True)
    key = hashlib.md5(f"{name}{color}".encode()).hexdigest()[:10]
    target = _TMP / f"{name}-{key}.svg"
    if not target.exists():
        target.write_bytes(tinted_svg(name, color))
    return str(target)


def size(n: int) -> QSize:
    return QSize(n, n)
