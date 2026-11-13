# -*- coding: utf-8 -*-
"""
WSL CheckV 离线真实前噬菌体矿脉挖掘器（严格限定于 train split 负样本染色体）

核心机制：
1. 严格读取 negative_splits.json，仅对 split == "train" 的细菌染色体开放扫描，严防 val/test 泄露；
2. 基于 negative_index.sqlite 的 `prophage_masks` 定位疑似区间，扩展 ±25 kb 宿主侧翼提取候选 contig；
3. 经 WSL CheckV (HMM + 基因界标分析) 精修前噬菌体真实断点坐标，分离出：
   - 真实宿主体内嵌合前噬菌体样本（含宿主侧翼 + 精确 viral 坐标，用于训练真实前噬菌体及边界模型）；
   - 易混移动元件硬负样本（viral_genes <= 1 且 host_genes >= 10，用于压制细菌误报）。
"""
import argparse
import csv
import json
import logging
import sqlite3
from collections import defaultdict
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..benchmark.chimera_builder import read_single_fasta_sequence, write_wrapped_fasta_record
from ...utils.phage_dataset.cleaner import merge_intervals
from .checkv_teacher import run_checkv_end_to_end

logger = logging.getLogger("phage_discovery.teachers.prophage_miner")


def extract_train_prophage_candidates(
    neg_dir: Path,
    neg_splits_path: Path,
    out_dir: Path,
    flank_bp: int = 25000,
    merge_gap_bp: int = 20000,
    target_split: str = "train",
) -> Dict[str, Any]:
    """抽取 train split 细菌染色体上的 prophage_masks 扩展候选片段供 CheckV 复核。"""
    neg_root = Path(neg_dir).resolve()
    out_root = Path(out_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    neg_splits = json.loads(Path(neg_splits_path).read_text(encoding="utf-8"))
    allowed_accs = {acc for acc, sp in neg_splits.items() if sp == target_split}

    neg_sqlite = neg_root / "index" / "negative_index.sqlite"
    masks_by_acc: Dict[str, List[Tuple[int, int]]] = defaultdict(list)
    meta_by_acc: Dict[str, Tuple[int, str]] = {}

    with closing(sqlite3.connect(neg_sqlite)) as conn:
        for acc, cat, length_bp, fasta_rel in conn.execute(
            "SELECT accession, negative_category, length_bp, fasta_relpath FROM genomes WHERE is_valid_negative = 1"
        ).fetchall():
            if str(acc) in allowed_accs and str(cat) == "bacterial_chromosome":
                fa = neg_root / fasta_rel if fasta_rel else neg_root / "fasta" / f"{acc}.fasta"
                if fa.exists():
                    meta_by_acc[str(acc)] = (int(length_bp or 0), str(fa))

        for acc, s_pos, e_pos in conn.execute(
            "SELECT accession, start_pos, end_pos FROM prophage_masks ORDER BY accession, start_pos"
        ).fetchall():
            if str(acc) in meta_by_acc:
                masks_by_acc[str(acc)].append((int(s_pos), int(e_pos)))

    cand_fna = out_root / "train_candidates.fna"
    tmp_fna = cand_fna.with_name(f".{cand_fna.name}.tmp")
    cand_map: Dict[str, Dict[str, Any]] = {}
    cand_idx = 0

    with open(tmp_fna, "w", encoding="utf-8") as fh:
        for acc in sorted(masks_by_acc.keys()):
            length_bp, fa_str = meta_by_acc[acc]
            # 先按间隔阈值把同一岛的多个碎片掩蔽合并为一个大上下文块，再向两侧扩 25kb
            padded_raw = [(max(0, s - merge_gap_bp // 2), min(length_bp, e + merge_gap_bp // 2)) for s, e in masks_by_acc[acc]]
            merged_clusters = merge_intervals(padded_raw, max_length=length_bp, flank_bp=0)
            seq = read_single_fasta_sequence(Path(fa_str))
            for cs, ce in merged_clusters:
                ctx_s = max(0, cs - flank_bp + merge_gap_bp // 2)
                ctx_e = min(len(seq), ce + flank_bp - merge_gap_bp // 2)
                if ctx_e - ctx_s < 5000:
                    continue
                cand_idx += 1
                cid = f"MINED_CAND_{cand_idx:04d}"
                sub = seq[ctx_s:ctx_e]
                write_wrapped_fasta_record(fh, cid, sub)
                cand_map[cid] = {
                    "source_accession": acc,
                    "source_start_bp": ctx_s,
                    "source_end_bp": ctx_e,
                    "length_bp": len(sub),
                }
            del seq

    tmp_fna.replace(cand_fna)
    map_path = out_root / "candidate_map.json"
    tmp_map = map_path.with_name(f".{map_path.name}.tmp")
    tmp_map.write_text(json.dumps(cand_map, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_map.replace(map_path)

    return {
        "target_split": target_split,
        "chromosomes_scanned": len(masks_by_acc),
        "candidates_extracted": cand_idx,
        "candidates_fasta": str(cand_fna),
        "candidate_map": str(map_path),
    }


def curate_checkv_mined_dataset(
    candidates_fasta: Path,
    checkv_dir: Path,
    out_dir: Path,
    min_viral_genes: int = 3,
    min_region_bp: int = 5000,
) -> Dict[str, Any]:
    """
    根据 CheckV quality_summary.tsv 与 contamination.tsv 分拣真实自然前噬菌体嵌合序列与硬负样本。
    产出格式直接兼容 benchmark / feature_dataset（mined_prophages.fna / truth.tsv / contigs.tsv）。
    """
    out_root = Path(out_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    cv_root = Path(checkv_dir).resolve()

    quality_by_id: Dict[str, Dict[str, str]] = {}
    q_tsv = cv_root / "quality_summary.tsv"
    if q_tsv.exists():
        with open(q_tsv, "r", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                quality_by_id[row["contig_id"]] = row

    verified_regions: Dict[str, List[Tuple[int, int, str, int, float]]] = defaultdict(list)
    hard_negative_ids: set[str] = set()

    contam_tsv = cv_root / "contamination.tsv"
    with open(contam_tsv, "r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            cid = row["contig_id"]
            length = int(float(row.get("contig_length") or 0))
            v_genes = int(float(row.get("viral_genes") or 0))
            h_genes = int(float(row.get("host_genes") or 0))
            q_info = quality_by_id.get(cid, {})
            comp = float(q_info.get("completeness") or 0.0) if (q_info.get("completeness") or "NA") != "NA" else 0.0
            q_tier = q_info.get("checkv_quality", "Unknown")

            if (row.get("provirus") or "").strip().lower() == "yes":
                types = (row.get("region_types") or "").split(",")
                coords = (row.get("region_coords_bp") or "").split(",")
                rv_list = (row.get("region_viral_genes") or "").split(",")
                for idx, (rtype, coord) in enumerate(zip(types, coords)):
                    if rtype.strip().lower() != "viral" or "-" not in coord:
                        continue
                    rv = int(float(rv_list[idx])) if idx < len(rv_list) and rv_list[idx] not in ("", "NA") else v_genes
                    s_txt, e_txt = coord.split("-", 1)
                    s_bp = int(s_txt) - 1
                    e_bp = int(e_txt)
                    if (e_bp - s_bp) >= min_region_bp and rv >= min_viral_genes:
                        verified_regions[cid].append((s_bp, e_bp, q_tier, rv, round(comp / 100.0, 3)))
            elif v_genes >= max(min_viral_genes + 2, 5) and h_genes <= 2 and length >= min_region_bp:
                verified_regions[cid].append((0, length, q_tier, v_genes, round(comp / 100.0, 3)))
            elif v_genes <= 1 and h_genes >= 10:
                hard_negative_ids.add(cid)

    # 流式写出筛选后的自然界前噬菌体嵌合体 + 纯硬负样本对照
    keep_ids = set(verified_regions.keys()) | hard_negative_ids
    out_fna = out_root / "mined_chimeras.fna"
    out_truth = out_root / "mined_chimeras_truth.tsv"
    out_contigs = out_root / "mined_chimeras_contigs.tsv"

    tmp_fna = out_fna.with_name(f".{out_fna.name}.tmp")
    tmp_truth = out_truth.with_name(f".{out_truth.name}.tmp")
    tmp_contigs = out_contigs.with_name(f".{out_contigs.name}.tmp")

    contig_lengths: Dict[str, int] = {}
    cur_id: Optional[str] = None
    cur_len = 0
    keep_cur = False

    with open(candidates_fasta, "r", encoding="utf-8", errors="replace") as fin, open(tmp_fna, "w", encoding="utf-8") as fout:
        for line in fin:
            if line.startswith(">"):
                if cur_id is not None and keep_cur:
                    contig_lengths[cur_id] = cur_len
                cur_id = line[1:].strip().split()[0]
                cur_len = 0
                keep_cur = cur_id in keep_ids
                if keep_cur:
                    fout.write(f">{cur_id}\n")
            elif keep_cur:
                cur_len += len(line.strip())
                fout.write(line)
        if cur_id is not None and keep_cur:
            contig_lengths[cur_id] = cur_len

    total_regions = 0
    with open(tmp_truth, "w", encoding="utf-8", newline="") as tr_fh, open(tmp_contigs, "w", encoding="utf-8", newline="") as cg_fh:
        tr_w = csv.writer(tr_fh, delimiter="\t")
        cg_w = csv.writer(cg_fh, delimiter="\t")
        tr_w.writerow([
            "contig_id", "contig_len_bp", "region_id", "start_bp", "end_bp",
            "region_len_bp", "mode", "checkv_quality", "viral_genes", "completeness_ratio",
        ])
        cg_w.writerow(["contig_id", "contig_len_bp", "host_acc", "scenario", "truth_region_count"])

        for cid in sorted(contig_lengths.keys()):
            clen = contig_lengths[cid]
            regs = verified_regions.get(cid, [])
            if regs:
                cg_w.writerow([cid, clen, "natural_train_host", "natural_prophage", len(regs)])
                for ri, (s_bp, e_bp, qt, vg, cr) in enumerate(regs, start=1):
                    total_regions += 1
                    tr_w.writerow([cid, clen, f"{cid}_R{ri}", s_bp, e_bp, e_bp - s_bp, "natural_prophage", qt, vg, cr])
            else:
                cg_w.writerow([cid, clen, "natural_train_host", "hard_negative_host", 0])

    tmp_fna.replace(out_fna)
    tmp_truth.replace(out_truth)
    tmp_contigs.replace(out_contigs)

    summary = {
        "curated_at": datetime.now().isoformat(timespec="seconds"),
        "verified_prophage_contigs": len(verified_regions),
        "verified_prophage_regions": total_regions,
        "hard_negative_contigs": len(hard_negative_ids),
        "mined_fasta": str(out_fna),
        "mined_truth_tsv": str(out_truth),
        "mined_contigs_tsv": str(out_contigs),
    }
    sum_path = out_root / "mined_manifest.json"
    tmp_sum = sum_path.with_name(f".{sum_path.name}.tmp")
    tmp_sum.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_sum.replace(sum_path)
    return summary


def run_prophage_mining_pipeline(
    neg_dir: Path,
    neg_splits_path: Path,
    out_dir: Path,
    db_dir: Optional[str] = None,
    threads: Optional[int] = None,
) -> Dict[str, Any]:
    """端到端运行 train split 候选抽提 -> WSL CheckV 复核 -> 自然前噬菌体分拣。"""
    out_root = Path(out_dir).resolve()
    cand_info = extract_train_prophage_candidates(neg_dir, neg_splits_path, out_root)
    cv_out = out_root / "checkv_raw"
    cv_run = run_checkv_end_to_end(
        Path(cand_info["candidates_fasta"]),
        cv_out,
        db_dir=db_dir,
        threads=threads,
    )
    if cv_run["returncode"] != 0:
        raise RuntimeError(f"CheckV 挖掘运行失败，详见日志: {cv_run['log']}")
    curated = curate_checkv_mined_dataset(Path(cand_info["candidates_fasta"]), cv_out, out_root)
    return {"extraction": cand_info, "checkv_run": cv_run, "curated": curated}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="从 train split 细菌染色体用 CheckV 挖掘真实自然前噬菌体样本")
    parser.add_argument("--negative-dir", required=True)
    parser.add_argument("--negative-splits", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--db", default="/opt/checkv_db/checkv-db-v1.5")
    parser.add_argument("--threads", type=int, default=0)
    args = parser.parse_args()
    res = run_prophage_mining_pipeline(
        Path(args.negative_dir), Path(args.negative_splits), Path(args.out_dir),
        db_dir=args.db, threads=args.threads if args.threads > 0 else None,
    )
    print(json.dumps(res["curated"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
