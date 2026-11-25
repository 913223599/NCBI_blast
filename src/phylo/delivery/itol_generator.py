# -*- coding: utf-8 -*-
"""
ItolTemplateGenerator - 第 7 步：标准 iTOL 可视化注释模板文件生成器
自动生成可直接拖入 iTOL 上传区使用的规范 UTF-8 注释模板：
1. itol_branch_colors.txt (精细模式分支着色：新测序株、外群、各已知属)
2. itol_label_colors.txt (叶节点标签与背景高亮)
3. itol_strip_taxonomy.txt (外圈 ICTV 属级分类色带 + 自动图例)
4. itol_bars_genome_length.txt (外圈基因组大小柱状条带)
5. itol_bars_gc.txt (外圈 GC% 柱状条带)
6. itol_branch_colors_macro.txt (宏观环形树分支着色：仅高亮查询株，背景树保持纯黑)
7. itol_strip_family.txt (宏观内圈 Virus family Top-N + Others 自动计数色带)
8. itol_strip_host_group.txt (宏观外圈 Host group Top-N + Others 自动计数色带)
9. itol_symbol_query_star.txt (宏观最外侧查询株红色五角星标记)
10. metadata_table.tsv (完整元数据汇总表，含 Host_Group)
"""
from collections import Counter
import csv
from pathlib import Path
from typing import Dict, List, Tuple

from ..models.schemas import ReferenceCandidate
from .host_taxonomy import get_host_group_color, map_host_to_phylum
from .label_formatter import clean_phage_description, format_leaf_label
from .publication_palettes import PALETTES

_PALETTE = list(PALETTES["nature"].taxon_colors)

_FAMILY_PALETTE = [
    "#3C5488",
    "#00A087",
    "#E64B35",
    "#4DBBD5",
    "#F39B7F",
    "#8491B4",
]

_EMPTY_TAX_TOKENS = frozenset({"", "unclassified", "unknown", "na", "n/a", "none", "nan", "-"})


def _clean_family_name(val: str) -> str:
    txt = (val or "").strip()
    return "" if txt.lower() in _EMPTY_TAX_TOKENS else txt


def _write_colorstrip_dataset(
    out_path: Path,
    dataset_label: str,
    legend_title: str,
    strip_width: int,
    margin: int,
    legend_entries: List[Tuple[str, str, int]],
    data_rows: List[Tuple[str, str, str]],
) -> None:
    """写出标准 iTOL DATASET_COLORSTRIP 注释文件。"""
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("DATASET_COLORSTRIP\n")
        fh.write("SEPARATOR TAB\n")
        fh.write(f"DATASET_LABEL\t{dataset_label}\n")
        fh.write(f"COLOR\t{legend_entries[0][1] if legend_entries else '#6b7280'}\n")
        fh.write(f"STRIP_WIDTH\t{strip_width}\n")
        fh.write(f"MARGIN\t{margin}\n")
        fh.write("BORDER_WIDTH\t0\n")
        fh.write("SHOW_LABELS\t0\n")
        if legend_entries:
            fh.write(f"LEGEND_TITLE\t{legend_title}\n")
            fh.write("LEGEND_SHAPES\t" + "\t".join(["1"] * len(legend_entries)) + "\n")
            fh.write("LEGEND_COLORS\t" + "\t".join(col for _, col, _ in legend_entries) + "\n")
            fh.write(
                "LEGEND_LABELS\t"
                + "\t".join(f"{name} ({cnt})" for name, _, cnt in legend_entries)
                + "\n"
            )
        fh.write("DATA\n")
        for acc, color, label in data_rows:
            fh.write(f"{acc}\t{color}\t{label}\n")


class ItolTemplateGenerator:
    """生成可直接复用与投稿修改的标准 iTOL 注释文件套。"""

    @staticmethod
    def generate(
        candidates: List[ReferenceCandidate],
        out_dir: Path,
        leaf_names: List[str] | None = None,
        top_families: int = 5,
        top_host_groups: int = 5,
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

        # 6. itol_branch_colors_macro.txt (宏观环形树仅标红查询株，保持其余分支为纯黑)
        macro_branch_path = out_dir / "itol_branch_colors_macro.txt"
        with open(macro_branch_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("TREE_COLORS\n")
            fh.write("SEPARATOR TAB\n")
            fh.write("DATA\n")
            for c in rows:
                if c.role == "query":
                    fh.write(f"{c.accession}\tbranch\t#dc2626\tnormal\t3\n")
        created.append(macro_branch_path.name)

        # 7. itol_strip_family.txt (宏观内圈：Virus family Top-N + Others 统计)
        family_counts: Counter[str] = Counter()
        row_families: List[Tuple[str, str]] = []
        for c in rows:
            fam = _clean_family_name(c.family)
            row_families.append((c.accession, fam))
            if fam:
                family_counts[fam] += 1

        top_fam_list = [name for name, _ in family_counts.most_common(max(1, top_families))]
        fam_color_map: Dict[str, str] = {
            name: _FAMILY_PALETTE[idx % len(_FAMILY_PALETTE)] for idx, name in enumerate(top_fam_list)
        }
        fam_legend: List[Tuple[str, str, int]] = [
            (name, fam_color_map[name], family_counts[name]) for name in top_fam_list
        ]
        other_fam_cnt = sum(cnt for name, cnt in family_counts.items() if name not in fam_color_map)
        if other_fam_cnt > 0:
            fam_legend.append(("Others", "#6b7280", other_fam_cnt))

        fam_rows: List[Tuple[str, str, str]] = []
        for acc, fam in row_families:
            if not fam:
                continue
            if fam in fam_color_map:
                fam_rows.append((acc, fam_color_map[fam], fam))
            else:
                fam_rows.append((acc, "#6b7280", f"Others ({fam})"))

        fam_strip_path = out_dir / "itol_strip_family.txt"
        _write_colorstrip_dataset(
            out_path=fam_strip_path,
            dataset_label="Virus_Family_Ring",
            legend_title="Inner ring: Virus family",
            strip_width=24,
            margin=4,
            legend_entries=fam_legend,
            data_rows=fam_rows,
        )
        created.append(fam_strip_path.name)

        # 8. itol_strip_host_group.txt (宏观外圈：Host group 门级归类 Top-N + Others)
        host_counts: Counter[str] = Counter()
        row_hosts: List[Tuple[str, str]] = []
        for c in rows:
            phylum = map_host_to_phylum(c.host)
            row_hosts.append((c.accession, phylum))
            if phylum and phylum != "Others":
                host_counts[phylum] += 1

        top_host_list = [name for name, _ in host_counts.most_common(max(1, top_host_groups))]
        top_host_set = set(top_host_list)
        host_legend: List[Tuple[str, str, int]] = [
            (name, get_host_group_color(name), host_counts[name]) for name in top_host_list
        ]
        other_host_cnt = sum(1 for _, p in row_hosts if p and p not in top_host_set)
        if other_host_cnt > 0:
            host_legend.append(("Others", "#6b7280", other_host_cnt))

        host_rows: List[Tuple[str, str, str]] = []
        for acc, phylum in row_hosts:
            if not phylum:
                continue
            if phylum in top_host_set:
                host_rows.append((acc, get_host_group_color(phylum), phylum))
            else:
                host_rows.append((acc, "#6b7280", "Others"))

        host_strip_path = out_dir / "itol_strip_host_group.txt"
        _write_colorstrip_dataset(
            out_path=host_strip_path,
            dataset_label="Host_Group_Ring",
            legend_title="Outer ring: Host group",
            strip_width=24,
            margin=6,
            legend_entries=host_legend,
            data_rows=host_rows,
        )
        created.append(host_strip_path.name)

        # 9. itol_symbol_query_star.txt (宏观最外侧查询株红色五角星)
        star_path = out_dir / "itol_symbol_query_star.txt"
        with open(star_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("DATASET_BINARY\n")
            fh.write("SEPARATOR TAB\n")
            fh.write("DATASET_LABEL\tQuery_Phage_Star\n")
            fh.write("COLOR\t#ef4444\n")
            fh.write("FIELD_SHAPES\t3\n")
            fh.write("FIELD_LABELS\tQuery Phage\n")
            fh.write("FIELD_COLORS\t#ef4444\n")
            fh.write("SHOW_LABELS\t0\n")
            fh.write("SYMBOL_SPACING\t6\n")
            fh.write("HEIGHT_FACTOR\t1.4\n")
            fh.write("MARGIN\t8\n")
            fh.write("LEGEND_TITLE\tQuery Marker\n")
            fh.write("LEGEND_SHAPES\t3\n")
            fh.write("LEGEND_COLORS\t#ef4444\n")
            fh.write("LEGEND_LABELS\tQuery Phage\n")
            fh.write("DATA\n")
            for c in rows:
                if c.role == "query":
                    fh.write(f"{c.accession}\t1\n")
        created.append(star_path.name)

        # 10. itol_labels_display.txt (将参考株登录号显示为 `实际名称 (登录号)` 标准发表标签)
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

        # 11. itol_clade_ranges.txt (已知属单系背景范围高亮)
        range_path = out_dir / "itol_clade_ranges.txt"
        range_lines: List[str] = ["TREE_COLORS", "SEPARATOR TAB", "DATA"]
        for c in rows:
            g = (c.genus or "").strip()
            if c.role != "outgroup" and g and g in genus_colors:
                range_lines.append(f"{c.accession}\trange\t{genus_colors[g]}\t{g}")
        range_path.write_text("\n".join(range_lines) + "\n", encoding="utf-8", newline="\n")
        created.append(range_path.name)

        # 12. metadata_table.tsv
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
                    "Host_Group",
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
                        map_host_to_phylum(c.host),
                        c.genome_length,
                        round(c.gc_content or 0.0, 2),
                        round(c.wg_ani, 2) if c.wg_ani is not None else "",
                        round(c.completeness, 1) if c.completeness is not None else "",
                    ]
                )
        created.append(tsv_path.name)

        return created
