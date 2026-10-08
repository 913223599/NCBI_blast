# -*- coding: utf-8 -*-
"""
rrnDB 16S rRNA 基因拷贝数 (Gene Copy Number, GCN) 归一化服务
数据源：Ribosomal RNA Operon Database (rrnDB)
"""
import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger("api_server")

# 获取项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class RrnDBService:
    """rrnDB 16S 拷贝数查询与相对丰度归一化服务"""
    
    _instance: Optional["RrnDBService"] = None

    def __init__(self):
        self.db_path = PROJECT_ROOT / "database" / "rrndb" / "rrnDB-5.10_pantaxa_stats_NCBI.tsv"
        self.lookup: Dict[str, Dict[str, Any]] = {}
        self.is_loaded = False
        self._load_database()

    @classmethod
    def get_instance(cls) -> "RrnDBService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load_database(self):
        if not self.db_path.exists():
            logger.warning(f"[rrnDB] 数据库文件不存在: {self.db_path}")
            return

        try:
            with open(self.db_path, "r", encoding="utf-8") as f:
                header = f.readline().strip().split("\t")
                for line in f:
                    parts = line.strip().split("\t")
                    if len(parts) >= 9:
                        name = parts[2].strip()
                        rank = parts[1].strip()
                        median_str = parts[7].strip()
                        mean_str = parts[8].strip()
                        
                        try:
                            mean_val = float(mean_str) if mean_str else 1.0
                        except ValueError:
                            mean_val = 1.0
                            
                        try:
                            median_val = float(median_str) if median_str else mean_val
                        except ValueError:
                            median_val = mean_val
                            
                        self.lookup[name.lower()] = {
                            "name": name,
                            "rank": rank,
                            "mean": mean_val,
                            "median": median_val
                        }
            self.is_loaded = True
            logger.info(f"[rrnDB] 成功载入 {len(self.lookup)} 条分类单元拷贝数记录")
        except Exception as e:
            logger.error(f"[rrnDB] 载入数据库异常: {e}", exc_info=True)

    def get_gcn(self, taxon_name: str) -> Dict[str, Any]:
        """
        根据物种名检索 16S 拷贝数，若物种未匹配则自动退化到属名匹配，否则回退到默认 1.0
        """
        if not taxon_name or not taxon_name.strip():
            return {"name": "Unknown", "rank": "default", "mean": 1.0, "median": 1.0, "matched": False}

        clean_name = taxon_name.strip()
        key = clean_name.lower()
        
        # 1. 精确匹配物种
        if key in self.lookup:
            res = dict(self.lookup[key])
            res["matched"] = True
            res["match_type"] = "species"
            return res

        # 2. 回退到属名匹配
        parts = clean_name.split()
        if len(parts) > 1:
            genus_key = parts[0].lower()
            if genus_key in self.lookup:
                res = dict(self.lookup[genus_key])
                res["matched"] = True
                res["match_type"] = "genus"
                return res

        # 3. 兜底默认
        return {
            "name": clean_name,
            "rank": "default",
            "mean": 1.0,
            "median": 1.0,
            "matched": False,
            "match_type": "fallback"
        }

    def normalize_abundance(self, taxa_counts: Dict[str, int]) -> Dict[str, Any]:
        """
        输入分类单元原始 Reads 计数，输出 rrnDB 16S 拷贝数归一化后的丰度字典
        公式:
            Count_norm_i = Count_raw_i / GCN_mean_i
            Pct_norm_i = Count_norm_i / sum(Count_norm) * 100
        """
        total_raw = sum(taxa_counts.values())
        if total_raw == 0:
            return {"details": [], "total_raw": 0, "total_norm": 0.0}

        norm_counts = {}
        gcn_info = {}
        for taxon, count in taxa_counts.items():
            gcn_meta = self.get_gcn(taxon)
            gcn_val = max(0.1, gcn_meta.get("mean", 1.0))
            gcn_info[taxon] = gcn_meta
            norm_counts[taxon] = count / gcn_val

        total_norm = sum(norm_counts.values())

        details = []
        for taxon, count in taxa_counts.items():
            raw_pct = (count / total_raw * 100.0) if total_raw > 0 else 0.0
            norm_c = norm_counts[taxon]
            norm_pct = (norm_c / total_norm * 100.0) if total_norm > 0 else 0.0
            meta = gcn_info[taxon]
            details.append({
                "taxon": taxon,
                "raw_count": count,
                "raw_pct": round(raw_pct, 4),
                "gcn_mean": round(meta.get("mean", 1.0), 2),
                "gcn_median": round(meta.get("median", 1.0), 2),
                "gcn_rank": meta.get("rank", "default"),
                "gcn_matched": meta.get("matched", False),
                "norm_count": round(norm_c, 4),
                "norm_pct": round(norm_pct, 4)
            })

        # 按归一化丰度降序排序
        details.sort(key=lambda x: x["norm_pct"], reverse=True)

        return {
            "total_raw": total_raw,
            "total_norm": round(total_norm, 4),
            "details": details
        }


def get_rrndb_service() -> RrnDBService:
    return RrnDBService.get_instance()
