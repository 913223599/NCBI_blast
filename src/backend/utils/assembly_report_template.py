# -*- coding: utf-8 -*-
"""
assembly_report_template.py — 噬菌体基因组诊断报告 HTML 静态样式与 Chart.js 渲染模板
将展示层样式与图表脚本与 ReportExporter 业务统计/安全转义逻辑解耦。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

REPORT_STYLE_CSS = """
:root { --c1:#1a4da1; --c2:#2563eb; --bg:#f4f7fa; --txt:#1e293b; --bd:#e2e8f0; }
*{ box-sizing:border-box; }
body{ font-family:'Inter',-apple-system,sans-serif; background:var(--bg); color:var(--txt); padding:40px; margin:0; line-height:1.6; }
.page{ max-width:1140px; margin:0 auto; background:#fff; padding:60px; border-radius:16px; box-shadow:0 20px 60px rgba(0,0,0,.08); }

header{ display:flex; justify-content:space-between; align-items:center; border-bottom:3px solid var(--c1); padding-bottom:20px; margin-bottom:40px; }
header h1{ margin:0; font-size:30px; color:var(--c1); }
header .meta{ text-align:right; font-size:13px; color:#64748b; font-family:monospace; }

section{ margin-bottom:55px; }
h2{ font-size:20px; color:#0f172a; margin:0 0 20px; padding-left:16px; border-left:5px solid var(--c1); }
h3{ font-size:15px; color:#334155; margin:20px 0 12px; }

.grid{ display:grid; gap:16px; margin-bottom:20px; }
.g4{ grid-template-columns:repeat(4,1fr); }
.g5{ grid-template-columns:repeat(5,1fr); }
.g3{ grid-template-columns:repeat(3,1fr); }
.g2{ grid-template-columns:1.3fr 1fr; }
.card{ background:#f8fafc; border:1px solid var(--bd); padding:18px; border-radius:10px; text-align:center; }
.card .lbl{ display:block; font-size:11px; color:#64748b; text-transform:uppercase; letter-spacing:.5px; margin-bottom:4px; }
.card .val{ font-size:20px; font-weight:800; color:var(--c1); }

table{ width:100%; border-collapse:collapse; font-size:13px; }
th{ background:#f1f5f9; text-align:left; padding:10px 12px; color:#475569; border-bottom:2px solid var(--bd); }
td{ padding:10px 12px; border-bottom:1px solid var(--bd); }
.mono{ font-family:'JetBrains Mono',monospace; font-size:11px; }
.product-cell{ max-width:260px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.func-tag{ display:inline-block; padding:1px 7px; border-radius:4px; font-size:11px; background:#e0f2fe; color:#0369a1; }

.tag{ padding:3px 10px; border-radius:6px; font-size:12px; font-weight:700; }
.tag-ok{ background:#dcfce7; color:#166534; }
.tag-warn{ background:#fef3c7; color:#854d0e; }
.tag-info{ background:#e0f2fe; color:#0369a1; }

.chart-box{ border:1px solid var(--bd); border-radius:10px; padding:12px; background:#fff; }
.chart-box p{ margin:0 0 8px; font-size:12px; font-weight:700; color:#64748b; text-align:center; }
canvas{ width:100%!important; height:200px!important; }

.map-box{ background:#0f172a; padding:40px; border-radius:16px; text-align:center; }
.map-box img{ max-width:100%; border-radius:10px; box-shadow:0 0 40px rgba(0,0,0,.5); }

footer{ margin-top:60px; padding-top:16px; border-top:1px solid var(--bd); display:flex; justify-content:space-between; font-size:11px; color:#94a3b8; }
""".strip()


def build_chart_script(
    quality_r1: List[Any],
    quality_r2: List[Any],
    base_content: Dict[str, Any],
    insert_hist: List[Any],
) -> str:
    """生成嵌入报告底部的 Chart.js 三图渲染脚本。"""
    return f"""<script>
// --- Chart Data ---
const qR1 = {json.dumps(quality_r1)};
const qR2 = {json.dumps(quality_r2)};
const baseA = {json.dumps(base_content.get("A") or [])};
const baseT = {json.dumps(base_content.get("T") or [])};
const baseC = {json.dumps(base_content.get("C") or [])};
const baseG = {json.dumps(base_content.get("G") or [])};
const insertH = {json.dumps(insert_hist[:300])};

const lineOpts = {{ pointRadius:0, borderWidth:1.5, tension:0.1 }};

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

if (insertH.length > 0) {{
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
</script>"""


def assemble_html_document(
    *,
    task_name_escaped: str,
    generated_at: str,
    sections_html: List[str],
    chart_script: str,
) -> str:
    """将各业务章节拼装为自包含单页 HTML 文档。"""
    body_sections = "\n\n".join(sections_html)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>噬菌体基因组报告 — {task_name_escaped}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
{REPORT_STYLE_CSS}
</style>
</head>
<body>
<div class="page">

<header>
  <div>
    <h1>Phage blast 噬菌体基因组报告</h1>
    <p style="margin:4px 0 0;color:#64748b;font-size:14px;">高通量测序全基因组深度诊断分析 · 自动化流水线生成</p>
  </div>
  <div class="meta">任务编号: {task_name_escaped}<br>生成时间: {generated_at}</div>
</header>

{body_sections}

<footer>
  <span>NCBI Bio-Station Pro v2.5 · 分析流水线自动生成</span>
  <span>Phage blast 诊断引擎</span>
  <span>&copy; 2026 噬菌体基因组分析平台</span>
</footer>

</div><!-- .page -->

{chart_script}
</body>
</html>"""
