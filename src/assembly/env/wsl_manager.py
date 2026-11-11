# -*- coding: utf-8 -*-
import os
import subprocess
from pathlib import Path
from typing import Optional, List

class WSLManager:
    """
    负责 Windows 与 WSL (Linux) 之间的跨系统指令调度与路径转换
    """
    @classmethod
    def is_available(cls) -> bool:
        """检查系统是否支持并开启了 WSL"""
        try:
            # 尝试获取 WSL 发行版列表
            res = subprocess.run(["wsl", "--list", "--quiet"], capture_output=True, timeout=5)
            return res.returncode == 0
        except:
            return False

    @classmethod
    def to_wsl_path(cls, windows_path: str) -> str:
        """
        将 Windows 路径转换为 WSL 路径，并优先使用无空格软链接
        """
        # 1. 使用稳定的项目根目录（不依赖运行时 CWD）
        try:
            from ...workbench.models.tool_config import ToolConfig
            project_root = str(ToolConfig.PROJECT_ROOT)
        except Exception:
            project_root = str(Path(__file__).resolve().parent.parent.parent.parent)
        try:
            abs_path = Path(windows_path).resolve()
            root_path = Path(project_root).resolve()
            
            if str(abs_path).startswith(str(root_path)):
                relative = abs_path.relative_to(root_path)
                # 使用预设的无空格软链接路径
                # 注意: Python 3.11 的 f-string 表达式内不允许出现反斜杠，需先转换
                relative_posix = str(relative).replace("\\", "/")
                return f"/ncbi_blast_link/{relative_posix}"
        except:
            pass

        # 2. 如果不在项目目录下，使用标准 /mnt 转换
        path = Path(windows_path).resolve()
        drive = path.drive.replace(":", "").lower()
        relative = str(path.relative_to(path.anchor)).replace("\\", "/")
        return f"/mnt/{drive}/{relative}"

    @classmethod
    def ensure_project_link(cls):
        """确保在 WSL 中存在指向项目根目录的无空格软链接"""
        try:
            from ...workbench.models.tool_config import ToolConfig
            project_root = str(ToolConfig.PROJECT_ROOT)
        except Exception:
            project_root = os.getcwd()
        try:
            #  强制创建相对于 /mnt/<盘符> 的根链接
            path = Path(project_root).resolve()
            drive = path.drive.replace(":", "").lower()
            relative = str(path.relative_to(path.anchor)).replace("\\", "/")
            
            target = f"/mnt/{drive}/{relative}"
            link = "/ncbi_blast_link"
            distro = cls.get_best_distro()
            cmd = ["wsl", "-d", distro, "-u", "root", "ln", "-sfT", target, link]
            subprocess.run(cmd, capture_output=True, timeout=5)
        except:
            pass

    @classmethod
    def shutdown_distro(cls):
        """完全关闭当前使用的 WSL 分发版，释放内存和进程"""
        try:
            distro = cls.get_best_distro()
            # 执行 wsl --terminate <distro>
            subprocess.run(["wsl", "--terminate", distro], capture_output=True, timeout=10)
            return True
        except Exception:
            return False

    @classmethod
    def wrap_cmd(cls, cmd: List[str], use_bash: bool = True) -> List[str]:
        """将普通命令封装为 WSL 格式 (自适应发行版)"""
        distro = cls.get_best_distro()
        distro_args = ["wsl", "-d", distro, "-u", "root"]
        if use_bash:
            return distro_args + ["bash", "-c", " ".join(cmd)]
        return distro_args + cmd

    @classmethod
    def get_best_distro(cls) -> str:
        """动态探测当前可用的 WSL 分发版，优先 Ubuntu，其次默认"""
        try:
            res = subprocess.run(
                ["wsl", "--list", "--quiet"],
                capture_output=True,
                timeout=3
            )
            if res.returncode == 0 and res.stdout:
                output = ""
                for enc in ['utf-16le', 'utf-16', 'utf-8']:
                    try:
                        output = res.stdout.decode(enc)
                        if "ubuntu" in output.lower() or "debian" in output.lower() or len(output.strip()) > 0:
                            break
                    except Exception:
                        continue
                
                # 过滤空字符与空白，清除非法控制字符
                distros = [line.strip().replace('\x00', '') for line in output.split('\n')]
                distros = [d for d in distros if d]
                if distros:
                    # 优先寻找 Ubuntu
                    for d in distros:
                        if "ubuntu" in d.lower():
                            return d
                    # 其次寻找 Debian
                    for d in distros:
                        if "debian" in d.lower():
                            return d
                    return distros[0]
        except Exception:
            pass
        return "Ubuntu"  # 最后的保底
