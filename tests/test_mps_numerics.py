"""The Apple GPU (MPS) computes what the CPU computes – run on a Mac with MPS (the macOS workflow's engine job),
skipped elsewhere.

- The augmentations of the CLIP losses go backwards on the GPU itself: without the CPU fallback (which made every
  CLIPasso step 2.6–6.7× slower, docs/macos/plan.md §7) their backward pass has to exist on MPS.
- CLIP sees on the GPU what it sees on the CPU (a job's own CLIP score came out at 90–96 on MPS where the CPU gave
  50–68): its image features agree – and where they do not, the first layer that differs is named.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest
import torch

MPS = bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available())
pytestmark = pytest.mark.skipif(not MPS, reason="no Apple GPU (MPS) here")


def test_the_augmentations_go_backwards_on_the_gpu():
    code = textwrap.dedent("""
        from types import SimpleNamespace
        import torch
        from clipasso_studio.engine import losses
        args = SimpleNamespace(augemntations=["affine"], aug_scale_min=0.8, device=torch.device("mps"))
        aug = losses._affine_augmentations(args)
        x = torch.rand(2, 3, 224, 224, device="mps", requires_grad=True)
        aug(x).square().mean().backward()
        bank = losses.AugmentBank(seed=1, size=224, scale=0.8, count=4)
        y = torch.rand(1, 3, 224, 224, device="mps", requires_grad=True)
        torch.cat([bank.apply(y, i) for i in range(4)]).square().mean().backward()
        assert x.grad is not None and y.grad is not None
        print("ok")
    """)
    env = {k: v for k, v in os.environ.items() if k != "PYTORCH_ENABLE_MPS_FALLBACK"}  # (no CPU fallback)
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=600)
    assert done.returncode == 0 and "ok" in done.stdout, done.stderr[-3000:]


def _first_difference(cpu_model, gpu_model, images: torch.Tensor) -> str:
    """The layers of the vision transformer on both devices: the first whose output differs, with how much."""
    outputs: dict[str, list[torch.Tensor]] = {}

    def keep(name):
        def hook(_module, _inputs, output):
            out = output[0] if isinstance(output, tuple) else output
            outputs.setdefault(name, []).append(out.detach().float().cpu())
        return hook

    names = []
    for model in (cpu_model, gpu_model):
        visual = model.visual
        parts = [("conv1", visual.conv1), ("ln_pre", visual.ln_pre)]
        parts += [(f"block{i}", block) for i, block in enumerate(visual.transformer.resblocks)]
        parts += [("ln_post", visual.ln_post)]
        handles = [module.register_forward_hook(keep(name)) for name, module in parts]
        names = [name for name, _ in parts]
        with torch.no_grad():
            model.encode_image(images.to(next(model.parameters()).device))
        for h in handles:
            h.remove()
    lines = []
    for name in names:
        a, b = outputs[name]
        rel = float((a - b).abs().max() / (a.abs().max() + 1e-9))
        lines.append(f"{name}: relative difference {rel:.2e}")
        if rel > 1e-3:
            return "first layer that differs – " + lines[-1] + "\n" + "\n".join(lines)
    return "no layer differs by more than 1e-3:\n" + "\n".join(lines)


def test_clip_sees_on_the_gpu_what_it_sees_on_the_cpu():
    from clipasso_studio.engine import model_store
    from clipasso_studio.engine.clip_ import clip

    if not model_store.is_available(model_store.clip_key("ViT-B/32")):
        pytest.skip("CLIP ViT-B/32 is not downloaded")
    cpu_model, _ = clip.load("ViT-B/32", "cpu")
    gpu_model, _ = clip.load("ViT-B/32", "mps")
    g = torch.Generator().manual_seed(0)
    noise = torch.rand(2, 3, 224, 224, generator=g)
    white = torch.ones(1, 3, 224, 224)
    lines = torch.ones(1, 3, 224, 224)
    lines[:, :, 60:64, 20:200] = 0  # (a sketch: a few dark lines on white)
    lines[:, :, 30:190, 110:113] = 0
    images = (torch.cat([noise, white, lines]) - 0.45) / 0.27
    with torch.no_grad():
        a = cpu_model.encode_image(images).float()
        b = gpu_model.encode_image(images.to("mps")).float().cpu()
    cos = torch.nn.functional.cosine_similarity(a, b, dim=-1)
    assert float(cos.min()) > 0.999, f"cosine CPU/MPS per image {cos.tolist()}\n" + \
        _first_difference(cpu_model, gpu_model, images)
    # (and the images stay apart on the GPU as on the CPU: white against the lines)
    na, nb = torch.nn.functional.normalize(a, dim=-1), torch.nn.functional.normalize(b, dim=-1)
    assert abs(float(na[2] @ na[3]) - float(nb[2] @ nb[3])) < 1e-3
