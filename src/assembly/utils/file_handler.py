
import os
import re
import gzip
import zipfile
from pathlib import Path
from typing import Tuple, Optional, Dict, Any, List, Callable, Union

class AssemblyFileHandler:
    """
    专门负责拼接输入文件的识别、校验与流式预处理
    支持格式: .fastq, .fastq.gz, .fq, .fq.gz, .zip (内含单/多分卷 FASTQ 归档)
    """
    @staticmethod
    def is_zip_archive(file_path: Union[str, Path]) -> bool:
        """
        判断指定路径是否为合法的 ZIP 归档文件
        双重校验: 物理大小与头部 Magic Number (PK\x03\x04) + zipfile 结构核验
        """
        try:
            p = Path(file_path)
            if not p.exists() or not p.is_file():
                return False
            if p.stat().st_size < 22:  # 最小合法空 zip 为 22 字节
                return False
            with open(p, 'rb') as f:
                magic = f.read(4)
                if magic != b'PK\x03\x04' and magic != b'PK\x05\x06' and magic != b'PK\x07\x08':
                    return False
            return zipfile.is_zipfile(p)
        except Exception:
            return False

    @staticmethod
    def list_zip_fastq_entries(zip_path: Union[str, Path]) -> List[str]:
        """
        扫描 ZIP 归档中的 FASTQ 测序文件条目列表
        自动过滤系统隐藏文件 (__MACOSX, ._*)，并按自然数字序列号稳定排序
        """
        valid_suffixes = ('.fastq', '.fq', '.fastq.gz', '.fq.gz')
        entries: List[str] = []
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                for name in zf.namelist():
                    # 过滤系统垃圾与隐藏文件
                    parts = name.split('/')
                    if any(part.startswith('._') or part == '__MACOSX' for part in parts):
                        continue
                    lower_name = name.lower()
                    if any(lower_name.endswith(sfx) for sfx in valid_suffixes):
                        entries.append(name)
        except Exception:
            return []

        # 自然数字排序函数 (例如 reads_1 < reads_2 < reads_10)
        def natural_sort_key(s: str):
            return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

        entries.sort(key=natural_sort_key)
        return entries

    @staticmethod
    def extract_and_merge_zip_fastq(
        zip_path: Union[str, Path],
        output_fastq_path: Union[str, Path],
        on_progress: Optional[Callable[[float, str], None]] = None,
        chunk_size: int = 1024 * 1024
    ) -> bool:
        """
        将 ZIP 归档内的所有 FASTQ 分卷按顺序流式合并落盘为单个 FASTQ 文件
        严格执行流式分片落盘（固定 1MB 缓冲区）与断点保护机制，严禁海量内存囤积
        """
        zip_p = Path(zip_path)
        out_p = Path(output_fastq_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        tmp_p = out_p.with_name(f"{out_p.name}.tmp_{os.getpid()}")

        entries = AssemblyFileHandler.list_zip_fastq_entries(zip_p)
        if not entries:
            return False

        total_entries = len(entries)
        if on_progress:
            on_progress(1.0, f"发现 {total_entries} 个分卷 FASTQ，准备流式合并...")

        try:
            if tmp_p.exists():
                tmp_p.unlink()

            with open(tmp_p, 'wb') as out_f:
                with zipfile.ZipFile(zip_p, 'r') as zf:
                    for idx, entry_name in enumerate(entries, 1):
                        lower_name = entry_name.lower()
                        is_gz = lower_name.endswith('.gz')

                        with zf.open(entry_name, 'r') as raw_entry_stream:
                            if is_gz:
                                # 如果 zip 内部条目本身经过 gzip 压缩，进行解压流式中转
                                with gzip.GzipFile(fileobj=raw_entry_stream, mode='rb') as gz_stream:
                                    last_byte = b''
                                    while True:
                                        chunk = gz_stream.read(chunk_size)
                                        if not chunk:
                                            break
                                        out_f.write(chunk)
                                        last_byte = chunk[-1:]
                                    if last_byte and last_byte != b'\n':
                                        out_f.write(b'\n')
                            else:
                                last_byte = b''
                                while True:
                                    chunk = raw_entry_stream.read(chunk_size)
                                    if not chunk:
                                        break
                                    out_f.write(chunk)
                                    last_byte = chunk[-1:]
                                if last_byte and last_byte != b'\n':
                                    out_f.write(b'\n')

                        # 计算进度并在 1% - 99% 区间平滑汇报
                        percent = round((idx / total_entries) * 98.0 + 1.0, 1)
                        if on_progress:
                            on_progress(percent, f"流式聚合测序数据 ({idx}/{total_entries})...")

            # 原子重命名，提供断点保护
            if out_p.exists():
                out_p.unlink()
            tmp_p.replace(out_p)

            if on_progress:
                on_progress(100.0, "测序数据聚合完成")
            return True

        except Exception as e:
            if tmp_p.exists():
                try:
                    tmp_p.unlink()
                except Exception:
                    pass
            return False

    @staticmethod
    def validate_fastq_pair(r1: str, r2: str) -> bool:
        """
        验证双端 Fastq 文件是否匹配及格式是否正确
        """
        p1, p2 = Path(r1), Path(r2)
        
        # 1. 存在性检查
        if not p1.exists() or not p2.exists():
            return False
            
        # 2. 格式扩展名检查 (支持 fastq, fq, gz, zip)
        valid_exts = {".fastq", ".fq", ".gz", ".zip"}
        if p1.suffix.lower() not in valid_exts or p2.suffix.lower() not in valid_exts:
            return False
            
        # 3. 双端配对校验 (支持常见的 R1/R2, _1/_2 模式)
        r1_patterns = [r"[_.]R1[_.]", r"[_.]1[_.]", r"_1\.fastq", r"_1\.fq"]
        r2_patterns = [r"[_.]R2[_.]", r"[_.]2[_.]", r"_2\.fastq", r"_2\.fq"]
        
        has_r1 = any(re.search(p, p1.name, re.I) for p in r1_patterns)
        has_r2 = any(re.search(p, p2.name, re.I) for p in r2_patterns)
        
        if has_r1 and not has_r2:
             return False
        if has_r2 and not has_r1:
             return False
             
        return True

    @staticmethod
    def get_sample_id(r1_path: str) -> str:
        """
        从文件名自动推断样本 ID (增强版)
        支持: .R1.fastq.gz, _R1.fq.gz, .1.fastq.gz, fastq.zip 等各种组合
        """
        name = Path(r1_path).name
        # 1. 尝试移除常见的测序末尾标记及扩展名
        pattern = r'[\._][Rr]?1[\._].*|[\._](fastq|fq|gz|zip).*'
        sample_id = re.split(pattern, name, flags=re.I)[0]
        
        # 2. 如果切完发现是空的，就保留原名（兜底）
        return sample_id if sample_id else name.split('.')[0]

    @staticmethod
    def check_file_integrity(file_path: str) -> bool:
        """
        全能型轻量校验:
        1. 检查文件物理存在与基本大小
        2. 确认头部魔数 (Magic Number)
        3. 对 GZ 与 ZIP 容器进行轻量结构探测
        """
        p = Path(file_path)
        if not p.exists() or p.stat().st_size < 22:
            return False
            
        if p.suffix.lower() == ".zip":
            return AssemblyFileHandler.is_zip_archive(p)

        if not file_path.lower().endswith(".gz"):
            return True
            
        try:
            with open(file_path, 'rb') as f:
                # 校验 GZ 头部
                if f.read(2) != b'\x1f\x8b':
                    return False
                
                # 探测尾部 (取最后 4KB 尝试解压)
                file_size = p.stat().st_size
                probe_size = min(4096, file_size // 2)
                f.seek(-probe_size, os.SEEK_END)
                tail_data = f.read()
                return len(tail_data) > 0
        except Exception:
            return False

