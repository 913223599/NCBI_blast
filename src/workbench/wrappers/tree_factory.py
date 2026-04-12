"""
TreeFactory - 统一的进化树构建工厂（协调器）

职责：协调各个子模块，提供统一的对外接口。

修复历史：
- ID 映射还原：使用 IDManager.restore_ids_in_newick() 精确匹配
- 类型注解：补充 make_dist_tree 等方法的返回类型
"""
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base_wrapper import BaseWrapper
from .tree_builder import TreeBuilder
from .tree_distance_calculator import DistanceCalculator
from .tree_id_manager import IDManager
from .tree_sequence_processor import SequenceProcessor

logger = logging.getLogger(__name__)


class TreeFactory(BaseWrapper):
    """
    Unified Tree Construction Factory (Coordinator).
    职责：协调各个子模块，提供统一的对外接口。
    """

    def __init__(self) -> None:
        super().__init__()
        self.processor = SequenceProcessor()
        self.calculator = DistanceCalculator()
        self.builder = TreeBuilder()

    # --- Section: Sequence Preprocessing (Delegated) ---
    def qc_stats(self, input_fasta: Path) -> Dict[str, Any]:
        return self.processor.qc_stats(input_fasta)

    def dna_complexity(self, input_fasta: Path, output_json: Optional[Path] = None):
        return self.processor.dna_complexity(input_fasta, output_json)

    def prot_complexity(self, input_fasta: Path, output_json: Optional[Path] = None):
        return self.processor.prot_complexity(input_fasta, output_json)

    def uniq_sequences(self, input_fasta: Path, output_fasta: Path):
        return self.processor.uniq_sequences(input_fasta, output_fasta)

    def dna2prots(self, input_fasta: Path, output_file: Optional[Path] = None, min_len: int = 30):
        return self.processor.dna2prots(input_fasta, output_file, min_len)

    # --- Section: Distance Calculation (Delegated) ---
    def fasta2dissim(self, input_fasta: Path, output_dm: Path, threads: Optional[int] = None):
        return self.calculator.fasta2dissim(input_fasta, output_dm, threads)

    def prot_collection2dissim(self, input_path: Path, output_dm: Path, threads: Optional[int] = None):
        return self.calculator.prot_collection2dissim(input_path, output_dm, threads)

    def hash2dissim(self, input_fasta: Path, output_dm: Path, k: int = 8, threads: Optional[int] = None):
        return self.calculator.hash2dissim(input_fasta, output_dm, k, threads)

    def _sanitize_dm_file(self, dm_path: Path) -> None:
        return self.calculator._sanitize_dm_file(dm_path)

    def _parse_dm_content(self, content: str):
        return self.calculator._parse_dm_content(content)

    # --- Section: Tree Building (Delegated) ---
    def build_tree_nj(self, input_dm: Optional[Path], output_nwk: Path, input_fasta: Optional[Path] = None) -> bool:
        return self.builder.build_tree_nj(input_dm, output_nwk, input_fasta)

    def build_tree_ml(
        self,
        input_fasta: Path,
        output_nwk: Path,
        bootstrap: int = 1000,
        use_gpu: bool = False,
        threads: Optional[int] = None,
    ) -> bool:
        return self.builder.build_tree_ml(input_fasta, output_nwk, bootstrap, use_gpu, threads)

    def build_tree_bayesian(
        self,
        input_fasta: Path,
        output_nwk: Path,
        ngen: int = 10000,
        use_gpu: bool = False,
    ) -> bool:
        return self.builder.build_tree_bayesian(input_fasta, output_nwk, ngen, use_gpu)

    def exec_fast_tree(
        self,
        input_fasta: Path,
        output_nwk: Path,
        params: Optional[Dict[str, Any]] = None,
    ) -> bool:
        return self.builder.exec_fast_tree(input_fasta, output_nwk, params)

    def make_dist_tree(
        self,
        input_dm: Optional[Path],
        output_nwk: Path,
        engine: str = "nj",
        input_fasta: Optional[Path] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Unified router for tree construction.
        Engines: 'nj' (FastTree/NCBI), 'ml' (IQ-Tree), 'bayesian' (MrBayes)

        Returns:
            True if tree was successfully built
        """
        param_dict = params or {}
        in_id_map: Dict[str, str] = param_dict.get("id_map", {})

        try:
            # 兼容性处理：如果前端发送了过时的 ml-gpu，自动回退到 IQ-TREE 3 CPU 模式
            if engine in ["ml", "ml-gpu"] and input_fasta:
                # 统一路由：所有最大似然（ML）请求均使用 IQ-TREE 3 高性能 CPU 模式
                bootstrap_val = param_dict.get("bootstrap", 1000)
                gpu_flag = param_dict.get("use_gpu", False)
                thread_count = param_dict.get("threads")
                return self.build_tree_ml(
                    input_fasta, output_nwk,
                    bootstrap=bootstrap_val, use_gpu=gpu_flag, threads=thread_count,
                )
            elif engine == "bayesian" and input_fasta:
                # 补全 MrBayes 动态参数：ngen
                gen_count = param_dict.get("ngen", 10000)
                gpu_flag = param_dict.get("use_gpu", False)
                return self.build_tree_bayesian(input_fasta, output_nwk, ngen=gen_count, use_gpu=gpu_flag)
            elif engine == "fast" and input_fasta:
                # FastTree 直接从 MSA 构树，不需要距离矩阵
                return self.exec_fast_tree(input_fasta, output_nwk)
            else:
                # 核心逻辑：执行构树。如果 input_dm 为空，则 build_tree_nj 会尝试兜底恢复
                success = self.build_tree_nj(input_dm, output_nwk, input_fasta=input_fasta)

                # Issue #3：使用 IDManager 精确还原 Newick 中的短 ID
                if success and in_id_map:
                    nwk = output_nwk.read_text(encoding="utf-8")
                    restored_nwk = IDManager.restore_ids_in_newick(nwk, in_id_map)
                    output_nwk.write_text(restored_nwk, encoding="utf-8")
                    logger.info(
                        f"Restored {len(in_id_map)} IDs in Newick output "
                        f"(regex word-boundary matching)"
                    )
                return success
        except Exception as exc:
            self.logger.error(f"Fundamental tree inference failure: {exc}")
            return False

    def tree_stats(self, tree_file: Path):
        """Silently compute stats. First try native then Biopython fallback."""
        try:
            # Note: statDistTree expects .tree file, but we might only have .nwk
            # Try to see if corresponding .tree exists
            tree_bin = tree_file.with_suffix(".tree")
            if tree_bin.exists():
                return self._run_command("statDistTree.exe", [str(tree_bin)])
            return None
        except Exception:
            return None

    def tree_reroot(self, input_nwk: Path, node_id: str, output_nwk: Path) -> None:
        """Reroot topology. Prefers binary if .tree exists, else Biopython."""
        tree_bin = input_nwk.with_suffix(".tree")
        if tree_bin.exists():
            res = self._run_command("replaceDistTree_reroot.exe", [str(tree_bin), node_id])
            output_nwk.write_text(res.stdout, encoding="utf-8")
        else:
            # Biopython Reroot implementation
            from Bio import Phylo

            tree = Phylo.read(input_nwk, "newick")
            tree.root_with_outgroup(node_id)
            Phylo.write(tree, output_nwk, "newick")

    def tree_compare(self, tree1: Path, tree2: Path):
        """Compare two tree topologies."""
        return self._run_command("compareTrees.exe", [str(tree1), str(tree2)])
