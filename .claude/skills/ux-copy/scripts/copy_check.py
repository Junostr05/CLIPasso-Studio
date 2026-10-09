"""Checks the interface text of CLIPasso Studio (resources/i18n/en.json and de.json) against the code and the
house style.

Reports:
- keys the code asks for that do not exist (the user would see the raw key, e.g. "ui.foo.bar");
- keys missing in one language, and {placeholders} that differ between the languages;
- texts that are the same in English and German (often not translated yet);
- house-style slips: straight quotes, "...", " - " for a dash, "->", double spaces, stray spaces; German: „…“ quotes
  and the informal "du" (formal Sie/Ihr in the middle of a sentence is flagged);
- German labels much longer than the English ones (risk of clipping in buttons and tabs);
- terminology: how often each word of a group of synonyms is used (photo / image / picture …);
- with --unused: keys no code seems to use (dynamic keys make this a hint, not a verdict).

Usage: python .claude/skills/ux-copy/scripts/copy_check.py [--unused] [--grep REGEX] [--key PREFIX]
       --grep REGEX  show every text (both languages) that matches, to check how a term is used
       --key PREFIX  show the texts of every key that starts with PREFIX
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
PKG = ROOT / "clipasso_studio"
I18N = PKG / "resources" / "i18n"
PHONE = PKG / "resources" / "phone"
PHONE_PREFIX = "ui.phone.page."
KEY = re.compile(r"""["']((?:ui|param|group|nav|method)\.[A-Za-z0-9_.]+)["']""")
FPREFIX = re.compile(r"""\bf["']((?:ui|param|group|nav|method)\.[A-Za-z0-9_.]*)\{""")
PLACEHOLDER = re.compile(r"\{(\w*)\}")
# groups of words that name the same thing – a group where several are used is worth a look
TERMS = {
    "the input": ["photo", "image", "picture"],
    "the output": ["sketch", "drawing", "result"],
    "removing": ["delete", "remove"],
    "the GPU": ["graphics card", "GPU"],
    "the CPU": ["processor", "CPU"],
    "start": ["start", "create", "run"],
}
STYLE_EN = [
    (r'"', "straight double quote – use “…”"),
    (r"\.\.\.", "three dots – use …"),
    (r" - ", "hyphen as a dash – use –"),
    (r"->|=>", "arrow – use →"),
    (r"  ", "double space"),
    (r"^\s|\s$", "leading/trailing space"),
    (r"!", "exclamation mark – the app's voice is calm"),
    (r"\b[Cc]lick here\b|\bAre you sure\b|\bsuccessfully\b", "filler phrase"),
]
STYLE_DE = [
    (r'"', "gerades Anführungszeichen – „…“ verwenden"),
    (r"\.\.\.", "drei Punkte – … verwenden"),
    (r" - ", "Bindestrich als Gedankenstrich – – verwenden"),
    (r"->|=>", "Pfeil – → verwenden"),
    (r"  ", "doppeltes Leerzeichen"),
    (r"^\s|\s$", "Leerzeichen am Anfang/Ende"),
    (r"[^.!?:–\s]\s+(Sie|Ihr|Ihre|Ihren|Ihrem|Ihrer|Ihnen)\b", "Sie-Form mitten im Satz – die App duzt"),
]


def load() -> tuple[dict, dict]:
    return (json.loads((I18N / "en.json").read_text(encoding="utf-8")),
            json.loads((I18N / "de.json").read_text(encoding="utf-8")))


def references() -> tuple[set[str], set[str], set[str]]:
    """(literal keys, dynamic prefixes, phone keys) found in the code."""
    literal: set[str] = set()
    prefixes: set[str] = {PHONE_PREFIX}
    for path in PKG.rglob("*.py"):
        src = path.read_text(encoding="utf-8")
        for m in KEY.finditer(src):
            key = m.group(1)
            (prefixes if key.endswith((".", "_")) else literal).add(key)
        prefixes.update(FPREFIX.findall(src))
    phone: set[str] = set()
    # gui/phone.py hands the page every ui.phone.page.* text plus a few from elsewhere (texts.update(name=tr(...)))
    phone_py = (PKG / "gui" / "phone.py").read_text(encoding="utf-8")
    provided = set(re.findall(r"\b(\w+)=tr\(", phone_py)) | set(re.findall(r"""texts\[["'](\w+)["']\]""", phone_py))
    for path in list(PHONE.glob("*.html")) + list(PHONE.glob("*.js")):
        src = path.read_text(encoding="utf-8")
        names = set(re.findall(r'data-t(?:-\w+)?="([a-z0-9_]+)"', src)) | set(re.findall(r"\bT\.([a-z0-9_]+)", src))
        phone.update(PHONE_PREFIX + k for k in names - provided)
    return literal, prefixes, phone


def style_hits(texts: dict, rules) -> list[tuple[str, str, str]]:
    out = []
    for key, text in texts.items():
        for pat, why in rules:
            if re.search(pat, text):
                out.append((key, why, text))
    return out


def word_count(texts: dict, word: str) -> int:
    pat = re.compile(rf"\b{re.escape(word)}", re.IGNORECASE)
    return sum(1 for t in texts.values() if pat.search(t))


def short(text: str, n: int = 110) -> str:
    text = text.replace("\n", " ⏎ ")
    return text if len(text) <= n else text[:n - 1] + "…"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):  # (Windows consoles default to a code page without ✅ “ ” →)
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--unused", action="store_true", help="also list keys no code seems to use")
    ap.add_argument("--grep", help="show the texts matching this regular expression")
    ap.add_argument("--key", help="show the texts of the keys starting with this prefix")
    args = ap.parse_args()
    en, de = load()

    if args.grep or args.key:
        pat = re.compile(args.grep, re.IGNORECASE) if args.grep else None
        for key in sorted(set(en) | set(de)):
            e, d = en.get(key, ""), de.get(key, "")
            if (args.key and key.startswith(args.key)) or (pat and (pat.search(e) or pat.search(d))):
                print(f"{key}\n  en: {e}\n  de: {d}")
        return 0

    out = [f"# Copy check – {len(en)} English / {len(de)} German texts", ""]

    def section(title, rows, hint=""):
        out.append(f"## {title} ({len(rows)})")
        if hint:
            out.append(hint)
        out.extend(rows)
        out.append("")

    literal, prefixes, phone = references()
    missing = sorted(k for k in literal | phone if k not in en)
    section("Keys the code uses that have no text", [f"- `{k}`" for k in missing],
            "The user sees the raw key. Add the key to en.json and de.json (same place in both files).")
    only_en = sorted(set(en) - set(de))
    only_de = sorted(set(de) - set(en))
    section("Keys in only one language",
            [f"- en only: `{k}`" for k in only_en] + [f"- de only: `{k}`" for k in only_de])
    ph = [f"- `{k}`: en {sorted(set(PLACEHOLDER.findall(en[k])))} · de {sorted(set(PLACEHOLDER.findall(de[k])))}"
          for k in en if k in de and set(PLACEHOLDER.findall(en[k])) != set(PLACEHOLDER.findall(de[k]))]
    section("Placeholders that differ", ph, "tr() falls back to the raw text when a placeholder is missing.")
    same = [f"- `{k}`: {short(en[k], 80)}" for k in en
            if k in de and en[k] == de[k] and re.search(r"[a-z]{4,}\s+[a-z]{3,}", en[k])]
    section("Same text in both languages", same,
            "Names (methods, models, formats) are fine; sentences are probably not translated.")
    section("English house style", [f"- `{k}` – {why}: {short(t)}" for k, why, t in style_hits(en, STYLE_EN)])
    section("German house style", [f"- `{k}` – {why}: {short(t)}" for k, why, t in style_hits(de, STYLE_DE)])

    long_rows = []
    for k, e in en.items():
        d = de.get(k, "")
        short_ui = k.endswith((".label", ".title")) or k.startswith(("nav.", "ui.mode.", "ui.tab")) or len(e) <= 24
        if short_ui and "\n" not in e and len(e) >= 6 and len(d) > 1.5 * len(e) and len(d) - len(e) >= 8:
            long_rows.append((len(d) / len(e), k, e, d))
    long_rows.sort(reverse=True)
    section("German much longer than English (short labels)",
            [f"- `{k}` ×{r:.1f}: “{e}” → „{d}“" for r, k, e, d in long_rows[:25]],
            "Check these in German screenshots (tools/screenshots.py --lang de): buttons, tabs, segmented controls.")

    term_rows = []
    for meaning, words in TERMS.items():
        counts = [(w, word_count(en, w)) for w in words]
        if sum(1 for _, n in counts if n) > 1:
            term_rows.append(f"- {meaning}: " + " · ".join(f"{w} {n}" for w, n in counts))
    section("Terminology (texts using each word)", term_rows,
            "Several words for one thing is fine only when they mean different things (say so in the glossary of the "
            "ux-copy skill); otherwise pick one. Look closer with --grep.")

    if args.unused:
        used = literal | phone
        unused = sorted(k for k in en if k not in used and not any(k.startswith(p) for p in prefixes))
        section("Keys no code seems to use", [f"- `{k}`: {short(en[k], 70)}" for k in unused],
                "Keys built at run time (tr(variable), error codes, schema names) show up here too – grep before "
                "deleting. Dynamic prefixes found: " + ", ".join(sorted(prefixes)[:30]))
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
