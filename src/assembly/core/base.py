
import abc
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable
from ..engine.runner import CommandRunner

# 全局模块级物理内存缓存，避免跨任务重复探测
_CACHED_SYSTEM_TOTAL_MEMORY_GB = None

class PipelineContext:
    """
    流水线上下文
    存储全局配置、中间文件路径及所有步骤的共享状态
    """
    def __init__(self, task_id: str, base_dir: Path, config: Dict[str, Any]):
        self.task_id = task_id
        self.base_dir = base_dir
        self.config = config
        self.is_wsl = config.get("is_wsl", False)
        self.data: Dict[str, Any] = {}
        self.history: List[Dict[str, Any]] = []
        self.is_aborted: bool = False
        
        # 回溯机制字段 (由步骤设置，由管理器消费)
        self.next_step_index: Optional[int] = None
        self.iteration_count: int = 0
        
        #  运行时内部工具对象 (不参与 JSON 序列化)
        self.gpu_manager: Any = None
        self.gpu_env: Optional[Dict[str, str]] = None
        
        #  内存盘统一资源管理器 (由 manager.py 注入)
        self.shm: Any = None

    def update(self, key: str, value: Any):
        self.data[key] = value

    def get(self, key: str, default: Any = None):
        return self.data.get(key, default)

class BaseAssemblyStep(abc.ABC):
    """
    模块化步骤基类
    """
    def __init__(self, context: PipelineContext):
        self.context = context
        self.runner = CommandRunner(self.__class__.__name__, is_wsl=context.is_wsl)
        self.logger = self.runner.logger   #  快捷访问日志对象
        self.status = "pending"
        self.progress = 0.0
        self.last_error: Optional[str] = None
        # 回调签名支持进度百分比和子状态描述
        self.on_progress: Optional[Callable[[float, Optional[str]], None]] = None

    @abc.abstractmethod
    async def execute(self) -> bool:
        """
        核心执行逻辑
        :return: 是否执行成功
        """
        pass

    def is_completed(self) -> bool:
        """
        检查该步骤是否已经成功完成（通过物理文件校验）
        :return: 是否已完成
        """
        return False

    def get_working_dir(self) -> Path:
        path = self.context.base_dir / self.__class__.__name__.lower()
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def get_best_wsl_tmp_dir(self, required_gb: float = 5.0) -> str:
        """
        智能内存/硬盘路由逻辑 (委托 ShmManager)
        
        如果 PipelineContext 中已注入 ShmManager，则通过统一管理器分配；
        否则回退到简单的 /tmp 分配 (向后兼容)。
        """
        if not self.context.is_wsl:
            return str(self.get_working_dir()).replace("\\", "/")

        # 委托 ShmManager (推荐路径)
        if self.context.shm is not None:
            step_name = self.__class__.__name__.lower()
            ws = await self.context.shm.acquire_manual(
                step_name, required_gb=required_gb
            )
            self.logger.info(
                f"{'内存盘' if ws.is_ramdisk else 'SSD'} 工作空间: {ws.path} "
                f"(进程可用内存: {self.context.shm.get_process_memory_limit()}G)"
            )
            return ws.path

        # 回退路径 (无 ShmManager 时)
        fallback = f"/tmp/asm_{self.context.task_id}_{self.__class__.__name__.lower()}"
        self.logger.warning(f"ShmManager 未注入，回退至: {fallback}")
        return fallback

    async def get_total_memory_gb(self) -> float:
        """
         获取当前系统的实际物理内存容量 (GB)
        ️ WSL2 的 /proc/meminfo MemTotal 包含 Windows Pagefile，会严重虚高
        优先通过 Windows WMI 获取真实物理内存
        """
        global _CACHED_SYSTEM_TOTAL_MEMORY_GB
        if _CACHED_SYSTEM_TOTAL_MEMORY_GB is not None:
            return _CACHED_SYSTEM_TOTAL_MEMORY_GB

        gb = 16.0
        try:
            # 优先从 context 获取 (缓存)
            if "system_total_memory_gb" in self.context.data:
                _CACHED_SYSTEM_TOTAL_MEMORY_GB = self.context.data["system_total_memory_gb"]
                return _CACHED_SYSTEM_TOTAL_MEMORY_GB

            # 方案 1: 通过 WSL 调用 Windows PowerShell 获取真实物理内存
            out_win = []
            def collect_win(line): out_win.append(line.strip())
            await self.runner.run_command(
                ["bash", "-c",
                 "powershell.exe -NoProfile -Command "
                 "\"[math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB, 1)\" "
                 "2>/dev/null"],
                on_output=collect_win, silence_errors=True
            )
            for line in out_win:
                try:
                    val = float(line.replace(',', '.'))
                    if 1 < val < 2048:  # 合理性校验
                        gb = val
                        self.logger.info(f" 实际物理内存 (Windows WMI): {gb:.1f} GB")
                        break
                except (ValueError, TypeError):
                    continue

            # 方案 2: 兜底 — WSL /proc/meminfo (注意此值可能偏高)
            if gb is None:
                out = []
                def collect(line): out.append(line)
                await self.runner.run_command(
                    ["grep", "MemTotal", "/proc/meminfo"],
                    is_shell=True, on_output=collect
                )
                for line in out:
                    if "MemTotal" in line:
                        kb = int(line.split(":")[1].strip().split()[0])
                        gb = kb / (1024 * 1024)
                        self.logger.warning(
                            f" 内存来自 WSL MemTotal: {gb:.1f} GB (可能含虚拟内存，已打 8 折修正)"
                        )
                        gb = gb * 0.8  # 打折修正，防止超分配
                        break

            if gb and gb > 0:
                #  物理穿透方案：如果探测值处于 WSL2 典型的 50%~80% 配额区，则尝试抓取宿主真实物理值
                if 8 <= gb <= 32:
                    out_sys = []
                    await self.runner.run_command(
                        ["bash", "-c", "systeminfo.exe | grep 'Total Physical Memory'"], 
                        on_output=lambda l: out_sys.append(l), silence_errors=True
                    )
                    for s_line in out_sys:
                        # 格式示例: Total Physical Memory:     49,152 MB
                        match = re.search(r"(\d+[\d,]*)\s+MB", s_line.replace("\x00", ""))
                        if match:
                            raw_mb = int(match.group(1).replace(",", ""))
                            real_gb = round(raw_mb / 1024, 1)
                            if real_gb > gb:
                                self.logger.info(f" 物理穿透成功：识别到宿主真实内存 {real_gb} GB (WSL配额 {gb:.1f} GB)")
                                gb = real_gb
                                break
                                
                self.context.data["system_total_memory_gb"] = gb
                _CACHED_SYSTEM_TOTAL_MEMORY_GB = gb
                return gb
        except: pass
        _CACHED_SYSTEM_TOTAL_MEMORY_GB = gb or 16.0
        return _CACHED_SYSTEM_TOTAL_MEMORY_GB
