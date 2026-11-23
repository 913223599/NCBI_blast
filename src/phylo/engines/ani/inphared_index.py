# -*- coding: utf-8 -*-
"""
InpharedIndex - 本地 INPHARED 噬菌体参考库 SQLite 快速索引
解析 database/pharokka_db/9Aug2025_data.tsv 并缓存至 results/phylo/cache/inphared_index.db。
"""
import csv
import logging
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from ...runtime.tool_registry import get_project_root

logger = logging.getLogger("phylo.inphared_index")


@dataclass
class InpharedRecord:
    accession: str
    description: str = ""
    genome_length: int = 0
    gc_content: float = 0.0
    host: str = ""
    lowest_taxa: str = ""
    genus: str = ""
    subfamily: str = ""
    family: str = ""
    order_name: str = ""
    class_name: str = ""
    realm: str = ""

    @property
    def is_ictv_classified(self) -> bool:
        g = (self.genus or "").strip()
        return bool(g) and g.lower() not in ("unclassified", "na", "none", "-")


def _clean_tax(val: Optional[str]) -> str:
    txt = (val or "").strip()
    if txt.lower() in ("", "unclassified", "na", "none", "nan", "-"):
        return ""
    return txt


def _safe_int(val: Optional[str], default: int = 0) -> int:
    try:
        return int(float(val or default))
    except (TypeError, ValueError):
        return default


def _safe_float(val: Optional[str], default: float = 0.0) -> float:
    try:
        return float(val or default)
    except (TypeError, ValueError):
        return default


class InpharedIndex:
    """INPHARED 37,563+ 噬菌体元数据检索中心。"""

    def __init__(
        self,
        tsv_path: Optional[Path] = None,
        db_path: Optional[Path] = None,
    ) -> None:
        root = get_project_root()
        self.tsv_path = tsv_path or (root / "database" / "pharokka_db" / "9Aug2025_data.tsv")
        self.msh_path = self.tsv_path.parent / "9Aug2025_genomes.fa.msh"
        self.db_path = db_path or (root / "results" / "phylo" / "cache" / "inphared_index.db")
        self._lock = threading.Lock()
        self._ready = False

    def is_available(self) -> bool:
        return self.tsv_path.is_file()

    def ensure_built(self) -> None:
        if self._ready and self.db_path.is_file():
            return
        with self._lock:
            if not self.tsv_path.is_file():
                raise FileNotFoundError(f"未找到 INPHARED 元数据文件: {self.tsv_path}")
            src_mtime = int(self.tsv_path.stat().st_mtime)
            if self.db_path.is_file():
                try:
                    with sqlite3.connect(str(self.db_path), timeout=10) as conn:
                        row = conn.execute(
                            "SELECT value FROM meta WHERE key = 'src_mtime'"
                        ).fetchone()
                        cnt = conn.execute("SELECT COUNT(*) FROM inphared").fetchone()
                        if row and int(row[0]) == src_mtime and cnt and int(cnt[0]) > 0:
                            self._ready = True
                            return
                except sqlite3.Error:
                    pass
            self._rebuild_sqlite(src_mtime)
            self._ready = True

    def _rebuild_sqlite(self, src_mtime: int) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_db = self.db_path.with_suffix(".db.tmp")
        if tmp_db.exists():
            tmp_db.unlink()

        conn = sqlite3.connect(str(tmp_db), timeout=30)
        try:
            conn.execute("PRAGMA journal_mode=OFF")
            conn.execute("PRAGMA synchronous=OFF")
            conn.execute(
                """
                CREATE TABLE meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE inphared (
                    accession TEXT PRIMARY KEY,
                    description TEXT,
                    genome_length INTEGER,
                    gc_content REAL,
                    host TEXT,
                    lowest_taxa TEXT,
                    genus TEXT,
                    subfamily TEXT,
                    family TEXT,
                    order_name TEXT,
                    class_name TEXT,
                    realm TEXT
                )
                """
            )

            batch: List[tuple] = []
            with open(self.tsv_path, "r", encoding="utf-8", errors="replace", newline="") as fh:
                reader = csv.DictReader(fh, delimiter="\t")
                for row in reader:
                    acc = (row.get("Accession") or "").strip()
                    if not acc:
                        continue
                    batch.append(
                        (
                            acc,
                            (row.get("Description") or "").strip(),
                            _safe_int(row.get("Genome Length (bp)"), 0),
                            _safe_float(row.get("molGC (%)"), 0.0),
                            _clean_tax(row.get("Host")),
                            _clean_tax(row.get("Lowest Taxa")),
                            _clean_tax(row.get("Genus")),
                            _clean_tax(row.get("Sub-family")),
                            _clean_tax(row.get("Family")),
                            _clean_tax(row.get("Order")),
                            _clean_tax(row.get("Class")),
                            _clean_tax(row.get("Realm")),
                        )
                    )
                    if len(batch) >= 2000:
                        conn.executemany(
                            "INSERT OR REPLACE INTO inphared VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                            batch,
                        )
                        batch.clear()
            if batch:
                conn.executemany(
                    "INSERT OR REPLACE INTO inphared VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    batch,
                )

            conn.execute("CREATE INDEX idx_inphared_genus ON inphared(genus)")
            conn.execute("CREATE INDEX idx_inphared_family ON inphared(family)")
            conn.execute("CREATE INDEX idx_inphared_order ON inphared(order_name)")
            conn.execute("CREATE INDEX idx_inphared_host ON inphared(host)")
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('src_mtime', ?)",
                (str(src_mtime),),
            )
            conn.commit()
        finally:
            conn.close()

        tmp_db.replace(self.db_path)
        logger.info(f"INPHARED SQLite 索引构建完成: {self.db_path}")

    @staticmethod
    def _row_to_record(row: tuple) -> InpharedRecord:
        return InpharedRecord(
            accession=row[0],
            description=row[1] or "",
            genome_length=int(row[2] or 0),
            gc_content=float(row[3] or 0.0),
            host=row[4] or "",
            lowest_taxa=row[5] or "",
            genus=row[6] or "",
            subfamily=row[7] or "",
            family=row[8] or "",
            order_name=row[9] or "",
            class_name=row[10] or "",
            realm=row[11] or "",
        )

    def get_by_accessions(self, accessions: Iterable[str]) -> Dict[str, InpharedRecord]:
        if not self.is_available():
            return {}
        self.ensure_built()
        clean_list = []
        base_map: Dict[str, str] = {}
        for raw in accessions:
            key = (raw or "").strip()
            if not key:
                continue
            clean_list.append(key)
            # 兼容 NC_005859.1 与 NC_005859 去版本号查询
            base = key.split(".")[0]
            base_map.setdefault(base, key)

        if not clean_list:
            return {}

        probe_keys = list(dict.fromkeys(clean_list + list(base_map.keys())))
        out: Dict[str, InpharedRecord] = {}
        with sqlite3.connect(str(self.db_path), timeout=15) as conn:
            for i in range(0, len(probe_keys), 500):
                chunk = probe_keys[i : i + 500]
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"SELECT * FROM inphared WHERE accession IN ({placeholders})",
                    chunk,
                ).fetchall()
                for row in rows:
                    rec = self._row_to_record(row)
                    out[rec.accession] = rec
                    if rec.accession in base_map:
                        out[base_map[rec.accession]] = rec
        return out

    def find_ictv_representatives(
        self,
        genera: Sequence[str],
        families: Sequence[str],
        exclude_accessions: Sequence[str] = (),
        per_genus: int = 3,
        max_total: int = 60,
    ) -> List[InpharedRecord]:
        """为目标属及同科邻近属抽样正式 ICTV 分类代表株。"""
        if not self.is_available():
            return []
        self.ensure_built()
        excl = set(exclude_accessions) | {x.split(".")[0] for x in exclude_accessions}
        selected: List[InpharedRecord] = []
        seen: set[str] = set()

        with sqlite3.connect(str(self.db_path), timeout=15) as conn:
            # 1. 目标属代表株
            for genus in genera:
                g = _clean_tax(genus)
                if not g:
                    continue
                rows = conn.execute(
                    """
                    SELECT * FROM inphared
                    WHERE genus = ? AND genome_length >= 3000
                    ORDER BY CASE WHEN accession LIKE 'NC_%' THEN 0 ELSE 1 END, genome_length DESC
                    LIMIT ?
                    """,
                    (g, per_genus * 3),
                ).fetchall()
                added_g = 0
                for row in rows:
                    rec = self._row_to_record(row)
                    if rec.accession in excl or rec.accession in seen:
                        continue
                    seen.add(rec.accession)
                    selected.append(rec)
                    added_g += 1
                    if added_g >= per_genus or len(selected) >= max_total:
                        break

            # 2. 同科邻近属代表株（每个邻近属 1-2 条）
            if len(selected) < max_total:
                genus_set = {_clean_tax(g) for g in genera if _clean_tax(g)}
                for fam in families:
                    f = _clean_tax(fam)
                    if not f:
                        continue
                    rows = conn.execute(
                        """
                        SELECT * FROM inphared
                        WHERE family = ? AND genus != '' AND genome_length >= 3000
                        ORDER BY CASE WHEN accession LIKE 'NC_%' THEN 0 ELSE 1 END, genome_length DESC
                        LIMIT 200
                        """,
                        (f,),
                    ).fetchall()
                    per_neighbor_count: Dict[str, int] = {}
                    for row in rows:
                        rec = self._row_to_record(row)
                        if rec.accession in excl or rec.accession in seen:
                            continue
                        if rec.genus in genus_set:
                            continue
                        c = per_neighbor_count.get(rec.genus, 0)
                        if c >= 2:
                            continue
                        per_neighbor_count[rec.genus] = c + 1
                        seen.add(rec.accession)
                        selected.append(rec)
                        if len(selected) >= max_total:
                            break
                    if len(selected) >= max_total:
                        break

        return selected

    def find_outgroup_candidates(
        self,
        target_genera: Sequence[str],
        target_families: Sequence[str],
        target_orders: Sequence[str] = (),
        host_hint: str = "",
        exclude_accessions: Sequence[str] = (),
        limit: int = 3,
    ) -> List[InpharedRecord]:
        """
        按科研原则筛选外群：与目标类群同科不同属，或同目邻近科，且排除在目标属之外。
        """
        if not self.is_available():
            return []
        self.ensure_built()
        excl = set(exclude_accessions) | {x.split(".")[0] for x in exclude_accessions}
        genus_excl = {_clean_tax(g) for g in target_genera if _clean_tax(g)}
        fam_list = [_clean_tax(f) for f in target_families if _clean_tax(f)]
        order_list = [_clean_tax(o) for o in target_orders if _clean_tax(o)]

        candidates: List[InpharedRecord] = []
        seen: set[str] = set()

        with sqlite3.connect(str(self.db_path), timeout=15) as conn:
            # 优先级 A：同科不同属的正式分类 RefSeq 代表
            for fam in fam_list:
                rows = conn.execute(
                    """
                    SELECT * FROM inphared
                    WHERE family = ? AND genus != '' AND genome_length >= 10000
                    ORDER BY CASE WHEN accession LIKE 'NC_%' THEN 0 ELSE 1 END, genome_length DESC
                    LIMIT 80
                    """,
                    (fam,),
                ).fetchall()
                for row in rows:
                    rec = self._row_to_record(row)
                    if rec.accession in excl or rec.accession in seen or rec.genus in genus_excl:
                        continue
                    seen.add(rec.accession)
                    candidates.append(rec)
                    if len(candidates) >= limit:
                        return candidates

            # 优先级 B：同目邻近科的正式代表
            fam_excl = set(fam_list)
            for ord_name in order_list:
                rows = conn.execute(
                    """
                    SELECT * FROM inphared
                    WHERE order_name = ? AND family != '' AND genus != '' AND genome_length >= 10000
                    ORDER BY CASE WHEN accession LIKE 'NC_%' THEN 0 ELSE 1 END, genome_length DESC
                    LIMIT 80
                    """,
                    (ord_name,),
                ).fetchall()
                for row in rows:
                    rec = self._row_to_record(row)
                    if (
                        rec.accession in excl
                        or rec.accession in seen
                        or rec.genus in genus_excl
                        or rec.family in fam_excl
                    ):
                        continue
                    seen.add(rec.accession)
                    candidates.append(rec)
                    if len(candidates) >= limit:
                        return candidates

            # 优先级 C：若原株未归入任何已知科（完全新型科/目级），选取同纲 Caudoviricetes 不同属高质量代表
            host_kw = (host_hint or "").split()[0] if host_hint else ""
            query = """
                SELECT * FROM inphared
                WHERE class_name = 'Caudoviricetes' AND genus != '' AND genome_length >= 15000
            """
            params: List[str] = []
            if host_kw:
                query += " AND host NOT LIKE ? "
                params.append(f"%{host_kw}%")
            query += " ORDER BY CASE WHEN accession LIKE 'NC_%' THEN 0 ELSE 1 END, genome_length DESC LIMIT 40"
            for row in conn.execute(query, params).fetchall():
                rec = self._row_to_record(row)
                if rec.accession in excl or rec.accession in seen or rec.genus in genus_excl:
                    continue
                seen.add(rec.accession)
                candidates.append(rec)
                if len(candidates) >= limit:
                    return candidates

        return candidates


_INDEX_SINGLETON: Optional[InpharedIndex] = None
_INDEX_LOCK = threading.Lock()


def get_inphared_index() -> InpharedIndex:
    global _INDEX_SINGLETON
    with _INDEX_LOCK:
        if _INDEX_SINGLETON is None:
            _INDEX_SINGLETON = InpharedIndex()
        return _INDEX_SINGLETON
