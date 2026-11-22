"""The rules "enabled when …" of the parameters are declarative (``clipasso_studio/conditions.py``), so they can be
exported as JSON for the Mac app – and they decide exactly what the lambdas they replaced decided."""

from __future__ import annotations

import json
import random

from clipasso_studio import settings_schema as schema


def _on(key):
    return lambda s: bool(s.get(key))


def _off(key):
    return lambda s: not s.get(key)


def _best_by(s):
    return int(s.get("num_sketches", 1) or 1) > 1 and not s.get("turbo")


def _clip_saliency(s):
    return bool(s.get("attention_init")) and s.get("saliency_model") == "clip"


def _clipasso_mask(s):
    return bool(s.get("mask_object")) or s.get("mask_object_attention", "auto") == "on"


def _scene_simplify(s):
    return int(s.get("simplicity_levels", 0)) > 0


def _diffusion_init(s):
    return bool(s.get("use_init_method")) and s.get("attn_model") == "diffusion"


def _gpu(s):
    return s.get("device") != "cpu"


# A frozen copy of the lambdas of settings_schema.py as they were in 4.2.4 (method, key) -> rule.
LEGACY = {
    ("clipasso", "num_paths"): _off("one_line"),
    ("clipasso", "best_by"): _best_by,
    ("clipasso", "mask_model"): _clipasso_mask,
    ("clipasso", "frame_object"): _on("mask_object"),
    ("clipasso", "one_line_segments"): _on("one_line"),
    ("clipasso", "num_segments"): _off("one_line"),
    ("clipasso", "control_points_per_seg"): _off("one_line"),
    ("clipasso", "saliency_model"): _on("attention_init"),
    ("clipasso", "saliency_clip_model"): _clip_saliency,
    ("clipasso", "xdog_intersec"): _clip_saliency,
    ("clipasso", "mask_object_attention"): _on("attention_init"),
    ("clipasso", "softmax_temp"): _clip_saliency,
    ("clipasso", "clip_conv_loss_type"): _on("clip_conv_loss"),
    ("clipasso", "clip_conv_layer_weights"): _on("clip_conv_loss"),
    ("clipasso", "clip_fc_loss_weight"): _on("clip_conv_loss"),
    ("clipasso", "semantic_model"):
        lambda s: bool(s.get("clip_conv_loss")) and float(s.get("clip_fc_loss_weight") or 0) > 0,
    ("clipasso", "clip_weight"): _on("train_with_clip"),
    ("clipasso", "start_clip"): _on("train_with_clip"),
    ("clipasso", "include_target_in_aug"): _on("train_with_clip"),
    ("clipasso", "perceptual_weight"): lambda s: s.get("percep_loss", "none") != "none",
    ("clipasso", "force_sparse"): _off("one_line"),
    ("clipasso", "color_lr"): _on("force_sparse"),
    ("clipasso", "color_vars_threshold"): _on("force_sparse"),
    ("clipasso", "num_stages"): _off("one_line"),
    ("clipasso", "noise_thresh"): lambda s: "noise" in str(s.get("augemntations", "")),
    ("clipasso", "gpunum"): _gpu,
    ("swiftsketch", "best_by"): _best_by,
    ("swiftsketch", "mask_model"): _on("mask_object"),
    ("swiftsketch", "frame_object"): _on("mask_object"),
    ("swiftsketch", "gpunum"): _gpu,
    ("controlsketch", "best_by"): _best_by,
    ("controlsketch", "mask_model"): _on("mask_object"),
    ("controlsketch", "object_size_ratio"): _on("mask_object"),
    ("controlsketch", "attn_model"): _on("use_init_method"),
    ("controlsketch", "object_name"): _diffusion_init,
    ("controlsketch", "sdxl_place"): _diffusion_init,
    ("controlsketch", "gpunum"): _gpu,
    ("scenesketch", "simplicity_pick"): _scene_simplify,
    ("scenesketch", "object_num_strokes"): _on("split_scene"),
    ("scenesketch", "mask_model"): _on("split_scene"),
    ("scenesketch", "resize_obj"): _on("split_scene"),
    ("scenesketch", "object_num_iter"): _on("split_scene"),
    ("scenesketch", "simplify_num_iter"): _scene_simplify,
    ("scenesketch", "background_divs"): _scene_simplify,
    ("scenesketch", "object_divs"): lambda s: _scene_simplify(s) and bool(s.get("split_scene")),
    ("scenesketch", "width_loss_weight"): _scene_simplify,
    ("scenesketch", "width_lr"): _scene_simplify,
    ("scenesketch", "gumbel_temp"): _scene_simplify,
    ("scenesketch", "saliency_model"): _on("attention_init"),
    ("scenesketch", "saliency_clip_model"): _clip_saliency,
    ("scenesketch", "xdog_intersec"): _clip_saliency,
    ("scenesketch", "softmax_temp"): _clip_saliency,
    ("scenesketch", "mask_object_attention"): lambda s: bool(s.get("attention_init")) and bool(s.get("split_scene")),
    ("scenesketch", "gpunum"): _gpu,
}

_MISSING = object()  # the key is not in the settings at all (the rules' defaults count then)

# every value a rule could look at; with _MISSING, None, 0 and the empty text for the edge cases
DRIVERS = {
    "one_line": (True, False, _MISSING),
    "num_sketches": (0, 1, 2, 5, None, _MISSING),
    "turbo": (True, False, _MISSING),
    "mask_object": (True, False, _MISSING),
    "mask_object_attention": ("auto", "on", "off", True, False, _MISSING),
    "attention_init": (True, False, _MISSING),
    "saliency_model": ("clip", "dino", _MISSING),
    "clip_conv_loss": (True, False, _MISSING),
    "clip_fc_loss_weight": (0, 0.0, 0.1, 1.0, None, _MISSING),
    "train_with_clip": (True, False, _MISSING),
    "percep_loss": ("none", "L2", "LPIPS", _MISSING),
    "force_sparse": (True, False, _MISSING),
    "augemntations": ("affine", "noise", "affine_noise", "none", "", _MISSING),
    "device": ("auto", "cpu", "cuda", _MISSING),
    "use_init_method": (True, False, _MISSING),
    "attn_model": ("clip", "diffusion", _MISSING),
    "split_scene": (True, False, _MISSING),
    "simplicity_levels": (0, 1, 4, 8, _MISSING),
}

SAMPLES = 20_000  # per method. Every rule reads at most three of the keys above, with at most six values each:
# at most 216 combinations, each drawn with a chance of at least 1/216 – (1 - 1/216) ** 20000 ≈ 1e-40 that one is missed


def _samples(method: str):
    rng = random.Random(0)
    base = schema.default_settings(method)
    yield dict(base)
    for _ in range(SAMPLES):
        s = dict(base)
        for key, values in DRIVERS.items():
            value = rng.choice(values)
            if value is _MISSING:
                s.pop(key, None)
            else:
                s[key] = value
        yield s


def test_conditions_match_the_legacy_lambdas():
    for method in schema.METHODS:
        params = schema.params_for(method)
        assert {k for m, k in LEGACY if m == method} == {p.key for p in params if p.enabled_if is not None}, method
        for s in _samples(method):
            for p in params:
                old = LEGACY.get((method, p.key))
                if old is not None:
                    assert p.enabled_if(s) == old(s), (method, p.key, s)


def test_every_condition_is_json():
    for method in schema.METHODS:
        for p in schema.params_for(method):
            if p.enabled_if is not None:
                data = p.enabled_if.to_json()
                assert json.loads(json.dumps(data)) == data, (method, p.key)


def test_condition_json_shapes():
    rule = schema.param("clipasso", "saliency_clip_model").enabled_if.to_json()
    assert rule == {"op": "all", "of": [{"op": "on", "key": "attention_init"},
                                        {"op": "eq", "key": "saliency_model", "value": "clip"}]}
    assert schema.param("clipasso", "mask_model").enabled_if.to_json() == {
        "op": "any", "of": [{"op": "on", "key": "mask_object"},
                            {"op": "eq", "key": "mask_object_attention", "value": "on", "default": "auto"}]}
    assert schema.param("clipasso", "noise_thresh").enabled_if.to_json() == {
        "op": "has", "key": "augemntations", "value": "noise"}
    assert schema.param("scenesketch", "simplicity_pick").enabled_if.to_json() == {
        "op": "gt", "key": "simplicity_levels", "value": 0}
    assert schema.param("swiftsketch", "gpunum").enabled_if.to_json() == {"op": "ne", "key": "device", "value": "cpu"}
    assert schema.param("clipasso", "num_paths").enabled_if.to_json() == {"op": "off", "key": "one_line"}
