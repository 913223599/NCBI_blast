# -*- coding: utf-8 -*-
"""
配套负样本多核并行完整性及反向噬菌体排异验证器

校验维度：
1. FASTA 与 GBK 文件成对存在、UTF-8 可读、双格式序列字节级一致、IUPAC 字符合法性；
2. 提取 CDS/蛋白翻译、tRNA、拓扑结构、物种分类及双文件 SHA-256 指纹；
3. 反向身份验证：确认确系细菌质粒 / 细菌染色体 / 非噬菌体病毒，若整条记录本身即为游离噬菌体则拦截拒绝；
4. 记录细菌染色体/质粒上疑似潜伏前噬菌体标志蛋白数量（供下游背景掩码剔除参考）。
"""
import concurrent.futures
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from Bio import SeqIO

from .validator import (
    INTEGRITY_WARN_N_RATIO,
    KEY_MARKER_PATTERNS,
    VALID_DNA_RE,
    PhageCDSRecord,
    _assess_phage_identity,
    _extract_host,
    _sha256_file,
)

logger = logging.getLogger("utils.phage_dataset.negative_validator")

PLASMID_DESC_RE = re.compile(r"\bplasmid\b|\bmegaplasmid\b|\bextrachromosomal\b", re.IGNORECASE)


@dataclass
class NegativeRecordValidation:
    accession: str
    status: str  # passed | warning | failed
    is_valid_negative: bool = False
    negative_category: str = ""  # plasmid | bacterial_chromosome | non_phage_virus | rejected
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    fasta_path: str = ""
    gbk_path: str = ""
    fasta_sha256: str = ""
    gbk_sha256: str = ""
    length_bp: int = 0
    gc_percent: float = 0.0
    n_percent: float = 0.0
    topology: str = "linear"
    molecule_type: str = ""
    organism: str = ""
    host: str = ""
    taxonomy: str = ""
    description: str = ""
    cds_count: int = 0
    translated_cds_count: int = 0
    trna_count: int = 0
    suspected_prophage_cds_count: int = 0
    cds_items: List[PhageCDSRecord] = field(default_factory=list)


def _classify_negative_category(
    taxonomy_tokens: List[str],
    organism: str,
    description: str,
    features: list,
    length_bp: int,
    product_texts: List[str],
    host: str,
) -> Tuple[bool, str, str]:
    """
    判定是否为合法负样本及其子类。
    返回: (is_valid_negative, category, reject_reason)
    """
    is_phage, _, tax_group, _ = _assess_phage_identity(
        taxonomy_tokens=taxonomy_tokens,
        organism=organism,
        description=description,
        host=host,
        product_texts=product_texts,
    )
    if is_phage:
        return False, "rejected", f"contaminated_with_phage:{tax_group}"

    token_set = {t.strip() for t in taxonomy_tokens if t.strip()}
    if "Viruses" in token_set:
        return True, "non_phage_virus", ""

    if "Bacteria" in token_set or "Archaea" in token_set:
        has_plasmid_qual = False
        for feat in features:
            if feat.type == "source":
                if feat.qualifiers.get("plasmid"):
                    has_plasmid_qual = True
                break
        if has_plasmid_qual or PLASMID_DESC_RE.search(description):
            return True, "plasmid", ""
        if length_bp >= 400000:
            return True, "bacterial_chromosome", ""
        return True, "plasmid", ""

    return False, "rejected", f"unknown_negative_taxonomy:{taxonomy_tokens[0] if taxonomy_tokens else 'empty'}"


def validate_single_negative_pair(args: Tuple[str, str, str, int]) -> NegativeRecordValidation:
    """校验单条负样本的 .fasta 与 .gbk 配对文件及反向身份。"""
    accession, fasta_path_str, gbk_path_str, min_length_bp = args
    fasta_path = Path(fasta_path_str)
    gbk_path = Path(gbk_path_str)
    res = NegativeRecordValidation(
        accession=accession,
        status="failed",
        fasta_path=str(fasta_path),
        gbk_path=str(gbk_path),
    )

    if not fasta_path.exists() or fasta_path.stat().st_size == 0:
        res.errors.append("missing_or_empty_fasta")
        return res
    if not gbk_path.exists() or gbk_path.stat().st_size == 0:
        res.errors.append("missing_or_empty_gbk")
        return res

    res.fasta_sha256 = _sha256_file(fasta_path)
    res.gbk_sha256 = _sha256_file(gbk_path)

    try:
        with open(fasta_path, "r", encoding="utf-8") as fh:
            fasta_recs = list(SeqIO.parse(fh, "fasta"))
    except Exception as exc:
        res.errors.append(f"fasta_parse_error:{exc}")
        return res

    if len(fasta_recs) != 1:
        res.errors.append(f"unexpected_fasta_record_count:{len(fasta_recs)}")
        return res

    try:
        with open(gbk_path, "r", encoding="utf-8") as fh:
            gbk_recs = list(SeqIO.parse(fh, "genbank"))
    except Exception as exc:
        res.errors.append(f"gbk_parse_error:{exc}")
        return res

    if len(gbk_recs) != 1:
        res.errors.append(f"unexpected_gbk_record_count:{len(gbk_recs)}")
        return res

    fa_rec = fasta_recs[0]
    gb_rec = gbk_recs[0]
    fa_seq = str(fa_rec.seq).upper()
    gb_seq = str(gb_rec.seq).upper()

    if len(gb_seq) == 0:
        res.errors.append("empty_genbank_sequence")
        return res
    if fa_seq != gb_seq:
        res.errors.append(f"sequence_mismatch:fasta={len(fa_seq)},gbk={len(gb_seq)}")
        return res
    if len(fa_seq) < min_length_bp:
        res.errors.append(f"sequence_too_short:{len(fa_seq)}")
        return res
    if not VALID_DNA_RE.match(fa_seq):
        res.errors.append("invalid_iupac_dna_characters")
        return res

    seq_len = len(fa_seq)
    gc_cnt = fa_seq.count("G") + fa_seq.count("C")
    n_cnt = fa_seq.count("N")
    n_ratio = n_cnt / seq_len

    res.length_bp = seq_len
    res.gc_percent = round((gc_cnt / seq_len) * 100.0, 2)
    res.n_percent = round(n_ratio * 100.0, 3)

    if n_ratio > INTEGRITY_WARN_N_RATIO:
        res.warnings.append(f"high_n_content:{res.n_percent}%")

    ann = gb_rec.annotations
    res.topology = str(ann.get("topology") or "linear").lower()
    res.molecule_type = str(ann.get("molecule_type") or "")
    res.organism = str(ann.get("organism") or fa_rec.id)
    tax_tokens = [str(x) for x in (ann.get("taxonomy") or [])]
    res.taxonomy = "; ".join(tax_tokens)
    res.description = str(gb_rec.description or fa_rec.description or "")
    res.host = _extract_host(gb_rec)

    cds_items: List[PhageCDSRecord] = []
    all_products: List[str] = []
    trna_cnt = 0
    prophage_hits = 0

    for idx, feat in enumerate(gb_rec.features, start=1):
        if feat.type == "tRNA":
            trna_cnt += 1
            continue
        if feat.type != "CDS":
            continue

        q = feat.qualifiers
        locus_tag = str((q.get("locus_tag") or q.get("gene") or [f"{accession}_CDS_{idx:04d}"])[0])
        protein_id = str((q.get("protein_id") or [locus_tag])[0])
        product = str((q.get("product") or ["hypothetical protein"])[0])
        all_products.append(product)

        trans = str((q.get("translation") or [""])[0]).strip()
        if not trans and feat.location:
            try:
                trans = str(feat.extract(gb_rec.seq).translate(table=11, to_stop=True))
            except Exception:
                trans = ""

        f_start = int(feat.location.start) + 1 if feat.location else 0
        f_end = int(feat.location.end) if feat.location else 0
        f_strand = int(feat.location.strand or 1) if feat.location else 1

        if trans:
            res.translated_cds_count += 1
            cds_items.append(
                PhageCDSRecord(
                    accession=accession,
                    locus_tag=locus_tag,
                    protein_id=protein_id,
                    start=f_start,
                    end=f_end,
                    strand=f_strand,
                    length_aa=len(trans),
                    product=product,
                    translation=trans,
                )
            )

        if any(pat.search(product) for pat in KEY_MARKER_PATTERNS.values()):
            prophage_hits += 1

    res.cds_count = len(all_products)
    res.trna_count = trna_cnt
    res.suspected_prophage_cds_count = prophage_hits
    res.cds_items = cds_items

    if res.cds_count == 0:
        res.errors.append("zero_cds_annotated")
        return res

    is_valid_neg, cat, reject_reason = _classify_negative_category(
        taxonomy_tokens=tax_tokens,
        organism=res.organism,
        description=res.description,
        features=gb_rec.features,
        length_bp=seq_len,
        product_texts=all_products,
        host=res.host,
    )
    res.is_valid_negative = is_valid_neg
    res.negative_category = cat
    if not is_valid_neg:
        res.errors.append(reject_reason)
        return res

    res.status = "warning" if res.warnings else "passed"
    return res


def validate_negative_dataset_parallel(
    data_dir: Path,
    min_length_bp: int = 3000,
    max_workers: Optional[int] = None,
) -> List[NegativeRecordValidation]:
    """多核并行校验负样本目录，自动预留 CPU 核心防止主机卡死。"""
    root = Path(data_dir).resolve()
    fasta_dir = root / "fasta"
    gbk_dir = root / "gbk"

    all_accessions = sorted(
        {p.stem for p in fasta_dir.glob("*.fasta")} | {p.stem for p in gbk_dir.glob("*.gbk")}
    )
    if not all_accessions:
        return []

    cpu_cnt = os.cpu_count() or 4
    safe_workers = max_workers if max_workers is not None else max(1, min(cpu_cnt - 2, 16))
    tasks = [
        (acc, str(fasta_dir / f"{acc}.fasta"), str(gbk_dir / f"{acc}.gbk"), min_length_bp)
        for acc in all_accessions
    ]

    logger.info(f"启动负样本多核并行校验: 共 {len(tasks)} 条样本, 并发进程数={safe_workers}")
    results: List[NegativeRecordValidation] = []
    if safe_workers == 1 or len(tasks) < 8:
        results = [validate_single_negative_pair(t) for t in tasks]
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=safe_workers) as pool:
            for item in pool.map(validate_single_negative_pair, tasks, chunksize=4):
                results.append(item)

    results.sort(key=lambda x: x.accession)
    return results

