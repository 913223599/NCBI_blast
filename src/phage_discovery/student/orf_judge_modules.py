# -*- coding: utf-8 -*-
"""
OrfFunctionalJudge 的 PyTorch 神经网络子模块定义。

将网络层定义独立至本文件以按需延迟加载 `torch`，确保主模块在无 PyTorch 的离线/CI
环境中可安全导入，同时将 `build_orf_functional_judge` 工厂函数维持低复杂度。
"""
from __future__ import annotations

from typing import Sequence

import numpy as np
import torch
from torch import nn


class MaskedSeqConvBlock1d(nn.Module):
    """带有效长度掩码的 1D 空洞残差卷积块。"""

    def __init__(self, ch: int, kernel_size: int, dilation: int):
        super().__init__()
        pad = ((kernel_size - 1) * dilation) // 2
        self.conv1 = nn.Conv1d(ch, ch, kernel_size=kernel_size, padding=pad, dilation=dilation)
        self.norm1 = nn.GroupNorm(8, ch)
        self.conv2 = nn.Conv1d(ch, ch, kernel_size=kernel_size, padding=pad, dilation=dilation)
        self.norm2 = nn.GroupNorm(8, ch)
        self.act = nn.GELU()

    def forward(self, x: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        h = self.act(self.norm1(self.conv1(x))) * mask
        h = self.norm2(self.conv2(h)) * mask
        return self.act(x + h) * mask


class OrfSequenceEncoder(nn.Module):
    """氨基酸一级序列编码器（支持 baseline / R1 / R2+ 多尺度与高分辨率短基序支路）。"""

    def __init__(
        self,
        *,
        vocab_size: int,
        aa_embed_dim: int,
        aa_channels: int,
        is_ctx_rel: bool,
        is_r2_or_r3: bool,
        aa_mask_prob: float,
        distill_dim: int,
    ):
        super().__init__()
        self.is_ctx_rel = is_ctx_rel
        self.is_r2_or_r3 = is_r2_or_r3
        self.aa_mask_prob = float(aa_mask_prob)
        self.emb = nn.Embedding(vocab_size, aa_embed_dim, padding_idx=0)
        if is_ctx_rel:
            self._init_ctx_rel_layers(aa_embed_dim, aa_channels, is_r2_or_r3, distill_dim)
        else:
            self._init_baseline_layers(aa_embed_dim, aa_channels)

    def _init_ctx_rel_layers(
        self, aa_embed_dim: int, aa_channels: int, is_r2_or_r3: bool, distill_dim: int
    ) -> None:
        self.stem = nn.Sequential(
            nn.Conv1d(aa_embed_dim, aa_channels, kernel_size=5, stride=2, padding=2),
            nn.GroupNorm(8, aa_channels),
            nn.GELU(),
        )
        self.blocks = nn.ModuleList(
            [
                MaskedSeqConvBlock1d(aa_channels, kernel_size=5, dilation=1),
                MaskedSeqConvBlock1d(aa_channels, kernel_size=7, dilation=2),
            ]
        )
        self.ds_conv = nn.Sequential(
            nn.Conv1d(aa_channels, aa_channels, kernel_size=5, stride=2, padding=2),
            nn.GroupNorm(8, aa_channels),
            nn.GELU(),
        )
        seq_attn_layer = nn.TransformerEncoderLayer(
            d_model=aa_channels,
            nhead=4,
            dim_feedforward=aa_channels * 2,
            dropout=0.20,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.seq_attn = nn.TransformerEncoder(
            seq_attn_layer,
            num_layers=2,
            enable_nested_tensor=False,
        )
        self.attn_pool = nn.Conv1d(aa_channels, 4, kernel_size=1)
        proj_in = aa_channels * (2 + 4) + 1
        if is_r2_or_r3:
            self.hi_motif = nn.Sequential(
                nn.Conv1d(aa_embed_dim, 48, kernel_size=5, stride=1, padding=2),
                nn.GroupNorm(8, 48),
                nn.GELU(),
                nn.Conv1d(48, 48, kernel_size=3, stride=1, padding=1),
                nn.GroupNorm(8, 48),
                nn.GELU(),
            )
            proj_in += 48 * 2
        self.proj = nn.Sequential(
            nn.Linear(proj_in, 128),
            nn.LayerNorm(128),
            nn.GELU(),
            nn.Dropout(0.25),
        )
        if is_r2_or_r3:
            self.distill_proj = nn.Sequential(
                nn.Linear(128, 256),
                nn.LayerNorm(256),
                nn.GELU(),
                nn.Linear(256, int(distill_dim)),
            )

    def _init_baseline_layers(self, aa_embed_dim: int, aa_channels: int) -> None:
        self.stem = nn.Sequential(
            nn.Conv1d(aa_embed_dim, aa_channels, kernel_size=5, padding=2),
            nn.GroupNorm(8, aa_channels),
            nn.GELU(),
        )
        self.blocks = nn.ModuleList(
            [
                MaskedSeqConvBlock1d(aa_channels, kernel_size=5, dilation=1),
                MaskedSeqConvBlock1d(aa_channels, kernel_size=5, dilation=2),
                MaskedSeqConvBlock1d(aa_channels, kernel_size=7, dilation=4),
            ]
        )
        self.attn_pool = nn.Conv1d(aa_channels, 1, kernel_size=1)
        self.proj = nn.Sequential(
            nn.Linear(aa_channels * 3 + 1, 128),
            nn.LayerNorm(128),
            nn.GELU(),
            nn.Dropout(0.15),
        )

    def forward(self, flat_ids: torch.Tensor, flat_lens: torch.Tensor) -> torch.Tensor:
        n_items, max_l = flat_ids.shape
        if n_items == 0:
            return flat_ids.new_zeros((0, 128), dtype=torch.float32)

        pos = torch.arange(max_l, device=flat_ids.device)[None, :]
        raw_valid = pos < flat_lens[:, None]
        if self.is_ctx_rel and self.training and self.aa_mask_prob > 0.0:
            drop_mask = (
                (torch.rand_like(flat_ids, dtype=torch.float32) < self.aa_mask_prob)
                & raw_valid
                & (flat_ids > 0)
            )
            in_ids = torch.where(drop_mask, flat_ids.new_full((), 21), flat_ids)
        else:
            in_ids = flat_ids

        mask = raw_valid.unsqueeze(1)
        x = self.emb(in_ids).permute(0, 2, 1)
        mask_f = mask.to(x.dtype)
        if self.is_ctx_rel:
            return self._forward_ctx_rel(x, mask, mask_f, flat_ids, flat_lens, n_items)
        return self._forward_baseline(x, mask, mask_f, flat_lens)

    def _forward_ctx_rel(
        self,
        x: torch.Tensor,
        mask: torch.Tensor,
        mask_f: torch.Tensor,
        flat_ids: torch.Tensor,
        flat_lens: torch.Tensor,
        n_items: int,
    ) -> torch.Tensor:
        h = self.stem(x * mask_f)
        s1_len = h.shape[-1]
        s1_cnt = ((flat_lens - 1) // 2 + 1).clamp(min=1, max=s1_len)
        s1_mask = (torch.arange(s1_len, device=flat_ids.device)[None, :] < s1_cnt[:, None]).unsqueeze(1).to(h.dtype)
        h = h * s1_mask
        for blk in self.blocks:
            h = blk(h, s1_mask)

        h_ds = self.ds_conv(h)
        ds_len = h_ds.shape[-1]
        ds_cnt = ((flat_lens - 1) // 4 + 1).clamp(min=1, max=ds_len)
        ds_valid = torch.arange(ds_len, device=flat_ids.device)[None, :] < ds_cnt[:, None]
        h_seq = self.seq_attn(h_ds.transpose(1, 2), src_key_padding_mask=~ds_valid)
        h_c = h_seq.transpose(1, 2)
        ds_mask_f = ds_valid.unsqueeze(1).to(h_c.dtype)
        h_c = h_c * ds_mask_f

        mean_p = h_c.sum(dim=-1) / ds_mask_f.sum(dim=-1).clamp(min=1.0)
        max_p = h_c.masked_fill(~ds_valid.unsqueeze(1), -1e4).max(dim=-1).values
        attn_l = self.attn_pool(h_c).masked_fill(~ds_valid.unsqueeze(1), -1e4)
        attn_w = torch.softmax(attn_l, dim=-1)
        attn_p = torch.einsum("nkl,ncl->nkc", attn_w, h_c).reshape(n_items, -1)
        len_f = torch.log1p(flat_lens.to(h_c.dtype)).unsqueeze(-1) / 7.0
        parts = [mean_p, max_p, attn_p, len_f]
        if self.is_r2_or_r3:
            hi = self.hi_motif(x * mask_f) * mask_f
            hi_mean = hi.sum(dim=-1) / mask_f.sum(dim=-1).clamp(min=1.0)
            hi_max = hi.masked_fill(~mask, -1e4).max(dim=-1).values
            parts.extend([hi_mean, hi_max])
        return self.proj(torch.cat(parts, dim=-1))

    def _forward_baseline(
        self, x: torch.Tensor, mask: torch.Tensor, mask_f: torch.Tensor, flat_lens: torch.Tensor
    ) -> torch.Tensor:
        h = self.stem(x * mask_f) * mask_f
        for blk in self.blocks:
            h = blk(h, mask_f)

        mean_p = h.sum(dim=-1) / mask_f.sum(dim=-1).clamp(min=1.0)
        max_p = h.masked_fill(~mask, -1e4).max(dim=-1).values
        attn_l = self.attn_pool(h).squeeze(1).masked_fill(~mask.squeeze(1), -1e4)
        attn_w = torch.softmax(attn_l, dim=-1).unsqueeze(1)
        attn_p = (h * attn_w).sum(dim=-1)
        len_f = torch.log1p(flat_lens.to(h.dtype)).unsqueeze(-1) / 7.0
        return self.proj(torch.cat([mean_p, max_p, attn_p, len_f], dim=-1))


class RelativeOperonAttentionBlock(nn.Module):
    """携带基因间相对位置、同链共线性与紧密操纵子连接偏置的 Pre-Norm Transformer 层。"""

    def __init__(self, dim: int, num_heads: int, dropout: float = 0.15):
        super().__init__()
        self.dim = dim
        self.num_heads = num_heads
        self.head_dim = dim // num_heads
        self.norm1 = nn.LayerNorm(dim)
        self.qkv = nn.Linear(dim, dim * 3)
        self.bias_proj = nn.Linear(4, num_heads, bias=False)
        self.proj = nn.Linear(dim, dim)
        self.drop = nn.Dropout(dropout)
        self.norm2 = nn.LayerNorm(dim)
        self.ffn = nn.Sequential(
            nn.Linear(dim, dim * 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(dim * 2, dim),
            nn.Dropout(dropout),
        )

    def forward(self, x: torch.Tensor, rel_topo: torch.Tensor, valid_mask: torch.Tensor) -> torch.Tensor:
        bsz, seq_len, _ = x.shape
        h = self.norm1(x)
        qkv = self.qkv(h).reshape(bsz, seq_len, 3, self.num_heads, self.head_dim).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]
        scores = torch.matmul(q, k.transpose(-2, -1)) / (float(self.head_dim) ** 0.5)
        topo_bias = self.bias_proj(rel_topo).permute(0, 3, 1, 2)
        scores = scores + topo_bias.to(scores.dtype)
        key_invalid = (~valid_mask)[:, None, None, :]
        scores = scores.masked_fill(key_invalid, -1e4)
        attn = torch.softmax(scores, dim=-1) * valid_mask[:, None, :, None].to(scores.dtype)
        attn = self.drop(attn)
        out = torch.matmul(attn, v).transpose(1, 2).reshape(bsz, seq_len, self.dim)
        x = x + self.drop(self.proj(out))
        x = x + self.ffn(self.norm2(x))
        return x * valid_mask.unsqueeze(-1).to(x.dtype)


def compute_operon_rel_topo(stat_feats: torch.Tensor, valid_mask: torch.Tensor) -> torch.Tensor:
    """
    从纯序列统计张量 stat_feats[..., 98:102] 解析每对 ORF (i, j) 的 4 维操纵子相对拓扑关系：
      [signed_rel_pos, inv_dist, same_strand, same_operon_block]。
    """
    bsz, seq_len, _ = stat_feats.shape
    device = stat_feats.device
    vm_f = valid_mask.to(torch.float32)

    strand = torch.where(stat_feats[:, :, 99] >= 0.0, 1.0, -1.0) * vm_f
    gap_next = torch.expm1(torch.clamp(stat_feats[:, :, 101].float() * 10.0, min=0.0, max=14.0))
    same_next_flag = stat_feats[:, :, 103].float() > 0.5

    pos = torch.arange(seq_len, device=device, dtype=torch.float32)
    diff = pos[None, :] - pos[:, None]
    signed_rel = torch.clamp(diff / 16.0, -1.0, 1.0)[None, :, :].expand(bsz, -1, -1)
    inv_dist = (1.0 / (1.0 + torch.abs(diff)))[None, :, :].expand(bsz, -1, -1)
    same_strand = 0.5 * (strand[:, :, None] * strand[:, None, :] + 1.0)

    if seq_len > 1:
        adj_valid = valid_mask[:, :-1] & valid_mask[:, 1:]
        adj_operon = adj_valid & same_next_flag[:, :-1] & (gap_next[:, :-1] <= 350.0)
        breaks = (~adj_operon).to(torch.long)
        block_ids = torch.cat(
            [torch.zeros((bsz, 1), device=device, dtype=torch.long), torch.cumsum(breaks, dim=1)],
            dim=1,
        )
        same_operon = (block_ids[:, :, None] == block_ids[:, None, :]).to(torch.float32)
    else:
        same_operon = torch.ones((bsz, 1, 1), device=device, dtype=torch.float32)

    pair_valid = (valid_mask[:, :, None] & valid_mask[:, None, :]).to(torch.float32)
    rel = torch.stack([signed_rel, inv_dist, same_strand, same_operon], dim=-1)
    return rel * pair_valid.unsqueeze(-1)


class OrfFunctionalJudgeNet(nn.Module):
    """ORF 功能分区与噬菌体同源基因精判主网络（保持 state_dict 键名与缓冲区结构 100% 不变）。"""

    stat_mean: torch.Tensor
    stat_std: torch.Tensor

    def __init__(
        self,
        stat_mean: np.ndarray,
        stat_std: np.ndarray,
        *,
        vocab_size: int,
        stat_dim: int,
        d_model: int,
        nhead: int,
        num_ctx_layers: int,
        ctx_len: int,
        aa_embed_dim: int,
        aa_channels: int,
        use_aa_seq: bool,
        num_classes: int,
        arch: str,
        aa_mask_prob: float,
        distill_dim: int,
    ):
        super().__init__()
        self.arch = arch
        self.use_aa_seq = bool(use_aa_seq)
        self.is_ctx_rel = arch in ("r1", "r2", "r3", "unified", "unified_v4_3")
        self.is_r2_or_r3 = arch in ("r2", "r3", "unified", "unified_v4_3")
        self.is_r3 = arch in ("r3", "unified", "unified_v4_3")
        self.is_unified = arch in ("unified", "unified_v4_3")
        self.is_v4_3 = arch == "unified_v4_3"
        self.distill_dim = int(distill_dim)

        self.register_buffer("stat_mean", torch.tensor(stat_mean, dtype=torch.float32))
        self.register_buffer("stat_std", torch.tensor(stat_std, dtype=torch.float32))

        self.stat_enc = nn.Sequential(
            nn.Linear(stat_dim, 128),
            nn.LayerNorm(128),
            nn.GELU(),
            nn.Dropout(0.15),
        )
        if self.use_aa_seq:
            self.seq_enc = OrfSequenceEncoder(
                vocab_size=vocab_size,
                aa_embed_dim=aa_embed_dim,
                aa_channels=aa_channels,
                is_ctx_rel=self.is_ctx_rel,
                is_r2_or_r3=self.is_r2_or_r3,
                aa_mask_prob=aa_mask_prob,
                distill_dim=distill_dim,
            )
            fuse_in = 256
        else:
            fuse_in = 128

        self.orf_fuse = nn.Sequential(
            nn.Linear(fuse_in, d_model),
            nn.LayerNorm(d_model),
            nn.GELU(),
            nn.Dropout(0.15),
        )
        self._init_context_and_heads(d_model, nhead, num_ctx_layers, ctx_len, num_classes)

    def _init_context_and_heads(
        self, d_model: int, nhead: int, num_ctx_layers: int, ctx_len: int, num_classes: int
    ) -> None:
        if self.is_ctx_rel:
            self.ctx_blocks = nn.ModuleList(
                [RelativeOperonAttentionBlock(d_model, nhead, dropout=0.15) for _ in range(num_ctx_layers)]
            )
        else:
            self.ctx_pos_emb = nn.Parameter(torch.randn(1, ctx_len, d_model) * 0.02)
            enc_layer = nn.TransformerEncoderLayer(
                d_model=d_model,
                nhead=nhead,
                dim_feedforward=d_model * 2,
                dropout=0.15,
                activation="gelu",
                batch_first=True,
                norm_first=True,
            )
            self.ctx_encoder = nn.TransformerEncoder(
                enc_layer,
                num_layers=num_ctx_layers,
                enable_nested_tensor=False,
            )

        self.func10_head = nn.Sequential(
            nn.Linear(d_model, 128),
            nn.GELU(),
            nn.Dropout(0.15),
            nn.Linear(128, num_classes),
        )
        if not self.is_ctx_rel:
            self.phage_head = nn.Sequential(
                nn.Linear(d_model, 64),
                nn.GELU(),
                nn.Dropout(0.10),
                nn.Linear(64, 1),
            )
            return

        self.phage_head = nn.Sequential(
            nn.Linear(d_model + num_classes * 2 + 2, 96),
            nn.LayerNorm(96),
            nn.GELU(),
            nn.Dropout(0.15),
            nn.Linear(96, 1),
        )
        self.gamma_p9_self = nn.Parameter(torch.tensor(0.5))
        self.gamma_p9_ctx = nn.Parameter(torch.tensor(0.3))
        self.gamma_core_ctx = nn.Parameter(torch.tensor(0.3))
        if self.is_r3:
            self.macro_pool_w = nn.Linear(d_model, 1)
            self.macro_fuse = nn.Sequential(
                nn.Linear(d_model * 2 + 6, d_model),
                nn.LayerNorm(d_model),
                nn.GELU(),
                nn.Dropout(0.15),
            )
            self.macro_film_scale = nn.Linear(d_model, d_model)
            self.macro_film_shift = nn.Linear(d_model, d_model)
            self.win_core_head = nn.Sequential(
                nn.Linear(d_model + 6, 64),
                nn.GELU(),
                nn.Dropout(0.10),
                nn.Linear(64, 1),
            )
        if self.is_unified:
            if self.is_v4_3:
                self.intact_dualskip_proj = nn.Sequential(
                    nn.Linear(d_model * 2, d_model),
                    nn.LayerNorm(d_model),
                    nn.GELU(),
                    nn.Dropout(0.15),
                )
                self.tailocin_guard_head = nn.Sequential(
                    nn.Linear(d_model + 14, 64),
                    nn.GELU(),
                    nn.Dropout(0.10),
                    nn.Linear(64, 1),
                )
                self.gamma_tailocin = nn.Parameter(torch.tensor(0.5))
            self.intact_func_head = nn.Sequential(
                nn.Linear(d_model, 128),
                nn.GELU(),
                nn.Dropout(0.15),
                nn.Linear(128, num_classes),
            )

    def _encode_orf_features(
        self,
        aa_ids: torch.Tensor,
        aa_lens: torch.Tensor,
        stat_feats: torch.Tensor,
        valid_mask: torch.Tensor,
        return_seq_distill: bool,
    ):
        bsz, seq_len, _ = stat_feats.shape
        stat_norm = ((stat_feats - self.stat_mean) / self.stat_std) * valid_mask.unsqueeze(-1).to(stat_feats.dtype)
        e_stat = self.stat_enc(stat_norm)
        distill_out = None
        if not self.use_aa_seq:
            return self.orf_fuse(e_stat), distill_out

        flat_mask = valid_mask.reshape(-1)
        e_seq = e_stat.new_zeros((bsz * seq_len, 128))
        if torch.any(flat_mask):
            v_ids = aa_ids.reshape(-1, aa_ids.shape[-1])[flat_mask]
            v_lens = aa_lens.reshape(-1)[flat_mask]
            seq_out = self.seq_enc(v_ids, v_lens).to(e_seq.dtype)
            e_seq[flat_mask] = seq_out
            if return_seq_distill and self.is_r2_or_r3:
                d_flat = e_stat.new_zeros((bsz * seq_len, self.distill_dim))
                d_flat[flat_mask] = self.seq_enc.distill_proj(seq_out).to(d_flat.dtype)
                distill_out = d_flat.reshape(bsz, seq_len, self.distill_dim)
        e_seq = e_seq.reshape(bsz, seq_len, 128)
        return self.orf_fuse(torch.cat([e_stat, e_seq], dim=-1)), distill_out

    def _apply_macro_context(
        self,
        h: torch.Tensor,
        stat_feats: torch.Tensor,
        valid_mask: torch.Tensor,
        vm: torch.Tensor,
        has_any: torch.Tensor,
    ):
        denom_f = vm.sum(dim=1).clamp(min=1.0)
        mean_t = (stat_feats[:, :, 98:104] * vm).to(h.dtype).sum(dim=1) / denom_f
        w_l = self.macro_pool_w(h).squeeze(-1).masked_fill(~valid_mask, -1e4)
        w_a = torch.softmax(w_l, dim=-1).unsqueeze(-1)
        h_attn = (h * w_a).sum(dim=1)
        h_max = h.masked_fill(~valid_mask.unsqueeze(-1), -1e4).max(dim=1).values
        h_max = torch.where(has_any[:, None], h_max, h_max.new_zeros(h_max.shape))
        h_macro = self.macro_fuse(torch.cat([h_attn, h_max, mean_t], dim=-1))
        scale = 1.0 + 0.5 * torch.tanh(self.macro_film_scale(h_macro)).unsqueeze(1)
        shift = 0.5 * self.macro_film_shift(h_macro).unsqueeze(1)
        return (h * scale + shift) * vm, h_macro

    def forward(
        self,
        aa_ids: torch.Tensor,
        aa_lens: torch.Tensor,
        stat_feats: torch.Tensor,
        valid_counts: torch.Tensor,
        return_seq_distill: bool = False,
        return_win_core: bool = False,
        active_experts: Sequence[str] | None = None,
        return_experts: bool = False,
        detach_intact_base: bool = False,
    ):
        _, seq_len, _ = stat_feats.shape
        pos = torch.arange(seq_len, device=stat_feats.device)[None, :]
        valid_mask = pos < valid_counts[:, None]
        has_any = valid_counts > 0
        e_orf, distill_out = self._encode_orf_features(aa_ids, aa_lens, stat_feats, valid_mask, return_seq_distill)
        vm = valid_mask.unsqueeze(-1).to(e_orf.dtype)

        if not self.is_ctx_rel:
            h = e_orf + self.ctx_pos_emb[:, :seq_len, :].to(e_orf.dtype)
            safe_pad = (~valid_mask) & ((pos > 0) | has_any[:, None])
            h = self.ctx_encoder(h, src_key_padding_mask=safe_pad)
            vm = valid_mask.unsqueeze(-1).to(h.dtype)
            h = h * vm
            return self.func10_head(h) * vm, self.phage_head(h).squeeze(-1) * valid_mask.to(h.dtype)

        rel_topo = compute_operon_rel_topo(stat_feats, valid_mask)
        h_base = e_orf * vm
        for blk in self.ctx_blocks:
            h_base = blk(h_base, rel_topo, valid_mask)

        exp_set = (
            set(active_experts)
            if active_experts is not None
            else ({"defense_func", "intact"} if self.is_unified else {"defense_func"})
        )
        need_defense_func = (not self.is_unified) or bool(exp_set & {"defense_func", "func", "phage"})
        need_intact = self.is_unified and ("intact" in exp_set)

        intact_logits = None
        if need_intact:
            if self.is_v4_3:
                e_in = e_orf.detach() if detach_intact_base else e_orf
                h_in = h_base.detach() if detach_intact_base else h_base
                ds_feat = self.intact_dualskip_proj(torch.cat([e_in, h_in], dim=-1)) * vm
                intact_logits = self.intact_func_head(ds_feat) * vm
            else:
                base_in = h_base.detach() if detach_intact_base else h_base
                intact_logits = self.intact_func_head(base_in) * vm

        func10_logits = phage_logits = win_core_logit = tailocin_neg_logit = None
        if need_defense_func:
            h = h_base
            h_macro = None
            if self.is_r3:
                h, h_macro = self._apply_macro_context(h, stat_feats, valid_mask, vm, has_any)
            func10_logits = self.func10_head(h) * vm
            f_prob = torch.sigmoid(func10_logits) * vm
            denom = vm.sum(dim=1, keepdim=True).clamp(min=1.0)
            ctx_f_mean = (f_prob.sum(dim=1, keepdim=True) / denom).expand(-1, seq_len, -1)
            core_max_per_cls = f_prob[:, :, :5].masked_fill(~valid_mask.unsqueeze(-1), 0.0).max(dim=1).values
            ctx_core_signal = core_max_per_cls.mean(dim=-1, keepdim=True).unsqueeze(1).expand(-1, seq_len, -1)
            ctx_p9_mean = ctx_f_mean[:, :, 9:10]
            if self.is_r3 and h_macro is not None:
                win_core_logit = self.win_core_head(
                    torch.cat([h_macro, core_max_per_cls, ctx_p9_mean[:, 0, :]], dim=-1)
                ).squeeze(-1) * has_any.to(h.dtype)

            ph_in = torch.cat([h, f_prob, ctx_f_mean, ctx_core_signal, ctx_p9_mean], dim=-1)
            raw_ph = self.phage_head(ph_in).squeeze(-1)
            tailocin_pen: torch.Tensor | float = 0.0
            if self.is_v4_3 and h_macro is not None:
                tailocin_neg_logit = self.tailocin_guard_head(
                    torch.cat([h_macro, core_max_per_cls, ctx_f_mean[:, 0, :9]], dim=-1)
                ).squeeze(-1) * has_any.to(h.dtype)
                tailocin_pen = torch.nn.functional.softplus(self.gamma_tailocin) * torch.sigmoid(tailocin_neg_logit).unsqueeze(1)
            phage_logits = (
                raw_ph
                - torch.nn.functional.softplus(self.gamma_p9_self) * (f_prob[:, :, 9] - 0.5)
                - torch.nn.functional.softplus(self.gamma_p9_ctx) * ctx_p9_mean.squeeze(-1)
                + torch.nn.functional.softplus(self.gamma_core_ctx) * ctx_core_signal.squeeze(-1)
                - tailocin_pen
            ) * valid_mask.to(raw_ph.dtype)

        if return_experts:
            return {
                "h_base": h_base,
                "e_orf": e_orf,
                "func10_logits": func10_logits,
                "phage_logits": phage_logits,
                "intact_func_logits": intact_logits,
                "distill_out": distill_out,
                "win_core_logit": win_core_logit,
                "tailocin_neg_logit": tailocin_neg_logit,
            }
        if return_win_core and self.is_r3:
            if return_seq_distill and distill_out is not None:
                return func10_logits, phage_logits, distill_out, win_core_logit
            return func10_logits, phage_logits, win_core_logit
        if return_seq_distill and self.is_r2_or_r3 and distill_out is not None:
            return func10_logits, phage_logits, distill_out
        return func10_logits, phage_logits
