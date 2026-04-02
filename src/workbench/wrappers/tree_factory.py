import os
import math
import subprocess
import re
from pathlib import Path
from typing import List, Optional, Union, Dict, Any

from src.workbench.wrappers.base_wrapper import BaseWrapper

class TreeFactory(BaseWrapper):
    """
    Wrapper for NCBI Tree Tools.
    Handles Sequence Processing, Distance Calculation, and Tree Building.
    """

    def _get_threads(self, threads: Optional[int]) -> int:
        return threads if threads is not None else (os.cpu_count() or 4)

    # --- Section: Sequence Preprocessing ---

    def qc_stats(self, input_fasta: Path) -> Dict[str, Any]:
        results = {}
        try:
            gc_res = self._run_command("fasta2GC.exe", [str(input_fasta)])
            results['gc'] = gc_res.stdout.strip()
            comp_res = self.dna_complexity(input_fasta)
            results['complexity'] = comp_res.stdout.strip()
        except: pass
        return results

    def dna_complexity(self, input_fasta: Path, output_json: Optional[Path] = None):
        args = [str(input_fasta)]
        if output_json: args.extend(["-json", str(output_json)])
        return self._run_command("dna_complexity.exe", args)

    def prot_complexity(self, input_fasta: Path, output_json: Optional[Path] = None):
        args = [str(input_fasta)]
        if output_json: args.extend(["-json", str(output_json)])
        return self._run_command("prot_complexity.exe", args)

    def uniq_sequences(self, input_fasta: Path, output_fasta: Path):
        result = self._run_command("uniqSeq.exe", [str(input_fasta)])
        output_fasta.write_text(result.stdout, encoding='utf-8')
        return result

    def dna2prots(self, input_fasta: Path, output_file: Optional[Path] = None, min_len: int = 30):
        result = self._run_command("dna2prots.exe", [str(input_fasta), "1", str(min_len)])
        if output_file: output_file.write_text(result.stdout, encoding='utf-8')
        return result

    # --- Section: Distance Calculation ---

    def fasta2dissim(self, input_fasta: Path, output_dm: Path, threads: int = None):
        n_threads = self._get_threads(threads)
        args = [str(input_fasta), "-threads", str(n_threads)]
        result = self._run_command("fasta2dissim.exe", args)
        output_dm.write_text(result.stdout, encoding='utf-8')
        return result

    def hash2dissim(self, input_fasta: Path, output_dm: Path, k: int = 8, threads: int = None):
        """Alignment-free dissimilarity using k-mer hashing (Enhanced Sensitivity)."""
        import tempfile; import shutil
        temp_dir = Path(tempfile.mkdtemp(prefix="tree_hash_"))
        split_dir = temp_dir / "split"; hash_dir = temp_dir / "hashes"
        split_dir.mkdir(); hash_dir.mkdir()
        try:
            self._run_command("splitFasta.exe", [str(input_fasta), str(split_dir), "-extension", ".fasta", "-whole"])
            seq_files = list(split_dir.glob("*.fasta"))
            if not seq_files: raise ValueError("FASTA splitting failed.")
            objects = []
            for sf in seq_files:
                orig_id = sf.name.removesuffix(".fasta")
                seq_id = re.sub(r'[^a-zA-Z0-9.-_]', '_', orig_id).strip(".") or f"seq_{len(objects)}"
                base_id = seq_id; counter = 1
                while seq_id in objects:
                    seq_id = f"{base_id}_{counter}"; counter += 1
                sanitized_sf = sf.parent / f"{seq_id}.fasta"
                sf.rename(sanitized_sf); objects.append(seq_id)
                self._run_command("fasta2hash.exe", [str(sanitized_sf), str(hash_dir / seq_id), "-kmer", str(k)])
            
            objects_file = temp_dir / "objects.txt"
            objects_file.write_text("\n".join(objects) + "\n", encoding='utf-8')
            dm_base = output_dm.parent / output_dm.stem
            self._run_command("hash2dissim.exe", [str(objects_file), str(hash_dir), str(dm_base)])
            
            actual_dm = Path(f"{str(dm_base)}.dm")
            if actual_dm.exists():
                self._sanitize_dm_file(actual_dm)
                if actual_dm.resolve() != output_dm.resolve(): shutil.copy(actual_dm, output_dm)
        finally:
            try: shutil.rmtree(temp_dir)
            except: pass
        return True

    def _sanitize_dm_file(self, dm_path: Path):
        if not dm_path.exists(): return
        try:
            content = dm_path.read_text()
            if 'nan' in content:
                new_content = content.replace('nan', '1.0').replace('\r\n', '\n')
                dm_path.write_text(new_content, encoding='utf-8')
        except: pass

    # --- Section: Tree Building ---

    def make_dist_tree(self, input_dm: Path, output_nwk: Path):
        """Unified tree builder. If binary fails, Biopython guarantees Newick output."""
        binary_success = False
        content = input_dm.read_text(encoding='utf-8', errors='replace')
        
        # 1. Try Binary first ONLY if format is OBJNUM (Native NCBI Matrix format)
        # NCBI makeDistTree.exe strictly requires OBJNUM format and will crash on pairwise data.
        if content.startswith("OBJNUM"):
            try:
                binary_success = self._make_dist_tree_binary(input_dm, output_nwk)
            except Exception as e:
                self.logger.debug(f"Binary makeDistTree fallback triggered: {e}")
                
        if binary_success and output_nwk.exists() and output_nwk.stat().st_size > 10:
            return True

        # 2. Biopython Fallback (guarantees a Newick file exists for the UI)
        try:
            from Bio.Phylo.TreeConstruction import DistanceTreeConstructor, DistanceMatrix
            from Bio import Phylo
            name_list, matrix = self._parse_dm_content(content)
            dm = DistanceMatrix(name_list, matrix)
            constructor = DistanceTreeConstructor()
            tree = constructor.nj(dm)
            
            for node in tree.find_clades():
                if not node.is_terminal(): node.name = None
            
            import io
            out_str = io.StringIO()
            Phylo.write(tree, out_str, "newick")
            nwk = out_str.getvalue().strip().replace('\r\n', '\n')
            nwk = re.sub(r':-?\d+\.\d+;$', ';', nwk)
            nwk = nwk.replace(" ;", ";")
            
            output_nwk.write_text(nwk, encoding='utf-8')
            self.logger.info(f"Tree built (Biopython Fallback): {output_nwk}")
            return True
        except Exception as e:
            self.logger.error(f"Fundamental tree inference failure: {e}")
            return False

    def exec_make_dist_tree(self, input_dm: Path, output_tree: Path, params: Dict[str, Any] = None):
        self._sanitize_dm_file(input_dm)
        base_path = str(input_dm.parent / input_dm.stem)
        args = ["-data", base_path, "-output_tree", str(output_tree)]
        if params:
            for k, v in params.items(): args.extend([f"-{k}", str(v)])
        
        # USE -variance_dissim -variance lin as a safe pair for NJ
        if "-variance" not in [a[:9] for a in args]:
            args.extend(["-variance", "lin", "-variance_dissim"])
        return self._run_command("makeDistTree.exe", args)

    def exec_print_dist_tree(self, input_tree: Path, output_nwk: Path, format: str = "newick"):
        args = [str(input_tree), "-format", format]
        result = self._run_command("printDistTree.exe", args)
        if result and result.stdout:
            output_nwk.write_text(result.stdout.strip(), encoding='utf-8')
            return True
        return False

    def _make_dist_tree_binary(self, input_dm: Path, output_nwk: Path):
        tree_bin = input_dm.with_suffix(".tree")
        try:
             self.exec_make_dist_tree(input_dm, tree_bin)
             return self.exec_print_dist_tree(tree_bin, output_nwk)
        except: return False

    def _parse_dm_content(self, content: str):
        lines = content.splitlines()
        if not lines: return [], []
        if lines[0].startswith("OBJNUM"): return self._parse_matrix_dm(lines)
        return self._parse_pairwise_dm(lines)

    def _parse_matrix_dm(self, lines: List[str]):
        names = []; in_data = False; in_values = False; val_rows = []
        for line in lines:
            line = line.strip()
            if line == "DATA": in_data = True; continue
            if line.startswith("cons FULL"): in_data = False; in_values = True; continue
            if in_data:
                parts = line.split('\t')
                if parts[0]: names.append(parts[0])
            elif in_values:
                row = []
                for p in line.split('\t'):
                    try: 
                        v = float(p.strip())
                        row.append(1.0 if math.isnan(v) else v)
                    except: pass
                if row: val_rows.append(row)
        dim = len(names); matrix = []
        for i in range(dim):
            matrix.append([val_rows[i][j] if i < len(val_rows) and j < len(val_rows[i]) else (0.0 if i == j else 1.0) for j in range(i + 1)])
        return names, matrix

    def _parse_pairwise_dm(self, lines: List[str]):
        names = set(); dists = {}
        for line in lines:
            p = line.split('\t')
            if len(p) >= 6:
                n1, n2 = p[0], p[1]
                names.update([n1, n2])
                try:
                    ni, l1, l2 = float(p[3]), float(p[4]), float(p[5])
                    d = 1.0 - (ni / min(l1, l2)) if l1 > 0 and l2 > 0 else 1.0
                    dists[tuple(sorted((n1, n2)))] = max(0.0, 1.0 if math.isnan(d) else d)
                except: dists[tuple(sorted((n1, n2)))] = 1.0
        n_list = sorted(list(names)); dim = len(n_list); matrix = []
        for i in range(dim):
            matrix.append([0.0 if i == j else dists.get(tuple(sorted((n_list[i], n_list[j]))), 1.0) for j in range(i + 1)])
        return n_list, matrix

    def tree_stats(self, tree_file: Path):
        """Silently compute stats. First try native then Biopython fallback."""
        try: 
            # Note: statDistTree expects .tree file, but we might only have .nwk
            # Try to see if corresponding .tree exists
            tree_bin = tree_file.with_suffix(".tree")
            if tree_bin.exists():
                return self._run_command("statDistTree.exe", [str(tree_bin)])
            return None
        except: return None

    def tree_reroot(self, input_nwk: Path, node_id: str, output_nwk: Path):
        """Reroot topology. Prefers binary if .tree exists, else Biopython."""
        tree_bin = input_nwk.with_suffix(".tree")
        if tree_bin.exists():
            res = self._run_command("replaceDistTree_reroot.exe", [str(tree_bin), node_id])
            output_nwk.write_text(res.stdout, encoding='utf-8')
        else:
            # Biopython Reroot implementation
            from Bio import Phylo
            tree = Phylo.read(input_nwk, "newick")
            tree.root_with_outgroup(node_id)
            Phylo.write(tree, output_nwk, "newick")

    def tree_compare(self, tree1: Path, tree2: Path):
        return self._run_command("compareTrees.exe", [str(tree1), str(tree2)])
