"""4.0: the design tokens live in one place (gui/theme.py) – colours, radii and styles – so the studio, its dialogs
and the phone page look the same and change together."""

import re
from dataclasses import fields
from pathlib import Path

from clipasso_studio.gui import theme

GUI = Path(theme.__file__).parent
# colours that are not interface colours: the sketch's ink and paper, export / print / brush defaults, the colour
# picker's swatch, captions on a dark photo scrim, the phone manifest (slice 9: from the palette)
ARTWORK = {"brush.py", "dialogs.py", "export.py", "export_jobs.py", "paper.py", "print_dialog.py", "print_layout.py",
           "strokes.py", "telegram.py", "thumbs.py", "phone_api.py", "remote.py", "image_edit.py", "gallery_viewer.py",
           "widgets/canvas.py"}


def _gui_files():
    for path in sorted(GUI.rglob("*.py")):
        rel = path.relative_to(GUI).as_posix()
        if rel != "theme.py":
            yield rel, path.read_text(encoding="utf-8")


def test_both_palettes_have_every_token_as_a_colour():
    names = [f.name for f in fields(theme.Palette) if f.name != "name"]
    assert {"chrome", "control", "field", "focus", "on_accent_soft", "accent_text_hover", "danger_text"} <= set(names)
    for p in (theme.DARK, theme.LIGHT):
        bad = [n for n in names if not re.fullmatch(r"#[0-9A-F]{6}", getattr(p, n))]
        assert bad == [], (p.name, bad)
    assert theme.DARK.focus == theme.DARK.accent_text and theme.LIGHT.focus == theme.LIGHT.accent_text


def test_no_interface_colour_outside_the_theme():
    """Hex colours and named QColors only in theme.py – or in the files that draw artwork (sketch, export, print)."""
    found = []
    for rel, text in _gui_files():
        if rel in ARTWORK:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if re.search(r"#[0-9A-Fa-f]{6}\b", line) or re.search(r"QColor\(\s*[\"'](white|black|red|gray)", line):
                found.append(f"{rel}:{n}: {line.strip()}")
    assert found == []


def test_style_sheets_only_in_the_theme():
    """Looks are properties (role, variant, state …) styled in theme.stylesheet() – not inline style sheets, which
    a theme switch does not reach. The colour picker's swatch (its own colour) is the one exception."""
    found = [f"{rel}:{n}" for rel, text in _gui_files() for n, line in enumerate(text.splitlines(), 1)
             if "setStyleSheet(" in line and rel != "dialogs.py"]
    assert found == []
    assert open(GUI / "dialogs.py", encoding="utf-8").read().count("setStyleSheet(") == 1


def test_rounded_shapes_use_the_radius_tokens():
    """4.0: radii 4 / 7 / 8 / 9 / 10 / 11 / 12 – every painted rounded rectangle takes one of theme.RADIUS_*."""
    found = []
    for rel, text in _gui_files():
        for n, line in enumerate(text.splitlines(), 1):
            if re.search(r"(draw|add)RoundedRect\(.*,\s*\d+(\.\d+)?\s*,\s*\d+(\.\d+)?\s*\)", line):
                found.append(f"{rel}:{n}: {line.strip()}")
    assert found == []
    radii = sorted(int(v) for k, v in vars(theme).items() if k.startswith("RADIUS_"))
    assert radii == [4, 7, 8, 9, 10, 11, 12]
    sheet = theme.stylesheet(theme.DARK)
    assert set(int(r) for r in re.findall(r"border-radius:\s*(\d+)px", sheet)) <= set(radii) | {2}  # (4 px grooves)


def test_the_label_role(qapp):
    """4.0: step labels ("1 · BILD") – 11 px, 600, faint, in capitals with 0.06 em spacing (set on the font: a Qt
    style sheet has no text-transform); the text itself stays as written, for screen readers."""
    from PySide6.QtGui import QFont

    from clipasso_studio.gui.widgets.common import label

    lbl = label("1 · Bild", "label")
    assert lbl.text() == "1 · Bild" and lbl.property("role") == "label"
    assert lbl.font().capitalization() == QFont.AllUppercase and lbl.font().letterSpacing() > 0
    assert 'QLabel[role="label"]' in theme.stylesheet(theme.DARK)
