"""Ancestral DDPM sampling for SwiftSketch (x0-prediction, fixed-small variance, cosine schedule)."""

from __future__ import annotations

import math
from typing import Callable, Iterator

import numpy as np
import torch


def cosine_betas(steps: int, power: float = 2.0, max_beta: float = 0.999) -> np.ndarray:
    """Betas for alpha_bar(t) = cos((t + 0.008) / 1.008 * pi / 2) ** power (Nichol & Dhariwal, with a
    configurable exponent)."""
    def alpha_bar(t):
        return math.cos((t + 0.008) / 1.008 * math.pi / 2) ** power

    return np.array([min(1 - alpha_bar((i + 1) / steps) / alpha_bar(i / steps), max_beta) for i in range(steps)],
                    dtype=np.float64)


class Sampler:
    def __init__(self, steps: int = 50, cos_power: float = 0.4):
        betas = cosine_betas(steps, cos_power)
        alphas = 1.0 - betas
        ac = np.cumprod(alphas)
        ac_prev = np.append(1.0, ac[:-1])
        self.steps = steps
        self.posterior_variance = betas * (1.0 - ac_prev) / (1.0 - ac)
        self.posterior_log_variance = np.log(np.append(self.posterior_variance[1], self.posterior_variance[1:]))
        self.coef1 = betas * np.sqrt(ac_prev) / (1.0 - ac)
        self.coef2 = (1.0 - ac_prev) * np.sqrt(alphas) / (1.0 - ac)

    def sample(self, predict_x0: Callable[[torch.Tensor, torch.Tensor], torch.Tensor], shape, device,
               generator: torch.Generator | None = None, noise: torch.Tensor | None = None
               ) -> Iterator[tuple[int, torch.Tensor, torch.Tensor]]:
        """Yields (step index, x_t after the step, predicted x0) from t = T-1 down to 0."""
        x = noise if noise is not None else torch.randn(*shape, generator=generator, device="cpu").to(device)
        for i in reversed(range(self.steps)):
            t = torch.full((shape[0],), i, dtype=torch.long, device=device)
            with torch.no_grad():
                x0 = predict_x0(x, t)
            mean = float(self.coef1[i]) * x0 + float(self.coef2[i]) * x
            if i > 0:
                z = torch.randn(*shape, generator=generator, device="cpu").to(device)
                x = mean + math.exp(0.5 * float(self.posterior_log_variance[i])) * z
            else:
                x = mean
            yield i, x, x0
