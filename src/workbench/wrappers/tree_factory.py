import os
import math
from pathlib import Path
from typing import List, Optional, Union, Dict, Any

from src.workbench.wrappers.base_wrapper import BaseWrapper

class TreeFactory(BaseWrapper):
    """
    Wrapper for NCBI Tree Tools.
    Handles Sequence Processing, Distance Calculation, and Tree Building.
    """

    def _get_threads(self, threads: Optional[int]) -> int:
        """Helper to determine thread count."""
        return threads if threads is not None else (os.cpu_count() or 4)

    # --- Section: Sequence QC & Preprocessing ---

    def qc_stats(self, input_fasta: Path) -> Dict[str, Any]:
        """Combine multiple QC tools to get sequence stats."""
        results = {}
        # 1. GC Content
        gc_res = self._run_command("fasta2GC.exe", [str(input_fasta)])
        results['gc'] = gc_res.stdout.strip()
        
        # 2. Complexity
        comp_res = self.dna_complexity(input_fasta)
        results['complexity'] = comp_res.stdout.strip()
        
        # 3. GC Skew (for long sequences/genomes)
        skew_res = self._run_command("dna_gc_skew.exe", [str(input_fasta)])
        results['gc_skew'] = skew_res.stdout.strip()
        
        return results

    def dna_complexity(self, input_fasta: Path, output_json: Optional[Path] = None):
        """Calculate DNA complexity score."""
        args = [str(input_fasta)]
        if output_json:
            args.extend(["-json", str(output_json)])
        return self._run_command("dna_complexity.exe", args)

    def prot_complexity(self, input_fasta: Path, output_json: Optional[Path] = None):
        """Calculate Protein complexity score."""
        args = [str(input_fasta)]
        if output_json:
            args.extend(["-json", str(output_json)])
        return self._run_command("prot_complexity.exe", args)

    def uniq_sequences(self, input_fasta: Path, output_fasta: Path):
        """Remove duplicate sequences."""
        # uniqSeq <INPUT> > <OUTPUT>
        result = self._run_command("uniqSeq.exe", [str(input_fasta)])
        with open(output_fasta, 'w') as f:
            f.write(result.stdout)
        return result

    def dna2prots(self, input_fasta: Path, output_file: Optional[Path] = None, min_len: int = 30):
        """Translate DNA to proteins (6 frames)."""
        # dna2prots <FASTA> 1 <MIN_LEN>
        result = self._run_command("dna2prots.exe", [str(input_fasta), "1", str(min_len)])
        if output_file:
            with open(output_file, 'w') as f:
                f.write(result.stdout)
        return result

    # --- Section: Distance Calculation Engines ---

    def fasta2dissim(self, input_fasta: Path, output_dm: Path, threads: int = None):
        """Calculate alignment-based dissimilarity matrix (DNA)."""
        n_threads = self._get_threads(threads)
        args = [str(input_fasta), "-threads", str(n_threads)]
        result = self._run_command("fasta2dissim.exe", args)
        with open(output_dm, 'w') as f:
            f.write(result.stdout)
        return result

    def prot_collection2dissim(self, input_fasta: Path, output_dm: Path, threads: int = None):
        """Calculate dissimilarity matrix for proteins using BLAST."""
        n_threads = self._get_threads(threads)
        args = [
            "-query", str(input_fasta), 
            "-subject", str(input_fasta), 
            "-outfmt", "6 qseqid sseqid nident length",
            "-max_hsps", "1",
            "-num_threads", str(n_threads)
        ]
        
        result = self._run_command("blastp.exe", args)
        
        # Convert BLAST output to .dm format
        lines = []
        for line in result.stdout.strip().splitlines():
            parts = line.split('\t')
            if len(parts) >= 4:
                q, s, ni, l = parts
                if q == s: continue
                lines.append(f"{q}\t{s}\tinf\t{ni}\t{l}\t{l}")
                  
        with open(output_dm, 'w') as f:
            f.write("\n".join(lines) + "\n")
        return result

    def hash2dissim(self, input_fasta: Path, output_dm: Path, k: int = 20, threads: int = None):
        """
        Calculate alignment-free dissimilarity using k-mer hashing.
        Handles the directory-based logic required by NCBI tree tools.
        """
        import tempfile
        import shutil
        
        # 1. Create Working Structure
        temp_dir = Path(tempfile.mkdtemp(prefix="tree_hash_"))
        split_dir = temp_dir / "split"
        hash_dir = temp_dir / "hashes"
        split_dir.mkdir(); hash_dir.mkdir()
        
        try:
            self.logger.info(f"Rapid Analysis: Splitting {input_fasta.name}...")
            # 2. Split Fasta (one per sequence)
            # Use -whole to keep original IDs as filenames
            self._run_command("splitFasta.exe", [str(input_fasta), str(split_dir), "-extension", ".fasta", "-whole"])
            
            # 3. Hash Each Sequence
            seq_files = list(split_dir.glob("*.fasta"))
            if not seq_files:
                raise ValueError("FASTA splitting failed - no files generated.")
                
            objects = []
            self.logger.info(f"Hashing {len(seq_files)} sequences...")
            for sf in seq_files:
                # Fix: Use removesuffix and strip trailing dots to avoid Windows filename issues
                # and ensure IDs match hash filenames exactly.
                orig_id = sf.name.removesuffix(".fasta")
                # Sanitize ID: remove trailing dots and replace problematic chars
                seq_id = "".join([c if c.isalnum() or c in ".-_" else "_" for c in orig_id])
                seq_id = seq_id.strip(".")
                
                # Handle empty or duplicate IDs after sanitization
                if not seq_id:
                    seq_id = f"seq_{len(objects)}"
                
                base_id = seq_id
                counter = 1
                while seq_id in objects:
                    seq_id = f"{base_id}_{counter}"
                    counter += 1
                    
                # Rename split file to match sanitized ID
                sanitized_sf = sf.parent / f"{seq_id}.fasta"
                if sf != sanitized_sf:
                    sf.rename(sanitized_sf)
                    
                objects.append(seq_id)
                # Fix: NCBI tree tools expect the hash filename to match the ID exactly (no .hash extension)
                hash_file = hash_dir / seq_id
                
                # fasta2hash <in> <out> -kmer <k>
                # Use k-mer mode to ensure hashes are generated even for non-CDS sequences
                self._run_command("fasta2hash.exe", [str(sanitized_sf), str(hash_file), "-kmer", str(k)])
            
            # 4. Create Objects List (Use LF for compatibility with Linux-ported tools)
            objects_file = temp_dir / "objects.txt"
            with open(objects_file, 'w', newline='\n') as f:
                f.write("\n".join(objects) + "\n")
            
            # 5. hash2dissim <objects> <hash_dir> <out_base>
            dm_base = output_dm.with_suffix("") 
            self.logger.info("Computing MinHash dissimilarity matrix...")
            self._run_command("hash2dissim.exe", [str(objects_file), str(hash_dir), str(dm_base)])
            
            # Note: hash2dissim creates <dm_base>.dm
            actual_dm = Path(f"{str(dm_base)}.dm")
            if actual_dm.exists():
                # Fix: Sanitize DM file to replace 'nan' with 1.0 (max distance)
                # This prevents downstream tool crashes when hash intersection is too low.
                self._sanitize_dm_file(actual_dm)
                
                if actual_dm.resolve() != output_dm.resolve():
                    shutil.copy(actual_dm, output_dm)
                
        finally:
            # Cleanup temp files
            try:
                shutil.rmtree(temp_dir)
            except: pass
        
        return True


    def _sanitize_dm_file(self, dm_path: Path):
        """Replace 'nan' in the .dm file with '1.0' to prevent tool crashes."""
        if not dm_path.exists(): return
        try:
            content = dm_path.read_text()
            if 'nan' in content:
                self.logger.warning(f"Found 'nan' in {dm_path.name}, replacing with '1.0'")
                new_content = content.replace('nan', '1.0').replace('\r\n', '\n')
                with open(dm_path, 'w', newline='\n', encoding='utf-8') as f:
                    f.write(new_content)
        except Exception as e:
            self.logger.error(f"Failed to sanitize DM file: {e}")


    # --- Section: Tree Building & Topology ---

    def make_dist_tree(self, input_dm: Path, output_nwk: Path):
        """Build tree from distance matrix using Biopython (Robust)."""
        try:
            from Bio.Phylo.TreeConstruction import DistanceTreeConstructor, DistanceMatrix
            from Bio import Phylo
            
            # Logic for parsing .dm and building NJ tree
            name_list, matrix = self._parse_dm_file(input_dm)
            dm = DistanceMatrix(name_list, matrix)
            
            constructor = DistanceTreeConstructor()
            tree = constructor.nj(dm)
            
            # Fix: Write Newick with LF line endings for compatibility with NCBI tools
            import io
            out_str = io.StringIO()
            Phylo.write(tree, out_str, "newick")
            nwk_string = out_str.getvalue().replace('\r\n', '\n')
            with open(output_nwk, 'w', newline='\n', encoding='utf-8') as f:
                f.write(nwk_string)
                
            self.logger.info(f"Tree built successfully: {output_nwk}")
            return True
        except Exception as e:
            self.logger.error(f"Tree construction failed: {e}")
            return self._make_dist_tree_binary(input_dm, output_nwk)

    def _parse_dm_file(self, input_dm: Path):
        """
        Internal helper to parse both pairwise (6-column) and matrix (OBJNUM) formats.
        Returns (name_list, matrix) where matrix is a lower triangular list of lists.
        """
        lines = input_dm.read_text().splitlines()
        if not lines:
            return [], []

        if lines[0].startswith("OBJNUM"):
            # Format: Matrix (NCBI/Workbench)
            return self._parse_matrix_dm(lines)
        else:
            # Format: Pairwise (Legacy)
            return self._parse_pairwise_dm(lines)

    def _parse_matrix_dm(self, lines: List[str]):
        names = []
        in_data = False
        in_values = False
        val_rows = []
        
        for line in lines:
            line = line.strip()
            if not line: continue
            
            if line == "DATA":
                in_data = True
                continue
            if line.startswith("cons FULL"):
                in_data = False
                in_values = True
                continue
            if line == "ATTRIBUTES":
                continue
            
            if in_data:
                # Part of the names block
                name = line.split('\t')[0].strip()
                if name: names.append(name)
            elif in_values:
                # Part of the values block
                parts = line.split('\t')
                rows_vals = []
                for p in parts:
                    p = p.strip()
                    if not p: continue
                    try:
                        val = float(p)
                        rows_vals.append(1.0 if math.isnan(val) else val)
                    except ValueError:
                        rows_vals.append(1.0)
                if rows_vals:
                    val_rows.append(rows_vals)

        # Convert full matrix to lower triangular for Biopython DistanceMatrix
        # DM(names, matrix) where matrix[i] has i+1 elements
        dim = len(names)
        matrix = []
        for i in range(dim):
            row = []
            for j in range(i + 1):
                if i < len(val_rows) and j < len(val_rows[i]):
                    row.append(val_rows[i][j])
                else:
                    row.append(0.0 if i == j else 1.0)
            matrix.append(row)
            
        return names, matrix

    def _parse_pairwise_dm(self, lines: List[str]):
        names = set()
        distances = {}
        for line in lines:
            parts = line.split('\t')
            if len(parts) >= 6:
                n1, n2, _, ni, l1, l2 = parts[:6]
                names.add(n1); names.add(n2)
                try:
                    f_ni, f_l1, f_l2 = float(ni), float(l1), float(l2)
                    if math.isnan(f_ni) or f_l1 <= 0 or f_l2 <= 0:
                        dist = 1.0
                    else:
                        dist = 1.0 - (f_ni / min(f_l1, f_l2))
                    
                    if math.isnan(dist): dist = 1.0
                    distances[tuple(sorted((n1, n2)))] = max(0.0, dist)
                except (ZeroDivisionError, ValueError):
                    distances[tuple(sorted((n1, n2)))] = 1.0
        
        name_list = sorted(list(names))
        dim = len(name_list)
        matrix = []
        for i in range(dim):
            row = []
            for j in range(i + 1):
                if i == j: row.append(0.0)
                else:
                    pair = tuple(sorted((name_list[i], name_list[j])))
                    row.append(distances.get(pair, 1.0))
            matrix.append(row)
        return name_list, matrix

    def tree_stats(self, tree_file: Path):
        """Get tree statistics using statDistTree.exe."""
        return self._run_command("statDistTree.exe", [str(tree_file)])

    def tree_reroot(self, input_nwk: Path, node_id: str, output_nwk: Path):
        """Reroot tree at specific node."""
        # replaceDistTree_reroot <TREE> <NODE>
        result = self._run_command("replaceDistTree_reroot.exe", [str(input_nwk), node_id])
        with open(output_nwk, 'w') as f:
            f.write(result.stdout)
        return result

    def tree_compare(self, tree1: Path, tree2: Path):
        """Compare two tree topologies."""
        return self._run_command("compareTrees.exe", [str(tree1), str(tree2)])

    def exec_make_dist_tree(self, input_dm: Path, output_tree: Path, params: Dict[str, Any] = None):
        """
        Execute makeDistTree.exe with full parameter support.
        """
        # Ensure sanitization before run
        self._sanitize_dm_file(input_dm)
        
        # Using base path for -data input logic
        base_path = str(input_dm.parent / input_dm.stem)
        
        args = ["-data", base_path, "-output_tree", str(output_tree)]
        
        # Inject optional parameters
        if params:
            for k, v in params.items():
                args.extend([f"-{k}", str(v)])
                
        # Run command
        return self._run_command("makeDistTree.exe", args)

    def exec_print_dist_tree(self, input_tree: Path, output_nwk: Path, format: str = "newick", params: Dict[str, Any] = None):
        """
        Execute printDistTree.exe to export tree to Newick format.
        
        Usage: printDistTree.exe <input_tree> [-format newick] ... 
        Output goes to stdout, so we capture it and write to file.
        """
        args = [str(input_tree)]
        
        # Correct usage: -format newick (outputs to stdout)
        if format.lower() == "newick":
            args.extend(["-format", "newick"])
        
        if params:
            for k, v in params.items():
                if k in ["format"]: continue 
                args.extend([f"-{k}", str(v)])
        
        # Run command and capture stdout
        result = self._run_command("printDistTree.exe", args)
        
        # Write stdout to output file (Newick content)
        if result and hasattr(result, 'stdout') and result.stdout:
            output_nwk.write_text(result.stdout.strip(), encoding='utf-8')
            self.logger.info(f"Newick tree written to {output_nwk}")
        elif isinstance(result, str) and result:
            output_nwk.write_text(result.strip(), encoding='utf-8')
            self.logger.info(f"Newick tree written to {output_nwk}")
        
        return result

    def _make_dist_tree_binary(self, input_dm: Path, output_nwk: Path):
        """Fallback to native binaries for tree building (Legacy Helper)."""
        tree_bin = input_dm.with_suffix(".tree")
        try:
             self.exec_make_dist_tree(input_dm, tree_bin)
             self.exec_print_dist_tree(tree_bin, output_nwk)
             return True
        except Exception as e:
             self.logger.warning(f"Binary makeDistTree failed: {e}")
             return False

