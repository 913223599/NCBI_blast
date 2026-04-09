import subprocess
from pathlib import Path

from src.workbench.wrappers.base_wrapper import BaseWrapper


class IQTreeWrapper(BaseWrapper):
    """
    Wrapper for IQ-TREE 2/3 (Maximum Likelihood Tree Inference).
    Source: vendor/iqtree3
    """

    def build_tree(self, 
                   input_fasta: Path, 
                   output_dir: Path, 
                   model: str = "JC", # Use JC for test speed/simplicity
                   bootstrap: int = 1000,
                   threads: Optional[int] = None,
                   use_gpu: bool = False) -> Path:
        """
        Execute IQ-Tree 3 to infer a Maximum Likelihood tree (CPU Optimized).
        """
        self.validate_file(input_fasta)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Consistent prefix
        prefix = output_dir / f"{input_fasta.stem}_iqtree"
        
        n_threads = str(threads) if threads else "AUTO"
        
        # --- 强行对齐：IQ-TREE 3 的 UFBoot 算法必须 >= 1000 次自展检验 ---
        original_bs = int(bootstrap)
        actual_bootstrap = max(1000, original_bs)
        
        self.logger.info(f"IQ-TREE 3 (CPU): Params - Model: {model}, Replicates: {actual_bootstrap}, Threads: {n_threads}")

        args = [
            "-s", str(input_fasta.absolute()),
            "-m", model,
            "-pre", str(prefix.absolute()),
            "-nt", n_threads,
            "-redo",
            "-bb", str(actual_bootstrap)
        ]

        # Performance strategy: Set binary path (IQ-TREE 3)
        wsl_cmd = "/opt/iqtree3/iqtree-3.1.1-Linux-intel/bin/iqtree3"
        
        from src.workbench.models.gpu_manager import GPUManager
        
        # Path translation for WSL (using original args)
        wsl_args = []
        for val in args:
            s_val = str(val)
            if ":" in s_val and ("/" in s_val or "\\" in s_val):
                wsl_args.append(GPUManager.to_wsl_path(s_val))
            else:
                wsl_args.append(s_val)
        
        # Execute via WSL
        wsl_full_cmd = ["wsl", "-d", "Ubuntu", "-u", "root", wsl_cmd] + wsl_args
        self.logger.info(f"Executing IQ-TREE 3 via WSL: {' '.join(wsl_full_cmd)}")
        
        # 使用标准 run 进行执行，强制 utf-8 声明防止 gbk 冲突
        result = subprocess.run(wsl_full_cmd, text=True, encoding='utf-8', errors='replace', check=False)
        
        if result.returncode != 0:
            raise RuntimeError(f"IQ-TREE 3 WSL Execution Failed with code {result.returncode}")

        try:
            # Check for output (IQ-Tree can append .treefile or .iqtree.treefile)
            for ext in [".treefile", ".iqtree.treefile"]:
                res = Path(f"{str(prefix)}{ext}")
                if res.exists():
                    return res
            raise FileNotFoundError(f"IQ-TREE result file not found near {prefix}")
        except Exception as e:
            # Enhanced error report
            err_msg = str(e)
            if hasattr(e, 'stderr') and e.stderr:
                err_msg += f"\nSTDERR: {e.stderr}"
            self.logger.error(f"IQ-TREE ERROR: {err_msg}")
            raise RuntimeError(f"IQ-TREE Failure: {err_msg}")
