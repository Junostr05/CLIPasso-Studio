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
    bg: str  # the window and the studio's middle, under the paper
    chrome: str  # 4.0: the header and the job footer (3.8: the sidebar)
    surface: str  # side columns, cards
    surface2: str  # buttons, inputs, flat cards, menus, the segment bar, floating toolbars
    surface3: str  # the chosen segment / tab, hover, tracks of progress and sliders
    border: str  # 1 px dividers – decorative, never the only edge of an input
    control: str  # 1 px outline of buttons, bars and toolbars (told by fill and label, so it may be soft)
    field: str  # border of text fields, spin boxes, drop-downs and check boxes: ≥ 3 : 1 on surface / surface2
    text: str
    muted: str
    faint: str  # captions, step labels, disabled text – on bg, chrome, surface, surface2 only
    accent: str
    accent_hover: str
    accent_soft: str
    on_accent: str
    on_accent_soft: str  # secondary text on accent_soft (the chosen method card's description and cost)
    accent_text: str  # the accent as text or icon on the surfaces (accent_hover is a button background)
    accent_text_hover: str  # a link under the mouse; counts in the header
    focus: str  # the keyboard focus ring (≥ 3 : 1 on every surface)
    success: str
    warning: str
    danger: str  # the outline of a destructive button, its hover fill
    danger_text: str  # the label of a destructive button, error text
    on_status: str  # text on the success / warning / danger colours (badges, a danger button's hover)
    paper: str  # the sketch's paper – white in both themes
    ink: str
    on_paper: str  # hints painted on the white sketch paper (the same in both themes)
    detail_more: str  # detail brush: more detail
    detail_less: str  # detail brush: less detail


# 4.0, direction A "Ruhiges Profi-Werkzeug" (the design system's tokens.json); every pair a test measures
DARK = Palette(
    name="dark", bg="#0E1015", chrome="#0B0D11", surface="#15181F", surface2="#1C2029", surface3="#2E3442",
    border="#2A303C", control="#3A4250", field="#636C80", text="#E8EAF0", muted="#A3ACBD", faint="#8790A2",
    accent="#6164F1", accent_hover="#5457E8", accent_soft="#262A55", on_accent="#FFFFFF", on_accent_soft="#C8CAF6",
    accent_text="#8E91FA", accent_text_hover="#B4B6FC", focus="#8E91FA", success="#22C55E", warning="#F5B547",
    danger="#F06A6A", danger_text="#F48A8A", on_status="#111111", paper="#FFFFFF", ink="#111111", on_paper="#5A6375",
    detail_more="#FF8C00", detail_less="#2878FF",
)

LIGHT = Palette(
    name="light", bg="#F4F5F9", chrome="#FFFFFF", surface="#FFFFFF", surface2="#F3F4F8", surface3="#E8EBF2",
    border="#DCE0E9", control="#C3C9D5", field="#7D8699", text="#141821", muted="#5A6375", faint="#626C80",
    accent="#4F46E5", accent_hover="#4338CA", accent_soft="#E4E4FC", on_accent="#FFFFFF", on_accent_soft="#3730A3",
    accent_text="#4F46E5", accent_text_hover="#3730A3", focus="#4F46E5", success="#11813B", warning="#A75C05",
    danger="#D32222", danger_text="#C21D1D", on_status="#FFFFFF", paper="#FFFFFF", ink="#111111", on_paper="#5A6375",
    detail_more="#FF8C00", detail_less="#2878FF",
)

_current = DARK

# spacing tokens (px): the same distances on every page
SPACE_XS, SPACE_S, SPACE_M, SPACE_L, SPACE_XL = 4, 8, 12, 16, 24
PAGE_MARGINS = (SPACE_XL, 20, SPACE_XL, 20)  # left, top, right, bottom of a page
PAGE_SPACING = SPACE_L  # between a page's parts (header, cards, lists)
COLUMN_PADDING = 20  # 4.0: inside the side columns, the header and the footer
DIALOG_MARGIN, DIALOG_SPACING = SPACE_XL, SPACE_L  # 4.0: dialogs on the scale (3.8: 22 / 14 by habit)
HEADER_HEIGHT, FOOTER_HEIGHT = 52, 76
LEFT_COLUMN, RIGHT_COLUMN = 312, 168

# radii (px) – every rounded shape uses one of these
RADIUS_PROGRESS = 4  # the progress bar, check boxes, scroll bar handles
RADIUS_SEGMENT = 7  # a segment or tab inside its bar, menu items
RADIUS_CONTROL = 8  # buttons, inputs, tool buttons, thumbnails, the paper, tooltips
RADIUS_BAR = 9  # the segment / tab bar, badges
RADIUS_CARD = 10  # cards, method cards, banners, menus
RADIUS_LARGE = 11  # large buttons, the toggle switch
RADIUS_FLOAT = 12  # floating toolbars and panels


def page_layout(layout) -> None:
    """A page's outer layout with the page margins and spacing."""
    layout.setContentsMargins(*PAGE_MARGINS)
    layout.setSpacing(PAGE_SPACING)
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
    pal.setColor(QPalette.Link, QColor(p.accent_text))
    app.setPalette(pal)
    app.setStyleSheet(stylesheet(p))
    return p


def stylesheet(p: Palette) -> str:
    rc, rb, rd, rl, rs, rp = RADIUS_CONTROL, RADIUS_BAR, RADIUS_CARD, RADIUS_LARGE, RADIUS_SEGMENT, RADIUS_PROGRESS
    return f"""
* {{
    font-family: "{FONT_FAMILY}";
    font-size: 13px;
    color: {p.text};
    outline: 0;
}}
QMainWindow, QWidget#Root {{ background: {p.bg}; }}
QWidget#Page {{ background: {p.bg}; }}
QWidget#Sidebar {{ background: {p.chrome}; border-right: 1px solid {p.border}; }}
QLabel {{ background: transparent; }}
QLabel[role="brand"] {{ font-size: 15px; font-weight: 700; }}
QLabel[role="title"] {{ font-size: 22px; font-weight: 700; }}
QLabel[role="h2"] {{ font-size: 15px; font-weight: 600; }}
QLabel[role="h3"] {{ font-size: 13px; font-weight: 600; }}
QLabel[role="muted"] {{ color: {p.muted}; }}
QLabel[role="faint"] {{ color: {p.faint}; font-size: 12px; }}
QLabel[role="label"] {{ color: {p.faint}; font-size: 11px; font-weight: 600; }}
QLabel[role="status-success"] {{ color: {p.success}; font-size: 12px; }}
QLabel[role="status-warning"] {{ color: {p.warning}; font-size: 12px; }}
QLabel[role="status-danger"] {{ color: {p.danger_text}; font-size: 12px; }}
QLabel[changed="true"] {{ color: {p.accent_text}; }}
QLabel#Byline {{ font-size: 11px; }}
QLabel[role="stat"] {{ font-size: 20px; font-weight: 700; }}
QLabel[role="mono"] {{ font-family: "Consolas", "DejaVu Sans Mono", monospace; color: {p.muted}; }}
QLabel[role="badge"] {{
    background: {p.accent_soft}; color: {p.accent_text}; border-radius: {rb}px; padding: 2px 8px;
    font-size: 11px; font-weight: 600;
}}
QLabel[role="count"] {{
    background: {p.accent_soft}; color: {p.accent_text_hover}; border-radius: {rb}px; padding: 1px 7px;
    font-size: 11px; font-weight: 600;
}}
QLabel[role="badge-success"] {{
    background: {p.success}; color: {p.on_status}; border-radius: {rb}px; padding: 2px 8px; font-size: 11px;
    font-weight: 600;
}}
QLabel[role="badge-warning"] {{
    background: {p.warning}; color: {p.on_status}; border-radius: {rb}px; padding: 2px 8px; font-size: 11px;
    font-weight: 600;
}}
QLabel[role="badge-danger"] {{
    background: {p.danger}; color: {p.on_status}; border-radius: {rb}px; padding: 2px 8px; font-size: 11px;
    font-weight: 600;
}}

QFrame#Card {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: {rd}px; }}
QFrame#CardFlat {{ background: {p.surface2}; border: 1px solid {p.border}; border-radius: {rd}px; }}
QFrame#CardFlat[state="selected"] {{ border: 2px solid {p.accent}; }}
QFrame#CardFlat[state="best"] {{ border: 2px solid {p.success}; }}
QFrame#Divider {{ background: {p.border}; max-height: 1px; min-height: 1px; border: none; }}
QFrame#MethodCard {{ background: transparent; border: 1px solid {p.border}; border-radius: {rd}px; }}
QFrame#MethodCard:hover {{ background: {p.surface2}; }}
QFrame#MethodCard[selected="true"] {{ background: {p.accent_soft}; border: 1.5px solid {p.accent}; }}
QFrame#Column {{ background: {p.surface}; border: none; }}
QFrame#Column[side="left"] {{ border-right: 1px solid {p.border}; }}
QFrame#Column[side="right"] {{ border-left: 1px solid {p.border}; }}
QFrame#Chip {{ background: transparent; border: none; }}
QFrame#Chip[framed="true"] {{ background: {p.surface2}; border: 1px solid {p.control}; border-radius: {rb}px; }}
QFrame#Banner {{ background: {p.accent_soft}; border: 1px solid {p.accent}; border-radius: {rd}px; }}
QFrame#BannerWarn {{ background: {p.surface2}; border: 1px solid {p.warning}; border-radius: {rd}px; }}
QLabel#WebcamView {{ background: {p.surface2}; border-radius: {rd}px; }}
QListView#GalleryView {{ background: transparent; border: none; }}

QPushButton {{
    background: {p.surface2}; border: 1px solid {p.control}; border-radius: {rc}px; padding: 7px 14px;
    font-weight: 500;
}}
QPushButton:hover {{ background: {p.surface3}; }}
QPushButton:pressed {{ background: {p.control}; }}
QPushButton:disabled {{ color: {p.faint}; background: transparent; border-color: {p.border}; }}
QPushButton[align="left"] {{ text-align: left; }}
QPushButton[variant="primary"] {{
    background: {p.accent}; border: 1px solid {p.accent}; color: {p.on_accent}; font-weight: 600;
}}
QPushButton[variant="primary"]:hover {{ background: {p.accent_hover}; border-color: {p.accent_hover}; }}
QPushButton[variant="primary"]:disabled {{ background: {p.surface3}; border-color: {p.surface3}; color: {p.faint}; }}
QPushButton[variant="danger"] {{ background: transparent; border: 1px solid {p.danger}; color: {p.danger_text}; }}
QPushButton[variant="danger"]:hover {{ background: {p.danger}; color: {p.on_status}; }}
QPushButton[variant="danger"]:disabled {{ border-color: {p.border}; color: {p.faint}; background: transparent; }}
QPushButton[variant="ghost"] {{ background: transparent; border: 1px solid transparent; }}
QPushButton[variant="ghost"]:hover {{ background: {p.surface2}; border-color: {p.control}; }}
QPushButton[variant="link"] {{
    background: transparent; border: none; padding: 2px 0; color: {p.accent_text}; font-weight: 500;
}}
QPushButton[variant="link"]:hover {{ color: {p.accent_text_hover}; background: transparent; }}
QPushButton[variant="link"]:disabled {{ color: {p.faint}; }}
QPushButton:checked, QPushButton[variant="ghost"]:checked {{ background: {p.accent_soft}; border-color: {p.accent}; }}
QPushButton[size="lg"] {{ padding: 10px 18px; font-size: 14px; font-weight: 600; border-radius: {rl}px; }}
QPushButton[size="sm"] {{ padding: 4px 10px; font-size: 12px; border-radius: {rc}px; }}
QPushButton#SectionHeader {{
    background: transparent; border: none; text-align: left; padding: 10px 4px; font-weight: 600;
    font-size: 13px;
}}
QPushButton#SectionHeader:hover {{ color: {p.accent_text}; background: transparent; }}

QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: {rc}px; padding: 4px; }}
QToolButton:hover {{ background: {p.surface2}; border-color: {p.control}; }}
QToolButton:checked {{ background: {p.accent_soft}; border-color: {p.accent}; }}

QToolButton#NavButton {{
    border-radius: {rd}px; padding: 8px 2px; color: {p.muted}; font-size: 11px; font-weight: 500;
}}
QToolButton#NavButton:hover {{ background: {p.surface2}; color: {p.text}; border-color: transparent; }}
QToolButton#NavButton:checked {{ background: {p.accent_soft}; color: {p.text}; border-color: transparent; }}

QPushButton#Segment {{
    background: transparent; border: none; border-radius: {rs}px; padding: 5px 12px; color: {p.muted};
}}
QPushButton#Segment:hover {{ color: {p.text}; }}
QPushButton#Segment:checked {{ background: {p.surface3}; color: {p.text}; font-weight: 600; }}
QFrame#SegmentBar {{ background: {p.surface2}; border: 1px solid {p.control}; border-radius: {rb}px; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{
    background: {p.surface2}; border: 1px solid {p.field}; border-radius: {rc}px; padding: 5px 8px;
    selection-background-color: {p.accent};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{
    border: 1px solid {p.focus};
}}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
    color: {p.faint}; border-color: {p.border};
}}
QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {{
    width: 0px; border: none;
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url({_icon_url('chevron-down', p.muted)}); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{
    background: {p.surface2}; border: 1px solid {p.control}; border-radius: {rc}px; padding: 4px;
    selection-background-color: {p.accent_soft}; selection-color: {p.text};
}}

QSlider::groove:horizontal {{ height: 4px; background: {p.surface3}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {p.accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {p.paper}; border: 2px solid {p.accent}; width: 12px; height: 12px; margin: -6px 0;
    border-radius: {rc}px;
}}
QSlider::handle:horizontal:hover {{ background: {p.accent_soft}; }}
QSlider::sub-page:horizontal:disabled {{ background: {p.faint}; }}
QSlider::handle:horizontal:disabled {{ border-color: {p.faint}; }}

QProgressBar {{
    background: {p.surface2}; border: none; border-radius: {rp}px; height: 8px; text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background: {p.accent}; border-radius: {rp}px; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p.surface3}; border-radius: {rp}px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {p.faint}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p.surface3}; border-radius: {rp}px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QToolTip {{
    background: {p.surface3}; color: {p.text}; border: 1px solid {p.control}; border-radius: {rc}px; padding: 8px;
}}
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: 8px; }}

QListWidget {{ background: transparent; border: none; }}
QListWidget::item {{ border-radius: {rc}px; padding: 6px; }}
QListWidget::item:selected {{ background: {p.accent_soft}; color: {p.text}; }}
QListWidget::item:hover {{ background: {p.surface2}; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: {rp}px; border: 1px solid {p.field}; background: {p.surface2};
}}
QCheckBox::indicator:checked {{
    background: {p.accent}; border-color: {p.accent}; image: url({_icon_url('check', p.on_accent)});
}}
QMenu {{ background: {p.surface2}; border: 1px solid {p.control}; border-radius: {rd}px; padding: 6px; }}
QMenu::item {{ padding: 6px 18px; border-radius: {rs}px; }}
QMenu::item:selected {{ background: {p.accent_soft}; }}
QMenu::separator {{ height: 1px; background: {p.border}; margin: 4px 6px; }}
QDialog {{ background: {p.bg}; }}
QMessageBox {{ background: {p.bg}; }}
"""


def _icon_url(name: str, color: str) -> str:
    from .icons import tinted_icon_file

    return tinted_icon_file(name, color).replace("\\", "/")
