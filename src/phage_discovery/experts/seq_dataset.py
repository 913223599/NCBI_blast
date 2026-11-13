# -*- coding: utf-8 -*-
"""
窗口原始序列编码数据集（Expert B / Student 共用）

依据特征分片中的 (contig_ids, starts, ends) 坐标，从对应 FASTA 流式切出窗口碱基，
编码为 uint8（A=0, C=1, G=2, T=3, 其它=4）并右侧填充至固定长度，同时记录真实长度。
保证序列模型与表格模型使用完全相同的窗口集合与标签，便于专家融合与蒸馏对齐。
"""
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

from ..data.feature_dataset import iter_fasta

_CODE_LUT = np.full(256, 4, dtype=np.uint8)
for _ch, _code in (("A", 0), ("C", 1), ("G", 2), ("T", 3), ("a", 0), ("c", 1), ("g", 2), ("t", 3)):
    _CODE_LUT[ord(_ch)] = _code


def encode_dna(seq: str) -> np.ndarray:
    return _CODE_LUT[np.frombuffer(seq.encode("ascii", errors="replace"), dtype=np.uint8)]


def load_window_sequences(
    fasta_path: Path,
    contig_ids: np.ndarray,
    starts: np.ndarray,
    ends: np.ndarray,
    max_len: int = 5000,
) -> Tuple[np.ndarray, np.ndarray]:
    """按坐标切出窗口编码矩阵 (N, max_len) 与真实长度 (N,)；填充位编码为 4（N）。"""
    n = len(contig_ids)
    codes = np.full((n, max_len), 4, dtype=np.uint8)
    lengths = np.zeros(n, dtype=np.int32)

    rows_by_contig: Dict[str, List[int]] = {}
    for i, cid in enumerate(contig_ids):
        rows_by_contig.setdefault(str(cid), []).append(i)

    for cid, seq in iter_fasta(Path(fasta_path)):
        rows = rows_by_contig.get(cid)
        if not rows:
            continue
        enc = encode_dna(seq)
        for i in rows:
            s = int(starts[i])
            e = min(int(ends[i]), s + max_len)
            seg = enc[s:e]
            codes[i, : len(seg)] = seg
            lengths[i] = len(seg)
    return codes, lengths


def reverse_complement_codes(codes: np.ndarray, lengths: np.ndarray) -> np.ndarray:
    """对填充编码矩阵执行逐行反向互补（仅翻转有效长度部分）。"""
    comp = np.array([3, 2, 1, 0, 4], dtype=np.uint8)
    out = np.full_like(codes, 4)
    for i in range(codes.shape[0]):
        L = int(lengths[i])
        if L > 0:
            out[i, :L] = comp[codes[i, :L][::-1]]
    return out

