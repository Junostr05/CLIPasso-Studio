"""How much each stroke of a sketch adds – for the "Simplify" slider of the studio, which hides the least
important strokes first.

Measured with CLIP (``ClipScorer.stroke_importance``: how far the score falls without a stroke) in a process of
its own (``--importance RUN_DIR``, a few seconds), and kept in ``importance.json`` of the run together with a hash
of the sketch it belongs to (an erased or edited sketch is measured again). Reading needs no torch. (Length, width
and opacity of a stroke turned out to say little about its importance – no estimate stands in.)"""

from __future__ import annotations

import hashlib
import json
import os

FILE = "importance.json"


def digest(svg: str) -> str:
    return hashlib.sha1(svg.encode("utf-8")).hexdigest()


def read(run_dir: str, svg: str) -> list[float] | None:
    """The measured importance of every stroke of ``svg`` (None when it was not measured for this sketch)."""
    try:
        with open(os.path.join(run_dir, FILE), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("sha1") != digest(svg):
        return None
    drops = data.get("drops")
    return [float(v) for v in drops] if isinstance(drops, list) else None


def order(values: list[float]) -> list[int]:
    """Stroke indices from the least to the most important."""
    return sorted(range(len(values)), key=lambda i: (values[i], i))


def compute(run_dir: str, device: str = "cpu") -> str:
    """Measure the strokes of the run's sketch (the edited one, if there is one) and write ``importance.json``;
    returns its path."""
    from PIL import Image

    from . import jobs
    from .scoring import get_scorer

    svg_path = jobs.sketch_file(run_dir)
    with open(svg_path, encoding="utf-8") as f:
        svg = f.read()
    target = os.path.join(run_dir, "input.png")
    if not os.path.isfile(target):
        raise FileNotFoundError(f"no input picture in {run_dir}")
    with Image.open(target) as img:
        base, drops = get_scorer(device).stroke_importance(svg_path, img.convert("RGB"))
    out = os.path.join(run_dir, FILE)
    with open(out + ".tmp", "w", encoding="utf-8") as f:
        json.dump({"sha1": digest(svg), "base": round(base, 3), "drops": [round(d, 4) for d in drops]}, f)
    os.replace(out + ".tmp", out)
    return out
