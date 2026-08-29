# -*- coding: utf-8 -*-
"""
双名法属名与种名一致性校正器 (Genus Aligner)
职责：
1. 解析学名中的属名与种加词
2. 根据权威分类库校对种名中的属名翻译
3. 修正属名漏字、误翻或混杂
"""

import re
from typing import Tuple, Optional
from .taxonomy_kb import TaxonomyKnowledgeBase

class GenusAligner:
    """
    属名对齐与校正器
    """

    def __init__(self):
        self.genus_map = TaxonomyKnowledgeBase.GENUS_STANDARD_MAP

    def align_species_genus(self, english: str, chinese: str) -> Tuple[str, bool, Optional[str]]:
        """
        校对种名翻译中的属名部分
        返回: (校正后的中文, 是否已校正, 校正说明)
        """
        if not english or not chinese:
            return chinese, False, None

        # 保护特定认可的通用俗名或特殊命名
        if english.startswith("Escherichia coli") and "大肠杆菌" in chinese:
            return chinese, False, None
        if english.startswith("Clostridium faecium") and "粪肠球菌" in chinese:
            return chinese, False, None


        parts = english.strip().split()
        if len(parts) < 2:
            # 纯属名条目
            if len(parts) == 1 and parts[0] in self.genus_map:
                std_genus_name, _, _ = self.genus_map[parts[0]]
                if chinese != std_genus_name and ("属" not in chinese or parts[0] in ("Macrococcus", "Arcobacter", "Pseudomonas", "Aeromonas")):
                    return std_genus_name, True, f"规范属名: {chinese} -> {std_genus_name}"
            return chinese, False, None

        genus_name = parts[0]
        if genus_name not in self.genus_map:
            return chinese, False, None

        std_genus_full, std_species_tail, wrong_patterns = self.genus_map[genus_name]

        # 检查当前中文翻译是否已经正确包含标准种名词尾
        if std_species_tail in chinese:
            return chinese, False, None

        original_chinese = chinese
        modified_chinese = chinese

        # 1. 优先匹配已知的严重错误模式精准替换
        replaced = False
        for wp in wrong_patterns:
            if wp in modified_chinese:
                # 避免错误替换，例如把 "假单胞菌" 里的 "单胞菌" 替换
                if wp == "单胞菌" and ("假单胞菌" in modified_chinese or "气单胞菌" in modified_chinese):
                    continue
                if wp == "杆菌" and ("芽孢杆菌" in modified_chinese or "弓形杆菌" in modified_chinese or "双歧杆菌" in modified_chinese):
                    continue
                if wp == "球菌" and ("大球菌" in modified_chinese or "微球菌" in modified_chinese or "葡萄球菌" in modified_chinese):
                    continue

                modified_chinese = modified_chinese.replace(wp, std_species_tail)
                replaced = True
                break

        # 2. 如果没有命中已知错误，但以泛称结尾进行纠正
        if not replaced:
            if modified_chinese.endswith("菌属"):
                prefix = modified_chinese[:-2]
                modified_chinese = prefix + std_species_tail
                replaced = True
            elif modified_chinese.endswith("细菌"):
                prefix = modified_chinese[:-2]
                modified_chinese = prefix + std_species_tail
                replaced = True
            elif modified_chinese.endswith("杆菌") and std_species_tail != "杆菌":
                prefix = modified_chinese[:-2]
                modified_chinese = prefix + std_species_tail
                replaced = True
            elif modified_chinese.endswith("球菌") and std_species_tail != "球菌":
                prefix = modified_chinese[:-2]
                modified_chinese = prefix + std_species_tail
                replaced = True
            elif modified_chinese.endswith("菌") and not modified_chinese.endswith(std_species_tail):
                prefix = modified_chinese[:-1]
                modified_chinese = prefix + std_species_tail
                replaced = True

        if replaced and modified_chinese != original_chinese:
            return modified_chinese, True, f"校准属名后缀: {original_chinese} -> {modified_chinese}"

        return original_chinese, False, None
