# -*- coding: utf-8 -*-
"""
同步刷新所有已持久化落盘的注释任务 (results/annotations/*) 与泛基因组分析任务 (results/pan_genomics/*)
中的功能分类字段 (category)、分类统计分布 (category_distribution) 与辅助代谢基因列表 (amg_genes)，
确保历史与当前工作台任务立即应用最新审核修正后的分类词条规则。
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.analysis.annotation.fuser import AnnotationFuser


def refresh_annotation_tasks() -> dict:
    anno_dir = BASE_DIR / "results" / "annotations"
    raw_notes_lookup = {}
    updated_files = 0
    updated_features = 0

    for feat_file in sorted(anno_dir.rglob("features.json")):
        task_id = feat_file.parent.name
        try:
            feats = json.loads(feat_file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[WARN] Failed to read {feat_file}: {e}")
            continue

        changed = False
        cat_dist = defaultdict(int)
        annotated_cnt = 0
        hypothetical_cnt = 0

        for f in feats:
            if f.get("feature_type") != "CDS":
                continue
            lt = f.get("locus_tag") or f.get("id")
            prod = f.get("product", "")
            notes = f.get("notes", "")
            new_cat = AnnotationFuser.infer_category(prod, notes)
            raw_notes_lookup[(task_id, lt)] = notes

            if f.get("category") != new_cat:
                f["category"] = new_cat
                changed = True
                updated_features += 1

            cat_dist[new_cat] += 1
            if AnnotationFuser.is_unannotated(prod):
                hypothetical_cnt += 1
            else:
                annotated_cnt += 1

        if changed:
            feat_file.write_text(json.dumps(feats, ensure_ascii=False, indent=2), encoding="utf-8")
            updated_files += 1

        sum_file = feat_file.parent / "summary.json"
        if sum_file.exists():
            try:
                summary = json.loads(sum_file.read_text(encoding="utf-8"))
                summary["category_distribution"] = dict(cat_dist)
                summary["annotated_count"] = annotated_cnt
                summary["hypothetical_count"] = hypothetical_cnt
                sum_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as e:
                print(f"[WARN] Failed to update summary {sum_file}: {e}")

    print(f"[Annotation Tasks] Updated {updated_features} CDS features across {updated_files} tasks.")
    return raw_notes_lookup


def refresh_pan_genomics_tasks(raw_notes_lookup: dict) -> None:
    pan_dir = BASE_DIR / "results" / "pan_genomics"
    standard_cats = [
        "Head & Packaging",
        "Tail & Host Interaction",
        "Replication & Repair",
        "Lysis",
        "Transcription & Regulation",
        "Defense & Host Interaction",
        "Metabolism & AMG",
        "Integration & Excision",
        "Other Functional",
        "Hypothetical",
    ]
    pathway_keywords = [
        ("核苷酸合成与代谢 (Nucleotide Pool)", [r"kinase", r"reductase", r"phoh", r"nrda", r"nrdb", r"thya", r"dutpase", r"thymidylate", r"nucleotidyltransferase"]),
        ("翻译修饰与表观干预 (Translation/Epigenetic)", [r"acetyltransferase", r"gnat", r"methyltransferase", r"queuosine", r"tgt", r"ribosyltransferase"]),
        ("碳源糖基水解与能量 (Carbon & Energy)", [r"hydrolase", r"glycosyl", r"esterase", r"transaldolase", r"psba", r"psbd", r"zwf", r"phosphogluconate"]),
        ("铁摄取与抗逆应激 (Stress & Cofactor)", [r"chaperone", r"ferritin", r"iron", r"glutaredoxin", r"thioredoxin", r"iscs", r"suf"]),
    ]

    for res_file in sorted(pan_dir.rglob("result.json")):
        try:
            data = json.loads(res_file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[WARN] Failed to read {res_file}: {e}")
            continue

        clusters = data.get("clusters", [])
        if not clusters:
            continue

        sample_cat_dist = {
            sid: {c: 0 for c in standard_cats}
            for sid in (data.get("sample_names") or {}).keys()
        }
        new_amg_genes = []
        new_amg_pathway_dist = {
            sid: {
                **{p[0]: 0 for p in pathway_keywords},
                "其他代谢 (Other AMG)": 0,
            }
            for sid in (data.get("sample_names") or {}).keys()
        }

        cluster_changes = 0
        for cl in clusters:
            rep_prod = cl.get("representative_product", "")
            genes = cl.get("genes", [])
            first_notes = ""
            if genes:
                first_notes = raw_notes_lookup.get((genes[0].get("sample_id"), genes[0].get("locus_tag")), "")

            new_rep_cat = AnnotationFuser.infer_category(rep_prod, first_notes)
            if cl.get("category") != new_rep_cat:
                cluster_changes += 1
                cl["category"] = new_rep_cat

            for g in genes:
                sid = g.get("sample_id")
                lt = g.get("locus_tag")
                g_prod = g.get("product", "")
                g_notes = raw_notes_lookup.get((sid, lt), first_notes)
                g_cat = AnnotationFuser.infer_category(g_prod, g_notes)
                if g_cat == "Hypothetical" and not AnnotationFuser.is_unannotated(rep_prod):
                    g_cat = new_rep_cat
                g["category"] = g_cat

                if sid in sample_cat_dist:
                    sample_cat_dist[sid][g_cat] = sample_cat_dist[sid].get(g_cat, 0) + 1

                if g_cat == "Metabolism & AMG":
                    prod_low = g_prod.lower()
                    matched_pw = None
                    for pname, pats in pathway_keywords:
                        if any(re.search(p, prod_low) for p in pats):
                            matched_pw = pname
                            break
                    actual_pw = matched_pw or "其他代谢 (Other AMG)"
                    if sid in new_amg_pathway_dist:
                        new_amg_pathway_dist[sid][actual_pw] += 1
                    new_amg_genes.append({
                        "sample_id": sid,
                        "sample_name": g.get("sample_name") or (data.get("sample_names") or {}).get(sid, sid),
                        "locus_tag": lt,
                        "product": g_prod,
                        "pathway": actual_pw,
                        "length_aa": g.get("length_aa", 0),
                        "start": g.get("start", 0),
                        "end": g.get("end", 0),
                    })

            pmap = cl.get("presence_map") or {}
            for sid, pitem in pmap.items():
                if isinstance(pitem, dict):
                    lt = pitem.get("locus_tag")
                    g_prod = pitem.get("product", "")
                    g_notes = raw_notes_lookup.get((sid, lt), first_notes)
                    g_cat = AnnotationFuser.infer_category(g_prod, g_notes)
                    if g_cat == "Hypothetical" and not AnnotationFuser.is_unannotated(rep_prod):
                        g_cat = new_rep_cat
                    pitem["category"] = g_cat

        data["category_distributions"] = sample_cat_dist
        data["amg_genes"] = new_amg_genes
        data["amg_pathway_distributions"] = new_amg_pathway_dist

        # 同步修正 lifestyles 中的溶原判定与措辞规范 ("溶原 (Temperate)")
        if "lifestyles" in data and isinstance(data["lifestyles"], dict):
            sample_genes_by_sid = defaultdict(list)
            for cl in clusters:
                for g in cl.get("genes", []):
                    sample_genes_by_sid[g.get("sample_id")].append(g)

            for sid, linfo in data["lifestyles"].items():
                if not isinstance(linfo, dict):
                    continue
                integrase_cnt = 0
                repressor_cnt = 0
                excisionase_cnt = 0
                for g in sample_genes_by_sid.get(sid, []):
                    prod_low = (g.get("product") or "").lower().replace("_", " ")
                    g_cat = g.get("category", "")
                    if re.search(r"\b(?:integrases?|site[- ]specific\s+recombinases?|tyrosine[- ]type\s+recombinases?|serine\s+recombinases?)\b", prod_low) or (
                        g_cat == "Integration & Excision" and re.search(r"\brecombinases?\b", prod_low)
                    ):
                        if not re.search(r"\b(?:uvsx|reca|rad51|homologous)\b", prod_low):
                            integrase_cnt += 1
                    if re.search(r"\b(?:repressors?|ci\s+proteins?|ci-like|c2\s+proteins?|cii(?:-like)?\s+(?:proteins?|regulators?)|cro(?:-like)?\s+proteins?|lexa|imm\s+proteins?|prophage\s+repressors?)\b", prod_low):
                        if not re.search(r"\b(?:anti[- ]?repressors?|antirepressors?)\b", prod_low):
                            repressor_cnt += 1
                    if re.search(r"\b(?:excisionases?|xis|recombination\s+directionality\s+factors?|rdf)\b", prod_low):
                        excisionase_cnt += 1

                linfo["integrase_count"] = integrase_cnt
                linfo["repressor_count"] = repressor_cnt
                linfo["excisionase_count"] = excisionase_cnt
                if integrase_cnt > 0 or (repressor_cnt > 0 and excisionase_cnt > 0):
                    linfo["lifestyle"] = "溶原 (Temperate)"
                    linfo["lifestyle_confidence"] = "High" if (integrase_cnt > 0 and repressor_cnt > 0) else "Medium"
                elif repressor_cnt >= 2:
                    linfo["lifestyle"] = "溶原倾向 (Likely Temperate)"
                    linfo["lifestyle_confidence"] = "Low"
                else:
                    linfo["lifestyle"] = "烈性 (Virulent)"
                    linfo["lifestyle_confidence"] = "High"

        res_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        print(f"[Pan-Genomics Task] {res_file.parent.name}: updated {cluster_changes} clusters, AMG count = {len(new_amg_genes)}")


if __name__ == "__main__":
    lookup = refresh_annotation_tasks()
    refresh_pan_genomics_tasks(lookup)

