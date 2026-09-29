"""Every argument of the original CLIPasso scripts must be reachable in the app."""

import pytest

from clipasso_studio import cli
from clipasso_studio import settings_schema as schema

# Arguments of run_object_sketching.py and config.py in yael-vinker/CLIPasso (main branch).
ORIGINAL_RUN_OBJECT_SKETCHING = {
    "target_file": None, "num_strokes": 16, "num_iter": 2001, "fix_scale": 0, "mask_object": 0,
    "num_sketches": 3, "multiprocess": 0, "colab": None, "cpu": None, "display": None, "gpunum": 0,
}
ORIGINAL_CONFIG = {
    "target": None, "output_dir": None, "path_svg": "none", "use_gpu": 0, "seed": 0, "mask_object": 0,
    "fix_scale": 0, "display_logs": 0, "display": 0, "use_wandb": 0, "wandb_user": "yael-vinker",
    "wandb_name": "test", "wandb_project_name": "none", "num_iter": 500, "num_stages": 1, "lr_scheduler": 0,
    "lr": 1.0, "color_lr": 0.01, "color_vars_threshold": 0.0, "batch_size": 1, "save_interval": 10,
    "eval_interval": 10, "image_scale": 224, "num_paths": 16, "width": 1.5, "control_points_per_seg": 4,
    "num_segments": 1, "attention_init": 1, "saliency_model": "clip", "saliency_clip_model": "ViT-B/32",
    "xdog_intersec": 1, "mask_object_attention": 0, "softmax_temp": 0.3, "percep_loss": "none",
    "perceptual_weight": 0, "train_with_clip": 0, "clip_weight": 0, "start_clip": 0, "num_aug_clip": 4,
    "include_target_in_aug": 0, "augment_both": 1, "augemntations": "affine", "noise_thresh": 0.5,
    "aug_scale_min": 0.7, "force_sparse": 0, "clip_conv_loss": 1, "clip_conv_loss_type": "L2",
    "clip_conv_layer_weights": "0,0,1.0,1.0,0", "clip_model_name": "RN101", "clip_fc_loss_weight": 0.1,
    "clip_text_guide": 0, "text_target": "none",
}


@pytest.mark.parametrize("name,default", list({**ORIGINAL_CONFIG, **ORIGINAL_RUN_OBJECT_SKETCHING}.items()))
def test_every_original_argument_is_covered(name, default):
    by_cli = {p.cli: p for p in schema.PARAMS if p.cli}
    if name in schema.EXCLUDED_ORIGINAL_ARGS:
        return
    assert name in by_cli, f"original argument {name} has no setting"
    p = by_cli[name]
    if default is None or name in schema.DEFAULT_DEVIATIONS or name == "mask_object_attention":
        return
    value = p.default
    if p.kind == "bool":
        value = int(value)
    assert value == default, f"default of {name} differs: {value!r} != {default!r}"


def test_every_param_has_translations():
    import json

    from clipasso_studio import paths

    for lang in ("de", "en"):
        data = json.loads(paths.resource("i18n", f"{lang}.json").read_text(encoding="utf-8"))
        for p in schema.PARAMS:
            assert f"param.{p.key}.label" in data, (lang, p.key)
            assert f"param.{p.key}.help" in data, (lang, p.key)
        for g in schema.GROUPS:
            assert f"group.{g}" in data, (lang, g)


def test_cli_parses_original_command_line():
    ns = cli.build_parser().parse_args([
        "--target_file", "camel.png", "--num_strokes", "8", "--mask_object", "1", "--fix_scale", "1",
        "--num_sketches", "2", "-cpu", "--clip_conv_layer_weights", "0,0,1,1,0", "--augemntations",
        "affine_noise", "--lr", "0.5", "-colab"])
    s = cli.settings_from_args(ns)
    assert s["num_paths"] == 8
    assert s["mask_object"] is True and s["fix_scale"] is True
    assert s["num_sketches"] == 2
    assert s["device"] == "cpu"
    assert s["augemntations"] == "affine_noise"
    assert s["lr"] == 0.5


def test_cli_roundtrip_of_changed_settings():
    s = schema.default_settings()
    s.update({"num_paths": 32, "mask_object": True, "saliency_model": "dino", "clip_conv_loss_type": "Cos",
              "text_target": "a camel"})
    argv = ["--target_file", "x.png"] + schema.to_cli_args(s)
    s2 = cli.settings_from_args(cli.build_parser().parse_args(argv))
    assert s2 == schema.normalize(s)


def test_normalize_and_coerce():
    s = schema.normalize({"num_paths": "300", "width": "2.5", "mask_object": "1", "unknown": 3,
                          "clip_conv_layer_weights": "0; 0; 1; 1; 0", "augemntations": "noise,affine"})
    assert s["num_paths"] == 256  # clamped
    assert s["width"] == 2.5
    assert s["mask_object"] is True
    assert "unknown" not in s
    assert s["clip_conv_layer_weights"] == "0,0,1,1,0"
    assert s["augemntations"] == "affine_noise"
    with pytest.raises(ValueError):
        schema.normalize({"saliency_model": "foo"})
