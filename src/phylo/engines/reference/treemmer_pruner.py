# -*- coding: utf-8 -*-
"""
TreemmerPruner - 基于系统发育冗余度的代表性降采样器
当参考集去冗余后仍偏大（如 > 80~300 条）时，按 Treemmer 算法迭代修剪距离最短的冗余叶对，
并严格保护查询株、外群及每个目标属保底代表不被剔除。
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Set, Tuple

from ...core.fasta_io import iter_fasta_records
from ...models.schemas import ReferenceCandidate
from ...runtime.process_runner import ProcessRunner
from ...runtime.tool_registry import get_tool_registry
from ..distance.mash import MashDistanceEngine
from ..tree.nj import NJBioNJEngine

if TYPE_CHECKING:
    from ...pipeline.postprocess import PhyloNode

logger = logging.getLogger("phylo.treemmer")


class TreemmerPruner:
    """Treemmer 代表性亚集降采样引擎（支持官方 CLI 优先与纯 Python 等效算法）。"""

    def __init__(
        self,
        cancel_event: Optional[threading.Event] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.cancel_event = cancel_event or threading.Event()
        self.on_log = on_log
        self.registry = get_tool_registry()
        self.runner = ProcessRunner(
            cancel_event=self.cancel_event,
            on_log=self.on_log,
            wsl_distro=self.registry.wsl_distro or "Ubuntu",
        )

    def terminate_active(self) -> None:
        self.runner.terminate_active()

    def _log(self, msg: str) -> None:
        logger.info(msg)
        if self.on_log:
            try:
                self.on_log(msg)
            except Exception as _exc:
                logger.debug("TreemmerPruner 日志回调执行失败: %s", _exc)

    def prune_if_needed(
        self,
        genome_paths: Dict[str, Path],
        candidates: List[ReferenceCandidate],
        work_dir: Path,
        target_count: int = 80,
        threads: int = 0,
    ) -> Tuple[Dict[str, Path], Dict[str, str | int]]:
        if len(genome_paths) <= target_count:
            return dict(genome_paths), {
                "before": len(genome_paths),
                "after": len(genome_paths),
                "removed": 0,
                "tool": "not_needed",
            }

        cand_map = {c.accession: c for c in candidates}
        protected: Set[str] = {
            acc for acc, c in cand_map.items() if c.role in ("query", "outgroup")
        }
        # 保护每个属至少 1 条代表
        seen_genera: Set[str] = set()
        for acc in genome_paths:
            c = cand_map.get(acc)
            if c and c.is_ictv_classified and c.genus and c.genus not in seen_genera:
                seen_genera.add(c.genus)
                protected.add(acc)

        if len(protected) >= target_count:
            target_count = len(protected) + 5

        # 1. 构建快速 Mash + BioNJ 引导树（统一使用纯 ASCII 短键避免中文/特殊字符在 Mash/Newick/Treemmer CLI 中截断）
        acc_to_ascii: Dict[str, str] = {acc: f"TM{idx:04d}" for idx, acc in enumerate(genome_paths, start=1)}
        ascii_to_acc: Dict[str, str] = {v: k for k, v in acc_to_ascii.items()}
        protected_ascii: Set[str] = {acc_to_ascii[a] for a in protected if a in acc_to_ascii}

        pruner_dir = work_dir / "treemmer_guide"
        pruner_dir.mkdir(parents=True, exist_ok=True)
        combined = pruner_dir / "guide_genomes.fasta"
        with open(combined, "w", encoding="utf-8", newline="\n") as out_fh:
            for acc, fpath in genome_paths.items():
                seq_parts = [str(r.seq).strip().upper() for r in iter_fasta_records(fpath)]
                merged = "".join(seq_parts)
                out_fh.write(f">{acc_to_ascii[acc]}\n")
                for pos in range(0, len(merged), 80):
                    out_fh.write(merged[pos : pos + 80] + "\n")

        mash = MashDistanceEngine(cancel_event=self.cancel_event, on_log=self.on_log)
        labels, mat = mash.compute_distance_matrix(
            combined, pruner_dir, kmer=21, sketch_size=1000, threads=threads
        )
        nj = NJBioNJEngine(cancel_event=self.cancel_event, on_log=self.on_log)
        guide_nwk = pruner_dir / "guide.nwk"
        nj.build_from_matrix(labels, mat, guide_nwk, method="bionj")
        nwk_text = guide_nwk.read_text(encoding="utf-8")

        # 2. 若外部 Treemmer CLI 可用则调用
        treemmer_desc = self.registry.get("treemmer")
        if treemmer_desc.available:
            cli_kept_ascii = self._try_run_treemmer_cli(
                treemmer_desc.path, guide_nwk, protected_ascii, pruner_dir, target_count
            )
            if cli_kept_ascii is not None:
                cli_kept = {ascii_to_acc[k] for k in cli_kept_ascii if k in ascii_to_acc}
                kept = {acc: genome_paths[acc] for acc in genome_paths if acc in cli_kept}
                for acc, cand in cand_map.items():
                    if acc in genome_paths and acc not in cli_kept:
                        cand.selected = False
                return kept, {
                    "before": len(genome_paths),
                    "after": len(kept),
                    "removed": len(genome_paths) - len(kept),
                    "tool": "Treemmer CLI",
                }

        # 3. 执行纯 Python 迭代修剪等效算法
        kept_ascii = self.prune_newick_leaves(nwk_text, target_count=target_count, protected=protected_ascii)
        kept_accs = {ascii_to_acc[k] for k in kept_ascii if k in ascii_to_acc}
        kept = {acc: genome_paths[acc] for acc in genome_paths if acc in kept_accs}
        for acc, cand in cand_map.items():
            if acc in genome_paths and acc not in kept_accs:
                cand.selected = False

        stats = {
            "before": len(genome_paths),
            "after": len(kept),
            "removed": len(genome_paths) - len(kept),
            "tool": "Treemmer-Equiv",
        }
        self._log(f"[Treemmer] 降采样完成 ({stats['tool']}): {stats['before']} -> {stats['after']} 条。")
        return kept, stats

    def _try_run_treemmer_cli(
        self,
        treemmer_bin: str,
        guide_nwk: Path,
        protected: Set[str],
        work_dir: Path,
        target_count: int,
    ) -> Optional[Set[str]]:
        from src.assembly.env.wsl_manager import WSLManager

        lp_file = work_dir / "protected_leaves.txt"
        with open(lp_file, "w", encoding="utf-8", newline="\n") as fh:
            for acc in sorted(protected):
                fh.write(f"{acc}\n")

        cmd = [
            treemmer_bin,
            WSLManager.to_wsl_path(str(guide_nwk.resolve())),
            "-X",
            str(target_count),
            "-lp",
            WSLManager.to_wsl_path(str(lp_file.resolve())),
        ]
        res = self.runner.run_wsl(cmd)
        trimmed_list = Path(f"{guide_nwk}_trimmed_list_X_{target_count}")
        if res.returncode == 0 and trimmed_list.is_file():
            kept = {
                line.strip()
                for line in trimmed_list.read_text(encoding="utf-8", errors="replace").splitlines()
                if line.strip()
            }
            kept.update(protected)
            return kept
        return None

    @staticmethod
    def prune_newick_leaves(
        newick: str,
        target_count: int,
        protected: Optional[Set[str]] = None,
    ) -> Set[str]:
        """
        基于引导树拓扑距离的 Treemmer 等效迭代裁剪：
        每次寻找具有共同亲本（cherry / 最近姊妹对）的叶子中枝长最短的非保护叶节点进行修剪，
        并将退化的度为 2 内部节点折叠合并枝长，直至达到目标条数或无更多可修剪非保护叶。
        """
        from ...pipeline.postprocess import parse_newick

        prot = set(protected or ())
        root = parse_newick(newick)

        def _collect_leaves(node: PhyloNode) -> List[PhyloNode]:
            out: List[PhyloNode] = []
            stack = [node]
            while stack:
                cur = stack.pop()
                if cur.is_leaf:
                    out.append(cur)
                else:
                    stack.extend(cur.children)
            return out

        def _remove_leaf(leaf: PhyloNode) -> None:
            p = leaf.parent
            if p is None:
                return
            if leaf in p.children:
                p.children.remove(leaf)
            # 若父节点仅剩 1 个子节点且非根，折叠保持总枝长
            if len(p.children) == 1 and p.parent is not None:
                gp = p.parent
                only = p.children[0]
                only.length += p.length
                only.parent = gp
                idx = gp.children.index(p)
                gp.children[idx] = only

        while True:
            leaves = _collect_leaves(root)
            if len(leaves) <= target_count:
                break

            # 计算每个非保护叶子到最近兄弟叶子的局部冗余距离
            best_victim: Optional[PhyloNode] = None
            best_score = float("inf")

            for leaf in leaves:
                if leaf.name in prot or leaf.parent is None:
                    continue
                siblings = [c for c in leaf.parent.children if c is not leaf]
                # 优先从包含叶子的 cherry 中找短枝修剪
                sib_leaf_dists = [
                    leaf.length + s.length for s in siblings if s.is_leaf
                ]
                if sib_leaf_dists:
                    score = leaf.length + min(sib_leaf_dists) * 0.1
                else:
                    score = leaf.length + 1e3
                if score < best_score:
                    best_score = score
                    best_victim = leaf

            if best_victim is None:
                break
            _remove_leaf(best_victim)

        return {lf.name for lf in _collect_leaves(root)}
