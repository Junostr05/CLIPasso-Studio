"""Experimental sketch improvement (3.7, setting ``sketch_guide`` – switched on at the bottom of the app's settings):
strokes follow the photo's edges, and its dark areas are filled with even, straight hatching at 45°.

From the target picture on the canvas:

- an **edge map** (Sobel on the softened brightness, as the quality hints), every pixel's distance to the
  nearest edge, and the edges' direction (the smoothed structure tensor, as (cos 2θ, sin 2θ): a direction without
  a sign);
- the **hatch region**: dark (brightness below ``DARK``) and a little away from the edges.

**Hatch strokes** come in addition to the set number of strokes (by the size of the hatch region, at most
``MAX_HATCH_EXTRA`` × as many – the set strokes all stay for the edges and the shape): short, thinner straight lines
at 45°, close together in the darkest (and most important) part of the dark area. They stay such lines
by construction (:meth:`Guide.project`: only their position is optimised), so the hatching stays even. The other
strokes start as usual (the attention map ∩ the edges) and a small extra loss

- turns them along the edge they lie on, and snaps them onto an edge that is very close,
- keeps the hatch strokes in the dark and apart from each other,

while the CLIP loss stays the leading one (``WEIGHT``: a pull that points the same way every step adds up, while
CLIP's gradient changes with its random augmentations – a first version with a pull towards every edge in reach
lost the faces of portraits). The choice of the best iteration is left to the CLIP loss.
"""

from __future__ import annotations

import math

import numpy as np
import torch
import torch.nn.functional as F

HATCH_DIR = (1 / math.sqrt(2), -1 / math.sqrt(2))  # 45°: from lower left to upper right (y points down)
DARK = 0.42  # brightness (0..1) below which an area is hatched
EDGE = 0.12  # Sobel magnitude from which a pixel is on an edge (a black-white step: 1)
BLUR = 1.2  # px: softened first, so noise and fine texture are no edges
TENSOR_BLUR = 2.0  # px: the structure tensor is averaged over this much (a calm direction field)
EDGE_CLEAR = 0.025  # hatching keeps this far from edges (share of the canvas side)
EDGE_REACH = 0.02  # an edge closer than this (share of the side) pulls the stroke onto it; farther: no pull
MIN_DARK_SHARE = 0.02  # smaller dark areas get no hatching
HATCH_FACTOR = 2.0  # extra hatch strokes = the set strokes × the share of the dark area × this …
MAX_HATCH_EXTRA = 0.5  # … at most this many times the set strokes
HATCH_WIDTH = 0.6  # × the stroke width: hatching is finer than the outlines
HATCH_LENGTH = 0.06  # share of the side
HATCH_SPACING = 0.03  # share of the side between hatch strokes: close, so they read as hatching – the strokes
# go to the darkest (and, with an attention map, most important) part of the dark area that they fill this densely
SAMPLES = 16  # points per stroke where the loss looks
WEIGHT = 0.1  # of the whole guide loss against the CLIP loss
W_EDGE_DIST, W_EDGE_ALIGN = 0.5, 1.0
W_HATCH_DARK, W_HATCH_SPACING = 1.0, 0.5

EDGE_ROLE, HATCH_ROLE, FREE_ROLE = 0, 1, -1  # FREE: not guided (e.g. strokes of a start sketch)


def _gray(target: torch.Tensor) -> np.ndarray:
    img = target.detach().float().cpu()
    img = img[0] if img.dim() == 4 else img
    r, g, b = img[0].numpy(), img[1].numpy(), img[2].numpy()
    return (0.299 * r + 0.587 * g + 0.114 * b).astype(np.float32)


def _bernstein(order: int, t: np.ndarray) -> np.ndarray:
    return np.stack([math.comb(order, k) * (1 - t) ** (order - k) * t ** k for k in range(order + 1)], axis=1)


def bezier_samples(points: torch.Tensor, order: int, samples: int = SAMPLES) -> tuple[torch.Tensor, torch.Tensor]:
    """Positions and tangents [N, S, 2] along strokes of Bézier segments of ``order`` (1–3); ``points``
    [N, 1 + segments × order, 2]."""
    n, m, _ = points.shape
    segments = max((m - 1) // order, 1)
    per = max(samples // segments, 4)
    t = (np.arange(per) + 0.5) / per
    basis = torch.as_tensor(_bernstein(order, t), dtype=points.dtype, device=points.device)  # [T, k+1]
    deriv = torch.as_tensor(_bernstein(order - 1, t), dtype=points.dtype, device=points.device) * order  # [T, k]
    pos, tan = [], []
    for s in range(segments):
        ctrl = points[:, s * order: s * order + order + 1]  # [N, k+1, 2]
        pos.append(torch.einsum("tk,nkd->ntd", basis, ctrl))
        tan.append(torch.einsum("tk,nkd->ntd", deriv, ctrl[:, 1:] - ctrl[:, :-1]))
    return torch.cat(pos, dim=1), torch.cat(tan, dim=1)


class Guide:
    def __init__(self, target: torch.Tensor, mask=None):
        """``target`` [1,3,H,W] in 0..1: the picture on the canvas the strokes live on (pixel coordinates);
        ``mask`` [H,W] (optional): hatching only inside it."""
        from scipy import ndimage

        gray = _gray(target)
        self.height, self.width = gray.shape
        side = float(min(self.height, self.width))
        g = ndimage.gaussian_filter(gray, BLUR)
        gx, gy = ndimage.sobel(g, axis=1) / 4.0, ndimage.sobel(g, axis=0) / 4.0  # (a black-white step: 1)
        mag = np.hypot(gx, gy)
        edges = mag > EDGE
        self.has_edges = bool(edges.any())
        dist = ndimage.distance_transform_edt(~edges) if self.has_edges else np.full(gray.shape, side)
        reach = EDGE_REACH * side
        # the edges' direction: the structure tensor's main axis is across the edge, the edge runs at right angles
        jxx = ndimage.gaussian_filter(gx * gx, TENSOR_BLUR)
        jxy = ndimage.gaussian_filter(gx * gy, TENSOR_BLUR)
        jyy = ndimage.gaussian_filter(gy * gy, TENSOR_BLUR)
        diff = jxx - jyy
        r = np.sqrt(diff ** 2 + 4 * jxy ** 2) + 1e-12
        cos2, sin2 = -diff / r, -2 * jxy / r  # of the edge's tangent
        coherence = r / (jxx + jyy + 1e-12)
        strength = np.clip(ndimage.gaussian_filter(mag, TENSOR_BLUR) / EDGE, 0.0, 1.0)
        # the hatch region: dark, a little away from the edges (inside the mask)
        region = (g < DARK) & (dist > EDGE_CLEAR * side)
        if mask is not None:
            m = mask.detach().cpu().numpy() if torch.is_tensor(mask) else np.asarray(mask)
            if m.shape == region.shape:
                region &= m > 0.5
        self.region = region
        self.darkness = np.clip((DARK - g) / DARK, 0.0, 1.0)
        self.dark_share = float(region.mean())
        dark_soft = ndimage.gaussian_filter(region.astype(np.float32), 1.5)
        maps = np.stack([np.minimum(dist / reach, 1.0), cos2, sin2, strength * coherence, dark_soft])
        self.maps = torch.from_numpy(maps.astype(np.float32))[None]  # [1, 5, H, W]
        self.length = HATCH_LENGTH * side
        self.spacing = 0.0  # the hatch strokes' distance, set by init_hatch

    # ------------------------------------------------------------------ start
    def hatch_count(self, strokes: int) -> int:
        """How many hatch strokes come in addition to ``strokes`` set strokes."""
        if self.dark_share < MIN_DARK_SHARE or strokes < 2:
            return 0
        return min(int(round(strokes * self.dark_share * HATCH_FACTOR)), int(strokes * MAX_HATCH_EXTRA))

    def init_hatch(self, n: int, points_per_stroke: int, rng=np.random, weight=None) -> list[np.ndarray]:
        """Up to ``n`` straight hatch strokes [points_per_stroke, 2] (pixels) at 45°, close and evenly spaced in the
        darkest part of the dark area (weighted by ``weight`` [H,W], e.g. the attention map) – fewer when there is
        no room for more."""
        if n <= 0 or not self.region.any():
            return []
        side = float(min(self.height, self.width))
        spacing = HATCH_SPACING * side
        score = self.darkness.copy()
        if weight is not None:
            w = np.asarray(weight.detach().cpu() if torch.is_tensor(weight) else weight, dtype=np.float64)
            if w.shape == score.shape and w.max() > w.min():
                score = score * (0.25 + (w - w.min()) / (w.max() - w.min()))
        score = np.where(self.region, score, -1.0)
        area = int(min(self.region.sum(), n * self.length * spacing * 1.3))
        cut = np.sort(score.ravel())[::-1][max(area - 1, 0)]
        patch = self.region & (score >= cut)  # the part the hatching fills
        h = np.asarray(HATCH_DIR)
        hp = np.array([-h[1], h[0]])
        ys, xs = np.nonzero(patch)
        pts = np.stack([xs, ys], axis=1).astype(np.float64)
        u, v = pts @ hp, pts @ h
        half = self.length / 2
        centres: np.ndarray = np.zeros((0, 2))
        for _ in range(6):  # closer together until there is room for all
            gu = np.arange(u.min(), u.max() + spacing, spacing)
            gv = np.arange(v.min(), v.max() + self.length * 1.25, self.length * 1.25)
            uu, vv = np.meshgrid(gu, gv)
            uu = uu + rng.uniform(-0.15, 0.15, uu.shape) * spacing
            vv = vv + rng.uniform(-0.25, 0.25, vv.shape) * self.length
            c = uu.reshape(-1, 1) * hp + vv.reshape(-1, 1) * h
            ok = self._inside(c, patch) & self._inside(c - half * h) & self._inside(c + half * h)
            centres = c[ok]
            if len(centres) >= n:
                break
            spacing *= 0.75
        self.spacing = spacing
        if len(centres) > n:  # the darker places first
            ix = np.clip(np.round(centres).astype(int), 0, [self.width - 1, self.height - 1])
            dark = self.darkness[ix[:, 1], ix[:, 0]] + 1e-3
            pick = rng.choice(len(centres), size=n, replace=False, p=dark / dark.sum())
            centres = centres[np.sort(pick)]
        steps = np.linspace(-half, half, points_per_stroke)
        return [c + steps[:, None] * h for c in centres]

    def _inside(self, pts: np.ndarray, region: np.ndarray | None = None) -> np.ndarray:
        region = self.region if region is None else region
        ix = np.round(pts).astype(int)
        ok = (ix[:, 0] >= 0) & (ix[:, 0] < self.width) & (ix[:, 1] >= 0) & (ix[:, 1] < self.height)
        out = np.zeros(len(pts), dtype=bool)
        out[ok] = region[ix[ok, 1], ix[ok, 0]]
        return out

    # ------------------------------------------------------------- hatch form
    def project(self, points: torch.Tensor, roles) -> torch.Tensor:
        """The strokes with the hatch strokes made straight lines at 45° of the hatch length through their centre
        (differentiable in the centre: only the position of a hatch stroke is optimised)."""
        roles = torch.as_tensor(roles, device=points.device)
        hatch = roles == HATCH_ROLE
        if not bool(hatch.any()):
            return points
        m = points.shape[1]
        h = torch.tensor(HATCH_DIR, dtype=points.dtype, device=points.device)
        steps = torch.linspace(-self.length / 2, self.length / 2, m, dtype=points.dtype, device=points.device)
        line = points.mean(dim=1, keepdim=True) + steps[None, :, None] * h  # [N, M, 2]
        return torch.where(hatch[:, None, None], line, points)

    # ------------------------------------------------------------------- loss
    def _sample(self, pos: torch.Tensor) -> torch.Tensor:
        """The maps at the positions [N, S, 2] (pixels) -> [5, N, S]."""
        n, s, _ = pos.shape
        maps = self.maps.to(device=pos.device, dtype=pos.dtype)
        gx = pos[..., 0] / max(self.width - 1, 1) * 2 - 1
        gy = pos[..., 1] / max(self.height - 1, 1) * 2 - 1
        grid = torch.stack([gx, gy], dim=-1).reshape(1, n * s, 1, 2)
        out = F.grid_sample(maps, grid, mode="bilinear", padding_mode="border", align_corners=True)
        return out.reshape(maps.shape[1], n, s)

    def loss(self, points: torch.Tensor, roles, order: int) -> torch.Tensor:
        """The guide loss of strokes ``points`` [N, M, 2] (pixels, Bézier segments of ``order``) with their roles
        (``EDGE_ROLE`` / ``HATCH_ROLE`` / ``FREE_ROLE``)."""
        roles = torch.as_tensor(roles, device=points.device)
        guided = roles >= 0
        if not bool(guided.any()):
            return points.sum() * 0.0
        pos, tan = bezier_samples(points, order)
        dist, cos2, sin2, align_w, dark = self._sample(pos)
        t = tan / (tan.norm(dim=-1, keepdim=True) + 1e-6)
        c2a, s2a = t[..., 0] ** 2 - t[..., 1] ** 2, 2 * t[..., 0] * t[..., 1]
        total = points.sum() * 0.0
        count = float(guided.sum())
        edge = roles == EDGE_ROLE
        if bool(edge.any()) and self.has_edges:
            misalign = 0.5 * (1 - (c2a * cos2 + s2a * sin2))
            term = W_EDGE_DIST * dist[edge].mean() + W_EDGE_ALIGN * (align_w * misalign)[edge].mean()
            total = total + term * float(edge.sum()) / count
        hatch = roles == HATCH_ROLE
        if bool(hatch.any()):  # (their form is kept by project(): in the dark, apart from each other)
            term = W_HATCH_DARK * (1 - dark[hatch]).mean() + W_HATCH_SPACING * self._spacing(pos[hatch])
            total = total + term * float(hatch.sum()) / count
        return WEIGHT * total

    def _spacing(self, pos: torch.Tensor) -> torch.Tensor:
        """Hatch strokes side by side closer than the spacing push each other apart (an even hatching)."""
        if pos.shape[0] < 2 or self.spacing <= 0:
            return pos.sum() * 0.0
        h = torch.tensor(HATCH_DIR, dtype=pos.dtype, device=pos.device)
        hp = torch.stack([-h[1], h[0]])
        mid = pos[:, pos.shape[1] // 2]
        u, v = mid @ hp, mid @ h
        du = (u[:, None] - u[None, :]).abs()
        dv = (v[:, None] - v[None, :]).abs()
        side_by_side = torch.relu(1 - dv / self.length)
        close = torch.relu(1 - du / self.spacing) ** 2
        off = 1 - torch.eye(len(mid), dtype=pos.dtype, device=pos.device)
        return (close * side_by_side * off).sum() / off.sum()
