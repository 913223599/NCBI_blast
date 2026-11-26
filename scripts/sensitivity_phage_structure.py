# -*- coding: utf-8 -*-
"""
T2.1 参数阈值敏感性扫描与零回归核验脚本 (仅面向 Suite A+B+C+D 调参集，严禁接触盲测集 Suite E)

阶段设计：
1. Stage 1（特征缓存分片断点落盘）：对去重后的 Suite A(120) + Suite B(30) + Suite C(160) + Suite D(33)
   全量执行一次标准序列优先管线 (Pyrodigal + PyHMMER + PhageTailFinder)，按 25 株分批持久化
   至 tuning_features_cache.jsonl，支持断点续跑与 `--fresh` 全量重算；
2. Stage 2（±20% 逐项敏感性扰动）：基于 `override_threshold` 逐项评估关键阈值的 ±20% 扰动对
   形态准确率、有尾 TMP 召回、短尾/无尾假 TMP 及 41 株实测 TEM 定量 MAE/MAPE 的影响，并在
   24 株分层子集上实测 WSL PyHMMER 搜索参数 `Z` 与 `default_score_cutoff` 双边扰动。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.benchmark_phage_structure import (  # noqa: E402
    LOCAL_FASTA_DIR,
    SUITE_B_TRUTH_RECORDS,
    ensure_fasta_for_acc,
    evaluate_suite_a,
    sample_120_ictv_genomes,
)
from scripts.validation_datasets import (  # noqa: E402
    prepare_suite_d_external,
    sample_suite_c_unseen_local,
)
from src.analysis.phage_structure.manager import evaluate_single_contig_structure  # noqa: E402
from src.analysis.phage_structure.sequence_annotator import (  # noqa: E402
    get_safe_workers,
    parse_input_contigs,
    predict_missing_orfs_parallel,
    scan_proteins_with_pyhmmer,
)
from src.analysis.phage_structure.tail_finder_adapter import run_phagetailfinder_on_contigs  # noqa: E402
from src.analysis.phage_structure.thresholds import (  # noqa: E402
    DEFAULT_THRESHOLDS,
    PhageStructureThresholds,
    list_threshold_keys,
    override_threshold,
)
from src.analysis.phage_structure.types import StructureProteinItem, TailFinderCluster  # noqa: E402

RESULTS_DIR = PROJECT_ROOT / "results" / "benchmarks" / "phage_structure_sensitivity"
CACHE_JSONL = RESULTS_DIR / "tuning_features_cache.jsonl"
REPORT_JSON = RESULTS_DIR / "sensitivity_report.json"
SUMMARY_MD = RESULTS_DIR / "sensitivity_summary.md"

# 待扫描的 23 个核心结构化配置阈值
PERTURB_KEYS: List[str] = [
    "tmp.direct_pfam_min_aa",
    "tmp.syntenic_yqaj_min_aa",
    "tmp.lytic_tmp_min_aa",
    "tmp.self_auth_hmm_score",
    "tmp.self_auth_min_aa",
    "tmp.high_conf_verified_hmm_score",
    "tmp.operon_window",
    "tmp.wide_operon_window",
    "tmp.ptf_backbone_prob",
    "tmp.hmm_tmp_default_min_aa",
    "tmp.hmm_tmp_tap_min_aa",
    "tmp.hmm_tmp_in_operon_min_score",
    "tmp.hmm_tmp_outside_operon_min_score",
    "tmp.syntenic_default_min_aa",
    "tmp.syntenic_min_score",
    "classifier.podo_negative_strong_weight",
    "classifier.incomplete_score_cutoff",
    "classifier.compact_tailless_max_bp",
    "completeness.podo_negative_min_bp",
    "completeness.terl_full_min_aa",
    "completeness.valid_long_tmp_min_aa",
    "split_tmp.max_gap_bp",
    "split_tmp.merged_min_aa",
]


def _assemble_tuning_entries() -> List[Dict[str, Any]]:
    """汇编去重后的 Suite A + Suite B + Suite C + Suite D 全量调参株清单。"""
    local_idx = {p.stem.split(".")[0]: p for p in LOCAL_FASTA_DIR.glob("*.fasta")}
    by_acc: Dict[str, Dict[str, Any]] = {}

    def _upsert(acc: str, payload: Dict[str, Any], suite_tag: str) -> None:
        if acc not in by_acc:
            by_acc[acc] = {**payload, "acc": acc, "suites": [suite_tag]}
        else:
            if suite_tag not in by_acc[acc]["suites"]:
                by_acc[acc]["suites"].append(suite_tag)
            for k in ("tem_nm", "verification_status"):
                if by_acc[acc].get(k) is None and payload.get(k) is not None:
                    by_acc[acc][k] = payload[k]

    for row in sample_120_ictv_genomes(local_idx, per_class=30):
        _upsert(
            row["acc"],
            {
                "family": row["family"],
                "expected": row["expected"],
                "fasta_path": row["fasta_path"],
                "tem_nm": None,
                "verification_status": None,
            },
            "suite_a",
        )

    for rec in SUITE_B_TRUTH_RECORDS:
        fa = ensure_fasta_for_acc(rec.accession, local_idx)
        if fa is None:
            raise FileNotFoundError(f"Suite B 序列不可用: {rec.accession}")
        _upsert(
            rec.accession,
            {
                "family": rec.name,
                "expected": rec.morphotype,
                "fasta_path": str(fa),
                "tem_nm": rec.tem_nm,
                "verification_status": rec.verification_status,
            },
            "suite_b",
        )

    d_entries = prepare_suite_d_external()
    d_accs = {str(x["acc"]) for x in d_entries}
    for row in sample_suite_c_unseen_local(per_class=40, extra_excluded=d_accs):
        _upsert(
            str(row["acc"]),
            {
                "family": row["family"],
                "expected": row["expected"],
                "fasta_path": str(row["fasta_path"]),
                "tem_nm": None,
                "verification_status": None,
            },
            "suite_c",
        )

    for row in d_entries:
        _upsert(
            str(row["acc"]),
            {
                "family": row["family"],
                "expected": row["expected"],
                "fasta_path": str(row["fasta_path"]),
                "tem_nm": row.get("tem_nm"),
                "verification_status": row.get("verification_status"),
            },
            "suite_d",
        )

    return list(by_acc.values())


def _build_or_load_feature_cache(
    entries: List[Dict[str, Any]],
    *,
    fresh: bool = False,
    batch_size: int = 25,
) -> List[Dict[str, Any]]:
    """分批抽取特征并以 JSONL 断点持久化，确保跨轮次高效零等待复现。"""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if fresh and CACHE_JSONL.is_file():
        CACHE_JSONL.unlink()

    cached_map: Dict[str, Dict[str, Any]] = {}
    if CACHE_JSONL.is_file():
        for line in CACHE_JSONL.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                cached_map[str(rec["acc"])] = rec

    pending = [e for e in entries if e["acc"] not in cached_map]
    if pending:
        print(f"=== [Stage 1] 正在生成调参集特征缓存 (待处理 {len(pending)}/{len(entries)} 株) ===")
    workers = get_safe_workers(12)

    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        cmap: Dict[str, Dict[str, Any]] = {}
        meta_by_uid: Dict[str, Dict[str, Any]] = {}

        for item in batch:
            parsed = parse_input_contigs(fasta_path=str(item["fasta_path"]))
            main_cid = max(parsed.keys(), key=lambda k: parsed[k]["length_bp"])
            uid = f"{item['acc']}__{main_cid}"
            info = parsed[main_cid]
            for p in info["proteins"]:
                p.contig_id = uid
            cmap[uid] = info
            meta_by_uid[uid] = item

        predict_missing_orfs_parallel(cmap, genetic_code=11, auto_select_genetic_code=True, workers=workers)
        scan_proteins_with_pyhmmer(cmap, workers=workers, hmm_thresholds=DEFAULT_THRESHOLDS.hmm)
        ptf_map: Dict[str, Tuple[int, List[TailFinderCluster]]] = {}
        try:
            ptf_map = run_phagetailfinder_on_contigs(cmap, workers=workers)
        except Exception as exc:
            print(f"[WARN] PhageTailFinder batch err: {exc}")

        with CACHE_JSONL.open("a", encoding="utf-8") as fh:
            for uid, info in cmap.items():
                item = meta_by_uid[uid]
                ptf_cnt, ptf_clusters = ptf_map.get(uid, (0, []))
                rec = {
                    "acc": item["acc"],
                    "uid": uid,
                    "suites": item["suites"],
                    "family": item["family"],
                    "expected": item["expected"],
                    "tem_nm": item.get("tem_nm"),
                    "verification_status": item.get("verification_status"),
                    "fasta_path": item["fasta_path"],
                    "length_bp": int(info["length_bp"]),
                    "gc_percent": float(info["gc_percent"]),
                    "dna_seq": info.get("dna_seq", ""),
                    "genetic_code_used": int(info.get("genetic_code_used") or 11),
                    "genetic_code_auto_selected": bool(info.get("genetic_code_auto_selected") or False),
                    "sparse_rescued_orfs": int(info.get("sparse_rescued_orfs") or 0),
                    "ptf_cnt": ptf_cnt,
                    "ptf_clusters": [c.model_dump() for c in ptf_clusters],
                    "proteins": [p.model_dump() for p in info["proteins"]],
                }
                cached_map[item["acc"]] = rec
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

        print(f"  [Cache] 已完成 {min(start + len(batch), len(pending))}/{len(pending)}")

    return [cached_map[e["acc"]] for e in entries]


def _hydrate_records(raw_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    hydrated: List[Dict[str, Any]] = []
    for r in raw_records:
        hydrated.append({
            **r,
            "proteins_obj": [StructureProteinItem(**p) for p in r["proteins"]],
            "ptf_clusters_obj": [TailFinderCluster(**c) for c in r["ptf_clusters"]],
        })
    return hydrated


def _filter_hmm_cutoff(proteins: List[StructureProteinItem], min_score: float) -> List[StructureProteinItem]:
    """在内存特征上模拟上调 HMM score_cutoff 对识别结果的影响。"""
    out: List[StructureProteinItem] = []
    for p in proteins:
        if p.evidence_source == "pyhmmer_phrog" and p.hmm_score < min_score:
            out.append(
                p.model_copy(
                    update={
                        "phrog_id": "",
                        "phrog_category": "",
                        "product": "hypothetical protein",
                        "structural_role": "OTHER",
                        "role_label_cn": "",
                        "hmm_score": 0.0,
                        "hmm_evalue": 1.0,
                        "evidence_source": "pyrodigal",
                    }
                )
            )
        else:
            out.append(p)
    return out


def _evaluate_thresholds_on_cache(
    hydrated_rows: List[Dict[str, Any]],
    thresholds: PhageStructureThresholds,
    *,
    hmm_min_score_filter: Optional[float] = None,
) -> Dict[str, Any]:
    eval_rows: List[Dict[str, Any]] = []
    tailed_total = 0
    tailed_tmp_found = 0
    false_tmp = 0
    merged_accs: List[str] = []
    tem_abs_errs: List[float] = []
    tem_pct_errs: List[float] = []

    for r in hydrated_rows:
        prots = _filter_hmm_cutoff(r["proteins_obj"], hmm_min_score_filter) if hmm_min_score_filter else r["proteins_obj"]
        info = {
            "length_bp": r["length_bp"],
            "gc_percent": r["gc_percent"],
            "dna_seq": r["dna_seq"],
            "proteins": prots,
            "genetic_code_used": r["genetic_code_used"],
            "genetic_code_auto_selected": r["genetic_code_auto_selected"],
            "sparse_rescued_orfs": r["sparse_rescued_orfs"],
        }
        c_res = evaluate_single_contig_structure(
            r["uid"],
            info,
            r["ptf_cnt"],
            r["ptf_clusters_obj"],
            default_genetic_code=11,
            workers=1,
            thresholds=thresholds,
        )
        pred_code = c_res.prediction.morphotype_code
        exp = str(r["expected"])
        primary_tmp = c_res.tmp_analyses[0] if c_res.tmp_analyses else None

        if exp in ("Myoviridae-like", "Siphoviridae-like"):
            tailed_total += 1
            if primary_tmp is not None:
                tailed_tmp_found += 1
        elif primary_tmp is not None:
            false_tmp += 1

        if primary_tmp and primary_tmp.evidence_kind == "merged_split_tmp":
            merged_accs.append(f"{r['acc']}:{primary_tmp.length_aa}")

        if r.get("verification_status") == "verified" and r.get("tem_nm") is not None and primary_tmp is not None:
            tem_val = float(r["tem_nm"])
            err = abs(primary_tmp.est_tail_length_nm - tem_val)
            tem_abs_errs.append(err)
            tem_pct_errs.append(err / tem_val * 100.0)

        eval_rows.append({
            "acc": r["acc"],
            "family": r["family"],
            "host": r.get("host") or r["family"],
            "expected": exp,
            "predicted": pred_code,
            "class_scores": c_res.prediction.class_scores,
            "connector": c_res.connector_profile.type_hint,
            "ptf_tail_protein_count": r["ptf_cnt"],
            "length_bp": r["length_bp"],
            "desc": r.get("desc") or r["family"],
            "tmp_aa": primary_tmp.length_aa if primary_tmp else None,
        })

    suite_metrics = evaluate_suite_a(eval_rows)
    mae = round(sum(tem_abs_errs) / len(tem_abs_errs), 3) if tem_abs_errs else None
    mape = round(sum(tem_pct_errs) / len(tem_pct_errs), 3) if tem_pct_errs else None
    return {
        "total": suite_metrics["total"],
        "correct": suite_metrics["correct"],
        "accuracy": suite_metrics["accuracy"],
        "macro_f1": suite_metrics["macro_f1"],
        "errors": [(e["acc"], e["expected"], e["predicted"]) for e in suite_metrics["errors"]],
        "tailed_tmp_found": tailed_tmp_found,
        "tailed_total": tailed_total,
        "false_tmp": false_tmp,
        "merged_accs": merged_accs,
        "tem_n": len(tem_abs_errs),
        "tem_mae_nm": mae,
        "tem_mape_pct": mape,
        "rows_by_acc": {row["acc"]: row for row in eval_rows},
    }


def _perturb_value(orig: Any, factor: float) -> Any:
    if isinstance(orig, int) and not isinstance(orig, bool):
        val = int(round(orig * factor))
        if orig > 0:
            val = max(1, val)
        return val if val != orig else (orig + (1 if factor > 1.0 else -1))
    return round(float(orig) * factor, 4)


def _run_live_pyhmmer_subset(
    hydrated_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """在 24 株跨四形态分层子集上实测 WSL PyHMMER 搜索参数 `Z` 与 `score_cutoff` 的敏感性。"""
    picked: List[Dict[str, Any]] = []
    for morph in ("Myoviridae-like", "Siphoviridae-like", "Podoviridae-like", "Non-tailed"):
        pool = [r for r in hydrated_rows if r["expected"] == morph]
        picked.extend(pool[:6])

    workers = get_safe_workers(12)
    configs = [
        ("hmm.pyhmmer_z", 200, "baseline_200"),
        ("hmm.pyhmmer_z", 160, "-20%_160"),
        ("hmm.pyhmmer_z", 240, "+20%_240"),
        ("hmm.default_score_cutoff", 22.4, "-20%_22.4"),
        ("hmm.default_score_cutoff", 33.6, "+20%_33.6"),
    ]
    out_records: List[Dict[str, Any]] = []
    base_correct = None
    base_tmp = None

    for key, val, tag in configs:
        th = override_threshold(DEFAULT_THRESHOLDS, key, val)
        cmap: Dict[str, Dict[str, Any]] = {}
        meta: Dict[str, Dict[str, Any]] = {}
        for r in picked:
            parsed = parse_input_contigs(fasta_path=str(r["fasta_path"]))
            main_cid = max(parsed.keys(), key=lambda k: parsed[k]["length_bp"])
            uid = r["uid"]
            info = parsed[main_cid]
            for p in info["proteins"]:
                p.contig_id = uid
            cmap[uid] = info
            meta[uid] = r

        predict_missing_orfs_parallel(cmap, genetic_code=11, auto_select_genetic_code=True, workers=workers)
        scan_proteins_with_pyhmmer(
            cmap,
            score_cutoff=th.hmm.default_score_cutoff,
            workers=workers,
            hmm_thresholds=th.hmm,
        )
        ptf_map = run_phagetailfinder_on_contigs(cmap, workers=workers)
        correct = 0
        tmp_found = 0
        for uid, info in cmap.items():
            ptf_cnt, ptf_cl = ptf_map.get(uid, (0, []))
            c_res = evaluate_single_contig_structure(uid, info, ptf_cnt, ptf_cl, workers=workers, thresholds=th)
            if c_res.prediction.morphotype_code == meta[uid]["expected"]:
                correct += 1
            if meta[uid]["expected"] in ("Myoviridae-like", "Siphoviridae-like") and c_res.tmp_analyses:
                tmp_found += 1

        if tag.startswith("baseline"):
            base_correct = correct
            base_tmp = tmp_found
        out_records.append({
            "key": key,
            "tag": tag,
            "value": val,
            "n": len(picked),
            "correct": correct,
            "delta_correct": correct - (base_correct or correct),
            "tailed_tmp_found": tmp_found,
            "delta_tmp": tmp_found - (base_tmp or tmp_found),
        })
    return out_records


def _write_summary_md(report: Dict[str, Any]) -> None:
    base = report["baseline"]
    lines = [
        "# T2.1 噬菌体结构预测阈值敏感性分析报告",
        "",
        f"- 调参评估总规模：`{base['total']}` 株（`Suite A + B + C + D` 去重，严禁包含 `Suite E` 盲测集）",
        f"- 默认基准配置零回归验收：**`{base['correct']} / {base['total']} ({base['accuracy'] * 100:.2f}%)`**, `Macro-F1 = {base['macro_f1']}`",
        f"- 有尾 TMP 召回：`{base['tailed_tmp_found']} / {base['tailed_total']}` | 假 TMP：`{base['false_tmp']}` | D3112 合并：`{base['merged_accs']}`",
        f"- `verified` TEM 定量基准（`n={base['tem_n']}`）：`MAE = {base['tem_mae_nm']} nm`, `MAPE = {base['tem_mape_pct']}%`",
        "",
        "## 一、 ±20% 单因素敏感性排名（按综合波动降序）",
        "",
        "| 排名 | 阈值键名 | 默认值 | -20% 准确率 / Δ | +20% 准确率 / Δ | TMP 召回区间 | 假 TMP 区间 | 敏感度评级与建议 |",
        "| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :--- |",
    ]
    for rank, item in enumerate(report["perturbations"], start=1):
        low = item["minus_20"]
        high = item["plus_20"]
        tmp_rng = f"{min(low['tailed_tmp_found'], high['tailed_tmp_found'])}..{max(low['tailed_tmp_found'], high['tailed_tmp_found'])}"
        ftmp_rng = f"{min(low['false_tmp'], high['false_tmp'])}..{max(low['false_tmp'], high['false_tmp'])}"
        lines.append(
            f"| {rank} | `{item['key']}` | `{item['default']}` | "
            f"`{low['accuracy'] * 100:.2f}%` ({low['delta_correct']:+d}) | "
            f"`{high['accuracy'] * 100:.2f}%` ({high['delta_correct']:+d}) | "
            f"`{tmp_rng}` | `{ftmp_rng}` | {item['stability_note']} |"
        )

    lines.extend([
        "",
        "## 二、 PyHMMER `Z` 与比特分 `default_score_cutoff` 实测敏感性（24 株分层子集）",
        "",
        "| 阈值参数 | 扰动设定 | 正确率 | Δ 正确数 | 有尾 TMP 召回 |",
        "| :--- | :--- | :---: | :---: | :---: |",
    ])
    for r in report["live_pyhmmer_subset"]:
        lines.append(
            f"| `{r['key']}` | `{r['tag']}` (`{r['value']}`) | `{r['correct']}/{r['n']}` | `{r['delta_correct']:+d}` | `{r['tailed_tmp_found']}/12` |"
        )
    SUMMARY_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="T2.1 噬菌体结构预测阈值敏感性分析脚本")
    parser.add_argument("--fresh", action="store_true", help="强制清空特征缓存并重算")
    args = parser.parse_args()

    t0 = time.perf_counter()
    entries = _assemble_tuning_entries()
    raw_cache = _build_or_load_feature_cache(entries, fresh=args.fresh, batch_size=25)
    hydrated = _hydrate_records(raw_cache)

    print("=== [Stage 2] 运行默认配置基线校验与 ±20% 单因素敏感性扫描 ===")
    baseline = _evaluate_thresholds_on_cache(hydrated, DEFAULT_THRESHOLDS)
    print(
        f"  [Baseline] {baseline['correct']}/{baseline['total']} (Acc={baseline['accuracy']}), "
        f"TMP={baseline['tailed_tmp_found']}/{baseline['tailed_total']}, FalseTMP={baseline['false_tmp']}, "
        f"Merged={baseline['merged_accs']}, TEM MAE={baseline['tem_mae_nm']} nm"
    )
    if baseline["correct"] != baseline["total"] or baseline["false_tmp"] != 0:
        raise RuntimeError(f"集中化阈值基线未通过零回归校验！errors={baseline['errors']}")

    flat_defaults = list_threshold_keys(DEFAULT_THRESHOLDS)
    perturb_results: List[Dict[str, Any]] = []

    for key in PERTURB_KEYS:
        orig_val = flat_defaults[key]
        low_val = _perturb_value(orig_val, 0.80)
        high_val = _perturb_value(orig_val, 1.20)
        low_res = _evaluate_thresholds_on_cache(hydrated, override_threshold(DEFAULT_THRESHOLDS, key, low_val))
        high_res = _evaluate_thresholds_on_cache(hydrated, override_threshold(DEFAULT_THRESHOLDS, key, high_val))

        max_drop = max(
            baseline["correct"] - low_res["correct"],
            baseline["correct"] - high_res["correct"],
        )
        max_tmp_drop = max(
            baseline["tailed_tmp_found"] - low_res["tailed_tmp_found"],
            baseline["tailed_tmp_found"] - high_res["tailed_tmp_found"],
        )
        max_ftmp_inc = max(low_res["false_tmp"], high_res["false_tmp"])
        sens_score = max_drop * 10 + max_tmp_drop * 5 + max_ftmp_inc * 5

        if sens_score == 0:
            note = "零敏感（平台期稳定）"
        elif max_drop > 0:
            note = f"需关注形态波动（最高 -{max_drop} 株，TMP 变动 -{max_tmp_drop} / 误报 +{max_ftmp_inc}），建议保持当前防漂移护栏"
        else:
            note = f"形态完全稳健（仅 TMP 检出 -{max_tmp_drop} / 误报 +{max_ftmp_inc}），建议维持保守锚点协同"

        def _compact_side(res: Dict[str, Any], v: Any) -> Dict[str, Any]:
            flipped = [
                {"acc": acc, "expected": row["expected"], "predicted": row["predicted"]}
                for acc, row in res["rows_by_acc"].items()
                if row["predicted"] != row["expected"]
            ]
            return {
                "value": v,
                "correct": res["correct"],
                "delta_correct": res["correct"] - baseline["correct"],
                "accuracy": res["accuracy"],
                "tailed_tmp_found": res["tailed_tmp_found"],
                "false_tmp": res["false_tmp"],
                "tem_mae_nm": res["tem_mae_nm"],
                "tem_mape_pct": res["tem_mape_pct"],
                "flipped_samples": flipped[:10],
            }

        perturb_results.append({
            "key": key,
            "default": orig_val,
            "sensitivity_score": sens_score,
            "stability_note": note,
            "minus_20": _compact_side(low_res, low_val),
            "plus_20": _compact_side(high_res, high_val),
        })

    # 额外补充 hmm.default_score_cutoff (+20% = 33.6) 在全量 343 株缓存上的过滤验证
    sc_plus = _evaluate_thresholds_on_cache(hydrated, DEFAULT_THRESHOLDS, hmm_min_score_filter=33.6)
    perturb_results.append({
        "key": "hmm.default_score_cutoff (cache +20% only)",
        "default": DEFAULT_THRESHOLDS.hmm.default_score_cutoff,
        "sensitivity_score": (baseline["correct"] - sc_plus["correct"]) * 10
        + max(0, baseline["tailed_tmp_found"] - sc_plus["tailed_tmp_found"]) * 5,
        "stability_note": (
            f"全量上调 score_cutoff 至 33.6：形态 {sc_plus['correct']}/{sc_plus['total']}，"
            f"TMP {sc_plus['tailed_tmp_found']}/{sc_plus['tailed_total']}"
        ),
        "minus_20": {
            "value": "见实测24株子集",
            "correct": baseline["correct"],
            "delta_correct": 0,
            "accuracy": baseline["accuracy"],
            "tailed_tmp_found": baseline["tailed_tmp_found"],
            "false_tmp": baseline["false_tmp"],
            "tem_mae_nm": baseline["tem_mae_nm"],
            "tem_mape_pct": baseline["tem_mape_pct"],
            "flipped_samples": [],
        },
        "plus_20": {
            "value": 33.6,
            "correct": sc_plus["correct"],
            "delta_correct": sc_plus["correct"] - baseline["correct"],
            "accuracy": sc_plus["accuracy"],
            "tailed_tmp_found": sc_plus["tailed_tmp_found"],
            "false_tmp": sc_plus["false_tmp"],
            "tem_mae_nm": sc_plus["tem_mae_nm"],
            "tem_mape_pct": sc_plus["tem_mape_pct"],
            "flipped_samples": [
                {"acc": acc, "expected": r["expected"], "predicted": r["predicted"]}
                for acc, r in sc_plus["rows_by_acc"].items()
                if r["predicted"] != r["expected"]
            ][:10],
        },
    })

    perturb_results.sort(key=lambda x: (-x["sensitivity_score"], x["key"]))

    print("=== [Stage 3] 在 24 株分层子集上实测 PyHMMER Z 与 score_cutoff 实时扫描 ===")
    live_subset = _run_live_pyhmmer_subset(hydrated)

    baseline_out = {k: v for k, v in baseline.items() if k != "rows_by_acc"}
    report = {
        "elapsed_sec": round(time.perf_counter() - t0, 2),
        "baseline": baseline_out,
        "perturbations": perturb_results,
        "live_pyhmmer_subset": live_subset,
    }
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_summary_md(report)

    print(f"敏感性分析报告已落盘: {REPORT_JSON} ({report['elapsed_sec']}s)")
    print("Top 5 高敏感阈值:")
    for item in perturb_results[:5]:
        print(
            f"  - {item['key']}: score={item['sensitivity_score']} | "
            f"-20% -> {item['minus_20']['correct']}/{baseline['total']} | "
            f"+20% -> {item['plus_20']['correct']}/{baseline['total']}"
        )


if __name__ == "__main__":
    main()
