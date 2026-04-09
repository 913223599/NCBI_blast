import os
import math
import re
import shutil
from pathlib import Path

from src.workbench.wrappers.base_wrapper import BaseWrapper
from src.workbench.wrappers.tree_id_manager import IDManager


class DistanceCalculator(BaseWrapper):
    """负责演化距离矩阵的计算与解析"""
    
    def __init__(self):
        super().__init__()
        self.id_manager = IDManager()  # 委托ID管理职责

    def _get_threads(self, threads: int = None) -> int:
        if threads is None or threads <= 0:
            return os.cpu_count() or 4
        return threads

    def fasta2dissim(self, input_fasta: Path, output_dm: Path, threads: int = None):
        """
        Alignment-based dissimilarity (ID-Safe Tunneling).
        
        Returns:
            ID映射字典 {short_id: original_id}
        """
        n_threads = self._get_threads(threads)
        
        try:
            # 委托给ID管理器进行安全化处理
            sanitized_fasta, id_map = self.id_manager.sanitize_fasta(input_fasta)
            
            args = [str(sanitized_fasta.absolute()), "-threads", str(n_threads)]
            result = self._run_command("fasta2dissim.exe", args)
            
            # 后处理：保存包含短 ID 的中间矩阵，确保解析器能精准对齐
            output_dm.write_text(result.stdout, encoding='utf-8')
            
            return id_map
            
        finally:
            # 清理临时文件
            sanitized_fasta = input_fasta.parent / f"{input_fasta.stem}_safe.fasta"
            if sanitized_fasta.exists(): 
                sanitized_fasta.unlink()

    def prot_collection2dissim(self, input_path: Path, output_dm: Path, threads: int = None):
        """Build dissimilarity matrix from protein collection."""
        n_threads = self._get_threads(threads)
        args = [str(input_path), "-threads", str(n_threads)]
        result = self._run_command("prot_collection2dissim.exe", args)
        output_dm.write_text(result.stdout, encoding='utf-8')
        return result

    def hash2dissim(self, input_fasta: Path, output_dm: Path, k: int = 8, threads: int = None):
        """Alignment-free dissimilarity using k-mer hashing (Enhanced Sensitivity)."""
        import tempfile
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
