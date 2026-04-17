"""
序列处理模块
负责序列读取、倍增、格式转换等基础操作
"""

import logging
from typing import Tuple, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class SequenceProcessor:
    """
    序列处理器
    职责：序列文件读取、序列倍增、序列格式处理
    """
    
    @staticmethod
    def read_fasta(file_path: str) -> Tuple[str, str, int]:
        """
        读取FASTA文件
        :param file_path: FASTA文件路径
        :return: (header, sequence, length)
        """
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                if not lines:
                    raise ValueError(f"空文件: {file_path}")
                
                header = lines[0].strip()
                sequence = "".join([line.strip() for line in lines[1:]])
                length = len(sequence)
                
                return header, sequence, length
                
        except FileNotFoundError:
            raise FileNotFoundError(f"序列文件不存在: {file_path}")
        except Exception as e:
            logger.error(f"读取序列失败: {e}")
            raise
    
    @staticmethod
    def double_sequence(header: str, sequence: str) -> str:
        """
        倍增序列（用于旋转检测）
        :param header: 序列头
        :param sequence: 原始序列
        :return: 倍增后的FASTA格式字符串
        """
        doubled_seq = sequence + sequence
        return f"{header} [DOUBLED]\n{doubled_seq}\n"
    
    @staticmethod
    def write_fasta(content: str, output_path: str) -> None:
        """
        写入FASTA文件
        :param content: FASTA格式内容
        :param output_path: 输出路径
        """
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)
    
    @staticmethod
    def prepare_doubled_fasta(input_path: str, output_path: str) -> int:
        """
        准备倍增序列文件
        :param input_path: 输入FASTA路径
        :param output_path: 输出倍增FASTA路径
        :return: 原始序列长度
        """
        header, sequence, length = SequenceProcessor.read_fasta(input_path)
        doubled_content = SequenceProcessor.double_sequence(header, sequence)
        SequenceProcessor.write_fasta(doubled_content, output_path)
        return length
