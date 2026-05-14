"""
assembly_report_export.py - 噬菌体基因组诊断报告 HTML 导出引擎
从 AssemblyReportParser 的结构化数据生成单页自包含诊断报告
已完成架构级优化：HTML 实体安全转义(防 XSS)、严格的零除/空值防崩处理、更清晰的模块化。
"""

import json
import base64
import html
import logging
from pathlib import Path
from datetime import datetime
from typing import Any

logger = logging.getLogger("api_server")

class ReportExporter:
    def __init__(self, task_dir: Path):
        self.task_dir = task_dir

    def _get_image_b64(self, img_path: Path) -> str:
        """将图片文件编码为 base64 字符串"""
        if img_path.exists() and img_path.stat().st_size > 0:
            try:
                with open(img_path, "rb") as f:
                    return base64.b64encode(f.read()).decode('utf-8')
            except Exception as e:
                logger.warning(f"图片转 base64 失败 ({img_path.name}): {e}")
        return ""

    @staticmethod
    def _safe_escape(val: Any) -> str:
        """安全的 HTML 转义函数，防止 XSS 注入和格式破坏"""
        if val is None:
            return ""
        return html.escape(str(val))

    # ═══════════════════════════════════════════════════
    # 主入口
    # ═══════════════════════════════════════════════════

    def export_html(self, report_data: dict) -> Path:
        """生成完整的单页 HTML 诊断报告"""
        
        # 兜底字典获取，防止上游返回 None 导致后续 .get() 引发 AttributeError
        qc = report_data.get("qc") or {}
        asm = report_data.get("assembly") or {}
        checkv = report_data.get("checkv") or {}
        audit = report_data.get("phagescope_audit") or {}
        anno = report_data.get("annotation") or {}
        type_counts = anno.get("type_counts") or {}
        host_cleaning = report_data.get("host_cleaning") or {}
        host_pct = host_cleaning.get("host_contamination_percent") or 0

        # ─── 从 QC 数据提取绘图数组 (严格防爆) ───
        r1_after = qc.get("read1_after") or {}
        r2_after = qc.get("read2_after") or {}
        
        quality_r1 = (r1_after.get("quality_curves") or {}).get("mean", [])
        quality_r2 = (r2_after.get("quality_curves") or {}).get("mean", [])
        base_content = r1_after.get("content_curves") or {}
        insert_hist = (qc.get("insert_size") or {}).get("histogram", [])

        # ─── fastp 指标 ───
        before = qc.get("before") or {}
        after = qc.get("after") or {}
        filtering = qc.get("filtering") or {}
        
        dup_rate = (qc.get("duplication") or {}).get("rate", 0)
        insert_peak = (qc.get("insert_size") or {}).get("peak", 0)
        adapter = qc.get("adapter_cutting") or {}
        adapter_trimmed = adapter.get("adapter_trimmed_reads", 0)
        
        # 零除保护
        total_before = before.get("total_reads") or 1

        passed = filtering.get("passed_filter_reads", 0)
        low_quality = filtering.get("low_quality_reads", 0)
        too_many_n = filtering.get("too_many_N_reads", 0)
        too_short = filtering.get("too_short_reads", 0)
        too_long = filtering.get("too_long_reads", 0)
        corrected = filtering.get("corrected_reads", 0)
        passed_pct = round(passed / total_before * 100, 4)

        # ─── 基因组图谱 ───
        map_b64 = ""
        plot_dir = self.task_dir / "phageannotationstep" / "phage_plot"
        if plot_dir.exists():
            pngs = sorted(list(plot_dir.glob("*.png")),
                          key=lambda x: x.stat().st_size, reverse=True)
            if pngs:
                map_b64 = self._get_image_b64(pngs[0])
        
        # ─── 进化树图 ───
        tree_b64 = ""
        tree_path = plot_dir / "phage_phylogeny.png"
        if tree_path.exists():
            tree_b64 = self._get_image_b64(tree_path)

        # ─── 注释数据 ───
        all_genes = (anno.get("phold") or {}).get("predictions", [])
        cds_genes = [g for g in all_genes if g.get("type", "CDS") == "CDS"]

        def _gene_text(g):
            """合并 product + function 文本用于关键词搜索"""
            return ((g.get("product") or "") + " " + (g.get("function") or "")).lower()

        integrase_found = any("integrase" in _gene_text(g) for g in all_genes)
        repressor_found = any("repressor" in _gene_text(g) for g in all_genes)
        excisionase_found = any("excisionase" in _gene_text(g) for g in all_genes)

        # ─── 安全审计数据 (双层架构) ───
        safety = audit.get("safety_status", "Pending Review")

        # AMR
        amr_direct = audit.get("amr_genes_direct", [])
        amr_list = audit.get("amr_genes", [])
        if isinstance(amr_list, list) and amr_list:
            amr_display = f"{len(amr_list)} 个检出"
            amr_evidence = "blastp 序列比对" if amr_direct else "参考推断 (PhageScope)"
        else:
            amr_display = "未检出"
            amr_evidence = ""

        # VF
        vf_direct = audit.get("virulent_factors_direct", [])
        vf_list = audit.get("virulent_factors", [])
        if isinstance(vf_list, list) and vf_list:
            vf_display = f"{len(vf_list)} 个检出"
            vf_evidence = "blastp 序列比对" if vf_direct else "参考推断 (PhageScope)"
        else:
            vf_display = "未检出"
            vf_evidence = ""

        # Anti-CRISPR (联动优化：优先使用 dbAPIS 的专项高灵敏度结果)
        acr_raw = audit.get("anti_crispr", "未检出")
        defense_hits = audit.get("defense_systems") or {}
        
        # 确保 defense_hits 是字典以防崩溃
        apis_acr = []
        if isinstance(defense_hits, dict):
            apis_acr = [v["system"] for v in defense_hits.values() if "Acr" in v.get("system", "") or "Anti-CRISPR" in v.get("system", "")]
        
        if apis_acr:
            acr_display = f"{len(apis_acr)} 个检出 (dbAPIS)"
            acr_evidence_zh = "HMM 结构域扫描 (APIS)"
        else:
            acr_display = "未检出" if acr_raw in ("Not Detected", "None", None, "") else str(acr_raw)
            acr_evidence = audit.get("anti_crispr_evidence", "")
            acr_evidence_zh = {"direct": "Diamond blastp 序列比对", "reference": "参考推断 (PhageScope)"}.get(acr_evidence, "—")

        # 宿主溯源 & 分类
        host_origin = audit.get("host_origin", "--")
        taxonomy = audit.get("taxonomy_info") or {}
        tax_name = taxonomy.get("top_hit_name", "--")
        tax_class = taxonomy.get("Classification", "--")
        tax_genus = taxonomy.get("Genus", "--")
        tax_family = taxonomy.get("Family", "--")
        tax_host = taxonomy.get("Host", host_origin)

        # ─── 深度宿主指认 ───
        host_enhanced = audit.get("host_prediction_enhanced") or {}
        host_hits = host_enhanced.get("top_hits", [])

        # ─── HTML 片段构建 ───
        defense_html = ""
        if isinstance(defense_hits, dict) and defense_hits:
            def_rows = []
            for i, (locus, hit) in enumerate(defense_hits.items(), 1):
                sys_name = hit.get("system", "Unknown")
                eval_val = hit.get("evalue", 0.0)
                clr = "#b91c1c" if "Acr" in sys_name or "Anti-CRISPR" in sys_name else "#1e293b"
                
                def_rows.append(
                    f"<tr>"
                    f"<td style='text-align:center;'>{i}</td>"
                    f"<td class='mono'>{self._safe_escape(locus)}</td>"
                    f"<td style='font-weight:bold; color:{clr};'>{self._safe_escape(sys_name)}</td>"
                    f"<td class='mono' style='font-size:0.85em;'>{eval_val:.2e}</td>"
                    f"</tr>"
                )
            defense_html = (
                "<div style='margin-top:20px;'>"
                "<h4>抗噬菌体防御系统 (dbAPIS) 检测详情</h4>"
                "<table class='data-table' style='width:100%;font-size:0.9em;'>"
                "<thead><tr><th>#</th><th>Locus Tag</th><th>System / Protein</th><th>E-value</th></tr></thead>"
                "<tbody>" + "\n".join(def_rows) + "</tbody>"
                "</table></div>"
            )
        else:
            defense_html = "<p style='color:#94a3b8; font-size:0.9em;'>未检出显著的抗噬菌体防御系统基因 (Hit < 1e-10)</p>"
            
        host_matches_html = ""
        if host_hits:
            match_rows = []
            for i, hit in enumerate(host_hits, 1):
                sim_val = hit.get("similarity", "0%")
                desc = hit.get("description", "Unknown Organism")
                acc = hit.get("accession", "N/A")
                dist = hit.get("distance", "--")
                conf = hit.get("confidence", "Low")
                pval = hit.get("p_value", "--")
                src = hit.get("db_source", "--")
                
                if conf == "High":
                    conf_badge = "<span class='tag tag-ok'>High</span>"
                elif conf == "Medium":
                    conf_badge = "<span class='tag tag-warn'>Medium</span>"
                else:
                    conf_badge = "<span style='color:#94a3b8;'>Low</span>"
                
                src_badge = f"<span style='background:#e0f2fe;color:#0369a1;padding:1px 6px;border-radius:4px;font-size:0.8em;'>{self._safe_escape(src)}</span>"
                match_rows.append(
                    f"<tr>"
                    f"<td style='text-align:center;font-weight:bold;'>{i}</td>"
                    f"<td>{conf_badge}</td>"
                    f"<td>{self._safe_escape(desc)}</td>"
                    f"<td class='mono' style='font-size:0.85em;'>{self._safe_escape(acc)}</td>"
                    f"<td style='font-size:0.85em;'>{self._safe_escape(dist)}</td>"
                    f"<td style='font-size:0.85em;'>{self._safe_escape(pval)}</td>"
                    f"<td>{src_badge}</td>"
                    f"</tr>"
                )
            host_matches_html = (
                "<table class='data-table' style='width:100%;font-size:0.9em;'>"
                "<thead><tr>"
                "<th>#</th><th>Confidence</th><th>Host Organism</th>"
                "<th>Accession</th><th>Distance</th><th>P-value</th>"
                "<th>Source</th>"
                "</tr></thead><tbody>"
                + "\n".join(match_rows)
                + "</tbody></table>"
            )
        else:
            host_matches_html = "<span style='color:#94a3b8;'>未发现显著高同源原噬菌体 (ANI < 80%)</span>"

        # ─── 格式化辅助函数 ───
        def fmt_reads(n):
            if not n: return "0"
            try:
                n = int(n)
                if n >= 1_000_000: return f"{n / 1_000_000:.2f}M"
                if n >= 1_000: return f"{n / 1_000:.1f}K"
                return str(n)
            except: return "0"

        def fmt_bp(n):
            if not n: return "0 bp"
            try:
                n = int(n)
                if n >= 1_000_000: return f"{n / 1_000_000:.2f} Mbp"
                if n >= 1_000: return f"{n / 1_000:.1f} Kbp"
                return f"{n} bp"
            except: return "0 bp"

        def fmt_pct(v):
            if v is None or v == 0: return "0.00%"
            try:
                return f"{float(v) * 100:.2f}%"
            except (ValueError, TypeError):
                return str(v)

        # ─── 功能分类统计行 (用于 HTML 表格) ───
        func_counts = (anno.get("pharokka") or {}).get("functions", [])
        func_rows_html = ""
        for fc in sorted(func_counts, key=lambda x: -x.get("count", 0)):
            name = fc.get("name", "")
            if name == "CDS": continue
            count = fc.get("count", 0)
            pct_val = round(count / len(cds_genes) * 100, 1) if cds_genes else 0
            func_rows_html += f"<tr><td>{self._safe_escape(name)}</td><td>{count}</td><td>{pct_val}%</td></tr>\n"

        # ─── CDS 注释详表 (前 50 行) ───
        cds_table_rows = ""
        for g in cds_genes[:50]:
            cds_table_rows += (
                f"<tr>"
                f"<td class='mono'>{self._safe_escape(g.get('cds_id',''))}</td>"
                f"<td>{self._safe_escape(g.get('start',''))}-{self._safe_escape(g.get('end',''))}</td>"
                f"<td>{self._safe_escape(g.get('strand',''))}</td>"
                f"<td><span class='func-tag'>{self._safe_escape(g.get('function',''))}</span></td>"
                f"<td class='product-cell' title='{self._safe_escape(g.get('product',''))}'>{self._safe_escape(g.get('product',''))}</td>"
                f"</tr>\n"
            )
        if len(cds_genes) > 50:
            cds_table_rows += f"<tr><td colspan='5' style='text-align:center;color:#94a3b8;'>... 共 {len(cds_genes)} 条 CDS, 仅展示前 50 条</td></tr>"

        # 拓扑学安全显示
        is_circular = asm.get('is_circular', False)
        # 如果能在 asm 表里面拿到 'DTR' 的标记，或者之前代码逻辑留的坑：
        # 这里统一采用更加健壮的显示方式
        if is_circular:
            topo_tag = '<span class="tag tag-ok">Circular (环形基因组)</span>'
        else:
            topo_tag = '<span class="tag tag-info">Linear (线性基因组)</span>'

        html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>噬菌体基因组报告 — {self._safe_escape(self.task_dir.name)}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
:root {{ --c1:#1a4da1; --c2:#2563eb; --bg:#f4f7fa; --txt:#1e293b; --bd:#e2e8f0; }}
*{{ box-sizing:border-box; }}
body{{ font-family:'Inter',-apple-system,sans-serif; background:var(--bg); color:var(--txt); padding:40px; margin:0; line-height:1.6; }}
.page{{ max-width:1140px; margin:0 auto; background:#fff; padding:60px; border-radius:16px; box-shadow:0 20px 60px rgba(0,0,0,.08); }}

header{{ display:flex; justify-content:space-between; align-items:center; border-bottom:3px solid var(--c1); padding-bottom:20px; margin-bottom:40px; }}
header h1{{ margin:0; font-size:30px; color:var(--c1); }}
header .meta{{ text-align:right; font-size:13px; color:#64748b; font-family:monospace; }}

section{{ margin-bottom:55px; }}
h2{{ font-size:20px; color:#0f172a; margin:0 0 20px; padding-left:16px; border-left:5px solid var(--c1); }}
h3{{ font-size:15px; color:#334155; margin:20px 0 12px; }}

.grid{{ display:grid; gap:16px; margin-bottom:20px; }}
.g4{{ grid-template-columns:repeat(4,1fr); }}
.g5{{ grid-template-columns:repeat(5,1fr); }}
.g3{{ grid-template-columns:repeat(3,1fr); }}
.g2{{ grid-template-columns:1.3fr 1fr; }}
.card{{ background:#f8fafc; border:1px solid var(--bd); padding:18px; border-radius:10px; text-align:center; }}
.card .lbl{{ display:block; font-size:11px; color:#64748b; text-transform:uppercase; letter-spacing:.5px; margin-bottom:4px; }}
.card .val{{ font-size:20px; font-weight:800; color:var(--c1); }}

table{{ width:100%; border-collapse:collapse; font-size:13px; }}
th{{ background:#f1f5f9; text-align:left; padding:10px 12px; color:#475569; border-bottom:2px solid var(--bd); }}
td{{ padding:10px 12px; border-bottom:1px solid var(--bd); }}
.mono{{ font-family:'JetBrains Mono',monospace; font-size:11px; }}
.product-cell{{ max-width:260px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.func-tag{{ display:inline-block; padding:1px 7px; border-radius:4px; font-size:11px; background:#e0f2fe; color:#0369a1; }}

.tag{{ padding:3px 10px; border-radius:6px; font-size:12px; font-weight:700; }}
.tag-ok{{ background:#dcfce7; color:#166534; }}
.tag-warn{{ background:#fef3c7; color:#854d0e; }}
.tag-info{{ background:#e0f2fe; color:#0369a1; }}

.chart-box{{ border:1px solid var(--bd); border-radius:10px; padding:12px; background:#fff; }}
.chart-box p{{ margin:0 0 8px; font-size:12px; font-weight:700; color:#64748b; text-align:center; }}
canvas{{ width:100%!important; height:200px!important; }}

.map-box{{ background:#0f172a; padding:40px; border-radius:16px; text-align:center; }}
.map-box img{{ max-width:100%; border-radius:10px; box-shadow:0 0 40px rgba(0,0,0,.5); }}

footer{{ margin-top:60px; padding-top:16px; border-top:1px solid var(--bd); display:flex; justify-content:space-between; font-size:11px; color:#94a3b8; }}
</style>
</head>
<body>
<div class="page">

<header>
  <div>
    <h1>Phage blast 噬菌体基因组报告</h1>
    <p style="margin:4px 0 0;color:#64748b;font-size:14px;">高通量测序全基因组深度诊断分析 · 自动化流水线生成</p>
  </div>
  <div class="meta">任务编号: {self._safe_escape(self.task_dir.name)}<br>生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
</header>

<!-- ═══ 1. QC ═══ -->
<section>
<h2>1. 测序质控与过滤审计</h2>

  <div class="grid g5">
    <div class="card"><span class="lbl">原始序列数</span><span class="val">{fmt_reads(before.get('total_reads',0))}</span></div>
    <div class="card"><span class="lbl">清洁序列数</span><span class="val">{fmt_reads(after.get('total_reads',0))}</span></div>
    <div class="card" style="background:#fff1f2;border-color:#fecaca;"><span class="lbl" style="color:#e11d48;">宿主占比</span><span class="val" style="color:#be123c;">{host_pct:.2f}%</span></div>
    <div class="card"><span class="lbl">重复率</span><span class="val">{fmt_pct(dup_rate)}</span></div>
    <div class="card"><span class="lbl">插入片段峰值</span><span class="val">{insert_peak} bp</span></div>
  </div>

<h3>过滤前后对比</h3>
<table>
  <thead><tr><th>指标</th><th>过滤前</th><th>过滤后</th></tr></thead>
  <tbody>
    <tr><td>总序列数 (Reads)</td><td>{fmt_reads(before.get('total_reads',0))}</td><td>{fmt_reads(after.get('total_reads',0))}</td></tr>
    <tr><td>总碱基数 (Bases)</td><td>{fmt_bp(before.get('total_bases',0))}</td><td>{fmt_bp(after.get('total_bases',0))}</td></tr>
    <tr><td>Q20 比率</td><td>{fmt_pct(before.get('q20_rate',0))}</td><td>{fmt_pct(after.get('q20_rate',0))}</td></tr>
    <tr><td>Q30 比率</td><td>{fmt_pct(before.get('q30_rate',0))}</td><td>{fmt_pct(after.get('q30_rate',0))}</td></tr>
    <tr><td>GC 含量</td><td>{fmt_pct(before.get('gc_content',0))}</td><td>{fmt_pct(after.get('gc_content',0))}</td></tr>
    <tr><td>平均读长 R1 / R2</td>
        <td>{before.get('read1_mean_length',0)} / {before.get('read2_mean_length',0)} bp</td>
        <td>{after.get('read1_mean_length',0)} / {after.get('read2_mean_length',0)} bp</td></tr>
  </tbody>
</table>

<h3>过滤统计</h3>
<table>
<thead><tr><th>过滤类别</th><th>序列数</th><th>占比</th></tr></thead>
<tbody>
  <tr><td>✅ 通过质控</td><td><strong>{fmt_reads(passed)}</strong></td><td><span class="tag tag-ok">{passed_pct}%</span></td></tr>
  <tr><td>低质量剔除</td><td>{low_quality:,}</td><td>{fmt_pct(low_quality / total_before)}</td></tr>
  <tr><td>N 碱基过多</td><td>{too_many_n:,}</td><td>{fmt_pct(too_many_n / total_before)}</td></tr>
  <tr><td>过短剔除</td><td>{too_short:,}</td><td>{fmt_pct(too_short / total_before)}</td></tr>
  <tr><td>过长剔除</td><td>{too_long:,}</td><td>{fmt_pct(too_long / total_before)}</td></tr>
  <tr><td>接头修剪</td><td>{adapter_trimmed:,}</td><td>{fmt_pct(adapter_trimmed / total_before)}</td></tr>
  <tr><td>碱基校正 (重叠区)</td><td>{corrected:,}</td><td>--</td></tr>
</tbody>
</table>

<h3>质量曲线与碱基组成</h3>
<div class="grid g3">
  <div class="chart-box"><p>碱基质量分布 (R1 + R2)</p><canvas id="cQuality"></canvas></div>
  <div class="chart-box"><p>碱基组成分布 (过滤后 R1)</p><canvas id="cBase"></canvas></div>
  <div class="chart-box"><p>插入片段长度分布</p><canvas id="cInsert"></canvas></div>
</div>
</section>

<!-- ═══ 2. Assembly ═══ -->
<section>
<h2>2. 基因组组装与拓扑分析</h2>
<div class="grid g4">
  <div class="card"><span class="lbl">基因组总长</span><span class="val">{fmt_bp(asm.get('total_length',0))}</span></div>
  <div class="card"><span class="lbl">GC 含量</span><span class="val">{asm.get('gc_content',0)}%</span></div>
  <div class="card"><span class="lbl">N50</span><span class="val">{fmt_bp(asm.get('n50',0))}</span></div>
  <div class="card"><span class="lbl">平均测序深度</span><span class="val">{asm.get('avg_depth',0)}x</span></div>
</div>
<table>
<thead><tr><th>指标</th><th>数值</th><th>备注</th></tr></thead>
<tbody>
  <tr><td>Contig 数量</td><td>{asm.get('num_contigs',0)}</td><td>L50 = {asm.get('l50',0)}</td></tr>
  <tr><td>最长 / 最短 Contig</td><td>{fmt_bp(asm.get('longest',0))} / {fmt_bp(asm.get('shortest',0))}</td><td>长度范围</td></tr>
  <tr><td>拓扑结构</td><td>{topo_tag}</td><td>基于物理序列拼接结果验证</td></tr>
</tbody>
</table>
</section>

<!-- ═══ 3. CheckV ═══ -->
<section>
<h2>3. 基因组质量评估 (CheckV)</h2>
<div class="grid g4">
  <div class="card"><span class="lbl">质量等级</span><span class="val">{self._safe_escape(checkv.get('quality','--'))}</span></div>
  <div class="card"><span class="lbl">完整度</span><span class="val">{self._safe_escape(checkv.get('completeness','--'))}%</span></div>
  <div class="card"><span class="lbl">污染度</span><span class="val">{self._safe_escape(checkv.get('contamination','0'))}%</span></div>
  <div class="card"><span class="lbl">基因总数</span><span class="val">{checkv.get('gene_count',0)}</span></div>
</div>
<table>
<thead><tr><th>评估项</th><th>结果</th></tr></thead>
<tbody>
  <tr><td>MIUViG 质量标准</td><td>{self._safe_escape(checkv.get('miuvig_quality','--'))}</td></tr>
  <tr><td>完整度评估方法</td><td>{self._safe_escape(checkv.get('completeness_method','--'))}</td></tr>
  <tr><td>病毒基因数 / 宿主基因数</td><td>{checkv.get('viral_genes',0)} / {checkv.get('host_genes',0)}</td></tr>
  <tr><td>前噬菌体 (Provirus)</td><td>{self._safe_escape(checkv.get('provirus','No'))}</td></tr>
  <tr><td>kmer 频率</td><td>{self._safe_escape(checkv.get('kmer_freq','--'))}</td></tr>
</tbody>
</table>
</section>

<!-- ═══ 4. Annotation ═══ -->
<section>
<h2>4. 基因组功能注释</h2>
<div class="grid g4" style="margin-bottom:20px;">
  <div class="card"><span class="lbl">注释特征总数</span><span class="val">{len(all_genes)}</span></div>
  <div class="card"><span class="lbl">编码序列 (CDS)</span><span class="val">{type_counts.get('CDS',0)}</span></div>
  <div class="card"><span class="lbl">转运 RNA (tRNA)</span><span class="val">{type_counts.get('tRNA',0)}</span></div>
  <div class="card"><span class="lbl">假基因</span><span class="val">{type_counts.get('pseudogene',0)}</span></div>
</div>

<h3>功能分类统计</h3>
<table>
<thead><tr><th>功能类别</th><th>数量</th><th>占比</th></tr></thead>
<tbody>
{func_rows_html}
</tbody>
</table>

<h3>CDS 注释详表</h3>
<div style="max-height:400px;overflow-y:auto;border:1px solid var(--bd);border-radius:8px;">
<table>
<thead><tr><th>基因 ID</th><th>位置</th><th>链方向</th><th>功能分类</th><th>产物名称</th></tr></thead>
<tbody>
{cds_table_rows}
</tbody>
</table>
</div>
</section>

<!-- ═══ 5. Safety ═══ -->
<section>
<h2>5. 安全性与生活史审计</h2>

<h3>溶源性证据搜索</h3>
<table>
<thead><tr><th>标志物</th><th>检测结果</th><th>生物学意义</th></tr></thead>
<tbody>
  <tr><td>整合酶 (Integrase)</td><td>{'<span class="tag tag-warn">检出</span>' if integrase_found else '<span class="tag tag-ok">未检出</span>'}</td><td>溶源性一级证据 — 催化噬菌体DNA整合至宿主基因组</td></tr>
  <tr><td>阻遏蛋白 (Repressor)</td><td>{'<span class="tag tag-warn">检出</span>' if repressor_found else '<span class="tag tag-ok">未检出</span>'}</td><td>溶源性二级证据 — 维持溶源状态的转录调控因子</td></tr>
  <tr><td>切除酶 (Excisionase)</td><td>{'<span class="tag tag-warn">检出</span>' if excisionase_found else '<span class="tag tag-ok">未检出</span>'}</td><td>溶源性三级证据 — 催化前噬菌体从宿主基因组切除</td></tr>
  <tr><td>附着位点 (attP)</td><td><span class="tag tag-info">待实验验证</span></td><td>需结合湿实验确认噬菌体末端附着序列</td></tr>
</tbody>
</table>

<h3>安全性评估</h3>
<p style="font-size:12px;color:#64748b;margin:-8px 0 12px;">检测方法: Tier 1 blastp 序列比对 (CDS → PhageScope 蛋白库 105万条, E≤1e-10) + 交叉查询 AMR/VF/ACR 元数据表</p>
<table>
<thead><tr><th>评估项目</th><th>结果</th><th>证据来源</th></tr></thead>
<tbody>
  <tr><td>生活方式 (Lifestyle)</td><td><strong>{self._safe_escape(audit.get('lifestyle','Unknown'))}</strong></td><td>参考推断 (PhageScope)</td></tr>
  <tr><td>毒力因子 (VFDB)</td><td><span class="tag {'tag-warn' if vf_list else 'tag-ok'}">{self._safe_escape(vf_display)}</span></td><td>{self._safe_escape(vf_evidence) if vf_evidence else '—'}</td></tr>
  <tr><td>耐药基因 (CARD)</td><td><span class="tag {'tag-warn' if amr_list else 'tag-ok'}">{self._safe_escape(amr_display)}</span></td><td>{self._safe_escape(amr_evidence) if amr_evidence else '—'}</td></tr>
  <tr><td>抗 CRISPR 蛋白</td><td>{self._safe_escape(acr_display)}</td><td>{self._safe_escape(acr_evidence_zh) if acr_evidence_zh else '—'}</td></tr>
  <tr><td>综合安全评级</td><td><span class="tag {'tag-ok' if 'Secure' in str(safety) or 'Clear' in str(safety) else 'tag-warn'}">{self._safe_escape(safety)}</span></td><td>基于以上指标综合裁定</td></tr>
</tbody>
</table>

{defense_html}

<h3>宿主范围与分类溯源</h3>
<table>
<thead><tr><th>分类项</th><th>结果</th></tr></thead>
<tbody>
  <tr><td>宿主来源 (Host Origin)</td><td><strong>{self._safe_escape(tax_host)}</strong></td></tr>
  <tr><td>最近参考基因组</td><td>{self._safe_escape(tax_name)}</td></tr>
  <tr><td>分类谱系</td><td class="mono">{self._safe_escape(tax_class)}</td></tr>
  <tr><td>科 (Family)</td><td>{self._safe_escape(tax_family)}</td></tr>
  <tr><td>属 (Genus)</td><td>{self._safe_escape(tax_genus)}</td></tr>
  <tr><td>3M+ 库同源性证据</td><td style="line-height:1.4;">{host_matches_html}</td></tr>
</tbody>
</table>

{f'''
<h3 style="margin-top:24px;">进化演化分析 (Top 30 Genomic Relationships)</h3>
<div style="background:#fff; border:1px solid var(--bd); border-radius:12px; padding:20px; text-align:center;">
    <img src="data:image/png;base64,{tree_b64}" alt="Phylogenetic Tree" style="max-width:100%; height:auto; border-radius:4px;">
    <p style="font-size:11px; color:#64748b; margin-top:12px;">注：红色加粗节点 (★) 为当前检测样本。分支长度代表 Mash 基因组距离 (1-ANI)。</p>
</div>
''' if tree_b64 else ""}
</section>

<!-- ═══ 6. Genome Map ═══ -->
<section>
<h2>6. 全景基因组注释图谱</h2>
<div class="map-box">
  {f'<img src="data:image/png;base64,{map_b64}" alt="基因组图谱">' if map_b64 else '<p style="color:#94a3b8;">暂无可视化数据</p>'}
</div>
</section>

<footer>
  <span>NCBI Bio-Station Pro v2.5 · 分析流水线自动生成</span>
  <span>Phage blast 诊断引擎</span>
  <span>&copy; 2026 噬菌体基因组分析平台</span>
</footer>

</div><!-- .page -->

<script>
// ─── Chart Data ───
const qR1 = {json.dumps(quality_r1)};
const qR2 = {json.dumps(quality_r2)};
const baseA = {json.dumps((base_content.get('A') or []))};
const baseT = {json.dumps((base_content.get('T') or []))};
const baseC = {json.dumps((base_content.get('C') or []))};
const baseG = {json.dumps((base_content.get('G') or []))};
const insertH = {json.dumps(insert_hist[:300])};

const lineOpts = {{ pointRadius:0, borderWidth:1.5, tension:0.1 }};

// 1) Quality
if (qR1.length > 0) {{
  new Chart(document.getElementById('cQuality'), {{
    type:'line',
    data: {{
      labels: qR1.map((_,i) => i+1),
      datasets: [
        {{ label:'R1', data:qR1, borderColor:'#2563eb', ...lineOpts }},
        {{ label:'R2', data:qR2, borderColor:'#f59e0b', ...lineOpts }}
      ]
    }},
    options: {{
      responsive:true, maintainAspectRatio:false,
      plugins: {{ legend:{{ position:'bottom', labels:{{ boxWidth:12 }} }} }},
      scales: {{ y:{{ min:20, max:42, title:{{ display:true, text:'Phred 质量值 (Q)' }} }}, x:{{ title:{{ display:true, text:'碱基位置 (bp)' }} }} }}
    }}
  }});
}}

// 2) Base Content
if (baseA.length > 0) {{
  new Chart(document.getElementById('cBase'), {{
    type:'line',
    data: {{
      labels: baseA.map((_,i) => i+1),
      datasets: [
        {{ label:'A', data:baseA, borderColor:'#eab308', ...lineOpts }},
        {{ label:'T', data:baseT, borderColor:'#ef4444', ...lineOpts }},
        {{ label:'C', data:baseC, borderColor:'#3b82f6', ...lineOpts }},
        {{ label:'G', data:baseG, borderColor:'#22c55e', ...lineOpts }}
      ]
    }},
    options: {{
      responsive:true, maintainAspectRatio:false,
      plugins: {{ legend:{{ position:'bottom', labels:{{ boxWidth:12 }} }} }},
      scales: {{ y:{{ min:0.15, max:0.35, title:{{ display:true, text:'碱基比例' }} }}, x:{{ title:{{ display:true, text:'碱基位置 (bp)' }} }} }}
    }}
  }});
}}

// 3) Insert Size
if (insertH.length > 0) {{
  // 只画有意义的范围 (跳过首部大量零值)
  let s=0; for(let i=0;i<insertH.length;i++) if(insertH[i]>0){{ s=Math.max(0,i-5); break; }}
  const sliced = insertH.slice(s);
  new Chart(document.getElementById('cInsert'), {{
    type:'bar',
    data: {{
      labels: sliced.map((_,i) => s+i),
      datasets: [{{ label:'读对数', data:sliced, backgroundColor:'rgba(37,99,235,.6)', borderWidth:0 }}]
    }},
    options: {{
      responsive:true, maintainAspectRatio:false,
      plugins: {{ legend:{{ display:false }} }},
      scales: {{ y:{{ title:{{ display:true, text:'计数' }} }}, x:{{ title:{{ display:true, text:'插入片段长度 (bp)' }} }} }}
    }}
  }});
}}
</script>
</body>
</html>"""

        out_path = self.task_dir / f"assembly_report_{self.task_dir.name}.html"
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(html_content)
        except Exception as e:
            logger.error(f"导出 HTML 报告失败: {e}")
            
        return out_path