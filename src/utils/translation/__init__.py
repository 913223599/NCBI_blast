"""
翻译模块初始化文件
"""

from .biology_translator import get_biology_translator, get_global_biology_translator
from .blast_result_translator import get_blast_result_translator
from .qwen_translator import get_qwen_translator
from .translation_data_manager import get_translation_data_manager

__all__ = [
    'get_biology_translator',
    'get_global_biology_translator',
    'get_qwen_translator',
    'get_translation_data_manager',
    'get_blast_result_translator'
]