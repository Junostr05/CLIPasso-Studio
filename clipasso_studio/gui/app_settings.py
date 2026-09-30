"""Persistent application preferences (language, theme, folders, last parameters …)."""

from __future__ import annotations

import json
from typing import Any

from .. import paths

# 2: "language" defaults to "auto" (2.0.1)
SETTINGS_VERSION = 2

DEFAULTS: dict[str, Any] = {
    "settings_version": SETTINGS_VERSION,
    "language": "auto",
    "theme": "dark",
    "output_dir": str(paths.default_output_dir()),
    "keep_awake": True,
    "notify": True,
    "check_updates": True,
    "ui_scale": 1.0,  # interface size (applied at the start via QT_SCALE_FACTOR)
    "skipped_version": "",
    "last_params": None,
    "last_preset": "standard",
    "last_image": "",
    "show_advanced": False,
    "geometry": None,
    "queue": [],
}


class AppSettings:
    def __init__(self):
        self._path = paths.app_settings_file()
        self.data = dict(DEFAULTS)
        try:
            stored = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                if not isinstance(stored.get("settings_version"), int) and stored.get("language") == "de":
                    # up to 2.0.0 German was the fixed default and got written to the file with every
                    # other setting, so a stored "de" was usually never chosen → follow the system language
                    stored["language"] = "auto"
                self.data.update(stored)
                self.data["settings_version"] = SETTINGS_VERSION
        except (OSError, ValueError):
            pass

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.save()

    def save(self) -> None:
        try:
            self._path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        except OSError:
            pass


_instance: AppSettings | None = None


def app_settings() -> AppSettings:
    global _instance
    if _instance is None:
        _instance = AppSettings()
    return _instance
