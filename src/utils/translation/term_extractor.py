"""
术语提取和存储模块
用于从生物学术语中提取关键术语并存储到翻译数据库中
"""

import re
from typing import List, Tuple, Optional


class TermExtractor:
    """
    术语提取器
    专门用于从生物学术语中提取关键术语并存储到翻译数据库中
    """

    def __init__(self, translation_data_manager=None, quality_checker=None):
        """
        初始化术语提取器
        
        Args:
            translation_data_manager: 翻译数据管理器实例
            quality_checker: 翻译质量检查器实例
        """
        self.translation_data_manager = translation_data_manager
        self.quality_checker = quality_checker

    def extract_and_store_key_terms(self, original: str, translated: str):
        """
        提取并存储关键术语翻译
        根据NCBI官方的物种分类模式进行结构化存储
        
        Args:
            original (str): 原文
            translated (str): 译文
        """
        if not self.translation_data_manager:
            return
            
        # 定义生物学术语模式和对应的分类
        patterns = [
            # 未培养菌种模式 (如: Uncultured Bacillus sp.)
            (r'\b(Uncultured\s+[A-Z][a-z]+(?:\s+sp\.?))\b', 'species', '菌种'),
            # 菌种名模式 (如: Bacillus licheniformis, Vogesella urethralis)
            (r'\b([A-Z][a-z]+(?:\s+[a-z]+){1,2})\b(?=\s+(?:16S|23S|gene|RNA|ITS|partial|complete|strain|isolate|clone)\b|,|\s*$)', 'species', '菌种'),
            # 菌株编号模式 (如: strain ZM059)
            (r'(strain\s+[A-Za-z0-9][A-Za-z0-9\-._]*)', 'strain', '菌株'),
            # 分离株信息模式 (如: isolate 3.47)
            (r'(isolate\s+[A-Za-z0-9][A-Za-z0-9\-._]*)', 'isolate', '分离株'),
            # 基因名称模式 (如: 16S ribosomal RNA gene)
            (r'(16S\s+ribosomal\s+RNA(?:\s+gene)?)', 'gene', '基因'),
            # RNA名称模式 (如: 16S ribosomal RNA)
            (r'(16S\s+ribosomal\s+RNA)(?!\s+gene)', 'gene', '基因'),
            # 序列类型模式 (如: partial sequence, complete genome)
            (r'(partial\s+sequence)', 'sequence', '序列'),
            (r'(complete\s+genome)', 'genome', '基因组'),
            (r'(plasmid\s+vector)', 'plasmid', '质粒'),
            # rRNA基因模式
            (r'(partial\s+16S\s+rRNA\s+gene)', 'gene', '基因'),
            # 克隆信息模式 (如: clone CBR4)
            (r'(clone\s+[A-Za-z0-9][A-Za-z0-9\-._]*)', 'clone', '克隆'),
            # 基因描述模式 (如: gene for 16S rRNA)
            (r'(gene for 16S rRNA)', 'gene', '基因'),
            # 染色体模式
            (r'(chromosome)', 'chromosome', '染色体'),
            # 通用基因模式 (如: ribosomal RNA gene)
            (r'\b(ribosomal\s+RNA\s+gene)\b', 'gene', '基因'),
        ]
        
        # 提取英文关键术语
        for pattern, term_type, category in patterns:
            matches = re.findall(pattern, original, re.IGNORECASE)
            for match in matches:
                # 处理分组匹配结果
                term = match if isinstance(match, str) else match[0] if match else ""
                if term and term.strip() and len(term.strip()) > 1:  # 过滤过短的术语
                    # 对于每个提取的英文术语，尝试在中文翻译中找到对应部分
                    chi_term = self._find_chinese_equivalent(term, translated)
                    if chi_term and chi_term.strip():
                        # 特殊处理：对于菌种名称，直接使用AI翻译结果
                        if term_type == 'species':
                            chi_term = self._extract_species_from_translation(term, translated) or chi_term
                        
                        # 验证提取的术语和翻译是否匹配
                        # 防止错误的术语翻译被存储
                        if not self._is_valid_term_translation(term, chi_term, translated):
                            print(f"[警告] 术语翻译不匹配，跳过存储: {term} -> {chi_term}")
                            continue
                        
                        # 存储术语翻译，使用结构化方式
                        # 检查是否已存在该术语的翻译
                        existing_translation = self.translation_data_manager.get_translation(term.strip())
                        if existing_translation:
                            # 如果已存在的翻译质量不高，而新的翻译质量高，则更新
                            if (self.quality_checker and 
                                self.quality_checker.is_poor_translation(existing_translation) and 
                                not self.quality_checker.is_poor_translation(chi_term.strip())):
                                print(f"更新低质量翻译条目: {term.strip()} -> {chi_term.strip()}")
                                self.translation_data_manager.update_translation(
                                    term.strip(), chi_term.strip(), term_type, category)
                            # 如果是菌种且新的翻译更完整，则更新
                            elif term_type == 'species' and len(chi_term.strip()) > len(existing_translation):
                                print(f"更新菌种翻译条目: {term.strip()} -> {chi_term.strip()}")
                                self.translation_data_manager.update_translation(
                                    term.strip(), chi_term.strip(), term_type, category)
                        else:
                            # 如果不存在，则添加新的翻译条目
                            self.translation_data_manager.add_structured_translation(
                                term.strip(), chi_term.strip(), term_type, category)

    def _find_chinese_equivalent(self, english_term: str, chinese_text: str) -> str:
        """
        在中文文本中查找英文术语的对应翻译
        
        Args:
            english_term (str): 英文术语
            chinese_text (str): 中文文本
            
        Returns:
            str: 对应的中文术语，如果找不到则返回空字符串
        """
        # 这是一个简化的实现，实际应用中可以使用更复杂的NLP技术
        # 根据术语类型使用不同的查找策略
        
        # 直接查找
        if self.translation_data_manager:
            predefined_translation = self.translation_data_manager.get_translation(english_term)
            if predefined_translation:
                return predefined_translation
        
        # 忽略大小写查找
        if self.translation_data_manager:
            all_terms = self.translation_data_manager.get_all_terms()
            for eng, chi in all_terms.items():
                if eng.lower() == english_term.lower():
                    return chi
        
        # 更精确的包含关系查找 - 只有当英文术语完全匹配字典中的键时才返回翻译
        # 避免像"complete genome"匹配到整个翻译结果这样的错误
        if self.translation_data_manager:
            all_terms = self.translation_data_manager.get_all_terms()
            for eng, chi in all_terms.items():
                # 使用正则表达式进行更精确的匹配
                if re.search(r'\b' + re.escape(english_term) + r'\b', eng, re.IGNORECASE):
                    return chi
        
        # 对于不在词典中的术语，返回空字符串而不是错误的匹配
        return ""

    def _extract_species_from_translation(self, english_term: str, chinese_text: str) -> str:
        """
        直接从翻译结果中提取菌种的中文名称
        
        Args:
            english_term (str): 英文菌种名称
            chinese_text (str): 包含菌种翻译的中文文本
            
        Returns:
            str: 菌种的中文名称，如果找不到则返回空字符串
        """
        # 基于分析示例的模式匹配：
        # 1. "Aeromonas sobria strain LD081008A-1 16S ribosomal RNA gene, partial sequence" 
        #    -> "温和气单胞菌LD081008A-1株16S核糖体RNA基因，部分序列"
        # 2. "Uncultured Bacillus sp. clone CBR4 16S ribosomal RNA gene, partial sequence" 
        #    -> "未培养芽孢杆菌属（Bacillus sp.）克隆CBR4 16S核糖体RNA基因，部分序列"
        
        # 处理"未培养"前缀的特殊情况
        if english_term.lower().startswith('uncultured'):
            # 匹配"未培养X"或"未培养 X"模式
            # 支持模式如："未培养芽孢杆菌属" 或 "未培养芽孢杆菌属（Bacillus sp.）"
            uncultured_pattern = r'^(未培养[^（\(株克\d\s]+?)(?:（[^）]*?）)?(?=\s*[0-9a-zA-Z（\(株克]|$)'
            match = re.search(uncultured_pattern, chinese_text)
            if match:
                return match.group(1).strip()
        
        # 一般情况：提取文本开头到第一个数字或特殊标识前的部分作为菌种名称
        # 匹配模式：从文本开头开始，直到遇到数字、字母、括号、"株"、"克隆"等标识
        # 支持模式如："脲道氏沃格斯菌" 或 "温和气单胞菌LD081008A-1株"
        species_pattern = r'^([^0-9a-zA-Z（\(株克\d\s]+?)(?=\s*[0-9a-zA-Z（\(株克]|$)'
        match = re.search(species_pattern, chinese_text)
        if match:
            candidate = match.group(1).strip()
            # 确保提取的结果包含常见的菌种关键词
            if any(keyword in candidate for keyword in ['菌', '杆菌', '球菌', '链球菌', '螺旋体', '弧菌', '假单胞菌']):
                return candidate
        
        # 备用方案：使用更宽松的模式匹配中文字符组成的短语
        # 检查是否包含常见的菌种关键词
        backup_pattern = r'^([^\s\d]{2,15}?[菌藻体])'
        match = re.search(backup_pattern, chinese_text)
        if match:
            candidate = match.group(1).strip()
            if any(keyword in candidate for keyword in ['菌', '藻', '体']):
                return candidate
        
        # 无法直接提取，返回空字符串
        return ""

    def _is_valid_term_translation(self, english_term: str, chinese_term: str, full_translation: str) -> bool:
        """
        验证英文术语和中文翻译是否匹配
        
        Args:
            english_term (str): 英文术语
            chinese_term (str): 提取的中文翻译
            full_translation (str): 完整的翻译文本
            
        Returns:
            bool: 如果术语和翻译匹配返回True，否则返回False
        """
        # 如果是预定义术语，直接验证翻译是否正确
        if self.translation_data_manager:
            predefined_translation = self.translation_data_manager.get_translation(english_term)
            if predefined_translation:
                return predefined_translation == chinese_term
        
        # 对于其他术语，简单验证翻译是否在完整翻译文本中
        return chinese_term in full_translation