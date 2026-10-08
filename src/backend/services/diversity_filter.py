# -*- coding: utf-8 -*-
"""
16S 多样性分析测序噪声与低频伪物种过滤器
依据相对丰度截断阈值和单读段过滤规则剔除三代测序随机 InDel/错配噪音，
并重新校正生态学 Alpha 多样性指标。
"""
import math
from typing import Dict, Any, List, Tuple, Optional


class DiversityNoiseFilter:
    """扩增子测序低频噪声与孤儿物种过滤器"""

    def __init__(
        self,
        min_rel_abundance: float = 0.5,
        min_reads_count: int = 2,
        preserve_other: bool = True
    ):
        """
        :param min_rel_abundance: 相对丰度截断阈值百分比 (例如 0.5 表示低于 0.5% 的物种视为疑似噪音)
        :param min_reads_count: 最小绝对 Reads 计数 (例如 2 表示 <=2 条 Reads 的孤儿读段视为疑似噪音)
        :param preserve_other: 是否将过滤掉的噪声 Reads 计入 Other 分组以维持总 Reads 数平衡
        """
        self.min_rel_abundance = float(min_rel_abundance)
        self.min_reads_count = int(min_reads_count)
        self.preserve_other = bool(preserve_other)

    def filter_taxa(
        self,
        taxa_counts: Dict[str, int],
        total_classified: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        对单样本的物种计数进行降噪过滤与评估
        """
        if not taxa_counts:
            return {
                "filtered_counts": {},
                "removed_taxa": [],
                "noise_reads": 0,
                "noise_taxa_count": 0,
                "raw_richness": 0,
                "clean_richness": 0,
                "alpha_raw": self._calc_alpha({}),
                "alpha_clean": self._calc_alpha({})
            }

        total_reads = total_classified or sum(taxa_counts.values())
        if total_reads <= 0:
            return {
                "filtered_counts": {},
                "removed_taxa": [],
                "noise_reads": 0,
                "noise_taxa_count": 0,
                "raw_richness": 0,
                "clean_richness": 0,
                "alpha_raw": self._calc_alpha({}),
                "alpha_clean": self._calc_alpha({})
            }

        filtered_counts: Dict[str, int] = {}
        removed_taxa: List[Dict[str, Any]] = []
        noise_reads = 0

        for taxon, count in taxa_counts.items():
            pct = (count / total_reads) * 100.0
            is_noise = False
            reasons = []

            if count <= self.min_reads_count:
                is_noise = True
                reasons.append(f"Reads数低于阈值 (当前 {count} 条 <= 最小阈值 {self.min_reads_count} 条)")
            if pct < self.min_rel_abundance:
                is_noise = True
                reasons.append(f"相对丰度低于阈值 (当前 {pct:.2f}% < 最小阈值 {self.min_rel_abundance:.2f}%)")

            if is_noise:
                removed_taxa.append({
                    "taxon": taxon,
                    "count": count,
                    "rel_pct": round(pct, 3),
                    "reason": "; ".join(reasons)
                })
                noise_reads += count
            else:
                filtered_counts[taxon] = count

        if self.preserve_other and noise_reads > 0:
            filtered_counts["Other (低频测序噪声)"] = noise_reads

        # 分别计算原始与过滤后的生态学指标 (计算 Alpha 时不应计入人工归类的 Other 分组)
        clean_for_alpha = {k: v for k, v in filtered_counts.items() if not k.startswith("Other")}
        alpha_raw = self._calc_alpha(taxa_counts)
        alpha_clean = self._calc_alpha(clean_for_alpha)

        return {
            "filtered_counts": filtered_counts,
            "removed_taxa": removed_taxa,
            "noise_reads": noise_reads,
            "noise_taxa_count": len(removed_taxa),
            "raw_richness": len(taxa_counts),
            "clean_richness": len(clean_for_alpha),
            "alpha_raw": alpha_raw,
            "alpha_clean": alpha_clean
        }

    @staticmethod
    def _calc_alpha(taxa_counts: Dict[str, int]) -> Dict[str, float]:
        """计算生态学标准 Alpha 多样性指标"""
        total = sum(taxa_counts.values())
        if total == 0:
            return {"richness": 0, "shannon": 0.0, "simpson": 0.0, "chao1": 0.0, "evenness": 0.0}

        proportions = [c / total for c in taxa_counts.values()]
        richness = len(taxa_counts)

        # Shannon-Wiener 指数: H = -sum(p * ln(p))
        shannon = -sum(p * math.log(p) for p in proportions if p > 0)

        # Gini-Simpson 指数: 1 - sum(p^2)
        simpson = 1.0 - sum(p ** 2 for p in proportions)

        # Pielou 均匀度: J = H / ln(S)
        evenness = (shannon / math.log(richness)) if richness > 1 else 1.0

        # Chao1 丰富度估计量
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
            "chao1": round(chao1, 2)
        }
