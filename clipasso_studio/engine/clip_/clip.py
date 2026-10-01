"""CLIP loader (port of CLIP_/clip/clip.py from the CLIPasso repository, MIT licence).

Models are loaded from the local model store instead of being downloaded at runtime.
"""

from __future__ import annotations

from typing import List, Union

import torch
from torchvision.transforms import CenterCrop, Compose, InterpolationMode, Normalize, Resize, ToTensor

from .. import model_store
from .model import build_model
from .simple_tokenizer import SimpleTokenizer as _Tokenizer

__all__ = ["available_models", "load", "tokenize"]

_tokenizer = None


def _get_tokenizer() -> _Tokenizer:
    global _tokenizer
    if _tokenizer is None:
        _tokenizer = _Tokenizer()
    return _tokenizer


def _convert_image_to_rgb(image):
    return image.convert("RGB")


def _transform(n_px):
    return Compose([
        Resize(n_px, interpolation=InterpolationMode.BICUBIC),
        CenterCrop(n_px),
        _convert_image_to_rgb,
        ToTensor(),
        Normalize((0.48145466, 0.4578275, 0.40821073), (0.26862954, 0.26130258, 0.27577711)),
    ])


def available_models() -> List[str]:
    return [k.split(":", 1)[1] for k in model_store.SPECS if k.startswith("clip:")]


_loaded: dict = {}


def load(name: str, device: Union[str, torch.device] = "cpu", jit: bool = False):
    """Load a CLIP model -> (model, preprocess). Same behaviour as ``clip.load(..., jit=False)``:
    fp16 weights on CUDA, fp32 on CPU. Weights are frozen (``requires_grad=False``): only the
    sketch is optimised, so gradients for the CLIP weights were never needed.

    A model is loaded once per process and shared (CLIPasso used to load it up to three times per
    sketch); callers must not change it. Building it does not touch the random number generator,
    so a sketch is the same whether the model was cached or not."""
    key = (name, str(torch.device(device)))
    if key not in _loaded:
        state_dict = model_store.load_state(model_store.clip_key(name))
        with torch.random.fork_rng(devices=[]):  # the random init is replaced by the weights
            model = build_model(state_dict).to(device)
        if torch.device(device).type == "cpu":
            model.float()
        model.requires_grad_(False)
        model.eval()
        _loaded[key] = (model, _transform(model.visual.input_resolution))
    return _loaded[key]


def release_models() -> None:
    """Forget the loaded models (their memory is freed when nothing else uses them)."""
    _loaded.clear()


def tokenize(texts: Union[str, List[str]], context_length: int = 77) -> torch.LongTensor:
    if isinstance(texts, str):
        texts = [texts]
    tok = _get_tokenizer()
    sot_token = tok.encoder["<|startoftext|>"]
    eot_token = tok.encoder["<|endoftext|>"]
    all_tokens = [[sot_token] + tok.encode(text) + [eot_token] for text in texts]
    result = torch.zeros(len(all_tokens), context_length, dtype=torch.long)
    for i, tokens in enumerate(all_tokens):
        if len(tokens) > context_length:
            tokens = tokens[:context_length - 1] + [eot_token]
        result[i, :len(tokens)] = torch.tensor(tokens)
    return result
