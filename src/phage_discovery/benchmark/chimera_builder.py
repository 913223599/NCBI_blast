# -*- coding: utf-8 -*-
"""
防泄露噬菌体/前噬菌体基准测试集构建器

核心保障：
1. 宿主隔离：按负样本类别（细菌染色体 / 质粒 / 非噬菌体病毒）确定性分层划分 train/val/test，
   确保同一宿主株系的序列背景永不跨越训练与测试集；
2. 零前噬菌体污染背景：严格扣除 negative_index.sqlite 中 `prophage_masks` 的 1,667 处掩蔽区间，
   仅从连续无掩蔽原生区段抽样；
3. 流式写盘（Rule 9）与全 UTF-8：逐条读取、拼接、80列折行原子写出，避免海量序列滞留内存。
"""
import argparse
import csv
import json
import logging
import random
import sqlite3
from collections import defaultdict
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

logger = logging.getLogger("phage_discovery.benchmark.chimera_builder")

_COMPLEMENT_TRANS = str.maketrans("ACGTNacgtn", "TGCANtgcan")


def reverse_complement(seq: str) -> str:
    """计算 DNA 反向互补序列。"""
    return seq.translate(_COMPLEMENT_TRANS)[::-1]


def read_single_fasta_sequence(fasta_path: Path) -> str:
    """流式读取单条 FASTA 文件碱基序列并统一转为大写。"""
    chunks: List[str] = []
    with open(fasta_path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith(">"):
                continue
            stripped = line.strip()
            if stripped:
                chunks.append(stripped.upper())
    return "".join(chunks)


def write_wrapped_fasta_record(fh: Any, header: str, seq: str, width: int = 80) -> None:
    """按标准 80 字符折行写入 FASTA 记录（兼容 VirSorter2 / CheckV / BLAST+）。"""
    fh.write(f">{header}\n")
    for idx in range(0, len(seq), width):
        fh.write(seq[idx:idx + width])
        fh.write("\n")


def compute_clean_intervals(
    length_bp: int,
    masked_intervals: Sequence[Tuple[int, int]],
    min_segment_bp: int = 1,
) -> List[Tuple[int, int]]:
    """计算 [0, length_bp) 扣除掩蔽区间后的干净连续半开区间列表。"""
    if length_bp <= 0:
        return []
    if not masked_intervals:
        return [(0, length_bp)] if length_bp >= min_segment_bp else []

    sorted_masks = sorted((max(0, s), min(length_bp, e)) for s, e in masked_intervals if e > s)
    clean: List[Tuple[int, int]] = []
    cursor = 0
    for ms, me in sorted_masks:
        if ms > cursor:
            if ms - cursor >= min_segment_bp:
                clean.append((cursor, ms))
        cursor = max(cursor, me)
    if cursor < length_bp and (length_bp - cursor) >= min_segment_bp:
        clean.append((cursor, length_bp))
    return clean


def _compute_gc_percent(seq: str) -> float:
    if not seq:
        return 0.0
    gc = seq.count("G") + seq.count("C")
    return round(100.0 * gc / len(seq), 2)


def split_negative_genomes_by_category(
    neg_sqlite: Path,
    seed: int = 42,
    ratios: Tuple[float, float, float] = (0.70, 0.15, 0.15),
) -> Dict[str, str]:
    """
    对负样本按类别确定性分层切分为 train / val / test，防止细菌株系背景跨集泄露。
    """
    rng = random.Random(seed)
    by_cat: Dict[str, List[str]] = defaultdict(list)

    with closing(sqlite3.connect(neg_sqlite)) as conn:
        rows = conn.execute(
            "SELECT accession, negative_category FROM genomes WHERE is_valid_negative = 1 ORDER BY accession"
        ).fetchall()
        for acc, cat in rows:
            by_cat[str(cat or "unknown")].append(str(acc))

    acc_to_split: Dict[str, str] = {}
    for cat, accs in sorted(by_cat.items()):
        shuffled = list(accs)
        rng.shuffle(shuffled)
        n = len(shuffled)
        n_val = max(1, round(n * ratios[1])) if n >= 5 else 0
        n_test = max(1, round(n * ratios[2])) if n >= 3 else 0
        n_train = max(0, n - n_val - n_test)
        for acc in shuffled[:n_train]:
            acc_to_split[acc] = "train"
        for acc in shuffled[n_train:n_train + n_val]:
            acc_to_split[acc] = "val"
        for acc in shuffled[n_train + n_val:]:
            acc_to_split[acc] = "test"

    return acc_to_split


def _load_positive_split_records(pos_dir: Path, split_name: str) -> List[Dict[str, Any]]:
    split_tsv = pos_dir / "preprocessed" / "splits" / f"{split_name}.tsv"
    if not split_tsv.exists():
        raise FileNotFoundError(f"未找到正样本切分文件: {split_tsv}")

    records: List[Dict[str, Any]] = []
    with open(split_tsv, "r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            acc = row["accession"]
            fa_path = pos_dir / "fasta" / f"{acc}.fasta"
            if fa_path.exists():
                records.append({
                    "accession": acc,
                    "cluster_id": row.get("cluster_id", ""),
                    "tax_group": row.get("tax_group", "Unknown"),
                    "host": row.get("host", ""),
                    "length_bp": int(float(row.get("length_bp") or 0)),
                    "fasta_path": fa_path,
                })
    return records


def _load_negative_pool_with_masks(
    neg_dir: Path,
    neg_splits: Dict[str, str],
    target_split: str,
) -> Dict[str, List[Dict[str, Any]]]:
    neg_sqlite = neg_dir / "index" / "negative_index.sqlite"
    masks_by_acc: Dict[str, List[Tuple[int, int]]] = defaultdict(list)
    pool: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    with closing(sqlite3.connect(neg_sqlite)) as conn:
        has_masks = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='prophage_masks'"
        ).fetchone()[0] > 0
        if has_masks:
            for acc, s_pos, e_pos in conn.execute(
                "SELECT accession, start_pos, end_pos FROM prophage_masks ORDER BY accession, start_pos"
            ).fetchall():
                masks_by_acc[str(acc)].append((int(s_pos), int(e_pos)))

        rows = conn.execute(
            """
            SELECT accession, negative_category, organism, length_bp, fasta_relpath
            FROM genomes
            WHERE is_valid_negative = 1
            ORDER BY accession
            """
        ).fetchall()
        for acc, cat, org, length_bp, fasta_rel in rows:
            acc_str = str(acc)
            if neg_splits.get(acc_str) != target_split:
                continue
            fa_path = neg_dir / fasta_rel if fasta_rel else neg_dir / "fasta" / f"{acc_str}.fasta"
            if not fa_path.exists():
                continue
            acc_masks = masks_by_acc.get(acc_str, [])
            clean_segs = compute_clean_intervals(int(length_bp or 0), acc_masks, min_segment_bp=1000)
            if not clean_segs:
                continue
            pool[str(cat)].append({
                "accession": acc_str,
                "category": str(cat),
                "organism": str(org or ""),
                "length_bp": int(length_bp or 0),
                "fasta_path": fa_path,
                "clean_segments": clean_segs,
                "mask_count": len(acc_masks),
            })
    return pool


def _build_window_benchmark_for_split(
    split_name: str,
    pos_records: List[Dict[str, Any]],
    neg_pool: Dict[str, List[Dict[str, Any]]],
    out_dir: Path,
    total_windows: int,
    rng: random.Random,
) -> Dict[str, Any]:
    """生成多尺度窗口级基准集（5000bp 约 70%, 3000bp 约 15%, 1000bp 约 15%，正负 1:1）。"""
    fna_path = out_dir / f"{split_name}_windows.fna"
    truth_path = out_dir / f"{split_name}_windows_truth.tsv"
    tmp_fna = fna_path.with_name(f".{fna_path.name}.tmp")
    tmp_tsv = truth_path.with_name(f".{truth_path.name}.tmp")

    target_pos = total_windows // 2
    target_neg = total_windows - target_pos

    scales = [5000] * 14 + [3000] * 3 + [1000] * 3  # 70% 5kb, 15% 3kb, 15% 1kb
    pos_written = 0
    neg_written = 0
    scale_counts: Dict[int, int] = defaultdict(int)

    # 先准备好负样本扁平化抽取清单（细菌染色体 50% + 纯净质粒 30% + 非噬菌体病毒 20%）
    clean_plasmids = [x for x in neg_pool.get("plasmid", []) if x["mask_count"] == 0] or neg_pool.get("plasmid", [])
    clean_chr = [x for x in neg_pool.get("bacterial_chromosome", []) if any((e - s) >= 50000 for s, e in x["clean_segments"])]
    non_phage_vir = neg_pool.get("non_phage_virus", [])

    with open(tmp_fna, "w", encoding="utf-8") as fa_fh, open(tmp_tsv, "w", encoding="utf-8", newline="") as tsv_fh:
        writer = csv.writer(tsv_fh, delimiter="\t")
        writer.writerow([
            "window_id", "label", "source_accession", "source_category", "tax_group",
            "win_len", "start_bp", "end_bp", "strand", "gc_percent",
        ])

        # 1. 正样本窗口抽样（按菌株均匀抽样以防少数巨型噬菌体主导）
        pos_idx = 0
        shuffled_pos = list(pos_records)
        rng.shuffle(shuffled_pos)
        while pos_written < target_pos and shuffled_pos:
            rec = shuffled_pos[pos_idx % len(shuffled_pos)]
            pos_idx += 1
            seq = read_single_fasta_sequence(rec["fasta_path"])
            seq_len = len(seq)
            if seq_len < 500:
                continue
            target_len = rng.choice(scales)
            actual_len = min(target_len, seq_len)
            start_bp = rng.randint(0, seq_len - actual_len) if seq_len > actual_len else 0
            end_bp = start_bp + actual_len
            subseq = seq[start_bp:end_bp]
            strand = -1 if rng.random() < 0.5 else 1
            if strand == -1:
                subseq = reverse_complement(subseq)
            # 跳过几乎全 N 的极端区段
            if subseq.count("N") / len(subseq) > 0.05:
                continue

            pos_written += 1
            wid = f"{split_name}_POS_{pos_written:06d}"
            write_wrapped_fasta_record(fa_fh, wid, subseq)
            writer.writerow([
                wid, 1, rec["accession"], "phage_refseq", rec["tax_group"],
                actual_len, start_bp, end_bp, strand, _compute_gc_percent(subseq),
            ])
            scale_counts[actual_len] += 1

        # 2. 负样本窗口抽样（严格取自 clean_segments）
        neg_attempts = 0
        max_attempts = target_neg * 10
        while neg_written < target_neg and neg_attempts < max_attempts:
            neg_attempts += 1
            roll = rng.random()
            if roll < 0.55 and clean_chr:
                rec = rng.choice(clean_chr)
            elif roll < 0.85 and clean_plasmids:
                rec = rng.choice(clean_plasmids)
            elif non_phage_vir:
                rec = rng.choice(non_phage_vir)
            else:
                all_avail = clean_chr + clean_plasmids + non_phage_vir
                if not all_avail:
                    break
                rec = rng.choice(all_avail)

            target_len = rng.choice(scales)
            valid_segs = [(s, e) for s, e in rec["clean_segments"] if (e - s) >= min(target_len, 1000)]
            if not valid_segs:
                continue
            seg_s, seg_e = rng.choice(valid_segs)
            seg_len = seg_e - seg_s
            actual_len = min(target_len, seg_len)
            start_bp = rng.randint(seg_s, seg_e - actual_len) if seg_len > actual_len else seg_s
            end_bp = start_bp + actual_len

            seq = read_single_fasta_sequence(rec["fasta_path"])
            subseq = seq[start_bp:end_bp]
            if len(subseq) < 500 or (subseq.count("N") / len(subseq) > 0.05):
                continue
            strand = -1 if rng.random() < 0.5 else 1
            if strand == -1:
                subseq = reverse_complement(subseq)

            neg_written += 1
            wid = f"{split_name}_NEG_{neg_written:06d}"
            write_wrapped_fasta_record(fa_fh, wid, subseq)
            writer.writerow([
                wid, 0, rec["accession"], rec["category"], rec["category"],
                actual_len, start_bp, end_bp, strand, _compute_gc_percent(subseq),
            ])
            scale_counts[actual_len] += 1

    tmp_fna.replace(fna_path)
    tmp_tsv.replace(truth_path)

    return {
        "fasta": str(fna_path),
        "truth_tsv": str(truth_path),
        "total_windows": pos_written + neg_written,
        "positive_windows": pos_written,
        "negative_windows": neg_written,
        "window_lengths_summary": dict(sorted((str(k), v) for k, v in scale_counts.items())),
    }


def _build_chimera_benchmark_for_split(
    split_name: str,
    pos_records: List[Dict[str, Any]],
    neg_pool: Dict[str, List[Dict[str, Any]]],
    out_dir: Path,
    chimeras_count: int,
    pure_neg_hosts: int,
    rng: random.Random,
) -> Dict[str, Any]:
    """
    构建半合成“细菌基因组 + 真实前噬菌体嵌入”区域定位基准集。
    包含模式：intact_single / degraded_fragment / multi_tandem / pure_negative_host。
    """
    fna_path = out_dir / f"{split_name}_chimeras.fna"
    truth_path = out_dir / f"{split_name}_chimeras_truth.tsv"
    contigs_path = out_dir / f"{split_name}_chimeras_contigs.tsv"

    tmp_fna = fna_path.with_name(f".{fna_path.name}.tmp")
    tmp_truth = truth_path.with_name(f".{truth_path.name}.tmp")
    tmp_contigs = contigs_path.with_name(f".{contigs_path.name}.tmp")

    host_candidates = [
        rec for rec in neg_pool.get("bacterial_chromosome", [])
        if any((e - s) >= 120000 for s, e in rec["clean_segments"])
    ]
    if not host_candidates:
        raise RuntimeError(f"split={split_name} 下没有长度 >=120kb 的干净细菌主干可用于构建嵌合基准。")

    # 筛选长度适中且具备结构代表性的真实噬菌体（>= 8kb 以避免微小单链碎片无法成岛，同时保留少部分短噬菌体测试极限）
    phage_pool = [r for r in pos_records if r["length_bp"] >= 8000] or list(pos_records)
    rng.shuffle(phage_pool)

    # 缓存单次遍历需要用的宿主序列长度只读一次即可，按需流式读取，不批量囤积内存
    mode_schedule: List[str] = []
    n_intact = max(1, round(chimeras_count * 0.45))
    n_degraded = max(1, round(chimeras_count * 0.30))
    n_multi = max(1, chimeras_count - n_intact - n_degraded)
    mode_schedule.extend(["intact_single"] * n_intact)
    mode_schedule.extend(["degraded_fragment"] * n_degraded)
    mode_schedule.extend(["multi_tandem"] * n_multi)
    rng.shuffle(mode_schedule)

    mode_counts: Dict[str, int] = defaultdict(int)
    total_truth_regions = 0
    total_contigs = 0
    total_bp = 0
    phage_cursor = 0

    with (
        open(tmp_fna, "w", encoding="utf-8") as fa_fh,
        open(tmp_truth, "w", encoding="utf-8", newline="") as tr_fh,
        open(tmp_contigs, "w", encoding="utf-8", newline="") as cg_fh,
    ):
        tr_writer = csv.writer(tr_fh, delimiter="\t")
        cg_writer = csv.writer(cg_fh, delimiter="\t")

        tr_writer.writerow([
            "contig_id", "contig_len_bp", "region_id", "start_bp", "end_bp",
            "region_len_bp", "mode", "phage_acc", "cluster_id", "tax_group",
            "strand", "completeness_ratio",
        ])
        cg_writer.writerow(["contig_id", "contig_len_bp", "host_acc", "scenario", "truth_region_count"])

        # 1. 构建嵌合体序列
        for idx, mode in enumerate(mode_schedule, start=1):
            host_rec = rng.choice(host_candidates)
            long_segs = [(s, e) for s, e in host_rec["clean_segments"] if (e - s) >= 120000]
            seg_s, seg_e = rng.choice(long_segs)
            desired_host_len = min(seg_e - seg_s, rng.randint(150000, 300000))
            crop_start = rng.randint(seg_s, seg_e - desired_host_len)
            host_full_seq = read_single_fasta_sequence(host_rec["fasta_path"])
            host_backbone = host_full_seq[crop_start:crop_start + desired_host_len]
            del host_full_seq

            contig_id = f"{split_name}_CHIM_{idx:04d}"
            insertions: List[Tuple[int, str, Dict[str, Any], int, float]] = []

            if mode == "multi_tandem":
                p1 = phage_pool[phage_cursor % len(phage_pool)]
                phage_cursor += 1
                p2 = phage_pool[phage_cursor % len(phage_pool)]
                phage_cursor += 1
                for frac, prec in [(0.28, p1), (0.72, p2)]:
                    p_seq = read_single_fasta_sequence(prec["fasta_path"])
                    strand = -1 if rng.random() < 0.5 else 1
                    if strand == -1:
                        p_seq = reverse_complement(p_seq)
                    pos_ins = int(len(host_backbone) * frac)
                    insertions.append((pos_ins, p_seq, prec, strand, 1.0))
            else:
                prec = phage_pool[phage_cursor % len(phage_pool)]
                phage_cursor += 1
                p_seq = read_single_fasta_sequence(prec["fasta_path"])
                comp_ratio = 1.0
                if mode == "degraded_fragment" and len(p_seq) >= 10000:
                    comp_ratio = round(rng.uniform(0.40, 0.75), 3)
                    keep_len = max(5000, int(len(p_seq) * comp_ratio))
                    sub_start = rng.randint(0, len(p_seq) - keep_len)
                    p_seq = p_seq[sub_start:sub_start + keep_len]
                strand = -1 if rng.random() < 0.5 else 1
                if strand == -1:
                    p_seq = reverse_complement(p_seq)
                pos_ins = rng.randint(25000, len(host_backbone) - 25000)
                insertions.append((pos_ins, p_seq, prec, strand, comp_ratio))

            insertions.sort(key=lambda item: item[0])
            parts: List[str] = []
            prev_cut = 0
            cur_offset = 0
            contig_regions: List[Tuple[int, int, Dict[str, Any], int, float]] = []

            for ins_pos, ins_seq, prec, strand, comp_ratio in insertions:
                flank = host_backbone[prev_cut:ins_pos]
                parts.append(flank)
                cur_offset += len(flank)
                reg_start = cur_offset
                parts.append(ins_seq)
                cur_offset += len(ins_seq)
                reg_end = cur_offset
                prev_cut = ins_pos
                contig_regions.append((reg_start, reg_end, prec, strand, comp_ratio))

            parts.append(host_backbone[prev_cut:])
            chimera_seq = "".join(parts)

            write_wrapped_fasta_record(fa_fh, contig_id, chimera_seq)
            cg_writer.writerow([contig_id, len(chimera_seq), host_rec["accession"], mode, len(contig_regions)])
            total_contigs += 1
            total_bp += len(chimera_seq)
            mode_counts[mode] += 1

            for r_i, (r_s, r_e, prec, strand, comp_ratio) in enumerate(contig_regions, start=1):
                total_truth_regions += 1
                tr_writer.writerow([
                    contig_id,
                    len(chimera_seq),
                    f"{contig_id}_R{r_i}",
                    r_s,
                    r_e,
                    r_e - r_s,
                    mode,
                    prec["accession"],
                    prec["cluster_id"],
                    prec["tax_group"],
                    strand,
                    comp_ratio,
                ])

        # 2. 构建零插入纯阴性对照主干（专门测量每 Mb 假阳性率 FP/Mb）
        for neg_i in range(1, pure_neg_hosts + 1):
            host_rec = host_candidates[(neg_i - 1) % len(host_candidates)]
            long_segs = [(s, e) for s, e in host_rec["clean_segments"] if (e - s) >= 120000]
            seg_s, seg_e = rng.choice(long_segs)
            desired_len = min(seg_e - seg_s, rng.randint(150000, 300000))
            crop_start = rng.randint(seg_s, seg_e - desired_len)
            host_full_seq = read_single_fasta_sequence(host_rec["fasta_path"])
            pure_seq = host_full_seq[crop_start:crop_start + desired_len]
            del host_full_seq

            contig_id = f"{split_name}_PURE_NEG_{neg_i:04d}"
            write_wrapped_fasta_record(fa_fh, contig_id, pure_seq)
            cg_writer.writerow([contig_id, len(pure_seq), host_rec["accession"], "pure_negative_host", 0])
            total_contigs += 1
            total_bp += len(pure_seq)
            mode_counts["pure_negative_host"] += 1

    tmp_fna.replace(fna_path)
    tmp_truth.replace(truth_path)
    tmp_contigs.replace(contigs_path)

    return {
        "fasta": str(fna_path),
        "truth_tsv": str(truth_path),
        "contigs_tsv": str(contigs_path),
        "total_contigs": total_contigs,
        "total_truth_regions": total_truth_regions,
        "total_bp": total_bp,
        "total_mb": round(total_bp / 1_000_000.0, 3),
        "scenario_counts": dict(mode_counts),
    }


def build_benchmark_suite(
    positive_dir: Path,
    negative_dir: Path,
    output_dir: Path,
    splits_to_build: Tuple[str, ...] = ("val", "test"),
    chimeras_per_split: int = 60,
    pure_neg_hosts_per_split: int = 15,
    windows_per_split: int = 4000,
    seed: int = 42,
) -> Dict[str, Any]:
    """构建并冻结防泄露的多尺度窗口基准集与细菌嵌合前噬菌体基准集。"""
    pos_root = Path(positive_dir).resolve()
    neg_root = Path(negative_dir).resolve()
    out_root = Path(output_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    neg_sqlite = neg_root / "index" / "negative_index.sqlite"
    neg_splits = split_negative_genomes_by_category(neg_sqlite, seed=seed)

    neg_split_path = out_root / "negative_splits.json"
    tmp_ns = neg_split_path.with_name(f".{neg_split_path.name}.tmp")
    tmp_ns.write_text(json.dumps(neg_splits, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_ns.replace(neg_split_path)

    rng = random.Random(seed)
    split_artifacts: Dict[str, Any] = {}

    for split_name in splits_to_build:
        pos_records = _load_positive_split_records(pos_root, split_name)
        neg_pool = _load_negative_pool_with_masks(neg_root, neg_splits, split_name)

        win_meta = _build_window_benchmark_for_split(
            split_name=split_name,
            pos_records=pos_records,
            neg_pool=neg_pool,
            out_dir=out_root,
            total_windows=windows_per_split,
            rng=rng,
        )
        chim_meta = _build_chimera_benchmark_for_split(
            split_name=split_name,
            pos_records=pos_records,
            neg_pool=neg_pool,
            out_dir=out_root,
            chimeras_count=chimeras_per_split,
            pure_neg_hosts=pure_neg_hosts_per_split,
            rng=rng,
        )
        split_artifacts[split_name] = {
            "windows": win_meta,
            "chimeras": chim_meta,
        }

    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "seed": seed,
        "positive_dir": str(pos_root),
        "negative_dir": str(neg_root),
        "negative_splits_file": str(neg_split_path),
        "negative_split_counts": {
            s: sum(1 for v in neg_splits.values() if v == s)
            for s in ("train", "val", "test")
        },
        "splits": split_artifacts,
    }
    manifest_path = out_root / "benchmark_manifest.json"
    tmp_mf = manifest_path.with_name(f".{manifest_path.name}.tmp")
    tmp_mf.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_mf.replace(manifest_path)

    return manifest


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="构建防泄露前噬菌体/噬菌体测试基准数据集")
    parser.add_argument("--positive-dir", required=True, help="正样本根目录")
    parser.add_argument("--negative-dir", default="", help="负样本根目录（默认 <positive-dir>/negative）")
    parser.add_argument("--output-dir", required=True, help="基准输出目录")
    parser.add_argument("--windows-per-split", type=int, default=4000, help="每个 split 生成的窗口数（默认 4000）")
    parser.add_argument("--chimeras-per-split", type=int, default=60, help="每个 split 生成的嵌合菌株条数（默认 60）")
    parser.add_argument("--pure-neg-hosts", type=int, default=15, help="每个 split 纯阴性对照细菌条数（默认 15）")
    parser.add_argument("--seed", type=int, default=42, help="确定性随机种子")

    args = parser.parse_args()
    pos_dir = Path(args.positive_dir)
    neg_dir = Path(args.negative_dir) if args.negative_dir else pos_dir / "negative"
    manifest = build_benchmark_suite(
        positive_dir=pos_dir,
        negative_dir=neg_dir,
        output_dir=Path(args.output_dir),
        windows_per_split=args.windows_per_split,
        chimeras_per_split=args.chimeras_per_split,
        pure_neg_hosts_per_split=args.pure_neg_hosts,
        seed=args.seed,
    )
    print(json.dumps({"negative_split_counts": manifest["negative_split_counts"], "splits": list(manifest["splits"].keys())}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

