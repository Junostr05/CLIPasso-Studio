"""The Apple GPU (MPS) computes what the CPU computes – run on a Mac with MPS (the macOS workflow's engine job),
skipped elsewhere.

- The augmentations of the CLIP losses go backwards on the GPU itself: without the CPU fallback (which made every
  CLIPasso step 2.6–6.7× slower, docs/macos/plan.md §7) their backward pass has to exist on MPS.
- The sampler that stands in for grid_sample on the GPU (mps_ops) gives there what grid_sample gives on the CPU.
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
        from clipasso_studio.engine.mps_ops import grid_sample_bilinear  # (the sketch guide's sampling)
        maps = torch.rand(1, 5, 64, 64, device="mps")
        pos = (torch.rand(1, 30, 1, 2, device="mps") * 2 - 1).requires_grad_(True)
        grid_sample_bilinear(maps, pos, padding_mode="border", align_corners=True).sum().backward()
        assert x.grad is not None and y.grad is not None and pos.grad is not None
        print("ok")
    """)
    env = {k: v for k, v in os.environ.items() if k != "PYTORCH_ENABLE_MPS_FALLBACK"}  # (no CPU fallback)
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=600)
    assert done.returncode == 0 and "ok" in done.stdout, done.stderr[-3000:]


def test_the_linear_layer_computes_right_on_the_gpu():
    from clipasso_studio.engine import mps_ops

    way = mps_ops.ensure_right("mps")
    print("F.linear on MPS:", way)  # (in the log: which way this Mac's GPU needs)
    assert way != "wrong", "no way of computing F.linear is right on this GPU"
    g = torch.Generator().manual_seed(4)
    x, w = torch.randn(50, 4, 768, generator=g), torch.randn(3072, 768, generator=g) / 28
    b = torch.randn(3072, generator=g)
    layer = torch.nn.Linear(768, 3072)
    with torch.no_grad():
        layer.weight.copy_(w)
        layer.bias.copy_(b)
        want = layer(x)
        got = layer.to("mps")(x.to("mps")).cpu()
    assert _rel(want, got) < 1e-4


def test_the_own_sampler_on_the_gpu_is_grid_sample():
    from clipasso_studio.engine.mps_ops import grid_sample_bilinear

    g = torch.Generator().manual_seed(1)
    img = torch.rand(2, 4, 33, 41, generator=g)
    grid = torch.rand(2, 19, 23, 2, generator=g) * 2.4 - 1.2
    weights = torch.rand(2, 4, 19, 23, generator=g)
    for pad, corners in (("zeros", False), ("border", True)):
        a_img, a_grid = img.clone().requires_grad_(True), grid.clone().requires_grad_(True)
        a = torch.nn.functional.grid_sample(a_img, a_grid, mode="bilinear", padding_mode=pad, align_corners=corners)
        (a * weights).sum().backward()
        b_img, b_grid = img.to("mps").requires_grad_(True), grid.to("mps").requires_grad_(True)
        b = grid_sample_bilinear(b_img, b_grid, padding_mode=pad, align_corners=corners)
        (b * weights.to("mps")).sum().backward()
        assert torch.allclose(a, b.cpu(), atol=1e-5), pad
        assert torch.allclose(a_img.grad, b_img.grad.cpu(), atol=1e-4), pad
        assert torch.allclose(a_grid.grad, b_grid.grad.cpu(), atol=1e-3, rtol=1e-3), pad


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
            out = "first layer that differs – " + lines[-1] + "\n" + "\n".join(lines)
            if name.startswith("block"):
                i = int(name[5:])
                out += "\n" + _inside_block(cpu_model, gpu_model, images, i)
            return out
    return "no layer differs by more than 1e-3:\n" + "\n".join(lines)


def _rel(a: torch.Tensor, b: torch.Tensor) -> float:
    return float((a - b).abs().max() / (a.abs().max() + 1e-9))


def _inside_block(cpu_model, gpu_model, images: torch.Tensor, i: int) -> str:
    """Block ``i`` step by step: each step on both devices from the same input (the CPU's), the input contiguous
    and as a permuted view – which operation of MPS computes wrongly, and whether only on a view."""
    import torch.nn.functional as F

    seen = {}
    cpu_block, gpu_block = cpu_model.visual.transformer.resblocks[i], gpu_model.visual.transformer.resblocks[i]
    handle = cpu_block.register_forward_pre_hook(lambda _m, args: seen.setdefault("x", args[0].detach().clone()))
    with torch.no_grad():
        cpu_model.encode_image(images)
    handle.remove()
    x = seen["x"].float()
    lines = [f"inside {f'block{i}'} (input {tuple(x.shape)}, contiguous on the CPU: {x.is_contiguous()}):"]

    def views(t):
        yield "contiguous", t.contiguous().to("mps")
        yield "permuted view", t.permute(1, 0, 2).contiguous().to("mps").permute(1, 0, 2)

    def step(name, run_cpu, run_gpu, t):
        with torch.no_grad():
            a = run_cpu(t)
            for layout, v in views(t):
                lines.append(f"  {name} ({layout}): relative difference {_rel(a, run_gpu(v).cpu()):.2e}")
        return a

    c, g = cpu_block, gpu_block
    h1 = step("ln_1", c.ln_1, g.ln_1, x)
    step("in_proj (F.linear)", lambda t: F.linear(t, c.attn.in_proj_weight, c.attn.in_proj_bias),
         lambda t: F.linear(t, g.attn.in_proj_weight, g.attn.in_proj_bias), h1)
    att = step("attention (fused)", lambda t: c.attn(t, t, t)[0], lambda t: g.attn(t, t, t)[0], h1)
    step("attention (explicit)", lambda t: c.attn(t, t, t, need_weights=True)[0],
         lambda t: g.attn(t, t, t, need_weights=True)[0], h1)
    x2 = x + att
    h2 = step("ln_2", c.ln_2, g.ln_2, x2)
    f = step("mlp.c_fc", c.mlp.c_fc, g.mlp.c_fc, h2)
    gl = step("mlp.gelu", c.mlp.gelu, g.mlp.gelu, f)
    step("mlp.c_proj", c.mlp.c_proj, g.mlp.c_proj, gl)
    step("the whole block", c, g, x)
    return "\n".join(lines)


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


def test_clip_reads_text_on_the_gpu_as_on_the_cpu():
    from clipasso_studio.engine import model_store
    from clipasso_studio.engine.clip_ import clip

    if not model_store.is_available(model_store.clip_key("ViT-B/32")):
        pytest.skip("CLIP ViT-B/32 is not downloaded")
    cpu_model, _ = clip.load("ViT-B/32", "cpu")
    gpu_model, _ = clip.load("ViT-B/32", "mps")
    tokens = clip.tokenize(["a sketch of a camel", "a drawing of a house", "lines"])
    with torch.no_grad():
        a = cpu_model.encode_text(tokens).float()
        b = gpu_model.encode_text(tokens.to("mps")).float().cpu()
    cos = torch.nn.functional.cosine_similarity(a, b, dim=-1)
    assert float(cos.min()) > 0.999, f"cosine CPU/MPS per text {cos.tolist()}"


@pytest.mark.parametrize("where", ["cpu", "gpu"])
def test_strokes_on_the_gpu_are_drawn_as_on_the_cpu(monkeypatch, where):
    """Strokes on MPS are drawn on the CPU (renderer.draw_device; CLIPASSO_MPS_RENDER=gpu: on the GPU): the same
    image and the same gradients as strokes on the CPU, the image back on MPS."""
    from clipasso_studio.engine import renderer

    monkeypatch.setenv("CLIPASSO_MPS_RENDER", where)
    g = torch.Generator().manual_seed(5)
    points = [torch.rand(4, 2, generator=g) * 200 + 12 for _ in range(16)]

    def draw(device):
        pts = [p.to(device).requires_grad_(True) for p in points]
        shapes = [renderer.Path(torch.tensor([2]), p, torch.tensor(1.5, device=device)) for p in pts]
        groups = [renderer.ShapeGroup(torch.tensor([i]), None, torch.tensor([0.0, 0.0, 0.0, 1.0], device=device))
                  for i in range(len(shapes))]
        img = renderer.render_on_white(224, 224, shapes, groups)
        (img * torch.linspace(0, 1, 224, device=device)[:, None, None]).sum().backward()
        return img, [p.grad for p in pts]

    a, ga = draw("cpu")
    b, gb = draw("mps")
    assert b.device.type == "mps" and all(t.device.type == "mps" for t in gb)
    assert torch.allclose(a, b.cpu(), atol=1e-5)
    assert all(torch.allclose(x, y.cpu(), atol=1e-3, rtol=1e-4) for x, y in zip(ga, gb))


def test_clip_in_half_precision_on_the_gpu_sees_nearly_what_the_cpu_sees(monkeypatch):
    """CLIPASSO_MPS_HALF=1 (float16 on the Apple GPU, as on an NVIDIA card): the image features stay close to the
    CPU's float32 ones."""
    from clipasso_studio.engine import model_store
    from clipasso_studio.engine.clip_ import clip

    if not model_store.is_available(model_store.clip_key("ViT-B/32")):
        pytest.skip("CLIP ViT-B/32 is not downloaded")
    monkeypatch.setenv("CLIPASSO_MPS_HALF", "1")
    monkeypatch.setattr(clip, "_loaded", {})  # (loaded anew, in half precision)
    cpu_model, _ = clip.load("ViT-B/32", "cpu")
    gpu_model, _ = clip.load("ViT-B/32", "mps")
    assert next(gpu_model.parameters()).dtype == torch.float16
    g = torch.Generator().manual_seed(0)
    images = (torch.rand(3, 3, 224, 224, generator=g) - 0.45) / 0.27
    with torch.no_grad():
        a = cpu_model.encode_image(images).float()
        b = gpu_model.encode_image(images.to("mps")).float().cpu()
    cos = torch.nn.functional.cosine_similarity(a, b, dim=-1)
    print("CLIP float16 on MPS against float32 on the CPU, cosine:", cos.tolist())
    assert float(cos.min()) > 0.995
