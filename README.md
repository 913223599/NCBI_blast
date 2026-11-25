# NCBI Bio-Station | 生物序列分析与基因组全流程工作站

NCBI Bio-Station 是一套面向微生物学、噬菌体研究与基因组学分析的跨平台本地生物计算工作站。系统采用 **Electron 35 桌面容器 + Vue 3.5 / TypeScript / Vite 7 现代前端 + FastAPI / Uvicorn 异步后端 + 多引擎本地/WSL2 生信与深度学习推理栈** 分层架构，覆盖序列比对、基因组拼接、全基因组注释、前噬菌体边界发现、噬菌体结构与尾型预测、泛基因组分析、科研出版级绘图、菌毒种 3D 冻存管理及实验室自动化流水线。

---

## 1. 核心业务功能矩阵

### 1.1 BLAST 序列比对与 16S 扩增子多样性
- **本地 BLAST+ 多核并行**：原生驱动 `blastn`、`blastp`、`blastx`、`tblastn`、`tblastx`，支持自动留核调度与结果解析缓存。
- **16S 扩增子混样多样性分析**：内置 rrnDB 拷贝数校正、低频噪声过滤、多样本物种丰度汇总与 Excel 报表导出。
- **数据库全生命周期管理**：支持自建 FASTA 比对库 (`makeblastdb`) 与本地核心库维护。

### 1.2 NGCS 基因组拼接组装流水线 (`src/assembly`)
- **多平台自适应路由**：自动识别 Illumina/MGI 短读长双端测序数据与 Nanopore/PacBio 长读长数据。
- **上游质控与深度评估**：集成 Fastp 质控清洗、NGCS 组装、QUAST 指标评估（N50/L50/环状拓扑）与 Contigs 加权测序深度解析。
- **持久化串行队列与 WSL2 互联**：通过持久化串行队列避免并发争抢资源，自动维护 WSL2 无空格软链接。

### 1.3 组装后深度分析工作台 (`src/analysis` & `src/phage_discovery`)
- **Sanger 测序峰图分析与突变检测**：解析 AB1 荧光峰图、识别 SNV/InDel 移码重叠峰并支持双单倍型解卷积。
- **全基因组结构与功能注释**：集成 Prokka、Pharokka、Phold、Prodigal 与 CDD/RPS-BLAST 级联补齐，输出标准 GFF3/GBK。
- **前噬菌体智能发现 (Stage 1.2 / Unified V4)**：结合 DNA 序列底座、200bp SubBinRefiner 边界精修与可选蛋白门控验证，实现宿主基因组前噬菌体精准分割与分片断点推理。
- **噬菌体结构与尾部形态预测 (`phage_structure`)**：融合尾鞘 TSP、MTP、TAP、TTPA/B、Virfam 连接器模块与 TMP 卷尺蛋白定量解析，区分肌尾/长尾/短尾/非有尾噬菌体。
- **多样本泛基因组比较分析 (`pan_genomics`)**：同源基因聚类、核心/附属/特异基因组统计、鸡尾酒去冗余与溶源安全性评估。
- **基因组双模式可视化**：环形图谱（CGView）与线性轨道浏览器（IGV.js）。

### 1.4 科研绘图工坊 (`src/phylo` & `src/figure_studio`)
- **系统发育树构建与多环出版出图**：集成 MAFFT、Muscle、FastTree、IQ-TREE、VIRIDIC ANI 与自研 Canvas/SVG 混合渲染引擎 (`PhyloWorkbench`)，支持矢量 PDF/SVG 与高清 PNG 导出。
- **六大噬菌体顶刊核心图型**：VIRIDIC 双向热图、单株全基因组功能圈图、比较基因组共线性丝带图、核苷酸多样性 (Pi) 滑窗热点图、蛋白共享网络与华夫格图、双树联动宿主谱矩阵。

### 1.5 菌毒种资源库与自动化流水线 (`src/backend/strain_db.py` & `src/mail_download`)
- **本地菌毒种资产与 3D 冻存拓扑**：基于 SQLite 与 Three.js 实现冰箱-层-柜-抽屉-盒位物理空间映射、编码检索与批量导入导出。
- **自动化邮件注释与生工 16S 流水线**：自动拉取邮件 FASTA 附件完成注释与 Word 报告回传，支持生工 16S 订单自动抓取、解压、比对与 CSV 导出。
- **局域网协同共享 (`lan_share.py`)**：支持同局域网设备免安装访问结果；未启用共享时由 `LanAccessGuardMiddleware` 自动拦截一切非本机回环 IP 请求。

---

## 2. 系统技术选型与兼容性基线

| 架构维度 | 采用技术 / 库 | 说明 |
| :--- | :--- | :--- |
| **桌面壳层** | Electron 35 (`sandbox: true`, `contextIsolation: true`) | 窗口管理、异步安全 IPC、CSP 策略与 Python Sidecar 守护 |
| **前端框架** | Vue 3.5 + TypeScript 5.9 (`ES2024`) + Vite 7 + Pinia 3 | 路由/重模块 `defineAsyncComponent` 懒加载与按库分包 |
| **设计系统** | 原生 CSS Design Tokens (`global.css`) | 浅色高对比度科研界面、标准滚动条、原生 `<dialog>` 与无障碍导航 |
| **生信可视化** | CGView, IGV.js, Plotly.js, D3.js, Three.js, 自研 Phylo Canvas/SVG | 环状/线性基因组、深度曲线、进化树出版预览、3D 冰箱 |
| **后端服务** | FastAPI + Uvicorn + WebSockets + SQLite 3 | 异步 REST、`/api/health` 探活、LAN 访问守卫与实时事件广播 |
| **生信与 AI 引擎** | Biopython, BLAST+, NGCS, Prokka/Pharokka/Phold, MAFFT/IQ-TREE, PyTorch | 混合 CPU 多核留核调度与 GPU 显存红线守卫 (`src/utils/resource_guard.py`) |

> **浏览器与运行时兼容基线 (Browser Support Policy)**：桌面主运行环境为 **Electron 35 (Chromium 134+)**；局域网协同模式兼容现代 Firefox / Safari，新 Web API（如原生 Sanitizer `setHTML()`、`<dialog closedby>`、标准滚动条与 IME 组合态检测）均按需保留轻量级回退实现。

---

## 3. 项目目录结构

```text
NCBI blast/
├── database/                    # 本地参考数据库 (16S, taxonomy 等)
├── docs/                        # 工程设计、排错记录与架构索引 (见 docs/INDEX.md)
├── electron-shell/              # Electron 35 桌面主进程 (main.js / preload.js)
├── resources/                   # 静态资源与内置帮助手册
│   └── help/                    # 覆盖全站核心模块的 Markdown 帮助文档
├── scripts/                     # 运维、环境配置、基准测试与批处理脚本
├── src/                         # 核心源代码
│   ├── analysis/                # 深度分析引擎
│   │   ├── annotation/          # Prokka / Pharokka / Phold / CDD 注释流水线
│   │   ├── comparison/          # 序列共线性与比对处理
│   │   ├── pan_genomics/        # 泛基因组聚类与鸡尾酒去冗余
│   │   ├── phage_finder/        # 前噬菌体工作台调度与模型发现
│   │   ├── phage_structure/     # 噬菌体结构与尾部形态预测
│   │   └── protein_search/      # 蛋白 FASTA 同源检索
│   ├── assembly/                # NGCS 基因组拼接组装与 WSL2 环境桥接
│   ├── backend/                 # FastAPI 后端服务 (routes/, services/, utils/, api_server.py, lan_share.py)
│   ├── blast/                   # 本地 BLAST+ 并发调度与库管理
│   ├── figure_studio/           # 科研出版级多图型渲染引擎
│   ├── mail_download/           # 自动化邮件收发与注释回传流水线
│   ├── phage_discovery/         # 前噬菌体深度学习模型与边界精修推理栈
│   ├── phylo/                   # 系统发育树引擎 (MSA, ANI, Marker, Tree, 出版渲染)
│   ├── resources/               # 国际化词典 (zh_CN / en_US) 与算法引文库 (citations.json)
│   ├── utils/                   # 通用工具集 (resource_guard, help_manager, config_manager, translation 等)
│   ├── web-next/                # Vue 3.5 + TypeScript + Vite 7 前端工程
│   └── workbench/               # 生信工具路径配置与运行模型
├── tests/                       # Pytest 自动化测试与仓库卫生/安全守护测试
├── LICENSE                      # MIT 开源许可证
├── pyrightconfig.json           # Python 类型检查配置
├── requirements.txt             # Python 核心依赖
└── RUN_DEV_ELECTRON.bat         # Windows 桌面端一键自愈与启动脚本
```

---

## 4. 快速上手与开发测试

### 4.1 环境要求
- **操作系统**：Windows 10 / Windows 11 (64 位)
- **Node.js**：18.0 及以上（推荐 20+）
- **Python**：3.10 至 3.13（64 位）
- **WSL2 (可选，推荐)**：Ubuntu 22.04 LTS，用于运行 Linux 生信组装、注释与构树工具链。

### 4.2 一键启动桌面工作站
```cmd
RUN_DEV_ELECTRON.bat
```

### 4.3 分体式开发与测试验证
```cmd
:: 启动 FastAPI 后端服务 (默认端口 8765，支持 /api/health 探活)
call .venv\Scripts\activate.bat
python -m src.backend.api_server

:: 运行后端安全、卫生与核心回归测试
pytest tests/test_security_and_lan_guard.py tests/test_repo_hygiene.py tests/test_resource_guard_and_hygiene_p2.py -q

:: 前端开发、单测与生产编译
cd src\web-next
npm run dev
npm run test -- --run
npm run build
```

---

## 5. 工程规范与安全约束
1. **禁用 Emoji 表情**：源码、国际化词典、运行日志与文档全面禁用 Emoji，由 `tests/test_repo_hygiene.py` 自动守护。
2. **消除硬编码绝对路径**：全系统采用相对路径与动态环境探测，禁止个人盘符硬编码。
3. **强制 UTF-8 编码**：禁用 GBK/CP936 编码，由 AST 测试持续守护全 `src/` 目录。
4. **硬件红线保护**：统一经由 `src/utils/resource_guard.py` 预留 CPU 核心并管理 CUDA 显存释放；批量推理执行分片落盘与断点保护。
5. **网络安全隔离**：FastAPI 保持 `0.0.0.0` 动态支持 LAN Share，但关闭共享时经 `LanAccessGuardMiddleware` 拦截一切非回环 IP；静态路由与帮助文档均强制执行路径穿越校验；Electron 主进程启用 `sandbox: true`、CSP 与 IPC 来源/协议白名单。

---

## 6. 开源许可证
本项目基于 [MIT 许可证](LICENSE) 开源。所集成生信算法的标准化引用信息统一维护于 `src/resources/citations.json`。
