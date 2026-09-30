"""LaMa ("big-lama") inpainting network, used to fill in the background behind the foreground object.

Port of ``FFCResNetGenerator`` from ``saicinpainting/training/modules/ffc.py`` of LaMa
(Suvorov et al., "Resolution-robust Large Mask Inpainting with Fourier Convolutions", WACV 2022,
https://github.com/advimman/lama, Apache-2.0), reduced to the configuration of the big-lama
checkpoint: 3 downsampling steps, 18 Fourier-convolution residual blocks (75 % global channels,
no local Fourier unit), sigmoid output. Module names match the checkpoint, so the weights load
strictly. SceneSketch (``preprocess_images.py``) runs this model on the scene with the dilated
U2Net mask of the foreground object.
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


class FourierUnit(nn.Module):
    def __init__(self, in_channels: int, out_channels: int):
        super().__init__()
        self.conv_layer = nn.Conv2d(in_channels * 2, out_channels * 2, kernel_size=1, bias=False)
        self.bn = nn.BatchNorm2d(out_channels * 2)
        self.relu = nn.ReLU(inplace=True)

    def forward(self, x):
        batch = x.shape[0]
        ffted = torch.fft.rfftn(x, dim=(-2, -1), norm="ortho")
        ffted = torch.stack((ffted.real, ffted.imag), dim=-1)
        ffted = ffted.permute(0, 1, 4, 2, 3).contiguous()  # (batch, c, 2, h, w/2+1)
        ffted = ffted.view((batch, -1) + ffted.size()[3:])
        ffted = self.relu(self.bn(self.conv_layer(ffted)))
        ffted = ffted.view((batch, -1, 2) + ffted.size()[2:]).permute(0, 1, 3, 4, 2).contiguous()
        ffted = torch.complex(ffted[..., 0], ffted[..., 1])
        return torch.fft.irfftn(ffted, s=x.shape[-2:], dim=(-2, -1), norm="ortho")


class SpectralTransform(nn.Module):
    def __init__(self, in_channels: int, out_channels: int):
        super().__init__()
        self.conv1 = nn.Sequential(nn.Conv2d(in_channels, out_channels // 2, kernel_size=1, bias=False),
                                   nn.BatchNorm2d(out_channels // 2), nn.ReLU(inplace=True))
        self.fu = FourierUnit(out_channels // 2, out_channels // 2)
        self.conv2 = nn.Conv2d(out_channels // 2, out_channels, kernel_size=1, bias=False)

    def forward(self, x):
        x = self.conv1(x)
        return self.conv2(x + self.fu(x))


class FFC(nn.Module):
    """Fast Fourier convolution: local (spatial) and global (spectral) channel groups."""

    def __init__(self, in_channels, out_channels, kernel_size, ratio_gin, ratio_gout, stride=1, padding=0):
        super().__init__()
        in_cg = int(in_channels * ratio_gin)
        in_cl = in_channels - in_cg
        out_cg = int(out_channels * ratio_gout)
        out_cl = out_channels - out_cg
        self.ratio_gout = ratio_gout
        self.global_in_num = in_cg

        def conv(cin, cout):
            if cin == 0 or cout == 0:
                return nn.Identity()
            return nn.Conv2d(cin, cout, kernel_size, stride, padding, bias=False, padding_mode="reflect")

        self.convl2l = conv(in_cl, out_cl)
        self.convl2g = conv(in_cl, out_cg)
        self.convg2l = conv(in_cg, out_cl)
        self.convg2g = nn.Identity() if in_cg == 0 or out_cg == 0 else SpectralTransform(in_cg, out_cg)

    def forward(self, x):
        x_l, x_g = x if type(x) is tuple else (x, 0)
        out_xl, out_xg = 0, 0
        if self.ratio_gout != 1:
            out_xl = self.convl2l(x_l) + self.convg2l(x_g)
        if self.ratio_gout != 0:
            out_xg = self.convl2g(x_l) + self.convg2g(x_g)
        return out_xl, out_xg


class FFC_BN_ACT(nn.Module):  # noqa: N801 - name of the original module
    def __init__(self, in_channels, out_channels, kernel_size, ratio_gin, ratio_gout, stride=1, padding=0):
        super().__init__()
        self.ffc = FFC(in_channels, out_channels, kernel_size, ratio_gin, ratio_gout, stride, padding)
        global_channels = int(out_channels * ratio_gout)
        self.bn_l = nn.Identity() if ratio_gout == 1 else nn.BatchNorm2d(out_channels - global_channels)
        self.bn_g = nn.Identity() if ratio_gout == 0 else nn.BatchNorm2d(global_channels)
        self.act_l = nn.Identity() if ratio_gout == 1 else nn.ReLU(inplace=True)
        self.act_g = nn.Identity() if ratio_gout == 0 else nn.ReLU(inplace=True)

    def forward(self, x):
        x_l, x_g = self.ffc(x)
        x_l = self.act_l(self.bn_l(x_l))
        x_g = self.act_g(self.bn_g(x_g))
        return x_l, x_g


class FFCResnetBlock(nn.Module):
    def __init__(self, dim: int, ratio: float):
        super().__init__()
        self.conv1 = FFC_BN_ACT(dim, dim, 3, ratio, ratio, padding=1)
        self.conv2 = FFC_BN_ACT(dim, dim, 3, ratio, ratio, padding=1)

    def forward(self, x):
        x_l, x_g = x if type(x) is tuple else (x, 0)
        id_l, id_g = x_l, x_g
        x_l, x_g = self.conv1((x_l, x_g))
        x_l, x_g = self.conv2((x_l, x_g))
        return id_l + x_l, id_g + x_g


class ConcatTupleLayer(nn.Module):
    def forward(self, x):
        x_l, x_g = x
        if not torch.is_tensor(x_g):
            return x_l
        return torch.cat(x, dim=1)


class LamaGenerator(nn.Module):
    """``FFCResNetGenerator(input_nc=4, output_nc=3, ngf=64, n_downsampling=3, n_blocks=18,
    resnet ratio 0.75, add_out_act='sigmoid')`` – the big-lama generator."""

    def __init__(self, ngf: int = 64, n_downsampling: int = 3, n_blocks: int = 18, ratio: float = 0.75):
        super().__init__()
        model = [nn.ReflectionPad2d(3), FFC_BN_ACT(4, ngf, 7, 0, 0)]
        for i in range(n_downsampling):
            mult = 2 ** i
            ratio_gout = ratio if i == n_downsampling - 1 else 0
            model.append(FFC_BN_ACT(ngf * mult, ngf * mult * 2, 3, 0, ratio_gout, stride=2, padding=1))
        dim = ngf * 2 ** n_downsampling
        model += [FFCResnetBlock(dim, ratio) for _ in range(n_blocks)]
        model.append(ConcatTupleLayer())
        for i in range(n_downsampling):
            mult = 2 ** (n_downsampling - i)
            model += [nn.ConvTranspose2d(ngf * mult, ngf * mult // 2, kernel_size=3, stride=2, padding=1,
                                         output_padding=1),
                      nn.BatchNorm2d(ngf * mult // 2), nn.ReLU(True)]
        model += [nn.ReflectionPad2d(3), nn.Conv2d(ngf, 3, kernel_size=7, padding=0), nn.Sigmoid()]
        self.model = nn.Sequential(*model)

    def forward(self, x):
        return self.model(x)


def load_lama(device) -> LamaGenerator:
    from ... import model_store

    net = LamaGenerator()
    state = {k: v.float() if v.is_floating_point() else v for k, v in model_store.load_state("lama").items()}
    net.load_state_dict(state, strict=True)
    net.requires_grad_(False)
    return net.to(device).eval()


def _pad_symmetric(x: torch.Tensor, ph: int, pw: int) -> torch.Tensor:
    """``np.pad(..., mode='symmetric')`` at the bottom / right (as LaMa's ``pad_img_to_modulo``)."""
    if ph:
        x = torch.cat([x, x[..., -ph:, :].flip(-2)], dim=-2)
    if pw:
        x = torch.cat([x, x[..., :, -pw:].flip(-1)], dim=-1)
    return x


@torch.no_grad()
def inpaint(net: LamaGenerator, image: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    """``image`` [1,3,H,W] in [0,1], ``mask`` [1,1,H,W] (1 = fill in) -> inpainted [1,3,H,W].

    Like LaMa's prediction script: the input is padded to a multiple of 8, the network sees the
    masked image plus the mask, and only the masked pixels are replaced.
    """
    h, w = image.shape[-2:]
    ph, pw = (8 - h % 8) % 8, (8 - w % 8) % 8
    mask = (mask > 0).to(image.dtype)
    img_p = _pad_symmetric(image, ph, pw)
    mask_p = _pad_symmetric(mask, ph, pw)
    masked = img_p * (1 - mask_p)
    pred = net(torch.cat([masked, mask_p], dim=1))
    out = mask_p * pred + (1 - mask_p) * img_p
    return out[..., :h, :w].clamp(0, 1)
