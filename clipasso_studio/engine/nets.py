"""Loaders for the auxiliary networks (BiRefNet / U2Net for masking, DINO ViT-S/8 for saliency, VGG16 for LPIPS).

Building a network does not touch the random number generator (its random init is replaced by the
weights): a sketch must not depend on which networks were already loaded in the process. U2Net, DINO
and VGG16 are small and are kept per process and device (every sketch of a job needs them).
"""

from __future__ import annotations

import torch
from torch import nn

from . import model_store

_cache: dict = {}


def release_models() -> None:
    _cache.clear()


def _cached(key, build):
    if key not in _cache:
        with torch.random.fork_rng(devices=[]):
            _cache[key] = build()
    return _cache[key]


def load_u2net(device) -> nn.Module:
    def build():
        from .u2net.u2net import U2NET

        net = U2NET(3, 1)
        state = {k: v.float() for k, v in model_store.load_state("u2net").items()}
        net.load_state_dict(state)
        net.requires_grad_(False)
        return net.to(device).eval()

    return _cached(("u2net", str(device)), build)


def load_birefnet(device, spec_key: str = "birefnet") -> nn.Module:
    """BiRefNet (``birefnet``: Swin-L, ``birefnet-lite``: Swin-T) in float32 (not kept: it is big and its
    masks are cached)."""
    from safetensors.torch import load_file

    from .birefnet import build

    with torch.random.fork_rng(devices=[]):
        net = build("lite" if spec_key == "birefnet-lite" else "general")
    state = load_file(str(model_store.model_dir(spec_key) / "model.safetensors"))
    net.load_state_dict({k: v.float() for k, v in state.items()}, strict=True)
    del state
    net.requires_grad_(False)
    return net.to(device).eval()


def load_dino_vits8(device) -> nn.Module:
    """Same network as ``torch.hub.load('facebookresearch/dino:main', 'dino_vits8')``."""
    def build():
        from .dino.vision_transformer import vit_small

        model = vit_small(patch_size=8, num_classes=0)
        state = {k: v.float() for k, v in model_store.load_state("dino").items()}
        model.load_state_dict(state, strict=True)
        model.requires_grad_(False)
        return model.to(device).eval()

    return _cached(("dino", str(device)), build)


def load_vgg16_features(device) -> nn.Sequential:
    def build():
        from torchvision.models import vgg16

        model = vgg16(weights=None)
        state = {k[len("features."):]: v.float() for k, v in model_store.load_state("vgg16").items()}
        model.features.load_state_dict(state)
        model.features.requires_grad_(False)
        return model.features.to(device).eval()

    return _cached(("vgg16", str(device)), build)
