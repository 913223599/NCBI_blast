import os
import subprocess
from pathlib import Path
from ..models.gpu_manager import GPUManager

class MAFFTWrapper:
    """
    WSL Bridge Wrapper for MAFFT (Molecular Multiple Alignment).
    Provides seamless alignment on Windows via WSL Linux distribution.
    """
    
    def __init__(self, wsl_dist="Ubuntu"):
        self.wsl_dist = wsl_dist
        self.gpu_manager = GPUManager()

    def align(self, input_fasta, output_fasta, threads=0):
        """
        Align sequences using MAFFT via WSL.
        """
        if not Path(input_fasta).exists():
            raise FileNotFoundError(f"Input FASTA not found: {input_fasta}")

        # Translation
        wsl_input = self.gpu_manager.to_wsl_path(str(Path(input_fasta).absolute()))
        
        # Threads logic - Correctly split arguments
        thread_num = "-1" if threads == 0 else str(threads)
        
        # Build command: mafft --auto --quiet input > output
        # Use stdout redirection via WSL
        cmd = ["wsl", "-u", "root", "-d", self.wsl_dist, "mafft", "--auto", "--quiet", "--thread", thread_num, wsl_input]
        
        try:
            with open(output_fasta, "w", encoding="utf-8") as f_out:
                # Specify encoding for stderr to avoid 'gbk' issues on Windows
                result = subprocess.run(cmd, stdout=f_out, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
            
            if result.returncode != 0:
                err = result.stderr.decode('utf-8', errors='replace')
                raise RuntimeError(f"MAFFT Alignment Failed: {err}")
            
            if not Path(output_fasta).exists() or os.path.getsize(output_fasta) < 10:
                raise RuntimeError("MAFFT Alignment produced an empty or invalid file.")
                
            return str(output_fasta)
            
        except Exception as e:
            raise RuntimeError(f"WSL MAFFT Execution Bridge Error: {str(e)}")
