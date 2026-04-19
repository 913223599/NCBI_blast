
import abc
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable
from ..engine.runner import CommandRunner

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
        
        # 🔗 运行时内部工具对象 (不参与 JSON 序列化)
        self.gpu_manager: Any = None
        self.gpu_env: Optional[Dict[str, str]] = None

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
        self.logger = self.runner.logger   # 🔗 快捷访问日志对象
        self.status = "pending"
        self.progress = 0.0
        # 💡 回调签名支持进度百分比和子状态描述
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
        🚀 智能内存/硬盘路由逻辑
        根据需要的空间大小，决策在 /dev/shm (内存盘) 还是 /tmp (原生硬盘) 执行
        """
        if not self.context.is_wsl:
            return str(self.get_working_dir()).replace("\\", "/")

        tmp_root = "/tmp"
        try:
            # 1. 尝试扩容内存盘 (仅在第一次调用时或必要时尝试，需要 root 权限，WSL runner 默认具备)
            # 我们直接尝试将其上限设为 40G (针对用户 48G 内存)
            await self.runner.run_command(["mount", "-o", "remount,size=40G", "/dev/shm"], is_shell=True)
            
            # 2. 探测当前剩余空间
            out = []
            def collect(line): out.append(line)
            await self.runner.run_command(["df", "-k", "/dev/shm"], is_shell=True, on_output=collect)
            
            # 解析 df -k 输出 (通常第二行是数据)
            # Filesystem     1K-blocks  Used Available Use% Mounted on
            # tmpfs           41943040     4  41943036   1% /dev/shm
            for line in out:
                if "/dev/shm" in line:
                    parts = line.split()
                    if len(parts) >= 4:
                        avail_kb = int(parts[3])
                        avail_gb = avail_kb / (1024 * 1024)
                        if avail_gb >= required_gb:
                            tmp_root = "/dev/shm"
                            self.logger.info(f"⚡ 内存盘空间充足 ({avail_gb:.1f}G > {required_gb}G)，激活内存首选模式")
                        else:
                            self.logger.warn(f"🐢 内存盘空闲不足 ({avail_gb:.1f}G < {required_gb}G)，降级至原生 EXT4 存储")
                    break
        except Exception as e:
            self.logger.warn(f"内存盘探测异常: {e}，默认使用 /tmp")

        wsl_tmp_path = f"{tmp_root}/asm_{self.context.task_id}_{self.__class__.__name__.lower()}"
        return wsl_tmp_path
