"""
文件处理工具模块
负责序列文件的读取和结果文件的保存
"""

import os
import warnings
from pathlib import Path
from typing import Generator, Dict, Any, List, Union

from Bio import SeqIO, BiopythonDeprecationWarning

# 忽略 Biopython 关于 FASTA 注释的弃用警告
warnings.simplefilter('ignore', BiopythonDeprecationWarning)

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
    
    def read_sequence_file(self, file_path: str) -> str:
        """
        读取序列文件（兼容旧方法，返回第一个序列）
        
        Args:
            file_path (str): 序列文件路径
            
        Returns:
            str: 序列内容
        """
        # 尝试使用生成器读取第一个序列
        try:
            for seq_info in self.read_fasta_file_iter(file_path):
                return seq_info['sequence']
        except Exception:
            pass
        
        # 如果FASTA解析失败，尝试作为纯文本序列文件读取
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read(1024 * 1024) # 限制读取大小，防止内存溢出，虽然这里假设是单序列
                # 如果文件很大，read() 可能会有问题，但对于单序列文件通常不会太大
                # 如果确实很大，应该使用流式处理，但这里为了兼容性先这样
                # 更好的做法是分块读取并过滤
                
                # 重新打开读取全部（假设单序列文件不会大到撑爆内存，或者用户应该用FASTA格式）
                f.seek(0)
                content = f.read().strip()
                
                # 移除可能的换行符、空格等
                sequence = content.replace('\n', '').replace(' ', '').replace('\r', '').strip()
                return sequence
        except Exception:
            return ""
    
    def read_fasta_file(self, file_path: str) -> List[Dict[str, Any]]:
        """
        读取FASTA文件，返回所有序列信息（一次性加载到内存）
        注意：对于大文件，建议使用 read_fasta_file_iter
        
        Args:
            file_path (str): FASTA文件路径
            
        Returns:
            list: 包含序列信息的字典列表
        """
        return list(self.read_fasta_file_iter(file_path))

    def read_fasta_file_iter(self, file_path: str) -> Generator[Dict[str, Any], None, None]:
        """
        [优化] 迭代读取序列文件，支持 FASTA 和 ABI (.ab1) 格式。
        
        Args:
            file_path (str): 文件路径
            
        Yields:
            dict: 包含序列信息的字典
        """
        found_any = False
        ext = Path(file_path).suffix.lower()
        
        # 针对 ABI 二进制格式的处理
        if ext in ['.ab1', '.abi']:
            try:
                with open(file_path, 'rb') as handle:
                    for record in SeqIO.parse(handle, "abi"):
                        found_any = True
                        yield {
                            'id': str(record.id),
                            'description': str(record.description),
                            'sequence': str(record.seq),
                            'length': len(record.seq)
                        }
                if found_any: return
            except Exception as e:
                # logger.error(f"ABI 解析失败: {e}")
                pass

        try:
            # 尝试使用 BioPython 解析 FASTA
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as handle:
                for record in SeqIO.parse(handle, "fasta"):
                    found_any = True
                    yield {
                        'id': str(record.id),
                        'description': str(record.description),
                        'sequence': str(record.seq),
                        'length': len(record.seq)
                    }
        except Exception:
            pass
        
        # 如果BioPython成功解析出序列，直接返回
        if found_any:
            return
        
        # 如果BioPython没解析出东西，尝试手动流式解析（容错模式）
        # 这种方式比一次性 read() 更省内存
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                header = None
                sequence_parts = []
                
                for line in f:
                    line = line.strip()
                    if not line: continue
                    
                    if line.startswith('>'):
                        if header:
                            # Yield previous sequence
                            full_seq = "".join(sequence_parts)
                            if full_seq:
                                found_any = True
                                yield {
                                    'id': header.split()[0][1:] if header.startswith('>') else header.split()[0], # 去掉 >
                                    'description': header[1:] if header.startswith('>') else header,
                                    'sequence': full_seq,
                                    'length': len(full_seq)
                                }
                        header = line
                        sequence_parts = []
                    else:
                        sequence_parts.append(line)
                
                # Yield last sequence
                if header and sequence_parts:
                    full_seq = "".join(sequence_parts)
                    if full_seq:
                        found_any = True
                        yield {
                            'id': header.split()[0][1:] if header.startswith('>') else header.split()[0],
                            'description': header[1:] if header.startswith('>') else header,
                            'sequence': full_seq,
                            'length': len(full_seq)
                        }
        except Exception as e2:
            print(f"手动解析失败: {e2}")

        if found_any:
            return

        # 如果还是没有，尝试作为单序列处理 (兜底)
        # 注意：这里仍然需要读取内容，但对于非FASTA的大文件，这本身就是风险
        # 我们假设非FASTA文件通常是短序列
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                # 只读取前 1KB 检查是否有 '>'
                first_chunk = f.read(1024)
                if '>' not in first_chunk:
                    f.seek(0)
                    content = f.read().strip()
                    if content:
                         yield {
                            'id': Path(file_path).stem,
                            'description': f"Sequence from {Path(file_path).name}",
                            'sequence': content.replace('\n', '').replace(' ', ''),
                            'length': len(content)
                        }
        except:
            pass
    
    def save_result_file(self, result_handle, output_file: str):
        """
        保存结果到文件
        [优化] 使用流式写入，避免一次性读取整个结果到内存
        
        Args:
            result_handle: BLAST结果句柄 (file-like object)
            output_file (str): 输出文件路径
        """
        try:
            # 创建结果目录（如果不存在）
            Path(output_file).parent.mkdir(parents=True, exist_ok=True)
            
            # 保存结果到文件
            with open(output_file, "w", encoding='utf-8') as out_handle:
                # 使用 shutil.copyfileobj 进行流式复制
                import shutil
                # 如果 result_handle 是 StringIO 或类似对象，可能需要 seek(0)
                if hasattr(result_handle, 'seek'):
                    try:
                        result_handle.seek(0)
                    except:
                        pass
                shutil.copyfileobj(result_handle, out_handle)
                
        except Exception as e:
            raise RuntimeError(f"保存结果文件失败 {output_file}: {e}")
    
    def validate_file_exists(self, file_path: str) -> bool:
        """
        验证文件是否存在
        
        Args:
            file_path (str): 文件路径
            
        Returns:
            bool: 文件是否存在
        """
        return os.path.exists(file_path)
    
    def get_file_list(self, directory: str, extension: str = None) -> List[str]:
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
            raise
