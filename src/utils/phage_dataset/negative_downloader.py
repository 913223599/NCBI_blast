# -*- coding: utf-8 -*-
"""
配套负样本（细菌质粒、代表性细菌染色体、非噬菌体病毒）分层检索与断点下载器

设计要点：
1. 采用分类型、跨宿主分层抽样（Plasmid / Bacterial Chromosome / Non-Phage Virus）；
2. 对大型细菌染色体自动采用小批次（batch_size=2）与长超时拉取，防止单次响应体过大导致超时与内存暴涨；
3. 下载入库前立即调用反向噬菌体排异校验（_assess_phage_identity），拦截任何误混入的游离噬菌体；
4. 每批次解析后即刻原子落盘 .gbk + .fasta 并持久化 Checkpoint，支持中断无损续传。
"""
import io
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import requests
from Bio import SeqIO

from .ncbi_downloader import (
    EUTILS_BASE,
    atomic_write_text,
    sanitize_accession,
    split_genbank_entries,
)
from .validator import _assess_phage_identity, _extract_host

logger = logging.getLogger("utils.phage_dataset.negative_downloader")

# 负样本分层配置：(分组名, 类别, NCBI检索式, 默认权重, 单批请求条数)
NEGATIVE_STRATA_QUERIES: List[Tuple[str, str, str, float, int]] = [
    # 1. 细菌质粒（约占 63%，重点作为携带转移/整合/复制蛋白的硬负例）
    ("Plasmid_Escherichia", "plasmid", "plasmid[Title] AND complete sequence[Title] AND srcdb_refseq[PROP] AND Escherichia[Organism] AND 3000:400000[SLEN]", 0.10, 20),
    ("Plasmid_Klebsiella", "plasmid", "plasmid[Title] AND complete sequence[Title] AND srcdb_refseq[PROP] AND Klebsiella[Organism] AND 3000:400000[SLEN]", 0.08, 20),
    ("Plasmid_Salmonella", "plasmid", "plasmid[Title] AND complete sequence[Title] AND srcdb_refseq[PROP] AND Salmonella[Organism] AND 3000:400000[SLEN]", 0.07, 20),
    ("Plasmid_Pseudomonas", "plasmid", "plasmid[Title] AND complete sequence[Title] AND srcdb_refseq[PROP] AND Pseudomonas[Organism] AND 3000:400000[SLEN]", 0.06, 20),
    ("Plasmid_Staphylococcus", "plasmid", "plasmid[Title] AND complete sequence[Title] AND srcdb_refseq[PROP] AND Staphylococcus[Organism] AND 3000:400000[SLEN]", 0.06, 20),
    ("Plasmid_Bacillus", "plasmid", "plasmid[Title] AND complete sequence[Title] AND srcdb_refseq[PROP] AND Bacillus[Organism] AND 3000:400000[SLEN]", 0.06, 20),
    ("Plasmid_Enterococcus", "plasmid", "plasmid[Title] AND complete sequence[Title] AND srcdb_refseq[PROP] AND Enterococcus[Organism] AND 3000:400000[SLEN]", 0.05, 20),
    ("Plasmid_Acinetobacter", "plasmid", "plasmid[Title] AND complete sequence[Title] AND srcdb_refseq[PROP] AND Acinetobacter[Organism] AND 3000:400000[SLEN]", 0.05, 20),
    ("Plasmid_Vibrio", "plasmid", "plasmid[Title] AND complete sequence[Title] AND srcdb_refseq[PROP] AND Vibrio[Organism] AND 3000:400000[SLEN]", 0.05, 20),
    ("Plasmid_General", "plasmid", "plasmid[Title] AND complete sequence[Title] AND srcdb_refseq[PROP] AND Bacteria[Organism] AND 3000:400000[SLEN]", 0.05, 20),
    # 2. 代表性细菌完整染色体（约占 23%，小批拉取以控制带宽与内存峰值）
    ("BactChrom_Escherichia", "bacterial_chromosome", "complete genome[Title] AND srcdb_refseq[PROP] AND Escherichia[Organism] AND 500000:5500000[SLEN] NOT plasmid[Title]", 0.025, 2),
    ("BactChrom_Salmonella", "bacterial_chromosome", "complete genome[Title] AND srcdb_refseq[PROP] AND Salmonella[Organism] AND 500000:5500000[SLEN] NOT plasmid[Title]", 0.020, 2),
    ("BactChrom_Pseudomonas", "bacterial_chromosome", "complete genome[Title] AND srcdb_refseq[PROP] AND Pseudomonas[Organism] AND 500000:5500000[SLEN] NOT plasmid[Title]", 0.020, 2),
    ("BactChrom_Klebsiella", "bacterial_chromosome", "complete genome[Title] AND srcdb_refseq[PROP] AND Klebsiella[Organism] AND 500000:5500000[SLEN] NOT plasmid[Title]", 0.020, 2),
    ("BactChrom_Staphylococcus", "bacterial_chromosome", "complete genome[Title] AND srcdb_refseq[PROP] AND Staphylococcus[Organism] AND 500000:5500000[SLEN] NOT plasmid[Title]", 0.020, 2),
    ("BactChrom_Bacillus", "bacterial_chromosome", "complete genome[Title] AND srcdb_refseq[PROP] AND Bacillus[Organism] AND 500000:5500000[SLEN] NOT plasmid[Title]", 0.020, 2),
    ("BactChrom_Mycobacterium", "bacterial_chromosome", "complete genome[Title] AND srcdb_refseq[PROP] AND Mycobacterium[Organism] AND 500000:5500000[SLEN] NOT plasmid[Title]", 0.020, 2),
    ("BactChrom_Vibrio", "bacterial_chromosome", "complete genome[Title] AND srcdb_refseq[PROP] AND Vibrio[Organism] AND 500000:5500000[SLEN] NOT plasmid[Title]", 0.017, 2),
    ("BactChrom_Acinetobacter", "bacterial_chromosome", "complete genome[Title] AND srcdb_refseq[PROP] AND Acinetobacter[Organism] AND 500000:5500000[SLEN] NOT plasmid[Title]", 0.017, 2),
    ("BactChrom_Streptococcus", "bacterial_chromosome", "complete genome[Title] AND srcdb_refseq[PROP] AND Streptococcus[Organism] AND 500000:5500000[SLEN] NOT plasmid[Title]", 0.017, 2),
    ("BactChrom_Enterococcus", "bacterial_chromosome", "complete genome[Title] AND srcdb_refseq[PROP] AND Enterococcus[Organism] AND 500000:5500000[SLEN] NOT plasmid[Title]", 0.017, 2),
    ("BactChrom_Listeria", "bacterial_chromosome", "complete genome[Title] AND srcdb_refseq[PROP] AND Listeria[Organism] AND 500000:5500000[SLEN] NOT plasmid[Title]", 0.017, 2),
    # 3. 非噬菌体病毒硬负例（真核 DNA/RNA 病毒 + 古菌病毒，约占 14%）
    ("NonPhageVirus_Euk_DNA", "non_phage_virus", "(Adenoviridae[Organism] OR Herpesvirales[Organism] OR Baculoviridae[Organism] OR Geminiviridae[Organism] OR Papillomaviridae[Organism]) AND complete genome[Title] AND srcdb_refseq[PROP] AND 3000:300000[SLEN]", 0.065, 15),
    ("NonPhageVirus_Euk_RNA", "non_phage_virus", "(Coronaviridae[Organism] OR Flaviviridae[Organism] OR Picornavirales[Organism] OR Solemoviridae[Organism]) AND complete genome[Title] AND srcdb_refseq[PROP] AND 3000:100000[SLEN]", 0.045, 15),
    ("NonPhageVirus_Archaeal", "non_phage_virus", "(Fuselloviridae[Organism] OR Rudiviridae[Organism] OR Lipothrixviridae[Organism] OR Bicaudaviridae[Organism]) AND complete genome[Title] AND srcdb_refseq[PROP] AND 3000:200000[SLEN]", 0.030, 15),
]


class NegativeDatasetDownloader:
    """NCBI 配套负样本分层下载器（支持按类别分片、反向排异与断点续传）。"""

    def __init__(
        self,
        data_dir: Path,
        *,
        email: str = "phage_dataset@localhost",
        api_key: Optional[str] = None,
        min_length_bp: int = 3000,
        max_length_bp: int = 6500000,
        request_timeout: int = 180,
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

        self.checkpoint_path = self.meta_dir / "negative_download_checkpoint.json"
        self.email = email
        self.api_key = api_key
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
        req_params = dict(params)
        req_params.setdefault("email", self.email)
        req_params.setdefault("tool", "phage_workbench_negative_dataset")
        if self.api_key:
            req_params.setdefault("api_key", self.api_key)

        last_err: Optional[Exception] = None
        for attempt in range(1, max_retries + 1):
            self._throttle()
            try:
                resp = self.session.get(url, params=req_params, timeout=self.request_timeout)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise RuntimeError(f"HTTP {resp.status_code}")
                resp.raise_for_status()
                return resp
            except Exception as exc:
                last_err = exc
                if attempt < max_retries and self.retry_backoff_base > 0:
                    time.sleep(self.retry_backoff_base ** attempt)
        raise RuntimeError(f"NCBI 请求连续失败 ({max_retries} 次): {last_err}")

    def load_checkpoint(self) -> Dict[str, Any]:
        if self.checkpoint_path.exists():
            try:
                data = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        else:
            data = {}

        data.setdefault("saved_records", {})
        data.setdefault("uid_to_accession", {})
        data.setdefault("skipped_ids", {})

        valid_saved: Dict[str, Any] = {}
        for acc, meta in data["saved_records"].items():
            fa = self.fasta_dir / f"{acc}.fasta"
            gb = self.gbk_dir / f"{acc}.gbk"
            if fa.exists() and gb.exists() and fa.stat().st_size > 0 and gb.stat().st_size > 0:
                valid_saved[acc] = meta

        for gb_file in self.gbk_dir.glob("*.gbk"):
            stem = gb_file.stem
            fa_file = self.fasta_dir / f"{stem}.fasta"
            if fa_file.exists() and stem not in valid_saved:
                valid_saved[stem] = {
                    "accession": stem,
                    "source_group": "existing_local",
                    "negative_category": "unknown",
                    "saved_at": datetime.now().isoformat(timespec="seconds"),
                }

        data["saved_records"] = valid_saved
        return data

    def save_checkpoint(self, state: Dict[str, Any]) -> None:
        state["updated_at"] = datetime.now().isoformat(timespec="seconds")
        atomic_write_text(self.checkpoint_path, json.dumps(state, ensure_ascii=False, indent=2))

    def search_stratified_candidates(
        self,
        target_count: int,
        queries: Optional[Sequence[Tuple[str, str, str, float, int]]] = None,
    ) -> List[Tuple[str, str, str, int]]:
        """
        检索各负样本分层候选 UID，按类别交错排列并返回 [(uid, group_name, category, batch_size), ...]。
        """
        strata = list(queries or NEGATIVE_STRATA_QUERIES)
        total_weight = sum(item[3] for item in strata) or 1.0
        pool_target = int(target_count * 1.25) + len(strata)

        seen_uids = set()
        buckets: List[List[Tuple[str, str, str, int]]] = []

        for group_name, category, term, weight, rec_batch_size in strata:
            quota = max(2, int(round(pool_target * (weight / total_weight))))
            resp = self._request_with_retry(
                f"{EUTILS_BASE}/esearch.fcgi",
                {
                    "db": "nuccore",
                    "term": term,
                    "retmax": min(max(quota * 2, quota + 20), 2500),
                    "sort": "relevance",
                    "retmode": "json",
                },
            )
            payload = resp.json().get("esearchresult", {})
            id_list = payload.get("idlist", []) or []
            bucket: List[Tuple[str, str, str, int]] = []
            for uid in id_list:
                uid_str = str(uid).strip()
                if not uid_str or uid_str in seen_uids:
                    continue
                seen_uids.add(uid_str)
                bucket.append((uid_str, group_name, category, rec_batch_size))
                if len(bucket) >= quota:
                    break
            buckets.append(bucket)
            logger.info(f"负样本检索 [{group_name}/{category}]: 候选总数 {payload.get('count', 0)}, 纳入 {len(bucket)} 条")

        # 交错合并，使不同类型样本在前缀中均匀分布，且同类批次可按 batch_size 调度
        ordered: List[Tuple[str, str, str, int]] = []
        max_len = max((len(b) for b in buckets), default=0)
        for i in range(max_len):
            for b in buckets:
                if i < len(b):
                    ordered.append(b[i])
        return ordered

    def _persist_negative_entry(
        self,
        entry_text: str,
        source_group: str,
        category: str,
        uid: str,
        state: Dict[str, Any],
    ) -> Optional[str]:
        """解析单条负样本 GenBank 记录，执行噬菌体排异预检后同步落盘 .gbk 与 .fasta。"""
        try:
            rec = SeqIO.read(io.StringIO(entry_text), "genbank")
        except Exception as exc:
            logger.debug(f"跳过不可解析负样本记录 (uid={uid}): {exc}")
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
        # 反向噬菌体过滤：绝不允许游离噬菌体混入负样本库
        is_phage, _, tax_group, _ = _assess_phage_identity(
            taxonomy_tokens=tax_list,
            organism=str(rec.annotations.get("organism") or rec.id or ""),
            description=str(rec.description or ""),
            host=_extract_host(rec),
            product_texts=product_texts,
        )
        if is_phage:
            state["skipped_ids"][uid] = f"phage_contamination_blocked:{tax_group}"
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
            "negative_category": category,
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
        target_count: int = 600,
        queries: Optional[Sequence[Tuple[str, str, str, float, int]]] = None,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
    ) -> Dict[str, Any]:
        """按分片自适应批次下载负样本至 target_count，支持断点续传。"""
        state = self.load_checkpoint()
        already_saved = len(state["saved_records"])
        logger.info(f"负样本断点检查完成: 本地已就绪 {already_saved} 条, 目标总数 {target_count}")

        if already_saved >= target_count:
            return {
                "target_count": target_count,
                "saved_count": already_saved,
                "newly_downloaded": 0,
                "skipped_count": len(state.get("skipped_ids", {})),
                "checkpoint_path": str(self.checkpoint_path),
            }

        candidates = self.search_stratified_candidates(
            target_count=max(target_count, target_count - already_saved + 40),
            queries=queries,
        )
        done_uids = set(state.get("uid_to_accession", {}).keys()) | set(state.get("skipped_ids", {}).keys())
        pending = [item for item in candidates if item[0] not in done_uids]

        # 按 batch_size 分组凑批（将细菌染色体的超小批次 2 与质粒批次 20 分别打包）
        batches: List[List[Tuple[str, str, str, int]]] = []
        small_buf: List[Tuple[str, str, str, int]] = []
        normal_buf: List[Tuple[str, str, str, int]] = []
        for item in pending:
            bsize = item[3]
            if bsize <= 4:
                small_buf.append(item)
                if len(small_buf) >= bsize:
                    batches.append(small_buf)
                    small_buf = []
            else:
                normal_buf.append(item)
                if len(normal_buf) >= bsize:
                    batches.append(normal_buf)
                    normal_buf = []
        if small_buf:
            batches.append(small_buf)
        if normal_buf:
            batches.append(normal_buf)

        # 交错调度小批（细菌染色体）与常规批（质粒/病毒），保障进度平稳推进
        small_batches = [b for b in batches if len(b) <= 4 and b[0][3] <= 4]
        normal_batches = [b for b in batches if not (len(b) <= 4 and b[0][3] <= 4)]
        scheduled_batches: List[List[Tuple[str, str, str, int]]] = []
        max_b = max(len(small_batches), len(normal_batches))
        for i in range(max_b):
            if i < len(normal_batches):
                scheduled_batches.append(normal_batches[i])
            if i < len(small_batches):
                scheduled_batches.append(small_batches[i])

        newly_downloaded = 0
        for batch in scheduled_batches:
            if len(state["saved_records"]) >= target_count:
                break

            batch_uids = [item[0] for item in batch]
            uid_meta = {item[0]: (item[1], item[2]) for item in batch}
            try:
                resp = self._request_with_retry(
                    f"{EUTILS_BASE}/efetch.fcgi",
                    {
                        "db": "nuccore",
                        "id": ",".join(batch_uids),
                        "rettype": "gbwithparts",
                        "retmode": "text",
                    },
                )
            except Exception as exc:
                logger.warning(f"负样本批次拉取失败（跳过本批 {len(batch_uids)} 条继续）: {exc}")
                for uid in batch_uids:
                    state["skipped_ids"][uid] = f"batch_fetch_error:{exc}"
                self.save_checkpoint(state)
                continue

            entries = split_genbank_entries(resp.text)
            for idx, entry_text in enumerate(entries):
                if len(state["saved_records"]) >= target_count:
                    break
                fb_uid = batch_uids[idx] if idx < len(batch_uids) else ""
                grp, cat = uid_meta.get(fb_uid, ("Negative_General", "unknown"))
                acc = self._persist_negative_entry(entry_text, grp, cat, fb_uid, state)
                if acc:
                    newly_downloaded += 1

            for uid in batch_uids:
                if uid not in state["uid_to_accession"] and uid not in state["skipped_ids"]:
                    state["skipped_ids"][uid] = "batch_processed_or_filtered"

            self.save_checkpoint(state)
            current_total = len(state["saved_records"])
            logger.info(f"负样本分片落盘进度: {current_total}/{target_count} (本轮新增 {newly_downloaded})")
            if progress_cb:
                progress_cb(current_total, target_count, f"已保存负样本 {current_total}/{target_count}")

        return {
            "target_count": target_count,
            "saved_count": len(state["saved_records"]),
            "newly_downloaded": newly_downloaded,
            "skipped_count": len(state.get("skipped_ids", {})),
            "checkpoint_path": str(self.checkpoint_path),
        }

