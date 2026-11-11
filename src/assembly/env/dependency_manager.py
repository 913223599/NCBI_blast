# -*- coding: utf-8 -*-
import subprocess
import shutil
import logging
import asyncio
from typing import List, Dict, Optional

import asyncio
from typing import List, Dict, Optional
from .conda_resolver import CondaResolver

from .wsl_manager import WSLManager

class DependencyManager:
    """
    负责生物信息工具栈的在线探测与自动部署
    在 Windows 下优先探测 WSL 兼容性
    """
    def __init__(self):
        self.logger = logging.getLogger("Assembly.Env")
        self.tools = ["fastp", "unicycler", "flye", "prokka", "minimap2", "samtools", "datasets", "bwa", "polypolish", "checkv", "seqtk", "spades", "flash", "gapfiller", "phispy", "kraken2"]
        self.is_wsl = WSLManager.is_available()

    def check_tool_installed(self, tool_name: str) -> bool:
        """检查工具是否就绪（支持本地或 WSL 穿透检查）"""
        if shutil.which(tool_name): return True
        
        if self.is_wsl:
            try:
                #  核心修复：显式使用 -u root 检查，防止普通用户 PATH 缺失导致误判
                cmd = ["wsl", "-d", "Ubuntu", "-u", "root", "which", tool_name]
                res = subprocess.run(cmd, capture_output=True, encoding='utf-8', errors='ignore', timeout=5)
                return res.returncode == 0
            except:
                pass
        return False

    async def install_dependencies(self) -> Dict[str, bool]:
        """
        尝试自动安装缺失的依赖 (探测到 WSL 时优先使用 Linux 版)
        """
        # --- 针对 Windows 原生 Conda 的 ToS 接受 ---
        if not self.is_wsl:
            await self._ensure_tos_accepted()

        results = {}
        for tool in self.tools:
            if self.check_tool_installed(tool):
                self.logger.info(f" 工具 {tool} 已就绪")
                results[tool] = True
            else:
                self.logger.warning(f" 未找到工具 {tool}，尝试进行静默安装...")
                try:
                    success = await self._install_via_conda(tool)
                    results[tool] = success
                except Exception as e:
                    self.logger.error(f"安装 {tool} 时发生异常: {str(e)}")
                    results[tool] = False
        return results

    async def _ensure_tos_accepted(self):
        """自动接受 Conda 的服务条款，防止非交互式模式安装失败"""
        try:
            conda_bin = CondaResolver.get_conda_cmd()
            channels = [
                "https://repo.anaconda.com/pkgs/main",
                "https://repo.anaconda.com/pkgs/r",
                "https://repo.anaconda.com/pkgs/msys2"
            ]
            
            for channel in channels:
                self.logger.info(f"正在自动接受 Conda 服务条款: {channel}")
                # 执行: conda tos accept --override-channels --channel <URL>
                cmd = [conda_bin, "tos", "accept", "--override-channels", "--channel", channel]
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await process.communicate()
        except:
            # 如果是旧版 conda 可能没有 tos 命令，忽略错误继续
            pass

    async def _install_via_conda(self, tool_name: str) -> bool:
        """调用 Conda 进行安装 (支持 Windows 原生与 WSL 转发)"""
        # --- 情况 A: 存在 WSL，使用 Linux 方式安装 ---
        if self.is_wsl:
            self.logger.info(f"正在通过 WSL (Ubuntu) 安装 {tool_name}...")
            #  强制指定 -d Ubuntu
            #  直接传递参数列表，减少嵌套转义
            cmd = ["wsl", "-d", "Ubuntu", "-u", "root", "conda", "install", "-y", "-c", "bioconda", "-c", "conda-forge", tool_name]
            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()
                if process.returncode == 0:
                    return True
                
                # 如果没装 conda，尝试使用 apt
                self.logger.warning("WSL 中未找到 Conda，尝试使用 Ubuntu 包管理器 Apt...")
                #  增强：unset 代理防止网络死循环，并添加 --fix-missing
                #  增强：使用 bash 执行复合指令 (update && install)
                apt_cmd = "apt-get update --fix-missing && apt-get install -y --fix-missing fastp prokka unicycler minimap2 samtools flash"
                full_apt_cmd = ["wsl", "-d", "Ubuntu", "-u", "root", "bash", "-c", apt_cmd]
                
                process = await asyncio.create_subprocess_exec(
                    *full_apt_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()
                
                if process.returncode == 0:
                    self.logger.info(f" {tool_name} 通过 Apt 安装成功")
                    return True
                else:
                    self.logger.error(f" Apt 安装失败 (代码 {process.returncode})")
                    return False
            except Exception as e:
                self.logger.error(f"WSL 安装失败: {str(e)}")
                return False

        # --- 情况 B: 仅 Windows 原生 ---
        try:
            conda_bin = CondaResolver.get_conda_cmd()
        except FileNotFoundError as e:
            self.logger.error(str(e))
            return False

        # 针对特定工具指定合适的 Channel
        channels = ["bioconda", "conda-forge"]
        channel_args = []
        for c in channels:
            channel_args.extend(["-c", c])
            
        # 使用获取到的绝对路径执行
        cmd = [conda_bin, "install", "-y", tool_name] + channel_args
        
        try:
            self.logger.info(f"正在通过 Conda 安装 {tool_name} (路径: {conda_bin})...")
            # 捕获输出以供调试
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                self.logger.info(f" {tool_name} 安装成功")
                return True
            else:
                error_msg = stderr.decode('utf-8', errors='ignore').strip()
                self.logger.error(f" {tool_name} 安装失败 (代码 {process.returncode}): {error_msg}")
                return False
        except Exception as e:
            self.logger.error(f" 执行 Conda 指令时崩溃: {str(e)}")
            return False
