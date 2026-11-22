"""The "read me first" of the Mac disk image, in German and English, from the app's texts (ui.mac.dmg_*).

    python macos/scripts/dmg_readme.py I18N_DIR OUT_DIR   → writes OUT_DIR/"<German title> – <English title>.txt"
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

KEYS = ("ui.mac.dmg_needs", "ui.mac.dmg_install", "ui.mac.dmg_unsigned", "ui.mac.dmg_step_open",
        "ui.mac.dmg_step_settings", "ui.mac.dmg_step_again", "ui.mac.dmg_models", "ui.mac.dmg_update")


def section(texts: dict) -> str:
    title = texts["ui.mac.dmg_title"]
    lines = [title, "=" * len(title), ""]
    for key in KEYS:
        lines.append(texts[key])
        if key in ("ui.mac.dmg_needs", "ui.mac.dmg_install", "ui.mac.dmg_step_again", "ui.mac.dmg_models"):
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def readme(i18n: Path) -> tuple[str, str]:
    de, en = (json.loads((i18n / f"{code}.json").read_text(encoding="utf-8")) for code in ("de", "en"))
    name = f"{de['ui.mac.dmg_file']} – {en['ui.mac.dmg_file']}.txt"
    return name, section(de) + "\n\n" + section(en)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    name, text = readme(Path(argv[0]))
    out = Path(argv[1]) / name
    out.write_text(text, encoding="utf-8", newline="\n")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
