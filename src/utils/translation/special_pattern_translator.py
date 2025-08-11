"""
特殊模式翻译模块
用于处理生物学专业术语中的特殊模式翻译
"""

import re
from typing import Optional


class SpecialPatternTranslator:
    """
    特殊模式翻译器
    专门用于处理生物学专业术语中的特殊模式翻译
    """
    
    def __init__(self, translation_data_manager=None):
        """
        初始化特殊模式翻译器
        
        Args:
            translation_data_manager: 翻译数据管理器实例
        """
        self.translation_data_manager = translation_data_manager

    def translate_special_patterns(self, text: str) -> str:
        """
        处理特殊模式的翻译
        
        Args:
            text (str): 待翻译的文本
            
        Returns:
            str: 翻译后的文本，如果无法翻译则返回原文
        """
        if not self.translation_data_manager:
            return text
            
        # 定义特殊处理模式
        special_patterns = [
            # 菌株模式: "Aeromonas veronii strain LTFS6 16S ribosomal RNA gene, partial sequence"
            {
                'pattern': r'([A-Z][a-z]+(?:\s+[a-z]+)?)\s+(strain\s+[A-Za-z0-9\-._]+)\s+(.+)',
                'prefix': '',
                'groups': ['species', 'strain', 'remaining']
            },
            # 分离株模式: "Staphylococcus epidermidis partial 16S rRNA gene, isolate OCOB16"
            {
                'pattern': r'([A-Z][a-z]+(?:\s+[a-z]+)?)\s+(.+)\s*,\s*(isolate\s+[A-Za-z0-9\-._]+)',
                'prefix': '',
                'groups': ['species', 'gene', 'isolate']
            },
            # 属名(sp.)和菌株模式: "Aeromonas sp. strain J16OP4 16S ribosomal RNA gene, partial sequence"
            {
                'pattern': r'([A-Z][a-z]+ sp\.)\s+(strain\s+[A-Za-z0-9\-._]+)\s+(.+)',
                'prefix': '',
                'groups': ['species', 'strain', 'remaining']
            },
            # 克隆模式: "Uncultured Bacillus sp. clone CBR4 16S ribosomal RNA gene, partial sequence"
            {
                'pattern': r'([Uu]ncultured\s+)?([A-Z][a-z]+(?:\s+[a-z]+)?)\s+(clone\s+[A-Za-z0-9\-._]+)\s+(.+)',
                'prefix': 'uncultured',
                'groups': ['uncultured', 'species', 'clone', 'remaining']
            }
        ]
        
        # 尝试匹配特殊模式
        for pattern_info in special_patterns:
            match = re.match(pattern_info['pattern'], text, re.IGNORECASE)
            if match:
                groups = pattern_info['groups']
                translations = {}
                
                # 处理每个匹配组
                for i, group_name in enumerate(groups):
                    if i < len(match.groups()):
                        group_value = match.group(i + 1)
                        if group_value:
                            if group_name in ['species', 'gene']:
                                # 翻译菌种名或基因信息
                                translation = self.translation_data_manager.get_translation(group_value)
                                if not translation:
                                    if group_name == 'species':
                                        # 导入物种翻译器并使用
                                        try:
                                            from .species_translator import get_species_translator
                                            species_translator = get_species_translator(self.translation_data_manager)
                                            translation = species_translator.translate_species_name(group_value)
                                        except ImportError:
                                            # 使用剩余文本翻译方法
                                            translation = self._translate_remaining_text(group_value)
                                    else:
                                        translation = self._translate_remaining_text(group_value)
                                translations[group_name] = translation
                            elif group_name in ['strain', 'isolate', 'clone']:
                                # 处理菌株、分离株、克隆信息，使用专门的翻译方法
                                if group_name == 'strain':
                                    translations[group_name] = self._translate_strain_name(group_value)
                                elif group_name == 'isolate':
                                    translations[group_name] = self._translate_isolate_name(group_value)
                                elif group_name == 'clone':
                                    translations[group_name] = self._translate_clone_name(group_value)
                            elif group_name == 'uncultured':
                                # 处理Uncultured前缀
                                translations[group_name] = "未培养" if group_value else ""
                            elif group_name == 'remaining':
                                # 翻译剩余部分
                                translations[group_name] = self._translate_remaining_text(group_value)
                
                # 组合翻译结果
                result_parts = []
                if translations.get('uncultured'):
                    result_parts.append(translations['uncultured'])
                if translations.get('species'):
                    result_parts.append(translations['species'])
                if translations.get('strain'):
                    result_parts.append(translations['strain'])
                if translations.get('gene'):
                    result_parts.append(translations['gene'])
                if translations.get('isolate'):
                    result_parts.append(translations['isolate'])
                if translations.get('clone'):
                    result_parts.append(translations['clone'])
                if translations.get('remaining'):
                    result_parts.append(translations['remaining'])
                
                if result_parts and all(part for part in result_parts if part is not None):
                    return " ".join(result_parts).strip()
        
        # 如果没有匹配到特殊模式，返回原文
        return text

    def _translate_remaining_text(self, text: str) -> str:
        """
        翻译文本的剩余部分（菌种和菌株之后的部分）
        
        Args:
            text (str): 需要翻译的文本部分
            
        Returns:
            str: 翻译后的文本部分
        """
        if not self.translation_data_manager:
            return text
            
        # 定义常见术语的翻译映射
        term_mapping = {
            '16S ribosomal RNA gene': '16S核糖体RNA基因',
            '16S ribosomal RNA': '16S核糖体RNA',
            'partial sequence': '部分序列',
            'complete genome': '完整基因组',
            'rRNA gene': '核糖体RNA基因',
            'gene': '基因',
            'RNA': '核糖体RNA'
        }
        
        # 尝试直接匹配整个文本
        if text in term_mapping:
            return term_mapping[text]
            
        # 尝试从本地数据管理器获取翻译
        direct_translation = self.translation_data_manager.get_translation(text)
        if direct_translation:
            return direct_translation
            
        # 如果是逗号分隔的短语，尝试分别翻译
        if ', ' in text:
            parts = text.split(', ')
            translated_parts = []
            for part in parts:
                if part in term_mapping:
                    translated_parts.append(term_mapping[part])
                else:
                    part_translation = self.translation_data_manager.get_translation(part)
                    if part_translation:
                        translated_parts.append(part_translation)
                    else:
                        translated_parts.append(part)  # 无法翻译则保持原样
            return ', '.join(translated_parts)
            
        # 无法翻译，返回原文
        return text

    def _translate_strain_name(self, strain_name: str) -> str:
        """
        翻译菌株名称
        
        Args:
            strain_name (str): 英文菌株名称
            
        Returns:
            str: 翻译后的菌株名称
        """
        if not self.translation_data_manager:
            return strain_name
            
        # 常见的strain前缀翻译
        strain_prefix_mapping = {
            "strain": "菌株",
        }
        
        # 检查是否有预定义翻译
        translation = self.translation_data_manager.get_translation(strain_name)
        if translation:
            return translation
            
        # 尝试处理"strain XXX"格式
        for prefix, chinese_prefix in strain_prefix_mapping.items():
            if strain_name.lower().startswith(prefix):
                # 提取菌株编号/名称部分
                strain_id = strain_name[len(prefix):].strip()
                return f"{chinese_prefix} {strain_id}"
                
        # 默认返回原名
        return strain_name

    def _translate_isolate_name(self, isolate_name: str) -> str:
        """
        翻译分离株名称
        
        Args:
            isolate_name (str): 英文分离株名称
            
        Returns:
            str: 翻译后的分离株名称
        """
        if not self.translation_data_manager:
            return isolate_name
            
        # 常见的isolate前缀翻译
        isolate_prefix_mapping = {
            "isolate": "分离株",
        }
        
        # 检查是否有预定义翻译
        translation = self.translation_data_manager.get_translation(isolate_name)
        if translation:
            return translation
            
        # 尝试处理"isolate XXX"格式
        for prefix, chinese_prefix in isolate_prefix_mapping.items():
            if isolate_name.lower().startswith(prefix):
                # 提取分离株编号/名称部分
                isolate_id = isolate_name[len(prefix):].strip()
                return f"{chinese_prefix} {isolate_id}"
                
        # 默认返回原名
        return isolate_name

    def _translate_clone_name(self, clone_name: str) -> str:
        """
        翻译克隆名称
        
        Args:
            clone_name (str): 英文克隆名称
            
        Returns:
            str: 翻译后的克隆名称
        """
        if not self.translation_data_manager:
            return clone_name
            
        # 常见的clone前缀翻译
        clone_prefix_mapping = {
            "clone": "克隆",
        }
        
        # 检查是否有预定义翻译
        translation = self.translation_data_manager.get_translation(clone_name)
        if translation:
            return translation
            
        # 尝试处理"clone XXX"格式
        for prefix, chinese_prefix in clone_prefix_mapping.items():
            if clone_name.lower().startswith(prefix):
                # 提取克隆编号/名称部分
                clone_id = clone_name[len(prefix):].strip()
                return f"{chinese_prefix} {clone_id}"
                
        # 默认返回原名
        return clone_name


def get_special_pattern_translator(translation_data_manager=None) -> SpecialPatternTranslator:
    """
    获取特殊模式翻译器实例
    
    Args:
        translation_data_manager: 翻译数据管理器实例
        
    Returns:
        SpecialPatternTranslator: 特殊模式翻译器实例
    """
    return SpecialPatternTranslator(translation_data_manager)