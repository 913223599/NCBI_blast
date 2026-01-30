"""
帮助文档管理器
负责管理和加载应用程序的帮助文档
"""

import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class HelpManager:
    """
    帮助文档管理器单例类
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(HelpManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self.project_root = Path(__file__).resolve().parent.parent.parent
        self.help_dir = self.project_root / "resources" / "help"
        self._ensure_help_dir()
        self._initialized = True

    def _ensure_help_dir(self):
        """确保帮助目录存在"""
        if not self.help_dir.exists():
            try:
                self.help_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.error(f"无法创建帮助目录: {e}")

    def get_help_topics(self):
        """获取所有可用的帮助主题（文件名列表）"""
        if not self.help_dir.exists():
            return []
            
        topics = []
        for file in self.help_dir.glob("*.md"):
            # 返回文件名（不含扩展名）作为主题ID
            topics.append(file.stem)
        return sorted(topics)

    def get_help_structure(self):
        """
        获取帮助文档的分类结构
        Returns:
            list: [{"category": str, "topics": [{"id": str, "title": str}, ...]}, ...]
        """
        return [
            {
                "category": "入门指南",
                "topics": [
                    {"id": "quick_start", "title": "快速入门"},
                ]
            },
            {
                "category": "核心功能",
                "topics": [
                    {"id": "local_blast", "title": "本地 BLAST"},
                    {"id": "elastic_blast", "title": "Elastic BLAST 云服务"},
                    {"id": "database_manager", "title": "数据库管理"},
                    {"id": "history", "title": "任务历史"},
                ]
            },
            {
                "category": "高级设置",
                "topics": [
                    {"id": "settings", "title": "参数设置"},
                    {"id": "translation_debugger", "title": "翻译调试器"},
                ]
            }
        ]

    def get_help_content(self, topic_id):
        """
        获取指定主题的帮助内容
        
        Args:
            topic_id (str): 主题ID（通常是文件名，如 'elastic_blast'）
            
        Returns:
            str: Markdown 格式的帮助内容，如果未找到则返回错误提示
        """
        file_path = self.help_dir / f"{topic_id}.md"
        
        if not file_path.exists():
            logger.warning(f"帮助文件未找到: {file_path}")
            return f"# 错误\n\n未找到主题 '{topic_id}' 的帮助文档。"
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.error(f"读取帮助文件失败: {e}")
            return f"# 错误\n\n读取帮助文件时发生错误: {e}"

# 全局获取函数
def get_help_manager():
    return HelpManager()
