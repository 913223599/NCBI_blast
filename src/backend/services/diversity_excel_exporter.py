# -*- coding: utf-8 -*-
"""
16S 扩增子混样多样性多工作表 Excel 导出构建器
100% 还原界面显示内容，并丰富下游生信与科研作图数据
"""
import os
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
import pandas as pd
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

logger = logging.getLogger("api_server")


def build_rich_diversity_excel(
    data: Dict[str, Any],
    excel_path: Path,
    custom_groups: Optional[List[Dict[str, Any]]] = None,
    translations: Optional[Dict[str, str]] = None
) -> Path:
    """
    生成包含 7-8 个科研级工作表的 Excel 综合报告
    """
    samples = data.get("samples", [])
    overview = data.get("taxa_overview", [])
    total_samples_cnt = len(samples)

    # 1. 物种中文翻译获取
    trans_map = dict(translations or {})
    all_taxa = sorted(list({
        d["taxon"] 
        for s in samples 
        for d in s.get("norm_result", {}).get("details", [])
    }))
    
    needed_taxa = [t for t in all_taxa if t not in trans_map and not t.lower().startswith("other") and "噪声" not in t]
    if needed_taxa:
        try:
            from ...utils.translation.biology_translator import get_global_biology_translator
            translator = get_global_biology_translator()
            batch_res = translator.translate_batch(needed_taxa, category="species")
            trans_map.update(batch_res)
        except Exception as exc:
            logger.warning(f"获取生物学翻译失败: {exc}")

    for t in all_taxa:
        if t.lower().startswith("other") or "噪声" in t:
            trans_map[t] = "低频测序噪声 (<1% 过滤合集)"
        elif t not in trans_map:
            trans_map[t] = t

    # ──────────────────────────────────────────────────────────
    # Sheet 1: 物种检出排行榜与总览 (还原 TAB 2)
    # ──────────────────────────────────────────────────────────
    overview_rows = []
    for idx, t in enumerate(overview, 1):
        t_name = t.get("taxon", "")
        zh_name = trans_map.get(t_name, t_name)
        norm_pct = float(t.get("norm_pct", 0.0))
        raw_pct = float(t.get("raw_pct", 0.0))
        
        freq_raw = str(t.get("sample_frequency", "0"))
        if "/" in freq_raw:
            try:
                cov_cnt = int(freq_raw.split("/")[0])
            except:
                cov_cnt = 0
        else:
            try:
                cov_cnt = int(freq_raw)
            except:
                cov_cnt = 0
                
        cov_pct = round((cov_cnt / total_samples_cnt * 100), 1) if total_samples_cnt > 0 else 0.0

        if idx == 1 and norm_pct >= 30:
            dom_status = "绝对优势物种"
        elif norm_pct >= 15:
            dom_status = "主要优势物种"
        elif t_name.lower().startswith("other") or "噪声" in t_name:
            dom_status = "噪声过滤合集"
        else:
            dom_status = "共存背景物种"

        overview_rows.append({
            "综合排名": idx,
            "物种拉丁学名 (Taxon)": t_name,
            "中文规范译名": zh_name,
            "16S 拷贝数 (GCN)": t.get("gcn_mean", 1.0),
            "全批次检出总 Reads": t.get("raw_count", 0),
            "总体校正后相对丰度 (%)": round(norm_pct, 2),
            "全批次原始 Reads 占比 (%)": round(raw_pct, 2),
            "采样点位检出频次": f"{cov_cnt}/{total_samples_cnt}",
            "点位检出覆盖率 (%)": f"{cov_pct}%",
            "群落优势级别": dom_status
        })
    df_overview = pd.DataFrame(overview_rows)

    # ──────────────────────────────────────────────────────────
    # Sheet 2: 样本明细大表 (原始点位) (还原 TAB 3 原始点位明细卡片)
    # ──────────────────────────────────────────────────────────
    detail_rows = []
    for s in samples:
        s_name = s.get("sample_name", "")
        s_reads = s.get("total_reads", 0)
        s_class = s.get("classified_reads", 0)
        details = s.get("norm_result", {}).get("details", [])
        for d_idx, d in enumerate(details):
            t_name = d.get("taxon", "")
            zh_name = trans_map.get(t_name, t_name)
            d_norm = float(d.get("norm_pct", 0.0))
            d_raw = float(d.get("raw_pct", 0.0))

            if d_idx == 0 and d_norm >= 30 and not (t_name.lower().startswith("other") or "噪声" in t_name):
                d_status = "主要优势物种"
            elif t_name.lower().startswith("other") or "噪声" in t_name:
                d_status = "低频噪声过滤合集"
            else:
                d_status = "共存物种"

            detail_rows.append({
                "采样点位": s_name,
                "点位有效 Reads": s_reads,
                "分类确证 Reads": s_class,
                "检出物种拉丁名": t_name,
                "中文规范译名": zh_name,
                "Reads 计数": d.get("raw_count", 0),
                "原始占比 (%)": round(d_raw, 2),
                "16S 拷贝数均值 (GCN)": d.get("gcn_mean", 1.0),
                "GCN 匹配精度": d.get("gcn_rank", "species"),
                "rrnDB 校正后占比 (%)": round(d_norm, 2),
                "群落地位": d_status
            })
    df_details = pd.DataFrame(detail_rows)

    # ──────────────────────────────────────────────────────────
    # Sheet 3: 分组聚合明细大表 (若有分组规则，还原 TAB 3 合并模式)
    # ──────────────────────────────────────────────────────────
    group_detail_rows = []
    if custom_groups:
        for g in custom_groups:
            g_name = g.get("name", "未命名组")
            matched = g.get("matchedSamples", [])
            if not matched:
                continue
            sub_samples = [s for s in samples if s.get("sample_name") in matched]
            if not sub_samples:
                continue

            g_total_reads = sum(s.get("total_reads", 0) for s in sub_samples)
            g_class_reads = sum(s.get("classified_reads", 0) for s in sub_samples)
            
            taxa_counts: Dict[str, int] = {}
            gcn_map: Dict[str, float] = {}
            for s in sub_samples:
                for d in s.get("norm_result", {}).get("details", []):
                    tn = d["taxon"]
                    taxa_counts[tn] = taxa_counts.get(tn, 0) + d.get("raw_count", 0)
                    gcn_map[tn] = d.get("gcn_mean", 1.0)

            total_norm = sum(c / gcn_map.get(tn, 1.0) for tn, c in taxa_counts.items())
            sorted_taxa = sorted(taxa_counts.items(), key=lambda x: x[1], reverse=True)

            for g_idx, (tn, cnt) in enumerate(sorted_taxa):
                gcn = gcn_map.get(tn, 1.0)
                norm_v = (cnt / gcn / total_norm * 100) if total_norm > 0 else 0.0
                raw_v = (cnt / g_class_reads * 100) if g_class_reads > 0 else 0.0
                zh_n = trans_map.get(tn, tn)

                if g_idx == 0 and norm_v >= 30 and not (tn.lower().startswith("other") or "噪声" in tn):
                    st = "组内主要优势物种"
                elif tn.lower().startswith("other") or "噪声" in tn:
                    st = "噪声过滤合集"
                else:
                    st = "共存物种"

                group_detail_rows.append({
                    "合并分组名称": g_name,
                    "包含点位数量": len(matched),
                    "包含采样点位清单": ",".join(matched),
                    "分组总 Reads": g_total_reads,
                    "分组有效 Reads": g_class_reads,
                    "检出物种拉丁名": tn,
                    "中文规范译名": zh_n,
                    "组内累加 Reads": cnt,
                    "组内原始占比 (%)": round(raw_v, 2),
                    "16S 拷贝数 (GCN)": gcn,
                    "rrnDB 校正后占比 (%)": round(norm_v, 2),
                    "群落地位": st
                })
    df_group_details = pd.DataFrame(group_detail_rows)

    # ──────────────────────────────────────────────────────────
    # Sheet 4: 样本群落结构与多样性 (Alpha 多样性指数)
    # ──────────────────────────────────────────────────────────
    alpha_rows = []
    for s in samples:
        a = s.get("alpha_diversity", {})
        details = s.get("norm_result", {}).get("details", [])
        dom_taxon = details[0]["taxon"] if details else "None"
        dom_pct = details[0]["norm_pct"] if details else 0.0
        dom_zh = trans_map.get(dom_taxon, dom_taxon)

        alpha_rows.append({
            "采样点位编号": s.get("sample_name"),
            "总测序 Reads": s.get("total_reads", 0),
            "有效分类 Reads": s.get("classified_reads", 0),
            "检出物种丰富度 (Richness)": a.get("richness", len(details)),
            "第一优势菌拉丁名": dom_taxon,
            "第一优势菌中文名": dom_zh,
            "第一优势菌校正丰度 (%)": round(dom_pct, 2),
            "香农多样性指数 (Shannon)": a.get("shannon", 0.0),
            "辛普森多样性指数 (Simpson)": a.get("simpson", 0.0),
            "Chao1 丰富度指数": a.get("chao1", 0.0),
            "Pielou 物种均匀度 (Evenness)": a.get("evenness", 0.0)
        })
    df_alpha = pd.DataFrame(alpha_rows)

    # ──────────────────────────────────────────────────────────
    # Sheet 5: 相对丰度矩阵 (校正后相对丰度 %) (科研制图 OTU Matrix)
    # ──────────────────────────────────────────────────────────
    gcn_dict = {t["taxon"]: t.get("gcn_mean", 1.0) for t in overview}
    norm_matrix_rows = []
    for tn in all_taxa:
        row = {
            "物种拉丁学名": tn,
            "中文规范译名": trans_map.get(tn, tn),
            "16S 拷贝数 (GCN)": gcn_dict.get(tn, 1.0)
        }
        for s in samples:
            s_name = s.get("sample_name", "")
            d_map = {d["taxon"]: d.get("norm_pct", 0.0) for d in s.get("norm_result", {}).get("details", [])}
            row[s_name] = round(d_map.get(tn, 0.0), 2)
        norm_matrix_rows.append(row)
    df_norm_matrix = pd.DataFrame(norm_matrix_rows)

    # ──────────────────────────────────────────────────────────
    # Sheet 6: 原始 Reads 计数矩阵 (Count Matrix，下游差异分析必备)
    # ──────────────────────────────────────────────────────────
    count_matrix_rows = []
    for tn in all_taxa:
        row = {
            "物种拉丁学名": tn,
            "中文规范译名": trans_map.get(tn, tn)
        }
        for s in samples:
            s_name = s.get("sample_name", "")
            d_map = {d["taxon"]: d.get("raw_count", 0) for d in s.get("norm_result", {}).get("details", [])}
            row[s_name] = d_map.get(tn, 0)
        count_matrix_rows.append(row)
    df_count_matrix = pd.DataFrame(count_matrix_rows)

    # ──────────────────────────────────────────────────────────
    # Sheet 7: 样本分组映射规则 (若存在)
    # ──────────────────────────────────────────────────────────
    group_map_rows = []
    if custom_groups:
        for idx, g in enumerate(custom_groups, 1):
            matched = g.get("matchedSamples", [])
            group_map_rows.append({
                "序号": idx,
                "分组名称": g.get("name", f"分组 {idx}"),
                "定义匹配规则": g.get("pattern", "自定义"),
                "包含点位数量": len(matched),
                "包含的具体采样点位列表": ", ".join(matched)
            })
    df_group_map = pd.DataFrame(group_map_rows)

    # ──────────────────────────────────────────────────────────
    # Sheet 8: 分析参数与权威数据库说明
    # ──────────────────────────────────────────────────────────
    meta_rows = [
        {"分析项目": "分析类型", "设定参数/数据库版本": "16S 全长扩增子混样多样性还原与多拷贝校正", "生物学说明": "针对未纯化样本、环境混样与多采样点位的高通量群落解析"},
        {"分析项目": "16S 参考数据库", "设定参数/数据库版本": "NCBI RefSeq 16S Targeted Loci", "生物学说明": "国际公认权威全长 16S 核糖体 RNA 标准基因库"},
        {"分析项目": "拷贝数校正数据库", "设定参数/数据库版本": "rrnDB v5.10 (Pan-taxa Statistics)", "生物学说明": "校正 16S 多操纵子偏好，还原真实细菌细胞相对丰度"},
        {"分析项目": "低频噪声过滤机制", "设定参数/数据库版本": "1% 相对阈值 + 孤儿 Reads 隔离", "生物学说明": "排除三代长读长随机测序假阳性，将噪点统一归并到 Other"},
        {"分析项目": "操纵子异质性诊断", "设定参数/数据库版本": "跨位点突变共识算法已启用", "生物学说明": "精确区分单菌株操纵子多拷贝多态性与真实多物种共存"},
        {"分析项目": "生物分类学翻译", "设定参数/数据库版本": "NCBI Taxonomy + 物种专业词典", "生物学说明": "全自动拉丁学名至中文规范译名对照"}
    ]
    df_meta = pd.DataFrame(meta_rows)

    # ──────────────────────────────────────────────────────────
    # 写入 Excel 并应用 openpyxl 专业样式
    # ──────────────────────────────────────────────────────────
    with pd.ExcelWriter(str(excel_path), engine="openpyxl") as writer:
        df_overview.to_excel(writer, sheet_name="物种检出排行榜与总览", index=False)
        df_details.to_excel(writer, sheet_name="样本明细大表(原始点位)", index=False)
        if not df_group_details.empty:
            df_group_details.to_excel(writer, sheet_name="分组聚合明细大表", index=False)
        df_alpha.to_excel(writer, sheet_name="样本群落结构与多样性", index=False)
        df_norm_matrix.to_excel(writer, sheet_name="相对丰度矩阵(校正后%)", index=False)
        df_count_matrix.to_excel(writer, sheet_name="原始Reads计数矩阵", index=False)
        if not df_group_map.empty:
            df_group_map.to_excel(writer, sheet_name="样本分组映射规则", index=False)
        df_meta.to_excel(writer, sheet_name="分析参数与数据库说明", index=False)

    # 美化工作表
    _beautify_excel_workbook(excel_path)
    return excel_path


def _beautify_excel_workbook(excel_path: Path):
    """
    对生成的 Excel 各工作表应用专业科研配色、自适应列宽与对齐
    """
    try:
        wb = openpyxl.load_workbook(str(excel_path))
        header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
        header_font = Font(name="Microsoft YaHei", size=10, bold=True, color="FFFFFF")
        regular_font = Font(name="Microsoft YaHei", size=9)
        border_thin = Border(
            left=Side(style="thin", color="E2E8F0"),
            right=Side(style="thin", color="E2E8F0"),
            top=Side(style="thin", color="E2E8F0"),
            bottom=Side(style="thin", color="E2E8F0")
        )

        for ws in wb.worksheets:
            # 冻结首行
            ws.freeze_panes = "A2"
            
            # 美化表头
            for cell in ws[1]:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=False)
                cell.border = border_thin
            ws.row_dimensions[1].height = 26

            # 内容单元格边框与对齐
            for row in ws.iter_rows(min_row=2):
                for cell in row:
                    cell.font = regular_font
                    cell.border = border_thin
                    val = cell.value
                    if isinstance(val, (int, float)):
                        cell.alignment = Alignment(horizontal="right", vertical="center")
                    else:
                        cell.alignment = Alignment(horizontal="left", vertical="center")

            # 自适应列宽
            for col in ws.columns:
                max_len = 0
                first_cell = col[0]
                col_idx = first_cell.column
                if not isinstance(col_idx, int):
                    continue
                col_letter = get_column_letter(col_idx)
                for cell in col:
                    v = str(cell.value or "")
                    # 中文字符按 2 字符计算
                    calc_len = sum(2 if ord(c) > 127 else 1 for c in v)
                    if calc_len > max_len:
                        max_len = calc_len
                ws.column_dimensions[col_letter].width = max(12, min(50, max_len + 3))

        wb.save(str(excel_path))
    except Exception as exc:
        logger.warning(f"Excel 样式美化异常 (数据仍正常导出): {exc}")
