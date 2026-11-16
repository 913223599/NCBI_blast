# -*- coding: utf-8 -*-
"""
Stage 1.2 噬菌体功能基因分区（9 大客观功能模块）三源合一分类、逐 ORF 坐标对齐、
多模块矛盾负样本自动清洗、稀有非有尾病毒多尺度采样及 Kendall 同方差多任务不确定性损失模块。

设计目标：
1. 彻底消除蛋白功能标注对窗口标签 y 的依赖（零标签泄露），所有蛋白仅依据客观序列同源与注释划分功能；
2. 将双层功能监督解耦为：
   - Level 1: is_phage_ortholog (1D) — 是否命中噬菌体同源蛋白家族（含 PHROGs unknown function 暗物质蛋白）；
   - Level 2: func_vec (9D) + is_func_known 掩码 — 9 大具体功能模块，当命中 unknown function 时豁免 P0..P8 负梯度；
3. 支持逐 ORF 槽位 (IoU >= 0.8) 精细对齐，为下游噬菌体基因组功能分区识别与模块边界定位提供原生支持。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
import torch
from torch import nn

FUNCTIONAL_PARTITION_NAMES: Tuple[str, ...] = (
    "head_packaging",
    "connector",
    "tail",
    "lysis",
    "integration_excision",
    "dna_rna_replication",
    "transcription_regulation",
    "moron_amg_defense",
    "transposon_plasmid_mge",
)

NUM_FUNC_PARTITIONS: int = len(FUNCTIONAL_PARTITION_NAMES)

# PHROGs 官方标准类别到 9 大功能分区索引的直接映射
_PHROG_CATEGORY_TO_INDEX: Dict[str, int] = {
    "head and packaging": 0,
    "connector": 1,
    "tail": 2,
    "lysis": 3,
    "integration and excision": 4,
    "dna, rna and nucleotide metabolism": 5,
    "transcription regulation": 6,
    "moron, auxiliary metabolic gene and host takeover": 7,
}

# 9 大功能分区的生物信息学关键词词表（涵盖有尾噬菌体与 Microviridae/Inoviridae/Leviviricetes 等非有尾病毒）
_PARTITION_KEYWORDS: Tuple[Tuple[int, Tuple[str, ...]], ...] = (
    (
        0,  # P0: head_packaging
        (
            "terminase",
            "terl",
            "ters",
            "portal protein",
            "portal",
            "major head",
            "minor head",
            "head protein",
            "head morphogenesis",
            "head maturation",
            "capsid",
            "procapsid",
            "prohead",
            "scaffold protein",
            "head-scaffolding",
            "virion structural",
            "coat protein",
            "major coat",
            "minor coat",
            "maturation protein",
            "internal virion protein",
        ),
    ),
    (
        1,  # P1: connector
        (
            "connector",
            "head-tail",
            "head to tail",
            "neck protein",
            "neck appendage",
            "adaptor protein",
            "head completion",
            "stopper protein",
        ),
    ),
    (
        2,  # P2: tail
        (
            "tail",
            "baseplate",
            "tape measure",
            "sheath",
            "whisker",
            "collar",
            "spike protein",
            "dna pilot protein",
            "pilot protein",
            "receptor binding",
            "receptor-binding",
            "adhesin",
        ),
    ),
    (
        3,  # P3: lysis
        (
            "endolysin",
            "holin",
            "spanin",
            "rz-like",
            "rz1",
            "phage lysin",
            "lysis protein",
            "phage lysozyme",
            "muramidase",
            "l-alanyl-d-glutamate",
        ),
    ),
    (
        4,  # P4: integration_excision
        (
            "integrase",
            "excisionase",
            "xis",
            "site-specific recombinase",
            "tyrosine recombinase",
            "serine recombinase",
            "phage recombinase",
            "attachment site",
        ),
    ),
    (
        5,  # P5: dna_rna_replication
        (
            "dna polymerase",
            "rna-dependent rna polymerase",
            "rna replicase",
            "replicase",
            "helicase",
            "primase",
            "primase-helicase",
            "single-stranded dna-binding",
            "ssdna-binding",
            "ssb",
            "rolling circle",
            "rolling-circle",
            "replication initiation",
            "replication protein",
            "gpa",
            "endonuclease",
            "exonuclease",
            "holliday junction",
            "resolvase",
            "erf",
            "recombination protein",
            "thymidylate",
            "ribonucleotide reductase",
            "darp",
            "deoxynucleoside",
        ),
    ),
    (
        6,  # P6: transcription_regulation
        (
            "repressor",
            "antirepressor",
            "anti-repressor",
            "transcriptional regulator",
            "transcription regulator",
            "transcription factor",
            "antitermination",
            "anti-sigma",
            "rna polymerase sigma",
            "cro protein",
            "ci protein",
            "cii protein",
        ),
    ),
    (
        7,  # P7: moron_amg_defense
        (
            "anti-crispr",
            "abortive infection",
            "superinfection exclusion",
            "toxin-antitoxin",
            "antitoxin",
            "host takeover",
            "host nuclease inhibitor",
            "gam protein",
            "kil protein",
            "auxiliary metabolic",
            "queuosine",
            "fole",
            "quet",
            "virulence",
            "shiga toxin",
            "zonula occludens",
        ),
    ),
    (
        8,  # P8: transposon_plasmid_mge
        (
            "transposase",
            "insertion sequence",
            "is630",
            "is200",
            "is605",
            "is110",
            "is256",
            "is3 family",
            "is4 family",
            "is5 family",
            "is66",
            "is91",
            "is1595",
            "is30",
            "isl3",
            "tn3",
            "tnp",
            "conjugal transfer",
            "type iv secretion",
            "relaxase",
            "mobilization protein",
            "plasmid partition",
            "parb",
            "para ",
            "traa",
            "trab",
            "trac",
            "trad",
            "trag",
        ),
    ),
)

_PHAGE_SPECIFIC_MARKERS: Tuple[str, ...] = (
    "phage",
    "bacteriophage",
    "prophage",
    "virion",
    "viral",
    "virus",
    "microvir",
    "inovir",
    "levivir",
    "corticovir",
    "tectivir",
    "cystovir",
    "caudovir",
    "terminase",
    "portal",
    "capsid",
    "procapsid",
    "baseplate",
    "tape measure",
    "tail",
    "holin",
    "endolysin",
    "spanin",
    "excisionase",
)

_UNKNOWN_MARKERS: Tuple[str, ...] = (
    "unknown",
    "hypothetical",
    "uncharacterized",
    "unassigned",
    "domain of unknown function",
    "duf",
)

_PHAGE_TAX_STEMS: Tuple[str, ...] = (
    "microvir",
    "inovir",
    "levivir",
    "corticovir",
    "tectivir",
    "cystovir",
    "caudovir",
)


# 预编译带词边界的正则，避免如 transferase 误触 erf、axis 误触 xis、detail 误触 tail
def _compile_kw_regex(keywords: Sequence[str], *, allow_prefix_stems: Sequence[str] = ()) -> re.Pattern[str]:
    stem_set = set(allow_prefix_stems)
    parts = []
    for k in keywords:
        ks = k.strip()
        if not ks:
            continue
        if ks in stem_set:
            parts.append(rf"\b{re.escape(ks)}[a-z]*\b")
        else:
            parts.append(rf"\b{re.escape(ks)}\b")
    return re.compile("|".join(parts), re.IGNORECASE)


_PARTITION_PATTERNS: Tuple[Tuple[int, re.Pattern[str]], ...] = tuple(
    (idx, _compile_kw_regex(kws)) for idx, kws in _PARTITION_KEYWORDS
)
_PHAGE_SPECIFIC_PATTERN: re.Pattern[str] = _compile_kw_regex(
    _PHAGE_SPECIFIC_MARKERS,
    allow_prefix_stems=_PHAGE_TAX_STEMS,
)
_UNKNOWN_PATTERN: re.Pattern[str] = _compile_kw_regex(_UNKNOWN_MARKERS)
_DMND_ORG_BRACKET_RE: re.Pattern[str] = re.compile(r"\s*\[[^\]]+\]\s*$")


def classify_protein_to_functional_partitions(
    phrog_category: str = "",
    phrog_annot: str = "",
    diamond_title: str = "",
    gbk_product: str = "",
) -> Dict[str, Any]:
    """
    将单个蛋白的三源注释（PHROGs + DIAMOND + GenBank CDS product）映射为双层客观功能表示。
    绝不依赖所在窗口的正负标签 y。

    返回字典：
    - is_phage_ortholog (bool): 是否属于噬菌体同源蛋白（包含 PHROGs unknown function）
    - is_func_known (bool): 具体功能模块是否已知（若为噬菌体暗物质蛋白则为 False，豁免功能分区负梯度）
    - func_vec (np.ndarray, shape=(9,), float32): 9 大功能分区多标签 0/1 向量
    - sem4_vec (np.ndarray, shape=(4,), float32): 兼容旧版 4 维语义 [hallmark, integrase, transposase, tail_lysis]
    """
    func_vec = np.zeros(NUM_FUNC_PARTITIONS, dtype=np.float32)
    cat_clean = (phrog_category or "").strip().lower()
    annot_clean = (phrog_annot or "").strip().lower()
    dmnd_raw = (diamond_title or "").strip().lower()
    # 剥离 DIAMOND stitle 末尾参考蛋白来源物种方括号（如 [Vibrio phage ...]），防止非病毒蛋白因物种名污染语义
    dmnd_desc = _DMND_ORG_BRACKET_RE.sub("", dmnd_raw).strip()
    gbk_clean = (gbk_product or "").strip().lower()

    has_any_input = bool(cat_clean or annot_clean or dmnd_desc or gbk_clean)
    if not has_any_input:
        return {
            "is_phage_ortholog": False,
            "is_func_known": True,
            "func_vec": func_vec,
            "sem4_vec": np.zeros(4, dtype=np.float32),
        }

    # 1. PHROGs 官方类别优先映射
    has_phrog = bool(cat_clean or annot_clean)
    if cat_clean in _PHROG_CATEGORY_TO_INDEX:
        func_vec[_PHROG_CATEGORY_TO_INDEX[cat_clean]] = 1.0

    # 2. 合并三源客观功能描述进行带词边界关键词匹配
    combined_desc = f" {annot_clean} | {dmnd_desc} | {gbk_clean} "
    for part_idx, pat in _PARTITION_PATTERNS:
        if pat.search(combined_desc):
            func_vec[part_idx] = 1.0

    # 若明确命中 PHROG 的 integration/head/tail 等噬菌体专属类别，修正单纯因 "transposase" 词根（如 Mu transposase）误触的 P8
    if has_phrog and cat_clean in _PHROG_CATEGORY_TO_INDEX and func_vec[8] > 0.5:
        if "mu-like" in combined_desc or "phage" in combined_desc or cat_clean == "integration and excision":
            func_vec[4] = 1.0
            func_vec[8] = 0.0

    # 3. 判定是否属于噬菌体同源蛋白 (Level 1)
    has_structural_hit = bool(np.any(func_vec[:3] > 0.5))
    has_phage_kw = bool(_PHAGE_SPECIFIC_PATTERN.search(combined_desc))
    has_pure_mge = bool(func_vec[8] > 0.5 and not has_phrog and not has_phage_kw and not has_structural_hit)

    if has_pure_mge:
        is_phage_ortholog = False
    elif has_phrog or has_structural_hit or has_phage_kw or bool(func_vec[3] > 0.5):
        is_phage_ortholog = True
    else:
        is_phage_ortholog = False

    # 4. 判定具体功能是否已知 (Level 2 Mask)
    any_func_active = bool(np.any(func_vec > 0.5))
    if any_func_active:
        is_func_known = True
    elif is_phage_ortholog:
        # 属于噬菌体同源蛋白（如 PHROGs unknown function / other 或 hypothetical phage protein），但无已知功能模块
        is_func_known = False
    else:
        # 普通宿主蛋白：若只是 hypothetical protein 但非噬菌体同源，对 P0..P8 均为明确阴性
        is_func_known = True if not _UNKNOWN_PATTERN.search(combined_desc) or bool(gbk_clean) else True
        if not any_func_active and not is_phage_ortholog:
            is_func_known = True

    # 5. 生成高特异度 4 维语义向量 [phage_hallmark, integrase, transposase, tail_lysis]
    sem4_vec = np.zeros(4, dtype=np.float32)
    if func_vec[0] > 0.5 or func_vec[1] > 0.5 or func_vec[2] > 0.5:
        sem4_vec[0] = 1.0
    if func_vec[4] > 0.5:
        sem4_vec[1] = 1.0
    if func_vec[8] > 0.5:
        sem4_vec[2] = 1.0
    if func_vec[2] > 0.5 or func_vec[3] > 0.5:
        sem4_vec[3] = 1.0

    return {
        "is_phage_ortholog": is_phage_ortholog,
        "is_func_known": is_func_known,
        "func_vec": func_vec,
        "sem4_vec": sem4_vec,
    }


def _interval_iou(s1: float, e1: float, s2: float, e2: float) -> float:
    inter = max(0.0, min(e1, e2) - max(s1, s2))
    if inter <= 0.0:
        return 0.0
    union = max(1e-6, (e1 - s1) + (e2 - s2) - inter)
    return inter / union


def build_window_and_orf_functional_targets(
    contig_ids: np.ndarray,
    starts: np.ndarray,
    ends: np.ndarray,
    labels: np.ndarray,
    orf_tokens: np.ndarray,
    orf_counts: np.ndarray,
    contig_annotated_orfs: Dict[str, List[Tuple[int, int, int, Dict[str, Any]]]],
    *,
    clean_contradictory_negatives: bool = True,
    iou_threshold: float = 0.80,
    non_clean_contig_prefixes: Tuple[str, ...] = ("ARCHAEA_",),
) -> Dict[str, np.ndarray]:
    """
    将 Contig 级客观蛋白功能注释通过 IoU >= 0.80 精确绑定到每个窗口的 36 个 ORF 槽位与窗口级目标，
    并自动识别多模块共现的矛盾负样本（将其 clean_labels 置为 -1，同时保留单基因孤立同源负样本为 0）。
    """
    n_win, max_orfs, _ = orf_tokens.shape
    func_targets = np.zeros((n_win, NUM_FUNC_PARTITIONS), dtype=np.float32)
    func_valid_mask = np.ones((n_win, NUM_FUNC_PARTITIONS), dtype=np.float32)
    orf_phage_targets = np.zeros((n_win, max_orfs), dtype=np.float32)
    orf_phage_valid = np.zeros((n_win, max_orfs), dtype=np.float32)
    orf_func_targets = np.zeros((n_win, max_orfs, NUM_FUNC_PARTITIONS), dtype=np.float32)
    orf_func_valid = np.zeros((n_win, max_orfs), dtype=np.float32)
    sem_targets = np.zeros((n_win, 4), dtype=np.float32)
    adv_host_counts = np.zeros(n_win, dtype=np.int32)
    clean_labels = labels.astype(np.int8, copy=True)

    for i in range(n_win):
        cid = str(contig_ids[i])
        win_s = float(starts[i])
        win_e = float(ends[i])
        win_len = max(1.0, win_e - win_s)
        cnt = min(max_orfs, max(0, int(orf_counts[i])))
        cand_orfs = contig_annotated_orfs.get(cid, [])

        # 预先筛选与当前窗口有交集的候选注释 ORF（保留原始坐标与裁剪坐标以兼容跨窗边界基因）
        win_cands: List[Tuple[float, float, float, float, int, Dict[str, Any]]] = []
        for os_bp, oe_bp, ostr, oinfo in cand_orfs:
            if oe_bp <= win_s or os_bp >= win_e:
                continue
            clip_s = max(win_s, float(os_bp))
            clip_e = min(win_e, float(oe_bp))
            if clip_e > clip_s:
                win_cands.append((float(os_bp), float(oe_bp), clip_s, clip_e, ostr, oinfo))

        phage_ortholog_cnt = 0
        structural_cnt = 0
        has_unknown_phage_orf = False

        # 1. 逐个 ORF Token 槽位按 IoU >= iou_threshold 进行坐标与链方向对齐
        for k in range(cnt):
            # 标准 expert_c_orf Token 格式：col 6 = rel_start, col 7 = rel_end, col 1 = strand
            if abs(float(orf_tokens[i, k, 6])) > 1e-7 or abs(float(orf_tokens[i, k, 7])) > 1e-7:
                rel_s = float(orf_tokens[i, k, 6])
                rel_e = float(orf_tokens[i, k, 7])
                tok_strand = 1 if float(orf_tokens[i, k, 1]) >= 0.0 else -1
            else:
                rel_s = float(orf_tokens[i, k, 0])
                rel_e = float(orf_tokens[i, k, 1])
                tok_strand = 1 if float(orf_tokens[i, k, 3]) >= 0.0 else -1
            tok_s = win_s + rel_s * win_len
            tok_e = win_s + rel_e * win_len
            if tok_e <= tok_s:
                continue
            tok_cs = max(win_s, tok_s)
            tok_ce = min(win_e, tok_e)

            best_iou = 0.0
            best_info: Optional[Dict[str, Any]] = None
            for raw_s, raw_e, cs, ce, cstrand, cinfo in win_cands:
                if cstrand != 0 and cstrand != tok_strand:
                    continue
                iou_raw = _interval_iou(tok_s, tok_e, raw_s, raw_e)
                iou_clip = _interval_iou(tok_cs, tok_ce, cs, ce) if tok_ce > tok_cs else 0.0
                iou = max(iou_raw, iou_clip)
                if iou > best_iou:
                    best_iou = iou
                    best_info = cinfo

            orf_phage_valid[i, k] = 1.0
            if best_info is not None and best_iou >= iou_threshold:
                is_ph = bool(best_info.get("is_phage_ortholog", False))
                is_kn = bool(best_info.get("is_func_known", True))
                fvec = np.asarray(best_info["func_vec"], dtype=np.float32)
                svec = np.asarray(best_info.get("sem4_vec", np.zeros(4, dtype=np.float32)), dtype=np.float32)

                orf_phage_targets[i, k] = 1.0 if is_ph else 0.0
                orf_func_targets[i, k] = fvec
                func_targets[i] = np.maximum(func_targets[i], fvec)
                sem_targets[i] = np.maximum(sem_targets[i], svec)

                if is_ph:
                    phage_ortholog_cnt += 1
                    if np.any(fvec[:4] > 0.5):
                        structural_cnt += 1

                if is_ph and not is_kn:
                    # 关键机制：对 unknown function 噬菌体同源蛋白豁免 P0..P8 负梯度惩罚
                    orf_func_valid[i, k] = 0.0
                    has_unknown_phage_orf = True
                else:
                    orf_func_valid[i, k] = 1.0
                if bool(best_info.get("adversarial_host_flag", False)):
                    adv_host_counts[i] += 1
            else:
                # 未命中任何已知噬菌体或特殊功能注释的普通背景 ORF
                orf_phage_targets[i, k] = 0.0
                orf_func_valid[i, k] = 1.0

        # 2. 补充汇总窗口内可能未被 Top-36 Token 捕获但实质落入窗口的注释 ORF
        for _, _, cs, ce, _, cinfo in win_cands:
            if (ce - cs) >= 120.0:
                fvec = np.asarray(cinfo["func_vec"], dtype=np.float32)
                svec = np.asarray(cinfo.get("sem4_vec", np.zeros(4, dtype=np.float32)), dtype=np.float32)
                func_targets[i] = np.maximum(func_targets[i], fvec)
                sem_targets[i] = np.maximum(sem_targets[i], svec)
                if bool(cinfo.get("is_phage_ortholog", False)) and not bool(cinfo.get("is_func_known", True)):
                    has_unknown_phage_orf = True

        # 若窗口内含未知功能噬菌体蛋白，对窗口级未显式激活的 P0..P7 维度豁免负向梯度惩罚
        if has_unknown_phage_orf:
            for d in range(8):
                if func_targets[i, d] < 0.5:
                    func_valid_mask[i, d] = 0.0

        # 3. 严格多模块核心结构矛盾负样本清洗：
        # 仅当看似负样本窗口出现 >=2 个不同病毒体核心结构/裂解模块 (P0..P3) 或 >=2 个独立结构 ORF 共生时才视为漏标原噬菌体；
        # 绝不因通用细菌 P5(复制)/P6(调控)/P7(辅助防御)/P8(转座子) 或 phrog_unknown 误清洗正常细菌背景负样本
        if clean_contradictory_negatives and int(labels[i]) == 0:
            if not any(cid.startswith(pfx) for pfx in non_clean_contig_prefixes):
                core_struct_modules = int(np.sum(func_targets[i, :4] > 0.5))
                if (
                    core_struct_modules >= 2
                    or (structural_cnt >= 2 and int(np.sum(func_targets[i, :8] > 0.5)) >= 2)
                ):
                    clean_labels[i] = -1

    return {
        "func_targets": func_targets,
        "func_valid_mask": func_valid_mask,
        "orf_phage_targets": orf_phage_targets,
        "orf_phage_valid": orf_phage_valid,
        "orf_func_targets": orf_func_targets,
        "orf_func_valid": orf_func_valid,
        "sem_targets": sem_targets,
        "adv_host_counts": adv_host_counts,
        "clean_labels": clean_labels,
    }


_HOST_ADV_PHOLD_SOURCES = frozenset({"card", "vfdb", "defensefinder", "netflax"})


def _is_valid_phold_phage_hit(phold_hit: Dict[str, Any]) -> bool:
    src = str(phold_hit.get("source_type", "none")).lower()
    if src not in {"phrog", "acr"}:
        return False
    conf = str(phold_hit.get("confidence", "")).lower()
    ev = float(phold_hit.get("evalue", 1.0))
    bs = float(phold_hit.get("bitscore", 0.0))
    if conf in {"high", "medium"}:
        return True
    return ev <= 1e-5 and bs >= 120.0


def classify_protein_with_p0_teachers(
    phrog_category: str = "",
    phrog_annot: str = "",
    diamond_title: str = "",
    gbk_product: str = "",
    phold_hit: Optional[Dict[str, Any]] = None,
    hmm_hit: Optional[Dict[str, Tuple[str, float, float]]] = None,
) -> Dict[str, Any]:
    """
    在客观三源分类基础上叠加 P0 离线结构教师 (phold 3Di+Foldseek) 与 HMM 对抗教师 (DefenseFinder/dbAPIS/VS2)：
    - 若结构/HMM 明确指向宿主耐药/毒力/防御/毒素-抗毒素（CARD/VFDB/DefenseFinder/Netflax）且无核心结构域，
      标记 adversarial_host_flag=True 且严禁混入噬菌体 moron_amg_defense 正类；
    - 若 phold 真实 PHROG/ACR 或 dbAPIS/VS2 病毒域显著命中，补全暗物质蛋白的噬菌体同源性及 9D 功能分区。
    """
    base = classify_protein_to_functional_partitions(
        phrog_category=phrog_category,
        phrog_annot=phrog_annot,
        diamond_title=diamond_title,
        gbk_product=gbk_product,
    )
    func_vec = np.array(base["func_vec"], dtype=np.float32, copy=True)
    sem4_vec = np.array(base["sem4_vec"], dtype=np.float32, copy=True)
    is_phage = bool(base["is_phage_ortholog"])
    is_known = bool(base["is_func_known"])
    adv_host_flag = False

    # 1. 检查宿主耐药/毒力/防御系统对抗证据
    has_host_df = bool(hmm_hit and "defense_finder" in hmm_hit and float(hmm_hit["defense_finder"][1]) <= 1e-5)
    has_host_phold = False
    if phold_hit:
        psrc = str(phold_hit.get("source_type", "")).lower()
        peval = float(phold_hit.get("evalue", 1.0))
        pconf = str(phold_hit.get("confidence", "")).lower()
        if psrc in _HOST_ADV_PHOLD_SOURCES and (pconf in {"high", "medium"} or peval <= 1e-5):
            has_host_phold = True

    # 2. 检查真实噬菌体结构与反防御补全证据
    extra_cat = ""
    extra_prod = ""
    has_phage_complement = False
    if phold_hit and _is_valid_phold_phage_hit(phold_hit):
        has_phage_complement = True
        psrc = str(phold_hit.get("source_type", "")).lower()
        pfunc = str(phold_hit.get("function", "")).strip()
        pprod = str(phold_hit.get("product", "")).strip()
        if psrc == "acr":
            func_vec[7] = 1.0
        elif pfunc and pfunc.lower() != "unknown function":
            extra_cat = pfunc
            extra_prod = pprod

    if hmm_hit:
        if "dbapis" in hmm_hit and float(hmm_hit["dbapis"][1]) <= 1e-5:
            has_phage_complement = True
            func_vec[7] = 1.0
        if "wsl_vs2_pfam_vir" in hmm_hit and float(hmm_hit["wsl_vs2_pfam_vir"][1]) <= 1e-6:
            has_phage_complement = True
            hmm_name = str(hmm_hit["wsl_vs2_pfam_vir"][0])
            extra_prod = f"{extra_prod} {hmm_name}".strip()

    if has_phage_complement and (extra_cat or extra_prod):
        sub = classify_protein_to_functional_partitions(
            phrog_category=extra_cat,
            phrog_annot=extra_prod,
        )
        func_vec = np.maximum(func_vec, np.asarray(sub["func_vec"], dtype=np.float32))
        sem4_vec = np.maximum(sem4_vec, np.asarray(sub["sem4_vec"], dtype=np.float32))
        if np.any(func_vec[:4] > 0.5):
            is_phage = True
        elif not has_host_df and not has_host_phold:
            is_phage = True
        is_known = bool(np.any(func_vec > 0.5)) or not is_phage
    elif has_phage_complement:
        if np.any(func_vec > 0.5):
            is_phage = True
            is_known = True

    # 若确认为宿主耐药/毒力/防御且未有强噬菌体结构域 P0..P3 支撑，打上对抗宿主旗标并禁止误归为噬菌体 moron
    has_core_struct = bool(np.any(func_vec[:4] > 0.5))
    if (has_host_df or has_host_phold) and not has_core_struct:
        adv_host_flag = True
        if not bool(base["is_phage_ortholog"]) or float(func_vec[7]) > 0.5:
            is_phage = False
            func_vec[7] = 0.0
            is_known = True

    # 同步 4 维兼容性语义向量
    if func_vec[0] > 0.5 or func_vec[1] > 0.5 or func_vec[2] > 0.5:
        sem4_vec[0] = 1.0
    if func_vec[4] > 0.5:
        sem4_vec[1] = 1.0
    if func_vec[8] > 0.5:
        sem4_vec[2] = 1.0
    if func_vec[2] > 0.5 or func_vec[3] > 0.5:
        sem4_vec[3] = 1.0

    return {
        "is_phage_ortholog": bool(is_phage),
        "is_func_known": bool(is_known),
        "func_vec": func_vec,
        "sem4_vec": sem4_vec,
        "adversarial_host_flag": bool(adv_host_flag),
    }


def build_p0_teacher_calibration(
    *,
    labels: np.ndarray,
    teacher_probs: np.ndarray,
    func_targets: np.ndarray,
    adv_host_counts: np.ndarray,
    base_sample_weights: Optional[np.ndarray] = None,
    hard_neg_weight: float = 1.75,
    suppression_blend: float = 0.65,
    mge_prob_trigger: float = 0.35,
) -> Dict[str, Any]:
    """
    依据 P0 对抗教师信号（宿主防御/耐药/毒力命中与无核心结构的 MGE 岛）对训练集教师软概率
    与难负例权重执行平滑对抗校准，防止学生盲从旧 OOF 在易混宿主岛上的高估软分数。
    """
    y = np.asarray(labels, dtype=np.int8)
    tp = np.asarray(teacher_probs, dtype=np.float32).copy()
    sw = (
        np.asarray(base_sample_weights, dtype=np.float32).copy()
        if base_sample_weights is not None
        else np.ones(len(y), dtype=np.float32)
    )
    ft = np.asarray(func_targets, dtype=np.float32)
    adv_cnt = np.asarray(adv_host_counts, dtype=np.int32)

    no_core_struct = np.sum(ft[:, :4] > 0.5, axis=1) == 0
    is_clean_neg = y == 0
    is_mge_fp_risk = (ft[:, 8] > 0.5) & (tp >= float(mge_prob_trigger))
    adv_mask = is_clean_neg & no_core_struct & ((adv_cnt >= 1) | is_mge_fp_risk)

    blend = float(np.clip(suppression_blend, 0.0, 1.0))
    tp[adv_mask] = tp[adv_mask] * (1.0 - blend)
    sw[adv_mask] = np.maximum(sw[adv_mask], float(hard_neg_weight))

    return {
        "teacher_probs": tp,
        "sample_weights": sw,
        "calibrated_count": int(np.sum(adv_mask)),
        "adv_host_neg_count": int(np.sum(is_clean_neg & no_core_struct & (adv_cnt >= 1))),
        "mge_fp_risk_count": int(np.sum(is_clean_neg & no_core_struct & is_mge_fp_risk)),
    }


def extract_rare_multiscale_windows(
    rare_records: Sequence[Tuple[str, str, str]],
    *,
    scales_bp: Sequence[int] = (600, 1000, 1800, 3000),
    seed: int = 42,
    windows_per_scale: int = 3,
) -> List[Dict[str, Any]]:
    """
    从训练集稀有非有尾噬菌体（Microviridae / Leviviricetes / Inoviridae 等）基因组上
    切取 600bp / 1000bp / 1800bp / 3000bp 多尺度训练窗口，修复短片段表征分布失衡。
    """
    rng = np.random.default_rng(seed)
    out_windows: List[Dict[str, Any]] = []

    for contig_id, raw_seq, lineage in rare_records:
        seq = (raw_seq or "").strip().upper()
        seq_len = len(seq)
        if seq_len < 300:
            continue

        seen_spans: Set[Tuple[int, int]] = set()
        for scale in scales_bp:
            target_len = scale
            if seq_len <= target_len:
                span = (0, seq_len)
                if span not in seen_spans:
                    seen_spans.add(span)
                    out_windows.append({
                        "contig_id": contig_id,
                        "start": 0,
                        "end": seq_len,
                        "seq": seq,
                        "length": seq_len,
                        "lineage": lineage,
                        "scale_bp": target_len,
                    })
                continue

            max_start = seq_len - target_len
            n_crops = max(1, windows_per_scale)
            if n_crops == 1:
                anchors = [int(rng.integers(0, max_start + 1))]
            else:
                base_grid = np.linspace(0, max_start, num=n_crops)
                jitter_bound = max(1, target_len // 8)
                anchors = [
                    int(np.clip(round(pos) + int(rng.integers(-jitter_bound, jitter_bound + 1)), 0, max_start))
                    for pos in base_grid
                ]

            for st in anchors:
                ed = st + target_len
                span = (st, ed)
                if span in seen_spans:
                    continue
                seen_spans.add(span)
                sub_seq = seq[st:ed]
                if sub_seq.count("N") > len(sub_seq) * 0.25:
                    continue
                out_windows.append({
                    "contig_id": contig_id,
                    "start": st,
                    "end": ed,
                    "seq": sub_seq,
                    "length": len(sub_seq),
                    "lineage": lineage,
                    "scale_bp": target_len,
                })

    return out_windows


def _seq_kmer_set(seq: str, k: int = 9, step: int = 3) -> Set[int]:
    s = seq.upper()
    n = len(s)
    if n < k:
        return {hash(s)}
    return {hash(s[i:i + k]) for i in range(0, n - k + 1, max(1, step))}


def deduplicate_sequences_kmer(
    candidates: Sequence[Tuple[str, str]],
    *,
    k: int = 9,
    max_jaccard: float = 0.90,
) -> List[Tuple[str, str]]:
    """
    基于精确哈希与 k-mer Jaccard 相似度对重复/近乎完全相同的窗口序列（如高度重复的 1,738bp 负样本切片）去重。
    """
    kept: List[Tuple[str, str]] = []
    kept_sigs: List[Tuple[int, Set[int]]] = []
    seen_exact: Set[str] = set()

    for seq_id, seq in candidates:
        s_clean = (seq or "").strip().upper()
        if not s_clean:
            continue
        if s_clean in seen_exact:
            continue

        sig = _seq_kmer_set(s_clean, k=k, step=3)
        s_len = len(s_clean)
        is_dup = False
        for prev_len, prev_sig in kept_sigs:
            if abs(s_len - prev_len) > max(100, int(0.15 * max(s_len, prev_len))):
                continue
            inter = len(sig & prev_sig)
            union = max(1, len(sig | prev_sig))
            if (inter / union) >= max_jaccard:
                is_dup = True
                break

        if not is_dup:
            seen_exact.add(s_clean)
            kept.append((seq_id, s_clean))
            kept_sigs.append((s_len, sig))

    return kept


class HomoscedasticMultiTaskLoss(nn.Module):
    """
    Kendall et al. (CVPR 2018) 同方差任务不确定性自动加权损失函数：
    L_total = sum_i (0.5 * exp(-s_i) * L_i + 0.5 * s_i)，其中 s_i = log(sigma_i^2) 为可学习对数方差。
    """

    def __init__(
        self,
        num_tasks: int,
        init_log_vars: Optional[Sequence[float]] = None,
        min_log_var: float = -4.0,
        max_log_var: float = 4.0,
    ) -> None:
        super().__init__()
        if num_tasks < 1:
            raise ValueError("num_tasks must be >= 1")
        self.num_tasks = num_tasks
        self.min_log_var = min_log_var
        self.max_log_var = max_log_var
        if init_log_vars is not None:
            init_t = torch.tensor(list(init_log_vars), dtype=torch.float32)
            if init_t.numel() != self.num_tasks:
                raise ValueError("init_log_vars length must match num_tasks")
        else:
            init_t = torch.zeros(self.num_tasks, dtype=torch.float32)
        self.log_vars = nn.Parameter(init_t)

    def forward(self, losses: Sequence[torch.Tensor]) -> torch.Tensor:
        if len(losses) != self.num_tasks:
            raise ValueError(f"Expected {self.num_tasks} task losses, got {len(losses)}")
        total = torch.zeros((), dtype=losses[0].dtype, device=losses[0].device)
        for i, task_loss in enumerate(losses):
            s_i = torch.clamp(self.log_vars[i], min=self.min_log_var, max=self.max_log_var)
            precision = torch.exp(-s_i)
            total = total + 0.5 * precision * task_loss + 0.5 * s_i
        return total
