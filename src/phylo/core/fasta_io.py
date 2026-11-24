# -*- coding: utf-8 -*-
"""
统一 UTF-8 FASTA 流式读取辅助工具。
规避 Windows 默认 cp936 (GBK) 下 Biopython SeqIO.parse(str(path), ...) 触发 UnicodeDecodeError 的隐患。
"""
from pathlib import Path
from typing import Iterator, List, Union

from Bio import SeqIO
from Bio.SeqRecord import SeqRecord


def iter_fasta_records(path: Union[Path, str]) -> Iterator[SeqRecord]:
    """显式以 UTF-8 编码流式解析 FASTA 记录，遇到异常字节时安全替换。"""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        yield from SeqIO.parse(fh, "fasta")


def read_fasta_records(path: Union[Path, str]) -> List[SeqRecord]:
    """显式以 UTF-8 编码读取 FASTA 文件的全部记录。"""
    return list(iter_fasta_records(path))
