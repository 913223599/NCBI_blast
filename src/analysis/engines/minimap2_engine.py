"""
Minimap2 比对引擎
职责：调用Minimap2进行序列比对
"""

import logging
import subprocess
from typing import Dict, Any
from pathlib import Path

from ..core.base import BaseEngine
from src.assembly.env.wsl_manager import WSLManager

logger = logging.getLogger(__name__)


class Minimap2Engine(BaseEngine):
    """
    Minimap2比对引擎
    职责：封装Minimap2调用，处理跨系统路径转换
    """
    
    def __init__(self, preset: str = "asm5", enable_cs: bool = True):
        """
        初始化引擎
        :param preset: Minimap2预设参数
        :param enable_cs: 是否启用CS标签
        """
        self.preset = preset
        self.enable_cs = enable_cs
        self.tool_name = "minimap2"
    
    def is_available(self) -> bool:
        """检查Minimap2是否可用"""
        try:
            result = subprocess.run(
                ["wsl", "-d", "Ubuntu", "-u", "root", self.tool_name, "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def execute(
        self,
        target_path: str,
        query_path: str,
        output_path: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        执行Minimap2比对
        :param target_path: 目标序列路径
        :param query_path: 查询序列路径
        :param output_path: 输出PAF文件路径
        :return: 执行结果
        """
        try:
            # 转换路径为WSL路径
            wsl_target = WSLManager.to_wsl_path(target_path)
            wsl_query = WSLManager.to_wsl_path(query_path)
            
            # 构建命令
            cmd = [
                "wsl", "-d", "Ubuntu", "-u", "root",
                self.tool_name,
                "-x", self.preset
            ]
            
            if self.enable_cs:
                cmd.append("--cs")
            
            cmd.extend([wsl_target, wsl_query])
            
            # 执行并捕获输出
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as out_f:
                process = subprocess.run(
                    cmd,
                    stdout=out_f,
                    stderr=subprocess.PIPE,
                    check=True,
                    encoding='utf-8',
                    errors='ignore',
                    timeout=300  # 5分钟超时
                )
            
            return {
                "success": True,
                "output_path": output_path,
                "message": "比对完成"
            }
            
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "比对超时"
            }
        except FileNotFoundError as e:
            return {
                "success": False,
                "error": f"Minimap2未找到: {e}"
            }
        except Exception as e:
            logger.error(f"Minimap2执行失败: {e}")
            return {
                "success": False,
                "error": f"Minimap2执行失败: {e}"
            }
