# -*- coding: utf-8 -*-
"""
种加词与生物学术语规范化校对器 (Epithet Corrector)
职责：
1. 纠正机器翻译中粗糙直译的种加词
2. 将规范的种加词与属名组合构建标准学名译名
"""

from typing import Tuple, Optional
from .taxonomy_kb import TaxonomyKnowledgeBase

class EpithetCorrector:
    """
    种加词校对器
    """

    def __init__(self):
        self.epithet_map = TaxonomyKnowledgeBase.EPITHET_STANDARD_MAP
        self.genus_map = TaxonomyKnowledgeBase.GENUS_STANDARD_MAP

    def correct_epithet_translation(self, english: str, chinese: str) -> Tuple[str, bool, Optional[str]]:
        """
        根据双名法种加词与属名组合纠偏
        """
        if not english or not chinese:
            return chinese, False, None

        parts = english.strip().split()
        if len(parts) < 2:
            return chinese, False, None

        genus_part = parts[0]
        epithet_part = parts[1].lower()

        # 特例规则库优化
        if genus_part == "Macrococcus" and "caseolytic" in epithet_part:
            if chinese != "溶酪大球菌":
                return "溶酪大球菌", True, f"标准学名校准: {chinese} -> 溶酪大球菌"

        if genus_part == "Aeromonas" and "aquarior" in epithet_part:
            if chinese != "水族箱气单胞菌" and chinese != "水族馆气单胞菌":
                return "水族箱气单胞菌", True, f"标准学名校准: {chinese} -> 水族箱气单胞菌"

        if genus_part == "Arcobacter" and "butzleri" in epithet_part:
            if chinese != "布氏弓形杆菌":
                return "布氏弓形杆菌", True, f"标准学名校准: {chinese} -> 布氏弓形杆菌"

        if genus_part == "Pseudomonas" and "arcuscaelestis" in epithet_part:
            if chinese != "天青假单胞菌":
                return "天青假单胞菌", True, f"标准学名校准: {chinese} -> 天青假单胞菌"

        if genus_part == "Clostridium" and epithet_part == "faecium":
            if chinese != "粪肠球菌":
                return "粪肠球菌", True, f"学名校准: {chinese} -> 粪肠球菌"

        if genus_part == "Clostridium" and "botulinum" in epithet_part:
            if "肉毒杆菌" in chinese:
                new_chi = chinese.replace("肉毒杆菌", "肉毒梭菌")
                return new_chi, True, f"规范梭菌译名: {chinese} -> {new_chi}"

        # 通用种加词修正
        if epithet_part in self.epithet_map and genus_part in self.genus_map:
            std_epithet = self.epithet_map[epithet_part]
            _, std_species_tail, _ = self.genus_map[genus_part]
            
            # 如果中文翻译中包含明显错翻的词根（如 巨球菌、弓形菌 等）且缺失标准种加词
            if genus_part == "Macrococcus" and "巨球菌" in chinese:
                corrected = f"{std_epithet}{std_species_tail}"
                return corrected, True, f"纠正大球菌种名: {chinese} -> {corrected}"
            if genus_part == "Arcobacter" and "弓形菌" in chinese:
                corrected = f"{std_epithet}{std_species_tail}"
                return corrected, True, f"纠正弓形杆菌种名: {chinese} -> {corrected}"

        return chinese, False, None
