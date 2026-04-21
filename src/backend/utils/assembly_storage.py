import os
import shutil
import logging
from pathlib import Path
from datetime import datetime, timedelta

logger = logging.getLogger("api_server")

class AssemblyStorage:
    """
    AssemblyStorage - 专门负责任务文件夹生命周期管理
    遵循单一职责原则，处理所有与文件存储相关的物理操作
    """
    
    # 基础存储路径 (使用 __file__ 确保不依赖运行时 CWD)
    BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "results" / "assembly"

    @classmethod
    def get_task_dir(cls, task_id: str) -> Path:
        """获取并创建任务专属目录"""
        task_dir = cls.BASE_DIR / str(task_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        return task_dir

    @classmethod
    def get_results_path(cls, task_id: str, filename: str) -> str:
        """获取任务结果文件的完整路径"""
        return str((cls.get_task_dir(task_id) / filename).resolve())

    @classmethod
    def cleanup_old_tasks(cls, days: int = 7):
        """清理超过指定天数的旧任务数据"""
        now = datetime.now()
        if not cls.BASE_DIR.exists():
            return

        for task_folder in cls.BASE_DIR.iterdir():
            if task_folder.is_dir():
                mtime = datetime.fromtimestamp(task_folder.stat().st_mtime)
                if now - mtime > timedelta(days=days):
                    try:
                        shutil.rmtree(task_folder)
                        logger.info(f"🧹 [Storage] 已自动清理过期任务: {task_folder.name}")
                    except Exception as e:
                        logger.error(f"❌ [Storage] 清理失败 {task_folder.name}: {e}")

    @classmethod
    def get_relative_path(cls, absolute_path: str) -> str:
        """将绝对路径转换为相对于项目根目录的路径（用于前端显示）"""
        try:
            return os.path.relpath(absolute_path, os.getcwd())
        except:
            return absolute_path
