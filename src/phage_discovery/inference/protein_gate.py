# -*- coding: utf-8 -*-
"""
第二阶段轻量级蛋白功能与病毒标志基因门控验证器（Protein Verification Gate）

设计目标：
1. 仅对第一阶段 Student 候选前噬菌体区间（全基因组的 ~1%-5%）运行 Pyrodigal ORF 提取与批处理 BLASTp；
2. 区分真正噬菌体核心标志基因（Hallmark：Capsid/Terminase/Tail/Portal/Integrase/Lysin 等）、
   未表征噬菌体蛋白簇、细菌转座酶（Transposase/IS）与通用宿主辅助代谢酶（ABC transporter 等）；
3. 针对极端高 GC（>=67%）OOD 假阳性施加强蛋白证据拦截，同时对正常 GC 高置信暗物质噬菌体保留保守豁免通路。
"""
import logging
import os
import re
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..benchmark.metrics import PredictedRegion

logger = logging.getLogger("phage_discovery.inference.protein_gate")

VIRAL_CORE_HALLMARK_RE = re.compile(
    r"\b(?:capsid|coat\s+protein|minor\s+coat|major\s+coat|spike\s+protein|pilot\s+protein|"
    r"scaffolding|scaffold\s+protein|prohead|portal|terminase|terl|ters|tail|baseplate|"
    r"tape\s+measure|holin|endolysin|lysin|spanin|integrase|excisionase|recombinase|"
    r"virion|head[- ]tail|neck\s+protein|collar|sheath|connector|packaging|"
    r"maturation\s+protein|lysis\s+protein|antirepressor|repressor|prophage|"
    r"bacteriophage|phage\s+protein|phage[- ]related|zot|zonular\s+occludens|"
    r"nin[bcfg]|kil\s+protein|gam\s+protein|cro\s+protein|gp\d+)\b",
    re.IGNORECASE,
)

TRANSPOSASE_RE = re.compile(
    r"\b(?:transposase|transposon|insertion\s+sequence|is\d+\s+family|resolvase)\b",
    re.IGNORECASE,
)

GENERIC_AMG_RE = re.compile(
    r"\b(?:transporter|permease|abc\s+|dehydrogenase|reductase|oxygenase|synthase|"
    r"synthetase|kinase|transferase|hydrolase|ligase|peptidase|esterase|isomerase|"
    r"tRNA\s+ligase|ribosomal|chaperonin|groel|atpase\s+aaa|cytochrome)\b",
    re.IGNORECASE,
)


@dataclass
class ProteinGateConfig:
    """蛋白门控参数配置（仅基于生物学规则及验证集标定，可独立调优/关闭）。"""

    enabled: bool = True
    evalue: float = 1e-5
    min_qcov: float = 35.0
    high_gc_cutoff: float = 0.67
    min_non_amg_hits: int = 3
    min_non_amg_ratio: float = 0.25
    allow_dark_matter_fallback: bool = True
    dark_matter_mean_score: float = 0.93
    dark_matter_peak_score: float = 0.97
    dark_matter_min_orfs: int = 2
    dark_matter_min_coding_density: float = 0.60


@dataclass
class RegionGateResult:
    """单个候选区域的蛋白门控证据与最终裁决。"""

    region: PredictedRegion
    decision: str  # "keep" | "reject"
    tier: str
    gc_ratio: float
    region_len_bp: int
    orf_count: int
    coding_density: float
    hallmark_hits: int
    non_amg_hits: int
    transposase_hits: int
    amg_hits: int
    total_hits: int
    matched_titles_sample: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


def _gc_ratio(seq: str) -> float:
    u = seq.upper()
    if not u:
        return 0.0
    return float(u.count("G") + u.count("C")) / float(len(u))


def _predict_orfs_for_regions(
    contig_seqs: Dict[str, str],
    regions: Sequence[PredictedRegion],
) -> Tuple[List[Dict[str, Any]], List[Tuple[str, str]]]:
    """用 Pyrodigal(meta=True) 提取候选区间 ORF 蛋白序列及基础编码密度。"""
    import pyrodigal

    finder = pyrodigal.GeneFinder(meta=True)
    region_stats: List[Dict[str, Any]] = []
    orf_records: List[Tuple[str, str]] = []

    for idx, reg in enumerate(regions):
        seq = contig_seqs.get(reg.contig_id, "")
        sub_seq = seq[max(0, reg.start_bp):min(len(seq), reg.end_bp)]
        reg_len = len(sub_seq)
        gc = _gc_ratio(sub_seq)
        coding_bp = 0
        orf_cnt = 0
        if reg_len >= 200:
            genes = finder.find_genes(sub_seq.encode("ascii", errors="ignore"))
            for gi, gene in enumerate(genes):
                aa = gene.translate(include_stop=False)
                if len(aa) >= 20:
                    orf_records.append((f"r{idx}__g{gi}", aa))
                    orf_cnt += 1
                    coding_bp += abs(gene.end - gene.begin) + 1
        coding_density = min(1.0, float(coding_bp) / float(max(1, reg_len)))
        region_stats.append(
            {
                "region_idx": idx,
                "gc_ratio": gc,
                "region_len_bp": reg_len,
                "orf_count": orf_cnt,
                "coding_density": round(coding_density, 4),
            }
        )
    return region_stats, orf_records


def _resolve_blast_db(blast_db: Path) -> Tuple[Path, str]:
    p = Path(blast_db).resolve()
    return p.parent, p.name


def _has_blast_db_files(blast_db: Path) -> bool:
    parent, name = _resolve_blast_db(blast_db)
    for ext in (".pin", ".pal", ".00.pin"):
        if (parent / f"{name}{ext}").exists():
            return True
    return False


def _run_batch_blastp(
    orf_records: Sequence[Tuple[str, str]],
    blast_db: Path,
    *,
    blastp_bin: str = "blastp",
    evalue: float = 1e-5,
    min_qcov: float = 35.0,
    threads: Optional[int] = None,
) -> Dict[str, Tuple[float, str]]:
    """
    一次性批处理全部候选区间 ORF 的本地 BLASTp 检索。
    关键约束：使用 cwd=db_dir + 相对 db_name，规避 Windows BLAST+ 路径含空格退出码 3 问题。
    """
    if not orf_records:
        return {}

    db_dir, db_name = _resolve_blast_db(blast_db)
    cpu_cnt = os.cpu_count() or 4
    n_threads = threads if threads is not None else max(1, cpu_cnt - 2)

    best_hits: Dict[str, Tuple[float, str]] = {}
    with tempfile.TemporaryDirectory(prefix="phage_pgate_") as tmpdir:
        tmp_root = Path(tmpdir)
        faa_path = tmp_root / "orfs.faa"
        out_path = tmp_root / "blastp_hits.tsv"

        lines = [f">{qid}\n{aa}\n" for qid, aa in orf_records]
        faa_path.write_text("".join(lines), encoding="utf-8")

        cmd = [
            blastp_bin,
            "-query",
            str(faa_path),
            "-db",
            db_name,
            "-outfmt",
            "6 qseqid sseqid pident length qcovs evalue bitscore stitle",
            "-evalue",
            str(evalue),
            "-qcov_hsp_perc",
            str(min_qcov),
            "-max_target_seqs",
            "3",
            "-num_threads",
            str(n_threads),
            "-out",
            str(out_path),
        ]
        proc = subprocess.run(
            cmd,
            cwd=str(db_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"blastp 执行失败 (exit={proc.returncode}): {proc.stderr.strip()}")

        if out_path.exists():
            for raw_line in out_path.read_text(encoding="utf-8", errors="replace").splitlines():
                if not raw_line.strip():
                    continue
                parts = raw_line.split("\t", 7)
                if len(parts) < 8:
                    continue
                qid = parts[0].strip()
                try:
                    bitscore = float(parts[6])
                except ValueError:
                    continue
                stitle = parts[7].strip()
                prev = best_hits.get(qid)
                if prev is None or bitscore > prev[0]:
                    best_hits[qid] = (bitscore, stitle)
    return best_hits


def _classify_hit_title(title: str) -> str:
    """将命中的蛋白注释分为 hallmark / transposase / generic_amg / non_amg_phage 四类。"""
    if TRANSPOSASE_RE.search(title) and not VIRAL_CORE_HALLMARK_RE.search(title):
        return "transposase"
    if VIRAL_CORE_HALLMARK_RE.search(title):
        return "hallmark"
    if GENERIC_AMG_RE.search(title):
        return "generic_amg"
    return "non_amg_phage"


def _decide_single_region(
    reg: PredictedRegion,
    stat: Dict[str, Any],
    hit_titles: Sequence[str],
    cfg: ProteinGateConfig,
) -> RegionGateResult:
    gc = float(stat["gc_ratio"])
    reg_len = int(stat["region_len_bp"])
    orf_cnt = int(stat["orf_count"])
    coding_density = float(stat["coding_density"])

    hallmark = 0
    transposase = 0
    amg = 0
    non_amg_other = 0
    for title in hit_titles:
        cls = _classify_hit_title(title)
        if cls == "hallmark":
            hallmark += 1
        elif cls == "transposase":
            transposase += 1
        elif cls == "generic_amg":
            amg += 1
        else:
            non_amg_other += 1

    non_amg_hits = hallmark + non_amg_other
    total_hits = len(hit_titles)
    is_high_gc = gc >= cfg.high_gc_cutoff

    decision = "reject"
    tier = "rejected_no_evidence"

    # 1. 转座酶孤岛拦截（无病毒核心基因且被转座酶主导的短区域）
    if hallmark == 0 and transposase >= 1 and non_amg_hits <= 1 and reg_len < 12000:
        decision = "reject"
        tier = "rejected_transposase_dom"
    # 2. Tier 1: 核心噬菌体标志基因确证
    elif hallmark >= 1 and (not is_high_gc or non_amg_hits >= 2 or reg_len < 8000):
        decision = "keep"
        tier = "hallmark_confirmed"
    # 3. Tier 2: 多条非 AMG 噬菌体蛋白支持（包括噬菌体未表征/假定蛋白簇）
    elif non_amg_hits >= cfg.min_non_amg_hits or (
        orf_cnt >= 3 and non_amg_hits >= 2 and (float(non_amg_hits) / float(orf_cnt)) >= cfg.min_non_amg_ratio
    ):
        decision = "keep"
        tier = "phage_cluster_confirmed"
    # 4. Tier 3: 极端高 GC OOD 区域缺少强蛋白证据时拒绝
    elif is_high_gc:
        decision = "reject"
        tier = "rejected_high_gc_no_evidence"
    # 5. Tier 4: 正常 GC 暗物质/退化碎片保守保留通路（高均值+高密度+无明显矛盾证据）
    elif (
        cfg.allow_dark_matter_fallback
        and total_hits == 0
        and reg.mean_score >= cfg.dark_matter_mean_score
        and reg.peak_score >= cfg.dark_matter_peak_score
        and orf_cnt >= cfg.dark_matter_min_orfs
        and coding_density >= cfg.dark_matter_min_coding_density
    ):
        decision = "keep"
        tier = "dark_matter_fallback"

    return RegionGateResult(
        region=reg,
        decision=decision,
        tier=tier,
        gc_ratio=round(gc, 4),
        region_len_bp=reg_len,
        orf_count=orf_cnt,
        coding_density=coding_density,
        hallmark_hits=hallmark,
        non_amg_hits=non_amg_hits,
        transposase_hits=transposase,
        amg_hits=amg,
        total_hits=total_hits,
        matched_titles_sample=list(hit_titles[:5]),
    )


def evaluate_regions_with_protein_gate(
    contig_seqs: Dict[str, str],
    regions: Sequence[PredictedRegion],
    blast_db: Optional[Path] = None,
    *,
    config: Optional[ProteinGateConfig] = None,
    blastp_bin: str = "blastp",
    threads: Optional[int] = None,
    hit_fetcher: Optional[Callable[[Sequence[Tuple[str, str]]], Dict[str, Tuple[float, str]]]] = None,
) -> Tuple[List[PredictedRegion], List[RegionGateResult]]:
    """
    对第一阶段候选预测区域执行蛋白门控验证，返回 (通过门控的区域列表, 全量裁决详情列表)。
    hit_fetcher 仅用于单元测试注入自定义蛋白比对桩实现。
    """
    cfg = config or ProteinGateConfig()
    if not regions:
        return [], []

    stats, orf_records = _predict_orfs_for_regions(contig_seqs, regions)
    if not cfg.enabled:
        passthrough = [
            RegionGateResult(
                region=reg,
                decision="keep",
                tier="gate_disabled",
                gc_ratio=round(float(st["gc_ratio"]), 4),
                region_len_bp=int(st["region_len_bp"]),
                orf_count=int(st["orf_count"]),
                coding_density=float(st["coding_density"]),
                hallmark_hits=0,
                non_amg_hits=0,
                transposase_hits=0,
                amg_hits=0,
                total_hits=0,
            )
            for reg, st in zip(regions, stats)
        ]
        return list(regions), passthrough

    best_hits: Dict[str, Tuple[float, str]] = {}
    if hit_fetcher is not None:
        best_hits = hit_fetcher(orf_records)
    elif blast_db is not None and _has_blast_db_files(Path(blast_db)):
        best_hits = _run_batch_blastp(
            orf_records,
            Path(blast_db),
            blastp_bin=blastp_bin,
            evalue=cfg.evalue,
            min_qcov=cfg.min_qcov,
            threads=threads,
        )
    else:
        logger.warning("未提供有效蛋白 BLAST 库，蛋白门控降级为透传模式以防止无库误删。")
        passthrough = [
            RegionGateResult(
                region=reg,
                decision="keep",
                tier="no_blast_db_passthrough",
                gc_ratio=round(float(st["gc_ratio"]), 4),
                region_len_bp=int(st["region_len_bp"]),
                orf_count=int(st["orf_count"]),
                coding_density=float(st["coding_density"]),
                hallmark_hits=0,
                non_amg_hits=0,
                transposase_hits=0,
                amg_hits=0,
                total_hits=0,
            )
            for reg, st in zip(regions, stats)
        ]
        return list(regions), passthrough

    hits_by_region: Dict[int, List[str]] = {i: [] for i in range(len(regions))}
    for qid, (_, title) in best_hits.items():
        if "__" in qid and qid.startswith("r"):
            try:
                ridx = int(qid[1:].split("__", 1)[0])
                hits_by_region[ridx].append(title)
            except ValueError:
                continue

    results: List[RegionGateResult] = []
    kept: List[PredictedRegion] = []
    for idx, (reg, st) in enumerate(zip(regions, stats)):
        res = _decide_single_region(reg, st, hits_by_region.get(idx, []), cfg)
        results.append(res)
        if res.decision == "keep":
            kept.append(reg)

    return kept, results

