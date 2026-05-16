"""
比对引擎基类
职责：定义统一的引擎抽象接口，提供共享的 WSL 路径转换工具。
所有比对引擎（MUMmer, Minimap2 等）均应继承此基类。
"""

import logging
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict


@dataclass
class AlignmentBlock:
    """单个比对片段的标准化表示"""
    ref_start: int
    ref_end: int
    query_start: int
    query_end: int
    ref_id: str = ""
    query_id: str = ""
    length: int = 0
    identity: float = 0.0
    strand: str = "+"


@dataclass
class AlignmentResult:
    """引擎输出的标准化结果模型"""
    engine: str = ""
    alignments: List[Dict[str, Any]] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    variants: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class BaseAlignmentEngine(ABC):
    """
    比对引擎基类
    提供统一的 WSL 路径转换、FASTA 预处理和 WSL 命令执行工具。
    """

    def __init__(self, wsl_distro: str = "Ubuntu"):
        self.wsl_distro = wsl_distro
        self.logger = logging.getLogger(self.__class__.__name__)

    # ── 核心抽象接口 ──────────────────────────────

    @abstractmethod
    async def run_alignment(
        self, ref_path: Path, query_path: Path, out_dir: Path, options: Optional[Dict[str, Any]] = None
    ) -> AlignmentResult:
        """
        执行比对分析
        :param ref_path: 参考序列路径
        :param query_path: 待测序列路径
        :param out_dir: 输出目录
        :param options: 引擎特定选项
        :return: 标准化比对结果
        """
        ...

    # ── WSL 路径工具 ──────────────────────────────

    @staticmethod
    def to_wsl_path(path: Path) -> str:
        """
        将 Windows 路径标准化转换为 WSL 路径。
        优先使用项目内置的 WSLManager，降级使用 /mnt 驱动器解析。
        """
        try:
            from src.assembly.env.wsl_manager import WSLManager
            linux_path = WSLManager.to_wsl_path(str(path.absolute()))
            if linux_path:
                return linux_path
        except Exception:
            pass

        # 降级方案：标准 /mnt 驱动器解析
        p_str = str(path.absolute()).replace('\\', '/')
        if ':' in p_str:
            drive, rest = p_str.split(':', 1)
            return f"/mnt/{drive.lower()}{rest}"
        return p_str

    # ── FASTA 预处理工具 ──────────────────────────

    @staticmethod
    def ensure_fasta(path: Path) -> Path:
        """
        确保文件为合规的 FASTA 格式（LF 换行、标准头部、末尾换行）。
        如果是 GBK 文件则进行转换。所有修复文件均输出到系统临时目录，防止污染源目录和权限异常。
        """
        import re
        import tempfile
        from Bio import SeqIO

        ext = path.suffix.lower()
        temp_dir = Path(tempfile.gettempdir())

        # GBK 转换
        if ext in ['.gbk', '.gb', '.gbff']:
            out_path = temp_dir / f"{path.stem}_converted.fasta"
            SeqIO.convert(str(path), "genbank", str(out_path), "fasta")
            # 转换后净化 Header（MUMmer postnuc 无法处理含空格的序列 ID）
            raw = out_path.read_text(encoding='utf-8', errors='ignore')
            sanitized = '\n'.join(
                '>' + re.sub(r'[^\w.>|-]', '_', line[1:]) if line.startswith('>') else line
                for line in raw.split('\n')
            )
            out_path.write_text(sanitized, encoding='utf-8', newline='\n')
            return out_path

        # FASTA 格式修复
        try:
            raw_content = path.read_text(encoding='utf-8', errors='ignore').strip()
            clean_seq = raw_content.replace('\r\n', '\n').replace('\r', '\n')

            if not clean_seq.startswith(">"):
                clean_seq = f">{path.stem}\n{clean_seq}\n"
            elif not clean_seq.endswith('\n'):
                clean_seq += '\n'

            # 净化 Header：将空格和特殊字符替换为下划线
            # MUMmer 的 postnuc 无法处理含空格的序列 ID
            sanitized_lines = []
            for line in clean_seq.split('\n'):
                if line.startswith('>'):
                    # 只保留第一个空格前的 ID 部分，或将整个 header 中的空格替换
                    sanitized = '>' + re.sub(r'[^\w.>|-]', '_', line[1:])
                    sanitized_lines.append(sanitized)
                else:
                    sanitized_lines.append(line)
            clean_seq = '\n'.join(sanitized_lines)

            out_path = temp_dir / f"{path.name}_fixed.fasta"
            out_path.write_text(clean_seq, encoding='utf-8', newline='\n')
            return out_path
        except Exception:
            return path

    # ── WSL 命令执行工具 ──────────────────────────

    def run_wsl_command(self, bash_script: str, timeout: int = 300) -> subprocess.CompletedProcess:
        """
        在 WSL 中执行 bash 脚本（原子操作模式）
        :param bash_script: bash 命令字符串
        :param timeout: 超时秒数
        :return: CompletedProcess 结果
        """
        full_cmd = [
            "wsl", "-d", self.wsl_distro, "-u", "root",
            "bash", "-c", bash_script
        ]
        return subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout
        )

    # ── 统计工具 ──────────────────────────────────

    @staticmethod
    def generate_summary(alignments: List[Dict[str, Any]]) -> Dict[str, Any]:
        """从比对列表生成统计摘要"""
        if not alignments:
            return {"total_matches": 0, "matched_length": 0, "average_identity": 0.0}

        total_len = 0
        identities = []
        for a in alignments:
            length_val = a.get('length')
            if length_val is None:
                length_val = a.get('len', 0)
            total_len += int(length_val) if length_val is not None else 0
            
            id_val = a.get('identity')
            if id_val is not None:
                f_id = float(id_val)
                if f_id > 0:
                    identities.append(f_id)

        avg_id = sum(identities) / len(identities) if identities else 0.0

        return {
            "total_matches": len(alignments),
            "matched_length": total_len,
            "average_identity": round(avg_id, 2)
        }
