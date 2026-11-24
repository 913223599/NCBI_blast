# -*- coding: utf-8 -*-
"""
DistanceMatrixCalculator - GPU (PyTorch CUDA) 分块加速 + 多核向量化 NumPy 演化距离引擎
支持 p-distance、JC69、K2P (DNA) 及 Poisson (蛋白)，以及加权列重采样 Bootstrap 矩阵批量计算。
"""
import logging
import threading
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from ...core.fasta_io import read_fasta_records
from ...models.errors import PhyloCancelledError
from ...runtime.resource_guard import GpuGuard

logger = logging.getLogger("phylo.distance_gpu")

# DNA 碱基到 0..3 映射
_DNA_CHAR_MAP = np.full(256, -1, dtype=np.int16)
_DNA_CHAR_MAP[ord("A")] = 0
_DNA_CHAR_MAP[ord("C")] = 1
_DNA_CHAR_MAP[ord("G")] = 2
_DNA_CHAR_MAP[ord("T")] = 3
_DNA_CHAR_MAP[ord("U")] = 3

# 标准 20 种氨基酸到 0..19 映射
_AA_ALPHABET = "ACDEFGHIKLMNPQRSTVWY"
_AA_CHAR_MAP = np.full(256, -1, dtype=np.int16)
for _aa_idx, _aa_ch in enumerate(_AA_ALPHABET):
    _AA_CHAR_MAP[ord(_aa_ch)] = _aa_idx

EPSILON = 1e-9


def encode_alignment(msa_fasta: Path, mol_type: str = "dna") -> Tuple[List[str], np.ndarray]:
    """将已对齐的 FASTA 文件编码为 (N, L) 整数数组，有效字符为 0..K-1，缺口/未知为 -1。"""
    records = read_fasta_records(msa_fasta)
    if not records:
        raise ValueError(f"MSA 文件为空: {msa_fasta}")
    lengths = {len(r.seq) if r.seq is not None else 0 for r in records}
    if len(lengths) != 1:
        raise ValueError(f"MSA 序列长度不一致: {msa_fasta}")

    ids = [str(r.id or "") for r in records]
    n_seqs = len(records)
    first_seq = records[0].seq
    seq_len = len(first_seq) if first_seq is not None else 0

    raw_bytes = np.frombuffer(
        b"".join(str(r.seq).upper().encode("ascii", errors="replace") for r in records),
        dtype=np.uint8,
    ).reshape(n_seqs, seq_len)

    lut = _AA_CHAR_MAP if mol_type == "protein" else _DNA_CHAR_MAP
    encoded = lut[raw_bytes]
    return ids, encoded


def _distance_from_counts(
    n_valid: np.ndarray,
    n_same: np.ndarray,
    n_ts: Optional[np.ndarray],
    model: str,
    mol_type: str,
) -> np.ndarray:
    """根据有效比较位点数、相同数、转换数换算为对称演化距离矩阵 float64。"""
    safe_valid = np.maximum(n_valid, 1.0)
    p = np.clip((safe_valid - n_same) / safe_valid, 0.0, 1.0)
    # 若两序列无任何公共有效位点，赋予最大饱和距离
    no_overlap = n_valid < 1.0

    m = model.lower().strip()
    if mol_type == "protein":
        if m in ("poisson", "jtt", "lg", "wag"):
            # Poisson 校正近似蛋白进化距离
            p_clip = np.minimum(p, 0.999)
            dist = -np.log(np.maximum(EPSILON, 1.0 - p_clip))
        else:
            dist = p
    else:
        if m in ("jc", "jc69", "jukes-cantor"):
            p_clip = np.minimum(p, 0.7499)
            dist = -0.75 * np.log(np.maximum(EPSILON, 1.0 - (4.0 / 3.0) * p_clip))
        elif m in ("k2p", "kimura", "gtr") and n_ts is not None:
            P = np.clip(n_ts / safe_valid, 0.0, 1.0)
            Q = np.clip(p - P, 0.0, 1.0)
            term1 = np.maximum(0.01, 1.0 - 2.0 * P - Q)
            term2 = np.maximum(0.01, 1.0 - 2.0 * Q)
            dist = -0.5 * np.log(term1) - 0.25 * np.log(term2)
            dist = np.maximum(0.0, dist)
        else:
            dist = p

    dist = np.where(no_overlap, 1.0, dist).astype(np.float64)
    dist = 0.5 * (dist + dist.T)
    np.fill_diagonal(dist, 0.0)
    return dist


class DistanceMatrixCalculator:
    """
    演化距离矩阵计算器：
    优先采用 PyTorch CUDA 矩阵分块乘法计算成对相同/转换计数，
    严格限制单块显存并执行显存回收；无 CUDA 时无缝使用 NumPy 向量化内核。
    """

    def __init__(
        self,
        use_gpu: bool = True,
        cancel_event: Optional[threading.Event] = None,
    ) -> None:
        gpu_info = GpuGuard.probe() if use_gpu else {"available": False}
        self.cuda_enabled = bool(use_gpu and gpu_info["available"])
        self.cancel_event = cancel_event or threading.Event()

    def compute(
        self,
        encoded: np.ndarray,
        mol_type: str = "dna",
        model: str = "jc69",
        col_weights: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """计算单张距离矩阵。col_weights 为 None 时等权计算；传入长度 L 向量时等价于 Bootstrap 重采样。"""
        matrices = self.compute_batch(
            encoded=encoded,
            mol_type=mol_type,
            model=model,
            weights_batch=[col_weights] if col_weights is not None else [None],
        )
        return matrices[0]

    def compute_batch(
        self,
        encoded: np.ndarray,
        mol_type: str = "dna",
        model: str = "jc69",
        weights_batch: Optional[List[Optional[np.ndarray]]] = None,
    ) -> List[np.ndarray]:
        """批量计算多个列权重（主树 + 多批 Bootstrap 重采样）的距离矩阵。"""
        if self.cancel_event.is_set():
            raise PhyloCancelledError("距离矩阵计算前任务已取消")
        if weights_batch is None:
            weights_batch = [None]
        n_seqs, seq_len = encoded.shape
        workload = n_seqs * seq_len * len(weights_batch)
        # 极小规模数据集直接走 NumPy，避免 CUDA 初始化与 PCIe 传输开销
        if self.cuda_enabled and workload >= 50_000:
            try:
                return self._compute_batch_cuda(encoded, mol_type, model, weights_batch)
            except PhyloCancelledError:
                raise
            except Exception as exc:
                logger.warning(f"CUDA 距离计算回退至 NumPy CPU 引擎: {exc}")
                GpuGuard.release_vram()
        return self._compute_batch_numpy(encoded, mol_type, model, weights_batch)

    def _compute_batch_numpy(
        self,
        encoded: np.ndarray,
        mol_type: str,
        model: str,
        weights_batch: List[Optional[np.ndarray]],
    ) -> List[np.ndarray]:
        n_seqs, seq_len = encoded.shape
        alphabet_size = 20 if mol_type == "protein" else 4
        need_ts = mol_type == "dna" and model.lower().strip() in ("k2p", "kimura", "gtr")

        # 沿序列长度分块累加，严格限制 CPU 内存峰值（单块中间张量 <= 64 MB）
        bytes_per_col = max(1, n_seqs * alphabet_size * 4 * 2)
        col_chunk = max(256, min(seq_len, (64 * 1024 * 1024) // bytes_per_col))

        n_batches = len(weights_batch)
        valid_acc = np.zeros((n_batches, n_seqs, n_seqs), dtype=np.float64)
        same_acc = np.zeros((n_batches, n_seqs, n_seqs), dtype=np.float64)
        ts_acc = np.zeros((n_batches, n_seqs, n_seqs), dtype=np.float64) if need_ts else None

        for c0 in range(0, seq_len, col_chunk):
            if self.cancel_event.is_set():
                raise PhyloCancelledError("距离矩阵计算过程已取消")
            c1 = min(seq_len, c0 + col_chunk)
            sub = encoded[:, c0:c1]
            sub_valid = (sub >= 0).astype(np.float32)  # (N, Lc)
            lc = c1 - c0

            onehot = np.zeros((n_seqs, alphabet_size, lc), dtype=np.float32)
            for ch_idx in range(alphabet_size):
                onehot[:, ch_idx, :] = (sub == ch_idx).astype(np.float32)

            onehot_flat = onehot.reshape(n_seqs, alphabet_size * lc)
            onehot_ts = (
                onehot[:, [2, 3, 0, 1], :].reshape(n_seqs, alphabet_size * lc)
                if need_ts
                else None
            )

            for b_idx, weights in enumerate(weights_batch):
                if weights is None:
                    vw = sub_valid
                    xw = onehot_flat
                else:
                    w = weights[c0:c1].astype(np.float32)
                    vw = sub_valid * w[None, :]
                    xw = (onehot * w[None, None, :]).reshape(n_seqs, alphabet_size * lc)

                valid_acc[b_idx] += (vw @ sub_valid.T).astype(np.float64)
                same_acc[b_idx] += (xw @ onehot_flat.T).astype(np.float64)
                if ts_acc is not None and onehot_ts is not None:
                    ts_acc[b_idx] += (xw @ onehot_ts.T).astype(np.float64)

        results: List[np.ndarray] = []
        for b_idx in range(n_batches):
            n_ts_mat = ts_acc[b_idx] if ts_acc is not None else None
            results.append(
                _distance_from_counts(valid_acc[b_idx], same_acc[b_idx], n_ts_mat, model, mol_type)
            )
        return results

    def _compute_batch_cuda(
        self,
        encoded: np.ndarray,
        mol_type: str,
        model: str,
        weights_batch: List[Optional[np.ndarray]],
    ) -> List[np.ndarray]:
        import torch

        n_seqs, seq_len = encoded.shape
        alphabet_size = 20 if mol_type == "protein" else 4
        need_ts = mol_type == "dna" and model.lower().strip() in ("k2p", "kimura", "gtr")

        # 严控物理显存红线：若单序列过长则沿序列维度切片累加，防止大矩阵爆显存
        gpu_info = GpuGuard.probe()
        free_mb = max(256, gpu_info.get("free_vram_mb", 1024))
        # 单切片最多使用空闲显存的 25% 且上限 768 MB
        budget_bytes = min(768 * 1024 * 1024, int(free_mb * 0.25 * 1024 * 1024))
        bytes_per_col = max(1, n_seqs * alphabet_size * 4 * 3)
        col_chunk = max(256, min(seq_len, budget_bytes // bytes_per_col))

        device = torch.device("cuda")
        results: List[np.ndarray] = []

        try:
            with torch.no_grad():
                n_batches = len(weights_batch)
                valid_acc = np.zeros((n_batches, n_seqs, n_seqs), dtype=np.float64)
                same_acc = np.zeros((n_batches, n_seqs, n_seqs), dtype=np.float64)
                ts_acc = np.zeros((n_batches, n_seqs, n_seqs), dtype=np.float64) if need_ts else None

                for c0 in range(0, seq_len, col_chunk):
                    if self.cancel_event.is_set():
                        raise PhyloCancelledError("CUDA 距离矩阵计算过程已取消")
                    c1 = min(seq_len, c0 + col_chunk)
                    sub = torch.from_numpy(encoded[:, c0:c1]).to(device=device, dtype=torch.int64)
                    sub_valid = (sub >= 0).to(dtype=torch.float32)  # (N, Lc)

                    # (N, Lc, A) -> (N, A, Lc)
                    clamped = sub.clamp(min=0)
                    oh = torch.nn.functional.one_hot(clamped, num_classes=alphabet_size).to(dtype=torch.float32)
                    oh = oh * sub_valid.unsqueeze(-1)
                    oh_flat = oh.permute(0, 2, 1).reshape(n_seqs, -1)  # (N, A*Lc)
                    oh_ts_flat = (
                        oh[:, :, [2, 3, 0, 1]].permute(0, 2, 1).reshape(n_seqs, -1)
                        if need_ts
                        else None
                    )

                    for b_idx, weights in enumerate(weights_batch):
                        if weights is None:
                            vw = sub_valid
                            xw = oh_flat
                        else:
                            w_t = torch.from_numpy(weights[c0:c1]).to(device=device, dtype=torch.float32)
                            vw = sub_valid * w_t.unsqueeze(0)
                            xw = (oh.permute(0, 2, 1) * w_t.view(1, 1, -1)).reshape(n_seqs, -1)

                        valid_acc[b_idx] += torch.mm(vw, sub_valid.t()).cpu().numpy()
                        same_acc[b_idx] += torch.mm(xw, oh_flat.t()).cpu().numpy()
                        if ts_acc is not None and oh_ts_flat is not None:
                            ts_acc[b_idx] += torch.mm(xw, oh_ts_flat.t()).cpu().numpy()

                    del sub, sub_valid, clamped, oh, oh_flat, oh_ts_flat

                for b_idx in range(n_batches):
                    n_ts_mat = ts_acc[b_idx] if ts_acc is not None else None
                    results.append(
                        _distance_from_counts(valid_acc[b_idx], same_acc[b_idx], n_ts_mat, model, mol_type)
                    )
        finally:
            GpuGuard.release_vram()

        return results
