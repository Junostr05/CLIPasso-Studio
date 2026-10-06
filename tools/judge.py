"""The benchmark's independent judges: how much a sketch looks like its photo, measured by models that take part in
no optimisation of the app – so a change cannot raise its own mark (a new CLIP model in the loss would otherwise
also be the one that grades it).

- ``clip_l14``: OpenAI CLIP **ViT-L/14** – the cosine similarity (in percent) of the image embeddings of the photo
  and of the sketch rendered on white. The app optimises with RN101 / ViT-B/32 (and other options) and picks its
  best sketch with ViT-B/32; ViT-L/14 is larger and nowhere in it.
- ``recog``: how **recognisable** the sketch is on its own – ViT-L/14's zero-shot probability (percent) of the
  right label among every label of the benchmark ("a sketch of a camel", "… of a horse", …), as in the evaluation
  of the CLIPasso paper. It does not see the photo.

(DINO's class token was tried as a judge of the shape: it hardly told a matching sketch from another one.)

The similarity is compared on the same photo for every variant, so its differences between variants count, not
its absolute value.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

JUDGES = ("clip_l14", "recog")
REQUIRED_MODELS = ("clip:ViT-L/14",)
_CLIP_MEAN, _CLIP_STD = (0.48145466, 0.4578275, 0.40821073), (0.26862954, 0.26130258, 0.27577711)
PROMPT = "a sketch of {}"


class Judge:
    def __init__(self, labels: list[str], device: str = "cpu"):
        """``labels``: every label of the benchmark (the choices for the recognisability)."""
        import torch
        from torchvision import transforms

        from clipasso_studio.engine.clip_ import clip

        self.torch, self.device = torch, device
        self.clip, _ = clip.load("ViT-L/14", device=device)
        self.norm = transforms.Normalize(_CLIP_MEAN, _CLIP_STD)
        self.labels = sorted(set(labels))
        with torch.no_grad():
            t = self.clip.encode_text(clip.tokenize([PROMPT.format(lb) for lb in self.labels]).to(device)).float()
        self.text = t / t.norm(dim=-1, keepdim=True)
        self.scale = float(self.clip.logit_scale.exp())
        self._photos: dict = {}

    def _embed(self, img):
        """img: [1,3,H,W] in [0,1] -> the normalised ViT-L/14 embedding."""
        import torch.nn.functional as F

        x = F.interpolate(img.float(), size=(224, 224), mode="bicubic", align_corners=False).clamp(0, 1)
        with self.torch.no_grad():
            c = self.clip.encode_image(self.norm(x).to(self.device)).float()
        return c / c.norm(dim=-1, keepdim=True)

    def _photo(self, path: str) -> dict:
        if path not in self._photos:
            from PIL import Image
            from torchvision import transforms

            from clipasso_studio.engine.imaging import load_rgb

            im = load_rgb(path)
            side = max(im.size)
            square = Image.new("RGB", (side, side), "white")  # (the sketches are square: the photo too)
            square.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
            self._photos[path] = self._embed(transforms.ToTensor()(square)[None])
        return self._photos[path]

    def score(self, photo: str, svg_path: str, label: str) -> dict[str, float]:
        """The marks (percent) of the sketch ``svg_path`` of the photo file ``photo`` showing ``label``."""
        from clipasso_studio.engine import svg_io
        from clipasso_studio.engine.renderer import render_on_white

        w, h, shapes, groups = svg_io.load_svg(svg_path)
        with self.torch.no_grad():
            img = render_on_white(w, h, shapes, groups).permute(2, 0, 1)[None].cpu()
        sketch, ref = self._embed(img), self._photo(photo)
        probs = (self.scale * sketch @ self.text.T).softmax(dim=-1)[0]
        return {"clip_l14": round(float((sketch * ref).sum().item() * 100.0), 2),
                "recog": round(float(probs[self.labels.index(label)].item() * 100.0), 2)}


def missing_models() -> list[str]:
    from clipasso_studio.engine import model_store

    return [k for k in REQUIRED_MODELS if not model_store.is_available(k)]
