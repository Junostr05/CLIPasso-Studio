"""ControlNet condition images for ControlSketch (``conditions_controlnet.py``) without OpenCV /
controlnet_aux:

* depth    – MiDaS DPT-Hybrid (``Intel/dpt-hybrid-midas``, the network behind controlnet_aux'
             MidasDetector), normalised to 0..255
* normal   – normals from the DPT depth like the ``lllyasviel/sd-controlnet-normal`` model card
             (the original uses NormalBae + ControlNet 1.1 normalbae)
* canny    – a NumPy port of ``cv2.Canny(image, 100, 200)``
* hed      – HED soft edges (``ControlNetHED_Apache2`` from ControlNet 1.1, Apache-2.0); also used
             for ``scribble`` like the original
* seg      – UperNet ConvNeXt-small ADE20K segmentation with the ADE palette
"""

from __future__ import annotations

import math

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from torch import nn

from ... import model_store
from ..requirements import DETECTOR_MODELS  # noqa: F401



def _hf_offline() -> None:
    import os

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")


def _detect_size(w: int, h: int, resolution: int = 512) -> tuple[int, int]:
    """controlnet_aux ``resize_image``: short side -> resolution, both sides multiples of 64."""
    k = resolution / min(w, h)
    return max(64, int(round(w * k / 64.0)) * 64), max(64, int(round(h * k / 64.0)) * 64)


def _to_pil(gray_or_rgb: np.ndarray, size: tuple[int, int]) -> Image.Image:
    arr = gray_or_rgb if gray_or_rgb.ndim == 3 else np.repeat(gray_or_rgb[:, :, None], 3, axis=2)
    img = Image.fromarray(arr.astype(np.uint8))
    return img if img.size == size else img.resize(size, Image.BILINEAR)


# ----------------------------------------------------------------------------- depth / normal


def _dpt_depth(image: Image.Image, device) -> np.ndarray:
    _hf_offline()
    from transformers import DPTForDepthEstimation

    model = DPTForDepthEstimation.from_pretrained(str(model_store.model_dir("dpt-hybrid")),
                                                  torch_dtype=torch.float32).to(device).eval()
    w, h = _detect_size(*image.size)
    x = torch.from_numpy(np.asarray(image.convert("RGB").resize((w, h), Image.BICUBIC), dtype=np.float32))
    x = (x / 127.5 - 1.0).permute(2, 0, 1)[None].to(device)
    emb = model.dpt.embeddings
    if hasattr(emb, "image_size"):  # MiDaS runs DPT at the detection size (position embeddings are resized)
        emb.image_size = (h, w)
    with torch.no_grad():
        depth = model(pixel_values=x).predicted_depth[0].float().cpu().numpy()
    del model
    return depth


def depth_condition(image: Image.Image, device) -> Image.Image:
    depth = _dpt_depth(image, device)
    depth = depth - depth.min()
    depth = depth / max(depth.max(), 1e-12)
    return _to_pil((depth * 255.0).clip(0, 255), image.size)


def _sobel(img: np.ndarray, dx: int, dy: int) -> np.ndarray:
    """``cv2.Sobel(img, CV_32F, dx, dy, ksize=3)`` (BORDER_REFLECT_101)."""
    p = np.pad(img.astype(np.float32), 1, mode="reflect")
    if dx:
        return (p[:-2, 2:] - p[:-2, :-2]) + 2 * (p[1:-1, 2:] - p[1:-1, :-2]) + (p[2:, 2:] - p[2:, :-2])
    return (p[2:, :-2] - p[:-2, :-2]) + 2 * (p[2:, 1:-1] - p[:-2, 1:-1]) + (p[2:, 2:] - p[:-2, 2:])


def normal_from_depth(depth: np.ndarray, bg_threshold: float = 0.4) -> np.ndarray:
    norm = depth - depth.min()
    norm = norm / max(norm.max(), 1e-12)
    x = _sobel(depth, 1, 0)
    y = _sobel(depth, 0, 1)
    x[norm < bg_threshold] = 0
    y[norm < bg_threshold] = 0
    z = np.ones_like(x) * np.pi * 2.0
    n = np.stack([x, y, z], axis=2)
    n /= np.sum(n ** 2.0, axis=2, keepdims=True) ** 0.5
    return (n * 127.5 + 127.5).clip(0, 255).astype(np.uint8)


def normal_condition(image: Image.Image, device) -> Image.Image:
    return _to_pil(normal_from_depth(_dpt_depth(image, device)), image.size)


# ----------------------------------------------------------------------------- canny


def canny(image: np.ndarray, low: float = 100, high: float = 200) -> np.ndarray:
    """Port of ``cv2.Canny`` (3x3 Sobel, L1 gradient, per-pixel strongest channel) -> uint8 0/255."""
    img = np.asarray(image, dtype=np.float32)
    if img.ndim == 2:
        img = img[:, :, None]
    p = np.pad(img, ((1, 1), (1, 1), (0, 0)), mode="edge")
    gx = (p[:-2, 2:] - p[:-2, :-2]) + 2 * (p[1:-1, 2:] - p[1:-1, :-2]) + (p[2:, 2:] - p[2:, :-2])
    gy = (p[2:, :-2] - p[:-2, :-2]) + 2 * (p[2:, 1:-1] - p[:-2, 1:-1]) + (p[2:, 2:] - p[:-2, 2:])
    mag_c = np.abs(gx) + np.abs(gy)
    best = mag_c.argmax(axis=2)[:, :, None]
    gx = np.take_along_axis(gx, best, 2)[:, :, 0]
    gy = np.take_along_axis(gy, best, 2)[:, :, 0]
    mag = np.take_along_axis(mag_c, best, 2)[:, :, 0]
    h, w = mag.shape
    m = np.pad(mag, 1)  # zero border
    c = m[1:-1, 1:-1]
    ax, ay = np.abs(gx), np.abs(gy)
    tg22 = ax * math.tan(math.pi / 8)
    tg67 = tg22 + 2 * ax
    horiz = ay < tg22
    vert = (~horiz) & (ay > tg67)
    diag = ~(horiz | vert)
    s = np.where((gx * gy) < 0, -1, 1)
    keep = np.zeros_like(mag, dtype=bool)
    keep |= horiz & (c > m[1:-1, :-2]) & (c >= m[1:-1, 2:])
    keep |= vert & (c > m[:-2, 1:-1]) & (c >= m[2:, 1:-1])
    left_up = m[:-2, :-2]
    right_up = m[:-2, 2:]
    left_down = m[2:, :-2]
    right_down = m[2:, 2:]
    prev_diag = np.where(s < 0, right_up, left_up)  # (y-1, x-s)
    next_diag = np.where(s < 0, left_down, right_down)  # (y+1, x+s)
    keep |= diag & (c > prev_diag) & (c > next_diag)
    candidate = keep & (mag > low)
    strong = candidate & (mag > high)
    # hysteresis: grow the strong edges through 8-connected candidates
    edges = torch.from_numpy(strong.astype(np.float32))[None, None]
    cand = torch.from_numpy(candidate.astype(np.float32))[None, None]
    while True:
        grown = F.max_pool2d(edges, 3, stride=1, padding=1) * cand
        if torch.equal(grown, edges):
            break
        edges = grown
    out = edges[0, 0].numpy() > 0
    out[0, :] = out[-1, :] = False
    out[:, 0] = out[:, -1] = False
    return (out * 255).astype(np.uint8)


def canny_condition(image: Image.Image, device=None) -> Image.Image:
    return _to_pil(canny(np.asarray(image.convert("RGB"))), image.size)


# ----------------------------------------------------------------------------- HED


class _DoubleConvBlock(nn.Module):
    def __init__(self, input_channel: int, output_channel: int, layer_number: int):
        super().__init__()
        self.convs = nn.Sequential()
        self.convs.append(nn.Conv2d(input_channel, output_channel, kernel_size=3, stride=1, padding=1))
        for _ in range(1, layer_number):
            self.convs.append(nn.Conv2d(output_channel, output_channel, kernel_size=3, stride=1, padding=1))
        self.projection = nn.Conv2d(output_channel, 1, kernel_size=1, stride=1, padding=0)

    def forward(self, x, down_sampling: bool = False):
        h = F.max_pool2d(x, kernel_size=2, stride=2) if down_sampling else x
        for conv in self.convs:
            h = F.relu(conv(h))
        return h, self.projection(h)


class ControlNetHED(nn.Module):
    """``ControlNetHED_Apache2`` (lllyasviel, ControlNet 1.1 annotators, Apache-2.0)."""

    def __init__(self):
        super().__init__()
        self.norm = nn.Parameter(torch.zeros(size=(1, 3, 1, 1)))
        self.block1 = _DoubleConvBlock(3, 64, 2)
        self.block2 = _DoubleConvBlock(64, 128, 2)
        self.block3 = _DoubleConvBlock(128, 256, 3)
        self.block4 = _DoubleConvBlock(256, 512, 3)
        self.block5 = _DoubleConvBlock(512, 512, 3)

    def forward(self, x):
        h = x - self.norm
        h, p1 = self.block1(h)
        h, p2 = self.block2(h, down_sampling=True)
        h, p3 = self.block3(h, down_sampling=True)
        h, p4 = self.block4(h, down_sampling=True)
        h, p5 = self.block5(h, down_sampling=True)
        return p1, p2, p3, p4, p5


def load_hed(device) -> ControlNetHED:
    from safetensors.torch import load_file

    net = ControlNetHED()
    net.load_state_dict(load_file(str(model_store.model_dir("hed") / "ControlNetHED.safetensors")))
    return net.float().to(device).eval().requires_grad_(False)


def hed_edges(image: Image.Image, net: ControlNetHED, device) -> np.ndarray:
    w, h = _detect_size(*image.size)
    arr = np.asarray(image.convert("RGB").resize((w, h), Image.LANCZOS if w > image.size[0] else Image.BOX),
                     dtype=np.float32)
    x = torch.from_numpy(arr).permute(2, 0, 1)[None].to(device)
    with torch.no_grad():
        edges = [F.interpolate(e.float(), size=(h, w), mode="bilinear", align_corners=False)[0, 0]
                 for e in net(x)]
    edge = torch.sigmoid(torch.stack(edges, 0).mean(0)).cpu().numpy()
    return (edge * 255.0).clip(0, 255).astype(np.uint8)


def hed_condition(image: Image.Image, device) -> Image.Image:
    return _to_pil(hed_edges(image, load_hed(device), device), image.size)


# ----------------------------------------------------------------------------- seg

# ADE20K palette used by ControlNet's segmentation model (150 classes)
ADE_PALETTE = np.asarray([
    [0, 0, 0], [120, 120, 120], [180, 120, 120], [6, 230, 230], [80, 50, 50], [4, 200, 3], [120, 120, 80],
    [140, 140, 140], [204, 5, 255], [230, 230, 230], [4, 250, 7], [224, 5, 255], [235, 255, 7], [150, 5, 61],
    [120, 120, 70], [8, 255, 51], [255, 6, 82], [143, 255, 140], [204, 255, 4], [255, 51, 7], [204, 70, 3],
    [0, 102, 200], [61, 230, 250], [255, 6, 51], [11, 102, 255], [255, 7, 71], [255, 9, 224], [9, 7, 230],
    [220, 220, 220], [255, 9, 92], [112, 9, 255], [8, 255, 214], [7, 255, 224], [255, 184, 6], [10, 255, 71],
    [255, 41, 10], [7, 255, 255], [224, 255, 8], [102, 8, 255], [255, 61, 6], [255, 194, 7], [255, 122, 8],
    [0, 255, 20], [255, 8, 41], [255, 5, 153], [6, 51, 255], [235, 12, 255], [160, 150, 20], [0, 163, 255],
    [140, 140, 140], [250, 10, 15], [20, 255, 0], [31, 255, 0], [255, 31, 0], [255, 224, 0], [153, 255, 0],
    [0, 0, 255], [255, 71, 0], [0, 235, 255], [0, 173, 255], [31, 0, 255], [11, 200, 200], [255, 82, 0],
    [0, 255, 245], [0, 61, 255], [0, 255, 112], [0, 255, 133], [255, 0, 0], [255, 163, 0], [255, 102, 0],
    [194, 255, 0], [0, 143, 255], [51, 255, 0], [0, 82, 255], [0, 255, 41], [0, 255, 173], [10, 0, 255],
    [173, 255, 0], [0, 255, 153], [255, 92, 0], [255, 0, 255], [255, 0, 245], [255, 0, 102], [255, 173, 0],
    [255, 0, 20], [255, 184, 184], [0, 31, 255], [0, 255, 61], [0, 71, 255], [255, 0, 204], [0, 255, 194],
    [0, 255, 82], [0, 10, 255], [0, 112, 255], [51, 0, 255], [0, 194, 255], [0, 122, 255], [0, 255, 163],
    [255, 153, 0], [0, 255, 10], [255, 112, 0], [143, 255, 0], [82, 0, 255], [163, 255, 0], [255, 235, 0],
    [8, 184, 170], [133, 0, 255], [0, 255, 92], [184, 0, 255], [255, 0, 31], [0, 184, 255], [0, 214, 255],
    [255, 0, 112], [92, 255, 0], [0, 224, 255], [112, 224, 255], [70, 184, 160], [163, 0, 255], [153, 0, 255],
    [71, 255, 0], [255, 0, 163], [255, 204, 0], [255, 0, 143], [0, 255, 235], [133, 255, 0], [255, 0, 235],
    [245, 0, 255], [255, 0, 122], [255, 245, 0], [10, 190, 212], [214, 255, 0], [0, 204, 255], [20, 0, 255],
    [255, 255, 0], [0, 153, 255], [0, 41, 255], [0, 255, 204], [41, 0, 255], [41, 255, 0], [173, 0, 255],
    [0, 245, 255], [71, 0, 255], [122, 0, 255], [0, 255, 184], [0, 92, 255], [184, 255, 0], [0, 133, 255],
    [255, 214, 0], [25, 194, 194], [102, 255, 0], [92, 0, 255],
], dtype=np.uint8)

_IMAGENET_MEAN = (0.485, 0.456, 0.406)
_IMAGENET_STD = (0.229, 0.224, 0.225)


def seg_condition(image: Image.Image, device) -> Image.Image:
    _hf_offline()
    from transformers import UperNetForSemanticSegmentation

    model = UperNetForSemanticSegmentation.from_pretrained(str(model_store.model_dir("upernet")),
                                                           torch_dtype=torch.float32).to(device).eval()
    x = torch.from_numpy(np.asarray(image.convert("RGB").resize((512, 512), Image.BILINEAR), dtype=np.float32))
    x = x.permute(2, 0, 1)[None] / 255.0
    x = (x - torch.tensor(_IMAGENET_MEAN).view(1, 3, 1, 1)) / torch.tensor(_IMAGENET_STD).view(1, 3, 1, 1)
    with torch.no_grad():
        logits = model(pixel_values=x.to(device)).logits
        logits = F.interpolate(logits.float(), size=image.size[::-1], mode="bilinear", align_corners=False)
    seg = logits.argmax(dim=1)[0].cpu().numpy()
    del model
    return Image.fromarray(ADE_PALETTE[np.clip(seg, 0, len(ADE_PALETTE) - 1)])


# ----------------------------------------------------------------------------- common


def create_condition(image: Image.Image, condition: str, device) -> Image.Image:
    fn = {"depth": depth_condition, "normal": normal_condition, "canny": canny_condition, "hed": hed_condition,
          "scribble": hed_condition, "seg": seg_condition}[condition]
    return fn(image, device)


def masked_condition(condition: Image.Image, mask: torch.Tensor, size: int) -> Image.Image:
    """``creat_masked_condition``: keep the condition on the object only."""
    m = mask.float().cpu().numpy()
    cond = condition.convert("RGB")
    if cond.size != (m.shape[1], m.shape[0]):
        cond = cond.resize((m.shape[1], m.shape[0]), Image.BILINEAR)
    im = np.asarray(cond, dtype=np.float64)
    im = im / max(im.max(), 1e-12)
    im = m[:, :, None] * im
    im[m < m.mean()] = 0
    im = (im / max(im.max(), 1e-12) * 255).astype(np.uint8)
    return Image.fromarray(im).resize((size, size))


def condition_tensor(condition: Image.Image, size: int, device, dtype) -> torch.Tensor:
    """``preprocessing_image_condtion``: resize (bilinear), centre crop, [0, 1] tensor [1, 3, S, S]."""
    from torchvision import transforms

    tf = transforms.Compose([
        transforms.Resize(size, interpolation=transforms.InterpolationMode.BILINEAR),
        transforms.CenterCrop(size),
        transforms.ToTensor(),
    ])
    return tf(condition.convert("RGB")).unsqueeze(0).to(device=device, dtype=dtype)
