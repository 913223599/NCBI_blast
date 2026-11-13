# -*- coding: utf-8 -*-
"""
统一模型基准评测运行器与零训练组成偏倚基线（Baseline）

职责：
1. 提供统一的预测格式读写与多维度评估入口 (`evaluate_predictions_on_split`)；
2. 内置无监督组成偏倚基线打分器 (`run_composition_baseline`)，基于反向互补规范化 4-mer 余弦偏离度
   与局部 GC Z-score 对窗口及细菌嵌合体打分（多核并行，自动保留 2 核），用于验证评测管线并设立初始下限榜单。
"""
import argparse
import concurrent.futures
import csv
import json
import logging
import os
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from ...utils.phage_dataset.preprocessor import compute_canonical_4mer_freq
from .metrics import (
    PredictedRegion,
    TruthRegion,
    WindowPrediction,
    compute_region_metrics,
    compute_window_metrics,
    decode_window_scores_to_regions,
)

logger = logging.getLogger("phage_discovery.benchmark.runner")


def _iter_fasta_stream(fasta_path: Path) -> Iterable[Tuple[str, str]]:
    """流式遍历 FASTA 文件记录，避免整库同时驻留内存。"""
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


def _score_window_batch_worker(batch: List[Tuple[str, str]]) -> List[Tuple[str, float]]:
    """
    无训练窗口基线打分：利用已知噬菌体偏低的四核苷酸熵/特征 GC 极性 + 编码周期偏好做简易启发打分
    （主要作为纯序列零参数垫底对照基线）。
    """
    results: List[Tuple[str, float]] = []
    for wid, seq in batch:
        if not seq:
            results.append((wid, 0.5))
            continue
        kmer = compute_canonical_4mer_freq(seq)
        # 计算归一化香农熵与 4-mer 方差：病毒基因组因紧致操纵子常具有略异于随机背景的频谱方差
        nz = kmer[kmer > 0]
        entropy = -float(np.sum(nz * np.log2(nz))) if nz.size > 0 else 7.0
        # 典型 4-mer 最大熵为 log2(136) ≈ 7.087，映射到 [0, 1] 置信分
        score = max(0.0, min(1.0, 1.0 - (entropy / 7.08746) * 0.85))
        results.append((wid, round(score, 5)))
    return results


def _score_chimera_contig_worker(
    item: Tuple[str, str, int, int],
) -> Tuple[str, List[WindowPrediction]]:
    """
    对长细菌序列按滑窗计算相对于整条 contig 宿主背景的 4-mer 余弦距离与 GC 偏离度，
    作为无监督水平基因转移（HGT）/前噬菌体启发式基线。
    """
    contig_id, seq, win_size, step_size = item
    n = len(seq)
    if n < 1000:
        return contig_id, []

    host_kmer = compute_canonical_4mer_freq(seq)
    host_norm = float(np.linalg.norm(host_kmer)) or 1.0
    host_unit = host_kmer / host_norm
    host_gc = (seq.count("G") + seq.count("C")) / max(1, n)

    raw_dists: List[Tuple[int, int, float]] = []
    pos = 0
    while pos < n:
        end_pos = min(n, pos + win_size)
        if (end_pos - pos) < 1000 and pos > 0:
            break
        sub = seq[pos:end_pos]
        wk = compute_canonical_4mer_freq(sub)
        wn = float(np.linalg.norm(wk)) or 1.0
        cos_sim = float(np.dot(wk / wn, host_unit))
        cos_dist = max(0.0, 1.0 - cos_sim)
        win_gc = (sub.count("G") + sub.count("C")) / max(1, len(sub))
        gc_diff = abs(win_gc - host_gc)
        anomaly = cos_dist * 8.0 + gc_diff * 3.0
        raw_dists.append((pos, end_pos, anomaly))
        if end_pos == n:
            break
        pos += step_size

    if not raw_dists:
        return contig_id, []

    vals = np.asarray([d[2] for d in raw_dists], dtype=np.float64)
    med = float(np.median(vals))
    mad = float(np.median(np.abs(vals - med))) or 1e-4

    preds: List[WindowPrediction] = []
    for s_bp, e_bp, val in raw_dists:
        # 稳健 Z-score 经 Sigmoid 映射至 [0, 1]
        z = (val - med) / (1.4826 * mad)
        prob = 1.0 / (1.0 + np.exp(-max(-10.0, min(10.0, (z - 2.5)))))
        preds.append(WindowPrediction(contig_id=contig_id, start_bp=s_bp, end_bp=e_bp, score=round(float(prob), 5)))
    return contig_id, preds


def evaluate_window_predictions(
    truth_tsv: Path,
    pred_scores: Dict[str, float],
    threshold: float = 0.5,
) -> Dict[str, Any]:
    """根据窗口真值表与预测得分计算全量及分尺度指标。"""
    all_y: List[int] = []
    all_s: List[float] = []
    by_scale_y: Dict[str, List[int]] = defaultdict(list)
    by_scale_s: Dict[str, List[float]] = defaultdict(list)

    with open(truth_tsv, "r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            wid = row["window_id"]
            label = int(row["label"])
            wlen = int(row["win_len"])
            scale_bucket = "5000bp" if wlen >= 4500 else ("3000bp" if wlen >= 2500 else "<=1000bp")
            score = float(pred_scores.get(wid, 0.0))

            all_y.append(label)
            all_s.append(score)
            by_scale_y[scale_bucket].append(label)
            by_scale_s[scale_bucket].append(score)

    overall = compute_window_metrics(all_y, all_s, threshold=threshold)
    per_scale = {
        bucket: compute_window_metrics(by_scale_y[bucket], by_scale_s[bucket], threshold=threshold)
        for bucket in sorted(by_scale_y.keys())
    }
    return {
        "overall": overall,
        "by_scale": per_scale,
    }


def evaluate_chimera_predictions(
    truth_tsv: Path,
    contigs_tsv: Path,
    predicted_regions: Sequence[PredictedRegion],
    iou_threshold: float = 0.5,
) -> Dict[str, Any]:
    """根据嵌合体真值区域表与预测区域计算总榜与分场景指标。"""
    contig_lengths: Dict[str, int] = {}
    contig_scenario: Dict[str, str] = {}
    with open(contigs_tsv, "r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            cid = row["contig_id"]
            contig_lengths[cid] = int(row["contig_len_bp"])
            contig_scenario[cid] = row["scenario"]

    truths: List[TruthRegion] = []
    with open(truth_tsv, "r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            truths.append(
                TruthRegion(
                    contig_id=row["contig_id"],
                    start_bp=int(row["start_bp"]),
                    end_bp=int(row["end_bp"]),
                    mode=row.get("mode", "intact"),
                )
            )

    overall = compute_region_metrics(
        truths, predicted_regions, contig_lengths=contig_lengths, iou_threshold=iou_threshold
    )

    # 分场景统计（intact_single / degraded_fragment / multi_tandem）
    by_mode: Dict[str, Any] = {}
    for mode in sorted({t.mode for t in truths}):
        mode_contigs = {t.contig_id for t in truths if t.mode == mode}
        mode_truths = [t for t in truths if t.mode == mode]
        mode_preds = [p for p in predicted_regions if p.contig_id in mode_contigs]
        mode_lengths = {cid: contig_lengths[cid] for cid in mode_contigs if cid in contig_lengths}
        by_mode[mode] = compute_region_metrics(
            mode_truths, mode_preds, contig_lengths=mode_lengths, iou_threshold=iou_threshold
        )["primary"]

    return {
        "overall": overall,
        "by_mode": by_mode,
    }


def run_composition_baseline(
    benchmark_dir: Path,
    split_name: str = "test",
    win_size: int = 5000,
    step_size: int = 2500,
    seed_threshold: float = 0.75,
    extend_threshold: float = 0.50,
    threads: Optional[int] = None,
) -> Dict[str, Any]:
    """
    在指定基准 split 上运行零训练组成偏倚基线，输出完整 JSON 与 Markdown 评测报告。
    """
    bench_root = Path(benchmark_dir).resolve()
    manifest = json.loads((bench_root / "benchmark_manifest.json").read_text(encoding="utf-8"))
    if split_name not in manifest.get("splits", {}):
        raise ValueError(f"基准集中不存在 split={split_name}")

    split_info = manifest["splits"][split_name]
    win_fna = Path(split_info["windows"]["fasta"])
    win_truth = Path(split_info["windows"]["truth_tsv"])
    chim_fna = Path(split_info["chimeras"]["fasta"])
    chim_truth = Path(split_info["chimeras"]["truth_tsv"])
    chim_contigs = Path(split_info["chimeras"]["contigs_tsv"])

    cpu_cnt = os.cpu_count() or 4
    workers = threads if threads is not None else max(1, cpu_cnt - 2)

    # 1. 窗口级基线评测（分批多核并发）
    t0 = time.perf_counter()
    win_scores: Dict[str, float] = {}
    batch: List[Tuple[str, str]] = []
    batches: List[List[Tuple[str, str]]] = []
    for wid, seq in _iter_fasta_stream(win_fna):
        batch.append((wid, seq))
        if len(batch) >= 250:
            batches.append(batch)
            batch = []
    if batch:
        batches.append(batch)

    if workers > 1 and len(batches) > 1:
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as ex:
            for res_list in ex.map(_score_window_batch_worker, batches):
                for wid, sc in res_list:
                    win_scores[wid] = sc
    else:
        for b in batches:
            for wid, sc in _score_window_batch_worker(b):
                win_scores[wid] = sc

    win_eval = evaluate_window_predictions(win_truth, win_scores, threshold=0.5)
    win_elapsed = round(time.perf_counter() - t0, 3)

    # 2. 嵌合体区域定位基线评测
    t1 = time.perf_counter()
    chim_tasks: List[Tuple[str, str, int, int]] = [
        (cid, seq, win_size, step_size) for cid, seq in _iter_fasta_stream(chim_fna)
    ]
    all_win_preds: List[WindowPrediction] = []
    if workers > 1 and len(chim_tasks) > 1:
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as ex:
            for _, wpreds in ex.map(_score_chimera_contig_worker, chim_tasks):
                all_win_preds.extend(wpreds)
    else:
        for item in chim_tasks:
            _, wpreds = _score_chimera_contig_worker(item)
            all_win_preds.extend(wpreds)

    pred_regions = decode_window_scores_to_regions(
        all_win_preds,
        seed_threshold=seed_threshold,
        extend_threshold=extend_threshold,
        merge_gap_bp=3000,
        min_region_bp=3000,
    )
    chim_eval = evaluate_chimera_predictions(chim_truth, chim_contigs, pred_regions, iou_threshold=0.5)
    chim_elapsed = round(time.perf_counter() - t1, 3)

    total_mb = float(chim_eval["overall"].get("total_scanned_mb") or 0.0)
    sec_per_5mb = round((chim_elapsed / total_mb) * 5.0, 3) if total_mb > 0 else 0.0

    report: Dict[str, Any] = {
        "evaluated_at": datetime.now().isoformat(timespec="seconds"),
        "model_name": "Baseline_4mer_GC_Anomaly",
        "split": split_name,
        "workers": workers,
        "timing": {
            "window_eval_sec": win_elapsed,
            "chimera_eval_sec": chim_elapsed,
            "est_sec_per_5mb_genome": sec_per_5mb,
        },
        "window_benchmark": win_eval,
        "chimera_benchmark": chim_eval,
    }

    report_dir = bench_root / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    json_out = report_dir / f"baseline_{split_name}_report.json"
    tmp_json = json_out.with_name(f".{json_out.name}.tmp")
    tmp_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_json.replace(json_out)

    md_out = report_dir / f"baseline_{split_name}_report.md"
    tmp_md = md_out.with_name(f".{md_out.name}.tmp")
    tmp_md.write_text(_format_markdown_report(report), encoding="utf-8")
    tmp_md.replace(md_out)

    report["report_json"] = str(json_out)
    report["report_md"] = str(md_out)
    return report


def _format_markdown_report(report: Dict[str, Any]) -> str:
    w_all = report["window_benchmark"]["overall"]
    c_all = report["chimera_benchmark"]["overall"]
    c_pri = c_all["primary"]
    c_str = c_all["strict_iou_0_8"]
    timing = report["timing"]

    lines = [
        f"# 基准评测报告：`{report['model_name']}` ({report['split']} split)",
        "",
        f"- 评测时间：{report['evaluated_at']}",
        f"- 并发核心数：{report['workers']}",
        f"- 5 Mb 细菌全基因组等效耗时：**{timing['est_sec_per_5mb_genome']} s**",
        "",
        "## 1. 窗口级识别性能（Window Benchmark）",
        "",
        "| 尺度桶 | 样本数 | AUROC | AUPRC | F1 | Recall@0.5%FPR | FPR@95%TPR |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: |",
        f"| **全部合并** | {w_all.get('total')} | {w_all.get('auroc')} | {w_all.get('auprc')} | {w_all.get('f1')} | {w_all.get('recall_at_fpr_0_5pct')} | {w_all.get('fpr_at_tpr_95pct')} |",
    ]
    for bucket, metrics in report["window_benchmark"]["by_scale"].items():
        lines.append(
            f"| `{bucket}` | {metrics.get('total')} | {metrics.get('auroc')} | {metrics.get('auprc')} | {metrics.get('f1')} | {metrics.get('recall_at_fpr_0_5pct')} | {metrics.get('fpr_at_tpr_95pct')} |"
        )

    lines.extend([
        "",
        "## 2. 细菌基因组嵌合前噬菌体定位（Chimera Benchmark）",
        "",
        "| 指标项 | 实测值 |",
        "| :--- | :--- |",
        f"| 扫描总序列 / 纯阴性对照 | `{c_all.get('total_scanned_mb')} Mb` / `{c_all.get('pure_negative_scanned_mb')} Mb` |",
        f"| 真实岛总数 / 预测岛总数 | `{c_all.get('truth_count')}` / `{c_all.get('predicted_count')}` |",
        f"| IoU >= 0.5 Precision / Recall / F1 | `{c_pri.get('precision')}` / `{c_pri.get('recall')}` / `{c_pri.get('f1')}` |",
        f"| IoU >= 0.8 Precision / Recall / F1 | `{c_str.get('precision')}` / `{c_str.get('recall')}` / `{c_str.get('f1')}` |",
        f"| 断点边界 MAE / 中位误差 | `{c_pri.get('breakpoint_mae_bp')} bp` / `{c_pri.get('breakpoint_median_ae_bp')} bp` |",
        f"| 纯阴性染色体假阳性密度 (`FP / Mb`) | **`{c_all.get('pure_negative_fp_per_mb')}`** |",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="运行前噬菌体测试基准基线评测")
    parser.add_argument("--benchmark-dir", required=True, help="基准集根目录（含 benchmark_manifest.json）")
    parser.add_argument("--split", default="test", choices=["val", "test"], help="评测 split")
    parser.add_argument("--threads", type=int, default=0, help="工作进程数（0 表示自动保留 2 核）")

    args = parser.parse_args()
    res = run_composition_baseline(
        benchmark_dir=Path(args.benchmark_dir),
        split_name=args.split,
        threads=args.threads if args.threads > 0 else None,
    )
    print(json.dumps({
        "model": res["model_name"],
        "split": res["split"],
        "window_auroc": res["window_benchmark"]["overall"].get("auroc"),
        "region_f1_iou05": res["chimera_benchmark"]["overall"]["primary"].get("f1"),
        "pure_neg_fp_per_mb": res["chimera_benchmark"]["overall"].get("pure_negative_fp_per_mb"),
        "est_sec_per_5mb": res["timing"]["est_sec_per_5mb_genome"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

