"""
物种名称翻译模块
用于翻译生物物种名称
"""

from typing import Optional, Dict


class SpeciesTranslator:
    """
    物种名称翻译器
    专门用于翻译生物物种名称
    """
    
    def __init__(self, translation_data_manager=None):
        """
        初始化物种名称翻译器
        
        Args:
            translation_data_manager: 翻译数据管理器实例
        """
        self.translation_data_manager = translation_data_manager
        
        # 常见的细菌属名翻译映射
        self.species_mapping = {
            "Bacillus": "芽孢杆菌属",
            "Staphylococcus": "葡萄球菌属",
            "Escherichia": "埃希氏菌属",
            "Pseudomonas": "假单胞菌属",
            "Acinetobacter": "不动杆菌属",
            "Rothia": "罗氏菌属",
            "Aeromonas": "气单胞菌属",
            "Bacterium": "细菌"
        }
    
    def translate_species_name(self, species_name: str) -> str:
        """
        翻译物种名称
        
        Args:
            species_name (str): 英文物种名称
            
        Returns:
            str: 翻译后的物种名称
        """
        if not self.translation_data_manager:
            return species_name
            
        # 处理"属名 sp."格式
        if " sp." in species_name:
            genus = species_name.replace(" sp.", "")
            genus_translation = self.species_mapping.get(genus, genus)
            return f"{genus_translation} sp."
            
        # 尝试直接翻译整个物种名
        translation = self.translation_data_manager.get_translation(species_name)
        if translation:
            return translation
            
        # 尝试翻译属名部分
        if " " in species_name:
            parts = species_name.split(" ")
            if len(parts) >= 2:
                genus = parts[0]
                species = " ".join(parts[1:])
                genus_translation = self.species_mapping.get(genus, genus)
                # 如果属名已翻译，尝试翻译种名
                if genus != genus_translation:
                    species_translation = self.translation_data_manager.get_translation(species)
                    if species_translation:
                        return f"{genus_translation} {species_translation}"
                    else:
                        return f"{genus_translation} {species}"
                        
        # 使用默认翻译或返回原名
        return self.species_mapping.get(species_name, species_name)


def get_species_translator(translation_data_manager=None) -> SpeciesTranslator:
    """
    获取物种名称翻译器实例
    
    Args:
        translation_data_manager: 翻译数据管理器实例
        
    Returns:
        SpeciesTranslator: 物种名称翻译器实例
    """
    return SpeciesTranslator(translation_data_manager)