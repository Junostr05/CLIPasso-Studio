"""Portrait mode: find a face with BlazeFace (MediaPipe's front-camera face detector) and make a detail map that
gives its eyes, nose and mouth more detail – the same map the detail brush paints (``engine/details.py``).

The network is MediaPipe's BlazeFace (Apache-2.0) in the PyTorch form of M. Hollemans' conversion (Apache-2.0):
a 128 × 128 input, 896 anchors, a box and six key points per face (right eye, left eye, nose tip, mouth, right and
left ear). Written anew here; the weights are a 0.4 MB download (``model_store`` "blazeface")."""

from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image

SIZE = 128
SCORE = 0.75  # the detector's own threshold for the front model
ACCEPT = 0.85  # what the portrait mode takes as a face (with a plausible arrangement, see ``plausible``)
NMS_IOU = 0.3
KEYPOINTS = ("right_eye", "left_eye", "nose", "mouth", "right_ear", "left_ear")


class _Block(nn.Module):
    """Depthwise 3×3 + pointwise 1×1 with a residual (max-pooled and zero-padded to the new width when it shrinks
    the picture); TFLite pads the stride-2 convolution on the right and bottom only."""

    def __init__(self, cin: int, cout: int, stride: int = 1):
        super().__init__()
        self.stride, self.pad = stride, cout - cin
        self.convs = nn.Sequential(nn.Conv2d(cin, cin, 3, stride, 0 if stride == 2 else 1, groups=cin),
                                   nn.Conv2d(cin, cout, 1))
        self.max_pool = nn.MaxPool2d(2, 2) if stride == 2 else None

    def forward(self, x):
        h = F.pad(x, (0, 2, 0, 2)) if self.stride == 2 else x
        if self.max_pool is not None:
            x = self.max_pool(x)
        if self.pad > 0:
            x = F.pad(x, (0, 0, 0, 0, 0, self.pad))
        return F.relu(self.convs(h) + x)


class BlazeFace(nn.Module):
    def __init__(self):
        super().__init__()
        widths = [(24, 24, 1), (24, 28, 1), (28, 32, 2), (32, 36, 1), (36, 42, 1), (42, 48, 2), (48, 56, 1),
                  (56, 64, 1), (64, 72, 1), (72, 80, 1), (80, 88, 1)]
        self.backbone1 = nn.Sequential(nn.Conv2d(3, 24, 5, 2, 0), nn.ReLU(inplace=True),
                                       *[_Block(a, b, s) for a, b, s in widths])
        self.backbone2 = nn.Sequential(_Block(88, 96, 2), *[_Block(96, 96) for _ in range(4)])
        self.classifier_8 = nn.Conv2d(88, 2, 1)
        self.classifier_16 = nn.Conv2d(96, 6, 1)
        self.regressor_8 = nn.Conv2d(88, 32, 1)
        self.regressor_16 = nn.Conv2d(96, 96, 1)

    def forward(self, x):
        x = self.backbone1(F.pad(x, (1, 2, 1, 2)))
        h = self.backbone2(x)
        b = x.shape[0]
        scores = torch.cat([self.classifier_8(x).permute(0, 2, 3, 1).reshape(b, -1),
                            self.classifier_16(h).permute(0, 2, 3, 1).reshape(b, -1)], dim=1)
        boxes = torch.cat([self.regressor_8(x).permute(0, 2, 3, 1).reshape(b, -1, 16),
                           self.regressor_16(h).permute(0, 2, 3, 1).reshape(b, -1, 16)], dim=1)
        return boxes, scores


def anchors() -> torch.Tensor:
    """The 896 anchor centres of the front model: a 16 × 16 grid with 2 anchors and an 8 × 8 grid with 6."""
    out = []
    for grid, per in ((16, 2), (8, 6)):
        for y in range(grid):
            for x in range(grid):
                out += [((x + 0.5) / grid, (y + 0.5) / grid)] * per
    return torch.tensor(out, dtype=torch.float32)


def decode(boxes: torch.Tensor, scores: torch.Tensor, anchor: torch.Tensor) -> torch.Tensor:
    """[N, 17]: ymin, xmin, ymax, xmax, six key points (x, y), score – in 0..1 of the input; above ``SCORE``."""
    raw = boxes / SIZE
    out = torch.zeros(boxes.shape[0], 17)
    cx, cy = raw[:, 0] + anchor[:, 0], raw[:, 1] + anchor[:, 1]
    w, h = raw[:, 2], raw[:, 3]
    out[:, 0], out[:, 1], out[:, 2], out[:, 3] = cy - h / 2, cx - w / 2, cy + h / 2, cx + w / 2
    for k in range(6):
        out[:, 4 + 2 * k] = raw[:, 4 + 2 * k] + anchor[:, 0]
        out[:, 5 + 2 * k] = raw[:, 5 + 2 * k] + anchor[:, 1]
    out[:, 16] = scores.clamp(-100, 100).sigmoid()
    return out[out[:, 16] >= SCORE]


def _iou(a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
    y0, x0 = torch.maximum(a[0], b[:, 0]), torch.maximum(a[1], b[:, 1])
    y1, x1 = torch.minimum(a[2], b[:, 2]), torch.minimum(a[3], b[:, 3])
    inter = (y1 - y0).clamp(min=0) * (x1 - x0).clamp(min=0)
    area = (a[2] - a[0]) * (a[3] - a[1]) + (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1]) - inter
    return inter / area.clamp(min=1e-9)


def blend(dets: torch.Tensor) -> list[torch.Tensor]:
    """BlazeFace's weighted non-maximum suppression: overlapping detections are averaged by their scores."""
    faces = []
    order = torch.argsort(dets[:, 16], descending=True)
    while len(order):
        first = dets[order[0]]
        same = _iou(first, dets[order, :4]) > NMS_IOU
        group = dets[order[same]]
        w = group[:, 16:17]
        face = first.clone()
        face[:16] = (group[:, :16] * w).sum(0) / w.sum()
        face[16] = group[:, 16].mean()
        faces.append(face)
        order = order[~same]
    return faces


def load(path: str, device="cpu") -> BlazeFace:
    net = BlazeFace()
    net.load_state_dict(torch.load(path, map_location="cpu", weights_only=True))
    return net.eval().to(device)


def find_faces(image: Image.Image, net: BlazeFace) -> list[dict]:
    """Faces in ``image``: {"box": (x0, y0, x1, y1), "points": {name: (x, y)}, "score"} in image pixels, the
    largest first. The picture is padded to a square first (BlazeFace looks at a square)."""
    w, h = image.size
    side = max(w, h)
    square = Image.new("RGB", (side, side), (0, 0, 0))
    ox, oy = (side - w) // 2, (side - h) // 2
    square.paste(image.convert("RGB"), (ox, oy))
    x = torch.from_numpy(np.asarray(square.resize((SIZE, SIZE), Image.BILINEAR), dtype=np.float32))
    x = (x.permute(2, 0, 1)[None] / 127.5 - 1.0).to(next(net.parameters()).device)
    with torch.no_grad():
        boxes, scores = net(x)
    faces = []
    for f in blend(decode(boxes[0].cpu(), scores[0].cpu(), anchors())):
        def px(v, off):
            return float(v) * side - off

        pts = {name: (px(f[4 + 2 * k], ox), px(f[5 + 2 * k], oy)) for k, name in enumerate(KEYPOINTS)}
        faces.append({"box": (px(f[1], ox), px(f[0], oy), px(f[3], ox), px(f[2], oy)), "points": pts,
                      "score": float(f[16])})
    faces.sort(key=lambda f: (f["box"][2] - f["box"][0]) * (f["box"][3] - f["box"][1]), reverse=True)
    return faces


def plausible(face: dict) -> bool:
    """A face the portrait mode can trust: confident, the eyes above the nose above the mouth, the eyes apart
    (the detector also answers on flowers and animals now and then)."""
    x0, _y0, x1, _y1 = face["box"]
    p = face["points"]
    eyes_y = (p["left_eye"][1] + p["right_eye"][1]) / 2
    eye_gap = abs(p["left_eye"][0] - p["right_eye"][0]) / max(x1 - x0, 1e-6)
    return face["score"] >= ACCEPT and eyes_y < p["nose"][1] < p["mouth"][1] and eye_gap >= 0.1


def detail_map(size: tuple[int, int], faces: list[dict]) -> np.ndarray:
    """A detail map (uint8, 128 normal) with "more" on the eyes, the nose and the mouth of every face and a little
    more on the whole face."""
    from . import details

    w, h = size
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    more = np.zeros((h, w), dtype=np.float32)
    for f in faces:
        x0, y0, x1, y1 = f["box"]
        fw = max(x1 - x0, 1.0)
        cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2 * 1.05, (y1 - y0) / 2 * 1.2
        face = np.clip(1.4 - np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2), 0, 1) * 0.35
        more = np.maximum(more, face)
        for name, (r, strength) in {"right_eye": (0.16, 1.0), "left_eye": (0.16, 1.0), "nose": (0.12, 0.7),
                                    "mouth": (0.2, 0.9)}.items():
            px, py = f["points"][name]
            d = np.sqrt((xx - px) ** 2 + ((yy - py) * (1.4 if name == "mouth" else 1.0)) ** 2) / (r * fw)
            more = np.maximum(more, np.clip(1.25 - d, 0, 1) * strength)
    return np.clip(np.round(details.NORMAL + more * 127), 0, 255).astype(np.uint8)
