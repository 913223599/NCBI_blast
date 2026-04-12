"""
DistanceCalculator - 负责演化距离矩阵的计算与解析

修复历史：
- 临时文件泄漏：统一使用 tempfile.TemporaryDirectory 上下文管理器
- 科学计数法支持：增强 float 解析，覆盖 1.23e-05 等格式
- 魔法数字消除：所有哨兵值提取为命名常量
"""
import logging
import math
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.workbench.wrappers.base_wrapper import BaseWrapper
from src.workbench.wrappers.tree_id_manager import IDManager

logger = logging.getLogger(__name__)

# ─── 命名常量 ──────────────────────────────────────
# 最小非零距离：防止距离为 0 导致的数值奇异性
MIN_NONZERO_DISTANCE = 1e-7
# 缺失距离值的默认替代（标记为"未知演化关系"）
MISSING_DISTANCE_SENTINEL = float("nan")
# NaN 替换默认值（用于工具输出中含 nan 的行）
NAN_REPLACEMENT_DEFAULT = 1.0


class DistanceCalculator(BaseWrapper):
    """负责演化距离矩阵的计算与解析"""

    def __init__(self) -> None:
        super().__init__()
        self.id_manager = IDManager()  # 委托ID管理职责

    def _get_threads(self, threads: Optional[int] = None) -> int:
        """获取可用线程数"""
        if threads is None or threads <= 0:
            return os.cpu_count() or 4
        return threads

    def fasta2dissim(
        self,
        input_fasta: Path,
        output_dm: Path,
        threads: Optional[int] = None,
    ) -> Dict[str, str]:
        """
        Alignment-based dissimilarity (ID-Safe Tunneling).

        Returns:
            ID映射字典 {short_id: original_id}
        """
        thread_count = self._get_threads(threads)
        sanitized_fasta: Optional[Path] = None

        try:
            # 委托给ID管理器进行安全化处理
            sanitized_fasta, id_map = self.id_manager.sanitize_fasta(input_fasta)

            args = [str(sanitized_fasta.absolute()), "-threads", str(thread_count)]
            result = self._run_command("fasta2dissim.exe", args)

            # 后处理：保存包含短 ID 的中间矩阵，确保解析器能精准对齐
            output_dm.write_text(result.stdout, encoding="utf-8")

            return id_map

        finally:
            # 清理临时文件（使用确定性路径计算）
            if sanitized_fasta is None:
                sanitized_fasta = input_fasta.parent / f"{input_fasta.stem}_safe.fasta"
            if sanitized_fasta.exists():
                try:
                    sanitized_fasta.unlink()
                except OSError as exc:
                    logger.warning(f"Failed to cleanup sanitized FASTA: {exc}")

    def prot_collection2dissim(
        self,
        input_path: Path,
        output_dm: Path,
        threads: Optional[int] = None,
    ):
        """Build dissimilarity matrix from protein collection."""
        thread_count = self._get_threads(threads)
        args = [str(input_path), "-threads", str(thread_count)]
        result = self._run_command("prot_collection2dissim.exe", args)
        output_dm.write_text(result.stdout, encoding="utf-8")
        return result

    def hash2dissim(
        self,
        input_fasta: Path,
        output_dm: Path,
        k: int = 8,
        threads: Optional[int] = None,
    ) -> Dict[str, str]:
        """
        Alignment-free dissimilarity using k-mer hashing (Enhanced Sensitivity).

        使用 TemporaryDirectory 上下文管理器确保临时文件在任何情况下被清理。
        """
        id_map: Dict[str, str] = {}

        # Determine optimal K (K=8 for long, K=min(4, len/2) for short)
        effective_k = k
        try:
            with open(input_fasta, "r", encoding="utf-8", errors="replace") as fobj:
                first_seq = fobj.read(5000).split("\n")[1][:100]
                min_short_seq_length = 30
                if len(first_seq) < min_short_seq_length:
                    effective_k = min(4, len(first_seq) // 2)
        except (IndexError, OSError) as exc:
            logger.debug(f"K-mer size auto-detection skipped: {exc}")

        # 使用上下文管理器确保临时目录一定被清理
        with tempfile.TemporaryDirectory(prefix="tree_hash_") as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            split_dir = temp_dir / "split"
            hash_dir = temp_dir / "hashes"
            split_dir.mkdir()
            hash_dir.mkdir()

            try:
                # 强化 IO：使用引号保护路径
                self._run_command(
                    "splitFasta.exe",
                    [str(input_fasta.absolute()), str(split_dir), "-extension", ".fasta", "-whole"],
                )
                seq_files = list(split_dir.glob("*.fasta"))
                if not seq_files:
                    raise ValueError("FASTA splitting failed: no output files produced.")

                objects: List[str] = []
                for seq_file in seq_files:
                    orig_id = seq_file.name.removesuffix(".fasta")
                    # 记录 ID 转换映射以便后续在 Newick 中还原
                    seq_id = re.sub(r"[^a-zA-Z0-9.\-_]", "_", orig_id).strip(".") or f"seq_{len(objects)}"
                    base_id = seq_id
                    counter = 1
                    while seq_id in objects:
                        seq_id = f"{base_id}_{counter}"
                        counter += 1

                    id_map[seq_id] = orig_id
                    sanitized_file = seq_file.parent / f"{seq_id}.fasta"
                    seq_file.rename(sanitized_file)
                    objects.append(seq_id)
                    self._run_command(
                        "fasta2hash.exe",
                        [str(sanitized_file), str(hash_dir / seq_id), "-kmer", str(effective_k)],
                    )

                objects_file = temp_dir / "objects.txt"
                objects_file.write_text("\n".join(objects) + "\n", encoding="utf-8")
                dm_base = output_dm.parent / output_dm.stem
                self._run_command(
                    "hash2dissim.exe",
                    [str(objects_file), str(hash_dir), str(dm_base)],
                )

                actual_dm = Path(f"{dm_base}.dm")
                if actual_dm.exists():
                    self._sanitize_dm_file(actual_dm)
                    if actual_dm.resolve() != output_dm.resolve():
                        shutil.copy(actual_dm, output_dm)

            except Exception:
                logger.error("hash2dissim pipeline failed", exc_info=True)
                raise

        return id_map

    def _sanitize_dm_file(self, dm_path: Path) -> None:
        """清理距离矩阵文件中的 NaN 值"""
        if not dm_path.exists():
            return
        try:
            content = dm_path.read_text(encoding="utf-8")
            if "nan" in content:
                new_content = content.replace("nan", str(NAN_REPLACEMENT_DEFAULT)).replace("\r\n", "\n")
                dm_path.write_text(new_content, encoding="utf-8")
                logger.warning(f"Replaced NaN values in {dm_path.name} with {NAN_REPLACEMENT_DEFAULT}")
        except OSError as exc:
            logger.error(f"Failed to sanitize DM file: {exc}")

    def _parse_dm_content(self, content: str) -> Tuple[List[str], List[List[float]]]:
        """
        统一入口：解析距离矩阵内容

        Returns:
            (名称列表, 下三角距离矩阵)
        """
        lines = content.splitlines()
        if not lines:
            return [], []
        if lines[0].startswith("OBJNUM"):
            return self._parse_matrix_dm(lines)
        return self._parse_pairwise_dm(lines)

    def _parse_matrix_dm(self, lines: List[str]) -> Tuple[List[str], List[List[float]]]:
        """解析 NCBI OBJNUM 格式的完整距离矩阵"""
        names: List[str] = []
        in_data = False
        in_values = False
        val_rows: List[List[float]] = []

        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line == "DATA":
                in_data = True
                continue
            if line.startswith("cons FULL"):
                in_data = False
                in_values = True
                continue
            if in_data:
                parts = line.split("\t")
                if parts[0]:
                    names.append(parts[0])
            elif in_values:
                row: List[float] = []
                for token in re.split(r"\s+", line):
                    if not token:
                        continue
                    try:
                        parsed_val = float(token.strip())
                        # 将 NaN 替换为默认值，防止下游算法崩溃
                        row.append(NAN_REPLACEMENT_DEFAULT if math.isnan(parsed_val) else parsed_val)
                    except ValueError:
                        logger.debug(f"Skipped non-numeric token in DM: '{token}'")
                if row:
                    val_rows.append(row)

        dim = len(names)
        matrix: List[List[float]] = []
        # 鲁棒性重构：确保矩阵对齐且具备真实的枝长差异
        for row_idx in range(dim):
            row = []
            if row_idx < len(val_rows):
                # 填充该行已有的距离值
                for col_idx in range(min(row_idx + 1, len(val_rows[row_idx]))):
                    row.append(val_rows[row_idx][col_idx])
                # 补齐长度（如果是下三角矩阵缺失）
                while len(row) < (row_idx + 1):
                    row.append(0.0 if len(row) == row_idx else NAN_REPLACEMENT_DEFAULT)
            else:
                row = [0.0 if col == row_idx else NAN_REPLACEMENT_DEFAULT for col in range(row_idx + 1)]
            matrix.append(row)
        return names, matrix

    def _parse_pairwise_dm(self, lines: List[str]) -> Tuple[List[str], List[List[float]]]:
        """
        Parse NCBI pairwise format: ID1 ID2 DIST [ALIGN LEN1 LEN2]

        增强：完整支持科学计数法（如 5.234e-05）
        """
        names: set[str] = set()
        dists: Dict[tuple, float] = {}

        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Handle variable whitespace and scientific notation
            parts = re.split(r"\s+", line)

            # NCBI standard output: Col 3 (index 2) is usually precomputed p-distance
            if len(parts) >= 3:
                name_1, name_2 = parts[0], parts[1]
                names.update([name_1, name_2])
                try:
                    # 如果是 6 列格式 (NCBI fasta2dissim)，p[2] 就是我们的目标演化距离
                    # 例如: SeqA SeqB 5.234e-05 1758 4540 4495
                    distance_val = float(parts[2])
                    if math.isnan(distance_val) or math.isinf(distance_val):
                        logger.warning(
                            f"Invalid distance value ({parts[2]}) between "
                            f"{name_1} and {name_2}, using sentinel"
                        )
                        parsed_distance = NAN_REPLACEMENT_DEFAULT
                    else:
                        # 保护逻辑：防止 0 导致的奇异点，确保它是正数
                        parsed_distance = max(MIN_NONZERO_DISTANCE, distance_val)
                    dists[tuple(sorted((name_1, name_2)))] = parsed_distance
                except ValueError:
                    logger.warning(
                        f"Failed to parse distance '{parts[2]}' between "
                        f"{name_1} and {name_2}, using sentinel"
                    )
                    dists[tuple(sorted((name_1, name_2)))] = NAN_REPLACEMENT_DEFAULT

        sorted_names = sorted(list(names))
        dim = len(sorted_names)
        matrix: List[List[float]] = []
        # 构建符合 Biopython NJ 输入要求的下三角矩阵
        for row_idx in range(dim):
            row: List[float] = []
            for col_idx in range(row_idx + 1):
                if row_idx == col_idx:
                    row.append(0.0)
                else:
                    pair = tuple(sorted((sorted_names[row_idx], sorted_names[col_idx])))
                    distance = dists.get(pair)
                    if distance is None:
                        logger.warning(
                            f"Missing distance for pair ({sorted_names[row_idx]}, "
                            f"{sorted_names[col_idx]}), using sentinel {NAN_REPLACEMENT_DEFAULT}"
                        )
                        row.append(NAN_REPLACEMENT_DEFAULT)
                    else:
                        row.append(distance)
            matrix.append(row)
        return sorted_names, matrix
