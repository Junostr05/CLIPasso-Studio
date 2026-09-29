"""Render the app icon (PNG + ICO) and the splash screen with Qt.

Usage: python tools/make_assets.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QGuiApplication, QImage, QLinearGradient,  # noqa: E402
                           QPainter, QPainterPath, QPen)

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "clipasso_studio" / "resources"
PACK = ROOT / "packaging"


def draw_icon(size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 256
    rect = QRectF(8 * s, 8 * s, 240 * s, 240 * s)
    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    grad.setColorAt(0.0, QColor("#6366F1"))
    grad.setColorAt(1.0, QColor("#A855F7"))
    p.setPen(Qt.NoPen)
    p.setBrush(grad)
    p.drawRoundedRect(rect, 56 * s, 56 * s)
    # paper
    paper = QRectF(52 * s, 46 * s, 152 * s, 164 * s)
    p.setBrush(QColor(255, 255, 255, 245))
    p.drawRoundedRect(paper, 18 * s, 18 * s)
    # a few "CLIPasso" strokes: an abstract bird-like line drawing
    pen = QPen(QColor("#1F1B3A"), max(1.0, 7 * s), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    strokes = [
        [(78, 150), (96, 104), (136, 96), (160, 118)],
        [(160, 118), (176, 132), (186, 116), (178, 96)],
        [(92, 160), (122, 176), (158, 170), (176, 146)],
        [(112, 172), (110, 186), (104, 194), (98, 196)],
        [(146, 172), (150, 186), (156, 192), (164, 194)],
    ]
    for pts in strokes:
        path = QPainterPath(QPointF(pts[0][0] * s, pts[0][1] * s))
        path.cubicTo(*(QPointF(x * s, y * s) for x, y in pts[1:]))
        p.drawPath(path)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#6366F1"))
    p.drawEllipse(QPointF(170 * s, 108 * s), 5 * s, 5 * s)
    p.end()
    return img


def qimage_to_pil(img: QImage) -> Image.Image:
    img = img.convertToFormat(QImage.Format_RGBA8888)
    data = bytes(img.constBits())[: img.width() * img.height() * 4]
    return Image.frombuffer("RGBA", (img.width(), img.height()), data, "raw", "RGBA", 0, 1).copy()


def draw_splash() -> QImage:
    w, h = 640, 360
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor("#0E1015"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    grad = QLinearGradient(0, 0, w, h)
    grad.setColorAt(0, QColor(99, 102, 241, 70))
    grad.setColorAt(1, QColor(168, 85, 247, 20))
    p.fillRect(0, 0, w, h, grad)
    icon = draw_icon(112)
    p.drawImage(56, 96, icon)
    fam = "Inter" if "Inter" in QFontDatabase.families() else p.font().family()
    f = QFont(fam, 30)
    f.setWeight(QFont.Bold)
    p.setFont(f)
    p.setPen(QColor("#E8EAF0"))
    p.drawText(QRectF(196, 104, 420, 50), Qt.AlignLeft | Qt.AlignVCenter, "CLIPasso Studio")
    f = QFont(fam, 12)
    p.setFont(f)
    p.setPen(QColor("#9AA3B4"))
    p.drawText(QRectF(198, 152, 420, 60), Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
               "Semantically-aware object sketching\nSemantische Objekt-Skizzen aus Fotos")
    p.setPen(QColor("#6B7385"))
    f = QFont(fam, 10)
    p.setFont(f)
    p.drawText(QRectF(56, 300, 540, 30), Qt.AlignLeft | Qt.AlignVCenter,
               "Wird gestartet … / Starting …")
    p.end()
    return img


def main() -> int:
    app = QGuiApplication(sys.argv)  # noqa: F841
    for f in (RES / "fonts").glob("*.ttf"):
        QFontDatabase.addApplicationFont(str(f))
    draw_icon(256).save(str(RES / "app_icon.png"))
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    base = qimage_to_pil(draw_icon(256))
    PACK.mkdir(exist_ok=True)
    base.save(PACK / "app.ico", sizes=[(s, s) for s in sizes])
    qimage_to_pil(draw_splash()).convert("RGB").save(PACK / "splash.png")
    # installer wizard images (Inno Setup: 164x314 / 55x58)
    big = Image.new("RGB", (164, 314), (14, 16, 21))
    ic = qimage_to_pil(draw_icon(120))
    big.paste(ic, (22, 97), ic)
    big.save(PACK / "wizard_large.bmp")
    small = Image.new("RGB", (55, 58), (255, 255, 255))
    ic = qimage_to_pil(draw_icon(50))
    small.paste(ic, (2, 4), ic)
    small.save(PACK / "wizard_small.bmp")
    print("assets written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
