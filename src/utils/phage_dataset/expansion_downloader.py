# -*- coding: utf-8 -*-
"""
V3 靶向数据扩展与零泄露防线下载器

核心功能：
1. 从冻结的 v1 基准（negative_splits.json、splits/*.tsv）与盲测真实细菌基因组收集
   严格排除集合（含版本号与基础 accession），杜绝任何数据泄露；
2. 靶向扩展负样本库（极端高 GC >= 68% 放线菌染色体、低 GC < 38% 细菌与古菌染色体、
   大型接合/耐药质粒、更多样化的真核/古菌非噬菌体病毒）；
3. 靶向扩展稀缺非有尾噬菌体正样本（Microviridae、Inoviridae、Leviviricetes、
   Tectiviridae、Corticoviridae、Cystoviridae），强制经 _assess_phage_identity 核验；
4. 复用 NegativeDatasetDownloader 的网络重试与校验原语，强制 UTF-8 与断点续传。
"""
import concurrent.futures
import io
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import requests
from Bio import SeqIO

from .ncbi_downloader import (
    EUTILS_BASE,
    atomic_write_text,
    sanitize_accession,
    split_genbank_entries,
)
from .negative_downloader import NegativeDatasetDownloader
from .validator import PHAGE_NAME_RE, _assess_phage_identity, _extract_host

logger = logging.getLogger("utils.phage_dataset.expansion_downloader")

# 默认盲测保留基因组（严禁进入任何训练或扩展池）
DEFAULT_UNSEEN_HOLDOUT_ACCS: Tuple[str, ...] = (
    "NC_003197.2",
    "NC_007795.1",
    "NC_000913.3",
    "NC_003888.3",
)

# 扩展查询格式: (group_name, category, ncbi_term, quota_weight, batch_size, min_gc, max_gc, min_len, max_len)
ExpansionQuery = Tuple[str, str, str, float, int, float, float, int, int]

NEGATIVE_EXPANSION_QUERIES: List[ExpansionQuery] = [
    # 高 GC 放线菌染色体（覆盖 >=68% GC，直接针对 Streptomyces 类误报盲区）
    (
        "HighGC_Streptomyces",
        "high_gc_chromosome",
        "Streptomyces[Organism] AND (complete genome[Title] OR chromosome[Title]) AND srcdb_refseq[PROP] AND 5000000:12000000[SLEN] NOT plasmid[Title] NOT coelicolor[Organism]",
        0.16,
        1,
        0.68,
        0.85,
        3000000,
        12000000,
    ),
    (
        "HighGC_Nocardia_Rhodococcus",
        "high_gc_chromosome",
        "(Nocardia[Organism] OR Rhodococcus[Organism] OR Micromonospora[Organism]) AND complete genome[Title] AND srcdb_refseq[PROP] AND 3000000:11000000[SLEN] NOT plasmid[Title]",
        0.12,
        1,
        0.65,
        0.85,
        2500000,
        11000000,
    ),
    (
        "HighGC_Corynebacterium_Pseudomonas",
        "high_gc_chromosome",
        "(Corynebacterium[Organism] OR Burkholderia[Organism] OR Xanthomonas[Organism]) AND complete genome[Title] AND srcdb_refseq[PROP] AND 2000000:8500000[SLEN] NOT plasmid[Title]",
        0.10,
        2,
        0.62,
        0.80,
        1500000,
        9000000,
    ),
    # 低 GC 细菌与古菌染色体（扩充 <38% GC 及跨界背景）
    (
        "LowGC_Clostridium_Mycoplasma",
        "low_gc_chromosome",
        "(Clostridium[Organism] OR Mycoplasma[Organism] OR Campylobacter[Organism] OR Fusobacterium[Organism]) AND complete genome[Title] AND srcdb_refseq[PROP] AND 500000:5500000[SLEN] NOT plasmid[Title]",
        0.10,
        2,
        0.20,
        0.40,
        500000,
        6000000,
    ),
    (
        "Archaea_Chromosomes",
        "archaeal_chromosome",
        "Archaea[Organism] AND complete genome[Title] AND srcdb_refseq[PROP] AND 1000000:5500000[SLEN] NOT plasmid[Title]",
        0.08,
        2,
        0.25,
        0.75,
        800000,
        6000000,
    ),
    # 大型质粒（富含转移/整合/耐药岛硬负例）
    (
        "Large_Conjugative_Plasmids",
        "plasmid",
        "plasmid[Title] AND complete sequence[Title] AND srcdb_refseq[PROP] AND Bacteria[Organism] AND 40000:450000[SLEN]",
        0.16,
        15,
        0.20,
        0.80,
        30000,
        500000,
    ),
    # 多样化非噬菌体病毒（强化短序列 1kb-3kb 低误报边界）
    (
        "NonPhageVirus_Euk_DNA_Ext",
        "non_phage_virus",
        "(Poxviridae[Organism] OR Polyomaviridae[Organism] OR Parvoviridae[Organism] OR Circoviridae[Organism] OR Herpesvirales[Organism] OR Adenoviridae[Organism]) AND complete genome[Title] AND srcdb_refseq[PROP] AND 2000:350000[SLEN]",
        0.14,
        15,
        0.20,
        0.80,
        2000,
        400000,
    ),
    (
        "NonPhageVirus_Euk_RNA_Archaeal_Ext",
        "non_phage_virus",
        "(Potyviridae[Organism] OR Rhabdoviridae[Organism] OR Paramyxoviridae[Organism] OR Togaviridae[Organism] OR Fuselloviridae[Organism] OR Rudiviridae[Organism] OR Halspiviridae[Organism]) AND complete genome[Title] AND srcdb_refseq[PROP] AND 2000:250000[SLEN]",
        0.14,
        15,
        0.20,
        0.80,
        2000,
        300000,
    ),
]

RARE_PHAGE_EXPANSION_QUERIES: List[ExpansionQuery] = [
    (
        "RarePhage_Microviridae",
        "Microviridae",
        "(Microviridae[Organism] OR Bullavirales[Organism] OR Gokushovirales[Organism] OR Malgrandaviricetes[Organism]) AND complete genome[Title] AND 3000:15000[SLEN]",
        0.35,
        25,
        0.20,
        0.75,
        3000,
        15000,
    ),
    (
        "RarePhage_Inoviridae",
        "Inoviridae",
        "(Inoviridae[Organism] OR Tubulavirales[Organism] OR Plectroviridae[Organism]) AND complete genome[Title] AND 3500:20000[SLEN]",
        0.25,
        25,
        0.20,
        0.75,
        3500,
        20000,
    ),
    (
        "RarePhage_Leviviricetes",
        "Leviviricetes",
        "(Leviviricetes[Organism] OR Fiersviridae[Organism] OR Atkinsviridae[Organism] OR Duinviridae[Organism]) AND complete genome[Title] AND 2500:12000[SLEN]",
        0.25,
        25,
        0.20,
        0.75,
        2500,
        12000,
    ),
    (
        "RarePhage_Tecti_Cortico_Cysto",
        "Tectiviridae",
        "(Tectiviridae[Organism] OR Autolykiviridae[Organism] OR Corticoviridae[Organism] OR Cystoviridae[Organism]) AND complete genome[Title] AND 3000:30000[SLEN]",
        0.15,
        20,
        0.20,
        0.75,
        3000,
        30000,
    ),
]


def _normalize_base_acc(acc: str) -> str:
    """提取去除版本号后缀的基础 accession（如 NC_003888.3 -> NC_003888）。"""
    clean = sanitize_accession(acc).strip()
    if "." in clean:
        return clean.split(".", 1)[0]
    return clean


def _compute_gc_ratio(seq_str: str) -> float:
    upper = seq_str.upper()
    if not upper:
        return 0.0
    gc = upper.count("G") + upper.count("C")
    return float(gc) / float(len(upper))


def _load_split_tsv_accs(tsv_path: Path) -> Set[str]:
    accs: Set[str] = set()
    if not tsv_path.exists():
        return accs
    lines = tsv_path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return accs
    header = lines[0].split("\t")
    col_idx = header.index("accession") if "accession" in header else 0
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split("\t")
        if col_idx < len(parts):
            accs.add(sanitize_accession(parts[col_idx]))
    return accs


def collect_excluded_accessions(
    *,
    negative_splits_json: Optional[Path] = None,
    positive_splits_dir: Optional[Path] = None,
    extra_excluded_accs: Optional[Iterable[str]] = None,
    include_existing_train: bool = True,
) -> Tuple[Set[str], Set[str]]:
    """
    汇总需要严格排除的 accession 集合，返回 (精确集合, 基础前缀集合)。
    同时排除 val/test、盲测真实基因组以及（可选）已有 train 数据以避免重复下载。
    """
    exact: Set[str] = set()

    for acc in DEFAULT_UNSEEN_HOLDOUT_ACCS:
        exact.add(sanitize_accession(acc))
    if extra_excluded_accs:
        for acc in extra_excluded_accs:
            if acc.strip():
                exact.add(sanitize_accession(acc))

    if negative_splits_json and Path(negative_splits_json).exists():
        payload = json.loads(Path(negative_splits_json).read_text(encoding="utf-8"))
        split_keys = ("train", "val", "test") if include_existing_train else ("val", "test")
        for key in split_keys:
            for acc in payload.get(key, []):
                exact.add(sanitize_accession(str(acc)))

    if positive_splits_dir and Path(positive_splits_dir).exists():
        split_files = ("train.tsv", "val.tsv", "test.tsv") if include_existing_train else ("val.tsv", "test.tsv")
        for fname in split_files:
            exact |= _load_split_tsv_accs(Path(positive_splits_dir) / fname)

    base = {_normalize_base_acc(a) for a in exact if a}
    return exact, base


class ExpansionDownloader:
    """V3 零泄露靶向扩展下载器（分别落盘负样本扩展与稀缺噬菌体扩展）。"""

    def __init__(
        self,
        output_dir: Path,
        *,
        excluded_exact: Optional[Set[str]] = None,
        excluded_base: Optional[Set[str]] = None,
        email: str = "phage_dataset@localhost",
        api_key: Optional[str] = None,
        request_timeout: int = 75,
        retry_backoff_base: float = 1.5,
        max_workers: int = 3,
        session: Optional[requests.Session] = None,
    ):
        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._custom_session = session is not None
        self.max_workers = max(1, max_workers)
        self.excluded_exact = set(excluded_exact or set())
        self.excluded_base = set(excluded_base or set())
        if self.excluded_exact:
            self.excluded_base |= {_normalize_base_acc(a) for a in self.excluded_exact}

        # 复用 NegativeDatasetDownloader 的重试网络客户端与本地保存目录规范
        self._neg_client = NegativeDatasetDownloader(
            data_dir=self.output_dir / "negative_ext",
            email=email,
            api_key=api_key,
            min_length_bp=2000,
            max_length_bp=12000000,
            request_timeout=request_timeout,
            retry_backoff_base=retry_backoff_base,
            session=session,
        )
        self._pos_client = NegativeDatasetDownloader(
            data_dir=self.output_dir / "positive_rare_ext",
            email=email,
            api_key=api_key,
            min_length_bp=2500,
            max_length_bp=50000,
            request_timeout=request_timeout,
            retry_backoff_base=retry_backoff_base,
            session=self._neg_client.session,
        )

    @staticmethod
    def _load_exp_state(client: NegativeDatasetDownloader) -> Dict[str, Any]:
        """加载扩展池断点，保留只含 .fasta（大型染色体快速模式）或 .fasta+.gbk 的已落盘记录。"""
        if client.checkpoint_path.exists():
            try:
                data = json.loads(client.checkpoint_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        else:
            data = {}
        data.setdefault("saved_records", {})
        data.setdefault("uid_to_accession", {})
        data.setdefault("skipped_ids", {})

        valid_saved: Dict[str, Any] = {}
        for acc, meta in data["saved_records"].items():
            fa = client.fasta_dir / f"{acc}.fasta"
            if fa.exists() and fa.stat().st_size > 0:
                valid_saved[acc] = meta
        data["saved_records"] = valid_saved
        return data

    def _persist_chromosome_fasta(
        self,
        *,
        client: NegativeDatasetDownloader,
        rec: Any,
        uid: str,
        query_meta: ExpansionQuery,
        state: Dict[str, Any],
    ) -> Optional[str]:
        group_name, category, _, _, _, min_gc, max_gc, min_len, max_len = query_meta
        acc = sanitize_accession(rec.id or rec.name)
        if self._is_excluded(acc):
            state["skipped_ids"][uid] = f"excluded_leakage_guard:{acc}"
            return None

        desc = str(rec.description or "")
        if PHAGE_NAME_RE.search(desc):
            state["skipped_ids"][uid] = "phage_keyword_in_fasta_header"
            return None

        seq_str = str(rec.seq)
        seq_len = len(seq_str)
        if seq_len < min_len or seq_len > max_len:
            state["skipped_ids"][uid] = f"length_out_of_range:{seq_len}"
            return None

        gc_ratio = _compute_gc_ratio(seq_str)
        if gc_ratio < min_gc or gc_ratio > max_gc:
            state["skipped_ids"][uid] = f"gc_out_of_range:{gc_ratio:.3f}"
            return None

        fasta_path = client.fasta_dir / f"{acc}.fasta"
        fasta_buf = io.StringIO()
        SeqIO.write(rec, fasta_buf, "fasta")
        atomic_write_text(fasta_path, fasta_buf.getvalue())

        state["saved_records"][acc] = {
            "accession": acc,
            "uid": uid,
            "source_group": group_name,
            "category": category,
            "format": "fasta_only",
            "length_bp": seq_len,
            "gc_ratio": round(gc_ratio, 4),
            "description": desc[:200],
            "saved_at": datetime.now().isoformat(timespec="seconds"),
        }
        if uid:
            state["uid_to_accession"][uid] = acc
        self.excluded_exact.add(acc)
        self.excluded_base.add(_normalize_base_acc(acc))
        return acc

    def _is_excluded(self, acc: str) -> bool:
        clean = sanitize_accession(acc)
        return (clean in self.excluded_exact) or (_normalize_base_acc(clean) in self.excluded_base)

    def _search_candidates(
        self,
        client: NegativeDatasetDownloader,
        target_count: int,
        queries: Sequence[ExpansionQuery],
    ) -> List[Tuple[str, ExpansionQuery]]:
        total_weight = sum(item[3] for item in queries) or 1.0
        pool_target = int(target_count * 2.0) + len(queries) * 2
        seen_uids: Set[str] = set()
        buckets: List[List[Tuple[str, ExpansionQuery]]] = []

        for q in queries:
            group_name, category, term, weight, _, _, _, _, _ = q
            quota = max(4, round(pool_target * (weight / total_weight)))
            resp = client._request_with_retry(
                f"{EUTILS_BASE}/esearch.fcgi",
                {
                    "db": "nuccore",
                    "term": term,
                    "retmax": min(max(quota * 3, 40), 2500),
                    "sort": "relevance",
                    "retmode": "json",
                },
            )
            payload = resp.json().get("esearchresult", {})
            id_list = payload.get("idlist", []) or []
            bucket: List[Tuple[str, ExpansionQuery]] = []
            for uid in id_list:
                uid_str = str(uid).strip()
                if not uid_str or uid_str in seen_uids:
                    continue
                seen_uids.add(uid_str)
                bucket.append((uid_str, q))
                if len(bucket) >= quota:
                    break
            buckets.append(bucket)
            logger.info(f"扩展检索 [{group_name}/{category}]: NCBI候选 {payload.get('count', 0)}, 入队 {len(bucket)} 条")

        ordered: List[Tuple[str, ExpansionQuery]] = []
        max_len = max((len(b) for b in buckets), default=0)
        for i in range(max_len):
            for b in buckets:
                if i < len(b):
                    ordered.append(b[i])
        return ordered

    def _persist_validated_record(
        self,
        *,
        client: NegativeDatasetDownloader,
        entry_text: str,
        uid: str,
        query_meta: ExpansionQuery,
        expect_phage: bool,
        state: Dict[str, Any],
    ) -> Optional[str]:
        group_name, category, _, _, _, min_gc, max_gc, min_len, max_len = query_meta
        try:
            rec = SeqIO.read(io.StringIO(entry_text), "genbank")
        except Exception as exc:
            logger.debug(f"跳过不可解析记录 (uid={uid}): {exc}")
            return None

        acc = sanitize_accession(rec.id or rec.name)
        if self._is_excluded(acc):
            state["skipped_ids"][uid] = f"excluded_leakage_guard:{acc}"
            return None

        seq_str = str(rec.seq)
        seq_len = len(seq_str)
        if seq_len < min_len or seq_len > max_len:
            state["skipped_ids"][uid] = f"length_out_of_range:{seq_len}"
            return None

        gc_ratio = _compute_gc_ratio(seq_str)
        if gc_ratio < min_gc or gc_ratio > max_gc:
            state["skipped_ids"][uid] = f"gc_out_of_range:{gc_ratio:.3f}"
            return None

        cds_count = sum(1 for feat in rec.features if feat.type == "CDS")
        if cds_count <= 0:
            state["skipped_ids"][uid] = "no_cds_features"
            return None

        tax_list = [str(x).strip() for x in (rec.annotations.get("taxonomy") or []) if str(x).strip()]
        product_texts = [
            str((feat.qualifiers.get("product") or [""])[0])
            for feat in rec.features
            if feat.type == "CDS"
        ]
        is_phage, confidence, tax_group, evidence = _assess_phage_identity(
            taxonomy_tokens=tax_list,
            organism=str(rec.annotations.get("organism") or rec.id or ""),
            description=str(rec.description or ""),
            host=_extract_host(rec),
            product_texts=product_texts,
        )

        if expect_phage:
            if not is_phage:
                state["skipped_ids"][uid] = f"rejected_non_phage:{tax_group}"
                return None
            # 确认避免与大量已有 Caudoviricetes 重复
            if tax_group == "Caudoviricetes":
                state["skipped_ids"][uid] = "skip_caudoviricetes_in_rare_pool"
                return None
        else:
            if is_phage:
                state["skipped_ids"][uid] = f"phage_contamination_blocked:{tax_group}"
                return None

        gbk_path = client.gbk_dir / f"{acc}.gbk"
        fasta_path = client.fasta_dir / f"{acc}.fasta"
        fasta_buf = io.StringIO()
        SeqIO.write(rec, fasta_buf, "fasta")

        atomic_write_text(gbk_path, entry_text)
        atomic_write_text(fasta_path, fasta_buf.getvalue())

        state["saved_records"][acc] = {
            "accession": acc,
            "uid": uid,
            "source_group": group_name,
            "category": tax_group if expect_phage else category,
            "length_bp": seq_len,
            "gc_ratio": round(gc_ratio, 4),
            "cds_count": cds_count,
            "tax_group": tax_group,
            "confidence": confidence,
            "evidence": evidence,
            "description": (rec.description or "")[:200],
            "saved_at": datetime.now().isoformat(timespec="seconds"),
        }
        if uid:
            state["uid_to_accession"][uid] = acc
        self.excluded_exact.add(acc)
        self.excluded_base.add(_normalize_base_acc(acc))
        return acc

    def _run_expansion_pool(
        self,
        *,
        client: NegativeDatasetDownloader,
        target_count: int,
        queries: Sequence[ExpansionQuery],
        expect_phage: bool,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
    ) -> Dict[str, Any]:
        state = self._load_exp_state(client)
        already_saved = len(state["saved_records"])
        pool_label = "rare_phage_pos" if expect_phage else "hard_domain_neg"
        logger.info(f"[{pool_label}] 断点核查: 本地已就绪 {already_saved} 条, 目标总数 {target_count}")
        if already_saved >= target_count:
            return {
                "pool": pool_label,
                "target_count": target_count,
                "saved_count": already_saved,
                "newly_downloaded": 0,
                "skipped_count": len(state.get("skipped_ids", {})),
                "checkpoint_path": str(client.checkpoint_path),
            }

        candidates = self._search_candidates(
            client=client,
            target_count=max(target_count, target_count - already_saved + 20),
            queries=queries,
        )
        done_uids = set(state.get("uid_to_accession", {}).keys()) | set(state.get("skipped_ids", {}).keys())
        pending = [item for item in candidates if item[0] not in done_uids]

        # 按同批最大允许 batch_size 分批打包，染色体(bsize<=2)单/双条拉 FASTA，其余批量拉 GenBank
        batches: List[List[Tuple[str, ExpansionQuery]]] = []
        small_buf: List[Tuple[str, ExpansionQuery]] = []
        normal_buf: List[Tuple[str, ExpansionQuery]] = []
        for uid, q in pending:
            bsize = max(1, q[4])
            if bsize <= 2:
                small_buf.append((uid, q))
                if len(small_buf) >= bsize:
                    batches.append(small_buf)
                    small_buf = []
            else:
                normal_buf.append((uid, q))
                if len(normal_buf) >= 15:
                    batches.append(normal_buf)
                    normal_buf = []
        if small_buf:
            batches.append(small_buf)
        if normal_buf:
            batches.append(normal_buf)

        # 交错调度确保高/低 GC 染色体配额不被纯小质粒先跑完（优先少量多批染色体）
        small_batches = [b for b in batches if len(b) <= 2 and b[0][1][4] <= 2]
        normal_batches = [b for b in batches if not (len(b) <= 2 and b[0][1][4] <= 2)]
        scheduled: List[List[Tuple[str, ExpansionQuery]]] = []
        for i in range(max(len(small_batches), len(normal_batches))):
            if i < len(small_batches):
                scheduled.append(small_batches[i])
            if i < len(normal_batches):
                scheduled.append(normal_batches[i])

        def _fetch_one_batch(batch_item: List[Tuple[str, ExpansionQuery]]) -> Tuple[List[Tuple[str, ExpansionQuery]], bool, Optional[str], Optional[str]]:
            uids = [x[0] for x in batch_item]
            is_fast = (not expect_phage) and (batch_item[0][1][4] <= 2)
            rtype = "fasta" if is_fast else "gbwithparts"
            try:
                resp = client._request_with_retry(
                    f"{EUTILS_BASE}/efetch.fcgi",
                    {
                        "db": "nuccore",
                        "id": ",".join(uids),
                        "rettype": rtype,
                        "retmode": "text",
                    },
                    max_retries=2,
                )
                return batch_item, is_fast, resp.text, None
            except Exception as exc:
                return batch_item, is_fast, None, str(exc)

        newly_downloaded = 0
        eff_workers = 1 if self._custom_session else self.max_workers
        pos = 0
        while pos < len(scheduled) and len(state["saved_records"]) < target_count:
            chunk = scheduled[pos:pos + eff_workers]
            pos += len(chunk)
            if eff_workers > 1 and len(chunk) > 1:
                with concurrent.futures.ThreadPoolExecutor(max_workers=len(chunk)) as ex:
                    fetched_results = list(ex.map(_fetch_one_batch, chunk))
            else:
                fetched_results = [_fetch_one_batch(b) for b in chunk]

            for batch, is_fast_fasta_batch, raw_text, err_msg in fetched_results:
                if len(state["saved_records"]) >= target_count:
                    break
                batch_uids = [item[0] for item in batch]
                uid_to_q = {item[0]: item[1] for item in batch}
                if err_msg or not raw_text:
                    logger.warning(f"[{pool_label}] 批次拉取失败(跳过 {len(batch_uids)} 条): {err_msg}")
                    for uid in batch_uids:
                        state["skipped_ids"][uid] = f"batch_fetch_error:{err_msg}"
                    client.save_checkpoint(state)
                    continue

                if is_fast_fasta_batch:
                    fa_records = list(SeqIO.parse(io.StringIO(raw_text), "fasta"))
                    for idx, rec in enumerate(fa_records):
                        if len(state["saved_records"]) >= target_count:
                            break
                        fb_uid = batch_uids[idx] if idx < len(batch_uids) else ""
                        q_meta = uid_to_q.get(fb_uid, queries[0])
                        acc = self._persist_chromosome_fasta(
                            client=client,
                            rec=rec,
                            uid=fb_uid,
                            query_meta=q_meta,
                            state=state,
                        )
                        if acc:
                            newly_downloaded += 1
                else:
                    entries = split_genbank_entries(raw_text)
                    for idx, entry_text in enumerate(entries):
                        if len(state["saved_records"]) >= target_count:
                            break
                        fb_uid = batch_uids[idx] if idx < len(batch_uids) else ""
                        q_meta = uid_to_q.get(fb_uid, queries[0])
                        acc = self._persist_validated_record(
                            client=client,
                            entry_text=entry_text,
                            uid=fb_uid,
                            query_meta=q_meta,
                            expect_phage=expect_phage,
                            state=state,
                        )
                        if acc:
                            newly_downloaded += 1

                for uid in batch_uids:
                    if uid not in state["uid_to_accession"] and uid not in state["skipped_ids"]:
                        state["skipped_ids"][uid] = "batch_processed_or_filtered"

                client.save_checkpoint(state)
                cur = len(state["saved_records"])
                logger.info(f"[{pool_label}] 落盘进度: {cur}/{target_count} (本轮新增 {newly_downloaded})")
                if progress_cb:
                    progress_cb(cur, target_count, f"[{pool_label}] {cur}/{target_count}")

        return {
            "pool": pool_label,
            "target_count": target_count,
            "saved_count": len(state["saved_records"]),
            "newly_downloaded": newly_downloaded,
            "skipped_count": len(state.get("skipped_ids", {})),
            "checkpoint_path": str(client.checkpoint_path),
        }

    def download_negative_expansion(
        self,
        *,
        target_count: int = 180,
        queries: Optional[Sequence[ExpansionQuery]] = None,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
    ) -> Dict[str, Any]:
        """下载 V3 负样本扩展池（高 GC 放线菌、低 GC/古菌染色体、大型质粒、非噬菌体病毒）。"""
        return self._run_expansion_pool(
            client=self._neg_client,
            target_count=target_count,
            queries=list(queries or NEGATIVE_EXPANSION_QUERIES),
            expect_phage=False,
            progress_cb=progress_cb,
        )

    def download_rare_phage_expansion(
        self,
        *,
        target_count: int = 160,
        queries: Optional[Sequence[ExpansionQuery]] = None,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
    ) -> Dict[str, Any]:
        """下载 V3 稀缺非有尾噬菌体正样本扩展池（Microviridae/Inoviridae/Leviviricetes/Tectiviridae）。"""
        return self._run_expansion_pool(
            client=self._pos_client,
            target_count=target_count,
            queries=list(queries or RARE_PHAGE_EXPANSION_QUERIES),
            expect_phage=True,
            progress_cb=progress_cb,
        )
