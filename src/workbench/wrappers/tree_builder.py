"""
TreeBuilder - 负责执行具体的进化树构建算法

修复历史：
- 序列填充逻辑：统一使用 SequenceProcessor.pad_sequences()
- 临时文件管理：使用 TemporaryDirectory 确保清理
- 错误恢复机制：记录原始错误原因并传播到降级日志
- 类型注解：补充所有公共方法的返回类型声明
"""
import io
import logging
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from src.workbench.wrappers.base_wrapper import BaseWrapper

logger = logging.getLogger(__name__)


class TreeBuilder(BaseWrapper):
    """负责执行具体的进化树构建算法"""

    def _validate_distance_matrix(self, matrix: list) -> bool:
        """
        验证距离矩阵是否有效（非平坦、非空）

        Args:
            matrix: 距离矩阵（二维列表）

        Returns:
            True if valid, False otherwise
        """
        if not matrix:
            return False

        matrix_is_flat = True
        flat_val: Optional[float] = None
        for row_idx in range(len(matrix)):
            for col_idx in range(row_idx):
                val = matrix[row_idx][col_idx]
                if flat_val is None:
                    flat_val = val
                elif abs(val - flat_val) > 1e-12:
                    matrix_is_flat = False
                    break
            if not matrix_is_flat:
                break

        return not matrix_is_flat

    def _recover_and_build_nj_from_fasta(
        self,
        input_fasta: Path,
        output_nwk: Path,
        original_error: Optional[str] = None,
    ) -> bool:
        """
        从FASTA文件恢复并构建NJ树（降级方案）

        Args:
            input_fasta: FASTA文件路径
            output_nwk: 输出Newick文件路径
            original_error: 原始触发降级的错误信息（Issue #9：日志追踪）

        Returns:
            True if successful, False otherwise
        """
        if original_error:
            self.logger.warning(
                f"NJ recovery triggered. Original error: {original_error}"
            )

        try:
            from Bio import SeqIO, Phylo
            from Bio.Align import MultipleSeqAlignment
            from Bio.SeqRecord import SeqRecord
            from Bio.Seq import Seq
            from Bio.Phylo.TreeConstruction import (
                DistanceCalculator as BiopythonDC,
                DistanceTreeConstructor,
            )

            # 使用统一的序列填充方法（Issue #8/#14）
            from src.workbench.wrappers.tree_sequence_processor import SequenceProcessor

            effective_fasta, was_padded = SequenceProcessor.pad_sequences(input_fasta)
            if was_padded:
                self.logger.info("Recovery path: sequences padded for alignment.")

            padded_records = list(SeqIO.parse(effective_fasta, "fasta"))
            alignment = MultipleSeqAlignment(padded_records)
            calculator = BiopythonDC("identity")  # p-distance for robustness
            distance_matrix = calculator.get_distance(alignment)

            constructor = DistanceTreeConstructor()
            tree = constructor.nj(distance_matrix)

            # 规范化清理
            for node in tree.find_clades():
                if not node.is_terminal():
                    node.name = None

            out_str = io.StringIO()
            Phylo.write(tree, out_str, "newick")
            nwk = out_str.getvalue().strip().replace("\r\n", "\n")
            nwk = re.sub(r":-?\d+\.\d+;$", ";", nwk)
            output_nwk.write_text(nwk, encoding="utf-8")
            self.logger.info(
                f"NJ Tree successfully RECOVERED via direct MSA analysis: {output_nwk}"
            )
            return True

        except Exception as exc:
            self.logger.error(f"High-precision NJ recovery failed: {exc}")
            return False
        finally:
            # 清理临时填充文件
            if was_padded and effective_fasta != input_fasta and effective_fasta.exists():
                try:
                    effective_fasta.unlink()
                except OSError:
                    pass

    def build_tree_nj(
        self,
        input_dm: Optional[Path],
        output_nwk: Path,
        input_fasta: Optional[Path] = None,
    ) -> bool:
        """
        Neighbor-Joining Tree Construction.

        Args:
            input_dm: 距离矩阵文件路径
            output_nwk: 输出Newick文件路径
            input_fasta: 原始FASTA文件（用于降级恢复）

        Returns:
            True if successful, False otherwise
        """
        from src.workbench.wrappers.tree_distance_calculator import DistanceCalculator

        calc = DistanceCalculator()

        content = ""
        if input_dm and input_dm.exists():
            content = input_dm.read_text(encoding="utf-8", errors="replace")

        name_list, matrix = calc._parse_dm_content(content)

        # 验证矩阵质量
        if not self._validate_distance_matrix(matrix):
            # Issue #9：记录原始失败原因
            error_reason = (
                "Distance matrix is flat/invalid"
                if matrix
                else "Distance matrix is empty"
            )
            if input_dm:
                error_reason += f" (source: {input_dm.name})"

            # 矩阵失效，尝试从FASTA恢复
            if input_fasta and input_fasta.exists():
                self.logger.warning(
                    f"Detected invalid distance matrix: {error_reason}. "
                    f"Starting recovery from FASTA..."
                )
                return self._recover_and_build_nj_from_fasta(
                    input_fasta, output_nwk, original_error=error_reason
                )
            else:
                self.logger.error(
                    f"Invalid distance matrix and no FASTA fallback available. "
                    f"Reason: {error_reason}"
                )
                return False

        # 正常流程：基于读入的矩阵构建
        try:
            from Bio.Phylo.TreeConstruction import DistanceTreeConstructor, DistanceMatrix
            from Bio import Phylo

            if not name_list or not matrix:
                return False

            distance_matrix = DistanceMatrix(name_list, matrix)
            constructor = DistanceTreeConstructor()
            tree = constructor.nj(distance_matrix)

            for node in tree.find_clades():
                if not node.is_terminal():
                    node.name = None

            out_str = io.StringIO()
            Phylo.write(tree, out_str, "newick")
            nwk = out_str.getvalue().strip().replace("\r\n", "\n")
            nwk = re.sub(r":-?\d+\.\d+;$", ";", nwk)
            nwk = nwk.replace(" ;", ";")

            # 高精度解析还原：确保科学计数法和长 ID 的匹配性
            output_nwk.write_text(nwk, encoding="utf-8")
            self.logger.info(f"Tree built from matrix: {output_nwk}")
            return True

        except Exception as exc:
            self.logger.error(f"NJ builder failed: {exc}")
            return False

    def build_tree_ml(
        self,
        input_fasta: Path,
        output_nwk: Path,
        bootstrap: int = 1000,
        use_gpu: bool = False,
        threads: Optional[int] = None,
    ) -> bool:
        """
        Maximum Likelihood Inference via IQ-TREE 3 (CPU Optimized).

        Returns:
            True if successful, False otherwise
        """
        from src.workbench.wrappers.iqtree_wrapper import IQTreeWrapper

        iqtree = IQTreeWrapper()
        try:
            tree_file = iqtree.build_tree(
                input_fasta,
                output_nwk.parent,
                bootstrap=bootstrap,
                use_gpu=use_gpu,
                threads=threads,
            )
            # Normalize to output_nwk path
            shutil.copy2(tree_file, output_nwk)
            return True
        except Exception as exc:
            self.logger.error(f"ML Algorithm Failure: {exc}")
            return False

    def build_tree_bayesian(
        self,
        input_fasta: Path,
        output_nwk: Path,
        ngen: int = 10000,
        use_gpu: bool = False,
    ) -> bool:
        """
        Bayesian Inference via MrBayes.

        Returns:
            True if successful, False otherwise
        """
        from src.workbench.wrappers.mrbayes_wrapper import MrBayesWrapper

        mb_wrapper = MrBayesWrapper()
        try:
            nex_file = output_nwk.with_suffix(".nex")
            mb_wrapper.prepare_nexus_from_fasta(input_fasta, nex_file, ngen=ngen, use_gpu=use_gpu)
            con_tree = mb_wrapper.build_tree(nex_file, ngen=ngen, use_gpu=use_gpu)

            # Map MrBayes .con.tre to .tree or .nwk
            shutil.copy2(con_tree, output_nwk)
            return True
        except Exception as exc:
            self.logger.error(f"Bayesian Algorithm Failure: {exc}")
            return False

    def exec_fast_tree(
        self,
        input_fasta: Path,
        output_nwk: Path,
        params: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Invoke FastTree for Maximum Likelihood approximation directly from MSA.

        Returns:
            True if successful, False otherwise
        """
        # 使用统一的序列填充方法（Issue #8/#14）
        from src.workbench.wrappers.tree_sequence_processor import SequenceProcessor

        temp_dir = None
        try:
            temp_dir = tempfile.TemporaryDirectory(prefix="fasttree_pad_")
            padded_output = Path(temp_dir.name) / f"padded_{input_fasta.name}"
            effective_input, was_padded = SequenceProcessor.pad_sequences(
                input_fasta, padded_output
            )

            if was_padded:
                self.logger.info("FastTree: sequences padded for alignment consistency.")

            args = ["-quiet"]
            param_dict = params or {}

            # DNA or Protein logic
            model = param_dict.get("model", "jc").lower()
            if param_dict.get("seq_type") == "protein":
                if model == "wag":
                    args.append("-wag")
            else:
                args.append("-nt")
                if model == "gtr":
                    args.append("-gtr")

            args.extend(["-quote", str(effective_input)])

            result = self._run_command("FastTree.exe", args)

            if result and result.stdout:
                output_nwk.write_text(result.stdout.strip(), encoding="utf-8")
                return True
            return False

        except Exception as exc:
            self.logger.error(f"FastTree analysis failed: {exc}")
            return False

        finally:
            # Issue #2：确保临时文件清理
            if temp_dir is not None:
                try:
                    temp_dir.cleanup()
                except OSError as cleanup_err:
                    self.logger.warning(f"FastTree temp cleanup failed: {cleanup_err}")
