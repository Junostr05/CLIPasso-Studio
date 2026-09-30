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
