# -*- coding: utf-8 -*-
"""
噬菌体结构与尾长独立外部验证脚本（支持分片断点续跑与双格式 FASTA vs GBK 对照）。

验证内容：
1. Suite C（本地 4,852 株未测库存按 35+ ICTV 科分层抽取 160 株）：
   同时在裸 FASTA 与原始 GBK 双模式下运行全量管线，验证四分类准确率、Macro-F1、
   假 TMP 零残留、有尾 TMP 召回率，以及 FASTA vs GBK 形态/TMP/尾长一致性。
2. Suite D（从 NCBI Entrez 在线拉取 33 株全新外部真实基因组）：
   在裸 FASTA 与原始在线 GBK 双模式下验证外部泛化、非标注释免疫力及独立 TEM 尾长回归精度。
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.benchmark_phage_structure import evaluate_suite_a  # noqa: E402
from scripts.validation_datasets import (  # noqa: E402
    EXTERNAL_DATA_DIR,
    prepare_suite_d_external,
    sample_suite_c_unseen_local,
)
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

RESULTS_DIR = PROJECT_ROOT / "results" / "benchmarks" / "phage_structure_external"


def run_dual_mode_pipeline(
    entries: List[Dict[str, Any]],
    *,
    mode: str,
    checkpoint_path: Path,
    batch_size: int = 20,
) -> List[Dict[str, Any]]:
    """按指定输入模式 ('fasta' 或 'gbk') 分批运行并实时写入 JSONL 断点文件。"""
    if mode not in ("fasta", "gbk"):
        raise ValueError(f"未知模式: {mode}")

    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    done_map: Dict[str, Dict[str, Any]] = {}
    if checkpoint_path.is_file():
        for line in checkpoint_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                done_map[str(rec["acc"])] = rec

    pending = [e for e in entries if str(e["acc"]) not in done_map]
    workers = get_safe_workers(12)

    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        cmap: Dict[str, Dict[str, Any]] = {}
        entry_by_uid: Dict[str, Dict[str, Any]] = {}

        for item in batch:
            in_path = str(item["fasta_path"] if mode == "fasta" else item["gbk_path"])
            parsed = parse_input_contigs(fasta_path=in_path)
            if not parsed:
                raise RuntimeError(f"解析失败 ({mode}): {item['acc']} -> {in_path}")
            main_cid = max(parsed.keys(), key=lambda k: parsed[k]["length_bp"])
            uid = f"{item['acc']}__{main_cid}"
            info = parsed[main_cid]
            for p in info["proteins"]:
                p.contig_id = uid
            cmap[uid] = info
            entry_by_uid[uid] = item

        # 与生产端 manager.py / benchmark_phage_structure.py 完全一致的序列优先管线
        predict_missing_orfs_parallel(cmap, genetic_code=11, workers=workers)
        scan_proteins_with_pyhmmer(cmap, workers=workers, verify_annotated=True)
        ptf_map: Dict[str, Any] = {}
        try:
            ptf_map = run_phagetailfinder_on_contigs(cmap, workers=workers, accurate_mode=False)
        except Exception as exc:
            print(f"[WARN] PhageTailFinder batch err ({mode}): {exc}")

        with checkpoint_path.open("a", encoding="utf-8") as out_fh:
            for uid, info in cmap.items():
                item = entry_by_uid[uid]
                prots = info["proteins"]
                mm = build_module_matrix(prots)
                cp = build_connector_profile(prots)
                ptf_cnt, ptf_clusters = ptf_map.get(uid, (0, []))
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
                    or len(ptf_clusters) >= 1
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
                    ptf_clusters=ptf_clusters,
                    genome_length_bp=int(info["length_bp"]),
                    dna_seq=info.get("dna_seq", ""),
                    genetic_code_used=int(info.get("genetic_code_used") or 11),
                    genetic_code_auto_selected=bool(info.get("genetic_code_auto_selected") or False),
                    sparse_rescued_orfs=int(info.get("sparse_rescued_orfs") or 0),
                )
                effective_tmps = [] if pred.morphotype_code in ("Podoviridae-like", "Non-tailed") else tmps
                primary_tmp = effective_tmps[0] if effective_tmps else None
                prot_map = {p.locus_tag: p for p in prots}
                lookup_lt = primary_tmp.merged_loci[0] if (primary_tmp and primary_tmp.merged_loci) else (primary_tmp.locus_tag if primary_tmp else "")
                tmp_prot = prot_map.get(lookup_lt) if primary_tmp else None

                unverified_cnt = sum(1 for p in prots if p.evidence_source == "unverified_text")
                overridden_cnt = sum(
                    1 for p in prots if p.raw_product and p.product and p.raw_product.lower() != p.product.lower()
                )

                row_out: Dict[str, Any] = {
                    **item,
                    "mode": mode,
                    "input_type": info.get("input_type", mode),
                    "length_bp": info["length_bp"],
                    "total_orfs": len(prots),
                    "genetic_code_used": int(info.get("genetic_code_used") or 11),
                    "sparse_rescued_orfs": int(info.get("sparse_rescued_orfs") or 0),
                    "unverified_text_cnt": unverified_cnt,
                    "overridden_gbk_cnt": overridden_cnt,
                    "predicted": pred.morphotype_code,
                    "confidence": pred.confidence,
                    "class_scores": pred.class_scores,
                    "connector": cp.type_hint,
                    "decision_basis": pred.decision_basis,
                    "warnings": pred.warnings,
                    "ptf_tail_protein_count": ptf_cnt,
                    "ptf_cluster_count": len(ptf_clusters),
                    "tmp": (
                        {
                            "locus_tag": primary_tmp.locus_tag,
                            "product": primary_tmp.product,
                            "evidence_kind": primary_tmp.evidence_kind,
                            "merged_loci": list(primary_tmp.merged_loci),
                            "length_aa": primary_tmp.length_aa,
                            "est_tail_length_nm": primary_tmp.est_tail_length_nm,
                            "ptf_pfam": tmp_prot.ptf_pfam if tmp_prot else "",
                            "raw_product": tmp_prot.raw_product if tmp_prot else "",
                        }
                        if primary_tmp
                        else None
                    ),
                }
                done_map[str(item["acc"])] = row_out
                out_fh.write(json.dumps(row_out, ensure_ascii=False) + "\n")

        print(f"  [{mode.upper()}] 已完成批次 {min(start + len(batch), len(pending))}/{len(pending)}")

    # 每次返回时用当前版本化数据集元数据（尤其是 tem_truth.tsv）同步覆盖，防止旧 checkpoint 残留过期真值
    sync_fields = ("tem_nm", "tem_range", "doi", "verification_status", "tem_state", "includes_baseplate", "tem_method")
    synced_rows: List[Dict[str, Any]] = []
    for e in entries:
        row = dict(done_map[str(e["acc"])])
        for fk in sync_fields:
            if fk in e:
                row[fk] = e[fk]
        synced_rows.append(row)
    return synced_rows


def evaluate_dual_concordance(
    fasta_rows: List[Dict[str, Any]],
    gbk_rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """评估裸 FASTA 与原始 GBK 的形态一致率、TMP 长度一致率及非标 GBK 子集稳定性。"""
    f_map = {str(r["acc"]): r for r in fasta_rows}
    g_map = {str(r["acc"]): r for r in gbk_rows}
    accs = [str(r["acc"]) for r in fasta_rows if str(r["acc"]) in g_map]

    morph_match = 0
    tmp_len_match = 0
    tmp_within_5pct = 0
    tailed_total = 0
    f_tailed_tmp_found = 0
    g_tailed_tmp_found = 0
    f_false_tmp = 0
    g_false_tmp = 0
    nontailed_total = 0

    mismatches: List[Dict[str, Any]] = []
    missing_trans_accs: List[str] = []
    high_hyp_accs: List[str] = []

    for acc in accs:
        fr = f_map[acc]
        gr = g_map[acc]
        exp = str(fr["expected"])
        prof = fr.get("gbk_profile") or {}
        if prof.get("missing_translation"):
            missing_trans_accs.append(acc)
        if prof.get("high_hyp_70"):
            high_hyp_accs.append(acc)

        if fr["predicted"] == gr["predicted"]:
            morph_match += 1
        ft = fr.get("tmp")
        gt = gr.get("tmp")
        ft_nm = ft["est_tail_length_nm"] if ft else None
        gt_nm = gt["est_tail_length_nm"] if gt else None
        ft_aa = ft["length_aa"] if ft else None
        gt_aa = gt["length_aa"] if gt else None

        if exp in ("Myoviridae-like", "Siphoviridae-like"):
            tailed_total += 1
            if ft:
                f_tailed_tmp_found += 1
            if gt:
                g_tailed_tmp_found += 1
        else:
            nontailed_total += 1
            if ft:
                f_false_tmp += 1
            if gt:
                g_false_tmp += 1

        same_tmp = (ft_aa == gt_aa)
        close_tmp = same_tmp or (
            ft_nm is not None and gt_nm is not None and abs(ft_nm - gt_nm) <= max(2.0, 0.05 * max(ft_nm, gt_nm))
        )
        if same_tmp:
            tmp_len_match += 1
        if close_tmp:
            tmp_within_5pct += 1

        if fr["predicted"] != gr["predicted"] or not same_tmp:
            mismatches.append({
                "acc": acc,
                "family": fr.get("family"),
                "expected": exp,
                "fasta_pred": fr["predicted"],
                "gbk_pred": gr["predicted"],
                "fasta_tmp_aa": ft_aa,
                "gbk_tmp_aa": gt_aa,
                "fasta_nm": ft_nm,
                "gbk_nm": gt_nm,
                "gbk_profile": prof,
            })

    def _sub_acc(sub_accs: List[str]) -> Dict[str, Any]:
        if not sub_accs:
            return {"count": 0}
        return {
            "count": len(sub_accs),
            "fasta_acc": round(sum(1 for a in sub_accs if f_map[a]["predicted"] == f_map[a]["expected"]) / len(sub_accs), 4),
            "gbk_acc": round(sum(1 for a in sub_accs if g_map[a]["predicted"] == g_map[a]["expected"]) / len(sub_accs), 4),
            "morph_concordance": round(sum(1 for a in sub_accs if f_map[a]["predicted"] == g_map[a]["predicted"]) / len(sub_accs), 4),
        }

    return {
        "total": len(accs),
        "morph_concordance": round(morph_match / max(1, len(accs)), 4),
        "morph_concordance_count": morph_match,
        "tmp_exact_aa_concordance": round(tmp_len_match / max(1, len(accs)), 4),
        "tmp_exact_aa_count": tmp_len_match,
        "tmp_within_5pct_concordance": round(tmp_within_5pct / max(1, len(accs)), 4),
        "tailed_tmp_recall_fasta": f"{f_tailed_tmp_found}/{tailed_total}",
        "tailed_tmp_recall_gbk": f"{g_tailed_tmp_found}/{tailed_total}",
        "false_tmp_podo_nontailed_fasta": f"{f_false_tmp}/{nontailed_total}",
        "false_tmp_podo_nontailed_gbk": f"{g_false_tmp}/{nontailed_total}",
        "subset_missing_translation": _sub_acc(missing_trans_accs),
        "subset_high_hypothetical_70pct": _sub_acc(high_hyp_accs),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
    }


def _compute_external_tem_stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """针对给定 TEM 行计算相关性与 0.145 回归误差。"""
    paired = []
    missing = []
    for r in rows:
        tem_nm = r.get("tem_nm")
        if tem_nm is None:
            continue
        tmp = r.get("tmp")
        if not tmp:
            missing.append({
                "acc": r["acc"],
                "name": r.get("name"),
                "expected": r["expected"],
                "predicted": r["predicted"],
                "tem_nm": tem_nm,
            })
            continue
        est = float(tmp["est_tail_length_nm"])
        abs_err = abs(est - float(tem_nm))
        pct_err = abs_err / float(tem_nm) * 100.0
        paired.append({
            "acc": r["acc"],
            "name": r.get("name"),
            "in_local_5k": r.get("in_local_5k"),
            "expected": r["expected"],
            "predicted": r["predicted"],
            "tem_nm": float(tem_nm),
            "verification_status": r.get("verification_status", "unverified"),
            "doi": r.get("doi", ""),
            "length_aa": int(tmp["length_aa"]),
            "est_0145_nm": est,
            "abs_err_nm": round(abs_err, 2),
            "pct_err": round(pct_err, 2),
            "evidence_kind": tmp["evidence_kind"],
        })

    n = len(paired)
    if n < 2:
        return {"tem_total": len(paired) + len(missing), "tmp_found": n, "missing": missing}

    xs = [p["length_aa"] for p in paired]
    ys = [p["tem_nm"] for p in paired]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    r_val = round(cov / (sx * sy), 4) if sx > 0 and sy > 0 else 0.0

    by_morph: Dict[str, Any] = {}
    for m in ("Myoviridae-like", "Siphoviridae-like"):
        sub = [p for p in paired if p["expected"] == m]
        if sub:
            by_morph[m] = {
                "count": len(sub),
                "mae_nm": round(statistics.mean(p["abs_err_nm"] for p in sub), 2),
                "mape_pct": round(statistics.mean(p["pct_err"] for p in sub), 2),
            }

    return {
        "tem_total": n + len(missing),
        "tmp_found": n,
        "missing": missing,
        "pearson_r": r_val,
        "mae_0145_nm": round(statistics.mean(p["abs_err_nm"] for p in paired), 2),
        "median_abs_err_nm": round(statistics.median(p["abs_err_nm"] for p in paired), 2),
        "mape_0145_pct": round(statistics.mean(p["pct_err"] for p in paired), 2),
        "by_morph": by_morph,
        "details": paired,
    }


def evaluate_external_tem(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """计算 Suite D 独立外部 TEM 尾长回归精度（默认严格仅纳入 verified 真值）。"""
    tem_rows = [r for r in rows if r.get("tem_nm") is not None]
    verified_rows = [r for r in tem_rows if r.get("verification_status") == "verified"]
    unverified_excluded = [
        {"acc": r["acc"], "name": r.get("name"), "tem_nm": r.get("tem_nm")}
        for r in tem_rows
        if r.get("verification_status") != "verified"
    ]
    primary = _compute_external_tem_stats(verified_rows if verified_rows else tem_rows)
    all_stats = _compute_external_tem_stats(tem_rows)
    primary["all_tem_total"] = len(tem_rows)
    primary["unverified_excluded_count"] = len(unverified_excluded)
    primary["unverified_excluded"] = unverified_excluded
    primary["all_incl_unverified"] = {
        k: all_stats.get(k)
        for k in ("tem_total", "tmp_found", "pearson_r", "mae_0145_nm", "median_abs_err_nm", "mape_0145_pct")
    }
    return primary


def _evaluate_by_family(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    by_fam: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_fam[str(r.get("family") or "Unknown")].append(r)
    out: Dict[str, Dict[str, Any]] = {}
    for fam, arr in sorted(by_fam.items()):
        ok = sum(1 for x in arr if x["predicted"] == x["expected"])
        out[fam] = {
            "expected": arr[0]["expected"],
            "total": len(arr),
            "correct": ok,
            "accuracy": round(ok / len(arr), 4),
        }
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="独立外部 + 跨科双格式验证")
    parser.add_argument("--fresh", action="store_true", help="清除历史断点重跑")
    parser.add_argument("--smoke", action="store_true", help="仅运行少量样本烟雾测试脚本通路")
    parser.add_argument("--per-class", type=int, default=40, help="Suite C 每形态抽样株数")
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "_smoke" if args.smoke else ""
    if args.fresh:
        for p in RESULTS_DIR.glob(f"*{suffix}_checkpoints.jsonl"):
            p.unlink(missing_ok=True)

    t0 = time.perf_counter()
    print("=== [准备] 拉取在线 NCBI Suite D 数据并抽样本地未测 Suite C ===")
    suite_d_entries = prepare_suite_d_external(EXTERNAL_DATA_DIR)
    suite_d_accs = {str(e["acc"]) for e in suite_d_entries}
    suite_c_entries = sample_suite_c_unseen_local(
        per_class=2 if args.smoke else args.per_class,
        extra_excluded=suite_d_accs,
    )

    if args.smoke:
        suite_d_entries = [suite_d_entries[0], suite_d_entries[12], suite_d_entries[22], suite_d_entries[28]]

    print(f"Suite D: {len(suite_d_entries)} 株 | Suite C: {len(suite_c_entries)} 株")

    print("\n=== [Suite D] 运行全新 NCBI 在线外部集 (FASTA vs GBK) ===")
    d_fasta = run_dual_mode_pipeline(
        suite_d_entries,
        mode="fasta",
        checkpoint_path=RESULTS_DIR / f"suite_d_fasta{suffix}_checkpoints.jsonl",
        batch_size=15,
    )
    d_gbk = run_dual_mode_pipeline(
        suite_d_entries,
        mode="gbk",
        checkpoint_path=RESULTS_DIR / f"suite_d_gbk{suffix}_checkpoints.jsonl",
        batch_size=15,
    )

    print("\n=== [Suite C] 运行本地未测多科集 (FASTA vs GBK) ===")
    c_fasta = run_dual_mode_pipeline(
        suite_c_entries,
        mode="fasta",
        checkpoint_path=RESULTS_DIR / f"suite_c_fasta{suffix}_checkpoints.jsonl",
        batch_size=20,
    )
    c_gbk = run_dual_mode_pipeline(
        suite_c_entries,
        mode="gbk",
        checkpoint_path=RESULTS_DIR / f"suite_c_gbk{suffix}_checkpoints.jsonl",
        batch_size=20,
    )

    for rows_list in (d_fasta, d_gbk, c_fasta, c_gbk):
        for r in rows_list:
            r.setdefault("family", r.get("source_note") or r.get("name") or "External")
            r.setdefault("host", r.get("name") or "External")
            r.setdefault("desc", r.get("source_note") or r.get("name") or "")

    report = {
        "elapsed_sec": round(time.perf_counter() - t0, 2),
        "smoke": args.smoke,
        "suite_d_external": {
            "total": len(suite_d_entries),
            "in_local_5k_false_cnt": sum(1 for e in suite_d_entries if not e["in_local_5k"]),
            "fasta_morph": evaluate_suite_a(d_fasta),
            "gbk_morph": evaluate_suite_a(d_gbk),
            "concordance": evaluate_dual_concordance(d_fasta, d_gbk),
            "tem_fasta": evaluate_external_tem(d_fasta),
            "tem_gbk": evaluate_external_tem(d_gbk),
        },
        "suite_c_unseen_local": {
            "total": len(suite_c_entries),
            "family_count": len({str(e["family"]) for e in suite_c_entries}),
            "fasta_morph": evaluate_suite_a(c_fasta),
            "gbk_morph": evaluate_suite_a(c_gbk),
            "concordance": evaluate_dual_concordance(c_fasta, c_gbk),
            "by_family_fasta": _evaluate_by_family(c_fasta),
            "by_family_gbk": _evaluate_by_family(c_gbk),
        },
    }
    report_path = RESULTS_DIR / f"external_validation_report{suffix}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n================ 外部独立验证汇总 ================")
    print(f"总耗时: {report['elapsed_sec']}s | 报告: {report_path}")
    sd = report["suite_d_external"]
    print(
        f"[Suite D ({sd['total']}株, {sd['in_local_5k_false_cnt']}株非本地)] "
        f"FASTA Acc={sd['fasta_morph']['accuracy']} ({sd['fasta_morph']['correct']}/{sd['total']}), "
        f"GBK Acc={sd['gbk_morph']['accuracy']} ({sd['gbk_morph']['correct']}/{sd['total']}), "
        f"双格式形态一致={sd['concordance']['morph_concordance']} ({sd['concordance']['morph_concordance_count']}/{sd['total']}), "
        f"TMP精确一致={sd['concordance']['tmp_exact_aa_count']}/{sd['total']}"
    )
    print(
        f"  TEM定量 (FASTA verified, 剔除unverified={sd['tem_fasta'].get('unverified_excluded_count')}): {sd['tem_fasta'].get('tmp_found')}/{sd['tem_fasta'].get('tem_total')}, "
        f"r={sd['tem_fasta'].get('pearson_r')}, MAE={sd['tem_fasta'].get('mae_0145_nm')}nm, MAPE={sd['tem_fasta'].get('mape_0145_pct')}% "
        f"(all={sd['tem_fasta'].get('all_incl_unverified', {}).get('pearson_r')}/{sd['tem_fasta'].get('all_incl_unverified', {}).get('mae_0145_nm')}nm/{sd['tem_fasta'].get('all_incl_unverified', {}).get('mape_0145_pct')}%)"
    )
    print(
        f"  TEM定量 (GBK   verified, 剔除unverified={sd['tem_gbk'].get('unverified_excluded_count')}): {sd['tem_gbk'].get('tmp_found')}/{sd['tem_gbk'].get('tem_total')}, "
        f"r={sd['tem_gbk'].get('pearson_r')}, MAE={sd['tem_gbk'].get('mae_0145_nm')}nm, MAPE={sd['tem_gbk'].get('mape_0145_pct')}% "
        f"(all={sd['tem_gbk'].get('all_incl_unverified', {}).get('pearson_r')}/{sd['tem_gbk'].get('all_incl_unverified', {}).get('mae_0145_nm')}nm/{sd['tem_gbk'].get('all_incl_unverified', {}).get('mape_0145_pct')}%)"
    )
    sc = report["suite_c_unseen_local"]
    print(
        f"[Suite C ({sc['total']}株, {sc['family_count']}个ICTV科)] "
        f"FASTA Acc={sc['fasta_morph']['accuracy']} (F1={sc['fasta_morph']['macro_f1']}), "
        f"GBK Acc={sc['gbk_morph']['accuracy']} (F1={sc['gbk_morph']['macro_f1']}), "
        f"双格式形态一致={sc['concordance']['morph_concordance']} ({sc['concordance']['morph_concordance_count']}/{sc['total']}), "
        f"TMP精确一致={sc['concordance']['tmp_exact_aa_count']}/{sc['total']}"
    )
    print(
        f"  假TMP (Podo/Non): FASTA={sc['concordance']['false_tmp_podo_nontailed_fasta']}, "
        f"GBK={sc['concordance']['false_tmp_podo_nontailed_gbk']} | "
        f"Tailed TMP召回: FASTA={sc['concordance']['tailed_tmp_recall_fasta']}, "
        f"GBK={sc['concordance']['tailed_tmp_recall_gbk']}"
    )


if __name__ == "__main__":
    main()
