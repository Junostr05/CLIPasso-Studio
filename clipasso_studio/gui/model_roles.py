"""The models the studio's settings choose, by category (3.7): the models page shows them for the method in the
studio and changes the choice there – the same settings as in the studio's parameters, both ways.

A *role* is a setting that picks a model (the mask network, the CLIP model of the shape loss, …) and the models
its current value needs. Without PyTorch (the GUI asks this on every change)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .. import settings_schema as schema
from ..engine import model_store
from ..engine.methods import requirements

# in this order on the page
CATEGORIES = ("mask", "shape", "semantic", "attention", "condition", "scoring")


@dataclass(frozen=True)
class Role:
    category: str
    key: str  # the setting that chooses
    models: Callable[[dict], list[str]]  # the models its current value needs (normalised settings)


def _clip(name: str) -> str:
    return model_store.clip_key(name)


def _saliency(s: dict) -> list[str]:
    return ["dino"] if s["saliency_model"] == "dino" else [_clip(s["saliency_clip_model"])]


def _semantic(s: dict) -> list[str]:
    return [requirements.SEMANTIC_KEYS.get(s["semantic_model"], _clip(s["clip_model_name"]))]


def _condition(s: dict) -> list[str]:
    detector = requirements.DETECTOR_MODELS.get(s["condition"])
    return [f"controlnet:{s['condition']}"] + ([detector] if detector else [])


_MASK = Role("mask", "mask_model", lambda s: [s["mask_model"]])
_SCORING = Role("scoring", "best_by", lambda s: [_clip("ViT-B/32")])
_ATTENTION = (Role("attention", "saliency_model", _saliency),
              Role("attention", "saliency_clip_model", lambda s: [_clip(s["saliency_clip_model"])]))

ROLES: dict[str, tuple[Role, ...]] = {
    "clipasso": (
        _MASK,
        Role("shape", "clip_model_name", lambda s: [_clip(s["clip_model_name"])]),
        Role("semantic", "semantic_model", _semantic),
        *_ATTENTION,
        _SCORING,
    ),
    "swiftsketch": (_MASK, _SCORING),
    "controlsketch": (
        _MASK,
        Role("attention", "attn_model", lambda s: ["sdxl"] if s["attn_model"] == "diffusion" else [_clip("ViT-B/32")]),
        Role("condition", "condition", _condition),
        _SCORING,
    ),
    "scenesketch": (_MASK, *_ATTENTION),
}


def experimental(model_key: str) -> bool:
    spec = model_store.SPECS.get(model_key)
    return bool(spec and spec.extra.get("experimental"))


def rows(method: str, settings: dict) -> list[dict]:
    """The roles of a method with the studio's settings, by category: {category, key, value, enabled, models,
    missing, experimental}."""
    s = schema.normalize({**settings, "method": method})
    out = []
    for role in ROLES[method]:
        param = schema.param(method, role.key)
        models = [k for k in role.models(s) if k in model_store.SPECS]
        out.append({"category": role.category, "key": role.key, "value": s[role.key],
                    "enabled": schema.is_enabled(param, s), "models": models,
                    "missing": [k for k in models if not model_store.is_available(k)],
                    "experimental": any(experimental(k) for k in models)})
    out.sort(key=lambda r: CATEGORIES.index(r["category"]))
    return out


def choice_models(method: str, key: str, value, settings: dict) -> list[str]:
    """The models a role would need with another value (the page marks experimental choices)."""
    role = next(r for r in ROLES[method] if r.key == key)
    s = schema.normalize({**settings, "method": method, key: value})
    return [k for k in role.models(s) if k in model_store.SPECS]


def in_use(method: str, settings: dict) -> set[str]:
    """Every model the studio's settings need (the page marks them in its list)."""
    return set(requirements.BY_METHOD[method](settings))
