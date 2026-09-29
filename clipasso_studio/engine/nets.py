"""Loaders for the auxiliary networks (U2Net for masking, DINO ViT-S/8 for saliency, VGG16 for LPIPS)."""

from __future__ import annotations

from torch import nn

from . import model_store


def load_u2net(device) -> nn.Module:
    from .u2net.u2net import U2NET

    net = U2NET(3, 1)
    state = {k: v.float() for k, v in model_store.load_state("u2net").items()}
    net.load_state_dict(state)
    net.requires_grad_(False)
    return net.to(device).eval()


def load_dino_vits8(device) -> nn.Module:
    """Same network as ``torch.hub.load('facebookresearch/dino:main', 'dino_vits8')``."""
    from .dino.vision_transformer import vit_small

    model = vit_small(patch_size=8, num_classes=0)
    state = {k: v.float() for k, v in model_store.load_state("dino").items()}
    model.load_state_dict(state, strict=True)
    model.requires_grad_(False)
    return model.to(device).eval()


def load_vgg16_features(device) -> nn.Sequential:
    from torchvision.models import vgg16

    model = vgg16(weights=None)
    state = {k[len("features."):]: v.float() for k, v in model_store.load_state("vgg16").items()}
    model.features.load_state_dict(state)
    model.features.requires_grad_(False)
    return model.features.to(device).eval()
