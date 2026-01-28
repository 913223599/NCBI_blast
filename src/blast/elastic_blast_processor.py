"""
Elastic BLAST 处理器模块
负责提交和管理 Elastic BLAST 云端任务
"""

import os
import sys
import logging
import time
import threading
import shutil
import subprocess
from pathlib import Path
from datetime import datetime

# 添加 elastic-blast 源码路径
project_root = Path(__file__).resolve().parent.parent.parent
elastic_blast_src = project_root / "tools" / "elastic-blast-master" / "src"
if str(elastic_blast_src) not in sys.path:
    sys.path.insert(0, str(elastic_blast_src))

try:
    from elastic_blast.elb_config import ElasticBlastConfig
    from elastic_blast.constants import ElbCommand, ElbStatus, CSP
    from elastic_blast.elasticblast_factory import ElasticBlastFactory
    from elastic_blast.util import get_gcp_project
except ImportError as e:
    logging.error(f"Failed to import elastic-blast modules: {e}")
    # Define dummy classes to prevent crash on import if elastic-blast is missing
    ElasticBlastConfig = None
    ElbCommand = None
    ElbStatus = None
    CSP = None
    ElasticBlastFactory = None

from src.blast.batch_processor import BaseProcessor
from src.blast.result_converter import BlastResultConverter

logger = logging.getLogger(__name__)

class ElasticBlastProcessor(BaseProcessor):
    """
    Elastic BLAST 处理器
    将任务提交到云端 (AWS/GCP) 执行
    """
    def __init__(self, max_workers=1, advanced_settings=None, task_name=None):
        super().__init__(max_workers, advanced_settings, task_name)
        self.elb_instance = None
        self.result_converter = BlastResultConverter()
        
        if ElasticBlastConfig is None:
            raise ImportError("Elastic BLAST modules not found. Please ensure elastic-blast is installed in tools/.")

    def process_sequences(self, sequence_files):
        """
        提交 Elastic BLAST 任务
        """
        if not sequence_files:
            return []

        # 1. 合并查询文件
        # Elastic BLAST 最好处理单个大文件
        merged_query_file = self.task_folder / "queries.fasta"
        try:
            with open(merged_query_file, 'w', encoding='utf-8') as outfile:
                for fname in sequence_files:
                    with open(fname, 'r', encoding='utf-8') as infile:
                        outfile.write(infile.read())
                        outfile.write('\n') # 确保分隔
        except Exception as e:
            logger.error(f"Failed to merge query files: {e}")
            return [{"status": "error", "error": f"Failed to merge files: {e}"}]

        # 2. 准备配置
        try:
            cfg = self._create_elb_config(str(merged_query_file))
        except Exception as e:
            logger.error(f"Failed to create Elastic BLAST config: {e}")
            return [{"status": "error", "error": f"Configuration error: {e}"}]

        # 更新任务历史状态
        self.history_manager.add_or_update_task(
            task_name=self.task_folder.name,
            total=1, # 视为一个大任务
            status="running"
        )

        # 3. 提交任务
        try:
            # 创建 ElasticBlast 实例
            # cleanup_stack 用于资源清理，这里传入空列表
            self.elb_instance = ElasticBlastFactory(cfg, create=True, cleanup_stack=[])
            
            if self.on_task_start:
                self.on_task_start("正在提交 Elastic BLAST 任务到云端...")
            
            # 提交 (可能会上传文件，耗时较长)
            query_length = merged_query_file.stat().st_size # 粗略估计
            
            self.elb_instance.submit([str(merged_query_file)], query_length, False)
            
            logger.info("Elastic BLAST job submitted successfully.")
            if self.on_task_start:
                self.on_task_start("任务已提交，正在云端运行...")
            
            # 4. 监控状态
            status = ElbStatus.UNKNOWN
            while not self._cancel_flag:
                # check_status 返回 (status, counts, verbose)
                status, counts, verbose = self.elb_instance.check_status()
                logger.info(f"Job Status: {status.name}")
                
                status_msg = f"云端运行中: {status.name}"
                if counts:
                    # 尝试显示进度: Pending, Running, Succeeded, Failed
                    succeeded = counts.get('Succeeded', 0)
                    running = counts.get('Running', 0)
                    total_jobs = sum(counts.values())
                    if total_jobs > 0:
                        status_msg += f" (完成: {succeeded}/{total_jobs}, 运行中: {running})"
                        # 更新进度条
                        if self.on_progress_update:
                            self.on_progress_update(succeeded, total_jobs)

                if self.on_task_start:
                    self.on_task_start(status_msg)

                if status in [ElbStatus.SUCCESS, ElbStatus.FAILURE]:
                    break
                
                # 等待一段时间再检查
                for _ in range(30):
                    if self._cancel_flag: break
                    time.sleep(1)

            if self._cancel_flag:
                logger.info("Cancelling Elastic BLAST job...")
                if self.on_task_start:
                    self.on_task_start("正在取消云端任务...")
                try:
                    self.elb_instance.delete()
                except Exception as e:
                    logger.error(f"Failed to delete cluster: {e}")
                return [{"status": "cancelled", "error": "Cancelled by user"}]

            if status == ElbStatus.FAILURE:
                # 尝试获取失败原因
                error_msg = self.elb_instance.cached_failure_message or "Unknown error"
                return [{"status": "error", "error": f"Elastic BLAST job failed: {error_msg}"}]

            # 5. 下载结果
            if status == ElbStatus.SUCCESS:
                if self.on_task_start:
                    self.on_task_start("任务完成，正在下载结果...")
                
                self._download_results(cfg.cluster.results, self.task_folder)
                
                # 6. 整理结果
                # 扫描下载的文件，查找 XML 结果
                downloaded_files = list(self.task_folder.glob("*"))
                
                # 假设结果是 XML 格式 (因为我们设置了 -outfmt 5)
                # Elastic BLAST 可能产生多个 batch_*.xml 文件
                xml_files = []
                for f in downloaded_files:
                    if f.name == "queries.fasta": continue
                    if f.suffix == '.xml' or f.name.startswith('batch_'):
                         # 简单的启发式检查是否为 XML
                         try:
                             with open(f, 'rb') as tf:
                                 header = tf.read(100)
                                 if b'<?xml' in header or b'<!DOCTYPE BlastOutput' in header:
                                     xml_files.append(f)
                         except:
                             pass

                if not xml_files:
                    logger.warning("No XML result files found.")
                    # 尝试查找任何非 fasta 文件
                    xml_files = [f for f in downloaded_files if f.name != "queries.fasta" and f.is_file()]

                # 转换结果
                result_info_list = []
                
                if not xml_files:
                     return [{"status": "error", "error": "No result files downloaded"}]

                # 如果有多个结果文件，我们可能需要返回多个 result_info，或者合并
                # 这里我们简单地为每个结果文件生成一个条目，但这可能与原始输入文件不对应
                # 因为我们合并了输入。
                # 这是一个限制：Elastic BLAST 批处理模式下，结果与原始文件的对应关系需要解析 XML 中的 query def。
                
                # 暂时只处理第一个结果文件作为主要结果，或者将所有结果文件列出
                main_xml = xml_files[0]
                csv_file = main_xml.with_suffix('.csv')
                desc_file = main_xml.with_suffix('.desc')
                
                try:
                    self.result_converter.convert_xml_to_csv(str(main_xml), str(csv_file), str(desc_file))
                except Exception as e:
                    logger.warning(f"Failed to convert {main_xml}: {e}")

                result_info = {
                    "file": str(merged_query_file),
                    "status": "success",
                    "result_file": str(main_xml),
                    "csv_file": str(csv_file),
                    "desc_file": str(desc_file),
                    "elapsed_time": 0, 
                    "sequence_id": "Cloud_Batch_Result"
                }
                
                # 保存任务历史
                self._save_task_history([result_info])
                
                if self.on_all_tasks_complete:
                    self.on_all_tasks_complete([result_info])

                return [result_info]

        except Exception as e:
            logger.error(f"Elastic BLAST execution failed: {e}", exc_info=True)
            return [{"status": "error", "error": str(e)}]
            
        return []

    def _create_elb_config(self, query_file):
        settings = self.advanced_settings
        
        provider_str = settings.get('elb_cloud_provider', 'AWS')
        results_bucket = settings.get('elb_results_bucket')
        region = settings.get('elb_region')
        
        if not results_bucket:
            raise ValueError("Results bucket is required")
        if not region:
            raise ValueError("Region is required")

        # 构造参数
        kwargs = {
            'task': ElbCommand.SUBMIT,
            'results': results_bucket,
            'queries': query_file,
            'program': settings.get('program', 'blastn'),
            'db': settings.get('nucleotide_database', 'nt') if settings.get('program', 'blastn') in ['blastn', 'tblastx'] else settings.get('protein_database', 'nr'),
            'cluster_name': f"elb-{self.task_name.lower().replace('_', '-')[:20]}",
            'dry_run': False,
            'options': '-outfmt 5' # 强制使用 XML 输出以便后续处理
        }
        
        if provider_str == 'AWS':
            kwargs['aws_region'] = region
        else:
            # GCP
            project = settings.get('elb_gcp_project')
            if not project:
                try:
                    project = get_gcp_project()
                except:
                    pass
            
            if not project:
                 raise ValueError("GCP Project is required. Please configure gcloud or add it to settings.")

            kwargs['gcp_project'] = project
            kwargs['gcp_region'] = region
            kwargs['gcp_zone'] = f"{region}-b" # 默认 Zone
            
        # 机器类型
        machine_type = settings.get('elb_machine_type')
        if machine_type:
            kwargs['machine_type'] = machine_type
            
        cfg = ElasticBlastConfig(**kwargs)
        
        # 设置其他集群参数
        if settings.get('elb_num_nodes'):
            cfg.cluster.num_nodes = int(settings.get('elb_num_nodes'))
        
        if settings.get('elb_use_spot') is not None:
            cfg.cluster.use_preemptible = settings.get('elb_use_spot')
            
        return cfg

    def _download_results(self, bucket_uri, local_dir):
        """下载结果"""
        logger.info(f"Downloading results from {bucket_uri} to {local_dir}")
        
        # 确保 bucket_uri 不以 / 结尾
        bucket_uri = str(bucket_uri).rstrip('/')
        
        if bucket_uri.startswith("s3://"):
            cmd = ["aws", "s3", "cp", "--recursive", bucket_uri, str(local_dir)]
        elif bucket_uri.startswith("gs://"):
            cmd = ["gsutil", "-m", "cp", "-r", f"{bucket_uri}/*", str(local_dir)]
        else:
            raise ValueError(f"Unknown bucket protocol: {bucket_uri}")
            
        # 使用 subprocess 调用 CLI 工具
        # 注意：这需要系统路径中有 aws 或 gsutil
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Download failed: {e.stderr.decode()}")
            raise RuntimeError(f"Failed to download results: {e.stderr.decode()}")
        except FileNotFoundError:
             raise RuntimeError(f"CLI tool not found for command: {cmd[0]}. Please install AWS CLI or gsutil.")

    def process_multiple_files(self, sequence_files):
        """适配 MultiSequenceProcessingThread"""
        return self.process_sequences(sequence_files)
