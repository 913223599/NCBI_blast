"""
ID Manager - 负责序列ID的安全化处理与映射管理
职责：统一管理FASTA序列ID的转换、验证和还原
"""
import re
from pathlib import Path
from typing import Dict, Tuple

from Bio import SeqIO
from Bio.SeqRecord import SeqRecord


class IDManager:
    """序列ID管理器，处理长ID截断和特殊字符问题"""
    
    def __init__(self):
        self.id_map: Dict[str, str] = {}  # short_id -> original_id
    
    def sanitize_fasta(self, input_fasta: Path) -> Tuple[Path, Dict[str, str]]:
        """
        清理FASTA文件中的ID，生成安全的短ID
        
        Args:
            input_fasta: 原始FASTA文件路径
            
        Returns:
            (清理后的FASTA路径, ID映射表 {short_id: original_id})
        """
        if not input_fasta.exists():
            raise FileNotFoundError(f"FASTA file not found: {input_fasta}")
        
        sanitized_fasta = input_fasta.parent / f"{input_fasta.stem}_safe.fasta"
        id_map = {}
        safe_records = []
        
        try:
            records = list(SeqIO.parse(input_fasta, "fasta"))
            for i, rec in enumerate(records):
                short_id = f"S{i:05d}"
                id_map[short_id] = rec.id
                
                # 创建新的SeqRecord，使用短ID
                safe_rec = SeqRecord(
                    seq=rec.seq,
                    id=short_id,
                    description=""
                )
                safe_records.append(safe_rec)
            
            SeqIO.write(safe_records, sanitized_fasta, "fasta")
            self.id_map = id_map
            
            return sanitized_fasta, id_map
            
        except Exception as e:
            # 清理可能生成的临时文件
            if sanitized_fasta.exists():
                sanitized_fasta.unlink()
            raise RuntimeError(f"Failed to sanitize FASTA IDs: {e}")
    
    def restore_ids_in_newick(self, newick_content: str, id_map: Dict[str, str]) -> str:
        """
        在Newick字符串中还原原始ID
        
        Args:
            newick_content: 包含短ID的Newick字符串
            id_map: ID映射表 {short_id: original_id}
            
        Returns:
            还原后的Newick字符串
        """
        if not id_map:
            return newick_content
        
        restored = newick_content
        # 按照长ID降序排列防止包含关系导致的错误替换
        for short_id in sorted(id_map.keys(), key=len, reverse=True):
            if short_id in restored:
                restored = restored.replace(short_id, id_map[short_id])
        
        return restored
    
    def validate_id_safety(self, sequence_id: str) -> bool:
        """
        验证ID是否安全（无特殊字符、长度适中）
        
        Args:
            sequence_id: 待验证的序列ID
            
        Returns:
            True if safe, False otherwise
        """
        # NCBI工具通常要求：不含空格、特殊字符，长度<100
        if len(sequence_id) > 100:
            return False
        
        # 只允许字母、数字、下划线、连字符、点号
        if not re.match(r'^[a-zA-Z0-9._-]+$', sequence_id):
            return False
        
        return True
    
    def clear_mapping(self):
        """清空当前ID映射"""
        self.id_map.clear()
