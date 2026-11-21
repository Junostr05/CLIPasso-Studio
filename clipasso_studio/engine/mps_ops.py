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
