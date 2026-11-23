# -*- coding: utf-8 -*-
"""
阶段 0 (T0.3) 碎片 Contig 与宿主嵌合前噬菌体基准测定脚本。

目的（只测量基线，不改算法）：
1. 滑窗截断实验：从 Suite A 完整基因组切出 5 / 10 / 20 / 30 / 40 kb 片段，
   统计 Incomplete 检出率及有尾基因组片段误判为 Podoviridae-like 的比率；
2. 定向边界截断实验：精确按结构模块坐标切出“仅含头部包装+裂解模块（故意截除尾部）”
   与“仅含尾部核心模块”的截断 Contig，实测 HEAD_PRESENT_LONG_TAIL_ABSENT 误触发率；
3. 宿主嵌合前噬菌体实验：将完整或截断（仅留头部）噬菌体序列嵌回真实细菌基因组切片，
   测定宿主基因背景对形态分类与假 TMP 的影响。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.benchmark_phage_structure import LOCAL_FASTA_DIR, sample_120_ictv_genomes  # noqa: E402
from src.analysis.phage_structure.morphotype_classifier import (  # noqa: E402
    build_connector_profile,
    build_module_matrix,
    classify_morphotype,
)
from src.analysis.phage_structure.sequence_annotator import (  # noqa: E402
    get_safe_workers,
    parse_input_contigs,
    predict_missing_orfs_parallel,
    scan_proteins_with_pyhmmer,
)
from src.analysis.phage_structure.tail_finder_adapter import run_phagetailfinder_on_contigs  # noqa: E402
from src.analysis.phage_structure.tmp_analyzer import select_and_analyze_tmps  # noqa: E402

HOST_GENOMES_DIR = LOCAL_FASTA_DIR.parent / "benchmarks" / "blind_sota_clinical"
RESULTS_DIR = PROJECT_ROOT / "results" / "benchmarks" / "phage_structure_fragmented"
WINDOW_SIZES_KB = (5, 10, 20, 30, 40)


def _read_single_fasta(path: Path) -> Tuple[str, str]:
    header = path.stem
    parts: List[str] = []
    for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith(">"):
            if not parts:
                header = s[1:].split()[0]
            else:
                break
        else:
            parts.append(s)
    return header, "".join(parts).upper()


def _select_source_phages(per_morph: int = 6) -> List[Dict[str, str]]:
    """从调参集 Suite A 中按不同科轮转选出完整参照基因组（绝不碰 Suite E）。"""
    local_idx = {p.stem.split(".")[0]: p for p in LOCAL_FASTA_DIR.glob("*.fasta")}
    suite_a = sample_120_ictv_genomes(local_idx, per_class=30)
    picked: List[Dict[str, str]] = []
    for morph in ("Myoviridae-like", "Siphoviridae-like", "Podoviridae-like", "Non-tailed"):
        pool = [x for x in suite_a if x["expected"] == morph]
        seen_fam: set[str] = set()
        chosen: List[Dict[str, str]] = []
        # 先各科选 1 株，再补足
        for item in pool:
            if item["family"] not in seen_fam:
                chosen.append(item)
                seen_fam.add(item["family"])
                if len(chosen) >= per_morph:
                    break
        for item in pool:
            if len(chosen) >= per_morph:
                break
            if item not in chosen:
                chosen.append(item)
        picked.extend(chosen)
    return picked


def _build_sliding_window_fragments(
    sources: List[Dict[str, str]],
    window_sizes_kb: Tuple[int, ...] = WINDOW_SIZES_KB,
) -> List[Dict[str, Any]]:
    """按 0% 与 45% 起止位置切出不同长度连续基因组碎片（仅限总长超过窗口且非完整保留）。"""
    frags: List[Dict[str, Any]] = []
    for src in sources:
        _, seq = _read_single_fasta(Path(src["fasta_path"]))
        n = len(seq)
        for wkb in window_sizes_kb:
            w = wkb * 1000
            if n < int(w * 1.15):
                continue
            offsets = [0, max(0, (n - w) // 2)]
            for idx_pos, start in enumerate(offsets):
                sub = seq[start : start + w]
                fid = f"SW__{src['acc']}__{wkb}kb__{idx_pos}"
                frags.append({
                    "frag_id": fid,
                    "scenario": f"sliding_{wkb}kb",
                    "window_kb": wkb,
                    "source_acc": src["acc"],
                    "source_family": src["family"],
                    "source_morph": src["expected"],
                    "source_len_bp": n,
                    "frag_len_bp": len(sub),
                    "seq": sub,
                })
    return frags


def _build_targeted_and_chimeric_fragments(
    sources: List[Dict[str, str]],
    workers: int,
) -> List[Dict[str, Any]]:
    """
    先对完整参考序列识别结构模块坐标，再切出：
    1. targeted_head_only: 切出连续 25-35 kb 且覆盖完整头部包装核心 (Portal+TerL+MCP) 但截断在长尾干之前；
    2. targeted_tail_only: 切出覆盖尾部操作子的连续片段；
    3. chimeric_full / chimeric_head_truncated: 嵌回真实宿主细菌基因组的 20 kb 左右背景窗口。
    """
    tailed_srcs = [s for s in sources if s["expected"] in ("Myoviridae-like", "Siphoviridae-like")]
    cmap: Dict[str, Dict[str, Any]] = {}
    seqs: Dict[str, str] = {}
    for s in tailed_srcs:
        _, seq = _read_single_fasta(Path(s["fasta_path"]))
        seqs[s["acc"]] = seq
        parsed = parse_input_contigs(fasta_path=s["fasta_path"])
        cid, info = next(iter(parsed.items()))
        for p in info["proteins"]:
            p.contig_id = s["acc"]
        cmap[s["acc"]] = info

    predict_missing_orfs_parallel(cmap, genetic_code=11, workers=workers)
    scan_proteins_with_pyhmmer(cmap, workers=workers, verify_annotated=True)

    # 载入细菌宿主背景序列（前 30kb 纯宿主区与中间 30kb）
    host_files = sorted(HOST_GENOMES_DIR.glob("*.fasta"))
    host_slices: List[Tuple[str, str]] = []
    for hf in host_files[:4]:
        _, hseq = _read_single_fasta(hf)
        if len(hseq) >= 120_000:
            host_slices.append((hf.stem.split("_")[0], hseq[50_000:75_000]))

    out: List[Dict[str, Any]] = []
    head_roles = {"PORTAL", "TERL", "TERS", "MCP", "HEAD_SCAFFOLD_PROTEASE"}
    tail_trunk_roles = {"TSP", "TTP", "MTP", "TAP", "TMP", "DIT", "BASEPLATE_MYO"}

    for h_idx, src in enumerate(tailed_srcs):
        acc = src["acc"]
        seq = seqs[acc]
        n = len(seq)
        prots = sorted(cmap[acc]["proteins"], key=lambda x: x.start)
        head_ps = [p for p in prots if p.structural_role in head_roles]
        tail_ps = [p for p in prots if p.structural_role in tail_trunk_roles]
        if not head_ps or not tail_ps:
            continue

        head_min = min(p.start for p in head_ps)
        head_max = max(p.end for p in head_ps)
        tail_min = min(p.start for p in tail_ps)
        tail_max = max(p.end for p in tail_ps)

        # 只有当头部模块和尾部核心区不严重穿插交叠时才可定向切出“仅头截断”片段
        head_only_seq: Optional[str] = None
        if head_max < tail_min:
            cut_end = min(tail_min - 50, max(head_max + 2000, min(n, head_min + 28_000)))
            cut_start = max(0, min(head_min - 2000, cut_end - 26_000))
            if (cut_end - cut_start) >= 12_000:
                head_only_seq = seq[cut_start:cut_end]
        elif tail_max < head_min:
            cut_start = max(tail_max + 50, head_min - 2000)
            cut_end = min(n, max(head_max + 2000, cut_start + 26_000))
            if (cut_end - cut_start) >= 12_000:
                head_only_seq = seq[cut_start:cut_end]

        if head_only_seq:
            out.append({
                "frag_id": f"TGT_HEAD__{acc}",
                "scenario": "targeted_head_only",
                "window_kb": round(len(head_only_seq) / 1000.0, 1),
                "source_acc": acc,
                "source_family": src["family"],
                "source_morph": src["expected"],
                "source_len_bp": n,
                "frag_len_bp": len(head_only_seq),
                "seq": head_only_seq,
            })

        # 仅尾部操作子片段
        t_start = max(0, tail_min - 1500)
        t_end = min(n, tail_max + 1500)
        if (t_end - t_start) >= 6000 and (t_end - t_start) < int(n * 0.85):
            sub_t = seq[t_start:t_end]
            out.append({
                "frag_id": f"TGT_TAIL__{acc}",
                "scenario": "targeted_tail_only",
                "window_kb": round(len(sub_t) / 1000.0, 1),
                "source_acc": acc,
                "source_family": src["family"],
                "source_morph": src["expected"],
                "source_len_bp": n,
                "frag_len_bp": len(sub_t),
                "seq": sub_t,
            })

        # 嵌回真实宿主细菌序列（完整嵌合与截断前噬菌体嵌合）
        if host_slices:
            h_acc, h_bg = host_slices[h_idx % len(host_slices)]
            flank = h_bg[:15_000]
            chim_full = flank + seq + h_bg[15_000:25_000]
            out.append({
                "frag_id": f"CHIM_FULL__{acc}__{h_acc}",
                "scenario": "chimeric_full_prophage",
                "window_kb": round(len(chim_full) / 1000.0, 1),
                "source_acc": acc,
                "source_family": src["family"],
                "source_morph": src["expected"],
                "source_len_bp": n,
                "frag_len_bp": len(chim_full),
                "seq": chim_full,
            })
            if head_only_seq:
                chim_trunc = flank + head_only_seq
                out.append({
                    "frag_id": f"CHIM_TRUNC__{acc}__{h_acc}",
                    "scenario": "chimeric_head_truncated",
                    "window_kb": round(len(chim_trunc) / 1000.0, 1),
                    "source_acc": acc,
                    "source_family": src["family"],
                    "source_morph": src["expected"],
                    "source_len_bp": n,
                    "frag_len_bp": len(chim_trunc),
                    "seq": chim_trunc,
                })
    return out


def run_fragments_with_checkpoint(
    fragments: List[Dict[str, Any]],
    *,
    checkpoint_path: Path,
    batch_size: int = 24,
) -> List[Dict[str, Any]]:
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    done_map: Dict[str, Dict[str, Any]] = {}
    if checkpoint_path.is_file():
        for ln in checkpoint_path.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                rec = json.loads(ln)
                done_map[str(rec["frag_id"])] = rec

    pending = [f for f in fragments if f["frag_id"] not in done_map]
    workers = get_safe_workers(12)

    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        cmap: Dict[str, Dict[str, Any]] = {}
        meta_by_id: Dict[str, Dict[str, Any]] = {}
        for item in batch:
            fid = str(item["frag_id"])
            parsed = parse_input_contigs(fasta_content=f">{fid}\n{item['seq']}\n")
            info = next(iter(parsed.values()))
            for p in info["proteins"]:
                p.contig_id = fid
            cmap[fid] = info
            meta_by_id[fid] = {k: v for k, v in item.items() if k != "seq"}

        predict_missing_orfs_parallel(cmap, genetic_code=11, workers=workers)
        scan_proteins_with_pyhmmer(cmap, workers=workers, verify_annotated=True)
        ptf_map: Dict[str, Any] = {}
        try:
            ptf_map = run_phagetailfinder_on_contigs(cmap, workers=workers, accurate_mode=False)
        except Exception as exc:
            print(f"[WARN] PhageTailFinder err: {exc}")

        with checkpoint_path.open("a", encoding="utf-8") as fh:
            for fid, info in cmap.items():
                meta = meta_by_id[fid]
                prots = info["proteins"]
                mm = build_module_matrix(prots)
                cp = build_connector_profile(prots)
                ptf_cnt, ptf_cl = ptf_map.get(fid, (0, []))
                verified_tmp_cnt = sum(
                    1
                    for p in prots
                    if p.structural_role == "TMP" and p.evidence_source in ("pyhmmer_phrog", "phold_3d")
                )
                has_tail_bg = (
                    (
                        mm.tail_sheath_count
                        + mm.major_tail_count
                        + mm.tail_tube_count
                        + mm.tail_assembly_chaperone_count
                        + verified_tmp_cnt
                    )
                    > 0
                    or mm.baseplate_count >= 2
                    or len(ptf_cl) >= 1
                )
                tmps = select_and_analyze_tmps(
                    prots,
                    has_tailed_context=has_tail_bg,
                    contig_length_bp=int(info["length_bp"]),
                    max_workers=workers,
                )
                pred = classify_morphotype(
                    prots,
                    tmps,
                    mm,
                    cp,
                    ptf_clusters=ptf_cl,
                    genome_length_bp=int(info["length_bp"]),
                    dna_seq=info.get("dna_seq", ""),
                )
                row_out = {
                    **meta,
                    "total_orfs": len(prots),
                    "predicted": pred.morphotype_code,
                    "confidence": pred.confidence,
                    "class_scores": pred.class_scores,
                    "tmp_cnt": 0 if pred.morphotype_code in ("Podoviridae-like", "Non-tailed", "Incomplete") else len(tmps),
                    "decision_basis": pred.decision_basis,
                    "warnings": pred.warnings,
                }
                done_map[fid] = row_out
                fh.write(json.dumps(row_out, ensure_ascii=False) + "\n")
        print(f"  [FragBenchmark] 已完成 {min(start + len(batch), len(pending))}/{len(pending)}")

    return [done_map[f["frag_id"]] for f in fragments]


def summarize_fragment_results(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_scenario: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_scenario[str(r["scenario"])].append(r)

    summary: Dict[str, Any] = {"total_fragments": len(rows), "scenarios": {}}
    for sc, arr in sorted(by_scenario.items()):
        pred_dist = dict(Counter(r["predicted"] for r in arr))
        n = len(arr)
        tailed_src = [r for r in arr if r["source_morph"] in ("Myoviridae-like", "Siphoviridae-like")]
        tailed_false_podo = sum(1 for r in tailed_src if r["predicted"] == "Podoviridae-like")
        tailed_exact = sum(1 for r in tailed_src if r["predicted"] == r["source_morph"])
        all_exact = sum(1 for r in arr if r["predicted"] == r["source_morph"])
        inc_cnt = pred_dist.get("Incomplete", 0)
        summary["scenarios"][sc] = {
            "total": n,
            "incomplete_count": inc_cnt,
            "incomplete_rate": round(inc_cnt / max(1, n), 4),
            "source_morph_exact_rate": round(all_exact / max(1, n), 4),
            "tailed_src_count": len(tailed_src),
            "tailed_false_podo_count": tailed_false_podo,
            "tailed_false_podo_rate": round(tailed_false_podo / max(1, len(tailed_src)), 4) if tailed_src else 0.0,
            "tailed_exact_rate": round(tailed_exact / max(1, len(tailed_src)), 4) if tailed_src else 0.0,
            "pred_distribution": pred_dist,
        }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="T0.3 碎片 Contig 与前噬菌体嵌合基线评测")
    parser.add_argument("--per-morph", type=int, default=6, help="每种形态抽取的完整参照株数")
    parser.add_argument("--fresh", action="store_true", help="清空断点重新跑")
    parser.add_argument("--smoke", action="store_true", help="少量碎片烟雾测试")
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "_smoke" if args.smoke else ""
    cp_path = RESULTS_DIR / f"fragments{suffix}_checkpoints.jsonl"
    if args.fresh:
        cp_path.unlink(missing_ok=True)

    t0 = time.perf_counter()
    workers = get_safe_workers(12)
    sources = _select_source_phages(per_morph=1 if args.smoke else args.per_morph)
    sw_frags = _build_sliding_window_fragments(sources, window_sizes_kb=(10, 30) if args.smoke else WINDOW_SIZES_KB)
    tgt_frags = _build_targeted_and_chimeric_fragments(sources, workers=workers)
    all_frags = sw_frags + tgt_frags
    if args.smoke:
        all_frags = all_frags[:8]

    print(f"参照源株: {len(sources)} | 总切片与嵌合样本: {len(all_frags)}")
    rows = run_fragments_with_checkpoint(all_frags, checkpoint_path=cp_path, batch_size=24)
    summary = summarize_fragment_results(rows)
    summary["elapsed_sec"] = round(time.perf_counter() - t0, 2)

    out_path = RESULTS_DIR / f"fragmented_baseline_report{suffix}.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n================ T0.3 碎片与嵌合前噬菌体基线 ================")
    for sc, info in summary["scenarios"].items():
        print(
            f"  {sc:25s} | n={info['total']:3d} | Incomplete={info['incomplete_rate']:.2%} "
            f"| Tailed->Podo误判={info['tailed_false_podo_count']}/{info['tailed_src_count']} ({info['tailed_false_podo_rate']:.2%}) "
            f"| 精确匹配={info['source_morph_exact_rate']:.2%}"
        )
    print(f"报告已落盘: {out_path} ({summary['elapsed_sec']}s)")


if __name__ == "__main__":
    main()
