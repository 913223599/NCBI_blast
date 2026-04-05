import os
import subprocess
from pathlib import Path
from typing import List, Optional, Dict, Any

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
                   threads: Optional[int] = None) -> Path:
        """
        Execute IQ-Tree to infer a Maximum Likelihood tree.
        """
        self.validate_file(input_fasta)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Consistent prefix
        prefix = output_dir / f"{input_fasta.stem}_iqtree"
        
        n_threads = str(threads) if threads else "AUTO"
        
        args = [
            "-s", str(input_fasta.absolute()),
            "-m", model,
            "-pre", str(prefix.absolute()),
            "-nt", n_threads,
            "-redo",
            "-bb", str(bootstrap)
        ]
        
        self.logger.info(f"IQ-TREE: Starting ML analysis (model={model})")
        
        try:
            self._run_command("iqtree.exe", args)
            
            # Check most common result files
            for ext in [".treefile", ".iqtree.treefile"]:
                res = Path(f"{str(prefix)}{ext}")
                if res.exists():
                    return res
                    
            raise FileNotFoundError(f"IQ-TREE result file not found near {prefix}")
            
        except Exception as e:
            self.logger.error(f"IQ-TREE ERROR: {e}")
            raise e
