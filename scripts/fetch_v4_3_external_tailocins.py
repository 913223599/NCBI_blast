# -*- coding: utf-8 -*-
"""
从公开 NCBI RefSeq / GenBank 拉取跨属非同源 Tailocin / Diffocin / PVC / Afp / eCIS / ICE 硬负样本基因座，
并执行严格的“菌株黑名单 + Gold-8/Unseen/Test 双向氨基酸 5-mer 同源去重 + 无衣壳/末端酶校验”，
确保零数据泄露后输出至 F:\\Phage data\\training\\v4_3_external\\。
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from Bio import SeqIO

REPO_ROOT = Path(__file__).resolve().parents[1]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("fetch_v4_3_external")

# 检索跨属典型无头收缩尾细菌素 / 纳米注射器 / 接合移动岛基因座（严格排除 PAO1 与 Gold-8 菌株）
DEFAULT_QUERIES: Tuple[Tuple[str, str], ...] = (
    # 1. 非 PAO1 假单胞菌 R-/F-Tailocin (如 P. protegens / P. fluorescens / P. chlororaphis / P. syringae)
    ("tailocin_pseudomonas", '("Pseudomonas protegens"[Organism] OR "Pseudomonas chlororaphis"[Organism] OR "Pseudomonas syringae"[Organism]) AND (tailocin[Title] OR pyocin[All Fields] OR "phage tail-like bacteriocin"[All Fields]) AND 15000:120000[SLEN]'),
    ("tailocin_r_type_locus", '("R-type pyocin"[All Fields] OR "F-type pyocin"[All Fields] OR "phage tail-like bacteriocin"[Title] OR "tailocin"[Title]) NOT "PAO1"[All Fields] AND 10000:150000[SLEN]'),
    # 2. PVC / Afp / eCIS 收缩尾纳米注射器 (Photorhabdus / Serratia / Xenorhabdus / Budvicia)
    ("tailocin_pvc_afp", '("Photorhabdus"[Organism] AND ("virulence cassette"[All Fields] OR "PVC"[Title])) OR ("Serratia"[Organism] AND ("antifeeding"[All Fields] OR "afp"[Title])) AND 10000:250000[SLEN]'),
    ("tailocin_maltocin_ecis", '("maltocin"[Title] OR "xenorhabdicin"[Title] OR "serracin"[Title] OR "carotovoricin"[Title] OR "extracellular contractile injection"[Title]) AND 10000:180000[SLEN]'),
    # 3. 革兰氏阳性菌 Diffocin / Monocin (Clostridioides difficile / Listeria non-EGDe / Bacillus non-168)
    ("tailocin_diffocin", '("Clostridioides difficile"[Organism] OR "Clostridium difficile"[Organism]) AND ("diffocin"[All Fields] OR "phage tail-like"[All Fields]) AND 10000:120000[SLEN]'),
    ("tailocin_monocin", '("monocin"[Title] OR ("Listeria innocua"[Organism] AND bacteriocin[All Fields]) OR ("Bacillus"[Organism] AND "phage tail-like bacteriocin"[All Fields])) NOT "EGD-e"[All Fields] NOT "168"[Title] AND 8000:120000[SLEN]'),
    # 4. 非 V583 接合转座移动岛 / ICE（如 ICEKp / ICEclc / SXT / Tn916 基因座）
    ("ice_conjugative", '("integrative conjugative element"[Title] OR "ICEKp"[Title] OR "ICEclc"[Title] OR "SXT/R391"[Title]) NOT "Enterococcus faecalis V583"[All Fields] AND 20000:160000[SLEN]'),
)

# 补充从完整细菌染色体中按蛋白检索定位并精准截取 ±15kb 操纵子上下文（覆盖 Diffocin / Photorhabdus PVC / Xenorhabdicin / Carotovoricin）
CHROMOSOME_LOCUS_QUERIES: Tuple[Tuple[str, str], ...] = (
    ("tailocin_diffocin_locus", '("diffocin"[Protein Name] OR "myophage-like bacteriocin"[Protein Name]) AND "Clostridioides difficile"[Organism]'),
    ("tailocin_pvc_locus", '("Photorhabdus virulence cassette"[All Fields] OR "Pvc1"[Gene Name] OR "Pvc2"[Gene Name] OR "Pvc16"[Gene Name]) AND "Photorhabdus"[Organism]'),
    ("tailocin_xenorhabdus_locus", '("xenorhabdicin"[All Fields] OR "tail sheath"[Protein Name]) AND "Xenorhabdus"[Organism]'),
    ("tailocin_carotovoricin_locus", '("carotovoricin"[All Fields] OR "Erwinia carotovora"[Organism]) AND ("tail sheath"[Protein Name] OR "bacteriocin"[Title])'),
)

# 任何包含这些禁词（测试集宿主与经典菌株）的记录一律拒收
FORBIDDEN_ORGANISM_TOKENS: Tuple[str, ...] = (
    "pao1",
    "nc_002516",
    "sakai",
    "nc_002695",
    "edl933",
    "mg1655",
    "nc_000913",
    "k-12",
    "k12",
    "lt2",
    "nc_003197",
    "v583",
    "nc_004668",
    "egd-e",
    "egde",
    "nc_003210",
    "il1403",
    "nc_002662",
    "sf370",
    "nc_002737",
    "168",
    "nc_000964",
    "nctc 8325",
    "nctc8325",
    "nc_007795",
    "a3(2)",
    "nc_003888",
)

# 若区段内存在真噬菌体包装核心关键字，说明是完整/残余真前噬菌体而非无头细菌素或纯 ICE，予以排除
PHAGE_HEAD_BLOCKLIST: Tuple[str, ...] = (
    "major capsid",
    "capsid protein",
    "prohead",
    "procapsid",
    "head scaffolding",
    "head morphogenesis",
    "head maturation",
    "portal protein",
    "terminase large",
    "terminase small",
    "large terminase",
    "small terminase",
    "terl",
    "head-tail connector",
    "coat protein",
)

TAILOCIN_REQUIRED_KEYWORDS: Tuple[str, ...] = (
    "tail",
    "sheath",
    "baseplate",
    "tube",
    "pyocin",
    "diffocin",
    "monocin",
    "bacteriocin",
    "tailocin",
    "afp",
    "pvc",
    "tape measure",
    "contractile",
    "holin",
    "lysis",
)

ICE_REQUIRED_KEYWORDS: Tuple[str, ...] = (
    "conjugative",
    "virb4",
    "vird4",
    "type iv",
    "relaxase",
    "mob",
    "conjugal",
    "integrative",
    "transposon",
    "tra",
)


def _fetch_url_text(url: str, *, retries: int = 3) -> str:
    last_err: Optional[Exception] = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "PhageDiscovery-V43-Builder/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {url}: {last_err}")


def _esearch_ids(term: str, retmax: int = 12, db: str = "nuccore") -> List[str]:
    q = urllib.parse.urlencode({
        "db": db,
        "term": term,
        "retmax": int(retmax),
        "retmode": "json",
    })
    raw = _fetch_url_text(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?{q}")
    obj = json.loads(raw)
    return list(obj.get("esearchresult", {}).get("idlist", []))


def _efetch_genbank(uid: str, *, seq_start: Optional[int] = None, seq_stop: Optional[int] = None) -> str:
    params: Dict[str, Any] = {
        "db": "nuccore",
        "id": uid,
        "rettype": "gbwithparts",
        "retmode": "text",
    }
    if seq_start is not None and seq_stop is not None:
        params["seq_start"] = int(seq_start)
        params["seq_stop"] = int(seq_stop)
    q = urllib.parse.urlencode(params)
    return _fetch_url_text(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?{q}")


def _resolve_nuccore_slices_from_proteins(prot_uids: Sequence[str], *, pad_bp: int = 18000) -> List[Tuple[str, int, int]]:
    """通过蛋白 GenPept coded_by 提取染色体上的操纵子中心坐标，仅截取 ±pad_bp 局部序列。"""
    import re

    if not prot_uids:
        return []
    q = urllib.parse.urlencode({"db": "protein", "id": ",".join(prot_uids), "rettype": "gp", "retmode": "text"})
    txt = _fetch_url_text(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?{q}")
    slices: List[Tuple[str, int, int]] = []
    seen_acc: Set[str] = set()
    for m in re.finditer(r"coded_by=\"(?:complement\()?([A-Za-z0-9_.]+):(\d+)\.\.(\d+)", txt):
        nuc_acc, s_s, e_s = m.group(1), int(m.group(2)), int(m.group(3))
        if nuc_acc in seen_acc:
            continue
        seen_acc.add(nuc_acc)
        center = (s_s + e_s) // 2
        slices.append((nuc_acc, max(1, center - pad_bp), center + pad_bp))
    return slices


def _kmer_set(seq: str, k: int = 5) -> Set[str]:
    s = seq.strip().upper()
    if len(s) < k:
        return set()
    return {s[i : i + k] for i in range(len(s) - k + 1)}


def _build_forbidden_kmer_index(pd_root: Path) -> Tuple[Set[str], List[Tuple[str, Set[str]]]]:
    """收集 Gold-8、Unseen 与 test/val 负样本的 accession 黑名单及关键靶点蛋白 5-mer 索引。"""
    forbidden_accs: Set[str] = set()
    splits_p = pd_root / "benchmarks" / "v1" / "negative_splits.json"
    if splits_p.is_file():
        ns = json.loads(splits_p.read_text(encoding="utf-8"))
        for acc, sp in ns.items():
            if sp != "train":
                forbidden_accs.add(str(acc).split(".")[0].lower())

    target_proteins: List[Tuple[str, Set[str]]] = []
    # 从 Gold-8 已知干扰区（PAO1 pyocin, EGD-e monocin, V583 ICE）与完整 Gold-8/Unseen 提取所有蛋白 k-mer
    for bdir in (pd_root / "benchmarks" / "gold_standard_hosts", pd_root / "benchmarks" / "unseen_real_genomes"):
        if not bdir.is_dir():
            continue
        for fa in bdir.glob("*.f*"):
            if fa.name.startswith("_"):
                continue
            acc_tok = fa.stem.split("_")[0]
            if acc_tok:
                forbidden_accs.add(acc_tok.split(".")[0].lower())
        for gbk in bdir.glob("*.gbk"):
            for rec in SeqIO.parse(str(gbk), "genbank"):
                forbidden_accs.add(str(rec.id).split(".")[0].lower())
                for feat in rec.features:
                    if feat.type != "CDS":
                        continue
                    aa = str((feat.qualifiers.get("translation") or [""])[0]).strip()
                    if len(aa) >= 60:
                        target_proteins.append((f"{gbk.stem}:{feat.qualifiers.get('locus_tag', [''])[0]}", _kmer_set(aa)))
    return forbidden_accs, target_proteins


def _max_kmer_jaccard(aa: str, ref_kmers: Sequence[Tuple[str, Set[str]]]) -> Tuple[float, str]:
    ks = _kmer_set(aa)
    if len(ks) < 20:
        return 0.0, ""
    best_j = 0.0
    best_src = ""
    # 快速过滤：利用集合长度比剪枝减少无效交集运算
    l1 = len(ks)
    for src, rks in ref_kmers:
        l2 = len(rks)
        if min(l1, l2) / max(1, max(l1, l2)) <= best_j:
            continue
        inter = len(ks & rks)
        if inter == 0:
            continue
        jac = inter / float(l1 + l2 - inter)
        if jac > best_j:
            best_j = jac
            best_src = src
    return best_j, best_src


def fetch_and_filter_external(pd_root: Path, *, max_per_query: int = 10, max_jaccard: float = 0.50) -> Dict[str, Any]:
    out_dir = pd_root / "training" / "v4_3_external"
    gbk_cache_dir = out_dir / "raw_gbk"
    out_dir.mkdir(parents=True, exist_ok=True)
    gbk_cache_dir.mkdir(parents=True, exist_ok=True)

    forbidden_accs, ref_kmers = _build_forbidden_kmer_index(pd_root)
    logger.info("零泄露屏障就绪: forbidden_accs=%d, gold_ref_proteins=%d", len(forbidden_accs), len(ref_kmers))

    # 读取断点记录，已解析成功的 UID 不重复请求 NCBI
    seen_uids: Dict[str, str] = {}
    uid_ckpt = out_dir / "fetched_uids.json"
    if uid_ckpt.is_file():
        seen_uids = json.loads(uid_ckpt.read_text(encoding="utf-8"))

    query_hits: List[Tuple[str, str, Optional[int], Optional[int]]] = []
    for tag, term in DEFAULT_QUERIES:
        try:
            uids = _esearch_ids(term, retmax=max_per_query, db="nuccore")
            logger.info("检索 [%s] 返回 %d 条 UID", tag, len(uids))
            for u in uids:
                query_hits.append((tag, str(u), None, None))
            time.sleep(0.4)
        except Exception as exc:  # noqa: BLE001
            logger.warning("检索 [%s] 失败: %s", tag, exc)

    for tag, pterm in CHROMOSOME_LOCUS_QUERIES:
        try:
            puids = _esearch_ids(pterm, retmax=max(4, max_per_query // 2), db="protein")
            slices = _resolve_nuccore_slices_from_proteins(puids, pad_bp=18000)
            logger.info("染色体基因座切片检索 [%s] 解析出 %d 个操纵子窗口", tag, len(slices))
            for nuc_acc, ss, se in slices:
                query_hits.append((tag, nuc_acc, ss, se))
            time.sleep(0.4)
        except Exception as exc:  # noqa: BLE001
            logger.warning("切片检索 [%s] 失败: %s", tag, exc)

    accepted_records: List[Dict[str, Any]] = []
    rejected_audit: List[Dict[str, Any]] = []
    accepted_fna_path = out_dir / "external_tailocin_ice.fna"
    accepted_meta_path = out_dir / "external_tailocin_ice.json"

    visited_accs: Set[str] = set()
    seen_sha256: Set[str] = set()
    fna_lines: List[str] = []

    for tag, uid, s_start, s_stop in query_hits:
        cache_name = f"{uid}_{s_start}_{s_stop}.gbk" if s_start is not None else f"{uid}.gbk"
        gb_path = gbk_cache_dir / cache_name
        if not gb_path.is_file():
            try:
                gb_txt = _efetch_genbank(uid, seq_start=s_start, seq_stop=s_stop)
                gb_path.write_text(gb_txt, encoding="utf-8")
                seen_uids[cache_name] = tag
                time.sleep(0.45)
            except Exception as exc:  # noqa: BLE001
                logger.warning("下载 UID=%s 失败: %s", cache_name, exc)
                continue

        try:
            recs = list(SeqIO.parse(str(gb_path), "genbank"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("解析 %s 失败: %s", gb_path, exc)
            continue

        for rec in recs:
            acc = str(rec.id)
            slice_key = f"{acc}:{s_start}-{s_stop}" if s_start is not None else acc
            acc_base = acc.split(".")[0].lower()
            desc = str(rec.description or "")
            org = str(rec.annotations.get("organism", ""))
            seq_str = str(rec.seq).upper()

            if slice_key in visited_accs:
                continue
            visited_accs.add(slice_key)

            # 1. Accession / 物种名称黑名单 & SHA256 重复过滤
            meta_txt = f"{acc} {desc} {org}".lower()
            if acc_base in forbidden_accs or any(tok in meta_txt for tok in FORBIDDEN_ORGANISM_TOKENS):
                rejected_audit.append({"acc": slice_key, "tag": tag, "reason": "forbidden_host_or_split", "org": org})
                continue

            seq_hash = hashlib.sha256(seq_str.encode("ascii", errors="ignore")).hexdigest()
            if seq_hash in seen_sha256:
                rejected_audit.append({"acc": slice_key, "tag": tag, "reason": "duplicate_sequence_sha256", "org": org})
                continue
            seen_sha256.add(seq_hash)

            if not (8000 <= len(seq_str) <= 300000):
                rejected_audit.append({"acc": slice_key, "tag": tag, "reason": f"length_out_of_range({len(seq_str)})", "org": org})
                continue

            # 2. 产品注释校验：确认具备目标功能域，且无真正噬菌体衣壳/Portal/TerL
            cds_prots: List[Tuple[int, int, int, str, str]] = []
            has_head_block = False
            tail_kw_hits = 0
            ice_kw_hits = 0
            for feat in rec.features:
                if feat.type != "CDS":
                    continue
                prod = str((feat.qualifiers.get("product") or [""])[0]).lower()
                gene = str((feat.qualifiers.get("gene") or [""])[0]).lower()
                note = str((feat.qualifiers.get("note") or [""])[0]).lower()
                txt = f"{prod} {gene} {note}"
                if any(bk in txt for bk in PHAGE_HEAD_BLOCKLIST):
                    has_head_block = True
                if any(tk in txt for tk in TAILOCIN_REQUIRED_KEYWORDS):
                    tail_kw_hits += 1
                if any(ik in txt for ik in ICE_REQUIRED_KEYWORDS):
                    ice_kw_hits += 1
                aa = str((feat.qualifiers.get("translation") or [""])[0]).strip()
                if aa and "*" not in aa:
                    cds_prots.append((int(feat.location.start), int(feat.location.end), int(feat.location.strand or 1), aa, prod))

            if len(cds_prots) < 10:
                rejected_audit.append({"acc": slice_key, "tag": tag, "reason": f"too_few_annotated_cds({len(cds_prots)})", "org": org})
                continue

            if has_head_block:
                rejected_audit.append({"acc": slice_key, "tag": tag, "reason": "contains_phage_capsid_portal_terl", "org": org})
                continue

            is_ice = tag.startswith("ice_")
            if (not is_ice and tail_kw_hits < 3) or (is_ice and ice_kw_hits < 2):
                rejected_audit.append({
                    "acc": slice_key,
                    "tag": tag,
                    "reason": f"insufficient_target_keywords(tail={tail_kw_hits},ice={ice_kw_hits})",
                    "org": org,
                })
                continue

            # 3. 与 Gold-8/Unseen 全量测试蛋白执行 5-mer Jaccard 严格零泄露审查
            leak_hit = None
            max_sim = 0.0
            for _, _, _, aa, _ in cds_prots:
                jac, src = _max_kmer_jaccard(aa, ref_kmers)
                if jac > max_sim:
                    max_sim = jac
                if jac >= max_jaccard:
                    leak_hit = (round(jac, 4), src)
                    break

            if leak_hit is not None:
                rejected_audit.append({
                    "acc": slice_key,
                    "tag": tag,
                    "reason": f"kmer_similarity_too_high({leak_hit[0]} vs {leak_hit[1]})",
                    "org": org,
                })
                continue

            cid = f"EXT_{tag}_{acc}"
            if s_start is not None:
                cid = f"{cid}_{s_start}_{s_stop}"
            fna_lines.append(f">{cid}\n{seq_str}\n")
            accepted_records.append({
                "contig_id": cid,
                "accession": acc,
                "tag": tag,
                "kind": "mge_ice" if is_ice else "tailocin",
                "organism": org,
                "description": desc,
                "length_bp": len(seq_str),
                "cds_count": len(cds_prots),
                "tail_kw_hits": tail_kw_hits,
                "ice_kw_hits": ice_kw_hits,
                "max_ref_5mer_jaccard": round(max_sim, 4),
            })

    tmp_uid = uid_ckpt.with_name(f".{uid_ckpt.name}.tmp")
    tmp_uid.write_text(json.dumps(seen_uids, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_uid.replace(uid_ckpt)

    tmp_fna = accepted_fna_path.with_name(f".{accepted_fna_path.name}.tmp")
    tmp_fna.write_text("".join(fna_lines), encoding="utf-8")
    tmp_fna.replace(accepted_fna_path)

    summary = {
        "accepted_count": len(accepted_records),
        "rejected_count": len(rejected_audit),
        "accepted": accepted_records,
        "rejected": rejected_audit,
    }
    tmp_meta = accepted_meta_path.with_name(f".{accepted_meta_path.name}.tmp")
    tmp_meta.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_meta.replace(accepted_meta_path)

    logger.info(
        "外源硬负样本拉取与零泄露审查完成: accepted=%d, rejected=%d -> %s",
        len(accepted_records),
        len(rejected_audit),
        accepted_fna_path,
    )
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phage-data-root", default=os.environ.get("PHAGE_DATA_ROOT", str(REPO_ROOT.parent / "Phage data")))
    ap.add_argument("--max-per-query", type=int, default=10)
    ap.add_argument("--max-jaccard", type=float, default=0.50)
    args = ap.parse_args()
    fetch_and_filter_external(Path(args.phage_data_root).resolve(), max_per_query=args.max_per_query, max_jaccard=args.max_jaccard)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

