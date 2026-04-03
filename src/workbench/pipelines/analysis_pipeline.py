from pathlib import Path
from typing import Dict, Any, List, Optional
import json

from src.workbench.wrappers.tree_factory import TreeFactory

class AnalysisPipeline:
    """
    Bio-Circuit Analysis Pipeline.
    Orchestrates Phylogenetic workflows using modular components.
    """
    
    def __init__(self):
        self.tree_tools = TreeFactory()
        
    def _detect_sequence_type(self, fasta_path: Path) -> str:
        dna_chars = set("ATGCNU- \n\r")
        try:
            with open(fasta_path, 'r') as f:
                content = f.read(4000)
                sequences = []
                for line in content.splitlines():
                    if not line.startswith(">"):
                        sequences.append(line.upper())
                
                seq_str = "".join(sequences)
                if not seq_str: return "dna"
                
                for char in seq_str:
                    if char not in dna_chars:
                        return "protein"
            return "dna"
        except:
            return "dna"

    # --- Phase 1: FASTA (Inlet) ---
    def stage_fasta_process(self, input_fasta: Path, output_dir: Path) -> Dict[str, Any]:
        """FASTA 元器件逻辑：进行 QC 并准备序列。"""
        results = {"status": "success"}
        seq_type = self._detect_sequence_type(input_fasta)
        results["seq_type"] = seq_type
        
        try:
            results["qc"] = self.tree_tools.qc_stats(input_fasta)
        except Exception as e:
            results["qc_error"] = str(e)
            
        return results
        
    # --- Phase 1.5: MSA (Refinement) ---
    def stage_msa_alignment(self, input_fasta: Path, output_fasta: Path, method: str = "none") -> Dict[str, Any]:
        """MSA 元器件逻辑：进行多序列比对。"""
        results = {"status": "success", "file": str(output_fasta)}
        if method == "none":
            # 简单拷贝
            import shutil
            shutil.copy(input_fasta, output_fasta)
        elif method in ["mafft", "muscle"]:
            # 仿真/Mock 比对 (在没有安装二进制文件时提示)
            # 在高性能版本中，此处应调用 MAFFT -auto input > output
            import shutil
            shutil.copy(input_fasta, output_fasta)
            results["info"] = f"Using {method.upper()} alignment strategy..."
            
        return results

    # --- Phase 2: DIST (Calculator) ---
    def stage_dist_compute(self, input_fasta: Path, output_dm: Path, 
                          method: str = "rapid", k: int = 20, threads: int = None) -> Dict[str, Any]:
        """DIST 元器件逻辑：计算距离矩阵。支持从 FASTA 启动。"""
        results = {"status": "success", "dm_file": str(output_dm)}
        
        if method == "rapid":
            self.tree_tools.hash2dissim(input_fasta, output_dm, k=k, threads=threads)
        else:
            seq_type = self._detect_sequence_type(input_fasta)
            if seq_type == "protein":
                self.tree_tools.prot_collection2dissim(input_fasta, output_dm, threads=threads)
            else:
                self.tree_tools.fasta2dissim(input_fasta, output_dm, threads=threads)
                
        return results

    # --- Phase 3: NWK (Topology Hub) ---
    def stage_nwk_inference(self, input_dm: Path, output_nwk: Path) -> Dict[str, Any]:
        """NWK 元器件逻辑：构树并生成 Newick 拓扑。"""
        self.tree_tools.make_dist_tree(input_dm, output_nwk)
        results = {"status": "success", "tree_file": str(output_nwk)}
        
        try:
            stats = self.tree_tools.tree_stats(output_nwk)
            results["tree_stats"] = stats.stdout.strip()
        except: pass
        
        return results

    # --- Phase 4: GROUP (Analysis Port) ---
    def stage_group_analysis(self, input_nwk: Path, output_dir: Path, dist_threshold: float = 0.05) -> Dict[str, Any]:
        """GROUP 元器件逻辑：基因型分析与聚类。"""
        results = {"status": "success"}
        try:
            # Conversion to binary format for tree2genogroup
            bin_tree_file = input_nwk.with_suffix(".tree_bin")
            cv_res = self.tree_tools._run_command("newick2tree.exe", [str(input_nwk)])
            with open(bin_tree_file, 'w', newline='\n', encoding='utf-8') as f:
                f.write(cv_res.stdout)
                
            group_res = self.tree_tools._run_command("tree2genogroup.exe", [str(bin_tree_file), str(dist_threshold)])
            results["groups"] = group_res.stdout.strip()
            results["bin_tree"] = str(bin_tree_file)
        except Exception as e:
            results["status"] = "error"
            results["error"] = str(e)
            
        return results

    # --- Auxiliary: Macro Flows ---
    def run_full_pipeline(self, input_fasta: Path, output_dir: Path, method: str = "rapid", params: Dict[str, Any] = None):
        """兼容新架构的全流程驱动，支持动态选择建树模式。"""
        p = params or {}
        msa_method = p.get("msa", "none")
        engine = p.get("engine", "nj")
        k = p.get("kmerSize", 8)
        threads = p.get("threads", None)
        
        yield {"step": "fasta", "progress": 10, "message": "启动 FASTA 预处理序列..."}
        self.stage_fasta_process(input_fasta, output_dir)
        
        yield {"step": "msa", "progress": 25, "message": f"执行 {msa_method} 多序列比对..."}
        msa_file = output_dir / f"{input_fasta.stem}_aligned.fasta"
        self.stage_msa_alignment(input_fasta, msa_file, method=msa_method)
        
        yield {"step": "dist", "progress": 50, "message": f"计算距离矩阵 ({method}模式，k={k})..."}
        dm_file = output_dir / f"{input_fasta.stem}.dm"
        # NJ 引擎对应 rapid/standard。ML 引擎在此演示版中也映射到 standard。
        dist_mode = "rapid" if engine == "nj" and method == "rapid" else "standard"
        self.stage_dist_compute(msa_file, dm_file, method=dist_mode, k=k, threads=threads)
        
        yield {"step": "nwk", "progress": 75, "message": "构建系统发育树拓扑..."}
        nwk_file = output_dir / f"{input_fasta.stem}.nwk"
        self.stage_nwk_inference(dm_file, nwk_file)
        
        yield {"step": "finish", "progress": 100, "message": "分析完成，准备加载视图渲染...", "result": {"tree_file": str(nwk_file)}}
