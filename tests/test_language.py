import json

import pytest

from clipasso_studio.gui import app_settings as app_settings_mod
from clipasso_studio.gui import i18n as i18n_mod


@pytest.mark.parametrize("ui_languages, expected", [
    (["de-DE", "en-US"], "de"),
    (["de_AT"], "de"),
    (["en-GB", "de-DE"], "en"),
    (["fr-FR", "de-DE"], "de"),  # first supported language in the preference list
    (["fr-FR"], "en"),  # unsupported → English
    ([], "en"),
])
def test_system_language(monkeypatch, ui_languages, expected):
    monkeypatch.setattr(i18n_mod, "_system_ui_languages", lambda: ui_languages)
    assert i18n_mod.system_language() == expected
    assert i18n_mod.resolve("auto") == expected
    assert i18n_mod.resolve(None) == expected
    assert i18n_mod.resolve("en") == "en" and i18n_mod.resolve("de") == "de"


def test_set_language_auto(monkeypatch):
    i18n = i18n_mod.i18n
    before = i18n.lang
    try:
        monkeypatch.setattr(i18n_mod, "_system_ui_languages", lambda: ["en-US"])
        i18n.set_language("auto")
        assert i18n.lang == "en" and i18n.tr("ui.settings.language") == "Language"
        monkeypatch.setattr(i18n_mod, "_system_ui_languages", lambda: ["de-CH"])
        i18n.set_language("auto")
        assert i18n.lang == "de" and i18n.tr("ui.settings.language") == "Sprache"
    finally:
        i18n.set_language(before)


@pytest.mark.parametrize("stored, expected", [
    (None, "auto"),  # first start
    ({"language": "de", "theme": "light"}, "auto"),  # written by ≤ 2.0.0, where German was the fixed default
    ({"language": "en"}, "en"),
    ({"settings_version": 2, "language": "de"}, "de"),  # chosen in 2.0.1 or later
    ({"settings_version": 2, "language": "auto"}, "auto"),
])
def test_settings_language_default_and_migration(monkeypatch, tmp_path, stored, expected):
    path = tmp_path / "settings.json"
    if stored is not None:
        path.write_text(json.dumps(stored), encoding="utf-8")
    monkeypatch.setattr(app_settings_mod.paths, "app_settings_file", lambda: path)
    s = app_settings_mod.AppSettings()
    assert s.get("language") == expected
    s.set("notify", False)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["language"] == expected and saved["settings_version"] == app_settings_mod.SETTINGS_VERSION
    if stored and "theme" in stored:
        assert saved["theme"] == stored["theme"]


def test_every_error_and_hint_code_has_a_text():
    """Codes of engine hints ("log" events) and UserErrors have texts in both languages."""
    import json
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "clipasso_studio"
    texts = {lang: json.loads((root / "resources" / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))
             for lang in ("en", "de")}
    source = "\n".join(p.read_text(encoding="utf-8") for p in root.rglob("*.py"))
    errors = set(re.findall(r'UserError\(\s*"([a-z_]+)"', source))
    hints = set(re.findall(r'event\(\s*"log",.{0,300}?code="([a-z_]+)"', source, re.S))
    assert len(errors) >= 10 and len(hints) >= 7
    for lang, data in texts.items():
        for code in errors:
            assert f"ui.err.{code}" in data, (lang, code)
        for code in hints:
            assert f"ui.log.{code}" in data, (lang, code)


def test_error_text_is_translated(qapp):
    from clipasso_studio.engine.errors import UserError
    from clipasso_studio.gui import dialogs
    from clipasso_studio.gui.i18n import i18n

    before = i18n.lang
    try:
        i18n.set_language("de")
        text = dialogs.error_text(UserError("download_failed", "Could not download sdxl", model="sdxl",
                                            details="timeout"))
        assert "konnte nicht" in text and "timeout" in text and "sdxl" not in text.split("\n")[0].lower()
        assert dialogs.error_text(ValueError("plain")) == "plain"
    finally:
        i18n.set_language(before)


def test_the_glossary_words():
    """4.0: the user settled the words (.claude/skills/ux-copy/reference/voice.md) – the input is the *image*
    („Bild“; “photo” / „Foto“ only for taking one with the camera and for photographs in general), the thing in the
    queue is the *job* („Auftrag“, never „Job“), and Fast / Standard / Quality are „Voreinstellungen“ (never
    „Preset“)."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "clipasso_studio" / "resources" / "i18n"
    en = json.loads((root / "en.json").read_text(encoding="utf-8"))
    de = json.loads((root / "de.json").read_text(encoding="utf-8"))
    camera = {"ui.phone.page.camera", "ui.webcam.tip", "ui.webcam.title", "ui.webcam.shoot"}
    photographs = {"param.best_by.help"}  # (LAION's aesthetic score – “trained on photos”)
    assert [k for k, v in en.items() if re.search(r"\b[Pp]ictures?\b", v)] == []
    assert {k for k, v in en.items() if re.search(r"\b[Pp]hotos?\b", v)} <= camera | photographs
    assert {k for k, v in de.items() if "Foto" in v} <= camera | photographs
    assert [k for k, v in de.items() if re.search(r"Preset|\bJobs?\b", v)] == []
    assert de["ui.cancel_run"] == "Auftrag abbrechen" and de["ui.phone.page.my_presets"] == "Meine Voreinstellungen"
