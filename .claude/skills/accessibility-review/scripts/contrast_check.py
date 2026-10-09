"""WCAG contrast of CLIPasso Studio's colours: the studio (theme.py, dark and light) and the phone page (phone.css,
light and dark) – text at 4.5:1 (1.4.3) and the parts of controls at 3:1 (1.4.11).

tests/test_theme_contrast.py already guards the studio's text colours; this adds the non-text pairs (borders,
focus, tracks, checked states), the phone page and any pair you pass.

Usage: python .claude/skills/accessibility-review/scripts/contrast_check.py            # every known pair
       python .claude/skills/accessibility-review/scripts/contrast_check.py "#9AA3B4" "#FFFFFF" [FG BG ...]
       --failing   only the pairs below their minimum
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
THEME = ROOT / "clipasso_studio" / "gui" / "theme.py"
PHONE_CSS = ROOT / "clipasso_studio" / "resources" / "phone" / "phone.css"
TEXT, LARGE, UI = 4.5, 3.0, 3.0


def _rgb(colour: str) -> tuple[float, float, float]:
    h = colour.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def luminance(colour: str) -> float:
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in _rgb(colour)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def palettes() -> dict[str, dict[str, str]]:
    tree = ast.parse(THEME.read_text(encoding="utf-8"))
    out, defaults = {}, {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Palette":  # fields with a default (on_status, on_paper)
            defaults = {f.target.id: f.value.value for f in node.body
                        if isinstance(f, ast.AnnAssign) and isinstance(f.value, ast.Constant)}
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and \
                getattr(node.value.func, "id", "") == "Palette":
            out[node.targets[0].id] = {**defaults, **{kw.arg: kw.value.value for kw in node.value.keywords
                                                      if isinstance(kw.value, ast.Constant)}}
    return out


def phone_vars() -> dict[str, dict[str, str]]:
    css = PHONE_CSS.read_text(encoding="utf-8")
    light = dict(re.findall(r"--([\w-]+):\s*(#[0-9A-Fa-f]{3,6})\s*;", re.search(r":root\s*\{([^}]*)\}", css).group(1)))
    m = re.search(r"prefers-color-scheme:\s*dark\)\s*\{\s*:root[^{]*\{([^}]*)\}", css)
    dark = {**light, **dict(re.findall(r"--([\w-]+):\s*(#[0-9A-Fa-f]{3,6})\s*;", m.group(1) if m else ""))}
    return {"light": light, "dark": dark}


def studio_pairs(p: dict[str, str]) -> list[tuple[str, str, str, float]]:
    """(what, foreground, background, minimum) – the text pairs of the test plus the non-text ones."""
    out = []
    for fg in ("text", "muted"):
        for bg in ("bg", "sidebar", "surface", "surface2", "surface3", "accent_soft"):
            out.append((f"text: {fg} on {bg}", p[fg], p[bg], TEXT))
    for bg in ("bg", "sidebar", "surface", "surface2"):
        out.append((f"text: faint (captions, placeholders, disabled) on {bg}", p["faint"], p[bg], TEXT))
    for fg in ("accent_text", "danger", "success", "warning"):
        for bg in ("bg", "surface", "surface2"):
            out.append((f"text: {fg} on {bg}", p[fg], p[bg], TEXT))
    out += [("text: on_accent on accent (primary button)", p["on_accent"], p["accent"], TEXT),
            ("text: on_accent on accent_hover", p["on_accent"], p["accent_hover"], TEXT),
            ("text: on_status on success (badge)", p["on_status"], p["success"], TEXT),
            ("text: on_status on warning (badge)", p["on_status"], p["warning"], TEXT),
            ("text: danger hover – on_status on danger", p["on_status"], p["danger"], TEXT),
            ("text: on_paper (hints on the empty canvas) on paper", p["on_paper"], p["paper"], TEXT)]
    # 1.4.11: what makes a control visible – its boundary or fill against what is around it
    for bg in ("bg", "surface"):
        out.append((f"ui: input/button border (border) on {bg}", p["border"], p[bg], UI))
        out.append((f"ui: input fill (surface2) on {bg}", p["surface2"], p[bg], UI))
    for bg in ("surface", "surface2"):
        out.append((f"ui: focus / checked border (accent) on {bg}", p["accent"], p[bg], UI))
    out += [("ui: slider groove (surface3) on surface", p["surface3"], p["surface"], UI),
            ("ui: slider filled part (accent) on surface", p["accent"], p["surface"], UI),
            ("ui: progress chunk (accent) on its track (surface3)", p["accent"], p["surface3"], UI),
            ("ui: checked nav / segment (accent_soft) on sidebar", p["accent_soft"], p["sidebar"], UI),
            ("ui: selected method card border (accent) on bg", p["accent"], p["bg"], UI),
            ("ui: warning banner border (warning) on bg", p["warning"], p["bg"], UI)]
    return out


def phone_pairs(v: dict[str, str]) -> list[tuple[str, str, str, float]]:
    out = []
    for fg in ("text", "muted"):
        for bg in ("bg", "card", "field"):
            if fg in v and bg in v:
                out.append((f"text: --{fg} on --{bg}", v[fg], v[bg], TEXT))
    out += [("text: --on-accent on --accent (primary button)", v["on-accent"], v["accent"], TEXT),
            ("text: --accent-text (.phase, the chosen tab) on --card", v.get("accent-text", v["accent"]), v["card"],
             TEXT),
            ("text: --accent-text on --bg", v.get("accent-text", v["accent"]), v["bg"], TEXT),
            ("text: --on-paper (hints on the white paper) on #fff", v.get("on-paper", v["muted"]), "#FFFFFF", TEXT),
            ("text: --warn-text on --warn", v["warn-text"], v["warn"], TEXT),
            ("text: toast – #fff on #222", "#FFFFFF", "#222222", TEXT),
            ("ui: --line (control border) on --card", v["line"], v["card"], UI),
            ("ui: --field (control fill) on --card", v["field"], v["card"], UI),
            ("ui: --accent (checked, range, checkbox) on --card", v["accent"], v["card"], UI),
            ("ui: favourite star #f5b301 on --field", "#F5B301", v["field"], UI),
            ("ui: best-result border #2fb36b on --card", "#2FB36B", v["card"], UI)]
    return out


def table(title: str, rows: list[tuple[str, str, str, float]], failing: bool) -> list[str]:
    lines = [f"## {title}", "", "| Pair | FG | BG | Ratio | Needs | |", "|---|---|---|---|---|---|"]
    bad = 0
    for what, fg, bg, need in rows:
        r = contrast(fg, bg)
        ok = r >= need
        bad += not ok
        if failing and ok:
            continue
        lines.append(f"| {what} | {fg.upper()} | {bg.upper()} | {r:.2f}:1 | {need}:1 | {'✅' if ok else '❌'} |")
    lines.insert(1, f"{bad} of {len(rows)} below their minimum.")
    lines.append("")
    return lines


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):  # (Windows consoles default to a code page without ✅ “ ” →)
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pairs", nargs="*", help="FG BG [FG BG ...] as hex colours")
    ap.add_argument("--failing", action="store_true", help="only the pairs below their minimum")
    args = ap.parse_args()
    if args.pairs:
        if len(args.pairs) % 2:
            ap.error("pass colours in pairs: FG BG")
        for fg, bg in zip(args.pairs[::2], args.pairs[1::2]):
            r = contrast(fg, bg)
            verdict = "AA text" if r >= TEXT else "large text / UI only" if r >= UI else "fails"
            print(f"{fg} on {bg}: {r:.2f}:1 – {verdict}")
        return 0
    lines = ["# Contrast – CLIPasso Studio", "",
             "Text needs 4.5:1 (3:1 from 18.66 px bold / 24 px). 'ui' rows are WCAG 1.4.11: the boundary or fill "
             "that shows a control needs 3:1 against its surroundings – unless something else (text, an icon, "
             "a label) already identifies it. Judge those rows in context before changing a token.", ""]
    pals = palettes()
    for name in ("DARK", "LIGHT"):
        lines += table(f"Studio · {name}", studio_pairs(pals[name]), args.failing)
    pv = phone_vars()
    for mode in ("light", "dark"):
        lines += table(f"Phone page · {mode}", phone_pairs(pv[mode]), args.failing)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
