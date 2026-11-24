# -*- coding: utf-8 -*-
"""
ItolTemplateGenerator - 第 7 步：标准 iTOL 可视化注释模板文件生成器
自动生成可直接拖入 iTOL 上传区使用的规范 UTF-8 注释模板：
1. itol_branch_colors.txt (分支着色：新测序株、外群、各已知属)
2. itol_label_colors.txt (叶节点标签与背景高亮)
3. itol_strip_taxonomy.txt (外圈 ICTV 分类色带 + 自动图例)
4. itol_bars_genome_length.txt (外圈基因组大小柱状条带)
5. itol_bars_gc.txt (外圈 GC% 柱状条带)
6. metadata_table.tsv (完整元数据汇总表)
"""
import csv
from pathlib import Path
from typing import Dict, List

from ..models.schemas import ReferenceCandidate
from .label_formatter import clean_phage_description, format_leaf_label

_PALETTE = [
    "#2563eb",
    "#059669",
    "#7c3aed",
    "#d97706",
    "#0891b2",
    "#db2777",
    "#4f46e5",
    "#65a30d",
    "#0d9488",
    "#9333ea",
]


class ItolTemplateGenerator:
    """生成可直接复用与投稿修改的标准 iTOL 注释文件套。"""

    @staticmethod
    def generate(
        candidates: List[ReferenceCandidate],
        out_dir: Path,
        leaf_names: List[str] | None = None,
    ) -> List[str]:
        out_dir.mkdir(parents=True, exist_ok=True)
        allowed = set(leaf_names) if leaf_names is not None else None
        rows = [
            c
            for c in candidates
            if c.selected and (allowed is None or c.accession in allowed)
        ]

        # 为已知 ICTV 属分配稳定科研色板
        genus_colors: Dict[str, str] = {}
        color_idx = 0
        for c in rows:
            g = (c.genus or "").strip()
            if g and g not in genus_colors:
                genus_colors[g] = _PALETTE[color_idx % len(_PALETTE)]
                color_idx += 1

        created: List[str] = []

        # 1. itol_branch_colors.txt
        branch_path = out_dir / "itol_branch_colors.txt"
        with open(branch_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("TREE_COLORS\n")
            fh.write("SEPARATOR TAB\n")
            fh.write("DATA\n")
            for c in rows:
                if c.role == "query":
                    fh.write(f"{c.accession}\tbranch\t#dc2626\tnormal\t3\n")
                elif c.role == "outgroup":
                    fh.write(f"{c.accession}\tbranch\t#64748b\tdashed\t2\n")
                elif c.genus and c.genus in genus_colors:
                    fh.write(f"{c.accession}\tbranch\t{genus_colors[c.genus]}\tnormal\t1.5\n")
        created.append(branch_path.name)

        # 2. itol_label_colors.txt
        label_path = out_dir / "itol_label_colors.txt"
        with open(label_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("TREE_COLORS\n")
            fh.write("SEPARATOR TAB\n")
            fh.write("DATA\n")
            for c in rows:
                if c.role == "query":
                    fh.write(f"{c.accession}\tlabel\t#b91c1c\tbold\t1.15\n")
                    fh.write(f"{c.accession}\tlabel_background\t#fee2e2\n")
                elif c.role == "outgroup":
                    fh.write(f"{c.accession}\tlabel\t#475569\titalic\t1\n")
                elif c.genus and c.genus in genus_colors:
                    fh.write(f"{c.accession}\tlabel\t{genus_colors[c.genus]}\tnormal\t1\n")
        created.append(label_path.name)

        # 3. itol_strip_taxonomy.txt
        strip_path = out_dir / "itol_strip_taxonomy.txt"
        with open(strip_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("DATASET_COLORSTRIP\n")
            fh.write("SEPARATOR TAB\n")
            fh.write("DATASET_LABEL\tICTV_Genus\n")
            fh.write("COLOR\t#2563eb\n")
            fh.write("STRIP_WIDTH\t28\n")
            fh.write("SHOW_LABELS\t0\n")
            if genus_colors:
                fh.write("LEGEND_TITLE\tICTV_Classification\n")
                fh.write(
                    "LEGEND_SHAPES\t" + "\t".join(["1"] * (len(genus_colors) + 2)) + "\n"
                )
                fh.write(
                    "LEGEND_COLORS\t#dc2626\t#64748b\t"
                    + "\t".join(genus_colors.values())
                    + "\n"
                )
                fh.write(
                    "LEGEND_LABELS\tQuery_Phage\tOutgroup\t"
                    + "\t".join(genus_colors.keys())
                    + "\n"
                )
            fh.write("DATA\n")
            for c in rows:
                if c.role == "query":
                    fh.write(f"{c.accession}\t#dc2626\tQuery\n")
                elif c.role == "outgroup":
                    fh.write(f"{c.accession}\t#64748b\tOutgroup ({c.genus or 'Ref'})\n")
                elif c.genus and c.genus in genus_colors:
                    fh.write(f"{c.accession}\t{genus_colors[c.genus]}\t{c.genus}\n")
                else:
                    fh.write(f"{c.accession}\t#cbd5e1\tUnclassified\n")
        created.append(strip_path.name)

        # 4. itol_bars_genome_length.txt
        len_path = out_dir / "itol_bars_genome_length.txt"
        with open(len_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("DATASET_SIMPLEBAR\n")
            fh.write("SEPARATOR TAB\n")
            fh.write("DATASET_LABEL\tGenome_Length_kb\n")
            fh.write("COLOR\t#0ea5e9\n")
            fh.write("WIDTH\t160\n")
            fh.write("MARGIN\t8\n")
            fh.write("DATA\n")
            for c in rows:
                kb = round((c.genome_length or 0) / 1000.0, 2)
                fh.write(f"{c.accession}\t{kb}\n")
        created.append(len_path.name)

        # 5. itol_bars_gc.txt
        gc_path = out_dir / "itol_bars_gc.txt"
        with open(gc_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("DATASET_SIMPLEBAR\n")
            fh.write("SEPARATOR TAB\n")
            fh.write("DATASET_LABEL\tGC_Content_pct\n")
            fh.write("COLOR\t#10b981\n")
            fh.write("WIDTH\t120\n")
            fh.write("MARGIN\t8\n")
            fh.write("DATA\n")
            for c in rows:
                fh.write(f"{c.accession}\t{round(c.gc_content or 0.0, 2)}\n")
        created.append(gc_path.name)

        # 6. itol_labels_display.txt (将参考株登录号显示为 `实际名称 (登录号)` 标准发表标签)
        labels_path = out_dir / "itol_labels_display.txt"
        label_lines: List[str] = ["LABELS", "SEPARATOR TAB", "DATA"]
        has_display_mapping = False
        for c in rows:
            disp = format_leaf_label(
                c.accession,
                {"role": c.role, "description": c.description},
                label_format="name_acc",
            )
            if disp and disp != c.accession:
                label_lines.append(f"{c.accession}\t{disp}")
                has_display_mapping = True
        if has_display_mapping:
            labels_path.write_text("\n".join(label_lines) + "\n", encoding="utf-8", newline="\n")
            created.append(labels_path.name)

        # 7. metadata_table.tsv
        tsv_path = out_dir / "metadata_table.tsv"
        with open(tsv_path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh, delimiter="\t")
            writer.writerow(
                [
                    "Accession",
                    "Description",
                    "Role",
                    "Source",
                    "Genus",
                    "Family",
                    "Order",
                    "Host",
                    "Genome_Length_bp",
                    "GC_pct",
                    "wgANI_pct",
                    "CheckV_Completeness",
                ]
            )
            for c in rows:
                writer.writerow(
                    [
                        c.accession,
                        clean_phage_description(c.description),
                        c.role,
                        c.source,
                        c.genus,
                        c.family,
                        c.order,
                        c.host,
                        c.genome_length,
                        round(c.gc_content or 0.0, 2),
                        round(c.wg_ani, 2) if c.wg_ani is not None else "",
                        round(c.completeness, 1) if c.completeness is not None else "",
                    ]
                )
        created.append(tsv_path.name)

        return created
