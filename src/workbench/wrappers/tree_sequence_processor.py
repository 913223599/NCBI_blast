from pathlib import Path
from typing import Dict, Any

from src.workbench.wrappers.base_wrapper import BaseWrapper


class SequenceProcessor(BaseWrapper):
    """负责序列的预处理和质量控制"""

    def qc_stats(self, input_fasta: Path) -> Dict[str, Any]:
        results = {}
        try:
            gc_res = self._run_command("fasta2GC.exe", [str(input_fasta)])
            results['gc'] = gc_res.stdout.strip()
            comp_res = self.dna_complexity(input_fasta)
            results['complexity'] = comp_res.stdout.strip()
        except: pass
        return results

    def dna_complexity(self, input_fasta: Path, output_json: Path = None):
        args = [str(input_fasta)]
        if output_json: args.extend(["-json", str(output_json)])
        return self._run_command("dna_complexity.exe", args)

    def prot_complexity(self, input_fasta: Path, output_json: Path = None):
        args = [str(input_fasta)]
        if output_json: args.extend(["-json", str(output_json)])
        return self._run_command("prot_complexity.exe", args)

    def uniq_sequences(self, input_fasta: Path, output_fasta: Path):
        result = self._run_command("uniqSeq.exe", [str(input_fasta)])
        output_fasta.write_text(result.stdout, encoding='utf-8')
        return result

    def dna2prots(self, input_fasta: Path, output_file: Path = None, min_len: int = 30):
        result = self._run_command("dna2prots.exe", [str(input_fasta), "1", str(min_len)])
        if output_file: output_file.write_text(result.stdout, encoding='utf-8')
        return result
