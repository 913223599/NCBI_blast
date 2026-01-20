"""
批量处理模块
负责批量处理序列文件的BLAST查询
"""

import logging
import re
import threading
import time
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

# 引入原有依赖
from src.utils.file_handler import FileHandler
from src.utils.history_manager import HistoryManager  # 引入历史记录管理器
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
    def __init__(self, max_workers=3, advanced_settings=None, task_name=None):
        self.max_workers = max_workers
        self.advanced_settings = advanced_settings or {}
        self.task_name = task_name or f"Task_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        self.file_handler = FileHandler()
        self.blast_executor = BlastExecutor()
        self.result_parser = BlastResultParser()
        self.result_converter = BlastResultConverter()
        self.history_manager = HistoryManager() # 初始化历史记录管理器
        
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
        self.task_folder = self._create_task_folder()
        
        # [新增] 初始化任务记录，确保任务一开始就被记录
        self._init_task_record()

        # 默认 BLAST 参数
        self.default_blast_params = {
            'hitlist_size': 10,
            'evalue': 0.1,
            'alignments': 100,
            'descriptions': 100,
            # 其他默认值可在此扩展
        }

    def _create_task_folder(self):
        """创建基于任务名的结果保存文件夹"""
        # 获取项目根目录 (src/blast/batch_processor.py -> src/blast -> src -> root)
        project_root = Path(__file__).resolve().parent.parent.parent
        
        # 清理任务名中的非法字符
        safe_task_name = "".join([c for c in self.task_name if c.isalnum() or c in (' ', '_', '-')]).strip()
        if not safe_task_name:
            safe_task_name = f"Task_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
        folder_path = project_root / "results" / safe_task_name
        
        # 如果文件夹已存在，添加后缀避免覆盖
        counter = 1
        original_path = folder_path
        while folder_path.exists():
            folder_path = original_path.parent / f"{original_path.name}_{counter}"
            counter += 1
            
        folder_path.mkdir(parents=True, exist_ok=True)
        return folder_path
        
    def _init_task_record(self):
        """初始化任务记录到数据库"""
        try:
            self.history_manager.add_task(
                task_name=self.task_folder.name,
                parameters=self.advanced_settings, # 此时可能还没合并默认参数，但足够了
                result_dir=str(self.task_folder),
                file_count=0, # 初始为0，后续更新
                status="running" # 初始状态为运行中
            )
        except Exception as e:
            logger.error(f"初始化任务记录失败: {e}")

    def cancel_processing(self):
        """取消处理过程"""
        self._cancel_flag = True
        # 尝试取消正在进行的线程池任务
        # 注意：Python 的 ThreadPoolExecutor 无法强制终止正在运行的线程
        # 但我们可以设置标志位，让任务在下一个检查点退出

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
        # 0. 早期取消检查
        if self._cancel_flag:
            logger.info(f"任务已取消，跳过序列: {seq_id}")
            return {
                "file": source_file_path,
                "status": "cancelled",
                "error": "Task cancelled by user",
                "thread_id": threading.current_thread().ident,
                "sequence_id": seq_id # 确保返回 sequence_id
            }

        thread_id = threading.current_thread().ident
        start_time = time.time()
        
        logger.info(f"开始处理序列: {seq_id}, 文件: {Path(source_file_path).name}")

        # 结果文件路径构建
        # [修改] 统一文件名格式，确保包含 seq_id，方便后续解析
        # 格式：{original_file_name}_{seq_id}_blast_result
        # 如果是单序列文件，seq_id 通常等于 original_file_name，此时避免重复
        if original_file_name == seq_id:
            base_filename = f"{original_file_name}_blast_result"
        else:
            base_filename = f"{original_file_name}_{seq_id}_blast_result"
            
        result_file = self.task_folder / f"{base_filename}.xml"
        csv_file = self.task_folder / f"{base_filename}.csv"
        desc_file = self.task_folder / f"{base_filename}.desc"

        # 构造基础返回对象
        result_info = {
            "file": source_file_path,
            "status": "pending",
            "thread_id": thread_id,
            "result_file": result_file,
            "csv_file": csv_file,
            "desc_file": desc_file,
            "sequence_id": seq_id # 始终包含 sequence_id
        }

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
                    # 确保缓存结果中包含 sequence_id
                    if 'sequence_id' not in cached_result:
                        cached_result['sequence_id'] = seq_id
                    return cached_result
                else:
                    logger.info(f"○ 缓存未命中，开始实际查询: {cache_key_id}")

            # 3. 准备参数
            blast_params = self._prepare_blast_params()

            # 4. 确定程序和数据库
            # [新增] 优先使用用户指定的程序
            user_program = self.advanced_settings.get('program')
            if user_program and user_program != 'auto':
                program = user_program
                # 根据程序类型自动选择默认数据库（如果用户未指定）
                if program in ['blastn', 'tblastx']:
                    database = self.advanced_settings.get('nucleotide_database', 'nt')
                else:
                    database = self.advanced_settings.get('protein_database', 'nr')
            else:
                # 自动检测
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

            # 从配置获取超时时间，默认4分钟
            timeout_minutes = self.advanced_settings.get('request_timeout', 6)

            # 再次检查取消标志，在发起网络请求前
            if self._cancel_flag:
                raise InterruptedError("任务被用户取消")

            result_handle = self.blast_executor.execute_with_retry(
                sequence,
                program=program,
                database=database,
                timeout_minutes=timeout_minutes,
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
                "timestamp_folder": str(self.task_folder)
            })

            logger.info(f"✓ 序列处理完成: {seq_id}, 耗时: {elapsed_time:.2f}秒")

            # 9. 写入缓存
            if use_cache:
                # 缓存记录不需要包含运行时长，设为0或不存
                cache_entry = result_info.copy()
                cache_entry["elapsed_time"] = 0
                self.cache.save_result(sequence, cache_entry, cache_key_id)
            
            # 10. 保存历史记录 (旧接口，保留兼容性)
            try:
                self.history_manager.add_record(
                    query_file=source_file_path,
                    database=database,
                    program=program,
                    parameters=blast_params,
                    result_file=str(result_file),
                    status="success"
                )
            except Exception as e:
                logger.error(f"保存历史记录失败: {e}")

            return result_info

        except InterruptedError as e:
            logger.info(f"任务取消: {seq_id}")
            result_info.update({
                "status": "cancelled",
                "error": str(e),
                "elapsed_time": time.time() - start_time
            })
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
            
    def _save_task_history(self, results):
        """保存任务级历史记录"""
        try:
            # 统计成功数量
            success_count = sum(1 for r in results if r.get("status") == "success")
            failed_count = sum(1 for r in results if r.get("status") == "error")
            
            # [修改] 状态判断逻辑，包含 cancelled
            if success_count == len(results):
                status = "completed"
            elif success_count > 0:
                status = "partial"
            elif any(r.get("status") == "cancelled" for r in results):
                status = "cancelled"
            else:
                status = "failed"
            
            # 更新任务记录（状态和文件数）
            self.history_manager.add_or_update_task(
                task_name=self.task_folder.name, # 使用实际创建的文件夹名作为任务名
                parameters=self._prepare_blast_params(),
                result_dir=str(self.task_folder),
                total=len(results),
                completed=success_count,
                failed=failed_count,
                status=status
            )
            
            # [新增] 保存详细的任务结果映射信息到 json 文件
            # 这对于恢复历史记录时的文件名和序列ID至关重要
            task_info = {
                "task_name": self.task_name,
                "timestamp": datetime.now().isoformat(),
                "results": []
            }
            
            for res in results:
                # 只保存必要信息，且将 Path 对象转为字符串
                info = {
                    "file": str(res.get("file", "")), # 原始文件路径
                    "sequence_id": res.get("sequence_id", ""),
                    "result_file": str(res.get("result_file", "")),
                    "csv_file": str(res.get("csv_file", "")),
                    "desc_file": str(res.get("desc_file", "")),
                    "status": res.get("status", "unknown"),
                    "elapsed_time": res.get("elapsed_time", 0)
                }
                task_info["results"].append(info)
                
            info_file = self.task_folder / "task_info.json"
            with open(info_file, 'w', encoding='utf-8') as f:
                json.dump(task_info, f, indent=2, ensure_ascii=False)

        except Exception as e:
            logger.error(f"保存任务历史失败: {e}")

    def _run_thread_pool(self, items, process_func, item_name_func=None):
        """通用的线程池执行逻辑"""
        logger.info(f"开始处理 {len(items)} 个项目，使用 {self.max_workers} 个工作线程")
        
        if item_name_func is None:
            item_name_func = lambda x: Path(x).name if isinstance(x, (str, Path)) else str(x)

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_item = {executor.submit(process_func, item): item for item in items}
            results = []
            completed = 0
            total = len(items)

            for future in as_completed(future_to_item):
                if self._cancel_flag:
                    logger.info(f"处理被取消，已完成 {completed}/{total} 个项目")
                    # 取消所有未开始的任务
                    for f in future_to_item:
                        f.cancel()
                    # 不 break，继续收集已完成或取消的结果
                    # break

                item = future_to_item[future]
                item_name = item_name_func(item)
                
                try:
                    result = future.result()
                    results.append(result)

                    # 日志与回调
                    if result["status"] == "success":
                        # 尝试获取更友好的名称
                        log_name = result.get("sequence_id", item_name) if "sequence_id" in result else item_name
                        logger.info(f"✓ 完成处理: {log_name}")
                    elif result["status"] == "cancelled":
                        logger.info(f"⚠ 任务取消: {item_name}")
                    else:
                        logger.error(f"✗ 处理失败: {item_name} - {result.get('error', 'Unknown')}")

                    if self.on_result_received:
                        self.on_result_received(result)
                        
                    # [新增] 实时更新任务进度到数据库
                    # 为了避免频繁写入，可以每完成一定数量更新一次
                    if len(results) % 5 == 0 or len(results) == total:
                        success_count = sum(1 for r in results if r.get("status") == "success")
                        failed_count = sum(1 for r in results if r.get("status") == "error")
                        self.history_manager.add_or_update_task(
                            task_name=self.task_folder.name,
                            completed=success_count,
                            failed=failed_count
                        )

                except Exception as e:
                    logger.error(f"任务执行异常: {e}")
                    # 兜底异常处理
                    err_res = {
                        "status": "error",
                        "error": str(e),
                        "file": str(item) if isinstance(item, (str, Path)) else "unknown"
                    }
                    if isinstance(item, dict) and 'id' in item:
                         err_res['sequence_id'] = item['id']
                    
                    results.append(err_res)
                    if self.on_result_received:
                        self.on_result_received(err_res)

                completed += 1
                # 输出进度日志，每处理10%或至少每处理10个项目时输出一次
                if completed % max(1, total // 10) == 0 or completed == total or completed == 1:
                    logger.info(f"进度: {completed}/{total} ({completed/total*100:.1f}%)")
                    
                if self.on_progress_update:
                    self.on_progress_update(completed, total)
        
        # [新增] 确保所有未完成的任务都被标记为取消或失败
        if self._cancel_flag:
            for future in future_to_item:
                if not future.done():
                    future.cancel()
                    item = future_to_item[future]
                    # 构造取消结果
                    cancel_res = {
                        "status": "cancelled",
                        "error": "Task cancelled by user",
                        "file": str(item) if isinstance(item, (str, Path)) else "unknown"
                    }
                    if isinstance(item, dict) and 'id' in item:
                         cancel_res['sequence_id'] = item['id']
                    
                    # 避免重复添加
                    if not any(r.get('sequence_id') == cancel_res.get('sequence_id') and r.get('file') == cancel_res.get('file') for r in results):
                        results.append(cancel_res)
                        if self.on_result_received:
                            self.on_result_received(cancel_res)

        logger.info(f"线程池处理完成，总共处理 {len(results)} 个项目，成功 {sum(1 for r in results if r.get('status') == 'success')} 个")
        
        if self.on_all_tasks_complete:
            self.on_all_tasks_complete(results)

        return results


class BatchProcessor(BaseProcessor):
    """
    针对单文件单序列的批量处理器
    """

    def process_single_sequence(self, sequence_file):
        """处理单个序列文件"""
        # 检查取消标志
        if self._cancel_flag:
            return {
                "file": str(sequence_file),
                "status": "cancelled",
                "error": "Task cancelled by user",
                "thread_id": threading.current_thread().ident,
                "sequence_id": Path(sequence_file).stem # 确保返回 sequence_id
            }

        # 回调
        if self.on_task_start:
            self.on_task_start(sequence_file)

        file_path = Path(sequence_file)
        file_name = file_path.stem

        try:
            # [修改] 尝试解析 FASTA 获取真实 ID，解决结果树重复节点问题
            seq_id = file_name
            sequence = ""
            
            # 尝试读取第一个序列
            found = False
            # 使用 read_fasta_file_iter，它已经包含了对非FASTA的兼容尝试
            for seq_info in self.file_handler.read_fasta_file_iter(str(sequence_file)):
                sequence = seq_info['sequence']
                if seq_info['id']:
                    seq_id = seq_info['id'].replace('|', '_').replace(' ', '_')
                found = True
                break
            
            if not found:
                 # 最后的兜底
                 sequence = self.file_handler.read_sequence_file(str(sequence_file))
                 seq_id = file_name

            # 执行核心逻辑
            # 对于单文件模式，seq_id 和 original_file_name 通常是一样的
            return self._execute_blast_workflow(sequence, seq_id, file_name, str(file_path))

        except Exception as e:
            # 捕获读取阶段的错误
            logger.error(f"读取文件失败: {sequence_file} - {e}")
            return {
                "file": str(sequence_file),
                "status": "error",
                "error": str(e),
                "thread_id": threading.current_thread().ident,
                "elapsed_time": 0,
                "sequence_id": file_name # 确保返回 sequence_id
            }

    def process_sequences(self, sequence_files):
        """批量处理入口"""
        if len(sequence_files) > 1:
            logger.info(f"开始批量处理 {len(sequence_files)} 个序列文件，线程数: {self.max_workers}")
            
        # [新增] 更新任务总数
        self.history_manager.add_or_update_task(
            task_name=self.task_folder.name,
            total=len(sequence_files),
            status="running"
        )

        results = self._run_thread_pool(sequence_files, self.process_single_sequence)
        
        # 保存任务历史
        self._save_task_history(results)
        
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
        # 检查取消标志
        if self._cancel_flag:
            return {
                "file": str(original_file_path),
                "sequence_id": sequence_info['id'],
                "status": "cancelled",
                "error": "Task cancelled by user"
            }

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
            # [优化] 使用迭代器读取，避免一次性加载
            sequences_iter = self.file_handler.read_fasta_file_iter(sequence_file)
            
            # 为了获取总数，我们可能需要先扫描一遍，或者在处理过程中动态更新
            # 但为了进度条，我们通常需要总数。
            # 权衡：对于超大文件，扫描一遍也耗时。
            # 方案：先快速扫描一遍获取数量（只读头），或者直接开始处理，进度条显示已处理数量而不是百分比
            # 这里为了保持现有逻辑兼容性，我们还是先转为列表，但 FileHandler 已经优化了读取方式
            # 如果文件真的巨大，这里 list() 仍然会消耗内存。
            # 真正的流式处理需要改造 ThreadPoolExecutor 的用法。
            
            # 暂时保持 list()，因为 FileHandler.read_fasta_file_iter 已经优化了底层读取
            # 如果内存仍然是瓶颈，需要进一步改造 MultiSequenceBatchProcessor
            sequences = list(sequences_iter)

            logger.info(f"找到 {len(sequences)} 条序列")

            if not sequences:
                logger.info(f"文件 {Path(sequence_file).name} 中没有序列，跳过处理")
                return []
                
            # [新增] 更新任务总数
            self.history_manager.add_or_update_task(
                task_name=self.task_folder.name,
                total=len(sequences),
                status="running"
            )

            # 使用 lambda 绑定 file path 参数，使其适配通用的线程池逻辑
            task_func = lambda seq_info: self.process_single_sequence(seq_info, sequence_file)
            
            # 自定义名称函数，用于日志
            name_func = lambda seq_info: seq_info['id']

            logger.info(f"开始处理 {len(sequences)} 条序列，使用 {self.max_workers} 个工作线程")
            
            # 复用 BaseProcessor 中的线程池逻辑
            results = self._run_thread_pool(sequences, task_func, item_name_func=name_func)

            logger.info(f"文件 {Path(sequence_file).name} 处理完成，总共处理 {len(results)} 个结果，成功 {sum(1 for r in results if r.get('status') == 'success')} 个")
            
            # 保存任务历史
            self._save_task_history(results)
            
            if self.on_all_tasks_complete:
                self.on_all_tasks_complete(results)

            return results

        except Exception as e:
            logger.error(f"处理文件级错误: {e}")
            return []

    def process_multiple_files(self, sequence_files):
        """同时处理多个文件中的所有序列"""
        all_tasks = []
        
        # 1. 收集所有任务
        for file_path in sequence_files:
            try:
                # 检查取消
                if self._cancel_flag: break
                
                logger.info(f"正在读取文件: {Path(file_path).name}")
                count = 0
                for seq_info in self.file_handler.read_fasta_file_iter(str(file_path)):
                    # 注入源文件路径
                    seq_info['source_file'] = str(file_path)
                    all_tasks.append(seq_info)
                    count += 1
                
                if count == 0:
                     logger.info(f"文件 {Path(file_path).name} 中没有序列")
                     
            except Exception as e:
                logger.error(f"读取文件 {file_path} 失败: {e}")
                # 可以在这里生成一个错误结果，或者忽略
        
        if not all_tasks:
            return []

        logger.info(f"总共收集到 {len(all_tasks)} 个序列任务，开始并行处理")
        
        # 更新任务总数
        self.history_manager.add_or_update_task(
            task_name=self.task_folder.name,
            total=len(all_tasks),
            status="running"
        )

        # 2. 执行线程池
        task_func = lambda seq_info: self.process_single_sequence(seq_info, seq_info['source_file'])
        name_func = lambda seq_info: f"{Path(seq_info['source_file']).name} - {seq_info['id']}"
        
        results = self._run_thread_pool(all_tasks, task_func, item_name_func=name_func)
        
        # 3. 保存历史
        self._save_task_history(results)
        
        if self.on_all_tasks_complete:
            self.on_all_tasks_complete(results)
            
        return results
