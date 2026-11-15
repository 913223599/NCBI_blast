# -*- coding: utf-8 -*-
"""
原始 DNA 窗口高知识丰富度特征提取器（v2，185 维，Expert A / Student 共用）

设计原则（防"注释来源捷径"泄露）：
- 训练、验证与推理一律只从原始碱基出发，统一经 Pyrodigal (meta=True) 重新预测基因，
  绝不直接混用 GenBank 与 PGAP 的异源注释，保证分布同源。

特征组成（共 185 维 = FEATURE_NAMES）：
1. 136 维反向互补规范化 4-mer 频率；
2. 碱基组成 (3)：GC、GC skew、N 比例；
3. 宿主上下文偏离 (4)：相对 contig GC 差值/绝对差、4-mer 余弦距离、是否无上下文标志；
4. 基因结构统计 (9)：基因密度、编码密度、平均/最大基因长度、短基因占比、链切换率、
   最长同向链占比、优势链占比、平均基因间隔；
5. 窗口长度对数 (1)；
6. 密码子三核苷酸位置偏倚 (4)：GC1、GC2、GC3 及 GC3 - (GC1+GC2)/2；
7. 窗口蛋白全局氨基酸组成与理化特征 (22)：20 种标准氨基酸频率 + 疏水/带电残基比例；
8. 左右 5 kb 邻域边界阶跃梯度 (6)：左右邻域与本窗的 4-mer 距离、GC 差值、基因密度差值。
"""
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ...utils.phage_dataset.preprocessor import CANONICAL_4MER_NAMES, compute_canonical_4mer_freq
from .peptide_features import (
    DIPEPTIDE_7X7_DIM,
    PYRODIGAL_WINDOW_AGG_DIM,
    STAGE1_WINDOW_EXTRA_DIM,
    STAGE1_WINDOW_EXTRA_NAMES,
    compute_best_6frame_coding_fraction,
    compute_biophysical_summary,
    encode_peptide_7x7_dipeptide,
    encode_peptide_7x7x7_triad,
    encode_pyrodigal_gene_attrs,
    find_best_6frame_orf,
)

GeneTuple = Tuple[int, int, int]  # (0-based start, end exclusive, strand)
# (start, end, strand, aa_22_vec, g1_cnt, c1_cnt, n1_cnt, g2_cnt, c2_cnt, n2_cnt, g3_cnt, c3_cnt, n3_cnt)
RichGeneRecord = Tuple[int, int, int, np.ndarray, int, int, int, int, int, int, int, int, int]
# Stage 1 在 RichGeneRecord 基础上附带：(dp49, ct343, pyro_attrs_11)
Stage1GeneRecord = Tuple[
    int, int, int, np.ndarray, int, int, int, int, int, int, int, int, int,
    np.ndarray, np.ndarray, np.ndarray,
]

SUB_BINS = 25  # 每个 5kb 窗口划分为 25 个子块（200 bp 粒度）用于精细边界定位

_AA_ALPHABET = "ACDEFGHIKLMNPQRSTVWY"
_AA_LUT = np.full(256, -1, dtype=np.int16)
for _i, _aa in enumerate(_AA_ALPHABET):
    _AA_LUT[ord(_aa)] = _i
_HYDROPHOBIC_CODES = {ord(ch) for ch in "AVILMFYW"}
_CHARGED_CODES = {ord(ch) for ch in "DEKRH"}

_COMPOSITION_NAMES = ["gc", "gc_skew", "n_frac"]
_CONTEXT_NAMES = ["ctx_gc_diff", "ctx_gc_absdiff", "ctx_kmer_cosdist", "ctx_is_self"]
_GENE_NAMES = [
    "gene_per_kb",
    "coding_density",
    "mean_gene_len",
    "max_gene_len",
    "short_gene_frac",
    "strand_switch_rate",
    "max_same_strand_run_frac",
    "dominant_strand_frac",
    "mean_intergenic_gap",
]
_CODON_NAMES = ["codon_gc1", "codon_gc2", "codon_gc3", "codon_gc3_bias"]
_AA_NAMES = [f"aa_{aa}" for aa in _AA_ALPHABET] + ["aa_hydrophobic", "aa_charged"]
_FLANK_NAMES = [
    "flank_l_kmer_cosdist",
    "flank_r_kmer_cosdist",
    "flank_l_gc_diff",
    "flank_r_gc_diff",
    "flank_l_gene_diff",
    "flank_r_gene_diff",
]

FEATURE_NAMES: List[str] = (
    [f"k4_{n}" for n in CANONICAL_4MER_NAMES]
    + _COMPOSITION_NAMES
    + _CONTEXT_NAMES
    + _GENE_NAMES
    + ["log10_win_len"]
    + _CODON_NAMES
    + _AA_NAMES
    + _FLANK_NAMES
)
FEATURE_NAMES_STAGE1: List[str] = FEATURE_NAMES + STAGE1_WINDOW_EXTRA_NAMES
_AA_SLICE_START: int = FEATURE_NAMES.index("aa_A")
_AA_SLICE_END: int = _AA_SLICE_START + 22


def get_feature_names(feature_profile: str = "v4") -> List[str]:
    """按特征版本配置返回对应窗口特征名称列表。"""
    if feature_profile.lower() in ("stage1", "v5_stage1"):
        return FEATURE_NAMES_STAGE1
    return FEATURE_NAMES

_GENE_FINDER: Optional[Any] = None


def _get_gene_finder() -> Any:
    """进程内惰性初始化 Pyrodigal meta 模式基因预测器。"""
    global _GENE_FINDER
    if _GENE_FINDER is None:
        import pyrodigal

        _GENE_FINDER = pyrodigal.GeneFinder(meta=True, mask=True)
    return _GENE_FINDER


def predict_genes(seq: str) -> List[GeneTuple]:
    """对整条序列执行 Pyrodigal meta 模式基因预测，返回 0-based 半开区间坐标。"""
    if len(seq) < 100:
        return []
    finder = _get_gene_finder()
    genes = finder.find_genes(seq.encode("ascii", errors="replace"))
    return [(int(g.begin) - 1, int(g.end), int(g.strand)) for g in genes]


def _encode_protein_22(aa_seq: str) -> np.ndarray:
    out = np.zeros(22, dtype=np.float32)
    if not aa_seq:
        return out
    arr = np.frombuffer(aa_seq.encode("ascii", errors="replace"), dtype=np.uint8)
    idx = _AA_LUT[arr]
    valid = idx[idx >= 0]
    n = max(1, len(aa_seq))
    if valid.size > 0:
        out[:20] = np.bincount(valid, minlength=20).astype(np.float32) / float(n)
    hydro = sum(1 for b in arr.tolist() if b in _HYDROPHOBIC_CODES)
    charged = sum(1 for b in arr.tolist() if b in _CHARGED_CODES)
    out[20] = hydro / float(n)
    out[21] = charged / float(n)
    return out


def _codon_gc_counts(cds_dna: str, strand: int) -> Tuple[int, int, int, int, int, int, int, int, int]:
    """按编码链方向统计密码子 1/2/3 位的 G/C 与有效碱基计数。"""
    if len(cds_dna) < 3:
        return (0,) * 9
    if strand < 0:
        comp = cds_dna.translate(str.maketrans("ACGTNacgtn", "TGCANtgcan"))[::-1]
        s = comp[: (len(comp) // 3) * 3]
    else:
        s = cds_dna[: (len(cds_dna) // 3) * 3]
    res: List[int] = []
    for offset in (0, 1, 2):
        sub = s[offset::3]
        g_c = sub.count("G") + sub.count("C")
        n_v = max(0, len(sub) - sub.count("N"))
        res.extend([g_c, 0, n_v])
    return tuple(res)  # type: ignore[return-value]


def _predict_genes_rich(seq: str) -> List[RichGeneRecord]:
    if len(seq) < 100:
        return []
    finder = _get_gene_finder()
    genes = finder.find_genes(seq.encode("ascii", errors="replace"))
    records: List[RichGeneRecord] = []
    for g in genes:
        s0 = int(g.begin) - 1
        e0 = int(g.end)
        strand = int(g.strand)
        aa_vec = _encode_protein_22(g.translate())
        c_counts = _codon_gc_counts(seq[s0:e0], strand)
        records.append((s0, e0, strand, aa_vec, *c_counts))
    records.sort(key=lambda r: r[0])
    return records


def _predict_genes_rich_stage1(seq: str) -> List[Stage1GeneRecord]:
    if len(seq) < 100:
        return []
    finder = _get_gene_finder()
    genes = finder.find_genes(seq.encode("ascii", errors="replace"))
    records: List[Stage1GeneRecord] = []
    for g in genes:
        s0 = int(g.begin) - 1
        e0 = int(g.end)
        strand = int(g.strand)
        aa_raw = g.translate()
        aa_vec = _encode_protein_22(aa_raw)
        aa_clean = aa_raw.rstrip("*")
        c_counts = _codon_gc_counts(seq[s0:e0], strand)
        dp49 = encode_peptide_7x7_dipeptide(aa_clean)
        ct343 = encode_peptide_7x7x7_triad(aa_clean)
        pyro_attrs = encode_pyrodigal_gene_attrs(g, len(aa_clean), is_fallback=0.0)
        records.append((s0, e0, strand, aa_vec, *c_counts, dp49, ct343, pyro_attrs))
    records.sort(key=lambda r: r[0])
    return records


def _gene_stats(genes: Sequence[Tuple[int, int, int]], win_start: int, win_end: int) -> List[float]:
    """统计与窗口相交（中点落入窗口）的基因结构特征。"""
    win_len = max(1, win_end - win_start)
    in_win = [g for g in genes if win_start <= (g[0] + g[1]) // 2 < win_end]
    if not in_win:
        return [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, float(win_len)]

    in_win = sorted(in_win, key=lambda g: g[0])
    lengths = np.asarray([g[1] - g[0] for g in in_win], dtype=np.float64)
    strands = [g[2] for g in in_win]

    covered = np.zeros(win_len, dtype=bool)
    for s, e, _ in in_win:
        cs = max(0, s - win_start)
        ce = min(win_len, e - win_start)
        if ce > cs:
            covered[cs:ce] = True

    switches = sum(1 for i in range(1, len(strands)) if strands[i] != strands[i - 1])
    max_run = 1
    cur_run = 1
    for i in range(1, len(strands)):
        if strands[i] == strands[i - 1]:
            cur_run += 1
            max_run = max(max_run, cur_run)
        else:
            cur_run = 1
    n_plus = sum(1 for s in strands if s > 0)
    gaps = [max(0, in_win[i][0] - in_win[i - 1][1]) for i in range(1, len(in_win))]

    n = len(in_win)
    return [
        n / (win_len / 1000.0),
        float(covered.mean()),
        float(lengths.mean()),
        float(lengths.max()),
        float(np.mean(lengths < 300)),
        switches / max(1, n - 1),
        max_run / n,
        max(n_plus, n - n_plus) / n,
        float(np.mean(gaps)) if gaps else 0.0,
    ]


def _rich_codon_and_aa_stats(
    rich_genes: Sequence[RichGeneRecord],
    win_start: int,
    win_end: int,
) -> Tuple[List[float], np.ndarray]:
    in_win = [g for g in rich_genes if win_start <= (g[0] + g[1]) // 2 < win_end]
    if not in_win:
        return [0.5, 0.5, 0.5, 0.0], np.zeros(22, dtype=np.float32)

    gc1_s = sum(g[4] for g in in_win)
    n1_s = sum(g[6] for g in in_win)
    gc2_s = sum(g[7] for g in in_win)
    n2_s = sum(g[9] for g in in_win)
    gc3_s = sum(g[10] for g in in_win)
    n3_s = sum(g[12] for g in in_win)

    gc1 = gc1_s / n1_s if n1_s > 0 else 0.5
    gc2 = gc2_s / n2_s if n2_s > 0 else 0.5
    gc3 = gc3_s / n3_s if n3_s > 0 else 0.5
    gc3_bias = gc3 - 0.5 * (gc1 + gc2)

    weights = np.asarray([max(1, g[1] - g[0]) for g in in_win], dtype=np.float32)
    aa_stack = np.stack([g[3] for g in in_win], axis=0)
    aa_avg = np.average(aa_stack, axis=0, weights=weights).astype(np.float32)
    return [gc1, gc2, gc3, gc3_bias], aa_avg


def _flank_summary(
    seq: str,
    flank_s: int,
    flank_e: int,
    simple_genes: Sequence[GeneTuple],
) -> Tuple[Optional[np.ndarray], float, float]:
    """计算左/右邻域 4-mer 单位向量、GC 与基因密度。"""
    flen = flank_e - flank_s
    if flen < 500:
        return None, 0.0, 0.0
    sub = seq[flank_s:flank_e]
    fk = compute_canonical_4mer_freq(sub)
    fn = float(np.linalg.norm(fk)) or 1.0
    fgc = (sub.count("G") + sub.count("C")) / float(flen)
    n_g = sum(1 for g in simple_genes if flank_s <= (g[0] + g[1]) // 2 < flank_e)
    return fk / fn, fgc, n_g / (flen / 1000.0)


def compute_window_features(
    win_seq: str,
    win_start: int,
    win_end: int,
    genes: Sequence[Tuple[int, int, int]],
    ctx_kmer_unit: np.ndarray,
    ctx_gc: float,
    ctx_is_self: bool,
    rich_genes: Optional[Sequence[RichGeneRecord]] = None,
    flank_feats: Optional[Sequence[float]] = None,
) -> np.ndarray:
    """计算单个窗口的完整 185 维特征向量（顺序与 FEATURE_NAMES 一致）。"""
    seq_len = max(1, len(win_seq))
    kmer = compute_canonical_4mer_freq(win_seq)

    g_cnt = win_seq.count("G")
    c_cnt = win_seq.count("C")
    gc = (g_cnt + c_cnt) / seq_len
    gc_skew = (g_cnt - c_cnt) / (g_cnt + c_cnt) if (g_cnt + c_cnt) > 0 else 0.0
    n_frac = win_seq.count("N") / seq_len

    k_norm = float(np.linalg.norm(kmer)) or 1.0
    kmer_unit = kmer / k_norm
    cos_dist = 0.0 if ctx_is_self else max(0.0, 1.0 - float(np.dot(kmer_unit, ctx_kmer_unit)))
    gc_diff = 0.0 if ctx_is_self else gc - ctx_gc

    if rich_genes is not None:
        codon_feats, aa_avg = _rich_codon_and_aa_stats(rich_genes, win_start, win_end)
    else:
        codon_feats, aa_avg = [0.5, 0.5, 0.5, 0.0], np.zeros(22, dtype=np.float32)

    feats = np.empty(len(FEATURE_NAMES), dtype=np.float32)
    feats[:136] = kmer
    tail: List[float] = [
        gc, gc_skew, n_frac,
        gc_diff, abs(gc_diff), cos_dist, 1.0 if ctx_is_self else 0.0,
    ]
    tail.extend(_gene_stats(genes, win_start, win_end))
    tail.append(float(np.log10(seq_len)))
    tail.extend(codon_feats)
    tail.extend(aa_avg.tolist())
    if flank_feats is not None:
        tail.extend(flank_feats)
    else:
        tail.extend([0.0] * len(_FLANK_NAMES))
    feats[136:] = np.asarray(tail, dtype=np.float32)
    return feats


def _overlap_fraction(win_start: int, win_end: int, regions: Sequence[Tuple[int, int]]) -> float:
    win_len = max(1, win_end - win_start)
    covered = 0
    for rs, re_ in regions:
        covered += max(0, min(win_end, re_) - max(win_start, rs))
    return min(1.0, covered / win_len)


def _compute_sub_mask(
    win_start: int,
    win_end: int,
    regions: Sequence[Tuple[int, int]],
    n_bins: int = SUB_BINS,
) -> np.ndarray:
    """将窗口均分为 n_bins 个子区段（5kb 下每块 200bp），计算各块真值覆盖比例。"""
    mask = np.zeros(n_bins, dtype=np.float32)
    if not regions:
        return mask
    wlen = max(1, win_end - win_start)
    for bi in range(n_bins):
        bs = win_start + (wlen * bi) // n_bins
        be = win_start + (wlen * (bi + 1)) // n_bins
        if be > bs:
            mask[bi] = _overlap_fraction(bs, be, regions)
    return mask


def _compute_stage1_window_extra(
    in_win: Sequence[Stage1GeneRecord],
    aa_22_avg: np.ndarray,
    coding_frac_6frame: float,
) -> np.ndarray:
    """计算单个窗口的 Stage 1 额外 71 维特征（49 二肽 + 12 Pyrodigal 质控 + 10 生物物理汇总）。"""
    out = np.zeros(STAGE1_WINDOW_EXTRA_DIM, dtype=np.float32)
    off_pyro = DIPEPTIDE_7X7_DIM
    off_bio = off_pyro + PYRODIGAL_WINDOW_AGG_DIM

    if not in_win:
        out[off_bio:] = compute_biophysical_summary(
            aa_22_avg,
            out[:DIPEPTIDE_7X7_DIM],
            np.empty(0, dtype=np.float32),
            [],
            coding_frac_6frame,
        )
        return out

    lengths = [max(1, g[1] - g[0]) for g in in_win]
    weights = np.asarray(lengths, dtype=np.float32)
    dp_avg = np.average(np.stack([g[13] for g in in_win], axis=0), axis=0, weights=weights).astype(np.float32)
    ct_avg = np.average(np.stack([g[14] for g in in_win], axis=0), axis=0, weights=weights).astype(np.float32)

    attrs = np.stack([g[15] for g in in_win], axis=0)
    cscores = attrs[:, 0]
    scores = attrs[:, 1]
    rscores = attrs[:, 2]
    sscores = attrs[:, 3]
    tscores = attrs[:, 4]
    is_partial = np.maximum(attrs[:, 5], attrs[:, 6])
    has_rbs = attrs[:, 7]
    is_atg = attrs[:, 8]
    is_fb = attrs[:, 9]

    overlap_cnt = 0
    n_g = len(in_win)
    if n_g >= 2:
        for gi in range(n_g):
            has_ov = False
            if gi > 0 and in_win[gi][0] < in_win[gi - 1][1]:
                has_ov = True
            if gi + 1 < n_g and in_win[gi + 1][0] < in_win[gi][1]:
                has_ov = True
            if has_ov:
                overlap_cnt += 1

    pyro_agg = np.array([
        float(cscores.mean()),
        float(cscores.max()),
        float(cscores.min()),
        float(scores.mean()),
        float(rscores.mean()),
        float(sscores.mean()),
        float(tscores.mean()),
        float(is_partial.mean()),
        float(has_rbs.mean()),
        float(is_atg.mean()),
        overlap_cnt / n_g,
        float(is_fb.mean()),
    ], dtype=np.float32)

    out[:off_pyro] = dp_avg
    out[off_pyro:off_bio] = pyro_agg
    out[off_bio:] = compute_biophysical_summary(
        aa_22_avg, dp_avg, ct_avg, lengths, coding_frac_6frame,
    )
    return out


def extract_contig_windows_for_spans(
    contig_id: str,
    seq: str,
    spans: Sequence[Tuple[int, int]],
    *,
    truth_regions: Optional[Sequence[Tuple[int, int]]] = None,
    feature_profile: str = "v4",
    context_win_size: int = 5000,
) -> Dict[str, Any]:
    """按指定窗口区间列表提取特征，支持 v4 (185 维) 与 stage1 (256 维) 两种版本。"""
    seq = seq.upper()
    n = len(seq)
    is_stage1 = feature_profile.lower() in ("stage1", "v5_stage1")
    if is_stage1:
        rich_s1 = _predict_genes_rich_stage1(seq)
        rich_genes: List[RichGeneRecord] = [g[:13] for g in rich_s1]  # type: ignore[misc]
    else:
        rich_s1 = []
        rich_genes = _predict_genes_rich(seq)
    simple_genes: List[GeneTuple] = [(g[0], g[1], g[2]) for g in rich_genes]

    ctx_kmer = compute_canonical_4mer_freq(seq)
    ctx_unit = ctx_kmer / (float(np.linalg.norm(ctx_kmer)) or 1.0)
    ctx_gc = (seq.count("G") + seq.count("C")) / max(1, n)
    regions = list(truth_regions or [])

    feat_dim = len(get_feature_names(feature_profile))
    ctx_is_self = n <= context_win_size
    feats = np.zeros((len(spans), feat_dim), dtype=np.float32)
    overlaps = np.zeros(len(spans), dtype=np.float32)
    sub_masks = np.zeros((len(spans), SUB_BINS), dtype=np.float32)

    for i, (s, e) in enumerate(spans):
        win_sub = seq[s:e]
        flank_vec = [0.0] * len(_FLANK_NAMES)
        if not ctx_is_self:
            wk = compute_canonical_4mer_freq(win_sub)
            wn = float(np.linalg.norm(wk)) or 1.0
            w_unit = wk / wn
            w_gc = (win_sub.count("G") + win_sub.count("C")) / max(1, e - s)
            w_gd = sum(1 for g in simple_genes if s <= (g[0] + g[1]) // 2 < e) / max(0.1, (e - s) / 1000.0)

            lk, lgc, lgd = _flank_summary(seq, max(0, s - 5000), s, simple_genes)
            rk, rgc, rgd = _flank_summary(seq, e, min(n, e + 5000), simple_genes)
            if lk is not None:
                flank_vec[0] = max(0.0, 1.0 - float(np.dot(w_unit, lk)))
                flank_vec[2] = w_gc - lgc
                flank_vec[4] = w_gd - lgd
            if rk is not None:
                flank_vec[1] = max(0.0, 1.0 - float(np.dot(w_unit, rk)))
                flank_vec[3] = w_gc - rgc
                flank_vec[5] = w_gd - rgd

        if not is_stage1:
            feats[i] = compute_window_features(
                win_sub, s, e, simple_genes, ctx_unit, ctx_gc, ctx_is_self,
                rich_genes=rich_genes, flank_feats=flank_vec,
            )
        else:
            in_win_s1 = [g for g in rich_s1 if s <= (g[0] + g[1]) // 2 < e]
            coding_6f = compute_best_6frame_coding_fraction(win_sub)
            if in_win_s1:
                base_185 = compute_window_features(
                    win_sub, s, e, simple_genes, ctx_unit, ctx_gc, ctx_is_self,
                    rich_genes=rich_genes, flank_feats=flank_vec,
                )
                aa_22_avg = base_185[_AA_SLICE_START:_AA_SLICE_END]
                extra_414 = _compute_stage1_window_extra(in_win_s1, aa_22_avg, coding_6f)
            else:
                fb = find_best_6frame_orf(win_sub, min_aa=15)
                if fb is not None:
                    rs, re_, f_strand, f_aa, coding_6f = fb
                    gs_abs, ge_abs = s + rs, s + re_
                    f_aa22 = _encode_protein_22(f_aa)
                    f_cc = _codon_gc_counts(win_sub[rs:re_], f_strand)
                    fb_rich: RichGeneRecord = (gs_abs, ge_abs, f_strand, f_aa22, *f_cc)
                    fb_dp49 = encode_peptide_7x7_dipeptide(f_aa)
                    fb_ct343 = encode_peptide_7x7x7_triad(f_aa)
                    fb_pyro = encode_pyrodigal_gene_attrs(None, len(f_aa), is_fallback=1.0)
                    fb_s1: Stage1GeneRecord = (*fb_rich, fb_dp49, fb_ct343, fb_pyro)
                    base_185 = compute_window_features(
                        win_sub, s, e, [(gs_abs, ge_abs, f_strand)], ctx_unit, ctx_gc, ctx_is_self,
                        rich_genes=[fb_rich], flank_feats=flank_vec,
                    )
                    extra_414 = _compute_stage1_window_extra([fb_s1], f_aa22, coding_6f)
                else:
                    base_185 = compute_window_features(
                        win_sub, s, e, simple_genes, ctx_unit, ctx_gc, ctx_is_self,
                        rich_genes=rich_genes, flank_feats=flank_vec,
                    )
                    extra_414 = _compute_stage1_window_extra([], base_185[_AA_SLICE_START:_AA_SLICE_END], coding_6f)

            feats[i, :185] = base_185
            feats[i, 185:] = extra_414

        if regions:
            overlaps[i] = _overlap_fraction(s, e, regions)
            sub_masks[i] = _compute_sub_mask(s, e, regions, SUB_BINS)

    return {
        "contig_id": contig_id,
        "starts": np.asarray([s for s, _ in spans], dtype=np.int64),
        "ends": np.asarray([e for _, e in spans], dtype=np.int64),
        "overlap": overlaps,
        "sub_mask": sub_masks,
        "features": feats,
    }


def extract_contig_windows(
    contig_id: str,
    seq: str,
    win_size: int = 5000,
    step_size: int = 2500,
    truth_regions: Optional[Sequence[Tuple[int, int]]] = None,
    *,
    feature_profile: str = "v4",
) -> Dict[str, Any]:
    """
    对单条 contig 统一预测基因后滑窗提取 185 维（v4）或 256 维（stage1）特征及 25 维 200bp 精细掩码标签。
    """
    n = len(seq)
    spans: List[Tuple[int, int]] = []
    if n <= win_size:
        spans.append((0, n))
    else:
        pos = 0
        while pos < n:
            end_pos = min(n, pos + win_size)
            if end_pos - pos < win_size // 2 and spans:
                spans.append((max(0, n - win_size), n))
                break
            spans.append((pos, end_pos))
            if end_pos == n:
                break
            pos += step_size

    return extract_contig_windows_for_spans(
        contig_id,
        seq,
        spans,
        truth_regions=truth_regions,
        feature_profile=feature_profile,
        context_win_size=win_size,
    )
