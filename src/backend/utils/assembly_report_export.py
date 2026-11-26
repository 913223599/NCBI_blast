# -*- coding: utf-8 -*-
"""
assembly_report_export.py - 噬菌体基因组诊断报告 HTML 导出引擎
从 AssemblyReportParser 的结构化数据生成单页自包含诊断报告，
展示层 CSS/Chart.js 模板已拆离至 assembly_report_template.py。
"""
from __future__ import annotations

import base64
import html
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .assembly_report_template import assemble_html_document, build_chart_script

logger = logging.getLogger("api_server")


class ReportExporter:
    """将组装、质控、注释、安全性与进化结果渲染为自包含 HTML 诊断报告。"""

    def __init__(self, task_dir: Path) -> None:
        self.task_dir = task_dir

    def _get_image_b64(self, img_path: Path) -> str:
        """将图片文件编码为 base64 字符串。"""
        if img_path.exists() and img_path.stat().st_size > 0:
            try:
                with open(img_path, "rb") as f:
                    return base64.b64encode(f.read()).decode("utf-8")
            except Exception as exc:
                logger.warning("图片转 base64 失败 (%s): %s", img_path.name, exc)
        return ""

    @staticmethod
    def _safe_escape(val: Any) -> str:
        """安全的 HTML 转义函数，防止 XSS 注入和格式破坏。"""
        if val is None:
            return ""
        return html.escape(str(val))

    @staticmethod
    def _fmt_reads(n: Any) -> str:
        if not n:
            return "0"
        try:
            val = int(n)
            if val >= 1_000_000:
                return f"{val / 1_000_000:.2f}M"
            if val >= 1_000:
                return f"{val / 1_000:.1f}K"
            return str(val)
        except Exception:
            return "0"

    @staticmethod
    def _fmt_bp(n: Any) -> str:
        if not n:
            return "0 bp"
        try:
            val = int(n)
            if val >= 1_000_000:
                return f"{val / 1_000_000:.2f} Mbp"
            if val >= 1_000:
                return f"{val / 1_000:.1f} Kbp"
            return f"{val} bp"
        except Exception:
            return "0 bp"

    @staticmethod
    def _fmt_pct(v: Any) -> str:
        if v is None or v == 0:
            return "0.00%"
        try:
            return f"{float(v) * 100:.2f}%"
        except (ValueError, TypeError):
            return str(v)

    def _load_visual_assets(self) -> Tuple[str, str]:
        """读取基因组图谱与进化树 PNG 的 base64 编码。"""
        map_b64 = ""
        tree_b64 = ""
        plot_dir = self.task_dir / "phageannotationstep" / "phage_plot"
        if plot_dir.exists():
            pngs = sorted(plot_dir.glob("*.png"), key=lambda x: x.stat().st_size, reverse=True)
            if pngs:
                map_b64 = self._get_image_b64(pngs[0])
            tree_path = plot_dir / "phage_phylogeny.png"
            if tree_path.exists():
                tree_b64 = self._get_image_b64(tree_path)
        return map_b64, tree_b64

    def _render_qc_section(self, qc: Dict[str, Any], host_pct: float) -> str:
        before = qc.get("before") or {}
        after = qc.get("after") or {}
        filtering = qc.get("filtering") or {}
        dup_rate = (qc.get("duplication") or {}).get("rate", 0)
        insert_peak = (qc.get("insert_size") or {}).get("peak", 0)
        adapter_trimmed = (qc.get("adapter_cutting") or {}).get("adapter_trimmed_reads", 0)
        total_before = before.get("total_reads") or 1

        passed = filtering.get("passed_filter_reads", 0)
        low_quality = filtering.get("low_quality_reads", 0)
        too_many_n = filtering.get("too_many_N_reads", 0)
        too_short = filtering.get("too_short_reads", 0)
        too_long = filtering.get("too_long_reads", 0)
        corrected = filtering.get("corrected_reads", 0)
        passed_pct = round(passed / total_before * 100, 4)

        return f"""<!-- 1. QC -->
<section>
<h2>1. 测序质控与过滤审计</h2>
  <div class="grid g5">
    <div class="card"><span class="lbl">原始序列数</span><span class="val">{self._fmt_reads(before.get("total_reads", 0))}</span></div>
    <div class="card"><span class="lbl">清洁序列数</span><span class="val">{self._fmt_reads(after.get("total_reads", 0))}</span></div>
    <div class="card" style="background:#fff1f2;border-color:#fecaca;"><span class="lbl" style="color:#e11d48;">宿主占比</span><span class="val" style="color:#be123c;">{host_pct:.2f}%</span></div>
    <div class="card"><span class="lbl">重复率</span><span class="val">{self._fmt_pct(dup_rate)}</span></div>
    <div class="card"><span class="lbl">插入片段峰值</span><span class="val">{insert_peak} bp</span></div>
  </div>
<h3>过滤前后对比</h3>
<table>
  <thead><tr><th>指标</th><th>过滤前</th><th>过滤后</th></tr></thead>
  <tbody>
    <tr><td>总序列数 (Reads)</td><td>{self._fmt_reads(before.get("total_reads", 0))}</td><td>{self._fmt_reads(after.get("total_reads", 0))}</td></tr>
    <tr><td>总碱基数 (Bases)</td><td>{self._fmt_bp(before.get("total_bases", 0))}</td><td>{self._fmt_bp(after.get("total_bases", 0))}</td></tr>
    <tr><td>Q20 比率</td><td>{self._fmt_pct(before.get("q20_rate", 0))}</td><td>{self._fmt_pct(after.get("q20_rate", 0))}</td></tr>
    <tr><td>Q30 比率</td><td>{self._fmt_pct(before.get("q30_rate", 0))}</td><td>{self._fmt_pct(after.get("q30_rate", 0))}</td></tr>
    <tr><td>GC 含量</td><td>{self._fmt_pct(before.get("gc_content", 0))}</td><td>{self._fmt_pct(after.get("gc_content", 0))}</td></tr>
    <tr><td>平均读长 R1 / R2</td>
        <td>{before.get("read1_mean_length", 0)} / {before.get("read2_mean_length", 0)} bp</td>
        <td>{after.get("read1_mean_length", 0)} / {after.get("read2_mean_length", 0)} bp</td></tr>
  </tbody>
</table>
<h3>过滤统计</h3>
<table>
<thead><tr><th>过滤类别</th><th>序列数</th><th>占比</th></tr></thead>
<tbody>
  <tr><td>[通过] 通过质控</td><td><strong>{self._fmt_reads(passed)}</strong></td><td><span class="tag tag-ok">{passed_pct}%</span></td></tr>
  <tr><td>低质量剔除</td><td>{low_quality:,}</td><td>{self._fmt_pct(low_quality / total_before)}</td></tr>
  <tr><td>N 碱基过多</td><td>{too_many_n:,}</td><td>{self._fmt_pct(too_many_n / total_before)}</td></tr>
  <tr><td>过短剔除</td><td>{too_short:,}</td><td>{self._fmt_pct(too_short / total_before)}</td></tr>
  <tr><td>过长剔除</td><td>{too_long:,}</td><td>{self._fmt_pct(too_long / total_before)}</td></tr>
  <tr><td>接头修剪</td><td>{adapter_trimmed:,}</td><td>{self._fmt_pct(adapter_trimmed / total_before)}</td></tr>
  <tr><td>碱基校正 (重叠区)</td><td>{corrected:,}</td><td>--</td></tr>
</tbody>
</table>
<h3>质量曲线与碱基组成</h3>
<div class="grid g3">
  <div class="chart-box"><p>碱基质量分布 (R1 + R2)</p><canvas id="cQuality"></canvas></div>
  <div class="chart-box"><p>碱基组成分布 (过滤后 R1)</p><canvas id="cBase"></canvas></div>
  <div class="chart-box"><p>插入片段长度分布</p><canvas id="cInsert"></canvas></div>
</div>
</section>"""

    def _render_assembly_section(self, asm: Dict[str, Any]) -> str:
        topo_tag = (
            '<span class="tag tag-ok">Circular (环形基因组)</span>'
            if asm.get("is_circular", False)
            else '<span class="tag tag-info">Linear (线性基因组)</span>'
        )
        return f"""<!-- 2. Assembly -->
<section>
<h2>2. 基因组组装与拓扑分析</h2>
<div class="grid g4">
  <div class="card"><span class="lbl">基因组总长</span><span class="val">{self._fmt_bp(asm.get("total_length", 0))}</span></div>
  <div class="card"><span class="lbl">GC 含量</span><span class="val">{asm.get("gc_content", 0)}%</span></div>
  <div class="card"><span class="lbl">N50</span><span class="val">{self._fmt_bp(asm.get("n50", 0))}</span></div>
  <div class="card"><span class="lbl">平均测序深度</span><span class="val">{asm.get("avg_depth", 0)}x</span></div>
</div>
<table>
<thead><tr><th>指标</th><th>数值</th><th>备注</th></tr></thead>
<tbody>
  <tr><td>Contig 数量</td><td>{asm.get("num_contigs", 0)}</td><td>L50 = {asm.get("l50", 0)}</td></tr>
  <tr><td>最长 / 最短 Contig</td><td>{self._fmt_bp(asm.get("longest", 0))} / {self._fmt_bp(asm.get("shortest", 0))}</td><td>长度范围</td></tr>
  <tr><td>拓扑结构</td><td>{topo_tag}</td><td>基于物理序列拼接结果验证</td></tr>
</tbody>
</table>
</section>"""

    def _render_checkv_section(self, checkv: Dict[str, Any]) -> str:
        return f"""<!-- 3. CheckV -->
<section>
<h2>3. 基因组质量评估 (CheckV)</h2>
<div class="grid g4">
  <div class="card"><span class="lbl">质量等级</span><span class="val">{self._safe_escape(checkv.get("quality", "--"))}</span></div>
  <div class="card"><span class="lbl">完整度</span><span class="val">{self._safe_escape(checkv.get("completeness", "--"))}%</span></div>
  <div class="card"><span class="lbl">污染度</span><span class="val">{self._safe_escape(checkv.get("contamination", "0"))}%</span></div>
  <div class="card"><span class="lbl">基因总数</span><span class="val">{checkv.get("gene_count", 0)}</span></div>
</div>
<table>
<thead><tr><th>评估项</th><th>结果</th></tr></thead>
<tbody>
  <tr><td>MIUViG 质量标准</td><td>{self._safe_escape(checkv.get("miuvig_quality", "--"))}</td></tr>
  <tr><td>完整度评估方法</td><td>{self._safe_escape(checkv.get("completeness_method", "--"))}</td></tr>
  <tr><td>病毒基因数 / 宿主基因数</td><td>{checkv.get("viral_genes", 0)} / {checkv.get("host_genes", 0)}</td></tr>
  <tr><td>前噬菌体 (Provirus)</td><td>{self._safe_escape(checkv.get("provirus", "No"))}</td></tr>
  <tr><td>kmer 频率</td><td>{self._safe_escape(checkv.get("kmer_freq", "--"))}</td></tr>
</tbody>
</table>
</section>"""

    def _render_annotation_section(
        self,
        anno: Dict[str, Any],
        all_genes: List[Dict[str, Any]],
        cds_genes: List[Dict[str, Any]],
    ) -> str:
        type_counts = anno.get("type_counts") or {}
        func_counts = (anno.get("pharokka") or {}).get("functions", [])
        func_rows = []
        for fc in sorted(func_counts, key=lambda x: -x.get("count", 0)):
            name = fc.get("name", "")
            if name == "CDS":
                continue
            count = fc.get("count", 0)
            pct_val = round(count / len(cds_genes) * 100, 1) if cds_genes else 0
            func_rows.append(f"<tr><td>{self._safe_escape(name)}</td><td>{count}</td><td>{pct_val}%</td></tr>")

        cds_rows = []
        for g in cds_genes[:50]:
            prod = self._safe_escape(g.get("product", ""))
            cds_rows.append(
                f"<tr>"
                f"<td class='mono'>{self._safe_escape(g.get('cds_id', ''))}</td>"
                f"<td>{self._safe_escape(g.get('start', ''))}-{self._safe_escape(g.get('end', ''))}</td>"
                f"<td>{self._safe_escape(g.get('strand', ''))}</td>"
                f"<td><span class='func-tag'>{self._safe_escape(g.get('function', ''))}</span></td>"
                f"<td class='product-cell' title='{prod}'>{prod}</td>"
                f"</tr>"
            )
        if len(cds_genes) > 50:
            cds_rows.append(
                f"<tr><td colspan='5' style='text-align:center;color:#94a3b8;'>... 共 {len(cds_genes)} 条 CDS, 仅展示前 50 条</td></tr>"
            )

        return f"""<!-- 4. Annotation -->
<section>
<h2>4. 基因组功能注释</h2>
<div class="grid g4" style="margin-bottom:20px;">
  <div class="card"><span class="lbl">注释特征总数</span><span class="val">{len(all_genes)}</span></div>
  <div class="card"><span class="lbl">编码序列 (CDS)</span><span class="val">{type_counts.get("CDS", 0)}</span></div>
  <div class="card"><span class="lbl">转运 RNA (tRNA)</span><span class="val">{type_counts.get("tRNA", 0)}</span></div>
  <div class="card"><span class="lbl">假基因</span><span class="val">{type_counts.get("pseudogene", 0)}</span></div>
</div>
<h3>功能分类统计</h3>
<table>
<thead><tr><th>功能类别</th><th>数量</th><th>占比</th></tr></thead>
<tbody>
{chr(10).join(func_rows)}
</tbody>
</table>
<h3>CDS 注释详表</h3>
<div style="max-height:400px;overflow-y:auto;border:1px solid var(--bd);border-radius:8px;">
<table>
<thead><tr><th>基因 ID</th><th>位置</th><th>链方向</th><th>功能分类</th><th>产物名称</th></tr></thead>
<tbody>
{chr(10).join(cds_rows)}
</tbody>
</table>
</div>
</section>"""

    def _render_defense_html(self, defense_hits: Any) -> str:
        if not isinstance(defense_hits, dict) or not defense_hits:
            return "<p style='color:#94a3b8; font-size:0.9em;'>未检出显著的抗噬菌体防御系统基因 (Hit < 1e-10)</p>"
        rows = []
        for idx, (locus, hit) in enumerate(defense_hits.items(), 1):
            sys_name = hit.get("system", "Unknown")
            eval_val = hit.get("evalue", 0.0)
            clr = "#b91c1c" if ("Acr" in sys_name or "Anti-CRISPR" in sys_name) else "#1e293b"
            rows.append(
                f"<tr>"
                f"<td style='text-align:center;'>{idx}</td>"
                f"<td class='mono'>{self._safe_escape(locus)}</td>"
                f"<td style='font-weight:bold; color:{clr};'>{self._safe_escape(sys_name)}</td>"
                f"<td class='mono' style='font-size:0.85em;'>{eval_val:.2e}</td>"
                f"</tr>"
            )
        return (
            "<div style='margin-top:20px;'>"
            "<h4>抗噬菌体防御系统 (dbAPIS) 检测详情</h4>"
            "<table class='data-table' style='width:100%;font-size:0.9em;'>"
            "<thead><tr><th>#</th><th>Locus Tag</th><th>System / Protein</th><th>E-value</th></tr></thead>"
            "<tbody>" + "\n".join(rows) + "</tbody></table></div>"
        )

    def _render_host_matches_html(self, host_hits: List[Dict[str, Any]]) -> str:
        if not host_hits:
            return "<span style='color:#94a3b8;'>未发现显著高同源原噬菌体 (ANI < 80%)</span>"
        badge_map = {
            "High": "<span class='tag tag-ok'>High</span>",
            "Medium": "<span class='tag tag-warn'>Medium</span>",
        }
        rows = []
        for idx, hit in enumerate(host_hits, 1):
            conf_badge = badge_map.get(hit.get("confidence", "Low"), "<span style='color:#94a3b8;'>Low</span>")
            src_badge = (
                "<span style='background:#e0f2fe;color:#0369a1;padding:1px 6px;"
                f"border-radius:4px;font-size:0.8em;'>{self._safe_escape(hit.get('db_source', '--'))}</span>"
            )
            rows.append(
                f"<tr>"
                f"<td style='text-align:center;font-weight:bold;'>{idx}</td>"
                f"<td>{conf_badge}</td>"
                f"<td>{self._safe_escape(hit.get('description', 'Unknown Organism'))}</td>"
                f"<td class='mono' style='font-size:0.85em;'>{self._safe_escape(hit.get('accession', 'N/A'))}</td>"
                f"<td style='font-size:0.85em;'>{self._safe_escape(hit.get('distance', '--'))}</td>"
                f"<td style='font-size:0.85em;'>{self._safe_escape(hit.get('p_value', '--'))}</td>"
                f"<td>{src_badge}</td>"
                f"</tr>"
            )
        return (
            "<table class='data-table' style='width:100%;font-size:0.9em;'>"
            "<thead><tr><th>#</th><th>Confidence</th><th>Host Organism</th>"
            "<th>Accession</th><th>Distance</th><th>P-value</th><th>Source</th></tr></thead>"
            "<tbody>" + "\n".join(rows) + "</tbody></table>"
        )

    @staticmethod
    def _resolve_acr_summary(audit: Dict[str, Any]) -> Tuple[str, str]:
        defense_hits = audit.get("defense_systems") or {}
        apis_acr = (
            [
                v["system"]
                for v in defense_hits.values()
                if "Acr" in v.get("system", "") or "Anti-CRISPR" in v.get("system", "")
            ]
            if isinstance(defense_hits, dict)
            else []
        )
        if apis_acr:
            return f"{len(apis_acr)} 个检出 (dbAPIS)", "HMM 结构域扫描 (APIS)"
        acr_raw = audit.get("anti_crispr", "未检出")
        display = "未检出" if acr_raw in ("Not Detected", "None", None, "") else str(acr_raw)
        evidence = {"direct": "Diamond blastp 序列比对", "reference": "参考推断 (PhageScope)"}.get(
            audit.get("anti_crispr_evidence", ""), "—"
        )
        return display, evidence

    def _render_safety_section(
        self,
        audit: Dict[str, Any],
        all_genes: List[Dict[str, Any]],
        tree_b64: str,
    ) -> str:
        def _has_marker(keyword: str) -> bool:
            return any(
                keyword in (((g.get("product") or "") + " " + (g.get("function") or "")).lower())
                for g in all_genes
            )

        integrase_found = _has_marker("integrase")
        repressor_found = _has_marker("repressor")
        excisionase_found = _has_marker("excisionase")

        safety = audit.get("safety_status", "Pending Review")
        amr_list = audit.get("amr_genes", [])
        amr_display = f"{len(amr_list)} 个检出" if isinstance(amr_list, list) and amr_list else "未检出"
        amr_evidence = (
            ("blastp 序列比对" if audit.get("amr_genes_direct") else "参考推断 (PhageScope)")
            if isinstance(amr_list, list) and amr_list
            else ""
        )

        vf_list = audit.get("virulent_factors", [])
        vf_display = f"{len(vf_list)} 个检出" if isinstance(vf_list, list) and vf_list else "未检出"
        vf_evidence = (
            ("blastp 序列比对" if audit.get("virulent_factors_direct") else "参考推断 (PhageScope)")
            if isinstance(vf_list, list) and vf_list
            else ""
        )

        acr_display, acr_evidence = self._resolve_acr_summary(audit)
        defense_html = self._render_defense_html(audit.get("defense_systems"))
        host_matches_html = self._render_host_matches_html(
            (audit.get("host_prediction_enhanced") or {}).get("top_hits", [])
        )

        taxonomy = audit.get("taxonomy_info") or {}
        tax_host = taxonomy.get("Host", audit.get("host_origin", "--"))
        tree_html = (
            f"""
<h3 style="margin-top:24px;">进化演化分析 (Top 30 Genomic Relationships)</h3>
<div style="background:#fff; border:1px solid var(--bd); border-radius:12px; padding:20px; text-align:center;">
    <img src="data:image/png;base64,{tree_b64}" alt="Phylogenetic Tree" style="max-width:100%; height:auto; border-radius:4px;">
    <p style="font-size:11px; color:#64748b; margin-top:12px;">注：红色加粗节点 (*) 为当前检测样本。分支长度代表 Mash 基因组距离 (1-ANI)。</p>
</div>"""
            if tree_b64
            else ""
        )
        ok_tag = '<span class="tag tag-ok">未检出</span>'
        warn_tag = '<span class="tag tag-warn">检出</span>'
        safety_cls = "tag-ok" if ("Secure" in str(safety) or "Clear" in str(safety)) else "tag-warn"

        return f"""<!-- 5. Safety -->
<section>
<h2>5. 安全性与生活史审计</h2>
<h3>溶源性证据搜索</h3>
<table>
<thead><tr><th>标志物</th><th>检测结果</th><th>生物学意义</th></tr></thead>
<tbody>
  <tr><td>整合酶 (Integrase)</td><td>{warn_tag if integrase_found else ok_tag}</td><td>溶源性一级证据 — 催化噬菌体DNA整合至宿主基因组</td></tr>
  <tr><td>阻遏蛋白 (Repressor)</td><td>{warn_tag if repressor_found else ok_tag}</td><td>溶源性二级证据 — 维持溶源状态的转录调控因子</td></tr>
  <tr><td>切除酶 (Excisionase)</td><td>{warn_tag if excisionase_found else ok_tag}</td><td>溶源性三级证据 — 催化前噬菌体从宿主基因组切除</td></tr>
  <tr><td>附着位点 (attP)</td><td><span class="tag tag-info">待实验验证</span></td><td>需结合湿实验确认噬菌体末端附着序列</td></tr>
</tbody>
</table>
<h3>安全性评估</h3>
<p style="font-size:12px;color:#64748b;margin:-8px 0 12px;">检测方法: Tier 1 blastp 序列比对 (CDS → PhageScope 蛋白库 105万条, E≤1e-10) + 交叉查询 AMR/VF/ACR 元数据表</p>
<table>
<thead><tr><th>评估项目</th><th>结果</th><th>证据来源</th></tr></thead>
<tbody>
  <tr><td>生活方式 (Lifestyle)</td><td><strong>{self._safe_escape(audit.get("lifestyle", "Unknown"))}</strong></td><td>参考推断 (PhageScope)</td></tr>
  <tr><td>毒力因子 (VFDB)</td><td><span class="tag {'tag-warn' if vf_list else 'tag-ok'}">{self._safe_escape(vf_display)}</span></td><td>{self._safe_escape(vf_evidence) if vf_evidence else "—"}</td></tr>
  <tr><td>耐药基因 (CARD)</td><td><span class="tag {'tag-warn' if amr_list else 'tag-ok'}">{self._safe_escape(amr_display)}</span></td><td>{self._safe_escape(amr_evidence) if amr_evidence else "—"}</td></tr>
  <tr><td>抗 CRISPR 蛋白</td><td>{self._safe_escape(acr_display)}</td><td>{self._safe_escape(acr_evidence) if acr_evidence else "—"}</td></tr>
  <tr><td>综合安全评级</td><td><span class="tag {safety_cls}">{self._safe_escape(safety)}</span></td><td>基于以上指标综合裁定</td></tr>
</tbody>
</table>
{defense_html}
<h3>宿主范围与分类溯源</h3>
<table>
<thead><tr><th>分类项</th><th>结果</th></tr></thead>
<tbody>
  <tr><td>宿主来源 (Host Origin)</td><td><strong>{self._safe_escape(tax_host)}</strong></td></tr>
  <tr><td>最近参考基因组</td><td>{self._safe_escape(taxonomy.get("top_hit_name", "--"))}</td></tr>
  <tr><td>分类谱系</td><td class="mono">{self._safe_escape(taxonomy.get("Classification", "--"))}</td></tr>
  <tr><td>科 (Family)</td><td>{self._safe_escape(taxonomy.get("Family", "--"))}</td></tr>
  <tr><td>属 (Genus)</td><td>{self._safe_escape(taxonomy.get("Genus", "--"))}</td></tr>
  <tr><td>3M+ 库同源性证据</td><td style="line-height:1.4;">{host_matches_html}</td></tr>
</tbody>
</table>
{tree_html}
</section>"""

    @staticmethod
    def _render_genome_map_section(map_b64: str) -> str:
        inner = (
            f'<img src="data:image/png;base64,{map_b64}" alt="基因组图谱">'
            if map_b64
            else '<p style="color:#94a3b8;">暂无可视化数据</p>'
        )
        return f"""<!-- 6. Genome Map -->
<section>
<h2>6. 全景基因组注释图谱</h2>
<div class="map-box">
  {inner}
</div>
</section>"""

    def export_html(self, report_data: Dict[str, Any]) -> Path:
        """生成完整的单页 HTML 诊断报告。"""
        qc = report_data.get("qc") or {}
        asm = report_data.get("assembly") or {}
        checkv = report_data.get("checkv") or {}
        audit = report_data.get("phagescope_audit") or {}
        anno = report_data.get("annotation") or {}
        host_pct = float((report_data.get("host_cleaning") or {}).get("host_contamination_percent") or 0)

        all_genes = (anno.get("phold") or {}).get("predictions", [])
        cds_genes = [g for g in all_genes if g.get("type", "CDS") == "CDS"]
        map_b64, tree_b64 = self._load_visual_assets()

        r1_after = qc.get("read1_after") or {}
        r2_after = qc.get("read2_after") or {}
        chart_script = build_chart_script(
            quality_r1=(r1_after.get("quality_curves") or {}).get("mean", []),
            quality_r2=(r2_after.get("quality_curves") or {}).get("mean", []),
            base_content=r1_after.get("content_curves") or {},
            insert_hist=(qc.get("insert_size") or {}).get("histogram", []),
        )

        sections = [
            self._render_qc_section(qc, host_pct),
            self._render_assembly_section(asm),
            self._render_checkv_section(checkv),
            self._render_annotation_section(anno, all_genes, cds_genes),
            self._render_safety_section(audit, all_genes, tree_b64),
            self._render_genome_map_section(map_b64),
        ]
        html_content = assemble_html_document(
            task_name_escaped=self._safe_escape(self.task_dir.name),
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            sections_html=sections,
            chart_script=chart_script,
        )

        out_path = self.task_dir / f"assembly_report_{self.task_dir.name}.html"
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(html_content)
        except Exception as exc:
            logger.error("导出 HTML 报告失败: %s", exc)
        return out_path
