"""Which downloadable models a method needs for its settings – without importing PyTorch (the GUI asks
this all the time, e.g. for the "missing models" banner and the method cards)."""

from __future__ import annotations

from ... import settings_schema as schema
from .. import model_store

SWIFT_DIFFUSION_KEY = "swiftsketch:diffusion"
SWIFT_REFINE_KEY = "swiftsketch:refine"
# ControlNet conditions that need a detector network to compute the condition image
DETECTOR_MODELS = {"depth": "dpt-hybrid", "normal": "dpt-hybrid", "hed": "hed", "scribble": "hed", "seg": "upernet",
                   "canny": None}


def clipasso(settings: dict) -> list[str]:
    s = schema.normalize({**settings, "method": "clipasso"})
    needed = {model_store.clip_key(s["clip_model_name"]), "u2net", model_store.clip_key("ViT-B/32")}
    if s["attention_init"]:
        needed.add(model_store.clip_key(s["saliency_clip_model"]) if s["saliency_model"] == "clip" else "dino")
    if schema.clipasso_uses_mask(s):
        needed.add(s["mask_model"])
    if s["percep_loss"] == "LPIPS":
        needed.add("vgg16")
    return sorted(needed)


def swiftsketch(settings: dict) -> list[str]:
    s = schema.normalize({**settings, "method": "swiftsketch"})
    needed = {SWIFT_DIFFUSION_KEY, model_store.clip_key("RN101"), model_store.clip_key("ViT-B/32")}
    if s["use_refine"]:
        needed.add(SWIFT_REFINE_KEY)
    if s["mask_object"]:
        needed.add(s["mask_model"])
    return sorted(needed)


def controlsketch_uses_sdxl(s: dict) -> bool:
    return bool(s["use_init_method"]) and s["attn_model"] == "diffusion" and bool(schema.text_value(s["object_name"]))


def controlsketch(settings: dict) -> list[str]:
    s = schema.normalize({**settings, "method": "controlsketch"})
    needed = {"sd15", f"controlnet:{s['condition']}", model_store.clip_key("ViT-B/32")}
    if s["mask_object"]:
        needed.add(s["mask_model"])
    if DETECTOR_MODELS.get(s["condition"]):
        needed.add(DETECTOR_MODELS[s["condition"]])
    if not schema.text_value(s["caption"]):
        needed.add("blip")
    if controlsketch_uses_sdxl(s):
        needed.add("sdxl")
    if schema.turbo(s):
        needed.add("taesd")
    return sorted(needed)


def scenesketch(settings: dict) -> list[str]:
    s = schema.normalize({**settings, "method": "scenesketch"})
    needed = {model_store.clip_key("ViT-B/32")}
    if s["split_scene"]:
        needed.update(("lama", s["mask_model"]))
    if s["attention_init"]:
        if s["saliency_model"] == "dino":
            needed.add("dino")
        else:
            needed.add(model_store.clip_key(s["saliency_clip_model"]))
    return sorted(needed)


BY_METHOD = {"clipasso": clipasso, "swiftsketch": swiftsketch, "controlsketch": controlsketch,
             "scenesketch": scenesketch}
