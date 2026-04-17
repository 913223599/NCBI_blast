
import os
import gzip
from pathlib import Path
from typing import Tuple, Optional, Dict, Any

class AssemblyFileHandler:
    """
    专门负责拼接输入文件的识别与校验
    支持格式: .fastq, .fastq.gz, .fq, .fq.gz
    """
    @staticmethod
    def validate_fastq_pair(r1: str, r2: str) -> bool:
        """
        验证双端 Fastq 文件是否匹配及格式是否正确
        """
        p1, p2 = Path(r1), Path(r2)
        
        # 1. 存在性检查
        if not p1.exists() or not p2.exists():
            return False
            
        # 2. 格式扩展名检查
        valid_exts = {".fastq", ".fq", ".gz"}
        if p1.suffix not in valid_exts or p2.suffix not in valid_exts:
            return False
            
        # 3. 双端配对简单校验 (通常文件名中包含 R1/R2)
        if "R1" in p1.name and "R2" not in p2.name:
             return False
             
        return True

    @staticmethod
    def get_sample_id(r1_path: str) -> str:
        """
        从文件名自动推断样本 ID (增强版)
        支持: .R1.fastq.gz, _R1.fq.gz, .1.fastq.gz 等各种组合
        """
        import re
        name = Path(r1_path).name
        # 1. 尝试移除常见的测序末尾标记及扩展名
        # 匹配模式: (.R1 | _R1 | .1 | _1) 后跟 (.fastq | .fq | .gz)+
        pattern = r'[\._][Rr]?1[\._].*|[\._](fastq|fq|gz).*'
        sample_id = re.split(pattern, name)[0]
        
        # 2. 如果切完发现是空的，就保留原名（兜底）
        return sample_id if sample_id else name.split('.')[0]

    @staticmethod
    def check_file_integrity(file_path: str) -> bool:
        """
        如果是 .gz 文件，尝试读取末尾以确认文件没有在传输中损坏
        """
        if not file_path.endswith(".gz"):
            return True
            
        try:
            with gzip.open(file_path, 'rb') as f:
                f.seek(-1, os.SEEK_END)
                return True
        except Exception:
            return False
