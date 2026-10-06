"""The user's own presets: named settings of a method, kept in the app settings ("user_presets") – the studio's
"My presets" menu and the phone page use them alike. A preset holds every setting of its method (files on the
computer, like a start SVG, are left out); choosing one of another method switches to that method."""

from __future__ import annotations

from .. import settings_schema as schema
from .app_settings import app_settings

KEY = "user_presets"
MAX_NAME = 40
MAX_PRESETS = 100


def clean_name(name) -> str:
    text = " ".join(str(name or "").split())[:MAX_NAME]
    if not text:
        raise ValueError("empty name")
    return text


def _clean_settings(settings: dict) -> dict:
    s = schema.normalize(settings)
    for p in schema.params_for(s["method"]):
        if p.kind == "path" or p.hidden:  # (hidden: the app's settings decide, not a preset)
            s[p.key] = p.default
    return s


def all_presets() -> list[dict]:
    """[{"name", "method", "settings"}] in the order they were made."""
    out = []
    for item in app_settings().get(KEY) or []:
        if not isinstance(item, dict) or not isinstance(item.get("settings"), dict) or \
                item.get("method") not in schema.METHODS:  # (e.g. of a newer version of the app)
            continue
        try:
            settings = _clean_settings({**item["settings"], "method": item.get("method")})
            out.append({"name": clean_name(item.get("name")), "method": settings["method"], "settings": settings})
        except (ValueError, TypeError):
            continue
    return out


def for_method(method: str) -> list[dict]:
    return [p for p in all_presets() if p["method"] == method]


def find(name: str, method: str) -> dict | None:
    return next((p for p in all_presets() if p["name"] == name and p["method"] == method), None)


def _store(presets: list[dict]) -> None:
    app_settings().set(KEY, [{"name": p["name"], "method": p["method"], "settings": p["settings"]}
                             for p in presets[-MAX_PRESETS:]])


def save(name: str, settings: dict) -> dict:
    """Keep ``settings`` under ``name`` (a preset of the same name and method is replaced in its place)."""
    name = clean_name(name)
    settings = _clean_settings(settings)
    entry = {"name": name, "method": settings["method"], "settings": settings}
    presets = all_presets()
    for i, p in enumerate(presets):
        if p["name"] == name and p["method"] == entry["method"]:
            presets[i] = entry
            break
    else:
        presets.append(entry)
    _store(presets)
    return entry


def delete(name: str, method: str) -> bool:
    presets = all_presets()
    kept = [p for p in presets if not (p["name"] == name and p["method"] == method)]
    if len(kept) == len(presets):
        return False
    _store(kept)
    return True


def matching(settings: dict) -> str:
    """The name of the own preset the settings are equal to ("" when none)."""
    try:
        s = _clean_settings(settings)
    except (ValueError, TypeError):
        return ""
    return next((p["name"] for p in for_method(s["method"]) if p["settings"] == s), "")
