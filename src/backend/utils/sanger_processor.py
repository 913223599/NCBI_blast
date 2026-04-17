import os
import logging
from Bio import SeqIO
from typing import Dict, Any, Optional

logger = logging.getLogger("api_server")

class SangerProcessor:
    """
    Sanger 测序数据 (AB1/ABI) 处理类
    专门用于处理 16S/18S 的单端或双端一代测序数据
    """
    
    @staticmethod
    def process_ab1(file_path: str, output_dir: str, trim_threshold: int = 20) -> Dict[str, Any]:
        """
        解析 AB1 峰图文件，进行质量裁剪并导出 FASTA
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
            
        filename = os.path.basename(file_path)
        base_name = os.path.splitext(filename)[0]
        fasta_out = os.path.join(output_dir, f"{base_name}.fasta")
        
        try:
            # 1. 解析 AB1
            record = SeqIO.read(file_path, "abi")
            
            # 2. 质量裁剪 (简化的阈值裁剪)
            qualities = record.letter_annotations.get("phred_quality", [])
            
            # 寻找序列中间的高质量区域
            start, end = 0, len(qualities)
            for i, q in enumerate(qualities):
                if q >= trim_threshold:
                    start = i
                    break
            for i, q in enumerate(reversed(qualities)):
                if q >= trim_threshold:
                    end = len(qualities) - i
                    break
            
            trimmed_record = record[start:end]
            
            # 3. 导出 FASTA
            SeqIO.write(trimmed_record, fasta_out, "fasta")
            
            logger.info(f"✅ [Sanger] 处理完成: {filename} -> {len(trimmed_record)} bp (裁掉 {start} bp 头, {len(qualities)-end} bp 尾)")
            
            return {
                "success": True,
                "seq_id": record.id,
                "original_len": len(record),
                "trimmed_len": len(trimmed_record),
                "fasta_path": fasta_out,
                "avg_quality": sum(qualities) / len(qualities) if qualities else 0
            }
            
        except Exception as e:
            logger.error(f"❌ [Sanger] 处理失败 {filename}: {e}")
            raise e
