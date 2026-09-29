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


_scorers: dict[str, ClipScorer] = {}


def get_scorer(device) -> ClipScorer:
    """Scorer cached per device (a job scores every seed)."""
    key = str(device)
    if key not in _scorers:
        _scorers[key] = ClipScorer(device)
    return _scorers[key]


def clip_score(svg_path: str, target: Image.Image, device="cpu") -> float:
    return get_scorer(device).score_svg(svg_path, target)
