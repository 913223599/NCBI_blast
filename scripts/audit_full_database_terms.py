# -*- coding: utf-8 -*-
"""
扫描本地权威噬菌体数据库 (PhageScope RefSeq / GenBank / PhagesDB 等数十万条真实蛋白注释)
以及项目中所有后端分类器的词条覆盖率，找出落入 Other Functional 的高频噬菌体功能词条，
全面核验后端 AnnotationFuser 分类词条是否准确、完善。
"""

import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.analysis.annotation.fuser import AnnotationFuser


def main():
    meta_dir = BASE_DIR / "database" / "phagescope" / "metadata" / "annotated_protein"
    tsv_files = list(meta_dir.glob("*.tsv")) if meta_dir.exists() else []
    print(f"Found {len(tsv_files)} metadata TSV files in {meta_dir}")

    product_counter = Counter()
    raw_class_by_prod = {}

    for tsv_path in tsv_files:
        print(f"Scanning {tsv_path.name} ...")
        with open(tsv_path, "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                prod = (row.get("Product") or "").strip()
                if prod:
                    product_counter[prod] += 1
                    if prod not in raw_class_by_prod:
                        raw_class_by_prod[prod] = (row.get("Protein_classification") or "").strip()

    print(f"Total unique product strings in PhageScope DB: {len(product_counter)} (Total rows: {sum(product_counter.values())})")

    cat_totals = Counter()
    other_functional_top = Counter()
    by_category_top = defaultdict(Counter)

    for prod, count in product_counter.items():
        cat = AnnotationFuser.infer_category(prod)
        cat_totals[cat] += count
        by_category_top[cat][prod] += count
        if cat == "Other Functional":
            other_functional_top[prod] += count

    print("\n=== 1. 权威库全量蛋白在各分组下的数量分布 ===")
    total_proteins = max(1, sum(cat_totals.values()))
    for cat, cnt in cat_totals.most_common():
        print(f"  {cat:<30}: {cnt:>10,} ({cnt * 100.0 / total_proteins:5.2f}%) | Unique terms: {len(by_category_top[cat]):,}")

    print("\n=== 2. 落入 [Other Functional] 的 Top 120 高频词条 (重点排查是否有漏网的核心功能蛋白或假定蛋白) ===")
    for prod, cnt in other_functional_top.most_common(120):
        ps_cls = raw_class_by_prod.get(prod, "")
        print(f"  [{cnt:>6}] {prod:<65} (PhageScope class: {ps_cls})")

    print("\n=== 3. 各核心分组 Top 25 高频词条抽样核验 ===")
    for cat in [
        "Head & Packaging",
        "Tail & Host Interaction",
        "Lysis",
        "Integration & Excision",
        "Replication & Repair",
        "Transcription & Regulation",
        "Defense & Host Interaction",
        "Metabolism & AMG",
        "Hypothetical",
    ]:
        print(f"\n--- [{cat}] Top 25 ---")
        for prod, cnt in by_category_top[cat].most_common(25):
            print(f"  [{cnt:>6}] {prod} (PS: {raw_class_by_prod.get(prod, '')})")

    print("\n=== 4. 二级分类器 (ProteinComparer / PanGenomeEngine) 回归断言测试 ===")
    from src.analysis.protein_compare.engine import ProteinComparer
    test_cases = [
        ("major capsid protein", "Head & Packaging", "capsid_head"),
        ("head morphogenesis protein", "Head & Packaging", "capsid_head"),
        ("terminase large subunit", "Head & Packaging", "packaging"),
        ("tail length tape measure protein", "Tail & Host Interaction", "tail_fiber"),
        ("Pfam:Phage_holin_7_1", "Lysis", "lysis"),
        ("UvsX-like recombinase", "Replication & Repair", "replication"),
        ("Papain fold toxin 1, glutamine deamidase", "Defense & Host Interaction", "other"),
        ("Pfam:DUF5403", "Hypothetical", "other"),
        ("Phage protein Gp19", "Hypothetical", "other"),
    ]
    for prod, exp_fuser, exp_pc in test_cases:
        got_fuser = AnnotationFuser.infer_category(prod)
        got_pc = ProteinComparer.classify_protein(prod, direct_cat=got_fuser, notes="Predicted by Builtin-Annotator")
        assert got_fuser == exp_fuser, f"Fuser mismatch for '{prod}': got {got_fuser}, expected {exp_fuser}"
        assert got_pc == exp_pc, f"ProteinComparer mismatch for '{prod}': got {got_pc}, expected {exp_pc}"
        print(f"  [PASS] {prod:<45} -> Fuser: {got_fuser:<26} | ProteinComparer: {got_pc}")


if __name__ == "__main__":
    main()
