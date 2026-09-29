"""Automatic caption for the SDS prompt when none is given.

The original uses BLIP-2 OPT-2.7b (15 GB); BLIP-large (0.9 GB in float16) gives captions of the same
kind ("a pink flamingo standing on a white background").
"""

from __future__ import annotations

import torch
from PIL import Image

from ... import model_store
from .conditions import _hf_offline

_PROMPT = "a picture of"


def caption_image(image: Image.Image, device) -> str:
    _hf_offline()
    from transformers import BlipForConditionalGeneration, BlipProcessor

    path = str(model_store.model_dir("blip"))
    dtype = torch.float16 if torch.device(device).type == "cuda" else torch.float32
    processor = BlipProcessor.from_pretrained(path)
    model = BlipForConditionalGeneration.from_pretrained(path, torch_dtype=dtype).to(device).eval()
    inputs = processor(images=image.convert("RGB"), text=_PROMPT, return_tensors="pt").to(device)
    inputs["pixel_values"] = inputs["pixel_values"].to(dtype)
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=20, num_beams=3)
    text = processor.decode(out[0], skip_special_tokens=True).strip()
    del model
    if text.lower().startswith(_PROMPT):
        text = text[len(_PROMPT):].strip()
    return text or "an object"
