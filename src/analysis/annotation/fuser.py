# -*- coding: utf-8 -*-
"""
功能注释特征融合与互补引擎 (AnnotationFuser)
负责在多引擎级联流水线中，针对前序引擎未注释或仅有部分特征的 CDS，
执行漏斗式属性互补、证据链整合、功能大类自动归并与置信度审计。
"""
import re
import logging
from typing import Dict, List, Any, Optional, Tuple, Set

from .types import FeatureItem, AnnotationSummary

logger = logging.getLogger("analysis.annotation.fuser")


class AnnotationFuser:
    """注释特征融合与补全器"""

    UNANNOTATED_PATTERNS = [
        r"^hypothetical(?:\s+protein)?$",
        r"^unknown(?:\s+protein)?$",
        r"^uncharacterized(?:\s+protein)?$",
        r"^putative\s+uncharacterized(?:\s+protein)?$",
        r"^putative\s+protein$",
        r"^predicted\s+protein$",
        r"^protein\s+of\s+unknown\s+function$",
        r"^conserved\s+hypothetical(?:\s+protein)?$",
        r"^unnamed\s+protein\s+product$",
        r"^none$",
        r"^na$",
        r"^unassigned$"
    ]

    CATEGORY_RULES = [
        ("Tail", [
            r"tail", r"baseplate", r"spike", r"fiber", r"receptor\s+binding", r"adhesin",
            r"sheath", r"tail\s+tube", r"tail\s+assembly", r"collar", r"central\s+spike", r"whisker"
        ]),
        ("Packaging", [
            r"terminase", r"portal", r"scaffolding", r"maturase", r"head\s+maturation",
            r"packaging\s+protein", r"small\s+subunit\s+terminase", r"large\s+subunit\s+terminase"
        ]),
        ("Structural", [
            r"capsid", r"head\s+protein", r"neck", r"structural\s+protein", r"virion", r"core\s+protein", r"major\s+head"
        ]),
        ("Lysis", [
            r"endolysin", r"holin", r"spanin", r"lysin", r"lysozyme", r"amidase",
            r"murein", r"peptidoglycan\s+hydrolase", r"lysis\s+protein", r"antiholin"
        ]),
        ("Replication & Repair", [
            r"polymerase", r"helicase", r"primase", r"ligase", r"topoisomerase",
            r"exonuclease", r"endonuclease", r"recombinase", r"integrase", r"single-stranded",
            r"dna\s+binding", r"rnase", r"dnase", r"resolvase", r"gyrase"
        ]),
        ("Transcription & Regulation", [
            r"transcription", r"repressor", r"activator", r"regulator", r"sigma\s+factor",
            r"anti-repressor", r"cro\s+protein", r"ci\s+repressor", r"promoter"
        ]),
        ("Defense & Host Interaction", [
            r"anti-crispr", r"methyltransferase", r"restriction", r"modification",
            r"toxin", r"antitoxin", r"cas\d+", r"abortive\s+infection", r"defense"
        ]),
        ("Metabolism & AMG", [
            r"synthase", r"reductase", r"kinase", r"transferase", r"dehydrogenase",
            r"hydrolase", r"isomerase", r"dada", r"psba", r"psbd", r"thiosulfate"
        ])
    ]

    @classmethod
    def is_unannotated(cls, product: Optional[str]) -> bool:
        """判断一个功能描述是否为未注释/假定蛋白/未知功能"""
        if not product:
            return True
        p_clean = product.strip().lower()
        if not p_clean:
            return True
        for pat in cls.UNANNOTATED_PATTERNS:
            if re.search(pat, p_clean):
                return True
        return False

    @classmethod
    def infer_category(cls, product: Optional[str], notes: Optional[str] = None) -> str:
        """依据产品描述与结构域特征，自动归类到标准生物学功能模块"""
        if cls.is_unannotated(product):
            return "Hypothetical"

        text_to_check = f"{product or ''} {notes or ''}".lower()

        for cat_name, patterns in cls.CATEGORY_RULES:
            for pat in patterns:
                if re.search(pat, text_to_check):
                    return cat_name

        return "Other Functional"

    @classmethod
    def clean_product_text(cls, raw_prod: Optional[str]) -> str:
        """清洗并规范化产品名称"""
        if not raw_prod:
            return "hypothetical protein"
        from urllib.parse import unquote
        cleaned = unquote(raw_prod.strip())
        if (cleaned.startswith('"') and cleaned.endswith('"')) or (cleaned.startswith("'") and cleaned.endswith("'")):
            cleaned = cleaned[1:-1].strip()
        cleaned = cleaned.replace("%20", " ").replace("%2C", ",").replace("%3B", ";")
        if not cleaned or cls.is_unannotated(cleaned):
            return "hypothetical protein"
        return cleaned

    @classmethod
    def complement_single_feature(
        cls,
        base_feat: FeatureItem,
        candidate_data: Dict[str, Any],
        engine_name: str
    ) -> bool:
        """
        尝试用新引擎的数据补充单个特征
        返回是否进行了有效补充
        """
        is_updated = False
        new_prod = cls.clean_product_text(candidate_data.get("product"))
        
        # 1. 产物描述补全: 若原先未注释，而新候选有确切功能，则更新
        if cls.is_unannotated(base_feat.product) and not cls.is_unannotated(new_prod):
            base_feat.product = new_prod
            base_feat.source_engine = engine_name
            is_updated = True

        # 2. 基因名称补全
        new_gene = candidate_data.get("gene_name") or candidate_data.get("gene")
        if new_gene and not base_feat.gene_name:
            base_feat.gene_name = str(new_gene).strip()
            is_updated = True

        # 3. EC 酶学编号补全
        new_ec = candidate_data.get("ec_number") or candidate_data.get("ec")
        if new_ec and not base_feat.ec_number:
            base_feat.ec_number = str(new_ec).strip()
            is_updated = True

        # 4. COG 分类补全
        new_cog = candidate_data.get("cog")
        if new_cog and not base_feat.cog:
            base_feat.cog = str(new_cog).strip()
            is_updated = True

        # 5. 证据链记录与 Notes 追加
        evidence_note = candidate_data.get("evidence") or candidate_data.get("note") or candidate_data.get("notes")
        evidence_tag = f"[{engine_name}]"
        
        if evidence_note:
            note_str = str(evidence_note).strip()
            if note_str not in base_feat.evidence_sources:
                base_feat.evidence_sources.append(f"{evidence_tag} {note_str}")
        elif engine_name not in [e.split()[0].replace("[", "").replace("]", "") for e in base_feat.evidence_sources]:
            base_feat.evidence_sources.append(f"{evidence_tag} Matched")

        # 刷新 Notes 字段
        if base_feat.evidence_sources:
            base_feat.notes = "; ".join(base_feat.evidence_sources)

        # 6. 重新评估功能分类
        base_feat.category = cls.infer_category(base_feat.product, base_feat.notes)

        return is_updated

    @classmethod
    def merge_by_coordinates(
        cls,
        base_features: List[FeatureItem],
        incoming_features: List[FeatureItem],
        engine_name: str,
        overlap_threshold: float = 0.7
    ) -> Tuple[List[FeatureItem], int]:
        """
        基于物理坐标重叠度对两组特征进行流式互补
        """
        updated_count = 0
        
        # 建立按起始位点排序的列表以供快速重叠匹配
        for in_feat in incoming_features:
            if in_feat.feature_type != "CDS" and cls.is_unannotated(in_feat.product):
                continue

            # 寻找在相同链、重叠度 >= overlap_threshold 的匹配特征
            best_match: Optional[FeatureItem] = None
            best_overlap_ratio = 0.0

            for b_feat in base_features:
                if b_feat.feature_type != in_feat.feature_type:
                    continue
                if b_feat.strand != in_feat.strand:
                    continue

                # 计算区间重叠
                overlap_start = max(b_feat.start, in_feat.start)
                overlap_end = min(b_feat.end, in_feat.end)
                if overlap_end >= overlap_start:
                    overlap_len = overlap_end - overlap_start + 1
                    min_len = min(b_feat.length_bp, in_feat.length_bp)
                    ratio = overlap_len / max(1, min_len)
                    if ratio >= overlap_threshold and ratio > best_overlap_ratio:
                        best_overlap_ratio = ratio
                        best_match = b_feat

            if best_match:
                cand_data = {
                    "product": in_feat.product,
                    "gene_name": in_feat.gene_name,
                    "ec_number": in_feat.ec_number,
                    "cog": in_feat.cog,
                    "evidence": in_feat.notes
                }
                if cls.complement_single_feature(best_match, cand_data, engine_name):
                    updated_count += 1

        return base_features, updated_count

    @classmethod
    def generate_summary(
        cls,
        records_len_dict: Dict[str, int],
        full_seq: str,
        features: List[FeatureItem]
    ) -> AnnotationSummary:
        """统计并生成全套基因组注释指标摘要"""
        from .builtin_annotator import BuiltinAnnotator

        total_len = sum(records_len_dict.values())
        gc_val = BuiltinAnnotator.calculate_gc(full_seq)

        cds_cnt = sum(1 for f in features if f.feature_type == "CDS")
        trna_cnt = sum(1 for f in features if f.feature_type == "tRNA")
        rrna_cnt = sum(1 for f in features if f.feature_type == "rRNA")
        tmrna_cnt = sum(1 for f in features if f.feature_type == "tmRNA")
        crispr_cnt = sum(1 for f in features if f.feature_type == "CRISPR")
        other_cnt = len(features) - (cds_cnt + trna_cnt + rrna_cnt + tmrna_cnt + crispr_cnt)

        annotated_cnt = 0
        hypothetical_cnt = 0
        engine_contrib: Dict[str, int] = {}
        cat_dist: Dict[str, int] = {}

        for f in features:
            if f.feature_type == "CDS":
                if cls.is_unannotated(f.product):
                    hypothetical_cnt += 1
                else:
                    annotated_cnt += 1

                eng = f.source_engine or "Baseline"
                engine_contrib[eng] = engine_contrib.get(eng, 0) + 1

                cat = f.category or cls.infer_category(f.product, f.notes)
                cat_dist[cat] = cat_dist.get(cat, 0) + 1

        total_cds_bp = sum(f.length_bp for f in features if f.feature_type == "CDS")
        coding_density = round((total_cds_bp / max(1, total_len)) * 100.0, 2)
        avg_len = round(total_cds_bp / max(1, cds_cnt), 1)

        return AnnotationSummary(
            total_length=total_len,
            num_contigs=len(records_len_dict),
            gc_content=gc_val,
            cds_count=cds_cnt,
            trna_count=trna_cnt,
            rrna_count=rrna_cnt,
            tmrna_count=tmrna_cnt,
            crispr_count=crispr_cnt,
            other_count=other_cnt,
            total_features=len(features),
            annotated_count=annotated_cnt,
            hypothetical_count=hypothetical_cnt,
            coding_density_pct=coding_density,
            avg_gene_length=avg_len,
            engine_contributions=engine_contrib,
            category_distribution=cat_dist
        )

    @classmethod
    def integrate_safety_audit(cls, features: List[Any], safety_audit: Dict[str, Any]) -> int:
        """
        将生物安全审计与 Anti-CRISPR 逃逸因子深度反向回写融合至各 FeatureItem (兼容对象与字典)，
        把假定蛋白直接升级为明确的生物学功能描述 (如 anti-CRISPR protein)，并在注释记录中保留实验证据。
        """
        if not safety_audit or not features:
            return 0

        feat_map: Dict[str, Any] = {}
        for f in features:
            fid = f.id if isinstance(f, FeatureItem) else f.get("id")
            lt = f.locus_tag if isinstance(f, FeatureItem) else f.get("locus_tag")
            pid = f.protein_id if isinstance(f, FeatureItem) else f.get("protein_id")
            if fid:
                feat_map[fid] = f
            if lt:
                feat_map[lt] = f
            if pid:
                feat_map[pid] = f

        updated_count = 0

        def get_val(item: Any, key: str, default: Any = None) -> Any:
            return getattr(item, key, default) if isinstance(item, FeatureItem) else item.get(key, default)

        def set_val(item: Any, key: str, value: Any):
            if isinstance(item, FeatureItem):
                setattr(item, key, value)
            elif isinstance(item, dict):
                item[key] = value

        # 1. 融合 Anti-CRISPR (Acr) 宿主防御逃逸因子
        for acr in safety_audit.get("anti_crispr_genes", []):
            cid = acr.get("cds_id")
            target_feat = feat_map.get(cid)
            if not target_feat:
                continue

            acr_source = acr.get("source") or "Acrank_er"
            ident = acr.get("identity", 0)
            e_val = acr.get("evalue", "1e-10")
            evidence_note = f"Anti-CRISPR: {acr_source} (Identity: {ident}%, E-value: {e_val})"

            curr_prod = get_val(target_feat, "product", "")
            # 若原本未注释或为假定蛋白，直接赋予明确的生物学功能名称！
            if cls.is_unannotated(curr_prod):
                clean_acr_name = f"anti-CRISPR protein ({acr_source})" if acr_source != "Acr Protein" else "anti-CRISPR protein"
                set_val(target_feat, "product", clean_acr_name)
                set_val(target_feat, "category", "Defense & Host Interaction")
                set_val(target_feat, "source_engine", "PhageScope")
                set_val(target_feat, "evidence", evidence_note)
                updated_count += 1
            
            # 在 notes 与 evidence_sources 中追加审计证据标记
            curr_notes = get_val(target_feat, "notes")
            if curr_notes:
                if "Anti-CRISPR" not in curr_notes:
                    set_val(target_feat, "notes", f"{curr_notes}; {evidence_note}")
            else:
                set_val(target_feat, "notes", evidence_note)

            curr_ev_list = list(get_val(target_feat, "evidence_sources") or [])
            ev_tag = f"[Anti-CRISPR] {acr_source} (Identity: {ident}%, E-value: {e_val})"
            if not any("Anti-CRISPR" in ev for ev in curr_ev_list):
                curr_ev_list.append(ev_tag)
                set_val(target_feat, "evidence_sources", curr_ev_list)

        # 2. 融合 AMR 耐药基因
        for amr in safety_audit.get("amr_genes", []):
            cid = amr.get("cds_id")
            target_feat = feat_map.get(cid)
            if not target_feat:
                continue
            desc = amr.get("description") or "AMR gene"
            ident = amr.get("identity", 0)
            note_str = f"CARD AMR: {desc} (Identity: {ident}%)"
            
            curr_prod = get_val(target_feat, "product", "")
            if cls.is_unannotated(curr_prod):
                set_val(target_feat, "product", f"antibiotic resistance protein ({desc})")
                set_val(target_feat, "category", "Defense & Host Interaction")
                set_val(target_feat, "source_engine", "CARD")
                updated_count += 1

            curr_notes = get_val(target_feat, "notes")
            if curr_notes:
                if "CARD AMR" not in curr_notes:
                    set_val(target_feat, "notes", f"{curr_notes}; {note_str}")
            else:
                set_val(target_feat, "notes", note_str)

        # 3. 融合 VFDB 毒力因子
        for vf in safety_audit.get("virulent_factors", []):
            cid = vf.get("cds_id")
            target_feat = feat_map.get(cid)
            if not target_feat:
                continue
            desc = vf.get("description") or "Virulence Factor"
            ident = vf.get("identity", 0)
            note_str = f"VFDB: {desc} (Identity: {ident}%)"

            curr_prod = get_val(target_feat, "product", "")
            if cls.is_unannotated(curr_prod):
                set_val(target_feat, "product", f"virulence factor ({desc})")
                set_val(target_feat, "category", "Defense & Host Interaction")
                set_val(target_feat, "source_engine", "VFDB")
                updated_count += 1

            curr_notes = get_val(target_feat, "notes")
            if curr_notes:
                if "VFDB" not in curr_notes:
                    set_val(target_feat, "notes", f"{curr_notes}; {note_str}")
            else:
                set_val(target_feat, "notes", note_str)

        return updated_count
