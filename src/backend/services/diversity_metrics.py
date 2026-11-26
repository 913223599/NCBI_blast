# -*- coding: utf-8 -*-
"""
16S 扩增子多样性生态学指标计算与分片解析辅助模块

提供纯函数形式的 Alpha 多样性、Bray-Curtis Beta 多样性与 PCoA 降维、
全局物种丰度汇总、自然排序键以及单分片 BLAST 输出解析，供 DiversityEngine 复用。
"""

import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

from .rrndb_service import RrnDBService


def natural_keys(text: str) -> List[Any]:
    return [int(c) if c.isdigit() else c for c in re.split(r"(\d+)", text)]


def parse_chunk_blast_output(
    c_out: Path,
    *,
    min_identity: float,
    min_coverage: float,
) -> Dict[str, Dict[str, tuple]]:
    """解析单个分片的 BLAST tabular 结果，按同一性与覆盖度过滤并取各读段最佳命中。"""
    local_best_hits: Dict[str, Dict[str, tuple]] = defaultdict(dict)
    if not c_out.exists():
        return local_best_hits
    with open(c_out, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) < 9 or "__" not in parts[0]:
                continue
            sname, raw_rid = parts[0].split("__", 1)
            bitscore = float(parts[7])
            pident = float(parts[2])
            aln_len = int(parts[3])
            qcovs = float(parts[9]) if len(parts) >= 10 else 100.0
            if pident < min_identity or aln_len < 40:
                continue
            if min_coverage > 0 and qcovs < min_coverage:
                continue
            stitle = parts[8]
            m = re.search(r"([A-Z][a-z]+ [a-z0-9\.\-]+(?: subsp\. [a-z0-9\.\-]+)?)", stitle)
            sp = m.group(1) if m else stitle
            if raw_rid not in local_best_hits[sname] or bitscore > local_best_hits[sname][raw_rid][0]:
                local_best_hits[sname][raw_rid] = (bitscore, sp, pident)
    return local_best_hits


def calc_alpha_diversity(taxa_counts: Dict[str, int]) -> Dict[str, float]:
    """计算生态学标准 Alpha 多样性指标。"""
    total = sum(taxa_counts.values())
    if total == 0:
        return {"richness": 0, "shannon": 0.0, "simpson": 0.0, "chao1": 0.0, "evenness": 0.0}

    proportions = [c / total for c in taxa_counts.values()]
    richness = len(taxa_counts)
    shannon = -sum(p * math.log(p) for p in proportions if p > 0)
    simpson = 1.0 - sum(p ** 2 for p in proportions)
    evenness = (shannon / math.log(richness)) if richness > 1 else 1.0

    singletons = sum(1 for c in taxa_counts.values() if c == 1)
    doubletons = sum(1 for c in taxa_counts.values() if c == 2)
    if doubletons > 0:
        chao1 = richness + (singletons * (singletons - 1)) / (2 * (doubletons + 1))
    else:
        chao1 = richness + (singletons * (singletons - 1)) / 2.0

    return {
        "richness": richness,
        "shannon": round(shannon, 3),
        "simpson": round(simpson, 3),
        "evenness": round(evenness, 3),
        "chao1": round(chao1, 2),
    }


def calc_beta_diversity(samples_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """计算 Bray-Curtis 距离矩阵与 PCoA 降维坐标。"""
    if len(samples_data) < 2:
        return {"pcoa_points": [], "var_pc1": 0.0, "var_pc2": 0.0, "matrix": []}

    all_taxa = sorted({
        d["taxon"]
        for s in samples_data
        for d in s.get("norm_result", {}).get("details", [])
    })
    if not all_taxa:
        return {"pcoa_points": [], "var_pc1": 0.0, "var_pc2": 0.0, "matrix": []}

    taxa_idx = {t: i for i, t in enumerate(all_taxa)}
    n_samples = len(samples_data)
    abund_mat = np.zeros((n_samples, len(all_taxa)))
    for i, s in enumerate(samples_data):
        for d in s.get("norm_result", {}).get("details", []):
            t = d["taxon"]
            if t in taxa_idx:
                abund_mat[i, taxa_idx[t]] = d.get("norm_pct", 0.0)

    dist_mat = np.zeros((n_samples, n_samples))
    for i in range(n_samples):
        for j in range(i + 1, n_samples):
            u = abund_mat[i]
            v = abund_mat[j]
            denom = np.sum(u + v)
            bc = (np.sum(np.abs(u - v)) / denom) if denom > 0 else 0.0
            dist_mat[i, j] = bc
            dist_mat[j, i] = bc

    A = -0.5 * (dist_mat ** 2)
    H = np.eye(n_samples) - np.ones((n_samples, n_samples)) / n_samples
    B = H.dot(A).dot(H)

    eigvals, eigvecs = np.linalg.eigh(B)
    sort_idx = np.argsort(eigvals)[::-1]
    eigvals = eigvals[sort_idx]
    eigvecs = eigvecs[:, sort_idx]

    pos_mask = eigvals > 0
    total_pos = np.sum(eigvals[pos_mask]) if np.sum(pos_mask) > 0 else 1.0

    var_pc1 = float(eigvals[0] / total_pos * 100) if len(eigvals) > 0 and eigvals[0] > 0 else 0.0
    var_pc2 = float(eigvals[1] / total_pos * 100) if len(eigvals) > 1 and eigvals[1] > 0 else 0.0

    pc1 = eigvecs[:, 0] * np.sqrt(max(0, eigvals[0]))
    pc2 = (eigvecs[:, 1] * np.sqrt(max(0, eigvals[1]))) if len(eigvals) > 1 else np.zeros(n_samples)

    pcoa_points = [
        {
            "sample_name": s["sample_name"],
            "pc1": round(float(pc1[i]), 4),
            "pc2": round(float(pc2[i]), 4),
            "total_reads": s.get("total_reads", 0),
        }
        for i, s in enumerate(samples_data)
    ]

    return {
        "pcoa_points": pcoa_points,
        "var_pc1": round(var_pc1, 2),
        "var_pc2": round(var_pc2, 2),
        "distance_matrix": np.round(dist_mat, 3).tolist(),
    }


def calc_global_taxa_overview(samples_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """全批次物种全局汇总（真实物种优先排序，低频噪声与 Other 合集沉底）。"""
    agg = defaultdict(
        lambda: {"raw_count": 0, "norm_count": 0.0, "sample_hits": 0, "gcn_mean": 1.0, "is_noise": False}
    )
    total_norm = 0.0
    total_raw = 0

    for s in samples_data:
        for d in s.get("norm_result", {}).get("details", []):
            taxon = d["taxon"]
            is_noise = bool(d.get("is_noise")) or RrnDBService.is_noise_or_other(taxon)
            agg[taxon]["raw_count"] += d["raw_count"]
            agg[taxon]["norm_count"] += d["norm_count"]
            agg[taxon]["sample_hits"] += 1
            agg[taxon]["gcn_mean"] = d.get("gcn_mean", 1.0)
            agg[taxon]["is_noise"] = is_noise
            total_norm += d["norm_count"]
            total_raw += d["raw_count"]

    res = [
        {
            "taxon": taxon,
            "raw_count": info["raw_count"],
            "raw_pct": round(info["raw_count"] / total_raw * 100.0, 2) if total_raw > 0 else 0.0,
            "norm_pct": round(info["norm_count"] / total_norm * 100.0, 2) if total_norm > 0 else 0.0,
            "sample_frequency": f"{info['sample_hits']}/{len(samples_data)}",
            "gcn_mean": info["gcn_mean"],
            "is_noise": info["is_noise"],
        }
        for taxon, info in agg.items()
    ]
    res.sort(key=lambda x: (-1 if x.get("is_noise") else 0, x["norm_pct"]), reverse=True)
    return res
