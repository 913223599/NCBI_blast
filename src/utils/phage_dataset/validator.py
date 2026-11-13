# -*- coding: utf-8 -*-
"""
噬菌体数据集多核并行完整性验证器

校验维度：
1. FASTA 与 GBK 文件严格成对存在且非空、UTF-8 可读；
2. BioPython 双格式解析成功且碱基全长 100% 一致；
3. 碱基合法字符与简并碱基 (N) 比例检查；
4. 注释完整度检查（CDS 数、tRNA 数、蛋白翻译可提取率、拓扑构型、宿主字段、物种分类）；
5. 关键特征基因信号标识（整合酶 Integrase、末端酶 Terminase、裂解酶 Lysin/Endolysin、衣壳 Capsid、尾丝 Tail）；
6. 计算双文件 SHA-256 校验和，供本地索引持久化存证。
"""
import concurrent.futures
import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Tuple

from Bio import SeqIO

logger = logging.getLogger("utils.phage_dataset.validator")

VALID_DNA_RE = re.compile(r"^[ACGTRYKMSWBDHVN]+$")
INTEGRITY_WARN_N_RATIO = 0.05

KEY_MARKER_PATTERNS = {
    "has_integrase": re.compile(r"\b(?:integrase|excisionase|recombinase|tyrosine[- ]recombinase)\b", re.IGNORECASE),
    "has_terminase": re.compile(r"\b(?:terminase|terl|ters)\b", re.IGNORECASE),
    "has_lysin": re.compile(r"\b(?:endolysin|lysin|holin|muramidase|spanin|peptidoglycan\s+hydrolase)\b", re.IGNORECASE),
    "has_capsid": re.compile(r"\b(?:major\s+capsid|capsid\s+protein|portal\s+protein|coat\s+protein)\b", re.IGNORECASE),
    "has_tail": re.compile(r"\b(?:tail\s+fiber|tail\s+fibre|tailspike|tape\s+measure|baseplate|tail\s+sheath)\b", re.IGNORECASE),
}

# 广谱噬菌体蛋白特征正则（覆盖有尾、丝状、微小、RNA 及覆膜等全部噬菌体类群）
PHAGE_PROTEIN_EVIDENCE_RE = re.compile(
    r"\b(?:capsid|coat\s+protein|minor\s+coat|major\s+coat|spike\s+protein|pilot\s+protein|"
    r"scaffolding|scaffold\s+protein|portal|terminase|tail|baseplate|tape\s+measure|holin|"
    r"endolysin|lysin|spanin|integrase|excisionase|recombinase|bacteriophage|phage\s+protein|"
    r"virion|maturation\s+protein|lysis\s+protein|head[- ]tail|neck\s+protein|collar|sheath|"
    r"connector|packaging|antirepressor|prophage|zot|zonular\s+occludens)\b",
    re.IGNORECASE,
)

# 权威噬菌体 ICTV 分类群归属映射
PHAGE_TAXONOMY_GROUPS: List[Tuple[str, Tuple[str, ...]]] = [
    ("Caudoviricetes", (
        "Caudoviricetes", "Uroviricota", "Crassvirales", "Podoviridae", "Siphoviridae", "Myoviridae",
        "Autographiviridae", "Herelleviridae", "Demerecviridae", "Drexlerviridae", "Straboviridae",
        "Ackermannviridae", "Chaseviridae", "Schitoviridae", "Zobellviridae", "Salasmaviridae",
        "Rountreeviridae", "Peduoviridae", "Casjensviridae", "Mesyanzhinovviridae", "Guelinviridae",
        "Kyanoviridae", "Vilmaviridae", "Orlajenseniviridae", "Suoliviridae", "Steigviridae", "Winoviridae",
    )),
    ("Microviridae", (
        "Microviridae", "Malgrandaviricetes", "Petitvirales",
        "Phixviricota", "Microviricetes", "Bullavirales", "Gokushovirales",
        "Eubullaviridae", "Alphagokushoviridae", "Betagokushoviridae", "Pichoviridae", "Groupodiviridae",
    )),
    ("Inoviridae", ("Inoviridae", "Paulinoviridae", "Plectroviridae", "Tubulavirales", "Faserviricetes")),
    ("Leviviricetes", ("Leviviricetes", "Fiersviridae", "Atkinsviridae", "Duinviridae", "Solspiviridae", "Norzivirales", "Timlovirales")),
    ("Tectiviridae", ("Tectiviridae", "Autolykiviridae", "Kalamavirales", "Tectiliviricetes")),
    ("Corticoviridae", ("Corticoviridae", "Vinavirales")),
    ("Plasmaviridae", ("Plasmaviridae",)),
    ("Cystoviridae", ("Cystoviridae", "Mindivirales", "Vidaverviricetes")),
]

# 明确属于真核/古菌非噬菌体病毒的排除分类群
NON_PHAGE_VIRAL_TAXA = {
    "Pisuviricota", "Kitrinoviricota", "Negarnaviricota", "Artverviricota", "Cressdnaviricota",
    "Nucleocytoviricota", "Preplasmiviricota", "Herpesvirales", "Adenoviridae", "Baculoviridae",
    "Coronaviridae", "Flaviviridae", "Picornavirales", "Mononegavirales", "Bunyavirales",
    "Retroviridae", "Parvoviridae", "Papillomaviridae", "Polyomaviridae", "Geminiviridae",
    "Potyviridae", "Solemoviridae", "Sobelivirales", "Polerovirus", "Enamovirus", "Luteoviridae",
    "Poxviridae", "Rhabdoviridae", "Orthomyxoviridae", "Paramyxoviridae", "Filoviridae",
    "Togaviridae", "Caliciviridae", "Astroviridae", "Reovirales", "Asfarviridae",
    "Iridoviridae", "Phycodnaviridae", "Mimiviridae", "Fuselloviridae", "Rudiviridae",
    "Lipothrixviridae", "Bicaudaviridae", "Ampullaviridae", "Globuloviridae", "Guttaviridae",
    "Halspiviridae", "Thaspiviridae", "Portogloboviridae",
}

PHAGE_NAME_RE = re.compile(
    r"\b(?:bacteriophage|phage|prophage|microphage|coliphage|cyanophage|mycobacteriophage|actinophage|vibrophage|rhizobiophage|crassphage)\b",
    re.IGNORECASE,
)
EUKARYOTIC_HOST_RE = re.compile(
    r"\b(?:homo\s+sapiens|mus\s+musculus|arabidopsis|zea\s+mays|drosophila|gallus|sus\s+scrofa|bos\s+taurus|saccharomyces|human|mouse|plant)\b",
    re.IGNORECASE,
)


@dataclass
class PhageCDSRecord:
    accession: str
    locus_tag: str
    protein_id: str
    start: int
    end: int
    strand: int
    length_aa: int
    product: str
    translation: str


@dataclass
class PhageRecordValidation:
    accession: str
    status: str  # passed | warning | failed
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
    has_integrase: bool = False
    has_terminase: bool = False
    has_lysin: bool = False
    has_capsid: bool = False
    has_tail: bool = False
    is_phage: bool = False
    phage_confidence: str = "rejected"  # high | medium | low | rejected
    phage_tax_group: str = ""
    phage_evidence: List[str] = field(default_factory=list)
    cds_items: List[PhageCDSRecord] = field(default_factory=list)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _extract_host(rec: Any) -> str:
    """从 GenBank source 特征或描述中提取宿主信息。"""
    for feat in rec.features:
        if feat.type == "source":
            hosts = feat.qualifiers.get("host") or feat.qualifiers.get("lab_host")
            if hosts:
                return str(hosts[0]).strip()
            break
    # 从物种名尝试回退（例如 Escherichia phage T4 -> Escherichia）
    org = str(rec.annotations.get("organism") or "").strip()
    m = re.match(r"^([A-Z][a-z]+)\s+(?:phage|bacteriophage)\b", org)
    if m:
        return m.group(1)
    return ""


def _assess_phage_identity(
    taxonomy_tokens: List[str],
    organism: str,
    description: str,
    host: str,
    product_texts: List[str],
) -> Tuple[bool, str, str, List[str]]:
    """
    基于分类树、物种命名、宿主类型与噬菌体特征蛋白四维证据，核验记录是否为真实噬菌体。
    返回: (is_phage, confidence, phage_tax_group, evidence_list)
    """
    token_set = {t.strip() for t in taxonomy_tokens if t.strip()}
    evidence: List[str] = []

    # 1. 非病毒界直接判定为非噬菌体
    if "Viruses" not in token_set:
        domain = taxonomy_tokens[0] if taxonomy_tokens else "unknown"
        return False, "rejected", "Non_Virus", [f"non_viral_domain:{domain}"]

    # 2. 识别权威噬菌体分类群
    tax_group = ""
    for grp_name, grp_markers in PHAGE_TAXONOMY_GROUPS:
        if any(marker in token_set for marker in grp_markers):
            tax_group = grp_name
            evidence.append(f"taxonomy_phage_clade:{grp_name}")
            break

    # 3. 明确非噬菌体（真核/古菌病毒）且无噬菌体分类支持的直接拒绝
    blacklisted = token_set & NON_PHAGE_VIRAL_TAXA
    if blacklisted and not tax_group:
        return False, "rejected", "Non_Phage_Virus", [f"non_phage_viral_taxon:{sorted(blacklisted)[0]}"]

    # 4. 命名、宿主与功能基因证据评估
    has_phage_name = bool(PHAGE_NAME_RE.search(organism) or PHAGE_NAME_RE.search(description))
    if has_phage_name:
        evidence.append("naming_phage_keyword")

    has_prokaryotic_host = bool(host and not EUKARYOTIC_HOST_RE.search(host))
    has_eukaryotic_host = bool(host and EUKARYOTIC_HOST_RE.search(host))
    if has_prokaryotic_host:
        evidence.append("prokaryotic_host_annotated")
    elif has_eukaryotic_host and not tax_group:
        return False, "rejected", "Non_Phage_Virus", ["eukaryotic_host_annotated"]

    marker_cds_cnt = sum(1 for prod in product_texts if PHAGE_PROTEIN_EVIDENCE_RE.search(prod))
    if marker_cds_cnt > 0:
        evidence.append(f"phage_marker_genes:{marker_cds_cnt}")

    # 5. 综合判定等级
    if tax_group:
        aux_signals = int(has_phage_name) + int(has_prokaryotic_host) + int(marker_cds_cnt > 0)
        confidence = "high" if aux_signals >= 1 else "medium"
        return True, confidence, tax_group, evidence

    # 无明确已知噬菌体 ICTV 分类时，需多重辅助证据交叉证实
    aux_signals = int(has_phage_name) + int(has_prokaryotic_host) + int(marker_cds_cnt > 0)
    if has_phage_name and aux_signals >= 2:
        confidence = "high" if aux_signals == 3 else "medium"
        return True, confidence, "Unclassified_Phage", evidence

    return False, "rejected", "Unverified_Virus", evidence or ["insufficient_phage_evidence"]


def validate_single_pair(args: Tuple[str, str, str, int]) -> PhageRecordValidation:
    """校验单株噬菌体的 .fasta 与 .gbk 配对文件。"""
    accession, fasta_path_str, gbk_path_str, min_length_bp = args
    fasta_path = Path(fasta_path_str)
    gbk_path = Path(gbk_path_str)
    res = PhageRecordValidation(
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
    res.taxonomy = "; ".join(str(x) for x in (ann.get("taxonomy") or []))
    res.description = str(gb_rec.description or fa_rec.description or "")
    res.host = _extract_host(gb_rec)

    cds_items: List[PhageCDSRecord] = []
    all_products: List[str] = []
    trna_cnt = 0
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

        for attr_name, pat in KEY_MARKER_PATTERNS.items():
            if pat.search(product):
                setattr(res, attr_name, True)

    res.cds_count = sum(1 for feat in gb_rec.features if feat.type == "CDS")
    res.trna_count = trna_cnt
    res.cds_items = cds_items

    if res.cds_count == 0:
        res.errors.append("zero_cds_annotated")
        return res
    if res.translated_cds_count == 0:
        res.warnings.append("no_translated_proteins")

    tax_tokens = [str(x) for x in (ann.get("taxonomy") or [])]
    is_phage, confidence, tax_group, evidence = _assess_phage_identity(
        taxonomy_tokens=tax_tokens,
        organism=res.organism,
        description=res.description,
        host=res.host,
        product_texts=all_products,
    )
    res.is_phage = is_phage
    res.phage_confidence = confidence
    res.phage_tax_group = tax_group
    res.phage_evidence = evidence

    if not is_phage:
        res.errors.append(f"not_verified_as_phage:{tax_group}")
        return res

    res.status = "warning" if res.warnings else "passed"
    return res


def validate_dataset_parallel(
    data_dir: Path,
    min_length_bp: int = 3000,
    max_workers: Optional[int] = None,
) -> List[PhageRecordValidation]:
    """
    多核并行校验 data_dir 下全部噬菌体 fasta/gbk 数据对。
    自动预留 2 个 CPU 核心防止主机卡死。
    """
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

    logger.info(f"启动多核并行校验: 共 {len(tasks)} 株样本, 并发进程数={safe_workers} (总核心={cpu_cnt})")
    results: List[PhageRecordValidation] = []
    if safe_workers == 1 or len(tasks) < 8:
        results = [validate_single_pair(t) for t in tasks]
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=safe_workers) as pool:
            for item in pool.map(validate_single_pair, tasks, chunksize=8):
                results.append(item)

    results.sort(key=lambda x: x.accession)
    return results

