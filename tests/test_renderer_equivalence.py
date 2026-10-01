"""The 3.0 rasterizer draws exactly like the 2.4 one (tests/_renderer_v24.py) – same image, same
gradients – on random scenes with every kind of path."""

import math
import time

import pytest
import torch

from clipasso_studio.engine import renderer as new
from tests import _renderer_v24 as old


def _scene(seed, dtype=torch.float64, size=64, n=6, colored=False, segments=(1, 4), orders=(1, 2, 3)):
    g = torch.Generator().manual_seed(seed)

    def r(*shape):
        return torch.rand(*shape, generator=g, dtype=dtype)

    shapes, groups = [], []
    for i in range(n):
        k = int(torch.randint(segments[0], segments[1] + 1, (1,), generator=g))
        ncp = [orders[int(torch.randint(0, len(orders), (1,), generator=g))] - 1 for _ in range(k)]
        closed = bool(torch.rand(1, generator=g) < 0.15)
        n_pts = sum(c + 1 for c in ncp) + (0 if closed else 1)
        centre = r(2) * size * 1.2 - 0.1 * size  # some strokes partly off the canvas
        pts = centre + (r(n_pts, 2) - 0.5) * size * 0.6
        if i == 1 and n_pts > 1:
            pts[1] = pts[0]  # a degenerate (zero-length) piece
        # (not exactly 0: then the coverage min(…, width) ties with 0 on every pixel of the box and the
        # width gradient depends on the box size, which is not a property of the drawing)
        width = [0.05, 0.3, 1.0, 1.5, 6.0][i % 5] if i < 5 else 0.1 + float(r(1)) * 4
        opacity = [1.0, 0.4, 0.0, 1.0, 0.75][i % 5]
        rgb = (r(3) if colored else torch.zeros(3, dtype=dtype)).tolist()
        shapes.append(new.Path(torch.tensor(ncp), pts.clone().requires_grad_(True),
                               torch.tensor(width, dtype=dtype).requires_grad_(True), closed))
        groups.append(new.ShapeGroup(torch.tensor([i]), None,
                                     torch.tensor(rgb + [opacity], dtype=dtype).requires_grad_(colored)))
    return shapes, groups


def _clone(shapes, groups, mod):
    s2 = [mod.Path(s.num_control_points, s.points.detach().clone().requires_grad_(True),
                   s.stroke_width.detach().clone().requires_grad_(True), s.is_closed) for s in shapes]
    g2 = [mod.ShapeGroup(g.shape_ids, None,
                         g.stroke_color.detach().clone().requires_grad_(g.stroke_color.requires_grad))
          for g in groups]
    return s2, g2


def _grads(fn, shapes, groups, size, samples=1):
    img = fn(size, size, shapes, groups, samples)
    w = torch.rand(img.shape, generator=torch.Generator().manual_seed(1), dtype=img.dtype)
    (img * w).sum().backward()
    gp = [s.points.grad.clone() if s.points.grad is not None else torch.zeros_like(s.points) for s in shapes]
    gw = [s.stroke_width.grad.clone() if s.stroke_width.grad is not None else torch.zeros_like(s.stroke_width)
          for s in shapes]
    gc = [g.stroke_color.grad.clone() if g.stroke_color.grad is not None else torch.zeros_like(g.stroke_color)
          for g in groups]
    return img.detach(), gp, gw, gc


@pytest.mark.parametrize("seed", range(12))
@pytest.mark.parametrize("dtype", [torch.float64, torch.float32])
def test_render_is_the_same_as_before(seed, dtype):
    size = 64 if seed % 3 else 48
    shapes, groups = _scene(seed, dtype=dtype, size=size, colored=seed % 2 == 1)
    a = _grads(old.render, *_clone(shapes, groups, old), size)
    b = _grads(new.render, *_clone(shapes, groups, new), size)
    assert torch.equal(a[0], b[0])  # the same image, bit for bit
    tol = dict(rtol=1e-5, atol=1e-10) if dtype == torch.float64 else dict(rtol=1e-4, atol=1e-5)
    for ga, gb in zip(a[1] + a[2] + a[3], b[1] + b[2] + b[3]):
        assert torch.allclose(ga, gb, **tol), (ga, gb)


@pytest.mark.parametrize("seed", range(8))
def test_render_on_white_with_black_strokes(seed):
    """Black strokes use the product of (1 - alpha): the same image up to rounding."""
    size = 56
    samples = 2 if seed % 4 == 0 else 1
    shapes, groups = _scene(100 + seed, size=size)
    a = _grads(old.render_on_white, *_clone(shapes, groups, old), size, samples)
    b = _grads(new.render_on_white, *_clone(shapes, groups, new), size, samples)
    assert torch.allclose(a[0], b[0], atol=1e-12)
    for ga, gb in zip(a[1] + a[2] + a[3], b[1] + b[2] + b[3]):
        assert torch.allclose(ga, gb, rtol=1e-6, atol=1e-9), (ga, gb)


def test_overlapping_opaque_strokes_have_correct_gradients():
    """Several opaque strokes over the same pixels (1 - a = 0 twice): no NaN, same gradients."""
    size = 32
    pts = torch.tensor([[4.0, 16.0], [12.0, 16.0], [20.0, 16.0], [28.0, 16.0]], dtype=torch.float64)
    shapes, groups = [], []
    for i in range(3):
        shapes.append(new.Path(torch.tensor([2]), (pts + i * 0.3).requires_grad_(True),
                               torch.tensor(4.0, dtype=torch.float64).requires_grad_(True)))
        groups.append(new.ShapeGroup(torch.tensor([i]), None, torch.tensor([0, 0, 0, 1.0], dtype=torch.float64)))
    a = _grads(old.render_on_white, *_clone(shapes, groups, old), size)
    b = _grads(new.render_on_white, *_clone(shapes, groups, new), size)
    assert torch.allclose(a[0], b[0], atol=1e-12)
    for ga, gb in zip(a[1] + a[2], b[1] + b[2]):
        assert not torch.isnan(gb).any() and torch.allclose(ga, gb, rtol=1e-6, atol=1e-9)


def _one_line(size, n_seg, dtype, seed=7):
    """A drawing made of one long path: a wandering line whose curves each stay in a small area."""
    g = torch.Generator().manual_seed(seed)
    steps = (torch.rand(3 * n_seg + 1, 2, generator=g, dtype=torch.float64) - 0.5) * size * 0.12
    pts = torch.cumsum(steps, dim=0)
    pts = (pts - pts.min(dim=0).values) / (pts.max(dim=0).values - pts.min(dim=0).values) * (size - 24) + 12
    pts = pts.to(dtype).requires_grad_(True)
    shapes = [new.Path(torch.full((n_seg,), 2), pts, torch.tensor(1.5, dtype=dtype).requires_grad_(True))]
    groups = [new.ShapeGroup(torch.tensor([0]), None, torch.tensor([0, 0, 0, 1.0], dtype=dtype))]
    return shapes, groups


def test_long_one_line_path_is_the_same():
    """One path of many curves across the canvas: each curve tests only the pixels near it."""
    shapes, groups = _one_line(96, 16, torch.float64)  # small: the old renderer needs pixels × segments
    a = _grads(old.render, *_clone(shapes, groups, old), 96)
    b = _grads(new.render, *_clone(shapes, groups, new), 96)
    assert torch.equal(a[0], b[0])
    for ga, gb in zip(a[1] + a[2], b[1] + b[2]):
        assert torch.allclose(ga, gb, rtol=1e-5, atol=1e-10)


def test_one_line_drawing_renders_fast():
    shapes, groups = _one_line(224, 48, torch.float32)
    start = time.perf_counter()
    new.render_on_white(224, 224, shapes, groups).sum().backward()
    assert time.perf_counter() - start < 2.0 and math.isfinite(shapes[0].points.grad.abs().sum().item())


def test_flatten_path_is_unchanged():
    shapes, _ = _scene(3, n=5)
    for s in shapes:
        p_old = old.Path(s.num_control_points, s.points, s.stroke_width, s.is_closed)
        assert torch.equal(old.flatten_path(p_old), new.flatten_path(s))


def test_width_and_opacity_gradients_match_finite_differences():
    pts = torch.tensor([[3.0, 3.0], [8.0, 14.0], [14.0, 2.0], [17.0, 12.0]], dtype=torch.float64)
    weights = torch.rand(20, 20, 3, generator=torch.Generator().manual_seed(0), dtype=torch.float64)

    def f(width, opacity):
        p = new.Path(torch.tensor([2]), pts, width)
        g = new.ShapeGroup(torch.tensor([0]), None, torch.stack([torch.zeros(3, dtype=torch.float64).sum()] * 3
                                                                 + [opacity]))
        return (new.render_on_white(20, 20, [p], [g]) * weights).sum()

    w = torch.tensor(1.7, dtype=torch.float64, requires_grad=True)
    o = torch.tensor(0.6, dtype=torch.float64, requires_grad=True)
    f(w, o).backward()
    eps = 1e-6
    with torch.no_grad():
        dw = (f(w + eps, o) - f(w - eps, o)) / (2 * eps)
        do = (f(w, o + eps) - f(w, o - eps)) / (2 * eps)
    assert torch.allclose(w.grad, dw, rtol=1e-4) and torch.allclose(o.grad, do, rtol=1e-4)
