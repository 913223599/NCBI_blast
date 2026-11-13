# -*- coding: utf-8 -*-
"""
前噬菌体扫描序列解析、ORF 提取与多格式结果落盘导出器

统一处理 FASTA / FASTA.GZ / GenBank 输入加载、Contig 预检，
并将扫描命中的前噬菌体区域及其 200bp 边界分布序列化落盘（FASTA/TSV/GFF3/GBK/JSON），
支持生成带宿主侧翼微区域的 GenBank 以直连 GenomeViewer 图谱浏览器。
"""
import gzip
import io
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqFeature import FeatureLocation, SeqFeature
from Bio.SeqRecord import SeqRecord
import pyrodigal

from ...phage_discovery.inference.protein_gate import RegionGateResult
from ...phage_discovery.inference.scanner import PredictedRegion, ScanResult
from .model_registry import PROJECT_ROOT, _normalize_storage_path, _resolve_user_path

_GBK_EXTENSIONS = {".gbk", ".gb", ".genbank", ".gbff", ".gbk.gz", ".gb.gz", ".gbff.gz"}


def _is_genbank_suffix(name: str) -> bool:
    lower = name.lower()
    return any(lower.endswith(ext) for ext in _GBK_EXTENSIONS)


def _open_text_source(path: Path):
    if str(path).lower().endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="ignore")
    return open(path, "r", encoding="utf-8", errors="ignore")


def _parse_fasta_text(text: str) -> Dict[str, str]:
    sequences: Dict[str, str] = {}
    current_id: Optional[str] = None
    chunks: List[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if current_id is not None:
                seq_str = "".join(chunks).upper()
                if seq_str:
                    sequences[current_id] = seq_str
            header = line[1:].strip()
            cid = header.split()[0] if header else f"contig_{len(sequences) + 1}"
            if cid in sequences:
                cid = f"{cid}_{len(sequences) + 1}"
            current_id = cid
            chunks = []
        else:
            chunks.append(line)
    if current_id is not None:
        seq_str = "".join(chunks).upper()
        if seq_str:
            sequences[current_id] = seq_str
    return sequences


def _extract_gbk_features_from_record(rec: Any) -> List[Dict[str, Any]]:
    """从 BioPython SeqRecord 中提取 GenBank 原始基因与结构特征作为叠图底图。"""
    items: List[Dict[str, Any]] = []
    skipped_types = {"source", "assembly_gap", "gap"}
    idx = 0
    for feat in getattr(rec, "features", []):
        ftype = str(getattr(feat, "type", "") or "")
        if not ftype or ftype.lower() in skipped_types:
            continue
        loc = getattr(feat, "location", None)
        if loc is None:
            continue
        sb = int(loc.start)
        eb = int(loc.end)
        if eb <= sb:
            continue
        strand = 1 if (loc.strand is None or loc.strand >= 0) else -1
        q = getattr(feat, "qualifiers", {}) or {}
        locus_tag = str((q.get("locus_tag") or q.get("ID") or [""])[0] or "")
        gene_name = str((q.get("gene") or q.get("Name") or [""])[0] or "")
        product = str((q.get("product") or q.get("description") or q.get("label") or [""])[0] or "")
        note = str((q.get("note") or q.get("inference") or [""])[0] or "")
        idx += 1
        items.append({
            "index": idx,
            "type": ftype,
            "start_bp": sb,
            "end_bp": eb,
            "strand": strand,
            "locus_tag": locus_tag,
            "gene": gene_name,
            "product": product or ftype,
            "note": note,
            "source": "genbank",
        })
    return items


def _parse_genbank_text_with_feats(
    text: str,
) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, List[Dict[str, Any]]]]:
    sequences: Dict[str, str] = {}
    descriptions: Dict[str, str] = {}
    features_map: Dict[str, List[Dict[str, Any]]] = {}
    handle = io.StringIO(text)
    for rec in SeqIO.parse(handle, "genbank"):
        cid = str(rec.id or rec.name or f"contig_{len(sequences) + 1}")
        if cid in sequences:
            cid = f"{cid}_{len(sequences) + 1}"
        seq_str = str(rec.seq).upper()
        if seq_str:
            sequences[cid] = seq_str
            descriptions[cid] = str(rec.description or "")
            features_map[cid] = _extract_gbk_features_from_record(rec)
    return sequences, descriptions, features_map


def load_sequences_with_annotations(
    fasta_path: Optional[str] = None,
    fasta_content: Optional[str] = None,
    project_root: Path = PROJECT_ROOT,
) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, List[Dict[str, Any]]], str]:
    """从文件路径或内联文本加载序列、描述、原有注释特征及输入格式 ('fasta'|'genbank')。"""
    if fasta_content and fasta_content.strip():
        text = fasta_content.strip()
        if text.startswith("LOCUS"):
            seqs, descs, feats = _parse_genbank_text_with_feats(text)
            src_fmt = "genbank"
        else:
            seqs = _parse_fasta_text(text)
            descs = {cid: "" for cid in seqs}
            feats = {}
            src_fmt = "fasta"
        if not seqs:
            raise ValueError("未能从提交的文本中解析出有效核酸序列 (需要 FASTA 或 GenBank 格式)")
        return seqs, descs, feats, src_fmt

    resolved = _resolve_user_path(fasta_path, project_root)
    if resolved is None or not resolved.exists():
        raise FileNotFoundError(f"指定的基因组文件不存在: {fasta_path}")

    sequences: Dict[str, str] = {}
    descriptions: Dict[str, str] = {}
    features_map: Dict[str, List[Dict[str, Any]]] = {}
    is_gbk = _is_genbank_suffix(resolved.name)

    with _open_text_source(resolved) as fh:
        if is_gbk:
            for rec in SeqIO.parse(fh, "genbank"):
                cid = str(rec.id or rec.name or f"contig_{len(sequences) + 1}")
                if cid in sequences:
                    cid = f"{cid}_{len(sequences) + 1}"
                seq_str = str(rec.seq).upper()
                if seq_str:
                    sequences[cid] = seq_str
                    descriptions[cid] = str(rec.description or "")
                    features_map[cid] = _extract_gbk_features_from_record(rec)
        else:
            for rec in SeqIO.parse(fh, "fasta"):
                cid = str(rec.id or rec.name or f"contig_{len(sequences) + 1}")
                if cid in sequences:
                    cid = f"{cid}_{len(sequences) + 1}"
                seq_str = str(rec.seq).upper()
                if seq_str:
                    sequences[cid] = seq_str
                    descriptions[cid] = str(rec.description or "")

    if not sequences:
        raise ValueError(f"文件 {resolved.name} 中未检测到有效核酸序列")
    return sequences, descriptions, features_map, ("genbank" if is_gbk else "fasta")


def _parse_genbank_text(text: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    seqs, descs, _ = _parse_genbank_text_with_feats(text)
    return seqs, descs


def load_sequences_with_meta(
    fasta_path: Optional[str] = None,
    fasta_content: Optional[str] = None,
    project_root: Path = PROJECT_ROOT,
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """从文件路径或内联文本安全加载核酸序列及其描述信息。"""
    if fasta_content and fasta_content.strip():
        text = fasta_content.strip()
        if text.startswith("LOCUS"):
            seqs, descs = _parse_genbank_text(text)
        else:
            seqs = _parse_fasta_text(text)
            descs = {cid: "" for cid in seqs}
        if not seqs:
            raise ValueError("未能从提交的文本中解析出有效核酸序列 (需要 FASTA 或 GenBank 格式)")
        return seqs, descs

    resolved = _resolve_user_path(fasta_path, project_root)
    if resolved is None or not resolved.exists():
        raise FileNotFoundError(f"指定的基因组文件不存在: {fasta_path}")

    sequences: Dict[str, str] = {}
    descriptions: Dict[str, str] = {}
    is_gbk = _is_genbank_suffix(resolved.name)

    with _open_text_source(resolved) as fh:
        if is_gbk:
            for rec in SeqIO.parse(fh, "genbank"):
                cid = str(rec.id or rec.name or f"contig_{len(sequences) + 1}")
                if cid in sequences:
                    cid = f"{cid}_{len(sequences) + 1}"
                seq_str = str(rec.seq).upper()
                if seq_str:
                    sequences[cid] = seq_str
                    descriptions[cid] = str(rec.description or "")
        else:
            for rec in SeqIO.parse(fh, "fasta"):
                cid = str(rec.id or f"contig_{len(sequences) + 1}")
                if cid in sequences:
                    cid = f"{cid}_{len(sequences) + 1}"
                seq_str = str(rec.seq).upper()
                if seq_str:
                    sequences[cid] = seq_str
                    descriptions[cid] = str(rec.description or "")

    if not sequences:
        raise ValueError(f"文件 {resolved.name} 中未检测到有效核酸序列")
    return sequences, descriptions


def compute_gc_percent(seq: str) -> float:
    if not seq:
        return 0.0
    upper = seq.upper()
    gc = upper.count("G") + upper.count("C")
    valid = upper.count("A") + upper.count("T") + gc
    denom = valid if valid > 0 else len(upper)
    return round(100.0 * float(gc) / float(max(1, denom)), 2)


def inspect_sequences(
    fasta_path: Optional[str] = None,
    fasta_content: Optional[str] = None,
    project_root: Path = PROJECT_ROOT,
) -> Dict[str, Any]:
    """预检输入文件/文本，返回 Contig 列表、长度与 GC 分布供工作台勾选。"""
    seqs, descs = load_sequences_with_meta(
        fasta_path=fasta_path,
        fasta_content=fasta_content,
        project_root=project_root,
    )
    contigs: List[Dict[str, Any]] = []
    total_bp = 0
    for cid, seq in seqs.items():
        length = len(seq)
        total_bp += length
        contigs.append({
            "id": cid,
            "length": length,
            "gc_percent": compute_gc_percent(seq),
            "description": descs.get(cid, ""),
        })
    return {
        "contigs": contigs,
        "total_contigs": len(contigs),
        "total_bp": total_bp,
    }


def filter_selected_contigs(
    sequences: Dict[str, str],
    selected_contigs: Optional[List[str]],
) -> Dict[str, str]:
    """根据前端勾选列表过滤参与扫描的 Contig；空选则返回全部。"""
    if not selected_contigs:
        return dict(sequences)
    wanted = {cid for cid in selected_contigs if cid}
    filtered = {cid: seq for cid, seq in sequences.items() if cid in wanted}
    if not filtered:
        raise ValueError("勾选的 Contig 均未在输入序列中找到")
    return filtered


def _extract_orfs_in_slice(seq_slice: str) -> List[Dict[str, Any]]:
    """使用 Pyrodigal meta 模式快速预测片段内的 ORF 列表 (1-based 坐标)。"""
    if len(seq_slice) < 90:
        return []
    finder = pyrodigal.GeneFinder(meta=True)
    genes = finder.find_genes(seq_slice.encode("ascii", errors="ignore"))
    orfs: List[Dict[str, Any]] = []
    for idx, gene in enumerate(genes, start=1):
        aa = gene.translate(include_stop=False)
        orfs.append({
            "index": idx,
            "begin": gene.begin,
            "end": gene.end,
            "strand": gene.strand,
            "length_aa": len(aa),
            "translation": aa,
        })
    return orfs


def _classify_completeness(
    length_bp: int,
    peak_score: float,
    gate: Optional[RegionGateResult],
) -> Tuple[str, str]:
    """返回 (机读等级 key, 中文人类可读评估标签)，综合 ProteinGate 真实 tier 与区段尺度/峰分。"""
    if gate is not None:
        tier = (gate.tier or "").lower()
        if gate.decision == "reject" or tier.startswith("rejected"):
            return "rejected", "蛋白门控过滤 (低可信/非典型)"
        if tier in {"hallmark_confirmed", "high"}:
            if length_bp >= 20000 or gate.hallmark_hits >= 5:
                return "high", "完整/高可信 (蛋白与模型双确证)"
            return "medium", "部分完整/标志蛋白确证 (Medium)"
        if tier in {"phage_cluster_confirmed", "medium"}:
            if length_bp >= 25000 and peak_score >= 0.85 and gate.non_amg_hits >= 6:
                return "high", "完整/高可信 (噬菌体蛋白簇确证)"
            return "medium", "疑似完整/蛋白集群确证 (Medium)"
        if tier == "dark_matter_fallback":
            if length_bp >= 25000 and peak_score >= 0.85:
                return "intact_like", "完整候选前噬菌体 (高分暗物质保留)"
            if length_bp >= 12000:
                return "medium", "中等长度暗物质前噬菌体"
            return "fragment", "短片段/暗物质前噬菌体"
        if tier != "gate_disabled":
            return "low", "低可信/可能残余片段 (Low)"

    if length_bp >= 25000 and peak_score >= 0.75:
        return "intact_like", "完整候选前噬菌体 (模型高置信)"
    if length_bp >= 12000:
        return "medium", "中等长度前噬菌体区段"
    return "fragment", "短片段/残余前噬菌体"


def _build_region_seq_record(
    *,
    record_id: str,
    description: str,
    slice_seq: str,
    rel_prophage_start: int,
    rel_prophage_end: int,
    region_label: str,
    note: str,
    orfs: List[Dict[str, Any]],
) -> SeqRecord:
    """构建带前噬菌体区段注释与 CDS 特征的标准 SeqRecord (支持 GenBank 写出)。"""
    clean_id = "".join(ch if (ch.isalnum() or ch in {"_", "-"}) else "_" for ch in record_id)[:16]
    if not clean_id:
        clean_id = "PROPHAGE"

    rec = SeqRecord(
        Seq(slice_seq),
        id=clean_id,
        name=clean_id,
        description=description,
        annotations={
            "molecule_type": "DNA",
            "topology": "linear",
            "data_file_division": "PHG",
        },
    )

    rec.features.append(
        SeqFeature(
            FeatureLocation(max(0, rel_prophage_start), min(len(slice_seq), rel_prophage_end), strand=1),
            type="misc_feature",
            qualifiers={
                "label": [region_label],
                "note": [note],
            },
        )
    )

    for idx, orf in enumerate(orfs, start=1):
        b0 = max(0, int(orf["begin"]) - 1)
        e0 = min(len(slice_seq), int(orf["end"]))
        if e0 <= b0:
            continue
        strand = 1 if int(orf["strand"]) >= 0 else -1
        in_core = (b0 < rel_prophage_end) and (e0 > rel_prophage_start)
        product = "putative prophage protein" if in_core else "host flanking region protein"
        qualifiers: Dict[str, Any] = {
            "locus_tag": [f"{clean_id}_ORF_{idx:04d}"],
            "product": [product],
        }
        aa = str(orf.get("translation") or "")
        if aa:
            qualifiers["translation"] = [aa]
        rec.features.append(
            SeqFeature(
                FeatureLocation(b0, e0, strand=strand),
                type="CDS",
                qualifiers=qualifiers,
            )
        )
    return rec


def _write_gbk_string(rec: SeqRecord) -> str:
    buf = io.StringIO()
    SeqIO.write(rec, buf, "genbank")
    return buf.getvalue()


def _compute_contig_base_tracks(
    seq: str,
    features: List[Dict[str, Any]],
    *,
    num_bins: int = 360,
) -> List[Dict[str, Any]]:
    """计算全长 Contig 的等距 GC%、GC Skew 与基因密度分箱曲线用于叠图底图。"""
    c_len = len(seq)
    if c_len <= 0:
        return []
    actual_bins = min(max(1, c_len // 200), max(16, num_bins))
    step = max(1.0, float(c_len) / float(actual_bins))
    gene_counts = [0] * actual_bins
    for feat in features:
        mid = 0.5 * (feat["start_bp"] + feat["end_bp"])
        bi = max(0, min(actual_bins - 1, int(mid / step)))
        gene_counts[bi] += 1

    upper = seq.upper()
    out: List[Dict[str, Any]] = []
    for bi in range(actual_bins):
        sb = round(bi * step)
        eb = min(c_len, round((bi + 1) * step))
        if eb <= sb:
            eb = min(c_len, sb + 1)
        sub = upper[sb:eb]
        g_cnt = sub.count("G")
        c_cnt = sub.count("C")
        at_cnt = sub.count("A") + sub.count("T")
        gc_tot = g_cnt + c_cnt
        atgc = at_cnt + gc_tot
        gc_pct = round(100.0 * float(gc_tot) / float(max(1, atgc)), 2) if atgc > 0 else 0.0
        gc_skew = round(float(g_cnt - c_cnt) / float(max(1, gc_tot)), 4) if gc_tot > 0 else 0.0
        out.append({
            "start_bp": sb,
            "end_bp": eb,
            "gc_pct": gc_pct,
            "gc_skew": gc_skew,
            "gene_count": gene_counts[bi],
        })
    return out


def _annotate_base_features_with_overlay(
    contig_id: str,
    contig_seq: str,
    raw_base_features: Optional[List[Dict[str, Any]]],
    contig_regions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """补齐底图基因特征（GBK 原生特征或 FASTA 的 Pyrodigal 骨架）并标记归属的前噬菌体区间。"""
    if raw_base_features is not None and len(raw_base_features) > 0:
        feats = [dict(f) for f in raw_base_features]
    else:
        orfs = _extract_orfs_in_slice(contig_seq)
        feats = [
            {
                "index": o["index"],
                "type": "CDS",
                "start_bp": max(0, o["begin"] - 1),
                "end_bp": o["end"],
                "strand": o["strand"],
                "locus_tag": f"{contig_id}_ORF_{o['index']:04d}",
                "gene": "",
                "product": f"putative predicted ORF ({o['length_aa']} aa)",
                "note": "Pyrodigal de novo base track",
                "source": "pyrodigal",
            }
            for o in orfs
        ]

    for feat in feats:
        fb = int(feat["start_bp"])
        fe = int(feat["end_bp"])
        matched_id: Optional[str] = None
        for reg in contig_regions:
            reg_s = int(reg["start_bp"])
            reg_e = int(reg["end_bp"])
            overlap = min(fe, reg_e) - max(fb, reg_s)
            if overlap > 0 and overlap >= 0.5 * max(1, fe - fb):
                matched_id = str(reg["region_id"])
                break
        feat["overlay_region_id"] = matched_id
        feat["in_prophage"] = matched_id is not None
    return feats


def build_contig_overlay_gbk(
    *,
    contig_id: str,
    contig_seq: str,
    base_features: List[Dict[str, Any]],
    regions: List[Dict[str, Any]],
    source_format: str = "fasta",
) -> str:
    """将完整目标 Contig 序列、底图特征与预测前噬菌体标注合成为完整叠图 GenBank 文本。"""
    clean_id = "".join(ch if (ch.isalnum() or ch in {"_", "-"}) else "_" for ch in contig_id)[:16] or "CONTIG"
    rec = SeqRecord(
        Seq(contig_seq),
        id=clean_id,
        name=clean_id,
        description=(
            f"{contig_id} overlay map ({source_format}, {len(contig_seq)} bp, "
            f"{len(regions)} predicted prophage regions)"
        ),
        annotations={
            "molecule_type": "DNA",
            "topology": "linear",
            "data_file_division": "BCT",
        },
    )

    for reg in regions:
        s0 = max(0, min(len(contig_seq), reg["start_bp"]))
        e0 = max(s0 + 1, min(len(contig_seq), reg["end_bp"]))
        rec.features.append(
            SeqFeature(
                FeatureLocation(s0, e0, strand=1),
                type="prophage_region",
                qualifiers={
                    "locus_tag": [reg["region_id"]],
                    "label": [reg["region_id"]],
                    "product": [f"Predicted Prophage ({reg['completeness_label']})"],
                    "note": [
                        f"PhageDiscovery V4.2; Peak={reg['peak_score']:.3f}; "
                        f"Mean={reg['mean_score']:.3f}; GC={reg['gc_percent']}%"
                    ],
                },
            )
        )

    for idx, feat in enumerate(base_features, start=1):
        sb = max(0, min(len(contig_seq), feat["start_bp"]))
        eb = max(sb + 1, min(len(contig_seq), feat["end_bp"]))
        strand = 1 if feat.get("strand", 1) >= 0 else -1
        qualifiers: Dict[str, Any] = {
            "locus_tag": [feat.get("locus_tag") or f"{clean_id}_F_{idx:05d}"],
            "product": [feat.get("product") or "hypothetical protein"],
        }
        if feat.get("gene"):
            qualifiers["gene"] = [feat["gene"]]
        if feat.get("overlay_region_id"):
            qualifiers["note"] = [f"Inside predicted region {feat['overlay_region_id']}"]
        rec.features.append(
            SeqFeature(
                FeatureLocation(sb, eb, strand=strand),
                type=feat.get("type") or "CDS",
                qualifiers=qualifiers,
            )
        )

    return _write_gbk_string(rec)


def export_scan_artifacts(
    *,
    task_id: str,
    task_name: str,
    model_info: Dict[str, Any],
    device_used: str,
    apply_protein_gate: bool,
    sequences: Dict[str, str],
    scan_result: ScanResult,
    out_dir: Path,
    flank_bp: int = 3000,
    base_features_by_contig: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    source_format: str = "fasta",
    input_source_path: Optional[str] = None,
    project_root: Path = PROJECT_ROOT,
) -> Dict[str, Any]:
    """将完整扫描结果、全基因组底图叠图分片与多格式生信产物安全落盘，并返回轻量级元数据与文件映射。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    regions_gbk_dir = out_dir / "regions"
    regions_gbk_dir.mkdir(parents=True, exist_ok=True)
    overlays_dir = out_dir / "overlays"
    overlays_dir.mkdir(parents=True, exist_ok=True)

    gate_map: Dict[Tuple[str, int, int], RegionGateResult] = {
        (g.region.contig_id, g.region.start_bp, g.region.end_bp): g
        for g in scan_result.gate_details
    }

    display_regions: List[PredictedRegion] = (
        list(scan_result.verified_regions) if apply_protein_gate else list(scan_result.raw_regions)
    )

    region_records: List[Dict[str, Any]] = []
    fasta_lines: List[str] = []
    tsv_lines: List[str] = [
        "\t".join([
            "region_index",
            "region_id",
            "contig_id",
            "start_bp",
            "end_bp",
            "length_bp",
            "peak_score",
            "mean_score",
            "window_count",
            "gc_percent",
            "orf_count",
            "completeness_label",
            "gate_decision",
            "hallmark_hits",
            "transposase_hits",
            "matched_titles",
        ])
    ]
    gff_lines: List[str] = ["##gff-version 3"]
    for cid, seq in sequences.items():
        gff_lines.append(f"##sequence-region {cid} 1 {len(seq)}")

    core_gbk_records: List[SeqRecord] = []

    for idx, region in enumerate(display_regions, start=1):
        contig_seq = sequences.get(region.contig_id, "")
        contig_len = len(contig_seq)
        s0 = max(0, min(region.start_bp, contig_len))
        e0 = max(s0, min(region.end_bp, contig_len))
        core_seq = contig_seq[s0:e0]
        length_bp = e0 - s0
        gc_pct = compute_gc_percent(core_seq)

        core_orfs = _extract_orfs_in_slice(core_seq)
        gate_res = gate_map.get((region.contig_id, region.start_bp, region.end_bp))
        comp_key, comp_label = _classify_completeness(length_bp, region.peak_score, gate_res)

        region_id = f"Phage_{idx:03d}"
        profile_key = f"{region.contig_id}:{region.start_bp}-{region.end_bp}"
        profile_bins = scan_result.region_profiles.get(profile_key, [])

        # 生成带宿主侧翼微区域的 GenBank (供 GenomeViewer 一键打开，兼顾速度与基因上下文)
        f_start = max(0, s0 - flank_bp)
        f_end = min(contig_len, e0 + flank_bp)
        flanked_seq = contig_seq[f_start:f_end]
        flanked_orfs = _extract_orfs_in_slice(flanked_seq)
        flanked_rec = _build_region_seq_record(
            record_id=f"{region_id}_{region.contig_id}",
            description=(
                f"{region_id} on {region.contig_id} [{s0 + 1}..{e0}] "
                f"(flanked window {f_start + 1}..{f_end}, model={model_info.get('version', 'V4')})"
            ),
            slice_seq=flanked_seq,
            rel_prophage_start=s0 - f_start,
            rel_prophage_end=e0 - f_start,
            region_label=f"{region_id} ({comp_label})",
            note=(
                f"Contig={region.contig_id}; GlobalCoord={s0 + 1}..{e0}; "
                f"PeakScore={region.peak_score:.4f}; MeanScore={region.mean_score:.4f}; GC={gc_pct}%"
            ),
            orfs=flanked_orfs,
        )
        flanked_gbk_path = regions_gbk_dir / f"region_{idx}.gbk"
        flanked_gbk_path.write_text(_write_gbk_string(flanked_rec), encoding="utf-8")

        core_rec = _build_region_seq_record(
            record_id=region_id,
            description=f"{region_id} {region.contig_id}:{s0 + 1}-{e0} length={length_bp}bp",
            slice_seq=core_seq,
            rel_prophage_start=0,
            rel_prophage_end=length_bp,
            region_label=region_id,
            note=f"PeakScore={region.peak_score:.4f}; Completeness={comp_label}",
            orfs=core_orfs,
        )
        core_gbk_records.append(core_rec)

        fasta_lines.append(
            f">{region_id}|{region.contig_id}:{s0 + 1}-{e0} length={length_bp} peak={region.peak_score:.4f} gc={gc_pct}"
        )
        for pos in range(0, len(core_seq), 80):
            fasta_lines.append(core_seq[pos: pos + 80])

        hallmark_hits = gate_res.hallmark_hits if gate_res else 0
        transposase_hits = gate_res.transposase_hits if gate_res else 0
        matched_titles = list(gate_res.matched_titles_sample) if gate_res else []
        gate_decision = gate_res.decision if gate_res else "bypass"

        tsv_lines.append(
            "\t".join([
                str(idx),
                region_id,
                region.contig_id,
                str(s0 + 1),
                str(e0),
                str(length_bp),
                f"{region.peak_score:.4f}",
                f"{region.mean_score:.4f}",
                str(region.window_count),
                f"{gc_pct:.2f}",
                str(len(core_orfs)),
                comp_label,
                gate_decision,
                str(hallmark_hits),
                str(transposase_hits),
                "; ".join(matched_titles[:5]),
            ])
        )

        # GFF3: 区域特征 + 内部 CDS
        gff_attrs = (
            f"ID={region_id};Name={region_id};peak_score={region.peak_score:.4f};"
            f"mean_score={region.mean_score:.4f};gc_percent={gc_pct:.2f};completeness={comp_key}"
        )
        gff_lines.append(
            f"{region.contig_id}\tPhageDiscovery\tprophage_region\t{s0 + 1}\t{e0}\t{region.peak_score:.4f}\t+\t.\t{gff_attrs}"
        )
        for orf in core_orfs:
            gs = s0 + int(orf["begin"])
            ge = s0 + int(orf["end"])
            strand_ch = "+" if int(orf["strand"]) >= 0 else "-"
            orf_id = f"{region_id}_CDS_{orf['index']:04d}"
            gff_lines.append(
                f"{region.contig_id}\tPyrodigal\tCDS\t{gs}\t{ge}\t.\t{strand_ch}\t0\tID={orf_id};Parent={region_id};aa_len={orf['length_aa']}"
            )

        region_records.append({
            "index": idx,
            "region_id": region_id,
            "contig_id": region.contig_id,
            "start_bp": s0,
            "end_bp": e0,
            "start_1based": s0 + 1,
            "end_1based": e0,
            "length_bp": length_bp,
            "peak_score": round(float(region.peak_score), 4),
            "mean_score": round(float(region.mean_score), 4),
            "window_count": region.window_count,
            "gc_percent": gc_pct,
            "orf_count": len(core_orfs),
            "completeness_key": comp_key,
            "completeness_label": comp_label,
            "gate_decision": gate_decision,
            "gate_tier": gate_res.tier if gate_res else "",
            "hallmark_hits": hallmark_hits,
            "non_amg_hits": gate_res.non_amg_hits if gate_res else 0,
            "transposase_hits": transposase_hits,
            "amg_hits": gate_res.amg_hits if gate_res else 0,
            "matched_titles": matched_titles,
            "profile": profile_bins,
            "gbk_file": _normalize_storage_path(str(flanked_gbk_path), project_root),
        })

    # 也记录被 ProteinGate 淘汰的候选供专业复核参考（不纳入正式交付，但在详情中可查）
    rejected_candidates: List[Dict[str, Any]] = []
    for g in scan_result.gate_details:
        if g.decision == "reject":
            rejected_candidates.append({
                "contig_id": g.region.contig_id,
                "start_bp": g.region.start_bp,
                "end_bp": g.region.end_bp,
                "length_bp": g.region_len_bp,
                "peak_score": round(float(g.region.peak_score), 4),
                "hallmark_hits": g.hallmark_hits,
                "transposase_hits": g.transposase_hits,
                "matched_titles": list(g.matched_titles_sample),
            })

    fasta_out = out_dir / f"{task_id}_prophages.fasta"
    tsv_out = out_dir / f"{task_id}_regions.tsv"
    gff_out = out_dir / f"{task_id}_prophages.gff3"
    gbk_out = out_dir / f"{task_id}_prophages.gbk"
    result_json_out = out_dir / f"{task_id}_result.json"

    fasta_out.write_text("\n".join(fasta_lines) + ("\n" if fasta_lines else ""), encoding="utf-8")
    tsv_out.write_text("\n".join(tsv_lines) + "\n", encoding="utf-8")
    gff_out.write_text("\n".join(gff_lines) + "\n", encoding="utf-8")
    with open(gbk_out, "w", encoding="utf-8") as gbk_fh:
        if core_gbk_records:
            SeqIO.write(core_gbk_records, gbk_fh, "genbank")

    contigs_summary: List[Dict[str, Any]] = []
    score_tracks_map = scan_result.contig_score_tracks or {}
    for c_idx, (cid, seq) in enumerate(sequences.items(), start=1):
        contig_regions = [r for r in region_records if r["contig_id"] == cid]
        contig_rejected = [r for r in rejected_candidates if r["contig_id"] == cid]
        raw_base = (base_features_by_contig or {}).get(cid)
        base_feats = _annotate_base_features_with_overlay(cid, seq, raw_base, contig_regions)
        base_tracks = _compute_contig_base_tracks(seq, base_feats, num_bins=360)
        score_tracks = list(score_tracks_map.get(cid, []))

        overlay_path = overlays_dir / f"contig_{c_idx}.json"
        overlay_payload = {
            "contig_id": cid,
            "length_bp": len(seq),
            "gc_percent": compute_gc_percent(seq),
            "source_format": source_format,
            "base_tracks": base_tracks,
            "score_tracks": score_tracks,
            "base_features": base_feats,
            "regions": contig_regions,
            "rejected_candidates": contig_rejected,
        }
        overlay_path.write_text(
            json.dumps(overlay_payload, ensure_ascii=False),
            encoding="utf-8",
        )
        contigs_summary.append({
            "id": cid,
            "length": len(seq),
            "gc_percent": compute_gc_percent(seq),
            "hit_count": len(contig_regions),
            "source_format": source_format,
            "base_feature_count": len(base_feats),
            "overlay_file": _normalize_storage_path(str(overlay_path), project_root),
        })

    total_prophage_bp = sum(r["length_bp"] for r in region_records)
    prophage_fraction_pct = round(100.0 * float(total_prophage_bp) / float(max(1, scan_result.total_bp)), 3)

    files_map = {
        "fasta": _normalize_storage_path(str(fasta_out), project_root),
        "tsv": _normalize_storage_path(str(tsv_out), project_root),
        "gff3": _normalize_storage_path(str(gff_out), project_root),
        "gbk": _normalize_storage_path(str(gbk_out), project_root),
        "overlays_dir": _normalize_storage_path(str(overlays_dir), project_root),
        "folder": _normalize_storage_path(str(out_dir), project_root),
    }
    if input_source_path:
        files_map["input_source"] = _normalize_storage_path(input_source_path, project_root)

    summary = {
        "contig_count": len(sequences),
        "total_bp": scan_result.total_bp,
        "total_windows": scan_result.total_windows,
        "raw_region_count": len(scan_result.raw_regions),
        "region_count": len(region_records),
        "rejected_count": len(rejected_candidates),
        "total_prophage_bp": total_prophage_bp,
        "prophage_fraction_pct": prophage_fraction_pct,
        "source_format": source_format,
        "model_id": model_info.get("model_id", ""),
        "model_version": model_info.get("version", ""),
        "model_label": model_info.get("label", ""),
        "device_used": device_used,
        "apply_protein_gate": apply_protein_gate,
        "timings_sec": dict(scan_result.timings_sec),
    }

    payload = {
        "task_id": task_id,
        "task_name": task_name,
        "summary": summary,
        "contigs": contigs_summary,
        "regions": region_records,
        "rejected_candidates": rejected_candidates,
        "files": files_map,
    }
    result_json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "summary": summary,
        "files": files_map,
        "result_path": _normalize_storage_path(str(result_json_out), project_root),
        "payload": payload,
    }
