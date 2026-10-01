"""Persistent application preferences (language, theme, folders, last parameters …)."""

from __future__ import annotations

import json
import os
import time
from typing import Any

from .. import paths

# 2: "language" defaults to "auto" (2.0.1)
SETTINGS_VERSION = 2

DEFAULTS: dict[str, Any] = {
    "tour_done": False,  # the first-start guide was shown
    "settings_version": SETTINGS_VERSION,
    "language": "auto",
    "theme": "dark",
    "output_dir": str(paths.default_output_dir()),
    "keep_awake": True,
    "notify": True,
    "check_updates": True,
    "ui_scale": 1.0,  # interface size (applied at the start via QT_SCALE_FACTOR)
    "keep_models_loaded": True,  # the worker stays open between jobs with its models (runner keep_warm)
    "parallel_sketches": "auto",  # "auto": the sketches of a job in parallel on a big CPU (runner.plan_workers)
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
        stored = paths.read_settings_file()  # falls back to the backup of a damaged file
        if stored is not None:
            if not isinstance(stored.get("settings_version"), int) and stored.get("language") == "de":
                # up to 2.0.0 German was the fixed default and got written to the file with every
                # other setting, so a stored "de" was usually never chosen → follow the system language
                stored["language"] = "auto"
            self.data.update(stored)
            self.data["settings_version"] = SETTINGS_VERSION
            if "tour_done" not in stored:  # used before the guide existed: only on request (About)
                self.data["tour_done"] = True
            self._backup()

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.save()

    def _backup(self) -> None:
        """The settings that loaded fine, as settings.json.bak (used if settings.json gets damaged)."""
        try:
            self._path.with_name(self._path.name + ".bak").write_text(json.dumps(self.data, indent=2),
                                                                       encoding="utf-8")
        except OSError:
            pass

    def save(self) -> None:
        """Write to a temporary file and replace settings.json with it: an interrupted write (crash,
        power loss) never leaves a half-written file, which would reset all settings and the queue."""
        tmp = self._path.with_name(self._path.name + ".tmp")
        try:
            tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        except OSError:
            return
        for attempt in range(5):
            try:
                os.replace(tmp, self._path)
                return
            except PermissionError:  # Windows: the file is open in another program for a moment
                time.sleep(0.05 * (attempt + 1))
            except OSError:
                break
        try:
            tmp.unlink()
        except OSError:
            pass


_instance: AppSettings | None = None


def app_settings() -> AppSettings:
    global _instance
    if _instance is None:
        _instance = AppSettings()
    return _instance
