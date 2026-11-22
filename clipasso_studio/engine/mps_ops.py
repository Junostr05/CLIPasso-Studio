"""Operations PyTorch lacks a backward pass for on the Apple GPU (MPS), from operations it has – so a step is not
computed on the CPU in part (PYTORCH_ENABLE_MPS_FALLBACK) with the tensors copied back and forth."""

from __future__ import annotations

import torch


def grid_sample_bilinear(img: torch.Tensor, grid: torch.Tensor, padding_mode: str = "zeros",
                         align_corners: bool = False) -> torch.Tensor:
    """``F.grid_sample(img, grid, "bilinear", padding_mode, align_corners)`` ("zeros" or "border") from gathers and
    sums: on the Apple GPU grid_sample has no backward pass (aten::grid_sampler_2d_backward), so every step would
    compute it on the CPU. The backward pass of a gather is a scatter-add, which MPS has; the gradient for the grid
    comes through the interpolation weights."""
    n, c, h, w = img.shape
    gx, gy = grid[..., 0], grid[..., 1]
    if align_corners:
        x, y = (gx + 1) / 2 * (w - 1), (gy + 1) / 2 * (h - 1)  # [N, Ho, Wo], pixel coordinates
    else:
        x, y = ((gx + 1) * w - 1) / 2, ((gy + 1) * h - 1) / 2
    if padding_mode == "border":
        x, y = x.clamp(0, w - 1), y.clamp(0, h - 1)
    elif padding_mode != "zeros":
        raise ValueError(f"padding_mode {padding_mode!r}")
    x0, y0 = torch.floor(x).detach(), torch.floor(y).detach()
    fx, fy = x - x0, y - y0
    flat = img.reshape(n, c, h * w)
    out = None
    for dx, dy, weight in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)), (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
        xi, yi = x0 + dx, y0 + dy
        inside = (xi >= 0) & (xi <= w - 1) & (yi >= 0) & (yi <= h - 1)
        index = (yi.clamp(0, h - 1) * w + xi.clamp(0, w - 1)).long().reshape(n, 1, -1).expand(n, c, -1)
        tap = flat.gather(2, index).reshape(n, c, *x.shape[1:]) * (weight * inside.to(img.dtype)).unsqueeze(1)
        out = tap if out is None else out + tap
    return out


# --- the linear layer --------------------------------------------------------------------------------------------
# On the Apple GPU of the macOS CI machines F.linear (matrix product and bias in one, addmm) computed wrongly for a
# contiguous input – 45 % off in CLIP's first block, so CLIP's scores and the losses that steer the strokes were
# wrong –, while the same product of a permuted view was right (tests/test_mps_numerics.py). Whether a Mac's own GPU
# does the same is not known; so the first use of MPS in a process checks it and, where the built-in way is wrong,
# makes F.linear (and so every nn.Linear: CLIP, the diffusion models) take a way that is right there.

_native_linear = torch.nn.functional.linear
_chosen: str | None = None  # how F.linear computes on MPS in this process (None: not checked yet)


def _matmul_linear(x, weight, bias=None):
    out = torch.matmul(x, weight.t())
    return out if bias is None else out + bias


def _view_linear(x, weight, bias=None):
    if x.dim() < 2:
        return _native_linear(x, weight, bias)
    view = x.transpose(-2, -1).contiguous().transpose(-2, -1)  # (the same values, laid out column by column)
    return _native_linear(view, weight, bias)


LINEAR_WAYS = {"native": _native_linear, "matmul": _matmul_linear, "view": _view_linear}


def _relative(a: torch.Tensor, b: torch.Tensor) -> float:
    return float((a - b).abs().max() / (a.abs().max() + 1e-9))


def check_linear(device, ways=None) -> str | None:
    """The first way of computing F.linear (``LINEAR_WAYS``) that gives on ``device`` what the CPU gives – for a 3-d
    and a 2-d input, with and without a bias, of CLIP's sizes; None when none does."""
    g = torch.Generator().manual_seed(0)
    x = torch.randn(50, 4, 768, generator=g)
    w = torch.randn(2304, 768, generator=g) / 28
    b = torch.randn(2304, generator=g)
    cases = [(x, w, b), (x.reshape(200, 768), w, b), (x, w, None), (x[:, :1], w[:768], b[:768])]
    for name, way in (ways or LINEAR_WAYS).items():
        try:
            with torch.no_grad():
                right = all(_relative(_native_linear(*case), way(*(None if t is None else t.to(device)
                                                                    for t in case)).cpu()) < 1e-4
                            for case in cases)
        except Exception:  # noqa: BLE001 - a way the device cannot compute is not the way
            right = False
        if right:
            return name
    return None


def _dispatching(way):
    def linear(input, weight, bias=None):  # noqa: A002 - the name of F.linear's argument
        if input.device.type == "mps":
            return way(input, weight, bias)
        return _native_linear(input, weight, bias)
    linear.__doc__ = _native_linear.__doc__
    return linear


def ensure_right(device) -> str:
    """Before a model computes on ``device``: on MPS, the way F.linear computes right there ("native", "matmul",
    "view"; "wrong" when none) – F.linear takes it from now on in this process. Anything else: "native"."""
    global _chosen
    if torch.device(device).type != "mps":
        return "native"
    if _chosen is None:
        _chosen = check_linear(device) or "wrong"
        if _chosen in LINEAR_WAYS and _chosen != "native":
            torch.nn.functional.linear = _dispatching(LINEAR_WAYS[_chosen])
    return _chosen


# --- a convolution whose kernel is its stride (ViT's patches) ------------------------------------------------------
def patch_conv(conv: torch.nn.Conv2d, x: torch.Tensor, force: bool = False) -> torch.Tensor:
    """``conv(x)`` for a convolution that cuts the image into patches (kernel = stride, no padding, no dilation, one
    group) – on the Apple GPU as one matrix product over the patches: measured on an M5 Pro its backward took 4.3 s
    there for ViT-B/32's input layer (2.4 ms on the CPU), the matrix product 2.5 ms; the same values. Anywhere else
    (or for another convolution) the convolution itself. ``force``: the matrix product anywhere (tests)."""
    kernel, stride = tuple(conv.kernel_size), tuple(conv.stride)
    simple = (kernel == stride and tuple(conv.dilation) == (1, 1) and conv.groups == 1
              and conv.padding in ((0, 0), "valid") and x.dim() == 4)
    if not simple or not (force or x.device.type == "mps"):
        return conv(x)
    n, c, h, w = x.shape
    kh, kw = kernel
    gh, gw = h // kh, w // kw
    x = x[:, :, :gh * kh, :gw * kw]  # (as the convolution: what does not fill a patch is left out)
    patches = x.reshape(n, c, gh, kh, gw, kw).permute(0, 2, 4, 1, 3, 5).reshape(n, gh * gw, c * kh * kw)
    out = patches @ conv.weight.reshape(conv.out_channels, -1).t()
    if conv.bias is not None:
        out = out + conv.bias
    return out.reshape(n, gh, gw, conv.out_channels).permute(0, 3, 1, 2)
