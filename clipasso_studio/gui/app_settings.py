"""Persistent application preferences (language, theme, folders, last parameters …)."""

from __future__ import annotations

import json
from typing import Any

from .. import paths

DEFAULTS: dict[str, Any] = {
    "language": "de",
    "theme": "dark",
    "output_dir": str(paths.default_output_dir()),
    "keep_awake": True,
    "notify": True,
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
                self.data.update(stored)
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
