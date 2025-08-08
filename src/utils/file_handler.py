"""
文件处理工具模块
负责序列文件的读取和结果文件的保存
"""

import os
from pathlib import Path


class FileHandler:
    """
    文件处理工具类
    负责处理序列文件的读取和结果文件的保存
    """
    
    def __init__(self):
        """
        初始化文件处理器
        """
        pass
    
    def read_sequence_file(self, file_path):
        """
        读取序列文件
        
        Args:
            file_path (str): 序列文件路径
            
        Returns:
            str: 序列内容
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                # 读取文件内容并去除空白字符
                sequence = f.read().strip()
                # 如果是FASTA格式，跳过第一行（描述行）
                if sequence.startswith('>'):
                    lines = sequence.split('\n')
                    sequence = ''.join(lines[1:]).strip()
            return sequence
        except Exception as e:
            raise RuntimeError(f"读取序列文件失败 {file_path}: {e}")
    
    def save_result_file(self, result_handle, output_file):
        """
        保存结果到文件
        
        Args:
            result_handle: BLAST结果句柄
            output_file (str): 输出文件路径
        """
        try:
            # 创建结果目录（如果不存在）
            Path(output_file).parent.mkdir(parents=True, exist_ok=True)
            
            # 保存结果到文件
            with open(output_file, "w", encoding='utf-8') as out_handle:
                out_handle.write(result_handle.read())
        except Exception as e:
            raise RuntimeError(f"保存结果文件失败 {output_file}: {e}")
    
    def validate_file_exists(self, file_path):
        """
        验证文件是否存在
        
        Args:
            file_path (str): 文件路径
            
        Returns:
            bool: 文件是否存在
        """
        return os.path.exists(file_path)
    
    def get_file_list(self, directory, extension=None):
        """
        获取目录中的文件列表
        
        Args:
            directory (str): 目录路径
            extension (str): 文件扩展名过滤器，如 ".seq"
            
        Returns:
            list: 文件列表
        """
        try:
            files = os.listdir(directory)
            if extension:
                files = [f for f in files if f.endswith(extension)]
            return files
        except Exception as e:
            print(f"获取文件列表时出错: {e}")
            raise e