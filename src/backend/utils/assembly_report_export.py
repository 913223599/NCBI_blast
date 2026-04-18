"""
assembly_report_export.py - 拼接分析报告导出器
将结构化报告数据渲染为可打印的 HTML 文档

遵循单一职责原则：只负责将已解析的报告 dict 导出为文件
"""

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("api_server")


class ReportExporter:
    """将拼接报告数据导出为正式的 HTML 报告文件"""

    def __init__(self, task_id: str, report: dict):
        self.task_id = task_id
        self.report = report

    def export_html(self, output_dir: Path) -> Path:
        """导出 HTML 报告并返回文件路径"""
        output_path = output_dir / f"assembly_report_{self.task_id[:16]}.html"
        html = self._render_html()
        output_path.write_text(html, encoding="utf-8")
        logger.info(f"[ReportExporter] HTML report saved: {output_path}")
        return output_path

    def _render_html(self) -> str:
        r = self.report
        qc = r.get("qc") or {}
        asm = r.get("assembly") or {}
        anno = r.get("annotation") or {}
        pharokka = anno.get("pharokka") or {}
        phold = anno.get("phold") or {}
        genome = pharokka.get("genome") or {}
        functions = pharokka.get("functions") or []
        predictions = phold.get("predictions") or []
        confidence = phold.get("confidence") or {}
        classification = pharokka.get("classification") or {}

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # ─── 构建各区块 HTML ─────────────────────────

        # 基因组概览
        genome_len = genome.get("length", asm.get("total_length", "--"))
        gc_pct = genome.get("gc_perc", "--")
        if gc_pct != "--":
            try:
                gc_pct = f"{float(gc_pct) * 100:.1f}%"
            except Exception:
                pass
        coding_density = genome.get("cds_coding_density", "--")
        if coding_density != "--":
            coding_density = f"{coding_density}%"

        total_cds = "--"
        for f in functions:
            if f.get("name") == "CDS":
                total_cds = f.get("count", "--")
                break
        if total_cds == "--" and phold.get("total_cds"):
            total_cds = phold["total_cds"]

        # QC 区块
        qc_html = ""
        if qc and qc.get("status") == "ok":
            bef = qc.get("before", {})
            aft = qc.get("after", {})
            filt = qc.get("filtering", {})
            qc_html = f"""
            <h2>1. 测序质量控制 (Fastp)</h2>
            <table>
                <thead><tr><th>指标</th><th>过滤前</th><th>过滤后</th></tr></thead>
                <tbody>
                    <tr><td>总 Reads</td><td>{self._fmt_reads(bef.get('total_reads', 0))}</td><td>{self._fmt_reads(aft.get('total_reads', 0))}</td></tr>
                    <tr><td>总碱基</td><td>{self._fmt_bp(bef.get('total_bases', 0))}</td><td>{self._fmt_bp(aft.get('total_bases', 0))}</td></tr>
                    <tr><td>Q20</td><td>{self._fmt_pct(bef.get('q20_rate', 0))}</td><td>{self._fmt_pct(aft.get('q20_rate', 0))}</td></tr>
                    <tr><td>Q30</td><td>{self._fmt_pct(bef.get('q30_rate', 0))}</td><td>{self._fmt_pct(aft.get('q30_rate', 0))}</td></tr>
                    <tr><td>GC 含量</td><td>{self._fmt_pct(bef.get('gc_content', 0))}</td><td>{self._fmt_pct(aft.get('gc_content', 0))}</td></tr>
                </tbody>
            </table>
            <p class="note">过滤统计: 通过 {self._fmt_reads(filt.get('passed', 0))} | 低质量淘汰 {self._fmt_reads(filt.get('low_quality', 0))} | 过短淘汰 {self._fmt_reads(filt.get('too_short', 0))}</p>
            """
        else:
            qc_html = "<h2>1. 测序质量控制</h2><p class='note'>质控数据不可用（可能使用了预处理后的数据）</p>"

        # 组装区块
        asm_html = ""
        if asm and asm.get("status") == "ok":
            contigs_rows = ""
            for i, c in enumerate(asm.get("contigs", [])[:10]):
                contigs_rows += f"<tr><td>{i+1}</td><td>{c['id']}</td><td>{self._fmt_bp(c['length'])}</td></tr>"

            asm_html = f"""
            <h2>2. 基因组组装 (Unicycler)</h2>
            <div class="stat-row">
                <div class="stat-box"><span class="stat-label">Contigs</span><span class="stat-val">{asm['num_contigs']}</span></div>
                <div class="stat-box"><span class="stat-label">总长度</span><span class="stat-val">{self._fmt_bp(asm['total_length'])}</span></div>
                <div class="stat-box"><span class="stat-label">N50</span><span class="stat-val">{self._fmt_bp(asm['n50'])}</span></div>
                <div class="stat-box"><span class="stat-label">最长 Contig</span><span class="stat-val">{self._fmt_bp(asm['longest'])}</span></div>
            </div>
            <table>
                <thead><tr><th>#</th><th>Contig ID</th><th>长度</th></tr></thead>
                <tbody>{contigs_rows}</tbody>
            </table>
            """
        else:
            asm_html = "<h2>2. 基因组组装</h2><p class='note'>组装数据不可用</p>"

        # 功能分类区块
        func_rows = ""
        for f in functions:
            if f["name"] != "CDS":
                func_rows += f"<tr><td>{f['name']}</td><td>{f['count']}</td></tr>"

        func_html = ""
        if func_rows:
            func_html = f"""
            <h2>3. 功能注释 (Pharokka)</h2>
            <div class="stat-row">
                <div class="stat-box"><span class="stat-label">基因组大小</span><span class="stat-val">{self._fmt_bp(int(genome_len) if str(genome_len).isdigit() else 0)}</span></div>
                <div class="stat-box"><span class="stat-label">GC 含量</span><span class="stat-val">{gc_pct}</span></div>
                <div class="stat-box"><span class="stat-label">总 CDS</span><span class="stat-val">{total_cds}</span></div>
                <div class="stat-box"><span class="stat-label">编码密度</span><span class="stat-val">{coding_density}</span></div>
            </div>
            <table>
                <thead><tr><th>功能类别</th><th>基因数</th></tr></thead>
                <tbody>{func_rows}</tbody>
            </table>
            """

        # Phold 区块
        phold_html = ""
        if predictions:
            conf_summary = ""
            if confidence:
                total = sum(confidence.values())
                conf_summary = f"""
                <p class="note">AI 置信度分布: 
                    High {confidence.get('high', 0)} ({confidence.get('high', 0)/max(total, 1)*100:.0f}%) | 
                    Medium {confidence.get('medium', 0)} | 
                    Low {confidence.get('low', 0)} | 
                    None {confidence.get('none', 0)}
                </p>"""

            pred_rows = ""
            for p in predictions[:50]:
                conf_class = p.get("confidence", "none")
                pred_rows += f"""<tr>
                    <td><code>{p['cds_id']}</code></td>
                    <td>{p['start']}-{p['end']}</td>
                    <td>{p['strand']}</td>
                    <td>{p['function']}</td>
                    <td>{p['product']}</td>
                    <td>{p['method']}</td>
                    <td><span class="conf-badge {conf_class}">{conf_class}</span></td>
                </tr>"""

            phold_html = f"""
            <h2>4. AI 结构功能预测 (Phold)</h2>
            {conf_summary}
            <table class="compact-table">
                <thead><tr><th>CDS ID</th><th>位置</th><th>链</th><th>功能</th><th>产物</th><th>方法</th><th>置信度</th></tr></thead>
                <tbody>{pred_rows}</tbody>
            </table>
            """

        # 分类鉴定区块
        class_html = ""
        genus = classification.get("Genus", "")
        family = classification.get("Family", "")
        if genus or family:
            class_html = f"""
            <h2>5. 分类鉴定 (MASH/INPHARED)</h2>
            <div class="stat-row">
                <div class="stat-box"><span class="stat-label">属</span><span class="stat-val">{genus or '--'}</span></div>
                <div class="stat-box"><span class="stat-label">科</span><span class="stat-val">{family or '--'}</span></div>
                <div class="stat-box"><span class="stat-label">亚科</span><span class="stat-val">{classification.get('Sub-family', '--')}</span></div>
                <div class="stat-box"><span class="stat-label">目</span><span class="stat-val">{classification.get('Order', '--')}</span></div>
            </div>
            """

        # ─── 完整 HTML 模板 ──────────────────────────
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>基因组拼接分析报告 - {self.task_id}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Helvetica Neue', Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif; color: #1e293b; background: #f8fafc; line-height: 1.6; }}
        .container {{ max-width: 900px; margin: 0 auto; background: #fff; box-shadow: 0 2px 20px rgba(0,0,0,0.08); }}
        
        .report-banner {{ background: linear-gradient(135deg, #1e3a5f, #2563eb); color: #fff; padding: 40px 48px; }}
        .report-banner h1 {{ font-size: 26px; margin-bottom: 8px; }}
        .report-banner .subtitle {{ opacity: 0.85; font-size: 14px; }}
        .report-banner .meta {{ margin-top: 16px; font-size: 12px; opacity: 0.7; }}
        
        .report-content {{ padding: 32px 48px 48px; }}
        
        h2 {{ font-size: 18px; color: #1e3a5f; margin: 32px 0 16px; padding-bottom: 8px; border-bottom: 2px solid #e2e8f0; }}
        h2:first-child {{ margin-top: 0; }}
        
        table {{ width: 100%; border-collapse: collapse; margin: 12px 0 20px; font-size: 13px; }}
        th {{ background: #f1f5f9; padding: 10px 14px; text-align: left; font-weight: 600; color: #475569; border-bottom: 2px solid #e2e8f0; }}
        td {{ padding: 8px 14px; border-bottom: 1px solid #f1f5f9; }}
        tr:hover td {{ background: #fafbfc; }}
        code {{ font-family: 'Cascadia Code', monospace; font-size: 11px; background: #f1f5f9; padding: 1px 4px; border-radius: 3px; }}
        
        .compact-table td, .compact-table th {{ padding: 6px 10px; font-size: 12px; }}
        
        .stat-row {{ display: flex; gap: 16px; margin: 16px 0 20px; flex-wrap: wrap; }}
        .stat-box {{ flex: 1; min-width: 140px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px; text-align: center; }}
        .stat-label {{ display: block; font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }}
        .stat-val {{ font-size: 20px; font-weight: 800; color: #1e293b; }}
        
        .note {{ font-size: 13px; color: #64748b; margin: 12px 0; padding: 10px 14px; background: #f8fafc; border-left: 3px solid #3b82f6; border-radius: 4px; }}
        
        .conf-badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 10px; font-weight: 700; }}
        .conf-badge.high {{ background: #ecfdf5; color: #059669; }}
        .conf-badge.medium {{ background: #fffbeb; color: #d97706; }}
        .conf-badge.low {{ background: #fef2f2; color: #dc2626; }}
        .conf-badge.none {{ background: #f1f5f9; color: #94a3b8; }}
        
        .footer {{ text-align: center; padding: 24px; color: #94a3b8; font-size: 11px; border-top: 1px solid #f1f5f9; }}
        
        @media print {{
            body {{ background: #fff; }}
            .container {{ box-shadow: none; }}
            .report-banner {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
            table {{ page-break-inside: auto; }}
            tr {{ page-break-inside: avoid; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="report-banner">
            <h1>基因组拼接分析报告</h1>
            <div class="subtitle">Genome Assembly &amp; Annotation Analysis Report</div>
            <div class="meta">
                任务 ID: {self.task_id} &nbsp;|&nbsp; 生成时间: {now} &nbsp;|&nbsp; Bio-Station Pro
            </div>
        </div>
        <div class="report-content">
            {qc_html}
            {asm_html}
            {func_html}
            {phold_html}
            {class_html}
        </div>
        <div class="footer">
            Powered by Bio-Station Pro &bull; Pharokka &bull; Phold AI &bull; Unicycler
        </div>
    </div>
</body>
</html>"""

    @staticmethod
    def _fmt_bp(bp) -> str:
        try:
            bp = int(bp)
        except Exception:
            return str(bp)
        if bp >= 1e6:
            return f"{bp / 1e6:.2f} Mbp"
        if bp >= 1e3:
            return f"{bp / 1e3:.1f} Kbp"
        return f"{bp} bp"

    @staticmethod
    def _fmt_reads(n) -> str:
        try:
            n = int(n)
        except Exception:
            return str(n)
        if n >= 1e6:
            return f"{n / 1e6:.2f}M"
        if n >= 1e3:
            return f"{n / 1e3:.1f}K"
        return str(n)

    @staticmethod
    def _fmt_pct(v) -> str:
        try:
            v = float(v)
        except Exception:
            return str(v)
        return f"{v * 100:.2f}%"
