"""V4.1 亚窗口边界精修头（Sub-Head）微调模块。"""
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..experts.seq_dataset import reverse_complement_codes
from ..features.window_features import SUB_BINS
from .v4_context_refiner import _predict_v4_all

logger = logging.getLogger(__name__)

def _compute_boundary_bin_weights(sub_arr: np.ndarray, sw_arr: np.ndarray) -> np.ndarray:
    """为 200bp 亚区跳变沿前后各 2 bins 及过渡窗口赋予更高损失权重。"""
    n, n_bins = sub_arr.shape
    bin_w = np.ones((n, n_bins), dtype=np.float32)
    if n_bins > 1:
        jumps = np.abs(np.diff(sub_arr, axis=1)) > 0.2
        for k in range(n_bins - 1):
            j = jumps[:, k]
            if np.any(j):
                lo = max(0, k - 1)
                hi = min(n_bins, k + 3)
                bin_w[j, lo:hi] = np.maximum(bin_w[j, lo:hi], 2.0)
    sub_mean = sub_arr.mean(axis=1)
    is_trans = (sub_mean > 0.02) & (sub_mean < 0.98)
    row_w = sw_arr.astype(np.float32) * np.where(is_trans, 1.25, 1.0).astype(np.float32)
    return bin_w * row_w[:, None]

def _extract_sub_head_inputs(
    model,
    codes: np.ndarray,
    lengths: np.ndarray,
    feats: np.ndarray,
    tokens: np.ndarray,
    counts: np.ndarray,
    device,
    batch_size: int = 128,
) -> Tuple[np.ndarray, np.ndarray]:
    """在冻结主干 eval 状态下提取 sub_pool(h_seq) 与 h_fused 特征，杜绝主干权重漂移。"""
    import torch

    n = len(codes)
    if n == 0:
        return (
            np.zeros((0, 1, SUB_BINS), dtype=np.float32),
            np.zeros((0, 1), dtype=np.float32),
        )
    model.eval()
    pool_chunks: List[np.ndarray] = []
    fused_chunks: List[np.ndarray] = []
    with torch.no_grad(), torch.autocast(device_type=device.type, dtype=torch.float16, enabled=device.type == "cuda"):
        for i in range(0, n, batch_size):
            sl = slice(i, i + batch_size)
            c_t = torch.from_numpy(codes[sl].astype(np.int64)).to(device)
            oh = torch.nn.functional.one_hot(c_t, num_classes=5)[..., :4].permute(0, 2, 1).float()
            tb_t = torch.from_numpy(feats[sl]).to(device)
            ln_t = torch.from_numpy(lengths[sl].astype(np.int64)).to(device)
            tk_t = torch.from_numpy(tokens[sl]).to(device)
            cn_t = torch.from_numpy(counts[sl].astype(np.int64)).to(device)
            h_seq, h_fused = model._forward_backbone(oh, tb_t, lengths=ln_t, orf_tokens=tk_t, orf_counts=cn_t)
            pool_chunks.append(model.sub_pool(h_seq).float().cpu().numpy())
            fused_chunks.append(h_fused.float().cpu().numpy())
    return np.concatenate(pool_chunks, axis=0), np.concatenate(fused_chunks, axis=0)

def refine_student_v4_sub_head(
    model,
    tr_codes: np.ndarray,
    tr_lengths: np.ndarray,
    tr_feats: np.ndarray,
    tr_tokens: np.ndarray,
    tr_counts: np.ndarray,
    tr_sub: np.ndarray,
    tr_sw: np.ndarray,
    va_codes: np.ndarray,
    va_lengths: np.ndarray,
    va_feats: np.ndarray,
    va_tokens: np.ndarray,
    va_counts: np.ndarray,
    va_sub: np.ndarray,
    *,
    out_ckpt_path: Optional[Path] = None,
    device=None,
    epochs: int = 12,
    batch_size: int = 128,
    lr: float = 1e-3,
    patience: int = 4,
    seed: int = 42,
    tr_labels: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """严格冻结 3.64M 主干权重，仅基于纯 BCE 在过渡与平衡窗口上精修 sub_cond + sub_head 消除边界平台扩散。"""
    import copy
    import torch
    import torch.nn.functional as F

    if device is None:
        device = next(model.parameters()).device
    rng = np.random.default_rng(seed)
    torch.manual_seed(seed)

    va_before = _predict_v4_all(
        model, va_codes, va_lengths, va_feats, va_tokens, va_counts, device, batch_size=max(batch_size, 128),
    )

    valid_mask = tr_sw > 0
    if tr_labels is not None:
        valid_mask = valid_mask & (tr_labels >= -1)
    tr_sub_f = tr_sub.astype(np.float32)
    sub_mean = tr_sub_f.mean(axis=1)

    trans_idx = np.where(valid_mask & (sub_mean > 0.02) & (sub_mean < 0.98))[0]
    pos_idx = np.where(valid_mask & (sub_mean >= 0.98))[0]
    neg_idx = np.where(valid_mask & (sub_mean <= 0.02))[0]

    total_valid = int(np.sum(valid_mask))
    if total_valid <= 512:
        sel_idx = np.where(valid_mask)[0]
    else:
        max_anchor = max(len(trans_idx), 1500)
        pos_sel = rng.choice(pos_idx, size=min(len(pos_idx), max_anchor), replace=False) if len(pos_idx) > 0 else np.zeros(0, dtype=np.int64)
        neg_sel = rng.choice(neg_idx, size=min(len(neg_idx), max_anchor), replace=False) if len(neg_idx) > 0 else np.zeros(0, dtype=np.int64)
        sel_idx = np.concatenate([trans_idx, pos_sel, neg_sel]).astype(np.int64)
        rng.shuffle(sel_idx)

    if len(sel_idx) == 0:
        return {
            "best_epoch": 0,
            "best_val_sub_bce": -1.0,
            "tr_used": 0,
            "tr_trans": 0,
            "win_max_drift": 0.0,
            "sem_max_drift": 0.0,
            "sub_max_delta": 0.0,
            "history": [],
        }

    max_len_seq = int(tr_codes.shape[1]) if tr_codes.ndim == 2 else 5000
    tr_pool, tr_fused = _extract_sub_head_inputs(
        model, tr_codes[sel_idx], tr_lengths[sel_idx], tr_feats[sel_idx], tr_tokens[sel_idx], tr_counts[sel_idx],
        device, batch_size=max(batch_size, 128),
    )
    tr_sub_sel = tr_sub_f[sel_idx]
    tr_w_sel = _compute_boundary_bin_weights(tr_sub_sel, tr_sw[sel_idx])

    # 对满长边界过渡窗口补充反向互补对等样本，增强正反链边界切点对称性
    full_trans = trans_idx[tr_lengths[trans_idx] == max_len_seq]
    if len(full_trans) > 0:
        rc_codes = reverse_complement_codes(tr_codes[full_trans], tr_lengths[full_trans])
        rc_pool, rc_fused = _extract_sub_head_inputs(
            model, rc_codes, tr_lengths[full_trans], tr_feats[full_trans], tr_tokens[full_trans], tr_counts[full_trans],
            device, batch_size=max(batch_size, 128),
        )
        rc_sub = tr_sub_f[full_trans][:, ::-1].copy()
        rc_w = _compute_boundary_bin_weights(rc_sub, tr_sw[full_trans])
        tr_pool = np.concatenate([tr_pool, rc_pool], axis=0)
        tr_fused = np.concatenate([tr_fused, rc_fused], axis=0)
        tr_sub_sel = np.concatenate([tr_sub_sel, rc_sub], axis=0)
        tr_w_sel = np.concatenate([tr_w_sel, rc_w], axis=0)

    # 提取验证集原链及满长反向互补特征，确保 val BCE 口径与双链平均推理完全对齐
    va_sub_f = va_sub.astype(np.float32)
    va_pool_f, va_fused_f = _extract_sub_head_inputs(
        model, va_codes, va_lengths, va_feats, va_tokens, va_counts, device, batch_size=max(batch_size, 128),
    )
    va_rc_mask = (va_lengths == max_len_seq)
    va_rc_idxs = np.where(va_rc_mask)[0]
    if len(va_rc_idxs) > 0:
        va_rc_codes = reverse_complement_codes(va_codes[va_rc_idxs], va_lengths[va_rc_idxs])
        va_pool_rc, va_fused_rc = _extract_sub_head_inputs(
            model, va_rc_codes, va_lengths[va_rc_idxs], va_feats[va_rc_idxs], va_tokens[va_rc_idxs], va_counts[va_rc_idxs],
            device, batch_size=max(batch_size, 128),
        )
    else:
        va_pool_rc = np.zeros((0, tr_pool.shape[1], SUB_BINS), dtype=np.float32)
        va_fused_rc = np.zeros((0, tr_fused.shape[1]), dtype=np.float32)

    va_sub_mean = va_sub_f.mean(axis=1)
    va_trans_mask = (va_sub_mean > 0.02) & (va_sub_mean < 0.98)

    # 严格冻结主干与其它头，仅开放 sub_cond 与 sub_head 参数
    orig_req_grad = {name: p.requires_grad for name, p in model.named_parameters()}
    for p in model.parameters():
        p.requires_grad_(False)
    trainable_params = list(model.sub_cond.parameters()) + list(model.sub_head.parameters())
    for p in trainable_params:
        p.requires_grad_(True)

    opt = torch.optim.AdamW(trainable_params, lr=lr, weight_decay=1e-3)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(1, epochs))

    best_bce = 1e9
    best_ep = -1
    bad_ep = 0
    best_sub_cond = copy.deepcopy(model.sub_cond.state_dict())
    best_sub_head = copy.deepcopy(model.sub_head.state_dict())
    history: List[Dict[str, Any]] = []

    for ep in range(1, epochs + 1):
        model.eval()
        model.sub_cond.train()
        model.sub_head.train()
        order = rng.permutation(len(tr_pool))
        ep_loss = 0.0
        n_seen = 0
        for i in range(0, len(order), batch_size):
            b_idx = order[i:i + batch_size]
            p_t = torch.from_numpy(tr_pool[b_idx]).to(device)
            f_t = torch.from_numpy(tr_fused[b_idx]).to(device)
            y_t = torch.from_numpy(tr_sub_sel[b_idx]).to(device)
            w_t = torch.from_numpy(tr_w_sel[b_idx]).to(device)

            opt.zero_grad(set_to_none=True)
            sub_logits = model.sub_head(p_t + model.sub_cond(f_t).unsqueeze(-1)).squeeze(1)
            bce = F.binary_cross_entropy_with_logits(sub_logits, y_t, reduction="none")
            loss = (bce * w_t).sum() / w_t.sum().clamp(min=1e-6)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(trainable_params, 1.0)
            opt.step()
            ep_loss += float(loss.item()) * len(b_idx)
            n_seen += len(b_idx)
        sched.step()

        model.eval()
        with torch.no_grad():
            n_va = len(va_pool_f)
            va_probs = np.zeros((n_va, SUB_BINS), dtype=np.float32)
            for i in range(0, n_va, max(batch_size, 256)):
                sl = slice(i, i + max(batch_size, 256))
                p_t = torch.from_numpy(va_pool_f[sl]).to(device)
                f_t = torch.from_numpy(va_fused_f[sl]).to(device)
                va_probs[sl] = torch.sigmoid(model.sub_head(p_t + model.sub_cond(f_t).unsqueeze(-1)).squeeze(1)).cpu().numpy()
            if len(va_rc_idxs) > 0:
                rc_probs = np.zeros((len(va_rc_idxs), SUB_BINS), dtype=np.float32)
                for i in range(0, len(va_rc_idxs), max(batch_size, 256)):
                    sl = slice(i, i + max(batch_size, 256))
                    p_t = torch.from_numpy(va_pool_rc[sl]).to(device)
                    f_t = torch.from_numpy(va_fused_rc[sl]).to(device)
                    rc_probs[sl] = torch.sigmoid(model.sub_head(p_t + model.sub_cond(f_t).unsqueeze(-1)).squeeze(1)).cpu().numpy()
                va_probs[va_rc_idxs] = 0.5 * (va_probs[va_rc_idxs] + rc_probs[:, ::-1])

        p_clip = np.clip(va_probs, 1e-6, 1.0 - 1e-6)
        bce_mat = -(va_sub_f * np.log(p_clip) + (1.0 - va_sub_f) * np.log(1.0 - p_clip))
        va_all_bce = float(np.mean(bce_mat)) if len(bce_mat) > 0 else float(ep_loss / max(1, n_seen))
        va_trans_bce = float(np.mean(bce_mat[va_trans_mask])) if np.any(va_trans_mask) else va_all_bce
        va_metric = (0.7 * va_trans_bce + 0.3 * va_all_bce) if np.any(va_trans_mask) else va_all_bce

        history.append({
            "epoch": ep,
            "train_bce": round(ep_loss / max(1, n_seen), 6),
            "val_trans_bce": round(va_trans_bce, 6),
            "val_all_bce": round(va_all_bce, 6),
        })
        if va_metric < best_bce or best_ep < 0:
            best_bce, best_ep, bad_ep = va_metric, ep, 0
            best_sub_cond = copy.deepcopy(model.sub_cond.state_dict())
            best_sub_head = copy.deepcopy(model.sub_head.state_dict())
        else:
            bad_ep += 1
            if bad_ep >= patience:
                break

    model.sub_cond.load_state_dict(best_sub_cond)
    model.sub_head.load_state_dict(best_sub_head)
    model.eval()
    for name, p in model.named_parameters():
        p.requires_grad_(orig_req_grad.get(name, True))

    if out_ckpt_path is not None:
        out_p = Path(out_ckpt_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_p.with_name(f".{out_p.name}.tmp")
        torch.save(model.state_dict(), tmp)
        tmp.replace(out_p)

    va_after = _predict_v4_all(
        model, va_codes, va_lengths, va_feats, va_tokens, va_counts, device, batch_size=max(batch_size, 128),
    )
    win_max_drift = float(np.max(np.abs(va_after["win_logits"] - va_before["win_logits"]))) if len(va_codes) > 0 else 0.0
    sem_max_drift = float(np.max(np.abs(va_after["sem_logits"] - va_before["sem_logits"]))) if len(va_codes) > 0 else 0.0
    sub_max_delta = float(np.max(np.abs(va_after["sub_probs"] - va_before["sub_probs"]))) if len(va_codes) > 0 else 0.0

    del tr_pool, tr_fused, va_pool_f, va_fused_f, va_pool_rc, va_fused_rc
    if device.type == "cuda":
        torch.cuda.empty_cache()

    return {
        "best_epoch": best_ep,
        "best_val_sub_bce": round(best_bce, 6),
        "tr_used": len(tr_sub_sel),
        "tr_trans": len(trans_idx),
        "win_max_drift": win_max_drift,
        "sem_max_drift": sem_max_drift,
        "sub_max_delta": sub_max_delta,
        "history": history,
    }
