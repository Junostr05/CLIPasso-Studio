"""Loss functions – port of ``models/loss.py`` from CLIPasso.

Fixes compared to the original (which crashed or silently ignored these options):
* ``percep_loss`` ("L2" / "LPIPS") is wired into the loss mapper and weighted by ``perceptual_weight``;
* ``clip_text_guide`` adds a CLIP text-image loss towards ``text_target``;
* ``clip_conv_loss_type="Cos"`` computes a real cosine distance for ResNet models;
* ``augment_both=0`` compares augmented sketches with the un-augmented image;
* ``include_target_in_aug`` adds the un-augmented sketch to the CLIP loss batch;
* ``aug_scale_min`` sets the scale of the random resized crop.
"""

from __future__ import annotations

import collections

import torch
import torch.nn as nn
from torchvision import transforms

from . import nets
from .clip_ import clip

_CLIP_MEAN = (0.48145466, 0.4578275, 0.40821073)
_CLIP_STD = (0.26862954, 0.26130258, 0.27577711)


def _affine_augmentations(args, normalize=True):
    augs = []
    if "affine" in args.augemntations:
        scale = float(getattr(args, "aug_scale_min", 0.8))
        augs.append(transforms.RandomPerspective(fill=0, p=1.0, distortion_scale=0.5))
        augs.append(transforms.RandomResizedCrop(224, scale=(scale, scale), ratio=(1.0, 1.0)))
    if normalize:
        augs.append(transforms.Normalize(_CLIP_MEAN, _CLIP_STD))
    return transforms.Compose(augs)


class Loss(nn.Module):
    def __init__(self, args):
        super(Loss, self).__init__()
        self.args = args
        self.percep_loss = args.percep_loss

        self.train_with_clip = args.train_with_clip
        self.clip_weight = args.clip_weight
        self.start_clip = args.start_clip

        self.clip_conv_loss = args.clip_conv_loss
        self.clip_fc_loss_weight = args.clip_fc_loss_weight
        self.clip_text_guide = args.clip_text_guide

        self.losses_to_apply = self.get_losses_to_apply()

        self.loss_mapper = {}
        if "clip" in self.losses_to_apply or self.train_with_clip:
            self.loss_mapper["clip"] = CLIPLoss(args)
        if self.clip_conv_loss:
            self.loss_mapper["clip_conv_loss"] = CLIPConvLoss(args)
        if self.clip_text_guide:
            self.loss_mapper["clip_text"] = CLIPTextLoss(args)
        if self.percep_loss == "L2":
            self.loss_mapper["L2"] = L2_(args)
        elif self.percep_loss == "LPIPS":
            self.loss_mapper["LPIPS"] = LPIPS(args, device=args.device)

    def get_losses_to_apply(self):
        losses_to_apply = []
        if self.percep_loss != "none":
            losses_to_apply.append(self.percep_loss)
        if self.train_with_clip and self.start_clip == 0:
            losses_to_apply.append("clip")
        if self.clip_conv_loss:
            losses_to_apply.append("clip_conv_loss")
        if self.clip_text_guide:
            losses_to_apply.append("clip_text")
        return losses_to_apply

    def update_losses_to_apply(self, epoch):
        if "clip" not in self.losses_to_apply:
            if self.train_with_clip:
                if epoch > self.start_clip:
                    self.losses_to_apply.append("clip")

    def forward(self, sketches, targets, color_parameters, renderer, epoch, points_optim=None, mode="train"):
        self.update_losses_to_apply(epoch)

        losses_dict = dict.fromkeys(self.losses_to_apply, torch.tensor([0.0]).to(self.args.device))
        loss_coeffs = dict.fromkeys(self.losses_to_apply, 1.0)
        loss_coeffs["clip"] = self.clip_weight
        loss_coeffs["clip_text"] = self.clip_text_guide
        if self.percep_loss != "none":
            loss_coeffs[self.percep_loss] = self.args.perceptual_weight

        for loss_name in self.losses_to_apply:
            if loss_name in ["clip_conv_loss"]:
                conv_loss = self.loss_mapper[loss_name](sketches, targets, mode)
                for layer in conv_loss.keys():
                    losses_dict[layer] = conv_loss[layer]
            elif loss_name == "l2":
                losses_dict[loss_name] = self.loss_mapper[loss_name](sketches, targets).mean()
            else:
                losses_dict[loss_name] = self.loss_mapper[loss_name](sketches, targets, mode).mean()

        for key in self.losses_to_apply:
            losses_dict[key] = losses_dict[key] * loss_coeffs[key]
        # "clip_conv_loss" itself is only a placeholder; its value lives in the per-layer entries
        losses_dict.pop("clip_conv_loss", None)
        return losses_dict


class CLIPLoss(torch.nn.Module):
    def __init__(self, args):
        super(CLIPLoss, self).__init__()

        self.args = args
        self.model, clip_preprocess = clip.load('ViT-B/32', args.device, jit=False)
        self.model.eval()
        self.preprocess = transforms.Compose([clip_preprocess.transforms[-1]])  # clip normalisation
        self.device = args.device
        self.NUM_AUGS = args.num_aug_clip
        self.augment_trans = _affine_augmentations(args)

        self.calc_target = True
        self.include_target_in_aug = args.include_target_in_aug
        self.counter = 0
        self.augment_both = args.augment_both

    def forward(self, sketches, targets, mode="train"):
        if self.calc_target:
            targets_ = self.preprocess(targets).to(self.device)
            self.targets_features = self.model.encode_image(targets_).detach()
            self.calc_target = False

        if mode == "eval":
            # for regular clip distance, no augmentations
            with torch.no_grad():
                sketches = self.preprocess(sketches).to(self.device)
                sketches_features = self.model.encode_image(sketches)
                return 1. - torch.cosine_similarity(sketches_features, self.targets_features)

        loss_clip = 0
        sketch_augs = []
        if self.include_target_in_aug:
            sketch_augs.append(self.preprocess(sketches))
        for _ in range(self.NUM_AUGS):
            augmented_pair = self.augment_trans(torch.cat([sketches, targets]))
            sketch_augs.append(augmented_pair[0].unsqueeze(0))
        if not sketch_augs:
            sketch_augs.append(self.preprocess(sketches))

        sketch_batch = torch.cat(sketch_augs)
        sketch_features = self.model.encode_image(sketch_batch)

        for n in range(sketch_batch.shape[0]):
            loss_clip += (1. - torch.cosine_similarity(sketch_features[n:n + 1], self.targets_features, dim=1))
        self.counter += 1
        return loss_clip


class CLIPTextLoss(torch.nn.Module):
    """CLIP guidance towards ``text_target`` (the original declared ``clip_text_guide`` but never implemented it)."""

    def __init__(self, args):
        super().__init__()
        text = args.text_target if args.text_target not in (None, "", "none") else "a sketch"
        self.device = args.device
        self.model, clip_preprocess = clip.load('ViT-B/32', args.device, jit=False)
        self.model.eval()
        self.num_augs = args.num_aug_clip
        self.augment_trans = _affine_augmentations(args)
        self.normalize = transforms.Normalize(_CLIP_MEAN, _CLIP_STD)
        with torch.no_grad():
            self.text_features = self.model.encode_text(clip.tokenize([text]).to(self.device)).detach()

    def forward(self, sketches, targets, mode="train"):
        batch = [self.normalize(sketches)]
        if mode == "train":
            for _ in range(self.num_augs):
                batch.append(self.augment_trans(torch.cat([sketches, targets]))[0].unsqueeze(0))
        feats = self.model.encode_image(torch.cat(batch).to(self.device))
        return (1. - torch.cosine_similarity(feats, self.text_features, dim=1)).mean()


class LPIPS(torch.nn.Module):
    def __init__(self, args=None, pretrained=True, normalize=True, pre_relu=True, device=None):
        """
        Args:
            pre_relu(bool): if True, selects features **before** reLU activations
        """
        super(LPIPS, self).__init__()
        # VGG using perceptually-learned weights (LPIPS metric)
        self.normalize = normalize
        self.pretrained = pretrained
        self.augment_trans = _affine_augmentations(args, normalize=False) if args is not None else \
            transforms.Compose([transforms.RandomPerspective(fill=0, p=1.0, distortion_scale=0.5),
                                transforms.RandomResizedCrop(224, scale=(0.8, 0.8), ratio=(1.0, 1.0))])
        self.feature_extractor = LPIPS._FeatureExtractor(pretrained, pre_relu, device).to(device)

    def _l2_normalize_features(self, x, eps=1e-10):
        nrm = torch.sqrt(torch.sum(x * x, dim=1, keepdim=True))
        return x / (nrm + eps)

    def forward(self, pred, target, mode="train"):
        """Compare VGG features of two inputs."""
        sketch_augs, img_augs = [pred], [target]
        if mode == "train":
            for _ in range(4):
                augmented_pair = self.augment_trans(torch.cat([pred, target]))
                sketch_augs.append(augmented_pair[0].unsqueeze(0))
                img_augs.append(augmented_pair[1].unsqueeze(0))

        xs = torch.cat(sketch_augs, dim=0)
        ys = torch.cat(img_augs, dim=0)

        pred = self.feature_extractor(xs)
        target = self.feature_extractor(ys)

        if self.normalize:
            pred = [self._l2_normalize_features(f) for f in pred]
            target = [self._l2_normalize_features(f) for f in target]

        if self.normalize:
            diffs = [torch.sum((p - t) ** 2, 1) for (p, t) in zip(pred, target)]
        else:
            diffs = [torch.mean((p - t) ** 2, 1) for (p, t) in zip(pred, target)]

        diffs = [diff.mean([1, 2]) for diff in diffs]
        return sum(diffs)

    class _FeatureExtractor(torch.nn.Module):
        def __init__(self, pretrained, pre_relu, device=None):
            super(LPIPS._FeatureExtractor, self).__init__()
            vgg_pretrained = nets.load_vgg16_features(device or "cpu")

            self.breakpoints = [0, 4, 9, 16, 23, 30]
            if pre_relu:
                for i, _ in enumerate(self.breakpoints[1:]):
                    self.breakpoints[i + 1] -= 1

            # Split at the maxpools
            for i, b in enumerate(self.breakpoints[:-1]):
                ops = torch.nn.Sequential()
                for idx in range(b, self.breakpoints[i + 1]):
                    op = vgg_pretrained[idx]
                    ops.add_module(str(idx), op)
                self.add_module("group{}".format(i), ops)

            for p in self.parameters():
                p.requires_grad = False

            self.register_buffer("shift", torch.Tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1))
            self.register_buffer("scale", torch.Tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1))

        def forward(self, x):
            feats = []
            x = (x - self.shift) / self.scale
            for idx in range(len(self.breakpoints) - 1):
                m = getattr(self, "group{}".format(idx))
                x = m(x)
                feats.append(x)
            return feats


class L2_(torch.nn.Module):
    def __init__(self, args=None):
        super(L2_, self).__init__()
        self.augment_trans = _affine_augmentations(args) if args is not None else transforms.Compose([
            transforms.RandomPerspective(fill=0, p=1.0, distortion_scale=0.5),
            transforms.RandomResizedCrop(224, scale=(0.8, 0.8), ratio=(1.0, 1.0)),
            transforms.Normalize(_CLIP_MEAN, _CLIP_STD)])

    def forward(self, pred, target, mode="train"):
        sketch_augs, img_augs = [pred], [target]
        if mode == "train":
            for _ in range(4):
                augmented_pair = self.augment_trans(torch.cat([pred, target]))
                sketch_augs.append(augmented_pair[0].unsqueeze(0))
                img_augs.append(augmented_pair[1].unsqueeze(0))

        pred = torch.cat(sketch_augs, dim=0)
        target = torch.cat(img_augs, dim=0)
        diffs = [torch.square(p - t).mean() for (p, t) in zip(pred, target)]
        return sum(diffs)


class CLIPVisualEncoder(nn.Module):
    def __init__(self, clip_model):
        super().__init__()
        self.clip_model = clip_model
        self.featuremaps = None
        self._hooks = []
        for i in range(len(self.clip_model.visual.transformer.resblocks)):
            self._hooks.append(self.clip_model.visual.transformer.resblocks[i].register_forward_hook(
                self.make_hook(i)))

    def make_hook(self, name):
        def hook(module, input, output):
            if len(output.shape) == 3:
                self.featuremaps[name] = output.permute(1, 0, 2)  # LND -> NLD bs, smth, 768
            else:
                self.featuremaps[name] = output

        return hook

    def forward(self, x):
        self.featuremaps = collections.OrderedDict()
        fc_features = self.clip_model.encode_image(x).float()
        featuremaps = [self.featuremaps[k] for k in range(len(self.featuremaps))]
        return fc_features, featuremaps


def l2_layers(xs_conv_features, ys_conv_features, clip_model_name):
    return [torch.square(x_conv - y_conv).mean() for x_conv, y_conv in zip(xs_conv_features, ys_conv_features)]


def l1_layers(xs_conv_features, ys_conv_features, clip_model_name):
    return [torch.abs(x_conv - y_conv).mean() for x_conv, y_conv in zip(xs_conv_features, ys_conv_features)]


def cos_layers(xs_conv_features, ys_conv_features, clip_model_name):
    # The original used ``torch.square(x, y, dim=1)`` for ResNets, which raises a TypeError.
    return [(1 - torch.cosine_similarity(x_conv.float(), y_conv.float(), dim=1)).mean()
            for x_conv, y_conv in zip(xs_conv_features, ys_conv_features)]


class CLIPConvLoss(torch.nn.Module):
    def __init__(self, args):
        super(CLIPConvLoss, self).__init__()
        self.clip_model_name = args.clip_model_name
        assert self.clip_model_name in ["RN50", "RN101", "RN50x4", "RN50x16", "ViT-B/32", "ViT-B/16"]

        self.clip_conv_loss_type = args.clip_conv_loss_type
        self.clip_fc_loss_type = "Cos"
        assert self.clip_conv_loss_type in ["L2", "Cos", "L1"]

        self.distance_metrics = {"L2": l2_layers, "L1": l1_layers, "Cos": cos_layers}

        self.model, clip_preprocess = clip.load(self.clip_model_name, args.device, jit=False)

        if self.clip_model_name.startswith("ViT"):
            self.visual_encoder = CLIPVisualEncoder(self.model)
        else:
            self.visual_model = self.model.visual
            layers = list(self.model.visual.children())
            self.layer1 = layers[8]
            self.layer2 = layers[9]
            self.layer3 = layers[10]
            self.layer4 = layers[11]
            self.att_pool2d = layers[12]

        self.args = args

        self.img_size = clip_preprocess.transforms[1].size
        self.model.eval()
        self.normalize_transform = transforms.Compose([
            clip_preprocess.transforms[0],  # Resize
            clip_preprocess.transforms[1],  # CenterCrop
            clip_preprocess.transforms[-1],  # Normalize
        ])

        self.device = args.device
        self.num_augs = self.args.num_aug_clip
        self.augment_both = args.augment_both
        self.augment_trans = _affine_augmentations(args)

        self.clip_fc_loss_weight = args.clip_fc_loss_weight
        self.counter = 0

    def forward(self, sketch, target, mode="train"):
        conv_loss_dict = {}
        x = sketch.to(self.device)
        y = target.to(self.device)
        sketch_augs, img_augs = [self.normalize_transform(x)], [self.normalize_transform(y)]
        if mode == "train":
            for _ in range(self.num_augs):
                augmented_pair = self.augment_trans(torch.cat([x, y]))
                sketch_augs.append(augmented_pair[0].unsqueeze(0))
                if self.augment_both:
                    img_augs.append(augmented_pair[1].unsqueeze(0))
                else:
                    img_augs.append(img_augs[0])

        xs = torch.cat(sketch_augs, dim=0).to(self.device)
        ys = torch.cat(img_augs, dim=0).to(self.device)

        if self.clip_model_name.startswith("RN"):
            xs_fc_features, xs_conv_features = self.forward_inspection_clip_resnet(xs.contiguous())
            with torch.no_grad():
                ys_fc_features, ys_conv_features = self.forward_inspection_clip_resnet(ys.detach())
        else:
            xs_fc_features, xs_conv_features = self.visual_encoder(xs)
            with torch.no_grad():
                ys_fc_features, ys_conv_features = self.visual_encoder(ys)

        conv_loss = self.distance_metrics[self.clip_conv_loss_type](xs_conv_features, ys_conv_features,
                                                                    self.clip_model_name)

        for layer, w in enumerate(self.args.clip_conv_layer_weights):
            if w and layer < len(conv_loss):
                conv_loss_dict[f"clip_conv_loss_layer{layer}"] = conv_loss[layer] * w

        if self.clip_fc_loss_weight:
            # fc distance is always cos
            fc_loss = (1 - torch.cosine_similarity(xs_fc_features, ys_fc_features, dim=1)).mean()
            conv_loss_dict["fc"] = fc_loss * self.clip_fc_loss_weight

        self.counter += 1
        return conv_loss_dict

    def forward_inspection_clip_resnet(self, x):
        def stem(m, x):
            for conv, bn in [(m.conv1, m.bn1), (m.conv2, m.bn2), (m.conv3, m.bn3)]:
                x = m.relu(bn(conv(x)))
            x = m.avgpool(x)
            return x

        x = x.type(self.visual_model.conv1.weight.dtype)
        x = stem(self.visual_model, x)
        x1 = self.layer1(x)
        x2 = self.layer2(x1)
        x3 = self.layer3(x2)
        x4 = self.layer4(x3)
        y = self.att_pool2d(x4)
        return y, [x, x1, x2, x3, x4]
