"""Design tokens and the Qt style sheet (dark / light)."""

from __future__ import annotations

import sys
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

from .. import paths


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str
    sidebar: str
    surface: str
    surface2: str
    surface3: str
    border: str
    text: str
    muted: str
    faint: str
    accent: str
    accent_hover: str
    accent_soft: str
    on_accent: str
    success: str
    warning: str
    danger: str
    paper: str
    ink: str


DARK = Palette(
    name="dark", bg="#0E1015", sidebar="#0B0D11", surface="#161920", surface2="#1D212A", surface3="#262B36",
    border="#2A303C", text="#E8EAF0", muted="#9AA3B4", faint="#6B7385", accent="#6366F1",
    accent_hover="#7C7FF8", accent_soft="#262A55", on_accent="#FFFFFF", success="#22C55E", warning="#F59E0B",
    danger="#EF4444", paper="#FFFFFF", ink="#111111",
)

LIGHT = Palette(
    name="light", bg="#F4F5F9", sidebar="#ECEEF4", surface="#FFFFFF", surface2="#F3F4F8", surface3="#E8EBF2",
    border="#DCE0E9", text="#141821", muted="#5A6375", faint="#8A93A5", accent="#4F46E5",
    accent_hover="#6366F1", accent_soft="#E4E4FC", on_accent="#FFFFFF", success="#16A34A", warning="#D97706",
    danger="#DC2626", paper="#FFFFFF", ink="#111111",
)

_current = DARK
FONT_FAMILY = "Inter"


def current() -> Palette:
    return _current


def load_fonts() -> str:
    global FONT_FAMILY
    families = []
    for f in sorted(paths.resource("fonts").glob("*.ttf")):
        fid = QFontDatabase.addApplicationFont(str(f))
        if fid >= 0:
            families += QFontDatabase.applicationFontFamilies(fid)
    if "Inter" in families:
        FONT_FAMILY = "Inter"
    elif sys.platform == "win32":
        FONT_FAMILY = "Segoe UI"
    return FONT_FAMILY


def resolve_mode(mode: str) -> Palette:
    if mode == "light":
        return LIGHT
    if mode == "dark":
        return DARK
    app = QApplication.instance()
    try:
        scheme = app.styleHints().colorScheme()
        return LIGHT if scheme == Qt.ColorScheme.Light else DARK
    except Exception:
        return DARK


def apply(app: QApplication, mode: str = "dark") -> Palette:
    global _current
    _current = resolve_mode(mode)
    p = _current
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(p.bg))
    pal.setColor(QPalette.WindowText, QColor(p.text))
    pal.setColor(QPalette.Base, QColor(p.surface2))
    pal.setColor(QPalette.AlternateBase, QColor(p.surface))
    pal.setColor(QPalette.Text, QColor(p.text))
    pal.setColor(QPalette.Button, QColor(p.surface2))
    pal.setColor(QPalette.ButtonText, QColor(p.text))
    pal.setColor(QPalette.Highlight, QColor(p.accent))
    pal.setColor(QPalette.HighlightedText, QColor(p.on_accent))
    pal.setColor(QPalette.ToolTipBase, QColor(p.surface3))
    pal.setColor(QPalette.ToolTipText, QColor(p.text))
    pal.setColor(QPalette.PlaceholderText, QColor(p.faint))
    pal.setColor(QPalette.Link, QColor(p.accent_hover))
    app.setPalette(pal)
    app.setStyleSheet(stylesheet(p))
    return p


def stylesheet(p: Palette) -> str:
    return f"""
* {{
    font-family: "{FONT_FAMILY}";
    font-size: 13px;
    color: {p.text};
    outline: 0;
}}
QMainWindow, QWidget#Root {{ background: {p.bg}; }}
QWidget#Page {{ background: {p.bg}; }}
QWidget#Sidebar {{ background: {p.sidebar}; border-right: 1px solid {p.border}; }}
QLabel {{ background: transparent; }}
QLabel[role="brand"] {{ font-size: 15px; font-weight: 700; }}
QLabel[role="title"] {{ font-size: 22px; font-weight: 700; }}
QLabel[role="h2"] {{ font-size: 15px; font-weight: 600; }}
QLabel[role="h3"] {{ font-size: 13px; font-weight: 600; }}
QLabel[role="muted"] {{ color: {p.muted}; }}
QLabel[role="faint"] {{ color: {p.faint}; font-size: 12px; }}
QLabel[role="stat"] {{ font-size: 20px; font-weight: 700; }}
QLabel[role="mono"] {{ font-family: "Consolas", "DejaVu Sans Mono", monospace; color: {p.muted}; }}
QLabel[role="badge"] {{
    background: {p.accent_soft}; color: {p.accent_hover}; border-radius: 9px; padding: 2px 8px;
    font-size: 11px; font-weight: 600;
}}
QLabel[role="badge-success"] {{
    background: {p.success}; color: white; border-radius: 9px; padding: 2px 8px; font-size: 11px; font-weight: 600;
}}
QLabel[role="badge-warning"] {{
    background: {p.warning}; color: #111; border-radius: 9px; padding: 2px 8px; font-size: 11px; font-weight: 600;
}}

QFrame#Card {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 14px; }}
QFrame#CardFlat {{ background: {p.surface2}; border: 1px solid {p.border}; border-radius: 10px; }}
QFrame#Divider {{ background: {p.border}; max-height: 1px; min-height: 1px; border: none; }}
QFrame#MethodCard {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 12px; }}
QFrame#MethodCard:hover {{ border-color: {p.faint}; }}
QFrame#MethodCard[selected="true"] {{ background: {p.accent_soft}; border: 1.5px solid {p.accent}; }}
QFrame#Banner {{ background: {p.accent_soft}; border: 1px solid {p.accent}; border-radius: 10px; }}
QFrame#BannerWarn {{ background: {p.surface2}; border: 1px solid {p.warning}; border-radius: 10px; }}

QPushButton {{
    background: {p.surface2}; border: 1px solid {p.border}; border-radius: 9px; padding: 7px 14px;
    font-weight: 500;
}}
QPushButton:hover {{ background: {p.surface3}; }}
QPushButton:pressed {{ background: {p.border}; }}
QPushButton:disabled {{ color: {p.faint}; background: {p.surface}; }}
QPushButton[variant="primary"] {{
    background: {p.accent}; border: 1px solid {p.accent}; color: {p.on_accent}; font-weight: 600;
}}
QPushButton[variant="primary"]:hover {{ background: {p.accent_hover}; border-color: {p.accent_hover}; }}
QPushButton[variant="primary"]:disabled {{ background: {p.surface3}; border-color: {p.surface3}; color: {p.faint}; }}
QPushButton[variant="danger"] {{ background: transparent; border: 1px solid {p.danger}; color: {p.danger}; }}
QPushButton[variant="danger"]:hover {{ background: {p.danger}; color: white; }}
QPushButton[variant="danger"]:disabled {{ border-color: {p.border}; color: {p.faint}; background: transparent; }}
QPushButton[variant="ghost"] {{ background: transparent; border: 1px solid transparent; }}
QPushButton[variant="ghost"]:hover {{ background: {p.surface2}; border-color: {p.border}; }}
QPushButton[size="lg"] {{ padding: 11px 20px; font-size: 14px; border-radius: 11px; }}

QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 4px; }}
QToolButton:hover {{ background: {p.surface2}; border-color: {p.border}; }}
QToolButton:checked {{ background: {p.accent_soft}; border-color: {p.accent}; }}

QToolButton#NavButton {{
    border-radius: 10px; padding: 8px 2px; color: {p.muted}; font-size: 11px; font-weight: 500;
}}
QToolButton#NavButton:hover {{ background: {p.surface2}; color: {p.text}; border-color: transparent; }}
QToolButton#NavButton:checked {{ background: {p.accent_soft}; color: {p.text}; border-color: transparent; }}

QPushButton#Segment {{
    background: transparent; border: none; border-radius: 7px; padding: 5px 12px; color: {p.muted};
}}
QPushButton#Segment:hover {{ color: {p.text}; }}
QPushButton#Segment:checked {{ background: {p.surface3}; color: {p.text}; font-weight: 600; }}
QFrame#SegmentBar {{ background: {p.surface2}; border: 1px solid {p.border}; border-radius: 9px; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{
    background: {p.surface2}; border: 1px solid {p.border}; border-radius: 8px; padding: 5px 8px;
    selection-background-color: {p.accent};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{
    border: 1px solid {p.accent};
}}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{ color: {p.faint}; }}
QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {{
    width: 0px; border: none;
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url({_icon_url('chevron-down', p.muted)}); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{
    background: {p.surface2}; border: 1px solid {p.border}; border-radius: 8px; padding: 4px;
    selection-background-color: {p.accent_soft}; selection-color: {p.text};
}}

QSlider::groove:horizontal {{ height: 4px; background: {p.surface3}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {p.accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {p.paper}; border: 2px solid {p.accent}; width: 12px; height: 12px; margin: -6px 0;
    border-radius: 8px;
}}
QSlider::handle:horizontal:hover {{ background: {p.accent_soft}; }}
QSlider::sub-page:horizontal:disabled {{ background: {p.faint}; }}
QSlider::handle:horizontal:disabled {{ border-color: {p.faint}; }}

QProgressBar {{
    background: {p.surface3}; border: none; border-radius: 4px; height: 8px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {p.accent}; border-radius: 4px; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p.surface3}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {p.faint}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p.surface3}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QToolTip {{
    background: {p.surface3}; color: {p.text}; border: 1px solid {p.border}; border-radius: 8px; padding: 8px;
}}
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: 8px; }}

QListWidget {{ background: transparent; border: none; }}
QListWidget::item {{ border-radius: 8px; padding: 6px; }}
QListWidget::item:selected {{ background: {p.accent_soft}; color: {p.text}; }}
QListWidget::item:hover {{ background: {p.surface2}; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 5px; border: 1px solid {p.border}; background: {p.surface2};
}}
QCheckBox::indicator:checked {{
    background: {p.accent}; border-color: {p.accent}; image: url({_icon_url('check', '#FFFFFF')});
}}
QMenu {{ background: {p.surface2}; border: 1px solid {p.border}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {p.accent_soft}; }}
QDialog {{ background: {p.bg}; }}
QMessageBox {{ background: {p.bg}; }}
"""


def _icon_url(name: str, color: str) -> str:
    from .icons import tinted_icon_file

    return tinted_icon_file(name, color).replace("\\", "/")
