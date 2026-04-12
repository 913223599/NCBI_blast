"""
SequenceProcessor - 负责序列的预处理和质量控制

统一了散布在 iqtree_wrapper / tree_builder / analysis_pipeline 三处的
序列填充（padding）逻辑，提供 pad_sequences() 公共方法。
"""
import logging
import tempfile
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from src.workbench.wrappers.base_wrapper import BaseWrapper

logger = logging.getLogger(__name__)


class SequenceProcessor(BaseWrapper):
    """负责序列的预处理和质量控制"""

    # ─── 序列填充 (Padding) ─────────────────────────
    @staticmethod
    def pad_sequences(
        input_fasta: Path,
        output_fasta: Optional[Path] = None,
    ) -> Tuple[Path, bool]:
        """
        检查 FASTA 文件中的序列长度是否一致。
        若不一致，在尾部补充 '-' 使其长度一致。

        Args:
            input_fasta: 输入 FASTA 文件路径
            output_fasta: 可选的输出路径；为 None 时创建临时文件

        Returns:
            (实际使用的文件路径, 是否执行了填充)
            如果未执行填充，返回的路径即为 input_fasta 本身
        """
        from Bio import SeqIO
        from Bio.Seq import Seq
        from Bio.SeqRecord import SeqRecord

        records = list(SeqIO.parse(input_fasta, "fasta"))
        if not records:
            raise ValueError(f"Empty FASTA file: {input_fasta}")

        max_length = max(len(record.seq) for record in records)
        needs_padding = any(len(record.seq) != max_length for record in records)

        if not needs_padding:
            return input_fasta, False

        logger.warning(
            f"Detected inconsistent sequence lengths in {input_fasta.name}. "
            f"Padding to {max_length}bp..."
        )

        padded_records: List[SeqRecord] = []
        for record in records:
            if len(record.seq) < max_length:
                new_seq = str(record.seq).ljust(max_length, "-")
                padded_records.append(
                    SeqRecord(Seq(new_seq), id=record.id, description="")
                )
            else:
                padded_records.append(record)

        if output_fasta is None:
            output_fasta = Path(tempfile.gettempdir()) / f"padded_{input_fasta.name}"

        SeqIO.write(padded_records, output_fasta, "fasta")
        return output_fasta, True

    # ─── QC (Quality Control) ──────────────────────
    def qc_stats(self, input_fasta: Path) -> Dict[str, Any]:
        """执行 QC 统计"""
        results: Dict[str, Any] = {}
        try:
            gc_result = self._run_command("fasta2GC.exe", [str(input_fasta)])
            results["gc"] = gc_result.stdout.strip()
            comp_result = self.dna_complexity(input_fasta)
            results["complexity"] = comp_result.stdout.strip()
        except Exception as exc:
            logger.error(f"QC stats failed: {exc}")
        return results

    def dna_complexity(self, input_fasta: Path, output_json: Optional[Path] = None):
        """计算 DNA 复杂度"""
        args = [str(input_fasta)]
        if output_json:
            args.extend(["-json", str(output_json)])
        return self._run_command("dna_complexity.exe", args)

    def prot_complexity(self, input_fasta: Path, output_json: Optional[Path] = None):
        """计算蛋白质复杂度"""
        args = [str(input_fasta)]
        if output_json:
            args.extend(["-json", str(output_json)])
        return self._run_command("prot_complexity.exe", args)

    def uniq_sequences(self, input_fasta: Path, output_fasta: Path):
        """去重序列"""
        result = self._run_command("uniqSeq.exe", [str(input_fasta)])
        output_fasta.write_text(result.stdout, encoding="utf-8")
        return result

    def dna2prots(
        self, input_fasta: Path, output_file: Optional[Path] = None, min_len: int = 30
    ):
        """DNA 翻译为蛋白质"""
        result = self._run_command(
            "dna2prots.exe", [str(input_fasta), "1", str(min_len)]
        )
        if output_file:
            output_file.write_text(result.stdout, encoding="utf-8")
        return result
