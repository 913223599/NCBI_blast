# -*- coding: utf-8 -*-
"""
Figure Studio 数据桥接、跨模块只读加载、内置科研演示数据集与产物归档管理。
"""
import csv
import io
import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from Bio import SeqIO

from ..analysis.annotation.manager import get_annotation_manager
from ..phylo.runtime.tool_registry import get_project_root
from ..phylo.storage.archive_store import PhyloArchiveStore
from .models import GenomeFeatureItem, ParsedGenomeInput, StudioFigureFile, StudioHistoryItem
import logging
logger = logging.getLogger(__name__)


def get_studio_root_dir() -> Path:
    root = get_project_root() / "results" / "figure_studio"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _build_demo_genomes() -> List[ParsedGenomeInput]:
    """构造贴近实际噬菌体模块化结构的内置演示基因组（含尾丝变异与抗防御缺失）。"""
    templates = [
        ("T5-E1_asm (Query)", True, False),
        ("Escherichia phage T5 (AY587007)", True, False),
        ("Escherichia phage EPS7 (EF204940)", True, True),
        ("Enterobacter phage vB_EhoP (Variant)", False, True),
    ]
    gene_defs = [
        ("terminase small subunit", "head and packaging", 120, 620, "+", "MKLQRVVLLPGAGKSTLLQAAARLLGVDVY"),
        ("terminase large subunit", "head and packaging", 660, 2180, "+", "MKTLLVFGDDRAVLQQLAEHYGKPVDLTRD"),
        ("portal protein", "head and packaging", 2240, 3680, "+", "MAVRLKPQQWTGDAILLSRNFEKQVAGLPA"),
        ("head maturation protease", "head and packaging", 3740, 4520, "+", "MSDVLAQVIKDGKTVFYPLSGTRQAELLKR"),
        ("major capsid protein", "head and packaging", 4600, 5880, "+", "MSKVGTLAAIVNQPLDERFYKATGQIVSML"),
        ("head-tail adaptor", "connector", 5960, 6580, "+", "MPRTSLQGDLVFAINQKSVATRLGDWVEYQ"),
        ("tail completion protein", "connector", 6640, 7280, "+", "MTKIVLAPGQVTSLEQWRKLAAGDTVSFEN"),
        ("major tail protein", "tail", 7380, 8420, "+", "MGFDVIKLASGQPLYTTRELAQKVTGVSLD"),
        ("tail length tape measure protein", "tail", 8520, 11800, "+", "MAVSLGQKTLAEQLAARVTGKLSDEVQKMA"),
        ("minor tail protein", "tail", 11880, 12960, "+", "MQLTVRKDGSIVAVPTQLLKDAEGNYVWRS"),
        ("tail fiber protein", "tail", 13060, 14820, "+", "MATSGDFNKLPTVYQWRGHLSADTVGKLVP"),
        ("anti-defence protein (Acr)", "anti-defence", 14920, 15540, "-", "MNKPQRLTVSSDDYFAAQKLVEAGYTPQDR"),
        ("DNA helicase", "DNA, RNA and nucleotide metabolism", 15680, 17200, "-", "MTRILVDGPHAGKSTFLQELVKLYGQPRVF"),
        ("DNA polymerase", "DNA, RNA and nucleotide metabolism", 17280, 19440, "-", "MKVVFADFETLGRQAVDKLRQAGYDVVLVG"),
        ("transcription regulator", "transcription regulation", 19540, 20280, "+", "MPQKRSVAELAGVTPQTVSRWLNGKDLVEP"),
        ("holin", "lysis", 20380, 20860, "+", "MLGIILVVVALLLSKKKQAAELAKRGVTVQ"),
        ("endolysin", "lysis", 20920, 21780, "+", "MRIFDGVTGHKLQPSWNAYKELLGRVPKDS"),
    ]
    out: List[ParsedGenomeInput] = []
    base_unit = "ATGCTAGCTAGCATCGATCGTAGCTAGCATGCATGCTAGCTAGCATCGAT"
    for g_idx, (name, has_acr, alt_tail) in enumerate(templates):
        feats: List[GenomeFeatureItem] = []
        for idx, (prod, cat, st, en, strand, aa_base) in enumerate(gene_defs):
            if not has_acr and "anti-defence" in cat:
                continue
            aa = aa_base
            prod_use = prod
            if alt_tail and "tail fiber" in prod:
                aa = "MVWXYZQKRSTUVWHKLMNPDQRS" + aa_base[-8:]
                prod_use = "divergent tail fiber / RBP"
            elif g_idx > 0:
                aa = aa_base[:-2] + "KA"
            feats.append(
                GenomeFeatureItem(
                    locus_tag=f"G{g_idx + 1}_CDS_{idx + 1:03d}",
                    start=st + (g_idx * 40 if idx > 8 else 0),
                    end=en + (g_idx * 40 if idx > 8 else 0),
                    strand=strand,
                    feature_type="CDS",
                    product=prod_use,
                    category=cat,
                    translation=aa,
                )
            )
        seq_len = 22400
        seq_chars = list((base_unit * (seq_len // len(base_unit) + 2))[:seq_len])
        # 在头部(2000-4000)制造高 GC 波，尾部(13000-15600)制造低 GC / skew 转换
        for pos in range(2000, 4200):
            seq_chars[pos] = "G" if pos % 3 else "C"
        for pos in range(13000, 15500):
            seq_chars[pos] = "A" if (pos + g_idx) % 2 else "T"
        out.append(
            ParsedGenomeInput(
                name=name,
                sequence="".join(seq_chars),
                length=seq_len,
                features=feats,
            )
        )
    return out


def get_demo_viridic_payload() -> Dict[str, Any]:
    labels = [
        "T5-E1_asm",
        "T5-E2_asm",
        "AY692264 (T5)",
        "EF204940 (EPS7)",
        "NC_005859 (T5_ref)",
        "MK373780 (Vequinta)",
        "NC_055913 (Outgroup)",
    ]
    wg = [
        [100.0, 98.4, 97.5, 86.2, 81.4, 34.5, 11.2],
        [98.4, 100.0, 96.9, 85.8, 80.9, 34.1, 11.0],
        [97.5, 96.9, 100.0, 86.9, 82.0, 35.0, 11.5],
        [86.2, 85.8, 86.9, 100.0, 79.5, 33.8, 10.9],
        [81.4, 80.9, 82.0, 79.5, 100.0, 34.2, 11.4],
        [34.5, 34.1, 35.0, 33.8, 34.2, 100.0, 14.8],
        [11.2, 11.0, 11.5, 10.9, 11.4, 14.8, 100.0],
    ]
    af = [
        [100.0, 97.0, 96.0, 85.0, 80.0, 42.0, 15.0],
        [97.0, 100.0, 95.5, 84.0, 79.5, 41.0, 14.5],
        [96.0, 95.5, 100.0, 86.0, 81.0, 43.0, 15.5],
        [85.0, 84.0, 86.0, 100.0, 78.0, 40.0, 14.0],
        [80.0, 79.5, 81.0, 78.0, 100.0, 41.5, 14.8],
        [42.0, 41.0, 43.0, 40.0, 41.5, 100.0, 19.0],
        [15.0, 14.5, 15.5, 14.0, 14.8, 19.0, 100.0],
    ]
    lengths = [121400, 120900, 121750, 111382, 121300, 139000, 128300]
    return {"labels": labels, "wgani_matrix": wg, "af_matrix": af, "genome_lengths": lengths}


def list_available_sources() -> Dict[str, Any]:
    phylo_jobs: List[Dict[str, Any]] = []
    try:
        for job in PhyloArchiveStore().list_jobs(limit=50):
            has_ani = bool(job.ani_result and (job.ani_result.wgani_matrix or job.ani_result.top_hits))
            has_nwk = bool(job.newick)
            if not has_ani and not has_nwk:
                continue
            phylo_jobs.append(
                {
                    "job_id": job.job_id,
                    "title": job.title,
                    "status": job.status,
                    "leaf_count": job.metrics.leaf_count if job.metrics else 0,
                    "has_ani_matrix": bool(job.ani_result and len(job.ani_result.wgani_matrix) >= 2),
                    "top_hits_count": len(job.ani_result.top_hits) if job.ani_result else 0,
                    "has_newick": has_nwk,
                    "created_at": job.created_at,
                }
            )
    except Exception as exc:
        logger.warning("读取进化树任务数据源失败: %s", exc)

    annotation_tasks: List[Dict[str, Any]] = []
    try:
        for t in get_annotation_manager().list_history(limit=100):
            if t.get("status") != "completed":
                continue
            summary = t.get("summary") or {}
            annotation_tasks.append(
                {
                    "task_id": t["task_id"],
                    "task_name": t["task_name"],
                    "sample_type": t.get("sample_type", "PHAGE"),
                    "feature_count": t.get("feature_count", summary.get("cds_count", 0)),
                    "genome_length": summary.get("genome_length", 0),
                    "created_at": t.get("created_at", ""),
                }
            )
    except Exception as exc:
        logger.warning("读取进化树任务数据源失败: %s", exc)

    return {
        "phylo_jobs": phylo_jobs,
        "annotation_tasks": annotation_tasks,
        "sample_presets": [
            {"id": "tequintavirus", "label": "Tequintavirus 同种/近缘示范集"},
            {"id": "depocatalog", "label": "Klebsiella 荚膜解聚酶特异性示范集"},
        ],
    }


def load_annotation_genome(task_id: str) -> ParsedGenomeInput:
    mgr = get_annotation_manager()
    res = mgr.get_task_result(task_id)
    if not res:
        raise ValueError(f"未找到注释任务: {task_id}")
    task_name = str(res.get("task_name") or task_id)
    gbk_path = mgr.get_task_file_path(task_id, "gbk")
    seq_full = ""
    total_len = 0
    if gbk_path and gbk_path.is_file():
        seqs: List[str] = []
        for rec in SeqIO.parse(str(gbk_path), "genbank"):
            seqs.append(str(rec.seq))
            total_len += len(rec.seq)
        seq_full = "".join(seqs)

    raw_feats = res.get("features") or []
    feats: List[GenomeFeatureItem] = []
    max_end = 0
    for f in raw_feats:
        st = int(f.get("start") or 0)
        en = int(f.get("end") or st)
        max_end = max(max_end, en)
        feats.append(
            GenomeFeatureItem(
                locus_tag=str(f.get("locus_tag") or f.get("id") or ""),
                start=st,
                end=en,
                strand="-" if str(f.get("strand") or "+") in ("-", "-1") else "+",
                feature_type=str(f.get("feature_type") or "CDS"),
                product=str(f.get("product") or "hypothetical protein"),
                category=str(f.get("category") or ""),
                function=str(f.get("function") or ""),
                phrog=str(f.get("phrog")) if f.get("phrog") else None,
                translation=str(f.get("translation") or ""),
                nucleotide_seq=str(f.get("nucleotide_seq") or ""),
            )
        )
    if not seq_full:
        seq_full = "".join(f.nucleotide_seq for f in feats if f.nucleotide_seq)
    if total_len <= 0:
        total_len = max(len(seq_full), max_end, 1000)

    return ParsedGenomeInput(
        name=task_name,
        sequence=seq_full.upper(),
        length=total_len,
        features=feats,
    )


def parse_gbk_source(gbk_path: Optional[str] = None, gbk_content: Optional[str] = None) -> ParsedGenomeInput:
    handle: Any
    name_fallback = "Uploaded_Genome"
    if gbk_content and gbk_content.strip():
        handle = io.StringIO(gbk_content)
        records = list(SeqIO.parse(handle, "genbank"))
    elif gbk_path and Path(gbk_path).is_file():
        p = Path(gbk_path)
        name_fallback = p.stem
        with open(p, "r", encoding="utf-8", errors="replace") as fh:
            records = list(SeqIO.parse(fh, "genbank"))
    else:
        raise ValueError("未提供有效的 GenBank 文件路径或文本内容")

    if not records:
        raise ValueError("无法从 GenBank 输入中解析出序列记录")

    feats: List[GenomeFeatureItem] = []
    seqs: List[str] = []
    offset = 0
    for rec in records:
        rseq = str(rec.seq).upper()
        seqs.append(rseq)
        for idx, feat in enumerate(rec.features, start=1):
            if feat.type not in ("CDS", "tRNA"):
                continue
            quals = feat.qualifiers
            prod = str((quals.get("product") or ["hypothetical protein"])[0])
            ltag = str((quals.get("locus_tag") or quals.get("gene") or [f"F_{idx:03d}"])[0])
            cat = str((quals.get("category") or quals.get("function") or [""])[0])
            trans = str((quals.get("translation") or [""])[0])
            st = int(feat.location.start) + offset + 1
            en = int(feat.location.end) + offset
            strand = "-" if feat.location.strand == -1 else "+"
            feats.append(
                GenomeFeatureItem(
                    locus_tag=ltag,
                    start=st,
                    end=en,
                    strand=strand,
                    feature_type=feat.type,
                    product=prod,
                    category=cat,
                    translation=trans,
                )
            )
        offset += len(rseq)

    merged_seq = "".join(seqs)
    return ParsedGenomeInput(
        name=str(records[0].description or records[0].id or name_fallback)[:64],
        sequence=merged_seq,
        length=max(len(merged_seq), 1),
        features=feats,
    )


def parse_fasta_text(fasta_text: str) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    handle = io.StringIO(fasta_text.strip())
    for rec in SeqIO.parse(handle, "fasta"):
        out.append((str(rec.id), str(rec.seq).upper()))
    return out


def parse_numeric_matrix_csv(
    csv_text: str,
) -> Tuple[List[str], List[str], List[List[float]], List[str], List[str]]:
    lines = [ln for ln in csv_text.strip().splitlines() if ln.strip()]
    if len(lines) < 2:
        raise ValueError("矩阵文本至少需要包含表头与 1 行数据")
    delim = "\t" if ("\t" in lines[0] and "," not in lines[0]) else ","
    rows = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=delim))
    header = [c.strip() for c in rows[0]]
    col_labels = header[1:]
    row_labels: List[str] = []
    values: List[List[float]] = []
    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        row_labels.append(row[0].strip())
        vec: List[float] = []
        for idx in range(1, len(col_labels) + 1):
            raw_v = row[idx].strip() if idx < len(row) else "0"
            try:
                vec.append(float(raw_v))
            except ValueError:
                vec.append(0.0)
        values.append(vec)
    return row_labels, col_labels, values, [], []


def create_render_dir(tool_id: str) -> Tuple[str, Path]:
    render_id = f"{tool_id}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    out_dir = get_studio_root_dir() / render_id
    out_dir.mkdir(parents=True, exist_ok=True)
    return render_id, out_dir


def build_figure_files_and_save_meta(
    render_id: str,
    tool_id: str,
    title: str,
    out_dir: Path,
    paths: List[Path],
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    created_at = time.time()
    figs: List[StudioFigureFile] = []
    for p in paths:
        figs.append(
            StudioFigureFile(
                filename=p.name,
                format=p.suffix.lstrip(".").lower(),
                size_bytes=p.stat().st_size,
                download_url=f"/api/figure-studio/files/{render_id}/{p.name}",
            )
        )
    payload = {
        "render_id": render_id,
        "tool_id": tool_id,
        "title": title,
        "created_at": created_at,
        "figures": [f.model_dump() for f in figs],
        "metadata": metadata or {},
    }
    (out_dir / "meta.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def list_render_history(limit: int = 30) -> List[StudioHistoryItem]:
    root = get_studio_root_dir()
    items: List[StudioHistoryItem] = []
    for meta_file in root.glob("*/meta.json"):
        try:
            data = json.loads(meta_file.read_text(encoding="utf-8"))
            items.append(
                StudioHistoryItem(
                    render_id=str(data.get("render_id") or meta_file.parent.name),
                    tool_id=str(data.get("tool_id") or "unknown"),
                    title=str(data.get("title") or meta_file.parent.name),
                    created_at=float(data.get("created_at") or meta_file.stat().st_mtime),
                    figures=[StudioFigureFile(**f) for f in (data.get("figures") or [])],
                )
            )
        except Exception as exc:
            logger.warning("读取 FigureStudio 元数据文件跳过损坏条目: %s", exc)
            continue
    items.sort(key=lambda x: x.created_at, reverse=True)
    return items[:limit]


def resolve_render_file(render_id: str, filename: str) -> Optional[Path]:
    safe_rid = Path(render_id).name
    safe_name = Path(filename).name
    base_dir = (get_studio_root_dir() / safe_rid).resolve()
    cand = (base_dir / safe_name).resolve()
    if cand.is_file() and cand.parent == base_dir:
        return cand
    return None
