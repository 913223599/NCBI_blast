"""
生物学专业术语翻译模块
提供生物学专业术语的英译中功能
使用更高效的数据结构支持大量数据的存储和检索
"""

import re
from typing import Dict, Optional

# 导入通义千问翻译器
try:
    from .qwen_translator import get_qwen_translator, QwenTranslator
    QWEN_AVAILABLE = True
except ImportError:
    QWEN_AVAILABLE = False
    QwenTranslator = object  # 占位符

# 导入翻译数据管理器
try:
    from .translation_data_manager import get_translation_data_manager, TranslationDataManager
    TRANSLATION_DATA_MANAGER_AVAILABLE = True
except ImportError:
    TRANSLATION_DATA_MANAGER_AVAILABLE = False
    TranslationDataManager = object  # 占位符


class BiologyTranslator:
    """
    生物学专业术语翻译器
    专门用于生物学领域专业术语的翻译
    使用高效的数据结构支持大量数据的存储和检索
    """
    
    def __init__(self, data_file: Optional[str] = None, use_ai: bool = False, 
                 ai_api_key: Optional[str] = None):
        """
        初始化翻译器
        
        Args:
            data_file (str, optional): 包含翻译数据的CSV文件路径
            use_ai (bool): 是否使用AI翻译器
            ai_api_key (str, optional): AI翻译器API密钥
        """
        # 初始化翻译数据管理器
        self.translation_data_manager = None
        if TRANSLATION_DATA_MANAGER_AVAILABLE:
            csv_file = data_file or "translation_data.csv"
            self.translation_data_manager = get_translation_data_manager(csv_file)
        
        # AI翻译器相关属性
        self.use_ai = use_ai
        self.ai_translator = None
        self.ai_api_key = ai_api_key
        
        # 初始化AI翻译器（如果启用）
        if self.use_ai and QWEN_AVAILABLE:
            try:
                self.ai_translator = get_qwen_translator(self.ai_api_key)
            except Exception as e:
                print(f"警告: 无法初始化AI翻译器: {e}")
                self.ai_translator = None
                self.use_ai = False
        elif self.use_ai and not QWEN_AVAILABLE:
            print("警告: 请求使用AI翻译器，但未安装dashscope库")
            self.use_ai = False
    
    def translate_text(self, text: str) -> str:
        """
        翻译整段文本中的生物学专业术语
        使用本地翻译数据优先，失败时使用AI翻译并回收数据
        
        Args:
            text (str): 英文文本
            
        Returns:
            str: 翻译后的文本，带有翻译类型标识（[AI]表示AI翻译，[本地]表示本地翻译）
        """
        if not text:
            return text
            
        # 如果启用了AI翻译且AI翻译器可用，则优先使用AI翻译
        if self.use_ai and self.ai_translator:
            # 首先尝试从本地数据中翻译
            if self.translation_data_manager:
                local_result = self._translate_with_local_data(text)
                if local_result != text:  # 如果本地翻译成功
                    print(f"[翻译调试] 使用本地翻译: {text} -> {local_result}")
                    # 返回本地翻译结果，并添加标识
                    return f"[本地]{local_result}"
            
            # 如果本地翻译失败或未启用，使用AI翻译
            print(f"[翻译调试] 使用AI翻译: {text}")
            try:
                result = self.ai_translator.translate_text(text)
                print(f"[翻译调试] AI翻译结果: {result}")
                # 回收翻译数据
                if self.translation_data_manager:
                    self._collect_translations(text, result)
                # 返回AI翻译结果，并添加标识
                return f"[AI]{result}"
            except Exception as e:
                print(f"AI翻译失败: {e}")
                # 新增逻辑：AI翻译失败时，将原文存储到本地词典中
                if self.translation_data_manager:
                    self.translation_data_manager.add_translation(text, text)
        
        # 如果有本地数据管理器，尝试使用本地数据翻译
        if self.translation_data_manager:
            local_result = self._translate_with_local_data(text)
            if local_result != text:  # 如果本地翻译成功
                print(f"[翻译调试] 使用本地翻译: {text} -> {local_result}")
                # 返回本地翻译结果，并添加标识
                return f"[本地]{local_result}"
        
        # 所有方法都失败，返回原文
        print(f"[翻译调试] 未翻译，返回原文: {text}")
        return text
    
    def _translate_with_local_data(self, text: str) -> str:
        """
        使用本地翻译数据翻译文本
        增强对复杂生物学术语的翻译能力，特别是对菌株信息的处理
        
        Args:
            text (str): 英文文本
            
        Returns:
            str: 翻译后的文本，如果无法翻译则返回原文
        """
        if not self.translation_data_manager:
            return text
            
        # 尝试直接匹配整个文本
        direct_translation = self.translation_data_manager.get_translation(text)
        if direct_translation:
            return direct_translation
            
        # 特殊处理：针对包含菌株信息的文本进行定制翻译
        # 例如："Aeromonas veronii strain LTFS6 16S ribosomal RNA gene, partial sequence"
        strain_pattern = r'([A-Z][a-z]+(?:\s+[a-z]+)?)\s+(strain\s+[A-Za-z0-9\-._]+)\s+(.+)'
        strain_match = re.match(strain_pattern, text, re.IGNORECASE)
        if strain_match:
            species = strain_match.group(1)  # 菌种名，如 "Aeromonas veronii"
            strain_info = strain_match.group(2)  # 菌株信息，如 "strain LTFS6"
            remaining_text = strain_match.group(3)  # 剩余部分，如 "16S ribosomal RNA gene, partial sequence"
            
            # 翻译菌种名
            species_translation = self.translation_data_manager.get_translation(species)
            if not species_translation:
                # 如果本地没有菌种翻译，尝试使用通用翻译方法
                species_translation = self._translate_species_name(species)
            
            # 处理菌株信息，直接转换为中文格式 "菌株 XXX"
            if strain_info.lower().startswith('strain '):
                strain_translation = '菌株 ' + strain_info[7:]  # 去掉"strain "前缀
            else:
                strain_translation = strain_info  # 如果格式不标准，保持原样
            
            # 翻译剩余部分
            remaining_translation = self._translate_remaining_text(remaining_text)
            
            # 组合翻译结果
            if species_translation and strain_translation and remaining_translation:
                return f"{species_translation} {strain_translation} {remaining_translation}".strip()
        
        # 特殊处理：针对包含分离株信息的文本进行定制翻译
        # 例如："Staphylococcus epidermidis partial 16S rRNA gene, isolate OCOB16"
        isolate_pattern = r'([A-Z][a-z]+(?:\s+[a-z]+)?)\s+(.+)\s*,\s*(isolate\s+[A-Za-z0-9\-._]+)'
        isolate_match = re.match(isolate_pattern, text, re.IGNORECASE)
        if isolate_match:
            species = isolate_match.group(1)  # 菌种名，如 "Staphylococcus epidermidis"
            gene_info = isolate_match.group(2)  # 基因信息，如 "partial 16S rRNA gene"
            isolate_info = isolate_match.group(3)  # 分离株信息，如 "isolate OCOB16"
            
            # 翻译菌种名
            species_translation = self.translation_data_manager.get_translation(species)
            if not species_translation:
                # 如果本地没有菌种翻译，尝试使用通用翻译方法
                species_translation = self._translate_species_name(species)
            
            # 翻译基因信息
            gene_translation = self.translation_data_manager.get_translation(gene_info)
            if not gene_translation:
                gene_translation = self._translate_remaining_text(gene_info)
            
            # 处理分离株信息，直接转换为中文格式 "分离株 XXX"
            if isolate_info.lower().startswith('isolate '):
                isolate_translation = '分离株 ' + isolate_info[8:]  # 去掉"isolate "前缀
            else:
                isolate_translation = isolate_info  # 如果格式不标准，保持原样
            
            # 组合翻译结果
            if species_translation and gene_translation and isolate_translation:
                return f"{species_translation} {gene_translation} {isolate_translation}".strip()
                
        # 特殊处理：针对包含属名(sp.)和菌株信息的文本进行定制翻译
        # 例如："Aeromonas sp. strain J16OP4 16S ribosomal RNA gene, partial sequence"
        sp_strain_pattern = r'([A-Z][a-z]+ sp\.)\s+(strain\s+[A-Za-z0-9\-._]+)\s+(.+)'
        sp_strain_match = re.match(sp_strain_pattern, text, re.IGNORECASE)
        if sp_strain_match:
            species = sp_strain_match.group(1)  # 菌种名，如 "Aeromonas sp."
            strain_info = sp_strain_match.group(2)  # 菌株信息，如 "strain J16OP4"
            remaining_text = sp_strain_match.group(3)  # 剩余部分，如 "16S ribosomal RNA gene, partial sequence"
            
            # 翻译菌种名
            species_translation = self.translation_data_manager.get_translation(species)
            if not species_translation:
                # 如果本地没有菌种翻译，尝试使用通用翻译方法
                species_translation = self._translate_species_name(species)
            
            # 处理菌株信息，直接转换为中文格式 "菌株 XXX"
            if strain_info.lower().startswith('strain '):
                strain_translation = '菌株 ' + strain_info[7:]  # 去掉"strain "前缀
            else:
                strain_translation = strain_info  # 如果格式不标准，保持原样
            
            # 翻译剩余部分
            remaining_translation = self._translate_remaining_text(remaining_text)
            
            # 组合翻译结果
            if species_translation and strain_translation and remaining_translation:
                return f"{species_translation} {strain_translation} {remaining_translation}".strip()
                
        # 特殊处理：针对包含克隆信息的文本进行定制翻译
        # 例如："Uncultured Bacillus sp. clone CBR4 16S ribosomal RNA gene, partial sequence"
        clone_pattern = r'([Uu]ncultured\s+)?([A-Z][a-z]+(?:\s+[a-z]+)?)\s+(clone\s+[A-Za-z0-9\-._]+)\s+(.+)'
        clone_match = re.match(clone_pattern, text, re.IGNORECASE)
        if clone_match:
            uncultured_prefix = clone_match.group(1) or ""  # "Uncultured"前缀，如存在
            species = clone_match.group(2)  # 菌种名，如 "Bacillus sp."
            clone_info = clone_match.group(3)  # 克隆信息，如 "clone CBR4"
            remaining_text = clone_match.group(4)  # 剩余部分，如 "16S ribosomal RNA gene, partial sequence"
            
            # 翻译菌种名
            species_translation = self.translation_data_manager.get_translation(species)
            if not species_translation:
                # 如果本地没有菌种翻译，尝试使用通用翻译方法
                species_translation = self._translate_species_name(species)
            
            # 处理克隆信息，直接转换为中文格式 "克隆 XXX"
            if clone_info.lower().startswith('clone '):
                clone_translation = '克隆 ' + clone_info[6:]  # 去掉"clone "前缀
            else:
                clone_translation = clone_info  # 如果格式不标准，保持原样
            
            # 翻译剩余部分
            remaining_translation = self._translate_remaining_text(remaining_text)
            
            # 组合翻译结果
            if species_translation and clone_translation and remaining_translation:
                result_parts = []
                if uncultured_prefix:
                    result_parts.append("未培养")
                result_parts.extend([species_translation, clone_translation, remaining_translation])
                return " ".join(result_parts).strip()
        
        # 尝试匹配常见的生物学术语模式
        # 模式1: 菌种 + 菌株 + 基因 + 序列类型
        # 例如: Staphylococcus epidermidis strain 041405A-3b 16S ribosomal RNA gene, partial sequence
        patterns = [
            # 完整模式匹配
            r'([A-Z][a-z]+(?:\s+[a-z]+)?)\s+(strain\s+[A-Za-z0-9\-._]+)\s+(16S\s+ribosomal\s+RNA(?:\s+gene)?)\s*,\s*(partial\s+sequence|complete\s+genome)',
            # 菌种 + 基因 + 序列类型
            r'([A-Z][a-z]+(?:\s+[a-z]+)?)\s+(16S\s+ribosomal\s+RNA(?:\s+gene)?)\s*,\s*(partial\s+sequence|complete\s+genome)',
            # 菌种 + 菌株 + 基因
            r'([A-Z][a-z]+(?:\s+[a-z]+)?)\s+(strain\s+[A-Za-z0-9\-._]+)\s+(16S\s+ribosomal\s+RNA(?:\s+gene)?)',
            # 菌种 + 分离株 + 基因
            r'([A-Z][a-z]+(?:\s+[a-z]+)?)\s+(partial\s+16S\s+rRNA\s+gene)\s*,\s*(isolate\s+[A-Za-z0-9\-._]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                translated_parts = []
                all_parts_translated = True
                
                # 尝试翻译每个匹配的部分
                for i in range(1, len(match.groups()) + 1):
                    part = match.group(i)
                    part_translation = self.translation_data_manager.get_translation(part)
                    if part_translation:
                        translated_parts.append(part_translation)
                    else:
                        # 尝试进一步拆分部分进行翻译
                        sub_parts = re.split(r'[,\s]+', part)
                        translated_sub_parts = []
                        all_sub_translated = True
                        
                        for sub_part in sub_parts:
                            sub_translation = self.translation_data_manager.get_translation(sub_part)
                            if sub_translation:
                                translated_sub_parts.append(sub_translation)
                            else:
                                all_sub_translated = False
                                break
                        
                        if all_sub_translated and translated_sub_parts:
                            translated_parts.append(" ".join(translated_sub_parts))
                        else:
                            all_parts_translated = False
                            break
                
                if all_parts_translated and translated_parts:
                    return " ".join(translated_parts)
        
        # 如果模式匹配失败，尝试逐词翻译
        words = text.split()
        translated_words = []
        all_translated = True
        
        for word in words:
            translation = self.translation_data_manager.get_translation(word)
            if translation:
                translated_words.append(translation)
            else:
                # 如果有任何词无法翻译，则整个翻译失败
                all_translated = False
                break
        
        # 只有当所有词都被翻译时才返回翻译结果
        if all_translated and translated_words:
            return " ".join(translated_words)
            
        # 新增逻辑：尝试对文本进行更细粒度的拆分
        phrases = re.split(r'[,\s]+', text)
        translated_phrases = []
        all_phrases_translated = True
        
        for phrase in phrases:
            phrase_translation = self.translation_data_manager.get_translation(phrase)
            if phrase_translation:
                translated_phrases.append(phrase_translation)
            else:
                all_phrases_translated = False
                break
        
        if all_phrases_translated and translated_phrases:
            return " ".join(translated_phrases)
            
        # 否则返回原文
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

    def _collect_translations(self, original: str, translated: str):
        """
        收集并存储翻译数据，优化存储方式，只存储关键术语
        
        Args:
            original (str): 原文
            translated (str): 译文
        """
        if not self.translation_data_manager:
            return
            
        # 提取并存储关键术语
        self._extract_and_store_key_terms(original, translated)

    def _extract_and_store_key_terms(self, original: str, translated: str):
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
            # 菌种名模式 (如: Bacillus licheniformis, Vogesella urethralis)
            (r'\b([A-Z][a-z]+(?:\s+[a-z]+){1,2})\b(?:\s+strain|16S|\b[a-z]+|$)', 'species', '菌种'),
            # 菌株编号模式 (如: strain ZM059)
            (r'(strain\s+[A-Z0-9][A-Za-z0-9\-._]*)', 'strain', '菌株'),
            # 分离株信息模式 (如: isolate 3.47)
            (r'(isolate\s+[A-Z0-9][A-Za-z0-9\-._]*)', 'isolate', '分离株'),
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
            (r'(clone\s+[A-Z0-9][A-Za-z0-9\-._]*)', 'clone', '克隆'),
            # 基因描述模式 (如: gene for 16S rRNA)
            (r'gene for 16S rRNA', 'gene', '基因'),
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
                        # 存储术语翻译，使用结构化方式
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
        
        # 通用查找方法：基于术语词典
        term_dictionary = {
            '16S ribosomal RNA': '16S核糖体RNA',
            '16S ribosomal RNA gene': '16S核糖体RNA基因',
            'partial sequence': '部分序列',
            'complete genome': '完整基因组',
            'plasmid vector': '质粒载体',
            'strain': '菌株',
            'isolate': '分离株',
            'rRNA gene': '核糖体RNA基因',
            'gene': '基因',
            'RNA': '核糖体RNA',
            'gene for 16S rRNA': '16S rRNA基因',
        }
        
        # 直接查找
        if english_term in term_dictionary:
            return term_dictionary[english_term]
        
        # 忽略大小写查找
        for eng, chi in term_dictionary.items():
            if eng.lower() == english_term.lower():
                return chi
        
        # 包含关系查找
        for eng, chi in term_dictionary.items():
            if eng.lower() in english_term.lower():
                return chi
        
        # 菌种名称处理
        if self._is_species_name(english_term):
            return self._translate_species_name(english_term)
        
        # 菌株名称处理
        if english_term.lower().startswith('strain'):
            return self._translate_strain_name(english_term)
            
        # 分离株名称处理
        if english_term.lower().startswith('isolate'):
            return self._translate_isolate_name(english_term)
        
        # 属名(sp.)处理
        if english_term.lower().endswith(' sp.'):
            genus = english_term[:-4]  # 移除" sp."后缀
            return f'{genus}属'
            
        # 克隆名称处理
        if english_term.lower().startswith('clone'):
            return self._translate_clone_name(english_term)
        
        return ""  # 未找到对应翻译
    
    def _translate_clone_name(self, clone_term: str) -> str:
        """
        翻译克隆名称
        
        Args:
            clone_term (str): 克隆术语
            
        Returns:
            str: 翻译后的克隆名称
        """
        # 克隆通常保留原文，只添加"克隆"前缀
        if clone_term.lower().startswith('clone '):
            clone_id = clone_term[6:]  # 移除"clone "前缀
            return f'克隆 {clone_id}'
        return clone_term
    
    def _translate_isolate_name(self, isolate_term: str) -> str:
        """
        翻译分离株名称
        
        Args:
            isolate_term (str): 分离株术语
            
        Returns:
            str: 翻译后的分离株名称
        """
        # 分离株通常保留原文，只添加"分离株"前缀
        if isolate_term.lower().startswith('isolate '):
            isolate_id = isolate_term[8:]  # 移除"isolate "前缀
            return f'分离株{isolate_id}'
        return isolate_term
    
    def _is_species_name(self, term: str) -> bool:
        """
        判断是否为菌种名称
        
        Args:
            term (str): 术语
            
        Returns:
            bool: 是否为菌种名称
        """
        # 菌种名称通常由两个单词组成，第一个单词首字母大写，第二个单词全小写
        parts = term.split()
        if len(parts) == 2:
            genus, species = parts
            return genus[0].isupper() and genus[1:].islower() and species.islower()
        return False
    
    def _translate_species_name(self, species_name: str) -> str:
        """
        翻译菌种名称
        
        Args:
            species_name (str): 菌种名称
            
        Returns:
            str: 翻译后的菌种名称
        """
        # 常见菌种翻译词典
        species_dict = {
            'Bacillus licheniformis': '地衣芽孢杆菌',
            'Bacillus cereus': '蜡样芽孢杆菌',
            'Bacillus thuringiensis': '苏云金芽孢杆菌',
            'Bacillus albus': '白杆菌',
            'Bacillus mobilis': '移动芽孢杆菌',
            'Bacillus sp.': '芽孢杆菌属',
            'Streptococcus iniae': '伊氏链球菌',
            'Staphylococcus epidermidis': '表皮葡萄球菌',
            'Acinetobacter johnsonii': '约翰逊氏不动杆菌',
            'Acinetobacter sp.': '不动杆菌属',
            'Rothia marina': '海洋罗氏菌',
            'Rothia endophytica': '内生罗氏菌',
            'Rothia sp.': '罗氏菌属',
            'Klebsiella pneumoniae': '肺炎克雷伯菌',
            'Klebsiella pneumoniae subsp. pneumoniae': '肺炎克雷伯菌肺炎亚种',
            'Aeromonas veronii': '维罗纳气单胞菌',
            'Aeromonas sobria': '气单胞菌',
            'Aeromonas sp.': '气单胞菌属',
            'Edwardsiella tarda': '迟缓爱德华氏菌',
            'Vogesella urethralis': '沃格氏菌尿道亚种',
            'Vogesella sp.': '沃格氏菌属',
            'Bacterium sp.': '细菌属',
            'Uncultured bacterium': '未培养细菌',
            'Uncultured Bacillus sp.': '未培养芽孢杆菌属',
        }
        
        # 直接查找
        if species_name in species_dict:
            return species_dict[species_name]
        
        # 属名处理（处理类似 "Bacillus sp." 的情况）
        if ' sp.' in species_name:
            genus = species_name.replace(' sp.', '')
            return f'{genus}属'
        
        # 通用规则：属名 + "菌"
        parts = species_name.split()
        if len(parts) >= 1:
            genus = parts[0]
            # 常见属名字典
            genus_dict = {
                'Bacillus': '芽孢杆菌',
                'Streptococcus': '链球菌',
                'Staphylococcus': '葡萄球菌',
                'Acinetobacter': '不动杆菌',
                'Rothia': '罗氏菌',
                'Klebsiella': '克雷伯菌',
                'Aeromonas': '气单胞菌',
                'Edwardsiella': '爱德华氏菌',
                'Vogesella': '沃格氏菌',
                'Bacterium': '细菌',
            }
            if genus in genus_dict:
                return genus_dict[genus]
            elif genus.endswith('s'):
                return f'{genus[:-1]}菌'
            else:
                return f'{genus}菌'
        
        return species_name  # 无法翻译时返回原文
    
    def _translate_strain_name(self, strain_term: str) -> str:
        """
        翻译菌株名称
        
        Args:
            strain_term (str): 菌株术语
            
        Returns:
            str: 翻译后的菌株名称
        """
        # 菌株通常保留原文，只添加"菌株"前缀
        if strain_term.lower().startswith('strain '):
            strain_id = strain_term[7:]  # 移除"strain "前缀
            return f'菌株{strain_id}'
        return strain_term
    
    def get_statistics(self) -> Dict[str, int]:
        """
        获取翻译数据统计信息
        
        Returns:
            dict: 包含各类翻译条目数量的字典
        """
        if self.translation_data_manager:
            return self.translation_data_manager.get_statistics()
        return {"total_entries": 0}


def get_biology_translator(data_file: Optional[str] = None, use_ai: bool = False, 
                           ai_api_key: Optional[str] = None) -> BiologyTranslator:
    """
    获取生物学翻译器实例
    
    Args:
        data_file (str, optional): 包含翻译数据的CSV文件路径
        use_ai (bool): 是否使用AI翻译器
        ai_api_key (str, optional): AI翻译器API密钥
        
    Returns:
        BiologyTranslator: 生物学翻译器实例
    """
    return BiologyTranslator(data_file, use_ai, ai_api_key)


def get_biology_translator_from_api(api_key: Optional[str] = None) -> BiologyTranslator:
    """
    获取基于API的生物学翻译器实例
    
    Args:
        api_key (str, optional): API密钥
        
    Returns:
        BiologyTranslator: 翻译器实例
    """
    return BiologyTranslator(use_ai=True, ai_api_key=api_key)