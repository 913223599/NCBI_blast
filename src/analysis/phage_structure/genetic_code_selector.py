# -*- coding: utf-8 -*-
"""
噬菌体遗传密码表自动选择器 (GeneticCodeSelector)

职责：
1. 按翻译表 (11 / 4) 预先拆筛 Pyrodigal 元基因组模型 bin，彻底消除 Table 4/11 混用告警；
2. 针对标准 Table 11、柔膜菌重编码 Table 4 (UGA->Trp) 与止密码重编码 Table 15 (UAG->Gln)
   自动评估编码密度、平均蛋白尺度及截断片段收敛性，识别真实重编码噬菌体并防止标准基因组误漂移。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple, cast

try:
    import pyrodigal
except ImportError:
    pyrodigal = None  # type: ignore[assignment]

from .thresholds import DEFAULT_THRESHOLDS, GeneticCodeThresholds

logger = logging.getLogger(__name__)

SUPPORTED_GENETIC_CODES = (11, 4, 15)

# 预按翻译表拆分内置元基因组训练模型，防止 meta=True 时用 table=11 翻译 table=4 模型触发警告
METAGENOMIC_BINS_11 = (
    pyrodigal.MetagenomicBins(
        [b for b in pyrodigal.METAGENOMIC_BINS if b.training_info.translation_table == 11]
    )
    if pyrodigal is not None
    else None
)
METAGENOMIC_BINS_4 = (
    pyrodigal.MetagenomicBins(
        [b for b in pyrodigal.METAGENOMIC_BINS if b.training_info.translation_table == 4]
    )
    if pyrodigal is not None
    else None
)


def _evaluate_table_stats(
    seq_bytes: bytes,
    train_bytes: bytes,
    genetic_code: int,
    *,
    min_orf_bp: int = 75,
) -> Dict[str, Any]:
    if pyrodigal is None:
        raise RuntimeError("pyrodigal 未安装，无法评估遗传密码子统计")
    gf = pyrodigal.GeneFinder(meta=False, mask=True)
    gf.train(train_bytes, translation_table=cast(Any, genetic_code))
    genes = gf.find_genes(seq_bytes)
    n_bp = max(1, len(seq_bytes))

    valid_orfs = [g for g in genes if (g.end - g.begin + 1) >= min_orf_bp]
    covered = bytearray(n_bp)
    for g in valid_orfs:
        s0 = max(0, g.begin - 1)
        e0 = min(n_bp, g.end)
        if e0 > s0:
            covered[s0:e0] = b"\x01" * (e0 - s0)

    cov = sum(covered) / n_bp
    mean_aa = (sum((g.end - g.begin + 1) // 3 for g in valid_orfs) / len(valid_orfs)) if valid_orfs else 0.0
    return {
        "orfs": len(valid_orfs),
        "cov": round(cov, 4),
        "mean_aa": round(mean_aa, 1),
    }


def select_optimal_genetic_code(
    dna_seq: str,
    *,
    default_code: int = 11,
    min_seq_bp: Optional[int] = None,
    thresholds: GeneticCodeThresholds = DEFAULT_THRESHOLDS.genetic_code,
) -> Tuple[int, bool, Dict[int, Dict[str, Any]]]:
    """
    评估 11 / 4 / 15 号遗传密码表下的 ORF 编码完整性并自动返回最优密码表。
    返回: (selected_code, auto_switched, stats_by_code)
    """
    seq = (dna_seq or "").strip().upper()
    n = len(seq)
    eff_min_bp = thresholds.min_seq_bp if min_seq_bp is None else min_seq_bp
    if n < eff_min_bp:
        return default_code, False, {}

    seq_bytes = seq.encode("ascii", errors="replace")
    # Pyrodigal 单基因组训练要求长度 >= 100 kb 才完全收敛并静默长度告警，短序列经首尾拼接重复满足训练窗口
    train_win = thresholds.train_window_bp
    train_bytes = seq_bytes * ((train_win // n) + 1) if n < train_win else seq_bytes

    stats: Dict[int, Dict[str, Any]] = {}
    for code in SUPPORTED_GENETIC_CODES:
        try:
            stats[code] = _evaluate_table_stats(
                seq_bytes,
                train_bytes,
                code,
                min_orf_bp=thresholds.min_orf_bp,
            )
        except Exception as _exc:
            logger.debug("遗传密码表 %s 预估跳过: %s", code, _exc)
            continue

    s11 = stats.get(11)
    if not s11:
        return default_code, False, stats

    best_code = default_code
    best_score = s11["cov"] * s11["mean_aa"]

    for alt in (4, 15):
        sa = stats.get(alt)
        if not sa or sa["orfs"] == 0:
            continue
        cov_gain = sa["cov"] - s11["cov"]
        len_ratio = sa["mean_aa"] / max(1.0, s11["mean_aa"])
        # 严格复合判据：必须观察到 Table 11 下显著编码断裂/低覆盖率，且替代密码表大幅恢复 ORF 平均长度并减少碎裂数
        has_truncation_evidence = (
            s11["cov"] < thresholds.low_cov_11_ceiling and cov_gain >= thresholds.min_cov_gain_with_low_11
        ) or (cov_gain >= thresholds.min_cov_gain_standalone)
        if has_truncation_evidence and len_ratio >= thresholds.min_mean_aa_ratio and sa["orfs"] < s11["orfs"]:
            sc_val = sa["cov"] * sa["mean_aa"]
            if sc_val > best_score:
                best_code = alt
                best_score = sc_val

    return best_code, (best_code != default_code), stats
