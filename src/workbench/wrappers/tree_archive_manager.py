"""
Archive Manager - 负责分析结果的归档与清理
职责：管理会话归档、文件迁移和临时产物清理
"""
import logging
import shutil
import time
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


class ArchiveManager:
    """分析结果归档管理器"""
    
    def __init__(self, base_archive_dir: Path = None):
        """
        初始化归档管理器
        
        Args:
            base_archive_dir: 基础归档目录，默认为 results/tree_results
        """
        self.base_archive_dir = base_archive_dir or Path("results/tree_results")
        self.base_archive_dir.mkdir(parents=True, exist_ok=True)
    
    def create_session_archive(self, 
                               source_fasta: Path, 
                               result_files: dict,
                               project_id: str = None,
                               session_id: str = None) -> Path:
        """
        创建会话归档，将源文件和结果文件组织到结构化目录
        
        Args:
            source_fasta: 原始FASTA文件路径
            result_files: 结果文件字典 {key: file_path}
            project_id: 项目ID（默认使用文件名）
            session_id: 会话ID（默认使用时间戳）
            
        Returns:
            归档目录路径
        """
        if not project_id:
            project_id = source_fasta.stem
        
        if not session_id:
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            session_id = f"Session_{timestamp}"
        
        # 创建归档目录结构: results/tree_results/{project_id}/{session_id}/
        archive_dir = self.base_archive_dir / project_id / session_id
        archive_dir.mkdir(parents=True, exist_ok=True)
        
        archived_files = {}
        
        try:
            # 1. 归档原始序列文件
            archive_fasta = archive_dir / source_fasta.name
            shutil.copy2(source_fasta, archive_fasta)
            archived_files["input_fasta"] = archive_fasta
            
            # 2. 归档结果文件
            for key, file_path in result_files.items():
                if file_path and Path(file_path).exists():
                    src_path = Path(file_path)
                    dest_path = archive_dir / src_path.name
                    shutil.move(str(src_path), str(dest_path))
                    archived_files[key] = dest_path
                    # 关键修复：同步更新传入的 result_files 字典，确保调用方能获取新路径
                    result_files[key] = dest_path
            
            logger.info(f"Session archived to: {archive_dir}")
            return archive_dir
            
        except Exception as e:
            logger.error(f"Failed to archive session: {e}")
            raise
    
    def cleanup_staging_area(self, project_id: str, staging_dir: Path = None):
        """
        清理临时工作区的冗余产物
        
        Args:
            project_id: 项目ID（用于匹配相关文件）
            staging_dir: 临时工作区目录（默认为 results/）
        """
        if not staging_dir:
            staging_dir = Path("results")
        
        if not staging_dir.exists():
            return
        
        cleaned_count = 0
        
        try:
            # 清理与项目相关的临时文件（不进入子目录）
            patterns = [
                f"{project_id}*.dm",
                f"{project_id}*_aligned.fasta",
                f"{project_id}*.nwk",
                f"{project_id}*.log",
                f"{project_id}*.mldist",
                f"{project_id}*.iqtree",
                f"{project_id}*.ckp.gz",
                "user_input.*"
            ]
            
            for pattern in patterns:
                for junk_file in staging_dir.glob(pattern):
                    if junk_file.is_file():
                        junk_file.unlink()
                        cleaned_count += 1
                        logger.debug(f"Cleaned up: {junk_file}")
            
            if cleaned_count > 0:
                logger.info(f"Cleanup completed: removed {cleaned_count} temporary files")
                
        except Exception as e:
            logger.warning(f"Cleanup execution failed (non-critical): {e}")
    
    def get_session_list(self, project_id: str) -> List[Path]:
        """
        获取指定项目的所有会话列表
        
        Args:
            project_id: 项目ID
            
        Returns:
            会话目录路径列表（按时间倒序）
        """
        project_dir = self.base_archive_dir / project_id
        
        if not project_dir.exists():
            return []
        
        sessions = [d for d in project_dir.iterdir() if d.is_dir()]
        # 按修改时间倒序排列
        sessions.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        
        return sessions
    
    def get_latest_session(self, project_id: str) -> Optional[Path]:
        """
        获取项目的最新会话
        
        Args:
            project_id: 项目ID
            
        Returns:
            最新会话目录路径，不存在则返回None
        """
        sessions = self.get_session_list(project_id)
        return sessions[0] if sessions else None
