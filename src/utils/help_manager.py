"""
帮助文档管理器
负责管理和加载应用程序的帮助文档
"""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)
_VALID_TOPIC_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")

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
        raw_structure = [
            {
                "category": "入门指南",
                "topics": [
                    {"id": "quick_start", "title": "快速入门"},
                ]
            },
            {
                "category": "核心分析流程",
                "topics": [
                    {"id": "local_blast", "title": "本地 BLAST 与比对"},
                    {"id": "genome_assembly", "title": "NGCS 基因组拼接"},
                    {"id": "analysis_workbench", "title": "组装后深度分析"},
                    {"id": "figure_studio", "title": "科研绘图工坊"},
                    {"id": "strain_bank", "title": "菌毒种库与冻存管理"},
                    {"id": "automation_pipelines", "title": "自动化流水线"},
                ]
            },
            {
                "category": "数据与系统设置",
                "topics": [
                    {"id": "database_manager", "title": "数据库管理"},
                    {"id": "history", "title": "任务历史"},
                    {"id": "settings", "title": "参数设置"},
                    {"id": "translation_debugger", "title": "翻译调试器"},
                ]
            }
        ]
        # 仅返回物理文件存在的帮助主题，避免无效空条目
        available = set(self.get_help_topics())
        filtered = []
        for group in raw_structure:
            valid_topics = [t for t in group["topics"] if t["id"] in available]
            if valid_topics:
                filtered.append({"category": group["category"], "topics": valid_topics})
        return filtered

    def get_help_content(self, topic_id):
        """
        获取指定主题的帮助内容
        
        Args:
            topic_id (str): 主题ID（通常是文件名，如 'quick_start'）
            
        Returns:
            str: Markdown 格式的帮助内容，如果非法或未找到则返回错误提示
        """
        if not isinstance(topic_id, str) or not _VALID_TOPIC_ID_RE.match(topic_id):
            logger.warning("拒绝非法帮助主题标识请求: %r", topic_id)
            return "# 错误\n\n非法的帮助主题标识。"

        help_root = self.help_dir.resolve()
        file_path = (help_root / f"{topic_id}.md").resolve()
        if not file_path.is_relative_to(help_root):
            logger.warning("拦截帮助文档路径穿越尝试: %r", topic_id)
            return "# 错误\n\n非法的帮助文档路径。"

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
