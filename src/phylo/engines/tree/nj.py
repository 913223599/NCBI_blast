# -*- coding: utf-8 -*-
"""
NJBioNJEngine - 向量化 Neighbor-Joining / BioNJ 构树及分片落盘 Bootstrap 引擎
"""
import csv
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

import numpy as np

from ...models.errors import InvalidInputError, PhyloCancelledError
from ...runtime.resource_guard import GpuGuard, get_safe_cpu_budget
from ..distance.matrix_gpu import DistanceMatrixCalculator, encode_alignment

logger = logging.getLogger("phylo.nj")

GPU_TREE_MIN_TAXA = 64
GPU_TREE_MIN_FREE_VRAM_MB = 512


@dataclass
class _Node:
    name: Optional[str] = None
    length: float = 0.0
    children: List["_Node"] = field(default_factory=list)
    support: Optional[float] = None


def _node_to_newick(node: _Node, is_root: bool = True) -> str:
    if not node.children:
        label = node.name or ""
        return f"{label}:{max(0.0, node.length):.6f}" if not is_root else label

    inner = ",".join(_node_to_newick(c, is_root=False) for c in node.children)
    sup = ""
    if not is_root and node.support is not None:
        sup = str(round(node.support))
    if is_root:
        return f"({inner}){sup};"
    return f"({inner}){sup}:{max(0.0, node.length):.6f}"


def should_use_cuda_for_tree(n: int, use_gpu: bool) -> bool:
    """判定当前矩阵规模与空闲显存是否适合启用 PyTorch CUDA 聚类加速。"""
    if not use_gpu or n < GPU_TREE_MIN_TAXA:
        return False
    gpu_info = GpuGuard.probe()
    if not gpu_info.get("available"):
        return False
    free_vram_mb = int(gpu_info.get("free_vram_mb", 0))
    if free_vram_mb < GPU_TREE_MIN_FREE_VRAM_MB:
        return False
    est_bytes = 3 * 8 * n * n + n * n
    budget_bytes = int(free_vram_mb * 0.4 * 1024 * 1024)
    return est_bytes <= budget_bytes


def _build_upgma_tree_cuda(ids: List[str], dist_matrix: np.ndarray) -> _Node:
    """PyTorch CUDA 原地槽位复用加速 UPGMA 超度量聚类。"""
    import torch

    n = len(ids)
    if n < 3:
        raise InvalidInputError(f"距离法构树至少需要 3 条序列，当前仅 {n} 条。")

    D_np = np.array(dist_matrix, dtype=np.float64, copy=True)
    D_np = 0.5 * (D_np + D_np.T)
    D_np = np.maximum(0.0, D_np)
    np.fill_diagonal(D_np, np.inf)

    nodes: List[_Node] = [_Node(name=sid) for sid in ids]
    sizes: List[int] = [1] * n
    heights: List[float] = [0.0] * n

    device = torch.device("cuda")
    D: Any = None
    active: Any = None
    rem: Any = None
    d_new: Any = None

    try:
        with torch.no_grad():
            D = torch.from_numpy(D_np).to(device=device, dtype=torch.float64)
            active = torch.ones(n, dtype=torch.bool, device=device)

            for step in range(n - 1):
                flat_idx = int(torch.argmin(D).item())
                i, j = divmod(flat_idx, n)
                if i > j:
                    i, j = j, i

                d_ij = float(D[i, j].item())
                new_height = max(heights[i], heights[j], 0.5 * d_ij)
                nodes[i].length = max(0.0, new_height - heights[i])
                nodes[j].length = max(0.0, new_height - heights[j])
                merged = _Node(children=[nodes[i], nodes[j]])

                w_i = float(sizes[i])
                w_j = float(sizes[j])
                nodes[i] = merged
                sizes[i] = sizes[i] + sizes[j]
                heights[i] = new_height
                active[j] = False

                if step < n - 2:
                    rem = active.clone()
                    rem[i] = False
                    d_new = torch.clamp((w_i * D[i, rem] + w_j * D[j, rem]) / (w_i + w_j), min=0.0)
                    D[i, :] = float("inf")
                    D[:, i] = float("inf")
                    D[i, rem] = d_new
                    D[rem, i] = d_new
                    D[j, :] = float("inf")
                    D[:, j] = float("inf")

            root_idx = int(torch.nonzero(active, as_tuple=False).flatten()[0].item())
            return nodes[root_idx]
    finally:
        del D, active, rem, d_new
        GpuGuard.release_vram()


def _build_nj_bionj_tree_cuda(
    ids: List[str],
    dist_matrix: np.ndarray,
    use_bionj: bool,
) -> _Node:
    """PyTorch CUDA 原地槽位复用加速 Neighbor-Joining / BioNJ 聚类。"""
    import torch

    n = len(ids)
    if n < 3:
        raise InvalidInputError(f"距离法构树至少需要 3 条序列，当前仅 {n} 条。")

    D_np = np.array(dist_matrix, dtype=np.float64, copy=True)
    D_np = 0.5 * (D_np + D_np.T)
    np.fill_diagonal(D_np, 0.0)

    nodes: List[_Node] = [_Node(name=sid) for sid in ids]
    device = torch.device("cuda")
    D: Any = None
    V: Any = None
    Q: Any = None
    row_sums: Any = None
    active: Any = None
    invalid_mask: Any = None
    rem: Any = None
    d_new: Any = None
    v_new: Any = None

    try:
        with torch.no_grad():
            D = torch.from_numpy(D_np).to(device=device, dtype=torch.float64)
            V = D.clone() if use_bionj else None
            active = torch.ones(n, dtype=torch.bool, device=device)
            invalid_mask = torch.eye(n, dtype=torch.bool, device=device)
            active_count = n

            while active_count > 3:
                row_sums = D.sum(dim=1)
                Q = (active_count - 2) * D - row_sums.unsqueeze(1) - row_sums.unsqueeze(0)
                Q.masked_fill_(invalid_mask, float("inf"))

                flat_idx = int(torch.argmin(Q).item())
                i, j = divmod(flat_idx, n)
                if i > j:
                    i, j = j, i

                d_ij = float(D[i, j].item())
                rs_i = float(row_sums[i].item())
                rs_j = float(row_sums[j].item())
                if abs(d_ij) < 1e-12:
                    len_i = 0.0
                    len_j = 0.0
                else:
                    len_i = 0.5 * d_ij + (rs_i - rs_j) / (2.0 * (active_count - 2))
                    len_j = d_ij - len_i

                len_i = max(0.0, len_i)
                len_j = max(0.0, len_j)

                node_i = nodes[i]
                node_j = nodes[j]
                node_i.length = len_i
                node_j.length = len_j
                nodes[i] = _Node(children=[node_i, node_j])

                active[j] = False
                rem = active.clone()
                rem[i] = False

                v_ij = 0.0
                if V is not None:
                    v_ij = float(V[i, j].item())
                    if v_ij <= 1e-12:
                        lam = 0.5
                    else:
                        v_diff = float((V[j, rem] - V[i, rem]).sum().item())
                        lam = max(0.0, min(1.0, 0.5 + v_diff / (2.0 * (active_count - 2) * v_ij)))
                else:
                    lam = 0.5

                d_new = torch.clamp(lam * (D[i, rem] - len_i) + (1.0 - lam) * (D[j, rem] - len_j), min=0.0)
                D[i, :] = 0.0
                D[:, i] = 0.0
                D[j, :] = 0.0
                D[:, j] = 0.0
                D[i, rem] = d_new
                D[rem, i] = d_new

                if V is not None:
                    v_new = torch.clamp(
                        lam * V[i, rem] + (1.0 - lam) * V[j, rem] - lam * (1.0 - lam) * v_ij,
                        min=0.0,
                    )
                    V[i, :] = 0.0
                    V[:, i] = 0.0
                    V[j, :] = 0.0
                    V[:, j] = 0.0
                    V[i, rem] = v_new
                    V[rem, i] = v_new

                invalid_mask[j, :] = True
                invalid_mask[:, j] = True
                active_count -= 1

            rem_indices = [int(x) for x in torch.nonzero(active, as_tuple=False).flatten().tolist()]
            a, b, c = rem_indices[0], rem_indices[1], rem_indices[2]
            d_ab = float(D[a, b].item())
            d_ac = float(D[a, c].item())
            d_bc = float(D[b, c].item())
            nodes[a].length = max(0.0, 0.5 * (d_ab + d_ac - d_bc))
            nodes[b].length = max(0.0, 0.5 * (d_ab + d_bc - d_ac))
            nodes[c].length = max(0.0, 0.5 * (d_ac + d_bc - d_ab))
            return _Node(children=[nodes[a], nodes[b], nodes[c]])
    finally:
        del D, V, Q, row_sums, active, invalid_mask, rem, d_new, v_new
        GpuGuard.release_vram()


def build_upgma_tree_from_distance_matrix(
    ids: List[str],
    dist_matrix: np.ndarray,
    use_gpu: bool = False,
) -> _Node:
    """
    向量化实现 UPGMA（超度量算数平均聚类）：
    当满足显存与规模条件且 use_gpu=True 时启用 PyTorch CUDA 加速，否则走 NumPy CPU。
    保证所有叶节点到根节点的路径高度相等，适合千株级 ViPTree 风格环形外缘齐平可视化。
    """
    n = len(ids)
    if n < 3:
        raise InvalidInputError(f"距离法构树至少需要 3 条序列，当前仅 {n} 条。")

    if should_use_cuda_for_tree(n, use_gpu):
        try:
            return _build_upgma_tree_cuda(ids, dist_matrix)
        except Exception as exc:
            logger.warning(f"CUDA UPGMA 聚类回退至 NumPy CPU 引擎: {exc}")
            GpuGuard.release_vram()

    D = np.array(dist_matrix, dtype=np.float64, copy=True)
    D = 0.5 * (D + D.T)
    D = np.maximum(0.0, D)
    np.fill_diagonal(D, 0.0)

    nodes: List[_Node] = [_Node(name=sid) for sid in ids]
    sizes: List[int] = [1] * n
    heights: List[float] = [0.0] * n

    while len(nodes) > 1:
        r = len(nodes)
        Q = D.copy()
        np.fill_diagonal(Q, np.inf)
        flat_idx = int(np.argmin(Q))
        i, j = divmod(flat_idx, r)
        if i > j:
            i, j = j, i

        d_ij = float(D[i, j])
        new_height = max(heights[i], heights[j], 0.5 * d_ij)
        nodes[i].length = max(0.0, new_height - heights[i])
        nodes[j].length = max(0.0, new_height - heights[j])
        merged = _Node(children=[nodes[i], nodes[j]])

        mask = np.ones(r, dtype=bool)
        mask[i] = False
        mask[j] = False

        if r == 2:
            nodes = [merged]
            break

        w_i = float(sizes[i])
        w_j = float(sizes[j])
        d_new = (w_i * D[i, mask] + w_j * D[j, mask]) / (w_i + w_j)
        d_new = np.maximum(0.0, d_new)

        rem_nodes = [nodes[idx] for idx in range(r) if mask[idx]]
        rem_nodes.append(merged)
        rem_sizes = [sizes[idx] for idx in range(r) if mask[idx]]
        rem_sizes.append(sizes[i] + sizes[j])
        rem_heights = [heights[idx] for idx in range(r) if mask[idx]]
        rem_heights.append(new_height)

        D_sub = D[np.ix_(mask, mask)]
        D_next = np.zeros((r - 1, r - 1), dtype=np.float64)
        D_next[:-1, :-1] = D_sub
        D_next[:-1, -1] = d_new
        D_next[-1, :-1] = d_new
        D = D_next
        nodes = rem_nodes
        sizes = rem_sizes
        heights = rem_heights

    return nodes[0]


def build_tree_from_distance_matrix(
    ids: List[str],
    dist_matrix: np.ndarray,
    method: str = "bionj",
    use_gpu: bool = False,
) -> _Node:
    """
    向量化实现 Neighbor-Joining (nj)、BioNJ (bionj) 与 UPGMA (upgma)。
    大规模矩阵在 use_gpu=True 且显存充裕时自动使用 PyTorch CUDA 加速。
    对极小负枝长做非负钳位，返回树根节点 _Node。
    """
    norm_method = method.lower().strip()
    if norm_method == "upgma":
        return build_upgma_tree_from_distance_matrix(ids, dist_matrix, use_gpu=use_gpu)
    n = len(ids)
    if n < 3:
        raise InvalidInputError(f"距离法构树至少需要 3 条序列，当前仅 {n} 条。")

    use_bionj = norm_method == "bionj"
    if should_use_cuda_for_tree(n, use_gpu):
        try:
            return _build_nj_bionj_tree_cuda(ids, dist_matrix, use_bionj=use_bionj)
        except Exception as exc:
            logger.warning(f"CUDA {norm_method.upper()} 聚类回退至 NumPy CPU 引擎: {exc}")
            GpuGuard.release_vram()

    D = np.array(dist_matrix, dtype=np.float64, copy=True)
    D = 0.5 * (D + D.T)
    np.fill_diagonal(D, 0.0)
    V = D.copy()  # BioNJ 初始方差等于距离矩阵

    nodes: List[_Node] = [_Node(name=sid) for sid in ids]

    while len(nodes) > 3:
        r = len(nodes)
        row_sums = D.sum(axis=1)
        # Q_ij = (r - 2) * D_ij - row_sums[i] - row_sums[j]
        Q = (r - 2) * D - row_sums[:, None] - row_sums[None, :]
        np.fill_diagonal(Q, np.inf)

        flat_idx = int(np.argmin(Q))
        i, j = divmod(flat_idx, r)
        if i > j:
            i, j = j, i

        d_ij = D[i, j]
        if abs(d_ij) < 1e-12:
            len_i = 0.0
            len_j = 0.0
        else:
            len_i = 0.5 * d_ij + (row_sums[i] - row_sums[j]) / (2.0 * (r - 2))
            len_j = d_ij - len_i

        len_i = max(0.0, float(len_i))
        len_j = max(0.0, float(len_j))

        node_i = nodes[i]
        node_j = nodes[j]
        node_i.length = len_i
        node_j.length = len_j
        merged = _Node(children=[node_i, node_j])

        # 计算新节点到其余节点 k 的距离与方差
        mask = np.ones(r, dtype=bool)
        mask[i] = False
        mask[j] = False

        if use_bionj:
            v_ij = V[i, j]
            if v_ij <= 1e-12:
                lam = 0.5
            else:
                v_diff = (V[j, mask] - V[i, mask]).sum()
                lam = 0.5 + v_diff / (2.0 * (r - 2) * v_ij)
                lam = float(np.clip(lam, 0.0, 1.0))
        else:
            lam = 0.5

        d_new = lam * (D[i, mask] - len_i) + (1.0 - lam) * (D[j, mask] - len_j)
        d_new = np.maximum(0.0, d_new)

        # 缩减矩阵（保留 mask 部分并在末尾追加新节点）
        rem_nodes = [nodes[idx] for idx in range(r) if mask[idx]]
        rem_nodes.append(merged)

        D_sub = D[np.ix_(mask, mask)]
        D_next = np.zeros((r - 1, r - 1), dtype=np.float64)
        D_next[:-1, :-1] = D_sub
        D_next[:-1, -1] = d_new
        D_next[-1, :-1] = d_new
        D = D_next

        if use_bionj:
            v_new = lam * V[i, mask] + (1.0 - lam) * V[j, mask] - lam * (1.0 - lam) * V[i, j]
            v_new = np.maximum(0.0, v_new)
            V_sub = V[np.ix_(mask, mask)]
            V_next = np.zeros((r - 1, r - 1), dtype=np.float64)
            V_next[:-1, :-1] = V_sub
            V_next[:-1, -1] = v_new
            V_next[-1, :-1] = v_new
            V = V_next

        nodes = rem_nodes

    # 最后 3 个节点做三叉无根合并
    l0 = max(0.0, float(0.5 * (D[0, 1] + D[0, 2] - D[1, 2])))
    l1 = max(0.0, float(0.5 * (D[0, 1] + D[1, 2] - D[0, 2])))
    l2 = max(0.0, float(0.5 * (D[0, 2] + D[1, 2] - D[0, 1])))
    nodes[0].length = l0
    nodes[1].length = l1
    nodes[2].length = l2
    root = _Node(children=[nodes[0], nodes[1], nodes[2]])
    return root


def _canonical_split_bitmask(mask: int, total: int, full_mask: int) -> Optional[int]:
    """将非平凡二分划（2 <= size <= total - 2）规范化为对称最小位掩码。"""
    cnt = mask.bit_count()
    if cnt <= 1 or cnt >= total - 1:
        return None
    comp = full_mask ^ mask
    return min(mask, comp)


def _parse_newick_leaves_splits(
    newick: str,
    bit_by_id: Dict[str, int],
    full_mask: int,
) -> Set[int]:
    """从短 ID Newick 字符串快速提取所有规范化整数 bitmask 二分划。"""
    s = newick.strip().rstrip(";")
    idx = 0
    n_chars = len(s)
    total = len(bit_by_id)
    splits: Set[int] = set()

    def _parse() -> int:
        nonlocal idx
        has_children = False
        sub_mask = 0
        if idx < n_chars and s[idx] == "(":
            has_children = True
            idx += 1
            while idx < n_chars:
                sub_mask |= _parse()
                if idx < n_chars and s[idx] == ",":
                    idx += 1
                elif idx < n_chars and s[idx] == ")":
                    idx += 1
                    break
                else:
                    break
        start = idx
        while idx < n_chars and s[idx] not in "(),:;":
            idx += 1
        label = s[start:idx].strip()
        if not has_children and label:
            sub_mask |= bit_by_id.get(label, 0)
        if idx < n_chars and s[idx] == ":":
            idx += 1
            while idx < n_chars and s[idx] not in "(),;":
                idx += 1
        if has_children:
            canon = _canonical_split_bitmask(sub_mask, total, full_mask)
            if canon is not None:
                splits.add(canon)
        return sub_mask

    _parse()
    return splits


def compute_bipartition_support(main_root: _Node, replicate_newicks: List[str]) -> _Node:
    """使用整数 bitmask 统计主树每个内部节点二分划在重采样树中出现的支持率 (0~100)。"""
    if not replicate_newicks:
        return main_root

    ordered_leaves: List[str] = []

    def _index_leaves(node: _Node) -> None:
        if not node.children:
            if node.name:
                ordered_leaves.append(node.name)
            return
        for c in node.children:
            _index_leaves(c)

    _index_leaves(main_root)
    bit_by_id: Dict[str, int] = {name: (1 << i) for i, name in enumerate(ordered_leaves)}
    total = len(bit_by_id)
    full_mask = (1 << total) - 1

    split_counts: Dict[int, int] = {}
    for rep_nwk in replicate_newicks:
        for sp in _parse_newick_leaves_splits(rep_nwk, bit_by_id, full_mask):
            split_counts[sp] = split_counts.get(sp, 0) + 1

    n_reps = len(replicate_newicks)

    def _assign(node: _Node, is_root: bool = True) -> int:
        if not node.children:
            return bit_by_id.get(node.name or "", 0)
        sub_mask = 0
        for c in node.children:
            sub_mask |= _assign(c, is_root=False)
        if not is_root:
            canon = _canonical_split_bitmask(sub_mask, total, full_mask)
            if canon is not None:
                cnt = split_counts.get(canon, 0)
                node.support = round(100.0 * cnt / n_reps, 1)
        return sub_mask

    _assign(main_root, is_root=True)
    return main_root


class NJBioNJEngine:
    """支持单次构树与分片落盘并行 Bootstrap 的 NJ / BioNJ 引擎。"""

    def __init__(
        self,
        cancel_event: Optional[threading.Event] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.cancel_event = cancel_event or threading.Event()
        self.on_log = on_log

    def _log(self, msg: str) -> None:
        logger.info(msg)
        if self.on_log:
            try:
                self.on_log(msg)
            except Exception as _exc:
                logger.debug("NJBioNJEngine._log 忽略非致命异常: %s", _exc)

    @staticmethod
    def save_distance_csv(ids: List[str], matrix: np.ndarray, csv_path: Path) -> Path:
        """将演化距离矩阵持久化为标准 UTF-8 CSV 表格。"""
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with open(csv_path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["Taxon"] + ids)
            for row_id, row_vals in zip(ids, matrix, strict=True):
                writer.writerow([row_id] + [f"{float(v):.6f}" for v in row_vals])
        return csv_path

    def build_from_matrix(
        self,
        ids: List[str],
        matrix: np.ndarray,
        output_nwk: Path,
        method: str = "bionj",
        use_gpu: bool = False,
    ) -> Path:
        if self.cancel_event.is_set():
            raise PhyloCancelledError("NJ/BioNJ 建树前任务已取消")
        will_cuda = should_use_cuda_for_tree(len(ids), use_gpu)
        cluster_backend = "PyTorch CUDA" if will_cuda else "NumPy CPU"
        self._log(f"[{method.upper()}] 矩阵聚类引擎: {cluster_backend} (N={len(ids)})")
        root = build_tree_from_distance_matrix(ids, matrix, method=method, use_gpu=use_gpu)
        nwk = _node_to_newick(root, is_root=True)
        output_nwk.parent.mkdir(parents=True, exist_ok=True)
        output_nwk.write_text(nwk + "\n", encoding="utf-8")
        return output_nwk

    def build_from_msa(
        self,
        msa_fasta: Path,
        output_nwk: Path,
        work_dir: Path,
        mol_type: str = "dna",
        model: str = "jc69",
        method: str = "bionj",
        bootstrap: int = 100,
        threads: int = 0,
        use_gpu: bool = True,
        dist_matrix_npy: Optional[Path] = None,
        dist_matrix_csv: Optional[Path] = None,
        id_map: Optional[Dict[str, str]] = None,
    ) -> Path:
        if self.cancel_event.is_set():
            raise PhyloCancelledError("NJ/BioNJ 建树前任务已取消")

        ids, encoded = encode_alignment(msa_fasta, mol_type=mol_type)
        n_seqs, seq_len = encoded.shape
        calc = DistanceMatrixCalculator(use_gpu=use_gpu, cancel_event=self.cancel_event)
        backend_label = "PyTorch CUDA" if calc.cuda_enabled else "NumPy Vectorized"
        self._log(f"[{method.upper()}] 距离矩阵计算引擎: {backend_label} (N={n_seqs}, L={seq_len}, model={model})")

        main_dist = calc.compute(encoded, mol_type=mol_type, model=model)
        if dist_matrix_csv is not None:
            from ..distance.mash import MashDistanceEngine

            MashDistanceEngine.save_matrix_artifacts(
                ids=ids,
                matrix=main_dist,
                id_map=id_map or {},
                npy_path=dist_matrix_npy or (work_dir / "distance_matrix.npy"),
                csv_path=dist_matrix_csv,
                ids_json_path=work_dir / "distance_ids.json",
            )
        elif dist_matrix_npy is not None:
            dist_matrix_npy.parent.mkdir(parents=True, exist_ok=True)
            np.save(str(dist_matrix_npy), main_dist)

        will_tree_cuda = should_use_cuda_for_tree(n_seqs, use_gpu)
        self._log(f"[{method.upper()}] 主树矩阵聚类引擎: {'PyTorch CUDA' if will_tree_cuda else 'NumPy CPU'} (N={n_seqs})")
        main_root = build_tree_from_distance_matrix(ids, main_dist, method=method, use_gpu=use_gpu)

        if bootstrap > 0 and n_seqs >= 4:
            safe_threads = get_safe_cpu_budget(threads)
            rep_file = work_dir / "bootstrap_replicates.nwk"
            existing_reps: List[str] = []
            if rep_file.exists():
                existing_reps = [
                    line.strip()
                    for line in rep_file.read_text(encoding="utf-8", errors="ignore").splitlines()
                    if line.strip()
                ]
            remaining = max(0, bootstrap - len(existing_reps))
            if existing_reps:
                self._log(f"[{method.upper()}] 检测到历史 Bootstrap 断点: 已完成 {len(existing_reps)}/{bootstrap} 次")

            rng = np.random.default_rng(42 + len(existing_reps))
            batch_size = 20 if calc.cuda_enabled else 16
            probs = np.full(seq_len, 1.0 / seq_len, dtype=np.float64)

            while remaining > 0:
                if self.cancel_event.is_set():
                    raise PhyloCancelledError("Bootstrap 重采样过程已终止")
                cur_batch = min(batch_size, remaining)
                weights_batch = [
                    rng.multinomial(seq_len, probs).astype(np.float32) for _ in range(cur_batch)
                ]
                rep_matrices = calc.compute_batch(
                    encoded, mol_type=mol_type, model=model, weights_batch=weights_batch  # type: ignore[arg-type]
                )

                def _build_rep(mat: np.ndarray) -> str:
                    r_node = build_tree_from_distance_matrix(ids, mat, method=method)
                    return _node_to_newick(r_node, is_root=True)

                with ThreadPoolExecutor(max_workers=min(safe_threads, cur_batch)) as pool:
                    batch_nwks = list(pool.map(_build_rep, rep_matrices))

                # 分片落盘，绝不囤积内存
                with open(rep_file, "a", encoding="utf-8", newline="\n") as fh:
                    for nwk in batch_nwks:
                        fh.write(nwk + "\n")
                existing_reps.extend(batch_nwks)
                remaining -= cur_batch
                self._log(f"[{method.upper()}] Bootstrap 进度: {len(existing_reps)}/{bootstrap}")

            compute_bipartition_support(main_root, existing_reps[:bootstrap])

        final_nwk = _node_to_newick(main_root, is_root=True)
        output_nwk.parent.mkdir(parents=True, exist_ok=True)
        output_nwk.write_text(final_nwk + "\n", encoding="utf-8")
        return output_nwk
