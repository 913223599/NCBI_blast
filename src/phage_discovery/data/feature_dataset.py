# -*- coding: utf-8 -*-
"""
基准格式数据目录 -> 窗口特征矩阵（多核并行 + 分片落盘 + 断点跳过）

输入：chimera_builder 产出的 split 目录（含 benchmark_manifest.json，
     `{split}_windows.fna/_truth.tsv` 与 `{split}_chimeras.fna/_truth.tsv/_contigs.tsv`）。
输出：`<out_dir>/{split}_{part}.npz`，part ∈ {windows, chimeras}，字段：
  features (N, F) float32 / labels (N,) int8（1 正、0 负、-1 边界模糊不参与训练）/
  overlap (N,) / contig_ids (N,) / starts / ends / source (0=独立窗口, 1=嵌合体滑窗)。

标签规则（嵌合体滑窗）：窗口被真值前噬菌体覆盖比例 >= pos_overlap 记 1，== 0 记 0，其余记 -1。
"""
import argparse
import concurrent.futures
import csv
import json
import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np

from ..features.window_features import FEATURE_NAMES, SUB_BINS, extract_contig_windows

logger = logging.getLogger("phage_discovery.data.feature_dataset")


def iter_fasta(fasta_path: Path) -> Iterable[Tuple[str, str]]:
    """流式遍历 FASTA。"""
    cur_id: Optional[str] = None
    chunks: List[str] = []
    with open(fasta_path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith(">"):
                if cur_id is not None:
                    yield cur_id, "".join(chunks)
                cur_id = line[1:].strip().split()[0]
                chunks = []
            else:
                s = line.strip()
                if s:
                    chunks.append(s.upper())
    if cur_id is not None:
        yield cur_id, "".join(chunks)


def _window_batch_worker(args: Tuple[List[Tuple[str, str, int]], int, int]) -> List[Dict[str, Any]]:
    batch, win_size, step_size = args
    out: List[Dict[str, Any]] = []
    for wid, seq, label in batch:
        res = extract_contig_windows(wid, seq, win_size=max(win_size, len(seq)), step_size=step_size)
        n_win = len(res["starts"])
        res["labels"] = np.full(n_win, label, dtype=np.int8)
        fill_val = 1.0 if int(label) == 1 else 0.0
        res["sub_mask"] = np.full((n_win, SUB_BINS), fill_val, dtype=np.float32)
        out.append(res)
    return out


def _chimera_worker(args: Tuple[str, str, List[Tuple[int, int]], int, int, float]) -> Dict[str, Any]:
    cid, seq, regions, win_size, step_size, pos_overlap = args
    res = extract_contig_windows(cid, seq, win_size=win_size, step_size=step_size, truth_regions=regions)
    ov = res["overlap"]
    labels = np.full(len(ov), -1, dtype=np.int8)
    labels[ov >= pos_overlap] = 1
    labels[ov <= 0.0] = 0
    res["labels"] = labels
    return res


def _concat_results(results: List[Dict[str, Any]], source_flag: int) -> Dict[str, np.ndarray]:
    if not results:
        return {
            "features": np.zeros((0, len(FEATURE_NAMES)), dtype=np.float32),
            "labels": np.zeros(0, dtype=np.int8),
            "overlap": np.zeros(0, dtype=np.float32),
            "sub_mask": np.zeros((0, SUB_BINS), dtype=np.float32),
            "contig_ids": np.zeros(0, dtype="<U64"),
            "starts": np.zeros(0, dtype=np.int64),
            "ends": np.zeros(0, dtype=np.int64),
            "source": np.zeros(0, dtype=np.int8),
        }
    n_rows = [len(r["starts"]) for r in results]
    return {
        "features": np.concatenate([r["features"] for r in results]),
        "labels": np.concatenate([r["labels"] for r in results]),
        "overlap": np.concatenate([r["overlap"] for r in results]),
        "sub_mask": np.concatenate([r["sub_mask"] for r in results]),
        "contig_ids": np.concatenate([np.full(n, r["contig_id"], dtype="<U64") for r, n in zip(results, n_rows)]),
        "starts": np.concatenate([r["starts"] for r in results]),
        "ends": np.concatenate([r["ends"] for r in results]),
        "source": np.full(sum(n_rows), source_flag, dtype=np.int8),
    }


def _save_npz_atomic(path: Path, payload: Dict[str, np.ndarray]) -> None:
    tmp = path.with_name(f".{path.stem}.tmp.npz")
    np.savez_compressed(tmp, feature_names=np.asarray(FEATURE_NAMES), **payload)
    tmp.replace(path)


def build_split_features(
    bench_dir: Path,
    split_name: str,
    out_dir: Path,
    win_size: int = 5000,
    step_size: int = 2500,
    pos_overlap: float = 0.5,
    workers: Optional[int] = None,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """为指定 split 构建独立窗口与嵌合体滑窗两部分特征分片（已存在则断点跳过）。"""
    bench_root = Path(bench_dir).resolve()
    out_root = Path(out_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((bench_root / "benchmark_manifest.json").read_text(encoding="utf-8"))
    info = manifest["splits"][split_name]

    cpu_cnt = os.cpu_count() or 4
    n_workers = workers if workers is not None else max(1, cpu_cnt - 2)
    summary: Dict[str, Any] = {"split": split_name}

    # 1. 独立窗口部分
    win_npz = out_root / f"{split_name}_windows.npz"
    if overwrite or not win_npz.exists():
        labels: Dict[str, int] = {}
        with open(info["windows"]["truth_tsv"], "r", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                labels[row["window_id"]] = int(row["label"])
        batches: List[List[Tuple[str, str, int]]] = []
        cur: List[Tuple[str, str, int]] = []
        for wid, seq in iter_fasta(Path(info["windows"]["fasta"])):
            cur.append((wid, seq, labels.get(wid, 0)))
            if len(cur) >= 200:
                batches.append(cur)
                cur = []
        if cur:
            batches.append(cur)

        results: List[Dict[str, Any]] = []
        with concurrent.futures.ProcessPoolExecutor(max_workers=n_workers) as ex:
            for part in ex.map(_window_batch_worker, [(b, win_size, step_size) for b in batches]):
                results.extend(part)
        _save_npz_atomic(win_npz, _concat_results(results, source_flag=0))
        del results
    summary["windows_npz"] = str(win_npz)

    # 2. 嵌合体滑窗部分
    chim_npz = out_root / f"{split_name}_chimeras.npz"
    if overwrite or not chim_npz.exists():
        regions: Dict[str, List[Tuple[int, int]]] = defaultdict(list)
        with open(info["chimeras"]["truth_tsv"], "r", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                regions[row["contig_id"]].append((int(row["start_bp"]), int(row["end_bp"])))
        tasks = [
            (cid, seq, regions.get(cid, []), win_size, step_size, pos_overlap)
            for cid, seq in iter_fasta(Path(info["chimeras"]["fasta"]))
        ]
        results = []
        with concurrent.futures.ProcessPoolExecutor(max_workers=n_workers) as ex:
            for res in ex.map(_chimera_worker, tasks):
                results.append(res)
        del tasks
        _save_npz_atomic(chim_npz, _concat_results(results, source_flag=1))
        del results
    summary["chimeras_npz"] = str(chim_npz)

    for key in ("windows_npz", "chimeras_npz"):
        with np.load(summary[key]) as data:
            lab = data["labels"]
            summary[key.replace("_npz", "_counts")] = {
                "rows": int(lab.size),
                "pos": int(np.sum(lab == 1)),
                "neg": int(np.sum(lab == 0)),
                "ignored": int(np.sum(lab == -1)),
            }
    return summary


def build_extra_chimera_features(
    fasta_path: Path,
    truth_tsv: Path,
    out_npz: Path,
    win_size: int = 5000,
    step_size: int = 2500,
    pos_overlap: float = 0.5,
    source_flag: int = 2,
    workers: Optional[int] = None,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """将额外嵌合体/真实前噬菌体基因组序列提取为特征分片 npz（如 CheckV 挖掘数据集）。"""
    out_path = Path(out_npz).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cpu_cnt = os.cpu_count() or 4
    n_workers = workers if workers is not None else max(1, cpu_cnt - 2)

    if overwrite or not out_path.exists():
        regions: Dict[str, List[Tuple[int, int]]] = defaultdict(list)
        if Path(truth_tsv).exists():
            with open(truth_tsv, "r", encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh, delimiter="\t"):
                    regions[row["contig_id"]].append((int(row["start_bp"]), int(row["end_bp"])))
        tasks = [
            (cid, seq, regions.get(cid, []), win_size, step_size, pos_overlap)
            for cid, seq in iter_fasta(Path(fasta_path))
        ]
        results: List[Dict[str, Any]] = []
        if tasks:
            with concurrent.futures.ProcessPoolExecutor(max_workers=n_workers) as ex:
                for res in ex.map(_chimera_worker, tasks):
                    results.append(res)
        del tasks
        _save_npz_atomic(out_path, _concat_results(results, source_flag=source_flag))
        del results

    with np.load(out_path) as data:
        lab = data["labels"]
        return {
            "npz": str(out_path),
            "rows": int(lab.size),
            "pos": int(np.sum(lab == 1)),
            "neg": int(np.sum(lab == 0)),
            "ignored": int(np.sum(lab == -1)),
        }


def load_split_arrays(feature_dir: Path, split_name: str, parts: Tuple[str, ...] = ("windows", "chimeras")) -> Dict[str, np.ndarray]:
    """加载并合并指定 split 的特征分片。"""
    loaded: List[Dict[str, np.ndarray]] = []
    for part in parts:
        p = Path(feature_dir) / f"{split_name}_{part}.npz"
        if not p.exists():
            raise FileNotFoundError(f"缺少特征分片: {p}")
        with np.load(p) as data:
            loaded.append({k: data[k] for k in data.files if k != "feature_names"})
    return {k: np.concatenate([d[k] for d in loaded]) for k in loaded[0].keys()}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="构建窗口特征分片")
    parser.add_argument("--bench-dir", required=True)
    parser.add_argument("--split", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    summary = build_split_features(
        Path(args.bench_dir), args.split, Path(args.out_dir),
        workers=args.workers if args.workers > 0 else None,
        overwrite=args.overwrite,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

