# 噬菌体本地数据集下载、多核真伪验证与索引构建留档记录

## 1. 任务目标与总体结果

向 `F:\Phage data` 下载并扩充跨宿主高多样性的 NCBI RefSeq 完整噬菌体基因组（配对 `.fasta` 与 `.gbk`），执行多核并行序列完整性校验及**四维噬菌体身份真伪核验**，最终构建关系型（SQLite WAL）、表格（TSV）、清单（JSON）与本地 NCBI BLAST+（核酸 + 蛋白）多维检索索引。

- **最新构建时间**：2026-11-13
- **数据落盘目录**：`F:\Phage data`
- **最终样本规模**：**5,000 株高置信真实噬菌体基因组**（`5,000 / 5,000` 验证为 `high` 置信度噬菌体，`failed_count=0`，`rejected_non_phage_count=0`）

---

## 2. 模块化架构 (`src/utils/phage_dataset/`)

按单一职责与模块化原则拆分构建，所有文件均强制 UTF-8 编码、零硬编码路径、保留 CPU 核心并发并支持断点保护：

1. **`src/utils/phage_dataset/ncbi_downloader.py`**
   - 覆盖 14 个主流细菌宿主与分类分层（`Escherichia`、`Salmonella`、`Pseudomonas`、`Klebsiella`、`Staphylococcus`、`Bacillus`、`Mycobacterium`、`Vibrio`、`Acinetobacter`、`Streptococcus`、`Enterococcus`、`Listeria`、`Non_Caudoviricetes_Phages`、`General_Caudoviricetes`）。
   - 采用 Round-Robin 交错采样与分层分页补齐机制（`Caudoviricetes` + `Microviricetes/Microviridae` + `Inoviridae` + `Leviviricetes (txid2842243)` + `Tectiviridae` + `Cystoviridae` + `Corticoviridae`）。
   - 批量调用 `gbwithparts` 下载并切分为单株 `.gbk` 与 `.fasta` 原子写盘，在落盘前调用 `_assess_phage_identity` 拦截非噬菌体记录，维护 `meta/download_checkpoint.json` 断点保护。
2. **`src/utils/phage_dataset/validator.py`**
   - 使用 `ProcessPoolExecutor` 多核并行校验（自动保留 2 个 CPU 核心，本机 32 核并发上限设为 16 进程）。
   - **完整性与注释校验**：`.fasta`/`.gbk` 双文件存在且非空、UTF-8 编码、`fa_seq == gb_seq` 全序列一致、最小长度阈值（`>=3000 bp`）、IUPAC 碱基合法性、N 碱基比例、CDS/tRNA 数量提取、关键特征基因标记及双文件 SHA-256 指纹。
   - **四维噬菌体身份真伪核验 (`_assess_phage_identity`)**：
     1. 分类树判定：必须属于 `Viruses`，排除真核/古菌非噬菌体病毒门纲科（如 `Pisuviricota`、`Kitrinoviricota`、`Negarnaviricota`、`Coronaviridae`、`Solemoviridae`、`Adenoviridae` 等），识别权威 ICTV 噬菌体分类群（包含新版 `Phixviricota; Microviricetes` 等）；
     2. 物种命名语义：识别 `bacteriophage/phage/prophage/microphage/coliphage/cyanophage/mycobacteriophage` 等特征词；
     3. 宿主类型检查：识别原核细菌宿主与真核宿主拦截；
     4. 广谱噬菌体蛋白特征：覆盖有尾、丝状、微小、RNA 及覆膜噬菌体的结构/包装/裂解标志蛋白计数。
3. **`src/utils/phage_dataset/indexer.py`**
   - 原子生成 `index/phage_index.sqlite`（WAL 模式，`genomes` 表含 `is_phage`、`phage_confidence`、`phage_tax_group`、`phage_evidence` 字段 + `cds_features` 表 + 8 个检索索引）。
   - 输出 `index/phage_index.tsv` 与 `index/manifest.json`。
   - **严格净库过滤**：仅将 `status in ("passed", "warning") and is_phage` 的记录写入 `blastdb/phage_refseq_nucl.fna` 与 `blastdb/phage_refseq_prot.faa`，并利用无空格临时目录暂存建库机制解决 Windows 下 NCBI BLAST+ `2.16.0+` LMDB mmap 路径空格异常。
4. **`src/utils/phage_dataset/pipeline.py`**
   - 统一 CLI 与编排入口。

---

## 3. 异常拦截与过程迭代留档

在从 500 株扩充至 5,000 株的过程中，四维真伪校验器发挥了关键把关作用：
1. **初次全库扩容拦截 `613` 条真核病毒**：最初在 `Non_Caudoviricetes_Phages` 检索词中误用了 `txid2732408`（在 ICTV 新版分类体系中该 ID 已指向囊括冠状病毒、肠道病毒、植物病毒的 `Pisuviricota`），`validator.py` 自动识别并拦截出其中 `613` 条真核病毒将其排除于 `blastdb` 之外；随后修正 `Leviviricetes` 的正确 TaxID 为 `txid2842243`，同时在 `validator.py` 中补充 `Phixviricota; Microviricetes` 分类名（挽回 22 株微小噬菌体）并剔除该 `613` 条非噬菌体后补足新样本。
2. **二次复检清除 `3` 条植物伴随/极光病毒**：在检查 `Unclassified_Phage` 时发现 `NC_076825.1`（`Groundnut rosette assistor virus`）、`NC_117050.1`（`Pterostylis polerovirus`）、`NC_139275.1`（`Red clover enamovirus 1`）因含 `coat protein` 与非黑名单植物宿主而通过宽松规则；随后收紧 `_assess_phage_identity` 规则并将 `Pisuviricota` / `Solemoviridae` / `Polerovirus` / `Enamovirus` 纳入排除清单，清除该 3 条记录后补齐至纯正 `5,000` 株。

---

## 4. 5,000 株全量验证与实测检索指标

### 4.1 数据集统计（源自 `F:\Phage data\index\manifest.json`）

| 指标 | 实测值 |
| :--- | :--- |
| 配对基因组总数 | `5,000`（`5,000` 个 `.fasta` + `5,000` 个 `.gbk`） |
| 校验通过 / 警告 / 失败 | `4,999` / `1` (`NC_075027.1` N 比例 `7.039%`) / `0` |
| 噬菌体真伪验证结果 | `5,000 / 5,000` 验证通过（`high` 置信度 `5,000` 株，`rejected=0`） |
| 分类群分布 | `Caudoviricetes` (`4,796`)、`Inoviridae` (`80`)、`Microviridae` (`56`)、`Leviviricetes` (`53`)、`Tectiviridae` (`12`)、`Corticoviridae` (`2`)、`Cystoviridae` (`1`) |
| 基因组总碱基数 / 平均长度 | `345,104,482 bp` / `69,020.9 bp`（最长 `497,513 bp`） |
| 拓扑结构分布 | 线性 (`linear`) `4,228` 株，环状 (`circular`) `772` 株 |
| 提取 CDS / 翻译蛋白总数 | `508,951` 条（总残基 `104,921,604` aa，最长 `7,351` aa） |
| 关键特征检出株数 | 整合酶 `1,902` 株、末端酶 `4,618` 株、裂解酶 `4,443` 株 |
| 主要宿主分布（前 5） | `Mycobacterium smegmatis mc2 155` (428)、`Escherichia coli` (219)、`Gordonia terrae 3612` (201)、`Unspecified` (165)、`Klebsiella pneumoniae` (125) |

### 4.2 多维索引与端到端检索实测

1. **SQLite WAL 数据库**：`F:\Phage data\index\phage_index.sqlite` -> `genomes` `5,000` 行（`is_phage=1 AND phage_confidence='high'` 共 `5,000` 行），`cds_features` `508,951` 行。
2. **TSV 清单**：`F:\Phage data\index\phage_index.tsv` -> `5,001` 行（表头 + `5,000` 条记录）。
3. **BLAST+ 库元数据检验 (`blastdbcmd -info`)**：
   - `phage_refseq_nucl`: BLASTDB Version 5，`5,000` sequences，`345,104,482` total bases，退出码 `0`
   - `phage_refseq_prot`: BLASTDB Version 5，`508,951` sequences，`104,921,604` total residues，退出码 `0`
4. **真实检索抽检**：
   - `blastn`（非有尾微小噬菌体 `NC_001422.1` phiX174）：返回退出码 `0`，首条命中 `ref|NC_001422.1|`（`pident=100.000`, `length=5386`, `evalue=0.0`, `bitscore=9947`），次优命中同源噬菌体 `ref|NC_007825.1|`。
   - `blastp`（样本 `NC_000866.4|NP_049616.1|T4p001`）：返回退出码 `0`，首条精确自命中 `100.000%`（`length=725`, `bitscore=1491`），并召回同源蛋白 `NC_025448.1|YP_009102206.1|RB27_001`（`99.172%`）。

### 4.3 单元测试验证

测试文件 `tests/test_phage_dataset_pipeline.py` 与 `tests/test_engineering_optimizations.py` 联合执行通过（`11 passed`）。

---

## 5. 常用命令行与检索使用说明

```powershell
# 仅基于本地现有文件重跑多核完整性及噬菌体真伪校验并重建全部索引
.\.venv\Scripts\python.exe -m src.utils.phage_dataset.pipeline --data-dir "F:\Phage data" --skip-download --count 5000

# 在 Windows 下调用 blastn / blastp 检索本库（切入 blastdb 目录以规避路径空格触发 LMDB mmap 异常）
Push-Location "F:\Phage data\blastdb"
blastn -query "path\to\query.fasta" -db phage_refseq_nucl -outfmt 6 -num_threads 8
blastp -query "path\to\query.faa" -db phage_refseq_prot -outfmt 6 -num_threads 8
Pop-Location
```

---

## 6. 5,000 株正样本训练前预处理（多核分片 + GPU 聚类无泄露切分）

模块文件：`src/utils/phage_dataset/preprocessor.py`，输出目录：`F:\Phage data\preprocessed\`。

### 6.1 处理流程与算法演进
1. **分片特征抽取**：保留 CPU 核心启用 `16` 进程并行，以 `250` 株为分片落盘并维护 `preprocess_checkpoint.json`：
   - 计算 136 维反向互补规范化 4-mer 频谱向量、基因密度（`cds_per_kb`）、编码率、同向转录链长度与 8 类噬菌体核心功能标签；
   - 流式落盘 `508,951` 条有序 ORF 拓扑序列分片（`shards/orf_shard_*.jsonl`）与 `135,527` 个 `5kb`（步长 `2.5kb`）滑窗特征分片（`shards/win_shard_*.jsonl`）。
2. **GPU 聚类去冗余升级**：利用 `NVIDIA GeForce RTX 4070 Laptop GPU` 计算余弦相似度后显式执行 `torch.cuda.empty_cache()`。将初版传递闭包并查集（出现 `4,447` 株雪球串联簇）升级为 **Greedy Centroid 中心聚类**（`sim_threshold=0.994`, `min_len_ratio=0.85`），并按簇做分层 8:1:1 切分。

### 6.2 预处理实测结果（源自 `F:\Phage data\preprocessed\preprocess_manifest.json`）

| 指标 | 实测值 |
| :--- | :--- |
| 计算设备 | `cuda:NVIDIA GeForce RTX 4070 Laptop GPU` |
| 有效基因组总数 / 聚类簇总数 | `5,000` 株 / `1,323` 簇（单例 `768`，最大簇 `119`） |
| 累计提取 ORF / 5kb 滑窗 | `508,951` 条 / `135,527` 窗 |
| 全库平均基因密度 / 编码率 | `1.477` CDS/kb / `0.9133` |
| Train / Val / Test 切分规模 | `4,001` / `500` / `499`（核验跨集同簇泄露数 = `0`） |

---

## 7. 配套负样本库构建与实测索引（`F:\Phage data\negative`）

模块文件：`negative_downloader.py`、`negative_validator.py`、`negative_indexer.py`、`negative_pipeline.py`。

### 7.1 负样本组成、反向校验与规模（源自 `F:\Phage data\negative\index\manifest.json`）

| 指标 | 实测值 |
| :--- | :--- |
| 配对文件总数 | `600` 个 `.fasta` + `600` 个 `.gbk` |
| 完整性与反向排异校验 | `600 / 600` 全部通过（`warning=0`, `failed=0`, `rejected_phage_contaminated=0`） |
| 负样本子类构成 | 细菌质粒 (`plasmid`) `433` 条 (`33,864,981 bp`)；非噬菌体真核/古菌病毒 (`non_phage_virus`) `107` 条 (`6,101,471 bp`)；代表细菌染色体 (`bacterial_chromosome`) `60` 条 (`231,846,066 bp`) |
| 总碱基数 / 平均长度 | `271,812,518 bp` / `453,020.9 bp`（最长 `5,460,057 bp`） |
| 提取 CDS / 翻译蛋白总数 | `261,189` / `261,188` 条（总残基 `78,119,468` aa，最长 `14,259` aa） |
| 拓扑结构分布 | 环状 (`circular`) `514` 条，线性 (`linear`) `86` 条 |
| 含疑似前噬菌体标记蛋白记录数 | `421` 条（已在数据库标记 `suspected_prophage_cds_count`，供下游生成负样本窗口时屏蔽剔除） |

### 7.2 索引与 BLAST 检索抽检
- **SQLite WAL 数据库**：`F:\Phage data\negative\index\negative_index.sqlite` -> `genomes` 表 `600` 行（`is_valid_negative=1` 共 `600` 行），`cds_features` 表 `261,188` 行。
- **TSV 清单**：`F:\Phage data\negative\index\negative_index.tsv` -> `601` 行。
- **本地 BLASTDB v5 索引**：
  - `neg_refseq_nucl`: `600 sequences; 271,812,518 total bases`，`blastn` 抽检 `NC_001391.1.fasta` 退出码 `0`，精确命中 `ref|NC_001391.1|`（`pident=100.000`, `length=3879`）。
  - `neg_refseq_prot`: `261,188 sequences; 78,119,468 total residues`，`blastp` 抽检 `NC_001391.1|PLSM16036718_RS00005` 退出码 `0`，精确自命中 `100.000%`。
- **单元测试**：`tests/test_negative_and_preprocess.py`、`tests/test_phage_dataset_pipeline.py` 与 `tests/test_engineering_optimizations.py` 联合执行通过。

---

## 8. 数据库冗余清理、噪声过滤与前噬菌体掩蔽（`cleaner.py`）

针对 `F:\Phage data` 正负样本数据库中存在的多余构建中间体、微肽/假基因噪声、高 N 残缺序列以及细菌染色体/质粒内潜伏前噬菌体片段污染，新增模块化清理引擎 `src/utils/phage_dataset/cleaner.py`，并同步加固 `indexer.py` 与 `negative_indexer.py`（建库后默认安全删除中间 `.fna`/`.faa`，并在落盘前过滤 `<25 aa` 片段及执行 SQLite `VACUUM`）。

### 8.1 实测清理与空间回收（源自 `F:\Phage data\meta\cleanup_report.json`）

| 清理维度 | 正样本 (`F:\Phage data`) | 负样本 (`F:\Phage data\negative`) |
| :--- | :--- | :--- |
| 中间合并 FASTA/FAA 清理 | 移除 `phage_refseq_nucl.fna` (`340.38 MB`) 与 `phage_refseq_prot.faa` (`131.24 MB`) | 移除 `neg_refseq_nucl.fna` (`267.91 MB`) 与 `neg_refseq_prot.faa` (`94.70 MB`) |
| `cds_features` 噪声剔除 | 移除 `<25 aa` `428` 条 + 假基因 `11` 条（`508,951` -> `508,512`） | 移除 `<25 aa` `1,216` 条 + 假基因 `791` 条（`261,188` -> `259,181`） |
| SQLite `VACUUM` 体积变化 | `67.10 MB` -> `67.04 MB`（`<25 aa` 残余 = `0`） | `40.96 MB` -> `40.65 MB`（`<25 aa` 残余 = `0`） |
| **磁盘总计回收** | **471.63 MB**（含 `0.06 MB` SQLite） | **362.92 MB**（含 `0.30 MB` SQLite），合计 **`834.60 MB`** |

### 8.2 负样本潜伏前噬菌体掩蔽（`prophage_masks`）与高 N 过滤

1. **前噬菌体精准掩蔽**：使用本地 `blastn`（`perc_identity=80.0`, `min_hit_len=500`, `evalue=1e-20`, 前后扩增 `±1,000 bp`）联合注释蛋白基因簇（>=2 个核心噬菌体基因间距 `<=10 kb`）扫描 `493` 条细菌染色体和质粒，发现原始 BLASTn 同源命中 `8,141` 处与核心基因簇 `399` 处；合并区间后在 **`216` 条负样本序列**（`156` 质粒 + `60` 细菌染色体）共标记 **`1,667` 个掩蔽区间**，覆盖 **`11,581,917 bp`**（`11.045 Mb`），已持久化至 `negative_index.sqlite` 的 `prophage_masks` 表与 `negative/index/prophage_masks.tsv`，供下游滑窗采样直接跳过以防负标签中毒。
2. **高 N 残缺正样本出库（Splits）**：将 `n_percent > 2.0%` 的 `3` 株正样本（`NC_075027.1` `7.039%`, `NC_029001.1` `2.637%`, `NC_048665.1` `2.257%`）从 `preprocessed/splits/train.tsv` 剔除，同步更新 `preprocess_manifest.json`（划分规模调整为 `train=3,998` / `val=500` / `test=499`），原始 `.fasta`/`.gbk` 档案保留以备溯源。
3. **BLASTDB 完整性复验**：清理后实测 `blastdbcmd -info`，`phage_refseq_nucl` (`5,000` seqs)、`phage_refseq_prot` (`508,951` seqs)、`neg_refseq_nucl` (`600` seqs)、`neg_refseq_prot` (`261,188` seqs) 全部返回退出码 `0`。

---

## 9. 标准测试流程与 `v1` 基准测试集构建（`src/phage_discovery/benchmark/`）

### 9.1 基准集构造与隔离机制（源自 `F:\Phage data\benchmarks\v1\benchmark_manifest.json`）

- **负样本宿主分层隔离**：将 600 条负样本按类别确定性划分 `train=420 / val=90 / test=90`，保证同一个细菌基因组/质粒不会跨越训练与评测边界；提取背景区段时严格扣除 `prophage_masks`（1,667 处前噬菌体区间）。
- **多尺度窗口基准 (`val` / `test`)**：每个 split `4,000` 个平衡窗口（正负 `2,000 : 2,000`，覆盖 `5000 bp`、`3000 bp`、`1000 bp` 三种尺度及短基因组完整体）。
- **细菌嵌合前噬菌体基准 (`val` / `test`)**：每个 split `75` 条（`150~300 kb` 原生干净细菌主干），总计 `val=19.448 Mb`、`test=20.862 Mb`（各含 `75` 个真值前噬菌体，覆盖 `intact_single` 27 条、`degraded_fragment` 18 条、`multi_tandem` 15 条以及 `pure_negative_host` 15 条）。

### 9.2 零训练组成偏倚基线实测（`Baseline_4mer_GC_Anomaly` on `test`）

| 维度 | 核心指标实测值 |
| :--- | :--- |
| 多尺度窗口综合 (`n=4000`) | `AUROC=0.5073`, `AUPRC=0.5240`, `Recall@0.5%FPR=0.0035` |
| 细菌嵌合体定位 (`IoU >= 0.5`) | `Precision=0.3067`, `Recall=0.6667`, `F1=0.4202`（`TP=50, FP=113, FN=25`） |
| 严格边界定位 (`IoU >= 0.8`) | `F1=0.3529`, `Breakpoint MAE=2319.7 bp`（中位 `1200.5 bp`） |
| 纯阴性细菌误报率 / 吞吐速度 | **`10.9536 FP/Mb`**（`3.287 Mb` 产生 `36` 假阳性），`5 Mb` 耗时 **`0.859 s`** |

---

## 10. 专家-教师-学生小样本实测闭环（`smoke_v1` -> `v1 test` 基准对比）

### 10.1 训练方案完善与防泄露落地
1. **统一无注释来源捷径特征（`src/phage_discovery/features/window_features.py`）**：训练、验证与推理一律只从原始 DNA 经 `Pyrodigal (meta=True)` 统一预测基因，统计 136 维 4-mer + GC/组成 + 相对宿主上下文偏离（`ctx_gc_diff`, `ctx_kmer_cosdist`）+ 9 维操纵子结构（`strand_switch_rate` 为首号增益特征 `71.185`）。
2. **三类异构专家与 OOF 知识蒸馏**：实现了 `Expert A (XGBoost-CUDA)`、`Expert B (1D 膨胀残差 CNN)`、`Expert C (Pyrodigal ORF 语法 Transformer)` 与 `Student (双流轻量网络 + 5折 GroupKFold 按 contig 防泄题 OOF 软标签蒸馏 + Focal Loss + ONNX 导出)`。
3. **WSL 教师验证**：实测确认 `CheckV v1.0.3 + checkv-db-v1.5`、`Pharokka`、`Phold v1.2.6` 在 WSL2 中可直接运行（注：`CheckV` 需暂存至无空格 `/tmp` 目录以兼容其内部 `prodigal-gv` 调用）；`virsorter2` conda 环境当前缺失。

### 10.2 `smoke_v1`（`8,360` 训练窗口）在冻结 `v1 test` 基准上的横向实测榜单

| 模型 / 方案 | Window AUROC | Window AUPRC | Recall @0.5%FPR | 区域 F1 (IoU>=0.5) | 区域 F1 (IoU>=0.8) | 断点 MAE (bp) | 纯阴性 FP/Mb | 显存 / 大小 / 5Mb 耗时 |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| `Baseline_4mer_GC_Anomaly`（零训练） | `0.5073` | `0.5240` | `0.0035` | `0.4202` | `0.3529` | `2319.7` | `10.9536` | CPU / 无参数 / `0.859 s` |
| `Expert A` (`XGBoost-CUDA`) | `0.9613` | `0.9641` | `0.5025` | `0.8415` | `0.7561` | `2741.7` | `1.2171` | CUDA / `XGB JSON` |
| `Expert B` (`1D Dilated ResCNN`) | `0.8955` | `0.9073` | `0.3555` | `0.5209` | `0.3070` | `7867.3` | `6.9981` | `339.9 MB` VRAM（训练 `40.27 s`） |
| `Expert C` (`ORF Transformer`) | `0.9018` | `0.8887` | `0.1525` | `0.8608` | `0.5949` | `4918.7` | `0.9128` | `47.0 MB` VRAM（训练 `18.88 s`） |
| `Ensemble` (`0.7*A + 0.2*B + 0.1*C`) | **`0.9638`** | **`0.9655`** | `0.5130` | `0.8701` | `0.8312` | `2218.0` | **`0.6085`** | 融合推理 |
| **`Student_Distilled_DualStream`** | `0.9550` | `0.9588` | **`0.5715`** | **`0.8889`** | **`0.8627`** | **`2037.7`** | **`0.6085`** | `86.9 MB` VRAM / **ONNX `0.289 MB`** / **`0.311 s`**（前向） |
| *CheckV Teacher*（9 条 `test` 抽样 `2.506 Mb`） | — | — | — | `0.9474` | `0.7368` | `2634.2`（中位 `808.0`） | `0.0` | WSL 重型教师，9 条耗时 `67.95 s` |

---

## 11. 高精度与知识丰富度升级闭环（`full_v2` + CheckV 真前噬菌体挖矿 + 200 bp 边界精修）

### 11.1 清理过期中间产物与训练样本全量扩容
1. **清理过期小样本产物**：清理 `F:\Phage data\{models,training,teachers}\smoke_v1` 过期模型与临时特征，完整保留冻结 `F:\Phage data\benchmarks\v1` 作为公平纵向对照基准。
2. **WSL CheckV 真实前噬菌体挖矿（严格限 `train` 宿主）**：`src/phage_discovery/teachers/prophage_miner.py` 仅扫描 `train` 分片 `42` 条细菌染色体上的 `526` 个可疑区段，经 WSL `CheckV v1.0.3` 鉴定并过滤，精准回收 **`139` 个真实自然整合前噬菌体（`139` 条嵌合切片）** 与 **`353` 条高难细菌假阳性易混淆区段（Hard Negatives）**，保存至 `F:\Phage data\teachers\train_prophage_mined\`（`val`/`test` 零泄露）。
3. **全量 `full_v2` 训练集规模（`86,507` 总行）**：经 `negative_splits.json` 与 `v1` 100% 一致性断言验证后，生成 `36,000` 多尺度窗口（`18,000` 正 + `18,000` 负）+ `300` 条细菌嵌合长序列 + `60` 条纯阴性细菌对照（共 `37,912` 滑窗）+ CheckV 真实前噬菌体/难负样本切片（`12,595` 滑窗），剔除 `-1` 模糊过渡窗后有效二分类样本 **`85,502` 行**，并保留 **`1,005` 个真实交界过渡滑窗** 专门用于 `200 bp` 亚窗口边界分割头监督。

### 11.2 `v2` 特征工程与模型/解码架构升级
1. **特征与亚窗口标签升级 (`window_features.py`, `feature_dataset.py`)**：从 153 维扩充至 **`185` 维**，新增密码子第一/二/三位 GC 偏倚（`gc1/gc2/gc3/bias`）、22 维 Pyrodigal 编码蛋白氨基酸频率与疏水/带电理化谱（`aa_*`，其中 `aa_L` 在全量 `Expert A` 特征增益中位列第 1，达 `213.62`）、左右 `5 kb` 侧翼阶跃变化特征，并同步输出 `25-bin`（每格 `200 bp`）`sub_mask` 掩码矩阵。
2. **200 bp 亚窗口精细边界解码器 (`decode_subwindow_probs_to_regions`)**：先由窗口级双阈值滞回扫描锚定高置信病毒岛，再融合重叠滑窗投影的 `200 bp` 网格分割概率并执行三点平滑与断点精修（`sub_threshold` 在 `val` 上联合网格搜索确定）。
3. **模型与学生蒸馏容量提升**：
   - `Expert A (XGBoost-CUDA)`: `max_depth=7`, `n_estimators=3000`, `learning_rate=0.04`, 185 维特征；
   - `Expert B (1D ResNet + BiGRU + SubSeg)`: 升级 128 通道 + 2 层双向 GRU + `25-bin` 分割多任务头（`1,350,274` 参数）；
   - `Expert C (ORF Synteny Transformer v2)`: 扩展至 `MAX_ORFS_PER_WIN=36`、`d_model=128`、3 层 Pre-LN 编码器与可学习注意力池化（`554,626` 参数）；
   - `Student Pro (Dual-Stream Distilled + 200 bp SubSeg)`: 保留流式与 ONNX 部署形态（`317,842` 参数，ONNX 体积 **`1.234 MB`**），结合 Focal Loss、5 折防泄题 GroupKFold OOF 软蒸馏与 `BCE + Dice` 200 bp 亚窗口边界分割联合训练。

### 11.3 `full_v2` 在冻结 `v1 test` 基准上的最新实测榜单

| 模型 / 方案 | Window AUROC | Window AUPRC | Recall @0.5%FPR | 区域 F1 (IoU>=0.5) | 区域 F1 (IoU>=0.8) | 断点 MAE / 中位误差 (bp) | 纯阴性 FP/Mb | 显存 / 大小 / 5Mb 耗时 |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| `Baseline_4mer_GC_Anomaly`（零训练） | `0.5073` | `0.5240` | `0.0035` | `0.4202` | `0.3529` | `2319.7 / 1200.5` | `10.9536` | CPU / 无参数 / `0.859 s` |
| `smoke_v1` `Student`（小样本 `8,360` 行） | `0.9550` | `0.9588` | `0.5715` | `0.8889` | `0.8627` | `2037.7 / —` | `0.6085` | `86.9 MB` / ONNX `0.289 MB` / `0.311 s` |
| `full_v2` `Expert A` (`XGBoost-CUDA`, 185d) | **`0.9906`** | **`0.9914`** | **`0.8450`** | `0.9677` (`R=1.00`) | `0.9290` | `1795.8 / 1460.0` | **`0.3043`** | CUDA 训练 `14.94 s` |
| `full_v2` `Expert B` (`ResBiGRU + SubSeg`) | `0.9634` | `0.9628` | `0.3890` | `0.7412` | `0.6706` | `2027.0 / 790.0` | `1.2171` | `1059.9 MB` VRAM / 训练 `813.4 s` |
| `full_v2` `Expert C` (`ORF Transformer v2`) | `0.9533` | `0.9508` | `0.4065` | `0.8810` | `0.7976` | `3428.8 / 1692.5` | **`0.3043`** | `157.9 MB` VRAM / 训练 `116.6 s` |
| `full_v2` `Ensemble` (`0.8*A + 0.2*B`) | `0.9890` | `0.9890` | `0.6760` | `0.9359` | `0.8846` | `1584.2 / 822.0` | **`0.3043`** | `val F1=0.9933, FP/Mb=0.0` |
| **`full_v2` `Student Pro` (ONNX)** | `0.9905` | `0.9911` | `0.8360` | **`0.9740`** (`75/75` 全检出, `P=0.9494`) | **`0.9740`** (`mean_iou=0.9655`) | **`757.3 / 670.0`** | **`0.3043`** | `193.1 MB` VRAM / **ONNX `1.234 MB`** / **`0.348 s`**（`val F1=0.9934, FP/Mb=0.0`） |

> **关键进展说明**：`Student Pro` 在冻结 `v1 test` 基准上实现 **75 / 75 真实前噬菌体 100% 检出**且 **全部达到 `IoU >= 0.8` 严格标准**（`F1(IoU>=0.5) = F1(IoU>=0.8) = 0.9740`），平均断点误差从 `2037.7 bp` 骤降至 **`757.3 bp`**（中位 `670.0 bp`），纯阴性细菌假阳性率压低至 **`0.3043 FP/Mb`**（较无训练基线下降 **36x**）。

### 11.4 能力上下限、同库对比与完全陌生细菌全基因组盲测评估

1. **尺度、类群与错误解剖（`v1 test` 细分）**：
   - **长度下限**：`5,000 bp` 窗口 `AUROC=0.9973 / Recall@0.5%FPR=0.9382`；`3,000 bp` `AUROC=0.9933 / Recall@0.5%FPR=0.8721`；`<=1,000 bp` 碎片骤降至 `AUROC=0.9192 / Recall@0.5%FPR=0.4512`（受单基因片段信息熵下限约束）。
   - **分类与负样本盲区**：`Caudoviricetes` (`TPR=0.9688`) 与 `Tectiviridae` (`1.0000`) 极强，`Microviridae` 微小噬菌体相对较弱 (`0.8500`)；短片段最易混淆 `non_phage_virus`（`<=1kb FPR=0.2653`，依托 `5kb` + `seed=0.90` 压至 `0.0059`）。
   - **表面 `4` 个测试集“假阳性”反转**：经 50 万条噬菌体蛋白库 (`phage_refseq_prot`) `BLASTp` 与 `CheckV` 复核，`4/4` 均命中高置信整合酶/溶菌酶/DNA引发酶/切除酶等噬菌体蛋白（其中 `test_CHIM_0033 [0:12400]` 与 `test_PURE_NEG_0007 [223369:244777]` 被 CheckV 独立认证为宿主体内漏掩蔽隐蔽原噬菌体）。
2. **全量 `v1 test`（`75` 条 `20.862 Mb`）正面对比 `CheckV v1.0.3` (`checkv-db-v1.5`)**：
   - `CheckV`：`F1(IoU>=0.5)=0.9167`（`66/75`, `Recall=0.88`）、`F1(IoU>=0.8)=0.7917`、`0.3043 FP/Mb`、耗时 `258.08 s`；
   - `CheckV` 在 `intact_single` 完整前噬菌体上中位边界极佳（`172.0 bp`, `MAE=611.4 bp` vs Student `830.4 bp`），但在 `degraded_fragment` 退化碎片上漏检 `1/3`（`Recall=0.6667`, `MAE=6727.2 bp`），而 `Student Pro` 在退化碎片上保持 `Recall=1.0000`、`F1=0.9730`、`MAE=601.2 bp`。
3. **4 株未见经典细菌全基因组零样本盲测（`F:\Phage data\benchmarks\unseen_real_genomes\`）**：
   - *Salmonella enterica* Typhimurium LT2 (`NC_003197.2`, `4.86 Mb`, `GC=52.22%`): 仅报 `4` 处（`0` 误报），精准全中 Fels-1 (`IoU=0.936`)、Gifsy-2 (`IoU=0.978`)、Gifsy-1 (`51/53 ORFs`, **CheckV 漏检**) 与 Fels-2 (`IoU=0.805`)；耗时特征 `20.35 s` + GPU `0.585 s`。
   - *Staphylococcus aureus* NCTC 8325 (`NC_007795.1`, `2.82 Mb`, `GC=32.87%`, 未见物种): 精准命中全部 3 个前噬菌体（`IoU=0.913~0.948`, `65/65`~`67/74 ORFs`），仅 1 处 `5.0 kb` 孤立转座酶假阳性（`0.35 FP/Mb`）；耗时 `3.94 s` + `0.425 s`。
   - *Escherichia coli* K-12 MG1655 (`NC_000913.3`, `4.64 Mb`, `GC=50.79%`): `CheckV` 报告 `0` 个；`Student Pro` 零误报精准抓出 `5` 个高度退化隐蔽前噬菌体（DLP12、e14、Rac、Qin、CPS-53，`13/16`~`28/36 ORFs` 命中），另有最碎化的微弱残片未达 `0.9` 阈值。
   - **分布外边界暴露 — *Streptomyces coelicolor* A3(2) (`NC_003888.3`, `8.67 Mb`, `GC=72.12%`)**: `CheckV` 报 `0` 个，而 `Student Pro` 报出 `95` 处（相当比例 `0/N` 无噬菌体蛋白命中）。根因定位：正样本库含 `478` 株高 GC ($\ge 66\%$, 最高 `72.64%`) 噬菌体，而负样本细菌染色体库最高仅 `69.30%`（缺少 $\ge 70\%$ 链霉菌/放线菌代表基因组及巨型次生代谢基因簇负样本），引发高 GC 域外分布漂移。







---

## 12. V3 零泄露扩容、难负样本挖矿、双阶段蛋白门控与真实收益/缺陷审计（2026-11-13）

为解决 `full_v2 Student Pro` 在高 GC 陌生基因组（如 `NC_003888.3` 链霉菌误报 `95` 处 / `10.9605/Mb`）、转座酶短岛（如金葡菌 `5 kb` 误报）以及极短非噬菌体病毒上的分布外泛化短板，本阶段完成了模块化双阶段推理引擎开发、零泄露扩容、两轮再训练实验与五路客观对照评测（产物归档于 `F:\Phage data\expansion_v3\`、`F:\Phage data\models\full_v3\` 与 `F:\Phage data\models\full_v3_1\`）。

### 12.1 模块化架构与核心测试结果

1. **`src/utils/phage_dataset/expansion_downloader.py`**：实现零泄露增量下载器（`collect_excluded_accessions` 汇总 `v1` 验证/测试正负样本及 4 株陌生检验基因组编号，`leakage_count = 0`；采用 3 线程 `ThreadPoolExecutor`、`request_timeout=75`、小批 `FASTA` 极速通道与 UTF-8 断点续传）。
2. **`src/phage_discovery/experts/expert_a_xgb.py` & `src/phage_discovery/student/distilled_student.py`**：扩展分片样本权重支持（`_load_weighted_train_split`、`part_weights`、`sample_weights`、`extra_sources`），完全兼容既有 `v2` 调用签名。
3. **`src/phage_discovery/inference/protein_gate.py` & `scanner.py`**：实现模块化双阶段推理引擎（`GenomeScanner`、`ProteinGateConfig`、`evaluate_regions_with_protein_gate`）。对一阶段候选区域采用 `Pyrodigal(meta=True)` 提取蛋白并在数据库目录作为 `cwd` 单批调用 `blastp`（规避 Windows 下 BLAST+ 空格路径内存映射错误），结合四级证据规则区分病毒 hallmark、未知噬菌体聚类、纯转座酶岛、通用代谢/重组酶基因与高 GC 无证据噪声。
4. **单元测试全量验证**：运行 `tests/test_protein_gate_and_scanner.py`、`tests/test_expansion_downloader.py` 等 8 个核心测试套件，合计 **`21 passed in 78.84s (0:01:18)`**（0 failed, 0 skipped）。

### 12.2 零泄露数据扩容与 V3 难负样本/前噬菌体挖矿

- **负样本扩容 (`F:\Phage data\expansion_v3\negative_ext`)**：共 `130` 条（高 GC 染色体 `13` 条、低 GC 染色体 `5` 条、古菌染色体 `4` 条，22 条染色体合计 `105.55 Mb`，GC 跨度 `0.2710–0.7312`，其中 `10` 条 GC >= `0.68`；另含质粒 `36` 条、非噬菌体病毒 `72` 条）。
- **罕见非有尾噬菌体扩容 (`F:\Phage data\expansion_v3\positive_rare_ext`)**：共 `140` 条（`Microviridae` `37`、`Inoviridae` `41`、`Tectiviridae` `41`、`Leviviricetes` `21`）。
- **高难度错题再挖掘 (`F:\Phage data\training\full_v3\features\`)**：用 `full_v2 Student Pro` 扫描上述 `105.55 Mb` 新染色体（耗时 `45.832 s`），捕获 `940` 个原始高分告警（合并为 `567` 条候选片段），再经 WSL `CheckV v1.0.3`（`432.16 s`）与本地 `BLASTp` 双核验（`394` 条无 CheckV 命中区中严格确认 `230` 条零 hallmark 片段），沉淀 `18` 个真实 `ext_mined` 前噬菌体与 `510` 条高难细菌难负样本，生成增量分片：`train_hard_neg.npz`（`5,142` 行）、`train_ext_rare.npz`（`2,310` 行）、`train_ext_windows.npz`（`1,710` 行）、`train_ext_mined.npz`（`14,533` 行）。

### 12.3 两轮再训练对比与五路客观基准审计（收益 vs 缺陷）

- **首轮过压制实验 (`full_v3`, 仅诊断保留)**：训练样本 `96,545` 行（漏加载旧版 `F:\Phage data\teachers\train_prophage_mined\mined_chimeras.fna` 且过重设置 `hard_neg=1.5`、`ext_mined=1.3`）。结果虽将链霉菌误报压至 `0`，但造成 *S. enterica* LT2 丢失 `Gifsy-1`（`4 -> 3`）、*E. coli* K-12 从 `5` 降至 `3`。
- **第二轮平衡训练 (`full_v3_1`)**：补回 `mined`（`w=1.1`）并将权重调整为 `windows=1.0, chimeras=1.0, mined=1.1, hard_neg=0.65, ext_rare=1.4, ext_windows=1.0, ext_mined=0.7`（共 `108,885` 行，`Student Pro v3.1` RTX 4070 CUDA 训练 `566.43 s`，峰值显存 `193.6 MB`，导出 ONNX `1.234 MB`）。

**冻结 `v1 test` 基准四路对照（来自 `F:\Phage data\models\full_v3_1\v3_final_comparison.json`）：**

| 方案 | 推理 / 门控耗时 | Window AUROC / AUPRC | Recall@0.5%FPR | Microviridae TPR | 非噬菌体病毒 FPR (`<=1kb`) | 嵌合 TP/FP/FN | F1 (IoU>=0.5 / 0.8) | 断点 MAE | 纯阴性 FP/Mb |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `v2_raw` | `1.491s / 0s` | `0.9905 / 0.9911` | **`0.8360`** | `0.8500` | `0.1471 (0.2653)` | `75 / 4 / 0` | **`0.9740 / 0.9740`** | `757.3 bp` | `0.3043` (`1` FP) |
| `v3_round1_raw` | `1.122s / 0s` | `0.9878 / 0.9883` | `0.7550` | `0.9000` | `0.1242 (0.2245)` | `75 / 3 / 0` | `0.9804 / 0.9673` | **`717.4 bp`** | `0.3043` (`1` FP) |
| `v3_1_raw` | `1.132s / 0s` | `0.9893 / 0.9895` | `0.7295` | **`0.9000`** | **`0.0915 (0.1633)`** | `75 / 5 / 0` | `0.9677 / 0.9548` | `740.8 bp` | `0.6085` (`2` FP) |
| `v3_1_gate` | `1.088s / 282.018s` | `0.9893 / 0.9895` | `0.7295` | **`0.9000`** | **`0.0915 (0.1633)`** | `75 / 4 / 0` | **`0.9740` / `0.9610`** | `740.8 bp` | **`0.3043`** (`1` FP) |

**4 株完全陌生真实细菌染色体五路对照：**

| 基因组 | `v2_raw` | `v2_gate` | `v3_round1_raw` | `v3_1_raw` | `v3_1_gate` | 核对结论 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `NC_003888.3` 链霉菌 (`8.668 Mb`, GC `72.12%`) | `95` (`10.9605/Mb`) | `30` (`3.4612/Mb`, `gate=99.141s`, 拒 65) | `0` (`0.0/Mb`) | **`0` (`0.0/Mb`)** | **`0` (`0.0/Mb`, `gate=0.0s`)** | V3 模型本体彻底根除高 GC 假阳性，而仅靠 `v2+gate` 仍残留 `30` 个 |
| `NC_003197.2` 鼠伤寒沙门氏菌 LT2 (`4.857 Mb`, GC `52.22%`) | `4` | `4` (`hallmark_confirmed: 4`) | `3` (漏 Gifsy-1) | **`4`** | **`4` (`hallmark_confirmed: 4`, `gate=18.909s`)** | `v3_1` 成功恢复 LT2 全部 4 个典型前噬菌体 |
| `NC_007795.1` 金葡菌 NCTC 8325 (`2.821 Mb`, GC `32.87%`) | `4` (含 1 转座酶误报) | **`3`** (`rejected_transposase_dom: 1`) | `3` | `4` (含 `1897800..1902400` 转座酶误报) | **`3` (`rejected_transposase_dom: 1`, `gate=17.987s`)** | 蛋白门控精准拦截转座酶假阳性并保留全部 3 个真前噬菌体 |
| `NC_000913.3` 大肠杆菌 K-12 MG1655 (`4.642 Mb`, GC `50.79%`) | **`5`** | **`5` (`hallmark_confirmed: 5`)** | `3` | `3` (`hallmark_confirmed: 3`) | `3` (`hallmark_confirmed: 3`, `gate=4.324s`) | **回退缺陷**：`v3_1` 漏检 `1412400..1435600` 与 `2467600..2477400` 2 处隐性退化前噬菌体 |

### 12.4 实测缺陷与后续权衡建议

1. **高保守性导致的退化隐性区段召回回退**：在加入跨门极端宿主难负样本后，`v3_1` 的验证集最优 `seed_threshold` 从 `0.90` 抬升至 `0.95`，导致 K-12 两处高度退化/短小前噬菌体漏检，`v1 test` 极低假阳性阈值区召回（`Recall@0.5%FPR`）从 `0.8360` 降至 `0.7295`，常规细菌短片段误报率（`bacterial_chromosome_le1kb`）从 `0.0932` 升至 `0.1366`。
2. **`ProteinGate` 的时间开销与互补局限**：`ProteinGate` 在 `4` 株细菌（`3~4` 个候选区）上增加 `4.3~18.9 s` 开销，在 `v1 test`（`80` 个候选区）上耗时 `282.018 s`；且在 `v2 + ProteinGate` 单独应用于链霉菌时，仍有 `30` 个含噬菌体同源辅助基因（AMG/重组酶/转运蛋白）的高 GC 假阳性无法仅靠序列门控剔除，证明 **模型本体对极端宿主分布的学习（`v3_1`）与蛋白门控对普通 GC 转座酶的拦截（`ProteinGate`）二者缺一不可**。
3. **现阶段选型策略**：对高 GC / 放线菌 / 极端未知细菌环境，启用 **`Student Pro v3.1 + ProteinGate`**（高置信低误报，链霉菌 `0` 误报、金葡菌 `3/3`、LT2 `4/4`、`v1 test F1=0.9740`）；若优先追求常规肠杆菌科退化残片极端覆盖率，可提供 `v2_gate` 作为高敏感备选配置，或通过下调 `v3.1` 推理期阈值（`seed_threshold=0.90`）并依托 `ProteinGate` 兜底筛选。
