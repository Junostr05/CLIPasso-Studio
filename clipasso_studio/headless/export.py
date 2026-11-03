"""The parameter schema (settings_schema.py) and the model list (engine/model_store.py) as JSON for the Mac app, which
builds its sliders, rules and downloads from them – nothing of either is written down a second time in Swift."""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path

from .. import __version__, paths
from .. import settings_schema as schema
from ..engine import model_store
from ..gui import methods_ui  # (no Qt: names and icons of the methods)

FORMAT = 1
PRESET_ORDER = ("fast", "standard", "quality")
MAC_BUNDLED = ("blazeface",)  # the only model in the Mac app; the others are downloaded when first needed


@lru_cache(maxsize=1)
def _text_keys() -> frozenset[str]:
    return frozenset(json.loads(paths.resource("i18n", "en.json").read_text(encoding="utf-8")))


def _text_key(method: str, key: str, suffix: str) -> str | None:
    """The text of a parameter like ``param_text_key`` of the studio: the method's own, else the shared one."""
    for candidate in (f"param.{method}.{key}.{suffix}", f"param.{key}.{suffix}"):
        if candidate in _text_keys():
            return candidate
    return None


def _param(method: str, p: schema.Param) -> dict:
    text = {"label": _text_key(method, p.key, "label") or p.key, "choices": {}}
    help_key = _text_key(method, p.key, "help")
    if help_key:
        text["help"] = help_key
    for choice in p.choices:
        key = _text_key(method, p.key, f"choice.{choice}")
        if key:
            text["choices"][str(choice)] = key
    return {"key": p.key, "kind": p.kind, "default": copy.deepcopy(p.default), "group": p.group, "cli": p.cli,
            "min": p.minimum, "max": p.maximum, "step": p.step, "decimals": p.decimals, "choices": list(p.choices),
            "advanced": p.advanced, "hidden": p.hidden,
            "enabled_if": p.enabled_if.to_json() if p.enabled_if is not None else None, "text": text}


def _method(method: str) -> dict:
    groups = list(schema.METHOD_GROUPS[method])
    return {
        "name": methods_ui.name(method), "icon": methods_ui.ICONS[method],
        "text": {part: f"method.{method}.{part}" for part in ("tagline", "desc", "speed")},
        "groups": groups, "group_text": {g: f"group.{g}" for g in groups},
        "presets": copy.deepcopy(schema.METHOD_PRESETS[method]), "preset_order": list(PRESET_ORDER),
        "preset_text": {p: f"ui.preset.{p}" for p in PRESET_ORDER},
        "defaults": schema.default_settings(method),
        "params": [_param(method, p) for p in schema.params_for(method)],
    }


def export_schema() -> dict:
    return {"format": FORMAT, "app_version": __version__, "methods": list(schema.METHODS),
            "default_method": schema.DEFAULT_METHOD,
            "devices": list(schema.param(schema.DEFAULT_METHOD, "device").choices),
            "method": {m: _method(m) for m in schema.METHODS}}


def _extra(spec: model_store.ModelSpec) -> dict:
    out = {}
    for key, value in spec.extra.items():
        if key == "files":
            out["files"] = [{"remote": f.remote, "local": f.local, "size": f.size, "fp16": f.fp16, "prefix": f.prefix}
                            for f in value]
        else:
            out[key] = value
    return out


def export_models() -> dict:
    models = [{"key": s.key, "filename": s.filename, "urls": list(s.urls), "sha256": s.download_sha256,
               "download_size": s.download_size, "stored_size_mb": s.stored_size_mb, "kind": s.kind,
               "mac_bundled": s.key in MAC_BUNDLED, "extra": _extra(s)} for s in model_store.SPECS.values()]
    return {"format": FORMAT, "partial_dir": model_store.partial_dir(Path(".")).name, "models": models}


def write_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write("\n")
