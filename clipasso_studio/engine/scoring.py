"""Method-independent quality score: CLIP similarity between a sketch and its input image.

Used to pick the best of several SwiftSketch / ControlSketch samples and to compare the
three methods on the same image (CLIPasso keeps its own eval loss for its best-of-N choice).
"""

from __future__ import annotations

import torch
import torch.nn.functional as F
from PIL import Image
from torchvision import transforms

from . import svg_io
from .clip_ import clip
from .renderer import render_on_white

_MEAN = (0.48145466, 0.4578275, 0.40821073)
_STD = (0.26862954, 0.26130258, 0.27577711)


class ClipScorer:
    """Cosine similarity (in percent) of CLIP ViT-B/32 image embeddings."""

    def __init__(self, device):
        self.device = device
        self.model, _ = clip.load("ViT-B/32", device=device)
        self.model.eval()
        self.norm = transforms.Normalize(_MEAN, _STD)

    def _embed(self, img: torch.Tensor) -> torch.Tensor:
        img = F.interpolate(img, size=(224, 224), mode="bicubic", align_corners=False).clamp(0, 1)
        with torch.no_grad():
            feats = self.model.encode_image(self.norm(img).to(self.device)).float()
        return feats / feats.norm(dim=-1, keepdim=True)

    def score_tensors(self, sketch: torch.Tensor, target: torch.Tensor) -> float:
        """sketch/target: [1,3,H,W] in [0,1]."""
        a = self._embed(sketch.float())
        b = self._embed(target.float())
        return float((a * b).sum(dim=-1).item() * 100.0)

    def score_svg(self, svg_path: str, target: Image.Image) -> float:
        w, h, shapes, groups = svg_io.load_svg(svg_path)
        with torch.no_grad():
            img = render_on_white(w, h, shapes, groups).permute(2, 0, 1)[None].cpu()
        tgt = transforms.ToTensor()(target.convert("RGB"))[None]
        return self.score_tensors(img, tgt)

    def embed_svg(self, svg_path: str):
        """The normalised CLIP embedding of a sketch rendered on white (numpy float32 [512]) – for the aesthetic
        score and the user's own taste (``engine/aesthetic.py``)."""
        w, h, shapes, groups = svg_io.load_svg(svg_path)
        with torch.no_grad():
            img = render_on_white(w, h, shapes, groups).permute(2, 0, 1)[None].cpu()
        return self._embed(img.float())[0].cpu().numpy().astype("float32")

    def stroke_importance(self, svg_path: str, target: Image.Image, batch: int = 16) -> tuple[float, list[float]]:
        """How much each stroke adds: the CLIP score of the sketch, and for every stroke (in the order of the
        SVG) how far the score falls without it.

        Every stroke is rendered once on its own (at the size CLIP sees); a picture of dark strokes on white is
        the product of those single-stroke pictures, so the picture without stroke i is the product of all the
        others (prefix and suffix products) – no stroke is rendered twice."""
        from .renderer import Path

        w, h, shapes, groups = svg_io.load_svg(svg_path)
        s = 224.0 / max(w, h)
        shapes = [Path(p.num_control_points, p.points * s, p.stroke_width * s, is_closed=p.is_closed) for p in shapes]
        w, h = max(1, round(w * s)), max(1, round(h * s))
        tgt = self._embed(transforms.ToTensor()(target.convert("RGB"))[None].float())
        with torch.no_grad():
            single = [render_on_white(w, h, shapes, [g]).permute(2, 0, 1).cpu() for g in groups]
        n = len(single)
        if n == 0:
            blank = torch.ones(1, 3, h, w)
            return float((self._embed(blank) * tgt).sum().item() * 100.0), []
        prefix = [torch.ones_like(single[0])]
        for img in single:
            prefix.append(prefix[-1] * img)
        suffix = [torch.ones_like(single[0])]
        for img in reversed(single):
            suffix.append(suffix[-1] * img)
        suffix.reverse()  # suffix[i]: the product of single[i:]
        base = float((self._embed(prefix[-1][None]) * tgt).sum().item() * 100.0)
        drops: list[float] = []
        for start in range(0, n, batch):
            imgs = torch.stack([prefix[i] * suffix[i + 1] for i in range(start, min(n, start + batch))])
            emb = self._embed(imgs)
            drops.extend(float(base - v) for v in ((emb * tgt).sum(dim=-1) * 100.0).tolist())
        return base, drops


_scorers: dict[str, ClipScorer] = {}


def get_scorer(device) -> ClipScorer:
    """Scorer cached per device (a job scores every seed)."""
    key = str(device)
    if key not in _scorers:
        _scorers[key] = ClipScorer(device)
    return _scorers[key]


def clip_score(svg_path: str, target: Image.Image, device="cpu") -> float:
    return get_scorer(device).score_svg(svg_path, target)
