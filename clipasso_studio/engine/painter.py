"""Stroke model and optimiser – port of ``models/painter_params.py`` from CLIPasso.

Changes compared to the original:
* ``pydiffvg`` is replaced by the PyTorch renderer in :mod:`.renderer`;
* CLIP / DINO weights come from the local model store (no ``torch.hub`` download);
* DINO saliency uses the processed target image, so it stays aligned with ``fix_scale``;
* ``mask_object_attention`` restricts the initial stroke positions to the object mask;
* ``num_stages`` adds new strokes per stage (see :func:`Painter.init_image`);
* scipy / scikit-image calls are replaced by :mod:`.imaging`.
"""

from __future__ import annotations

import random

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision import transforms

from . import imaging, nets, renderer, svg_io
from .clip_ import clip


class Painter(torch.nn.Module):
    def __init__(self, args, num_strokes=4, num_segments=4, imsize=224, device=None, target_im=None, mask=None):
        super().__init__()

        self.args = args
        self.num_paths = num_strokes
        self.num_segments = num_segments
        self.width = args.width
        self.control_points_per_seg = args.control_points_per_seg
        self.opacity_optim = args.force_sparse
        self.num_stages = args.num_stages
        self.add_random_noise = "noise" in args.augemntations
        self.noise_thresh = args.noise_thresh
        self.softmax_temp = args.softmax_temp

        self.shapes = []
        self.shape_groups = []
        self.device = device
        self.canvas_width, self.canvas_height = imsize, imsize
        self.points_vars = []
        self.color_vars = []
        self.color_vars_threshold = args.color_vars_threshold

        self.path_svg = args.path_svg
        self.strokes_per_stage = self.num_paths
        self.optimize_flag = []

        # attention related for strokes initialisation
        self.attention_init = args.attention_init
        self.target_im = target_im
        self.saliency_model = args.saliency_model
        self.xdog_intersec = args.xdog_intersec
        self.mask_object = args.mask_object_attention

        self.text_target = args.text_target  # for clip gradients
        self.saliency_clip_model = args.saliency_clip_model
        self.define_attention_input(target_im)
        self.mask = mask
        self.attention_map = self.set_attention_map() if self.attention_init else None
        self.thresh = self.set_attention_threshold_map() if self.attention_init else None
        self.strokes_counter = 0  # counts the number of calls to "get_path"
        self.epoch = 0
        self.final_epoch = args.num_iter - 1

    def init_image(self, stage=0):
        if stage > 0:
            # if multi stages training than add new strokes on existing ones
            # don't optimize on previous strokes
            self.optimize_flag = [False for _ in range(len(self.shapes))]
            for _ in range(self.strokes_per_stage):
                stroke_color = torch.tensor([0.0, 0.0, 0.0, 1.0], device=self.device)
                path = self.get_path()
                self.shapes.append(path)
                path_group = renderer.ShapeGroup(shape_ids=torch.tensor([len(self.shapes) - 1]),
                                                 fill_color=None, stroke_color=stroke_color)
                self.shape_groups.append(path_group)
                self.optimize_flag.append(True)
        else:
            num_paths_exists = 0
            if self.path_svg not in (None, "", "none"):
                self.canvas_width, self.canvas_height, self.shapes, self.shape_groups = self._load_init_svg()
                # if you want to add more strokes to existing ones and optimize on all of them
                num_paths_exists = len(self.shapes)

            for _ in range(num_paths_exists, self.num_paths):
                stroke_color = torch.tensor([0.0, 0.0, 0.0, 1.0], device=self.device)
                path = self.get_path()
                self.shapes.append(path)
                path_group = renderer.ShapeGroup(shape_ids=torch.tensor([len(self.shapes) - 1]),
                                                 fill_color=None, stroke_color=stroke_color)
                self.shape_groups.append(path_group)
            self.optimize_flag = [True for _ in range(len(self.shapes))]

        return self.get_image()

    def _load_init_svg(self):
        w, h, shapes, groups = svg_io.load_svg(self.path_svg, device=self.device)
        # rescale to the working canvas
        sx, sy = self.canvas_width / w, self.canvas_height / h
        for s in shapes:
            s.points = (s.points * torch.tensor([sx, sy], device=s.points.device)).to(self.device)
        return self.canvas_width, self.canvas_height, shapes, groups

    def get_image(self):
        img = self.render_warp()  # on white (black strokes take the fast path of the renderer)
        # Convert img from HWC to NCHW
        img = img.unsqueeze(0)
        img = img.permute(0, 3, 1, 2).to(self.device)  # NHWC -> NCHW
        return img

    def get_path(self):
        points = []
        self.num_control_points = torch.zeros(self.num_segments, dtype=torch.int32) + (self.control_points_per_seg - 2)
        p0 = self.inds_normalised[self.strokes_counter] if self.attention_init else (random.random(), random.random())
        points.append(p0)

        for _ in range(self.num_segments):
            radius = 0.05
            for _ in range(self.control_points_per_seg - 1):
                p1 = (p0[0] + radius * (random.random() - 0.5), p0[1] + radius * (random.random() - 0.5))
                points.append(p1)
                p0 = p1
        points = torch.tensor(points, dtype=torch.float32).to(self.device)
        points[:, 0] *= self.canvas_width
        points[:, 1] *= self.canvas_height

        path = renderer.Path(num_control_points=self.num_control_points, points=points,
                             stroke_width=torch.tensor(self.width, device=self.device), is_closed=False)
        self.strokes_counter += 1
        return path

    def render_warp(self):
        if self.opacity_optim:
            for group in self.shape_groups:
                group.stroke_color.data[:3].clamp_(0., 0.)  # to force black stroke
                group.stroke_color.data[-1].clamp_(0., 1.)  # opacity
        if self.add_random_noise:
            if random.random() > self.noise_thresh:
                eps = 0.01 * min(self.canvas_width, self.canvas_height)
                for path in self.shapes:
                    path.points.data.add_(eps * torch.randn_like(path.points))
        return renderer.render_on_white(self.canvas_width, self.canvas_height, self.shapes, self.shape_groups)

    def parameters(self):
        self.points_vars = []
        # strokes' location optimization
        for i, path in enumerate(self.shapes):
            if self.optimize_flag[i]:
                path.points.requires_grad = True
                self.points_vars.append(path.points)
            else:
                path.points.requires_grad = False
        return self.points_vars

    def get_points_parans(self):
        return self.points_vars

    def set_color_parameters(self):
        # for strokes' color optimization (opacity)
        self.color_vars = []
        for i, group in enumerate(self.shape_groups):
            if self.optimize_flag[i]:
                group.stroke_color.requires_grad = True
                self.color_vars.append(group.stroke_color)
        return self.color_vars

    def get_color_parameters(self):
        return self.color_vars

    def min_opacity(self) -> float:
        return float(self.color_vars_threshold) if self.opacity_optim else 0.0

    def to_svg(self) -> str:
        return svg_io.scene_to_svg(self.canvas_width, self.canvas_height, self.shapes, self.shape_groups,
                                   min_opacity=self.min_opacity())

    def save_svg(self, output_dir, name):
        svg_io.save_svg('{}/{}.svg'.format(output_dir, name), self.canvas_width, self.canvas_height,
                        self.shapes, self.shape_groups, min_opacity=self.min_opacity())

    # ------------------------------------------------------------------ saliency

    def dino_attn(self):
        patch_size = 8  # dino hyperparameter
        threshold = 0.6

        mean_imagenet = torch.Tensor([0.485, 0.456, 0.406])[None, :, None, None].to(self.device)
        std_imagenet = torch.Tensor([0.229, 0.224, 0.225])[None, :, None, None].to(self.device)
        dino_model = nets.load_dino_vits8(self.device)

        main_im_tensor = F.interpolate(self.target_im.float(), size=(self.canvas_height, self.canvas_width),
                                       mode="bilinear", align_corners=False)
        img = (main_im_tensor - mean_imagenet) / std_imagenet
        w_featmap = img.shape[-2] // patch_size
        h_featmap = img.shape[-1] // patch_size

        with torch.no_grad():
            attn = dino_model.get_last_selfattention(img).detach().cpu()[0]

        nh = attn.shape[0]
        attn = attn[:, 0, 1:].reshape(nh, -1)
        val, idx = torch.sort(attn)
        val /= torch.sum(val, dim=1, keepdim=True)
        cumval = torch.cumsum(val, dim=1)
        th_attn = cumval > (1 - threshold)
        idx2 = torch.argsort(idx)
        for head in range(nh):
            th_attn[head] = th_attn[head][idx2[head]]
        th_attn = th_attn.reshape(nh, w_featmap, h_featmap).float()
        th_attn = nn.functional.interpolate(th_attn.unsqueeze(0), scale_factor=patch_size, mode="nearest")[0].cpu()

        attn = attn.reshape(nh, w_featmap, h_featmap).float()
        attn = nn.functional.interpolate(attn.unsqueeze(0), scale_factor=patch_size, mode="nearest")[0].cpu()
        attn = F.interpolate(attn.unsqueeze(0), size=(self.canvas_height, self.canvas_width), mode="nearest")[0]
        del dino_model
        return attn

    def define_attention_input(self, target_im):
        model, preprocess = clip.load(self.saliency_clip_model, device=self.device, jit=False)
        model.eval().to(self.device)
        data_transforms = transforms.Compose([preprocess.transforms[-1]])
        self.image_input_attn_clip = data_transforms(target_im).to(self.device)
        self._clip_input_res = model.visual.input_resolution
        del model

    def clip_attn(self):
        model, preprocess = clip.load(self.saliency_clip_model, device=self.device, jit=False)
        model.eval().to(self.device)
        text_input = clip.tokenize([self.text_target]).to(self.device)
        image_input = F.interpolate(self.image_input_attn_clip, size=(self._clip_input_res, self._clip_input_res),
                                    mode="bicubic", align_corners=False)

        if "RN" in self.saliency_clip_model:
            saliency_layer = "layer4"
            attn_map = gradCAM(
                model.visual,
                image_input.type(model.dtype),
                model.encode_text(text_input).float(),
                getattr(model.visual, saliency_layer),
            )
            attn_map = attn_map.squeeze().detach().cpu().float().numpy()
            attn_map = (attn_map - attn_map.min()) / (attn_map.max() - attn_map.min() + 1e-12)
        else:
            attn_map = interpret(image_input, text_input, model, device=self.device)

        del model
        if attn_map.shape != (self.canvas_height, self.canvas_width):
            t = torch.from_numpy(np.ascontiguousarray(attn_map, dtype=np.float32))[None, None]
            attn_map = F.interpolate(t, size=(self.canvas_height, self.canvas_width), mode="bicubic",
                                     align_corners=False)[0, 0].numpy()
        return attn_map

    def set_attention_map(self):
        assert self.saliency_model in ["dino", "clip"]
        if self.saliency_model == "dino":
            attn = self.dino_attn()
        else:
            attn = self.clip_attn()
        if self.mask_object and self.mask is not None:
            mask = self.mask.float().cpu()
            if torch.is_tensor(attn):
                if mask.sum() > 0:
                    attn = attn * mask[None]
            else:
                m = mask.numpy()
                if m.sum() > 0:
                    attn = attn * m
        return attn

    def softmax(self, x, tau=0.2):
        e_x = np.exp(x / tau)
        return e_x / e_x.sum()

    def set_inds_clip(self):
        attn_map = (self.attention_map - self.attention_map.min()) / (
            self.attention_map.max() - self.attention_map.min() + 1e-12)
        if self.xdog_intersec:
            xdog = XDoG_()
            im_xdog = xdog(self.image_input_attn_clip[0].permute(1, 2, 0).cpu().float().numpy(), k=10)
            intersec_map = (1 - im_xdog) * attn_map
            if intersec_map.max() > 0:
                attn_map = intersec_map

        attn_map_soft = np.copy(attn_map)
        attn_map_soft[attn_map > 0] = self.softmax(attn_map[attn_map > 0], tau=self.softmax_temp)

        k = self.num_stages * self.num_paths
        p = attn_map_soft.flatten().astype(np.float64)
        p = np.nan_to_num(p)
        if np.count_nonzero(p) < k:  # too few candidate pixels: fall back to a slightly smoothed map
            p = p + 1e-12
        p = p / p.sum()
        self.inds = np.random.choice(range(attn_map.flatten().shape[0]), size=k, replace=False, p=p)
        self.inds = np.array(np.unravel_index(self.inds, attn_map.shape)).T

        self.inds_normalised = np.zeros(self.inds.shape)
        self.inds_normalised[:, 0] = self.inds[:, 1] / self.canvas_width
        self.inds_normalised[:, 1] = self.inds[:, 0] / self.canvas_height
        self.inds_normalised = self.inds_normalised.tolist()
        return attn_map_soft

    def set_inds_dino(self):
        k = max(3, (self.num_stages * self.num_paths) // 6 + 1)  # sample top 3 three points from each attention head
        num_heads = self.attention_map.shape[0]
        self.inds = np.zeros((k * num_heads, 2))
        # "thresh" is used for visualisaiton purposes only
        thresh = torch.zeros(num_heads + 1, self.attention_map.shape[1], self.attention_map.shape[2])
        for i in range(num_heads):
            topk, indices = np.unique(self.attention_map[i].numpy(), return_index=True)
            topk = topk[::-1][:k]
            cur_attn_map = self.attention_map[i].numpy()
            # prob function for uniform sampling
            prob = cur_attn_map.flatten()
            prob[prob > topk[-1]] = 1
            prob[prob <= topk[-1]] = 0
            if prob.sum() < k:
                prob = cur_attn_map.flatten() + 1e-12
            prob = prob / prob.sum()
            thresh[i] = torch.Tensor(prob.reshape(cur_attn_map.shape))

            # choose k pixels from each head
            inds = np.random.choice(range(cur_attn_map.flatten().shape[0]), size=k, replace=False, p=prob)
            inds = np.unravel_index(inds, cur_attn_map.shape)
            self.inds[i * k: i * k + k, 0] = inds[0]
            self.inds[i * k: i * k + k, 1] = inds[1]

        # for visualisaiton
        sum_attn = self.attention_map.sum(0).numpy()
        mask = np.zeros(sum_attn.shape)
        mask[thresh[:-1].sum(0) > 0] = 1
        sum_attn = sum_attn * mask
        sum_attn = sum_attn / sum_attn.sum()
        thresh[-1] = torch.Tensor(sum_attn)

        # sample num_paths from the chosen pixels.
        prob_sum = sum_attn[self.inds[:, 0].astype(int), self.inds[:, 1].astype(int)]
        prob_sum = prob_sum + 1e-12
        prob_sum = prob_sum / prob_sum.sum()
        new_inds = []
        replace = self.inds.shape[0] < self.num_paths
        for _ in range(self.num_stages):
            new_inds.extend(np.random.choice(range(self.inds.shape[0]), size=self.num_paths, replace=replace,
                                             p=prob_sum))
        self.inds = self.inds[new_inds]

        self.inds_normalised = np.zeros(self.inds.shape)
        self.inds_normalised[:, 0] = self.inds[:, 1] / self.canvas_width
        self.inds_normalised[:, 1] = self.inds[:, 0] / self.canvas_height
        self.inds_normalised = self.inds_normalised.tolist()
        return thresh

    def set_attention_threshold_map(self):
        assert self.saliency_model in ["dino", "clip"]
        if self.saliency_model == "dino":
            return self.set_inds_dino()
        return self.set_inds_clip()

    def get_attn(self):
        return self.attention_map

    def get_thresh(self):
        return self.thresh

    def get_inds(self):
        return self.inds

    def get_mask(self):
        return self.mask

    def attention_preview(self):
        """PIL image: attention map over the input with the initial stroke positions (or None)."""
        if not self.attention_init:
            return None
        attn = self.attention_map
        if torch.is_tensor(attn):
            attn = attn.sum(0).numpy()
        return imaging.attention_overlay(self.target_im, attn, self.inds)

    def set_random_noise(self, epoch):
        if epoch % self.args.save_interval == 0:
            self.add_random_noise = False
        else:
            self.add_random_noise = "noise" in self.args.augemntations


class PainterOptimizer:
    def __init__(self, args, renderer):
        self.renderer = renderer
        self.points_lr = args.lr
        self.color_lr = args.color_lr
        self.args = args
        self.optim_color = args.force_sparse

    def init_optimizers(self):
        self.points_optim = torch.optim.Adam(self.renderer.parameters(), lr=self.points_lr)
        if self.optim_color:
            self.color_optim = torch.optim.Adam(self.renderer.set_color_parameters(), lr=self.color_lr)

    def update_lr(self, counter):
        new_lr = get_epoch_lr(counter, self.args)
        for param_group in self.points_optim.param_groups:
            param_group["lr"] = new_lr

    def zero_grad_(self):
        self.points_optim.zero_grad()
        if self.optim_color:
            self.color_optim.zero_grad()

    def step_(self):
        self.points_optim.step()
        if self.optim_color:
            self.color_optim.step()

    def get_lr(self):
        return self.points_optim.param_groups[0]['lr']


def get_epoch_lr(counter, args):
    """Learning-rate schedule used when ``lr_scheduler`` is on.

    The original code calls ``utils.get_epoch_lr`` which does not exist in the repository;
    this implements an exponential decay from ``lr`` to ``0.1 * lr`` over all iterations.
    """
    progress = min(max(counter / max(args.num_iter - 1, 1), 0.0), 1.0)
    return args.lr * (0.1 ** progress)


class Hook:
    """Attaches to a module and records its activations and gradients."""

    def __init__(self, module: nn.Module):
        self.data = None
        self.hook = module.register_forward_hook(self.save_grad)

    def save_grad(self, module, input, output):
        self.data = output
        output.requires_grad_(True)
        output.retain_grad()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.hook.remove()

    @property
    def activation(self) -> torch.Tensor:
        return self.data

    @property
    def gradient(self) -> torch.Tensor:
        return self.data.grad


def interpret(image, texts, model, device):
    """Relevance map of a CLIP ViT (Chefer et al.); generalised to any patch grid."""
    images = image.repeat(1, 1, 1, 1)
    image_attn_blocks = list(dict(model.visual.transformer.resblocks.named_children()).values())
    for blk in image_attn_blocks:
        blk.keep_attention = True
    try:
        model.encode_image(images.type(model.dtype))
    finally:
        for blk in image_attn_blocks:
            blk.keep_attention = False
    model.zero_grad()
    num_tokens = image_attn_blocks[0].attn_probs.shape[-1]
    R = torch.eye(num_tokens, num_tokens, dtype=image_attn_blocks[0].attn_probs.dtype).to(device)
    R = R.unsqueeze(0).expand(1, num_tokens, num_tokens)
    cams = []
    for blk in image_attn_blocks:
        cam = blk.attn_probs.detach()
        cam = cam.reshape(1, -1, cam.shape[-1], cam.shape[-1])
        cam = cam.clamp(min=0).mean(dim=1)
        cams.append(cam)
        R = R + torch.bmm(cam, R)

    cams_avg = torch.cat(cams)
    cams_avg = cams_avg[:, 0, 1:]
    image_relevance = cams_avg.mean(dim=0).unsqueeze(0)
    grid = int(round((num_tokens - 1) ** 0.5))
    size = image.shape[-1]
    image_relevance = image_relevance.reshape(1, 1, grid, grid).float()
    image_relevance = torch.nn.functional.interpolate(image_relevance, size=size, mode='bicubic')
    image_relevance = image_relevance.reshape(size, size).data.cpu().numpy().astype(np.float32)
    image_relevance = (image_relevance - image_relevance.min()) / (
        image_relevance.max() - image_relevance.min() + 1e-12)
    return image_relevance


# Reference: https://arxiv.org/abs/1610.02391
def gradCAM(model: nn.Module, input: torch.Tensor, target: torch.Tensor, layer: nn.Module) -> torch.Tensor:
    if input.grad is not None:
        input.grad.data.zero_()

    requires_grad = {}
    for name, param in model.named_parameters():
        requires_grad[name] = param.requires_grad
        param.requires_grad_(False)

    assert isinstance(layer, nn.Module)
    with torch.enable_grad(), Hook(layer) as hook:
        output = model(input)
        output.backward(target.type(output.dtype))

        grad = hook.gradient.float()
        act = hook.activation.float()
        alpha = grad.mean(dim=(2, 3), keepdim=True)
        gradcam = torch.sum(act * alpha, dim=1, keepdim=True)
        gradcam = torch.clamp(gradcam, min=0)

    gradcam = F.interpolate(gradcam, input.shape[2:], mode='bicubic', align_corners=False)

    for name, param in model.named_parameters():
        param.requires_grad_(requires_grad[name])

    return gradcam


class XDoG_(object):
    def __init__(self):
        super(XDoG_, self).__init__()
        self.gamma = 0.98
        self.phi = 200
        self.eps = -0.1
        self.sigma = 0.8
        self.binarize = True

    def __call__(self, im, k=10):
        if im.shape[2] == 3:
            im = imaging.rgb2gray(im)
        imf1 = imaging.gaussian_filter(im, self.sigma)
        imf2 = imaging.gaussian_filter(im, self.sigma * k)
        imdiff = imf1 - self.gamma * imf2
        imdiff = (imdiff < self.eps) * 1.0 + (imdiff >= self.eps) * (1.0 + np.tanh(self.phi * imdiff))
        imdiff -= imdiff.min()
        if imdiff.max() > 0:
            imdiff /= imdiff.max()
        if self.binarize:
            th = imaging.threshold_otsu(imdiff)
            imdiff = imdiff >= th
        imdiff = imdiff.astype('float32')
        return imdiff
