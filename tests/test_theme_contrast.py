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
        for bg in ("bg", "chrome", "surface", "surface2", "surface3", "accent_soft"):
            out.append((f"{fg} on {bg}", getattr(p, fg), getattr(p, bg)))
    for bg in ("bg", "chrome", "surface", "surface2"):  # small captions and step labels ("faint")
        out.append((f"faint on {bg}", p.faint, getattr(p, bg)))
    # links, counts, error text, states and costs as text
    for fg in ("accent_text", "accent_text_hover", "danger_text", "success", "warning"):
        for bg in ("bg", "chrome", "surface", "surface2"):
            out.append((f"{fg} on {bg}", getattr(p, fg), getattr(p, bg)))
    out += [("accent_text on accent_soft (badge)", p.accent_text, p.accent_soft),
            ("accent_text_hover on accent_soft (count badge, pressed tool)", p.accent_text_hover, p.accent_soft),
            ("on_accent_soft on accent_soft (the chosen method card)", p.on_accent_soft, p.accent_soft),
            ("on_accent on accent (primary button)", p.on_accent, p.accent),
            ("on_accent on accent_hover (primary button, hover)", p.on_accent, p.accent_hover),
            ("on_status on success (badge)", p.on_status, p.success),
            ("on_status on warning (badge)", p.on_status, p.warning),
            ("on_status on danger (a danger button, hover)", p.on_status, p.danger),
            ("on_paper on paper (hints on the empty canvas)", p.on_paper, p.paper),
            ("ink on paper (the sketch)", p.ink, p.paper)]
    return out


def ui_pairs(p: theme.Palette) -> list[tuple[str, str, str]]:
    """(what, part, what is around it) for the parts that make a control or a state visible (WCAG 1.4.11)."""
    out = []
    for bg in ("bg", "chrome", "surface", "surface2"):
        out.append((f"field (text-field border) on {bg}", p.field, getattr(p, bg)))
    for bg in ("bg", "chrome", "surface", "surface2", "surface3", "accent_soft"):
        out.append((f"focus ring on {bg}", p.focus, getattr(p, bg)))
    for bg in ("bg", "chrome", "surface"):
        out.append((f"accent (chosen card edge, progress) on {bg}", p.accent, getattr(p, bg)))
        out.append((f"danger (a destructive button's edge) on {bg}", p.danger, getattr(p, bg)))
        out.append((f"warning (warning banner edge) on {bg}", p.warning, getattr(p, bg)))
    out.append(("accent progress on its track (surface2)", p.accent, p.surface2))
    return out


@pytest.mark.parametrize("palette", [theme.DARK, theme.LIGHT], ids=lambda p: p.name)
def test_every_text_colour_meets_wcag_aa(palette):
    low = [f"{what}: {contrast(fg, bg):.2f}" for what, fg, bg in pairs(palette) if contrast(fg, bg) < AA]
    assert low == []


@pytest.mark.parametrize("palette", [theme.DARK, theme.LIGHT], ids=lambda p: p.name)
def test_the_parts_of_controls_meet_3_to_1(palette):
    """4.0: text-field borders, the focus ring, chosen edges, the progress and the destructive / warning edges
    stand out at least 3 : 1 (the 3.8 inputs had 1.1–1.4 : 1). ``control`` (button outlines) is decorative – a
    button is told by its fill and label – and is not measured."""
    low = [f"{what}: {contrast(fg, bg):.2f}" for what, fg, bg in ui_pairs(palette) if contrast(fg, bg) < 3.0]
    assert low == []


def test_the_contrast_formula():
    assert round(contrast("#000000", "#FFFFFF"), 1) == 21.0
    assert contrast("#777777", "#777777") == 1.0


def _phone_palettes() -> dict[str, dict[str, str]]:
    """The phone page's colours (phone.css): light from :root, dark from the prefers-color-scheme block."""
    import re
    from pathlib import Path

    css = (Path(theme.__file__).parent.parent / "resources" / "phone" / "phone.css").read_text(encoding="utf-8")
    pick = lambda block: dict(re.findall(r"--([\w-]+):\s*(#[0-9A-Fa-f]{6})\s*;", block))  # noqa: E731
    light = pick(re.search(r":root\s*\{([^}]*)\}", css).group(1))
    dark = {**light, **pick(re.search(r"prefers-color-scheme:\s*dark\)\s*\{\s*:root[^{]*\{([^}]*)\}", css).group(1))}
    return {"light": light, "dark": dark}


@pytest.mark.parametrize("name", ["light", "dark"])
def test_phone_page_text_colours_meet_wcag_aa(name):
    """4.0: the phone page's text colours meet AA as well – white on the accent of the buttons, the accent as text,
    the muted text, the hints on the white paper (the dark page's buttons had 3.2:1)."""
    v = _phone_palettes()[name]
    pairs_ = [(f"{fg} on {bg}", v[fg], v[bg]) for fg in ("text", "muted") for bg in ("bg", "card", "field")]
    pairs_ += [(f"accent-text on {bg}", v["accent-text"], v[bg]) for bg in ("bg", "card")]
    pairs_ += [("on-accent on accent (buttons)", v["on-accent"], v["accent"]),
               ("on-paper on white paper", v["on-paper"], "#FFFFFF"),
               ("warn-text on warn", v["warn-text"], v["warn"])]
    low = [f"{what}: {contrast(fg, bg):.2f}" for what, fg, bg in pairs_ if contrast(fg, bg) < AA]
    assert low == []
