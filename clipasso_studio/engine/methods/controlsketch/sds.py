"""Score distillation with Stable Diffusion 1.5 + ControlNet (``control_sds_loss_file.ControlSDSLoss``).

The rendered sketch is encoded with the VAE, noised at a random timestep in [50, 950) and denoised by
the UNet with classifier-free guidance, where the ControlNet (condition image of the input) steers
the conditional branch. The SDS gradient w(t) * (eps_pred - eps) is pushed back into the latent.
"""

from __future__ import annotations

import json

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
                 conditioning_scale: float = 0.15, diffusion_timesteps: int = 1000, device="cpu"):
        self.unet, self.controlnet, self.vae = unet, controlnet, vae
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
        latent = self.vae.encode(x.to(self.dtype)).latent_dist.sample() * self.scaling
        with torch.no_grad():
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
    return torch.float16 if torch.device(device).type == "cuda" else torch.float32


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
    config = json.loads((root / "scheduler" / "scheduler_config.json").read_text(encoding="utf-8"))
    return unet, controlnet, vae, tokenizer, text_encoder, alphas_cumprod_from_config(config)


def embed_text(tokenizer, text_encoder, caption: str, device) -> tuple[torch.Tensor, torch.Tensor]:
    """-> (text embeddings, empty-prompt embeddings), each [1, 77, 768]."""
    ids = tokenizer(caption, padding="max_length", max_length=tokenizer.model_max_length, truncation=True,
                    return_tensors="pt").input_ids
    uncond = tokenizer([""], padding="max_length", max_length=ids.shape[-1], return_tensors="pt").input_ids
    with torch.no_grad():
        text = text_encoder(ids.to(device))[0]
        empty = text_encoder(uncond.to(device))[0]
    return text, empty
