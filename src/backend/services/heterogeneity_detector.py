# -*- coding: utf-8 -*-
"""
16S rRNA 操纵子多拷贝基因组内异质性 (Intragenomic Heterogeneity) 智能诊断器
通过化学计量比分析、整数比逼近残差及 rrnDB 基因组操纵子拷贝数上限匹配，
自动判定多物种共现是属于同一菌体内部的拷贝变异还是多物种真实共存。
"""
import re
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict

from .rrndb_service import get_rrndb_service


class OperonHeterogeneityDetector:
    """16S 操纵子基因组内异质性智能诊断器"""

    def __init__(self, max_ratio_denominator: int = 15, max_residual: float = 0.08):
        """
        :param max_ratio_denominator: 最大操纵子拷贝数测试上限 (细菌最高一般不超过 15 个拷贝)
        :param max_residual: 整数化学计量比拟合最大容许相对残差 (默认 8%)
        """
        self.max_ratio_denominator = max_ratio_denominator
        self.max_residual = max_residual
        self.rrndb = get_rrndb_service()

    def diagnose_sample(
        self,
        taxa_counts: Dict[str, int],
        min_dominance_pct: float = 5.0
    ) -> List[Dict[str, Any]]:
        """
        对单个样本内的物种结构进行操纵子异质性诊断
        :param taxa_counts: 物种计数字典
        :param min_dominance_pct: 参与诊断的优势物种最小相对丰度占比 (默认 >= 5%)
        :return: 诊断报告列表
        """
        total_reads = sum(taxa_counts.values())
        if total_reads <= 0:
            return []

        # 1. 提取相对丰度达到阈值的物种并提取属名
        genus_groups: Dict[str, List[Tuple[str, int, float]]] = defaultdict(list)
        for taxon, count in taxa_counts.items():
            if taxon.startswith("Other"):
                continue
            pct = (count / total_reads) * 100.0
            if pct < min_dominance_pct:
                continue

            genus = self._extract_genus(taxon)
            if genus:
                genus_groups[genus].append((taxon, count, pct))

        advisories: List[Dict[str, Any]] = []

        # 2. 针对同属内出现两个及以上优势物种的情况进行异质性建模
        for genus, species_list in genus_groups.items():
            if len(species_list) < 2:
                continue

            # 按 Reads 降序排列，取前两大优势同属物种
            species_list.sort(key=lambda x: x[1], reverse=True)
            sp1, count1, pct1 = species_list[0]
            sp2, count2, pct2 = species_list[1]

            # 检索该属在 rrnDB 中的生物学拷贝数特征
            gcn_info = self.rrndb.get_gcn(genus)
            known_mean_gcn = gcn_info.get("mean", 4.0)
            known_median_gcn = gcn_info.get("median", 4.0)

            # 进行化学计量整数比拟合
            fit_result = self._fit_integer_ratio(count1, count2, max_sum=self.max_ratio_denominator)

            # 综合判断置信度与结论
            diagnosis = self._evaluate_confidence(
                sp1=sp1,
                count1=count1,
                pct1=pct1,
                sp2=sp2,
                count2=count2,
                pct2=pct2,
                genus=genus,
                known_median=known_median_gcn,
                known_mean=known_mean_gcn,
                fit=fit_result
            )
            advisories.append(diagnosis)

        return advisories

    def _fit_integer_ratio(self, c1: int, c2: int, max_sum: int = 15) -> Dict[str, Any]:
        """寻找最佳拟合的最简整数比 a : b (1 <= a+b <= max_sum)"""
        total = c1 + c2
        if total <= 0:
            return {"a": 1, "b": 1, "ratio_str": "1:1", "residual": 1.0, "sum": 2}

        observed_p1 = c1 / total
        best_a, best_b = 1, 1
        best_residual = 1.0

        for s in range(2, max_sum + 1):
            for a in range(1, s):
                b = s - a
                model_p1 = a / s
                residual = abs(observed_p1 - model_p1)
                if residual < best_residual:
                    best_residual = residual
                    best_a = a
                    best_b = b

        return {
            "a": best_a,
            "b": best_b,
            "ratio_str": f"{best_a}:{best_b}",
            "residual": round(best_residual, 4),
            "sum": best_a + best_b,
            "observed_ratio": round(c1 / max(1, c2), 2)
        }

    def _evaluate_confidence(
        self,
        sp1: str,
        count1: int,
        pct1: float,
        sp2: str,
        count2: int,
        pct2: float,
        genus: str,
        known_median: float,
        known_mean: float,
        fit: Dict[str, Any]
    ) -> Dict[str, Any]:
        """评估属于操纵子异质性的置信度"""
        fitted_sum = fit["sum"]
        residual = fit["residual"]

        # 生物学拷贝数一致性评估
        gcn_diff = abs(fitted_sum - known_median)
        gcn_consistent = gcn_diff <= 2.5 or (fitted_sum <= known_median + 2)

        score = 0
        evidence_points = []

        # 1. 整数比吻合度打分
        if residual <= 0.03:
            score += 45
            evidence_points.append(f"Reads 实测比例 ({fit['observed_ratio']}:1) 与理论整数比 {fit['ratio_str']} 高度吻合 (残差 {residual*100:.1f}%)")
        elif residual <= 0.06:
            score += 30
            evidence_points.append(f"Reads 实测比例与理论整数比 {fit['ratio_str']} 较为吻合 (残差 {residual*100:.1f}%)")
        else:
            score += 10
            evidence_points.append(f"Reads 比例拟合整数比 {fit['ratio_str']} (残差 {residual*100:.1f}%)")

        # 2. rrnDB 拷贝数上限打分
        if gcn_diff <= 1.0:
            score += 40
            evidence_points.append(f"拟合总拷贝数 ({fitted_sum}) 与 {genus} 属已知典型拷贝数 ({known_median_gcn_str(known_median)}) 完全契合")
        elif gcn_diff <= 2.5:
            score += 25
            evidence_points.append(f"拟合总拷贝数 ({fitted_sum}) 处于 {genus} 属正常拷贝数分布范围内 (典型中位数: {known_median})")
        else:
            score += 5
            evidence_points.append(f"拟合总拷贝数 ({fitted_sum}) 与已知典型中位数 ({known_median}) 略有偏差")

        # 3. 相对丰度高主导性打分 (两者合计超过 85% 强提示单菌背景)
        pair_sum_pct = pct1 + pct2
        if pair_sum_pct >= 85.0:
            score += 15
            evidence_points.append(f"两物种合计占比高达 {pair_sum_pct:.1f}%，极强提示为单菌落测序背景")

        if score >= 75:
            level = "high"
            conclusion = "高度疑似同菌 16S 操纵子异质性 (Intragenomic Heterogeneity)"
            suggestion = f"建议在分析中将 '{sp1}' 与 '{sp2}' 视为同一宿主菌的异质拷贝合并统计"
        elif score >= 50:
            level = "medium"
            conclusion = "疑似同菌 16S 操纵子异质性或极近缘种共存"
            suggestion = "比例符合操纵子理论分布，建议结合近缘系统发育树进一步验证"
        else:
            level = "low"
            conclusion = "倾向为独立多物种共存 (可能存在真实混菌)"
            suggestion = "比例与典型操纵子拷贝数存在偏差，优先作为共生物种对待"

        return {
            "genus": genus,
            "taxa_pair": [sp1, sp2],
            "counts": [count1, count2],
            "percentages": [round(pct1, 2), round(pct2, 2)],
            "fitted_ratio": fit["ratio_str"],
            "fitted_operon_sum": fitted_sum,
            "known_gcn_median": known_median,
            "residual_pct": round(residual * 100, 2),
            "confidence_score": score,
            "confidence_level": level,
            "conclusion": conclusion,
            "suggestion": suggestion,
            "evidence": evidence_points
        }

    @staticmethod
    def _extract_genus(taxon: str) -> Optional[str]:
        """从物种全名提取属名"""
        m = re.match(r"^([A-Z][a-z]+)", taxon)
        return m.group(1) if m else None


def known_median_gcn_str(val: float) -> str:
    return f"{int(val)}" if val.is_integer() else f"{val:.1f}"
