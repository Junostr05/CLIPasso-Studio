"""The read me of the Mac disk image comes from the app's texts – in German and English, every step in both."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
I18N = ROOT / "clipasso_studio" / "resources" / "i18n"


def _module():
    spec = importlib.util.spec_from_file_location("dmg_readme", ROOT / "macos" / "scripts" / "dmg_readme.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_readme_has_every_text_in_both_languages(tmp_path):
    dmg = _module()
    assert dmg.main([str(I18N), str(tmp_path)]) == 0
    (out,) = tmp_path.iterdir()
    assert out.name == "Bitte zuerst lesen – Read me first.txt"
    text = out.read_text(encoding="utf-8")
    for code in ("de", "en"):
        texts = json.loads((I18N / f"{code}.json").read_text(encoding="utf-8"))
        for key in ("ui.mac.dmg_title", *dmg.KEYS):
            assert texts[key] in text, (code, key)
    assert text.index("vor dem ersten Start") < text.index("before the first start")  # German first
    assert "Dennoch öffnen" in text and "Open Anyway" in text  # the button macOS shows
    assert "\r" not in text


def test_usage_without_arguments(capsys):
    assert _module().main([]) == 2
    assert "dmg_readme.py" in capsys.readouterr().err
