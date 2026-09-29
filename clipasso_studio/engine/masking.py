"""Background masking with U2Net – port of ``sketch_utils.get_mask_u2net``."""

from __future__ import annotations

import numpy as np
import torch
from PIL import Image
from torchvision import transforms
from torchvision.transforms import InterpolationMode

from . import nets


def get_mask_u2net(device, pil_im: Image.Image, net=None):
    """Returns (masked image with white background, binary mask as PIL 'L' image at full size)."""
    w, h = pil_im.size[0], pil_im.size[1]
    im_size = min(w, h)
    data_transforms = transforms.Compose([
        transforms.Resize(min(320, im_size), interpolation=InterpolationMode.BICUBIC),
        transforms.ToTensor(),
        transforms.Normalize(mean=(0.48145466, 0.4578275, 0.40821073), std=(0.26862954, 0.26130258, 0.27577711)),
    ])

    input_im_trans = data_transforms(pil_im).unsqueeze(0).to(device)
    net = net or nets.load_u2net(device)
    with torch.no_grad():
        d1, d2, d3, d4, d5, d6, d7 = net(input_im_trans.detach())
    pred = d1[:, 0, :, :]
    pred = (pred - pred.min()) / (pred.max() - pred.min() + 1e-12)
    predict = pred
    predict[predict < 0.5] = 0
    predict[predict >= 0.5] = 1

    # resize back to the input size (bilinear like skimage.transform.resize) and re-binarise
    small = predict[0].cpu().numpy().astype(np.float32)
    mask = np.asarray(Image.fromarray(small, mode="F").resize((w, h), Image.BILINEAR))
    mask = (mask >= 0.5).astype(np.float64)
    mask3 = np.repeat(mask[:, :, None], 3, axis=2)

    im_np = np.array(pil_im).astype(np.float64)
    im_np = im_np / max(im_np.max(), 1e-12)
    im_np = mask3 * im_np
    im_np[mask3 == 0] = 1
    im_final = (im_np / max(im_np.max(), 1e-12) * 255).astype(np.uint8)
    mask_img = Image.fromarray((mask * 255).astype(np.uint8), mode="L")
    return Image.fromarray(im_final), mask_img


def u2net_soft_mask(device, pil_im: Image.Image, net=None) -> np.ndarray:
    """Soft foreground probability in [0, 1] at the image size (float32 [H, W]).

    Stands in for the BRIA RMBG-1.4 matte that SwiftSketch / ControlSketch use (``get_mask``):
    min-max normalised, bilinearly resized to the input resolution.
    """
    w, h = pil_im.size
    tf = transforms.Compose([
        transforms.Resize(min(320, min(w, h)), interpolation=InterpolationMode.BICUBIC),
        transforms.ToTensor(),
        transforms.Normalize(mean=(0.48145466, 0.4578275, 0.40821073), std=(0.26862954, 0.26130258, 0.27577711)),
    ])
    net = net or nets.load_u2net(device)
    with torch.no_grad():
        d1 = net(tf(pil_im.convert("RGB")).unsqueeze(0).to(device))[0]
    pred = d1[0, 0].float()
    pred = (pred - pred.min()) / (pred.max() - pred.min() + 1e-12)
    mask = torch.nn.functional.interpolate(pred[None, None], size=(h, w), mode="bilinear", align_corners=False)
    return mask[0, 0].clamp(0, 1).cpu().numpy().astype(np.float32)


def apply_soft_mask(pil_im: Image.Image, mask: np.ndarray) -> Image.Image:
    """``create_masked_image`` of SwiftSketch: multiply by the matte, pixels below the mean matte
    value become white."""
    im = np.asarray(pil_im.convert("RGB")).astype(np.float64)
    im = im / max(im.max(), 1e-12)
    im = mask[:, :, None] * im
    im[mask < mask.mean()] = 1
    return Image.fromarray((im / max(im.max(), 1e-12) * 255).astype(np.uint8))
