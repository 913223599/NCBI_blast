
import subprocess
import shutil
import os
import logging
from typing import Dict, Any, Optional

class GPUConfigManager:
    """
    GPU 加速策略管理器
    职责: 探测 CUDA 环境、分配显卡资源、生成加速环境变量
    """
    def __init__(self):
        self.logger = logging.getLogger("Assembly.GPU")
        self._has_cuda: Optional[bool] = None
        self._gpu_info: Dict[str, Any] = {}

    def is_cuda_available(self) -> bool:
        """检查系统中是否存在 NVIDIA GPU 及驱动"""
        if self._has_cuda is not None:
            return self._has_cuda
            
        try:
            # 尝试调用 nvidia-smi 
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
                capture_output=True, encoding='utf-8', errors='ignore', check=True
            )
            info = result.stdout.strip().split(",")
            if info:
                self._gpu_info = {
                    "name": info[0],
                    "memory": info[1],
                    "driver": info[2]
                }
                self._has_cuda = True
                self.logger.info(f"✨ 发现可用 GPU 加速设备: {self._gpu_info['name']}")
            else:
                self._has_cuda = False
        except (subprocess.CalledProcessError, FileNotFoundError):
            self._has_cuda = False
            self.logger.info("ℹ️ 未发现 NVIDIA GPU，将使用纯 CPU 模式运行。")
            
        return self._has_cuda

    def get_acceleration_env(self) -> Dict[str, str]:
        """
        获取为了开启加速所需的各个工具的环境变量
        """
        env = os.environ.copy()
        if self.is_cuda_available():
            # 为支持 CUDA 的生物信息工具设置通用开关
            env["USE_CUDA"] = "1"
            env["CUDA_VISIBLE_DEVICES"] = "0"
            # 如果后续集成 Medaka 或备选的 GPU 拼接器，可以在此注入
            self.logger.info("已注入 GPU 加速上下文。")
        return env

    def apply_gpu_flags(self, tool_name: str, base_cmd: list) -> list:
        """
        针对特定工具注入 GPU 启动参数
        :param tool_name: 工具名称 (如 spades)
        :param base_cmd: 原始命令列表
        """
        if not self.is_cuda_available():
            return base_cmd
            
        # 示例：某些拼接变体支持 GPU 
        if tool_name == "spades" and "--gpu" not in base_cmd:
            return base_cmd + ["--gpu"] # 假设使用的 SPAdes 版本支持此参数
            
        return base_cmd
