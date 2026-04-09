import shutil
from pathlib import Path
from typing import Dict, Any

from src.workbench.wrappers.base_wrapper import BaseWrapper


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
        flat_val = None
        for i in range(len(matrix)):
            for j in range(i):
                val = matrix[i][j]
                if flat_val is None: 
                    flat_val = val
                elif abs(val - flat_val) > 1e-12: 
                    matrix_is_flat = False
                    break
            if not matrix_is_flat: 
                break
        
        return not matrix_is_flat
    
    def _recover_and_build_nj_from_fasta(self, input_fasta: Path, output_nwk: Path) -> bool:
        """
        从FASTA文件恢复并构建NJ树（降级方案）
        
        Args:
            input_fasta: FASTA文件路径
            output_nwk: 输出Newick文件路径
            
        Returns:
            True if successful, False otherwise
        """
        try:
            from Bio import SeqIO
            from Bio.Align import MultipleSeqAlignment
            from Bio.SeqRecord import SeqRecord
            from Bio.Seq import Seq
            from Bio.Phylo.TreeConstruction import DistanceCalculator as BiopythonDC, DistanceTreeConstructor
            
            # 核心修复：如果未对齐或长度不一，先执行原子级补齐 (Padding)
            raw_records = list(SeqIO.parse(input_fasta, "fasta"))
            max_len = max(len(r.seq) for r in raw_records)
            padded_records = []
            for r in raw_records:
                if len(r.seq) < max_len:
                    new_seq = str(r.seq).ljust(max_len, "-")
                    padded_records.append(SeqRecord(Seq(new_seq), id=r.id, description=""))
                else:
                    padded_records.append(r)
            
            alignment = MultipleSeqAlignment(padded_records)
            calculator = BiopythonDC('identity')  # p-distance for robustness
            dm = calculator.get_distance(alignment)
            
            constructor = DistanceTreeConstructor()
            tree = constructor.nj(dm)
            
            # 规范化清理
            for node in tree.find_clades():
                if not node.is_terminal(): 
                    node.name = None
            
            from Bio import Phylo
            import io
            out_str = io.StringIO()
            Phylo.write(tree, out_str, "newick")
            nwk = out_str.getvalue().strip().replace('\r\n', '\n')
            import re
            nwk = re.sub(r':-?\d+\.\d+;$', ';', nwk)
            output_nwk.write_text(nwk, encoding='utf-8')
            self.logger.info(f"NJ Tree successfully RECOVERED via direct MSA analysis: {output_nwk}")
            return True
            
        except Exception as e:
            self.logger.error(f"High-precision NJ recovery failed: {e}")
            return False

    def build_tree_nj(self, input_dm: Path, output_nwk: Path, input_fasta: Path = None) -> bool:
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
            content = input_dm.read_text(encoding='utf-8', errors='replace')
            
        name_list, matrix = calc._parse_dm_content(content)
        
        # 验证矩阵质量
        if not self._validate_distance_matrix(matrix):
            # 矩阵失效，尝试从FASTA恢复
            if input_fasta and input_fasta.exists():
                self.logger.warning("Detected invalid distance matrix. Starting recovery from FASTA...")
                return self._recover_and_build_nj_from_fasta(input_fasta, output_nwk)
            else:
                self.logger.error("Invalid distance matrix and no FASTA fallback available")
                return False
        
        # 正常流程：基于读入的矩阵构建
        try:
            from Bio.Phylo.TreeConstruction import DistanceTreeConstructor, DistanceMatrix
            from Bio import Phylo
            if not name_list or not matrix: 
                return False
            
            dm = DistanceMatrix(name_list, matrix)
            constructor = DistanceTreeConstructor()
            tree = constructor.nj(dm)
            
            for node in tree.find_clades():
                if not node.is_terminal(): 
                    node.name = None
            
            import io
            out_str = io.StringIO()
            Phylo.write(tree, out_str, "newick")
            nwk = out_str.getvalue().strip().replace('\r\n', '\n')
            import re
            nwk = re.sub(r':-?\d+\.\d+;$', ';', nwk)
            nwk = nwk.replace(" ;", ";")
            
            # 高精度解析还原：确保科学计数法和长 ID 的匹配性
            output_nwk.write_text(nwk, encoding='utf-8')
            self.logger.info(f"Tree built from matrix: {output_nwk}")
            return True
            
        except Exception as e:
            self.logger.error(f"NJ builder failed: {e}")
            return False

    def build_tree_ml(self, input_fasta: Path, output_nwk: Path, bootstrap: int = 1000, use_gpu: bool = False, threads: int = None):
        """Maximum Likelihood Inference via IQ-TREE 3 (CPU Optimized)."""
        from src.workbench.wrappers.iqtree_wrapper import IQTreeWrapper
        iqtree = IQTreeWrapper()
        try:
            tree_file = iqtree.build_tree(input_fasta, output_nwk.parent, bootstrap=bootstrap, use_gpu=use_gpu, threads=threads)
            # Normalize to output_nwk path
            shutil.copy2(tree_file, output_nwk)
            return True
        except Exception as e:
            self.logger.error(f"ML Algorithm Failure: {e}")
            return False

    def build_tree_bayesian(self, input_fasta: Path, output_nwk: Path, ngen: int = 10000, use_gpu: bool = False):
        """Bayesian Inference via MrBayes."""
        from src.workbench.wrappers.mrbayes_wrapper import MrBayesWrapper
        mb = MrBayesWrapper()
        try:
            nex_file = output_nwk.with_suffix(".nex")
            mb.prepare_nexus_from_fasta(input_fasta, nex_file, ngen=ngen, use_gpu=use_gpu)
            con_tree = mb.build_tree(nex_file, ngen=ngen, use_gpu=use_gpu)
            
            # Map MrBayes .con.tre to .tree or .nwk
            shutil.copy2(con_tree, output_nwk)
            return True
        except Exception as e:
            self.logger.error(f"Bayesian Algorithm Failure: {e}")
            return False

    def exec_fast_tree(self, input_fasta: Path, output_nwk: Path, params: Dict[str, Any] = None):
        """Invoke FastTree for Maximum Likelihood approximation directly from MSA."""
        args = ["-quiet"]
        p = params or {}
        
        # DNA or Protein logic
        model = p.get('model', 'jc').lower()
        if p.get('seq_type') == 'protein':
            if model == 'wag': args.append("-wag")
        else:
            args.append("-nt")
            if model == 'gtr': args.append("-gtr")
            
        args.extend(["-quote", str(input_fasta)])
        
        try:
            result = self._run_command("FastTree.exe", args)
            if result and result.stdout:
                output_nwk.write_text(result.stdout.strip(), encoding='utf-8')
                return True
        except Exception as e:
            self.logger.error(f"FastTree analysis failed: {e}")
        return False
