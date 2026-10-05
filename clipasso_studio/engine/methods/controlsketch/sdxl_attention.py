"""Object attention from SDXL cross-attention (``attn_model = diffusion``; ``painter_params.diffusion_attn``).

The input is DDIM-inverted with the prompt "a portrait of a <object>", the generation is then
steered along the inverted latents while the cross-attention maps of every layer and step are
collected; the map of the object token is the stroke-initialisation attention.

Differences to the original: the per-layer maps are averaged on the fly instead of being kept in
memory (identical result), and the maps of any latent grid are resized to the 1/16 resolution grid.
"""

from __future__ import annotations

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

from ... import model_store
from .conditions import _hf_offline

PROMPT = "a portrait of a {}"
STEPS = 50


class _AttentionAverage:
    """Running mean of ``upscale``d conditional cross-attention maps: [77, g*g]."""

    def __init__(self, grid: int):
        self.grid = grid
        self.total = None
        self.count = 0

    def add(self, probs: torch.Tensor) -> None:  # [2 * heads, tokens, 77] (uncond, cond)
        m = torch.chunk(probs, 2)[1].float().mean(0).permute(1, 0)  # [77, tokens]
        side = int(round(m.shape[1] ** 0.5))
        if side != self.grid:
            m = F.interpolate(m.reshape(1, m.shape[0], side, side), size=(self.grid, self.grid), mode="bilinear",
                              align_corners=False)[0]
        m = torch.softmax(m.reshape(m.shape[0], -1), dim=0).cpu()
        self.total = m if self.total is None else self.total + m
        self.count += 1

    def result(self) -> torch.Tensor:
        return (self.total / max(self.count, 1)).reshape(-1, self.grid, self.grid)


class _StoreProcessor:
    """Plain attention (like ``AttnStoreProcessor`` of the original) that reports cross-attention maps."""

    def __init__(self, store: _AttentionAverage):
        self.store = store

    def __call__(self, attn, hidden_states, encoder_hidden_states=None, attention_mask=None, **kwargs):
        cross = encoder_hidden_states is not None
        encoder_hidden_states = encoder_hidden_states if cross else hidden_states
        query = attn.head_to_batch_dim(attn.to_q(hidden_states))
        key = attn.head_to_batch_dim(attn.to_k(encoder_hidden_states))
        value = attn.head_to_batch_dim(attn.to_v(encoder_hidden_states))
        probs = attn.get_attention_scores(query, key, attention_mask)
        if cross:
            self.store.add(probs.detach())
        out = attn.batch_to_head_dim(torch.bmm(probs, value))
        return attn.to_out[1](attn.to_out[0](out))


def _text_embeddings(prompt: str, tokenizer, text_encoder, device):
    ids = tokenizer(prompt, padding="max_length", max_length=tokenizer.model_max_length, truncation=True,
                    return_tensors="pt").input_ids.to(device)
    with torch.no_grad():
        out = text_encoder(ids, output_hidden_states=True)
    pooled, embeds = out[0], out.hidden_states[-2]
    if prompt == "":
        return torch.zeros_like(embeds), torch.zeros_like(pooled)
    return embeds, pooled


def _encode_prompt(pipe, prompt: str, size: int):
    device = pipe._execution_device
    e1, _ = _text_embeddings(prompt, pipe.tokenizer, pipe.text_encoder, device)
    e2, pooled2 = _text_embeddings(prompt, pipe.tokenizer_2, pipe.text_encoder_2, device)
    time_ids = pipe._get_add_time_ids((size, size), (0, 0), (size, size), dtype=pipe.unet.dtype,
                                      text_encoder_projection_dim=pipe.text_encoder_2.config.projection_dim).to(device)
    return {"text_embeds": pooled2, "time_ids": time_ids}, torch.cat((e1, e2), dim=-1)


def _encode_prompt_with_negative(pipe, prompt: str, size: int):
    cond_kw, cond = _encode_prompt(pipe, prompt, size)
    unc_kw, unc = _encode_prompt(pipe, "", size)
    return ({k: torch.cat((unc_kw[k], cond_kw[k])) for k in cond_kw}, torch.cat((unc, cond)))


def ddim_inversion(pipe, image: np.ndarray, prompt: str, steps: int, guidance_scale: float, size: int,
                   tick=None) -> torch.Tensor:
    """Latents z_T .. z_0 of the DDIM inversion ([steps + 1, 4, h, w], noisiest first); ``tick(i)`` before
    every step."""
    vae_dtype = pipe.vae.dtype
    pipe.vae.to(dtype=torch.float32)
    x = torch.from_numpy(image).float() / 255.0
    x = (x * 2 - 1).permute(2, 0, 1).unsqueeze(0).to(pipe.vae.device)
    with torch.no_grad():
        z0 = pipe.vae.encode(x)["latent_dist"].mean * pipe.vae.config.scaling_factor
    pipe.vae.to(dtype=vae_dtype)
    sched = pipe.scheduler
    sched.set_timesteps(steps, device=z0.device)
    added, context = _encode_prompt_with_negative(pipe, prompt, size)
    latent = z0.clone().to(pipe.unet.dtype)
    all_latents = [z0.to(pipe.unet.dtype)]
    step = sched.config.num_train_timesteps // sched.num_inference_steps
    for i in range(sched.num_inference_steps):
        if tick is not None:
            tick(i)
        t = sched.timesteps[len(sched.timesteps) - i - 1]
        with torch.no_grad():
            noise = pipe.unet(torch.cat([latent] * 2), t, encoder_hidden_states=context,
                              added_cond_kwargs=added)["sample"]
        uncond, text = noise.chunk(2)
        noise = uncond + guidance_scale * (text - uncond)
        cur, nxt = min(int(t) - step, 999), int(t)
        a_t = sched.alphas_cumprod[cur] if cur >= 0 else sched.final_alpha_cumprod
        a_next = sched.alphas_cumprod[nxt]
        x0 = (latent - (1 - a_t) ** 0.5 * noise) / a_t ** 0.5
        latent = (a_next ** 0.5 * x0 + (1 - a_next) ** 0.5 * noise).to(pipe.unet.dtype)
        all_latents.append(latent)
    return torch.cat(all_latents).flip(0)


def token_index(tokenizer, prompt: str, position: int = 4) -> int:
    """Index (in the 77 tokens) of the ``position``-th word token – the object in "a portrait of a X"."""
    ids = tokenizer(prompt, padding="max_length", max_length=tokenizer.model_max_length, truncation=True,
                    return_tensors="pt").input_ids[0].tolist()
    special = {tokenizer.bos_token_id, tokenizer.eos_token_id, tokenizer.pad_token_id}
    words = [i for i, tok in enumerate(ids) if tok not in special]
    return words[min(position, len(words) - 1)] if words else 0


def load_pipeline(device, spec_key: str = "sdxl", offload: bool = False):
    """SDXL on ``device``. ``offload``: for a graphics card too small for it, the networks stay in the RAM and
    every layer goes onto the card only while it computes (about 2 GB of graphics memory instead of 7)."""
    _hf_offline()
    from diffusers import DDIMScheduler, StableDiffusionXLPipeline

    from ...precision import gpu_dtype

    dtype = gpu_dtype(device)
    scheduler = DDIMScheduler(beta_start=0.00085, beta_end=0.012, beta_schedule="scaled_linear", clip_sample=False,
                              set_alpha_to_one=False)
    pipe = StableDiffusionXLPipeline.from_pretrained(str(model_store.model_dir(spec_key)), torch_dtype=dtype,
                                                     scheduler=scheduler)
    pipe.set_progress_bar_config(disable=True)
    if offload:
        # the VAE (small) stays on the card as a whole: ddim_inversion encodes the photo with it in float32
        pipe._exclude_from_cpu_offload = ["vae"]
        pipe.enable_sequential_cpu_offload(gpu_id=torch.device(device).index or 0)
        return pipe
    return pipe.to(device)


MODES = ("gpu", "offload", "cpu")


def run_mode(device, place: str = "offload") -> str:
    """How the SDXL step runs: "gpu" (it fits), on a graphics card with less than ``SDXL_MIN_VRAM_GB``
    "offload" (piece by piece) or "cpu" as ``place`` says, "cpu" without a graphics card. The rest of
    ControlSketch stays on the card either way."""
    from ..requirements import sdxl_on_cpu

    device = torch.device(device)
    if device.type != "cuda":
        return "cpu"
    if sdxl_on_cpu(torch.cuda.get_device_properties(device).total_memory / 2 ** 30):
        return "cpu" if place == "cpu" else "offload"
    return "gpu"


def object_attention(image: Image.Image, object_name: str, device, size: int, place: str = "offload", tick=None,
                     log=None) -> torch.Tensor:
    """``sdxl_attention`` in the mode that fits (:func:`run_mode`); a graphics card that runs out of memory hands
    it on: the whole card → piece by piece → the CPU. ``tick(step, steps, mode, elapsed)`` is called before every
    network step (pause and stop; it may raise), ``log(code, **params)`` reports a mode other than the card."""
    import gc

    from ...runner import is_out_of_memory

    def report(code, **params):
        if log is not None:
            log(code, **params)

    mode = run_mode(device, place)
    chain = list(MODES[MODES.index(mode):])  # gpu → offload → cpu
    if mode != "gpu" and torch.device(device).type == "cuda":
        report(f"sdxl_{mode}", gb=f"{torch.cuda.get_device_properties(device).total_memory / 2 ** 30:.0f}")
    try:
        for i, m in enumerate(chain):
            if i:
                gc.collect()  # (outside the except block: the traceback no longer holds the tensors)
                torch.cuda.empty_cache()
                report(f"sdxl_{m}_oom")
            try:
                return sdxl_attention(image, object_name, torch.device("cpu") if m == "cpu" else device, size,
                                      tick=tick, offload=m == "offload")
            except Exception as exc:  # noqa: BLE001 - only running out of graphics memory is handled
                if m == "cpu" or not is_out_of_memory(exc):
                    raise
    finally:
        gc.collect()  # SDXL in the RAM (7–14 GB) goes before Stable Diffusion loads
    raise AssertionError("unreachable")  # (the CPU either returns or raises)


def sdxl_attention(image: Image.Image, object_name: str, device, size: int, pipe=None,
                   steps: int = STEPS, tick=None, offload: bool = False) -> torch.Tensor:
    """Attention of the object token -> [size, size] in [0, 1] (already squared like the original)."""
    import time

    pipe = pipe or load_pipeline(device, offload=offload)
    res = int(pipe.unet.config.sample_size * pipe.vae_scale_factor)
    prompt = PROMPT.format(object_name)
    mode = "cpu" if torch.device(device).type == "cpu" else "offload" if offload else "gpu"
    start = time.time()

    def step(done):  # network steps done of the inversion and the generation
        if tick is not None:
            tick(done, 2 * steps, mode, time.time() - start)

    zts = ddim_inversion(pipe, np.array(image.convert("RGB").resize((res, res))), prompt, steps, 2.0, res, step)
    step(steps)
    offset = min(5, steps - 1)  # 5 of 50 steps like the original

    def on_step_end(p, i, t, kwargs):
        step(steps + i + 1)
        latents = kwargs["latents"]
        latents[0] = zts[max(offset + 1, i + 1)].to(latents.device, latents.dtype)
        return {"latents": latents}

    store = _AttentionAverage(res // 16)
    processors = {name: (_StoreProcessor(store) if name.split(".")[-2].startswith("attn2") else proc)
                  for name, proc in pipe.unet.attn_processors.items()}
    original = pipe.unet.attn_processors
    pipe.unet.set_attn_processor(processors)
    try:
        g = torch.Generator(device="cpu").manual_seed(10)
        latent_side = res // pipe.vae_scale_factor
        latents = torch.randn(1, pipe.unet.config.in_channels, latent_side, latent_side, generator=g,
                              dtype=pipe.unet.dtype).to(device)
        latents[0] = zts[offset]
        pipe(prompt, latents=latents, callback_on_step_end=on_step_end, num_inference_steps=steps,
             guidance_scale=10.0, height=res, width=res, output_type="latent")
    finally:
        pipe.unet.set_attn_processor(original)
    maps = F.interpolate(store.result()[None], size=(res, res), mode="bilinear", align_corners=False)[0]
    attn = maps[token_index(pipe.tokenizer, prompt)]
    attn = ((attn - attn.min()) / (attn.max() - attn.min()).clamp_min(1e-12) * 255).to(torch.uint8).float()
    attn = (attn - attn.min()) / (attn.max() - attn.min()).clamp_min(1e-12)
    attn = attn ** 2
    return F.interpolate(attn[None, None], (size, size))[0, 0]
