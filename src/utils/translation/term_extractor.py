"""
术语提取和存储模块
用于从生物学术语中提取关键术语并存储到翻译数据库中
I/O 优化版 - 使用内存缓存提高性能
"""

import csv
import json
import re
from pathlib import Path


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
        
        # 添加线程锁
        import threading
        self._lock = threading.Lock()
        
        # [优化点] 初始化时加载预定义术语到内存缓存
        self._predefined_terms_cache = {}
        self._load_predefined_terms_to_cache()

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
                "gene_patterns": ["gene", "protein", "hydrolase", "oxidase", "reductase", "transferase", "kinase", "enzyme"],
                "sequence_patterns": ["sequence", "genome", "cds", "fragment"],
                "strain_patterns": ["strain", "isolate", "clone"],
                "taxonomic_ranks": ["phylum", "class", "order", "family"],
                "special_terms": ["sp.", "subsp.", "var."],
                "common_genera": ["staphylococcus", "escherichia", "bacillus", "pseudomonas", "clostridium"],
                "genus_suffixes": ["us", "a", "um", "er", "ia", "ella"],
                "virus_terms": ["virus", "viral"],
                "phage_terms": ["phage"]
            }

    def _load_predefined_terms_to_cache(self):
        """[新增方法] 将预定义术语加载到内存缓存"""
        try:
            # 使用更健壮的路径获取方案
            root_dir = Path(__file__).parent.parent.parent.parent
            predefined_terms_file = root_dir / "predefined_terms.csv"
            
            if predefined_terms_file.exists():
                with open(predefined_terms_file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        term = row.get('english', '').strip()
                        category = row.get('category', '').strip()
                        chinese = row.get('chinese', '').strip()
                        
                        if not term: continue
                        
                        if term not in self._predefined_terms_cache:
                            self._predefined_terms_cache[term] = []
                        
                        self._predefined_terms_cache[term].append({
                            'chinese': chinese,
                            'category': category
                        })
        except Exception as e:
            print(f"警告: 预加载术语库失败: {e}")

    # Removed: _load_learned_patterns, _save_learned_patterns, learn_from_examples, 
    # _extract_features_from_term, _update_classification_rules_with_learned_patterns
    # for simplicity and reliability as requested by user.

    def normalize_term(self, term: str) -> str:
        """
        规范化术语，移除编号部分，如phiCP39-O, DOBBIE2, XP41-N3, strain WS02等
        但保留有效的生物学名称，如属+种的双名法命名
        """
        if not term:
            return term
            
        # 1. 首先处理方括号等特殊字符
        term = term.strip()
        if term.startswith('[') and term.endswith(']'):
            term = term[1:-1].strip()
        elif term.startswith('['):
            term = term[1:].strip()
            
        # 2. 定义需要彻底裁剪的噪音关键字（及其后续所有内容）
        # 这些词通常标志着非规范化部分的开始
        strip_keywords = [
            'strain', 'isolate', 'clone', 'serotype', 'subtype', 
            'str.', 'str', 'isolate:', 'type:', 'sample', 'accession'
        ]
        
        # 3. 定义需要保留但需要裁剪后续编号的关键字
        keep_keywords = ['phage', 'sp.', 'subsp.', 'var.', 'ssp.']

        # 4. 执行基于关键字的裁剪
        words = term.split()
        normalized_words = []
        
        for i, word in enumerate(words):
            lower_word = word.lower().rstrip(',;:').strip('.')
            
            # 如果遇到彻底裁剪关键字，直接停止并返回之前的部分
            if lower_word in strip_keywords:
                break
                
            # 如果遇到保留关键字
            if lower_word in [k.strip('.') for k in keep_keywords] or word.lower() in keep_keywords:
                normalized_words.append(word)
                break # 保留关键字通常是名称的最后有效部分（如 xxx phage）

            normalized_words.append(word)
            
        # 重新组合
        normalized_term = ' '.join(normalized_words).strip().rstrip(',;: ')
        
        if normalized_term == term:
            # 强化正则：必须包含数字或特定的 ID 格式，避免误删普通单词
            patterns = [
                (r'\s+v?B_[A-Za-z0-9_]+$', re.IGNORECASE),  # 匹配 vB_xxxx
                (r'\s+[A-Z\d_\-]{2,}$', 0),                 # 匹配全大写/数字的 ID (至少2位)
                (r'\s+[A-Za-z]*\d+[A-Za-z0-9]*$', 0),       # 匹配包含数字的 ID
                (r'\s+[A-Z]+[A-Za-z]*\d+$', 0),             # 匹配以大写开头且包含数字的 ID
            ]
            for pattern, flags in patterns:
                new_term = re.sub(pattern, '', normalized_term, flags=flags)
                if new_term != normalized_term:
                    normalized_term = new_term
                    break
        
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
        
        if normalized_original != processed_original:
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
        从 BLAST 结果 CSV 中增量提取术语 (I/O 优化版)
        """
        try:
            root_dir = Path(__file__).parent.parent.parent.parent
            predefined_terms_file = root_dir / "predefined_terms.csv"
            
            # 使用内存缓存后的快速去重检查
            existing_keys = set()
            for term, entries in self._predefined_terms_cache.items():
                for entry in entries:
                    existing_keys.add((term, entry['category']))
            
            new_rows = []
            with open(csv_file_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # 批量检查感兴趣的列
                    for col, category in [('基因类型', 'gene'), ('序列类型', 'sequence'), ('菌株', 'strain')]:
                        val = row.get(col, '').strip()
                        if not val: continue
                        
                        # 如果是菌株，可能需要特殊处理（移除编码）
                        term_to_save = val
                        if category == 'strain':
                            term_to_save, _ = self._parse_strain_info(val)
                        
                        if (term_to_save, category) not in existing_keys:
                            # 确定翻译 (如果缓存中没有，可能是新抓取的)
                            translated = self._translate_term_from_db(term_to_save, category)
                            new_rows.append([term_to_save, translated, category])
                            existing_keys.add((term_to_save, category))
            
            # 仅在有新条目时追加，避免全量重写
            if new_rows:
                file_exists = predefined_terms_file.exists()
                with open(predefined_terms_file, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    if not file_exists:
                        writer.writerow(['english', 'chinese', 'category'])
                    writer.writerows(new_rows)
                    
                # 同步更新内存缓存，防止同一批次内重复
                for term, trans, cat in new_rows:
                    if term not in self._predefined_terms_cache:
                        self._predefined_terms_cache[term] = []
                    self._predefined_terms_cache[term].append({'chinese': trans, 'category': cat})
                
                print(f"[I/O 优化] 已向预定义术语表追加 {len(new_rows)} 条新记录")
                
        except Exception as e:
            print(f"提取 BLAST 结果术语时出错: {e}")

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
        
        # Determination based on static rules and predefined patterns
        # Removed dynamic learning patterns lookup for reliability.
        
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
            
            # [优化] 拦截明显的生化描述后缀 (仅对长单词)，防止 mis-id 为属名
            # 如 Hydrolase (9) 拦截, Base (4) 放行
            if len(genus) > 6 and genus.lower().endswith(('ase', 'zyme', 'in', 'ogen', 'one', 'an', 'ate', 'ide')):
                return 'other'
            
            # [优化] 上下文种加词拦截
            # 如果第二个词本身就是生化名词后缀，则它一定不是物种名
            biochem_descriptors = [
                'precursor', 'receptor', 'complex', 'factor', 'family', 'domain', 
                'subunit', 'enzyme', 'protein', 'kinase', 'binding', 'inhibitor'
            ]
            if species.lower() in biochem_descriptors:
                return 'gene'

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