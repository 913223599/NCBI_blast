"""
生物学专业术语翻译模块
提供生物学专业术语的英译中功能
"""

# 生物学专业术语翻译字典
BIOLOGY_TRANSLATION_DICT = {
    # 常见细菌属名
    "Bacillus": "芽孢杆菌",
    "Staphylococcus": "葡萄球菌",
    "Streptococcus": "链球菌",
    "Escherichia": "埃希氏菌",
    "Salmonella": "沙门氏菌",
    "Pseudomonas": "假单胞菌",
    "Clostridium": "梭菌",
    "Lactobacillus": "乳酸杆菌",
    "Corynebacterium": "棒状杆菌",
    "Mycobacterium": "分枝杆菌",
    "Vibrio": "弧菌",
    "Klebsiella": "克雷伯氏菌",
    "Enterococcus": "肠球菌",
    "Listeria": "李斯特菌",
    "Shigella": "志贺氏菌",
    "Campylobacter": "弯曲杆菌",
    "Helicobacter": "幽门螺杆菌",
    "Neisseria": "奈瑟氏菌",
    "Haemophilus": "嗜血杆菌",
    "Brucella": "布鲁氏菌",
    "Yersinia": "耶尔森氏菌",
    
    # 常见真菌属名
    "Aspergillus": "曲霉菌",
    "Candida": "念珠菌",
    "Saccharomyces": "酵母菌",
    "Penicillium": "青霉菌",
    "Fusarium": "镰刀菌",
    "Rhizopus": "根霉菌",
    "Mucor": "毛霉菌",
    "Cryptococcus": "隐球菌",
    "Trichophyton": "毛癣菌",
    "Microsporum": "小孢子菌",
    
    # 常见病毒相关术语
    "virus": "病毒",
    "phage": "噬菌体",
    "bacteriophage": "细菌噬菌体",
    
    # 常见基因和序列相关术语
    "ribosomal RNA gene": "核糖体RNA基因",
    "16S": "16S",
    "18S": "18S",
    "23S": "23S",
    "gene": "基因",
    "partial": "部分",
    "complete": "完整",
    "sequence": "序列",
    "genome": "基因组",
    "plasmid": "质粒",
    
    # 常见生物学过程和特性
    "strain": "菌株",
    "isolate": "分离株",
    "species": "种",
    "subspecies": "亚种",
    "type": "型",
    "subtype": "亚型",
    
    # 常见实验和培养相关术语
    "culture": "培养物",
    "clone": "克隆",
    "library": "文库",
    "vector": "载体",
    
    # 常见生物分子
    "DNA": "DNA",
    "RNA": "RNA",
    "protein": "蛋白质",
    "enzyme": "酶",
    "antibiotic": "抗生素",
    "resistance": "抗性",
}

# 常见物种完整名称翻译
SPECIES_TRANSLATION_DICT = {
    "Bacillus licheniformis": "地衣芽孢杆菌",
    "Bacillus paralicheniformis": "副地衣芽孢杆菌",
    "Staphylococcus epidermidis": "表皮葡萄球菌",
    "Escherichia coli": "大肠埃希氏菌",
    "Saccharomyces cerevisiae": "酿酒酵母",
    "Pseudomonas aeruginosa": "铜绿假单胞菌",
}

class BiologyTranslator:
    """
    生物学专业术语翻译器
    专门用于生物学领域专业术语的翻译
    """
    
    def __init__(self):
        """
        初始化翻译器
        """
        self.term_dict = BIOLOGY_TRANSLATION_DICT
        self.species_dict = SPECIES_TRANSLATION_DICT
    
    def translate_term(self, term):
        """
        翻译单个术语
        
        Args:
            term (str): 英文术语
            
        Returns:
            str: 中文翻译，如果找不到则返回原词
        """
        return self.term_dict.get(term, term)
    
    def translate_species(self, species_name):
        """
        翻译物种名称
        
        Args:
            species_name (str): 英文物种名称
            
        Returns:
            str: 中文物种名称，如果找不到则返回原名
        """
        # 首先尝试完整名称翻译
        if species_name in self.species_dict:
            return self.species_dict[species_name]
        
        # 如果没有完整名称翻译，则逐词翻译
        words = species_name.split()
        translated_words = []
        
        for word in words:
            # 处理常见的术语
            if word in self.term_dict:
                translated_words.append(self.term_dict[word])
            # 处理拉丁文结尾（如 sp. spp. 等）
            elif word in ["sp.", "spp.", "str."]:
                translated_words.append(word)  # 这些通常保持原样
            else:
                translated_words.append(word)  # 未找到翻译的词保持原样
                
        return " ".join(translated_words)
    
    def translate_text(self, text):
        """
        翻译整段文本中的生物学专业术语
        
        Args:
            text (str): 英文文本
            
        Returns:
            str: 部分翻译的文本（仅翻译专业术语）
        """
        # 对于完整的文本，我们通常需要更复杂的处理
        # 这里提供一个简单的实现，可以根据需要扩展
        
        # 尝试匹配完整的物种名称
        for species_en, species_zh in self.species_dict.items():
            if species_en in text:
                text = text.replace(species_en, species_zh)
        
        # 然后处理单个术语
        for term_en, term_zh in self.term_dict.items():
            # 使用单词边界匹配，避免部分匹配
            import re
            pattern = r'\b' + re.escape(term_en) + r'\b'
            text = re.sub(pattern, term_zh, text)
            
        return text


def get_biology_translator():
    """
    获取生物学翻译器实例
    
    Returns:
        BiologyTranslator: 翻译器实例
    """
    return BiologyTranslator()


# 示例和测试
if __name__ == "__main__":
    translator = get_biology_translator()
    
    # 测试翻译
    test_cases = [
        "Bacillus licheniformis strain WS02 16S ribosomal RNA gene, partial sequence",
        "Staphylococcus epidermidis partial 16S rRNA gene, isolate OCOB16",
        "Escherichia coli gene sequence",
        "Saccharomyces cerevisiae strain ABC123 plasmid vector"
    ]
    
    print("生物学专业术语翻译测试:")
    print("=" * 50)
    
    for test_case in test_cases:
        translated = translator.translate_text(test_case)
        print(f"原文: {test_case}")
        print(f"译文: {translated}")
        print("-" * 50)