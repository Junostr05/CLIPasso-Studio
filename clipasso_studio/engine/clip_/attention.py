"""Multi-head attention that exposes its attention probabilities.

Replaces ``CLIP_/clip/auxilary.py`` of the original CLIPasso repository (a copy of an old
``torch.nn.functional.multi_head_attention_forward`` with extra hooks) with a compact
implementation that works on current PyTorch versions. Parameter names match
``torch.nn.MultiheadAttention`` so the OpenAI CLIP checkpoints load unchanged.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F
from torch import nn


class MultiheadAttention(nn.Module):
    def __init__(self, embed_dim: int, num_heads: int, dropout: float = 0.0, bias: bool = True):
        super().__init__()
        self.embed_dim = embed_dim
        self.num_heads = num_heads
        self.head_dim = embed_dim // num_heads
        assert self.head_dim * num_heads == embed_dim, "embed_dim must be divisible by num_heads"
        self.dropout = dropout
        self.in_proj_weight = nn.Parameter(torch.empty(3 * embed_dim, embed_dim))
        self.in_proj_bias = nn.Parameter(torch.zeros(3 * embed_dim)) if bias else None
        self.out_proj = nn.Linear(embed_dim, embed_dim, bias=bias)
        # attributes referenced by clip.model.convert_weights
        self.q_proj_weight = self.k_proj_weight = self.v_proj_weight = None
        self.bias_k = self.bias_v = None
        nn.init.xavier_uniform_(self.in_proj_weight)

    def forward(self, query, key, value, key_padding_mask=None, need_weights=False, attn_mask=None,
                attention_probs_forward_hook=None, attention_probs_backwards_hook=None):
        # query/key/value: [L, N, E] (sequence first, like torch.nn.MultiheadAttention)
        tgt_len, bsz, embed_dim = query.shape
        q, k, v = F.linear(query, self.in_proj_weight, self.in_proj_bias).chunk(3, dim=-1)
        q = q * (self.head_dim ** -0.5)
        q = q.contiguous().view(tgt_len, bsz * self.num_heads, self.head_dim).transpose(0, 1)
        k = k.contiguous().view(-1, bsz * self.num_heads, self.head_dim).transpose(0, 1)
        v = v.contiguous().view(-1, bsz * self.num_heads, self.head_dim).transpose(0, 1)
        src_len = k.shape[1]

        weights = torch.bmm(q, k.transpose(1, 2))
        if attn_mask is not None:
            if attn_mask.dtype == torch.bool:
                weights = weights.masked_fill(attn_mask, float("-inf"))
            else:
                weights = weights + attn_mask
        if key_padding_mask is not None:
            weights = weights.view(bsz, self.num_heads, tgt_len, src_len)
            weights = weights.masked_fill(key_padding_mask[:, None, None, :], float("-inf"))
            weights = weights.view(bsz * self.num_heads, tgt_len, src_len)
        weights = F.softmax(weights, dim=-1)
        weights = F.dropout(weights, p=self.dropout, training=self.training)

        if attention_probs_forward_hook is not None:
            attention_probs_forward_hook(weights)
        if attention_probs_backwards_hook is not None and weights.requires_grad:
            weights.register_hook(attention_probs_backwards_hook)

        out = torch.bmm(weights, v)
        out = out.transpose(0, 1).contiguous().view(tgt_len, bsz, embed_dim)
        out = self.out_proj(out)
        if need_weights:
            return out, weights.view(bsz, self.num_heads, tgt_len, src_len).mean(dim=1)
        return out, None
