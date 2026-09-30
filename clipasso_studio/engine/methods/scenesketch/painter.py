"""Stroke parameterisation of SceneSketch – port of ``models/painter_params.py`` (CLIPascene, MIT licence).

Unlike CLIPasso, the control points are not optimised directly: an MLP maps the initial points to
their positions (``MLP``), and while simplifying, a second MLP (``WidthMLP``) gives every stroke a
keep-probability that is turned into a stroke width with a Gumbel-softmax. Rendering uses the
PyTorch rasterizer of the app instead of diffvg.
"""

from __future__ import annotations

import torch
import torch.nn as nn

from ... import renderer, svg_io

BASE_WIDTH = 1.5  # width of every stroke; the width MLP scales it by the stroke's probability
KEEP_THRESHOLD = 0.7  # a stroke is kept in the SVG when width / BASE_WIDTH > 0.7


class MLP(nn.Module):
    """Offsets for all control points: points_init (normalised to [-1, 1]) -> new points."""

    def __init__(self, num_strokes: int, num_cp: int, hidden: int = 1000):
        super().__init__()
        self.layers_points = nn.Sequential(
            nn.Flatten(),
            nn.Linear(num_strokes * num_cp * 2, hidden),
            nn.SELU(inplace=True),
            nn.Linear(hidden, hidden),
            nn.SELU(inplace=True),
            nn.Linear(hidden, num_strokes * num_cp * 2),
        )

    def forward(self, x):
        return x.flatten() + 0.1 * self.layers_points(x)


class WidthMLP(nn.Module):
    """Keep-probability of every stroke (the input is the constant vector of initial widths)."""

    def __init__(self, num_strokes: int, hidden: int = 1000):
        super().__init__()
        self.layers_width = nn.Sequential(
            nn.Linear(num_strokes, hidden),
            nn.SELU(inplace=True),
            nn.Linear(hidden, hidden),
            nn.SELU(inplace=True),
            nn.Linear(hidden, num_strokes),
            nn.Sigmoid(),
        )

    def forward(self, widths):
        return self.layers_width(widths)


def init_weights(m):
    if isinstance(m, nn.Linear):
        torch.nn.init.xavier_uniform_(m.weight)
        m.bias.data.fill_(0.01)


class MLPPainter(nn.Module):
    """Strokes = MLP(initial points); optionally widths = Gumbel-softmax(WidthMLP(...)) * 1.5."""

    def __init__(self, points_init: torch.Tensor, canvas: int, device, width_optim: bool = False,
                 gumbel_temp: float = 0.2, width: float = BASE_WIDTH):
        super().__init__()
        self.device = device
        self.canvas = int(canvas)
        self.points_init = points_init.to(device=device, dtype=torch.float32)  # [N, cp, 2] in pixels
        self.num_paths, self.num_cp = int(points_init.shape[0]), int(points_init.shape[1])
        self.width = float(width)
        self.width_optim = bool(width_optim)
        self.gumbel_temp = float(gumbel_temp)
        self.num_control_points = torch.zeros(1, dtype=torch.int32) + (self.num_cp - 2)
        self.mlp = MLP(self.num_paths, self.num_cp).to(device)
        self.mlp_width = None
        self.init_widths = torch.ones(self.num_paths, device=device) * BASE_WIDTH
        if self.width_optim:
            self.mlp_width = WidthMLP(self.num_paths).to(device)
            self.mlp_width.apply(init_weights)
        self.out_of_canvas_mask = torch.ones(self.num_paths, device=device)
        self.stroke_probs = None
        self.widths = None
        self.shapes: list[renderer.Path] = []
        self.shape_groups: list[renderer.ShapeGroup] = []

    # -------------------------------------------------------------------------- forward
    def _normalised_init(self) -> torch.Tensor:
        pts = self.points_init.unsqueeze(0) / self.canvas
        return 2 * pts - 1

    def current_points(self, grad: bool = True) -> torch.Tensor:
        """[N, cp, 2] control points in pixels."""
        x = self._normalised_init()
        if grad:
            points = self.mlp(x)
        else:
            with torch.no_grad():
                points = self.mlp(x)
        points = 0.5 * (points + 1.0) * self.canvas
        points = points + 1e-4 * torch.randn_like(points)
        return points.reshape(self.num_paths, self.num_cp, 2)

    def sample_widths(self) -> torch.Tensor:
        probs = self.mlp_width(self.init_widths).clamp(min=1e-8)
        flipped = (1 - probs).clamp(min=1e-8)
        v = torch.stack((torch.log(probs), torch.log(flipped)), dim=-1)
        hard = torch.nn.functional.gumbel_softmax(v, self.gumbel_temp, False)
        self.stroke_probs = hard[:, 0] * self.out_of_canvas_mask
        self.widths = self.stroke_probs * self.init_widths
        return self.widths

    def render(self, mode: str = "train") -> torch.Tensor:
        """``mlp_pass`` + rasterisation -> sketch [1, 3, H, W] on white. ``mode="init"`` also finds the
        strokes that lie completely outside the canvas (they are never counted)."""
        points = self.current_points()
        widths = None
        if self.width_optim and mode != "init":
            widths = self.sample_widths()
        shapes, groups = [], []
        for p in range(self.num_paths):
            w = widths[p] if widths is not None else torch.tensor(self.width, device=self.device)
            path = renderer.Path(self.num_control_points, points[p], w, is_closed=False)
            if mode == "init" and not in_canvas(path, self.canvas):
                self.out_of_canvas_mask[p] = 0
            shapes.append(path)
            groups.append(renderer.ShapeGroup(shape_ids=torch.tensor([len(shapes) - 1]), fill_color=None,
                                              stroke_color=torch.tensor([0.0, 0.0, 0.0, 1.0])))
        self.shapes, self.shape_groups = shapes, groups
        img = renderer.render_on_white(self.canvas, self.canvas, shapes, groups)
        return img.permute(2, 0, 1).unsqueeze(0)

    def strokes_in_canvas(self) -> torch.Tensor:
        return self.out_of_canvas_mask.sum()

    def strokes_count(self) -> float:
        if self.width_optim and self.stroke_probs is not None:
            return float(self.stroke_probs.detach().sum())
        return float(self.num_paths)

    # -------------------------------------------------------------------------- output
    def kept_paths(self, shapes=None) -> list[renderer.Path]:
        """Strokes of the SVG: with width optimisation only those with width / 1.5 > 0.7."""
        out = []
        for path in shapes if shapes is not None else self.shapes:
            w = float(path.stroke_width.detach())
            if self.width_optim and w / BASE_WIDTH <= KEEP_THRESHOLD:
                continue
            out.append(renderer.Path(path.num_control_points, path.points.detach(), torch.tensor(w),
                                     is_closed=False))
        return out

    def to_svg(self) -> str:
        return paths_to_svg(self.kept_paths(), self.canvas)

    def state(self) -> dict:
        return {"mlp": {k: v.detach().clone() for k, v in self.mlp.state_dict().items()},
                "mlp_width": None if self.mlp_width is None else
                {k: v.detach().clone() for k, v in self.mlp_width.state_dict().items()}}

    @torch.no_grad()
    def inference(self, state: dict) -> list[renderer.Path]:
        """``inference_sketch``: final strokes from saved MLP weights (a fresh Gumbel sample for the
        widths), without strokes outside the canvas or below the width threshold."""
        self.mlp.load_state_dict(state["mlp"])
        if self.width_optim and state.get("mlp_width") is not None:
            self.mlp_width.load_state_dict(state["mlp_width"])
        points = self.current_points(grad=False)
        widths = None
        if self.width_optim:
            probs = self.mlp_width(self.init_widths).clamp(min=1e-8)
            flipped = (1 - probs).clamp(min=1e-8)
            v = torch.stack((torch.log(probs), torch.log(flipped)), dim=-1)
            widths = torch.nn.functional.gumbel_softmax(v, 0.2, False)[:, 0] * self.init_widths
        out = []
        for p in range(self.num_paths):
            w = float(widths[p]) if widths is not None else self.width
            path = renderer.Path(self.num_control_points, points[p].clone(), torch.tensor(w), is_closed=False)
            if in_canvas(path, self.canvas) and (widths is None or w / BASE_WIDTH > KEEP_THRESHOLD):
                out.append(path)
        return out


def in_canvas(path: renderer.Path, canvas: int) -> bool:
    """Whether any part of the stroke is drawn on the canvas (``is_in_canvas``)."""
    with torch.no_grad():
        poly = renderer.flatten_path(path)
        half = float(path.stroke_width) / 2 + 0.5
        lo = poly.min(dim=0).values
        hi = poly.max(dim=0).values
        return bool((hi[0] > -half) and (hi[1] > -half) and (lo[0] < canvas + half) and (lo[1] < canvas + half))


def paths_to_svg(paths, canvas: int, background: str | None = None) -> str:
    groups = [renderer.ShapeGroup(shape_ids=torch.tensor([i]), fill_color=None,
                                  stroke_color=torch.tensor([0.0, 0.0, 0.0, 1.0])) for i in range(len(paths))]
    return svg_io.scene_to_svg(canvas, canvas, paths, groups, background=background)


def render_paths(paths, canvas: int) -> torch.Tensor:
    """[1, 3, H, W] on white."""
    groups = [renderer.ShapeGroup(shape_ids=torch.tensor([i]), fill_color=None,
                                  stroke_color=torch.tensor([0.0, 0.0, 0.0, 1.0])) for i in range(len(paths))]
    with torch.no_grad():
        img = renderer.render_on_white(canvas, canvas, paths, groups)
    return img.permute(2, 0, 1).unsqueeze(0)
