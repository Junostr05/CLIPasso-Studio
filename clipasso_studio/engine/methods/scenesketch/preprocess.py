"""Scene preprocessing of SceneSketch (``preprocess_images.py`` and ``sketch_utils.get_mask_u2net``).

* the scene is made square (centre crop, or white padding with ``fix_scale``) and at most 512 px;
* U2Net (with its own preprocessing: 320x320, ImageNet normalisation) finds the foreground object –
  or BiRefNet (``mask_model``), at the scene size;
* LaMa fills in the object area (mask dilated by 11x11 at 320 px) -> the background image;
* the object image is the scene with a white background; with ``resize_obj`` a single, small
  object is enlarged to 70 % of the canvas for sketching and scaled back when the sketches are
  combined (``resize_params``).
"""

from __future__ import annotations

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

MAX_SIZE = 512


def square_scene(image: Image.Image, fix_scale: bool) -> Image.Image:
    """Square version of the input (SceneSketch expects square scenes), at most 512 px."""
    image = image.convert("RGB")
    w, h = image.size
    if w != h:
        if fix_scale:
            side = max(w, h)
            canvas = Image.new("RGB", (side, side), "white")
            canvas.paste(image, ((side - w) // 2, (side - h) // 2))
            image = canvas
        else:
            side = min(w, h)
            left, top = (w - side) // 2, (h - side) // 2
            image = image.crop((left, top, left + side, top + side))
    if image.size[0] > MAX_SIZE:
        image = image.resize((MAX_SIZE, MAX_SIZE), Image.BICUBIC)
    return image


def u2net_probability(image: Image.Image, device, net=None) -> torch.Tensor:
    """U2Net saliency, min-max normalised, at 320x320 (``RescaleT(320)`` + ``ToTensorLab(flag=0)``)."""
    from ... import nets

    im = np.asarray(image.convert("RGB").resize((320, 320), Image.BILINEAR), dtype=np.float64) / 255.0
    im = im / max(im.max(), 1e-12)
    mean, std = np.array([0.485, 0.456, 0.406]), np.array([0.229, 0.224, 0.225])
    x = torch.from_numpy(((im - mean) / std).transpose(2, 0, 1)).float().unsqueeze(0).to(device)
    net = net or nets.load_u2net(device)
    with torch.no_grad():
        pred = net(x)[0][0, 0].float()
    return ((pred - pred.min()) / (pred.max() - pred.min() + 1e-12)).cpu()


def object_probability(image: Image.Image, device, model: str = "u2net") -> torch.Tensor:
    """Object probability: U2Net's at 320x320 (``u2net_probability``) or BiRefNet's at the image size."""
    if model == "u2net":
        return u2net_probability(image, device)
    from ... import masking

    return torch.from_numpy(masking.birefnet_probability(device, image, model))


def object_mask(prob: torch.Tensor, size: int) -> np.ndarray:
    """Binary object mask at the scene size (``get_mask_u2net``: threshold, bilinear resize, threshold)."""
    binary = (prob >= 0.5).float()[None, None]
    m = F.interpolate(binary, size=(size, size), mode="bilinear", align_corners=False)[0, 0]
    return (m >= 0.5).numpy().astype(np.float32)


def inpaint_mask(prob: torch.Tensor, size: int) -> np.ndarray:
    """Dilated mask for the inpainting (``get_U2Net_mask`` of preprocess_images.py: 11x11 at 320 px,
    scaled for a probability map of another size)."""
    binary = (prob >= 0.5).float()[None, None]
    k = max(3, round(11 * prob.shape[-1] / 320) // 2 * 2 + 1)
    dilated = F.max_pool2d(binary, kernel_size=k, stride=1, padding=k // 2)
    m = F.interpolate(dilated, size=(size, size), mode="nearest")[0, 0]
    return (m >= 0.5).numpy().astype(np.float32)


def inpaint_background(image: Image.Image, mask: np.ndarray, device, net=None) -> Image.Image:
    from .lama import inpaint, load_lama

    net = net or load_lama(device)
    x = torch.from_numpy(np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0).permute(2, 0, 1)[None]
    m = torch.from_numpy(mask)[None, None]
    out = inpaint(net, x.to(device), m.to(device))
    arr = (out[0].permute(1, 2, 0).float().cpu().numpy() * 255).round().clip(0, 255).astype(np.uint8)
    return Image.fromarray(arr)


# ------------------------------------------------------------------------------ object resizing


def _components(mask: np.ndarray, connectivity: int) -> tuple[np.ndarray, int]:
    """Connected components (labels start at 1) by iterated max-propagation of pixel ids."""
    m = torch.from_numpy(mask > 0)
    if not bool(m.any()):
        return np.zeros(mask.shape, dtype=np.int64), 0
    ids = torch.arange(1, m.numel() + 1, dtype=torch.float64).reshape(m.shape) * m
    x = ids[None, None]
    fm = m.double()[None, None]
    for _ in range(4 * max(mask.shape)):
        if connectivity == 2:
            nxt = F.max_pool2d(x, 3, stride=1, padding=1)
        else:
            p = F.pad(x, (1, 1, 1, 1))
            nxt = torch.stack([x, p[..., :-2, 1:-1], p[..., 2:, 1:-1], p[..., 1:-1, :-2], p[..., 1:-1, 2:]]).amax(0)
        nxt = nxt * fm
        if torch.equal(nxt, x):
            break
        x = nxt
    labels = x[0, 0].numpy()
    uniq = np.unique(labels[labels > 0])
    out = np.zeros(mask.shape, dtype=np.int64)
    for i, u in enumerate(uniq, start=1):
        out[labels == u] = i
    return out, len(uniq)


def _resize_array(arr: np.ndarray, h: int, w: int) -> np.ndarray:
    t = torch.from_numpy(np.ascontiguousarray(arr, dtype=np.float32)).permute(2, 0, 1)[None]
    t = F.interpolate(t, size=(h, w), mode="bilinear", align_corners=False, antialias=True)
    return t[0].permute(1, 2, 0).numpy().astype(np.float64)


def _cut_and_resize(im: np.ndarray, x0, x1, y0, y1, new_h, new_w) -> np.ndarray:
    resized = _resize_array(im[y0:y1, x0:x1], new_h, new_w)
    out = np.zeros(im.shape)
    cy, cx = out.shape[0] // 2, out.shape[1] // 2
    sy, sx = cy - new_h // 2, cx - new_w // 2
    out[sy: sy + new_h, sx: sx + new_w] = resized
    return out


def object_target(image: Image.Image, mask: np.ndarray, resize_obj: bool) -> tuple[Image.Image, np.ndarray, dict]:
    """(object on white, its mask, resize params) – ``get_mask_u2net`` with ``mask_object`` and ``resize_obj``."""
    h, w = mask.shape
    im_np = np.asarray(image.convert("RGB"), dtype=np.float64)
    im_np = im_np / max(im_np.max(), 1e-12)
    mask3 = np.repeat(mask[:, :, None].astype(np.float64), 3, axis=2)
    params: dict = {}
    if resize_obj and mask.sum() > 0:
        labels, num = _components(mask, connectivity=2)
        sizes = np.bincount(labels.ravel())[1:]
        min_size = int(sizes.max() / 3)
        # remove_small_objects (4-connectivity) keeps components with at least min_size pixels
        labels4, num4 = _components(mask, connectivity=1)
        sizes4 = np.bincount(labels4.ravel())
        keep = (sizes4 >= min_size)
        keep[0] = False
        mask2 = keep[labels4].astype(np.float64)
        _, num_cc = _components(mask2, connectivity=2)
        if mask2.sum() > 0:
            ys, xs = np.nonzero(mask2)
            x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
            obj_w, obj_h = x1 - x0, y1 - y0
            target_size = int(min(h, w) * 0.7)
            if max(obj_w, obj_h) < target_size and num_cc == 1 and obj_w > 0 and obj_h > 0:
                if obj_w > obj_h:
                    new_w, new_h = target_size, int((target_size / obj_w) * obj_h)
                else:
                    new_w, new_h = int((target_size / obj_h) * obj_w), target_size
                mask3 = _cut_and_resize(np.repeat(mask2[:, :, None], 3, axis=2), x0, x1, y0, y1, new_h, new_w)
                im_np = _cut_and_resize(im_np, x0, x1, y0, y1, new_h, new_w)
                params = {"original_center_y": (y0 + (y1 - y0) / 2) / h,
                          "original_center_x": (x0 + (x1 - x0) / 2) / w,
                          "scale_w": new_w / obj_w, "scale_h": new_h / obj_h}
    out = mask3 * im_np
    out[mask3 == 0] = 1
    out = (out / max(out.max(), 1e-12) * 255).astype(np.uint8)
    return Image.fromarray(out), mask3[:, :, 0], params
