# -*- coding: utf-8 -*-
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional, List

class CondaResolver:
    """
    负责在不同操作系统环境下深度搜寻 Conda 执行程序
    """
    DEFAULT_WINDOWS_PATHS = [
        "miniconda3/Scripts/conda.exe",
        "anaconda3/Scripts/conda.exe",
        "Miniconda3/Scripts/conda.exe",
        "Anaconda3/Scripts/conda.exe",
        "AppData/Local/Continuum/anaconda3/Scripts/conda.exe",
        "AppData/Local/miniconda3/Scripts/conda.exe"
    ]

    @classmethod
    def find_conda(cls) -> Optional[str]:
        """优先搜索 PATH，然后搜索本程序 tools 目录，最后搜索常见目录"""
        # 0. 定义校验函数
        def is_valid(p: str) -> bool:
            try:
                # 尝试运行 conda --version
                res = subprocess.run([p, "--version"], capture_output=True, text=True, timeout=5, encoding='utf-8', errors='ignore')
                return res.returncode == 0
            except:
                return False

        # 1. 检查 PATH
        conda_in_path = shutil.which("conda")
        if conda_in_path and is_valid(conda_in_path):
            return conda_in_path

        # 2. 检查程序内置 tools 目录
        project_root = Path(__file__).resolve().parents[3]
        internal_conda = project_root / "tools" / "miniconda" / "Scripts" / "conda.exe"
        if internal_conda.exists() and is_valid(str(internal_conda)):
            return str(internal_conda)

        # 3. 针对 Windows 进行深度搜索
        if os.name == 'nt':
            roots = [
                Path(os.environ.get("USERPROFILE") or Path.home()),
                Path("C:/ProgramData"),
                Path("D:/"),
                Path(os.environ.get("LOCALAPPDATA", ""))
            ]
            
            for root in roots:
                if not root or not root.exists(): continue
                for p_suffix in cls.DEFAULT_WINDOWS_PATHS:
                    full_path = root / p_suffix
                    if full_path.exists() and is_valid(str(full_path)):
                        return str(full_path)

        return None

    @classmethod
    def get_conda_cmd(cls) -> str:
        """获取可用的 conda 命令，如果未找到则引发异常"""
        path = cls.find_conda()
        if not path:
            raise FileNotFoundError(
                "未能在系统中找到 Conda 环境。请确保已安装 Anaconda 或 Miniconda，"
                "并将其添加到 PATH，或者安装在默认目录下。"
            )
        return path
