# NCBI Bio-Station | 生物序列分析与基因组全流程工作站

NCBI Bio-Station (NCBI BLAST Pro) 是一套面向生物医学、微生物学及基因组学研究的跨平台工业级生物计算分析平台。系统采用“跨平台桌面容器 + 现代化高响应前端 + 异步高并发后端 + 混合生信计算引擎”的现代化分层架构，深度集成序列比对、高保真基因组拼接、全基因组结构与功能注释、Sanger 一代测序峰图分析、泛基因组分析、核心蛋白质比对、系统发育进化树分析、菌毒种资产管理及局域网协同共享等全流程功能，为科研人员提供开箱即用的一站式计算生物学解决方案。

---

## 1. 核心业务功能矩阵

### 1.1 BLAST 序列比对与智能鉴定中心
- **本地 BLAST+ 极速并行**：原生驱动 `blastn`、`blastp`、`blastx`、`tblastn`、`tblastx` 等核心算法，支持多核并行加速，保障数据离线计算的私密性与安全性。
- **云端 Elastic BLAST 弹性调度**：无缝对接 AWS 与 GCP 云端计算实例，针对超大规模或海量高通量比对任务实现自动弹性伸缩与结果聚合。
- **自动化结果解析与一致性判定**：内置高性能结果解析引擎与结果缓存机制，自动提取 Top Hits 最佳比对项，推断生物学分类学名。
- **数据库全生命周期管理**：支持从 FASTA 文件构建本地化专有比对库 (`makeblastdb`)，并提供 NCBI 官方核心数据库（如 `nt`、`nr`、`16S_ribosomal_RNA`、`swissprot` 等）的下载与更新。

### 1.2 NGCS 基因组拼接组装流水线 (Genome Assembly Pipeline)
- **NGCS 核心组装架构**：全面收敛并采用 NGCS (Neural Genome Coordinate System) 核心高保真组装引擎，包含二代欧拉残差流与三代连续谱流形拓扑及 SIMD-POA 分层打磨。
- **多平台自适应路由**：自动识别并路由 Illumina/MGI 短读长双端测序数据与 Nanopore/PacBio 长读长单分子测序数据。
- **全流程上游质控与清洗**：内置 Fastp 自动测序数据质控过滤、接头剪切与低质量碱基修剪。
- **测序深度与覆盖度动态解析**：结合比对与覆盖度计算组件，提供 Contigs 加权平均深度、覆盖度分布及 GC 含量曲线解析。
- **学术级装配指标评估**：自动生成 N50、L50、Contig 数量、总装配长度分布图，自动完成环状染色体/质粒拓扑结构检测与断点修复。
- **串行持久化任务队列**：采用基于持久化存储的串行任务队列，防止多任务并发引起系统硬件资源耗尽与系统卡死。
- **WSL 容器化环境无缝互通**：支持 Windows 与 WSL2 Linux 运行时深度互联，自动建立软链接消除目录空格兼容性隐患，生命周期结束时自动安全回收分发版内存。

### 1.3 组装后深度分析工作台 (Analysis Workbench)
- **Sanger 测序峰图分析与突变检测**：
  - 高保真解析 AB1 格式色谱荧光原始信号与质量值 (QV)。
  - 智能识别单核苷酸变异 (SNV) 与 InDel 移码重叠峰。
  - 支持双单倍型位移解卷积分离与主序列提取导出。
- **全基因组结构与功能注释**：
  - 集成 Prokka、Pharokka、Phold、Prodigal 等原核生物与噬菌体专业注释引擎。
  - 全面完成 CDS 编码区、tRNA 及 rRNA 基因预测。
  - CDD/RPS-BLAST 级联注释引擎，针对假定蛋白 (Hypothetical Protein) 进行深度功能补齐。
  - 自动生成标准化 GFF3、GenBank (GBK) 注释文件并支持无缝下发可视化。
- **核心功能蛋白同源性比对**：
  - 针对两样本间结构蛋白、裂解酶、复制酶等关键基因进行同源性与一致性精准比对。
  - 自动标注氨基酸点突变并生成变异谱图。
- **多样本泛基因组比较分析 (Pan-Genomics)**：
  - 基于直系同源基因聚类算法构建泛基因组族谱。
  - 精确统计核心基因组 (Core)、附属基因组 (Accessory) 与特异基因组 (Unique) 的得失演变。
  - 解析受体结合蛋白多态性与噬菌体生活史 (Lifestyle / 溶源性与裂解性特征) 及生物安全性评估。
- **基因组序列图谱双模式可视化**：
  - **环形图谱模式**：集成 CGView 渲染引擎，直观展示全基因组环状图谱、正负链 CDS 分布、GC 含量与 GC Skew 波动。
  - **线性图谱模式**：集成 IGV.js 基因组浏览器，支持高分辨率缩放平移、多轨道特征层叠与单碱基级测序深度比对浏览。

### 1.4 系统发育进化树中心 (Phylogenetic Tree)
- **多序列比对 (MSA)**：集成 MAFFT、Muscle 与 ClustalW 算法引擎。
- **系统发育构建**：支持 FastTree、IQ-TREE 以及邻接法 (Neighbor-Joining)、最大似然法 (Maximum Likelihood) 多种构树策略。
- **交互式可视化展示**：基于 Phylotree.js 与 D3 引擎，支持环形树、矩形树灵活切换，提供分支折叠、置信度标注、节点重命名与高质量矢量图导出。

### 1.5 菌毒种资源库与分类学中心 (Strain DB & Taxonomy)
- **本地菌株资产管理**：基于 SQLite 构建本地化菌毒种资产库，支持样本元数据录入、多维度标签管理、批量导入导出及历史鉴定追溯。
- **NCBI Taxonomy 本地化服务**：内置本地分类数据库 (taxa.sqlite / ETE4 驱动)，提供离线分类阶元树回溯、学名标准化与层级展示。
- **物种分类界定**：支持平均核苷酸一致性 (ANI) 计算与 16S rRNA 相似度联合鉴定。

### 1.6 AI 智能翻译与生物学专业词典
- **大语言模型生态对接**：支持接入 DashScope (Qwen 通义千问)、DeepSeek、OpenAI 等主流大模型 API。
- **本地术语持久化与高速提取**：基于 SQLite 本地词库缓存数百兆专业翻译条目，结合毫秒级专有名词提取器，实现本地毫秒级命中。
- **学术规范与学名保护**：内置生物学分类学规则引擎，严格保护拉丁双名法学名不受机器翻译破坏，实现表型与医学描述的规范中文化。

### 1.7 局域网协同共享模式 (LAN Share)
- **跨终端即时协同**：一键开启局域网共享广播，支持移动终端（手机、平板）或实验室其他设备通过局域网免安装访问分析结果、查看交互式图谱与下载报告。

### 1.8 系统环境自愈与运行安全保障
- **环境自愈与依赖巡检**：内置自动巡检脚本，初次启动或运行异常时自动探测并修复必要目录结构，自动补齐 FastTree、Muscle 等附属二进制程序。
- **国内高速镜像优化**：预置清华源、阿里源及 npmmirror 镜像源配置，解决国内网络环境下依赖下载超时问题。
- **资源监控与安全红线**：实时监测系统 CPU 利用率与物理内存使用量；严格遵守显存与内存安全红线，杜绝海量数据长期囤积在内存中，执行分片落盘与断点保护。

---

## 2. 系统技术架构

### 2.1 架构层次划分

```text
+-----------------------------------------------------------------------+
|                      桌面应用层 (Electron Shell)                       |
|         BrowserWindow 生命周期管理 | IPC 通信 | Python Sidecar 守护进程  |
+-----------------------------------------------------------------------+
                                  |
                                  v
+-----------------------------------------------------------------------+
|                  现代前端交互层 (Vue 3 + TypeScript)                   |
|  - 视图组件: Dashboard, BLAST, Assembly, Analysis, Tree, Strain, Settings |
|  - 生信可视化: CGView, IGV.js, Plotly.js, Phylotree.js, D3.js, Three.js  |
|  - 状态控制: Pinia 响应式状态流, Vue Router 路由, TailwindCSS 现代化样式   |
+-----------------------------------------------------------------------+
                                  | HTTP REST / WebSocket 实时广播 (8765)
                                  v
+-----------------------------------------------------------------------+
|                  高性能后端服务层 (FastAPI + Uvicorn)                   |
|  - 路由调度: routes/ (blast, assembly, analysis, annotation, tree...)  |
|  - 任务管控: PersistentQueue 串行任务队列, Broadcaster 状态广播中心      |
|  - 存储中心: SQLite (菌株库, 序列库, 翻译缓存库, NCBI Taxonomy 本地库)    |
+-----------------------------------------------------------------------+
                                  | 系统进程调用 / WSL2 Linux 桥接
                                  v
+-----------------------------------------------------------------------+
|                       混合生物信息学计算引擎层                          |
|  - 序列比对: NCBI BLAST+ (blastn, blastp...), Elastic BLAST           |
|  - 基因组组装: NGCS (二代欧拉残差流 / 三代连续谱流形), Fastp, QUAST, Depth |
|  - 结构与功能注释: Prokka, Pharokka, Phold, Prodigal, CDD / RPS-BLAST  |
|  - 系统发育分析: MAFFT, Muscle, FastTree, IQ-TREE                     |
|  - 生物计算底层: Biopython, Edlib, NumPy, Pandas                      |
+-----------------------------------------------------------------------+
```

### 2.2 核心技术选型

| 架构维度 | 采用技术 / 库 | 用途与定位 |
| :--- | :--- | :--- |
| **桌面壳层** | Electron | 跨平台应用分发、本地文件系统权限与 Python 守护 |
| **前端框架** | Vue 3.5 + TypeScript + Vite 7 | 现代化高响应度前端交互 |
| **状态与样式** | Pinia + TailwindCSS | 全局状态管理与现代界面样式系统 |
| **生信交互组件** | CGView, IGV.js, Plotly.js, Phylotree, Three.js | 环状图谱、线性基因组、深度曲线、进化树、3D分子 |
| **后端框架** | FastAPI + Uvicorn + WebSockets | 异步 REST 接口服务与任务状态毫秒级实时广播 |
| **数据存储** | SQLite 3 | 菌株元数据、任务历史记录、专业术语本地缓存 |
| **生信核心套件** | Biopython, NCBI BLAST+, NGCS, Fastp, QUAST | 基础生物序列运算、局部比对、全基因组拼接与评测 |
| **注释与发育树** | Prokka, Pharokka, Phold, FastTree, IQ-TREE | 结构注释、噬菌体注释、功能蛋白比对与进化发育分析 |

---

## 3. 项目目录结构

```text
NCBI BLAST/
├── database/                    # 数据库存放目录
│   ├── 16S/                     # 16S 核糖体 RNA 本地数据库
│   └── taxonomy/                # NCBI 本地分类学数据库 (taxa.sqlite / ETE4)
├── docs/                        # 项目设计与开发留档文档
│   ├── node_studio_records/     # 节点工作流研发记录
│   ├── project_structure.md     # 历史工程结构快照
│   └── readme_update_record.md  # README 更新过程留档
├── electron-shell/              # Electron 桌面端主进程与配置文件
│   ├── main.js                  # Electron 启动入口与 Python Sidecar 守护
│   ├── preload.js               # IPC 桥接安全注入脚本
│   └── package.json             # Electron 运行依赖配置
├── reports/                     # 自动生成的分析报表与导出产物
├── resources/                   # 静态帮助资源与本地化支持
│   └── help/                    # 模块 Markdown 帮助文档
├── results/                     # 分析计算结果目录
│   ├── assembly/                # 基因组拼接组装任务产物
│   └── tree_results/            # 系统发育进化树运算产物
├── scripts/                     # 生信扩展分析脚本与运维辅助工具
│   ├── build_cdd_rps_index.py   # CDD 结构域索引构建脚本
│   ├── heal_assembly_metrics.py # 组装指标自愈修复脚本
│   ├── setup_assembly_env.sh    # Linux/WSL 组装环境配置脚本
│   └── test_end_to_end_pipeline.py # 全流程端到端自动化测试
├── src/                         # 平台核心源代码目录
│   ├── analysis/                # 高级生信分析模块
│   │   ├── annotation/          # 全基因组结构与功能注释引擎 (Prokka/Pharokka/Phold/Prodigal)
│   │   ├── comparison/          # 序列共线性与 ANI 计算
│   │   ├── pan_genomics/        # 泛基因组分析与生活史预测
│   │   └── protein_compare/     # 核心功能蛋白同源性比对
│   ├── assembly/                # NGCS 基因组拼接组装系统
│   │   ├── core/                # 流水线抽象基类与上下文管理
│   │   ├── engine/              # NGCS 执行器与 GPU 硬件检测适配
│   │   ├── env/                 # WSL2 运行环境与软链接管理器
│   │   ├── steps/               # 组装子步骤 (Assembler, Fastp, Quast, Depth)
│   │   └── manager.py           # 组装任务调度管理器
│   ├── backend/                 # FastAPI 后端服务
│   │   ├── routes/              # 业务路由切片 (blast, assembly, analysis, strains, tree...)
│   │   ├── utils/               # 后端工具集 (blast_utils, persistent_queue, assembly_db)
│   │   ├── api_server.py        # 后端主服务入口与生命周期托管
│   │   ├── broadcaster.py       # WebSocket 实时广播服务
│   │   ├── lan_share.py         # 局域网协同共享服务管理器
│   │   └── strain_db.py         # 菌株数据库持久化管理器
│   ├── blast/                   # BLAST 核心算法引擎
│   │   ├── database_manager.py  # BLAST 本地数据库下载与构建
│   │   ├── executor.py          # BLAST 本地多核并发调度器
│   │   └── manager.py           # BLAST 任务执行与回调分发
│   ├── resources/               # 国际化多语言本地化资源包 (zh_CN / en_US)
│   ├── utils/                   # 通用工具集
│   │   ├── translation/         # AI 大模型翻译与本地 SQLite 词库缓存
│   │   ├── config_manager.py    # 全局系统参数配置管理器
│   │   ├── taxonomy_provider.py # 分类学本地查询服务提供者
│   │   └── verify_and_install_deps.py # 环境自愈与依赖自动补齐模块
│   ├── web-next/                # Vue 3 前端工程
│   │   ├── src/                 # 前端源码 (components, views, stores, router)
│   │   ├── package.json         # 前端依赖配置
│   │   └── vite.config.ts       # Vite 构建与服务配置
│   └── workbench/               # 生信工具包装层与运行模型定义
├── vendor/                      # 附属生信计算二进制组件 (FastTree, Muscle, IQ-TREE 等)
├── build.bat                    # 前端工程快速构建脚本
├── build_release.py             # 工业级发布构建打包脚本
├── dev.bat                      # 纯前端 Vite 开发启动脚本
├── RUN_DEV_ELECTRON.bat         # 桌面端完整环境一键自愈与启动脚本
├── requirements.txt             # Python 后端核心依赖列表
└── config.json                  # 系统核心全局配置文件
```

---

## 4. 快速上手与操作指南

### 4.1 环境准备
- **操作系统**：Windows 10 / Windows 11 (64位)
- **Node.js**：18.0 及以上版本
- **Python**：3.10 或 3.11（推荐 64 位版本）
- **WSL2 (可选，推荐)**：用于运行 Linux 高性能生信组装与注释工具链（如 Ubuntu 22.04 LTS）。

### 4.2 一键自愈与全流程启动 (推荐)
双击运行根目录下的自愈启动脚本：
```cmd
RUN_DEV_ELECTRON.bat
```
该脚本将自动执行以下自动化动作：
1. 检查并校验系统 Node.js 与 Python 环境（如缺失可通过 winget 智能拉取）。
2. 检测或重建 Python 虚拟环境 (`.venv`)。
3. 运行 `verify_and_install_deps.py` 进行目录结构补齐、附属二进制工具自愈并配置清华源补齐 Python 依赖。
4. 基于 npmmirror 镜像源检查并安装 Electron 及前端依赖。
5. 启动 Vite 开发服务，同时唤起 Electron 桌面工作站窗口，并自动拉起 Python FastAPI 后端服务。

### 4.3 分体式开发调试模式

#### 启动后端 API 服务
```cmd
# 激活虚拟环境
call .venv\Scripts\activate.bat

# 启动 FastAPI 后端服务 (默认监听 8765 端口)
python -m src.backend.api_server
```

#### 启动前端开发调试
```cmd
# 进入前端工作区
cd src\web-next

# 安装依赖 (如尚未安装)
npm install --registry=https://registry.npmmirror.com

# 启动前端开发服务器 (默认端口 5173)
npm run dev
```

#### 启动 Electron 桌面应用
```cmd
# 进入 Electron 工作区
cd electron-shell

# 启动桌面容器 (已集成对已启动 Vite 与 Python 服务的探活接入)
npm run dev
```

### 4.4 生产打包发布
系统提供工业级自动化构建脚本，自动执行前端编译、静态资源 Robocopy 同步、NCBI BLAST+ 套件集成与独立可分发程序打包：
```cmd
python build_release.py
```
构建产物将输出至 `dist/NCBI_BLAST_GUI/` 目录。

---

## 5. 系统核心运行规范与原则

本系统在代码实现与工程维护中严格遵循以下架构规范：
1. **禁用 Emoji 表情**：代码实现、运行日志、分析报表及文档中均禁用 Emoji 符号，确保字符集跨平台兼容性与严肃科研规范。
2. **单一职责与目录模块化**：严格拆分各生信分析模块，各引擎独立封装，保证高内聚、低耦合。
3. **消除硬编码**：全系统严格使用相对路径与可配置相对引用，禁止物理磁盘绝对路径硬编码。
4. **内存保护与分片落盘**：海量数据处理（如长读长比对、泛基因组分析、批量翻译）严格实施“分片落盘与断点保护 (Checkpoint)”机制，严禁海量结果长期积聚于内存引发 OOM 崩溃。
5. **硬件资源控制与防卡死**：
   - 多核并行调度时，严格预留系统核心数，防止主机界面假死。
   - 严格监控物理显存红线，涉及 GPU 计算时控制 Batch Size，引擎切换时强制执行显存垃圾回收。
6. **全流程字符编码控制**：全系统禁用 GBK 编码，强制所有文件读写声明与使用 UTF-8 编码，消除中文字符乱码风险。

---

## 6. 开源许可证与致谢

- **开源许可证**：本项目采用 [MIT 许可证](LICENSE)。
- **学术与工具致谢**：
  - NCBI (National Center for Biotechnology Information) 提供 BLAST+ 及 Taxonomy 分类数据支持。
  - NGCS (Neural Genome Coordinate System) 提供新一代高精度基因组组装技术架构。
  - Biopython、FastTree、IQ-TREE、Fastp、QUAST、Prokka、Pharokka 等开源生物信息学软件与算法。
  - Vue.js、Electron、FastAPI、CGView、IGV.js、Phylotree.js 等现代化开源软件生态。
