# -*- coding: utf-8 -*-
"""
深度扫描与验证生物学功能分类算法 (全面排查错分、漏分与边界条件)
"""
import re
from pathlib import Path

def test_full_classification_logic():
    gbk_files = list(Path("results/annotations").glob("*/*.gbk"))
    print(f"============================================================")
    print(f"开始全量扫描 {len(gbk_files)} 个 GBK 文件中的所有 CDS 特征...")
    print(f"============================================================\n")

    all_cds = []
    for gbk in gbk_files:
        text = gbk.read_text(encoding="utf-8")
        # 提取每一个 CDS 块
        cds_blocks = text.split("     CDS             ")[1:]
        for block in cds_blocks:
            locus = re.search(r'/locus_tag="([^"]+)"', block)
            prod = re.search(r'/product="([^"]+)"', block)
            note = re.search(r'/note="([^"]+)"', block)
            gene = re.search(r'/gene="([^"]+)"', block)
            
            locus_str = locus.group(1) if locus else ""
            prod_str = prod.group(1).replace("\n", " ").strip() if prod else ""
            note_str = note.group(1).replace("\n", " ").strip() if note else ""
            gene_str = gene.group(1) if gene else ""
            
            if prod_str or locus_str:
                all_cds.append({
                    "locus": locus_str,
                    "product": prod_str,
                    "note": note_str,
                    "gene": gene_str,
                    "file": gbk.parent.name
                })

    print(f"共提取到 {len(all_cds)} 个真实 CDS 记录\n")

    classified_results = {}
    for item in all_cds:
        cat = run_classifier(item["product"], item["note"])
        classified_results.setdefault(cat, []).append(item)

    for cat in sorted(classified_results.keys()):
        items = classified_results[cat]
        print(f"--------------------------------------------------")
        print(f"[{cat}] Total {len(items)} CDS")
        print(f"--------------------------------------------------")
        # 去重展示 product
        unique_prods = sorted(list(set(x["product"] for x in items)))
        for p in unique_prods:
            print(f"  * {p}")
        print()

def is_hypothetical_name(text: str) -> bool:
    t = text.strip().lower()
    if re.search(r'^(hypothetical protein|uncharacterized protein|unknown function|orf\d+|protein of unknown function)$', t):
        return True
    if re.search(r'protein of unknown function\s*\(duf\d+\)', t):
        return True
    if re.search(r'^duf\d+\s+family\s+protein', t):
        return True
    if re.search(r'^pha\d+\s+domain-containing\s+protein', t):
        return True
    return False

def run_classifier(product: str, notes: str) -> str:
    p = (product or "").strip().lower()
    
    # 1. 假定蛋白优先排除
    if not p or is_hypothetical_name(p):
        return "Hypothetical"

    # 2. Product 规则匹配 (Product 优先原则)
    cat = match_rules(p)
    if cat != "Hypothetical":
        return cat

    # 3. Notes 兜底
    if notes:
        n = notes.lower()
        # 显式 Category 声明
        cat_match = re.search(r'category:\s*([a-z\s_-]+)', n, re.I)
        if cat_match:
            exp_cat = match_rules(cat_match.group(1))
            if exp_cat != "Hypothetical":
                return exp_cat
        
        cat_notes = match_rules(n)
        if cat_notes != "Hypothetical":
            return cat_notes

    return "Other Functional"

def match_rules(text: str) -> str:
    t = text.lower()

    # A. 宿主裂解系统 (Lysis System)
    if re.search(r'(lysin|endolysin|holin|antiholin|spanin|i-spanin|o-spanin|amidase|endopeptidase|peptidoglycan|murein|cell wall hydrolase|transglycosylase|lysis)', t):
        return "Lysis"

    # B. 尾部与尾丝吸附元件 (Tail & Host Recognition)
    if re.search(r'(tail|baseplate|tape measure|tail fiber|tail spike|tail tube|tail sheath|tail assembly|tail needle|tail protein|chaperone|neck1|head-tail adaptor|head-tail connector)', t):
        return "Tail & Host Interaction"

    # C. 头部与衣壳包装 (Head & Packaging)
    if re.search(r'(capsid|portal|terminase|head|scaffold|scaffolding|neck|collar|whisker|virion|structural|major coat|minor coat|prohead|large subunit|small subunit|head closure|head decoration|head maturation|head morphogenesis)', t):
        return "Head & Packaging"

    # D. 溶源整合与位点特异性重组 (Integration & Excision)
    if re.search(r'(integrase|excisionase|transposase|site-specific recombinase)', t):
        return "Integration & Excision"

    # E. DNA 复制、重组与修复 (Replication & Repair)
    if re.search(r'(polymerase|helicase|primase|ligase|recombinase|endonuclease|exonuclease|ssb|single-stranded dna|single-stranded dna-binding|ssdna|topoisomerase|gyrase|resolvase|nuclease|rnase|dnase|dna repair|recombination|dna binding|dntp|primase-helicase|erf|rusa|ninb|ning|rap|holliday|dead\/deah|dna\s)', t):
        return "Replication & Repair"

    # F. 转录调控与开关 (Transcription & Regulation)
    if re.search(r'(repressor|activator|regulator|promoter|transcription|cro|c1|ci|cii|ciii|antitermination|anti-terminator|anti-sigma|sigma factor|modulator|transcriptional|helix-turn-helix|hth|csra|gntr|marr|anti-repressor|parb|partition)', t):
        return "Transcription & Regulation"

    # G. 宿主防御与抗防御互作 (Defense & Host Interaction)
    if re.search(r'(anti-crispr|acr|crispr|cas\d*|methyltransferase|methylase|restriction|modification|toxin|antitoxin|darb|dar|lar-like|immunity|defense|anti-restriction|tcib|colicin)', t):
        return "Defense & Host Interaction"

    # H. 辅助代谢与酶学 (Metabolism & AMG)
    if re.search(r'(kinase|phosphatase|pyrophosphatase|mazg|synthase|synthetase|reductase|dehydrogenase|hydrolase|transferase|mutase|isomerase|acyltransferase|metabolism|amg|ribonucleotide|thioredoxin|glutaredoxin|nad|folate)', t):
        return "Metabolism & AMG"

    if "hypothetical" in t or "uncharacterized" in t or "unknown" in t:
        return "Hypothetical"

    return "Other Functional"

if __name__ == "__main__":
    test_full_classification_logic()
