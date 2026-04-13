"""
文件处理工具模块
负责序列文件的读取和结果文件的保存 (基于通用解析模块)
"""

import logging
import os
import warnings
import shutil
from pathlib import Path
from typing import List, Dict, Any, Generator

from .universal_parser import UniversalParser

# 忽略 Biopython 生命周期警告
try:
    from Bio import BiopythonDeprecationWarning
    warnings.simplefilter('ignore', BiopythonDeprecationWarning)
except ImportError:
    pass

logger = logging.getLogger(__name__)

class FileHandler:
    """
    文件处理工具类
    本类作为 Facade 接口，具体解析逻辑托管给 UniversalParser
    """
    
    def __init__(self):
        """初始化文件处理器，实例化通用解析器"""
        self.parser = UniversalParser()
    
    def read_sequence_file(self, file_path: str) -> str:
        """
        读取序列文件并返回找到的首条序列内容。
        """
        try:
            for seq_info in self.parser.parse_iter(file_path):
                return seq_info.get('sequence', '')
        except Exception as e:
            logger.debug(f"Read first sequence error: {e}")
        return ""
    
    def read_fasta_file(self, file_path: str) -> List[Dict[str, Any]]:
        """
        同步读取所有序列信息（一次性加载到内存）。
        """
        return list(self.read_fasta_file_iter(file_path))

    def read_fasta_file_iter(self, file_path: str) -> Generator[Dict[str, Any], None, None]:
        """
        迭代读取序列文件，支持 FASTA, ABI, ZIP, GZ 等格式。
        """
        yield from self.parser.parse_iter(file_path)

    def save_result_file(self, result_handle, output_file: str):
        """
        将结果句柄内容保存到物理文件。
        """
        try:
            target_path = Path(output_file)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_file, "w", encoding='utf-8') as out_handle:
                if hasattr(result_handle, 'seek'):
                    try:
                        result_handle.seek(0)
                    except:
                        pass
                shutil.copyfileobj(result_handle, out_handle)
        except Exception as e:
            raise RuntimeError(f"Failed to save result file to {output_file}: {e}")
    
    def validate_file_exists(self, file_path: str) -> bool:
        """检查物理文件是否存在"""
        return os.path.exists(file_path)
    
    def get_file_list(self, directory: str, extension: str = None) -> List[str]:
        """获取目录下的文件列表，可选后缀过滤"""
        try:
            if not os.path.exists(directory):
                return []
            files = os.listdir(directory)
            if extension:
                files = [f for f in files if f.endswith(extension)]
            return files
        except Exception as e:
            logger.error(f"Error list directory {directory}: {e}")
            raise
