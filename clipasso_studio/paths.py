"""Filesystem locations for bundled resources, models and user data.

Works both from a source checkout and from a PyInstaller bundle (onefile or onedir).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from . import APP_ID

PACKAGE_DIR = Path(__file__).resolve().parent


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    """Root of the bundle (``sys._MEIPASS``) or the repository root when running from source."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return PACKAGE_DIR.parent


def resources_dir() -> Path:
    if is_frozen():
        return bundle_root() / "clipasso_studio" / "resources"
    return PACKAGE_DIR / "resources"


def resource(*parts: str) -> Path:
    return resources_dir().joinpath(*parts)


def bundled_models_dir() -> Path:
    """Models shipped with the app (read-only)."""
    override = os.environ.get("CLIPASSO_MODELS_DIR")
    if override:
        return Path(override)
    return bundle_root() / "models"


def user_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    path = base / APP_ID
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_models_dir() -> Path:
    return user_data_dir() / "models"


def read_settings_file() -> dict | None:
    """The stored app settings: settings.json, or its backup (settings.json.bak) when the file is
    missing or damaged (e.g. the computer lost power while it was written)."""
    main = app_settings_file()
    for path in (main, main.with_name(main.name + ".bak")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    return None


def _stored_setting(key: str):
    """A value of settings.json read directly (worker processes have no app settings object)."""
    data = read_settings_file()
    return data.get(key) if data else None


def downloaded_models_dir() -> Path:
    """Optional models downloaded on demand (writable): the folder chosen in the settings ("Model
    folder") or <app data>/models."""
    custom = os.environ.get("CLIPASSO_DOWNLOADS_DIR") or _stored_setting("models_dir")
    path = Path(custom) if custom else default_models_dir()
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:  # e.g. an external drive that is not connected: nothing is found there
        pass
    return path


def app_settings_file() -> Path:
    return user_data_dir() / "settings.json"


def default_output_dir() -> Path:
    docs = Path.home() / "Documents"
    if not docs.exists():
        docs = Path.home()
    return docs / "CLIPasso Studio"
