"""
BLAST结果翻译模块
用于处理和翻译BLAST结果中的物种、属名和菌株信息
基于统一的 TranslationDataManager SQLite 词库
"""

from typing import Optional
from .translation_data_manager import get_translation_data_manager


class BlastResultTranslator:
    """
    BLAST结果翻译器
    专门用于处理BLAST结果中物种、属名和菌株的翻译
    """
    
    def __init__(self, data_file: Optional[str] = None):
        self.data_manager = get_translation_data_manager()
    
    def translate_species(self, species_english: str) -> str:
        """翻译物种名称"""
        if not isinstance(species_english, str) or not species_english.strip():
            return species_english or ""
        
        result = self.data_manager.get_translation(species_english.strip(), category="species")
        return result if result else species_english
    
    def translate_genus(self, genus_english: str) -> str:
        """翻译属名"""
        if not isinstance(genus_english, str) or not genus_english.strip():
            return genus_english or ""
        
        result = self.data_manager.get_translation(genus_english.strip(), category="genus")
        return result if result else genus_english
    
    def translate_strain(self, strain_english: str) -> str:
        """翻译菌株名称"""
        if not isinstance(strain_english, str) or not strain_english.strip():
            return strain_english or ""
        
        result = self.data_manager.get_translation(strain_english.strip(), category="strain")
        return result if result else strain_english


def get_blast_result_translator(data_file: Optional[str] = None) -> BlastResultTranslator:
    """获取BLAST结果翻译器实例"""
    return BlastResultTranslator(data_file)