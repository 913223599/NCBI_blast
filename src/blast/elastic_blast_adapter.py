"""
Elastic BLAST 适配器模块
用于将 Elastic BLAST 的云功能集成到现有项目中
"""

import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional
import tempfile
from dataclasses import dataclass
import configparser
from enum import Enum

from src.utils.config_manager import get_config_manager


class CloudProvider(Enum):
    """云提供商枚举"""
    AWS = "aws"
    GCP = "gcp"


@dataclass
class ElasticBlastParams:
    """Elastic BLAST 参数配置"""
    cloud_provider: CloudProvider  # 'aws' or 'gcp'
    aws_region: Optional[str] = None
    gcp_project: Optional[str] = None
    gcp_region: Optional[str] = None
    gcp_zone: Optional[str] = None
    program: Optional[str] = 'blastn'
    database: Optional[str] = 'nt'
    query_file: Optional[str] = None
    results_bucket: Optional[str] = None
    machine_type: Optional[str] = None
    num_nodes: Optional[int] = 1
    num_cpus: Optional[int] = 2
    cluster_name: Optional[str] = None
    blast_options: Optional[str] = None
    batch_len: Optional[int] = None


class ElasticBlastAdapter:
    """
    Elastic BLAST 适配器
    用于在现有项目中使用 Elastic BLAST 的云功能
    """
    
    def __init__(self):
        self.config_manager = get_config_manager()
        self.logger = logging.getLogger(__name__)
        
    def _create_elastic_blast_config(self, params: ElasticBlastParams):
        """创建 Elastic BLAST 配置对象"""
        # 动态导入，仅在需要时导入以避免依赖问题
        try:
            from elastic_blast.elb_config import ElasticBlastConfig
            from elastic_blast.constants import ElbCommand
        except ImportError:
            raise ImportError("Elastic BLAST 模块未安装。请先安装 elastic-blast 包。")
        
        # 使用临时配置文件创建配置对象
        cfg = configparser.ConfigParser()
        
        # 添加必要的配置节
        cfg.add_section('cloud-provider')
        cfg.add_section('cluster')
        cfg.add_section('blast')
        cfg.add_section('timeouts')
        
        # 设置云提供商配置
        if params.cloud_provider == CloudProvider.AWS:
            cfg.set('cloud-provider', 'aws-region', params.aws_region or 'us-east-1')
        elif params.cloud_provider == CloudProvider.GCP:
            cfg.set('cloud-provider', 'gcp-project', params.gcp_project or '')
            cfg.set('cloud-provider', 'gcp-region', params.gcp_region or 'us-central1')
            cfg.set('cloud-provider', 'gcp-zone', params.gcp_zone or 'us-central1-a')
        
        # 设置集群配置
        cfg.set('cluster', 'results', params.results_bucket or '')
        if params.cluster_name:
            cfg.set('cluster', 'cluster-name', params.cluster_name)
        if params.machine_type:
            cfg.set('cluster', 'machine-type', params.machine_type)
        cfg.set('cluster', 'num-nodes', str(params.num_nodes))
        cfg.set('cluster', 'num-cpus', str(params.num_cpus))
        
        # 设置 BLAST 配置
        cfg.set('blast', 'program', params.program or 'blastn')
        cfg.set('blast', 'db', params.database or 'nt')
        cfg.set('blast', 'query', params.query_file or '')
        if params.blast_options:
            cfg.set('blast', 'options', params.blast_options)
        if params.batch_len:
            cfg.set('blast', 'batch-len', str(params.batch_len))
        
        # 创建 ElasticBlastConfig 对象
        config = ElasticBlastConfig(cfg, task=ElbCommand.SUBMIT)
        return config
    
    def execute_elastic_blast_search(self, params: ElasticBlastParams) -> Dict[str, Any]:
        """
        执行 Elastic BLAST 搜索
        
        Args:
            params: ElasticBlastParams 对象，包含搜索参数
            
        Returns:
            包含搜索结果信息的字典
        """
        try:
            # 验证必需参数
            if not params.query_file:
                raise ValueError("必须提供查询文件路径")
            if not params.results_bucket:
                raise ValueError("必须提供结果存储桶")
            if not params.cloud_provider:
                raise ValueError("必须指定云提供商 (aws 或 gcp)")
            
            # 导入 Elastic BLAST 模块
            from elastic_blast.elb_config import ElasticBlastConfig
            from elastic_blast.commands.submit import submit
            from elastic_blast.elasticblast_factory import ElasticBlastFactory
            from elastic_blast.constants import ElbCommand
            
            # 创建配置
            config = self._create_elastic_blast_config(params)
            
            # 验证配置
            config.validate(ElbCommand.SUBMIT)
            
            # 准备清理栈
            clean_up_stack = []
            
            # 提交搜索任务
            result = submit(None, config, clean_up_stack)
            
            # 创建 ElasticBlast 对象并提交任务
            elastic_blast = ElasticBlastFactory(config, True, clean_up_stack)
            
            return {
                "status": "submitted",
                "task_id": config.cluster.name,
                "results_bucket": params.results_bucket,
                "query_file": params.query_file,
                "cloud_provider": params.cloud_provider.value,
                "message": f"Elastic BLAST 任务已提交: {config.cluster.name}"
            }
            
        except ImportError as e:
            self.logger.error(f"Elastic BLAST 模块未安装: {str(e)}")
            return {
                "status": "error",
                "error": str(e),
                "message": "Elastic BLAST 模块未安装。请先安装 elastic-blast 包。"
            }
        except Exception as e:
            self.logger.error(f"Elastic BLAST 执行失败: {str(e)}")
            return {
                "status": "error",
                "error": str(e),
                "message": f"Elastic BLAST 执行失败: {str(e)}"
            }
    
    def check_task_status(self, cluster_name: str, results_bucket: str, 
                         cloud_provider: str) -> Dict[str, Any]:
        """
        检查 Elastic BLAST 任务状态
        
        Args:
            cluster_name: 集群名称
            results_bucket: 结果存储桶
            cloud_provider: 云提供商 ('aws' or 'gcp')
            
        Returns:
            包含任务状态信息的字典
        """
        try:
            # 导入 Elastic BLAST 模块
            from elastic_blast.elb_config import ElasticBlastConfig
            from elastic_blast.elasticblast_factory import ElasticBlastFactory
            from elastic_blast.constants import ElbCommand, CSP
            from elastic_blast.constants import ElbStatus
            
            # 创建一个简化的配置用于状态检查
            cfg = configparser.ConfigParser()
            cfg.add_section('cloud-provider')
            cfg.add_section('cluster')
            cfg.add_section('blast')
            cfg.add_section('timeouts')
            
            if cloud_provider.lower() == 'aws':
                cfg.set('cloud-provider', 'aws-region', 'us-east-1')  # 默认值
            elif cloud_provider.lower() == 'gcp':
                cfg.set('cloud-provider', 'gcp-project', '')  # 默认值
                cfg.set('cloud-provider', 'gcp-region', 'us-central1')  # 默认值
                cfg.set('cloud-provider', 'gcp-zone', 'us-central1-a')  # 默认值
            
            cfg.set('cluster', 'results', results_bucket)
            cfg.set('cluster', 'cluster-name', cluster_name)
            
            config = ElasticBlastConfig(cfg, task=ElbCommand.STATUS)
            
            # 创建 ElasticBlast 对象并检查状态
            elastic_blast = ElasticBlastFactory(config, False, [])
            status, counts, verbose_result = elastic_blast.check_status(extended=True)
            
            return {
                "status": status.name if hasattr(status, 'name') else str(status),
                "counts": dict(counts),
                "verbose_result": verbose_result,
                "cluster_name": cluster_name
            }
            
        except ImportError as e:
            self.logger.error(f"Elastic BLAST 模块未安装: {str(e)}")
            return {
                "status": "error",
                "error": str(e),
                "message": "Elastic BLAST 模块未安装。请先安装 elastic-blast 包。"
            }
        except Exception as e:
            self.logger.error(f"检查 Elastic BLAST 任务状态失败: {str(e)}")
            return {
                "status": "error",
                "error": str(e),
                "message": f"检查任务状态失败: {str(e)}"
            }
    
    def delete_task(self, cluster_name: str, results_bucket: str, 
                   cloud_provider: str) -> Dict[str, Any]:
        """
        删除 Elastic BLAST 任务和相关资源
        
        Args:
            cluster_name: 集群名称
            results_bucket: 结果存储桶
            cloud_provider: 云提供商 ('aws' or 'gcp')
            
        Returns:
            包含删除结果的字典
        """
        try:
            # 导入 Elastic BLAST 模块
            from elastic_blast.elb_config import ElasticBlastConfig
            from elastic_blast.elasticblast_factory import ElasticBlastFactory
            from elastic_blast.constants import ElbCommand, CSP
            
            # 创建配置用于删除操作
            cfg = configparser.ConfigParser()
            cfg.add_section('cloud-provider')
            cfg.add_section('cluster')
            cfg.add_section('blast')
            cfg.add_section('timeouts')
            
            if cloud_provider.lower() == 'aws':
                cfg.set('cloud-provider', 'aws-region', 'us-east-1')  # 默认值
            elif cloud_provider.lower() == 'gcp':
                cfg.set('cloud-provider', 'gcp-project', '')  # 默认值
                cfg.set('cloud-provider', 'gcp-region', 'us-central1')  # 默认值
                cfg.set('cloud-provider', 'gcp-zone', 'us-central1-a')  # 默认值
            
            cfg.set('cluster', 'results', results_bucket)
            cfg.set('cluster', 'cluster-name', cluster_name)
            
            config = ElasticBlastConfig(cfg, task=ElbCommand.DELETE)
            
            # 创建 ElasticBlast 对象并删除任务
            elastic_blast = ElasticBlastFactory(config, False, [])
            elastic_blast.delete()
            
            return {
                "status": "deleted",
                "cluster_name": cluster_name,
                "message": f"已成功删除集群: {cluster_name}"
            }
            
        except ImportError as e:
            self.logger.error(f"Elastic BLAST 模块未安装: {str(e)}")
            return {
                "status": "error",
                "error": str(e),
                "message": "Elastic BLAST 模块未安装。请先安装 elastic-blast 包。"
            }
        except Exception as e:
            self.logger.error(f"删除 Elastic BLAST 任务失败: {str(e)}")
            return {
                "status": "error",
                "error": str(e),
                "message": f"删除任务失败: {str(e)}"
            }


# 便利函数
def get_elastic_blast_adapter() -> ElasticBlastAdapter:
    """
    获取 Elastic BLAST 适配器实例
    
    Returns:
        ElasticBlastAdapter: 适配器实例
    """
    return ElasticBlastAdapter()