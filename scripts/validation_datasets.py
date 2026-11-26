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
import hashlib
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
    load_tem_truth_records,
    sample_120_ictv_genomes,
)

LOCAL_GBK_DIR = LOCAL_FASTA_DIR.parent / "gbk"
LOCAL_INDEX_TSV = LOCAL_FASTA_DIR.parent / "index" / "phage_index.tsv"
EXTERNAL_DATA_DIR = PROJECT_ROOT / "data" / "validation" / "external_ncbi"
SUITE_E_DATA_DIR = PROJECT_ROOT / "data" / "validation" / "suite_e_frozen"
SUITE_E_FROZEN_MANIFEST = PROJECT_ROOT / "tests" / "fixtures" / "phage_structure" / "suite_e_manifest.json"

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
    doi: str = ""
    verification_status: str = "unverified"
    tem_state: str = "unknown"
    includes_baseplate: str = "unknown"
    tem_method: str = "TEM"


def _build_suite_d_external_cases() -> List[ExternalTemCase]:
    """合并 tem_truth.tsv 中的 Suite D 22 株 TEM 样本与 11 株短尾/无尾外部对照。"""
    cases: List[ExternalTemCase] = [
        ExternalTemCase(
            name=rec.name,
            acc=rec.accession,
            expected=rec.morphotype,
            tem_nm=rec.tem_nm,
            tem_range=rec.tem_range,
            source_note=rec.notes,
            doi=rec.doi,
            verification_status=rec.verification_status,
            tem_state=rec.state,
            includes_baseplate=rec.includes_baseplate,
            tem_method=rec.method,
        )
        for rec in load_tem_truth_records(suite="suite_d")
    ]
    non_tem_controls = [
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
    cases.extend(non_tem_controls)
    return cases


# 全新外部独立验证集 Suite D（33 株：100% 剔除原有 151 株；其中 14 株甚至不在本地 5000 株内）
SUITE_D_EXTERNAL_CASES: List[ExternalTemCase] = _build_suite_d_external_cases()


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


# 2025/08/10 INPHARED 发布日之后 NCBI 新公开的跨科完整基因组（Suite E 外部补充，24 株）
# 格式: (name, acc, family, expected, source_note)
SUITE_E_POST_2025_EXTERNAL: List[Tuple[str, str, str, str, str]] = [
    # Myoviridae-like (6 株 / 6 科)
    ("ELT2", "PQ469686", "Straboviridae", "Myoviridae-like", "Post-2025/08 Escherichia Straboviridae"),
    ("Romulus", "PV821423", "Herelleviridae", "Myoviridae-like", "Post-2025/08 Staphylococcus Herelleviridae"),
    ("PhiBP82.2", "PX400618", "Peduoviridae", "Myoviridae-like", "Post-2025/08 Burkholderia Peduoviridae"),
    ("LL-5504721-AH", "PX277138", "Vandenendeviridae", "Myoviridae-like", "Post-2025/08 Pseudomonas Vandenendeviridae"),
    ("E2005-A", "PX277137", "Lindbergviridae", "Myoviridae-like", "Post-2025/08 Pseudomonas Lindbergviridae"),
    ("vB_CECAV_034", "PX411236", "Ackermannviridae", "Myoviridae-like", "Post-2025/08 Salmonella Ackermannviridae"),
    # Siphoviridae-like (6 株 / 5 科 6 宿主)
    ("KSP7", "PQ564757", "Demerecviridae", "Siphoviridae-like", "Post-2025/08 Salmonella Demerecviridae"),
    ("vB_Kpn9997-EKp3", "QB005391", "Drexlerviridae", "Siphoviridae-like", "Post-2025/08 Klebsiella Drexlerviridae"),
    ("PA14_MA16", "PZ585225", "Mesyanzhinovviridae", "Siphoviridae-like", "Post-2025/08 Pseudomonas Mesyanzhinovviridae"),
    ("P09", "PX138300", "Aliceevansviridae", "Siphoviridae-like", "Post-2025/08 Streptococcus Aliceevansviridae"),
    ("Odze", "PZ295849", "Casjensviridae", "Siphoviridae-like", "Post-2025/08 Aeromonas Casjensviridae"),
    ("BCVI_Sma-b24phi", "PX828564", "Casjensviridae", "Siphoviridae-like", "Post-2025/08 Stenotrophomonas Casjensviridae"),
    # Podoviridae-like (6 株 / 6 科 5 宿主)
    ("UroKP46", "QB184940", "Autotranscriptaviridae", "Podoviridae-like", "Post-2025/08 Klebsiella Autotranscriptaviridae"),
    ("ZamKleb01", "OZ562183", "Schitoviridae", "Podoviridae-like", "Post-2025/08 Klebsiella Schitoviridae"),
    ("SA53-CTH4", "PZ593363", "Rountreeviridae", "Podoviridae-like", "Post-2025/08 Staphylococcus Rountreeviridae"),
    ("P71S", "PX404141", "Zobellviridae", "Podoviridae-like", "Post-2025/08 Pseudomonas Zobellviridae"),
    ("GH_01", "PX974340", "Salasmaviridae", "Podoviridae-like", "Post-2025/08 Bacillus Salasmaviridae"),
    ("PhiCP17-i", "PV983592", "Guelinviridae", "Podoviridae-like", "Post-2025/08 Clostridium Guelinviridae"),
    # Non-tailed (6 株 / 4 演化支)
    ("RG2", "PX216439", "Inoviridae", "Non-tailed", "Post-2025/08 Xanthomonas Inoviridae"),
    ("Ino_60253", "PX433842", "Inoviridae", "Non-tailed", "Post-2025/08 UNVERIFIED Inoviridae"),
    ("Thayendanegea", "PZ531164", "Eubullaviridae", "Non-tailed", "Post-2025/08 Salmonella Microviricetes"),
    ("PRD1-C1", "PX306536", "Tectiviridae", "Non-tailed", "Post-2025/08 Escherichia Alphatectivirus"),
    ("ZRIMUP76", "PZ201852", "Tectiviridae", "Non-tailed", "Post-2025/08 Streptomyces Deltatectivirus"),
    ("MAG_Levivir_03", "PZ823764", "Fiersviridae", "Non-tailed", "Post-2025/08 MAG +ssRNA Fiersviridae"),
]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _sample_unseen_local_stratified(
    per_class: int,
    *,
    excluded_accs: Set[str],
) -> List[Dict[str, object]]:
    """
    从本地配对库（PHAGE_DATA_ROOT）中按扩展 ICTV 科轮转 + 宿主分散抽取分层未测样本，
    严格保证与 excluded_accs 零交集。
    """
    local_fasta = {p.stem.split(".")[0]: p for p in LOCAL_FASTA_DIR.glob("*.fasta")}
    local_gbk = {p.stem.split(".")[0]: p for p in LOCAL_GBK_DIR.glob("*.gbk")}
    paired_accs = set(local_fasta) & set(local_gbk)

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
            if not acc or acc not in paired_accs or acc in excluded_accs:
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


def sample_suite_c_unseen_local(
    per_class: int = 40,
    extra_excluded: Optional[Set[str]] = None,
) -> List[Dict[str, object]]:
    """
    构建调参集 Suite C（每形态 40 株），100% 排除基线及 Suite D（不排除后续 Suite E，保持 C 可复现一致）。
    """
    local_fasta = {p.stem.split(".")[0]: p for p in LOCAL_FASTA_DIR.glob("*.fasta")}
    excluded = get_baseline_excluded_accs(local_fasta)
    if extra_excluded:
        excluded |= set(extra_excluded)
    excluded |= {c.acc for c in SUITE_D_EXTERNAL_CASES}
    return _sample_unseen_local_stratified(per_class=per_class, excluded_accs=excluded)


def _download_ncbi_pair(acc: str, fasta_dir: Path, gbk_dir: Path) -> Tuple[Path, Path]:
    fa_path = fasta_dir / f"{acc}.fasta"
    gb_path = gbk_dir / f"{acc}.gbk"
    if not fa_path.is_file() or fa_path.stat().st_size < 200:
        fa_txt = _fetch_ncbi_text(acc, "fasta")
        if not fa_txt.startswith(">"):
            raise RuntimeError(f"下载 FASTA 异常 ({acc}): {fa_txt[:120]}")
        fa_path.write_text(fa_txt, encoding="utf-8")
        time.sleep(0.35)
    if not gb_path.is_file() or gb_path.stat().st_size < 400:
        gb_txt = _fetch_ncbi_text(acc, "gbwithparts")
        if "LOCUS " not in gb_txt[:200] or "ORIGIN" not in gb_txt:
            raise RuntimeError(f"下载 GBK 异常 ({acc}): 缺少 LOCUS 或 ORIGIN")
        gb_path.write_text(gb_txt, encoding="utf-8")
        time.sleep(0.35)
    return fa_path, gb_path


def build_and_freeze_suite_e(
    *,
    local_per_class: int = 50,
    manifest_path: Path = SUITE_E_FROZEN_MANIFEST,
    external_dir: Path = SUITE_E_DATA_DIR,
) -> List[Dict[str, object]]:
    """
    构建并永久冻结纯粹盲测集 Suite E（本地每形态 50 株 + 24 株 2025/08 后 NCBI 新株）。
    若冻结清单已存在，则直接按清单加载并核验零重叠断言与文件 SHA256，绝不重新抽样改动名单。
    """
    local_fasta = {p.stem.split(".")[0]: p for p in LOCAL_FASTA_DIR.glob("*.fasta")}
    local_gbk = {p.stem.split(".")[0]: p for p in LOCAL_GBK_DIR.glob("*.gbk")}

    # 全量先前已用集合 = Suite A(120) + Suite B(30) + 单元测试排除 + Suite D(33) + Suite C(160)
    suite_d_accs = {c.acc for c in SUITE_D_EXTERNAL_CASES}
    suite_c_accs = {str(x["acc"]) for x in sample_suite_c_unseen_local(per_class=40, extra_excluded=suite_d_accs)}
    all_prior_excluded = get_baseline_excluded_accs(local_fasta) | suite_d_accs | suite_c_accs

    fasta_ext_dir = external_dir / "fasta"
    gbk_ext_dir = external_dir / "gbk"
    fasta_ext_dir.mkdir(parents=True, exist_ok=True)
    gbk_ext_dir.mkdir(parents=True, exist_ok=True)

    if manifest_path.is_file():
        frozen = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries: List[Dict[str, object]] = []
        frozen_accs: Set[str] = set()
        for rec in frozen["entries"]:
            acc = str(rec["acc"])
            frozen_accs.add(acc)
            if rec["origin"] == "ncbi_post_202508":
                fa_p, gb_p = _download_ncbi_pair(acc, fasta_ext_dir, gbk_ext_dir)
            else:
                if acc not in local_fasta or acc not in local_gbk:
                    raise FileNotFoundError(f"冻结清单本地株缺失: {acc}")
                fa_p, gb_p = local_fasta[acc], local_gbk[acc]
            if _sha256_file(fa_p) != rec["fasta_sha256"] or _sha256_file(gb_p) != rec["gbk_sha256"]:
                raise AssertionError(f"Suite E 文件 SHA256 哈希不一致 ({acc})，冻结集合已被改动！")
            entries.append({
                **rec,
                "fasta_path": str(fa_p),
                "gbk_path": str(gb_p),
                "gbk_profile": inspect_gbk_annotation_profile(gb_p),
            })
        overlap = frozen_accs & all_prior_excluded
        assert len(overlap) == 0, f"Suite E 与调参/基线集存在重叠: {sorted(overlap)}"
        return entries

    # 首次冻结构建
    ext_accs = {acc for _, acc, _, _, _ in SUITE_E_POST_2025_EXTERNAL}
    local_picks = _sample_unseen_local_stratified(
        per_class=local_per_class,
        excluded_accs=all_prior_excluded | ext_accs,
    )

    frozen_records: List[Dict[str, object]] = []
    runtime_entries: List[Dict[str, object]] = []

    for name, acc, fam, exp_m, note in SUITE_E_POST_2025_EXTERNAL:
        if acc in all_prior_excluded or acc in local_fasta:
            raise AssertionError(f"Suite E 外部株 {acc} 与本地或先前基准重叠！")
        fa_p, gb_p = _download_ncbi_pair(acc, fasta_ext_dir, gbk_ext_dir)
        rec = {
            "acc": acc,
            "origin": "ncbi_post_202508",
            "family": fam,
            "host": name,
            "expected": exp_m,
            "desc": note,
            "fasta_sha256": _sha256_file(fa_p),
            "gbk_sha256": _sha256_file(gb_p),
        }
        frozen_records.append(rec)
        runtime_entries.append({
            **rec,
            "fasta_path": str(fa_p),
            "gbk_path": str(gb_p),
            "gbk_profile": inspect_gbk_annotation_profile(gb_p),
        })

    for item in local_picks:
        acc = str(item["acc"])
        fa_p = Path(str(item["fasta_path"]))
        gb_p = Path(str(item["gbk_path"]))
        rec = {
            "acc": acc,
            "origin": "local_unseen_pool",
            "family": item["family"],
            "host": item["host"],
            "expected": item["expected"],
            "desc": item["desc"],
            "fasta_sha256": _sha256_file(fa_p),
            "gbk_sha256": _sha256_file(gb_p),
        }
        frozen_records.append(rec)
        runtime_entries.append({
            **rec,
            "fasta_path": str(fa_p),
            "gbk_path": str(gb_p),
            "gbk_profile": item["gbk_profile"],
        })

    e_accs = {str(r["acc"]) for r in frozen_records}
    assert len(e_accs) == len(frozen_records), "Suite E 存在重复编号"
    overlap = e_accs & all_prior_excluded
    assert len(overlap) == 0, f"Suite E 与先验集合存在交集: {sorted(overlap)}"

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "frozen_version": "suite_e_v1",
        "excluded_prior_count": len(all_prior_excluded),
        "total_entries": len(frozen_records),
        "external_post_202508_count": len(SUITE_E_POST_2025_EXTERNAL),
        "local_unseen_count": len(local_picks),
        "entries": frozen_records,
    }
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return runtime_entries


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
    print("正在构建/核验冻结盲测集 (Suite E)...")
    e_entries = build_and_freeze_suite_e(local_per_class=50)
    e_fams = Counter(str(e["family"]) for e in e_entries)
    e_miss_t = sum(1 for e in e_entries if e["gbk_profile"]["missing_translation"])  # type: ignore[index]
    e_high_h = sum(1 for e in e_entries if e["gbk_profile"]["high_hyp_70"])  # type: ignore[index]
    print(f"Suite E 冻结就绪: {len(e_entries)} 株, 覆盖 {len(e_fams)} 个科, 缺/translation={e_miss_t}, hyp>=70%={e_high_h}")
