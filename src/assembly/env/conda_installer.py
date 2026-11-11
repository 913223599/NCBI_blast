# -*- coding: utf-8 -*-
import os
import subprocess
import urllib.request
import logging
from pathlib import Path
from typing import Optional

class CondaInstaller:
    """
    负责静默下载并部署极简版 Conda (Miniconda) 环境
    """
    CONDA_URL = "https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe"

    def __init__(self, install_base_dir: Path):
        self.install_dir = install_base_dir / "tools" / "miniconda"
        self.installer_path = install_base_dir / "miniconda_installer.exe"
        self.logger = logging.getLogger("Assembly.Installer")

    def download_installer(self):
        """在线下载官方安装包"""
        if self.installer_path.exists():
            return True
            
        self.logger.info(f"正在从官网下载 Miniconda 安装程序...")
        try:
            # 记录上一次打印的百分比，避免重复输出
            self._last_pct = -1

            def progress(block_num, block_size, total_size):
                pct = int(block_num * block_size * 100 / total_size)
                # 每隔 5% 记录一次
                if pct % 5 == 0 and pct != self._last_pct:
                    self.logger.info(f"下载进度: {pct}%")
                    self._last_pct = pct

            urllib.request.urlretrieve(self.CONDA_URL, str(self.installer_path), progress)
            return True
        except Exception as e:
            self.logger.error(f"下载失败: {str(e)}")
            return False

    def run_silent_install(self) -> bool:
        """执行 Windows 静默安装 (优化带空格路径的处理)"""
        import shutil
        if self.install_dir.exists():
             self.logger.info("清理已存在的异常安装目录...")
             try:
                 shutil.rmtree(str(self.install_dir))
             except:
                 pass

        self.logger.info(f"正在进行静默安装至: {self.install_dir}")
        
        #  重要: Miniconda /D 参数后面即使有空格也不能加引号
        # 且必须使用 shell=True 配合字符串才能正确传递
        cmd_str = f'"{self.installer_path}" /S /InstallationType=JustMe /D={self.install_dir}'
        
        try:
            # 静默安装通常需要几分钟
            subprocess.run(cmd_str, check=True, timeout=600, shell=True)
            self.logger.info(" Miniconda 部署成功！")
            
            # 安装成功后清理安装包
            if self.installer_path.exists():
                os.remove(self.installer_path)
            return True
        except Exception as e:
            self.logger.error(f"安装过程出错: {str(e)}")
            return False

    def get_installed_conda_bin(self) -> Optional[str]:
        """获取刚安装好的 conda.exe 路径"""
        path = self.install_dir / "Scripts" / "conda.exe"
        return str(path) if path.exists() else None
