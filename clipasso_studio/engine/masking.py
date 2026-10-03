"""Background masking – the object mask of all methods.

``u2net`` is the U2Net port of ``sketch_utils.get_mask_u2net`` (what CLIPasso and SceneSketch use);
``birefnet`` / ``birefnet-lite`` use BiRefNet, a much more accurate segmentation network, in its place
(the default since 2.4). SwiftSketch and ControlSketch originally use BRIA RMBG-1.4, whose licence
does not allow redistribution; both networks stand in for it.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import numpy as np
from PIL import Image

from .. import paths
from ..settings_schema import DEFAULT_MASK_MODEL, MASK_MODELS  # noqa: F401 (re-exported)

OBJECT_THRESHOLD = 0.5  # BiRefNet probability from which a pixel belongs to the object

_cache: dict[tuple, np.ndarray] = {}  # the last BiRefNet result (the same image for every seed of a job)


def get_mask_u2net(device, pil_im: Image.Image, net=None):
    """Returns (masked image with white background, binary mask as PIL 'L' image at full size)."""
    import torch
    from torchvision import transforms
    from torchvision.transforms import InterpolationMode

    from . import nets

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
    return _on_white(pil_im, mask >= 0.5)


ROWS = 256  # image rows computed at a time: a 24-megapixel photo no longer needs gigabytes in float64


def _rows(height: int):
    return (slice(y, min(y + ROWS, height)) for y in range(0, height, ROWS))


def _whitened(im: np.ndarray, mask: np.ndarray, white) -> np.ndarray:
    """The image scaled to [0, 1] and multiplied by ``mask``, with 1 where ``white(mask)``, scaled to
    its maximum and as uint8 – per block of rows (computed twice: once for the maximum), with the same
    float64 arithmetic as the original whole-image version."""
    peak = max(float(im.max()), 1e-12)

    def block(rows):
        m = mask[rows].astype(np.float64)[:, :, None]
        b = m * (im[rows].astype(np.float64) / peak)
        b[np.broadcast_to(white(m), b.shape)] = 1
        return b

    top = max(max((float(block(r).max()) for r in _rows(im.shape[0])), default=0.0), 1e-12)
    out = np.empty(im.shape, dtype=np.uint8)
    for rows in _rows(im.shape[0]):
        out[rows] = (block(rows) / top * 255).astype(np.uint8)
    return out


def _on_white(pil_im: Image.Image, mask: np.ndarray) -> tuple[Image.Image, Image.Image]:
    """The image with everything outside the binary ``mask`` white, and the mask as an 'L' image."""
    im = np.asarray(pil_im)
    im_final = _whitened(im, mask, lambda m: m == 0)
    mask_img = Image.fromarray((np.asarray(mask, dtype=np.float32) * 255).astype(np.uint8), mode="L")
    return Image.fromarray(im_final), mask_img


def cache_dir() -> Path:
    """BiRefNet masks already computed (16-bit PNG per model and image)."""
    return paths.user_data_dir() / "cache" / "masks"


CACHE_KEEP = 100  # masks kept in the cache (the least recently used ones are removed)


def image_digest(im: Image.Image) -> str:
    """SHA-1 of the pixels of the loaded RGB image – identifies an input independent of its file."""
    return hashlib.sha1(im.convert("RGB").tobytes()).hexdigest()


def image_key(im: Image.Image, digest: str | None = None) -> str:
    return f"{im.width}x{im.height}-{(digest or image_digest(im))[:24]}"


# ------------------------------------------------------------------ masks edited by the user
def edited_dir() -> Path:
    """Masks touched up in the mask editor, one per image content (never removed automatically)."""
    return paths.user_data_dir() / "masks" / "edited"


def edited_mask_path(im: Image.Image, digest: str | None = None) -> Path:
    return edited_dir() / f"{image_key(im, digest)}.png"


def edited_mask(im: Image.Image, digest: str | None = None) -> np.ndarray | None:
    """The user's mask for this image (float32 0 / 1 at the image size), or None. It is used instead
    of the mask model by every method – the queue, parallel workers and Continue find it by the
    image content."""
    path = edited_mask_path(im, digest)
    try:
        with Image.open(path) as m:
            if m.size != im.size:
                return None
            return (np.asarray(m.convert("L")) >= 128).astype(np.float32)
    except (OSError, ValueError):
        return None


def save_edited_mask(im: Image.Image, mask: np.ndarray, digest: str | None = None) -> Path:
    path = edited_mask_path(im, digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + f".{os.getpid()}.tmp")
    Image.fromarray(((np.asarray(mask) > 0.5) * 255).astype(np.uint8), mode="L").save(tmp, format="PNG")
    os.replace(tmp, path)
    return path


def remove_edited_mask(im: Image.Image, digest: str | None = None) -> None:
    edited_mask_path(im, digest).unlink(missing_ok=True)


def edited_stamp(target: str) -> float:
    """Modification time of the edited mask of an input file (0 = none) – part of the input caches
    of the methods, so a new edit is never served from a cache."""
    from .imaging import load_rgb

    try:
        return edited_mask_path(load_rgb(target)).stat().st_mtime
    except OSError:
        return 0.0


@contextmanager
def _locked(lock: Path, stale: float = 30.0):
    """Only one process at a time computes a mask – parallel CLIPasso workers ask for the same one and
    then take it from the cache. The holder refreshes the lock file every few seconds, so a lock left
    by a killed process expires after ``stale`` seconds."""
    held = False
    while not held:
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            held = True
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > stale:
                    lock.unlink()
            except OSError:
                pass
            time.sleep(0.2)
        except OSError:  # no usable cache folder: go on without the lock
            break
    stop = threading.Event()

    def beat():
        while not stop.wait(5.0):
            try:
                os.utime(lock)
            except OSError:
                pass

    if held:
        threading.Thread(target=beat, daemon=True).start()
    try:
        yield
    finally:
        stop.set()
        if held:
            try:
                lock.unlink()
            except OSError:
                pass


def _read_cached(path: Path) -> np.ndarray | None:
    try:
        with Image.open(path) as im:
            prob = np.asarray(im, dtype=np.float32) / 65535.0
        os.utime(path)  # recently used
        return prob
    except (OSError, ValueError):
        return None


def _write_cached(path: Path, q: np.ndarray) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.stem + f".{os.getpid()}.tmp")
        Image.fromarray(q).save(tmp, format="PNG")
        os.replace(tmp, path)
        os.utime(path)
        old = sorted(path.parent.glob("*.png"), key=lambda f: f.stat().st_mtime, reverse=True)[CACHE_KEEP:]
        for f in old:
            f.unlink(missing_ok=True)
    except OSError:
        pass


def _predict(device, im: Image.Image, model: str, net=None) -> np.ndarray:
    import torch
    import torch.nn.functional as F

    from . import nets

    from .birefnet import MEAN, SIZE, STD

    x = torch.from_numpy(np.asarray(im.resize((SIZE, SIZE), Image.BILINEAR), dtype=np.float32) / 255.0)
    x = ((x - torch.tensor(MEAN)) / torch.tensor(STD)).permute(2, 0, 1)[None].to(device)
    own = net is None
    net = net or nets.load_birefnet(device, model)
    from .precision import half_precision

    # on a GPU in half precision: half the memory and about twice as fast at 1024 px
    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16, enabled=half_precision(device)):
        logits = net(x).float()
    prob = F.interpolate(logits.sigmoid(), size=(im.height, im.width), mode="bilinear", align_corners=False)
    prob = prob[0, 0].clamp(0, 1).cpu().numpy()
    if own:
        del net
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    return prob


def birefnet_probability(device, pil_im: Image.Image, model: str = DEFAULT_MASK_MODEL, net=None) -> np.ndarray:
    """Object probability in [0, 1] at the image size (float32 [H, W]) like BiRefNet's inference
    code: 1024 x 1024 (bilinear), ImageNet normalisation, sigmoid – then bilinear back to the image size.

    The result is rounded to 16 bits (so a mask from the cache equals a fresh one) and kept: the last
    one in memory (the seeds of a job), the last ``CACHE_KEEP`` on disk (the same image again, the
    parallel workers of a job). With an explicit ``net`` nothing is cached."""
    im = pil_im.convert("RGB")
    if net is not None:
        return _predict(device, im, model, net).astype(np.float32)
    digest = image_digest(im)
    key = (model, im.size, digest)
    if key in _cache:
        return _cache[key]
    path = cache_path(im, model, digest)
    prob = _read_cached(path)
    if prob is None:
        _make_folder(path.parent)
        with _locked(path.with_suffix(".lock")):
            prob = _read_cached(path)  # computed by another process meanwhile
            if prob is None:
                q = np.round(_predict(device, im, model) * 65535.0).astype(np.uint16)
                _write_cached(path, q)
                prob = q.astype(np.float32) / 65535.0
    _cache.clear()
    _cache[key] = prob
    return prob


def cache_path(im: Image.Image, model: str, digest: str | None = None) -> Path:
    return cache_dir() / f"{model}-{image_key(im, digest)}.png"


def cached_probability(im: Image.Image, model: str, digest: str | None = None) -> np.ndarray | None:
    """The mask of this image from the disk cache without computing it (the preview in the GUI)."""
    return _read_cached(cache_path(im, model, digest))


def preview_probability(device, im: Image.Image, model: str) -> np.ndarray:
    """The object probability the preview shows: BiRefNet's (cached like for a run), or U2Net's
    binary mask (``get_mask_u2net``, also kept in the cache for the preview)."""
    im = im.convert("RGB")
    if model != "u2net":
        return birefnet_probability(device, im, model)
    prob = cached_probability(im, "u2net")
    if prob is None:
        mask = np.asarray(get_mask_u2net(device, im)[1], dtype=np.float32) / 255.0
        _make_folder(cache_dir())
        _write_cached(cache_path(im, "u2net"), np.round(mask * 65535.0).astype(np.uint16))
        prob = mask
    return prob


def _make_folder(folder: Path) -> None:
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:  # no cache then
        pass


def get_mask(device, pil_im: Image.Image, model: str = DEFAULT_MASK_MODEL, net=None):
    """``get_mask_u2net`` with the chosen mask model: (image with white background, binary mask 'L').
    When BiRefNet finds no object, the whole picture is kept. A mask edited by the user wins."""
    edited = edited_mask(pil_im.convert("RGB"))
    if edited is not None:
        return _on_white(pil_im.convert("RGB"), edited.astype(np.float64))
    if model == "u2net":
        return get_mask_u2net(device, pil_im, net=net)
    mask = (birefnet_probability(device, pil_im, model, net) >= OBJECT_THRESHOLD).astype(np.float64)
    if not mask.any():
        mask[:] = 1
    return _on_white(pil_im.convert("RGB"), mask)


def u2net_soft_mask(device, pil_im: Image.Image, net=None) -> np.ndarray:
    """Soft foreground probability in [0, 1] at the image size (float32 [H, W]).

    Stands in for the BRIA RMBG-1.4 matte that SwiftSketch / ControlSketch use (``get_mask``):
    min-max normalised, bilinearly resized to the input resolution.
    """
    import torch
    from torchvision import transforms
    from torchvision.transforms import InterpolationMode

    from . import nets

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


def soft_mask(device, pil_im: Image.Image, model: str = DEFAULT_MASK_MODEL, net=None) -> np.ndarray:
    """Soft object matte in [0, 1] at the image size for SwiftSketch / ControlSketch, min-max
    normalised like RMBG-1.4's post-processing. When BiRefNet finds no object: all ones (the whole
    picture is kept). A mask edited by the user wins."""
    edited = edited_mask(pil_im.convert("RGB"))
    if edited is not None:
        return edited
    if model == "u2net":
        return u2net_soft_mask(device, pil_im, net=net)
    prob = birefnet_probability(device, pil_im, model, net)
    if float(prob.max()) < OBJECT_THRESHOLD:
        return np.ones_like(prob)
    return ((prob - prob.min()) / (prob.max() - prob.min() + 1e-12)).astype(np.float32)


def apply_soft_mask(pil_im: Image.Image, mask: np.ndarray) -> Image.Image:
    """``create_masked_image`` of SwiftSketch: multiply by the matte, pixels below the mean matte
    value become white."""
    mean = mask.mean()
    return Image.fromarray(_whitened(np.asarray(pil_im.convert("RGB")), mask, lambda m: m < mean))
