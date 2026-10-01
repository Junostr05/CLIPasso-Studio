"""BiRefNet – high-resolution dichotomous segmentation, used for the object mask.

Port of ``birefnet.py`` of the Hugging Face repositories ``ZhengPeng7/BiRefNet`` and
``ZhengPeng7/BiRefNet_lite`` (Peng Zheng et al., "Bilateral Reference for High-Resolution Dichotomous
Image Segmentation", CAAI AIR 2024, https://github.com/ZhengPeng7/BiRefNet, MIT licence; the Swin
Transformer backbone is Microsoft's, MIT licence), reduced to the configuration of these checkpoints:
Swin-L (general model) or Swin-T (lite) backbone run at full and half resolution, three multi-scale
context features, deformable ASPP decoder blocks, image patches fed into every decoder stage and
gradient attention. The training-only heads are kept so the checkpoints load strictly; timm, kornia,
einops and transformers are not needed. Input: 1024 x 1024, ImageNet normalisation; output: the
foreground probability (sigmoid of the last prediction).
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision.ops import deform_conv2d

SIZE = 1024
MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)

BACKBONES = {  # embed_dim, depths, num_heads, window_size
    "swin_v1_l": (192, (2, 2, 18, 2), (6, 12, 24, 48), 12),
    "swin_v1_t": (96, (2, 2, 6, 2), (3, 6, 12, 24), 7),
}


# ------------------------------------------------------------------------- Swin Transformer
class Mlp(nn.Module):
    def __init__(self, dim: int, hidden: int):
        super().__init__()
        self.fc1 = nn.Linear(dim, hidden)
        self.act = nn.GELU()
        self.fc2 = nn.Linear(hidden, dim)

    def forward(self, x):
        return self.fc2(self.act(self.fc1(x)))


def window_partition(x, ws: int):
    b, h, w, c = x.shape
    x = x.view(b, h // ws, ws, w // ws, ws, c)
    return x.permute(0, 1, 3, 2, 4, 5).contiguous().view(-1, ws, ws, c)


def window_reverse(windows, ws: int, h: int, w: int):
    b = int(windows.shape[0] / (h * w / ws / ws))
    x = windows.view(b, h // ws, w // ws, ws, ws, -1)
    return x.permute(0, 1, 3, 2, 4, 5).contiguous().view(b, h, w, -1)


class WindowAttention(nn.Module):
    """Window multi-head self attention with relative position bias."""

    def __init__(self, dim: int, ws: int, num_heads: int):
        super().__init__()
        self.ws = ws
        self.num_heads = num_heads
        self.scale = (dim // num_heads) ** -0.5
        self.relative_position_bias_table = nn.Parameter(torch.zeros((2 * ws - 1) ** 2, num_heads))
        coords = torch.stack(torch.meshgrid([torch.arange(ws), torch.arange(ws)], indexing="ij")).flatten(1)
        rel = (coords[:, :, None] - coords[:, None, :]).permute(1, 2, 0).contiguous()
        rel[:, :, 0] += ws - 1
        rel[:, :, 1] += ws - 1
        rel[:, :, 0] *= 2 * ws - 1
        self.register_buffer("relative_position_index", rel.sum(-1))
        self.qkv = nn.Linear(dim, dim * 3)
        self.proj = nn.Linear(dim, dim)

    def forward(self, x, mask=None):
        b_, n, c = x.shape
        qkv = self.qkv(x).reshape(b_, n, 3, self.num_heads, c // self.num_heads).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0] * self.scale, qkv[1], qkv[2]
        attn = q @ k.transpose(-2, -1)
        bias = self.relative_position_bias_table[self.relative_position_index.view(-1)].view(n, n, -1)
        attn = attn + bias.permute(2, 0, 1).contiguous().unsqueeze(0)
        if mask is not None:
            nw = mask.shape[0]
            attn = attn.view(b_ // nw, nw, self.num_heads, n, n) + mask.unsqueeze(1).unsqueeze(0)
            attn = attn.view(-1, self.num_heads, n, n)
        attn = attn.softmax(dim=-1)
        return self.proj((attn @ v).transpose(1, 2).reshape(b_, n, c))


class SwinTransformerBlock(nn.Module):
    def __init__(self, dim: int, num_heads: int, ws: int, shift: int):
        super().__init__()
        self.ws, self.shift = ws, shift
        self.norm1 = nn.LayerNorm(dim)
        self.attn = WindowAttention(dim, ws, num_heads)
        self.norm2 = nn.LayerNorm(dim)
        self.mlp = Mlp(dim, dim * 4)

    def forward(self, x, h: int, w: int, attn_mask):
        b, _, c = x.shape
        ws = self.ws
        shortcut = x
        x = self.norm1(x).view(b, h, w, c)
        pad_r, pad_b = (ws - w % ws) % ws, (ws - h % ws) % ws
        x = F.pad(x, (0, 0, 0, pad_r, 0, pad_b))
        hp, wp = x.shape[1], x.shape[2]
        if self.shift:
            x = torch.roll(x, shifts=(-self.shift, -self.shift), dims=(1, 2))
        windows = window_partition(x, ws).view(-1, ws * ws, c)
        windows = self.attn(windows, mask=attn_mask if self.shift else None)
        x = window_reverse(windows.view(-1, ws, ws, c), ws, hp, wp)
        if self.shift:
            x = torch.roll(x, shifts=(self.shift, self.shift), dims=(1, 2))
        if pad_r or pad_b:
            x = x[:, :h, :w, :].contiguous()
        x = shortcut + x.view(b, h * w, c)
        return x + self.mlp(self.norm2(x))


class PatchMerging(nn.Module):
    def __init__(self, dim: int):
        super().__init__()
        self.reduction = nn.Linear(4 * dim, 2 * dim, bias=False)
        self.norm = nn.LayerNorm(4 * dim)

    def forward(self, x, h: int, w: int):
        b, _, c = x.shape
        x = x.view(b, h, w, c)
        if h % 2 or w % 2:
            x = F.pad(x, (0, 0, 0, w % 2, 0, h % 2))
        x = torch.cat([x[:, 0::2, 0::2], x[:, 1::2, 0::2], x[:, 0::2, 1::2], x[:, 1::2, 1::2]], -1)
        return self.reduction(self.norm(x.view(b, -1, 4 * c)))


class BasicLayer(nn.Module):
    def __init__(self, dim: int, depth: int, num_heads: int, ws: int, downsample: bool):
        super().__init__()
        self.ws, self.shift = ws, ws // 2
        self.blocks = nn.ModuleList([SwinTransformerBlock(dim, num_heads, ws, 0 if i % 2 == 0 else ws // 2)
                                     for i in range(depth)])
        self.downsample = PatchMerging(dim) if downsample else None

    def _attn_mask(self, h: int, w: int, x):
        ws, s = self.ws, self.shift
        hp, wp = -(-h // ws) * ws, -(-w // ws) * ws
        img = torch.zeros((1, hp, wp, 1), device=x.device)
        cnt = 0
        for hs in (slice(0, -ws), slice(-ws, -s), slice(-s, None)):
            for wsl in (slice(0, -ws), slice(-ws, -s), slice(-s, None)):
                img[:, hs, wsl, :] = cnt
                cnt += 1
        mw = window_partition(img, ws).view(-1, ws * ws)
        mask = mw.unsqueeze(1) - mw.unsqueeze(2)
        return mask.masked_fill(mask != 0, -100.0).masked_fill(mask == 0, 0.0).to(x.dtype)

    def forward(self, x, h: int, w: int):
        attn_mask = self._attn_mask(h, w, x)
        for blk in self.blocks:
            x = blk(x, h, w, attn_mask)
        if self.downsample is None:
            return x, x, h, w
        return x, self.downsample(x, h, w), (h + 1) // 2, (w + 1) // 2


class PatchEmbed(nn.Module):
    def __init__(self, embed_dim: int, patch: int = 4):
        super().__init__()
        self.patch = patch
        self.proj = nn.Conv2d(3, embed_dim, kernel_size=patch, stride=patch)
        self.norm = nn.LayerNorm(embed_dim)

    def forward(self, x):
        _, _, h, w = x.shape
        p = self.patch
        if w % p:
            x = F.pad(x, (0, p - w % p))
        if h % p:
            x = F.pad(x, (0, 0, 0, p - h % p))
        x = self.proj(x)
        wh, ww = x.shape[2], x.shape[3]
        x = self.norm(x.flatten(2).transpose(1, 2))
        return x.transpose(1, 2).view(-1, x.shape[-1], wh, ww)


class SwinTransformer(nn.Module):
    def __init__(self, embed_dim: int, depths, num_heads, ws: int):
        super().__init__()
        self.patch_embed = PatchEmbed(embed_dim)
        self.num_features = [embed_dim * 2 ** i for i in range(len(depths))]
        self.layers = nn.ModuleList([BasicLayer(self.num_features[i], depths[i], num_heads[i], ws, i < len(depths) - 1)
                                     for i in range(len(depths))])
        for i, nf in enumerate(self.num_features):
            self.add_module(f"norm{i}", nn.LayerNorm(nf))

    def forward(self, x):
        x = self.patch_embed(x)
        h, w = x.shape[2], x.shape[3]
        x = x.flatten(2).transpose(1, 2)
        outs = []
        for i, layer in enumerate(self.layers):
            out, x, nh, nw = layer(x, h, w)
            out = getattr(self, f"norm{i}")(out)
            outs.append(out.view(-1, h, w, self.num_features[i]).permute(0, 3, 1, 2).contiguous())
            h, w = nh, nw
        return tuple(outs)


# ----------------------------------------------------------------------------- decoder parts
def deform_conv2d_cpu(x, offset, weight, mask, padding: int):
    """Modulated deformable convolution (stride 1, no bias) like ``torchvision.ops.deform_conv2d``:
    one bilinear ``grid_sample`` and one matrix product per kernel position. On the CPU this is
    about 2.5x faster than torchvision's im2col kernel and needs no column buffer."""
    b, c, h, w = x.shape
    o, _, kh, kw = weight.shape
    ho, wo = offset.shape[2], offset.shape[3]
    ys = torch.arange(ho, device=x.device, dtype=x.dtype).view(1, ho, 1) - padding
    xs = torch.arange(wo, device=x.device, dtype=x.dtype).view(1, 1, wo) - padding
    sy, sx = 2.0 / max(h - 1, 1), 2.0 / max(w - 1, 1)  # pixel index -> grid_sample's [-1, 1] (align_corners)
    wmat = weight.reshape(o, c, kh * kw)
    out = x.new_zeros(b, o, ho * wo)
    for j in range(kh * kw):
        ky, kx = divmod(j, kw)
        grid = torch.stack(((xs + kx + offset[:, 2 * j + 1]) * sx - 1, (ys + ky + offset[:, 2 * j]) * sy - 1), dim=-1)
        sampled = F.grid_sample(x, grid, mode="bilinear", padding_mode="zeros", align_corners=True)
        out.baddbmm_(wmat[:, :, j].expand(b, o, c), (sampled * mask[:, j:j + 1]).reshape(b, c, ho * wo))
    return out.view(b, o, ho, wo)


class DeformableConv2d(nn.Module):
    def __init__(self, cin: int, cout: int, k: int, padding: int):
        super().__init__()
        self.padding = padding
        self.offset_conv = nn.Conv2d(cin, 2 * k * k, k, 1, padding)
        self.modulator_conv = nn.Conv2d(cin, k * k, k, 1, padding)
        self.regular_conv = nn.Conv2d(cin, cout, k, 1, padding, bias=False)

    def forward(self, x):
        offset = self.offset_conv(x)
        modulator = 2.0 * torch.sigmoid(self.modulator_conv(x))
        if x.device.type == "cpu":
            return deform_conv2d_cpu(x, offset, self.regular_conv.weight, modulator, self.padding)
        return deform_conv2d(x, offset, self.regular_conv.weight, self.regular_conv.bias,
                             padding=(self.padding, self.padding), mask=modulator)


class _ASPPModuleDeformable(nn.Module):
    def __init__(self, cin: int, planes: int, k: int, padding: int):
        super().__init__()
        self.atrous_conv = DeformableConv2d(cin, planes, k, padding)
        self.bn = nn.BatchNorm2d(planes)
        self.relu = nn.ReLU(inplace=True)

    def forward(self, x):
        return self.relu(self.bn(self.atrous_conv(x)))


class ASPPDeformable(nn.Module):
    def __init__(self, cin: int, block_sizes=(1, 3, 7)):
        super().__init__()
        planes = 256
        self.aspp1 = _ASPPModuleDeformable(cin, planes, 1, 0)
        self.aspp_deforms = nn.ModuleList([_ASPPModuleDeformable(cin, planes, k, k // 2) for k in block_sizes])
        self.global_avg_pool = nn.Sequential(nn.AdaptiveAvgPool2d((1, 1)), nn.Conv2d(cin, planes, 1, bias=False),
                                             nn.BatchNorm2d(planes), nn.ReLU(inplace=True))
        self.conv1 = nn.Conv2d(planes * (2 + len(block_sizes)), cin, 1, bias=False)
        self.bn1 = nn.BatchNorm2d(cin)
        self.relu = nn.ReLU(inplace=True)

    def forward(self, x):
        x1 = self.aspp1(x)
        x5 = F.interpolate(self.global_avg_pool(x), size=x1.shape[2:], mode="bilinear", align_corners=True)
        x = torch.cat((x1, *[m(x) for m in self.aspp_deforms], x5), dim=1)
        return self.relu(self.bn1(self.conv1(x)))


class BasicDecBlk(nn.Module):
    def __init__(self, cin: int, cout: int, inter: int = 64):
        super().__init__()
        self.conv_in = nn.Conv2d(cin, inter, 3, 1, 1)
        self.bn_in = nn.BatchNorm2d(inter)
        self.relu_in = nn.ReLU(inplace=True)
        self.dec_att = ASPPDeformable(inter)
        self.conv_out = nn.Conv2d(inter, cout, 3, 1, 1)
        self.bn_out = nn.BatchNorm2d(cout)

    def forward(self, x):
        x = self.relu_in(self.bn_in(self.conv_in(x)))
        return self.bn_out(self.conv_out(self.dec_att(x)))


class BasicLatBlk(nn.Module):
    def __init__(self, cin: int, cout: int):
        super().__init__()
        self.conv = nn.Conv2d(cin, cout, 1, 1, 0)

    def forward(self, x):
        return self.conv(x)


class SimpleConvs(nn.Module):
    def __init__(self, cin: int, cout: int, inter: int = 64):
        super().__init__()
        self.conv1 = nn.Conv2d(cin, inter, 3, 1, 1)
        self.conv_out = nn.Conv2d(inter, cout, 3, 1, 1)

    def forward(self, x):
        return self.conv_out(self.conv1(x))


def image2patches(x, ref):
    """``rearrange(x, 'b c (hg h) (wg w) -> b (c hg wg) h w')`` with the grid given by ``ref``'s size."""
    b, c, height, width = x.shape
    h, w = ref.shape[-2], ref.shape[-1]
    hg, wg = height // h, width // w
    x = x.view(b, c, hg, h, wg, w).permute(0, 1, 2, 4, 3, 5)
    return x.reshape(b, c * hg * wg, h, w)


def _gdt(cin: int):
    return nn.Sequential(nn.Conv2d(cin, 16, 3, 1, 1), nn.BatchNorm2d(16), nn.ReLU(inplace=True))


class Decoder(nn.Module):
    def __init__(self, ch):
        super().__init__()
        self.ipt_blk5 = SimpleConvs(2 ** 10 * 3, ch[0] // 8)
        self.ipt_blk4 = SimpleConvs(2 ** 8 * 3, ch[0] // 8)
        self.ipt_blk3 = SimpleConvs(2 ** 6 * 3, ch[1] // 8)
        self.ipt_blk2 = SimpleConvs(2 ** 4 * 3, ch[2] // 8)
        self.ipt_blk1 = SimpleConvs(2 ** 0 * 3, ch[3] // 8)
        self.decoder_block4 = BasicDecBlk(ch[0] + ch[0] // 8, ch[1])
        self.decoder_block3 = BasicDecBlk(ch[1] + ch[0] // 8, ch[2])
        self.decoder_block2 = BasicDecBlk(ch[2] + ch[1] // 8, ch[3])
        self.decoder_block1 = BasicDecBlk(ch[3] + ch[2] // 8, ch[3] // 2)
        self.conv_out1 = nn.Sequential(nn.Conv2d(ch[3] // 2 + ch[3] // 8, 1, 1, 1, 0))
        self.lateral_block4 = BasicLatBlk(ch[1], ch[1])
        self.lateral_block3 = BasicLatBlk(ch[2], ch[2])
        self.lateral_block2 = BasicLatBlk(ch[3], ch[3])
        # multi-scale supervision and gradient heads: only the attention is used for inference
        for n, c in ((4, ch[1]), (3, ch[2]), (2, ch[3])):
            self.add_module(f"conv_ms_spvn_{n}", nn.Conv2d(c, 1, 1, 1, 0))
            self.add_module(f"gdt_convs_{n}", _gdt(c))
            self.add_module(f"gdt_convs_pred_{n}", nn.Sequential(nn.Conv2d(16, 1, 1, 1, 0)))
            self.add_module(f"gdt_convs_attn_{n}", nn.Sequential(nn.Conv2d(16, 1, 1, 1, 0)))

    def _with_patches(self, feat, x, blk):
        patches = image2patches(x, feat)
        return torch.cat((feat, blk(F.interpolate(patches, size=feat.shape[2:], mode="bilinear",
                                                  align_corners=True))), 1)

    def _gate(self, p, n: int):
        attn = getattr(self, f"gdt_convs_attn_{n}")(getattr(self, f"gdt_convs_{n}")(p)).sigmoid()
        return p * attn

    def forward(self, x, x1, x2, x3, x4):
        def up(t, ref):
            return F.interpolate(t, size=ref.shape[2:], mode="bilinear", align_corners=True)

        p4 = self._gate(self.decoder_block4(self._with_patches(x4, x, self.ipt_blk5)), 4)
        p3 = up(p4, x3) + self.lateral_block4(x3)
        p3 = self._gate(self.decoder_block3(self._with_patches(p3, x, self.ipt_blk4)), 3)
        p2 = up(p3, x2) + self.lateral_block3(x2)
        p2 = self._gate(self.decoder_block2(self._with_patches(p2, x, self.ipt_blk3)), 2)
        p1 = up(p2, x1) + self.lateral_block2(x1)
        p1 = up(self.decoder_block1(self._with_patches(p1, x, self.ipt_blk2)), x)
        return self.conv_out1(self._with_patches(p1, x, self.ipt_blk1))


class BiRefNet(nn.Module):
    def __init__(self, backbone: str = "swin_v1_l"):
        super().__init__()
        embed, depths, heads, ws = BACKBONES[backbone]
        self.bb = SwinTransformer(embed, depths, heads, ws)
        ch = [embed * 2 ** i * 2 for i in (3, 2, 1, 0)]  # lateral channels, doubled by the half-size input
        self.squeeze_module = nn.Sequential(BasicDecBlk(ch[0] + sum(ch[1:]), ch[0]))
        self.decoder = Decoder(ch)

    def forward_enc(self, x):
        def up(t, ref):
            return F.interpolate(t, size=ref.shape[2:], mode="bilinear", align_corners=True)

        feats = self.bb(x)
        h, w = x.shape[2], x.shape[3]
        half = self.bb(F.interpolate(x, size=(h // 2, w // 2), mode="bilinear", align_corners=True))
        x1, x2, x3, x4 = (torch.cat([f, up(g, f)], dim=1) for f, g in zip(feats, half))
        x4 = torch.cat((up(x1, x4), up(x2, x4), up(x3, x4), x4), dim=1)
        return x1, x2, x3, x4

    def forward(self, x):
        """Logits of the foreground at the input size ([B, 1, H, W]); H and W: multiples of 32."""
        x1, x2, x3, x4 = self.forward_enc(x)
        return self.decoder(x, x1, x2, x3, self.squeeze_module(x4))


def build(variant: str = "general") -> BiRefNet:
    return BiRefNet("swin_v1_t" if variant == "lite" else "swin_v1_l")
