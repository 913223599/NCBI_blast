"""
术语提取和存储模块
用于从生物学术语中提取关键术语并存储到翻译数据库中
I/O 优化版 - 使用内存缓存提高性能
"""

import csv
import json
import re
from pathlib import Path
from typing import Tuple, Dict, List, Optional


class TermExtractor:
    """
    术语提取器 - I/O 优化版
    专门用于从生物学术语中提取关键术语并存储到翻译数据库中
    """

    def __init__(self, translation_data_manager=None):
        """
        初始化术语提取器
        
        Args:
            translation_data_manager: 翻译数据管理器实例
        """
        self.translation_data_manager = translation_data_manager
        
        # 加载分类规则
        self.classification_rules = self._load_classification_rules()
        
        # 初始化学习数据结构
        self.learning_patterns = {
            'species': [],
            'genus': [],
            'gene': [],
            'sequence': [],
            'strain': [],
            'other': []
        }
        
        # 添加线程锁
        import threading
        self._lock = threading.Lock()
        
        # [优化点 1] 初始化时加载预定义术语到内存缓存
        self._predefined_terms_cache = {}
        self._load_predefined_terms_to_cache()
        
        # 加载学习到的模式
        self._load_learned_patterns()

    def _load_classification_rules(self):
        """加载分类规则"""
        try:
            # 获取规则文件路径
            rules_file = Path(__file__).parent / "classification_rules.json"
            with open(rules_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"警告: 加载分类规则失败，使用最小默认规则: {e}")
            # 返回最小化的默认规则，避免重复定义
            return {
                "gene_patterns": ["gene", "protein"],
                "sequence_patterns": ["sequence", "genome"],
                "strain_patterns": ["strain", "isolate"],
                "taxonomic_ranks": ["phylum", "class", "order", "family"],
                "special_terms": ["sp.", "subsp.", "var."],
                "common_genera": ["clostridium", "escherichia", "bacillus"],
                "genus_suffixes": ["us", "a", "um"],
                "virus_terms": ["virus"],
                "phage_terms": ["phage"]
            }

    def _load_predefined_terms_to_cache(self):
        """[新增方法] 将预定义术语加载到内存缓存"""
        try:
            # 确定预定义术语文件路径 (保持原逻辑)
            predefined_terms_file = Path(__file__).parent.parent.parent.parent / "predefined_terms.csv"
            
            if predefined_terms_file.exists():
                with open(predefined_terms_file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        term = row['english'].strip()
                        category = row['category'].strip()
                        chinese = row['chinese'].strip()
                        
                        # 构建多级索引缓存: cache[term] = {'chinese': xxx, 'category': xxx}
                        # 同时也支持 (term, category) 的快速查找
                        if term not in self._predefined_terms_cache:
                            self._predefined_terms_cache[term] = []
                        
                        self._predefined_terms_cache[term].append({
                            'chinese': chinese,
                            'category': category
                        })
        except Exception as e:
            print(f"警告: 预加载术语库失败: {e}")

    def _load_learned_patterns(self):
        """加载已学习的模式"""
        try:
            learned_patterns_file = Path(__file__).parent / "learned_patterns.json"
            if learned_patterns_file.exists():
                with open(learned_patterns_file, 'r', encoding='utf-8') as f:
                    loaded_patterns = json.load(f)
                    for category, patterns in loaded_patterns.items():
                        if category in self.learning_patterns:
                            self.learning_patterns[category] = patterns
        except Exception as e:
            print(f"警告: 加载学习模式失败: {e}")

    def _save_learned_patterns(self):
        """保存学习到的模式"""
        try:
            learned_patterns_file = Path(__file__).parent / "learned_patterns.json"
            with open(learned_patterns_file, 'w', encoding='utf-8') as f:
                json.dump(self.learning_patterns, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"警告: 保存学习模式失败: {e}")

    def learn_from_examples(self, examples: List[Tuple[str, str]]) -> None:
        """
        从示例中学习分类模式
        
        Args:
            examples: 术语和类别对的列表，例如 [("Staphylococcus aureus", "species"), ("hydrolase", "gene")]
        """
        with self._lock:  # 确保线程安全
            for term, expected_category in examples:
                # 提取特征模式
                self._extract_features_from_term(term, expected_category)
            
            # 保存学习到的模式
            self._save_learned_patterns()
            
            # 更新分类规则
            self._update_classification_rules_with_learned_patterns()

    def _extract_features_from_term(self, term: str, category: str) -> None:
        """
        从术语中提取特征模式并学习
        
        Args:
            term: 术语
            category: 类别
        """
        term_lower = term.lower()
        words = term.split()
        
        # 为每个类别积累术语样本，用于后续分析
        if hasattr(self, '_category_samples'):
            if category not in self._category_samples:
                self._category_samples[category] = []
            if term not in self._category_samples[category]:
                self._category_samples[category].append(term)
        else:
            self._category_samples = {category: [term]}
        
        # 提取词汇模式
        for word in words:
            if len(word) > 2 and word.lower() not in self.classification_rules.get("common_genera", []):
                # 如果这个词经常出现在某个类别中，将其加入该类别的模式
                if word not in self.learning_patterns[category]:
                    self.learning_patterns[category].append(word)
        
        # 提取正则表达式模式
        if category == 'species':
            # 对于物种名，学习双名法模式
            if len(words) >= 2:
                genus = words[0]
                species = words[1]
                if (genus[0].isupper() and 
                    all(c.islower() or c in ['.', '-', '_'] for c in genus[1:]) and 
                    all(c.islower() or c in ['.', '-', '_', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9'] for c in species)):
                    # 学习属名+种名模式，但仅在确认这是有效模式时
                    pattern = rf"{re.escape(genus)}\s+{re.escape(species)}"
                    if pattern not in self.learning_patterns[category]:
                        self.learning_patterns[category].append(pattern)
        
        elif category == 'genus':
            # 学习属名模式
            if len(words) == 1 and words[0][0].isupper():
                # 单个词，首字母大写，可能是属名
                word = words[0]
                if word not in self.learning_patterns[category]:
                    self.learning_patterns[category].append(word)

    def _update_classification_rules_with_learned_patterns(self):
        """使用学习到的模式更新分类规则"""
        # 将学习到的模式合并到现有规则中，但不覆盖原有规则
        for category, patterns in self.learning_patterns.items():
            if category in ['gene', 'sequence', 'strain']:
                # 为基因、序列、菌株类别添加学习到的模式
                for pattern in patterns:
                    if pattern not in self.classification_rules.get(f"{category}_patterns", []):
                        self.classification_rules[f"{category}_patterns"].append(pattern)
            elif category == 'genus':
                # 为属名类别添加学习到的模式
                for pattern in patterns:
                    if pattern not in self.classification_rules.get("common_genera", []):
                        self.classification_rules["common_genera"].append(pattern)
            elif category == 'species':
                # 为物种类别添加学习到的模式
                for pattern in patterns:
                    if pattern not in self.classification_rules.get("common_genera", []) and \
                       pattern not in [term.lower() for term in self.classification_rules.get("special_terms", [])]:
                        # 只添加不在现有规则中的新模式
                        if pattern not in self.classification_rules.get("species", []):
                            if 'species' not in self.classification_rules:
                                self.classification_rules['species'] = []
                            self.classification_rules['species'].append(pattern)

    def normalize_term(self, term: str) -> str:
        """
        规范化术语，移除编号部分，如phiCP39-O, DOBBIE2, XP41-N3等
        但保留有效的生物学名称，如属+种的双名法命名
        
        Args:
            term: 原始术语
            
        Returns:
            str: 规范化后的术语
        """
        if not term:
            return term
            
        # 预先检查是否为已知的有效术语，避免不必要的处理
        # 检查是否为有效的双名法命名（属+种）或包含有效生物学术语的情况
        words = term.split()
        
        # 首先处理方括号等特殊字符
        # 如果术语以左方括号开头但没有闭合，可能是提取不完整，尝试清理
        if term.startswith('[') and not term.endswith(']'):
            # 移除开头的左方括号
            cleaned_term = term[1:]
            if cleaned_term:
                # 递归处理清理后的术语
                return self.normalize_term(cleaned_term)
        
        # 如果术语以左方括号开头并以右方括号结尾，移除方括号
        if term.startswith('[') and term.endswith(']'):
            cleaned_term = term[1:-1].strip()
            if cleaned_term:
                # 递归处理清理后的术语
                return self.normalize_term(cleaned_term)
        
        if len(words) >= 2:
            # 优先检查特殊生物学术语模式（如 phage, sp. 等）
            first_word = words[0].strip()
            second_word = words[1].strip()
            
            # 检查是否为 "属名 phage 编号" 或 "属名 sp. 编号" 模式
            if (second_word.lower() == 'phage' or second_word.lower() == 'sp.') and len(words) > 2:
                # 检查是否有编号需要移除
                remaining_part = ' '.join(words[2:])
                patterns = [
                    r'\s+v?B_[A-Za-z0-9_]+$',  # 匹配 vB_CpeP_PMQ04 样式的编号
                    r'\s+\w*[A-Z]+\d+[A-Z]*-*\d*[A-Z]*$',  # 匹配 phiCP39-O, XP41-N3 等
                    r'\s+\w*[A-Z]*\d+-*\d*-*\d*[A-Z]*\d*$',  # 匹配 C2-6-12, DOBBIE2 等
                    r'\s+[a-z]*[A-Z]*[A-Z0-9]+$',  # 匹配 ctNU74 等
                ]
                
                for pattern in patterns:
                    if re.search(pattern, term, re.IGNORECASE):
                        # 移除匹配的编号部分，保留属名和生物学术语
                        cleaned_term = re.sub(pattern, '', term, flags=re.IGNORECASE)
                        # 确保只保留属名和生物学术语
                        if second_word.lower() == 'phage':
                            return f"{first_word} phage"
                        elif second_word.lower() == 'sp.':
                            return f"{first_word} sp."
            
            # 检查是否符合双名法格式：属名（首字母大写）+ 种名（全小写或包含数字）
            # 但要排除生物学术语如 'phage', 'sp.' 等
            is_valid_genus = first_word[0].isupper() and all(c.islower() or c in ['.', '-', '_'] for c in first_word[1:])
            is_valid_species = all(c.islower() or c in ['.', '-', '_', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '[', ']'] for c in second_word)
            
            # 排除生物学术语作为种名
            is_bio_term = second_word.lower() in ['phage', 'sp.', 'subsp.', 'var.', 'str.', 'strain', 'isolate', 'clone']
            
            # 检查是否是有效的生物学术语（但不是编号）
            if is_valid_genus and is_valid_species and not is_bio_term:
                # 检查第二部分是否更像是编号而不是种名
                # 如果第二部分全是数字或看起来像编号，则可能是需要移除的部分
                looks_like_number = re.match(r'^\d+$', second_word) or \
                                   re.search(r'(?:\d+[A-Z]+\d*|[A-Z]+\d+|_|\-[A-Z]*\d)', second_word, re.IGNORECASE)
                
                # 如果第二部分看起来像编号，移除它
                if looks_like_number and len(words) > 2:
                    # 检查后续部分是否包含真正的编号模式
                    potential_number_part = ' '.join(words[1:])
                    patterns = [
                        r'\s+v?B_[A-Za-z0-9_]+$',  # 匹配 vB_CpeP_PMQ04 样式的编号
                        r'\s+\w*[A-Z]+\d+[A-Z]*-*\d*[A-Z]*$',  # 匹配 phiCP39-O, XP41-N3 等
                        r'\s+\w*[A-Z]*\d+-*\d*-*\d*[A-Z]*\d*$',  # 匹配 C2-6-12, DOBBIE2 等
                        r'\s+[a-z]*[A-Z]*[A-Z0-9]+$',  # 匹配 ctNU74 等
                    ]
                    
                    for pattern in patterns:
                        if re.search(pattern, term, re.IGNORECASE):
                            # 移除匹配的编号部分
                            cleaned_term = re.sub(pattern, '', term, flags=re.IGNORECASE)
                            return cleaned_term.strip()
                
                # 如果第二部分是有效种名，但后面还有编号，则移除编号部分
                elif len(words) > 2:
                    # 检查第三个及以后的词是否是编号
                    remaining_part = ' '.join(words[2:])
                    patterns = [
                        r'\s+v?B_[A-Za-z0-9_]+$',  # 匹配 vB_CpeP_PMQ04 样式的编号
                        r'\s+\w*[A-Z]+\d+[A-Z]*-*\d*[A-Z]*$',  # 匹配 phiCP39-O, XP41-N3 等
                        r'\s+\w*[A-Z]*\d+-*\d*-*\d*[A-Z]*\d*$',  # 匹配 C2-6-12, DOBBIE2 等
                        r'\s+[a-z]*[A-Z]*[A-Z0-9]+$',  # 匹配 ctNU74 等
                    ]
                    
                    for pattern in patterns:
                        if re.search(pattern, term, re.IGNORECASE):
                            # 移除匹配的编号部分，保留属名和种名
                            cleaned_term = re.sub(pattern, '', term, flags=re.IGNORECASE)
                            return cleaned_term.strip()
                
                # 如果只是简单的双名法，不做改变
                return term
        
        # 对于非双名法术语，应用编号移除规则
        # 定义编号模式的正则表达式
        patterns = [
            r'\s+v?B_[A-Za-z0-9_]+$',  # 匹配 vB_CpeP_PMQ04 样式的编号
            r'\s+\w*[A-Z]+\d+[A-Z]*-*\d*[A-Z]*$',  # 匹配 phiCP39-O, XP41-N3 等
            r'\s+\w*[A-Z]*\d+-*\d*-*\d*[A-Z]*\d*$',  # 匹配 C2-6-12, DOBBIE2 等
            r'\s+[a-z]*[A-Z]*[A-Z0-9]+$',  # 匹配 ctNU74 等
        ]
        
        # 依次尝试每个模式
        normalized_term = term
        for pattern in patterns:
            # 移除匹配的编号部分
            new_term = re.sub(pattern, '', normalized_term, flags=re.IGNORECASE)
            if new_term != normalized_term:
                normalized_term = new_term
                break  # 找到匹配项后停止
        
        # 如果上面的模式没有匹配，尝试更通用的方法
        if normalized_term == term:
            # 对于 "属名 phage 编号" 这样的模式，我们需要保留属名和phage，只移除编号
            # 如 "Clostridium phage phiCP39-O" -> "Clostridium phage"
            # 或 "Clostridium phage HMD-PC1" -> "Clostridium phage"
            phage_pattern = r'(\w+\s+phage)\s+[\w\d_-]+$'
            match = re.search(phage_pattern, term, re.IGNORECASE)
            if match:
                normalized_term = match.group(1)
                return normalized_term.strip()
        
        # 如果还是没有变化，尝试移除结尾的字母数字组合（增强版）
        if normalized_term == term:
            # 移除结尾的编号部分，但保留有意义的词汇
            # 这次使用更广泛的模式来匹配各种编号格式
            suffix_patterns = [
                r'\s+[A-Z]+-?[A-Z]*\d+[A-Z]*$',  # 匹配 HMD-PC1, XP41-N3 等
                r'\s+\w*[A-Z]*\d+[A-Z]*-*\d*[A-Z]*$',  # 更通用的数字字母组合
                r'\s+v?B_[A-Za-z0-9_]+$',  # 匹配 vB_CpeP_PMQ04 样式
                r'\s+[\w\d_-]+$',  # 最后兜底：任何以字母数字下划线结尾的部分
            ]
            
            for pattern in suffix_patterns:
                new_term = re.sub(pattern, '', normalized_term, flags=re.IGNORECASE)
                if new_term != normalized_term:
                    normalized_term = new_term
                    break
        
        # 如果还是没有变化，尝试移除结尾的字母数字组合
        if normalized_term == term:
            # 移除结尾的编号部分，但保留有意义的词汇
            normalized_term = re.sub(r'\s+[\w\d_-]+$', '', term)
        
        return normalized_term.strip()

    def _normalize_chinese_term(self, chinese_term: str, original_english: str) -> str:
        """
        根据英文术语的规范化结果，相应地规范化中文术语
        
        Args:
            chinese_term: 原始中文术语
            original_english: 原始英文术语
            
        Returns:
            str: 规范化后的中文术语
        """
        # 对英文术语进行规范化
        normalized_english = self.normalize_term(original_english)
        
        if normalized_english != original_english:
            # 英文术语被规范化了，我们需要相应地处理中文术语
            # 基于英文的变化来推断中文应该如何变化
            
            # 使用更通用的方法：根据英文术语的变化调整中文术语
            import re
            
            # 分析英文术语的变化
            original_parts = original_english.split()
            normalized_parts = normalized_english.split()
            
            if len(normalized_parts) < len(original_parts):
                # 从英文中移除了某些部分，相应地从中文中移除
                adjusted_chinese = chinese_term
                
                # 找出被移除的英文部分
                removed_parts = original_parts[len(normalized_parts):]
                
                # 根据被移除的部分调整中文
                for removed_part in removed_parts:
                    # 从数据库获取被移除部分的中文翻译
                    if self.translation_data_manager:
                        removed_chinese = self.translation_data_manager.get_translation(removed_part)
                        if removed_chinese:
                            # 从整体中文翻译中移除这部分
                            adjusted_chinese = adjusted_chinese.replace(removed_chinese, '').strip()
                
                # 清理多余空格
                adjusted_chinese = ' '.join(adjusted_chinese.split()).strip()
                
                # 如果调整后不为空，返回调整后的结果
                if adjusted_chinese:
                    return adjusted_chinese
            
            # 如果以上方法都不适用，使用通用方法：移除中文末尾的字母数字部分
            chinese_normalized = re.sub(r'[a-zA-Z0-9_\-]+$', '', chinese_term)
            # 清理可能剩余的空格或标点
            chinese_normalized = chinese_normalized.rstrip(' _-，。')
            return chinese_normalized.strip()
        else:
            # 英文没有被规范化，返回原始中文
            return chinese_term
        
        return chinese_term

    def _filter_meaningful_terms(self, original: str, translated: str) -> Tuple[str, str]:
        """
        过滤出有意义的术语部分，移除无意义的描述
        
        Args:
            original (str): 原始英文术语
            translated (str): 翻译后的中文术语
            
        Returns:
            tuple: (过滤后的英文术语, 过滤后的中文术语)
        """
        # 返回原始值，但可以在这里添加额外的过滤逻辑
        return original, translated

    def extract_and_store_key_terms(self, original: str, translated: str):
        """
        提取并存储关键术语翻译
        根据NCBI官方的物种分类模式进行结构化存储
        
        Args:
            original (str): 原文
            translated (str): 译文
        """
        # 如果没有翻译数据管理器，则直接返回
        if not self.translation_data_manager:
            return
            
        # 从翻译结果中提取纯文本（去除[AI]或[本地]前缀）
        clean_translated = translated
        if translated.startswith('[AI]'):
            clean_translated = translated[4:]  # 去掉前缀[AI]
        elif translated.startswith('[本地]'):
            clean_translated = translated[4:]  # 去掉前缀[本地]
            
        # 识别和过滤术语，只保留有意义的部分
        processed_original, processed_translation = self._filter_meaningful_terms(original, clean_translated)
        
        # 对原始术语进行规范化，移除编号部分
        normalized_original = self.normalize_term(processed_original)
        
        # 根据规范化结果处理中文翻译
        if normalized_original != processed_original:
            # 英文被规范化了，需要相应地处理中文翻译
            # 这里需要更智能地处理中文翻译，使其与英文的规范化保持一致
            normalized_translation = self._adjust_chinese_translation_for_normalized_english(
                processed_original, processed_translation, normalized_original
            )
        else:
            # 英文没有被规范化，使用原始中文翻译
            normalized_translation = processed_translation
        
        print(f"[术语规范化] 将 '{processed_original}' 规范化为 '{normalized_original}'")
        
        # 将规范化后的术语添加到翻译数据管理器中
        # 先尝试确定术语的分类
        category = self._determine_category(normalized_original)
        
        # 添加到翻译数据库
        try:
            # 为避免多线程冲突，先检查是否已存在该翻译
            existing_translation = self.translation_data_manager.get_translation(normalized_original)
            if not existing_translation:
                self.translation_data_manager.add_translation(normalized_original, normalized_translation, category)
                print(f"[翻译调试] 已将'{normalized_original}'的翻译结果存储到术语数据库，分类为'{category}'")
                
                # 学习这个术语的分类（用于后续改进）
                self.learn_from_examples([(normalized_original, category)])
            else:
                # 如果已存在，但内容不同，则更新
                if existing_translation != normalized_translation:
                    self.translation_data_manager.add_translation(normalized_original, normalized_translation, category)
                    print(f"[翻译调试] 已更新'{normalized_original}'的翻译结果，分类为'{category}'")
        except Exception as e:
            print(f"[翻译调试] 存储翻译结果到术语数据库失败: {e}")
            import traceback
            traceback.print_exc()

    def _adjust_chinese_translation_for_normalized_english(self, original_english: str, original_chinese: str, normalized_english: str) -> str:
        """
        根据英文术语的规范化结果，相应地调整中文翻译
        
        Args:
            original_english: 原始英文术语
            original_chinese: 原始中文翻译
            normalized_english: 规范化后的英文术语
            
        Returns:
            str: 调整后的中文翻译
        """
        # 如果规范化后的英文与原始英文相同，返回原始中文翻译
        if normalized_english == original_english:
            return original_chinese
        
        # 首先检查规范化后的英文术语是否已有翻译
        if self.translation_data_manager:
            direct_translation = self.translation_data_manager.get_translation(normalized_english)
            if direct_translation:
                return direct_translation
        
        # 特殊处理常见术语，但尽量从数据库获取信息
        if normalized_english.lower() == "unclassified":
            # 检查数据库中是否有"unclassified"的翻译
            db_translation = self.translation_data_manager.get_translation("unclassified") if self.translation_data_manager else None
            if db_translation:
                return db_translation
            else:
                return "未分类"  # 默认翻译
        elif normalized_english.lower() == "partial":
            db_translation = self.translation_data_manager.get_translation("partial") if self.translation_data_manager else None
            return db_translation if db_translation else "部分"
        elif normalized_english.lower() == "complete":
            db_translation = self.translation_data_manager.get_translation("complete") if self.translation_data_manager else None
            return db_translation if db_translation else "完整"
        elif normalized_english.lower() == "sequence":
            db_translation = self.translation_data_manager.get_translation("sequence") if self.translation_data_manager else None
            return db_translation if db_translation else "序列"
        elif normalized_english.lower() == "strain":
            db_translation = self.translation_data_manager.get_translation("strain") if self.translation_data_manager else None
            return db_translation if db_translation else "菌株"
        elif normalized_english.lower() == "isolate":
            db_translation = self.translation_data_manager.get_translation("isolate") if self.translation_data_manager else None
            return db_translation if db_translation else "分离株"
        elif normalized_english.lower() == "clone":
            db_translation = self.translation_data_manager.get_translation("clone") if self.translation_data_manager else None
            return db_translation if db_translation else "克隆"
        
        # 对于其他情况，如果规范化是移除了一些特定后缀，则从中文翻译中移除对应部分
        original_parts = original_english.split()
        normalized_parts = normalized_english.split()
        
        if len(normalized_parts) < len(original_parts):
            # 从英文中移除了某些部分，相应地从中文中移除
            adjusted_chinese = original_chinese
            
            # 找出被移除的英文部分
            removed_parts = original_parts[len(normalized_parts):]
            
            # 根据被移除的部分调整中文
            for removed_part in removed_parts:
                # 从数据库获取被移除部分的中文翻译
                if self.translation_data_manager:
                    removed_chinese = self.translation_data_manager.get_translation(removed_part)
                    if removed_chinese:
                        # 从整体中文翻译中移除这部分
                        adjusted_chinese = adjusted_chinese.replace(removed_chinese, '').strip()
                    else:
                        # 如果数据库中没有，尝试简单的模式匹配
                        import re
                        # 移除类似于编号或特定模式的部分
                        adjusted_chinese = re.sub(r'\s*' + re.escape(removed_part) + r'\s*', ' ', adjusted_chinese)
                        adjusted_chinese = ' '.join(adjusted_chinese.split()).strip()
            
            # 清理多余空格
            adjusted_chinese = ' '.join(adjusted_chinese.split()).strip()
            
            # 如果调整后不为空，返回调整后的结果
            if adjusted_chinese:
                return adjusted_chinese
        
        # 如果以上方法都不适用，尝试使用数据库中的直接翻译
        if self.translation_data_manager:
            fallback_translation = self.translation_data_manager.get_translation(normalized_english)
            if fallback_translation:
                return fallback_translation
        
        # 最后的回退：返回原始翻译
        return original_chinese

    def extract_blast_result_terms(self, csv_file_path: str):
        """
        从BLAST结果CSV文件中提取术语并保存到预定义术语文件中
        
        Args:
            csv_file_path (str): BLAST结果CSV文件路径
        """
        # 确定预定义术语文件路径
        predefined_terms_file = Path(__file__).parent.parent.parent.parent / "predefined_terms.csv"
        
        # 读取现有的预定义术语
        existing_terms = set()
        existing_terms_dict = {}  # 用于快速查找
        if predefined_terms_file.exists():
            with open(predefined_terms_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    term_key = (row['english'], row['category'])
                    existing_terms.add(term_key)
                    existing_terms_dict[term_key] = row['chinese']
        
        # 从CSV文件中提取术语
        new_terms = {}
        try:
            with open(csv_file_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # 提取基因类型
                    gene_type = row.get('基因类型', '').strip()
                    if gene_type:
                        translated_gene = self._translate_term_from_db(gene_type, 'gene')
                        new_terms[(gene_type, 'gene')] = translated_gene
                    
                    # 提取序列类型
                    sequence_type = row.get('序列类型', '').strip()
                    if sequence_type:
                        translated_sequence = self._translate_term_from_db(sequence_type, 'sequence')
                        new_terms[(sequence_type, 'sequence')] = translated_sequence
                    
                    # 提取菌株信息（可能包含术语和编码）
                    strain = row.get('菌株', '').strip()
                    if strain:
                        # 分离术语部分和编码部分
                        strain_term, strain_code = self._parse_strain_info(strain)
                        if strain_term:
                            translated_strain = self._translate_term_from_db(strain_term, 'strain')
                            new_terms[(strain_term, 'strain')] = translated_strain
        except Exception as e:
            print(f"读取CSV文件时出错: {e}")
            return
        
        # 合并现有术语和新术语
        all_terms = []
        # 先添加现有术语
        for term_key, chinese in existing_terms_dict.items():
            all_terms.append((term_key[0], chinese, term_key[1]))
        
        # 再添加新术语（避免重复）
        for term_key, chinese in new_terms.items():
            if term_key not in existing_terms:
                all_terms.append((term_key[0], chinese, term_key[1]))
        
        # 将所有术语写入预定义术语文件，分类使用英文
        try:
            with open(predefined_terms_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['english', 'chinese', 'category'])
                for term in all_terms:
                    writer.writerow(term)
            print(f"成功更新预定义术语文件: {predefined_terms_file}")
        except Exception as e:
            print(f"写入预定义术语文件时出错: {e}")

    def _determine_category(self, original: str) -> str:
        """
        确定术语的分类
        
        Args:
            original (str): 原始术语
            
        Returns:
            str: 分类名称
        """
        original_lower = original.lower().strip()
        words = original.split()
        
        # 检查学习到的模式（优先级最高）
        for category, learned_patterns in self.learning_patterns.items():
            for pattern in learned_patterns:
                if isinstance(pattern, str) and pattern.lower() in original_lower:
                    return category
        
        # 检查基因/蛋白质模式
        for pattern in self.classification_rules["gene_patterns"]:
            if pattern in original_lower:
                return 'gene'
        
        # 检查序列模式
        for pattern in self.classification_rules["sequence_patterns"]:
            if pattern in original_lower:
                return 'sequence'
        
        # 检查菌株模式
        for pattern in self.classification_rules["strain_patterns"]:
            if pattern in original_lower:
                return 'strain'
        
        # 检查是否为物种名称（双名法：属+种 或 属+种+其他）
        if len(words) >= 2:
            genus = words[0].strip()
            species = words[1].strip()
            
            # 检查属名是否符合生物学命名规范（首字母大写，其余小写或特殊字符）
            if (genus[0].isupper() and 
                all(c.islower() or c in ['.', '-', '_'] for c in genus[1:])):
                # 检查种名是否主要为小写字符
                if all(c.islower() or c in ['.', '-', '_', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9'] for c in species):
                    return 'species'
        
        # 检查是否包含常见属名（改进的属名识别逻辑）
        original_lower_clean = original_lower.replace('.', '').replace('-', '').replace('_', '')
        for genus in self.classification_rules["common_genera"]:
            if genus in original_lower_clean:
                # 如果包含属名且有多个单词，则可能是物种名
                if len(words) > 1:
                    # 检查第二个词是否看起来像物种名
                    species_word = words[1].lower()
                    if (species_word[0].islower() if species_word else False) or 'sp' in species_word or 'subsp' in species_word:
                        return 'species'
                else:
                    # 单个词可能是属名
                    return 'genus'
        
        # 检查是否为属名（单个词，以生物学后缀结尾，但先检查常见属名列表）
        if len(words) == 1:
            # 检查是否为单个单词的属名
            word = words[0].strip()
            if word[0].isupper() and len(word) > 2:
                # 检查是否以常见的属名后缀结尾
                for suffix in self.classification_rules["genus_suffixes"]:
                    if word.lower().endswith(suffix):
                        return 'genus'
        
        # 检查是否为噬菌体或病毒
        for virus_term in self.classification_rules["virus_terms"]:
            if virus_term in original_lower:
                return 'other'  # 病毒归入other类
        
        # 噬菌体通常是针对特定细菌的，应视为物种级别的分类
        for phage_term in self.classification_rules["phage_terms"]:
            if phage_term in original_lower:
                # 如果是噬菌体，检查是否遵循属+种的模式
                if len(words) >= 2:
                    genus = words[0].strip()
                    species_part = words[1].strip()
                    if (genus[0].isupper() and 
                        all(c.islower() or c in ['.', '-', '_', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9'] for c in species_part)):
                        return 'species'
                # 对于以Clostridium phage开头的，视为物种
                if original_lower.startswith('clostridium phage'):
                    return 'species'
                # 检查是否包含常见属名
                for genus in self.classification_rules["common_genera"]:
                    if genus in original_lower_clean:
                        return 'species'
                # 默认情况下，噬菌体也可以视为物种
                return 'species'
        
        # 检查是否为分类单元（如门、纲、目等）
        for rank in self.classification_rules["taxonomic_ranks"]:
            if rank in original_lower:
                return 'other'
        
        # 检查是否为特殊术语
        for term in self.classification_rules["special_terms"]:
            if term in original_lower:
                return 'species'  # 包含这些词的通常表示物种
        
        # 检查是否为未培养或环境样本术语
        if 'uncultured' in original_lower or 'environmental' in original_lower or 'sample' in original_lower:
            return 'other'
        
        # 默认返回 'other'
        return 'other'

    def _translate_term_from_db(self, term: str, category: str = None) -> str:
        """
        从内存缓存中获取术语翻译 (替代原有的文件读取方法)
        """
        if not term:
            return term
            
        term_key = term.strip()
        
        # 1. 检查缓存中是否有该术语
        if term_key in self._predefined_terms_cache:
            candidates = self._predefined_terms_cache[term_key]
            
            # 2. 如果指定了分类，优先精确匹配
            if category:
                for item in candidates:
                    if item['category'] == category.strip():
                        return item['chinese']
            
            # 3. 如果没指定分类，或者分类未匹配到，返回第一个匹配项
            if candidates:
                return candidates[0]['chinese']
                
        # 如果缓存未命中，返回原术语
        return term

    def _translate_gene_term(self, gene_term: str) -> str:
        """
        翻译基因术语
        
        Args:
            gene_term (str): 英文基因术语
            
        Returns:
            str: 中文翻译
        """
        return self._translate_term_from_db(gene_term, 'gene')

    def _translate_sequence_term(self, sequence_term: str) -> str:
        """
        翻译序列术语
        
        Args:
            sequence_term (str): 英文序列术语
            
        Returns:
            str: 中文翻译
        """
        return self._translate_term_from_db(sequence_term, 'sequence')

    def _translate_strain_term(self, strain_term: str) -> str:
        """
        翻译菌株术语
        
        Args:
            strain_term (str): 英文菌株术语
            
        Returns:
            str: 中文翻译
        """
        return self._translate_term_from_db(strain_term, 'strain')

    def _parse_strain_info(self, strain_info: str) -> Tuple[str, str]:
        """
        解析菌株信息，分离术语部分和编码部分
        
        Args:
            strain_info (str): 完整的菌株信息
            
        Returns:
            tuple: (术语部分, 编码部分)
        """
        if not strain_info:
            return "", ""
        
        # 分离术语和编码部分
        parts = strain_info.split(' ', 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        else:
            return strain_info, ""