import torch

from clipasso_studio.engine.renderer import Path, ShapeGroup, render, render_on_white


def _stroke(points, width=1.5, ncp=(2,), opacity=1.0, requires_grad=False):
    pts = torch.tensor(points, dtype=torch.float64, requires_grad=requires_grad)
    path = Path(torch.tensor(ncp, dtype=torch.int32), pts, torch.tensor(width, dtype=torch.float64))
    group = ShapeGroup(torch.tensor([0]), None, torch.tensor([0.0, 0.0, 0.0, opacity], dtype=torch.float64))
    return path, group


def test_horizontal_line_coverage():
    path, group = _stroke([[4.0, 10.0], [16.0, 10.0]], width=2.0, ncp=(0,))
    img = render(20, 20, [path], [group])
    assert img.shape == (20, 20, 4)
    alpha = img[..., 3]
    # pixel rows 9 and 10 (centres 9.5 / 10.5) are inside the 2px wide stroke
    assert torch.allclose(alpha[9, 8:12], torch.ones(4, dtype=alpha.dtype))
    assert torch.allclose(alpha[10, 8:12], torch.ones(4, dtype=alpha.dtype))
    assert alpha[5].max() == 0
    assert alpha[15].max() == 0
    # the stroke area is close to length * width (+ round caps)
    assert 22 < alpha.sum().item() < 30


def test_white_background_and_opacity():
    path, group = _stroke([[2.0, 2.0], [6.0, 2.0], [10.0, 12.0], [14.0, 14.0]], opacity=0.5)
    img = render_on_white(16, 16, [path], [group])
    assert img.min().item() >= 0.49
    assert img.max().item() == 1.0


def test_gradients_match_finite_differences():
    path, group = _stroke([[3.0, 3.0], [8.0, 14.0], [14.0, 2.0], [17.0, 12.0]], width=1.5, requires_grad=True)
    weights = torch.rand(20, 20, dtype=torch.float64, generator=torch.Generator().manual_seed(0))

    def f(pts):
        p = Path(path.num_control_points, pts, path.stroke_width)
        return (render(20, 20, [p], [group])[..., 3] * weights).sum()

    loss = f(path.points)
    loss.backward()
    grad = path.points.grad.clone()
    assert grad.abs().sum() > 0
    eps = 1e-4
    num = torch.zeros_like(grad)
    with torch.no_grad():
        for i in range(grad.shape[0]):
            for j in range(2):
                p1 = path.points.detach().clone()
                p2 = path.points.detach().clone()
                p1[i, j] += eps
                p2[i, j] -= eps
                num[i, j] = (f(p1) - f(p2)) / (2 * eps)
    assert torch.allclose(grad, num, rtol=0.05, atol=0.05)


def test_multi_segment_and_closed_paths():
    pts = torch.tensor([[2.0, 2.0], [10.0, 2.0], [10.0, 10.0], [2.0, 10.0]], dtype=torch.float32)
    path = Path(torch.tensor([0, 0, 0, 0], dtype=torch.int32), pts, torch.tensor(1.0), is_closed=True)
    group = ShapeGroup(torch.tensor([0]), None, torch.tensor([1.0, 0.0, 0.0, 1.0]))
    img = render(12, 12, [path], [group])
    alpha = img[..., 3]
    # all four sides of the square are drawn; a 1px line on a pixel border covers two half pixels
    for a, b in ((alpha[1, 6], alpha[2, 6]), (alpha[9, 6], alpha[10, 6]), (alpha[6, 1], alpha[6, 2]),
                 (alpha[6, 9], alpha[6, 10])):
        assert abs((a + b).item() - 1.0) < 1e-4
    # the inside stays empty
    assert alpha[6, 6] == 0
    # colour is kept (straight alpha)
    assert torch.allclose(img[2, 6, :3], torch.tensor([1.0, 0.0, 0.0]), atol=1e-4)


def test_empty_and_offcanvas():
    path, group = _stroke([[-50.0, -50.0], [-40.0, -40.0]], ncp=(0,))
    img = render(8, 8, [path], [group])
    assert img.abs().sum() == 0
    assert render(8, 8, [], []).shape == (8, 8, 4)


def test_supersampling_keeps_shape():
    path, group = _stroke([[1.0, 4.0], [7.0, 4.0]], ncp=(0,), width=1.0)
    a1 = render(8, 8, [path], [group])[..., 3].sum()
    a2 = render(8, 8, [path], [group], samples=2)[..., 3].sum()
    assert abs(a1.item() - a2.item()) < 1.0
