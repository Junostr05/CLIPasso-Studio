"""CLIPasso (Vinker et al., SIGGRAPH 2022) – the optimisation in :mod:`..pipeline`."""

from __future__ import annotations

from ... import settings_schema as schema
from .. import model_store


def run_single(settings, target, run_dir, seed, reporter=None, control=None, device=None):
    from .. import pipeline

    return pipeline.run_single(settings, target, run_dir, seed, reporter, control, device)


def required_models(settings: dict) -> list[str]:
    s = schema.normalize({**settings, "method": "clipasso"})
    needed = {model_store.clip_key(s["clip_model_name"]), "u2net", model_store.clip_key("ViT-B/32")}
    if s["attention_init"]:
        needed.add(model_store.clip_key(s["saliency_clip_model"]) if s["saliency_model"] == "clip" else "dino")
    if s["percep_loss"] == "LPIPS":
        needed.add("vgg16")
    return sorted(needed)
