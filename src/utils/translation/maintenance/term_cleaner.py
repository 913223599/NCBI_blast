# -*- coding: utf-8 -*-
"""
生物学术语基础清洗器 (Term Cleaner)
职责：
1. 识别垃圾与测试脏数据
2. 消除机翻重复叠词
3. 规范标点符号与特殊字符
4. 清洗通用未培养与环境生物条目
"""

import re
from typing import Tuple, Optional
from .taxonomy_kb import TaxonomyKnowledgeBase

class TermCleaner:
    """
    词条清洗器
    """

    @staticmethod
    def is_junk_or_test_entry(english: str) -> bool:
        """判断是否为测试脏数据"""
        eng_lower = english.strip().lower()
        if eng_lower.startswith("test_") or eng_lower == "test" or "test_entry" in eng_lower:
            return True
        if len(eng_lower) <= 1:
            return True
        return False

    @staticmethod
    def clean_chinese_text(english: str, chinese: str) -> Tuple[str, bool]:
        """
        清洗中文翻译文本
        返回: (清洗后的中文, 是否发生了修改)
        """
        if not chinese:
            return chinese, False

        original_chinese = chinese
        cleaned = chinese.strip()

        # 1. 通用环境/未培养映射优先
        eng_lower = english.strip().lower()
        if eng_lower in TaxonomyKnowledgeBase.UNCULTURED_MAP:
            return TaxonomyKnowledgeBase.UNCULTURED_MAP[eng_lower], True

        # 2. 消除叠词
        for pattern, replacement in TaxonomyKnowledgeBase.DOUBLE_WORD_PATTERNS:
            if pattern in cleaned:
                cleaned = cleaned.replace(pattern, replacement)

        # 3. 标点符号规范化
        cleaned = cleaned.replace("sp。", "sp.").replace("aff。", "aff.").replace("var。", "var.").replace("subsp。", "subsp.")
        # 移除末尾多余的句号或空格
        cleaned = re.sub(r'[。；;，,\s]+$', '', cleaned)

        # 4. 修复特定的英文混杂（如带 sp. 的格式规范化）
        if cleaned.endswith(" sp") and not cleaned.endswith(" sp."):
            cleaned = cleaned + "."

        return cleaned, cleaned != original_chinese

    @staticmethod
    def handle_untranslated(english: str, chinese: str) -> Optional[str]:
        """
        如果未翻译 (如中文等于英文)，尝试给出基础翻译或规范化格式
        """
        eng_strip = english.strip()
        chi_strip = chinese.strip()
        if chi_strip.lower() == eng_strip.lower():
            # 常见 "XXXviridae sp." 等病毒科属未定种
            if eng_strip.endswith("viridae sp.") or eng_strip.endswith("viridae sp"):
                base_fam = eng_strip.split()[0]
                return f"{base_fam} 病毒科未定种"
            if eng_strip.endswith("viricetes sp."):
                base_cls = eng_strip.split()[0]
                return f"{base_cls} 病毒纲未定种"
            if eng_strip.endswith("virales sp."):
                base_ord = eng_strip.split()[0]
                return f"{base_ord} 病毒目未定种"
            if eng_strip.endswith("viricota sp."):
                base_phy = eng_strip.split()[0]
                return f"{base_phy} 病毒门未定种"
            if eng_strip.endswith("viria sp."):
                base_rea = eng_strip.split()[0]
                return f"{base_rea} 病毒界未定种"
            if eng_strip.endswith(" sp.") or eng_strip.endswith(" sp"):
                base_name = eng_strip.split()[0]
                return f"{base_name} 未定种"
        return None
