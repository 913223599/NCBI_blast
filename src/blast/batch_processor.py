"""
批量处理模块
负责批量处理序列文件的BLAST查询
"""

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

# 引入原有依赖
from src.utils.file_handler import FileHandler
from .executor import BlastExecutor, delay_before_request
from .parser import BlastResultParser
from .result_cache import BlastResultCache
from .result_converter import BlastResultConverter

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 常量定义
NUCLEOTIDE_CHARS = set('ATCGNU')
PROTEIN_CHARS = set('KERYWHDNQSTVRLEAICGPMF')
MIN_SEQUENCE_LENGTH = 5
NUCLEOTIDE_THRESHOLD = 0.7
PROTEIN_THRESHOLD = 0.7
MIN_PROTEIN_SEQ_LENGTH = 10

# 预编译正则以提升性能
RE_NUCLEOTIDE_PATTERN = re.compile(r'[ATCGU]{3,}')
RE_PROTEIN_PATTERN = re.compile(r'[KERYWHDNQSTVRLEAICGPMF]{3,}')

class BaseProcessor:
    """
    基础处理器类
    包含两个处理器共用的核心逻辑：参数配置、类型检测、文件管理、核心BLAST流程
    """
    def __init__(self, max_workers=3, advanced_settings=None):
        self.max_workers = max_workers
        self.advanced_settings = advanced_settings or {}
        self.file_handler = FileHandler()
        self.blast_executor = BlastExecutor()
        self.result_parser = BlastResultParser()
        self.result_converter = BlastResultConverter()
        # 统一缓存配置
        self.cache = BlastResultCache(
            cache_dir="cache",
            expiry_time=self.advanced_settings.get('cache_expiry', 86400)
        )

        # 回调函数
        self.on_task_start = None
        self.on_progress_update = None
        self.on_result_received = None
        self.on_all_tasks_complete = None

        self._cancel_flag = False
        self.timestamp_folder = self._create_timestamp_folder()

        # 默认 BLAST 参数
        self.default_blast_params = {
            'hitlist_size': 10,
            'evalue': 0.1,
            'alignments': 100,
            'descriptions': 100,
            # 其他默认值可在此扩展
        }

    def _create_timestamp_folder(self):
        """创建基于时间戳的结果保存文件夹"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder_path = Path("results") / timestamp
        folder_path.mkdir(parents=True, exist_ok=True)
        return folder_path

    def cancel_processing(self):
        """取消处理过程"""
        self._cancel_flag = True

    def _prepare_blast_params(self):
        """合并默认参数与高级设置"""
        params = self.default_blast_params.copy()

        # 允许的参数白名单
        allowed_keys = ['hitlist_size', 'word_size', 'evalue', 'matrix_name',
                        'filter', 'alignments', 'descriptions']

        # 仅当 settings 中有值且不为 None 时覆盖
        for key in allowed_keys:
            if key in self.advanced_settings and self.advanced_settings[key] is not None:
                params[key] = self.advanced_settings[key]

        return params

    def _detect_sequence_type(self, sequence):
        """检测序列类型（核苷酸或蛋白质）"""
        sequence_upper = sequence.upper()

        # 过滤掉非字母字符
        seq_chars = [c for c in sequence_upper if c.isalpha()]
        if not seq_chars:
            return 'nucleotide' # 默认回退

        total_len = len(sequence_upper)
        nucleotide_count = sum(1 for c in seq_chars if c in NUCLEOTIDE_CHARS)
        protein_count = sum(1 for c in seq_chars if c in PROTEIN_CHARS)

        # 逻辑分支优化
        if nucleotide_count > 0 and protein_count > 0:
            return self._detect_sequence_type_both_present(sequence_upper, nucleotide_count, protein_count, total_len)

        if nucleotide_count > 0 and (nucleotide_count / total_len > NUCLEOTIDE_THRESHOLD):
            return 'nucleotide'

        if protein_count > 0 and (protein_count / total_len > PROTEIN_THRESHOLD):
            return 'protein'

        if total_len > MIN_PROTEIN_SEQ_LENGTH and protein_count > 0:
            return 'protein'

        return 'nucleotide'

    def _detect_sequence_type_both_present(self, sequence_upper, n_count, p_count, total_len):
        """混合字符情况下的详细判断"""
        has_n_pattern = bool(RE_NUCLEOTIDE_PATTERN.search(sequence_upper))
        has_p_pattern = bool(RE_PROTEIN_PATTERN.search(sequence_upper))

        if has_n_pattern and not has_p_pattern:
            return 'nucleotide'
        elif has_p_pattern and not has_n_pattern:
            return 'protein'

        # 比例判断
        p_ratio = p_count / total_len if total_len > 0 else 0
        n_ratio = n_count / total_len if total_len > 0 else 0

        return 'protein' if p_ratio > n_ratio else 'nucleotide'

    def _execute_blast_workflow(self, sequence, seq_id, original_file_name, source_file_path):
        """
        核心工作流：执行单个序列的BLAST、文件保存、转换和缓存
        此方法被两个子类通用调用
        """
        thread_id = threading.current_thread().ident
        start_time = time.time()
        
        logger.info(f"开始处理序列: {seq_id}, 文件: {Path(source_file_path).name}")

        # 结果文件路径构建
        base_filename = f"{original_file_name}_blast_result" if original_file_name == seq_id else f"{original_file_name}_{seq_id}_blast_result"
        result_file = self.timestamp_folder / f"{base_filename}.xml"
        csv_file = self.timestamp_folder / f"{base_filename}.csv"
        desc_file = self.timestamp_folder / f"{base_filename}.desc"

        # 构造基础返回对象
        result_info = {
            "file": source_file_path,
            "status": "pending",
            "thread_id": thread_id,
            "result_file": result_file,
            "csv_file": csv_file,
            "desc_file": desc_file
        }

        # 如果是 MultiSequenceProcessor 调用，可能需要额外的字段
        if original_file_name != seq_id:
             result_info["sequence_id"] = seq_id

        try:
            # 1. 验证序列
            if not sequence or not sequence.strip():
                raise ValueError(f"无效的空序列: {seq_id}")

            # 2. 检查缓存
            use_cache = self.advanced_settings.get('use_cache', True)
            if use_cache:
                # 缓存键策略：如果是多序列文件，组合文件名和ID；如果是单文件，使用ID(即文件名)
                cache_key_id = seq_id if original_file_name == seq_id else f"{original_file_name}_{seq_id}"
                cached_result = self.cache.get_cached_result(sequence, cache_key_id)
                if cached_result:
                    logger.info(f"✓ 使用缓存结果: {cache_key_id}")
                    cached_result['from_cache'] = True
                    return cached_result
                else:
                    logger.info(f"○ 缓存未命中，开始实际查询: {cache_key_id}")

            # 3. 准备参数
            blast_params = self._prepare_blast_params()

            # 4. 确定程序和数据库
            sequence_type = self._detect_sequence_type(sequence)
            logger.debug(f"检测到序列类型: {sequence_type} (序列ID: {seq_id})")
            
            if sequence_type == 'protein':
                program = 'blastp'
                database = self.advanced_settings.get('protein_database', 'nr')
            else:
                program = 'blastn'
                database = self.advanced_settings.get('nucleotide_database', 'nt')

            logger.debug(f"使用程序: {program}, 数据库: {database} (序列ID: {seq_id})")

            # 5. 请求控制与执行
            if self._cancel_flag:
                raise InterruptedError("任务被用户取消")

            delay_before_request()

            result_handle = self.blast_executor.execute_with_retry(
                sequence,
                program=program,
                database=database,
                timeout_minutes=6, # 统一超时设置
                **blast_params
            )

            # 6. 保存原始XML
            self.file_handler.save_result_file(result_handle, str(result_file))
            result_handle.close() # 确保关闭句柄

            # 7. 格式转换
            self.result_converter.convert_xml_to_csv(str(result_file), str(csv_file), str(desc_file))

            # 8. 更新结果状态
            elapsed_time = time.time() - start_time
            result_info.update({
                "status": "success",
                "elapsed_time": elapsed_time,
                "timestamp_folder": str(self.timestamp_folder)
            })

            logger.info(f"✓ 序列处理完成: {seq_id}, 耗时: {elapsed_time:.2f}秒")

            # 9. 写入缓存
            if use_cache:
                # 缓存记录不需要包含运行时长，设为0或不存
                cache_entry = result_info.copy()
                cache_entry["elapsed_time"] = 0
                self.cache.save_result(sequence, cache_entry, cache_key_id)

            return result_info

        except Exception as e:
            elapsed_time = time.time() - start_time
            logger.error(f"处理 {seq_id} 时出错: {e}")
            # 记录详细堆栈
            logger.debug(e, exc_info=True)

            result_info.update({
                "status": "error",
                "error": str(e),
                "elapsed_time": elapsed_time
            })
            return result_info


class BatchProcessor(BaseProcessor):
    """
    针对单文件单序列的批量处理器
    """

    def process_single_sequence(self, sequence_file):
        """处理单个序列文件"""
        # 回调
        if self.on_task_start:
            self.on_task_start(sequence_file)

        file_path = Path(sequence_file)
        file_name = file_path.stem

        try:
            # 读取
            sequence = self.file_handler.read_sequence_file(str(sequence_file))
            # 执行核心逻辑
            # 对于单文件模式，seq_id 和 original_file_name 通常是一样的
            return self._execute_blast_workflow(sequence, file_name, file_name, str(file_path))

        except Exception as e:
            # 捕获读取阶段的错误
            logger.error(f"读取文件失败: {sequence_file} - {e}")
            return {
                "file": str(sequence_file),
                "status": "error",
                "error": str(e),
                "thread_id": threading.current_thread().ident,
                "elapsed_time": 0
            }

    def process_sequences(self, sequence_files):
        """批量处理入口"""
        if len(sequence_files) > 1:
            logger.info(f"开始批量处理 {len(sequence_files)} 个序列文件，线程数: {self.max_workers}")

        return self._run_thread_pool(sequence_files, self.process_single_sequence)

    def _run_thread_pool(self, items, process_func):
        """通用的线程池执行逻辑"""
        logger.info(f"开始处理 {len(items)} 个项目，使用 {self.max_workers} 个工作线程")
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_item = {executor.submit(process_func, item): item for item in items}
            results = []
            completed = 0
            total = len(items)

            for future in as_completed(future_to_item):
                if self._cancel_flag:
                    logger.info(f"处理被取消，已完成 {completed}/{total} 个项目")
                    break

                item = future_to_item[future]
                try:
                    result = future.result()
                    results.append(result)

                    # 日志与回调
                    if result["status"] == "success":
                        name = Path(result["file"]).name
                        logger.info(f"✓ 完成处理: {name}")
                    else:
                        name = Path(item).name if isinstance(item, (str, Path)) else "Item"
                        logger.error(f"✗ 处理失败: {name} - {result.get('error', 'Unknown')}")

                    if self.on_result_received:
                        self.on_result_received(result)

                except Exception as e:
                    logger.error(f"任务执行异常: {e}")

                completed += 1
                # 输出进度日志，每处理10%或至少每处理10个项目时输出一次
                if completed % max(1, total // 10) == 0 or completed == total or completed == 1:
                    logger.info(f"进度: {completed}/{total} ({completed/total*100:.1f}%)")
                    
                if self.on_progress_update:
                    self.on_progress_update(completed, total)
        
        logger.info(f"线程池处理完成，总共处理 {len(results)} 个项目，成功 {sum(1 for r in results if r['status'] == 'success')} 个")
        
        if self.on_all_tasks_complete:
            self.on_all_tasks_complete(results)

        return results

    def print_summary(self, results):
        """打印简单的文本总结"""
        successful = sum(1 for r in results if r["status"] == "success")
        failed = len(results) - successful

        print(f"\nBatch processing complete!")
        print(f"Total: {len(results)}, Success: {successful}, Failed: {failed}")

        if failed > 0:
            print("\nFailures:")
            for result in results:
                if result["status"] == "error":
                    print(f"  - {Path(result['file']).name}: {result['error']}")


class MultiSequenceBatchProcessor(BaseProcessor):
    """
    针对单文件多序列 (FASTA) 的批量处理器
    """

    def process_single_sequence(self, sequence_info, original_file_path):
        """适配器方法：将 dict 输入转为核心工作流调用"""
        seq_id = sequence_info['id'].replace('|', '_').replace(' ', '_')
        description = sequence_info.get('description', '')

        if self.on_task_start:
            self.on_task_start(f"{original_file_path} - {seq_id}")

        result = self._execute_blast_workflow(
            sequence=sequence_info['sequence'],
            seq_id=seq_id,
            original_file_name=Path(original_file_path).stem,
            source_file_path=str(original_file_path)
        )

        # 补充多序列特有的字段
        result['sequence_description'] = description
        return result

    def process_sequences_from_file(self, sequence_file):
        """处理文件中的所有序列"""
        logger.info(f"开始读取文件: {Path(sequence_file).name}")

        try:
            sequences = self.file_handler.read_fasta_file(sequence_file)
            logger.info(f"找到 {len(sequences)} 条序列")

            if not sequences:
                logger.info(f"文件 {Path(sequence_file).name} 中没有序列，跳过处理")
                return []

            # 使用 lambda 绑定 file path 参数，使其适配通用的线程池逻辑
            task_func = lambda seq_info: self.process_single_sequence(seq_info, sequence_file)

            logger.info(f"开始处理 {len(sequences)} 条序列，使用 {self.max_workers} 个工作线程")
            
            # 复用 BatchProcessor 中的线程池逻辑 (这里通过复制逻辑实现，或可提取mixin)
            # 为了保持干净，这里重写一个针对性的线程池调用，但逻辑是一样的
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_seq = {executor.submit(task_func, seq): seq for seq in sequences}
                results = []
                completed = 0
                total = len(sequences)

                for future in as_completed(future_to_seq):
                    if self._cancel_flag:
                        logger.info(f"处理被取消，已完成 {completed}/{total} 个序列")
                        break

                    seq_info = future_to_seq[future]
                    try:
                        result = future.result()
                        results.append(result)

                        if result["status"] == "success":
                            logger.info(f"✓ 完成处理: {seq_info['id']}")
                        else:
                            logger.error(f"✗ 处理失败: {seq_info['id']} - {result['error']}")

                        if self.on_result_received:
                            self.on_result_received(result)

                    except Exception as e:
                        logger.error(f"处理序列 {seq_info['id']} 时发生异常: {e}")
                        # 兜底异常处理
                        err_res = {
                            "file": sequence_file,
                            "sequence_id": seq_info['id'],
                            "status": "error",
                            "error": str(e)
                        }
                        results.append(err_res)
                        if self.on_result_received:
                            self.on_result_received(err_res)

                    completed += 1
                    # 输出进度日志，每处理10%或至少每处理10个序列时输出一次
                    if completed % max(1, total // 10) == 0 or completed == total or completed == 1:
                        logger.info(f"进度: {completed}/{total} ({completed/total*100:.1f}%)")
                    
                    if self.on_progress_update:
                        self.on_progress_update(completed, total)

            logger.info(f"文件 {Path(sequence_file).name} 处理完成，总共处理 {len(results)} 个结果，成功 {sum(1 for r in results if r['status'] == 'success')} 个")
            
            if self.on_all_tasks_complete:
                self.on_all_tasks_complete(results)

            return results

        except Exception as e:
            logger.error(f"处理文件级错误: {e}")
            return []
