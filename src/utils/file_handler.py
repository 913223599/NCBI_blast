"""
文件处理工具模块
负责序列文件的读取和结果文件的保存
"""

import os
from pathlib import Path

from Bio import SeqIO


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
        读取序列文件（兼容旧方法，返回第一个序列）
        
        Args:
            file_path (str): 序列文件路径
            
        Returns:
            str: 序列内容
        """
        sequences = self.read_fasta_file(file_path)
        if sequences:
            return sequences[0]['sequence']  # 返回第一个序列
        
        # 如果FASTA解析失败，尝试作为纯文本序列文件读取
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                # 移除可能的换行符、空格等
                sequence = content.replace('\n', '').replace(' ', '').replace('\r', '').strip()
                return sequence
        except Exception:
            return ""
    
    def read_fasta_file(self, file_path):
        """
        读取FASTA文件，返回所有序列信息
        
        Args:
            file_path (str): FASTA文件路径
            
        Returns:
            list: 包含序列信息的字典列表，每个字典包含'id', 'description', 'sequence'键
        """
        sequences = []
        try:
            # 尝试直接使用BioPython解析
            # BioPython通常能很好地处理FASTA格式
            with open(file_path, 'r', encoding='utf-8') as handle:
                # 使用 'fasta' 而不是 'fasta-pearson'，后者是旧格式
                for record in SeqIO.parse(handle, "fasta"):
                    seq_info = {
                        'id': str(record.id),
                        'description': str(record.description),
                        'sequence': str(record.seq),
                        'length': len(record.seq)
                    }
                    sequences.append(seq_info)
        except Exception as e:
            print(f"BioPython解析失败: {e}")
        
        # 如果BioPython没解析出东西，尝试手动解析（容错模式）
        if not sequences:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # 查找第一个 '>'
                    start_idx = content.find('>')
                    if start_idx != -1:
                        content = content[start_idx:] # 跳过前面的垃圾内容
                        entries = content.split('>')
                        for entry in entries:
                            if entry.strip():
                                lines = entry.strip().split('\n', 1)
                                if len(lines) > 0:
                                    header = lines[0].strip()
                                    sequence = ''.join(lines[1:]).replace('\n', '').replace(' ', '').strip() if len(lines) > 1 else ""
                                    if sequence: # 只添加有序列的
                                        seq_info = {
                                            'id': header.split()[0] if header else "unknown",
                                            'description': header,
                                            'sequence': sequence,
                                            'length': len(sequence)
                                        }
                                        sequences.append(seq_info)
            except Exception as e2:
                print(f"手动解析失败: {e2}")

        # 如果还是没有，尝试作为单序列处理 (兜底)
        if not sequences:
             try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    # 只有当内容不为空且不包含 '>' 时才作为纯序列处理
                    # 如果包含 '>' 但前面解析失败，说明格式有问题，不应作为纯序列
                    if content and '>' not in content:
                         seq_info = {
                            'id': Path(file_path).stem,
                            'description': f"Sequence from {Path(file_path).name}",
                            'sequence': content.replace('\n', '').replace(' ', ''),
                            'length': len(content)
                        }
                         sequences.append(seq_info)
             except:
                 pass

        return sequences
    
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