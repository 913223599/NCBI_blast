import os
import io
import zipfile
import gzip
import logging
from pathlib import Path
from typing import Dict, Any, Generator, Optional, List
from Bio import SeqIO

logger = logging.getLogger(__name__)

class UniversalParser:
    """
    通用序列解析器 (Universal Sequence Parser)
    -----------------------------------------
    整合了对多种文件格式 (FASTA, ABI, ZIP, GZ) 的支持，
    并处理字符编码探测与流式读取。
    """
    
    VALID_EXTENSIONS = {'.fasta', '.fas', '.fa', '.fna', '.seq', '.txt', '.ab1', '.abi'}
    TEXT_ENCODINGS = ['utf-8', 'gbk', 'latin-1']
    
    @classmethod
    def parse_iter(cls, file_path: str) -> Generator[Dict[str, Any], None, None]:
        """
        通用解析入口：根据文件后缀自动选择解析策略。
        """
        p_path = Path(file_path)
        if not p_path.exists():
            logger.error(f"File not found: {file_path}")
            return

        ext = p_path.suffix.lower()
        
        try:
            if ext == '.zip':
                yield from cls._parse_zip(p_path)
            elif ext == '.gz':
                yield from cls._parse_gz(p_path)
            elif ext in ('.ab1', '.abi'):
                yield from cls._parse_abi(p_path)
            else:
                # 尝试作为普通文本序列文件解析
                yield from cls._parse_text_file(p_path)
        except Exception as e:
            logger.error(f"Universal parsing failed for {file_path}: {e}")

    @classmethod
    def _parse_zip(cls, file_path: Path) -> Generator[Dict[str, Any], None, None]:
        """解析 ZIP 压缩包中的所有有效序列文件"""
        try:
            with zipfile.ZipFile(file_path, 'r') as zf:
                for name in zf.namelist():
                    if name.endswith('/') or name.startswith('__MACOSX'):
                        continue
                        
                    f_ext = Path(name).suffix.lower()
                    if f_ext not in cls.VALID_EXTENSIONS:
                        continue
                        
                    with zf.open(name) as member:
                        if f_ext in ('.ab1', '.abi'):
                            yield from cls._parse_abi_stream(member, name)
                        else:
                            content = member.read()
                            text = cls._decode_binary(content)
                            if text:
                                yield from cls._parse_text_content(text, name)
        except Exception as e:
            logger.error(f"Error parsing ZIP {file_path}: {e}")

    @classmethod
    def _parse_gz(cls, file_path: Path) -> Generator[Dict[str, Any], None, None]:
        """解析 GZ 压缩的 FASTA 文件"""
        try:
            with gzip.open(file_path, 'rt', encoding='utf-8', errors='replace') as handle:
                yield from cls._parse_bio_record_iter(handle, "fasta", file_path.name)
        except Exception as e:
            logger.error(f"Error parsing GZ {file_path}: {e}")

    @classmethod
    def _parse_abi(cls, file_path: Path) -> Generator[Dict[str, Any], None, None]:
        """解析 ABI 二进制测序文件"""
        try:
            with open(file_path, 'rb') as handle:
                yield from cls._parse_abi_stream(handle, file_path.name)
        except Exception as e:
            logger.error(f"Error parsing ABI {file_path}: {e}")

    @classmethod
    def _parse_abi_stream(cls, stream, display_name: str) -> Generator[Dict[str, Any], None, None]:
        """处理 ABI 流数据"""
        try:
            for record in SeqIO.parse(stream, "abi"):
                yield cls._format_record(record, display_name)
        except Exception as e:
            logger.debug(f"ABI stream parse error in {display_name}: {e}")

    @classmethod
    def _parse_text_file(cls, file_path: Path) -> Generator[Dict[str, Any], None, None]:
        """尝试多种编码读取并解析文本文件内容"""
        text = None
        for enc in cls.TEXT_ENCODINGS:
            try:
                with open(file_path, 'r', encoding=enc) as f:
                    text = f.read()
                    break
            except:
                continue
        
        if text:
            yield from cls._parse_text_content(text, file_path.name)

    @classmethod
    def _parse_text_content(cls, text: str, display_name: str) -> Generator[Dict[str, Any], None, None]:
        """解析文本内容，自动识别 FASTA 或纯文本序列"""
        text_stream = io.StringIO(text)
        found_any = False
        
        # 1. 尝试作为 FASTA 解析
        try:
            for record in SeqIO.parse(text_stream, "fasta"):
                if record.seq:
                    found_any = True
                    yield cls._format_record(record, display_name)
        except:
            pass
            
        # 2. 如果 FASTA 没读到，尝试作为单条纯文本序列解析 (仅包含 A-Z)
        if not found_any:
            clean_seq = "".join(c for c in text if c.isalpha())
            if len(clean_seq) > 10:
                yield {
                    'id': Path(display_name).stem,
                    'description': f"{display_name} (PlainText)",
                    'sequence': clean_seq,
                    'length': len(clean_seq)
                }

    @classmethod
    def _parse_bio_record_iter(cls, handle, format: str, display_name: str) -> Generator[Dict[str, Any], None, None]:
        """通用的 BioPython 记录转换器"""
        try:
            for record in SeqIO.parse(handle, format):
                yield cls._format_record(record, display_name)
        except Exception as e:
            logger.debug(f"Bio record parse error in {display_name}: {e}")

    @classmethod
    def _format_record(cls, record, display_name: str) -> Dict[str, Any]:
        """格式化 BioPython Record 对象，支持 ID 智能提取逻辑"""
        stem = Path(display_name).stem.strip()
        rid = str(record.id).strip()
        
        # 智能 ID 拼接逻辑：如果 ID 已经包含文件名关键信息，则不再多余重复拼接
        m_low = stem.lower()
        r_low = rid.lower()
        
        if m_low in r_low or r_low in m_low:
            fid = rid if len(rid) >= len(stem) else stem
        else:
            fid = f"{stem}::{rid}"
            
        return {
            'id': fid,
            'description': f"{display_name} - {record.description}",
            'sequence': str(record.seq),
            'length': len(record.seq)
        }

    @classmethod
    def _decode_binary(cls, content: bytes) -> Optional[str]:
        """自动探测二进制数据的文本编码"""
        for enc in cls.TEXT_ENCODINGS:
            try:
                return content.decode(enc)
            except:
                continue
        return content.decode('utf-8', errors='replace')
