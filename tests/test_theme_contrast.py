"""WCAG AA in both themes: every text colour on every surface it is shown on has a contrast of at least 4.5:1."""

import pytest

from clipasso_studio.gui import theme

AA = 4.5


def _luminance(colour: str) -> float:
    h = colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def pairs(p: theme.Palette) -> list[tuple[str, str, str]]:
    """(what, text colour, background) for every pair the app shows."""
    out = []
    for fg in ("text", "muted"):
        for bg in ("bg", "sidebar", "surface", "surface2", "surface3", "accent_soft"):
            out.append((f"{fg} on {bg}", getattr(p, fg), getattr(p, bg)))
    for bg in ("bg", "sidebar", "surface", "surface2"):  # small captions ("faint") sit on pages and cards
        out.append((f"faint on {bg}", p.faint, getattr(p, bg)))
    for fg in ("accent_text", "danger", "success", "warning"):  # links, badges, states, errors as text
        for bg in ("bg", "surface", "surface2"):
            out.append((f"{fg} on {bg}", getattr(p, fg), getattr(p, bg)))
    out += [("accent_text on accent_soft (badge)", p.accent_text, p.accent_soft),
            ("on_accent on accent (primary button)", p.on_accent, p.accent),
            ("on_accent on accent_hover (primary button, hover)", p.on_accent, p.accent_hover),
            ("on_status on success (badge)", p.on_status, p.success),
            ("on_status on warning (badge)", p.on_status, p.warning),
            ("ink on paper (the sketch)", p.ink, p.paper)]
    return out


@pytest.mark.parametrize("palette", [theme.DARK, theme.LIGHT], ids=lambda p: p.name)
def test_every_text_colour_meets_wcag_aa(palette):
    low = [f"{what}: {contrast(fg, bg):.2f}" for what, fg, bg in pairs(palette) if contrast(fg, bg) < AA]
    assert low == []


def test_the_contrast_formula():
    assert round(contrast("#000000", "#FFFFFF"), 1) == 21.0
    assert contrast("#777777", "#777777") == 1.0
