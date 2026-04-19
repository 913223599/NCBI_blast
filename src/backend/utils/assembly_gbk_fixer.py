"""
assembly_gbk_fixer.py - 基因组 GBK 注释回填工具
将 BLAST 的比对结果（蛋白注释）写回到原始的 GenBank 文件中，
实现从“组装 -> 预测 -> 深度鉴定 -> 注释更新”的完整闭环。
"""

import logging
from pathlib import Path
from Bio import SeqIO
from Bio.SeqFeature import SeqFeature, FeatureLocation

logger = logging.getLogger("api_server")

class GBKAnnotationBackfiller:
    def __init__(self, gbk_path: Path):
        self.gbk_path = gbk_path
        if not gbk_path.exists():
            raise FileNotFoundError(f"GBK file not found: {gbk_path}")

    def _clean_functional_product(self, title: str) -> str:
        """
        🚀 增强版清洗算法：适配 NCBI 与 PhageScope 两种模式
        """
        import re
        if not title or title == "N/A":
            return "hypothetical protein"
            
        # [NEW] 探测是否为 PhageScope 结构化标题 (通常不含方括号，且 ID 风格明显)
        # PhageScope 数据通常是: "Tail fiber protein [PHAGESCOPE_ID]" 这种风格，或者直接是功能名
        if "PHAGESCOPE" in title.upper() or "|" not in title:
            # 如果是 PhageScope 结果，通常已经是功能分类名，直接修剪两侧即可
            res = re.sub(r'\[PHAGESCOPE_[^\]]+\]', '', title).strip()
            if res: return res[:100]

        # --- 原始 NCBI NR 清洗逻辑 (仅作为回退方案) ---
        # 1. 移除末尾方括号及其中的物种名 (e.g. [Vibrio phage...])
        res = re.sub(r'\s*\[[^\]]+\]\s*$', '', title).strip()
        
        # 2. 移除开头的 Accession 流水号 (e.g. gb|ABC12345.1|)
        res = re.sub(r'^(?:[a-z]{2,3}\|[^|]+\|\s*)+', '', res, flags=re.I).strip()
        
        # 3. 常见噪声清理
        res = re.sub(r'^>\s*', '', res)
        
        if not res or len(res) < 3:
            return "hypothetical protein"
        
        return res[:100]

    def apply_blast_hits(self, hits_mapping: dict, output_path: Path = None) -> Path:
        """
        将 BLAST 命中结果回填到 GBK
        hits_mapping: { "CDS_ID": { "product": "...", "evalue": "..." }, ... }
        """
        if output_path is None:
            output_path = self.gbk_path.parent / f"{self.gbk_path.stem}_refined{self.gbk_path.suffix}"

        records = list(SeqIO.parse(self.gbk_path, "genbank"))
        updated_count = 0

        # 为了加速匹配，对 hits_mapping 进行预处理（兼容带冒号的 ID）
        flat_hits = {}
        for k, v in hits_mapping.items():
            flat_hits[k] = v
            if ":" in k:
                flat_hits[k.split(":")[-1]] = v

        for record in records:
            for feature in record.features:
                if feature.type == "CDS":
                    # 获取 CDS ID
                    cds_id = None
                    for tag in ["ID", "locus_tag", "protein_id"]:
                        if tag in feature.qualifiers:
                            val = feature.qualifiers[tag][0]
                            if val in flat_hits:
                                cds_id = val
                                break
                    
                    if cds_id and cds_id in flat_hits:
                        hit = flat_hits[cds_id]
                        raw_product = hit.get("product", "hypothetical protein")
                        # ✨ 使用智能清洗引擎
                        new_product = self._clean_functional_product(raw_product)
                        
                        evalue = hit.get("evalue", "N/A")
                        
                        # 更新 product (如果原先是 unknown 或 hypothetical)
                        old_product = feature.qualifiers.get("product", ["hypothetical protein"])[0]
                        should_update = (
                            "unknown" in old_product.lower() or 
                            "hypothetical" in old_product.lower() or
                            old_product.strip() == ""
                        )
                        
                        if should_update and new_product != "hypothetical protein":
                            feature.qualifiers["product"] = [new_product]
                            
                            # 添加注释来源说明
                            note_text = f"Refined by silent BLASTp; E-value: {evalue}; Original: {raw_product}"
                            if "note" in feature.qualifiers:
                                feature.qualifiers["note"].append(note_text)
                            else:
                                feature.qualifiers["note"] = [note_text]
                            
                            # 标记鉴定方法
                            feature.qualifiers["inference"] = [f"protein motif profile:BLASTp:{new_product}"]
                            
                            updated_count += 1
                            logger.info(f"[GBKFixer] Updated CDS {cds_id}: {old_product} -> {new_product}")

        # 保存更新后的 GBK
        with open(output_path, "w", encoding="utf-8") as out_f:
            SeqIO.write(records, out_f, "genbank")
            
        logger.info(f"[GBKFixer] Backfill complete. Updated {updated_count} features. Saved to {output_path}")
        return output_path
