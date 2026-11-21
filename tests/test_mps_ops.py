"""The stand-ins for operations the Apple GPU has no backward pass for (engine/mps_ops.py, losses.perspective),
checked on the CPU against PyTorch's and torchvision's own: the same values and the same gradients – so a sketch on
the Apple GPU is drawn as on the CPU, only faster."""

from __future__ import annotations

import pytest
import torch
from torchvision import transforms
from torchvision.transforms import InterpolationMode
from torchvision.transforms import functional as TF

from clipasso_studio.engine import losses
from clipasso_studio.engine.mps_ops import grid_sample_bilinear


@pytest.mark.parametrize("padding_mode, align_corners",
                         [("zeros", False), ("zeros", True), ("border", False), ("border", True)])
def test_the_sampler_is_grid_sample(padding_mode, align_corners):
    g = torch.Generator().manual_seed(0)
    img = torch.rand(2, 4, 17, 23, generator=g, dtype=torch.float64, requires_grad=True)
    grid = (torch.rand(2, 9, 11, 2, generator=g, dtype=torch.float64) * 2.6 - 1.3).requires_grad_(True)
    weights = torch.rand(2, 4, 9, 11, generator=g, dtype=torch.float64)
    a = torch.nn.functional.grid_sample(img, grid, mode="bilinear", padding_mode=padding_mode,
                                        align_corners=align_corners)
    b = grid_sample_bilinear(img, grid, padding_mode=padding_mode, align_corners=align_corners)
    assert torch.allclose(a, b, atol=1e-12)
    ga = torch.autograd.grad((a * weights).sum(), (img, grid))
    gb = torch.autograd.grad((b * weights).sum(), (img, grid))
    assert torch.allclose(ga[0], gb[0], atol=1e-12) and torch.allclose(ga[1], gb[1], atol=1e-11)


def test_another_padding_is_refused():
    with pytest.raises(ValueError):
        grid_sample_bilinear(torch.zeros(1, 1, 4, 4), torch.zeros(1, 2, 2, 2), padding_mode="reflection")


def test_the_perspective_is_torchvisions():
    torch.manual_seed(3)
    img = torch.rand(3, 3, 224, 224)
    start, end = transforms.RandomPerspective.get_params(224, 224, 0.5)
    expected = TF.perspective(img, start, end, InterpolationMode.BILINEAR, fill=[0.0] * 3)
    assert torch.allclose(losses._own_perspective(img, start, end), expected, atol=1e-4)
    assert torch.equal(losses.perspective(img, start, end), expected)  # (on the CPU: torchvision's own)


def test_the_random_perspective_draws_the_same_numbers():
    img = torch.rand(2, 3, 64, 64)
    torch.manual_seed(5)
    a = transforms.RandomPerspective(fill=0, p=1.0, distortion_scale=0.5)(img)
    after_a = torch.rand(1)
    torch.manual_seed(5)
    b = losses.RandomPerspective(fill=0, p=1.0, distortion_scale=0.5)(img)
    assert torch.equal(a, b) and torch.equal(torch.rand(1), after_a)


@pytest.mark.parametrize("way", ["matmul", "view"])
def test_the_other_ways_of_the_linear_layer_compute_as_it_does(way):
    from clipasso_studio.engine import mps_ops

    g = torch.Generator().manual_seed(2)
    x, w, b = torch.randn(7, 3, 32, generator=g), torch.randn(48, 32, generator=g), torch.randn(48, generator=g)
    for args in ((x, w, b), (x[0], w, b), (x, w, None)):
        assert torch.allclose(mps_ops.LINEAR_WAYS[way](*args), torch.nn.functional.linear(*args), atol=1e-5)
    # (and on the CPU every way is right: the check takes the first, the built-in one)
    assert mps_ops.check_linear("cpu") == "native"
    assert mps_ops.check_linear("cpu", {"broken": lambda x, w, b=None: x.sum()}) is None


def test_the_linear_layer_changes_only_for_the_apple_gpu(monkeypatch):
    from clipasso_studio.engine import mps_ops

    monkeypatch.setattr(torch.nn.functional, "linear", torch.nn.functional.linear)  # (restored afterwards)
    assert mps_ops.ensure_right("cpu") == "native"
    calls = []
    linear = mps_ops._dispatching(lambda *args: calls.append(args) or "other way")
    x, w = torch.randn(2, 4), torch.randn(3, 4)
    assert torch.equal(linear(x, w), mps_ops._native_linear(x, w)) and calls == []  # (a CPU tensor: as before)



def test_clip_in_half_precision_only_on_an_nvidia_card(monkeypatch):
    from clipasso_studio.engine.clip_ import clip

    monkeypatch.setenv("CLIPASSO_MPS_HALF", "1")  # (the measuring switch of before: gone)
    assert clip.half_precision("cuda") and not clip.half_precision("cpu") and not clip.half_precision("mps")
