import os
import subprocess
from pathlib import Path
from typing import List, Optional, Dict, Any, Union

from src.workbench.wrappers.base_wrapper import BaseWrapper

class MrBayesWrapper(BaseWrapper):
    """
    Wrapper for MrBayes (Bayesian Inference).
    Source: vendor/MrBayes
    """

    def build_tree(self, 
                   input_nex: Path, 
                   ngen: int = 5000) -> Path:
        """Execute chain inference."""
        self.validate_file(input_nex)
        
        # mb.exe expects input as single arg in some versions or via redirect
        args = [str(input_nex.absolute())]
        
        self.logger.info(f"MrBayes: Starting Bayesian analysis (ngen={ngen})")
        
        try:
            # MrBayes is chatty and might block on stdin if not configured with autoclose
            self._run_command("mb.exe", args)
            
            # Look for '.con.tre' which is the consensus tree MrBayes generates
            # IMPORTANT: MrBayes might output to the CWD of the nexus file
            con_tree = input_nex.with_suffix(".nex.con.tre")
            if not con_tree.exists():
                con_tree = input_nex.parent / f"{input_nex.name}.con.tre"
            
            if con_tree.exists():
                return con_tree
            raise FileNotFoundError(f"MrBayes Consensus Tree not found at {con_tree}")
            
        except Exception as e:
            self.logger.error(f"MRBAYES ERROR: {e}")
            raise e

    def prepare_nexus_from_fasta(self, 
                               fasta_path: Path, 
                               output_nex: Path,
                               ngen: int = 5000) -> Path:
        """Ensures FASTA to NEXUS conversion with valid MCMC block."""
        try:
            from Bio import SeqIO
            sequences = list(SeqIO.parse(fasta_path, "fasta"))
            
            with open(output_nex, "w", encoding="utf-8") as f:
                f.write("#NEXUS\n\nBEGIN DATA;\n")
                f.write(f"  DIMENSIONS NTAX={len(sequences)} NCHAR={len(sequences[0].seq)};\n")
                f.write("  FORMAT DATATYPE=DNA MISSING=? GAP=-;\n")
                f.write("  MATRIX\n")
                for s in sequences:
                    # MrBayes IDs can't have spaces or certain chars
                    clean_id = "".join(c if c.isalnum() or c == '_' else '_' for c in s.id)
                    f.write(f"    {clean_id.ljust(30)} {str(s.seq)}\n")
                f.write("  ;\nEND;\n\n")
                
                f.write("BEGIN MRBAYES;\n")
                f.write("  set autoclose=yes nowarn=yes;\n")
                f.write("  lset nst=2 rates=gamma;\n")
                f.write(f"  mcmc ngen={ngen} samplefreq=10 printfreq=1000;\n")
                f.write("  sump;\n")
                f.write("  sumt;\n")
                f.write("END;\n")
            return output_nex
        except Exception as e:
            self.logger.error(f"NEXUS Prepare failed: {e}")
            raise e
