from pathlib import Path

from .base_wrapper import BaseWrapper


class MrBayesWrapper(BaseWrapper):
    """
    Wrapper for MrBayes (Bayesian Inference).
    Source: vendor/MrBayes
    """

    def build_tree(self, 
                   input_nex: Path, 
                   ngen: int = 5000,
                   use_gpu: bool = False) -> Path:
        """Execute chain inference via MrBayes (Standard CPU mode)."""
        self.validate_file(input_nex)
        
        args = [str(input_nex.absolute())]
        self.logger.info(f"MrBayes: Starting Bayesian analysis (ngen={ngen})")
        
        try:
            self._run_command("mb.exe", args)
            
            # Look for '.con.tre' which is the consensus tree MrBayes generates
            con_tree = input_nex.parent / f"{input_nex.name}.con.tre"
            if not con_tree.exists():
                # Fallback to MrBayes default naming
                con_tree = input_nex.with_suffix(".nex.con.tre")
            
            if con_tree.exists():
                return con_tree
            raise FileNotFoundError(f"MrBayes Consensus Tree not found at {con_tree}")
            
        except Exception as e:
            self.logger.error(f"MRBAYES ERROR: {e}")
            raise e

    def prepare_nexus_from_fasta(self, 
                               fasta_path: Path, 
                               output_nex: Path,
                               ngen: int = 5000,
                               use_gpu: bool = False) -> Path:
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
                
                # Standard MCMC configuration
                f.write("  set autoclose=yes nowarn=yes;\n")
                f.write("  lset nst=2 rates=gamma;\n")
                f.write(f"  mcmc ngen={ngen} samplefreq=10 printfreq=1000;\n")
                f.write("  sump;\n")
                f.write("  sumt;\n")
                f.write("END;\n")
            return output_nex
            return output_nex
        except Exception as e:
            self.logger.error(f"NEXUS Prepare failed: {e}")
            raise e
