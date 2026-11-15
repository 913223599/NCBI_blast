# -*- coding: utf-8 -*-
"""
阶段 1 蛋白高阶序列与编码质量特征模块：
1. 7 类理化等价分组 Conjoint Triad（7x7 简化二肽 49 维 + 7x7x7 简化三肽 343 维）；
2. 单 ORF 紧凑生物物理三肽（3x3x3 = 27 维：疏水/极性/带电）；
3. Pyrodigal 免费编码潜能/RBS/截断属性编码（11 维）与窗口统计汇总；
4. 向量化超快六框无终止子编码区（6-frame ORF）扫描，修复短片段与无预测基因盲区。
"""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

import numpy as np

# 7 类 Shen (2007) Conjoint Triad 理化聚簇
_CT7_GROUPS = (
    "AGV",   # 0: 小脂肪族/非极性
    "ILFP",  # 1: 强疏水脂肪族与芳环脯氨酸
    "YMTS",  # 2: 中等极性羟基/含硫疏水
    "HNQW",  # 3: 酰胺/杂环极性
    "RK",    # 4: 正电碱性
    "DE",    # 5: 负电酸性
    "C",     # 6: 二硫键半胱氨酸
)
_CT7_LUT = np.full(256, -1, dtype=np.int16)
for _gid, _aas in enumerate(_CT7_GROUPS):
    for _aa in _aas:
        _CT7_LUT[ord(_aa)] = _gid

# 3 类紧凑三肽分组（单 ORF 27 维低方差表示，覆盖全部 20 种标准氨基酸）
_TRI3_GROUPS = (
    "AVILMFYW",  # 0: 疏水核心
    "STNQCGP",   # 1: 极性/中性结构残基
    "DEKRH",     # 2: 带电残基
)
_TRI3_LUT = np.full(256, -1, dtype=np.int16)
for _gid, _aas in enumerate(_TRI3_GROUPS):
    for _aa in _aas:
        _TRI3_LUT[ord(_aa)] = _gid

DIPEPTIDE_7X7_DIM = 49
TRIPEPTIDE_7X7X7_DIM = 343
TRIPEPTIDE_3X3X3_DIM = 27
PYRODIGAL_ORF_ATTR_DIM = 11
STAGE1_ORF_EXTRA_DIM = PYRODIGAL_ORF_ATTR_DIM + DIPEPTIDE_7X7_DIM + TRIPEPTIDE_3X3X3_DIM  # 87

PYRODIGAL_WINDOW_AGG_DIM = 12
PEPTIDE_BIOPHYS_SUMMARY_DIM = 10
STAGE1_WINDOW_EXTRA_DIM = (
    DIPEPTIDE_7X7_DIM
    + PYRODIGAL_WINDOW_AGG_DIM
    + PEPTIDE_BIOPHYS_SUMMARY_DIM
)  # 71 (窗级保留 49 二肽 + 12 Pyrodigal + 10 理化熵汇总；三肽由单 ORF 117d 流建模以防窗级稀疏过拟合)

STAGE1_WINDOW_EXTRA_NAMES: List[str] = (
    [f"dp7_{i}{j}" for i in range(7) for j in range(7)]
    + [
        "pyro_mean_cscore",
        "pyro_max_cscore",
        "pyro_min_cscore",
        "pyro_mean_score",
        "pyro_mean_rscore",
        "pyro_mean_sscore",
        "pyro_mean_tscore",
        "pyro_partial_frac",
        "pyro_rbs_frac",
        "pyro_atg_frac",
        "pyro_overlap_gene_frac",
        "pyro_fallback_6frame_frac",
    ]
    + [
        "pep_aa_entropy",
        "pep_dp_entropy",
        "pep_ct_entropy",
        "pep_dp_hydro_pair",
        "pep_dp_same_charge_pair",
        "pep_dp_opp_charge_pair",
        "pep_dp_polar_pair",
        "pep_dp_cys_pair",
        "orf_len_cv",
        "fb_6frame_coding_frac",
    ]
)

# 6-frame 向量化碱基 LUT（A=0, C=1, G=2, T/U=3, N/其他=4）
_BASE_LUT = np.full(256, 4, dtype=np.uint8)
_BASE_LUT[ord("A")] = 0
_BASE_LUT[ord("C")] = 1
_BASE_LUT[ord("G")] = 2
_BASE_LUT[ord("T")] = 3
_BASE_LUT[ord("U")] = 3
_RC_CODE_MAP = np.array([3, 2, 1, 0, 4], dtype=np.uint8)

# 三联体编码 idx = b0*25 + b1*5 + b2 (0..124)，标注终止子与非法 N 密码子
_CODON_TABLE_125: List[str] = ["*"] * 125
_STD_CODE = {
    "TTT": "F", "TTC": "F", "TTA": "L", "TTG": "L",
    "TCT": "S", "TCC": "S", "TCA": "S", "TCG": "S",
    "TAT": "Y", "TAC": "Y", "TAA": "*", "TAG": "*",
    "TGT": "C", "TGC": "C", "TGA": "*", "TGG": "W",
    "CTT": "L", "CTC": "L", "CTA": "L", "CTG": "L",
    "CCT": "P", "CCC": "P", "CCA": "P", "CCG": "P",
    "CAT": "H", "CAC": "H", "CAA": "Q", "CAG": "Q",
    "CGT": "R", "CGC": "R", "CGA": "R", "CGG": "R",
    "ATT": "I", "ATC": "I", "ATA": "I", "ATG": "M",
    "ACT": "T", "ACC": "T", "ACA": "T", "ACG": "T",
    "AAT": "N", "AAC": "N", "AAA": "K", "AAG": "K",
    "AGT": "S", "AGC": "S", "AGA": "R", "AGG": "R",
    "GTT": "V", "GTC": "V", "GTA": "V", "GTG": "V",
    "GCT": "A", "GCC": "A", "GCA": "A", "GCG": "A",
    "GAT": "D", "GAC": "D", "GAA": "E", "GAG": "E",
    "GGT": "G", "GGC": "G", "GGA": "G", "GGG": "G",
}
_BASE_INT = {"A": 0, "C": 1, "G": 2, "T": 3}
_IS_STOP_OR_BAD_125 = np.ones(125, dtype=bool)
for _codon, _aa_ch in _STD_CODE.items():
    _cidx = _BASE_INT[_codon[0]] * 25 + _BASE_INT[_codon[1]] * 5 + _BASE_INT[_codon[2]]
    _CODON_TABLE_125[_cidx] = _aa_ch
    if _aa_ch != "*":
        _IS_STOP_OR_BAD_125[_cidx] = False


def _aa_to_group_idx(aa_seq: str, lut: np.ndarray) -> np.ndarray:
    if not aa_seq:
        return np.empty(0, dtype=np.int16)
    arr = np.frombuffer(aa_seq.upper().encode("ascii", errors="replace"), dtype=np.uint8)
    return lut[arr]


def encode_peptide_7x7_dipeptide(aa_seq: str) -> np.ndarray:
    """计算 7 类理化分组简化二肽归一化频率（49 维）。"""
    out = np.zeros(DIPEPTIDE_7X7_DIM, dtype=np.float32)
    g = _aa_to_group_idx(aa_seq, _CT7_LUT)
    if g.size < 2:
        return out
    valid = (g[:-1] >= 0) & (g[1:] >= 0)
    if not np.any(valid):
        return out
    idx2 = g[:-1][valid].astype(np.int32) * 7 + g[1:][valid].astype(np.int32)
    counts = np.bincount(idx2, minlength=DIPEPTIDE_7X7_DIM).astype(np.float32)
    return counts / float(idx2.size)


def encode_peptide_7x7x7_triad(aa_seq: str) -> np.ndarray:
    """计算 7 类 Conjoint Triad 三肽归一化频率（343 维）。"""
    out = np.zeros(TRIPEPTIDE_7X7X7_DIM, dtype=np.float32)
    g = _aa_to_group_idx(aa_seq, _CT7_LUT)
    if g.size < 3:
        return out
    valid = (g[:-2] >= 0) & (g[1:-1] >= 0) & (g[2:] >= 0)
    if not np.any(valid):
        return out
    idx3 = (
        g[:-2][valid].astype(np.int32) * 49
        + g[1:-1][valid].astype(np.int32) * 7
        + g[2:][valid].astype(np.int32)
    )
    counts = np.bincount(idx3, minlength=TRIPEPTIDE_7X7X7_DIM).astype(np.float32)
    return counts / float(idx3.size)


def encode_peptide_3x3x3_triad(aa_seq: str) -> np.ndarray:
    """计算 3 类理化三肽紧凑归一化频率（27 维，适于单条短 ORF 防止稀疏过拟合）。"""
    out = np.zeros(TRIPEPTIDE_3X3X3_DIM, dtype=np.float32)
    g = _aa_to_group_idx(aa_seq, _TRI3_LUT)
    if g.size < 3:
        return out
    valid = (g[:-2] >= 0) & (g[1:-1] >= 0) & (g[2:] >= 0)
    if not np.any(valid):
        return out
    idx3 = (
        g[:-2][valid].astype(np.int32) * 9
        + g[1:-1][valid].astype(np.int32) * 3
        + g[2:][valid].astype(np.int32)
    )
    counts = np.bincount(idx3, minlength=TRIPEPTIDE_3X3X3_DIM).astype(np.float32)
    return counts / float(idx3.size)


def encode_pyrodigal_gene_attrs(
    gene: Optional[Any],
    aa_len: int,
    *,
    is_fallback: float = 0.0,
) -> np.ndarray:
    """提取 Pyrodigal 免费编码质量、RBS、起始密码子与边界截断向量（11 维）。"""
    out = np.zeros(PYRODIGAL_ORF_ATTR_DIM, dtype=np.float32)
    if gene is None or is_fallback >= 0.5:
        out[5] = 1.0  # partial_begin
        out[6] = 1.0  # partial_end
        out[9] = 1.0  # is_fallback_6frame
        out[10] = float(np.log1p(max(0, aa_len)) / 7.0)
        return out

    cscore = float(getattr(gene, "cscore", 0.0) or 0.0)
    score = float(getattr(gene, "score", 0.0) or 0.0)
    rscore = float(getattr(gene, "rscore", 0.0) or 0.0)
    sscore = float(getattr(gene, "sscore", 0.0) or 0.0)
    tscore = float(getattr(gene, "tscore", 0.0) or 0.0)
    p_beg = 1.0 if bool(getattr(gene, "partial_begin", False)) else 0.0
    p_end = 1.0 if bool(getattr(gene, "partial_end", False)) else 0.0
    rbs = getattr(gene, "rbs_motif", None)
    has_rbs = 1.0 if (rbs is not None and str(rbs).strip() not in ("", "None")) else 0.0
    start_t = str(getattr(gene, "start_type", "") or "").upper()
    is_atg = 1.0 if start_t == "ATG" else 0.0

    out[0] = float(np.clip(cscore / 100.0, -5.0, 20.0))
    out[1] = float(np.clip(score / 100.0, -5.0, 20.0))
    out[2] = float(np.clip(rscore / 20.0, -5.0, 10.0))
    out[3] = float(np.clip(sscore / 20.0, -5.0, 10.0))
    out[4] = float(np.clip(tscore / 20.0, -5.0, 10.0))
    out[5] = p_beg
    out[6] = p_end
    out[7] = has_rbs
    out[8] = is_atg
    out[9] = float(is_fallback)
    out[10] = float(np.log1p(max(0, aa_len)) / 7.0)
    return out


def encode_orf_peptide_extra(aa_seq: str, pyro_attrs: Optional[np.ndarray] = None) -> np.ndarray:
    """组合单条 ORF 的 87 维阶段 1 特征（11 Pyrodigal + 49 dp7 + 27 ct3x3x3）。"""
    out = np.zeros(STAGE1_ORF_EXTRA_DIM, dtype=np.float32)
    if pyro_attrs is not None:
        out[:PYRODIGAL_ORF_ATTR_DIM] = pyro_attrs
    else:
        out[:PYRODIGAL_ORF_ATTR_DIM] = encode_pyrodigal_gene_attrs(None, len(aa_seq), is_fallback=1.0)
    out[PYRODIGAL_ORF_ATTR_DIM:PYRODIGAL_ORF_ATTR_DIM + DIPEPTIDE_7X7_DIM] = encode_peptide_7x7_dipeptide(aa_seq)
    out[PYRODIGAL_ORF_ATTR_DIM + DIPEPTIDE_7X7_DIM:] = encode_peptide_3x3x3_triad(aa_seq)
    return out


def _longest_stop_free_run_in_codes(codes: np.ndarray) -> Tuple[int, int, int, np.ndarray]:
    """在单链碱基编码序列上扫描 3 个阅读框的最长无终止密码子连续区段，返回 (max_codons, frame, c_start, codon_ids)。"""
    n = codes.size
    if n < 6:
        return 0, 0, 0, np.empty(0, dtype=np.int32)
    codon_all = (
        codes[:-2].astype(np.int32) * 25
        + codes[1:-1].astype(np.int32) * 5
        + codes[2:].astype(np.int32)
    )
    best_len = 0
    best_frame = 0
    best_cs = 0
    best_cids = np.empty(0, dtype=np.int32)

    for frame in (0, 1, 2):
        sub_c = codon_all[frame::3]
        if sub_c.size == 0:
            continue
        stops = _IS_STOP_OR_BAD_125[sub_c]
        stop_pos = np.flatnonzero(stops)
        if stop_pos.size == 0:
            run_len = int(sub_c.size)
            run_start = 0
        else:
            bounds = np.empty(stop_pos.size + 2, dtype=np.int64)
            bounds[0] = -1
            bounds[1:-1] = stop_pos
            bounds[-1] = sub_c.size
            diffs = np.diff(bounds) - 1
            argmax = int(np.argmax(diffs))
            run_len = int(diffs[argmax])
            run_start = int(bounds[argmax] + 1)
        if run_len > best_len:
            best_len = run_len
            best_frame = frame
            best_cs = run_start
            best_cids = sub_c[run_start:run_start + run_len]
    return best_len, best_frame, best_cs, best_cids


def compute_best_6frame_coding_fraction(win_seq: str) -> float:
    """超快向量化计算窗口六框中最长无终止密码子连续读框占总长比例（约数十微秒/窗）。"""
    n = len(win_seq)
    if n < 15:
        return 0.0
    arr = np.frombuffer(win_seq.upper().encode("ascii", errors="replace"), dtype=np.uint8)
    codes = _BASE_LUT[arr]
    rc_codes = _RC_CODE_MAP[codes[::-1]]
    fwd_len, _, _, _ = _longest_stop_free_run_in_codes(codes)
    rev_len, _, _, _ = _longest_stop_free_run_in_codes(rc_codes)
    return float(min(1.0, max(fwd_len, rev_len) * 3.0 / float(n)))


def find_best_6frame_orf(
    win_seq: str,
    *,
    min_aa: int = 20,
) -> Optional[Tuple[int, int, int, str, float]]:
    """
    在 Pyrodigal 未检出完整 ORF 的短片/边界窗中扫描 6 个阅读框，
    返回最长无终止编码段：(rel_start, rel_end, strand, aa_seq, coding_frac)。
    """
    n = len(win_seq)
    if n < max(15, min_aa * 3):
        return None
    arr = np.frombuffer(win_seq.upper().encode("ascii", errors="replace"), dtype=np.uint8)
    codes = _BASE_LUT[arr]
    rc_codes = _RC_CODE_MAP[codes[::-1]]

    f_len, f_frame, f_cs, f_cids = _longest_stop_free_run_in_codes(codes)
    r_len, r_frame, r_cs, r_cids = _longest_stop_free_run_in_codes(rc_codes)

    if max(f_len, r_len) < min_aa:
        return None
    if f_len >= r_len:
        rs = f_frame + f_cs * 3
        re_ = rs + f_len * 3
        aa_seq = "".join(_CODON_TABLE_125[int(cid)] for cid in f_cids.tolist())
        return rs, min(n, re_), 1, aa_seq, float(min(1.0, f_len * 3.0 / float(n)))

    rc_s = r_frame + r_cs * 3
    rc_e = rc_s + r_len * 3
    rs = max(0, n - rc_e)
    re_ = min(n, n - rc_s)
    aa_seq = "".join(_CODON_TABLE_125[int(cid)] for cid in r_cids.tolist())
    return rs, re_, -1, aa_seq, float(min(1.0, r_len * 3.0 / float(n)))


def compute_biophysical_summary(
    aa_22: np.ndarray,
    dp49: np.ndarray,
    ct343: np.ndarray,
    orf_lengths: List[int],
    coding_frac_6frame: float,
) -> np.ndarray:
    """计算窗口级 10 维蛋白语义熵与二肽物理聚集统计。"""
    out = np.zeros(PEPTIDE_BIOPHYS_SUMMARY_DIM, dtype=np.float32)

    def _norm_entropy(p: np.ndarray) -> float:
        pos = p[p > 1e-9]
        if pos.size == 0:
            return 0.0
        s = float(pos.sum())
        if s <= 0.0:
            return 0.0
        q = pos / s
        ent = -float(np.sum(q * np.log(q)))
        denom = float(np.log(max(2, len(p))))
        return float(ent / denom)

    out[0] = _norm_entropy(aa_22[:20])
    out[1] = _norm_entropy(dp49)
    out[2] = _norm_entropy(ct343)

    if dp49.size == 49:
        mat = dp49.reshape(7, 7)
        # 疏水核心对（组 0,1 x 组 0,1）
        out[3] = float(mat[0:2, 0:2].sum())
        # 同号电荷对（4-4 与 5-5）
        out[4] = float(mat[4, 4] + mat[5, 5])
        # 盐桥异号电荷对（4-5 与 5-4）
        out[5] = float(mat[4, 5] + mat[5, 4])
        # 极性富含对（组 2,3 x 组 2,3）
        out[6] = float(mat[2:4, 2:4].sum())
        # 半胱氨酸含硫二肽（第 6 行或第 6 列）
        out[7] = float(mat[6, :].sum() + mat[:, 6].sum() - mat[6, 6])

    if len(orf_lengths) >= 2:
        arr_l = np.asarray(orf_lengths, dtype=np.float64)
        mu = float(arr_l.mean())
        if mu > 1e-6:
            out[8] = float(arr_l.std() / mu)

    out[9] = float(coding_frac_6frame)
    return out

