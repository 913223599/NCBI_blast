
import logging
from pathlib import Path
from typing import Optional, Dict

class HostPathResolver:
    """
    宿主路径解析器 (SRP: 负责将前端 ID 转化为后端物理 Fasta 路径)
    """
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.host_base_dir = self.project_root / "database" / "hosts"

    def resolve(self, host_id: str) -> Optional[Path]:
        """
        解析逻辑：支持物理路径、预设 ID、以及云端同步标识
        """
        # 1. 如果已经是物理路径 (含盘符或斜杠)，直接原样返回
        if ":" in host_id or "/" in host_id or "\\" in host_id:
            return Path(host_id)
            
        # 2. 预设库映射矩阵
        host_map = {
            "default_ecoli": self.host_base_dir / "ecoli_k12.fasta",
            "b_subtilis": self.host_base_dir / "b_subtilis.fasta",
            "s_aureus": self.host_base_dir / "s_aureus.fasta"
        }
        
        path = host_map.get(host_id)
        if path and path.exists():
            return path
            
        return None
