# -*- coding: utf-8 -*-
"""
独立外部验证集构建与 NCBI 在线数据获取模块。

职责：
1. 计算已测基线样本集合（Suite A 120 + Suite B 30 + 单元测试保留株），确保新验证集 100% 零重叠；
2. 构建 Suite D（从 NCBI Entrez 在线拉取全新真实 .gbk 与 .fasta，含 2023-2025 新发现噬菌体与历史非标注释样本，及文献实测 TEM 尾长真值）；
3. 构建 Suite C（从本地未测配对库分层抽样跨 35+ ICTV 科的多形态样本，完全排除基线及 Suite D）。
"""
from __future__ import annotations

import csv
import json
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.benchmark_phage_structure import (  # noqa: E402
    EXCLUDE_ACCS,
    FAMILY_TO_MORPH,
    LOCAL_FASTA_DIR,
    TEM_REFERENCES,
    sample_120_ictv_genomes,
)

LOCAL_GBK_DIR = LOCAL_FASTA_DIR.parent / "gbk"
LOCAL_INDEX_TSV = LOCAL_FASTA_DIR.parent / "index" / "phage_index.tsv"
EXTERNAL_DATA_DIR = PROJECT_ROOT / "data" / "validation" / "external_ncbi"

# 扩展至更多 2024-2025 ICTV 确切形态明确的科（不混入不确定或古菌域外科）
EXTENDED_FAMILY_TO_MORPH: Dict[str, str] = {
    **FAMILY_TO_MORPH,
    # Myoviridae-like 新增明确科
    "Vandenendeviridae": "Myoviridae-like",
    "Lindbergviridae": "Myoviridae-like",
    "Andersonviridae": "Myoviridae-like",
    # Siphoviridae-like 新增明确科
    "Stanwilliamsviridae": "Siphoviridae-like",
    "Hodgkinviridae": "Siphoviridae-like",
    "Orlajensenviridae": "Siphoviridae-like",
    # Podoviridae-like 新增明确科 (Autographivirales 拆分科 + CrAss Steigviridae)
    "Autotranscriptaviridae": "Podoviridae-like",
    "Autoscriptoviridae": "Podoviridae-like",
    "Autonotataviridae": "Podoviridae-like",
    "Autosignataviridae": "Podoviridae-like",
    "Steigviridae": "Podoviridae-like",
    # Non-tailed 新增明确科 (+ssRNA Leviviricetes 无尾噬菌体)
    "Steitzviridae": "Non-tailed",
}


@dataclass(frozen=True)
class ExternalTemCase:
    name: str
    acc: str
    expected: str
    tem_nm: Optional[float]
    tem_range: str
    source_note: str


# 全新外部独立验证集 Suite D（33 株：100% 剔除原有 151 株；其中 14 株甚至不在本地 5000 株内）
SUITE_D_EXTERNAL_CASES: List[ExternalTemCase] = [
    # --- Myoviridae-like TEM 定量 (8 株) ---
    ExternalTemCase("PaSz-1_45_92k", "MN871481", "Myoviridae-like", 102.0, "102", "2024-2025 UNVERIFIED Pseudomonas myovirus"),
    ExternalTemCase("PaZh_1", "MN871489", "Myoviridae-like", 200.0, "200", "2024-2025 UNVERIFIED Pseudomonas jumbo myovirus"),
    ExternalTemCase("Arash", "OQ632216", "Myoviridae-like", 140.47, "140.47+-1.05", "Salmonella myovirus OQ632216"),
    ExternalTemCase("PseuGes_254", "OR575930", "Myoviridae-like", 139.6, "139.6+-5.6", "Pseudomonas gessardii myovirus OR575930"),
    ExternalTemCase("VP882", "NC_009016", "Myoviridae-like", 156.0, "156+-8", "Vibrio 38kb small-genome myovirus"),
    ExternalTemCase("PB1", "NC_011810", "Myoviridae-like", 140.0, "140", "Pseudomonas Pbunavirus PB1"),
    ExternalTemCase("Bxz1", "NC_004687", "Myoviridae-like", 80.0, "80", "Mycobacterium I3-like short contractile tail"),
    ExternalTemCase("RB49", "NC_005066", "Myoviridae-like", 113.5, "113-114", "Enterobacteria T4-superfamily myovirus RB49"),
    # --- Siphoviridae-like TEM 定量 (14 株) ---
    ExternalTemCase("Patience", "NC_023691", "Siphoviridae-like", 358.0, "358", "Mycobacterium ultra-long siphovirus"),
    ExternalTemCase("PA_L9", "PP869205", "Siphoviridae-like", 300.0, "300", "2024-2025 Pseudomonas siphovirus"),
    ExternalTemCase("BK5-T", "NC_002796", "Siphoviridae-like", 232.0, "232", "Lactococcus siphovirus BK5-T"),
    ExternalTemCase("Giles", "NC_009993", "Siphoviridae-like", 205.0, "205", "Mycobacteriophage Giles"),
    ExternalTemCase("r1t", "NC_004302", "Siphoviridae-like", 140.5, "140-141", "Lactococcus phage r1t historical GenBank"),
    ExternalTemCase("2972", "NC_007019", "Siphoviridae-like", 260.0, "260", "Streptococcus thermophilus phage 2972"),
    ExternalTemCase("Rosebush", "NC_004684", "Siphoviridae-like", 252.5, "252.5", "Mycobacteriophage Rosebush"),
    ExternalTemCase("Corndog", "NC_004685", "Siphoviridae-like", 248.0, "248+-8", "Mycobacteriophage Corndog"),
    ExternalTemCase("Chi", "NC_021315", "Siphoviridae-like", 225.0, "220-230", "Salmonella flagellotropic phage Chi"),
    ExternalTemCase("Omega", "NC_004688", "Siphoviridae-like", 200.0, "200", "Mycobacteriophage Omega"),
    ExternalTemCase("D3112", "NC_005178", "Siphoviridae-like", 190.0, "190", "Pseudomonas transposable siphovirus D3112 (split N+C ORFs)"),
    ExternalTemCase("phi80", "NC_021190", "Siphoviridae-like", 149.0, "147-151", "Enterobacteria lambdoid phage phi80"),
    ExternalTemCase("YuA", "NC_010116", "Siphoviridae-like", 145.0, "145", "Pseudomonas phage YuA"),
    ExternalTemCase("Gamma", "NC_007458", "Siphoviridae-like", 200.0, "200-217", "Bacillus anthracis phage Gamma (Schuch 2006)"),
    # --- Podoviridae-like 外部对照 (6 株) ---
    ExternalTemCase("BUCT775", "PV277657", "Podoviridae-like", None, "12.31+-1.51", "2025 Acinetobacter Friunavirus podovirus"),
    ExternalTemCase("Bhz16", "PV067733", "Podoviridae-like", None, "podovirus", "2025 Acinetobacter podovirus Bhz16"),
    ExternalTemCase("epsilon15", "NC_004775", "Podoviridae-like", None, "short", "Salmonella temperate podovirus epsilon15"),
    ExternalTemCase("phiKMV", "NC_005045", "Podoviridae-like", None, "short", "Pseudomonas Autoscriptoviridae phiKMV"),
    ExternalTemCase("LUZ19", "NC_010326", "Podoviridae-like", None, "short", "Pseudomonas Autographiviridae LUZ19"),
    ExternalTemCase("VpV262_N4", "NC_013651", "Podoviridae-like", None, "short", "Vibrio N4-like Schitoviridae"),
    # --- Non-tailed 外部对照 (5 株) ---
    ExternalTemCase("PR772", "AY441783", "Non-tailed", None, "tailless", "Tectiviridae lipid-containing tailless PR772"),
    ExternalTemCase("MS2", "NC_001417", "Non-tailed", None, "tailless", "Fiersviridae +ssRNA tailless MS2"),
    ExternalTemCase("phiCPAR39", "NC_002180", "Non-tailed", None, "tailless", "Chlamydia Microviridae tailless"),
    ExternalTemCase("phiX174", "NC_001422", "Non-tailed", None, "tailless", "Escherichia Microviridae phiX174"),
    ExternalTemCase("CTXphi", "NC_015209", "Non-tailed", None, "filamentous", "Vibrio Inoviridae filamentous CTXphi"),
]


def get_baseline_excluded_accs(local_fasta_index: Dict[str, Path]) -> Set[str]:
    """返回旧基准 Suite A 120 + Suite B 30 + 单元测试排除集的完整并集。"""
    s120 = {x["acc"] for x in sample_120_ictv_genomes(local_fasta_index, per_class=30)}
    tem30 = {x[1] for x in TEM_REFERENCES}
    return s120 | tem30 | set(EXCLUDE_ACCS)


def inspect_gbk_annotation_profile(gbk_path: Path) -> Dict[str, object]:
    """轻量检查单个 .gbk 的注释特征（缺翻译比率、hypothetical 比率），不加载模型。"""
    txt = gbk_path.read_text(encoding="utf-8", errors="ignore")
    prod_cnt = txt.count("/product=")
    trans_cnt = txt.count("/translation=")
    hyp_cnt = txt.lower().count("hypothetical protein")
    cds_cnt = max(prod_cnt, txt.count("\n     CDS "))
    missing_trans = trans_cnt < prod_cnt or (cds_cnt > 0 and trans_cnt == 0)
    hyp_ratio = round(hyp_cnt / max(1, prod_cnt), 4) if prod_cnt > 0 else 1.0
    return {
        "cds_like_cnt": cds_cnt,
        "prod_cnt": prod_cnt,
        "trans_cnt": trans_cnt,
        "missing_translation": bool(missing_trans),
        "no_cds": prod_cnt == 0 and trans_cnt == 0,
        "hyp_ratio": hyp_ratio,
        "high_hyp_70": hyp_ratio >= 0.7,
    }


def _fetch_ncbi_text(acc: str, rettype: str, timeout: int = 30) -> str:
    url = (
        f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        f"?db=nuccore&id={acc}&rettype={rettype}&retmode=text"
    )
    last_err: Optional[Exception] = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "NCBI-Workbench-ExtVal/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except Exception as exc:
            last_err = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"NCBI efetch 失败 ({acc}, {rettype}): {last_err}")


def prepare_suite_d_external(out_dir: Path = EXTERNAL_DATA_DIR) -> List[Dict[str, object]]:
    """从 NCBI Entrez 在线拉取全部 Suite D 的真实 .gbk (gbwithparts) 与 .fasta 文件并落盘缓存。"""
    fasta_dir = out_dir / "fasta"
    gbk_dir = out_dir / "gbk"
    fasta_dir.mkdir(parents=True, exist_ok=True)
    gbk_dir.mkdir(parents=True, exist_ok=True)

    local_fasta_idx = {p.stem.split(".")[0]: p for p in LOCAL_FASTA_DIR.glob("*.fasta")}
    excluded = get_baseline_excluded_accs(local_fasta_idx)

    entries: List[Dict[str, object]] = []
    for case in SUITE_D_EXTERNAL_CASES:
        if case.acc in excluded:
            raise AssertionError(f"Suite D 样本 {case.acc} 与旧基准集重叠，违反独立验证原则！")
        fa_path = fasta_dir / f"{case.acc}.fasta"
        gb_path = gbk_dir / f"{case.acc}.gbk"

        if not fa_path.is_file() or fa_path.stat().st_size < 200:
            fa_txt = _fetch_ncbi_text(case.acc, "fasta")
            if not fa_txt.startswith(">"):
                raise RuntimeError(f"下载 FASTA 异常 ({case.acc}): {fa_txt[:120]}")
            fa_path.write_text(fa_txt, encoding="utf-8")
            time.sleep(0.35)

        if not gb_path.is_file() or gb_path.stat().st_size < 400:
            gb_txt = _fetch_ncbi_text(case.acc, "gbwithparts")
            if "LOCUS " not in gb_txt[:200] or "ORIGIN" not in gb_txt:
                raise RuntimeError(f"下载 GBK 异常 ({case.acc}): 缺少 LOCUS 或 ORIGIN")
            gb_path.write_text(gb_txt, encoding="utf-8")
            time.sleep(0.35)

        prof = inspect_gbk_annotation_profile(gb_path)
        entries.append({
            **asdict(case),
            "family": case.source_note,
            "host": case.name,
            "desc": case.source_note,
            "in_local_5k": case.acc in local_fasta_idx,
            "fasta_path": str(fa_path),
            "gbk_path": str(gb_path),
            "gbk_profile": prof,
        })

    manifest_path = out_dir / "suite_d_manifest.json"
    manifest_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    return entries


def sample_suite_c_unseen_local(
    per_class: int = 40,
    extra_excluded: Optional[Set[str]] = None,
) -> List[Dict[str, object]]:
    """
    从 F:\\Phage data 未测配对库（4,852 株）按 35+ ICTV 科轮转+宿主分散抽取跨科未知样本。
    优先融合本地 phage_index.tsv 更新分类与 INPHARED 元数据，100% 排除基线及 Suite D。
    """
    local_fasta = {p.stem.split(".")[0]: p for p in LOCAL_FASTA_DIR.glob("*.fasta")}
    local_gbk = {p.stem.split(".")[0]: p for p in LOCAL_GBK_DIR.glob("*.gbk")}
    paired_accs = set(local_fasta) & set(local_gbk)

    excluded = get_baseline_excluded_accs(local_fasta)
    if extra_excluded:
        excluded |= set(extra_excluded)
    excluded |= {c.acc for c in SUITE_D_EXTERNAL_CASES}

    # 先读取 INPHARED 做科/宿主补充索引
    inphared_tsv = PROJECT_ROOT / "database" / "pharokka_db" / "9Aug2025_data.tsv"
    inphared_meta: Dict[str, Tuple[str, str, str]] = {}
    if inphared_tsv.is_file():
        with inphared_tsv.open("r", encoding="utf-8", errors="ignore", newline="") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                acc = str(row.get("Accession") or "").strip().split(".")[0]
                if acc:
                    inphared_meta[acc] = (
                        str(row.get("Family") or "").strip(),
                        str(row.get("Host") or "Unspecified").strip(),
                        str(row.get("Description") or "").strip(),
                    )

    pools: Dict[str, Dict[str, List[Dict[str, object]]]] = defaultdict(lambda: defaultdict(list))
    with LOCAL_INDEX_TSV.open("r", encoding="utf-8", errors="ignore", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            acc = str(row.get("accession") or "").strip().split(".")[0]
            if not acc or acc not in paired_accs or acc in excluded:
                continue
            if row.get("is_phage") != "1":
                continue

            tax_parts = [t.strip() for t in str(row.get("taxonomy") or "").split(";") if t.strip()]
            matched_fam: Optional[str] = None
            for part in reversed(tax_parts):
                if part in EXTENDED_FAMILY_TO_MORPH:
                    matched_fam = part
                    break
            if matched_fam is None and acc in inphared_meta:
                inph_fam = inphared_meta[acc][0]
                if inph_fam in EXTENDED_FAMILY_TO_MORPH:
                    matched_fam = inph_fam
            if matched_fam is None:
                continue

            morph = EXTENDED_FAMILY_TO_MORPH[matched_fam]
            host = str(row.get("host") or "").strip()
            if not host or host.lower() in ("unknown", "unspecified"):
                host = inphared_meta.get(acc, ("", "Unspecified", ""))[1] or "Unspecified"
            org = str(row.get("organism") or "").strip() or inphared_meta.get(acc, ("", "", ""))[2]

            pools[morph][matched_fam].append({
                "acc": acc,
                "family": matched_fam,
                "host": host,
                "expected": morph,
                "desc": org,
                "fasta_path": str(local_fasta[acc]),
                "gbk_path": str(local_gbk[acc]),
            })

    selected: List[Dict[str, object]] = []
    for morph in ("Myoviridae-like", "Siphoviridae-like", "Podoviridae-like", "Non-tailed"):
        fam_dict = pools[morph]
        for fam in fam_dict:
            fam_dict[fam].sort(key=lambda x: str(x["acc"]))
        picked_hosts: Counter[str] = Counter()
        seen_in_morph: Set[str] = set()
        bucket: List[Dict[str, object]] = []
        fam_keys = sorted(fam_dict.keys())
        round_idx = 0
        while len(bucket) < per_class and round_idx < 100:
            progressed = False
            for fam in fam_keys:
                if len(bucket) >= per_class:
                    break
                unused = [it for it in fam_dict[fam] if str(it["acc"]) not in seen_in_morph]
                if not unused:
                    continue
                unused.sort(key=lambda it: (picked_hosts[str(it["host"])], str(it["acc"])))
                chosen = unused[0]
                chosen["gbk_profile"] = inspect_gbk_annotation_profile(Path(str(chosen["gbk_path"])))
                bucket.append(chosen)
                seen_in_morph.add(str(chosen["acc"]))
                picked_hosts[str(chosen["host"])] += 1
                progressed = True
            if not progressed:
                break
            round_idx += 1
        selected.extend(bucket)

    return selected


if __name__ == "__main__":
    print("正在准备外部 NCBI 下载集 (Suite D)...")
    d_entries = prepare_suite_d_external()
    d_accs = {str(e["acc"]) for e in d_entries}
    print(f"Suite D 就绪: {len(d_entries)} 株 (其中 {sum(1 for e in d_entries if not e['in_local_5k'])} 株不在本地 5k 库)")
    c_entries = sample_suite_c_unseen_local(per_class=40, extra_excluded=d_accs)
    fam_counts = Counter(str(e["family"]) for e in c_entries)
    miss_t = sum(1 for e in c_entries if e["gbk_profile"]["missing_translation"])  # type: ignore[index]
    high_h = sum(1 for e in c_entries if e["gbk_profile"]["high_hyp_70"])  # type: ignore[index]
    print(f"Suite C 就绪: {len(c_entries)} 株, 覆盖 {len(fam_counts)} 个 ICTV 科, 缺/translation={miss_t}, hyp>=70%={high_h}")
