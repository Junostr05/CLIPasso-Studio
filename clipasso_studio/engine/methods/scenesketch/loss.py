"""Losses of SceneSketch – port of ``models/loss.py`` (CLIPascene, Vinker et al., ICCV 2023, MIT licence).

Only the parts the SceneSketch scripts use: the CLIP ViT-B/32 feature loss of selected layers
(``clip_conv_loss``), the stroke count loss (``WidthLoss``), the ratio loss that ties the number
of strokes to the CLIP loss (``RatioLoss``), and gradient-norm balancing (``compute_grad_norm_losses``).

The ViT is only evaluated up to the deepest layer the loss needs (a layer's features do not depend
on the layers after it), which gives the same values in less time for the shallow layers.
"""

from __future__ import annotations

import re

import torch
import torch.nn as nn
from torchvision import transforms
from torchvision.transforms import InterpolationMode

from ...clip_ import clip
from ...losses import AugmentBank

_CLIP_MEAN = (0.48145466, 0.4578275, 0.40821073)
_CLIP_STD = (0.26862954, 0.26130258, 0.27577711)


def vit_layer_features(visual, x: torch.Tensor, upto: int) -> list[torch.Tensor]:
    """Outputs of the residual blocks 0..``upto`` of a CLIP ViT, as [N, tokens, width] each
    (what the forward hooks of ``CLIPVisualEncoder`` record)."""
    x = x.type(visual.conv1.weight.dtype)
    x = visual.conv1(x)
    x = x.reshape(x.shape[0], x.shape[1], -1).permute(0, 2, 1)
    cls = visual.class_embedding.to(x.dtype) + torch.zeros(x.shape[0], 1, x.shape[-1], dtype=x.dtype,
                                                           device=x.device)
    x = torch.cat([cls, x], dim=1) + visual.positional_embedding.to(x.dtype)
    x = visual.ln_pre(x).permute(1, 0, 2)  # NLD -> LND
    feats = []
    for block in list(visual.transformer.resblocks)[: upto + 1]:
        x = block(x)
        feats.append(x.permute(1, 0, 2))
    return feats


def compute_grad_norm_losses(losses: dict, model_params: list, params: list) -> tuple[dict, dict | None]:
    """Weights each loss inversely to its share of the mean absolute gradient of ``model_params``.

    Returns (weights, the gradient of every loss for ``params``): the gradient of the weighted sum is
    put together from these (SceneLoss.backward) instead of a further backward pass through CLIP and
    the renderer."""
    if len(losses) < 2:
        return {k: 1.0 for k in losses}, None
    index = {id(p): i for i, p in enumerate(params)}
    grads, grad_norms = {}, {}
    for name, loss in losses.items():
        if loss.requires_grad:
            g = torch.autograd.grad(loss, params, retain_graph=True, allow_unused=True)
        else:
            g = (None,) * len(params)
        grads[name] = g
        used = [g[index[id(w)]] for w in model_params if id(w) in index and g[index[id(w)]] is not None]
        num_elem = sum(x.numel() for x in used)
        grad_norms[name] = torch.stack([x.abs().sum() for x in used]).sum() / max(num_elem, 1) if used else None
    values = [v for v in grad_norms.values() if v is not None]
    norms = dict(zip(grad_norms, torch.stack(values).tolist())) if values else {}  # one transfer
    norms = {k: norms.get(k, 0.0) for k in grad_norms}
    total = sum(norms.values())
    if total <= 0:
        return {k: 1.0 / len(losses) for k in losses}, grads
    return {k: (total - norms[k]) / ((len(losses) - 1) * total) for k in losses}, grads


class CLIPLayersLoss(nn.Module):
    """``CLIPConvLoss`` for ViT-B/32: per-layer distance of the sketch and target token features,
    on the image plus ``num_augs`` random perspective / crop augmentations (same for both).

    With ``bank_seed`` (turbo mode) the augmentations come from an :class:`AugmentBank` drawn from that
    seed, whose target features are computed once."""

    def __init__(self, layers: list[int], device, num_augs: int = 4, loss_type: str = "L2", model=None,
                 bank_seed: int | None = None):
        super().__init__()
        self.bank_seed = bank_seed
        self.bank: AugmentBank | None = None
        self.layers = sorted({int(layer) for layer in layers})
        self.device = device
        self.num_augs = int(num_augs)
        self.loss_type = loss_type
        if model is None:
            model, _ = clip.load("ViT-B/32", device, jit=False)
        self.model = model.eval()
        size = model.visual.input_resolution
        self.normalize_transform = transforms.Compose([
            transforms.Resize(size, interpolation=InterpolationMode.BICUBIC),
            transforms.CenterCrop(size),
            transforms.Normalize(_CLIP_MEAN, _CLIP_STD),
        ])
        self.augment_trans = transforms.Compose([
            transforms.RandomPerspective(fill=0, p=1.0, distortion_scale=0.5),
            transforms.RandomResizedCrop(224, scale=(0.8, 0.8), ratio=(1.0, 1.0)),
            transforms.Normalize(_CLIP_MEAN, _CLIP_STD),
        ])

    def _distance(self, x: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
        if self.loss_type == "L1":
            return torch.abs(x - y).mean()
        if self.loss_type == "Cos":
            return (1 - torch.cosine_similarity(x.float(), y.float(), dim=-1)).mean()
        return torch.square(x - y).mean()

    def _forward_bank(self, x: torch.Tensor, y: torch.Tensor, mode: str) -> dict:
        upto = self.layers[-1]
        if self.bank is None:
            self.bank = AugmentBank(self.bank_seed, y.shape[-1], 0.8)
            self.bank.build(self.normalize_transform(y), y, lambda b: [
                f for i, f in enumerate(vit_layer_features(self.model.visual, b, upto)) if i in self.layers])
        picked = self.bank.pick(self.num_augs) if mode == "train" else []
        xs = torch.cat([self.normalize_transform(x)] + [self.bank.apply(x, i) for i in picked], dim=0)
        xs_feats = vit_layer_features(self.model.visual, xs, upto)
        ys = self.bank.targets(picked)
        return {f"clip_vit_l{layer}": self._distance(xs_feats[layer].float(), y_feats.float())
                for layer, y_feats in zip(self.layers, ys)}

    def forward(self, sketch: torch.Tensor, target: torch.Tensor, mode: str = "train") -> dict:
        x = sketch.to(self.device)
        y = target.to(self.device)
        if self.bank_seed is not None:
            return self._forward_bank(x, y, mode)
        sketch_augs, img_augs = [self.normalize_transform(x)], [self.normalize_transform(y)]
        if mode == "train":
            for _ in range(self.num_augs):
                pair = self.augment_trans(torch.cat([x, y]))
                sketch_augs.append(pair[0].unsqueeze(0))
                img_augs.append(pair[1].unsqueeze(0))
        xs = torch.cat(sketch_augs, dim=0)
        ys = torch.cat(img_augs, dim=0)
        upto = self.layers[-1]
        xs_feats = vit_layer_features(self.model.visual, xs, upto)
        with torch.no_grad():
            ys_feats = vit_layer_features(self.model.visual, ys, upto)
        return {f"clip_vit_l{layer}": self._distance(xs_feats[layer].float(), ys_feats[layer].float())
                for layer in self.layers}


class SceneLoss(nn.Module):
    """``Loss`` of SceneSketch with ``clip_conv_loss`` (+ ``width_loss`` / ``ratio_loss`` when the
    strokes are being removed). Returns (weighted, normalised, original) loss dicts like the original."""

    def __init__(self, layer_weights: dict[int, float], device, num_augs: int = 4, loss_type: str = "L2",
                 width_optim: bool = False, width_loss_weight: float = 1.0, ratio: float = 0.0,
                 gradnorm: bool = False, clip_model=None, ratio_detach_clip: bool = False,
                 bank_seed: int | None = None):
        super().__init__()
        self.layer_weights = {int(k): float(v) for k, v in layer_weights.items() if v}
        self.clip_loss = CLIPLayersLoss(list(self.layer_weights), device, num_augs, loss_type, clip_model,
                                        bank_seed)
        self.width_optim = bool(width_optim)
        self.width_loss_weight = float(width_loss_weight)
        self.ratio = float(ratio)
        self.gradnorm = bool(gradnorm)
        self.ratio_detach_clip = bool(ratio_detach_clip)
        self.new_weights: dict = {}
        self._grads = None  # per-loss gradients of the last training step (gradnorm), see backward()

    def forward(self, sketch, target, widths=None, strokes_in_canvas=None, width_mlp=None, points_mlp=None,
                mode="train"):
        losses: dict[str, torch.Tensor] = {}
        coeffs: dict[str, float] = {}
        clip_names = []
        for name, value in self.clip_loss(sketch, target, mode).items():
            layer = int(re.findall(r"\d+", name)[0])
            losses[name] = value
            coeffs[name] = self.layer_weights[layer]
            clip_names.append(name)
        if self.width_optim:
            losses["width_loss"] = torch.sum(widths) / strokes_in_canvas
            coeffs["width_loss"] = self.width_loss_weight

        original = dict(losses)
        self._grads = None
        if self.gradnorm:
            if mode == "train":
                model = width_mlp if self.width_optim else points_mlp
                params = [p for m in (points_mlp, width_mlp) if m is not None for p in m.parameters()
                          if p.requires_grad]
                self.new_weights, grads = compute_grad_norm_losses(losses, list(model.parameters()), params)
                if grads is not None:
                    self._grads = (params, grads, dict(coeffs))
            # in eval mode the weights of the previous training step are used
            losses = {k: v * self.new_weights.get(k, 1.0) for k, v in losses.items()}

        normalised = {k: v.clone().detach() for k, v in losses.items()}
        weighted = {k: (v.detach() * coeffs[k] if coeffs[k] == 0 else v * coeffs[k]) for k, v in losses.items()}
        if self.ratio:
            # the number of strokes should follow ``ratio`` x the CLIP loss
            clip_sum = sum(original[k] for k in clip_names)
            if self.ratio_detach_clip:  # the ratio only sets how many strokes remain, never moves them
                clip_sum = clip_sum.detach()
            weighted["ratio_loss"] = nn.functional.mse_loss(original["width_loss"], clip_sum * self.ratio)
        original = {k: v.clone().detach() for k, v in original.items()}
        return weighted, normalised, original

    def backward(self, weighted: dict) -> None:
        """``sum(weighted.values()).backward()`` – with gradient-norm balancing, the gradients of the
        balanced losses are already known (one backward each), so only the rest (the ratio loss) is
        propagated again."""
        stored, self._grads = self._grads, None
        if stored is None:
            sum(weighted.values()).backward()
            return
        params, grads, coeffs = stored
        total = [None] * len(params)
        for name, g in grads.items():
            factor = coeffs[name] * self.new_weights.get(name, 1.0) if coeffs[name] != 0 else 0.0
            if factor == 0:
                continue
            for i, gi in enumerate(g):
                if gi is not None:
                    total[i] = gi * factor if total[i] is None else total[i] + gi * factor
        for p, g in zip(params, total):
            if g is not None:
                p.grad = g if p.grad is None else p.grad + g
        rest = [v for k, v in weighted.items() if k not in grads and v.requires_grad]
        if rest:
            sum(rest).backward()
