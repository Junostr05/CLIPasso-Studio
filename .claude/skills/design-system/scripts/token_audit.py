"""Design-token audit of CLIPasso Studio: where the UI leaves the theme.

Reads the tokens from clipasso_studio/gui/theme.py (DARK, LIGHT, SPACE_*) and the phone page's CSS variables
(resources/phone/phone.css) without importing Qt, then lists:

- hard-coded colours in the GUI code – a colour that equals a token value is the strongest finding (it will be
  wrong in the other theme), the rest are off-palette; colours of the sketch itself (export, paper, brush,
  print) are listed apart because they are artwork, not interface;
- inline style sheets (setStyleSheet outside theme.py) and font sizes outside the type roles;
- layout numbers (setContentsMargins / setSpacing) that are not spacing tokens;
- drift between the phone page's palette and the studio's.

Usage: python .claude/skills/design-system/scripts/token_audit.py [--json] [--all]
       (--all also lists every layout number and artwork colour)
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
GUI = ROOT / "clipasso_studio" / "gui"
THEME = GUI / "theme.py"
PHONE = ROOT / "clipasso_studio" / "resources" / "phone"

# files whose colours belong to the sketch / the exported picture (ink, paper, brush, print), not to the interface
ARTWORK = {"export.py", "export_jobs.py", "paper.py", "brush.py", "print_layout.py", "print_dialog.py", "telegram.py",
           "phone_api.py", "strokes.py"}
HEX = re.compile(r"""(?<![\w&])#([0-9A-Fa-f]{8}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})\b""")
QCOLOR_RGB = re.compile(r"QColor\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*(\d+))?\s*\)")
QCOLOR_NAME = re.compile(r"""QColor\(\s*["'](white|black|red|green|blue|gray|grey|transparent)["']\s*\)""")
# a line about the sketch's own colours (export stroke / background, colour pickers, paper) in an interface file
ARTWORK_LINE = re.compile(r"export_|stroke|ColorButton|svg|paper|\bink\b|lightness\(|qlineargradient")
NEUTRAL = {"#FFFFFF", "#000000"}
FONT_PX = re.compile(r"font-size:\s*(\d+)px|setPixelSize\((\d+)\)|setPointSize\(([\d.]+)\)")
LAYOUT_NUM = re.compile(r"\.(setContentsMargins|setSpacing)\(([^)]*)\)")


def norm(h: str) -> str:
    h = h.lstrip("#").upper()
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return "#" + h[:6]


def read_theme() -> dict:
    """Palettes, spacing tokens and the font sizes of the type roles, parsed from theme.py."""
    src = THEME.read_text(encoding="utf-8")
    tree = ast.parse(src)
    palettes: dict[str, dict[str, str]] = {}
    spacing: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and \
                getattr(node.value.func, "id", "") == "Palette":
            name = node.targets[0].id
            palettes[name] = {kw.arg: kw.value.value for kw in node.value.keywords
                              if isinstance(kw.value, ast.Constant) and kw.arg != "name"}
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Tuple) and \
                isinstance(node.value, ast.Tuple):
            for t, v in zip(node.targets[0].elts, node.value.elts):
                if isinstance(t, ast.Name) and t.id.startswith("SPACE_") and isinstance(v, ast.Constant):
                    spacing[t.id] = v.value
    sizes = sorted({int(m) for m in re.findall(r"font-size:\s*(\d+)px", src)})
    return {"palettes": palettes, "spacing": spacing, "font_sizes": sizes}


def token_index(palettes: dict) -> dict[str, list[str]]:
    idx: dict[str, list[str]] = {}
    for pal, tokens in palettes.items():
        for tok, value in tokens.items():
            if isinstance(value, str) and value.startswith("#"):
                idx.setdefault(norm(value), []).append(f"{pal}.{tok}")
    return idx


def scan_gui(theme: dict) -> dict:
    idx = token_index(theme["palettes"])
    allowed_space = set(theme["spacing"].values()) | {0, 20}  # (20: PAGE_MARGINS top/bottom)
    out = {"token_hex": [], "off_palette": [], "neutral": [], "artwork": [], "qcolor_literal": [], "inline_qss": [],
           "font_sizes": [], "layout_numbers": []}
    for path in sorted(GUI.rglob("*.py")):
        if path == THEME:
            continue
        rel = path.relative_to(ROOT).as_posix()
        art_file = path.name in ARTWORK
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("  #")[0]
            art = art_file or bool(ARTWORK_LINE.search(code))
            for m in HEX.finditer(code):
                value = norm(m.group(0))
                hit = {"file": rel, "line": no, "value": value, "code": line.strip()[:140]}
                if art:
                    out["artwork"].append(hit)
                elif value in NEUTRAL:
                    out["neutral"].append(hit)
                elif value in idx:
                    out["token_hex"].append({**hit, "tokens": idx[value]})
                else:
                    out["off_palette"].append(hit)
            for m in list(QCOLOR_RGB.finditer(code)) + list(QCOLOR_NAME.finditer(code)):
                if not art:
                    out["qcolor_literal"].append({"file": rel, "line": no, "value": m.group(0),
                                                  "code": line.strip()[:140]})
            if "setStyleSheet(" in code:
                out["inline_qss"].append({"file": rel, "line": no, "code": line.strip()[:140]})
            for m in FONT_PX.finditer(code):
                px = m.group(1) or m.group(2)
                size = m.group(0) if px is None else f"{px}px"
                if px is None or int(px) not in theme["font_sizes"]:
                    out["font_sizes"].append({"file": rel, "line": no, "value": size, "code": line.strip()[:140]})
            for m in LAYOUT_NUM.finditer(code):
                nums = [int(n) for n in re.findall(r"(?<![\w.])(\d+)(?![\w.])", m.group(2))]
                odd = [n for n in nums if n not in allowed_space]
                if odd:
                    out["layout_numbers"].append({"file": rel, "line": no, "values": odd, "code": line.strip()[:140]})
    return out


def read_phone_css() -> dict[str, dict[str, str]]:
    css = (PHONE / "phone.css").read_text(encoding="utf-8")
    blocks = {"light": "", "dark": ""}
    m = re.search(r":root\s*\{([^}]*)\}", css)
    blocks["light"] = m.group(1) if m else ""
    m = re.search(r"prefers-color-scheme:\s*dark\)\s*\{\s*:root[^{]*\{([^}]*)\}", css)
    blocks["dark"] = m.group(1) if m else ""
    out = {k: dict(re.findall(r"--([\w-]+):\s*([^;]+);", v)) for k, v in blocks.items()}
    out["dark"] = {**out["light"], **out["dark"]}  # (the dark block only overrides)
    return out


# which phone variable plays the role of which studio token
PHONE_TO_QT = {"bg": "bg", "card": "surface", "text": "text", "muted": "muted", "accent": "accent",
               "on-accent": "on_accent", "line": "border", "field": "surface2"}


def scan_phone(theme: dict) -> dict:
    css_vars = read_phone_css()
    pals = {"light": theme["palettes"].get("LIGHT", {}), "dark": theme["palettes"].get("DARK", {})}
    drift = []
    for mode in ("light", "dark"):
        for var, tok in PHONE_TO_QT.items():
            a, b = css_vars[mode].get(var), pals[mode].get(tok)
            if a and b and a.strip().startswith("#") and norm(a.strip()) != norm(b):
                drift.append({"mode": mode, "phone": f"--{var}", "phone_value": norm(a.strip()),
                              "studio": tok, "studio_value": norm(b)})
    literals = []
    for name in ("phone.css", "phone.js", "index.html", "login.html", "login.js"):
        path = PHONE / name
        if not path.exists():
            continue
        in_root = False
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if name == "phone.css" and (":root" in line or in_root):
                in_root = "}" not in line or ":root" in line and line.count("}") == 0
                continue
            for m in HEX.finditer(line):
                literals.append({"file": path.relative_to(ROOT).as_posix(), "line": no, "value": norm(m.group(0)),
                                 "code": line.strip()[:140]})
    return {"variables": css_vars, "drift": drift, "literals": literals}


def report(theme: dict, gui: dict, phone: dict, show_all: bool) -> str:
    lines = ["# Token audit – CLIPasso Studio", ""]
    p = theme["palettes"]
    lines.append(f"Tokens: {len(p.get('DARK', {}))} colours per theme (DARK, LIGHT) · spacing "
                 + ", ".join(f"{k}={v}" for k, v in theme["spacing"].items())
                 + f" · type sizes {theme['font_sizes']} px")
    lines.append("")

    def section(title, rows, fmt, hint=""):
        lines.append(f"## {title} ({len(rows)})")
        if hint:
            lines.append(hint)
        lines.extend(fmt(r) for r in rows)
        lines.append("")

    section("Hard-coded token values (wrong in the other theme)", gui["token_hex"],
            lambda r: f"- {r['file']}:{r['line']} {r['value']} = {', '.join(r['tokens'])} — `{r['code']}`",
            "Use `theme.current().<token>` (QSS: the stylesheet in theme.py) so it follows dark/light.")
    section("Off-palette interface colours", gui["off_palette"],
            lambda r: f"- {r['file']}:{r['line']} {r['value']} — `{r['code']}`",
            "Not a token in either theme: add a token or map it to an existing one.")
    section("QColor literals in interface code", gui["qcolor_literal"],
            lambda r: f"- {r['file']}:{r['line']} {r['value']} — `{r['code']}`",
            "Scrims/overlays (black/white with alpha) can be fine; text and icon colours should be tokens.")
    section("Inline style sheets (outside theme.py)", gui["inline_qss"],
            lambda r: f"- {r['file']}:{r['line']} `{r['code']}`",
            "Prefer an objectName / dynamic property styled in theme.stylesheet(); inline QSS does not re-theme "
            "unless the widget rebuilds it.")
    section("Font sizes outside the type roles", gui["font_sizes"],
            lambda r: f"- {r['file']}:{r['line']} {r['value']} — `{r['code']}`",
            "Use a label role (title, h2, h3, muted, faint, stat, mono, badge) from theme.py.")
    section("Pure white / black in interface code", gui["neutral"],
            lambda r: f"- {r['file']}:{r['line']} {r['value']} — `{r['code']}`",
            "Fine on a fixed dark scrim or the white sketch paper; on a themed surface use a token (on_accent, "
            "paper, ink, text).")
    rows = gui["layout_numbers"]
    counts: dict[int, int] = {}
    for r in rows:
        for v in r["values"]:
            counts[v] = counts.get(v, 0) + 1
    lines.append(f"## Layout numbers that are not spacing tokens ({len(rows)} lines)")
    lines.append("Tokens: theme.SPACE_XS/S/M/L/XL = 4/8/12/16/24 (+20 for the page's top/bottom). A value used "
                 "often is an unofficial token: add it to theme.py or snap it to the scale. Small optical offsets "
                 "inside one widget are often deliberate – judge.")
    lines.append("- by value: " + ", ".join(f"{v} px × {n}" for v, n in sorted(counts.items(), key=lambda t: -t[1])))
    files: dict[str, int] = {}
    for r in rows:
        files[r["file"]] = files.get(r["file"], 0) + 1
    lines.append("- by file: " + ", ".join(f"{f.rsplit('/', 1)[-1]} × {n}"
                                         for f, n in sorted(files.items(), key=lambda t: -t[1])[:12]))
    if show_all:
        lines.extend(f"- {r['file']}:{r['line']} {r['values']} — `{r['code']}`" for r in rows)
    else:
        lines.append("  (--all lists every line)")
    lines.append("")
    section("Phone page vs studio palette", phone["drift"],
            lambda r: f"- {r['mode']}: {r['phone']} {r['phone_value']} ≠ {r['studio']} {r['studio_value']}",
            "The phone page has its own CSS variables. Differences are not always wrong (web vs desktop), but the "
            "accent and text colours should read as the same app.")
    section("Colour literals on the phone page (outside :root)", phone["literals"],
            lambda r: f"- {r['file']}:{r['line']} {r['value']} — `{r['code']}`")
    by_file: dict[str, int] = {}
    for r in gui["artwork"]:
        by_file[r["file"]] = by_file.get(r["file"], 0) + 1
    lines.append(f"## Artwork colours (sketch, paper, export – usually fine) ({len(gui['artwork'])})")
    if show_all:
        lines.extend(f"- {r['file']}:{r['line']} {r['value']} — `{r['code']}`" for r in gui["artwork"])
    else:
        lines.extend(f"- {f}: {n}" for f, n in sorted(by_file.items(), key=lambda t: -t[1]))
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):  # (Windows consoles default to a code page without ✅ “ ” →)
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--all", action="store_true", help="list every layout number and artwork colour too")
    args = ap.parse_args()
    if not THEME.exists():
        print(f"theme.py not found at {THEME} – run this inside the CLIPasso Studio repository", file=sys.stderr)
        return 2
    theme = read_theme()
    gui = scan_gui(theme)
    phone = scan_phone(theme)
    if args.json:
        print(json.dumps({"theme": theme, "gui": gui, "phone": phone}, indent=1, ensure_ascii=False))
    else:
        print(report(theme, gui, phone, args.all))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
