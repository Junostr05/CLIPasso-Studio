"""Score distillation with Stable Diffusion 1.5 + ControlNet (``control_sds_loss_file.ControlSDSLoss``).

The rendered sketch is encoded with the VAE, noised at a random timestep in [50, 950) and denoised by
the UNet with classifier-free guidance, where the ControlNet (condition image of the input) steers
the conditional branch. The SDS gradient w(t) * (eps_pred - eps) is pushed back into the latent.

Turbo mode: the Tiny AutoEncoder (TAESD) encodes the sketch instead of the SD VAE (on a CPU 8 s -> 1 s
for encoder and backward pass at 512 px), and on CPUs with bfloat16 support (AVX512-BF16 / AMX) the
UNet and ControlNet run in bfloat16 (about 2x).
"""

from __future__ import annotations

import functools
import json
import os
import subprocess
import sys

import torch

from ... import model_store
from .conditions import _hf_offline


def alphas_cumprod_from_config(config: dict) -> torch.Tensor:
    """alpha-bar of the SD scheduler (scaled_linear betas 0.00085 .. 0.012, 1000 steps)."""
    n = int(config.get("num_train_timesteps", 1000))
    b0, b1 = float(config.get("beta_start", 0.00085)), float(config.get("beta_end", 0.012))
    schedule = config.get("beta_schedule", "scaled_linear")
    if schedule == "scaled_linear":
        betas = torch.linspace(b0 ** 0.5, b1 ** 0.5, n, dtype=torch.float32) ** 2
    elif schedule == "linear":
        betas = torch.linspace(b0, b1, n, dtype=torch.float32)
    else:
        raise ValueError(f"unsupported beta schedule {schedule!r}")
    return torch.cumprod(1.0 - betas, dim=0)


class ControlSDSLoss:
    def __init__(self, unet, controlnet, vae, text_embeddings: torch.Tensor, uncond_embeddings: torch.Tensor,
                 condition_image: torch.Tensor, alphas_cumprod: torch.Tensor, guidance_scale: float = 100,
                 conditioning_scale: float = 0.15, diffusion_timesteps: int = 1000, device="cpu",
                 bf16: bool = False):
        self.unet, self.controlnet, self.vae = unet, controlnet, vae
        self.bf16 = bool(bf16)  # bfloat16 autocast for UNet + ControlNet (CPU, no gradient through them)
        self.device = torch.device(device)
        self.dtype = next(unet.parameters()).dtype
        self.text = text_embeddings.to(self.device, self.dtype)
        self.text_plus_uncond = torch.cat([uncond_embeddings, text_embeddings]).to(self.device, self.dtype)
        self.cond = condition_image.to(self.device, self.dtype)
        self.alphas = alphas_cumprod.to(self.device)
        self.sigmas = 1 - self.alphas
        self.guidance_scale = float(guidance_scale)
        self.conditioning_scale = float(conditioning_scale)
        self.t_high = min(950, int(diffusion_timesteps)) - 1
        self.scaling = float(getattr(getattr(vae, "config", None), "scaling_factor", 0.18215) or 0.18215)

    def __call__(self, x: torch.Tensor) -> torch.Tensor:
        """x: rendered sketch [1, 3, H, W] in [0, 1] (requires grad) -> scalar surrogate loss."""
        x = x * 2.0 - 1.0
        encoded = self.vae.encode(x.to(self.dtype))
        # TAESD gives the (already scaled) latents, the SD VAE a distribution to sample from
        latent = getattr(encoded, "latents", None)
        if latent is None:
            latent = encoded.latent_dist.sample()
        latent = latent * self.scaling
        with torch.no_grad(), torch.autocast("cpu", dtype=torch.bfloat16, enabled=self.bf16):
            t = torch.randint(50, max(self.t_high, 51), (latent.shape[0],), device=self.device, dtype=torch.long)
            eps = torch.randn_like(latent)
            a = self.alphas[t].view(-1, 1, 1, 1)
            zt = (a ** 0.5 * latent.float() + (1 - a) ** 0.5 * eps.float()).to(self.dtype)
            down, mid = self.controlnet(zt, t, encoder_hidden_states=self.text, controlnet_cond=self.cond,
                                        conditioning_scale=self.conditioning_scale, return_dict=False)
            # the ControlNet acts on the conditional half of the CFG batch only
            down = [torch.cat([torch.zeros_like(d), d]) for d in down]
            mid = torch.cat([torch.zeros_like(mid), mid])
            eps_uncond, eps_cond = self.unet(torch.cat([zt] * 2), t, encoder_hidden_states=self.text_plus_uncond,
                                             down_block_additional_residuals=down,
                                             mid_block_additional_residual=mid).sample.float().chunk(2)
            eps_t = eps_uncond + self.guidance_scale * (eps_cond - eps_uncond)
            w = (self.alphas[t] ** 0.5 * self.sigmas[t]).view(-1, 1, 1, 1)
            grad = torch.nan_to_num(w * (eps_t - eps.float()), 0.0, 0.0, 0.0)
        return (grad * latent.float()).sum(1).mean()


# ----------------------------------------------------------------------------- loading


def model_dtype(device) -> torch.dtype:
    from ...precision import gpu_dtype

    return gpu_dtype(device)


def load_sd15(condition: str, device):
    """-> (unet, controlnet, vae, tokenizer, text_encoder, alphas_cumprod) from the installed models."""
    _hf_offline()
    from diffusers import AutoencoderKL, ControlNetModel, UNet2DConditionModel
    from transformers import CLIPTextModel, CLIPTokenizer

    dtype = model_dtype(device)
    root = model_store.model_dir("sd15")
    unet = UNet2DConditionModel.from_pretrained(str(root / "unet"), torch_dtype=dtype)
    vae = AutoencoderKL.from_pretrained(str(root / "vae"), torch_dtype=dtype)
    controlnet = ControlNetModel.from_pretrained(str(model_store.model_dir(f"controlnet:{condition}")),
                                                 torch_dtype=dtype)
    tokenizer = CLIPTokenizer.from_pretrained(str(root / "tokenizer"))
    text_encoder = CLIPTextModel.from_pretrained(str(root / "text_encoder"), torch_dtype=dtype)
    for m in (unet, vae, controlnet, text_encoder):
        m.requires_grad_(False)
        m.eval()
        m.to(device)
    # channels-last convolutions: on a CPU measured 1.15x for the VAE (the UNet gains nothing there);
    # on a GPU for all three (fp16 tensor cores)
    for m in (vae, unet, controlnet) if torch.device(device).type == "cuda" else (vae,):
        m.to(memory_format=torch.channels_last)
    config = json.loads((root / "scheduler" / "scheduler_config.json").read_text(encoding="utf-8"))
    return unet, controlnet, vae, tokenizer, text_encoder, alphas_cumprod_from_config(config)


def load_taesd(device):
    """The Tiny AutoEncoder for SD (turbo mode); only its encoder is used."""
    _hf_offline()
    from diffusers import AutoencoderTiny

    vae = AutoencoderTiny.from_pretrained(str(model_store.model_dir("taesd")), torch_dtype=model_dtype(device))
    vae.requires_grad_(False)
    vae.eval()
    return vae.to(device)


BF16_CHECK_FLAG = "--bf16-check"
BF16_OK = "bf16 ok"
BF16_CHECK_TIMEOUT_S = 180


def cpu_bf16_fast() -> bool:
    """Does this CPU compute bfloat16 natively (AVX512-BF16 or AMX) – and does it really run here? Otherwise
    bfloat16 is slower, or ends the process (see :func:`bf16_runs`)."""
    return cpu_claims_bf16() and bf16_runs()


def cpu_claims_bf16() -> bool:
    try:
        return bool(torch.cpu._is_avx512_bf16_supported() or torch.cpu._is_amx_tile_supported())
    except Exception:
        return False


def bf16_check_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, BF16_CHECK_FLAG]
    return [sys.executable, "-m", "clipasso_studio", BF16_CHECK_FLAG]


@functools.lru_cache(maxsize=1)
def bf16_runs() -> bool:
    """The layers of the UNet once in bfloat16 – in a process of their own (:func:`bf16_check`): on a Windows
    machine a bfloat16 Linear ended the whole process with an illegal instruction (0xC000001D); here that is
    only a "no", and the sketch is drawn in float32."""
    env = {**os.environ, "PYINSTALLER_SUPPRESS_SPLASH_SCREEN": "1"}
    if not getattr(sys, "frozen", False):  # (run from the sources: the package wherever the working folder is)
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 4))
        env["PYTHONPATH"] = os.pathsep.join(p for p in (root, env.get("PYTHONPATH", "")) if p)
    try:
        done = subprocess.run(bf16_check_command(), capture_output=True, text=True, timeout=BF16_CHECK_TIMEOUT_S,
                              env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0  # (a windowed exe has no stdout: the exit code is the answer)


def bf16_check() -> int:
    """``--bf16-check``: what the SDS loss runs in bfloat16 – small and SD-sized linear layers, a convolution
    after a group norm, attention – once; 0 (and :data:`BF16_OK`) when the results are finite."""
    import torch.nn.functional as F

    torch.manual_seed(0)
    with torch.no_grad(), torch.autocast("cpu", dtype=torch.bfloat16):
        outs = [torch.nn.Linear(32, 128)(torch.randn(2, 32)), torch.nn.Linear(320, 1280)(torch.randn(2, 64, 320)),
                torch.nn.Conv2d(64, 64, 3, padding=1)(torch.nn.GroupNorm(8, 64)(torch.randn(1, 64, 32, 32))),
                F.scaled_dot_product_attention(*[torch.randn(2, 8, 64, 40)] * 3),
                torch.randn(2, 77, 768) @ torch.randn(768, 320)]
    if all(bool(torch.isfinite(o.float()).all()) for o in outs):
        print(BF16_OK, flush=True)
        return 0
    return 1


def embed_text(tokenizer, text_encoder, caption: str, device) -> tuple[torch.Tensor, torch.Tensor]:
    """-> (text embeddings, empty-prompt embeddings), each [1, 77, 768]."""
    ids = tokenizer(caption, padding="max_length", max_length=tokenizer.model_max_length, truncation=True,
                    return_tensors="pt").input_ids
    uncond = tokenizer([""], padding="max_length", max_length=ids.shape[-1], return_tensors="pt").input_ids
    with torch.no_grad():
        text = text_encoder(ids.to(device))[0]
        empty = text_encoder(uncond.to(device))[0]
    return text, empty
