"""
文件处理工具模块
负责序列文件的读取和结果文件的保存
"""

import logging
import os
import warnings
from pathlib import Path
from typing import List, Dict, Any, Generator

from Bio import SeqIO, BiopythonDeprecationWarning

# 忽略 Biopython 关于 FASTA 注释的弃用警告
warnings.simplefilter('ignore', BiopythonDeprecationWarning)

logger = logging.getLogger(__name__)

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
        except Exception as e:
            logger.debug(f"尝试作为 FASTA 读取失败: {e}")
            pass
        
        # 如果FASTA解析失败，尝试作为纯文本序列文件读取
        # 依次尝试 UTF-8 和 GBK
        for encoding in ['utf-8', 'gbk']:
            try:
                with open(file_path, 'r', encoding=encoding, errors='replace') as f:
                    content = f.read().strip()
                    # 移除可能的换行符、空格等，仅保留碱基/氨基酸符号
                    sequence = "".join(content.split())
                    if sequence:
                        return sequence
            except Exception as e:
                logger.debug(f"尝试以 {encoding} 读取纯文本失败: {e}")
                continue
                
        logger.error(f"无法从文件读取任何有效序列: {file_path}")
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
        迭代读取序列文件，支持 FASTA、ABI (.ab1)、ZIP 压缩包及 GZ 压缩文件。
        具备多编码自动探测功能。
        """
        import zipfile
        import gzip
        import io
        from Bio import SeqIO
        
        found_any = False
        p_path = Path(file_path)
        ext = p_path.suffix.lower()
        
        # 1. 递归处理 ZIP 压缩包
        if ext == '.zip':
            try:
                with zipfile.ZipFile(file_path, 'r') as zf:
                    all_names = [n for n in zf.namelist() if not n.endswith('/')] # 排除目录
                    valid_exts = ['.fasta', '.fas', '.fa', '.seq', '.txt', '.fna', '.ab1', '.abi']
                    
                    for name in all_names:
                        f_ext = Path(name).suffix.lower()
                        if f_ext in valid_exts:
                            with zf.open(name) as member:
                                if f_ext in ['.ab1', '.abi']:
                                    try:
                                        for record in SeqIO.parse(member, "abi"):
                                            # 优化 ID 拼接：如果文件名和 ID 相似（忽略大小写和空格），则不重复拼接
                                            m_stem = Path(name).stem.strip()
                                            rid = str(record.id).strip()
                                            
                                            m_low = m_stem.lower()
                                            r_low = rid.lower()
                                            
                                            if m_low in r_low or r_low in m_low:
                                                fid = rid if len(rid) >= len(m_stem) else m_stem
                                            else:
                                                fid = f"{m_stem}::{rid}"
                                            found_any = True
                                            yield {
                                                'id': fid,
                                                'description': f"{name} - {record.description}",
                                                'sequence': str(record.seq),
                                                'length': len(record.seq)
                                            }
                                    except: pass
                                else:
                                    # 处理 ZIP 内部文本文件
                                    try:
                                        content = member.read()
                                        text = None
                                        # 尝试常见编码
                                        for enc in ['utf-8', 'gbk']:
                                            try:
                                                text = content.decode(enc)
                                                break
                                            except: continue
                                        if text is None: text = content.decode('utf-8', errors='replace')
                                        
                                        # 此时 text 是文件内容，尝试解析
                                        this_file_found = False
                                        # (a) 尝试 BioPython FASTA
                                        text_stream = io.StringIO(text)
                                        for record in SeqIO.parse(text_stream, "fasta"):
                                            if not record.seq: continue
                                            # 优化 ID 拼接
                                            m_stem = Path(name).stem.strip()
                                            rid = str(record.id).split()[0] if ' ' in str(record.id) else str(record.id)
                                            rid = rid.strip()
                                            
                                            m_low = m_stem.lower()
                                            r_low = rid.lower()
                                            
                                            if m_low in r_low or r_low in m_low:
                                                fid = rid if len(rid) >= len(m_stem) else m_stem
                                            else:
                                                fid = f"{m_stem}::{rid}"
                                            found_any = True
                                            this_file_found = True
                                            yield {
                                                'id': fid,
                                                'description': f"{name} - {record.description}",
                                                'sequence': str(record.seq),
                                                'length': len(record.seq)
                                            }
                                        
                                        # (b) 如果不是 FASTA，尝试作为手动单序列解析
                                        if not this_file_found:
                                            # 去除空白和换行
                                            clean_seq = "".join(c for c in text if c.isalnum())
                                            if len(clean_seq) > 10:
                                                found_any = True
                                                yield {
                                                    'id': Path(name).stem,
                                                    'description': f"{name} (Extracted text)",
                                                    'sequence': clean_seq,
                                                    'length': len(clean_seq)
                                                }
                                    except: pass
                # 对于 ZIP、GZ、ABI 等已知格式，如果解析完没找到序列，在此直接退出，防止回退到“读取压缩包二进制”
                return 
            except Exception as e:
                logger.error(f"ZIP 压缩包解析失败: {e}")
                return

        # 2. 处理 GZ 压缩文件
        if ext == '.gz':
            try:
                with gzip.open(file_path, 'rt', encoding='utf-8', errors='replace') as handle:
                    for record in SeqIO.parse(handle, "fasta"):
                        yield {
                            'id': str(record.id),
                            'description': str(record.description),
                            'sequence': str(record.seq),
                            'length': len(record.seq)
                        }
                        found_any = True
                return
            except Exception as e:
                logger.error(f"GZ 文件解析失败: {e}")
                return

        # 3. 针对 ABI 二进制格式的处理
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
                return
            except Exception as e:
                logger.error(f"ABI 解析失败: {e}")
                return

        # 4. 标准 FASTA 文件解析 (仅针对普通文本文件)
        for encoding in ['utf-8', 'gbk', 'latin-1']:
            try:
                with open(file_path, 'r', encoding=encoding) as handle:
                    handle.read(4096)
                    handle.seek(0)
                    this_pass_found = False
                    for record in SeqIO.parse(handle, "fasta"):
                        if not record.seq: continue
                        this_pass_found = True
                        found_any = True
                        yield {
                            'id': str(record.id),
                            'description': str(record.description),
                            'sequence': str(record.seq),
                            'length': len(record.seq)
                        }
                    if this_pass_found: return
            except: continue

        # 5. 手动流式解析 (仅针对普通文本文件)
        if not found_any:
            for encoding in ['utf-8', 'gbk']:
                try:
                    with open(file_path, 'r', encoding=encoding) as f:
                        header = None
                        sequence_parts = []
                        this_pass_found = False
                        for line in f:
                            line = line.strip()
                            if not line: continue
                            if line.startswith('>'):
                                if header and sequence_parts:
                                    seq_str = "".join(sequence_parts)
                                    if seq_str:
                                        this_pass_found = True
                                        found_any = True
                                        yield {
                                            'id': header.split()[0][1:] if header.startswith('>') else header.split()[0],
                                            'description': header[1:] if header.startswith('>') else header,
                                            'sequence': seq_str,
                                            'length': len(seq_str)
                                        }
                                header = line
                                sequence_parts = []
                            else:
                                sequence_parts.append("".join(line.split()))
                        
                        if header and sequence_parts:
                            seq_str = "".join(sequence_parts)
                            if seq_str:
                                this_pass_found = True
                                found_any = True
                                yield {
                                    'id': header.split()[0][1:] if header.startswith('>') else header.split()[0],
                                    'description': header[1:] if header.startswith('>') else header,
                                    'sequence': seq_str,
                                    'length': len(seq_str)
                                }
                        if this_pass_found: return
                except: continue

        # 6. 完全作为文本处理 (最后保底，但排除已知二进制后缀)
        if not found_any and ext not in ['.zip', '.gz', '.ab1', '.abi', '.exe', '.dll', '.bin']:
            for encoding in ['utf-8', 'gbk']:
                try:
                    with open(file_path, 'r', encoding=encoding, errors='replace') as f:
                        content = f.read().strip()
                        sequence = "".join(c for c in content if c.isalpha())
                        if len(sequence) > 10:
                            yield {
                                'id': p_path.stem,
                                'description': f"Extracted from {p_path.name}",
                                'sequence': sequence,
                                'length': len(sequence)
                            }
                            return
                except: continue

    def save_result_file(self, result_handle, output_file: str):
        """保存结果到文件"""
        try:
            Path(output_file).parent.mkdir(parents=True, exist_ok=True)
            with open(output_file, "w", encoding='utf-8') as out_handle:
                import shutil
                if hasattr(result_handle, 'seek'):
                    try: result_handle.seek(0)
                    except: pass
                shutil.copyfileobj(result_handle, out_handle)
        except Exception as e:
            raise RuntimeError(f"保存结果文件失败 {output_file}: {e}")
    
    def validate_file_exists(self, file_path: str) -> bool:
        return os.path.exists(file_path)
    
    def get_file_list(self, directory: str, extension: str = None) -> List[str]:
        try:
            files = os.listdir(directory)
            if extension:
                files = [f for f in files if f.endswith(extension)]
            return files
        except Exception as e:
            logger.error(f"获取文件列表时出错: {e}")
            raise
