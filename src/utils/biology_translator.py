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
            
        # 如果启用了AI翻译且AI翻译器可用，则根据翻译质量决定是否使用AI翻译
        if self.use_ai and self.ai_translator:
            # 首先尝试从本地数据中翻译
            if self.translation_data_manager:
                local_result = self._translate_with_local_data(text)
                # 检查本地翻译质量 - 如果包含"菌"字但不是完整翻译，则认为质量不高
                if local_result != text and "菌" in local_result and not self._is_poor_translation(local_result):
                    print(f"[翻译调试] 使用本地翻译: {text} -> {local_result}")
                    # 返回本地翻译结果，并添加标识
                    return f"[本地]{local_result}"
                elif local_result != text:
                    # 本地翻译质量不高，尝试使用AI翻译
                    print(f"[翻译调试] 本地翻译质量不高，尝试AI翻译: {text}")
                else:
                    # 本地翻译失败，使用AI翻译
                    print(f"[翻译调试] 本地翻译失败，尝试AI翻译: {text}")
            
            # 使用AI翻译
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
                # 新增逻辑：AI翻译失败时，如果已有本地翻译则使用本地翻译，否则将原文存储到本地词典中
                if self.translation_data_manager:
                    local_result = self._translate_with_local_data(text)
                    if local_result != text:
                        print(f"[翻译调试] AI翻译失败，使用本地翻译: {text} -> {local_result}")
                        return f"[本地]{local_result}"
                    else:
                        self.translation_data_manager.add_translation(text, text)
        
        # 如果有本地数据管理器，尝试使用本地数据翻译
        if self.translation_data_manager:
            local_result = self._translate_with_local_data(text)
            if local_result != text:  # 如果本地翻译成功
                print(f"[翻译调试] 使用本地翻译: {text} -> {local_result}")
                # 返回本地翻译结果，并添加标识
                quality_indicator = "[本地-低质]" if self._is_poor_translation(local_result) else "[本地]"
                return f"{quality_indicator}{local_result}"
        
        # 所有方法都失败，返回原文
        print(f"[翻译调试] 未翻译，返回原文: {text}")
        return text
    
    def _is_poor_translation(self, translation: str) -> bool:
        """
        判断翻译质量是否不高
        
        Args:
            translation (str): 翻译结果
            
        Returns:
            bool: 如果翻译质量不高返回True，否则返回False
        """
        # 如果翻译中包含明显的不完整翻译，如"xxx菌"但没有完整翻译属名
        # 检查是否有类似"Pseudomona菌"这样的不完整翻译
        if "菌" in translation:
            # 匹配类似"Pseudomona菌"的模式（英文名不完整）
            incomplete_bacteria_pattern = r'[A-Za-z]{4,}菌'
            matches = re.findall(incomplete_bacteria_pattern, translation)
            for match in matches:
                # 如果匹配到的英文部分在常见细菌属名字典中不存在，则认为是不完整翻译
                genus_name = match[:-1]  # 去掉"菌"字
                # 检查是否是完整的属名
                if len(genus_name) < 5 or re.match(r'^[A-Z][a-z]+$', genus_name):  # 通常细菌属名不会太短
                    return True
        
        # 如果翻译中包含"属"字但没有完整翻译属名
        if "属" in translation:
            # 匹配类似"Stenotrophomonas属"这样的不完整翻译
            incomplete_genus_pattern = r'[A-Za-z]{4,}属'
            matches = re.findall(incomplete_genus_pattern, translation)
            for match in matches:
                # 如果匹配到的英文部分在常见细菌属名字典中不存在，则认为是不完整翻译
                genus_name = match[:-1]  # 去掉"属"字
                # 检查是否是完整的属名
                if len(genus_name) < 5 or re.match(r'^[A-Z][a-z]+$', genus_name):  # 通常细菌属名不会太短
                    return True
            
        # 检查是否包含未翻译的英文词（除了菌株、分离株、克隆等标识词）
        # 允许的英文词列表（这些是专业术语的一部分）
        allowed_english_words = ['strain', 'isolate', 'clone']
        english_words_pattern = r'\b[a-zA-Z]{2,}\b'  # 放宽到2个字符以上
        english_words = re.findall(english_words_pattern, translation.lower())
        for word in english_words:
            if word not in allowed_english_words and re.match(r'^[a-zA-Z]+$', word):
                # 如果有较长的英文单词未被翻译，可能是翻译不完整
                return True
            
        return False
    
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
            
        # 处理包含多个序列的情况（以">"分隔）
        if '>' in text and 'gi|' in text:
            # 分割多个序列
            sequences = text.split(' >')
            translated_sequences = []
            
            for i, sequence in enumerate(sequences):
                if i == 0:
                    # 第一个序列不需要添加">"
                    translated_sequences.append(self._translate_single_sequence(sequence))
                else:
                    # 后续序列需要添加">"
                    translated_sequences.append('> ' + self._translate_single_sequence(sequence))
            
            return ' '.join(translated_sequences)
            
        # 处理单个序列
        return self._translate_single_sequence(text)
        
    def _translate_single_sequence(self, text: str) -> str:
        """
        翻译单个序列文本
        
        Args:
            text (str): 单个序列的英文文本
            
        Returns:
            str: 翻译后的文本，如果无法翻译则返回原文
        """
        # 尝试直接匹配整个文本
        direct_translation = self.translation_data_manager.get_translation(text)
        if direct_translation:
            return direct_translation
            
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
                                        translation = self._translate_species_name(group_value)
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
            # 菌种名模式 (如: Bacillus licheniformis, Vogesella urethralis, Beta proteobacterium BIWA27)
            # 进一步优化的正则表达式，仅匹配菌种名称本身
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
                        # 检查是否已存在该术语的翻译
                        existing_translation = self.translation_data_manager.get_translation(term.strip())
                        if existing_translation:
                            # 如果已存在的翻译质量不高，而新的翻译质量高，则更新
                            if self._is_poor_translation(existing_translation) and not self._is_poor_translation(chi_term.strip()):
                                print(f"更新低质量翻译条目: {term.strip()} -> {chi_term.strip()}")
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
        
        # 菌种名称处理 - 直接从翻译结果中提取
        if self._is_species_name(english_term):
            # 尝试直接从翻译结果中提取菌种名称
            species_translation = self._extract_species_from_translation(english_term, chinese_text)
            if species_translation:
                return species_translation
            # 如果无法直接提取，则使用_translate_species_name方法
            return self._translate_species_name(english_term)
        
    def _extract_species_from_translation(self, english_term: str, chinese_text: str) -> str:
        """
        直接从翻译结果中提取菌种的中文名称
        
        Args:
            english_term (str): 英文菌种名称
            chinese_text (str): 包含菌种翻译的中文文本
            
        Returns:
            str: 菌种的中文名称，如果找不到则返回空字符串
        """
        # 这是一个简化的实现，实际应用中可以使用更复杂的NLP技术
        # 我们假设AI翻译结果中已经包含了正确的菌种翻译
        
        # 常见菌种翻译映射（用于验证和后备）
        species_dictionary = {
            'Bacillus cereus': '蜡样芽孢杆菌',
            'Bacillus licheniformis': '地衣芽孢杆菌',
            'Staphylococcus epidermidis': '表皮葡萄球菌',
            'Streptococcus iniae': '海豚链球菌',
            'Aeromonas veronii': '维罗纳气单胞菌',
            'Vogesella urethralis': '沃格氏菌尿道亚种',
            'Acinetobacter johnsonii': '约翰逊氏不动杆菌',
            'Rothia marina': '海洋罗氏菌',
            'Bacillus thuringiensis': '苏云金芽孢杆菌',
            'Bacillus mobilis': '移动芽孢杆菌',
            'Edwardsiella tarda': '迟缓爱德华氏菌',
            'Bacillus sonorensis': '索诺拉沙漠芽孢杆菌',
            'Aeromonas caviae': '豚鼠气单胞菌',
        }
        
        # 如果在词典中，直接返回
        if english_term in species_dictionary:
            # 验证翻译结果中是否包含预期的翻译
            expected_translation = species_dictionary[english_term]
            if expected_translation in chinese_text:
                return expected_translation
        
        # 无法直接提取，返回空字符串
        return ""
    
    def _translate_species_name(self, species_name: str) -> str:
        """
        翻译菌种名称
        
        Args:
            species_name (str): 菌种名称
            
        Returns:
            str: 翻译后的菌种名称
        """
        # 首先尝试从本地翻译数据库获取翻译
        if self.translation_data_manager:
            translation = self.translation_data_manager.get_translation(species_name)
            if translation:
                return translation
        
        # 属名处理（处理类似 "Bacillus sp." 的情况）
        if ' sp.' in species_name:
            genus = species_name.replace(' sp.', '')
            # 尝试从本地数据库获取属名翻译
            if self.translation_data_manager:
                genus_translation = self.translation_data_manager.get_translation(genus + '属')
                if genus_translation:
                    return genus_translation
            # 如果本地数据库没有，使用通用规则
            return f'{genus}属'
        
        # 通用规则：属名 + "菌"
        parts = species_name.split()
        if len(parts) >= 1:
            genus = parts[0]
            # 尝试从本地数据库获取属名翻译
            if self.translation_data_manager:
                genus_translation = self.translation_data_manager.get_translation(genus + '属')
                if genus_translation:
                    return genus_translation
            
            # 特殊处理以's'结尾的属名，避免错误地去掉's'
            # 例如Bacillus应该翻译为芽孢杆菌，而不是Bacillu菌
            genus_dict = {
                'Bacillus': '芽孢杆菌',
            }
            
            if genus in genus_dict:
                return genus_dict[genus]
            elif genus.endswith('s'):
                # 对于以's'结尾的属名，检查是否在特殊处理列表中
                # 如果不在，则去掉's'加上'菌'
                stem = genus[:-1]
                special_stem_dict = {
                    'Bacillu': '芽孢杆菌',
                }
                if stem in special_stem_dict:
                    return special_stem_dict[stem]
                else:
                    return f'{stem}菌'
            else:
                return f'{genus}菌'
        
        return species_name  # 无法翻译时返回原文

    def _translate_strain_name(self, strain_name: str) -> str:
        """
        翻译菌株名称
        
        Args:
            strain_name (str): 菌株名称
            
        Returns:
            str: 翻译后的菌株名称
        """
        # 基本菌株翻译规则
        if self.translation_data_manager:
            translation = self.translation_data_manager.get_translation(strain_name)
            if translation:
                return translation
        
        # 默认翻译规则
        return "菌株" + strain_name.replace("strain", "").strip()

    def _translate_isolate_name(self, isolate_name: str) -> str:
        """
        翻译分离株名称
        
        Args:
            isolate_name (str): 分离株名称
            
        Returns:
            str: 翻译后的分离株名称
        """
        # 基本分离株翻译规则
        if self.translation_data_manager:
            translation = self.translation_data_manager.get_translation(isolate_name)
            if translation:
                return translation
        
        # 默认翻译规则
        return "分离株" + isolate_name.replace("isolate", "").strip()

    def _translate_clone_name(self, clone_name: str) -> str:
        """
        翻译克隆名称
        
        Args:
            clone_name (str): 克隆名称
            
        Returns:
            str: 翻译后的克隆名称
        """
        # 基本克隆翻译规则
        if self.translation_data_manager:
            translation = self.translation_data_manager.get_translation(clone_name)
            if translation:
                return translation
        
        # 默认翻译规则
        return "克隆" + clone_name.replace("clone", "").strip()

    def _is_species_name(self, term: str) -> bool:
        """
        判断一个术语是否为菌种名称
        
        Args:
            term (str): 术语
            
        Returns:
            bool: 是否为菌种名称
        """
        # 基本判断规则：属名+种名的格式
        parts = term.split()
        if len(parts) >= 2:
            genus, species = parts[0], parts[1]
            # 属名首字母大写，种名全小写
            if genus[0].isupper() and genus[1:].islower() and species.islower():
                return True
        return False

    def get_statistics(self):
        """
        获取翻译统计信息
        
        Returns:
            dict: 包含各类术语统计信息的字典
        """
        if self.translation_data_manager:
            return self.translation_data_manager.get_statistics()
        return {}

def get_biology_translator(data_file: str = None, use_ai: bool = False, 
                          ai_api_key: str = None) -> BiologyTranslator:
    """
    获取生物学翻译器实例
    
    Args:
        data_file (str, optional): 数据文件路径
        use_ai (bool): 是否使用AI翻译器
        ai_api_key (str, optional): AI翻译器API密钥
        
    Returns:
        BiologyTranslator: 生物学翻译器实例
    """
    return BiologyTranslator(data_file, use_ai, ai_api_key)

