"""Experimental image models for CLIPasso's semantic loss (3.7, ``semantic_model``).

CLIPasso compares sketch and photo in two ways: the conv layers of CLIP RN101 (the geometry) and the final image
embedding (the meaning, ``clip_fc_loss_weight``). Here the embedding can come from a newer model instead, while
RN101 stays for the conv layers:

- ``openclip_b16``: OpenCLIP ViT-B/16 trained on LAION-2B (MIT) – the architecture of OpenAI's CLIP with GELU
  instead of QuickGELU, so it is built by the bundled CLIP code;
- ``siglip_b16``: Google's SigLIP B/16 at 224 px (Apache-2.0), with its attention-pooling head (``transformers``).

Both get the batches CLIPasso already makes (augmented, normalised for CLIP) and turn them into their own input.
Experimental: optional, downloaded on request on the models page.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F
from torch import nn

from . import model_store
from .methods.requirements import SEMANTIC_KEYS as MODELS

DEFAULT = "clip"  # the embedding of the conv model itself, as in the original

_CLIP_MEAN = torch.tensor((0.48145466, 0.4578275, 0.40821073)).view(1, 3, 1, 1)
_CLIP_STD = torch.tensor((0.26862954, 0.26130258, 0.27577711)).view(1, 3, 1, 1)


def model_key(name: str) -> str | None:
    """The model store key of a semantic model, None for the default."""
    return MODELS.get(name)


def _state(key: str) -> dict:
    from safetensors.torch import load_file

    return load_file(str(model_store.model_dir(key) / "model.safetensors"))


class _OpenCLIP(nn.Module):
    def __init__(self, device):
        super().__init__()
        from .clip_.model import ResidualAttentionBlock, VisualTransformer

        state = {k[len("visual."):]: v.float() for k, v in _state(MODELS["openclip_b16"]).items()}
        width = state["conv1.weight"].shape[0]
        layers = len([k for k in state if k.endswith(".attn.in_proj_weight")])
        patch = state["conv1.weight"].shape[-1]
        grid = round((state["positional_embedding"].shape[0] - 1) ** 0.5)
        with torch.random.fork_rng(devices=[]):  # (the random init is replaced: the sketch stays the same)
            self.visual = VisualTransformer(input_resolution=patch * grid, patch_size=patch, width=width,
                                            layers=layers, heads=width // 64, output_dim=state["proj"].shape[1])
        for block in self.visual.modules():
            if isinstance(block, ResidualAttentionBlock):
                block.mlp.gelu = nn.GELU()  # OpenCLIP's models of LAION use the exact GELU
        self.visual.load_state_dict(state)
        self.size = patch * grid
        self.to(device)

    def forward(self, x_clip: torch.Tensor) -> torch.Tensor:
        if x_clip.shape[-1] != self.size:
            x_clip = F.interpolate(x_clip, size=(self.size, self.size), mode="bicubic", align_corners=False)
        return self.visual(x_clip)


class _SigLIP(nn.Module):
    def __init__(self, device):
        super().__init__()
        from transformers import SiglipVisionConfig, SiglipVisionModel

        config = SiglipVisionConfig()  # (the defaults are the base model: 768 wide, 12 layers, 224 px, patch 16)
        with torch.random.fork_rng(devices=[]):
            self.model = SiglipVisionModel(config)
        prefix = "vision_model."  # (the file's names; the vision model's own have no prefix in transformers 5)
        state = {k[len(prefix):] if k.startswith(prefix) else k: v.float()
                 for k, v in _state(MODELS["siglip_b16"]).items()}
        own = set(self.model.state_dict())
        self.model.load_state_dict(state if set(state) == own else {prefix + k: v for k, v in state.items()})
        self.size = config.image_size
        self.to(device)

    def forward(self, x_clip: torch.Tensor) -> torch.Tensor:
        # from CLIP's normalisation to SigLIP's (mean = std = 0.5)
        x = x_clip * _CLIP_STD.to(x_clip) + _CLIP_MEAN.to(x_clip)
        x = (x - 0.5) / 0.5
        if x.shape[-1] != self.size:
            x = F.interpolate(x, size=(self.size, self.size), mode="bicubic", align_corners=False)
        return self.model(pixel_values=x).pooler_output


_loaded: dict = {}


def load(name: str, device="cpu") -> nn.Module:
    """The encoder of a semantic model: batches normalised for CLIP [N,3,H,W] -> embeddings [N,D] (float32,
    frozen, shared within the process)."""
    if name not in MODELS:
        raise ValueError(f"unknown semantic model {name!r}: {', '.join(MODELS)}")
    key = (name, str(torch.device(device)))
    if key not in _loaded:
        model = (_OpenCLIP if name == "openclip_b16" else _SigLIP)(device)
        model.requires_grad_(False)
        _loaded[key] = model.eval()
    return _loaded[key]


def release_models() -> None:
    _loaded.clear()
