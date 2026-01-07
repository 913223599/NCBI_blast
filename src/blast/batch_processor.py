"""
批量处理模块
负责批量处理序列文件的BLAST查询
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime

from src.utils.file_handler import FileHandler
from .executor import BlastExecutor, delay_before_request
from .parser import BlastResultParser
from .result_converter import BlastResultConverter
from .result_cache import BlastResultCache


class BatchProcessor:
    """
    批量处理器类
    负责多线程批量处理序列文件
    """
    
    def __init__(self, max_workers=3, advanced_settings=None):  # 减少默认线程数
        """
        初始化批量处理器
        
        Args:
            max_workers (int): 最大工作线程数，默认为1（减少并发以避免NCBI限制和崩溃）
            advanced_settings (dict): 高级设置参数，包含BLAST搜索的高级参数设置
                                      默认为None，表示使用BLAST的默认参数
        """
        self.max_workers = max_workers
        self.advanced_settings = advanced_settings or {}
        self.file_handler = FileHandler()
        self.blast_executor = BlastExecutor()
        self.result_parser = BlastResultParser()
        self.result_converter = BlastResultConverter()
        self.cache = BlastResultCache(cache_dir="cache", expiry_time=86400)  # 24小时缓存
        self.on_task_start = None  # 任务开始回调
        self.on_progress_update = None  # 进度更新回调
        self.on_result_received = None  # 结果接收回调
        self.on_all_tasks_complete = None  # 所有任务完成回调
        self._cancel_flag = False  # 取消标志
        self.timestamp_folder = self._create_timestamp_folder()

    def _create_timestamp_folder(self):
        """
        创建基于时间戳的结果保存文件夹
        
        Returns:
            Path: 时间戳文件夹路径
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder_path = Path("results") / timestamp
        folder_path.mkdir(parents=True, exist_ok=True)
        return folder_path
    
    def cancel_processing(self):
        """
        取消处理过程
        """
        self._cancel_flag = True
    
    def process_single_sequence(self, sequence_file):
        """
        处理单个序列文件
        
        Args:
            sequence_file (str): 序列文件路径
            
        Returns:
            dict: 处理结果信息，包含以下键值:
                  - file: 序列文件路径
                  - status: 处理状态 ("success" 或 "error")
                  - result_file: 结果文件路径 (仅在成功时存在)
                  - error: 错误信息 (仅在失败时存在)
                  - thread_id: 处理线程ID
                  - elapsed_time: 处理耗时(秒)
        """
        thread_id = threading.current_thread().ident
        start_time = time.time()
        
        try:
            # 获取文件名（不含扩展名）用于结果文件命名
            file_name = Path(sequence_file).stem
            result_file = self.timestamp_folder / f"{file_name}_blast_result.xml"
            csv_file = self.timestamp_folder / f"{file_name}_blast_result.csv"
            desc_file = self.timestamp_folder / f"{file_name}_blast_result.desc"
            
            # 调用任务开始回调
            if self.on_task_start:
                self.on_task_start(sequence_file)
            
            # 读取序列
            sequence = self.file_handler.read_sequence_file(str(sequence_file))
            
            # 验证序列是否有效
            if not sequence or len(sequence.strip()) == 0:
                raise ValueError(f"无法从文件中读取有效序列: {sequence_file}")
            
            # 检查缓存
            use_cache = self.advanced_settings.get('use_cache', True)
            if use_cache:
                sequence_id = Path(sequence_file).stem  # 使用文件名作为序列ID
                cached_result = self.cache.get_cached_result(sequence, sequence_id)
                if cached_result:
                    print(f"✓ 使用缓存结果: {Path(sequence_file).name}")
                    cached_result['from_cache'] = True
                    return cached_result
            
            # 准备BLAST参数，设置更快的默认值
            blast_params = {}
            
            # 添加启用的参数，设置更快的默认值
            if 'hitlist_size' in self.advanced_settings and self.advanced_settings['hitlist_size'] is not None:
                blast_params['hitlist_size'] = self.advanced_settings['hitlist_size']
            else:
                # 使用较小的默认值以提高速度
                blast_params['hitlist_size'] = 10
                
            if 'word_size' in self.advanced_settings and self.advanced_settings['word_size'] is not None:
                blast_params['word_size'] = self.advanced_settings['word_size']
                
            if 'evalue' in self.advanced_settings and self.advanced_settings['evalue'] is not None:
                blast_params['evalue'] = self.advanced_settings['evalue']
            else:
                # 使用更严格的默认值以提高速度
                blast_params['evalue'] = 0.1
                
            if 'matrix_name' in self.advanced_settings and self.advanced_settings['matrix_name'] is not None:
                blast_params['matrix_name'] = self.advanced_settings['matrix_name']
                
            if 'filter' in self.advanced_settings and self.advanced_settings['filter'] is not None:
                blast_params['filter'] = self.advanced_settings['filter']
                
            if 'alignments' in self.advanced_settings and self.advanced_settings['alignments'] is not None:
                blast_params['alignments'] = self.advanced_settings['alignments']
            else:
                # 使用较小的默认值以提高速度
                blast_params['alignments'] = 100
                
            if 'descriptions' in self.advanced_settings and self.advanced_settings['descriptions'] is not None:
                blast_params['descriptions'] = self.advanced_settings['descriptions']
            else:
                # 使用较小的默认值以提高速度
                blast_params['descriptions'] = 100
            
            # 根据序列类型选择合适的BLAST程序和数据库
            sequence_type = self._detect_sequence_type(sequence)
            
            if sequence_type == 'protein':
                program = 'blastp'
                database = self.advanced_settings.get('protein_database', 'nr')
            else:
                program = 'blastn'
                database = self.advanced_settings.get('nucleotide_database', 'nt')
            
            # 在发送请求前添加延迟，以控制请求频率并遵循NCBI限制
            delay_before_request()  # 使用伪队列机制控制请求频率
            
            # 执行BLAST搜索，传递参数
            result_handle = self.blast_executor.execute_with_retry(
                sequence,
                program=program,
                database=database,
                timeout_minutes=6,
                **blast_params
            )
            
            # 保存结果到文件（使用序列文件名命名）
            self.file_handler.save_result_file(result_handle, str(result_file))
            result_handle.close()
            
            # 将XML结果转换为CSV格式并生成描述文件
            self.result_converter.convert_xml_to_csv(str(result_file), str(csv_file), str(desc_file))
            
            # 重新打开结果文件进行解析
            result_handle = open(result_file)
            result_handle.close()
            
            # 保存到缓存
            if use_cache:
                sequence_id = Path(sequence_file).stem  # 使用文件名作为序列ID
                cache_result = {
                    "file": sequence_file,
                    "status": "success",
                    "result_file": result_file,
                    "csv_file": csv_file,
                    "desc_file": desc_file,
                    "thread_id": thread_id,
                    "elapsed_time": 0,  # 缓存结果不需要计算处理时间
                    "timestamp_folder": str(self.timestamp_folder)  # 记录时间戳文件夹
                }
                self.cache.save_result(sequence, cache_result, sequence_id)
            
            end_time = time.time()
            elapsed_time = end_time - start_time
            
            result = {
                "file": sequence_file,
                "status": "success",
                "result_file": result_file,
                "csv_file": csv_file,
                "desc_file": desc_file,
                "thread_id": thread_id,
                "elapsed_time": elapsed_time
            }
            
            return result
        except Exception as e:
            end_time = time.time()
            elapsed_time = end_time - start_time
            
            print(f"处理文件 {sequence_file} 时出错: {e}")
            result = {
                "file": sequence_file,
                "status": "error",
                "error": str(e),
                "thread_id": thread_id,
                "elapsed_time": elapsed_time
            }
            
            return result
    
    def _detect_sequence_type(self, sequence):
        """
        检测序列类型（核苷酸或蛋白质）
        
        Args:
            sequence (str): 序列字符串
            
        Returns:
            str: 'nucleotide' 或 'protein'
        """
        # 检查序列中是否包含蛋白质特有氨基酸（如K, E, P, etc.）
        sequence_upper = sequence.upper()
        
        # 核苷酸字符集合
        nucleotide_chars = set('ATCGNU')
        # 蛋白质特有字符集合
        protein_chars = set('KERYWHDNQSTVRLEAICGPMF')
        
        # 过滤掉非字母字符
        seq_chars = set(c for c in sequence_upper if c.isalpha())
        
        # 计算核苷酸字符和蛋白质字符的数量
        nucleotide_count = sum(1 for c in seq_chars if c in nucleotide_chars)
        protein_count = sum(1 for c in seq_chars if c in protein_chars)
        
        # 如果序列中同时包含核苷酸和蛋白质字符，根据比例判断
        if nucleotide_count > 0 and protein_count > 0:
            # 检查序列中是否包含核苷酸模式（连续的A,T,G,C字符）
            import re
            nucleotide_pattern = r'[ATCGU]{3,}'  # 至少3个连续的核苷酸字符
            protein_pattern = r'[KERYWHDNQSTVRLEAICGPMF]{3,}'  # 至少3个连续的蛋白质字符
            
            has_nucleotide_pattern = bool(re.search(nucleotide_pattern, sequence_upper))
            has_protein_pattern = bool(re.search(protein_pattern, sequence_upper))
            
            if has_nucleotide_pattern and not has_protein_pattern:
                return 'nucleotide'
            elif has_protein_pattern and not has_nucleotide_pattern:
                return 'protein'
            elif has_protein_pattern and has_nucleotide_pattern:
                # 如果都有，根据序列长度和字符比例判断
                total_len = len(sequence_upper)
                protein_chars_in_seq = sum(1 for c in sequence_upper if c in protein_chars)
                nucleotide_chars_in_seq = sum(1 for c in sequence_upper if c in nucleotide_chars)
                
                protein_ratio = protein_chars_in_seq / total_len if total_len > 0 else 0
                nucleotide_ratio = nucleotide_chars_in_seq / total_len if total_len > 0 else 0
                
                if protein_ratio > nucleotide_ratio:
                    return 'protein'
                else:
                    return 'nucleotide'
        
        # 如果只包含一种类型的字符
        elif nucleotide_count > 0 and protein_count == 0:
            # 检查是否主要是核苷酸字符
            nucleotide_seq_chars = [c for c in sequence_upper if c in nucleotide_chars]
            if len(nucleotide_seq_chars) / len(sequence_upper) > 0.7:  # 70%以上是核苷酸字符
                return 'nucleotide'
        
        elif protein_count > 0 and nucleotide_count == 0:
            # 检查是否主要是蛋白质字符
            protein_seq_chars = [c for c in sequence_upper if c in protein_chars]
            if len(protein_seq_chars) / len(sequence_upper) > 0.7:  # 70%以上是蛋白质字符
                return 'protein'
        
        # 默认情况下，如果序列较长且包含蛋白质字符，认为是蛋白质序列
        if len(sequence_upper) > 10 and protein_count > 0:
            return 'protein'
        
        # 否则默认为核苷酸序列
        return 'nucleotide'
    
    def process_sequences(self, sequence_files):
        """
        批量处理序列文件
        
        Args:
            sequence_files (list): 序列文件路径列表
            
        Returns:
            list: 处理结果列表
        """
        # 只有当有多个文件时才打印批量处理信息
        if len(sequence_files) > 1:
            print(f"开始批量处理 {len(sequence_files)} 个序列文件...")
            print(f"使用 {self.max_workers} 个线程进行处理（减少并发以避免NCBI限制）")
        
        # 时间戳文件夹已在初始化时创建
        
        # 使用线程池处理序列文件
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交所有任务
            future_to_file = {
                executor.submit(self.process_single_sequence, seq_file): seq_file
                for seq_file in sequence_files
            }
            
            # 收集结果
            results = []
            completed = 0
            total = len(sequence_files)
            
            for future in as_completed(future_to_file):
                # 更新进度
                if self.on_progress_update:
                    self.on_progress_update(completed, total)
                
                file = future_to_file[future]
                try:
                    result = future.result()
                    results.append(result)
                    if result["status"] == "success":
                        print(f"✓ 完成处理: {Path(file).name}")
                    else:
                        print(f"✗ 处理失败: {Path(file).name} - {result['error']}")
                    
                    # 发送结果（确保只发送一次）
                    if self.on_result_received:
                        self.on_result_received(result)
                except Exception as e:
                    print(f"✗ 处理 {file} 时发生异常: {e}")
                    error_result = {
                        "file": file,
                        "status": "error",
                        "error": str(e)
                    }
                    results.append(error_result)
                    if self.on_result_received:
                        self.on_result_received(error_result)
                
                # 更新完成计数
                completed += 1
                
                # 更新进度
                if self.on_progress_update:
                    self.on_progress_update(completed, total)
        
        # 调用所有任务完成回调
        if self.on_all_tasks_complete:
            self.on_all_tasks_complete(results)
            
        return results
    
    def print_summary(self, results):
        """
        打印处理结果总结
        
        Args:
            results (list): 处理结果列表
        """
        successful = sum(1 for r in results if r["status"] == "success")
        failed = len(results) - successful
        
        print(f"\n批量处理完成!")
        print(f"总共处理: {len(results)} 个文件")
        print(f"成功处理: {successful} 个文件")
        print(f"处理失败: {failed} 个文件")
        
        if failed > 0:
            print("\n失败的文件:")
            for result in results:
                if result["status"] == "error":
                    print(f"  - {Path(result['file']).name}: {result['error']}")


class MultiSequenceBatchProcessor:
    """
    多序列批量处理器类
    负责处理包含多个序列的单个文件
    """
    
    def __init__(self, max_workers=3, advanced_settings=None):  # 减少默认线程数
        """
        初始化多序列批量处理器
        
        Args:
            max_workers (int): 最大工作线程数，默认为2（减少并发以避免NCBI限制）
            advanced_settings (dict): 高级设置参数
        """
        self.max_workers = max_workers
        self.advanced_settings = advanced_settings or {}
        self.file_handler = FileHandler()
        self.blast_executor = BlastExecutor()
        self.result_parser = BlastResultParser()
        self.result_converter = BlastResultConverter()
        self.cache = BlastResultCache(cache_dir="cache", expiry_time=86400)  # 24小时缓存
        self.on_task_start = None  # 任务开始回调
        self.on_progress_update = None  # 进度更新回调
        self.on_result_received = None  # 结果接收回调
        self.on_all_tasks_complete = None  # 所有任务完成回调
        self._cancel_flag = False  # 取消标志
        self.timestamp_folder = self._create_timestamp_folder()

    def _create_timestamp_folder(self):
        """
        创建基于时间戳的结果保存文件夹
        
        Returns:
            Path: 时间戳文件夹路径
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder_path = Path("results") / timestamp
        folder_path.mkdir(parents=True, exist_ok=True)
        return folder_path
    
    def cancel_processing(self):
        """
        取消处理过程
        """
        self._cancel_flag = True
    
    def process_single_sequence(self, sequence_info, original_file_path):
        """
        处理单个序列信息
        
        Args:
            sequence_info (dict): 序列信息字典，包含'id', 'description', 'sequence'等
            original_file_path (str): 原始文件路径
            
        Returns:
            dict: 处理结果
        """
        thread_id = threading.current_thread().ident
        start_time = time.time()
        
        try:
            # 获取原始文件名（不含扩展名）和序列ID用于结果文件命名
            base_name = Path(original_file_path).stem
            sequence_id = sequence_info['id'].replace('|', '_').replace(' ', '_')  # 确保文件名安全
            result_file = self.timestamp_folder / f"{base_name}_{sequence_id}_blast_result.xml"
            csv_file = self.timestamp_folder / f"{base_name}_{sequence_id}_blast_result.csv"
            desc_file = self.timestamp_folder / f"{base_name}_{sequence_id}_blast_result.desc"
            
            # 调用任务开始回调
            if self.on_task_start:
                self.on_task_start(f"{original_file_path} - {sequence_info['id']}")
            
            sequence = sequence_info['sequence']
            
            # 验证序列是否有效
            if not sequence or len(sequence.strip()) == 0:
                raise ValueError(f"序列信息中包含空序列: {sequence_info['id']}")
            
            # 检查缓存
            use_cache = self.advanced_settings.get('use_cache', True)
            if use_cache:
                cached_result = self.cache.get_cached_result(sequence)
                if cached_result:
                    print(f"✓ 使用缓存结果: {sequence_info['id']}")
                    cached_result['from_cache'] = True
                    return cached_result
            
            # 准备BLAST参数，设置更快的默认值
            blast_params = {}
            
            # 添加启用的参数，设置更快的默认值
            if 'hitlist_size' in self.advanced_settings and self.advanced_settings['hitlist_size'] is not None:
                blast_params['hitlist_size'] = self.advanced_settings['hitlist_size']
            else:
                # 使用较小的默认值以提高速度
                blast_params['hitlist_size'] = 10
                
            if 'word_size' in self.advanced_settings and self.advanced_settings['word_size'] is not None:
                blast_params['word_size'] = self.advanced_settings['word_size']
                
            if 'evalue' in self.advanced_settings and self.advanced_settings['evalue'] is not None:
                blast_params['evalue'] = self.advanced_settings['evalue']
            else:
                # 使用更严格的默认值以提高速度
                blast_params['evalue'] = 0.1
                
            if 'matrix_name' in self.advanced_settings and self.advanced_settings['matrix_name'] is not None:
                blast_params['matrix_name'] = self.advanced_settings['matrix_name']
                
            if 'filter' in self.advanced_settings and self.advanced_settings['filter'] is not None:
                blast_params['filter'] = self.advanced_settings['filter']
                
            if 'alignments' in self.advanced_settings and self.advanced_settings['alignments'] is not None:
                blast_params['alignments'] = self.advanced_settings['alignments']
            else:
                # 使用较小的默认值以提高速度
                blast_params['alignments'] = 100
                
            if 'descriptions' in self.advanced_settings and self.advanced_settings['descriptions'] is not None:
                blast_params['descriptions'] = self.advanced_settings['descriptions']
            else:
                # 使用较小的默认值以提高速度
                blast_params['descriptions'] = 100
            
            # 根据序列类型选择合适的BLAST程序和数据库
            sequence_type = self._detect_sequence_type(sequence)
            
            if sequence_type == 'protein':
                program = 'blastp'
                database = self.advanced_settings.get('protein_database', 'nr')
            else:
                program = 'blastn'
                database = self.advanced_settings.get('nucleotide_database', 'nt')
            
            # 在发送请求前添加延迟，以控制请求频率并遵循NCBI限制
            delay_before_request()  # 使用伪队列机制控制请求频率
            
            # 执行BLAST搜索，传递参数
            result_handle = self.blast_executor.execute_with_retry(
                sequence,
                program=program,
                database=database,
                **blast_params
            )
            
            # 保存结果到文件
            self.file_handler.save_result_file(result_handle, str(result_file))
            result_handle.close()
            
            # 将XML结果转换为CSV格式并生成描述文件
            self.result_converter.convert_xml_to_csv(str(result_file), str(csv_file), str(desc_file))
            
            # 保存到缓存
            if use_cache:
                cache_result = {
                    "file": original_file_path,
                    "sequence_id": sequence_info['id'],
                    "sequence_description": sequence_info['description'],
                    "status": "success",
                    "result_file": result_file,
                    "csv_file": csv_file,
                    "desc_file": desc_file,
                    "thread_id": thread_id,
                    "elapsed_time": 0,  # 缓存结果不需要计算处理时间
                    "timestamp_folder": str(self.timestamp_folder)  # 记录时间戳文件夹
                }
                self.cache.save_result(sequence, cache_result)
            
            end_time = time.time()
            elapsed_time = end_time - start_time
            
            result = {
                "file": original_file_path,
                "sequence_id": sequence_info['id'],
                "sequence_description": sequence_info['description'],
                "status": "success",
                "result_file": result_file,
                "csv_file": csv_file,
                "desc_file": desc_file,
                "thread_id": thread_id,
                "elapsed_time": elapsed_time
            }
            
            return result
        except Exception as e:
            end_time = time.time()
            elapsed_time = end_time - start_time
            
            print(f"处理序列 {sequence_info['id']} 时出错: {e}")
            result = {
                "file": original_file_path,
                "sequence_id": sequence_info['id'],
                "sequence_description": sequence_info['description'],
                "status": "error",
                "error": str(e),
                "thread_id": thread_id,
                "elapsed_time": elapsed_time
            }
            
            return result
    
    def _detect_sequence_type(self, sequence):
        """
        检测序列类型（核苷酸或蛋白质）
        
        Args:
            sequence (str): 序列字符串
            
        Returns:
            str: 'nucleotide' 或 'protein'
        """
        # 检查序列中是否包含蛋白质特有氨基酸（如K, E, P, etc.）
        sequence_upper = sequence.upper()
        
        # 核苷酸字符集合
        nucleotide_chars = set('ATCGNU')
        # 蛋白质特有字符集合
        protein_chars = set('KERYWHDNQSTVRLEAICGPMF')
        
        # 过滤掉非字母字符
        seq_chars = set(c for c in sequence_upper if c.isalpha())
        
        # 计算核苷酸字符和蛋白质字符的数量
        nucleotide_count = sum(1 for c in seq_chars if c in nucleotide_chars)
        protein_count = sum(1 for c in seq_chars if c in protein_chars)
        
        # 如果序列中同时包含核苷酸和蛋白质字符，根据比例判断
        if nucleotide_count > 0 and protein_count > 0:
            # 检查序列中是否包含核苷酸模式（连续的A,T,G,C字符）
            import re
            nucleotide_pattern = r'[ATCGU]{3,}'  # 至少3个连续的核苷酸字符
            protein_pattern = r'[KERYWHDNQSTVRLEAICGPMF]{3,}'  # 至少3个连续的蛋白质字符
            
            has_nucleotide_pattern = bool(re.search(nucleotide_pattern, sequence_upper))
            has_protein_pattern = bool(re.search(protein_pattern, sequence_upper))
            
            if has_nucleotide_pattern and not has_protein_pattern:
                return 'nucleotide'
            elif has_protein_pattern and not has_nucleotide_pattern:
                return 'protein'
            elif has_protein_pattern and has_nucleotide_pattern:
                # 如果都有，根据序列长度和字符比例判断
                total_len = len(sequence_upper)
                protein_chars_in_seq = sum(1 for c in sequence_upper if c in protein_chars)
                nucleotide_chars_in_seq = sum(1 for c in sequence_upper if c in nucleotide_chars)
                
                protein_ratio = protein_chars_in_seq / total_len if total_len > 0 else 0
                nucleotide_ratio = nucleotide_chars_in_seq / total_len if total_len > 0 else 0
                
                if protein_ratio > nucleotide_ratio:
                    return 'protein'
                else:
                    return 'nucleotide'
        
        # 如果只包含一种类型的字符
        elif nucleotide_count > 0 and protein_count == 0:
            # 检查是否主要是核苷酸字符
            nucleotide_seq_chars = [c for c in sequence_upper if c in nucleotide_chars]
            if len(nucleotide_seq_chars) / len(sequence_upper) > 0.7:  # 70%以上是核苷酸字符
                return 'nucleotide'
        
        elif protein_count > 0 and nucleotide_count == 0:
            # 检查是否主要是蛋白质字符
            protein_seq_chars = [c for c in sequence_upper if c in protein_chars]
            if len(protein_seq_chars) / len(sequence_upper) > 0.7:  # 70%以上是蛋白质字符
                return 'protein'
        
        # 默认情况下，如果序列较长且包含蛋白质字符，认为是蛋白质序列
        if len(sequence_upper) > 10 and protein_count > 0:
            return 'protein'
        
        # 否则默认为核苷酸序列
        return 'nucleotide'
    
    def process_sequences_from_file(self, sequence_file):
        """
        处理来自单个文件的多个序列
        
        Args:
            sequence_file (str): 序列文件路径
            
        Returns:
            list: 处理结果列表
        """
        print(f"开始处理文件 {Path(sequence_file).name} 中的多条序列...")
        print(f"使用 {self.max_workers} 个线程进行处理（减少并发以避免NCBI限制）")
        
        # 读取文件中的所有序列
        sequences = self.file_handler.read_fasta_file(sequence_file)
        print(f"在文件中找到 {len(sequences)} 个序列")
        
        if not sequences:
            return []
        
        # 时间戳文件夹已在初始化时创建
        
        # 使用线程池处理序列
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交所有任务
            future_to_seq = {
                executor.submit(self.process_single_sequence, seq_info, sequence_file): seq_info
                for seq_info in sequences
            }
            
            # 收集结果
            results = []
            completed = 0
            total = len(sequences)
            
            for future in as_completed(future_to_seq):
                # 更新进度
                if self.on_progress_update:
                    self.on_progress_update(completed, total)
                
                seq_info = future_to_seq[future]
                try:
                    result = future.result()
                    results.append(result)
                    if result["status"] == "success":
                        print(f"✓ 完成处理: {seq_info['id']}")
                    else:
                        print(f"✗ 处理失败: {seq_info['id']} - {result['error']}")
                    
                    # 发送结果
                    if self.on_result_received:
                        self.on_result_received(result)
                except Exception as e:
                    print(f"✗ 处理序列 {seq_info['id']} 时发生异常: {e}")
                    error_result = {
                        "file": sequence_file,
                        "sequence_id": seq_info['id'],
                        "sequence_description": seq_info['description'],
                        "status": "error",
                        "error": str(e)
                    }
                    results.append(error_result)
                    if self.on_result_received:
                        self.on_result_received(error_result)
                
                # 更新完成计数
                completed += 1
                
                # 更新进度
                if self.on_progress_update:
                    self.on_progress_update(completed, total)
        
        # 调用所有任务完成回调
        if self.on_all_tasks_complete:
            self.on_all_tasks_complete(results)
            
        return results