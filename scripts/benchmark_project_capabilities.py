# -*- coding: utf-8 -*-
"""
项目核心能力端到端综合实战基准评测脚本（跨门宿主泛化 + 真实模型不变量 + 跨中心流式切割 + 应用全栈贯通）。

默认全部采用相对工作区推断路径，可通过命令行参数覆盖。
示例：
  .venv\\Scripts\\python.exe scripts/benchmark_project_capabilities.py
"""
from __future__ import annotations

import argparse
import csv
import gc
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import torch
from Bio import SeqIO

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import predict_unified as cli_mod  # noqa: E402
from src.analysis.phage_finder.exporter import inspect_sequences  # noqa: E402
from src.analysis.phage_finder.model_registry import discover_available_models  # noqa: E402
from src.phage_discovery.benchmark.metrics import PredictedRegion, compute_interval_iou  # noqa: E402
from src.phage_discovery.data.feature_dataset import iter_fasta  # noqa: E402
from src.phage_discovery.inference.unified_model import UnifiedPhageModel  # noqa: E402

_COMP = str.maketrans("ACGTNacgtn", "TGCANtgcan")
_PHAGE_KW = re.compile(
    r"\b(prophage|bacteriophage|phage|capsid|portal|terminase|tail\s+(?:fiber|sheath|tube|protein)|"
    r"integrase|excisionase|holin|endolysin|baseplate|head-tail|provirus)\b",
    re.I,
)

# 权威文献跨门参考基准（均已确认零泄露，坐标对照本地官方 .gbk 核验）
_CURATED_CROSS_PHYLUM_REFS: Dict[str, List[Tuple[str, int, int, str]]] = {
    "NC_000962.3": [
        ("phiRv1", 1779313, 1788505, "gold_prophage"),
        ("phiRv2", 2970122, 2980818, "gold_prophage"),
    ],
    "NC_002935.2": [
        ("Corynephage_beta_tox", 155599, 191000, "gold_prophage"),
        ("DIP_prophage_2", 1869507, 1880855, "gold_prophage"),
    ],
    "NC_003912.7": [
        ("CJIE1_Mu_like", 207114, 246021, "gold_prophage"),
        ("CJIE2", 495852, 538671, "gold_prophage"),
        ("CJIE4", 1335925, 1370632, "gold_prophage"),
    ],
    "NC_006351.1": [
        ("phiK96243", 1429447, 1463523, "gold_prophage"),
    ],
    "NC_006624.1": [
        ("TKV1", 62980, 87128, "archaea_provirus"),
        ("TKV2", 317132, 348469, "archaea_provirus"),
        ("TKV3", 500134, 527651, "archaea_provirus"),
        ("TKV4", 1182836, 1210000, "archaea_provirus"),
    ],
    "NC_005072.1": [],
    "NC_000908.2": [],
}


def _revcomp(seq: str) -> str:
    return seq.translate(_COMP)[::-1]


def _release_gpu() -> None:
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def _inspect_gbk_region_cds(gbk_path: Optional[Path], start_bp: int, end_bp: int) -> Dict[str, Any]:
    """抽取给定基因组区间内的 GenBank 官方 CDS 注释密度与噬菌体关键词命中统计。"""
    if gbk_path is None or not gbk_path.is_file():
        return {"cds_count": 0, "phage_kw_hits": 0, "sample_products": []}
    rec = SeqIO.read(str(gbk_path), "genbank")
    cds_cnt = 0
    kw_hits = 0
    samples: List[str] = []
    for feat in rec.features:
        if feat.type != "CDS":
            continue
        fs, fe = int(feat.location.start), int(feat.location.end)
        if fe <= start_bp or fs >= end_bp:
            continue
        cds_cnt += 1
        prod = "; ".join(feat.qualifiers.get("product", []))
        if prod and _PHAGE_KW.search(prod):
            kw_hits += 1
            if len(samples) < 5:
                samples.append(prod[:80])
    return {"cds_count": cds_cnt, "phage_kw_hits": kw_hits, "sample_products": samples}


def _run_cross_phylum_suite(
    upm: UnifiedPhageModel,
    cross_dir: Path,
) -> Dict[str, Any]:
    """能力一：跨 8 大门/界 14 条未见完整原核染色体的泛化与境界实测。"""
    manifest_path = cross_dir / "cross_phylum_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"未找到跨门基准清单文件: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    results: List[Dict[str, Any]] = []
    curated_hits = 0
    curated_total = 0
    arch_hits = 0
    arch_total = 0
    strict_neg_fp = 0

    for item in manifest:
        acc = str(item["accession"])
        tag = str(item["tag"])
        phylum = str(item["phylum"])
        fa_p = cross_dir / f"{acc}_{tag}.fasta"
        gb_p = cross_dir / f"{acc}_{tag}.gbk"
        seqs = dict(iter_fasta(fa_p))
        cid = next(iter(seqs))
        seq_len = len(seqs[cid])

        res = upm.scan_sequences(seqs)
        _release_gpu()

        preds_detail: List[Dict[str, Any]] = []
        for reg in res.regions:
            key = f"{reg.contig_id}:{reg.start_bp}-{reg.end_bp}"
            ann = res.region_annotations.get(key, {})
            gb_info = _inspect_gbk_region_cds(gb_p, reg.start_bp, reg.end_bp)
            preds_detail.append(
                {
                    "start_bp": reg.start_bp,
                    "end_bp": reg.end_bp,
                    "len_bp": reg.end_bp - reg.start_bp,
                    "peak_score": round(reg.peak_score, 4),
                    "completeness_class": ann.get("completeness_class", ""),
                    "active_modules": ann.get("active_modules", []),
                    "att_aligned": bool(ann.get("att_site")),
                    "gbk_cds": gb_info["cds_count"],
                    "gbk_phage_kw_hits": gb_info["phage_kw_hits"],
                    "gbk_samples": gb_info["sample_products"],
                }
            )

        cur_eval: List[Dict[str, Any]] = []
        if acc in _CURATED_CROSS_PHYLUM_REFS:
            refs = _CURATED_CROSS_PHYLUM_REFS[acc]
            if not refs:
                strict_neg_fp += len(res.regions)
            for name, gs, ge, tier in refs:
                best_iou = 0.0
                best_pair: Optional[Tuple[int, int]] = None
                for reg in res.regions:
                    iou = compute_interval_iou(reg.start_bp, reg.end_bp, gs, ge)
                    if iou > best_iou:
                        best_iou = iou
                        best_pair = (reg.start_bp, reg.end_bp)
                hit = best_iou >= 0.30
                if tier == "archaea_provirus":
                    arch_total += 1
                    if hit:
                        arch_hits += 1
                else:
                    curated_total += 1
                    if hit:
                        curated_hits += 1
                cur_eval.append(
                    {
                        "name": name,
                        "tier": tier,
                        "gt": [gs, ge],
                        "hit": hit,
                        "iou": round(best_iou, 4),
                        "pred": list(best_pair) if best_pair else None,
                    }
                )

        row = {
            "accession": acc,
            "tag": tag,
            "phylum": phylum,
            "len_bp": seq_len,
            "gc_pct": item["gc_pct"],
            "n_preds": len(res.regions),
            "elapsed_sec": res.timings_sec.get("total_sec", 0.0),
            "protein_skip_ratio": res.routing_stats.get("protein_skip_ratio"),
            "rescue_stats": res.routing_stats.get("rescue_stats"),
            "predictions": preds_detail,
            "curated_eval": cur_eval,
        }
        results.append(row)
        print(
            f"[CrossPhylum] {acc:11s} ({phylum:21s} GC={item['gc_pct']:5.1f}%) "
            f"| preds={len(res.regions):2d} | time={row['elapsed_sec']:5.2f}s | eval={cur_eval or 'gbk_cross_audit'}",
            flush=True,
        )
        for pd_item in preds_detail:
            print(
                f"    -> [{pd_item['start_bp']}..{pd_item['end_bp']}] len={pd_item['len_bp']}bp "
                f"cls={pd_item['completeness_class']} gbk_cds={pd_item['gbk_cds']} "
                f"gbk_phage_hits={pd_item['gbk_phage_kw_hits']} samples={pd_item['gbk_samples'][:2]}",
                flush=True,
            )

    return {
        "strains_count": len(results),
        "total_mb": round(sum(r["len_bp"] for r in results) / 1e6, 2),
        "curated_bacteria_hits": curated_hits,
        "curated_bacteria_total": curated_total,
        "archaea_provirus_hits": arch_hits,
        "archaea_provirus_total": arch_total,
        "strict_negative_cross_phylum_fp": strict_neg_fp,
        "per_strain": results,
    }


def _run_real_invariance_and_streaming(
    upm: UnifiedPhageModel,
    cross_dir: Path,
) -> Dict[str, Any]:
    """能力二：在真实参考染色体上验证反向互补对称性及 2Mb 流式分片一致性。"""
    # 1. 低 GC 弯曲菌 RM1221 (1.78 Mb) 正反双链扫描对称性测试
    rm_fa = cross_dir / "NC_003912.7_Campylobacter_jejuni_RM1221.fasta"
    rm_seqs = dict(iter_fasta(rm_fa))
    rm_cid = next(iter(rm_seqs))
    fwd_seq = rm_seqs[rm_cid]
    L = len(fwd_seq)
    rev_seq = _revcomp(fwd_seq)

    fwd_res = upm.scan_sequences({"rm_fwd": fwd_seq})
    _release_gpu()
    rev_res = upm.scan_sequences({"rm_rev": rev_seq})
    _release_gpu()

    mapped_back = sorted(
        [(L - r.end_bp, L - r.start_bp) for r in rev_res.regions],
        key=lambda x: x[0],
    )
    fwd_coords = sorted([(r.start_bp, r.end_bp) for r in fwd_res.regions], key=lambda x: x[0])
    rc_pair_ious: List[float] = []
    for fs, fe in fwd_coords:
        best = max((compute_interval_iou(fs, fe, rs, re_) for rs, re_ in mapped_back), default=0.0)
        rc_pair_ious.append(round(best, 4))

    print(
        f"[RevComp Symmetry] NC_003912.7 fwd={len(fwd_coords)} {fwd_coords} | "
        f"rev_mapped={len(mapped_back)} {mapped_back} | pair_IoUs={rc_pair_ious}",
        flush=True,
    )

    # 2. 跨门 6.26 Mb 拟杆菌 (NC_004663.1) 2Mb 强制分段流式 vs 单批扫描一致性对比
    bt_fa = cross_dir / "NC_004663.1_Bacteroides_thetaiotaomicron_VPI5482.fasta"
    bt_seqs = dict(iter_fasta(bt_fa))
    single_res = upm.scan_sequences(bt_seqs)
    _release_gpu()
    single_coords = [(r.contig_id, r.start_bp, r.end_bp) for r in single_res.regions]

    with tempfile.TemporaryDirectory() as tmpd:
        stream_res = upm.scan_fasta_streaming(
            bt_fa,
            Path(tmpd) / "bt_stream",
            chunk_max_bp=2_000_000,
            resume=False,
            export_outputs=False,
        )
        _release_gpu()
        stream_coords = [(r.contig_id, r.start_bp, r.end_bp) for r in stream_res.regions]

    print(
        f"[Streaming 2Mb] NC_004663.1 exact_match={single_coords == stream_coords} | "
        f"single={single_coords} | stream={stream_coords}",
        flush=True,
    )
    return {
        "revcomp_symmetry": {
            "contig_id": rm_cid,
            "fwd_coords": fwd_coords,
            "rev_mapped_coords": mapped_back,
            "pair_ious": rc_pair_ious,
            "mean_sym_iou": round(sum(rc_pair_ious) / max(1, len(rc_pair_ious)), 4),
        },
        "bacteroides_streaming_2mb": {
            "exact_match": single_coords == stream_coords,
            "single_coords": single_coords,
            "stream_coords": stream_coords,
        },
    }


def _run_fullstack_application_check(
    models_root: Path,
    sample_fasta: Path,
) -> Dict[str, Any]:
    """能力三：全栈应用链路核验（模型自动探测 + 工作台输入预检 + 生产 CLI 真实扫描导出闭环）。"""
    found = discover_available_models(project_root=REPO_ROOT)
    uni_found = [m for m in found if m.get("has_unified_judge")]
    assert uni_found, "工作台模型探测未发现 Unified 模型"
    sub_thr_detected = float(uni_found[0]["decoder_defaults"]["sub_threshold"])

    inspected = inspect_sequences(fasta_path=str(sample_fasta), project_root=REPO_ROOT)

    with tempfile.TemporaryDirectory() as tmpd:
        cli_out = Path(tmpd) / "cli_real_out"
        rc = cli_mod.main(
            [
                "--fasta",
                str(sample_fasta),
                "--out-dir",
                str(cli_out),
                "--models-root",
                str(models_root),
                "--chunk-mb",
                "0",
                "--workers",
                str(max(1, min(10, (os.cpu_count() or 6) - 2))),
                "--device",
                "cuda" if torch.cuda.is_available() else "cpu",
            ]
        )
        _release_gpu()
        assert rc == 0
        tsv_rows = list(csv.DictReader((cli_out / "regions.tsv").open("r", encoding="utf-8"), delimiter="\t"))
        gff_lines = [
            ln for ln in (cli_out / "regions.gff3").read_text(encoding="utf-8").splitlines()
            if ln and not ln.startswith("#")
        ]
        fna_headers = [
            ln for ln in (cli_out / "prophages.fna").read_text(encoding="utf-8").splitlines() if ln.startswith(">")
        ]
        summary = json.loads((cli_out / "scan_summary.json").read_text(encoding="utf-8"))

    print(
        f"[FullStack Check] model_badge={uni_found[0]['version']} sub_thr={sub_thr_detected} | "
        f"inspect_contigs={inspected['total_contigs']} | cli_tsv={len(tsv_rows)} gff={len(gff_lines)} fna={len(fna_headers)}",
        flush=True,
    )
    return {
        "discovered_unified_version": uni_found[0]["version"],
        "detected_sub_threshold": sub_thr_detected,
        "inspect_contig_count": inspected["total_contigs"],
        "cli_exit_code": rc,
        "tsv_rows": len(tsv_rows),
        "gff3_rows": len(gff_lines),
        "fasta_records": len(fna_headers),
        "cli_rescue_stats": summary.get("routing_stats", {}).get("rescue_stats", {}),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="UnifiedPhageModel 项目多维度能力综合实战验证脚本")
    default_data_root = (REPO_ROOT.parent / "Phage data").resolve()
    parser.add_argument("--models-root", type=Path, default=default_data_root / "models" / "full_v4")
    parser.add_argument("--cross-dir", type=Path, default=default_data_root / "benchmarks" / "cross_phylum_unseen")
    parser.add_argument("--workers", type=int, default=max(1, min(12, (os.cpu_count() or 6) - 2)))
    parser.add_argument("--device", type=str, default="cuda" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args(argv)

    t0 = time.perf_counter()
    models_root = Path(args.models_root).resolve()
    cross_dir = Path(args.cross_dir).resolve()

    upm = UnifiedPhageModel.from_models_root(models_root, workers=int(args.workers), device=str(args.device))
    print(f"[Init] {upm.model_version} | sub_threshold={upm.dna_scanner.sub_threshold} | workers={args.workers}", flush=True)

    cross_rep = _run_cross_phylum_suite(upm, cross_dir)
    inv_rep = _run_real_invariance_and_streaming(upm, cross_dir)
    sample_fa = cross_dir / "NC_002935.2_Corynebacterium_diphtheriae_NCTC13129.fasta"
    app_rep = _run_fullstack_application_check(models_root, sample_fa)

    report = {
        "model_version": upm.model_version,
        "sub_threshold": upm.dna_scanner.sub_threshold,
        "elapsed_sec": round(time.perf_counter() - t0, 2),
        "cross_phylum_generalization": cross_rep,
        "real_invariance_and_streaming": inv_rep,
        "fullstack_application": app_rep,
    }
    out_json = models_root / "orf_judge_unified" / "project_capability_validation_report.json"
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[Completed] 全维度能力验证报告已落盘: {out_json} (elapsed={report['elapsed_sec']}s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

