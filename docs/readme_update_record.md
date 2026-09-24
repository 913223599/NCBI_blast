# 项目概览与 README.md 更新过程留档

## 1. 任务背景与目标
- 目标：全面概览当前项目实际架构与功能演进，全面重构与更新根目录 `README.md`。
- 现状分析：
  - 原 `README.md` 严重滞后，仅描述了早期 PyQt6 简单客户端。
  - 当前项目已演化为集 Electron 跨平台桌面壳、Vue 3 + Vite + TypeScript 现代前端、FastAPI + WebSocket 异步后端、NGCS 核心基因组拼接引擎、全基因组功能注释、Sanger 测序峰图分析、泛基因组分析、蛋白质同源性比对、系统发育树构建、菌株资源库与局域网协同为一体的工业级综合生物计算工作站。
- 规范要求：
  - 严格禁用任何 Emoji 表情符号（遵循用户全局规则 0）。
  - 全文采用规范简体中文编写。
  - 模块化、分层架构清晰呈现，避免硬编码，采用相对路径。
  - 强制全流程 UTF-8 编码。
  - 过程步骤留档记录（遵循用户全局规则 5）。

## 2. 核心架构与功能梳理
1. **系统架构层**：
   - 桌面容器：Electron (`electron-shell/`)，统一管理生命周期与 Python Sidecar 守护进程。
   - 前端视窗：Vue 3.5 + TypeScript + Vite 7 + Pinia + TailwindCSS (`src/web-next/`)，集成 CGView、IGV.js、Plotly.js、Phylotree.js、Three.js 等生信可视化组件。
   - 后端服务：FastAPI 异步微服务 (`src/backend/api_server.py`) + WebSocket 实时长连接广播 (`broadcaster.py`)。
   - 生信引擎：Local BLAST+、NGCS 拼接引擎 (二代欧拉残差流/三代谱图流形)、Prokka/Pharokka/Phold/Prodigal 注释工具集、FastTree/IQ-TREE 发育树、WSL 隔离运行环境。
2. **主要功能板块**：
   - BLAST 序列比对分析中心（本地多核加速 / Elastic BLAST 云调度 / 自动化学名解析与结果缓存）。
   - NGCS 基因组拼接组装流水线（短读长/长读长自适应路由 / Fastp 质控 / 测序深度与覆盖度评估 / QUAST 指标 / 串行持久化队列）。
   - 组装后高级分析工作台（Analysis Workbench）：
     - Sanger 测序峰图分析与突变检测 (AB1 荧光信号 / SNV / InDel 移码检测 / 双单倍型解卷积)。
     - 全基因组结构与功能注释 (CDS/tRNA/rRNA 预测 / CDD 级联注释 / GFF3/GBK 生成)。
     - 核心功能蛋白同源性比对 (同源家族 / 突变图谱)。
     - 多样本泛基因组比较分析 (Pan-genome 核心与特有基因 / 噬菌体生活史与安全性)。
     - 基因组序列图谱可视化 (CGView 环状图谱 / IGV 线性浏览器)。
   - 系统发育进化树中心 (MSA / FastTree / IQ-TREE / 交互式发育树渲染)。
   - 菌毒种资源库与分类学中心 (Strain DB / NCBI 本地化 Taxonomy / ANI 计算)。
   - AI 智能翻译与生物学词典 (大模型 / 本地 SQLite 缓存 / 拉丁学名防破坏保护)。
   - 局域网协同共享模式 (LAN Share 跨终端免装访问)。
   - 环境自愈与运行保障 (一键依赖巡检 / 国内镜像源加速 / CPU 与内存安全监控)。

## 3. 执行步骤
- [x] 步骤 1：深度巡检工作区文件树与模块实现，梳理前后端架构与脚本配置。
- [x] 步骤 2：建立过程留档 `docs/readme_update_record.md`。
- [x] 步骤 3：编写并重构 `README.md`（无 Emoji、UTF-8 编码、规范模块化结构）。
- [x] 步骤 4：校验 `README.md` 编码、格式以及 Emoji 过滤（通过 Python 正则与编码检测脚本验证通过）。
- [x] 步骤 5：完成留档与向用户汇报。

## 4. 验证结论
- 已使用专用正则脚本全面检测 `README.md`，确认字符集中无任何 Emoji 或特殊符号违规。
- 全文已规范声明并采用 UTF-8 编码，完全符合系统规则与跨平台要求。
- 完整反映了当前系统的 Electron 跨平台桌面壳、Vue 3 现代化前端、FastAPI 异步微服务、NGCS 核心基因组拼接流水线、全基因组功能注释、Sanger 峰图分析、泛基因组分析与局域网协同共享等全量模块。
