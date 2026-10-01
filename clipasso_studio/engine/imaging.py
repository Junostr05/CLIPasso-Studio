"""Small image helpers replacing the scipy / scikit-image / matplotlib calls of the original code."""

from __future__ import annotations

import math

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image


def load_rgb(path: str) -> Image.Image:
    """The input image as RGB; transparent areas become white (like the original ``get_target``)."""
    target = Image.open(path)
    if target.mode in ("RGBA", "LA") or (target.mode == "P" and "transparency" in target.info):
        target = target.convert("RGBA")
        new_image = Image.new("RGBA", target.size, "WHITE")
        new_image.paste(target, (0, 0), target)
        target = new_image
    return target.convert("RGB")


def _gauss_kernel(sigma: float, truncate: float = 4.0) -> torch.Tensor:
    radius = int(truncate * float(sigma) + 0.5)
    x = torch.arange(-radius, radius + 1, dtype=torch.float64)
    k = torch.exp(-0.5 * (x / sigma) ** 2)
    return k / k.sum()


def _pad_reflect(x: torch.Tensor, r: int, dim: int) -> torch.Tensor:
    """Pad like scipy.ndimage mode 'reflect' (d c b a | a b c d | d c b a)."""
    n = x.shape[dim]
    idx = []
    for i in range(-r, n + r):
        m = i % (2 * n)
        idx.append(m if m < n else 2 * n - 1 - m)
    return x.index_select(dim, torch.tensor(idx, dtype=torch.long))


def gaussian_filter(im: np.ndarray, sigma: float) -> np.ndarray:
    """Equivalent of ``scipy.ndimage.gaussian_filter(im, sigma)`` for 2D arrays."""
    t = torch.from_numpy(np.asarray(im, dtype=np.float64))
    k = _gauss_kernel(sigma)
    r = (k.numel() - 1) // 2
    t = _pad_reflect(t, r, 0)
    t = _pad_reflect(t, r, 1)
    t = F.conv2d(t[None, None], k.view(1, 1, -1, 1))
    t = F.conv2d(t, k.view(1, 1, 1, -1))
    return t[0, 0].numpy()


def rgb2gray(im: np.ndarray) -> np.ndarray:
    """Same luminance weights as ``skimage.color.rgb2gray``."""
    return im[..., 0] * 0.2125 + im[..., 1] * 0.7154 + im[..., 2] * 0.0721


def threshold_otsu(image: np.ndarray, nbins: int = 256) -> float:
    """Port of ``skimage.filters.threshold_otsu``."""
    image = np.asarray(image, dtype=np.float64)
    lo, hi = float(image.min()), float(image.max())
    if lo == hi:
        return lo
    hist, edges = np.histogram(image.ravel(), bins=nbins, range=(lo, hi))
    centers = (edges[:-1] + edges[1:]) / 2.0
    hist = hist.astype(np.float64)
    w1 = np.cumsum(hist)
    w2 = np.cumsum(hist[::-1])[::-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        m1 = np.cumsum(hist * centers) / w1
        m2 = (np.cumsum((hist * centers)[::-1]) / w2[::-1])[::-1]
    var12 = w1[:-1] * w2[1:] * (m1[:-1] - m2[1:]) ** 2
    var12 = np.nan_to_num(var12, nan=-1.0)
    return float(centers[int(np.argmax(var12))])


def fix_image_scale(im: Image.Image, fill: int | tuple = 255) -> Image.Image:
    """Pad a non-square image to a square with a 10px margin (``sketch_utils.fix_image_scale``)."""
    im_np = np.array(im)
    height, width = im_np.shape[0], im_np.shape[1]
    max_len = max(height, width) + 20
    shape = (max_len, max_len) + im_np.shape[2:]
    new = np.full(shape, fill, dtype=np.uint8)
    y, x = max_len // 2 - height // 2, max_len // 2 - width // 2
    new[y: y + height, x: x + width] = im_np
    return Image.fromarray(new)


# A compact "viridis"-like colormap for attention map previews (no matplotlib needed).
_VIRIDIS = np.array([
    [68, 1, 84], [72, 35, 116], [64, 67, 135], [52, 94, 141], [41, 120, 142], [32, 144, 140],
    [34, 167, 132], [68, 190, 112], [121, 209, 81], [189, 222, 38], [253, 231, 37],
], dtype=np.float64)


def colormap(values: np.ndarray) -> np.ndarray:
    """Map values in [0, 1] to uint8 RGB."""
    v = np.clip(np.nan_to_num(values), 0, 1) * (len(_VIRIDIS) - 1)
    lo = np.floor(v).astype(int)
    hi = np.minimum(lo + 1, len(_VIRIDIS) - 1)
    frac = (v - lo)[..., None]
    rgb = _VIRIDIS[lo] * (1 - frac) + _VIRIDIS[hi] * frac
    return rgb.astype(np.uint8)


def tensor_to_pil(img: torch.Tensor) -> Image.Image:
    """[1,3,H,W] or [3,H,W] tensor in [0,1] -> PIL image."""
    if img.dim() == 4:
        img = img[0]
    arr = img.detach().float().clamp(0, 1).permute(1, 2, 0).cpu().numpy()
    return Image.fromarray((arr * 255 + 0.5).astype(np.uint8))


def attention_overlay(image: torch.Tensor, attn: np.ndarray, points: np.ndarray | None = None) -> Image.Image:
    """Blend an attention map over the input image and mark the initial stroke positions."""
    base = np.asarray(tensor_to_pil(image).convert("RGB"), dtype=np.float64)
    a = np.asarray(attn, dtype=np.float64)
    if a.shape != base.shape[:2]:
        a = np.asarray(Image.fromarray(a.astype(np.float32)).resize((base.shape[1], base.shape[0]),
                                                                     Image.BILINEAR))
    rng = a.max() - a.min()
    a = (a - a.min()) / rng if rng > 0 else np.zeros_like(a)
    heat = colormap(a).astype(np.float64)
    out = (0.45 * base + 0.55 * heat).astype(np.uint8)
    if points is not None:
        h, w = out.shape[:2]
        for (py, px) in np.asarray(points).reshape(-1, 2):
            cy, cx = int(round(py)), int(round(px))
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    if dy * dy + dx * dx <= 5 and 0 <= cy + dy < h and 0 <= cx + dx < w:
                        out[cy + dy, cx + dx] = (239, 68, 68)
    return Image.fromarray(out)


def eta_string(seconds: float) -> str:
    if not math.isfinite(seconds) or seconds < 0:
        return "–"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
