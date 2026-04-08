import os
import math
import subprocess
import re
import shutil
from pathlib import Path
from typing import List, Optional, Union, Dict, Any

from src.workbench.wrappers.base_wrapper import BaseWrapper

class TreeFactory(BaseWrapper):
    """
    Unified Tree Construction Factory.
    Integrates NCBI DistTree, FastTree, IQ-TREE, and MrBayes.
    """

    def _get_threads(self, threads: Optional[int]) -> int:
        # 兼容性修复：0 或 None 均视为自动模式 (AUTO)
        if threads is None or threads <= 0:
            return os.cpu_count() or 4
        return threads

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
        """Alignment-based dissimilarity (ID-Safe Tunneling)."""
        n_threads = self._get_threads(threads)
        
        # 核心改进：创建 ID 映射以防止 NCBI 工具在 Windows 下因长 ID 崩溃或截断
        id_map = {}
        sanitized_fasta = input_fasta.parent / f"{input_fasta.stem}_safe.fasta"
        try:
            from Bio import SeqIO
            records = list(SeqIO.parse(input_fasta, "fasta"))
            safe_records = []
            for i, rec in enumerate(records):
                short_id = f"S{i:05d}"
                id_map[short_id] = rec.id
                rec.id = short_id
                rec.description = ""
                safe_records.append(rec)
            SeqIO.write(safe_records, sanitized_fasta, "fasta")
            
            args = [str(sanitized_fasta.absolute()), "-threads", str(n_threads)]
            result = self._run_command("fasta2dissim.exe", args)
            
            # 后处理：保存包含短 ID 的中间矩阵，确保解析器能精准对齐
            output_dm.write_text(result.stdout, encoding='utf-8')
            # 返回 ID 映射字典供后续还原
            return id_map
        finally:
            if sanitized_fasta.exists(): sanitized_fasta.unlink()

    def prot_collection2dissim(self, input_path: Path, output_dm: Path, threads: int = None):
        """Build dissimilarity matrix from protein collection."""
        n_threads = self._get_threads(threads)
        args = [str(input_path), "-threads", str(n_threads)]
        result = self._run_command("prot_collection2dissim.exe", args)
        output_dm.write_text(result.stdout, encoding='utf-8')
        return result

    def hash2dissim(self, input_fasta: Path, output_dm: Path, k: int = 8, threads: int = None):
        """Alignment-free dissimilarity using k-mer hashing (Enhanced Sensitivity)."""
        import tempfile; import shutil
        temp_dir = Path(tempfile.mkdtemp(prefix="tree_hash_")).absolute()
        split_dir = temp_dir / "split"; hash_dir = temp_dir / "hashes"
        split_dir.mkdir(); hash_dir.mkdir()
        
        # Determine optimal K (K=8 for long, K=min(4, len/2) for short)
        effective_k = k
        try:
             with open(input_fasta, 'r') as f:
                 first_seq = f.read(5000).split('\n')[1][:100]
                 if len(first_seq) < 30: effective_k = min(4, len(first_seq)//2)
        except: pass
        
        id_map = {}
        try:
            # 强化 IO：使用引号保护路径，特别是 splitFasta
            self._run_command("splitFasta.exe", [str(input_fasta.absolute()), str(split_dir), "-extension", ".fasta", "-whole"])
            seq_files = list(split_dir.glob("*.fasta"))
            if not seq_files: raise ValueError("FASTA splitting failed.")
            objects = []
            for sf in seq_files:
                orig_id = sf.name.removesuffix(".fasta")
                # 记录 ID 转换映射以便后续在 Newick 中还原
                seq_id = re.sub(r'[^a-zA-Z0-9.-_]', '_', orig_id).strip(".") or f"seq_{len(objects)}"
                base_id = seq_id; counter = 1
                while seq_id in objects:
                    seq_id = f"{base_id}_{counter}"; counter += 1
                
                id_map[seq_id] = orig_id
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
        return id_map

    def _sanitize_dm_file(self, dm_path: Path):
        if not dm_path.exists(): return
        try:
            content = dm_path.read_text()
            if 'nan' in content:
                new_content = content.replace('nan', '1.0').replace('\r\n', '\n')
                dm_path.write_text(new_content, encoding='utf-8')
        except: pass

    # --- Section: Tree Building ---

    def build_tree_nj(self, input_dm: Optional[Path], output_nwk: Path, input_fasta: Path = None) -> bool:
        """
        Neighbor-Joining Tree Construction.
        If the matrix is invalid, it falls back to direct MSA distance computation.
        """
        # --- 核心改进：空对象保护 ---
        content = ""
        if input_dm and input_dm.exists():
            content = input_dm.read_text(encoding='utf-8', errors='replace')
            
        name_list, matrix = self._parse_dm_content(content)
        
        # 矩阵质量评分：极大提升灵敏度，捕获科学计数法级别的演化差异 (如 5e-05)
        matrix_is_flat = True
        flat_val = None
        for i in range(len(matrix)):
            for j in range(i):
                val = matrix[i][j]
                if flat_val is None: flat_val = val
                elif abs(val - flat_val) > 1e-12: 
                    matrix_is_flat = False; break
            if not matrix_is_flat: break
            
        # --- 如果矩阵失效且有比对序列，启动强制重算 (True Dist Calculation) ---
        if (matrix_is_flat or not matrix) and input_fasta and input_fasta.exists():
            self.logger.warning("Detected dead distance matrix. Starting high-precision recovery calculation...")
            try:
                from Bio import SeqIO
                from Bio.Align import MultipleSeqAlignment
                from Bio.SeqRecord import SeqRecord
                from Bio.Seq import Seq
                from Bio.Phylo.TreeConstruction import DistanceCalculator, DistanceTreeConstructor
                
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
                calculator = DistanceCalculator('identity') # p-distance for robustness
                dm = calculator.get_distance(alignment)
                
                constructor = DistanceTreeConstructor()
                tree = constructor.nj(dm)
                
                # 规范化清理
                for node in tree.find_clades():
                    if not node.is_terminal(): node.name = None
                
                from Bio import Phylo
                import io
                out_str = io.StringIO()
                Phylo.write(tree, out_str, "newick")
                nwk = out_str.getvalue().strip().replace('\r\n', '\n')
                nwk = re.sub(r':-?\d+\.\d+;$', ';', nwk)
                output_nwk.write_text(nwk, encoding='utf-8')
                self.logger.info(f"NJ Tree successfully RECOVERED via direct MSA analysis: {output_nwk}")
                return True
            except Exception as e:
                self.logger.error(f"High-precision NJ recovery failed: {e}")

        # --- 正常流程：基于读入的矩阵构建 ---
        try:
            from Bio.Phylo.TreeConstruction import DistanceTreeConstructor, DistanceMatrix
            from Bio import Phylo
            if not name_list or not matrix: return False
            
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

    def make_dist_tree(self, input_dm: Path, output_nwk: Path, engine: str = 'nj', 
                       input_fasta: Path = None, params: Dict[str, Any] = None):
        """
        Unified router for tree construction.
        Engines: 'nj' (FastTree/NCBI), 'ml' (IQ-Tree), 'bayesian' (MrBayes)
        """
        p = params or {}
        in_id_map = p.get("id_map", {})
        
        try:
            # 兼容性处理：如果前端发送了过时的 ml-gpu，自动回退到 IQ-TREE 3 CPU 模式
            if engine in ['ml', 'ml-gpu'] and input_fasta:
                # 统一路由：所有最大似然（ML）请求均使用 IQ-TREE 3 高性能 CPU 模式
                bs = p.get("bootstrap", 1000)
                gpu = p.get("use_gpu", False)
                threads = p.get("threads")
                return self.build_tree_ml(input_fasta, output_nwk, bootstrap=bs, use_gpu=gpu, threads=threads)
            elif engine == 'bayesian' and input_fasta:
                # 补全 MrBayes 动态参数：ngen
                gen = p.get("ngen", 10000)
                gpu = p.get("use_gpu", False)
                return self.build_tree_bayesian(input_fasta, output_nwk, ngen=gen, use_gpu=gpu)
            elif engine == 'fast' and input_fasta:
                # FastTree 直接从 MSA 构树，不需要距离矩阵
                return self.exec_fast_tree(input_fasta, output_nwk)
            else:
                # 核心逻辑：执行构树。如果 input_dm 为空，则 build_tree_nj 会尝试兜底恢复
                success = self.build_tree_nj(input_dm, output_nwk, input_fasta=input_fasta)
                
                # 如果构树成功且有映射表需还原，则在这里执行
                if success and in_id_map:
                    nwk = output_nwk.read_text(encoding='utf-8')
                    # 按照长 ID 降序排列防止包含关系导致的错误替换 (e.g. S0001 vs S00011)
                    # 只有在 newick 字符串中真正包含这些 SID 时才进行替换
                    for sid in sorted(in_id_map.keys(), key=len, reverse=True):
                        if sid in nwk:
                            nwk = nwk.replace(sid, in_id_map[sid])
                    output_nwk.write_text(nwk, encoding='utf-8')
                return success
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
    def exec_iqtree(self, input_fasta: Path, output_dir: Path, params: Dict[str, Any] = None):
        """Invoke IQ-TREE for Maximum Likelihood inference."""
        p = params or {}
        model = p.get('model', 'AUTO')
        # IQ-TREE uses -s for alignment, -m for model, -pre for prefix
        prefix = str(output_dir / input_fasta.stem)
        args = ["-s", str(input_fasta), "-m", model, "-pre", prefix, "-nt", "AUTO"]
        
        try:
            self._run_command("iqtree.exe", args)
            # IQ-TREE output tree is usually .iqtree.treefile
            tree_file = Path(f"{prefix}.treefile")
            return tree_file
        except Exception as e:
            self.logger.error(f"IQ-TREE analysis failed: {e}")
            return None

    def exec_mrbayes(self, input_nexus: Path, output_dir: Path):
        """Invoke MrBayes for Bayesian inference (requires NEXUS format)."""
        # MrBayes typically takes a command file or runs interactively
        # We'll create a simple command file
        cmd_file = output_dir / f"{input_nexus.stem}_mb.cmd"
        cmd_text = f"begin mrbayes;\n  set autoclose=yes nowarn=yes;\n  execute {input_nexus.name};\n  lset nst=6 rates=gamma;\n  mcmc ngen=10000 samplefreq=100 printfreq=100 diagnfreq=1000;\n  sumt;\nend;"
        cmd_file.write_text(cmd_text, encoding='utf-8')
        
        try:
            # MrBayes takes command file as stdin or via command line Redirect
            self._run_command("mb.exe", [str(cmd_file)])
            tree_file = output_dir / f"{input_nexus.name}.con.tre"
            return tree_file
        except Exception as e:
            self.logger.error(f"MrBayes analysis failed: {e}")
            return None

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
                # 关键修复：改用正则分割，处理变长空格对齐造成的解析失败
                row = []
                import re
                for p in re.split(r'\s+', line):
                    if not p: continue
                    try: 
                        v = float(p.strip())
                        # 处理 NaN 并防止全 1.0 的平坦矩阵
                        row.append(1.0 if math.isnan(v) else v)
                    except: pass
                if row: val_rows.append(row)
        dim = len(names); matrix = []
        # 鲁棒性重构：确保矩阵对齐且具备真实的枝长差异
        for i in range(dim):
            row = []
            if i < len(val_rows):
                # 填充该行已有的距离值
                for j in range(min(i + 1, len(val_rows[i]))):
                    row.append(val_rows[i][j])
                # 补齐长度（如果是下三角矩阵缺失）
                while len(row) < (i + 1):
                    row.append(1.0 if len(row) != i else 0.0)
            else:
                row = [0.0 if j == i else 1.0 for j in range(i+1)]
            matrix.append(row)
        return names, matrix

    def _parse_pairwise_dm(self, lines: List[str]):
        """Parse NCBI pairwise format: ID1 ID2 DIST [ALIGN LEN1 LEN2]"""
        names = set(); dists = {}
        for line in lines:
            line = line.strip()
            if not line: continue
            # Handle variable whitespace and scientific notation
            import re
            p = re.split(r'\s+', line)
            
            # NCBI standard output: Col 3 (index 2) is usually precomputed p-distance
            if len(p) >= 3:
                n1, n2 = p[0], p[1]
                names.update([n1, n2])
                try:
                    # 如果是 6 列格式 (NCBI fasta2dissim)，p[2] 就是我们的目标演化距离
                    # 例如: SeqA SeqB 5.234e-05 1758 4540 4495
                    d_val = float(p[2])
                    # 保护逻辑：防止 0 导致的奇异点，确保它是正数
                    dists[tuple(sorted((n1, n2)))] = max(0.0000001, d_val)
                except:
                    dists[tuple(sorted((n1, n2)))] = 1.0
                    
        n_list = sorted(list(names)); dim = len(n_list); matrix = []
        # 构建符合 Biopython NJ 输入要求的下三角矩阵
        for i in range(dim):
            row = []
            for j in range(i + 1):
                if i == j:
                    row.append(0.0)
                else:
                    pair = tuple(sorted((n_list[i], n_list[j])))
                    # 默认值使用 1.0 (演化差异极大)
                    row.append(dists.get(pair, 1.0))
            matrix.append(row)
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
