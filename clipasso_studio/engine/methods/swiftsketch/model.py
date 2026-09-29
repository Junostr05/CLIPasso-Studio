"""SwiftSketch network – an independent implementation of the architecture described in
"SwiftSketch: A Diffusion Model for Image-to-Vector Sketch Generation" (Arar et al., SIGGRAPH 2025).

A transformer decoder denoises the control points of all strokes jointly
([batch, strokes, 4 control points, xy]) while cross-attending to intermediate CLIP ResNet-101
features of the input image. Module and parameter names follow the official checkpoints
(https://github.com/swiftsketch/SwiftSketch) so they load unchanged.
"""

from __future__ import annotations

import math

import torch
from torch import nn

# channels and spatial size of the conditioning features, per feature type
FEATURE_DIMS = {
    "CLIPMiddle_layer3": (512, 28),
    "CLIPMiddle_layer4": (1024, 14),
    "CLIPMiddle_layer5": (2048, 7),
}


def sinusoidal_table(max_len: int, dim: int) -> torch.Tensor:
    """[max_len, 1, dim] sine/cosine position table."""
    position = torch.arange(max_len, dtype=torch.float32).unsqueeze(1)
    div = torch.exp(torch.arange(0, dim, 2, dtype=torch.float32) * (-math.log(10000.0) / dim))
    table = torch.zeros(max_len, dim)
    table[:, 0::2] = torch.sin(position * div)
    table[:, 1::2] = torch.cos(position * div)
    return table.unsqueeze(1)


class PositionalEncoding(nn.Module):
    def __init__(self, dim: int, dropout: float = 0.1, max_len: int = 5000):
        super().__init__()
        self.dropout = nn.Dropout(dropout)
        self.register_buffer("pe", sinusoidal_table(max_len, dim))

    def forward(self, x):  # x: [seq, batch, dim]
        return self.dropout(x + self.pe[: x.shape[0]])


class TimestepEmbedder(nn.Module):
    def __init__(self, dim: int, pos: PositionalEncoding):
        super().__init__()
        self.sequence_pos_encoder = pos
        self.time_embed = nn.Sequential(nn.Linear(dim, dim), nn.SiLU(), nn.Linear(dim, dim))

    def forward(self, t):  # t: [batch] long -> [1, batch, dim]
        return self.time_embed(self.sequence_pos_encoder.pe[t]).permute(1, 0, 2)


class InputProcess(nn.Module):
    def __init__(self, in_dim: int, dim: int):
        super().__init__()
        self.pointsEmbedding = nn.Linear(in_dim, dim)

    def forward(self, x):  # [batch, strokes, cp, 2] -> [strokes, batch, dim]
        b, n, cp, f = x.shape
        return self.pointsEmbedding(x.permute(1, 0, 2, 3).reshape(n, b, cp * f))


class OutputProcess(nn.Module):
    def __init__(self, out_dim: int, dim: int, ncpoints: int, nfeats: int, normalize: bool, scaling: float):
        super().__init__()
        self.pointsFinal = nn.Linear(dim, out_dim)
        self.ncpoints, self.nfeats = ncpoints, nfeats
        self.normalize, self.scaling = normalize, scaling

    def forward(self, h):  # [strokes, batch, dim] -> [batch, strokes, cp, 2]
        n, b, _ = h.shape
        out = self.pointsFinal(h)
        if self.normalize:
            out = torch.tanh(out) * self.scaling
        return out.reshape(n, b, self.ncpoints, self.nfeats).permute(1, 0, 2, 3)


class ImageCrossAttentionEmbed(nn.Module):
    """CLIP feature map -> sequence of image tokens used as decoder memory."""

    def __init__(self, in_channels: int, dim: int):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(in_channels, 512, 3, padding=1), nn.ReLU(),
            nn.Conv2d(512, 512, 3, padding=1), nn.ReLU(),
            nn.Conv2d(512, 512, 3, padding=1), nn.ReLU(),
        )
        self.fc = nn.Sequential(nn.Linear(512, 512), nn.ReLU(), nn.Linear(512, 512), nn.ReLU(), nn.Linear(512, dim))

    def forward(self, feats):  # [batch, C, S, S] -> [S*S, batch, dim]
        x = self.conv(feats)
        b, c, h, w = x.shape
        return self.fc(x.permute(2, 3, 0, 1).reshape(h * w, b, c))


class SwiftSketchNet(nn.Module):
    ncpoints = 4
    nfeats = 2

    def __init__(self, latent_dim=512, ff_size=1024, num_layers=8, num_heads=4, dropout=0.1, activation="gelu",
                 image_features_type="CLIPMiddle_layer4", normalize_model_output=True, scaling_factor=2.0,
                 cond_mask_prob=0.0):
        super().__init__()
        feat_ch, _ = FEATURE_DIMS[image_features_type]
        in_dim = self.ncpoints * self.nfeats
        self.cond_mask_prob = cond_mask_prob
        self.input_process = InputProcess(in_dim, latent_dim)
        self.sequence_pos_encoder = PositionalEncoding(latent_dim, dropout)
        layer = nn.TransformerDecoderLayer(d_model=latent_dim, nhead=num_heads, dim_feedforward=ff_size,
                                           dropout=dropout, activation=activation)
        self.seqTransDecoder = nn.TransformerDecoder(layer, num_layers=num_layers)
        self.embed_timestep = TimestepEmbedder(latent_dim, self.sequence_pos_encoder)
        self.embed_image_ca = ImageCrossAttentionEmbed(feat_ch, latent_dim)
        self.output_process = OutputProcess(in_dim, latent_dim, self.ncpoints, self.nfeats, normalize_model_output,
                                            scaling_factor)

    @classmethod
    def from_args(cls, args: dict) -> "SwiftSketchNet":
        return cls(latent_dim=args.get("latent_dim", 512), num_layers=args.get("layers", 8),
                   num_heads=args.get("heads", 4), image_features_type=args.get("image_features_type",
                                                                                 "CLIPMiddle_layer4"),
                   normalize_model_output=bool(args.get("normalize_model_output", 1)),
                   scaling_factor=float(args.get("scaling_factor", 2.0)),
                   cond_mask_prob=float(args.get("cond_mask_prob", 0.0)))

    def forward(self, x, timesteps, image_features, uncond: bool = False):
        h = self.input_process(x)
        emb = self.embed_timestep(timesteps)
        feats = torch.zeros_like(image_features) if uncond else image_features
        memory = emb + self.embed_image_ca(feats)
        h = self.sequence_pos_encoder(h)
        h = self.seqTransDecoder(tgt=h, memory=memory)
        return self.output_process(h)

    def guided(self, x, timesteps, image_features, scale: float):
        """Classifier-free guidance: uncond + scale * (cond - uncond)."""
        if scale == 1.0 or self.cond_mask_prob <= 0:
            return self(x, timesteps, image_features)
        out = self(x, timesteps, image_features)
        out_uncond = self(x, timesteps, image_features, uncond=True)
        return out_uncond + scale * (out - out_uncond)
