# -*- coding: utf-8 -*-
"""
fast_matcher.py - 极速氨基酸序列相似度比对与 K-mer 剪枝加速器
基于整型编码 K-mer 集合过滤、长度动态剪枝与 C 扩展 PairwiseAligner 对齐，全面释放 CPU 多核算力。
"""
from typing import Set, Optional, Tuple, Dict
import functools
import threading
from Bio.Align import PairwiseAligner

# 标准 20 种氨基酸整型映射表 (0 ~ 20)
_AA_MAP: Dict[str, int] = {
    'A': 0, 'C': 1, 'D': 2, 'E': 3, 'F': 4,
    'G': 5, 'H': 6, 'I': 7, 'K': 8, 'L': 9,
    'M': 10, 'N': 11, 'P': 12, 'Q': 13, 'R': 14,
    'S': 15, 'T': 16, 'V': 17, 'W': 18, 'Y': 19,
    'X': 20, '*': 20, 'U': 20
}

# 线程局部存储，确保各工作线程独立复用 PairwiseAligner 实例（免加锁，C 扩展极速对齐）
_THREAD_LOCAL = threading.local()


def get_thread_aligner() -> PairwiseAligner:
    """获取当前线程绑定的 PairwiseAligner 单例实例"""
    if not hasattr(_THREAD_LOCAL, "aligner"):
        aligner = PairwiseAligner()
        aligner.mode = 'global'
        aligner.match_score = 1.0
        aligner.mismatch_score = 0.0
        aligner.open_gap_score = -1.0
        aligner.extend_gap_score = -0.5
        _THREAD_LOCAL.aligner = aligner
    return _THREAD_LOCAL.aligner


def get_kmers(seq: str, k: int = 3) -> Set[int]:
    """
    生成序列的整型编码 k-mer 集合 (0 ~ 8000)
    采用整数运算替代字符串切片，大幅减少内存分配与 GC 压力
    """
    if not seq or len(seq) < k:
        return set()

    upper_seq = seq.upper()
    kmers: Set[int] = set()
    val = 0
    # 预填充前 k-1 个字符
    for i in range(k - 1):
        c_code = _AA_MAP.get(upper_seq[i], 20)
        val = val * 21 + c_code

    mod = 21 ** (k - 1)
    for i in range(k - 1, len(upper_seq)):
        c_code = _AA_MAP.get(upper_seq[i], 20)
        val = (val % mod) * 21 + c_code
        kmers.add(val)

    return kmers


@functools.lru_cache(maxsize=32768)
def _cached_align_score(seq1: str, seq2: str) -> float:
    """带 LRU 记忆化缓存的 C 扩展全局对齐得分"""
    aligner = get_thread_aligner()
    try:
        score = aligner.score(seq1, seq2)
        return float(score)
    except Exception:
        # 兜底：快速逐字符比对
        min_l = min(len(seq1), len(seq2))
        matches = sum(1 for a, b in zip(seq1[:min_l], seq2[:min_l]) if a == b)
        return float(matches)


def fast_seq_identity(
    seq1: str,
    seq2: str,
    ident_thresh: float = 0.5,
    cov_thresh: float = 0.5,
    kmers1: Optional[Set[int]] = None,
    kmers2: Optional[Set[int]] = None
) -> float:
    """
    极速计算两条氨基酸序列的一致性 (0.0 ~ 1.0)
    具备 4 级提前退出与剪枝优化：
    1. 长度覆盖度硬剪枝 (O(1))
    2. 3-mer Jaccard 理论下限剪枝 (整型位集合操作)
    3. 同长序列向量化直接比对
    4. C-扩展 PairwiseAligner 全局比对 + 线程局部实例复用
    """
    if not seq1 or not seq2:
        return 0.0

    if seq1 == seq2:
        return 1.0

    len1 = len(seq1)
    len2 = len(seq2)
    min_len = min(len1, len2)
    max_len = max(len1, len2)

    # 1. 长度覆盖度剪枝
    if min_len / max_len < cov_thresh:
        return 0.0

    # 2. K-mer (3-mer) 共有度理论下限剪枝
    if kmers1 is None:
        kmers1 = get_kmers(seq1, 3)
    if kmers2 is None:
        kmers2 = get_kmers(seq2, 3)

    if kmers1 and kmers2:
        intersection_cnt = len(kmers1 & kmers2)
        min_kmers = min(len(kmers1), len(kmers2))
        if min_kmers > 0:
            kmer_ratio = intersection_cnt / min_kmers
            # 若共有 3-mer 的比例低于 阈值 * 0.35，理论上无法达到目标同源度
            kmer_cutoff = max(0.04, ident_thresh * 0.35)
            if kmer_ratio < kmer_cutoff:
                return 0.0

    # 3. 极短序列或等长序列直接比对加速
    if len1 == len2:
        matches = sum(1 for a, b in zip(seq1, seq2) if a == b)
        ratio = matches / len1
        if ratio >= ident_thresh:
            return ratio
        if ratio < ident_thresh * 0.7:
            # 极大差异直接退出
            return 0.0

    if max_len <= 15:
        matches = sum(1 for a, b in zip(seq1, seq2) if a == b)
        return matches / max_len

    # 4. 使用 C 扩展 PairwiseAligner 计算全局对齐得分
    score = _cached_align_score(seq1, seq2)
    identity = max(0.0, min(1.0, score / max_len))
    return identity if identity >= ident_thresh else 0.0
