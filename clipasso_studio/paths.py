"""Filesystem locations for bundled resources, models and user data.

Works both from a source checkout and from a PyInstaller bundle (onefile or onedir).
"""

from __future__ import annotations

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


def downloaded_models_dir() -> Path:
    """Optional models downloaded on demand (writable)."""
    path = user_data_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def app_settings_file() -> Path:
    return user_data_dir() / "settings.json"


def default_output_dir() -> Path:
    docs = Path.home() / "Documents"
    if not docs.exists():
        docs = Path.home()
    return docs / "CLIPasso Studio"
