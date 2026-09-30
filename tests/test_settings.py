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


# Arguments of SwiftSketch/generate.py (generate_args: wandb + base + generate options).
ORIGINAL_SWIFT_GENERATE = {
    "use_wandb": 0, "wandb_user": "", "wandb_name": "test", "wandb_project_name": "SwiftSketch",
    "experiment_name": "SwiftSketch", "title": "", "cuda": True, "device": 0, "seed": 20, "batch_size": 32,
    "model_path": None, "input_data": None, "output_dir": "", "generate_batch_size": 24, "use_refine": 1,
    "fix_scale": 0, "guidance_param": 2.5, "save_final_sketch_in_dict": 1, "save_svg": 1,
    "save_diffusion_sketch_in_dict": 0, "refine_model_path": "",
}
# Arguments of ControlSketch/config.py.
ORIGINAL_CONTROL_CONFIG = {
    "target": None, "save_svg_in_dict": 1, "output_dir": "", "use_cpu": 0, "seed": 0, "fix_scale": 0,
    "sort_final_sketch": 1, "use_wandb": 0, "wandb_user": "", "wandb_name": "defualt", "wandb_project_name": "",
    "experiment_name": "", "num_iter": 2000, "lr_scheduler": 0, "lr": 0.8, "batch_size": 1, "save_interval": 100,
    "object_size_ratio": 0.75, "render_size": 512, "output_svg_size": 512, "num_strokes": 32, "width": 2.5,
    "control_points_per_seg": 4, "num_segments": 1, "use_init_method": 1, "object_name": "",
    "attn_model": "diffusion", "diffusion_model": "runwayml/stable-diffusion-v1-5", "diffusion_timesteps": 1000,
    "diffusion_guidance_scale": 100, "caption": "", "conditioning_scale": 0.15, "condition": "depth",
}

# Arguments of SceneSketch (yael-vinker/SceneSketch): config.py + run_sketch.py + the driver scripts, with the
# values the scripts actually use (run_sketch.py / generate_fidelity_levels.py / run_ratio.py / run_*.py).
ORIGINAL_SCENE = {
    # config.py
    "target": None, "output_dir": None, "path_svg": "none", "use_gpu": 0, "seed": 0, "mask_object": 0,
    "resize_obj": 0, "fix_scale": 0, "display_logs": 0, "display": 0, "use_wandb": 0, "wandb_user": "",
    "wandb_name": "test", "wandb_project_name": "none", "num_iter": 500, "num_stages": 1, "lr_scheduler": 0,
    "lr": 1.0, "color_lr": 0.01, "width_lr": 1e-4, "color_vars_threshold": 0.0, "batch_size": 1, "save_interval": 10,
    "eval_interval": 20, "min_eval_iter": 100, "image_scale": 224, "loss_mask": "none", "dilated_mask": 0,
    "mask_cls": "none", "mask_attention": 0, "num_paths": 16, "width": 1.5, "control_points_per_seg": 4,
    "num_segments": 1, "attention_init": 1, "saliency_model": "clip", "saliency_clip_model": "ViT-B/32",
    "xdog_intersec": 1, "mask_object_attention": 0, "softmax_temp": 0.3, "mlp_train": 0, "width_optim": 0,
    "mlp_width_weights_path": "none", "mlp_points_weights_path": "none", "switch_loss": 0, "gumbel_temp": 0.2,
    "width_loss_weight": "0", "width_loss_type": "L1", "optimize_points": 1, "load_points_opt_weights": 0,
    "gradnorm": 0, "width_weights_lst": "", "ratio_loss": 0, "percep_loss": "none", "perceptual_weight": 0,
    "train_with_clip": 0, "clip_weight": 0, "start_clip": 0, "num_aug_clip": 4, "include_target_in_aug": 0,
    "augment_both": 1, "augemntations": "affine", "noise_thresh": 0.5, "aug_scale_min": 0.7, "force_sparse": 0,
    "clip_conv_loss": 1, "clip_mask_loss": 0, "clip_conv_loss_type": "L2", "clip_conv_layer_weights": "0,0,1.0,1.0,0",
    "clip_model_name": "RN101", "clip_fc_loss_weight": 0.1, "clip_text_guide": 0, "text_target": "none",
    # run_sketch.py (only the ones config.py does not have)
    "target_file": None, "output_pref": None, "num_strokes": 64, "test_name": None, "num_sketches": 1,
    "multiprocess": 1, "colab": None, "cpu": None,
    # scripts
    "im_name": None, "layers": "2,8,11", "divs": None, "layer_opt": None, "object_or_background": None,
    "min_div": None, "run_u2net": None, "top_path": None,
}
# the values the scripts pass instead of the config.py defaults
SCENE_SCRIPT_VALUES = {"num_strokes": 64, "num_sketches": 2, "num_iter": 1501, "lr": 1e-4, "width_lr": 5e-5,
                       "save_interval": 100, "eval_interval": 50, "min_eval_iter": 400, "resize_obj": 1,
                       "width_loss_weight": 1.0}


@pytest.mark.parametrize("name,default", list(ORIGINAL_SCENE.items()))
def test_every_scenesketch_argument_is_covered(name, default):
    if name in schema.SCENE_EXCLUDED_ARGS:
        return
    by_cli = {p.cli: p for p in schema.SCENE_PARAMS if p.cli}
    assert name in by_cli, f"scenesketch: original argument {name} has no setting"
    p = by_cli[name]
    if name in schema.SCENE_DEFAULT_DEVIATIONS:
        default = SCENE_SCRIPT_VALUES[name]
    value = int(p.default) if p.kind == "bool" else p.default
    if name == "layers":
        value, default = value.split("_"), default.split(",")
    assert value == default, f"scenesketch: default of {name} differs: {value!r} != {default!r}"
    assert set(schema.SCENE_DEFAULT_DEVIATIONS) <= set(SCENE_SCRIPT_VALUES)


def test_scenesketch_cells_and_iterations():
    s = schema.default_settings("scenesketch")
    assert schema.scene_layers(s) == [2, 8, 11]
    cells = schema.scene_cells(s)
    assert len(cells) == 3 * 9 and cells[:2] == [200, 201] and cells[-1] == 1108
    # fidelity: background 1501 + object 1000 (layer 2: 60 %) per seed, levels: 401 per part and seed
    assert schema.scene_cell_iterations(s, 800) == 2 * (1501 + 1000)
    assert schema.scene_cell_iterations(s, 200) == 2 * (1501 + 600)
    assert schema.scene_cell_iterations(s, 803) == 2 * 2 * 401
    s2 = schema.normalize({**s, "split_scene": False, "layers": "11,4", "simplicity_levels": 0})
    assert schema.scene_cells(s2) == [400, 1100] and s2["layers"] == "4_11"
    assert schema.scene_cell_iterations(s2, 400) == 2 * 1501
    assert schema.parse_scene_divs("8:0.7, 11:bad", schema.SCENE_BACKGROUND_DIVS)[8] == 0.7
    assert schema.parse_scene_divs("none", schema.SCENE_OBJECT_DIVS) == schema.SCENE_OBJECT_DIVS
    from clipasso_studio.engine import jobs

    assert jobs.job_seeds(s2) == [400, 1100]
    assert jobs.run_name_for("x/ballerina.png", s2, 1103) == "ballerina_scenesketch_L11_level3"


def test_cli_parses_original_scenesketch_command_line():
    argv = ["--method", "scenesketch", "--im_name", "ballerina.png", "--layers", "2,8", "--num_paths", "32",
            "--min_div", "0.5", "--object_or_background", "background", "--resize_obj", "0", "--width_lr", "0.001",
            "-cpu"]
    s = cli.settings_from_args(cli.build_parser("scenesketch").parse_args(argv))
    assert s["method"] == "scenesketch" and s["layers"] == "2_8" and s["num_strokes"] == 32
    assert s["resize_obj"] is False and s["width_lr"] == 0.001 and s["device"] == "cpu"
    s = cli.settings_from_args(cli.build_parser("scenesketch").parse_args(
        ["--method", "scenesketch", "--target", "x.png", "--layer_opt", "11"]))
    assert s["layers"] == "11"


def _check_original_argument(method, excluded, deviations, name, default):
    params = schema.params_for(method)
    by_cli = {p.cli: p for p in params if p.cli}
    if name in excluded:
        return
    assert name in by_cli, f"{method}: original argument {name} has no setting"
    p = by_cli[name]
    if default is None or name in deviations:
        return
    value = p.default
    if p.kind == "bool":
        value = int(value)
    if p.kind == "text":
        value, default = schema.text_value(value), schema.text_value(default)
    assert value == default, f"{method}: default of {name} differs: {value!r} != {default!r}"


@pytest.mark.parametrize("name,default", list(ORIGINAL_SWIFT_GENERATE.items()))
def test_every_swiftsketch_argument_is_covered(name, default):
    _check_original_argument("swiftsketch", schema.SWIFT_EXCLUDED_ARGS, {}, name, default)


@pytest.mark.parametrize("name,default", list(ORIGINAL_CONTROL_CONFIG.items()))
def test_every_controlsketch_argument_is_covered(name, default):
    _check_original_argument("controlsketch", schema.CONTROL_EXCLUDED_ARGS, schema.CONTROL_DEFAULT_DEVIATIONS,
                             name, default)


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

    def has(data, method, key, suffix):
        return f"param.{method}.{key}.{suffix}" in data or f"param.{key}.{suffix}" in data

    langs = {}
    for lang in ("de", "en"):
        data = json.loads(paths.resource("i18n", f"{lang}.json").read_text(encoding="utf-8"))
        langs[lang] = data
        for method in schema.METHODS:
            for p in schema.params_for(method):
                assert has(data, method, p.key, "label"), (lang, method, p.key)
                assert has(data, method, p.key, "help"), (lang, method, p.key)
                if p.kind == "choice" and p.key not in ("control_points_per_seg", "clip_model_name",
                                                          "saliency_clip_model", "device", "gpunum"):
                    for c in p.choices:
                        assert has(data, method, p.key, f"choice.{c}") or p.key in (
                            "clip_conv_loss_type", "percep_loss", "saliency_model"), (lang, method, p.key, c)
            for g in schema.METHOD_GROUPS[method]:
                assert f"group.{g}" in data, (lang, g)
            for key in ("tagline", "speed", "desc"):
                assert f"method.{method}.{key}" in data, (lang, method, key)
    assert set(langs["de"]) == set(langs["en"]), set(langs["de"]) ^ set(langs["en"])


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


def test_default_settings_per_method():
    for method in schema.METHODS:
        s = schema.default_settings(method)
        assert s["method"] == method
        n = schema.normalize(s)
        assert schema.normalize(n) == n and n["method"] == method
        for preset in schema.METHOD_PRESETS[method]:
            assert schema.normalize(schema.apply_preset(s, preset))["method"] == method
    assert schema.method_of({}) == "clipasso"
    assert schema.method_of({"method": "bogus"}) == "clipasso"
    assert schema.num_strokes(schema.default_settings("swiftsketch")) == 32
    assert schema.num_strokes(schema.default_settings("controlsketch")) == 32
    assert schema.num_strokes(schema.default_settings("scenesketch")) == 64
    # keys of another method are dropped, the method is kept
    s = schema.normalize({"method": "swiftsketch", "num_paths": 8, "guidance_param": "3"})
    assert "num_paths" not in s and s["guidance_param"] == 3.0 and s["method"] == "swiftsketch"


def test_cli_parses_original_swiftsketch_command_line():
    argv = ["--method", "swiftsketch", "--input_data", "camel.png", "--model_path", "x/model000450000.pt",
            "--refine_model_path", "y/model000430000.pt", "--guidance_param", "3.5", "--use_refine", "0",
            "--fix_scale", "1", "--seed", "7", "--device", "1", "--save_diffusion_sketch_in_dict", "1",
            "--generate_batch_size", "8"]
    assert cli.method_from_argv(argv) == "swiftsketch"
    s = cli.settings_from_args(cli.build_parser("swiftsketch").parse_args(argv))
    assert s["method"] == "swiftsketch"
    assert s["guidance_param"] == 3.5 and s["use_refine"] is False and s["fix_scale"] is True
    assert s["seed"] == 7 and s["gpunum"] == 1 and s["device"] == "auto"
    assert s["save_diffusion_sketch"] is True
    s = cli.settings_from_args(cli.build_parser("swiftsketch").parse_args(
        ["--method", "swiftsketch", "--input_data", "c.png", "--cuda", "False"]))
    assert s["device"] == "cpu"


def test_cli_parses_original_controlsketch_command_line():
    argv = ["--method", "controlsketch", "--target", "camel.png", "--num_strokes", "24", "--condition", "canny",
            "--conditioning_scale", "0.3", "--attn_model", "diffusion", "--object_name", "camel",
            "--caption", "a camel", "--use_cpu", "1", "--diffusion_model", "runwayml/stable-diffusion-v1-5",
            "--control_points_per_seg", "3", "--sort_final_sketch", "0"]
    s = cli.settings_from_args(cli.build_parser("controlsketch").parse_args(argv))
    assert s["method"] == "controlsketch" and s["num_strokes"] == 24 and s["condition"] == "canny"
    assert s["conditioning_scale"] == 0.3 and s["attn_model"] == "diffusion" and s["object_name"] == "camel"
    assert s["caption"] == "a camel" and s["device"] == "cpu" and s["control_points_per_seg"] == 3
    assert s["sort_final_sketch"] is False
    with pytest.raises(SystemExit):
        cli.build_parser("controlsketch").parse_args(["--target", "c.png", "--condition", "bogus"])


@pytest.mark.parametrize("method,changes", [
    ("swiftsketch", {"guidance_param": 4.0, "use_refine": False, "save_diffusion_sketch": True, "width": 3.0,
                     "num_sketches": 5, "device": "cpu"}),
    ("controlsketch", {"num_strokes": 16, "condition": "hed", "caption": "a camel", "attn_model": "diffusion",
                       "object_name": "camel", "save_interval": 50, "control_points_per_seg": 2}),
    ("scenesketch", {"layers": "4_11", "simplicity_levels": 3, "split_scene": False, "background_divs": "8:0.6",
                     "gumbel_temp": 0.3, "num_strokes": 32, "saliency_model": "dino"}),
])
def test_cli_roundtrip_per_method(method, changes):
    s = {**schema.default_settings(method), **changes}
    argv = ["--target_file", "x.png"] + schema.to_cli_args(s)
    assert argv[2:4] == ["--method", method]
    s2 = cli.settings_from_args(cli.build_parser(cli.method_from_argv(argv)).parse_args(argv))
    assert s2 == schema.normalize(s)
