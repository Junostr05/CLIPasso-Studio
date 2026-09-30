"""Tiny translation layer: ``tr("key", name=value)`` with live language switching."""

from __future__ import annotations

import json

from PySide6.QtCore import QLocale, QObject, Signal

from .. import paths

LANGUAGES = {"de": "Deutsch", "en": "English"}
AUTO = "auto"  # setting value: follow the display language of the operating system


def _system_ui_languages() -> list[str]:
    # on Windows the user's preferred display languages (e.g. ["de-DE", "en-US"]), elsewhere LANGUAGE/LANG
    return list(QLocale.system().uiLanguages())


def system_language() -> str:
    """The first supported language in the system's display language list, otherwise English."""
    for tag in _system_ui_languages():
        code = tag.replace("_", "-").split("-")[0].lower()
        if code in LANGUAGES:
            return code
    return "en"


def resolve(code: str | None) -> str:
    """Setting value (``"auto"``, ``"de"``, ``"en"``) → language code."""
    return code if code in LANGUAGES else system_language()


class _I18n(QObject):
    language_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.lang = "de"
        self._data: dict[str, dict[str, str]] = {}
        for code in LANGUAGES:
            self._data[code] = json.loads(paths.resource("i18n", f"{code}.json").read_text(encoding="utf-8"))

    def set_language(self, code: str | None) -> None:
        """Accepts a language code or ``"auto"`` (anything unknown counts as ``"auto"``)."""
        code = resolve(code)
        if code != self.lang:
            self.lang = code
            self.language_changed.emit(code)

    def tr(self, key: str, **fmt) -> str:
        text = self._data[self.lang].get(key)
        if text is None:
            text = self._data["en"].get(key, key)
        if fmt:
            try:
                text = text.format(**fmt)
            except (KeyError, IndexError, ValueError):
                pass
        return text

    def has(self, key: str) -> bool:
        return key in self._data[self.lang] or key in self._data["en"]


i18n = _I18n()


def tr(key: str, **fmt) -> str:
    return i18n.tr(key, **fmt)
