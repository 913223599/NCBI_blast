
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
