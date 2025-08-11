"""
翻译模块初始化文件
"""

from .biology_translator import get_biology_translator
from .qwen_translator import get_qwen_translator
from .special_pattern_translator import get_special_pattern_translator
from .species_translator import get_species_translator
from .translation_data_manager import get_translation_data_manager
from .translation_quality_checker import get_translation_quality_checker

__all__ = [
    'get_biology_translator',
    'get_qwen_translator',
    'get_special_pattern_translator',
    'get_species_translator',
    'get_translation_data_manager',
    'get_translation_quality_checker'
]