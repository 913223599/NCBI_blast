# -*- coding: utf-8 -*-
"""
NCBI RefSeq 噬菌体高质量基因组（GBK + FASTA）分层检索与断点续传下载器

设计要点：
1. 分层跨宿主抽样检索，防止默认按时间倒序导致样本高度集中在单一宿主或单篇测序论文；
2. 采用 gbwithparts 格式下载后，流式分批解析并即时原子落盘 .gbk 与 .fasta，不在内存中囤积大批量记录；
3. 支持 Checkpoint 断点保护：记录已处理 Accession 与状态，支持中断后无缝接续与按需增量扩充；
4. 遵循 NCBI E-utilities 速率限制与指数退避重试，强制使用 UTF-8 编码。
"""
import io
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import requests
from Bio import SeqIO

from .validator import _assess_phage_identity, _extract_host

logger = logging.getLogger("utils.phage_dataset.downloader")

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# 分层跨宿主与跨分类检索配置：(分组标签, 检索词, 默认占比权重)
STRATIFIED_HOST_QUERIES: List[Tuple[str, str, float]] = [
    ("Escherichia", "txid2731619[Organism:exp] AND Escherichia[All Fields] AND complete genome[Title] AND srcdb_refseq[PROP]", 0.13),
    ("Salmonella", "txid2731619[Organism:exp] AND Salmonella[All Fields] AND complete genome[Title] AND srcdb_refseq[PROP]", 0.09),
    ("Pseudomonas", "txid2731619[Organism:exp] AND Pseudomonas[All Fields] AND complete genome[Title] AND srcdb_refseq[PROP]", 0.09),
    ("Klebsiella", "txid2731619[Organism:exp] AND Klebsiella[All Fields] AND complete genome[Title] AND srcdb_refseq[PROP]", 0.08),
    ("Staphylococcus", "txid2731619[Organism:exp] AND Staphylococcus[All Fields] AND complete genome[Title] AND srcdb_refseq[PROP]", 0.06),
    ("Bacillus", "txid2731619[Organism:exp] AND Bacillus[All Fields] AND complete genome[Title] AND srcdb_refseq[PROP]", 0.06),
    ("Mycobacterium", "txid2731619[Organism:exp] AND Mycobacterium[All Fields] AND complete genome[Title] AND srcdb_refseq[PROP]", 0.08),
    ("Vibrio", "txid2731619[Organism:exp] AND Vibrio[All Fields] AND complete genome[Title] AND srcdb_refseq[PROP]", 0.05),
    ("Acinetobacter", "txid2731619[Organism:exp] AND Acinetobacter[All Fields] AND complete genome[Title] AND srcdb_refseq[PROP]", 0.04),
    ("Streptococcus", "txid2731619[Organism:exp] AND Streptococcus[All Fields] AND complete genome[Title] AND srcdb_refseq[PROP]", 0.05),
    ("Enterococcus", "txid2731619[Organism:exp] AND Enterococcus[All Fields] AND complete genome[Title] AND srcdb_refseq[PROP]", 0.04),
    ("Listeria", "txid2731619[Organism:exp] AND Listeria[All Fields] AND complete genome[Title] AND srcdb_refseq[PROP]", 0.03),
    ("Non_Caudoviricetes_Phages", "(txid10841[Organism:exp] OR txid10860[Organism:exp] OR txid10656[Organism:exp] OR txid2842243[Organism:exp] OR txid10877[Organism:exp] OR txid10659[Organism:exp]) AND complete genome[Title] AND srcdb_refseq[PROP]", 0.06),
    ("General_Caudoviricetes", "txid2731619[Organism:exp] AND complete genome[Title] AND srcdb_refseq[PROP] AND 3000:600000[SLEN]", 0.14),
]

# 分级补齐检索词（当分层交错采样未达缓冲上限时按优先级分页补齐）
FALLBACK_PHAGE_QUERIES: List[Tuple[str, str]] = [
    ("General_Caudoviricetes", "txid2731619[Organism:exp] AND complete genome[Title] AND srcdb_refseq[PROP]"),
    ("RefSeq_All_Phage_Taxa", "(txid2731619[Organism:exp] OR txid10841[Organism:exp] OR txid10860[Organism:exp] OR txid10656[Organism:exp] OR txid2842243[Organism:exp] OR txid10877[Organism:exp] OR txid10659[Organism:exp]) AND complete genome[Title] AND srcdb_refseq[PROP]"),
    ("RefSeq_Phage_Title", "(phage[Title] OR bacteriophage[Title]) AND complete genome[Title] AND srcdb_refseq[PROP] AND Viruses[Organism]"),
]

SAFE_ACCESSION_RE = re.compile(r"[^A-Za-z0-9._-]")


def sanitize_accession(acc: str) -> str:
    """将 Accession 清洗为安全文件名。"""
    cleaned = SAFE_ACCESSION_RE.sub("_", (acc or "").strip())
    return cleaned or "unknown_record"


def atomic_write_text(path: Path, content: str) -> None:
    """原子写 UTF-8 文本文件，防止写一半中断损坏产物。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


def split_genbank_entries(raw_gbk_text: str) -> List[str]:
    """将合并的 GenBank 多记录文本按标准 '//' 记录边界切分为单株文本列表。"""
    entries: List[str] = []
    current_lines: List[str] = []
    for line in raw_gbk_text.splitlines():
        if not current_lines and not line.strip():
            continue
        current_lines.append(line)
        if line.strip() == "//":
            entry = "\n".join(current_lines) + "\n"
            if entry.lstrip().startswith("LOCUS") and "ORIGIN" in entry:
                entries.append(entry)
            current_lines = []
    return entries


class PhageDatasetDownloader:
    """NCBI 噬菌体数据集分层批量下载器（支持分片落盘与 Checkpoint 断点保护）。"""

    def __init__(
        self,
        data_dir: Path,
        *,
        email: str = "phage_dataset@localhost",
        api_key: Optional[str] = None,
        batch_size: int = 20,
        min_length_bp: int = 3000,
        max_length_bp: int = 1000000,
        request_timeout: int = 60,
        retry_backoff_base: float = 1.5,
        session: Optional[requests.Session] = None,
    ):
        self.data_dir = Path(data_dir).resolve()
        self.fasta_dir = self.data_dir / "fasta"
        self.gbk_dir = self.data_dir / "gbk"
        self.meta_dir = self.data_dir / "meta"
        self.fasta_dir.mkdir(parents=True, exist_ok=True)
        self.gbk_dir.mkdir(parents=True, exist_ok=True)
        self.meta_dir.mkdir(parents=True, exist_ok=True)

        self.checkpoint_path = self.meta_dir / "download_checkpoint.json"
        self.email = email
        self.api_key = api_key
        self.batch_size = max(1, min(batch_size, 50))
        self.min_length_bp = min_length_bp
        self.max_length_bp = max_length_bp
        self.request_timeout = request_timeout
        self.retry_backoff_base = retry_backoff_base
        self.session = session or requests.Session()
        self._min_interval = 0.15 if api_key else 0.42
        self._last_req_ts = 0.0

    def _throttle(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_req_ts
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_req_ts = time.monotonic()

    def _request_with_retry(self, url: str, params: Dict[str, Any], max_retries: int = 4) -> requests.Response:
        """带速率控制与指数退避重试的 NCBI HTTP GET 请求。"""
        base_params = dict(params)
        base_params.setdefault("email", self.email)
        base_params.setdefault("tool", "ncbi_blast_pro_phage_dataset")
        if self.api_key:
            base_params["api_key"] = self.api_key

        last_exc: Optional[Exception] = None
        for attempt in range(max_retries):
            self._throttle()
            try:
                resp = self.session.get(url, params=base_params, timeout=self.request_timeout)
                if resp.status_code in (429, 500, 502, 503, 504):
                    wait_sec = (2 ** attempt) * self.retry_backoff_base
                    logger.warning(f"NCBI 返回状态码 {resp.status_code}，{wait_sec:.1f}s 后重试...")
                    if wait_sec > 0:
                        time.sleep(wait_sec)
                    continue
                resp.raise_for_status()
                return resp
            except requests.RequestException as exc:
                last_exc = exc
                wait_sec = (2 ** attempt) * self.retry_backoff_base
                logger.warning(f"网络请求异常 ({attempt + 1}/{max_retries}): {exc}，{wait_sec:.1f}s 后重试")
                if wait_sec > 0:
                    time.sleep(wait_sec)

        raise RuntimeError(f"请求 NCBI E-utilities 失败（已重试 {max_retries} 次）: {last_exc}")

    def load_checkpoint(self) -> Dict[str, Any]:
        """读取断点记录，并扫描磁盘现有成对文件以保证目录状态自洽。"""
        data: Dict[str, Any] = {
            "version": 1,
            "updated_at": "",
            "saved_records": {},
            "skipped_ids": {},
            "uid_to_accession": {},
        }
        if self.checkpoint_path.exists():
            try:
                loaded = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data.update(loaded)
            except Exception as exc:
                logger.warning(f"读取断点文件失败，将从磁盘已有文件重建: {exc}")

        # 扫盘同步：确认记录中的文件确实存在于 fasta/ 与 gbk/ 中
        valid_saved: Dict[str, Dict[str, Any]] = {}
        saved_raw = data.get("saved_records", {})
        if isinstance(saved_raw, dict):
            for acc, meta in saved_raw.items():
                clean_acc = sanitize_accession(acc)
                if (self.gbk_dir / f"{clean_acc}.gbk").exists() and (self.fasta_dir / f"{clean_acc}.fasta").exists():
                    valid_saved[acc] = meta

        # 补充手工放入目录或断点未及时记录的完整双文件
        for gbk_file in self.gbk_dir.glob("*.gbk"):
            stem = gbk_file.stem
            fasta_file = self.fasta_dir / f"{stem}.fasta"
            if fasta_file.exists() and stem not in valid_saved:
                valid_saved[stem] = {
                    "accession": stem,
                    "source_group": "existing_local",
                    "saved_at": datetime.now().isoformat(timespec="seconds"),
                }

        data["saved_records"] = valid_saved
        return data

    def save_checkpoint(self, state: Dict[str, Any]) -> None:
        state["updated_at"] = datetime.now().isoformat(timespec="seconds")
        atomic_write_text(self.checkpoint_path, json.dumps(state, ensure_ascii=False, indent=2))

    def search_stratified_uids(
        self,
        target_count: int,
        queries: Optional[Sequence[Tuple[str, str, float]]] = None,
    ) -> List[Tuple[str, str]]:
        """
        按宿主分层检索候选 NCBI nuccore UID，去重并以 Round-Robin 交错排列返回 [(uid, source_group), ...]，
        确保任意前缀批次均具备跨宿主多样性。
        """
        host_queries = list(queries or STRATIFIED_HOST_QUERIES)
        grouped_buckets: List[List[Tuple[str, str]]] = []
        seen_uids = set()

        # 适当超采 25% 作为缓冲，以防个别过短或缺失注释的记录被过滤
        pool_target = int(target_count * 1.25) + 10

        for group_name, term, weight in host_queries:
            quota = max(5, int(round(pool_target * weight)))
            req_retmax = min(max(quota * 2, quota + 20), 2500)
            resp = self._request_with_retry(
                f"{EUTILS_BASE}/esearch.fcgi",
                {
                    "db": "nuccore",
                    "term": term,
                    "retmax": req_retmax,
                    "sort": "relevance",
                    "retmode": "json",
                },
            )
            payload = resp.json().get("esearchresult", {})
            id_list = payload.get("idlist", []) or []
            bucket: List[Tuple[str, str]] = []
            for uid in id_list:
                uid_str = str(uid).strip()
                if not uid_str or uid_str in seen_uids:
                    continue
                seen_uids.add(uid_str)
                bucket.append((uid_str, group_name))
                if len(bucket) >= quota:
                    break
            grouped_buckets.append(bucket)
            logger.info(f"分层检索 [{group_name}]: 候选总数 {payload.get('count', 0)}, 本组纳入 {len(bucket)} 条")

        # Round-Robin 轮转交错合并各宿主分组
        selected: List[Tuple[str, str]] = []
        max_len = max((len(b) for b in grouped_buckets), default=0)
        for i in range(max_len):
            for b in grouped_buckets:
                if i < len(b):
                    selected.append(b[i])

        # 若去重后仍未达到缓冲总量，按优先级分页从权威 RefSeq 噬菌体全库补齐
        if len(selected) < pool_target:
            page_size = 2000
            for fb_group, fb_term in FALLBACK_PHAGE_QUERIES:
                if len(selected) >= pool_target:
                    break
                retstart = 0
                while len(selected) < pool_target:
                    resp = self._request_with_retry(
                        f"{EUTILS_BASE}/esearch.fcgi",
                        {
                            "db": "nuccore",
                            "term": fb_term,
                            "retstart": retstart,
                            "retmax": page_size,
                            "retmode": "json",
                        },
                    )
                    es_res = resp.json().get("esearchresult", {})
                    page_ids = es_res.get("idlist", []) or []
                    try:
                        total_avail = int(es_res.get("count", 0))
                    except (TypeError, ValueError):
                        total_avail = len(page_ids)

                    if not page_ids:
                        break

                    for uid in page_ids:
                        uid_str = str(uid).strip()
                        if uid_str and uid_str not in seen_uids:
                            seen_uids.add(uid_str)
                            selected.append((uid_str, fb_group))
                            if len(selected) >= pool_target:
                                break

                    retstart += len(page_ids)
                    if retstart >= total_avail or len(page_ids) < page_size:
                        break

        return selected

    def _persist_gbk_entry(
        self,
        entry_text: str,
        source_group: str,
        uid: str,
        state: Dict[str, Any],
    ) -> Optional[str]:
        """解析单条 GenBank 记录并即时同步落盘为 .gbk 和 .fasta，返回成功保存的 Accession。"""
        try:
            rec = SeqIO.read(io.StringIO(entry_text), "genbank")
        except Exception as exc:
            logger.debug(f"跳过不可解析 GenBank 记录 (uid={uid}): {exc}")
            return None

        acc = sanitize_accession(rec.id or rec.name)
        seq_len = len(rec.seq)
        if seq_len < self.min_length_bp or seq_len > self.max_length_bp:
            state["skipped_ids"][uid] = f"length_out_of_range:{seq_len}"
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
        is_phage, _, tax_group, _ = _assess_phage_identity(
            taxonomy_tokens=tax_list,
            organism=str(rec.annotations.get("organism") or rec.id or ""),
            description=str(rec.description or ""),
            host=_extract_host(rec),
            product_texts=product_texts,
        )
        if not is_phage:
            state["skipped_ids"][uid] = f"non_phage_record:{tax_group}"
            return None

        gbk_path = self.gbk_dir / f"{acc}.gbk"
        fasta_path = self.fasta_dir / f"{acc}.fasta"

        fasta_buf = io.StringIO()
        SeqIO.write(rec, fasta_buf, "fasta")

        atomic_write_text(gbk_path, entry_text)
        atomic_write_text(fasta_path, fasta_buf.getvalue())

        state["saved_records"][acc] = {
            "accession": acc,
            "uid": uid,
            "source_group": source_group,
            "length_bp": seq_len,
            "cds_count": cds_count,
            "description": (rec.description or "")[:200],
            "saved_at": datetime.now().isoformat(timespec="seconds"),
        }
        if uid:
            state["uid_to_accession"][uid] = acc
        return acc

    def download_batch_dataset(
        self,
        target_count: int = 500,
        queries: Optional[Sequence[Tuple[str, str, float]]] = None,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
    ) -> Dict[str, Any]:
        """
        执行分层检索与分片批量下载，直到有效双文件数达到 target_count 或候选耗尽。
        每下载完一个 batch 即时拆分落盘并持久化 Checkpoint。
        """
        state = self.load_checkpoint()
        already_saved = len(state["saved_records"])
        logger.info(f"断点检查完成: 本地已就绪 {already_saved} 株完整噬菌体，目标总数 {target_count}")

        if already_saved >= target_count:
            return {
                "target_count": target_count,
                "saved_count": already_saved,
                "newly_downloaded": 0,
                "skipped_count": len(state.get("skipped_ids", {})),
                "checkpoint_path": str(self.checkpoint_path),
            }

        candidates = self.search_stratified_uids(target_count=max(target_count, target_count - already_saved + 80), queries=queries)
        done_uids = set(state.get("uid_to_accession", {}).keys()) | set(state.get("skipped_ids", {}).keys())
        pending = [(uid, grp) for uid, grp in candidates if uid not in done_uids]

        newly_downloaded = 0
        for start in range(0, len(pending), self.batch_size):
            if len(state["saved_records"]) >= target_count:
                break

            batch = pending[start:start + self.batch_size]
            batch_uids = [u for u, _ in batch]
            uid_group_map = dict(batch)

            resp = self._request_with_retry(
                f"{EUTILS_BASE}/efetch.fcgi",
                {
                    "db": "nuccore",
                    "id": ",".join(batch_uids),
                    "rettype": "gbwithparts",
                    "retmode": "text",
                },
            )
            entries = split_genbank_entries(resp.text)

            for idx, entry_text in enumerate(entries):
                if len(state["saved_records"]) >= target_count:
                    break
                # 根据每条记录尽量匹配回原始 UID（若记录数对应）
                fallback_uid = batch_uids[idx] if idx < len(batch_uids) else ""
                group_name = uid_group_map.get(fallback_uid, "General_Caudoviricetes")
                acc = self._persist_gbk_entry(entry_text, group_name, fallback_uid, state)
                if acc:
                    newly_downloaded += 1

            # 即使部分记录未能匹配，也标记已请求的 UID 以防止死循环重复请求
            for uid in batch_uids:
                if uid not in state["uid_to_accession"] and uid not in state["skipped_ids"]:
                    state["skipped_ids"][uid] = "batch_processed_or_filtered"

            self.save_checkpoint(state)
            current_total = len(state["saved_records"])
            logger.info(f"分片落盘进度: {current_total}/{target_count} (本批新增后累计新增 {newly_downloaded})")
            if progress_cb:
                progress_cb(current_total, target_count, f"已保存 {current_total}/{target_count} 株")

        return {
            "target_count": target_count,
            "saved_count": len(state["saved_records"]),
            "newly_downloaded": newly_downloaded,
            "skipped_count": len(state.get("skipped_ids", {})),
            "checkpoint_path": str(self.checkpoint_path),
        }
