"""
云资源管理器对话框
负责管理和清理 Elastic BLAST 云端资源
"""

import logging
import threading
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, 
    QTextEdit, QGroupBox, QMessageBox, QProgressBar, QComboBox
)

try:
    from elastic_blast.elb_config import ElasticBlastConfig
    from elastic_blast.constants import ElbCommand, ElbStatus
    from elastic_blast.elasticblast_factory import ElasticBlastFactory
    from elastic_blast.util import get_gcp_project
except ImportError:
    ElasticBlastConfig = None

from src.gui.widgets.help_viewer import HelpViewerDialog # 导入新的帮助查看器

logger = logging.getLogger(__name__)

class CloudActionThread(QThread):
    """后台执行云操作的线程"""
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, action_type, settings):
        super().__init__()
        self.action_type = action_type # 'status' or 'delete'
        self.settings = settings

    def run(self):
        try:
            if ElasticBlastConfig is None:
                raise ImportError("Elastic BLAST 模块未加载")

            self.log_signal.emit(f"正在初始化配置 (Provider: {self.settings.get('elb_cloud_provider')})...")
            
            # 构造配置
            # 注意：这里我们构造一个用于管理目的的 Config，不需要具体的 queries
            # 但 ElasticBlastConfig 验证较严，可能需要伪造一些参数
            
            provider = self.settings.get('elb_cloud_provider', 'AWS')
            results = self.settings.get('elb_results_bucket')
            region = self.settings.get('elb_region')
            
            kwargs = {
                'task': ElbCommand.STATUS if self.action_type == 'status' else ElbCommand.DELETE,
                'results': results,
                'queries': 'dummy.fa', # 占位符，status/delete 命令通常不检查这个，但在 Config init 中可能是必须的
                'program': 'blastn',
                'db': 'nt',
                'cluster_name': 'elb-manager', # 这里的名字可能不重要，因为我们是基于 results bucket 操作
                'dry_run': False
            }

            if provider == 'AWS':
                kwargs['aws_region'] = region
            else:
                project = self.settings.get('elb_gcp_project')
                if not project:
                    try:
                        project = get_gcp_project()
                    except:
                        pass
                kwargs['gcp_project'] = project
                kwargs['gcp_region'] = region
                kwargs['gcp_zone'] = f"{region}-b"

            # 尝试初始化配置
            # 注意：ElasticBlastConfig 可能会校验 queries 文件是否存在
            # 我们创建一个临时空文件以绕过校验
            import tempfile
            import os
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp:
                kwargs['queries'] = tmp.name
                tmp_path = tmp.name
            
            try:
                cfg = ElasticBlastConfig(**kwargs)
                
                # 创建实例
                elb = ElasticBlastFactory(cfg, create=False, cleanup_stack=[])
                
                if self.action_type == 'status':
                    self.log_signal.emit("正在检查集群状态...")
                    # check_status 返回 (status, counts, verbose)
                    # 但 elasticblast.py 中的 check_status 是抽象方法
                    # 具体实现 (aws.py/gcp.py) 会检查云端资源
                    
                    # 注意：check_status 通常检查的是与 'results' bucket 关联的特定集群
                    # 如果我们想列出所有集群，可能需要更底层的 API，但 Elastic BLAST 设计是基于 Results Bucket 的
                    
                    status, counts, verbose = elb.check_status(extended=True)
                    
                    msg = f"集群状态: {status.name}\n"
                    if counts:
                        msg += f"任务统计: {counts}\n"
                    if verbose:
                        msg += "详细信息:\n"
                        for k, v in verbose.items():
                            msg += f"  {k}: {v}\n"
                            
                    self.finished_signal.emit(True, msg)
                    
                elif self.action_type == 'delete':
                    self.log_signal.emit("正在执行删除操作 (Janitor)...")
                    elb.delete()
                    self.finished_signal.emit(True, "集群资源删除命令已发送。")
                    
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

        except Exception as e:
            self.finished_signal.emit(False, str(e))


class CloudManagerDialog(QDialog):
    """云资源管理对话框"""
    
    def __init__(self, parent=None, default_settings=None):
        super().__init__(parent)
        self.setWindowTitle("Elastic BLAST 云资源管理器")
        self.resize(600, 500)
        self.default_settings = default_settings or {}
        
        self._setup_ui()
        self._load_defaults()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # 1. 配置区域
        config_group = QGroupBox("目标配置")
        config_layout = QVBoxLayout(config_group)
        
        # Provider
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("云提供商:"))
        self.provider_combo = QComboBox()
        self.provider_combo.addItems(["AWS", "GCP"])
        row1.addWidget(self.provider_combo)
        config_layout.addLayout(row1)
        
        # Region
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("区域 (Region):"))
        self.region_input = QLineEdit()
        self.region_input.setPlaceholderText("例如: us-east-1")
        row2.addWidget(self.region_input)
        config_layout.addLayout(row2)
        
        # Bucket
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("结果存储桶 (Results Bucket):"))
        self.bucket_input = QLineEdit()
        self.bucket_input.setPlaceholderText("s3://... 或 gs://...")
        row3.addWidget(self.bucket_input)
        config_layout.addLayout(row3)
        
        layout.addWidget(config_group)
        
        # 2. 操作区域
        action_layout = QHBoxLayout()
        
        self.check_status_btn = QPushButton("检查状态")
        self.check_status_btn.clicked.connect(self._on_check_status)
        
        self.delete_btn = QPushButton("删除/清理集群")
        self.delete_btn.setStyleSheet("background-color: #f56c6c; color: white;")
        self.delete_btn.clicked.connect(self._on_delete)
        
        action_layout.addWidget(self.check_status_btn)
        action_layout.addWidget(self.delete_btn)
        
        # [新增] 帮助按钮
        self.help_btn = QPushButton("帮助")
        self.help_btn.clicked.connect(self._show_help)
        action_layout.addWidget(self.help_btn)
        
        layout.addLayout(action_layout)
        
        # 3. 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0) # Indeterminate
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)
        
        # 4. 日志输出
        layout.addWidget(QLabel("操作日志:"))
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        layout.addWidget(self.log_output)
        
        # 5. 关闭按钮
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def _load_defaults(self):
        """加载默认设置"""
        if not self.default_settings:
            return
            
        provider = self.default_settings.get('elb_cloud_provider', 'AWS')
        idx = self.provider_combo.findText(provider)
        if idx >= 0: self.provider_combo.setCurrentIndex(idx)
        
        self.region_input.setText(self.default_settings.get('elb_region', ''))
        self.bucket_input.setText(self.default_settings.get('elb_results_bucket', ''))

    def _get_current_settings(self):
        return {
            'elb_cloud_provider': self.provider_combo.currentText(),
            'elb_region': self.region_input.text(),
            'elb_results_bucket': self.bucket_input.text(),
            # GCP Project 暂时无法从 UI 获取，只能依赖环境或默认配置
            'elb_gcp_project': self.default_settings.get('elb_gcp_project')
        }

    def _on_check_status(self):
        self._start_action('status')

    def _on_delete(self):
        reply = QMessageBox.warning(
            self, 
            "确认删除", 
            "确定要删除与该存储桶关联的云端集群资源吗？\n此操作不可逆，将终止所有正在运行的任务并释放计算资源。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._start_action('delete')

    def _start_action(self, action_type):
        settings = self._get_current_settings()
        if not settings['elb_results_bucket'] or not settings['elb_region']:
            QMessageBox.warning(self, "参数缺失", "请填写区域和存储桶地址")
            return

        self.check_status_btn.setEnabled(False)
        self.delete_btn.setEnabled(False)
        self.help_btn.setEnabled(False)
        self.progress_bar.show()
        self.log_output.clear()
        
        self.thread = CloudActionThread(action_type, settings)
        self.thread.log_signal.connect(self._append_log)
        self.thread.finished_signal.connect(self._on_finished)
        self.thread.start()

    def _append_log(self, msg):
        self.log_output.append(msg)

    def _on_finished(self, success, msg):
        self.progress_bar.hide()
        self.check_status_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)
        self.help_btn.setEnabled(True)
        
        if success:
            self.log_output.append("\n[操作成功]")
            self.log_output.append(msg)
        else:
            self.log_output.append("\n[操作失败]")
            self.log_output.append(msg)
            QMessageBox.critical(self, "错误", f"操作失败: {msg}")

    def _show_help(self):
        """显示帮助文档"""
        HelpViewerDialog.show_topic(self, "elastic_blast")
