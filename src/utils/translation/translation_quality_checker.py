"""
翻译质量检查模块
用于评估翻译结果的质量
"""

import re


class TranslationQualityChecker:
    """
    翻译质量检查器
    用于评估翻译结果的质量，判断翻译是否完整和准确
    """
    
    def __init__(self):
        """
        初始化翻译质量检查器
        """
        pass
    
    def is_poor_translation(self, translation: str) -> bool:
        """
        判断翻译质量是否较差
        
        Args:
            translation (str): 翻译后的文本
            
        Returns:
            bool: 如果翻译质量较差返回True，否则返回False
        """
        if not translation:
            return True
            
        # 检查是否包含明显的翻译不完整特征
        poor_indicators = [
            "sp.",  # 未完全翻译的属名
            "endophytica",  # 未翻译的种名
            "partial sequen",  # 部分序列未完整翻译
            "16S rRNA gene",  # 基因名称未翻译完整
            "ribosomal RNA gene",  # 核糖体RNA基因未翻译完整
        ]
        
        # 如果翻译中包含这些不完整的翻译片段，则认为质量较差
        for indicator in poor_indicators:
            if indicator in translation:
                return True
        
        # 如果翻译中包含"u菌"这种不规范的翻译
        if "u菌" in translation:
            return True
            
        # 如果翻译中包含明显的不完整翻译，如"xxx菌"但没有完整翻译属名
        # 检查是否有类似"Pseudomona菌"这样的不完整翻译
        if "菌" in translation:
            # 匹配类似"Pseudomona菌"的模式
            incomplete_bacteria_pattern = r'[A-Za-z]{4,}菌'
            if re.search(incomplete_bacteria_pattern, translation):
                return True
        
        # 如果翻译中包含"属"字但没有完整翻译属名
        if "属" in translation:
            # 匹配类似"Stenotrophomonas属"这样的不完整翻译
            incomplete_genus_pattern = r'[A-Za-z]{4,}属'
            if re.search(incomplete_genus_pattern, translation):
                return True
        
        # 如果翻译结果过短，可能翻译不完整
        if len(translation) < 10 and ("菌" in translation or "属" in translation):
            return True
            
        return False


def get_translation_quality_checker() -> TranslationQualityChecker:
    """
    获取翻译质量检查器实例
    
    Returns:
        TranslationQualityChecker: 翻译质量检查器实例
    """
    return TranslationQualityChecker()