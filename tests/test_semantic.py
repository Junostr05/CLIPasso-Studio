"""3.7, experimental: newer image models (OpenCLIP ViT-B/16, SigLIP B/16) for CLIPasso's semantic loss – optional,
downloaded on request, only their image part stored."""

import pytest
import torch

from clipasso_studio import settings_schema as schema
from clipasso_studio.engine import model_store
from clipasso_studio.engine.methods import requirements

CLIPASSO_MODELS = all(model_store.is_available(k) for k in ("clip:RN101", "clip:ViT-B/32"))
SEMANTIC = [k for k in requirements.SEMANTIC_KEYS if model_store.is_available(requirements.SEMANTIC_KEYS[k])]


def test_the_choices_and_their_models():
    assert schema.SEMANTIC_MODELS[0] == "clip" and schema.default_settings("clipasso")["semantic_model"] == "clip"
    assert set(schema.SEMANTIC_MODELS[1:]) == set(requirements.SEMANTIC_KEYS)
    for key in requirements.SEMANTIC_KEYS.values():
        spec = model_store.SPECS[key]
        assert spec.kind == "hf" and not spec.bundled and spec.extra.get("experimental") is True
        assert all(f.prefix and f.fp16 for f in spec.extra["files"])  # (the image part only, in float16)


def test_the_model_is_needed_only_when_it_is_used():
    s = schema.default_settings("clipasso")
    assert not any(k.startswith("semantic:") for k in requirements.clipasso(s))
    assert "semantic:siglip-b16" in requirements.clipasso({**s, "semantic_model": "siglip_b16"})
    for off in ({"clip_fc_loss_weight": 0.0}, {"clip_conv_loss": False}):
        assert "semantic:siglip-b16" not in requirements.clipasso({**s, "semantic_model": "siglip_b16", **off})
        assert not schema.is_enabled(schema.param("clipasso", "semantic_model"), {**s, **off})


def test_only_the_kept_part_is_stored(tmp_path):
    from safetensors.torch import load_file, save_file

    src = tmp_path / "raw.safetensors"
    save_file({"visual.a": torch.ones(2), "visual.b": torch.zeros(1, dtype=torch.int64), "text.c": torch.ones(3)},
              str(src))
    model_store._convert_hf_file(src, tmp_path / "out" / "model.safetensors",
                                 model_store.HFFile("raw", "model.safetensors", None, True, "visual."))
    out = load_file(str(tmp_path / "out" / "model.safetensors"))
    assert set(out) == {"visual.a", "visual.b"} and out["visual.a"].dtype == torch.float16
    assert out["visual.b"].dtype == torch.int64


def test_an_unknown_model():
    from clipasso_studio.engine import semantic

    with pytest.raises(ValueError):
        semantic.load("nope")


@pytest.mark.skipif(not (CLIPASSO_MODELS and SEMANTIC), reason="semantic models not downloaded "
                    "(tools/fetch_models.py --only semantic:openclip-b16,semantic:siglip-b16)")
@pytest.mark.parametrize("turbo", [False, True], ids=["plain", "turbo"])
def test_the_semantic_loss_uses_the_chosen_model(turbo):
    from clipasso_studio.engine import losses, pipeline, semantic

    name = SEMANTIC[0]
    s = {**schema.default_settings("clipasso"), "semantic_model": name, "turbo": turbo, "device": "cpu",
         "num_aug_clip": 2}
    args = pipeline.build_args(s, "", 0, "", torch.device("cpu"))
    conv = losses.Loss(args).loss_mapper["clip_conv_loss"]
    assert conv.semantic is semantic.load(name)
    seen = []
    forward = conv.semantic.forward
    conv.semantic.forward = lambda batch: (seen.append(batch.shape[0]), forward(batch))[1]
    torch.manual_seed(0)
    x = torch.rand(1, 3, 224, 224, requires_grad=True)
    y = torch.rand(1, 3, 224, 224)
    out = conv(x, y, mode="train")
    assert "fc" in out and seen  # the embedding came from the semantic model
    sum(out.values()).backward()
    assert x.grad is not None and torch.isfinite(x.grad).all()
    # without the fc loss no model is loaded
    args = pipeline.build_args({**s, "clip_fc_loss_weight": 0.0}, "", 0, "", torch.device("cpu"))
    assert losses.Loss(args).loss_mapper["clip_conv_loss"].semantic is None
