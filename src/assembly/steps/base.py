
import abc
from pathlib import Path
from typing import Dict, Any, Optional

class AssemblyStep(abc.ABC):
    """
    基因组拼接流水线步骤的抽象基类
    """
    def __init__(self, task_id: str, working_dir: Path, config: Dict[str, Any]):
        self.task_id = task_id
        self.working_dir = working_dir
        self.config = config
        self.status = "pending"  # pending, running, completed, failed
        self.progress = 0.0
        self.result_data: Dict[str, Any] = {}
        
        # 确保工作目录存在
        self.working_dir.mkdir(parents=True, exist_ok=True)

    @abc.abstractmethod
    async def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行当前步骤
        :param input_data: 上一步传递下来的数据字典
        :return: 输出数据字典，将传递给下一步
        """
        pass

    def update_progress(self, progress: float):
        self.progress = progress

    def set_status(self, status: str):
        self.status = status
        
    def get_info(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "step_name": self.__class__.__name__,
            "status": self.status,
            "progress": self.progress,
            "results": self.result_data
        }
