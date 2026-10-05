"""Which of a job's sketches is the best: as before the one most like the photo ("faithful"), or the one most like
the photo *and* nicest to look at – by LAION's aesthetic predictor ("beautiful") or by the user's own taste, learnt
from their thumbs up and down ("mine").

Everything works on the CLIP ViT-B/32 embedding of a sketch (rendered on white), which the job keeps next to every
sketch (``clip_embedding.npz``, with a hash of the sketch it belongs to); reading and choosing need numpy only.

- LAION-Aesthetics Predictor V1 (MIT): a linear layer on the normalised embedding, about 1 … 10
  (``resources/aesthetic/laion_vit_b_32.npz``, converted from ``sa_0_4_vit_b_32_linear.pth``).
- The own taste: every rating is kept with its embedding (``<app data>/taste.json``, so it outlives moved or deleted
  jobs); from ``MIN_RATINGS`` on, with both thumbs used, a logistic regression is fitted on them.

The look is added to the CLIP score on a fixed scale, so a sketch a little less like the photo can win if it is
clearly nicer – never one that is far off (``FIDELITY_GUARD``)."""

from __future__ import annotations

import hashlib
import json
import os
import time

import numpy as np

from .. import paths

EMB_FILE = "clip_embedding.npz"
TASTE_FILE = "taste.json"
MODES = ("faithful", "beautiful", "mine")
MIN_RATINGS = 10
SCALE = 10.0  # differences between sketch embeddings are small (unit vectors); scaled before the regression
RIDGE = 1.0
# how the look is weighed against the likeness (CLIP points): see ``choose``
BEAUTY_UNIT = 0.25
TASTE_UNIT = 1.0
FIDELITY_GUARD = 3.0

_head: tuple[np.ndarray, float] | None = None


# ------------------------------------------------------------------ embeddings of the sketches
def digest(svg_text: str) -> str:
    return hashlib.sha1(svg_text.encode("utf-8")).hexdigest()


def _read_text(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def save_embedding(run_dir: str, svg_path: str, emb: np.ndarray) -> str:
    out = os.path.join(run_dir, EMB_FILE)
    tmp = out + f".{os.getpid()}.tmp.npz"
    np.savez(tmp, emb=np.asarray(emb, dtype=np.float32), sha1=np.array(digest(_read_text(svg_path) or "")))
    os.replace(tmp, out)
    return out


def read_embedding(run_dir: str, svg_path: str | None = None) -> np.ndarray | None:
    """The embedding kept in ``run_dir`` – None if there is none, or if it belongs to another sketch than
    ``svg_path`` (e.g. erased since)."""
    try:
        with np.load(os.path.join(run_dir, EMB_FILE), allow_pickle=False) as data:
            emb, sha1 = np.asarray(data["emb"], dtype=np.float32), str(data["sha1"])
    except (OSError, ValueError, KeyError):
        return None
    if svg_path is not None and sha1 != digest(_read_text(svg_path) or ""):
        return None
    return emb if emb.shape == (512,) and np.isfinite(emb).all() else None


def compute_embedding(run_dir: str, svg_path: str | None = None, device="cpu") -> np.ndarray:
    """Embed the sketch of a run (the edited one, if there is one) and keep it (``--embed RUN_DIR``)."""
    from . import jobs
    from .scoring import get_scorer

    svg_path = svg_path or jobs.sketch_file(run_dir)
    emb = get_scorer(device).embed_svg(svg_path)
    save_embedding(run_dir, svg_path, emb)
    return emb


# ------------------------------------------------------------------ LAION aesthetic score
def head() -> tuple[np.ndarray, float]:
    global _head
    if _head is None:
        with np.load(paths.resource("aesthetic", "laion_vit_b_32.npz"), allow_pickle=False) as data:
            _head = np.asarray(data["weight"], dtype=np.float32), float(data["bias"])
    return _head


def beauty(emb: np.ndarray) -> float:
    """LAION's aesthetic score (about 1 … 10) of a normalised CLIP ViT-B/32 embedding."""
    w, b = head()
    return float(np.dot(w, emb) + b)


# ------------------------------------------------------------------ the own taste
def taste_path():
    return paths.user_data_dir() / TASTE_FILE


def load_taste() -> dict:
    try:
        with open(taste_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict) or not isinstance(data.get("samples"), dict):
        data = {"samples": {}, "model": None}
    return data


def _save_taste(data: dict) -> None:
    path = taste_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def train(embs: np.ndarray, labels: np.ndarray) -> dict | None:
    """Logistic regression (ridge, Newton steps) of thumbs up (1) / down (0) on the embeddings; None with fewer than
    ``MIN_RATINGS`` ratings or only one kind of thumb."""
    x = np.asarray(embs, dtype=np.float64)
    y = np.asarray(labels, dtype=np.float64)
    if len(y) < MIN_RATINGS or y.min() == y.max():
        return None
    mean = x.mean(axis=0)
    xs = np.hstack([(x - mean) * SCALE, np.ones((len(y), 1))])
    w = np.zeros(xs.shape[1])
    reg = np.full(xs.shape[1], RIDGE)
    reg[-1] = 1e-6  # (the bias is not held back)
    for _ in range(25):
        p = 1.0 / (1.0 + np.exp(-np.clip(xs @ w, -30, 30)))
        grad = xs.T @ (p - y) + reg * w
        hess = (xs * (p * (1 - p))[:, None]).T @ xs + np.diag(reg)
        step = np.linalg.solve(hess, grad)
        w -= step
        if np.abs(step).max() < 1e-6:
            break
    return {"mean": mean.astype(np.float32).round(6).tolist(), "w": w[:-1].astype(np.float32).round(6).tolist(),
            "b": float(w[-1]), "n": int(len(y)), "up": int(y.sum()), "trained": time.strftime("%Y-%m-%d %H:%M:%S")}


def taste(emb: np.ndarray, model: dict) -> float:
    """How much the user would like the sketch (the regression's logit; > 0 = rather a thumb up)."""
    x = (np.asarray(emb, dtype=np.float64) - np.asarray(model["mean"])) * SCALE
    return float(x @ np.asarray(model["w"]) + model["b"])


def set_rating(key: str, emb: np.ndarray | None, value: int | None) -> dict:
    """Keep (value ±1) or forget (None) the rating of a sketch and fit the taste again; returns the taste data."""
    data = load_taste()
    if value is None or emb is None:
        data["samples"].pop(key, None)
    else:
        data["samples"][key] = {"y": 1 if value > 0 else -1,
                                "emb": np.asarray(emb, dtype=np.float32).round(5).tolist()}
    samples = [s for s in data["samples"].values() if isinstance(s, dict) and len(s.get("emb") or ()) == 512]
    data["model"] = train(np.array([s["emb"] for s in samples]), np.array([s["y"] > 0 for s in samples])) \
        if samples else None
    _save_taste(data)
    return data


def forget_taste() -> None:
    try:
        taste_path().unlink()
    except OSError:
        pass


def counts(data: dict | None = None) -> tuple[int, int]:
    """(thumbs up, thumbs down) given so far."""
    data = data if data is not None else load_taste()
    ys = [s.get("y") for s in data["samples"].values() if isinstance(s, dict)]
    return sum(1 for y in ys if y == 1), sum(1 for y in ys if y == -1)


# ------------------------------------------------------------------ choosing
def choose(fidelity: list[float], embs: list[np.ndarray | None], mode: str = "faithful", model: dict | None = None,
           clip: list[float | None] | None = None) -> int:
    """Index of the best sketch. ``fidelity``: how much each one is like the photo (higher is better; the method's
    own measure), ``clip``: their CLIP scores (in percent). "beautiful" / "mine" add the look to the CLIP score –
    ``BEAUTY_UNIT`` LAION points or ``TASTE_UNIT`` of the taste weigh as much as a CLIP point – among the sketches
    at most ``FIDELITY_GUARD`` CLIP points behind the most similar one."""
    best = int(np.argmax(fidelity))
    if mode not in ("beautiful", "mine") or len(fidelity) < 2 or any(e is None for e in embs) \
            or not clip or any(c is None for c in clip):
        return best
    if mode == "mine":
        if not model:
            return best  # not enough ratings yet: as before
        look = [taste(e, model) / TASTE_UNIT for e in embs]
    else:
        look = [beauty(e) / BEAUTY_UNIT for e in embs]
    top = max(clip)
    value = [c + v if c >= top - FIDELITY_GUARD else -np.inf for c, v in zip(clip, look)]
    return int(np.argmax(value))
