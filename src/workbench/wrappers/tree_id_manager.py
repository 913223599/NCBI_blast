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
    
    def __init__(self) -> None:
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
        id_map: Dict[str, str] = {}
        safe_records = []
        
        try:
            records = list(SeqIO.parse(input_fasta, "fasta"))
            for idx, rec in enumerate(records):
                short_id = f"S{idx:05d}"
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
            
        except Exception as exc:
            # 清理可能生成的临时文件
            if sanitized_fasta.exists():
                sanitized_fasta.unlink()
            raise RuntimeError(f"Failed to sanitize FASTA IDs: {exc}") from exc
    
    @staticmethod
    def restore_ids_in_newick(newick_content: str, id_map: Dict[str, str]) -> str:
        """
        在Newick字符串中精确还原原始ID（使用正则词边界匹配）

        通过正则表达式在 Newick 分隔符（圆括号、逗号、冒号、分号）
        之间匹配完整标识符，避免 S0001 误替换 S00011 的问题。

        Args:
            newick_content: 包含短ID的Newick字符串
            id_map: ID映射表 {short_id: original_id}
            
        Returns:
            还原后的Newick字符串
        """
        if not id_map:
            return newick_content
        
        # 构建用于Newick格式的精确替换正则：
        # Newick 中节点名称出现在 (, ), , : ; 之间
        # 使用捕获组确保只匹配完整的标识符
        
        # 按 key 长度降序排列，防止短 key 意外匹配长 key 的前缀
        sorted_keys = sorted(id_map.keys(), key=len, reverse=True)
        
        # 构建单一正则：匹配 Newick 分隔符之间的完整标识符
        # 使用零宽断言匹配 Newick 分隔符边界
        newick_delimiters = r'(?<=[\(\),;:]|^)'
        newick_following = r'(?=[\(\),;:]|$|:)'
        
        escaped_keys = [re.escape(key) for key in sorted_keys]
        pattern = newick_delimiters + r'(' + '|'.join(escaped_keys) + r')' + newick_following
        
        def _replacer(match: re.Match) -> str:
            matched_id = match.group(1)
            original_id = id_map[matched_id]
            # 如果原始 ID 包含 Newick 特殊字符，用单引号包裹
            if re.search(r"[():,;\[\]'\s]", original_id):
                return f"'{original_id}'"
            return original_id
        
        restored = re.sub(pattern, _replacer, newick_content)
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
        max_safe_id_length = 100
        if len(sequence_id) > max_safe_id_length:
            return False
        
        # 只允许字母、数字、下划线、连字符、点号
        if not re.match(r'^[a-zA-Z0-9._-]+$', sequence_id):
            return False
        
        return True
    
    def clear_mapping(self) -> None:
        """清空当前ID映射"""
        self.id_map.clear()
