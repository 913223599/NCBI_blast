# -*- coding: utf-8 -*-
"""
噬菌体结构与尾部形态预测——大规模真实 ICTV 形态分类 + 电镜 (TEM) 尾长基准测试脚本

包含两套独立验证集（全量使用纯裸 FASTA 核酸输入，零参考注释泄漏）：
1. Suite A (120 株跨 ICTV 20+ 科分层抽样盲测集)：评估 Myo / Sipho / Podo / Non-tailed 四分类准确率、Macro-F1、混淆矩阵及失误病理解析；
2. Suite B (25+ 株文献实测电镜 TEM 尾长金标准集)：评估现行 TMP 0.145 nm/aa 公式的 Pearson r / R² / MAE / MAPE / 系统偏差，并开展多策略交叉验证对照。
"""
from __future__ import annotations

import csv
import json
import math
import statistics
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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

LOCAL_FASTA_DIR = Path(r"F:\Phage data\fasta")
BENCH_DIR = Path(r"F:\Phage data\benchmarks\phage_structure")
TEM_FASTA_DIR = BENCH_DIR / "tem_refs"
RESULTS_DIR = PROJECT_ROOT / "results" / "benchmarks" / "phage_structure"
TEM_TRUTH_TSV = PROJECT_ROOT / "tests" / "fixtures" / "phage_structure" / "tem_truth.tsv"


@dataclass(frozen=True)
class TemTruthRecord:
    """文献电镜 (TEM / Cryo-EM) 实测尾长标准真值记录。"""

    suite: str
    name: str
    accession: str
    morphotype: str
    tem_nm: float
    tem_range: str
    state: str
    includes_baseplate: str
    method: str
    doi: str
    verification_status: str
    notes: str


def load_tem_truth_records(
    suite: Optional[str] = None,
    verified_only: bool = False,
    tsv_path: Optional[Path] = None,
) -> List[TemTruthRecord]:
    """从版本化真值表 tem_truth.tsv 加载电镜尾长金标准集合。"""
    target_path = tsv_path or TEM_TRUTH_TSV
    if not target_path.is_file():
        raise FileNotFoundError(f"缺失 TEM 真值表文件: {target_path}")
    records: List[TemTruthRecord] = []
    with target_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            row_suite = (row.get("suite") or "").strip()
            status = (row.get("verification_status") or "").strip()
            if suite and row_suite != suite:
                continue
            if verified_only and status != "verified":
                continue
            records.append(
                TemTruthRecord(
                    suite=row_suite,
                    name=(row.get("name") or "").strip(),
                    accession=(row.get("accession") or "").strip(),
                    morphotype=(row.get("morphotype") or "").strip(),
                    tem_nm=float(row["tem_nm"]),
                    tem_range=(row.get("tem_range") or "").strip(),
                    state=(row.get("state") or "unknown").strip(),
                    includes_baseplate=(row.get("includes_baseplate") or "unknown").strip(),
                    method=(row.get("method") or "TEM").strip(),
                    doi=(row.get("doi") or "").strip(),
                    verification_status=status,
                    notes=(row.get("notes") or "").strip(),
                )
            )
    return records

# 2022+ ICTV 权威形态明确科映射 (覆盖 27 个科)
FAMILY_TO_MORPH: Dict[str, str] = {
    "Straboviridae": "Myoviridae-like",
    "Herelleviridae": "Myoviridae-like",
    "Ackermannviridae": "Myoviridae-like",
    "Kyanoviridae": "Myoviridae-like",
    "Peduoviridae": "Myoviridae-like",
    "Chaseviridae": "Myoviridae-like",
    "Pootjesviridae": "Myoviridae-like",
    "Vertoviridae": "Myoviridae-like",
    "Arenbergviridae": "Myoviridae-like",
    "Vilmaviridae": "Siphoviridae-like",
    "Drexlerviridae": "Siphoviridae-like",
    "Demerecviridae": "Siphoviridae-like",
    "Aliceevansviridae": "Siphoviridae-like",
    "Casjensviridae": "Siphoviridae-like",
    "Mesyanzhinovviridae": "Siphoviridae-like",
    "Orlajenseniviridae": "Siphoviridae-like",
    "Zierdtviridae": "Siphoviridae-like",
    "Autographiviridae": "Podoviridae-like",
    "Autotranscriptaviridae": "Podoviridae-like",
    "Schitoviridae": "Podoviridae-like",
    "Rountreeviridae": "Podoviridae-like",
    "Guelinviridae": "Podoviridae-like",
    "Salasmaviridae": "Podoviridae-like",
    "Zobellviridae": "Podoviridae-like",
    "Grimontviridae": "Podoviridae-like",
    "Microviridae": "Non-tailed",
    "Inoviridae": "Non-tailed",
    "Tectiviridae": "Non-tailed",
    "Fiersviridae": "Non-tailed",
    "Corticoviridae": "Non-tailed",
}

# 已公开文献 TEM 实测尾长金标准 (从 tem_truth.tsv 单点真源动态加载)
# 格式: (name, acc_base, expected_morphotype, tem_mid_nm, tem_range_str, source_note)
SUITE_B_TRUTH_RECORDS: List[TemTruthRecord] = load_tem_truth_records(suite="suite_b")
TEM_TRUTH_BY_ACC: Dict[str, TemTruthRecord] = {r.accession: r for r in SUITE_B_TRUTH_RECORDS}
TEM_REFERENCES: List[Tuple[str, str, str, float, str, str]] = [
    (r.name, r.accession, r.morphotype, r.tem_nm, r.tem_range, r.notes)
    for r in SUITE_B_TRUTH_RECORDS
]

# 仅在单元测试用过的代表株排除在 120 株未知抽样池外，保证真实泛化测试
EXCLUDE_ACCS = {"NC_000866", "NC_001416", "NC_001604", "NC_002371", "NC_003287", "NC_005859"}


def ensure_fasta_for_acc(acc_base: str, local_index: Dict[str, Path]) -> Optional[Path]:
    if acc_base in local_index:
        return local_index[acc_base]
    TEM_FASTA_DIR.mkdir(parents=True, exist_ok=True)
    cached = TEM_FASTA_DIR / f"{acc_base}.fasta"
    if cached.is_file() and cached.stat().st_size > 200:
        return cached
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=nuccore&id={acc_base}&rettype=fasta&retmode=text"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "NCBI-Workbench-Benchmark/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            txt = resp.read().decode("utf-8", errors="ignore")
        if txt.startswith(">") and len(txt) > 300:
            cached.write_text(txt, encoding="utf-8")
            return cached
    except Exception as exc:
        print(f"[WARN] 拉取 {acc_base} 失败: {exc}")
    return None


def sample_120_ictv_genomes(local_index: Dict[str, Path], per_class: int = 30) -> List[Dict[str, str]]:
    """从 INPHARED x 本地 F:\\Phage data\\fasta 严格分层轮转抽取 120 株（每科/每宿主充分分散）。"""
    inphared_tsv = PROJECT_ROOT / "database" / "pharokka_db" / "9Aug2025_data.tsv"
    pools: Dict[str, Dict[str, List[Dict[str, str]]]] = defaultdict(lambda: defaultdict(list))

    with inphared_tsv.open("r", encoding="utf-8", errors="ignore", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            acc_full = str(row.get("Accession") or "").strip()
            acc_base = acc_full.split(".")[0]
            fam = str(row.get("Family") or "").strip()
            if acc_base in EXCLUDE_ACCS or acc_base not in local_index or fam not in FAMILY_TO_MORPH:
                continue
            morph = FAMILY_TO_MORPH[fam]
            pools[morph][fam].append({
                "acc": acc_base,
                "family": fam,
                "host": str(row.get("Host") or "Unspecified").strip(),
                "expected": morph,
                "desc": str(row.get("Description") or "").strip(),
                "fasta_path": str(local_index[acc_base]),
            })

    selected: List[Dict[str, str]] = []
    for morph in ("Myoviridae-like", "Siphoviridae-like", "Podoviridae-like", "Non-tailed"):
        fam_dict = pools[morph]
        # 按科轮转挑选（同时尽量分散宿主）确保覆盖所有代表性科
        picked_hosts: Counter[str] = Counter()
        for fam in fam_dict:
            fam_dict[fam].sort(key=lambda x: x["acc"])
        bucket: List[Dict[str, str]] = []
        round_idx = 0
        fam_keys = sorted(fam_dict.keys())
        while len(bucket) < per_class and round_idx < 100:
            progressed = False
            for fam in fam_keys:
                if len(bucket) >= per_class:
                    break
                items = fam_dict[fam]
                # 优先选当前宿主出现次数最少的条目
                unused = [it for it in items if all(it["acc"] != b["acc"] for b in bucket)]
                if not unused:
                    continue
                unused.sort(key=lambda it: (picked_hosts[it["host"]], it["acc"]))
                chosen = unused[0]
                bucket.append(chosen)
                picked_hosts[chosen["host"]] += 1
                progressed = True
            if not progressed:
                break
            round_idx += 1
        selected.extend(bucket)
    return selected


def run_batch_pipeline(
    entries: List[Dict[str, str]],
    *,
    checkpoint_path: Path,
    batch_size: int = 20,
    enable_ptf: bool = True,
) -> List[Dict[str, Any]]:
    """按批执行完整裸 FASTA 预测并即时写入断点 JSONL（兼顾 PyHMMER 吞吐与 OOM 防护）。"""
    done_map: Dict[str, Dict[str, Any]] = {}
    if checkpoint_path.is_file():
        for line in checkpoint_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                done_map[rec["acc"]] = rec

    pending = [e for e in entries if e["acc"] not in done_map]
    workers = get_safe_workers(14)

    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        cmap: Dict[str, Dict[str, Any]] = {}
        entry_by_cid: Dict[str, Dict[str, str]] = {}

        for item in batch:
            parsed = parse_input_contigs(fasta_path=item["fasta_path"])
            # 若样本偶发多 Contig，选最长为主序列并规范 ID 防重名
            main_cid = max(parsed.keys(), key=lambda k: parsed[k]["length_bp"])
            uid = f"{item['acc']}__{main_cid}"
            info = parsed[main_cid]
            for p in info["proteins"]:
                p.contig_id = uid
            cmap[uid] = info
            entry_by_cid[uid] = item

        predict_missing_orfs_parallel(cmap, genetic_code=11, workers=workers)
        scan_proteins_with_pyhmmer(cmap, workers=workers)
        ptf_map: Dict[str, Any] = {}
        if enable_ptf:
            try:
                ptf_map = run_phagetailfinder_on_contigs(cmap, workers=workers)
            except Exception as exc:
                print(f"[WARN] PhageTailFinder batch err: {exc}")

        with checkpoint_path.open("a", encoding="utf-8") as out_fh:
            for uid, info in cmap.items():
                item = entry_by_cid[uid]
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
                    (mm.tail_sheath_count + mm.major_tail_count + mm.tail_tube_count + mm.tail_assembly_chaperone_count + verified_tmp_cnt) > 0
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

                row_out: Dict[str, Any] = {
                    **item,
                    "length_bp": info["length_bp"],
                    "total_orfs": len(prots),
                    "genetic_code_used": int(info.get("genetic_code_used") or 11),
                    "sparse_rescued_orfs": int(info.get("sparse_rescued_orfs") or 0),
                    "predicted": pred.morphotype_code,
                    "confidence": pred.confidence,
                    "class_scores": pred.class_scores,
                    "connector": cp.type_hint,
                    "decision_basis": pred.decision_basis,
                    "warnings": pred.warnings,
                    "ptf_tail_protein_count": ptf_cnt,
                    "ptf_cluster_count": len(ptf_clusters),
                    "matrix": mm.model_dump(),
                    "tmp": (
                        {
                            "locus_tag": primary_tmp.locus_tag,
                            "product": primary_tmp.product,
                            "evidence_kind": primary_tmp.evidence_kind,
                            "length_aa": primary_tmp.length_aa,
                            "est_tail_length_nm": primary_tmp.est_tail_length_nm,
                            "polyx_total_aa": primary_tmp.polyx_total_aa,
                            "tr_total_aa": primary_tmp.tr_total_aa,
                            "hydrophobic_count": len(primary_tmp.hydrophobic_segments),
                            "hydrophobic_segments": [s.model_dump() for s in primary_tmp.hydrophobic_segments],
                            "ptf_pfam": tmp_prot.ptf_pfam if tmp_prot else "",
                            "translation": tmp_prot.translation if tmp_prot else "",
                        }
                        if primary_tmp
                        else None
                    ),
                }
                out_fh.write(json.dumps(row_out, ensure_ascii=False) + "\n")
                done_map[item["acc"]] = row_out
        print(f"  Batch {start // batch_size + 1} done ({min(start + batch_size, len(pending))}/{len(pending)})")

    return [done_map[e["acc"]] for e in entries if e["acc"] in done_map]


def evaluate_suite_a(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    labels = ["Myoviridae-like", "Siphoviridae-like", "Podoviridae-like", "Non-tailed"]
    pred_cols = labels + ["Incomplete"]
    cm: Dict[str, Dict[str, int]] = {t: {p: 0 for p in pred_cols} for t in labels}
    errors: List[Dict[str, Any]] = []
    for r in rows:
        t = r["expected"]
        p = r["predicted"]
        cm[t][p] = cm[t].get(p, 0) + 1
        if t != p:
            errors.append({
                "acc": r["acc"],
                "family": r["family"],
                "host": r["host"],
                "expected": t,
                "predicted": p,
                "scores": r["class_scores"],
                "connector": r["connector"],
                "ptf_cnt": r["ptf_tail_protein_count"],
                "length_bp": r["length_bp"],
                "desc": r["desc"],
            })

    total = len(rows)
    correct = sum(cm[l][l] for l in labels)
    per_class: Dict[str, Dict[str, float]] = {}
    f1s: List[float] = []
    for l in labels:
        tp = cm[l][l]
        fn = sum(cm[l][p] for p in pred_cols if p != l)
        fp = sum(cm[t][l] for t in labels if t != l)
        prec = tp / max(1, tp + fp)
        rec = tp / max(1, tp + fn)
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0
        per_class[l] = {"precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4), "support": tp + fn}
        f1s.append(f1)

    return {
        "total": total,
        "correct": correct,
        "accuracy": round(correct / max(1, total), 4),
        "macro_f1": round(sum(f1s) / len(f1s), 4),
        "confusion_matrix": cm,
        "per_class": per_class,
        "errors": errors,
    }


def _pearson(xs: List[float], ys: List[float]) -> float:
    mx, my = statistics.mean(xs), statistics.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return num / den if den > 1e-12 else 0.0


def _compute_tem_regression_stats(paired: List[Dict[str, Any]]) -> Dict[str, Any]:
    """针对传入 TEM 样本对计算 Pearson r、MAE/MAPE 与分形态 LOOCV 指标。"""
    valid = [p for p in paired if p["tmp_aa"] is not None]
    xs = [float(p["tmp_aa"]) for p in valid]
    ys_true = [float(p["tem_nm"]) for p in valid]
    ys_0145 = [float(p["est_0145_nm"]) for p in valid]
    err_0145 = [abs(a - b) for a, b in zip(ys_0145, ys_true)]
    mape_0145 = [abs(a - b) / b * 100.0 for a, b in zip(ys_0145, ys_true)]

    by_morph: Dict[str, Dict[str, float]] = {}
    for m in ("Myoviridae-like", "Siphoviridae-like"):
        sub = [p for p in valid if p["expected_morph"] == m]
        if len(sub) >= 3:
            sx = [float(p["tmp_aa"]) for p in sub]
            sy = [float(p["tem_nm"]) for p in sub]
            sp = [float(p["est_0145_nm"]) for p in sub]
            by_morph[m] = {
                "n": len(sub),
                "pearson_r": round(_pearson(sx, sy), 4),
                "mae_0145_nm": round(statistics.mean(abs(a - b) for a, b in zip(sp, sy)), 2),
                "mape_0145_pct": round(statistics.mean(abs(a - b) / b * 100.0 for a, b in zip(sp, sy)), 2),
                "mean_signed_bias_nm": round(statistics.mean(a - b for a, b in zip(sp, sy)), 2),
            }

    def loocv_linear(sub_x: List[float], sub_y: List[float]) -> Tuple[float, float, float, float]:
        loocv_err = []
        loocv_pct = []
        n = len(sub_x)
        for i in range(n):
            tx = [sub_x[j] for j in range(n) if j != i]
            ty = [sub_y[j] for j in range(n) if j != i]
            mx, my = statistics.mean(tx), statistics.mean(ty)
            denom = sum((x - mx) ** 2 for x in tx)
            slope = sum((x - mx) * (y - my) for x, y in zip(tx, ty)) / denom if denom > 0 else 0.145
            inter = my - slope * mx
            pred = slope * sub_x[i] + inter
            loocv_err.append(abs(pred - sub_y[i]))
            loocv_pct.append(abs(pred - sub_y[i]) / sub_y[i] * 100.0)
        mx, my = statistics.mean(sub_x), statistics.mean(sub_y)
        slope = sum((x - mx) * (y - my) for x, y in zip(sub_x, sub_y)) / sum((x - mx) ** 2 for x in sub_x)
        inter = my - slope * mx
        return round(slope, 5), round(inter, 2), round(statistics.mean(loocv_err), 2), round(statistics.mean(loocv_pct), 2)

    slope_all, inter_all, loocv_mae_all, loocv_mape_all = loocv_linear(xs, ys_true) if len(xs) >= 5 else (0.145, 0.0, 0.0, 0.0)
    normal_sub = [p for p in valid if p["tmp_aa"] <= 2500]
    loocv_normal = (
        loocv_linear([float(p["tmp_aa"]) for p in normal_sub], [float(p["tem_nm"]) for p in normal_sub])
        if len(normal_sub) >= 5
        else (0.145, 0.0, 0.0, 0.0)
    )
    sipho_norm = [p for p in normal_sub if p["expected_morph"] == "Siphoviridae-like"]
    myo_norm = [p for p in normal_sub if p["expected_morph"] == "Myoviridae-like"]

    def _mae_mape_0145(sub: List[Dict[str, Any]]) -> Dict[str, float]:
        if not sub:
            return {"n": 0, "mae": 0.0, "mape": 0.0, "r": 0.0, "bias": 0.0}
        sx = [float(p["tmp_aa"]) for p in sub]
        sy = [float(p["tem_nm"]) for p in sub]
        sp = [float(p["est_0145_nm"]) for p in sub]
        return {
            "n": len(sub),
            "r": round(_pearson(sx, sy), 4) if len(sub) >= 3 else 0.0,
            "mae": round(statistics.mean(abs(a - b) for a, b in zip(sp, sy)), 2),
            "mape": round(statistics.mean(abs(a - b) / b * 100.0 for a, b in zip(sp, sy)), 2),
            "bias": round(statistics.mean(a - b for a, b in zip(sp, sy)), 2),
        }

    morph_loocv_abs_errs: List[float] = []
    morph_loocv_pct_errs: List[float] = []
    for sub in (myo_norm, sipho_norm):
        if len(sub) >= 4:
            sx = [float(p["tmp_aa"]) for p in sub]
            sy = [float(p["tem_nm"]) for p in sub]
            for i in range(len(sub)):
                tx = [sx[j] for j in range(len(sub)) if j != i]
                ty = [sy[j] for j in range(len(sub)) if j != i]
                mx, my = statistics.mean(tx), statistics.mean(ty)
                denom = sum((x - mx) ** 2 for x in tx)
                sl = sum((x - mx) * (y - my) for x, y in zip(tx, ty)) / denom if denom > 0 else 0.145
                ic = my - sl * mx
                pr = sl * sx[i] + ic
                morph_loocv_abs_errs.append(abs(pr - sy[i]))
                morph_loocv_pct_errs.append(abs(pr - sy[i]) / sy[i] * 100.0)

    return {
        "n_paired": len(paired),
        "n_tmp_found": len(valid),
        "pearson_r_all": round(_pearson(xs, ys_true), 4) if len(xs) >= 3 else 0.0,
        "mae_0145_nm": round(statistics.mean(err_0145), 2) if err_0145 else 0.0,
        "mape_0145_pct": round(statistics.mean(mape_0145), 2) if mape_0145 else 0.0,
        "standard_range_le2500aa": _mae_mape_0145(normal_sub),
        "loocv_linear_fit_all": {
            "slope_nm_per_aa": slope_all,
            "intercept_nm": inter_all,
            "loocv_mae_nm": loocv_mae_all,
            "loocv_mape_pct": loocv_mape_all,
        },
        "loocv_linear_fit_le2500aa": {
            "slope_nm_per_aa": loocv_normal[0],
            "intercept_nm": loocv_normal[1],
            "loocv_mae_nm": loocv_normal[2],
            "loocv_mape_pct": loocv_normal[3],
        },
        "loocv_morph_stratified_le2500aa": {
            "loocv_mae_nm": round(statistics.mean(morph_loocv_abs_errs), 2) if morph_loocv_abs_errs else 0.0,
            "loocv_mape_pct": round(statistics.mean(morph_loocv_pct_errs), 2) if morph_loocv_pct_errs else 0.0,
        },
        "by_morph": by_morph,
    }


def evaluate_suite_b_tem(rows: List[Dict[str, Any]], tem_meta: Dict[str, Tuple[str, str, str, float, str, str]]) -> Dict[str, Any]:
    paired: List[Dict[str, Any]] = []
    for r in rows:
        meta = tem_meta[r["acc"]]
        name, acc_key, exp_m, tem_nm, tem_rng, note = meta
        truth_rec = TEM_TRUTH_BY_ACC.get(acc_key)
        tmp = r.get("tmp")
        paired.append({
            "name": name,
            "acc": acc_key,
            "expected_morph": exp_m,
            "pred_morph": r["predicted"],
            "tem_nm": tem_nm,
            "tem_range": tem_rng,
            "verification_status": truth_rec.verification_status if truth_rec else "unverified",
            "doi": truth_rec.doi if truth_rec else "",
            "tem_state": truth_rec.state if truth_rec else "unknown",
            "includes_baseplate": truth_rec.includes_baseplate if truth_rec else "unknown",
            "tem_method": truth_rec.method if truth_rec else "TEM",
            "tmp_aa": tmp["length_aa"] if tmp else None,
            "est_0145_nm": tmp["est_tail_length_nm"] if tmp else None,
            "polyx_aa": tmp["polyx_total_aa"] if tmp else None,
            "tr_aa": tmp["tr_total_aa"] if tmp else None,
            "evidence_kind": tmp["evidence_kind"] if tmp else None,
            "note": note,
        })

    verified_paired = [p for p in paired if p["verification_status"] == "verified"]
    unverified_items = [{"name": p["name"], "acc": p["acc"], "tem_nm": p["tem_nm"]} for p in paired if p["verification_status"] != "verified"]

    # 主定量统计严格仅纳入 verified 真值，避免未核实文献噪声误导回归校准
    primary_stats = _compute_tem_regression_stats(verified_paired if verified_paired else paired)
    all_stats = _compute_tem_regression_stats(paired)

    return {
        "total_tem": len(paired),
        "verified_total": len(verified_paired),
        "verified_tmp_found_count": primary_stats["n_tmp_found"],
        "tmp_found_count": all_stats["n_tmp_found"],
        "morph_correct": sum(1 for p in paired if p["pred_morph"] == p["expected_morph"]),
        "unverified_excluded_count": len(unverified_items),
        "unverified_excluded": unverified_items,
        "pearson_r_all": primary_stats["pearson_r_all"],
        "mae_0145_nm": primary_stats["mae_0145_nm"],
        "mape_0145_pct": primary_stats["mape_0145_pct"],
        "standard_range_le2500aa": primary_stats["standard_range_le2500aa"],
        "loocv_linear_fit_all": primary_stats["loocv_linear_fit_all"],
        "loocv_linear_fit_le2500aa": primary_stats["loocv_linear_fit_le2500aa"],
        "loocv_morph_stratified_le2500aa": primary_stats["loocv_morph_stratified_le2500aa"],
        "by_morph": primary_stats["by_morph"],
        "all_entries_incl_unverified": all_stats,
        "details": paired,
    }


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh", action="store_true", help="清空历史 Checkpoint 重新全量评测")
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if args.fresh:
        for cp_file in RESULTS_DIR.glob("*_checkpoints.jsonl"):
            cp_file.unlink(missing_ok=True)
    local_index = {p.stem.split(".")[0]: p for p in LOCAL_FASTA_DIR.glob("*.fasta")}

    t0 = time.perf_counter()
    print("=== [Suite A] 构建 120 株跨 24 个 ICTV 科随机分层盲测集 ===")
    suite_a_entries = sample_120_ictv_genomes(local_index, per_class=30)
    print(f"已选定 {len(suite_a_entries)} 株基因组，开始盲测执行...")
    suite_a_rows = run_batch_pipeline(
        suite_a_entries,
        checkpoint_path=RESULTS_DIR / "suite_a_120_checkpoints.jsonl",
        batch_size=20,
        enable_ptf=True,
    )
    suite_a_report = evaluate_suite_a(suite_a_rows)

    print("=== [Suite B] 构建 30 株文献电镜 TEM 尾长金标准基准集 ===")
    tem_entries: List[Dict[str, str]] = []
    tem_meta: Dict[str, Tuple[str, str, str, float, str, str]] = {}
    for row_meta in TEM_REFERENCES:
        name, acc, exp_m, tem_nm, rng, note = row_meta
        fp = ensure_fasta_for_acc(acc, local_index)
        if fp is not None:
            tem_entries.append({
                "acc": acc,
                "family": name,
                "host": note,
                "expected": exp_m,
                "desc": f"{name} TEM={tem_nm}nm",
                "fasta_path": str(fp),
            })
            tem_meta[acc] = row_meta
    print(f"成功备齐 {len(tem_entries)} / {len(TEM_REFERENCES)} 株电镜金标准序列，开始实测...")
    suite_b_rows = run_batch_pipeline(
        tem_entries,
        checkpoint_path=RESULTS_DIR / "suite_b_tem_checkpoints.jsonl",
        batch_size=15,
        enable_ptf=True,
    )
    suite_b_report = evaluate_suite_b_tem(suite_b_rows, tem_meta)

    elapsed = round(time.perf_counter() - t0, 2)
    final = {
        "elapsed_sec": elapsed,
        "suite_a_120_ictv": suite_a_report,
        "suite_b_tem": suite_b_report,
    }
    report_path = RESULTS_DIR / "benchmark_report.json"
    report_path.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n================ 基准测试汇总结果 ================")
    print(f"总耗时: {elapsed} s | 报告: {report_path}")
    print(f"[Suite A] ICTV 120株盲测: Accuracy={suite_a_report['accuracy']} ({suite_a_report['correct']}/{suite_a_report['total']}), Macro-F1={suite_a_report['macro_f1']}")
    print("Per-class:", suite_a_report["per_class"])
    print("Confusion Matrix:", suite_a_report["confusion_matrix"])
    print(f"误判样本数: {len(suite_a_report['errors'])}")
    for e in suite_a_report["errors"][:15]:
        print(f"  ERR: {e['acc']} ({e['family']}, host={e['host']}) exp={e['expected']} -> pred={e['predicted']} scores={e['scores']} conn={e['connector']} ptf={e['ptf_cnt']}")
    print(
        f"\n[Suite B] TEM 实测尾长验证 (verified={suite_b_report['verified_tmp_found_count']}/{suite_b_report['verified_total']}, "
        f"all={suite_b_report['tmp_found_count']}/{suite_b_report['total_tem']}, 剔除unverified={suite_b_report['unverified_excluded_count']}, "
        f"形态正确 {suite_b_report['morph_correct']}/{suite_b_report['total_tem']}):"
    )
    print(f"  Verified Pearson r={suite_b_report['pearson_r_all']}, MAE(0.145)={suite_b_report['mae_0145_nm']}nm, MAPE(0.145)={suite_b_report['mape_0145_pct']}%")
    print(f"  All-Incl-Unverified Summary: r={suite_b_report['all_entries_incl_unverified']['pearson_r_all']}, MAE={suite_b_report['all_entries_incl_unverified']['mae_0145_nm']}nm, MAPE={suite_b_report['all_entries_incl_unverified']['mape_0145_pct']}%")
    print(f"  Standard <=2500aa (0.145): {suite_b_report['standard_range_le2500aa']}")
    print(f"  By Morph: {suite_b_report['by_morph']}")
    print(f"  LOOCV Fit All: {suite_b_report['loocv_linear_fit_all']}")
    print(f"  LOOCV Fit <=2500aa: {suite_b_report['loocv_linear_fit_le2500aa']}")
    print(f"  LOOCV Morph-Stratified <=2500aa: {suite_b_report['loocv_morph_stratified_le2500aa']}")


if __name__ == "__main__":
    main()
