"""Tiny randomly initialised stand-ins for the downloadable models.

Used by the self-test of the packaged app and by the unit tests to run SwiftSketch and ControlSketch
end to end (all code paths, including the diffusers / transformers imports) without downloading
gigabytes of weights.
"""

from __future__ import annotations

import torch

SWIFT_ARGS = {"latent_dim": 64, "layers": 2, "heads": 4, "image_features_type": "CLIPMiddle_layer4",
              "normalize_model_output": 1, "scaling_factor": 2.0, "cond_mask_prob": 0.1, "num_paths": 32,
              "diffusion_steps": 50, "cos_power": 0.4}


def swiftsketch_net(seed: int = 0, **overrides):
    from .methods.swiftsketch.model import SwiftSketchNet

    torch.manual_seed(seed)
    return SwiftSketchNet.from_args({**SWIFT_ARGS, **overrides}).eval()


def tiny_sd(seed: int = 0):
    """(unet, controlnet, vae) with the Stable Diffusion 1.5 structure, a few MB in size."""
    from diffusers import AutoencoderKL, ControlNetModel, UNet2DConditionModel

    torch.manual_seed(seed)
    unet = UNet2DConditionModel(block_out_channels=(32, 64), layers_per_block=1, sample_size=8, in_channels=4,
                                out_channels=4, down_block_types=("DownBlock2D", "CrossAttnDownBlock2D"),
                                up_block_types=("CrossAttnUpBlock2D", "UpBlock2D"), cross_attention_dim=32,
                                attention_head_dim=4, norm_num_groups=8)
    controlnet = ControlNetModel.from_unet(unet, conditioning_embedding_out_channels=(16, 32, 96, 256))
    vae = AutoencoderKL(block_out_channels=(32, 32, 32, 32), in_channels=3, out_channels=3, latent_channels=4,
                        down_block_types=("DownEncoderBlock2D",) * 4, up_block_types=("UpDecoderBlock2D",) * 4,
                        norm_num_groups=8)
    for m in (unet, controlnet, vae):
        m.requires_grad_(False).eval()
    return unet, controlnet, vae


def tiny_text_encoder():
    """A 2-layer CLIP text encoder (hidden size 32) – exercises transformers' CLIPTextModel."""
    from transformers import CLIPTextConfig, CLIPTextModel

    torch.manual_seed(0)
    cfg = CLIPTextConfig(bos_token_id=49406, eos_token_id=49407, pad_token_id=49407, hidden_size=32,
                         intermediate_size=37, num_attention_heads=4, num_hidden_layers=2, vocab_size=49408,
                         projection_dim=32, hidden_act="gelu")
    return CLIPTextModel(cfg).eval()


class TinyTokenizer:
    """Minimal stand-in for CLIPTokenizer (the real one needs the SD 1.5 vocabulary files)."""

    model_max_length = 77

    def __call__(self, text, padding=None, max_length=77, truncation=True, return_tensors="pt"):
        texts = [text] if isinstance(text, str) else list(text)
        ids = torch.full((len(texts), max_length), 49407, dtype=torch.long)
        ids[:, 0] = 49406
        for i, t in enumerate(texts):
            for j, ch in enumerate(t.encode("utf-8")[: max_length - 2]):
                ids[i, j + 1] = 256 + ch
        return type("Tokens", (), {"input_ids": ids})()


def tiny_sd15_loader(condition: str, device):
    """Replacement for ``controlsketch.sds.load_sd15``."""
    from .methods.controlsketch.sds import alphas_cumprod_from_config

    unet, controlnet, vae = tiny_sd()
    return (unet.to(device), controlnet.to(device), vae.to(device), TinyTokenizer(),
            tiny_text_encoder().to(device), alphas_cumprod_from_config({}))


def tiny_lama(device="cpu"):
    """LaMa generator with the big-lama structure but 8 base channels and one residual block."""
    from .methods.scenesketch.lama import LamaGenerator

    torch.manual_seed(0)
    return LamaGenerator(ngf=8, n_blocks=1).eval().to(device)
