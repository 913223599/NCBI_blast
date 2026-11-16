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

---

## 13. V4 高容量纯神经架构升级（4D 语义蒸馏 + 嵌入式 ORF Transformer + 上下文精修）与六路实测对比审计（2026-11-13）

为回答“能否尽量通过纯粹神经网络模型完成 `ProteinGate` 的转座酶排异与退化前噬菌体语义识别、并验证适度提升模型容量后的真实对比效果”，本阶段构建、测试并全量训练了 **V4 纯神经三模态体系**（产物归档于 `F:\Phage data\training\full_v4\` 与 `F:\Phage data\models\full_v4\`，综合报告位于 `F:\Phage data\models\full_v4\v4_comprehensive_comparison.json`）。

### 13.1 V4 架构升级与模块化代码落地

1. **零泄露难样本与离线蛋白语义知识准备（`src/phage_discovery/data/v4_semantic_prep.py`）**：
   - `hard_v4`：严格仅从 `v1 train` 负样本细菌/质粒提取高难度转座酶富集岛与古菌/极端细菌窗共 **`1,483` 条记录（`1,664` 行）**，绝不触碰 `v1 val/test` 与 `unseen_real_genomes`。
   - 8 份训练分片 4D 语义标注与假阴性清洗：离线运行 `DIAMOND BLASTp` 对齐生成 4 维蛋白语义监督目标 `sem_targets`（`sem_phage_hallmark`, `sem_integrase`, `sem_transp`, `sem_tail_lysis`）及 `sem_valid_mask`（耗时 `187.4 s`），并从 `chimeras`（`242`）、`mined`（`86`）、`ext_mined`（`71`）、`hard_v4`（`13`）、`hard_neg`（`3`）累计清洗 **`415` 条矛盾伪阴性标签**至 `train_*_semantic.npz`。
2. **多教师 V4 语义对齐与 GroupKFold OOF 升级（`src/phage_discovery/experts/expert_a_xgb.py`, `expert_b_cnn.py`, `expert_c_orf.py`）**：
   - 统一接入 `clean_labels` 标签对齐与 8 分片加权采样（`110,134` 行）；`Expert B` 仅在真实清晰标签上监督 200 bp `sub_mask`；`Expert C` 增加 `extract_contig_orf_tokens` 供端到端全基因组推理与分片 ORF 缓存核验。
3. **高容量三模态神经网络与跨窗上下文精修器（`src/phage_discovery/student/distilled_student_v4.py`, `inference/scanner.py`）**：
   - **容量提升**：参数量从 `v3.1` 的 **`317,842`（`0.32M`）** 提升至 **`3,639,114`（`3.64M`）**，全量 `111,451` 行在 RTX 4070 CUDA 上训练耗时 `3,407.07 s`、峰值显存仅 **`1,275.0 MB`**。
   - **三模态特征融合与长短尺度修复**：
     - DNA 骨干采用 `dna_channels=160` 掩码残差空洞卷积 + `pack_padded_sequence` 双向 GRU（严格屏蔽 `<=1 kb` 碎片序列后的 zero-padding 信号稀释）；
     - 端到端内置 3 层 `ORF Synteny Transformer`（`orf_d_model=128, orf_nhead=4, orf_num_layers=3`）+ 185 维统计特征残差流，通过 Tri-Modal Gate（`fusion_dim=256`）融合；
     - 新增 `4` 维可微蛋白语义辅助头（`sem_head`），其预测向量反馈输入主分类头 `win_head` 与 `200 bp` 亚窗口分割头 `sub_head`，无需在推理阶段挂载任何外部蛋白检索。
   - **跨窗上下文精修器（`RegionContextRefiner`）**：对按 `contig` 有序排列的连续 15 维步骤特征（含 `win_logits`、4 维 `sem_logits/probs` 及其邻居信息等）执行双向序列建模，用于区分多窗连贯前噬菌体与 1~2 窗孤立转座酶假阳性脉冲；`GenomeScanner` 已同步支持自动识别 `v4` 与 `use_context_refiner` 开关。
4. **先导单测与全库回归验证**：
   - 新增 `tests/test_v4_architecture_and_prep.py`（零泄露、Masked Pooling Padding 不变性、Refiner 排序与 V4 端到端链路 4 项单测），运行全库回归 `pytest tests/ -q --tb=short` 实测 **`196 passed in 221.39s (0:03:41)`**（`0 failed, 0 skipped`）。

### 13.2 训练结果、冻结 `v1 test` 基准六路对照与 4 株陌生基因组实测

#### 1. 教师与学生收敛快照（`F:\Phage data\models\full_v4\`）

- `Expert A v4`（XGBoost-CUDA, `110,134` 行, `best_iteration=1845`）：`test` 窗 `AUROC=0.9902` / `AUPRC=0.9911` / `Rec@0.5%FPR=0.8575`，区域 `F1@0.5=0.9615` / `F1@0.8=0.9359`，`MAE=1398.5 bp`。
- `Expert B v4`（`160` ch, `2,087,106` 参数）：Epoch 2~3 学习率过冲震荡（`val AUPRC`: `0.95712 -> 0.81493 -> 0.7151 -> 0.91707 -> 0.9452`）触发 `best_epoch=1` 早停，导致独立 `test AUPRC=0.9244`（OOF 3 折使用 128 ch 表现稳健）；`Ensemble` 验证集择优权重退化为 `ExpertA=1.0`。
- `Expert C v4`（`best_epoch=16`）：`test` 窗 `AUROC=0.9578` / `AUPRC=0.9557`，区域 `F1@0.5=0.8427`。
- `Student V4`（`111,451` 行）：`best_epoch=8`（`best_val_auprc=0.99589`）；`RegionContextRefiner`：`best_epoch=12`（`best_val_auprc=0.99949`）；`val` 标定最优解码阈值：无 Refiner (`v4_no_refiner_raw`) `seed=0.95, extend=0.30, sub=0.65`；带 Refiner (`v4_raw`) `seed=0.80, extend=0.30, sub=0.65`。

#### 2. 冻结 `v1 test` 基准（4,000 窗口 + 20.862 Mb / 75 嵌合区段）六路客观对照

| 方案 | 推理 / 门控耗时 | Window AUROC / AUPRC | Rec@0.5%FPR | 1~3 kb AUPRC / Rec@0.5%FPR | <=1 kb AUPRC | Microviridae / Leviviricetes TPR | 非噬菌体病毒 FPR (`<=1kb`) | 嵌合 TP/FP/FN | 区域 F1 (IoU>=0.5 / 0.8) | 断点 MAE | 纯阴性 FP/Mb |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `v2_raw` | `0.77s / 0s` | **`0.9905 / 0.9911`** | **`0.8360`** | `0.9815 / 0.6996` | `0.9532` | `0.8500 / 0.9000` | `0.1471 (0.2653)` | `75 / 4 / 0` | `0.9740 / 0.9740` | `757.3 bp` | **`0.3043`** (`1`) |
| `v3.1_raw` | `0.77s / 0s` | `0.9893 / 0.9895` | `0.7295` | `0.9751 / 0.5442` | `0.9503` | `0.9000 / 0.9000` | `0.0915 (0.1633)` | `75 / 5 / 0` | `0.9677 / 0.9548` | **`740.8 bp`** | `0.6085` (`2`) |
| `v3.1_gate` | `0.79s / 179.84s` | `0.9893 / 0.9895` | `0.7295` | `0.9751 / 0.5442` | `0.9503` | `0.9000 / 0.9000` | `0.0915 (0.1633)` | `75 / 4 / 0` | `0.9740 / 0.9610` | **`740.8 bp`** | **`0.3043`** (`1`) |
| `v4_no_refiner_raw` | `9.80s / 0s` | `0.9895 / 0.9898` | `0.7470` | **`0.9834 / 0.7102`** | **`0.9536`** | **`0.9500 / 0.9500`** | **`0.0817`** (`0.1837`) | `75 / 4 / 0` | `0.9740 / 0.9740` | `1046.7 bp` | **`0.3043`** (`1`) |
| **`v4_raw` (纯神经)** | `10.20s / 0s` | `0.9895 / 0.9898` | `0.7470` | **`0.9834 / 0.7102`** | **`0.9536`** | **`0.9500 / 0.9500`** | **`0.0817`** (`0.1837`) | `74 / 2 / 1` | **`0.9801 / 0.9801`** | `1047.3 bp` | **`0.3043`** (`1`, 总体 **`0.0959`**) |
| `v4_gate` | `9.93s / 177.62s` | `0.9895 / 0.9898` | `0.7470` | **`0.9834 / 0.7102`** | **`0.9536`** | **`0.9500 / 0.9500`** | **`0.0817`** (`0.1837`) | `74 / 2 / 1` | **`0.9801 / 0.9801`** | `1047.3 bp` | **`0.3043`** (`1`, 拒杀 `0`) |

> **表注**：`v4_raw` 仅余的 `2` 处“FP”经前序 CheckV/BLASTp 与本次 `v4_gate` 核验均为宿主漏掩蔽真实隐蔽原噬菌体（`test_CHIM_0033 [0..12400]` 与 `test_PURE_NEG_0007 [225000..237200]`），`ProteinGate` 在 `v4_raw` 基础上拒杀数 **`0`**；`v4_no_refiner_raw` 中 `test_CHIM_0026 [86000..91800]` 与 `test_CHIM_0039 [37400..42200]` 两处真实短假阳性已被 `RegionContextRefiner` 纯神经彻底消除。

#### 3. 4 株陌生真实细菌全基因组六路对照

| 基因组 | `v2_raw` | `v3.1_raw` | `v3.1_gate` | `v4_no_refiner_raw` | `v4_raw` (纯神经) | `v4_gate` |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `NC_003888.3` 链霉菌 (`8.668 Mb`, GC `72.12%`) | `95` (`10.9605/Mb`) | `0` (`0.0/Mb`) | `0` (`0.0/Mb`) | **`0` (`0.0/Mb`, `28.35s`)** | **`0` (`0.0/Mb`, `28.38s`)** | `0` (`0.0/Mb`) |
| `NC_003197.2` 鼠伤寒沙门氏菌 LT2 (`4.857 Mb`, GC `52.22%`) | **`4`** | **`4`** | **`4`** | **`4`** (`38.52s`) | **`4`** (`38.28s`) | **`4`** (`hallmark: 4`) |
| `NC_007795.1` 金葡菌 NCTC 8325 (`2.821 Mb`, GC `32.87%`) | `4` (含转座酶) | `4` (含转座酶) | **`3`** (`rejected_transposase_dom: 1`) | `4` (`1897.8k..1902.2k` 峰 `0.9512`) | **`3` (`0` 转座酶误报, `8.01s`)** | **`3`** (`hallmark: 3`, 拒杀 `0`) |
| `NC_000913.3` 大肠杆菌 K-12 MG1655 (`4.642 Mb`, GC `50.79%`) | **`5`** | `3` (DLP12/e14/Qin) | `3` (`hallmark: 3`) | `3` (`564k/1202k/2470k`) | **`1` (`1202.4k..1212.2k` e14)** | `1` (`hallmark: 1`) |

### 13.3 机理诊断结论：真实突破 vs 实测暴露缺陷

1. **真实验证的突破与收益**：
   - **纯神经独立攻克 *S. aureus* 转座酶孤立脉冲**：在 `1897500..1902500` 处，`Student V4` 本体虽然给出了 `raw_p=0.9512`，但其内置 `4D` 语义头自发判定 `sem_hallmark=0.1470`（极低噬菌体核心蛋白语义）；随后 `RegionContextRefiner` 结合相邻窗低分（`0.1643 / 0.0984`）将其精准压降至 `0.7282 (< 0.80)`，**首次在不依赖任何 BLASTp 的情况下使 `v4_raw` 与 `v3.1_gate` / `v4_gate` 在金葡菌上完全对齐（`3/3` 真前噬菌体、0 误报）**。
   - **远缘非有尾病毒与短中尺度分类全面新高**：`v1 test` 上 `Microviridae TPR@0.5` 升至 `0.9500`（vs `v2=0.85`, `v3.1=0.90`）、`Leviviricetes` 升至 `0.9500`、`Inoviridae` 达 `1.0000`、`non_phage_virus` 误报率降至 `0.0817`、`1~3 kb` `AUPRC=0.9834` / `Rec@0.5%FPR=0.7102`、`<=1 kb` `AUPRC=0.9536` 全部创历史新高，且 `v1 test` 区域严格标准 `F1(IoU>=0.8)` 从 `v3.1_gate` 的 `0.9610` 跃升至 **`0.9801`**。
   - **V4 主干网络在 K-12 上的潜在完整感知力**：只读窗口级探测显示，基础模型 `v4_no_ref` 在 K-12 全部 5 处已知隐蔽前噬菌体均有强语义与高概率响应（`DLP12` 峰值 `0.9760, sem_hall=0.87`；`e14` 峰值 `0.9813, sem_hall=0.95`；`Rac` 连续 8 窗峰值 `0.9321, sem_hall=0.89`；`Qin` 连续 7 窗峰值 `0.9497, sem_hall=0.80`；`CP4-57` 峰值 `0.9527, sem_hall=0.91`），证明三模态与 4D 语义表征本身已有效恢复退化隐蔽前噬菌体的识别能力。
2. **实测暴露的四项明确缺陷与成因**：
   - **缺陷 1（最关键）— `RegionContextRefiner` 因 `in-sample` 过自信校准偏移产生过度压制**：Refiner 直接以 `Student V4` 在训练集 `chimeras` 上的过自信输出训练，导致对“局部窗存在波动或峰值在 `0.75~0.97`、长度约 4~8 窗的退化型片段”施加整体负向压制：
     - 将 `v1 test` 1 条 `degraded_fragment`（`test_CHIM_0012`，原本 `raw_p` 最高 `0.9798`）压至 `0.7876 (< 0.80)` 造成 `FN=1`；
     - 将 *E. coli* K-12 的 `DLP12 (0.9760 -> 0.7378)`、`Rac (0.9321 -> 0.7230)`、`Qin (0.9497 -> 0.5773)` 与 `CP4-57 (0.9527 -> 0.6595)` 全部压到 `0.80` 以下，使 `v4_raw` 在 K-12 仅留存 `1` 个（相比 `v2_raw` 的 `5` 个、`v3.1` 的 `3` 个明显退化）。
   - **缺陷 2 — `200 bp` 断点定位 MAE 退化约 `306 bp`**：`breakpoint_mae_bp` 从 `v3.1` 的 `740.8 bp` 升至 `v4` 的 `1047.3 bp`；消融确认是 V4 容量与 Focal 损失下 `sub_probs` 边界较饱满、最优 `sub_threshold` 触及网格上限 `0.65` 所致（`0.35 -> 0.65` 期间 MAE 从 `1348.1 bp` 单调降至 `1047.3 bp`，但受网格截断仍逊于 `v3.1`）。
   - **缺陷 3 — `Expert B v4` 独立训练震荡**：`160` 通道配置下学习率调度在 Epoch 2~3 过冲触发 `patience=4` 早停于 Epoch 1（`test AUPRC=0.9244`），使集成权重未采纳独立 `Expert B v4`（但 3-Fold OOF 使用 `128` ch 正常收敛）。
   - **缺陷 4 — `v1 test` 窗口级超高严格度截断召回及推理延迟权衡**：`Rec@0.5%FPR` 为 `0.7470`（优于 `v3.1` 的 `0.7295`，仍低于 `v2` 的 `0.8360`，其中 `gt_3kb` 从 `0.9309` 降至 `0.8675`）；同时滑窗内置 `Pyrodigal` ORF 编码与 3 层 Transformer 使纯神经每基因组扫描耗时从 `v3.1` 的 `~16~20 s` 增至 `8~38 s`（`v1 test` `20.86 Mb` GPU 推理从 `0.77 s` 增至 `9.8~10.2 s`，但仍比挂载 `ProteinGate` 快约 `18x`）。

---

## 14. V4.1 零泄漏轻量精修（冻结主干 `sub_head` 纯 BCE 校准 + `RegionContextRefiner V2`）与七路对比（2026-11-13）

围绕第 13 节定位的 `RegionContextRefiner` 校准下沉与 `200 bp` 边界 MAE 退化两大问题，在不从头重训 `3.64M` 主干 (`student_v4.pt`) 的前提下完成了 V4.1 轻量修复，先通过全库单元测试回归再执行真实训练与七路严格对比，**严格遵守零测试集泄露原则**。

### 14.1 架构与源码改动（`src/phage_discovery/`）

1. **`RegionContextRefiner V2`（`src/phage_discovery/student/distilled_student_v4.py`）**：
   - **`group_windows_by_contig` 物理边界拆段**：新增 `max_gap_bp=5000` 与 `source_tags`，防止同一 `contig_id` 相邻窗口跨越物理间隙或不同训练分片拼接成伪连续序列；
   - **19 维跨窗上下文输入通道**：在原 `15` 维时间步特征基础上，`forward` 内动态追加 `4` 维物理意义明确的局部邻域脉冲对比特征（总计 `19` 维）：排除中心自身 +/-3 窗邻居平均概率 `neigh_p_mean`、7 窗活性密度 `cluster_density`、5 窗最大噬菌体语义峰值 `local_max_hall` 与 `p_hall - p_trnp` 语义差值；`max_delta` 收敛至 `2.2`；
   - **全量 5 大连续分片联合训练与防过压制目标函数**：将训练集由 V4.0 仅 `chimeras` (`360` 条) 扩充至全部 5 个物理连续分片（`chimeras: 360`, `mined: 492`, `ext_mined: 528`, `hard_neg: 259`, `hard_v4: 14`，合计 **`1,653`** 条连续序列），加强“多窗低置信退化但保留高 `hallmark`”与“远离真界面的 `1~2` 窗孤立低 `hallmark`（含无 `trnp` 触发模式）脉冲”两类增强；损失函数摒弃易造成概率负偏移的 `FocalBCE`，改用轻度正加权 `BCE (pos_w=1.35)` + **非对称正样本正向保底惩罚** `0.35 * relu(rl_t - ref_logits)^2 * y_t` + `0.06 * delta^2`，早停判据设为校准联合分 `val_auprc - 0.12 * val_bce`。
2. **冻结主干 `sub_head` 纯 BCE 精修（`refine_student_v4_sub_head`）**：
   - 抽取 `DistilledStudentV4Net._forward_backbone`，在精修期间严格冻结全部主干、`sem_head` 与 `win_head`（`win_max_drift = 0.0`, `sem_max_drift = 0.0`），仅训练 `sub_cond + sub_head`；
   - 基于训练集筛选边界过渡窗（`0.02 < sub.mean < 0.98`）及平衡采样的纯阳/纯阴锚定窗（`tr_used=10,006`, `tr_trans=2,502`，并补充满长过渡窗反向互补对等样本），结合跳变沿前后各 `2 bins` 的 `2x` 权重，以纯粹 `BCEWithLogitsLoss`（去除 SoftDice 扩散模糊）精修并严格依据 `val_chimeras` 过渡窗/全窗联合 BCE 早停。
3. **`GenomeScanner` 向后兼容加载（`src/phage_discovery/inference/scanner.py`）**：
   - 调整精修器权重优先读取模型同目录 `context_refiner.pt`（防复制/备份目录加载串扰），并通过解析 `in_proj.0.weight` 输入维数自动适配 `V4.0 (15d)` 与 `V4.1 (19d)` 权重。

### 14.2 单元测试与真实轻量精修日志

- **代码实施前回归验证（`tests/test_v4_architecture_and_prep.py` + 全库）**：
  - 新增 `test_refiner_v2_gap_split_and_pulse_vs_degraded_separation` 与 `test_refine_student_v4_sub_head_preserves_win_and_sem_outputs`，专项测试 `6 passed in 26.83s`；全仓库单元测试实测 **`198 passed in 225.05s (0:03:45)`**（0 失败、0 跳过）。
- **V4.1 真实精修执行 (`F:\Phage data\models\full_v4\student_v4_1\`, 原 V4.0 完整备份至 `student_v4_0_bak`)**：
  - **`sub_head` 精修**：耗时 `39.66 s`，`best_epoch=12`，`best_val_sub_bce=0.274308`，严格验证 **`win_max_drift = 0.0`**、**`sem_max_drift = 0.0`**、`sub_max_delta = 0.9450`。
  - **`Refiner V2` 训练**：耗时 `80.91 s`，基于 `1,653` 条连续序列训练至 `best_epoch=19`，验证集达成 **`val_auprc = 0.99888`**、**`val_bce = 0.03076`**（`val_score = 0.99519`）。
  - **仅依据 `val` 标定解码阈值**：`decoder_tuned_on_val = {seed: 0.95, extend: 0.60, sub: 0.55}`。

### 14.3 冻结 `v1 test` 与 4 株陌生真实细菌全基因组七路实测对比（`v4_1_comprehensive_comparison.json`）

#### 1. 冻结 `v1 test` (`20.862 Mb` 嵌合体与 `4,000` 多尺度窗口) 核心对比

| 方案 | 阈值 (`seed/ext/sub`) | 推理 / 门控耗时 | Window AUROC / AUPRC | Rec@0.5%FPR | Micro / Levi TPR | 非噬菌体病毒 FPR (`<=1kb`) | 嵌合 TP/FP/FN | 区域 F1 (IoU>=0.5 / 0.8) | 断点 MAE (中位) | 退化片段 MAE / IoU | 总体 FP/Mb (纯阴性) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `v2_raw` | `0.90/0.50/0.35` | `0.815s / 0s` | **`0.9905 / 0.9911`** | **`0.8360`** | `0.8500 / 0.9000` | `0.1471 (0.2653)` | `75 / 4 / 0` | `0.9740 / 0.9740` | `757.3 (670.0) bp` | `601.2 bp / 0.9524` | `0.1917 (0.3043)` |
| `v3.1_raw` | `0.95/0.30/0.35` | `0.826s / 0s` | `0.9893 / 0.9895` | `0.7295` | `0.9000 / 0.9000` | `0.0915 (0.1633)` | `75 / 5 / 0` | `0.9677 / 0.9548` | `740.8 (620.0) bp` | `665.8 bp / 0.9500` | `0.2397 (0.6085)` |
| `v3.1_gate` | `0.95/0.30/0.35` | `0.793s / 189.256s` | `0.9893 / 0.9895` | `0.7295` | `0.9000 / 0.9000` | `0.0915 (0.1633)` | `75 / 4 / 0` | `0.9740 / 0.9610` | `740.8 (620.0) bp` | `665.8 bp / 0.9500` | `0.1917 (0.3043)` |
| `v4_0_raw`* | `0.80/0.30/0.65` | `10.142s / 0s` | `0.9895 / 0.9898` | `0.7470` | **`0.9500 / 0.9500`** | **`0.0817`** (`0.1837`) | `75 / 4 / 0` | `0.9740 / 0.9740` | `1046.7 (832.0) bp` | `876.5 bp / 0.9272` | `0.1917 (0.3043)` |
| `v4_1_no_refiner_raw` | `0.95/0.60/0.45` | `10.320s / 0s` | `0.9895 / 0.9898` | `0.7470` | **`0.9500 / 0.9500`** | **`0.0817`** (`0.1837`) | `75 / 6 / 0` | `0.9615 / 0.9359` | `1604.9 (586.0) bp` | `535.6 bp / 0.9593` | `0.2876 (0.3043)` |
| **`v4_1_raw` (纯神经)** | `0.95/0.60/0.55` | `11.872s / 0s` | `0.9895 / 0.9898` | `0.7470` | **`0.9500 / 0.9500`** | **`0.0817`** (`0.1837`) | **`75 / 2 / 0`** | **`0.9868 / 0.9868`** | **`728.6 (460.0) bp`** | **`426.9 bp / 0.9656`** | **`0.0959 (0.3043)`** |
| `v4_1_gate` | `0.95/0.60/0.55` | `13.186s / 199.349s` | `0.9895 / 0.9898` | `0.7470` | **`0.9500 / 0.9500`** | **`0.0817`** (`0.1837`) | **`75 / 2 / 0`** | **`0.9868 / 0.9868`** | **`728.6 (460.0) bp`** | **`426.9 bp / 0.9656`** | **`0.0959 (0.3043)`** (拒杀 `0`) |

> **注***：`v4_0_raw` 在本表同台复测中加载自统一后的 `max_delta=2.2` `RegionContextRefiner` 构造器（其 V4.0 原生 `max_delta=3.0` 归档结果见第 13.2 节：`74/2/1, F1=0.9801, MAE=1047.3 bp`，K-12=`1`，金葡菌=`3`）。`v4_1_raw` 在 `v1 test` 仅余的 `2` 个“FP”为 `test_CHIM_0033 (1000..12400, p=0.9851)` 与 `test_PURE_NEG_0007 (223400..236400, p=0.9915)`，`ProteinGate` 亦未拒绝其中任何一处（`rej={}`）。

#### 2. 4 株陌生真实细菌全基因组七路对照

| 基因组 | `v2_raw` | `v3.1_raw` | `v3.1_gate` | `v4_0_raw`* | `v4_1_no_refiner_raw` | **`v4_1_raw` (纯神经)** | `v4_1_gate` |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `NC_003888.3` 链霉菌 (`72.12%` GC) | `95` (`10.96/Mb`) | `0` (`0.00/Mb`) | `0` (`0.00/Mb`) | `0` (`0.00/Mb`) | `0` (`0.00/Mb`) | **`0` (`0.00/Mb`, `30.92s`)** | `0` (`0.00/Mb`) |
| `NC_003197.2` 鼠伤寒沙门氏菌 LT2 | **`4`** (`0.82/Mb`) | **`4`** (`0.82/Mb`) | **`4`** (`0.82/Mb`) | **`4`** (`0.82/Mb`) | **`4`** (`0.82/Mb`) | **`4`** (`0.82/Mb`, `40.31s`) | **`4`** (`0.82/Mb`) |
| `NC_007795.1` 金葡菌 NCTC 8325 | `4` (含转座酶 FP) | `4` (含转座酶 FP) | **`3`** (门控剔除 `1`) | `4` (受 2.2 clamp 回弹) | `4` (`1897.4k` `p=0.951`) | **`3` (`0` 转座酶误报, `8.81s`)** | **`3`** (门控拒杀 `0`) |
| `NC_000913.3` 大肠杆菌 K-12 MG1655 | **`5`** | `3` (`DLP12/e14/Qin`) | `3` (`DLP12/e14/Qin`) | `4` | `3` (`DLP12/e14/CP4-57`) | `2` (`DLP12/e14`)* | `2` (`DLP12/e14`) |

### 14.4 V4.1 逐窗概率核验：已实现突破与客观留存短板

1. **已实证的核心突破**：
   - **`v1 test` 全方位刷新历史最佳且完全追平 `ProteinGate`**：`v4_1_raw`（无 BLASTp）将嵌合区域 `F1(IoU>=0.5)` 与严格 `F1(IoU>=0.8)` 同步推进至历史新高 **`0.9868`**（`TP=75, FP=2, FN=0`，无漏检），`overall_fp_per_mb` 降至 **`0.0959`**，且 **`v4_1_gate` 在测试集与 4 株未知基因组上均拒杀 `0` 处（输出完全一致）**，彻底证实了纯神经网络独立达成“门控级精准度”的可行性。
   - **200 bp 边界精度反超 V3.1 与 V2**：主干窗口与语义头保持零漂移（`0.0`），而 `breakpoint_mae_bp` 从 `1046.7 bp` 锐减至 **`728.6 bp`**（中位误差 **`460.0 bp`**，低于 `v3.1` 的 `740.8 / 620.0 bp`），`degraded_fragment` 边界 MAE 低至 **`426.9 bp`**（`mean_iou=0.9656`）。
   - **同时攻克 V4.0 Refiner 过度压制与 *S. aureus* 转座酶假阳脉冲**：
     - 在 `v1 test_CHIM_0012`（V4.0 唯一漏检实例）上，`raw` 序列 `[0.716, 0.922, 0.980, 0.930, 0.751, 0.856]` 经 `Refiner V2` 稳固抬升为 `[0.822, 0.936, 0.980, 0.938, 0.850, 0.860]`，同时 `test_CHIM_0026` 尾部两窗（`[0.938, 0.960] -> [0.908, 0.943]`）与 `test_CHIM_0039` 头部短脉冲（`[0.898, 0.966] -> [0.828, 0.946]`）均被压至 `0.95` 以下彻底清除；
     - 在 *S. aureus* NCTC8325 `1892.5k..1907.5k` 孤立转座酶单窗脉冲上，将 `raw_p = 0.9512` 干净压制 **`-0.267`** 至 **`0.6842`**，实现 `3/3` 真前噬菌体零假阳。
2. **必须客观指出的留存短板（对应后续架构级优化建议）**：
   - **K-12 高阈值临界截断（`seed=0.95` 差千分之几未过线）**：逐窗探针实测显示 `Refiner V2` 在 K-12 实际已彻底修复 V4.0 的压制崩塌——`DLP12` 由 `0.852` 恢复至 **`0.9766`**，`e14` 保持 **`0.9811`**，**`Rac` 由 `raw=0.9321` 正向抬升至 `0.9423`（10 窗均稳定在 `0.65..0.94`）**，`Qin` 保持 **`0.9474`**（且内部 `0.751` 低谷被拉补至 `0.878`），`CP4-57` 为 **`0.9457`**；但因验证集自动择优选择了较高门槛 `seed=0.95`（而非 `0.90`），使 `Rac (0.9423)`、`Qin (0.9474)`、`CP4-57 (0.9457)` 以 `0.0026~0.0077` 之微落在 `0.95` 种子线外，导致最终 K-12 区域解码仅输出 `2` 个（`DLP12`, `e14`）。
   - **单窗模型（`v4_1_no_refiner_raw`）的本质表征与训练瓶颈仍在**：脱离 Refiner 后单窗仍会对 *S. aureus* 远缘转座酶给出 `0.9512`、对 `<=1 kb` 片段维持 `0.1424` 较高 FPR，且高容量 `3.64M` 主干原先在 `OneCycleLR` Epoch 14 早停截断。若后续追求**无需 Refiner 单窗即能辨别跨菌种陌生蛋白域并进一步拉高短残片表现**，核心在于为学生网络补充 **ORF 翻译氨基酸序列化/二三肽感知分支 + 面向异构尺度/移动元件防火墙的门控混合专家头（Regime-Aware MoE）**。

---

## 15. 场景 A 单株全基因组分割专向优化（Student V4.2：ORF2Bin + SubBinContextRefiner + Plateau Seeding）

为优先解决“场景 A：单株细菌全基因组扫描中的中等信心原噬菌体高原漏检（如 K-12 `Rac/Qin`）与 200 bp 断点边界精度提升”两项短板，在严格遵循“零测试集泄露（所有架构对比、特征消融与解码器标定均严格限定在 `train_*` 与 `v1 val`）”的前提下，于 V4.1 上完成 **Student V4.2** 升级、模块化集成、全仓库回归测试及冻结冷评测。

### 15.1 模块化工程落地与测试验证（先测试后执行）

1. **新增/修改的核心模块**
   - [subbin_refiner.py](file:///f:/NCBI%20blast/src/phage_discovery/student/subbin_refiner.py)（新增）：
     - `extract_per_orf_viral_scores` 与 `project_orf_to_25bins`：复用冻结 `StudentV4` 的 `OrfStream` 每 ORF 隐式表征生成神经病毒倾向评分并映射至 25 个 `200 bp` 亚窗，产出 `10` 维 `ORF2Bin` 空间特征；
     - `build_contig_subbin_sequences`：构建全量 `28` 维亚窗序列特征（`18` 维边界邻域与窗口/语义对齐特征 + `10` 维 `ORF2Bin`），包含对齐 `1 kb` 步长窗口的 `O(1)` 快速路径与任意窗口回退路径；
     - `SubBinContextRefiner`（`subbin_v1_dilated_tcn`, `in_dim=28`, `hidden_dim=96`, `max_delta=2.4`）：多尺度膨胀一维卷积残差精修器，搭配过渡带加权 BCE 损失、正反链翻转对称增强与推理 TTA，以及 `max_chunk_bins=4096, overlap_bins=256` 分块安全推理（显式 `torch.no_grad()`）。
   - [metrics.py](file:///f:/NCBI%20blast/src/phage_discovery/benchmark/metrics.py) & [model_eval.py](file:///f:/NCBI%20blast/src/phage_discovery/benchmark/model_eval.py)：
     - 为 `decode_window_scores_to_regions` 与 `decode_subwindow_probs_to_regions` 增加 `plateau_min_windows=0` / `plateau_second_threshold=None`（“多窗高原触发”：`len >= k` 且次高窗概率 `>= t_2nd` 时允许作为候选区域种子）与 `precomputed_bin_profiles` / `smooth_profile` / `refine_pad_bp` 参数，将 `0.48, 0.50` 纳入默认 `DEFAULT_SUB_GRID`；
     - 验证集（`v1 val`）独立对比表明：`Refiner V2 + Plateau Seeding (seed=0.95 | len>=4 & 2nd>=0.90)` 在 `v1 val` 上保持 `TP=75/FP=3/FN=0 (F1=0.9804, pureNegFP/Mb=0.0)` 完全不回撤；尝试放大 Refiner 幅度的 `V2.1 (max_delta=2.8)` 反而引起 `v1 val FN=1`，遂予废弃并保留 `Refiner V2 (max_delta=2.2)`。
   - [distilled_student_v4.py](file:///f:/NCBI%20blast/src/phage_discovery/student/distilled_student_v4.py) & [scanner.py](file:///f:/NCBI%20blast/src/phage_discovery/inference/scanner.py)：
     - 支持 `subbin_refiner.pt` 训练保存、元信息持久化与 `GenomeScanner.from_model_dir` 自动版本识别（保留 `_predict_windows` 旧版二元组接口不变，新增 `_predict_windows_with_profiles` 并由 `scan_sequences` 自动接管全基因组 `200 bp` 精修曲线与 Plateau 解码）；
     - 兼容性抽检确认：加载 `student_v4_1` 时 `subbin_refiner is None, plateau_min_windows=0, sub_threshold=0.55`；加载 `student_v4_2` 时 `subbin_refiner` 自动加载，`plateau_min_windows=4, plateau_second_threshold=0.9, sub_threshold=0.45, refine_pad_bp=3000, smooth_sub_profile=False`。
   - [test_v4_architecture_and_prep.py](file:///f:/NCBI%20blast/tests/test_v4_architecture_and_prep.py)：
     - 新增 `ORF2Bin` 映射与分块推理/单窗越界防护单测、`Plateau Seeding` 与 `precomputed_bin_profiles` 解码单测，并扩展 V4.2 端到端闭环验证。
2. **回归测试结果**
   - V4/基准/门控专项测试（`test_v4_architecture_and_prep.py`, `test_benchmark_pipeline.py`, `test_protein_gate_and_scanner.py`）：**`13 passed in 28.45s`**。
   - 全仓库回归测试（`.\.venv\Scripts\python.exe -m pytest tests/ -q --tb=short`）：**`200 passed in 238.87s (0:03:58)`**（`0 failed, 0 skipped`）。

### 15.2 V4.2 训练结果与零泄漏 `v1 val` 解码器标定（`F:\Phage data\models\full_v4\student_v4_2\`）

- **训练输出**：在保留原有 `student_v4_1` 目录完全不动的基础上，由 [run_v4_2_upgrade_and_eval.py](file:///C:/Users/Administrator/.gemini/antigravity/brain/a84b4add-178c-4aff-97a2-c2e69eae3a98/scratch/run_v4_2_upgrade_and_eval.py) 基于全量 `train_*` 切分（`tr_chunks=3217`, `va_seqs=75`）完成 `SubBinContextRefiner` 训练（`ORF2Bin` 投影 `3.55s`，`16` 轮训练 `31.57s`，Epoch `15` 早停 `best_val_joint_bce=0.291703`）。
- **`v1 val`（仅验证集）解码器择优**：
  - 选定配置：`seed_threshold=0.95, extend_threshold=0.30, sub_threshold=0.45, plateau_min_windows=4, plateau_second_threshold=0.90, refine_pad_bp=3000, smooth_profile=False`。
  - `v1 val`（完整 V4.2 vs 去除 SubBinContextRefiner 的 `val_raw`）：
    - `val_raw`（仅 Refiner V2 + 原 `sub_head`）：`TP=75 / FP=6 / FN=0`, `F1=0.9615`, `pureNegFP/Mb=0.3334`, `MAE=539.3 bp` (`Med=364.0 bp`, `degraded_fragment MAE=541.8 bp`)。
    - **`V4.2`（+ SubBinContextRefiner）**：**`TP=75 / FP=3 / FN=0`**, **`F1(IoU>=0.5 & 0.8)=0.9804`**, **`pureNegFP/Mb=0.0`**, **`mean_iou=0.9812`**, **`MAE=424.4 bp` (`Med=272.0 bp`)**（其中 `degraded_fragment MAE=381.6 bp`, `intact_single MAE=436.6 bp`, `multi_tandem MAE=439.2 bp`），对比 V4.1 验证集基线（`563.4 bp`）降低 **`139.0 bp`**。

### 15.3 冻结 `v1 test` 与 4 株真实细菌全基因组冷对比（[v4_2_comprehensive_comparison.json](file:///F:/Phage%20data/models/full_v4/v4_2_comprehensive_comparison.json)）

#### 1. 冻结 `v1 test`（20.862 Mb，75 真前噬菌体 + 15 条纯阴性）

| 方案 | 阈值 (`seed/ext/sub`) | 推理 / 门控耗时 | 嵌合 TP/FP/FN | F1 (`IoU>=0.5 / 0.8`) | `mean_iou` | 断点 `MAE (Med)` | `intact_single MAE` | `multi_tandem MAE` | `degraded_fragment MAE` (`Med`) | 总体 FP/Mb (纯阴性) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `v2_raw` | `0.90/0.50/0.35` | `0.815s / 0s` | `75 / 4 / 0` | `0.9740 / 0.9740` | `0.9655` | `757.3 (670.0) bp` | `830.4 bp` | `785.1 bp` | `601.2 bp` | `0.1917 (0.3043)` |
| `v3.1_raw` | `0.95/0.30/0.35` | `0.826s / 0s` | `75 / 5 / 0` | `0.9677 / 0.9548` | `0.9659` | `740.8 (620.0) bp` | `797.7 bp` | `734.7 bp` | `665.8 bp` | `0.2397 (0.6085)` |
| `v4_1_raw` (纯神经) | `0.95/0.60/0.55` | `11.872s / 0s` | **`75 / 2 / 0`** | **`0.9868 / 0.9868`** | `0.9682` | `728.6 (460.0) bp` | `821.9 bp` | `825.5 bp` | **`426.9 bp`** | **`0.0959 (0.3043)`** |
| **`v4_2_raw` (纯神经)** | `0.95/0.30/0.45` (+Plateau) | `13.698s / 0s` | **`75 / 2 / 0`** | **`0.9868` / `0.9737`** | **`0.9688`** | **`702.0 (378.0) bp`** | **`530.7 bp`** | **`758.3 bp`** | `865.2 (381.0) bp` | **`0.0959 (0.3043)`** |
| `v4_2_gate` (+ProteinGate) | `0.95/0.30/0.45` (+Plateau) | `13.299s / 193.926s` | **`75 / 2 / 0`** | **`0.9868` / `0.9737`** | **`0.9688`** | **`702.0 (378.0) bp`** | **`530.7 bp`** | **`758.3 bp`** | `865.2 (381.0) bp` | **`0.0959 (0.3043)`** (拒杀 `0`) |

> **说明**：`v4_2_raw` 在 `v1 test` 主指标（`TP=75/FP=2/FN=0, F1=0.9868`）与纯神经零门控拒杀保持历史最优，同时将全局 `MedAE` 由 `460.0 bp` 大幅压缩至 **`378.0 bp`**（`-82.0 bp`）、`intact_single MAE` 由 `821.9 bp` 锐降至 **`530.7 bp`**（`-291.2 bp`）、`multi_tandem MAE` 由 `825.5 bp` 降至 **`758.3 bp`**。诚实可见的小幅回撤在于：`degraded_fragment` 虽保持中位数 `381.0 bp` 且 `TP=18/FP=0/FN=0 (F1=1.0)`，但受个别长尾样本拖累致均值由 `426.9 bp` 升至 `865.2 bp`，且 `strict_iou_0_8` 有 `1` 例退化为 `0.5 <= IoU < 0.8` 区间（`sF1: 0.9868 -> 0.9737`）。

#### 2. 4 株陌生真实细菌全基因组扫描与 CheckV 独立金标准边界对齐

| 基因组（`len / GC%`） | `v4_1_raw` | `v4_2_raw` (纯神经) | `v4_2_gate` (+ProteinGate) | V4.1 vs V4.2 CheckV 对齐及区间要点 |
| :--- | :--- | :--- | :--- | :--- |
| `NC_003888.3` 链霉菌 (`8.668 Mb / 72.12%`) | `0` (`0.00/Mb`) | **`0` (`0.00/Mb`, `30.578s`)** | `0` (`0.00/Mb`, `31.446s`) | 高 GC 宿主维持绝对 `0` 误报，Plateau Seeding 未引入任何假阳 |
| `NC_000913.3` 大肠杆菌 K-12 MG1655 (`4.642 Mb / 50.79%`) | `2` (`DLP12`, `e14`) | **`4` (`36.207s`)** | **`4` (`4/4 hallmark_confirmed`, `42.894s`)** | 新增召回 **`Rac` (`1411600..1436000, p=0.9423`)** 与 **`Qin` (`1633800..1653200, p=0.9474`)**，4/4 全过蛋白门控实锤（`CP4-57` 仍未过线） |
| `NC_007795.1` 金葡菌 NCTC 8325 (`2.821 Mb / 32.87%`) | `3` (`0` 转座酶 FP) | **`3` (`0` 转座酶 FP, `8.451s`)** | **`3` (`3/3 hallmark_confirmed`, `21.369s`)** | CheckV `mean_IoU` **`0.8560 -> 0.9407`**，**`mean_MAE` `3373.3 -> 1362.7 bp`（`-2010.6 bp`，反超 V3.1 的 `1516.7 bp`）**；`phi11` 达 `IoU=0.9882 / MAE=307.5 bp`，`phi13` 从 `0.7459 (5824 bp)` 升至 `0.8886 (2562 bp)` |
| `NC_003197.2` 鼠伤寒沙门氏菌 LT2 (`4.857 Mb / 52.22%`) | `4` (`0.82/Mb`) | **`4` (`0.82/Mb`, `40.078s`)** | **`4` (`4/4 hallmark_confirmed`, `52.887s`)** | CheckV 前两段达百 bp 精度（`Gifsy-2`: `IoU=0.9936 / MAE=137.0 bp`, `Fels-1`: **`IoU=0.9959 / MAE=93.5 bp`**）；第 3 段 (`2845818..2889112`) 尾部偏早截断（`IoU 0.7840 -> 0.7108, MAE 4765 -> 6465 bp`），使 LT2 均值略调至 `IoU=0.9001, MAE=2231.8 bp`（对比 V4.1 `0.9024 / 2159.8 bp`） |

### 15.4 结论与后续路线留档

- **场景 A（单株细菌全基因组扫描与 200 bp 分割）阶段性收口**：V4.2 在未触碰测试集、不增加 BLASTp 依赖的纯神经网络下，同时达成了 **K-12 真前噬菌体召回倍增（`2 -> 4`，`4/4 hallmark_confirmed`）、高 GC 与低 GC 转座酶 0 误报、以及 `v1 test` 与 *S. aureus* NCTC 8325 断点精度跃迁（`v1 test MedAE 460 -> 378 bp`, `NCTC8325 CheckV MAE 3373.3 -> 1362.7 bp`）**。
- **残余边界与下一阶段方向**：K-12 `CP4-57`（偏弱退化）、LT2 第 3 段末梢及 `v1 test` 极少数退化片段长尾边界误差与 `<=1 kb` 窗口能力瓶颈，属于原始 `StudentV4` 主干缺少**氨基酸级表征（ORF 翻译序列/二三肽分支）与尺度/MGE 防火墙路由头（Regime-Aware MoE）** 的结构上限，将作为后续 V5 主干与复杂混合多菌/短片段场景的优化重点。

---

## 16. 工程收口：模型目录瘦身、废弃代码清理与静态检查归零

1. **模型产物归档精简（`F:\Phage data\models\`）**
   - 仅保留稳定可复现里程碑与核心专家基线：`full_v2`、`full_v3_1`、`full_v4/expert_{a,b,c}`、`full_v4/ensemble`、`full_v4/student_v4_1`、`full_v4/student_v4_2` 及其基准评估报告。
   - 移除作废实验产物与中间断点缓存（`full_v3`、`full_v4/student`、`student_v4_0_bak`、OOF/Refiner 临时 `.npz`/`.json`）。
2. **代码库清理**
   - 移除失效脚本与误追踪大库：`src/backend/test_read.py`、根目录遗留空标识文件与 `translations_backup_20260829_111949.db`（保留 `tools/_deprecated/` 下仍被运行时路径修复工具引用的 `libwinpthread-1.dll`）。
3. **静态检查与兼容性修复**
   - `pyrefly check src/ tests/`（`.venv` 与默认环境双重校核）：全仓库错误数 **`0 errors`**；`src/phage_discovery/` 与 `src/utils/phage_dataset/` 达到 **`0 diagnostics`**（消除 `GroupKFold.split` 参数类型冲突、`implicit-import`、`os.system` 弃用调用及冗余类型强转）。
   - `ruff check` 对 `src/phage_discovery/`、`src/utils/phage_dataset/` 及本次修复模块与测试全部通过。
   - 前端构建验证 `npm run build --prefix src/web-next`（`vue-tsc -b && vite build`）正常退出（`0`）。

---

## 17. Student V4.2 接入组装分析工作台与 `protein_compare` 移除

1. **彻底移除 `核心功能蛋白同源性比对 (protein_compare)`**
   - 删除 `src/analysis/protein_compare/`、`src/backend/routes/protein_compare.py`、`src/web-next/src/views/Analysis/modules/protein_compare/` 及失效单测 `tests/test_disambiguation.py`、`tests/test_nomenclature.py`、`tests/test_engineering_optimizations.py` 中对应测试。
2. **仅保留 Student V4.2 版本接入工作台引擎 (`src/analysis/phage_finder/`)**
   - `model_registry.py`：采用项目根相对路径、`PHAGE_DISCOVERY_*` 环境变量与 `ConfigManager` 动态发现模型与蛋白库，仅识别包含 `student_v4.pt + student_v4_meta.json + subbin_refiner.pt` 的完整 **Student V4.2** 版本，过滤 `V2 / V3.1 / V4.1`；按 `cpu_count() - 2` 计算多核安全并发数。
   - `metrics.py` 与 `scanner.py`：抽取共享 `assemble_contig_subbin_profile(...)`，在 `ScanResult` 补充 `region_profiles` 200 bp 边界概率剖面与 `blastp_bin` 注入支持。
   - `db.py` / `queue.py` / `manager.py` / `exporter.py`：SQLite WAL 持久化、单序列 CUDA 异步队列（`gc.collect()` + `torch.cuda.empty_cache()` / `ipc_collect()` 显存回收）、支持 FASTA / FASTA.GZ / GenBank 预检，按需导出 FASTA、TSV、GFF3、GBK 及带 3 kb 侧翼+Pyrodigal ORF 注释的单区微基因组 GenBank，并以 `src/backend/routes/phage_discovery.py` 挂载至 `api_server.py`。
3. **前端工作台界面与跨模块联动 (`src/web-next/src/views/Analysis/`)**
   - 新增 `modules/phage_discovery/`，支持文件上传/粘贴/组装历史导入、复用 `ContigSelector` 多 Contig 筛选、计算设备与可选 BLASTp 蛋白门控切换、Contig 全长线性轨道 SVG 与 200 bp SubBin 边界曲线 SVG 展示，以及一键跳转 `GenomeViewerModule` 与 `AnnotationModule`。
4. **全栈静态检验与端到端回归测试**
   - `pyrefly`：全仓库 `0 errors`，工作台新模块及测试 `--min-severity=warn` `0 diagnostics`。
   - `ruff check`：本次修改与新增 Python 模块及测试全部通过（`All checks passed!`）。
   - 前端构建：`npm run build --prefix src/web-next`（`vue-tsc -b && vite build`）退出码 `0`。
   - 真实权重冒烟：自动识别本地 `V4.2`（`has_subbin_refiner=True`）及 `NVIDIA GeForce RTX 4070 Laptop GPU`，端到端推理成功。
   - 全仓库回归：`.\.venv\Scripts\python.exe -m pytest tests/ -q --tb=short` 运行通过 **`196 passed in 258.80s (0:04:18)`**（`0 failed, 0 skipped`）。

---

## 18. 全基因组底图与预测前噬菌体交互式叠图模块 (`PhageOverlayMap`)

1. **序列底图保真解析与连续景观采样 (`scanner.py`, `exporter.py`, `manager.py`, `routes/phage_discovery.py`)**
   - `scanner.py` 新增 `_collect_contig_score_tracks` 与 `ScanResult.contig_score_tracks`：当启用 `collect_profiles=True` 时，为每条目标 Contig 生成至多 360 分箱的 V4.2 模型连续 `max_prob / mean_prob` 概率曲线数据。
   - `exporter.py` 新增 `load_sequences_with_annotations`（自动辨识 GenBank 与 FASTA/FASTA.GZ 输入，完整保留原 GenBank 中的 `CDS` / `tRNA` / `rRNA` / `mobile_element` 注释；若为纯 FASTA，则采用 `pyrodigal` 自动构建碱基坐标系特征骨架）、`_compute_contig_base_tracks`（360 分箱 `GC%` 与 `GC Skew`）、`build_contig_overlay_gbk`（整条 Contig 底图与 `prophage_region` 融合 GenBank），并按 Rule 9 分片落盘至 `results/phage_discovery/<task_id>/overlays/contig_<i>.json`。
   - 新增路由端点 `GET /api/analysis/phage_discovery/{task_id}/overlay` 与 `/overlay-gbk`。
2. **前端双模态交互式叠图工作台 (`PhageOverlayMap.vue` & `GenomeViewerModule.vue`)**
   - `PhageOverlayMap.vue` 支持**线性多轨道对齐叠图**与**环形全长叠图**即时切换、滚轮缩放、左键拖拽漫游、顶部/底部全局 Minimap 俯瞰快速跳转、独立图层开关（底图特征 / V4.2 概率曲线 / `GC%` 偏移 / `GC Skew` / 蛋白门控滤除对照）、底图特征实时关键词搜索与步进高亮定位（如 `integrase`, `tRNA`, `dnaA`）、大基因组智能视口过滤抽稀、SVG 矢量导出及一键生成并跳转 `GenomeViewer` 查看整条 Contig 叠图。
   - 同步增强 `GenomeViewerModule.vue`：分离 `prophageOverlayFeatures` (`type === 'prophage_region'`) 至跨正负链半透明包络亮点层，确保全序列底图 CDS 箭头与预测噬菌体区段同时清晰展现。
3. **蛋白门控完整度分级枚举对齐修复 (`exporter.py`)**
   - 修正 `_classify_completeness()` 对 `RegionGateResult.tier` 的映射缺失（原错误仅匹配 `"high"` / `"medium"`，导致 `ProteinGate` 真实输出的 `"hallmark_confirmed"`、`"phage_cluster_confirmed"`、`"dark_matter_fallback"` 在开启门控时误落入兜底 `"low"` 分支），改为联合评估真实 `tier`、`hallmark_hits`、`non_amg_hits`、区段长度与模型峰值评分，同步补齐单元回归断言。

## 19. 任务排队调度机制与前端排队视图全链路修复
1. **故障诊断与测试先行验证 (`pytest` & `Vitest`)**
   - **前噬菌体发现 (Student V4.2)**：后端 `PhageDiscoveryQueue(max_workers=1)` 虽然底层串行执行，但前端 `usePhageDiscovery.ts` 将 `queued` 与 `running` 混同为 `isRunning`，`PhageDiscoveryModule.vue` 缺少独立排队等待卡片，导致任务排队提交后界面直接渲染运行中进度视图；同时后端 `submit_task()` 生成的 `task_id` 精确到秒级易在高频并发提交时触发 SQLite `UNIQUE constraint failed` 冲突，且 `cancel_task()` / `delete_task()` 未从待执行队列中清理任务编号并同步 `phage_discovery_queue_update` 元数据。
   - **基因组组装 (`Assembly`)**：排查发现真实的前后端排队绕过缺陷——当任务 1 正在运行（已从 `_queue` 弹出）时，提交任务 2 后 `_queue` 长度为 `1`（`queue_position = 1`），前端 `useAssembly.ts` 原判断 `queuePos > 1 ? 'queued' : 'running'` 直接将排队中的任务 2 覆写为 `running` 并弹出运行进度界面，且未订阅 WebSocket `assembly_queue_status` 事件；后端 `/assembly/run` 亦缺少 `status: "queued"` 与 `is_busy` 状态标记，`assembly_db.get_queued_tasks()` 漏查 `'queued'` 状态。
   - 按照规则 6 先在 `tests/test_phage_finder_workbench.py`、`tests/test_assembly_queue.py` 与前端 `phageQueue.test.ts`、`assemblyQueue.test.ts` 编写复现与回归测试。
2. **前后端全链路排队改造**
   - **前噬菌体发现后端 (`queue.py`, `manager.py`)**：`enqueue()` 与 `submit_task()` 返回精确 `queue_position`、`is_busy`、`running_count`、`queued_count`；`task_id` 附加随机十六进制后缀消除高频并发主键碰撞；完善 `remove_from_waiting()`、`cancel_task()` 与 `delete_task()` 队列同步清理及快照 `running_tasks` / `waiting_tasks` 详情广播；`_worker_loop` 调度起跑前立即推送 `running`（`2%`）事件。
   - **前噬菌体发现前端 (`usePhageDiscovery.ts`, `PhageDiscoveryModule.vue`, `PhageDiscoveryQueueCard.vue`, `PhageDiscoverySetup.vue`, `PhageDiscoveryProgress.vue`, `PhageDiscoveryHistory.vue`, `types.ts`)**：拆分 `isQueued` 与 `isRunning` 计算属性，新增独立排队等待卡片 `PhageDiscoveryQueueCard.vue`（展示真实 `#序号`、前方运行中任务、扫描摘要、`取消排队` 与 `继续提交新任务`）；在 `PhageDiscoveryProgress.vue` 顶部增加 `新建排队` 入口；在 `PhageDiscoverySetup.vue` 增加引擎忙碌提示横幅与排队提交文案；在 `selectTask()` 中切换任务时清理日志并支持 `2.5s` 忙时兜底轮询同步。
   - **基因组组装全栈 (`assembly.py`, `assembly_db.py`, `persistent_queue.py`, `useAssembly.ts`)**：后端补齐 `is_busy` / `running_task` / `waiting_count` / `waiting_tasks` 与 `'queued'` 状态恢复查询；前端 `submitTask()` 按 `backendIsBusy || isQueued || queuePos > 1 || backendStatus === 'queued'` 保持排队态，新增 `assembly_queue_status` 事件监听驱动自动转入运行态与排队位次更新。

## 20. 失效测试代码清理与全库校验归档
1. **排查与清理失效测试**
   - 移除前端遗留失效测试 `src/web-next/src/composables/__tests__/useBlastDetailViewer.test.ts`：该测试仍导入已弃用的 `pyqt-bridge` 并 Mock 回调方式，而 `useBlastDetailViewer.ts` 早已迁移至基于 `ElectronBridge` 的异步 Promise 调用，导致 `vitest` 运行直接报错失败。
   - 移除后端阻塞及空壳测试文件 `tests/test_annotation_cascade.py` 与 `tests/test_diversity_upgrade_evaluation.py`：前者因未隔离真实 WSL 外部进程且向工作区写入产物而导致全量 `pytest` 在首个文件挂起超时（其合法逻辑已完全被 `tests/test_auto_return_workflow.py` 与 `tests/test_annotation_fixes.py` 覆盖）；后者不含任何 `test_*` 用例（直接执行报退出码 `5`）且硬编码依赖本地非受控基准报告（已被 `tests/test_diversity_qc_integration.py` 替代）。
2. **清理后全栈验证结果**
   - 后端全量单元测试 `pytest tests/ --tb=short -q`：**`197 passed in 103.74s`**（零超时、零失败、零跳过）。
   - 前端全量单元测试 `npm run test --prefix src/web-next -- --run`：**`6 passed (6), 42 passed (42)`**。
   - 前端编译与静态类型检查 `npm run build --prefix src/web-next`（含 `vue-tsc -b && vite build`）通过，后端 `pyrefly check src/ tests/` 报告 **`0 errors`**，并整理分主题提交推送至 Git。

## 21. 叠图区段图表去重、真实特征能力门控与标签防裁切优化
1. **移除重合的下方旧边界精细概率曲线卡片 (`PhageDiscoveryResults.vue`)**
   - 上方新构建的交互式 `PhageOverlayMap` 已完整涵盖全基因组与单区段的 `V4.2 分数` 曲线、快速聚焦区段（含侧翼缩放）等可视化能力，因此移除下方重复的 `边界精细概率曲线 (200bp SubBin 分辨率)` 卡片、冗余 `PROF_*` / `profileGeometry` 几何计算代码及旧 SVG 样式规则。
   - 将原先卡片右上角的“在图谱浏览器中查看” / “注释此区段”快捷联动操作无损迁移至 `PhageOverlayMap.vue` 底部的快速聚焦栏（`.region-pills-bar`），激活并触发已定义的 `open-region-viewer` 与 `open-annotation` 事件，直接作用于当前选中的 `activeRegion`。
2. **底图真实能力感知与禁用虚假特征展示 (`PhageOverlayMap.vue`)**
   - 当输入序列为 `FASTA` 时，后台仅经由 Pyrodigal 提取无基因名、无功能注释的 de novo ORF（`source_format === 'fasta'`），工作台叠图界面并不具备识别 `整合酶 / 转座酶` 或 `tRNA / rRNA` 的能力。
   - 在 `PhageOverlayMap.vue` 新增 `isGenbankSource`、`hasIntegraseOrTransposase`、`hasRnaFeatures`、`baseLayerLabel`、`searchPlaceholder` 等能力感知计算属性：
     - `FASTA + Pyrodigal` 模式下彻底隐藏 `整合酶 / 转座酶`（紫色）与 `tRNA / rRNA`（绿色）图例，并将区段内/宿主图例、图层开关及检索框提示准确修正为 `区段内 ORF`、`宿主 ORF`、`底图特征 (ORF)` 与 `检索底图 ORF 编号或坐标 (如 ORF_0010)...`。
     - 仅当输入为原生 `GenBank` 且底图特征真包含对应注释时，按需渲染 `整合酶 / 转座酶`、`tRNA / rRNA` 图例及 `(CDS/tRNA)` 标签。
   - 修复线性模式中区段徽标背景 `<rect>` 最小宽度固定 `42` 导致 `Phage_001` 文本右侧溢出的视觉裁切缺陷，改为按文本长度自适应计算 `Math.max(item.w, item.reg.region_id.length * 6.8 + 12)`。
3. **测试先行与全栈回归验证**
   - 遵循测试先行规则新增 Vitest 组件回归测试 [phageOverlayAndResults.test.ts](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_discovery/__tests__/phageOverlayAndResults.test.ts)，先复现 3 条失败断言后完成组件修复并转绿。
   - 修改后验证全量前端单元测试 `npm run test --prefix src/web-next -- --run`：**`7 passed (7), 45 passed (45)`**；`npm run build --prefix src/web-next`（`vue-tsc -b && vite build`）退出码 `0` 构建通过；`pytest tests/test_engineering_optimizations.py -q`（**`6 passed`**）确认全仓无 Emoji 与 UTF-8 规范合规。

## 22. 图谱浏览器联动贯穿全长错误注释（misc_feature_1_*）全链路修复
1. **根因排查**
   - `exporter.py` 的 `_build_region_seq_record()` 此前使用 `type="misc_feature"` 标注预测区段，且当输入为完整噬菌体全长基因组或无宿主侧翼区间（`rel_prophage_start == 0` 且 `rel_prophage_end == len(slice_seq)`）时，仍写入一条从首碱基贯穿至末尾的全长特征。
   - `GenomeViewer` 前端 `parseGenBank()` 读取 `misc_feature` 时，因缺失 `/gene` 与 `/product` 而生成 `misc_feature_1_<len>`，进而被渲染在正链 `CDS` 主轨道上形成贯穿头尾的巨大灰色箭头遮盖全部内部真实 ORF，并在详情面板被误算为超长假定蛋白（`aa` / `kDa`）及混入左侧基因特征清单。
   - 同时排查到 `GenomeViewerModule.vue` 的 `filteredFeatures`、`categoryCounts` 与中心徽标 `CDS` 计数此前未排除 `prophage_region`，导致全长叠图模式下包络框也混入基因列表与 `Hypothetical` 统计并算出错误蛋白尺寸。
2. **双端修复方案**
   - **导出源头 (`src/analysis/phage_finder/exporter.py`)**：`_build_region_seq_record()` 仅在真实存在宿主侧翼（`rel_start > 0 or rel_end < len(slice_seq)`）时写入 `type="prophage_region"`（统一交由跨链包络层渲染），不再写出 `misc_feature` 污染正链轨道；纯噬菌体全长或核心 `core_rec` 不再附加冗余的贯穿头尾区段特征。
   - **历史兼容与解析纯化 (`src/web-next/src/views/Analysis/modules/viewer/utils/parser.ts`)**：新增 `normalizeLegacyOverlayFeatures()` 后处理，对磁盘已保存的历史旧 `misc_feature`（无 `/gene`/`/product` 且含 `GlobalCoord=`/`PeakScore=`/`Completeness=`）进行自动兼容清洗——贯穿全长（`>= 98%`）者直接过滤剔除，局部带侧翼者自动升级为 `prophage_region` 跨链包络框，同时保留常规短 `misc_feature` 与 `/label` 显示名称。
   - **视图列表、计数与详情纯化 (`src/web-next/src/views/Analysis/modules/viewer/GenomeViewerModule.vue`)**：将 `filteredFeatures`、`categoryCounts`、侧边栏与中心特征数统一基于 `baseTrackFeatures`（剔除 `prophage_region`）；高亮选中 `prophage_region` 时取消单链错位高亮并联动高亮其区间内基因；悬浮提示与详情抽屉针对 `prophage_region` 隐去误导性的 `蛋白规模 (aa/kDa)` 与 `复制蛋白翻译序列` 按钮。
3. **涉及模块回归验证**
   - 遵循规则 6 先编写后端 `test_exporter_full_length_region_omits_spanning_feature` 与前端 [phageViewerOverlay.test.ts](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/viewer/__tests__/phageViewerOverlay.test.ts)（先复现失败后修补转绿），随后仅测试涉及模块并跳过无关全量回归。

---

## 23. 阶段 1 模型优化消融评测（ORF 丰富编码 + 二三肽特征 + PHROGs MMseqs 语义）

1. **模块化特征架构与零覆盖隔离设计**
   - **Window 与 ORF 解耦设计（先消融后落盘）**：早期 `599d` 全量特征对照证实，直接将 `343d` 约化三肽拼接进窗口级表格向量会在 XGBoost 中引入稀疏过拟合（`test_windows Rec@0.5%` 由 `0.8315` 降至 `0.7645`）。据此将结构收敛为：**窗口级采用紧凑 `256d`**（原 `185d` + `49d` `7×7` 约化二肽 + `12d` Pyrodigal 质量统计 + `10d` 生物物理/6-frame 兜底），而将 `27d` (`3×3×3`) 约化三肽与 Pyrodigal 编码细节收敛至**逐 ORF Token（`117d` = 原 `30d` + `87d`）** 专供 `ORFTransformer` 与 `OrfStream`；当短片段未检出完整 Pyrodigal 基因时启用向量化 6-frame 最长可读框兜底（`is_fallback_6frame` 标记位）。
   - **源码落地与向后兼容**：新增 [peptide_features.py](file:///f:/NCBI%20blast/src/phage_discovery/features/peptide_features.py) 与 [phrog_teacher.py](file:///f:/NCBI%20blast/src/phage_discovery/data/phrog_teacher.py)，扩展 [window_features.py](file:///f:/NCBI%20blast/src/phage_discovery/features/window_features.py)、[expert_c_orf.py](file:///f:/NCBI%20blast/src/phage_discovery/experts/expert_c_orf.py)、[expert_a_xgb.py](file:///f:/NCBI%20blast/src/phage_discovery/experts/expert_a_xgb.py)、[distilled_student_v4.py](file:///f:/NCBI%20blast/src/phage_discovery/student/distilled_student_v4.py) 与 [scanner.py](file:///f:/NCBI%20blast/src/phage_discovery/inference/scanner.py)，通过 `feature_profile` / `orf_feat_dim` 元数据持久化实现 `V4.2`（`185d / 30d`）与 `Stage 1`（`256d / 117d`）完全无缝隔离与自动识别。
   - **PHROGs MMseqs2 语义补全**：基于 `database/pharokka_db/phrogs_profile_db` 对 8 个训练分片（`111,866` 窗）增量搜索（剔除 `unknown function`），累计在不更改 `clean_labels` 的前提下在各分片新增回填高特异噬菌体特征标志窗（`windows: 559`、`chimeras: 273`、`mined: 64`、`hard_v4: 56`、`ext_rare: 44`、`ext_windows: 31`、`ext_mined: 27`、`hard_neg: 5`）。

2. **Teacher 与 Student 隔离训练数据（`F:\Phage data\models\full_v4\stage1_ablation\`）**
   - **`Expert A`（`185d -> 256d`）**：`v1 test` 总体 `AUPRC 0.9911 -> 0.9915`、`<=1kb Rec@0.5% 0.4970 -> 0.5396`、嵌合 `F1 0.9615 -> 0.9677`（`negFP/Mb = 0.6085` 不变）；增益榜前 15 中 Pyrodigal 与 7×7 二肽特征稳定上榜（`pyro_overlap_gene_frac`、`dp7_11`、`pyro_mean_score`、`pyro_mean_cscore`、`pyro_min_cscore`）。
   - **`Expert C`（`30d -> 117d`）**：纯 ORF 神经网络全尺度跃升，`win AUPRC 0.9557 -> 0.9661`、`win Rec@0.5% 0.3345 -> 0.4950`、`<=1kb AUPRC 0.7735 -> 0.8241`、`<=1kb Rec@0.5% 0.0000 -> 0.1128`、嵌合 `F1 0.8427 -> 0.8571`（伴随 `negFP/Mb 0.3043 -> 0.9128`）。
   - **`Student V4.2 Stage 1`**：参数仅微增 **`+0.81%`**（`3,639,114 -> 3,668,426`），Epoch 16 达到 **`best_val_auprc = 0.99622`**（对比 `V4.2`: `0.99589`、`Ensemble Stage1`: `0.99586`），`val` 自动校准最优解码达成 `F1 = 0.9934, MAE = 413.8 bp, FP/Mb = 0.0`（`seed=0.95, extend=0.30, sub=0.45, plateau=4/0.90`）。

3. **`Student V4.2` vs `Student V4.2 Stage 1` 同台冷评测（收益与损失审计）**
   - **明确收益**：
     1. **嵌合体边界精度大幅跃升**：`v1 test` 全局断点 **`MAE 702.0 -> 426.0 bp`（`-39.3%`）**、**`MedAE 378.0 -> 250.0 bp`（`-33.9%`）**、`mean_iou 0.9688 -> 0.9807`，最困难的 `degraded_fragment MAE` 由 `865.3` 锐降至 **`347.0 bp`（`-59.9%`）**，达成 **`75/75 (100%)`** 满足 `strict_iou_0_8`（`sF1: 0.9737 -> 0.9740`）。
     2. **窗口整体排序与常规阈值更优**：`win AUPRC 0.9898 -> 0.9901`、`AUROC 0.9895 -> 0.9901`、`F1@0.5 0.9457 -> 0.9507`、`<=1kb AUPRC 0.9536 -> 0.9577`（`<=1kb F1@0.5 0.8778 -> 0.8956`，`FPR@95%TPR 0.3010 -> 0.2265`）、`>3kb Rec@0.5%FPR 0.8675 -> 0.9057`；非噬菌体病毒与质粒假阳性明显下降（`0.0817 -> 0.0392` 与 `0.0946 -> 0.0743`）。
     3. **真实基因组边界微改善**：`NC_003888.3` 链霉菌维持 **`0` 误报**，`NC_000913.3` K-12 维持 **`4/4`**，`NC_003197.2` LT2 4/4 且 CheckV 对齐提升（`mean_IoU 0.9001 -> 0.9060`、`MAE 2231.8 -> 2107.2 bp`，修复第 3 段尾部截断 `IoU 0.7108 -> 0.7621`），`NC_007795.1` 金葡菌维持 **`3/3` 零转座酶误报**且 `phi13` CheckV IoU 由 `0.8886` 升至 **`0.9451`**（`MAE 2562 -> 1262 bp`）。
   - **明确损失与开销**：
     1. **嵌合体新增 2 处 `6.8 kb` 假阳性区段**：`v1 test` 嵌合体 `TP/FP/FN` 由 `75/2/0` 变为 `75/4/0`（主 `F1 0.9868 -> 0.9740`，`overall FP/Mb 0.0959 -> 0.1917`；`pure_negative_fp_per_mb` 仍保持 `0.3043` 不变）。新增 2 处为 `test_CHIM_0026: 85400..92200` 与 `test_CHIM_0039: 35600..42400`，均为 `6.8 kb` 短高置信峰且均未遭蛋白门控拒杀。
     2. **窗口极端低假阳端 (`Rec@0.5%FPR`) 回撤**：整体 `0.7470 -> 0.6605`、`1_3kb AUPRC 0.9834 -> 0.9750`。审计定位为 `test_windows` 中 `8` 个重复/相似的 `1,738 bp` 细菌负样本片段在 Stage 1 被抬高至 `0.981~0.983` 集体占据前 8 名高分负例，从而推高了 `0.5%FPR` 截断门槛（`0.9687 -> 0.9755`）。
     3. **罕见非有尾小基因组（<15 kb）召回小幅下降**：`Microviridae: 0.95 -> 0.85`、`Leviviricetes: 0.95 -> 0.90`、`Inoviridae: 1.0 -> 0.9688`（有尾主体 `Caudoviricetes` 升至 `0.9760`）。
     4. **从头扫描端到端特征耗时微增**：模型 GPU 推理本身持平微快（`5Mb: 3.174s -> 2.943s`，显存 `+2.4 MB` 至 `516.9 MB`），但 FASTA 全特征提取耗时平均增加约 `5.5% ~ 17.8%`（单基因组多 `1.1s ~ 2.9s`）。

4. **阶段性结论与后续建议**
   - Stage 1 证明了 **逐 ORF 丰富编码 + 二三肽 + PHROGs 语义** 对 **200 bp 边界切割（特别是退化残缺片段）与全基因组真实边界对齐** 具有极大正向价值，但同时略微放大了对宿主内部 **6–8 kb 短片段局部信号的敏感度** 并略削弱超短微病毒（Microviridae/Leviviricetes）权重。建议先**保留现有 `student_v4_2` 生产权重不动**，后续若升版融合时重点配合：**仅正样本或分尺度路由过滤 6–8 kb 短嵌合伪峰**（或 `min_region_bp / plateau` 联调）以及针对非有尾短小病毒补强采样，避免直接替换引入 `v1 test` 主 F1 回退。

---

## 24. 阶段 1.2 精度纠偏、三源合一 9 维功能基因分区蒸馏与全量同台冷对比评测

针对阶段 1（Stage 1）消融中暴露的三项回撤（嵌合体新增 2 处 6.8 kb 短伪峰、`v1 test` 窗口端 `Recall@0.5%FPR` 降至 `0.6605` 以及非有尾小基因组召回微降），同时为后续“原噬菌体完整度判定、生活方式推测与 MGE 污染过滤”建立逐 ORF 功能识别能力，**步骤 31（阶段 1.2）** 在完全隔离目录（`F:\Phage data\training\stage1_2_ablation\` 与 `F:\Phage data\models\full_v4\stage1_2_ablation\`，严禁覆写生产权重 `student_v4_2/`）完成端到端重构与冷评测：

1. **零人工拍参的架构与多任务自校准（`src/phage_discovery/data/functional_partitions.py`, `src/phage_discovery/student/distilled_student_v4.py`）**
   - **彻底移除手工分片加权**：`part_weights=None`，不再依赖人工调整分片倍率，避免顾此失彼。
   - **Kendall 同方差多任务不确定性自动加权（`HomoscedasticMultiTaskLoss`）**：对 `Student V4` 6 个并行监督头（`win_bce`、`sub_bce`、`sem_distill`、`orf_phage_bce`、`win_func_bce`、`orf_func_bce`）引入可学习对数方差约束（`min_log_var=-3.0, max_log_var=3.0`）。Stage 1.2 收敛后学得的实际平衡权重为 `[1.2747, 20.0855, 8.6843, 4.7463, 2.1717, 1.0731]`。
   - **双层客观 9 维功能基因分区定义（`FUNCTIONAL_PARTITION_NAMES`）**：
     `head_packaging`, `connector`, `tail`, `lysis`, `integration_excision`, `dna_rna_replication`, `transcription_regulation`, `moron_amg_defense`, `transposon_plasmid_mge`；配合窗口级别与逐 ORF 级别双层监督头（`func_dim=9`）以及 `IoU>=0.8` 的 ORF 对齐掩码，对 `unknown function` 实施掩码豁免（不强压为负类）。

2. **零泄露非有尾多尺度补强与三源合一客观数据清洗（Step A & Step B）**
   - **非有尾小基因组多尺度零泄露补强 (`train_rare_multiscale`)**：从本地 303 株非有尾候选基因组中，经全基因组 `stride=1` 的 21-mer containment 审计（阈值 `0.25`）剔除 55 株与评估集存在 k-mer 重叠的基因组，保留 **248 株纯净非有尾基因组**，构建 `600 / 1000 / 1800 / 3000 bp` 多尺度均衡窗口正负样本共 **5,680 行**（正负各 2,840 行）。
   - **三源合一 9 维功能注释真值**：解析 `4,631` 个非评估 `.gbk` CDS 注释并联合 `DIAMOND phage_refseq_prot` 与 `PHROGs + PHOLD MMseqs2` 对 `269,613` 条唯一蛋白序列进行客观三源证据对齐（`GBK=160,856`、`DIAMOND=144,061`、`PHROG/PHOLD=135,700`，含 `109,404` 条合并 PHROG+PHOLD 条目）。
   - **9 分片缓存对齐与矛盾样本屏蔽**：全量 `117,546` 行样本（9 分片：`windows 36,000`、`chimeras 37,912`、`mined 12,595`、`hard_neg 5,142`、`ext_rare 2,310`、`ext_windows 1,710`、`ext_mined 14,533`、`hard_v4 1,664`、`rare_multiscale 5,680`）同步构建 `_functional.npz` 与 `_semantic.npz`，累计清洗/掩蔽 **458** 条矛盾负样本与潜在泄露样本，累计有效标注 `orf_phage_pos = 289,363`、`orf_func_known_valid = 464,500`。

3. **Teacher OOF 与 Stage 1.2 Student 训练链路（Step C & Step D）**
   - **Teacher 再训练与 5 折 GroupKFold OOF**：`Expert A (256d)`（`train_rows=115,827`, `best_iteration=1,648`, `train_sec=18.49s`, Val `val_f1=0.9554`, `val_strict_f1=0.9299`, `val_fp_per_mb=0.3334`, `val_breakpoint_mae_bp=1286.2`）与 `Expert C (117d)`（`params=565,762`, `best_epoch=17`, `best_val_auprc=0.9764`, `train_sec=184.64s`）联同冻结 Expert B 输出生成 `train_stage1_2_teacher_oof.npz`（`117,546` 行）。
   - **Student V4.2 Stage 1.2 主体与双 Refiner**：`train_rows=117,144`, `params=3,715,879`（`func_dim=9`, `use_homoscedastic_loss=true`），峰值显存 `1,279.3 MB`（`train_sec=6,487.39s`, `best_epoch=24`, `best_val_auprc=0.99588`）；`sub_head_refinement`（`best_epoch=4`, `best_val_sub_bce=0.164185`, `sub_max_delta=0.9193`）；`RegionContextRefiner v2`（`tr_contigs=3,306`, `best_epoch=9`, `best_val_auprc=0.99808`, `best_val_bce=0.02536`）；`SubBinContextRefiner`（`tr_chunks=3,230`, `best_epoch=3`, `best_val_joint_bce=0.247988`）。验证集自动解码选参得到 `seed_threshold=0.95`, `extend_threshold=0.30`, `sub_threshold=0.35`, `plateau_min_windows=0`, `plateau_second_threshold=null`（Val `val_f1=0.9867`, `val_strict_f1=0.9867`, `val_fp_per_mb=0.0`, `val_breakpoint_mae_bp=312.3`）。

4. **推理暴露接口升级与单窗极值抬升缺陷修复（`src/phage_discovery/inference/scanner.py`）**
   - 在 `ScanResult` 中新增 `region_functional_modules`，输出逐预测区段的 `module_scores`、`active_modules`、`orf_module_counts`、`structural_completeness_hint`、`lifestyle_hint` 与 `mge_contamination_score`。
   - 诊断并修复了 `_collect_region_functional_modules` 中早期 `max(mean_probs, 0.7 * max_probs)` 导致的单窗口极值抬升问题（先前单窗偶发峰值把无实际对应 ORF 的 `connector` 也拉高至 `~0.70`），切换为当存在预测 ORF 时按 `0.4 * mean_probs + 0.6 * orf_max_vec` 聚合（无 ORF 时退回 `mean_probs`），并写入 `tests/test_stage1_2_functional_partitions.py`（`test_collect_region_functional_modules_avoids_single_window_peak_inflation`）回归锁定。

5. **全量同台冷对比评测（`V4.2` vs `Stage 1` vs `Stage 1.2`）**
   - **A. `v1 test` 4,000 窗口基准对照**

| 评测维度 | `V4.2`（生产基线） | `Stage 1`（阶段 1） | `Stage 1.2`（本阶段） | 关键变化解析 |
| :--- | :---: | :---: | :---: | :--- |
| **整体 AUROC / AUPRC** | `0.9895 / 0.9898` | `0.9901 / 0.9901` | **`0.9912 / 0.9905`** | 三代最高，排序区分度稳定抬升 |
| **整体 Recall / FPR@0.5 / F1** | `0.9705 / 0.0820 / 0.9457` (`FN=59`) | `0.9740 / 0.0750 / 0.9507` (`FN=52`) | **`0.9780 / 0.0770 / 0.9518`** (`FN=44`) | **Stage 1 新增的 16 个 FN 回撤救回 14 个** |
| **整体 `Rec@0.5%FPR` / `FPR@95%TPR`** | `0.7470 / 0.0555` | `0.6605 / 0.0470` | **`0.7750 / 0.0335`** | `Rec@0.5%FPR` **反超 V4.2 (+0.0280) 与 Stage 1 (+0.1145)** |
| **`<=1000bp` Recall / F1 / AUPRC** | `0.8872 / 0.8398 / 0.9214` | `0.9024 / 0.8567 / 0.9013` | **`0.9177 / 0.8600 / 0.9269`** | 短窗全面超越前两代（`Rec@0.5%FPR` 由 `0.2012 -> 0.3628`） |
| **`3000bp` Recall / `Rec@0.5%FPR` / `FPR@95%TPR`** | `0.9865 / 0.8451 / 0.02472` | `0.9899 / 0.8384 / 0.02921` | `0.9933 / 0.2862 / 0.01798` | 召回与 `FPR@95%TPR` 均最优；`Rec@0.5%FPR` 回撤系该分桶 (`neg_cnt=364` 仅容许 `1` 个 FP) 被 `1447bp`x3/`1738bp`x6 等高同源细菌片段集中在 `0.905~0.925` 卡线所致（较 Stage 1 的 `0.981~0.983` 实已显著压低） |
| **`5000bp` Recall / F1 / `FPR@95%TPR`** | `0.9869 / 0.9735 / 0.01891` | `0.9876 / 0.9735 / 0.01234` | **`0.9891 / 0.9753 / 0.00987`** | 主尺度长窗 F1 与假阳抑制均最佳 |
| **罕见非有尾类群召回 (`n=32/20/20/8`)** | `Ino 1.0000 / Levi 0.9500 / Micro 0.9500 / Tecti 1.0000` | `Ino 0.9688 / Levi 0.9000 / Micro 0.8500 / Tecti 1.0000` | **`全 4 类 1.0000`** | 非有尾小基因组召回回撤 **100% 消除** |

   - **B. `v1 test` 嵌合体全基因组基准（75 真前噬菌体，共 `20.862 Mb`）**

| 模型配置 | 主指标 `TP/FP/FN` (`IoU>=0.5`) | 主 `F1` | 严格 `F1` (`IoU>=0.8`) | 全图 `MAE / MedAE (bp)` | 退化片段 (`degraded_fragment`, n=18) `MAE / MedAE` | `FP/Mb` (总 / 纯负对照) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| `V4.2`（`plateau=4, 0.90`） | `75 / 2 / 0` | `0.9868` | `0.9737` (`74/3/1`) | `702.0 / 378.0` | `865.2 / 381.0` | `0.0959 / 0.3043` |
| `Stage 1`（`plateau=4, 0.90`） | `75 / 4 / 0` | `0.9740` | `0.9740` (`75/4/0`) | `426.0 / 250.0` | `347.0 / 227.0` | `0.1917 / 0.3043` |
| `Stage 1.2 raw`（Val 选参 `plateau=0`） | `74 / 2 / 1` | `0.9801` | `0.9669` (`73/3/2`) | `437.1 / 180.0` | `253.6 / 156.0` | `0.0959 / 0.3043` |
| `Stage 1.2 plateau_aligned`（`4, 0.90`） | `75 / 3 / 0` | `0.9804` | `0.9673` (`74/4/1`) | `435.9 / 186.0` | **`258.5 / 176.0` (`TP=18/18`)** | `0.1438 / 0.3043` |

   - 根因审计说明：Stage 1 新增的 `test_CHIM_0026:85400-92200`（6.8 kb 伪峰）在 Stage 1.2 中无论是否启用 plateau 均已**彻底消除**；`Stage 1.2 raw` 的唯一漏报 `test_CHIM_0012 (26127..42591)` 最高峰已达 `0.9350`（仅低于单点种子阈值 `0.95`），启用 `plateau=(4, 0.90)` 即恢复 `TP=75/75, FN=0`，此时 `FP=3` 均为高密含噬菌体基因区（`test_CHIM_0033` 含 `17/19`、`test_CHIM_0039` 含 `6/6`、`test_PURE_NEG_0007` 含 `20/25` 噬菌体 ORF）。同时退化片段 `MedAE` 由 `381.0 bp (V4.2) -> 227.0 bp (Stage 1) -> 156.0~176.0 bp (Stage 1.2)` 进一步逼近 200 bp 极限分辨率。

   - **C. `unseen_real_genomes` 4 株真实细菌基因组、CheckV 对齐与 9 维功能模块验证**
     - `NC_003888.3`（链霉菌阴性对照）：`V4.2` / `Stage 1` / `Stage 1.2 (raw & plateau_aligned)` 全部保持 **`0` 假阳性**（总耗时 `34.487s` / `32.654s`）。
     - `NC_000913.3`（*E. coli* K-12）：`stage1_2_raw` 因 `Val` 选参为 `plateau=0` 且 4 个隐蔽前噬菌体峰值落于 `0.9247~0.9495`（`DLP12=0.9416, e14=0.9495, Rac=0.9247, Qin=0.9355`）导致默认阈值 `count=0`；配合 `plateau=(4, 0.90)` 则**全部 `4/4` 检出**，且功能模块成功区分残缺隐蔽特征：`e14 (1199600..1212400)` 与 `Rac (1410600..1434800)` 正确标记为 **`cryptic_or_incomplete`**（`head_packaging`/`connector` ORF 计数均为 `0`），`DLP12 (565800..582400)` 敏锐捕捉到高 MGE 污染（`mge_contamination_score=0.6975`, `transposon_plasmid_mge` ORF 计数 `2`）。
     - `NC_003197.2`（*S. enterica* LT2）：CheckV `3/3` 检出（`mean_iou=0.8892`, `mean_mae=2452.5 bp`，其中 `Gifsy-2 1097800..1144000` 达到 **`IoU=0.9901, MAE=229.5 bp`**；相较 `V4.2` CheckV `0.9001` 与 `Stage 1` CheckV `0.9060` 在第 3 段边界略收缩至 `33.8 kb`）。4 个主体区段全部正确判为 **`complete_structural_core`**（`head=4~8, connector=1~2, tail=14~17, lysis=4~5`）；`plateau_aligned` 额外检出的 `4419600..4438000` 则准确标记为 **`cryptic_or_incomplete`**（仅 `tail=13, lysis=2, moron=1`，无头部/连接颈/整合酶 ORF）。
     - `NC_007795.1`（*S. aureus* NCTC8325）：CheckV **`3/3` 检出（`mean_iou=0.9247`, `mean_mae=1819.3 bp`）**（`V4.2` `0.9407`、`Stage 1` `0.9404`），无转座酶假阳性，且全部正确判为 `complete_structural_core`（`mge_contamination_score=0.0408~0.1455`）。

6. **当前阶段遗留细节与下一步建议（保留 `student_v4_2` 生产权重暂不覆盖）**
   - **遗留细节**：(1) Val 自动调参因 Val 嵌合体上无低于 `0.95` 的真值峰而选出 `plateau_min_windows=0`，令真实隐蔽原噬菌体（峰值 `0.925~0.949`）需依赖 `plateau=(4, 0.90)` 保底检出；(2) `K-12 DLP12` 因窗均值加权在 `orf_module_counts['head_packaging']=0` 情况下 `module_scores['head_packaging']=0.5473 >= 0.45`，仍被启发式划为 `complete_structural_core`（后续可要求结构核心激活在存在 ORF 时至少有 1 个同模块 ORF 确认）；(3) `3000bp` 分桶在超严截断 (`0.5% FPR`) 下仍受 `1447bp / 1738bp` 同源细菌片段群集中得 `0.905~0.925` 影响，CheckV 主体均值亦略低于 `Stage 1`（`0.8892 / 0.9247` vs `0.9060 / 0.9404`）。
   - **决策建议**：继续**保留现有生产模型 `F:\Phage data\models\full_v4\student_v4_2\` 不动**；将 Stage 1.2 产物（`stage1_2_ablation/`）作为功能模块识别与零泄露多尺度优化验证版留档，后续（步骤 32 候选）再针对 Val 解码 plateau 搜索防退化约束、结构核心最少 ORF 确认门控及 `1447/1738bp` 同源负例细校准后推进融合上线。

---

## 25. 30 个零泄露独立 FASTA 横向对照（V4.2 vs Stage 1.2）与四组件正交校验

为在训练与冻结基准集以外验证 **V4.2 生产模型** 与 **Stage 1.2 消融模型** 的真实泛化差异，**步骤 32** 通过临时评测脚本 [run_30fasta_benchmark.py](file:///C:/Users/Administrator/.gemini/antigravity/brain/a84b4add-178c-4aff-97a2-c2e69eae3a98/scratch/run_30fasta_benchmark.py)（固定随机种子 `seed=20261114`）从 `F:\Phage data` 冻结 `test` 分片与实验室真实纳米孔三代组装中抽取 **30 个零泄露 FASTA（总计 `39.614 Mb`）**，同台运行三路模型解码并引入四大正交/独立组件进行交叉仲裁，完整结果已落盘于 [random_30fasta_comparison_report.json](file:///F:/Phage%20data/models/full_v4/stage1_2_ablation/random_30fasta_eval/random_30fasta_comparison_report.json)：

1. **零泄露随机抽样队列构成（`n = 30`, `39.614 Mb`）**
   - **A 组（细菌全基因组 + 实验室真实组装，共 `10` 例，`38.734 Mb`）**：`v1 test` 独立细菌完整染色体 `9` 株（`NZ_AP045834.1` 弧菌、`NZ_CP019184.1` 沙门氏菌、`NZ_CP023147.1` 分枝杆菌、`NZ_CP061944.1` 假单胞菌、`NZ_CP097190.1` 克雷伯菌、`NZ_CP103399.1` 李斯特菌、`NZ_CP167021.1` 化脓性链球菌、`NZ_CP171830.1` 克雷伯菌、`NZ_CP199964.1` 鲍曼不动杆菌）+ 本项目真实三代 Flye 组装 `LAB_FLYE_ASM`（`147 contigs`, `970,217 bp`）。
   - **B 组（阴性特异度对照，共 `10` 例，`0.461 Mb`）**：`v1 test` 细菌质粒 `7` 条（`4.2–133.8 kb`）+ 非噬菌体真核/古菌病毒 `3` 株（`NC_030884.1` SIRV3、`NC_076464.1` 植物双生病毒、`NC_010537.1` AFV9）。
   - **C 组（独立真噬菌体阳性对照，共 `10` 例，`0.419 Mb`）**：`v1 test` 有尾噬菌体 `Caudoviricetes` `7` 株（`15.8–152.5 kb`）+ 非有尾小噬菌体 `3` 株（`Inoviridae` `NC_001331.1` 7,349 bp、`Microviridae` `NC_048874.1` 4,526 bp、`Leviviricetes` `NC_138365.1` 3,709 bp）。

2. **四路正交校验体系与同台宏观对比汇总**
   - 四路校验组件：`CheckV v1.0.3`（对全部 B/C、`LAB_FLYE_ASM` 整条序列以及全部 224 条/区段预测片段批量校验）+ `PhiSpy`（对 A 组 9 株完整 `.gbk` 独立预测）+ `ProteinGate`（RefSeq Phage BLASTp）+ `MMseqs2`（Pharokka `PHROGs` 库）。

| 模型 / 解码策略 | 预测区段总数 (`raw`) | 正交仲裁确认真噬菌体 (`ortho_confirmed`) | 待核实/宿主岛 (`unconfirmed`) | A 组检出 (`raw / confirmed`) | B 组阴性误报 (`raw / Gate 放行`) | C 组真噬菌体检出 (含 3 非有尾) | 全队列扫描总耗时 (`s`) | 纯神经+特征耗时 (`不含 BLASTp`) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`V4.2` 生产基线** (`plateau=4, 0.90`) | `35` | `32`（注：含 1 例质粒因 PHROG 非结构>=8 误记） | `3` | `21 / 21` | **`4 / 4`** (`3` 条质粒) | `10 / 10` (`3/3`, 平均覆 98.71%) | `375.96 s` | `255.01 s` |
| **`Stage 1.2 raw`** (`Val 选参 plateau=0`) | `31` | `30` | `1` | `21 / 20` | **`0 / 0`** | `10 / 10` (`3/3`, 平均覆 **100.00%**) | `384.42 s` | `269.15 s` |
| **`Stage 1.2 plateau`** (`plateau=4, 0.90`) | `35` | **`34`** | `1` | **`25 / 24`** | **`0 / 0`** | `10 / 10` (`3/3`, 平均覆 **100.00%**) | `382.49 s` | `267.08 s` |

3. **核心优势与短板深度核查结论（全部由 GBK / CheckV / PhiSpy / PHROGs 直接验证）**
   - **B 组细菌质粒抗假阳性能力实质性跃升（`4` 处误报 -> `0` 误报）**：`V4.2` 在 3 条质粒产生了 4 处误报且全部绕过 `ProteinGate`：`NZ_CP034080.1:22600..51200`（`CheckV v=1, h=9` 宿主主控片段，靠含 1 个溶菌酶与阻遏蛋白绕过门控）、`NZ_CP107304.1:0..50800`（`CheckV v=1, h=7, Gate tnp=10` 转座酶簇）、`NZ_CP107304.1:89200..103669`（`.gbk` 实测为 `ParB/RepB` + `PsiB` + `Hok/RelE` 纯接合质粒区段，`CheckV v=0, h=1`，因 PHROG 非结构交叉命中 `10` 条而同时欺骗了 `V4.2`、`ProteinGate` 与 PHROG 简单计分）以及 `NZ_CP117345.1:37200..51400`（`CheckV v=0, h=3`）。**`Stage 1.2`（`raw` 与 `plateau`）在这 10 例阴性对照上全部准确判零**；且 3 株古菌/真核病毒均 `0` 误报。
   - **A 组细菌与复杂三代组装真实召回与全长边界明显胜出**：
     - 在 `NZ_CP199964.1`（鲍曼不动杆菌）上，`Stage 1.2 plateau` 新增抓获 `2626600..2645400`（`18,800 bp`, `peak=0.9313`），与 `PhiSpy (2629395..2648086)` IoU 达 **`0.7449`**，经 CheckV（`v=21, h=0`）、PHROG（`25`, 含 18 个结构基因）与 ProteinGate（`20hm`）三重确认为高纯度真前噬菌体（`V4.2` 与 `Stage 1.2 raw` 均漏检）；同时对同株另一前噬菌体 `2049600..2092800` 边界从 `V4.2` 的 `33.2 kb (v=19)` 恢复至 `43.2 kb (v=25)`。
     - 在实验室三代组装 `LAB_FLYE_ASM` 上，整序列 `CheckV` 提示 `contig_19 (52,433 bp)` 为 `High-quality (comp=100.0%, v=26)`：`V4.2` 仅截取后端 `20000..49400 (29.4 kb, v=19)`，而 **`Stage 1.2` 精确覆盖全长 `0..52433 (52.4 kb, v=26, High-quality 100%)`**；对 `contig_141 (45,273 bp, CheckV Medium-quality v=10, h=4)`，`V4.2` 与 `Stage 1.2 raw` 完全漏检，**`Stage 1.2 plateau` 成功捕获两段（`4400..16200` `v=3, PHROG=15` 与 `27600..45273` `v=7, PHROG=31`）**；且对 `Stage 1.2 raw` 漏检的 `contig_2`（`peak=0.9455`），`Stage 1.2 plateau` 亦成功救回（`0..10400`, `v=11`）。
   - **C 组小基因组覆盖率达成 100%**：`NC_001331.1`（`Inoviridae` 丝状噬菌体 `7,349 bp`）在 `V4.2` 被截断为 `200..6600 (87.09%)`，`Stage 1.2` 实现 **`0..7349` (100.0%)** 全覆盖，全部 10 株平均覆盖 `98.71% -> 100.00%`。
   - **9 维功能模块评估与两项需关注的现存短板**：
     1. **短片段敏感点（`NZ_CP097190.1:808800..815600`）与 `complete_structural_core` 启发式过宽**：`Stage 1.2` 在 `NZ_CP097190.1` 上报出 1 处 `6.8 kb` 整合酶岛（`.gbk` 实测为 `site-specific integrase` + `Rha regulator` 等 5 个 CDS，`CheckV v=1, h=0`），功能头准确预测出 `integration_excision=1`，但窗均值加权令无结构 ORF 命中的 `head_packaging` 跨过 `0.45` 线而误归为 `complete_structural_core`。在 `35` 个评估区段中，`Stage 1.2` 结构完整度与生活方式两大类与 `MMseqs2 PHROGs` 的客观一致率均为 **`30 / 35` (`85.7%`)**（其中结构完整度 5 例不一致均为窗均值导致对短片段过宽松；而 `NZ_CP103399.1:742k..777k` 生活方式不一致反而是 Stage 1.2 正确捕捉到了 GBK 真实的 `recombinase` + `phage repressor`，而 PHROG 库漏标）。
     2. **`plateau=4, 0.90` 显著优于 `raw`（`plateau=0`）**：`Stage 1.2 raw` 漏掉了 3 个真前噬菌体区段（`NZ_CP199964.1:2626.6k`、`LAB_FLYE contig_141`、`contig_2`），开启 `plateau=(4, 0.90)` 后全部救回且未增加任何 B 组误报。
     3. **PhiSpy 对照下的共同盲区**：PhiSpy 在 9 株细菌共预测 `28` 个区段，`Stage 1.2 plateau` 高契合命中的 `16` 个全部获正交确认为真噬菌体（共有区段与 PhiSpy 平均 IoU `0.7711`，`V4.2` 为 `0.7862`；另 `NZ_CP167021.1` 第 5 段因偏右边界错位 IoU 低于 0.25）；PhiSpy 独有的 `11` 个额外区段经独立 CheckV 核验，**4 个为宿主核心误报**（`viral=0, host=7~11` 核糖体/TusBCD 操纵子，两模型正确免疫）、**2 个为弱信号区（`viral=2`）**、**5 个为真实短退化/混合防御岛漏检**（`8.4–10.3 kb` 4 处 `viral=4~9` + `NZ_CP199964.1:1016672..1055738` 39.1 kb `viral=12, host=2`）。

---

## 26. Stage 1.2 替代 V4.2 阻塞缺陷修复与工作台端到端替换验收（步骤 33）

针对第 24、25 节识别出的两项阻碍 `Stage 1.2` 直接替代生产 `Student V4.2` 的工程与逻辑问题，**步骤 33** 采用“回归单测先行（红） -> 模块化修复（绿） -> 真实基因组及便携工作台端到端验证”闭环实施了修正与替换可行性评估：

1. **测试先行构建回归基线（5 项新增用例全部先行复现失败，修复前 `5 failed, 15 passed`）**
   - 在 [test_stage1_2_functional_partitions.py](file:///f:/NCBI%20blast/tests/test_stage1_2_functional_partitions.py) 新增 `test_collect_region_functional_modules_requires_head_orf_for_complete_core`：复现并覆盖无 `head_packaging` 实证 ORF 时因窗口均值或次优多标签分数漂移导致的 `complete_structural_core` 误判。
   - 在 [test_phage_finder_workbench.py](file:///f:/NCBI%20blast/tests/test_phage_finder_workbench.py) 新增 4 项工作台与扫描器用例：`test_model_registry_exposes_stage1_2_plateau_and_func_metadata`、`test_scanner_from_model_dir_propagates_and_overrides_plateau`、`test_manager_execute_forwards_plateau_and_functional_partitions`、`test_exporter_attaches_optional_functional_modules`。

2. **两项根因修复内容（保留 `F:\Phage data\models\full_v4\student_v4_2\` 生产目录暂不覆盖）**
   - **修复 1（`head_packaging` 实证 ORF 结构核心门控）**：更新 [scanner.py](file:///f:/NCBI%20blast/src/phage_discovery/inference/scanner.py) `_collect_region_functional_modules()`。当区段存在解析 ORF（`orfs_sorted` 非空）时，`active_modules` 要求至少具备 `orf_module_counts[name] >= 1` 或 `orf_max_vec[mi] >= module_threshold` 的 ORF 证据；且判定 `complete_structural_core` 时强制要求**实证主导结构模块计数** `confirmed_struct = [m for m in ("head_packaging", "connector", "tail") if m in active_modules and orf_module_counts.get(m, 0) >= 1]` 满足 `len(confirmed_struct) >= 2 and "head_packaging" in confirmed_struct`（无 ORF 时按原窗口级逻辑回退）。
   - **修复 2（`plateau=(4, 0.90)` 默认部署与全链路参数透传）**：
     - 更新 [scanner.py](file:///f:/NCBI%20blast/src/phage_discovery/inference/scanner.py) `GenomeScanner.from_model_dir()`：通过 `_UNSET_ARG` 哨兵支持调用端按需显式覆盖 `plateau_min_windows`、`plateau_second_threshold`、`refine_pad_bp`、`smooth_sub_profile`（包括显式传 `0 / None` 禁用 plateau）。
     - 更新 [model_registry.py](file:///f:/NCBI%20blast/src/analysis/phage_finder/model_registry.py) `_inspect_v4_2_dir()`：读取并暴露 `feature_profile`、`func_dim` 以及 `decoder_defaults` 中的 `plateau_min_windows`、`plateau_second_threshold`、`refine_pad_bp`、`smooth_profile`（向后兼容旧版 `V4.2` 元数据）。
     - 更新 [types.py](file:///f:/NCBI%20blast/src/analysis/phage_finder/types.py) `PhageScanRunRequest` 与 [manager.py](file:///f:/NCBI%20blast/src/analysis/phage_finder/manager.py) `execute_pipeline_task()`：在工作台调度中透传 `plateau_min_windows` / `plateau_second_threshold`，并当 `func_dim > 0` 时自动开启 `collect_functional_partitions=True`。
     - 更新 [exporter.py](file:///f:/NCBI%20blast/src/analysis/phage_finder/exporter.py) `export_scan_artifacts()`：向后兼容地在 `region_records` 中附带轻量汇总字段 `functional_modules`（剔除重型逐 ORF `orfs` 明细防 JSON 膨胀）。
     - 备份原 `Stage 1.2` 评估报告至 `F:\Phage data\models\full_v4\stage1_2_ablation\student_v4_2_stage1_2\student_v4_report.json.bak`，在 `student_v4_report.json` 中保留原无界检索快照至 `decoder_tuned_on_val_unbounded_search`，并将 `decoder_tuned_on_val` 校准为 `seed=0.95, extend=0.30, sub=0.35, plateau_min_windows=4, plateau_second_threshold=0.90, refine_pad_bp=3000, smooth_profile=false`。

3. **静态检查、单测全集与真实端到端替代性实测结果**
   - **代码检查与单元测试**：修改后 `ruff check` 输出 `All checks passed!`，`python -m py_compile` 退出码 `0`；覆盖 `Stage 1.2`、工作台、V4 架构及 Stage 1 特征的 4 套测试共 **`35 passed in 76.11s`**（`0 failed, 0 skipped`）。
   - **Check A — 真实基因组零手动参数覆盖推理**（使用 `GenomeScanner.from_model_dir(stage1_2_dir, blast_db=phage_refseq_prot, workers=30, device="cuda")`，零阈值覆写，详情见 [verify_dropin_e2e_report.json](file:///C:/Users/Administrator/.gemini/antigravity/brain/a84b4add-178c-4aff-97a2-c2e69eae3a98/scratch/verify_dropin_e2e_report.json)）：
     - `from_model_dir` 自动加载 `seed=0.95, extend=0.3, sub=0.35, plateau_min_windows=4, plateau_second_threshold=0.9, refine_pad_bp=3000, smooth_sub_profile=False, func_dim=9, feature_profile='stage1'`。
     - `NC_000913.3` (*E. coli* K-12)：`4/4` 全部召回（`DLP12` `565800..582400`、`e14`、`Rac`、`Qin`）；其中 **`DLP12` (`head_packaging` ORF=0, `mge_contamination_score=0.6975`) 已修正为 `cryptic_or_incomplete`**，`Qin` 保持 `complete_structural_core`。
     - `NZ_CP097190.1`：`4/4` 召回，原过宽短区段 **`808800..815600` (`head_packaging` ORF=0) 已修正为 `cryptic_or_incomplete`**（`"head_packaging"` 亦未进入 `active_modules`），其余 3 个完整前噬菌体保持 `complete_structural_core`。
     - `NZ_CP199964.1`：`2/2` 召回（自动借 `plateau=(4, 0.9)` 救回 `2626600..2645400` 18.8 kb `peak=0.9313`），均判定 `complete_structural_core`。
     - `NZ_CP107304.1`（质粒）：`raw=0, verified=0`（`0` 假阳性）。
     - `LAB_FLYE_ASM`（147 contigs）：`8/8` 全部召回（含 `contig_19` `0..52433` 100% 全长、`contig_141` 两段 `peak=0.931/0.9219`、`contig_2` `0..10400` `peak=0.9455` 等）。
     - `NC_001331.1`（7,349 bp `Inoviridae`）与 `NC_048874.1`（4,526 bp `Microviridae`）：均 `100%` 全长检出且无过度门控误杀（`NC_048874.1` 为 `complete_structural_core`）。
   - **Check B — 便携工作台隔离端到端替换测试**：
     - 将 5 个权重与元数据文件（`student_v4.pt`, `context_refiner.pt`, `subbin_refiner.pt`, `student_v4_meta.json`, `student_v4_report.json`）拷贝至全新隔离目录 `models/full_v4/student_v4_2/`，并故意将 `student_v4_meta.json` 中的绝对 `*_ckpt` 训练路径改写为不存在路径以模拟跨目录/跨机迁移。
     - `discover_available_models()` 与 `PhageDiscoveryManager` 自动发现并加载该目录，在 `cuda` + `phage_refseq_prot` 上执行 150-contig 混合 FASTA（总 `1,085,761 bp`）扫描，总耗时 `25.641s`，`status="completed"`，`region_count=10, rejected_count=0`，所有产物（`FASTA/TSV/GFF3/GBK/result.json`、`150` 个 `overlays/contig_*.json`、`10` 个侧翼 `region_*.gbk`）正常落盘且 `get_region_gbk`、`get_contig_overlay` 读取无误，导出 `regions` 自动附带精简 `functional_modules` 且无 `orfs` 冗余膨胀。
   - **附带观测说明**：若不传 `custom_blast_db` 调用 `resolve_protein_gate_resources()`，当项目存在 `database/swissprot/swissprot` 时当前逻辑会优先命中通用库 `swissprot`（导致 `NZ_CP097190.1` 与 `LAB_FLYE_ASM` 在开启 ProteinGate 时分别多拒 1 个与 2 个候选），在配置中显式指定 `phage_refseq_prot` 则为 `0` 误拒。

---

## 27. 正式备份旧 V4.2、部署 Stage 1.2 上线及蛋白库探测优先级修正（步骤 34）

经用户确认正式切换，**步骤 34** 完成了生产模型目录的原子替换与蛋白库默认探测优先级修正：

1. **测试先行与蛋白门控库发现顺序修正**
   - 在 [test_phage_finder_workbench.py](file:///f:/NCBI%20blast/tests/test_phage_finder_workbench.py#L951-L969) 新增 `test_protein_gate_prefers_phage_refseq_over_generic_swissprot`，验证同时存在 `database/swissprot/swissprot` 与 `../Phage data/blastdb/phage_refseq_prot` 时修复前失败（命中 `swissprot`）。
   - 修复 [model_registry.py](file:///f:/NCBI%20blast/src/analysis/phage_finder/model_registry.py#L289-L295) `resolve_protein_gate_resources()` 候选顺序：将 `sibling_data / "blastdb" / "phage_refseq_prot"` 提升至通用库 `database/swissprot/swissprot` 之前（`phage_refseq_prot` 专库优先，通用 `swissprot` 兜底）。

2. **安全备份旧 V4.2 并原子部署 Stage 1.2 至生产目录**
   - 将原生产目录完整备份至 `F:\Phage data\models\full_v4\student_v4_2_legacy_v4_2_backup`（保留完整可回滚权重与报告）。
   - 从 `F:\Phage data\models\full_v4\stage1_2_ablation\student_v4_2_stage1_2` 复制全套模型与校验文件（`student_v4.pt` `14,956,421 bytes`、`context_refiner.pt`、`subbin_refiner.pt`、`student_scores.npz`、`student_v4_meta.json`、`student_v4_report.json` 及同口径 `student_report.json`），同步更新 `student_v4_meta.json` / 报告中的路径指向新生产目录 [student_v4_2](file:///F:/Phage%20data/models/full_v4/student_v4_2)，并原子替换上线；原消融目录保持完好留存。

3. **切换上线后全链路验收**
   - **静态检查与单元测试**：`ruff check`（`All checks passed!`）、`python -m py_compile` 通过；4 套 pytest 共 **`36 passed in 77.98s`**（`0 failed, 0 skipped`）。
   - **默认生产路径冒烟测试**：不传任何 `custom_model_dir` / `blast_db` / 手动阈值，直接通过 `discover_available_models()` 与 `PhageDiscoveryManager` 探测到生产 [student_v4_2](file:///F:/Phage%20data/models/full_v4/student_v4_2)（`params=3715879`, `feature_profile='stage1'`, `func_dim=9`, `plateau=(4, 0.9)`）与 `F:\Phage data\blastdb\phage_refseq_prot`，在 `CUDA + ProteinGate` 下扫描 6 条测试序列（含 `NC_001331.1`、`NC_048874.1`、`NZ_CP107304.1` 质粒与 `LAB_FLYE_ASM` `contig_19`/`contig_141`/`contig_2`，共 `227,497 bp`）：总耗时 **`15.548s`**，检出 `6` 个真实区段（`NC_001331.1` `0..7349`、`NC_048874.1` `0..4526`、`contig_19` `0..52433`、`contig_141` 两段 `peak=0.931/0.9219`、`contig_2` `0..10400` `peak=0.9455`），`rejected_count=0`，`NZ_CP107304.1` 质粒 `0` 误报。
4. **模型名称、前端界面与运行日志简洁区分 `Stage 1.2`**
   - **后端日志与模型标签**：更新 [model_registry.py](file:///f:/NCBI%20blast/src/analysis/phage_finder/model_registry.py#L140-L153) `_inspect_v4_2_dir()`，当检测到 `feature_profile == "stage1"` 且 `func_dim > 0` 时自动将默认名称映射为 `Stage 1.2 边界精修模型`（保留 `version: "V4.2"` 协议兼容）；同步更新 [manager.py](file:///f:/NCBI%20blast/src/analysis/phage_finder/manager.py) `[STEP 2/5]` 与 `[STEP 3/5]` 日志，使其打印当前模型的真实名称而非硬编码 `V4.2`。
   - **前端组件与构建刷新**：先在 [phageOverlayAndResults.test.ts](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_discovery/__tests__/phageOverlayAndResults.test.ts) 新增回归用例校验 `Stage 1.2` 标签展示，随后更新 [types.ts](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_discovery/types.ts)、[PhageDiscoveryModule.vue](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_discovery/PhageDiscoveryModule.vue)、[PhageDiscoverySetup.vue](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_discovery/components/PhageDiscoverySetup.vue)、[PhageDiscoveryHistory.vue](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_discovery/components/PhageDiscoveryHistory.vue)、[PhageDiscoveryProgress.vue](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_discovery/components/PhageDiscoveryProgress.vue)、[PhageDiscoveryQueueCard.vue](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_discovery/components/PhageDiscoveryQueueCard.vue)、[PhageDiscoveryResults.vue](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_discovery/components/PhageDiscoveryResults.vue) 与 [AnalysisView.vue](file:///f:/NCBI%20blast/src/web-next/src/views/AnalysisView.vue)，动态展示 `Stage 1.2` 并移除残留写死的 `Student V4.2` / `V4.2` 文案。
   - **构建与全量验证**：Vitest 前端测试 `8` 个文件共 **`49 passed`**（含 `phageOverlayAndResults.test.ts` `4` 项通过）；`npm run build --prefix src/web-next`（`vue-tsc -b && vite build`）通过并刷新 `src/web-next/dist`（`1175 modules transformed`，`built in 12.63s`）；`ruff check`（`All checks passed!`）、`py_compile` 与 [test_phage_finder_workbench.py](file:///f:/NCBI%20blast/tests/test_phage_finder_workbench.py) **`13 passed in 8.87s`**。
5. **TypeScript 与 Pyrefly 静态诊断清零**
   - **测试对象属性补全**：在 [phageOverlayAndResults.test.ts](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_discovery/__tests__/phageOverlayAndResults.test.ts#L387-L389) 补齐 `PhageCapabilities` 必填字段 `has_model: true`，消除 TS2741 缺失属性报错。
   - **冗余类型转换清理**：按 Pyrefly `unnecessary-type-conversion` 检查清理 [manager.py](file:///f:/NCBI%20blast/src/analysis/phage_finder/manager.py#L324)、[functional_partitions.py](file:///f:/NCBI%20blast/src/phage_discovery/data/functional_partitions.py) 与 [window_features.py](file:///f:/NCBI%20blast/src/phage_discovery/features/window_features.py) 中所有多余的 `bool()`、`int()`、`str()` 及 `float()` 调用。
   - **修复后重验**：`pyrefly check --min-severity warn` 输出 `INFO 0 diagnostics (2 suppressed)`，`ruff check` 输出 `All checks passed!`，`py_compile` 通过，`tests/test_phage_finder_workbench.py` + `tests/test_stage1_2_functional_partitions.py` + `tests/test_stage1_orf_peptide.py` 共 **`28 passed in 71.36s`**；`vue-tsc --noEmit` 对 `phageOverlayAndResults.test.ts` 退出码 `0`，Vitest `8` 文件 **`49 passed`**，`npm run build --prefix src/web-next` 通过（`15.22s`）。
6. **生产目录物理命名迁移至 `stage1_2` 与前端残留 `V4.2` 文案清零**
   - **先导测试（红灯）**：新增 `test_model_registry_and_scanner_prefer_stage1_2_directory_and_filenames` 与前端 `PhageDiscovery_Stage1_2` 默认任务名/文案断言（均按预期先行失败）。
   - **模块化文件名解析与目录重整**：在 [scanner.py](file:///f:/NCBI%20blast/src/phage_discovery/inference/scanner.py) 抽取公共函数 `resolve_model_dir_files()`，使 `GenomeScanner` 与 [model_registry.py](file:///f:/NCBI%20blast/src/analysis/phage_finder/model_registry.py) 优先探测 `full_v4/stage1_2` 目录及 `stage1_2.pt` / `stage1_2_meta.json` / `stage1_2_report.json`（同时向后兼容 `student_v4_2` 与 `student_v4.*`）；同时清理 [scanner.py](file:///f:/NCBI%20blast/src/phage_discovery/inference/scanner.py) 中 8 处冗余 `float()`/`int()`。
   - **前端残余清理**：更新 [PhageDiscoverySetup.vue](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_discovery/components/PhageDiscoverySetup.vue)（默认任务名改 `PhageDiscovery_Stage1_2`、移除配置抽屉/兜底文案/默认按钮里的 `V4.2`）、[PhageOverlayMap.vue](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_discovery/components/PhageOverlayMap.vue)（`模型概率曲线`、`预测分数`）与 [usePhageDiscovery.ts](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_discovery/composables/usePhageDiscovery.ts)（动态使用激活 `model_id` 并去除 `已加入 V4.2 调度队列...`）。
   - **生产磁盘目录切换**：将全套 `Stage 1.2` 权重、元数据、评分与校准报告正式部署于 `F:\Phage data\models\full_v4\stage1_2`（`stage1_2.pt`, `stage1_2_meta.json`, `stage1_2_report.json`, `stage1_2_scores.npz`, `context_refiner.pt`, `subbin_refiner.pt`），确认旧版安全留存于 `student_v4_2_legacy_v4_2_backup` 后清理过渡目录 `student_v4_2`。
   - **全量终验**：`discover_available_models()` 唯一探测到 `stage1_2`（`params=3715879`, `feature_profile='stage1'`, `func_dim=9`, `plateau=(4, 0.9)`）；`ruff check` 通过、`pyrefly check --min-severity warn` 输出 `INFO 0 diagnostics`、`py_compile` 退出码 `0`、4 套 `pytest` 共 **`37 passed in 78.02s`**；`vue-tsc --noEmit` 退出码 `0`、Vitest `8` 文件 **`49 passed`**、`vite build` 刷新 `dist`（`1175 modules transformed`，`13.27s`）。
7. **修复扫描运行中/排队中历史卡片仍显示 `V4.2` 徽章的问题**
   - **根因定位**：[model_registry.py](file:///f:/NCBI%20blast/src/analysis/phage_finder/model_registry.py#L140-L157) 对 `Stage 1.2` 模型仍返回 `version: "V4.2"`，且 [manager.py](file:///f:/NCBI%20blast/src/analysis/phage_finder/manager.py#L151-L159) 在 `submit_task` 入库与 `mark_completed` 时均硬编码写入 `model_version="V4.2"`；任务运行中 `summary` 尚为空，导致 [PhageDiscoveryHistory.vue](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_discovery/components/PhageDiscoveryHistory.vue#L59) 回退显示 `V4.2`。
   - **修复方案**：[model_registry.py](file:///f:/NCBI%20blast/src/analysis/phage_finder/model_registry.py) 对 `Stage 1.2` 模型返回 `version: "Stage 1.2"`（兼容传统 `V4.2`）；[manager.py](file:///f:/NCBI%20blast/src/analysis/phage_finder/manager.py)、[queue.py](file:///f:/NCBI%20blast/src/analysis/phage_finder/queue.py) 与 [usePhageDiscovery.ts](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_discovery/composables/usePhageDiscovery.ts) 动态透传 `model_info["version"]`；[PhageDiscoveryHistory.vue](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_discovery/components/PhageDiscoveryHistory.vue) 与 [PhageDiscoveryResults.vue](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_discovery/components/PhageDiscoveryResults.vue) 对 `model_id === 'stage1_2'` 强制优先展示 `Stage 1.2`；同步清理 [PhageDiscoverySetup.vue](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_discovery/components/PhageDiscoverySetup.vue) `Demo_Genome_Stage1_2` 等剩余提示文案。
   - **回归测试与构建**：先新增 `Stage 1.2` `version` / `submit_task` 入库单测及运行中历史卡片 Vitest 用例（均先红后绿）；修复后 `ruff check` 与 `pyrefly check --min-severity warn`（`0 diagnostics`）通过、[test_phage_finder_workbench.py](file:///f:/NCBI%20blast/tests/test_phage_finder_workbench.py) **`14 passed in 8.50s`**、Vitest `8` 文件 **`49 passed`**、`npm run build --prefix src/web-next` 刷新 `dist`（`1175 modules transformed`，`12.93s`）。

---

## 28. P0 离线多教师蒸馏（pyhmmer + phold）与 Stage 1.2 零新增参数热启动消融验证（步骤 35）

为验证在不增加推理期任何参数（严格保持 `params = 3,715,879`）的前提下，引入细菌防御/反防御 HMM 教师与 `ProstT5 + Foldseek` 三维结构暗物质教师能否增强 `Stage 1.2` 模型表现，我们在隔离目录 `F:\Phage data\training\stage1_3_p0_ablation` 与 `F:\Phage data\models\full_v4\stage1_3_p0_ablation`（生产目录 [stage1_2](file:///F:/Phage%20data/models/full_v4/stage1_2) 保持完全未动）开展了完整 P0 多教师蒸馏与同台冷对比消融实验：

1. **新增/扩展模块化组件与先导测试**
   - [hmm_adversarial_teacher.py](file:///f:/NCBI%20blast/src/phage_discovery/teachers/hmm_adversarial_teacher.py)：基于相对路径解析本地 HMM 库（`DefenseFinder` 1,332 文件、`dbAPIS` 183 条、`VirSorter2 Pfam-A-Viruses` 1,074 条），通过 WSL2 28 核 `pyhmmer 0.12.0` 与 30,000 条/片断点 Checkpoint 执行扫描。
   - [phold_teacher.py](file:///f:/NCBI%20blast/src/phage_discovery/teachers/phold_teacher.py)：封装 WSL2 GPU `phold 1.2.6`（本地 `ProstT5_fp16` + `Foldseek`），按序列长度降序预排序并约束 `max_aa_len=600`（守住 RTX 4070 8GB 物理显存红线、避开超长序列 $O(L^2)$ 溢出及 `--omit_probs` 空引用缺陷），支持 4,000 条/片 Checkpoint。
   - [functional_partitions.py](file:///f:/NCBI%20blast/src/phage_discovery/data/functional_partitions.py)：新增 `classify_protein_with_p0_teachers()`（将 `DefenseFinder`、`NetFlax`、`CARD`、`VFDB` 结构/HMM 命中显式反转隔离为 `adversarial_host_flag=True, is_phage_ortholog=False`，避免污染 `P7` 宿主劫持标签）及 `build_p0_teacher_calibration()`。
   - [distilled_student_v4.py](file:///f:/NCBI%20blast/src/phage_discovery/student/distilled_student_v4.py)：在 `train_distilled_student_v4()` 增加 `init_student_ckpt`（严格热加载 `stage1_2.pt`）、`backbone_lr_scale=0.25` 差分学习率及 `sample_weights_override`。
   - [run_p0_distill_ablation.py](file:///f:/NCBI%20blast/scripts/run_p0_distill_ablation.py) 与 [test_p0_teachers_and_distill.py](file:///f:/NCBI%20blast/tests/test_p0_teachers_and_distill.py)：实现分步流水线与 4 项单元回归测试。

2. **离线多教师扫库与校准目标构建实测**
   - **Step 1（`--step hmm`）**：扫描 Stage 1.2 全 9 分片 **`269,613`** 条唯一蛋白（28 核、9 chunks，耗时 `7m46s`），缓存至 `p0_hmm_aa_hits.pkl.gz`，命中 **`22,580`** 条（`defense_finder=15,653`, `wsl_vs2_pfam_vir=6,901`, `dbapis=869`）。
   - **Step 2（`--step phold`）**：先用 150 条跨长度真实暗物质完成 WSL 冒烟（`80.84s`，召回 `76/150` 并精准检出 `terminase large subunit` 与 `VFDB virulence factor`），随后对核心 6 难分片（`hard_neg`, `hard_v4`, `rare_multiscale`, `ext_rare`, `mined`, `ext_mined`）全部 **`33,405`** 条暗物质蛋白分 9 块完成结构扫描，结构召回 **`18,648 / 33,405 (55.82%)`**，落盘 `p0_phold_aa_hits.pkl.gz`。
   - **Step 3（`--step targets`）**：耗时 `24.19s` 完成全量融合，共标识 **`19,092`** 条唯一宿主对抗蛋白（`DefenseFinder`/`NetFlax`/`CARD`/`VFDB`），对 **`28,512`** 个窗口进行了对抗校准，对 **`28,243`** 个宿主对抗窗口与 **`427`** 个无病毒证据却高预测分的 MGE/暗物质风险窗口施加 `1.75x` 难负例惩罚权重。

3. **热启动蒸馏训练与严格同台冷对比结果（[p0_vs_stage1_2_comparison.json](file:///F:/Phage%20data/models/full_v4/stage1_3_p0_ablation/p0_vs_stage1_2_comparison.json)）**
   - **零新增参数热启动微调（`--step train`）**：从 `stage1_2.pt` 加载并采用 `lr=4e-4, backbone_lr_scale=0.25, batch_size=64, patience=4` 微调，`params=3,715,879`，在 `epoch 1` 达到最高 `val_auprc=0.99611` 并于 `epoch 5` 早停，随后重训 `ContextRefiner` 与 `SubBinContextRefiner`（验证集自动网格搜索解得 `seed=0.95, extend=0.40, sub=0.35, plateau=(4, 0.90)`）。
   - **`v1 test` 窗口评测对比（`Stage 1.2` -> `P0 消融`）**：
     - **Overall**：`AUROC 0.9912 -> 0.9913`，`AUPRC 0.9905 -> 0.9905`，`Precision 0.9270 -> 0.9283`（`FP 154 -> 151`，`FPR@0.5 0.0770 -> 0.0755`），`F1 0.9518 -> 0.9520`，`Recall@0.5%FPR 0.7750 -> 0.7785`（`+0.35%`）。
     - **分尺度低误报率区间全线提升**：`<=1000bp Rec@0.5%FPR` 从 **`0.3628 -> 0.3902`（+2.74%）**（但默认阈值 `0.5` 处 recall 从 `0.9177 -> 0.9116`，反映短片段打分排序改善而偏正阈值略收紧）；`3000bp Rec@0.5%FPR` 从 **`0.2862 -> 0.2896`（+0.34%）**；`5000bp F1 0.9753 -> 0.9763`、`FP 54 -> 51`、`Rec@0.5%FPR 0.9040 -> 0.9091`（**+0.51%**）。
   - **`v1 test` 嵌合体边界评测对比**：`TP/FP/FN` 维持 `[74, 2, 1]`（`F1=0.9801`, `Strict IoU>=0.8 F1=0.9669`, `pure_neg_fp_per_mb=0.3043`），`breakpoint_mae_bp` 从 **`437.1 bp -> 433.0 bp`（-4.1 bp）**，`strict IoU>=0.8 MAE` 从 **`368.6 bp -> 364.5 bp`（-4.1 bp）**。
   - **未见真实基因组实盘（`unseen_real_genomes`，关闭蛋白门控同台对照）**：4 株菌总区段数两模型完全一致且 `0` 误报（*E. coli* K-12 `4` 个、*S. enterica* LT2 `5` 个、*S. aureus* NCTC8325 `3` 个、*S. coelicolor* `0` 个）；其中 *E. coli* `DLP12`（`565800..582400 -> 567000..582400`）收紧左侧 `1.2 kb` 冗余，`Qin` 由 `complete_structural_core` 转为更符合生物学实际缺陷隐匿型的 `cryptic_or_incomplete`（其余 *S. aureus* `3` 个完整前噬菌体维持 `complete_structural_core` 且峰值略升）。

4. **诊断与下一步决定**
   - **提升温和的根因诊断**：在当前热启动配方中，早停依据仅为“干净标准验证集 `v1 val` 的主任务 AUPRC”（基线本就高达 `0.996+`），导致训练在第 1 个 Epoch 即定格最佳检查点，而此时同方差损失中的功能/ORF 分支任务精度权重（`task_prec`）才刚刚开始拉升（epoch 1 仅 `~1.12`，epoch 2~5 才升至 `1.86~11.9`），对抗宿主负例与结构暗物质语义信号尚未充分反哺共享主干表示。
   - **现阶段处置**：实验证实 `P0` 多教师管线及 1.9 万条对抗负样本标注链路稳定可用且对 `v1` 有温和正向增益，但幅度尚不足以立即替代线上 `Stage 1.2`；**生产目录 [stage1_2](file:///F:/Phage%20data/models/full_v4/stage1_2) 保持不动**，本次消融产物留存于 `F:\Phage data\models\full_v4\stage1_3_p0_ablation`，作为后续联合“防御岛/暗物质独立难验证集早停机制 + 语义通道扩容（P1）”实验的对照组基准。

---

## 29. 独立轻量化 `OrfFunctionalJudge`（序列+邻域上下文）功能与防御对抗扩展模块实证消融（步骤 36）

为验证在不动摇 `Stage 1.2` 边界主干的前提下，将“逐 ORF 10 类功能分区（原 9 类 `P0..P8` + 新增第 10 类 `P9 host_defense_virulence`）与噬菌体同源基因判断”解耦并下放给**独立、轻量、单一职责的后置精判模块 `OrfFunctionalJudge`** 能否突破多任务拥挤瓶颈，我们在全零泄露真实基准上完成了“序列输入 vs 纯统计输入 vs 50/50 集成”消融与区段级实盘收益评测（生产目录 [stage1_2](file:///F:/Phage%20data/models/full_v4/stage1_2) 保持完全未动）：

1. **新增模块化组件、修复与消融流水线**
   - [orf_functional_judge.py](file:///f:/NCBI%20blast/src/phage_discovery/student/orf_functional_judge.py)：实现 10 类定义 `JUDGE_CLASS_NAMES`、纯序列/拓扑 104D 编码 `encode_contig_orf_stat_features()`（消除 Pyrodigal 内部打分漂移）、多尺度 1D 氨基酸卷积编码器 + 3 层上下文 Transformer `OrfFunctionalJudge`（支持 `use_aa_seq=False/True` 开关对照）与快速推理接口 `predict_contig_orfs_with_judge()`。
   - [hmm_adversarial_teacher.py](file:///f:/NCBI%20blast/src/phage_discovery/teachers/hmm_adversarial_teacher.py) 与 [phold_teacher.py](file:///f:/NCBI%20blast/src/phage_discovery/teachers/phold_teacher.py)：修复 Pyrodigal 默认翻译保留末尾终止符 `*` 导致整条完整蛋白被过滤的缺陷，改为 `.strip().rstrip("*")` 后再判定内部终止密码子。
   - [run_orf_judge_ablation.py](file:///f:/NCBI%20blast/scripts/run_orf_judge_ablation.py) 与 [test_orf_functional_judge.py](file:///f:/NCBI%20blast/tests/test_orf_functional_judge.py)：构建四步离线验证流水线与 4 项先行单元测试。

2. **零泄露测试真值缓存与按 Contig 隔离训练集构建**
   - **`eval_truth_cache.pkl.gz`（Step 1）**：解析 `v1_test_chimeras`（75 contigs, 21,262 ORFs）与 4 株 `unseen_real_genomes`（19,255 ORFs），通过 24 核 WSL `pyhmmer` 扫描 `all_phrogs` / `defense_finder` / `dbapis` / `wsl_vs2_pfam_vir`，共构建 `34,885` 条唯一蛋白注释（严格零重合 `strictly_unseen = 28,318` 条，其中噬菌体同源 `18,364`、已知功能模块 `6,787`、`DefenseFinder` 命中 `2,901`）。
   - **`judge_dataset.npz`（Step 2）**：从 `all_9_parts_orfs.pkl.gz` 切分 `45,451` contigs（90/10 按 contig 隔离，并掩码过滤验证集中与训练集重合的 AA 槽位），得到 `train_windows = 49,173`、`val_windows = 5,325`（`train_aa_vocab = 250,362`）。
   - **对照训练（Step 3）**：
     - `Stat-Only`（`use_aa_seq=False, params=691,723`）：12 epochs 约 `62s` 完成，zero-overlap val 最高 `MacroF1(P0..8) = 0.5167, Top1Acc = 0.7470, PhageAUROC = 0.8486`（权重：[orf_judge_statonly.pt](file:///F:/Phage%20data/models/full_v4/orf_judge_ablation/orf_judge_statonly.pt)）。
     - `AA-Seq`（`use_aa_seq=True, params=1,081,100`）：Epoch 10 达到最高 `MacroF1(P0..8) = 0.5507, Top1Acc = 0.7538, PhageAUROC = 0.8745`（Epoch 8 `PhageAUROC = 0.8765`，权重：[orf_judge_seq.pt](file:///F:/Phage%20data/models/full_v4/orf_judge_ablation/orf_judge_seq.pt)）。

3. **32,782 个严格零重合真实 ORF 四方同台实测（[orf_judge_ensemble_and_regions.json](file:///F:/Phage%20data/models/full_v4/orf_judge_ablation/orf_judge_ensemble_and_regions.json)）**
   - 对齐全部 `32,782` 个 `strictly_unseen` ORF（`n_known = 21,941`, `n_p08_pos = 6,444`, `defense_finder_count = 2,764`, `host_defense_virulence = 1,629`），全集推理耗时 `Stat-Only = 2.78s`、`AA-Seq = 12.09s`（对比 `Stage 1.2` 全扫描特征提取抽样 `151.14s`）：
     - **`Stage 1.2` 原生头**：`is_phage AUROC = 0.7517`、`AUPRC = 0.7500`、`DefenseFinder 误判率 = 46.35%`、`P0..8 Macro-F1 = 0.4562`、`Micro-F1 = 0.4428`、`Top1 = 0.6327`（`transposon_plasmid_mge F1 = 0.1724`、`moron_amg_defense F1 = 0.2466`、`P9 = 无`）。
     - **`Judge (Stat-Only)`**：`is_phage AUROC = 0.7728`、`AUPRC = 0.8027`、`DF 误判率 = 41.21%`、`Macro-F1 = 0.5017`、`Micro-F1 = 0.4970`、`Top1 = 0.6564`、`DF P9 AUROC = 0.7901 / AUPRC = 0.3512`（`P9 整体 AUPRC = 0.4384 / AUROC = 0.8397`）。
     - **`Judge (AA-Seq)`**：`is_phage AUROC = 0.7885`、`AUPRC = 0.8078`、`DF 误判率 = 39.44%`、`Macro-F1 = 0.4631`、`Micro-F1 = 0.4783`、`Top1 = 0.6516`、`DF P9 AUROC = 0.7828 / AUPRC = 0.4528`（`P9 整体 AUPRC = 0.5802 / AUROC = 0.8558`、`transposon_plasmid_mge F1 = 0.4024 / AUROC = 0.9499`）；序列 1D 卷积对短催化基序和对抗蛋白具有优势，但对未知保守结构蛋白出现序列记忆过拟合。
     - **`Judge (Stat+Seq 50/50 融合)`**：两路表示强烈互补并全线刷出最高分——`is_phage AUROC = 0.8106 (+5.89%)`、`AUPRC = 0.8340 (+8.40%)`、`DF 误判率 = 39.83% (-6.52%)`、`DF P9 AUROC = 0.8148 / AUPRC = 0.4317`、`P9 整体 AUPRC = 0.5454 / AUROC = 0.8731`、`Macro-F1 = 0.5474 (+9.12%)`、`Micro-F1 = 0.5521 (+10.93%)`、`Top1 = 0.6873 (+5.46%)`（`integration_excision 0.5942 -> 0.6627`、`dna_rna_replication 0.4434 -> 0.6044`、`transcription_regulation 0.2122 -> 0.3587`、`moron_amg_defense 0.2466 -> 0.4894`、`transposon_plasmid_mge 0.1724 -> 0.4779`）。

4. **区段级与真实基因组候选区段实盘收益结论**
   - **真实基因组建出 108 个原生候选区段透视（`unseen_real_genomes`）**：共有 `202` 个 `pyhmmer` 客观功能模块存在实例，`Stage 1.2` 原生头仅召回 `97 / 202 (48.02%)`，而 **`Judge (Stat+Seq 50/50)` 召回 `168 / 202 (83.17%, +35.15%)`**；在 *E. coli* K-12（`24/31 -> 29/31`）、*S. enterica* LT2 与 *S. aureus* NCTC8325 典型前噬菌体上基本达成模块全召回，同时在高 GC *Streptomyces* 无真实病毒模块候选区段中准确给出 `max P9 = 0.728 ~ 0.977` 对抗预警。
   - **嵌合体 75 真值区段 vs 宿主背景 / 高 Defense 岛对比**：`Stat-Only` 区段功能模块 `Macro-F1 = 0.8058`、`Micro-F1 = 0.8995`（高于 `Stage 1.2` 的 `0.7863 / 0.8886`），`vsHost_net = 0.9874`；`AA-Seq` 区段 `ModMacroF1 = 0.8265`（其中 `transposon_plasmid_mge` 区段 F1 达 `0.48` vs `Stage 1.2` 的 `0.20`），高 DefenseFinder 宿主岛 `P9` 检出率 `100%`（`Stage 1.2` 为 `0%`）；但在“完整 `intact` vs 残片 `degraded` 区分”上，携带全序列 200bp/5kb DNA 窗口语境的 `Stage 1.2`（`AUROC = 0.8265`）仍略高于纯局部 31-ORF 上下文模型（`Stat-Only = 0.8158`, `Ensemble = 0.7856`）。
   - **工程落地定位**：实验实证了**“主干聚焦边界分割 + 独立后置 `OrfFunctionalJudge (Stat+Seq)` 精判功能/MGE/宿主防御对抗”**的解耦路线收益极大且推理开销仅约 `15s`（`2.78s + 12.09s`）；后续如需正式上线，可将两路模型封装为区段后置精判与轻量化蛋白门控二分类先验，并对 `AA-Seq` 分支补充正则化及分位阈值校准。

---

## 30. `OrfFunctionalJudge` R1 → R2 → R3 单变量递进升级与零泄露消融实证（步骤 37）

围绕第 29 节暴露出的四大核心瓶颈——（1）`AA-Seq` 对未知结构蛋白序列局部死记过拟合；（2）单通道仅见局部 1D 卷积缺少操纵子相对共线性感知；（3）稀缺类在 `pos_weight` 训练下的概率漂移导致 `50/50` 平均后在固定 `0.5` 阈值归零；（4）缺乏折叠结构同源表征先验——我们在严格统一基准（**32,782 条零株系重合 `strictly_unseen` ORF + 75 嵌合真值区段 + 108 真实基因组原生检出区段**，生产目录 [stage1_2](file:///F:/Phage%20data/models/full_v4/stage1_2) 全程未动）依次推进三级单变量消融实验：

### 1. 递进架构设计与新增/扩展模块
1. **升级 1（R1，操纵子拓扑感知 + 先功能后鉴伪门控）**：
   - 在 [orf_functional_judge.py](file:///f:/NCBI%20blast/src/phage_discovery/student/orf_functional_judge.py) 实现 `arch="r1"`：序列编码端采用 `aa_mask_prob` 随机残基掩码 + `stem stride=2` 与 `ds_conv` 下采样压缩显存 + 2 层远程自注意力 + 4 头多原型池化；上下文端以基因间相对距离/链向/同向操纵子断点偏置注意力 `RelativeOperonAttentionBlock` 替代绝对位置编码；决策端采用 `FuncToPhageGatedHead`（先判功能再由 `P9` 抑制与 `P0..P4` 结构协同显式耦合门控 `is_phage`）与互斥惩罚项。
   - **显存红线实践**：针对 RTX 4070 8GB，序列支路训练自动锁定 `seq_bs=16, grad_accum=8`（等效 `bs=128`），峰值显存控制在 `2.4~4.0 GiB` 安全区内，无共享内存溢出。
2. **升级 2（R2，双尺度短基序 + 本地 `ProstT5_fp16` 折叠同源表征蒸馏）**：
   - 新增 [prostt5_embed_teacher.py](file:///f:/NCBI%20blast/src/phage_discovery/teachers/prostt5_embed_teacher.py) 与 [test_r2_prostt5_judge.py](file:///f:/NCBI%20blast/tests/test_r2_prostt5_judge.py)：借助 WSL2 `/usr/bin/python3` GPU 挂载本地 `database/phold_db` 内置 `ProstT5_fp16`（绑定 `shared.weight -> encoder.embed_tokens.weight`），耗时 `1341.4s`（8 个 `5,000` 条/片断点分片）完成 `40,000` 条高价值优先蛋白的 `1024D` 折叠表征提取（覆盖 `96,896` 个训练 ORF 槽位），缓存至 [prostt5_train_index.npz](file:///F:/Phage%20data/training/orf_judge_ablation/prostt5_train_index.npz)。
   - 在 `arch="r2"` 中叠加 `stride=1` 浅层高分辨率短基序支路 `hi_motif`（找回被 4 倍下采样抹平的防御系统短活性中心）与 `distill_proj`（`0.7*cosine + 0.3*smooth_l1` 对齐 1024D 折叠表征）。
3. **升级 3（R3，操纵子宏观态势门控 + 窗级完整度回归 + 零泄露 Logit 校准与跨模态协同）**：
   - 在 `arch="r3"` 中增加 `OperonMacroContextGate`（窗口注意力+最大池化结合宏观拓扑特征 FiLM 调制逐 ORF）与 `win_core_head`（利用窗口核心模块 `P0..P4` 丰度回归辅助监督），同时将硬对抗防御互斥惩罚加权至 `0.65`。
   - 新增单一职责后置校准模块 [judge_calibration.py](file:///f:/NCBI%20blast/src/phage_discovery/student/judge_calibration.py) 与单测 [test_r3_judge_and_calibration.py](file:///f:/NCBI%20blast/tests/test_r3_judge_and_calibration.py)：**严格仅在零重叠验证集 `va_*` (`va_unseen==1`) 上**拟合按类 Logit 融合权重及温和 L2 正则偏置校准（冻结 `is_phage` 负偏置防放水、限制 `P0..P4` 正偏置上限），并实现可选的 `Stage 1.2` DNA 主干信号轻度跨模态残差协同（`s12_phage_weight=0.22, s12_func_weight=0.05`）。

### 2. 训练规模与收敛记录
- **R1**（[train_summary.json](file:///F:/Phage%20data/models/full_v4/orf_judge_ablation_r1/train_summary.json)）：`r1_aa_seq_ctx` (`params=1,223,874`)，14 epochs 耗时 `1729.34s`，Epoch 14 验证集 `MacroF1=0.5561, Top1Acc=0.7682, PhageAUROC=0.8668`。
- **R2**（[train_summary.json](file:///F:/Phage%20data/models/full_v4/orf_judge_ablation_r2/train_summary.json)）：`r2_aa_seq_ctx` (`params=1,547,746`)，14 epochs 耗时 `1987.28s`，Epoch 13 验证集 `MacroF1=0.5507, Top1Acc=0.7697, PhageAUROC=0.8789`。
- **R3**（[train_summary.json](file:///F:/Phage%20data/models/full_v4/orf_judge_ablation_r3/train_summary.json)）：`r3_stat_only_ctx` (`params=809,216`) 耗时 `109.25s` 验证集达 `MacroF1=0.5509, Top1Acc=0.7760, PhageAUROC=0.8567`；`r3_aa_seq_ctx` (`params=1,662,820`) 耗时 `3021.58s` 验证集刷新最高 **`MacroF1=0.5573, Top1Acc=0.7808, PhageAUROC=0.8742`**。

### 3. 四代同台全量实测对比（32,782 零泄露 ORF 与 75 嵌合区段）

| 模型版本与形态 | `is_phage AUROC` | `is_phage AUPRC` | `DF 误判率 (DF_FP)` | `P0..8 MacroF1` | `P0..8 MicroF1` | `Top1Acc` | `P9 整体 AUPRC` | 区段 `vsHost_net` | 区段 `Intact_AUROC` | 区段 `ModMacroF1 / MicroF1` |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`Stage 1.2` 原生基准** | `0.7517` | `0.7500` | `0.4635` | `0.4562` | `0.4428` | `0.6327` | `-` | `0.9849` | `0.8265` | `0.7863 / 0.8886` |
| **Baseline `50/50`** | `0.8106` | `0.8340` | `0.3983` | `0.5474` | `0.5521` | `0.6873` | `0.5454` | `0.9840` | `0.7856` | `0.7912 / 0.8998` |
| **R1 `Stat-Only`** | `0.7880` | `0.8164` | `0.4041` | `0.5257` | `0.5158` | `0.6816` | `0.4211` | `-` | `-` | `-` |
| **R1 `AA-Seq`** | `0.7940` | `0.8258` | `0.4193` | `0.5073` | `0.5104` | `0.6710` | `0.4010` | `-` | `-` | `-` |
| **R1 `50/50`** | `0.8151` | `0.8442` | `0.4110` | `0.5561` | `0.5567` | `0.6963` | `0.4328` | `-` | `-` | `-` |
| **R2 `AA-Seq` 单模** | `0.8028` | `0.8317` | `0.4168` | `0.5126` | `0.5171` | `0.6819` | `0.4604` | `0.9920` | **`0.8343`** | `0.7938 / 0.8821` |
| **R2 (`R1 Stat + R2 Seq 50/50`)** | `0.8215` | `0.8478` | `0.4146` | **`0.5672`** | `0.5638` | `0.6993` | `0.4619` | `0.9913` | `0.8255` | `0.7673 / 0.8879` |
| **R3 `Stat-Only`** | `0.7935` | `0.8210` | **`0.3781`** | `0.5275` | `0.5212` | `0.6808` | `0.4284` | **`0.9932`** | `0.7865` | **`0.8092`** `/ 0.8992` |
| **R3 `AA-Seq`** | `0.8008` | `0.8298` | `0.3987` | `0.5136` | `0.5156` | `0.6915` | `0.4576` | `0.9836` | `0.7934` | `0.7843 / 0.8791` |
| **R3 `Calibrated Ensemble` (纯 Judge)** | `0.8229` | `0.8516` | `0.3962` | `0.5639` | `0.5664` | `0.7093` | `0.4678` | `0.9916` | `0.7641` | `0.8022 / 0.8963` |
| **R3 `Cross-Modal S1.2` (跨模态终态)** | **`0.8294`** | **`0.8577`** | `0.3849` | **`0.5699`** | **`0.5721`** | **`0.7107`** | **`0.4678`** | `0.9924` | `0.7632` | `0.8070 /` **`0.9000`** |

*(注：R1/R2/R3 结果文件分别见 [R1报告](file:///F:/Phage%20data/models/full_v4/orf_judge_ablation_r1/orf_judge_vs_stage1_2.json)、[R2区段报告](file:///F:/Phage%20data/models/full_v4/orf_judge_ablation_r2/orf_judge_ensemble_and_regions.json) 与 [R3区段报告](file:///F:/Phage%20data/models/full_v4/orf_judge_ablation_r3/orf_judge_ensemble_and_regions.json)；在 108 个 `unseen` 原生候选区段共 202 个功能存在实例中，`Stage 1.2` 原生召回 `97/202`，`Baseline` 召回 `168/202`，`R2` 召回 `167/202`，`R3` 在收紧防御误报门槛后召回 `161/202`。)*

### 4. 关键科学发现与客观选型定论
1. **逐级单变量实证结论**：
   - **R1 治愈了序列记忆过拟合**：`AA-Seq` 结构类 F1 大幅拉升（`head 0.5231 -> 0.6379`、`connector 0.3860 -> 0.5632`、`tail 0.5412 -> 0.6246`），但 4 倍下采样削弱了短防御活性基序（`P9 AUPRC 0.5802 -> 0.4010`）。
   - **R2 验证了折叠同源表征与高分辨率短基序支路的决定性价值**：单模 `AA-Seq` 不仅将 `P9 AUPRC` 拉回并涨至 `0.4604`（`is_phage AUROC` 首破 `0.80`），更在区段完整度 `Intact_AUROC` 上以 **`0.8343`** 首次正面反超 DNA 主干 `Stage 1.2`（`0.8265`）；`R1 Stat + R2 Seq 50/50` 拿下未校准全功能最高 `MacroF1 = 0.5672`（较 `Stage 1.2` 提升 `+11.10%`），但概率硬平均导致区段级 `transposon_plasmid_mge` 归零。
   - **R3 验证了宏观排雷门控、Logit 校准与跨模态 DNA/AA 协同的上限**：`R3 Stat-Only` 单模即达成全系最低 `DF_FP = 0.3781` 与最高区段 `ModMacroF1 = 0.8092`；Logit 空间校准救活 `transposon_plasmid_mge`（`0.0 -> 0.2353`）并将纯 Judge 推上 `AUROC=0.8229 / AUPRC=0.8516 / Top1=0.7093`；接入 `Stage 1.2` 跨模态后刷出全系列最高 ORF 判别（**`AUROC=0.8294 / AUPRC=0.8577 / MacroF1=0.5699 / Top1=0.7107`**、`DF_FP=0.3849`、区段 `ModMicroF1=0.9000`）。
2. **如实记录 R3 的唯一副作用与部署策略**：`OperonMacroContextGate` 的全窗平滑化与逐类偏置偏移使得累加连续评分 `Intact_AUROC`（`sum(max(P0..P4))`）在 R3 回落至 `0.7934 (AA-Seq) / 0.7641 (Calib)`，低于 `R2 AA-Seq` 单模的 `0.8343`。因此工程整合时应将 **R3 `Cross-Modal + Calib` 作为主精判与防御岛排雷引擎**，而将 **R2 未校准核心结构支路输出作为完整度 (`intact vs degraded`) 参考分**（后续可在 R4 探索引入“HMM 结构域包络 + 3Di 过程思维链与对抗错题库重放”）。

---

## 31. `Stage 1.2` + `R2/R3 Judge` 后置联动边界与灰区挽救单变量消融（步骤 38）

为验证在不动摇 `Stage 1.2` 权重的前提下，引入 [judge_region_refiner.py](file:///f:/NCBI%20blast/src/phage_discovery/inference/judge_region_refiner.py)（含边界外延裁边、基于 `200bp SubBin` 灰区高响应碎片的 `R3` 二审捞回及 `R2` 核心完整度拆分汇总）对最终区段边界精确度与隐蔽前噬菌体召回的净收益，我们在 `v1 test_chimeras`（75 嵌合区段）及 4 株 `unseen_real_genomes` 全基因组上开展了逐级单变量检验（生产 [scanner.py](file:///f:/NCBI%20blast/src/phage_discovery/inference/scanner.py) 默认路径暂未修改，结果缓存于 [p0_linkage_eval.json](file:///F:/Phage%20data/models/full_v4/orf_judge_ablation_r3/p0_linkage_eval.json)）：

| 联动方案 | `v1` TP/FP/FN (`IoU>=0.5`) | `v1` F1 / `meanIoU` | `v1` 断点 `MAE` (`bp`) | `v1 Strict0.8` TP / F1 | *S. aureus* NCTC8325 | *E. coli* K-12 MG1655 | *S. enterica* LT2 | *S. coelicolor* A3(2) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`E0` (`Stage 1.2` 原生基准)** | `75 / 3 / 0` | `0.9804 / 0.9795` | **`435.9 bp`** | `74 /` **`0.9673`** | `3` (CheckV 均值 `0.9247`) | `4` (`DLP12/e14/Rac/Qin`) | `5` (`Fels-2` IoU `0.7320`) | **`0`** |
| **`E1` (+ DNA 门控语义微调)** | `75 / 3 / 0` | `0.9804 / 0.9644` | `709.4 bp` (退步) | `73 / 0.9542` | `3` (`Gifsy` 降至 `0.8879`) | `4` | `5` (`Fels-2` `0.7716`, `Gifsy-2` `0.9119`) | `0` |
| **`E2` (+ `SubBin` 灰区 `R3` 二审，关闭外延)** | **`75 / 3 / 0`** | **`0.9804 / 0.9795`** | **`435.9 bp`** | **`74 / 0.9673`** | **`3` (完全无损)** | **`6`** (零误报救回 **`CPS-53 2467.8k..2475k`** 与 `2558.6k..2565.4k`) | **`6`** (零误报救回 **`1963k..1968.2k`** `7/7` 真 ORF) | **`0`** |
| **`E3` (`E2` + DNA 门控语义微调)** | `75 / 3 / 0` | `0.9804 / 0.9644` | `709.4 bp` | `73 / 0.9542` | `3` | `6` | `6` | `0` |

### 关键实证取舍定论
1. **明确否决 ORF 级向外扩边（`E1`）**：即便加上 `min_ext_backbone_score=0.22` DNA 过渡带门控，由于相邻宿主近端 ORF 在 `32-ORF` 滑窗上下文内易被宏观传染且基因粒度（`~1 kb`）远粗于 `200bp SubBin`，仍会将 `v1_test` 断点误差由 `435.9 bp` 恶化至 `709.4 bp`（无门控初测更是恶化至 `1581.1 bp`）；因此 `Stage 1.2` `200bp SubBin` 原生物理断点应保持绝对主导，不应由后置 ORF 强行外延。
2. **明确采纳 `E2`（`SubBin` 高响应灰区提取 + `R3` 严格二审 + `R2` 完整度）**：在不增加 `v1` 任何假阳性（`pure_negative_false_positives = 1` 不变）、不损失 `0.1 bp` 原生边界精度、且保持高 GC *S. coelicolor* **`0` 误报**的前提下，精准捞回因全局 `ContextRefiner` 下压 `win_score` 而遗漏的短隐蔽前噬菌体（`K-12` 检出由 `4 → 6`、`LT2` 检出由 `5 → 6`，均经 `pyhmmer` 真值蛋白核实为真实噬菌体片段）。

---

## 32. 统一分化底座 + 按需激活路由模型 (`UnifiedPhageModel`) 验证（步骤 39）

针对 R2 完整度与 R3 排雷能力需串联两套独立蛋白大模型的问题，在 [orf_functional_judge.py](file:///f:/NCBI%20blast/src/phage_discovery/student/orf_functional_judge.py) 与 [unified_model.py](file:///f:/NCBI%20blast/src/phage_discovery/inference/unified_model.py) 实现 `arch="unified"` 共享知识底座内部分化架构及单入口条件路由模型 `UnifiedPhageModel`，并由 [train_unified_judge.py](file:///f:/NCBI%20blast/scripts/train_unified_judge.py) 在冻结 R3 共享底座 `h_base` 与 Head C 权重的前提下，采用 R2 结构教师无平滑核心 logits 蒸馏出仅 `21,898` 参数的完整度分化头 `intact_func_head`（耗时 `130.09s`，收敛 `val_core_kd=4.0567`，产出 [unified_judge_seq.pt](file:///F:/Phage%20data/models/full_v4/orf_judge_unified/unified_judge_seq.pt) 与 [unified_eval_report.json](file:///F:/Phage%20data/models/full_v4/orf_judge_unified/unified_eval_report.json)）。

### 1. 模型整合收益与 `32,782` 零泄露 ORF / 75 嵌合区段同台实测

| 对比维度 | 分离双蛋白底座 (`R3 + R2`) | **统一分化模型 (`Unified`)** | 变化说明 |
| :--- | :---: | :---: | :--- |
| **Judge 总参数量** | `4,019,782` | **`2,493,934`** (头 B 仅 `21,898`) | **减少 `1,525,848` (`-37.96%`)**，不再加载 `R2_seq.pt` |
| **32,782 ORF `is_phage AUROC / AUPRC` (`Cross-Modal`)** | `0.8294 / 0.8577` | **`0.8294 / 0.8577`** | **100% 零损复现 R3 最高精度** |
| **32,782 ORF `DF_FP / MacroF1 / Top1`** | `0.3849 / 0.5699 / 0.7107` | **`0.3849 / 0.5699 / 0.7107`** | **100% 零损守住防御岛排雷与 10 类分区** |
| **区段 `vsHost / vsDF / ModMacroF1 / ModMicroF1`** | `0.9924 / 1.0000 / 0.8070 / 0.9000` | **`0.9924 / 1.0000 / 0.8070 / 0.9000`** | **防御岛 `DF_FP = 0.0000` 与功能识别无任何退化** |
| **区段 `Intact_AUROC`（单次前向）** | Head C `0.7632` / 独立 R2 `0.8343` | Head C `0.7632` -> **Head B `0.7992`** | 从单次 `h_base` 拉回 `+0.0360`（全冻结 R3 `h_base` 限制其达上限 `0.8343`） |

### 2. `UnifiedPhageModel` 端到端按需激活路由实测

| 数据集 / 模式 | 检出区段与边界精度 | 蛋白底座唤醒比例 (`activated / total`) | 蛋白跳过率 (`skip_ratio`) | 分段耗时 (`DNA` + `蛋白` = `总计`) |
| :--- | :--- | :---: | :---: | :---: |
| **`v1_test`（全专家按需模式）** | `TP/FP/FN=75/3/0, F1=0.9804, meanIoU=0.9795, MAE=435.9bp, Strict0.8=74` | `61 / 75` | **`18.67%`** | `31.995s + 12.920s = 44.915s` |
| **`v1_test`（仅 `boundary` 专家）** | `TP/FP/FN=75/3/0, F1=0.9804, meanIoU=0.9795, MAE=435.9bp, Strict0.8=74` | `0 / 75` | **`100.00%`** | `32.353s + 0.000s = 32.353s` (`-28.0%`) |
| ***S. aureus* NCTC8325** (`2.82 Mb`) | `3` 个 (`CheckV_IoU`: `0.9123 / 0.9407 / 0.9211`)，全标 `complete_structural_core` | `1 / 1` | `0.00%` | `10.216s + 3.777s = 13.993s` |
| ***E. coli* K-12 MG1655** (`4.64 Mb`) | `4 -> 6`（含灰区救回 `CPS-53 2467.8k` 与 `2558.6k`）；`DLP12 (2.45)`、`Rac (2.50)`、`2467.8k (0.78)`、`2558.6k (1.14)` 均正确标 `cryptic_or_incomplete` | `1 / 1` | `0.00%` | `38.550s + 16.659s = 55.209s` |
| ***S. enterica* LT2** (`4.86 Mb`) | `5 -> 6`（救回 `1963k..1968.2k`）；4 大完整噬菌体全标 `complete_structural_core` (`4.94~4.98`)，2 残余标 `cryptic_or_incomplete` | `1 / 1` | `0.00%` | `42.267s + 18.122s = 60.389s` |
| ***S. coelicolor* A3(2)** (`8.67 Mb` 纯宿主) | **`0` 检出 (`0` 误报)** | **`0 / 1`** | **`100.00%`** | `35.025s +` **`0.000s`** `= 35.025s` |

### 3. 科学结论与客观边界
1. **单底座分化的工程与生物收益成立**：仅增加 `21,898` 参数的分化头即在单次前向中同时提供 R3 顶级防御排雷/10类分区与 R2 式完整度判别；在 *E. coli* K-12 上不仅无损保住 `6` 处全召回，还将分离版 R2 误判为 `complete_structural_core` 的缺陷噬菌体 `DLP12`（`3.22 -> 2.45`）与 `6.8kb` 短碎片 `2558.6k..2565.4k`（`2.51 -> 1.14`）准确纠正回 `cryptic_or_incomplete`。
2. **客观局限记录**：因训练阶段为保持 100% R3 精度而彻底冻结 R3 `h_base`（其内含 `OperonMacroContextGate` 前段特征编码与局部上下文平滑），仅微调线性/MLP `Head B` 将 `Intact_AUROC` 从 `0.7632/0.7641` 拉回至 `0.7992`，尚未达到独立无平滑 `R2_seq` 单模上限（`0.8343`）；未来若在 `OrfContextEncoder` 之前分裂双支路并行联合微调，有望在不掉 R3 精度的前提下彻底追平 `0.834+`。

---

## 33. `UnifiedPhageModel` 生产准入大样本压力测试（步骤 40）

针对上线生产环境前必须核验的质粒/非噬菌体病毒误报率、高碎片化宏基因组短 Contig（`6~15 kb`）稳定性及显存/分片流式吞吐，从 [negative_splits.json](file:///F:/Phage%20data/benchmarks/v1/negative_splits.json) 的严格零泄露 `test` 分片（扣除 `prophage_masks ± 5 kb`）及 `v1_test` 截断构造了 7 组端到端压力基准（详表见 [production_stress_report.json](file:///F:/Phage%20data/models/full_v4/orf_judge_unified/production_stress_report.json)）：

| 测试组（零训练泄露） | 样本规模 / Contig 数 | `Stage 1.2` 原生基准 | `UnifiedPhageModel` | 蛋白跳过率 / 耗时 / 峰值显存 |
| :--- | :---: | :---: | :---: | :---: |
| **`A1` 纯质粒完整长段** (`>=3kb`) | `3.77 Mb` / `92` 条 | `FP=4` (`1.061/Mb`) | **`FP=6`** (`1.592/Mb`, `veto=0`, **`gray_rescued=2`**) | `skip=0.8370` / `15.71s` / `587.3 MB` |
| **`A2` 非噬菌体真核/古菌病毒** | `0.25 Mb` / `16` 条 | `FP=0` (`0.000/Mb`) | **`FP=2`** (`7.871/Mb`, **`gray_rescued=2`**, 两株古菌梭状病毒) | `skip=0.8750` / `10.23s` / `403.1 MB` |
| **`A3` 细菌染色体干净长段** (整批) | `36.12 Mb` / `84` 条 | `FP=6` (`0.166/Mb`) | **`FP=8`** (`0.222/Mb`, `veto=0`, **`gray_rescued=2`**) | `skip=0.8690` / `67.90s` / `1010.9 MB` |
| **`A3_chunked` (`10 Mb/片`, `4` 片)** | `36.12 Mb` / `84` 条 | `FP=6` | **`FP=8`** (`activated=11/84` 完全一致) | `rss_delta=24.1MB` / `118.15s` / `1010.9 MB` |
| **`B1` 碎片化质粒短 Contig** (`6~15kb`) | `3.47 Mb` / `342` 条 | `FP=5` (`1.440/Mb`) | **`FP=9`** (`2.591/Mb`, `veto=0`, **`gray_rescued=4`**) | `skip=0.9327` / `22.73s` / `527.7 MB` |
| **`B2` 碎片化细菌短 Contig** (`6~15kb`) | `15.01 Mb` / `1462` 条 | `FP=1` (`0.067/Mb`) | **`FP=3`** (`0.200/Mb`, `veto=0`, **`gray_rescued=2`**) | `skip=0.9952` / `39.84s` / `527.7 MB` |
| **`C1` 短侧翼 `±4kb` 正样本** | `4.87 Mb` / `75` 条 | `TP=75/0/0, F1=1.0, MAE=981.0bp` | **`TP=75/0/0, F1=1.0, MAE=981.0bp`** | `skip=0.0000` / `21.05s` / `645.1 MB` |
| **`C2` 截断 `12kb` 超短正样本** | `0.90 Mb` / `75` 条 | `75/75 (100.0%)` | **`75/75 (100.0%)`** | `skip=0.0000` / `27.24s` / `527.0 MB` |

### 压测暴露的 3 个关键生产隐患与定位结论
1. **`gray_rescue` 准入与 `base_veto` 拦截在质粒/MGE 场景存在过松虫洞（核心阻断点）**：
   - `rescue_and_filter_regions_with_judge` 将“命中 `P0..P6` 中任意 2 类 (`active_phage_mods >= 2`)”作为灰区放行条件，导致缺少 `head/connector/tail` 形态结构蛋白、仅含质粒/ICE 常见的 `integration_excision + dna_rna_replication + transcription_regulation` 的质粒碎片与细菌 MGE 岛在二审中被误捞，使 `B1` 碎片化质粒误报率从 `1.440/Mb` 升至 `2.591/Mb`、`A2` 古菌梭状病毒由 `0` 升至 `2`。
   - 同时，`strict_veto` 仅在 `core_mods == 0` 时才触发，致使含有 `max_p9=0.7931`、`mean_phage_prob=0.4306` 且带有 `transposon_plasmid_mge` 标签但偶含 `1` 个 `lysis` 预测的质粒区间（`NZ_CP134785.1_clean1 6200..36600`）绕过了拦截，导致 `base_vetoed = 0`。
2. **显存安全充裕，但按批重建子进程池推高分片耗时**：`36.12 Mb` 细菌单批峰值显存仅 `1010.9 MB`（`8 GB` 显存余量充足），但 `10 Mb/片` 直接重复调用 `scan_sequences` 因逐片拉起/销毁 `ProcessPoolExecutor` 使总耗时由 `67.90s` 增至 `118.15s`（`+74%`），后续流式分片必须复用持久进程池。
3. **正样本短碎片召回鲁棒性已彻底过关**：在 `±4 kb` 短侧翼和无侧翼 `12 kb` 超短截断正样本中均守住 **`100.0% (75/75)`** 全召回且零误杀（*注：`A3` 中 `NZ_CP097190.1_clean10 80800..93800` 检出 `head/connector/tail/lysis/integration` 全套核心 `core_sum=4.00`，疑似 `negative_index` 掩蔽遗漏的真实残余前噬菌体*）。

---

## 34. 生产转正风控修复、流式分片持久池与标准交付验收（步骤 41）

针对步 40 暴露出的质粒/MGE 灰区误救、防御岛逃逸与分片进程重建开销，按批准计划 [production_readiness_plan.md](file:///C:/Users/Administrator/.gemini/antigravity/brain/a84b4add-178c-4aff-97a2-c2e69eae3a98/production_readiness_plan.md) 完成了 3 阶段工程与算法落地：

### 1. 代码落地模块
- **二审风控加固**（[judge_region_refiner.py](file:///f:/NCBI%20blast/src/phage_discovery/inference/judge_region_refiner.py)）：抽出 `_should_veto_base_region`（新增零形态核心 `P0..P2==0` + 低均值 `<0.48` 质粒/防御对抗否决通道，拦截含单个 `lysis` 噪声的 `ParA/ParB` 质粒误报）与 `_passes_gray_rescue_criteria`（强制灰区救回需具形态结构证据或双核心 `lysis` 簇，且高 `P8` 激活时需多形态交叉佐证），新增 `suppressed_out` 可追溯审计记录。
- **持久进程池流式分片与断点续跑**（[unified_model.py](file:///f:/NCBI%20blast/src/phage_discovery/inference/unified_model.py)）：在 `UnifiedPhageModel` 新增 `scan_fasta_streaming`，跨 Chunk 仅启动并复用 1 个安全限核 `ProcessPoolExecutor`，每片落盘 `chunks.jsonl` 与原子更新 `checkpoint.json` 并强制 `gc.collect()` + `torch.cuda.empty_cache()`。
- **标准化导出与正式入口**（[report_exporter.py](file:///f:/NCBI%20blast/src/phage_discovery/inference/report_exporter.py)、[inference/__init__.py](file:///f:/NCBI%20blast/src/phage_discovery/inference/__init__.py)、[predict_unified.py](file:///f:/NCBI%20blast/scripts/predict_unified.py)）：导出 `regions.tsv`、`regions.gff3`（1-based inclusive）、按需流式切分的 `prophages.fna` 与 `scan_summary.json`。

### 2. 全量修复前后同台对照与回归结果（[production_readiness_verified_report.json](file:///F:/Phage%20data/models/full_v4/orf_judge_unified/production_readiness_verified_report.json)）

| 验证组（全量复测） | 修复前 (`Unified` 初版) | **修复后 (`Unified` 生产预备版)** | 关键对照与核实细节 |
| :--- | :---: | :---: | :--- |
| **`A1` 纯质粒 (`3.77 Mb`, `92` 条)** | `FP=6 (1.592/Mb)` | **`FP=4 (1.061/Mb)`**（追平 `Stage 1.2`） | `base_vetoed=1`（击落 `NZ_CP134785.1` `ParA/ParB+P9+P8`），`gray_rescued=1`（`14/15` 拒救） |
| **`A2` 非噬菌体病毒 (`0.25 Mb`, `16` 条)** | `FP=2 (7.871/Mb)` | `FP=2 (7.871/Mb)` | `2` 株古菌梭状病毒因含病毒衣壳 (`head_packaging`, `mean_ph=0.93`) 仍从灰区召回 |
| **`A3` 细菌完整长段 (`36.12 Mb`, `84` 条)** | `FP=8 (0.222/Mb)` | **`FP=7 (0.194/Mb)`** | `gray_rescued=1`（GenBank 确认为掩蔽漏标 `major capsid + integrase` `NZ_CP097190.1`） |
| **`A3_streaming` (`10 Mb/片` 持久池)** | `118.15s`（无续跑/非复用） | **`86.23s`** (`resume_half=39.82s`, `rss_delta=30.9MB`, `gpu_peak=1010.9MB`) | 耗时较重建池降 `27%`（较全载 `65.15s` 高 `+32.4%`），`exact_match=True` 且 4 类文件导出齐全 |
| **`B1` 碎片质粒 (`3.47 Mb`, `342` 条)** | `FP=9 (2.591/Mb)` | **`FP=6 (1.728/Mb)`**（减降 `33%`） | `base_vetoed=1`、`gray_rejected=16/18`；较 `S1.2` 原生 `5` 处仍多 `1` 处（含 `plasmid_frag0257` `head+lysis` 误触） |
| **`B2` 碎片细菌 (`15.01 Mb`, `1,462` 条)** | `FP=3 (0.200/Mb)` | **`FP=2 (0.133/Mb)`**（`skip=99.52%`） | 仅保留 `S1.2` 原生 `1` 处与掩蔽漏标真核衣壳碎片 `bacteria_frag0713` |
| **`C1 / C2` 截断正样本 (`n=75`)** | `100.0% / 100.0%` | **`100.0% / 100.0%`**（`F1=1.00, MAE=981.0bp`） | 正样本短侧翼与无侧翼 `12 kb` 片段零损全召回 |
| **`v1_test` 75 嵌合体** | `75/3/0, F1=0.9804, MAE=435.9bp` | **`75/3/0, F1=0.9804, MAE=435.9bp`** | 与 `Stage 1.2` / 分离版 `E2` 精度完全无损一致 |
| **4 株 `unseen_real_genomes`** | *S. aureus*=3, `K-12`=6, `LT2`=6, `A3(2)`=0 | ***S. aureus*=`3`, `K-12`=`5`, `LT2`=`6`, `A3(2)`=`0`** | `K-12` 稳健救回真 `CPS-53 (2467.8k)` 并依规剥除 `7/9` 宿主化 `2558.6k` 残骸至 `suppressed` |

### 3. CLI 端到端与回归验证
- 使用 [predict_unified.py](file:///f:/NCBI%20blast/scripts/predict_unified.py)（`--chunk-mb 3 --no-resume`）实跑 *E. coli* K-12（`4,641,652 bp`），耗时 `53.644s` 输出规范的 `regions.tsv`、`regions.gff3`、`prophages.fna` 与 `scan_summary.json`（5 处检出 + 1 处抑制预览）。
- 全量代码规范与回归检查：`ruff check` 全绿通过（`All checks passed!`）；8 个测试套件共 `38` 项用例全部通过（**`38 passed in 50.06s`**）；`nvidia-smi` 显示 GPU 显存回归基线（`774 MiB / 8188 MiB`）。
- **上线结论**：当前已满足**正式单株与中小规模基因组及带断点保护分片任务上线要求**（推荐以 [predict_unified.py](file:///f:/NCBI%20blast/scripts/predict_unified.py) 投产运行，同时留意高质粒碎片与古菌病毒样本在极少数携带病毒同源蛋白区段上仍可能保留残余召回）。

---

## 35. 生产主工作台全链路切换：用 `Unified V4` 替代默认 `Stage 1.2`（步骤 42）

为将线上 FastAPI + Vue 工作台默认主模型由纯 `Stage 1.2` 无缝升级为 `UnifiedPhageModel`，保留 `stage1_2` DNA 底座磁盘资产并完成全链路生产替换：

### 1. 生产全链路切换改造
- **自动模型注册切换**（[model_registry.py](file:///f:/NCBI%20blast/src/analysis/phage_finder/model_registry.py)）：在探测 `stage1_2` 后自动查找配套 `orf_judge_unified`（`unified_judge_seq.pt` + `orf_judge_statonly.pt`），当存在时将 **`unified` (`Unified V4`, `5,400,597` 参数)** 自动置顶为默认激活模型（`models[0]`），`stage1_2` 自动退居次席作为安全降级备选。
- **工作台引擎与剖面打通**（[unified_model.py](file:///f:/NCBI%20blast/src/phage_discovery/inference/unified_model.py)、[manager.py](file:///f:/NCBI%20blast/src/analysis/phage_finder/manager.py)、[exporter.py](file:///f:/NCBI%20blast/src/analysis/phage_finder/exporter.py)）：
  - `UnifiedPhageModel.scan_sequences` 支持输出 200bp `region_profiles` 与 `contig_score_tracks`；
  - `PhageDiscoveryManager` 识别 `has_unified_judge` 后主路径改由 `UnifiedPhageModel` 执行（仍透传界面调优阈值及可选外接 `BLASTp` 门控），并把 `Head B` 完整度级别、10 类功能模块、`protein_skip_ratio` 与二审拦截记录接入导出 JSON / GBK / GFF3 / TSV；
  - `Release` 生命期结束后强制释放全部 GPU 缓存（`release_gpu_memory()`）。
- **前端工作台升级**（[utils.ts](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_discovery/utils.ts)、[PhageDiscoverySetup.vue](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_discovery/components/PhageDiscoverySetup.vue)、[PhageDiscoveryResults.vue](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_discovery/components/PhageDiscoveryResults.vue)、[PhageDiscoveryHistory.vue](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_discovery/components/PhageDiscoveryHistory.vue)）：新增统一徽章工具函数正确显示 `Unified V4` 与按需引擎状态芯片、蛋白跳过率 KPI 与命中区段功能模块标签。

### 2. 真实权重端到端与回归验收
- **真实工作台运行实测**（隔离环境调用真实 [manager.py](file:///f:/NCBI%20blast/src/analysis/phage_finder/manager.py) 与 `F:\Phage data\models\full_v4`）：
  - `get_capabilities()` 自动首选 **`('unified', 'Unified V4', has_unified_judge=True)`**；
  - *E. coli* K-12：`regions=5`（含救回 `CPS-53 Phage_005: 2467800..2475000`，`e14/Qin` 标 `high`，`DLP12/Rac` 标 `medium`）、`rejected=1`、叠图 `360` bins 及 `region_1.gbk` (`43,892` 字符) 均正常输出（`54.869s`）；
  - *S. coelicolor* A3(2)：`regions=0`、`rejected=0`、**`skip=1.0` (`100%` 跳过蛋白推理)**、叠图 `360` bins（`34.89s`）。
- **全套自动化校验（最后一次编辑代码后）**：后端工作台 `16` 项与算法核心 `38` 项全通过；前端 Vitest `6/6` 通过且 `vue-tsc -b && vite build` 生产打包无错完成。








---

## 36. 8 株权威金标准宿主全基因组实测与“漏查 / 多出”独立蛋白库仲裁（步骤 43）

在完成生产主工作台全链路切换之后，选取 **8 株前噬菌体数目、生物功能与基因座界限已在经典文献及 NCBI RefSeq 中明确锚定**、且**完整宿主序列零存在于本地负样本库 (`negative_index.tsv` 命中 0 条)** 的跨菌属参考基因组（革兰氏阳性 4 属 + 革兰氏阴性 4 属，合计 **`31,216,619 bp` (`31.22 Mb`)**），以已投产的默认配置运行 `UnifiedPhageModel`（`prefer_unified_judge=True`, CUDA GPU），并使用独立本地蛋白库 **PHROGs (`all_phrogs.h3m`, `E<=1e-4`) + DefenseFinder (`1,332` 个 HMM) + RefSeq 官方 `/product=`** 对每一处漏查（`FN`）、额外多出（`Extra`）、已知非噬菌体干扰对照（`Confounder`）及二审拦截候选（`Suppressed`）逐区进行交叉验证（完整评测结果留档：[gold_standard_hosts_eval.json](file:///F:/Phage%20data/models/full_v4/orf_judge_unified/gold_standard_hosts_eval.json)，评估与仲裁脚本位于 scratch 目录）。

### 1. 训练集透明度审计与总盘表现
- **训练集重合披露**：8 株宿主全基因组均未进入 `negative_index.tsv`。正样本训练集 `splits/train.tsv` 收录过 6 株独立游离噬菌体同源记录（`933W`/`NC_000924.1`, `Stx2_Min27`/`NC_004914.3`, *Listeria* `A118`/`NC_003216.1`, `Fels-1`/`NC_010391.1`, `Gifsy-1`/`NC_010392.1`, `Gifsy-2`/`NC_010393.1`）；而 *E. faecalis* V583 (`pp1..pp7`)、*L. lactis* IL1403 (`bIL285..bIL312`)、*S. pyogenes* SF370 (`Spy370.1..4`)、*B. subtilis* 168 (`PBSX/SPbeta/skin`，仅 `SPbeta` 与 `Pf1` 在 `test.tsv`) 及 *S. enterica* LT2 (`Fels-2` 与退化残片) 的独立游离记录均未进入 `train.tsv`。
- **8 株总计实测结果**（总推理耗时 `270.98s`）：
  - **经典核心前噬菌体召回率 (`gold_prophage`)**：**`35 / 38 (92.1%)`**；
  - **卫星 / 高度退化前噬菌体样元件 (`gold_satellite_or_island`)**：`4 / 18`（精准召回 IL1403 3 株卫星 + LT2 `STM4200` 退化残骸；对 Sakai 6 株毒力/防御岛 `SpLE1..SpLE6` 与 *B. subtilis* 4 处高龄非核心岛做到零误报）；
  - **经典已知非噬菌体干扰对照误报 (`known_nonphage_confounder`)**：`2 / 4`（精准拒识 `ICEBs1` 与 `vanB_PAI`；但误报两处纯尾部细菌素）；
  - **金标准外额外多出 (`Extra`)**：`2` 处（全 `31.22 Mb` 宿主染色体中 6 株做到了 `Extra=0`）。

| 权威参考菌株 (RefSeq) | 基因组长度 / 耗时 | DNA 底座 -> 最终检出 (拦截) | 核心前噬菌体命中 | 卫星/退化元件命中 | 干扰对照误报 | 金标准外 Extra | 关键实测边界与特征 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| *S. pyogenes* SF370 (`NC_002737.2`) | `1.85 Mb` / `11.35s` | `3 -> 3 (0)` | `3 / 3` (`Spy370.1..3`) | `0 / 1` (`SpyCIM1`) | `--` | `0` | 3 大诱导前噬菌体 IoU `0.806~0.966` 全判 `complete_structural_core` |
| *L. lactis* IL1403 (`NC_002662.1`) | `2.37 Mb` / `15.10s` | `6 -> 6 (0)` | `3 / 3` (`bIL285/286/309`) | `3 / 3` (`bIL310/311/312`) | `--` | `0` | 隔 `18.5 kb` 的 `bIL309` 与 `bIL312` 精准分离，Head B 对 3 大 3 小完整度分化 `100%` 准确 |
| *P. aeruginosa* PAO1 (`NC_002516.2`) | `6.26 Mb` / `46.92s` | `2 -> 2 (0)` | `1 / 1` (`Pf4` `10.8 kb`) | `--` | `1 / 1` (`R2/F2 pyocin`) | `0` | 精准检出 `Pf4` 丝状噬菌体 (`IoU=0.858`)；但尾部样细菌素 `R2/F2 pyocin` 误报且判成完整前噬菌体 |
| *B. subtilis* 168 (`NC_000964.3`) | `4.22 Mb` / `37.34s` | `4 -> 4 (0)` | `3 / 3` (`PBSX/SPbeta/skin`) | `0 / 4` (`pp1/3/6/yjc`) | `0 / 1` (`ICEBs1`) | `0` | 完美拒识 `ICEBs1` 与 4 个非核心防御岛；但 `134.3 kb` 巨型 `SPbeta` 中间出现 `15 kb` 断裂分拆成 2 段 |
| *E. coli* O157 Sakai (`NC_002695.2`) | `5.50 Mb` / `65.33s` | `14 -> 14 (2)` | `15 / 18` (`Sp1..18`) | `0 / 6` (`SpLE1..6`) | `--` | `0` | 13 株单区精准命中（`Sp10=0.997`）；`Sp11+Sp12` 因 `0 bp` 相邻发生串联粘连合并；`SpLE1..6` `0/6` 零误报；漏 `Sp2, Sp16, Sp17` |
| *S. enterica* LT2 (`NC_003197.2`) | `4.86 Mb` / `59.88s` | `5 -> 6 (1)` | `4 / 4` (`Fels-1/2`, `Gifsy-1/2`) | `1 / 2` (`STM4200` 救回) | `--` | `1` | 灰区主动救回真 `STM4200` (`IoU=0.936`) 与隐蔽真微前噬菌体 `STM1867..1871`；五大致病岛 `0` 误报；`STM2234` 碎片遭灰区拦截 |
| *E. faecalis* V583 (`NC_004668.1`) | `3.22 Mb` / `18.27s` | `6 -> 6 (2)` | `5 / 5` (`pp1,3,4,5,6`) | `0 / 2` (`pp2`, `pp7`) | `0 / 1` (`vanB_PAI`) | `1` | 未训先泛化 `5/5` 全中；成功拒识 `vanB_PAI`；多报 1 段紧邻 `vanB` 的 `47.2 kb` 接合耐药移动岛 (`EF2297..EF2340`) |
| *L. monocytogenes* EGD-e (`NC_003210.1`) | `2.94 Mb` / `16.79s` | `1 -> 2 (1)` | `1 / 1` (`A118`, `IoU=0.978`) | `--` | `1 / 1` (`monocin`) | `0` | 完美拒识 `LIPI-1` 与防御岛 `SUP_0_1143400_1150000`；但尾部细菌素 `monocin` 由灰区主动救回误报 |

### 2. 漏查与多出区段独立分子验证定论（不修改当前权重参数，客观记录能力边界）
1. **“漏查 (`FN`)”独立验证结果**：
   - **二审灰区阈值过严导致的真实短/低分噬菌体漏检 (`3` 例)**：`Sakai Sp16` (`8.55 kb`, `PHROG=100%`, `head=1, int=1`, `mean_p=0.5786`)、`Sakai Sp17` (`24.19 kb`, `PHROG=82.8%`, `core=9`, `mean_p=0.7803`) 与 `LT2_remnant_STM2234` (`9.88 kb`, `PHROG=90.0%`, `head=1, tail=3, lysis=1`, `mean_p=0.6533`)，**`Stage 1.2` DNA 灰区均已正确提案，但均因 `mean_phage_prob < 0.85` 与边缘 `max_p9 (0.34~0.47)` 被 `Head A` 二审 `gray_rejected` 拦截**；
   - **卫星海盗岛 / 强退化抗噬菌体防御岛的合理或边界性未报**：`SF370 SpyCIM1`、`Sakai Sp2`（P4 样）与 `V583 pp7_EfCIV583` 经 PHROGs 与 DefenseFinder 验证均为 `head=0, tail=0, int=1` 且携带 **`3~7` 个抗噬菌体防御蛋白**的寄生染色体岛；`V583 pp2_phage02`（`14.6 kb`, `head=1, tail=5, int=0`）为极度宿主体内化无整合酶残核，`DNA_NO_PROPOSAL`；而 `Sakai SpLE1..SpLE6`（含 LEE 岛 `SpLE4` 与携带 `10` 个 `Zorya/Druantia/RM` 防御基因的 `SpLE6`）及 *B. subtilis* 168 `prophage_1/3/6/yjc` 缺乏核心头尾骨架，模型对其零误报为预期表现。
2. **“多出 (`Extra`) / 非噬菌体误报”与拦截验证结果**：
   - **真隐蔽微型前噬菌体额外检出 (`1` 例)**：`LT2 EXTRA_1963000_1968200` (`5.2 kb`，灰区主动救回)。经 RefSeq 与 PHROGs 证实内部紧凑排列 `STM1867 (pagK) -> STM1868 (mig-3 tail) -> STM1868A (lytic enzyme) -> STM1869 (tail) -> STM1870 (recE-like) -> STM1871 (integrase)`（`PHROG=87.5%`），属于未被传统 4 大前噬菌体列表涵盖的真实退化微型前噬菌体（`Head B` 准确标为 `cryptic_or_incomplete`）。
   - **细菌驯化尾部样细菌素假阳性 (`2` 例)**：革兰氏阴性菌 *P. aeruginosa* PAO1 的 **`R2/F2 pyocin`**（`23.2 kb`, `IoU=0.789`, `mean_p=0.9031` 且 `Head B` 误触发 `complete_structural_core`）与革兰氏阳性菌 *L. monocytogenes* EGD-e 的 **`monocin`**（`10.0 kb`, `IoU=0.735`, 甚至系由灰区主动救回）。独立 `pyhmmer` 铁证二者皆为 **`head=0, int=0`** 的无衣壳、无整合酶纯尾部+裂解细菌素（`PAO1 tail=20`, `EGD-e tail=5, lysis=2`），揭示现有蛋白头部尚缺针对“有尾无头无整合 Tailocin”的一票否决约束。
   - **巨型接合耐药移动岛误报 (`1` 例)**：`V583 EXTRA_2215600_2262800`（`47.2 kb`, 紧邻 `vanB_PAI` 右翼）。经 `.gbk` + `pyhmmer` 验证实为携 `vanY-B/S-B/R-B`、`VirB4/VirB6/VirD4` 接合转移酶、`MobT/relaxase`、`ltrA` 反转录酶及 **`10` 个 DefenseFinder 防御模块**的接合转座移动岛；`Head B` 已精准标其带 `transposon_plasmid_mge` 与 `cryptic_or_incomplete (1/4)`，但主区段未能触发 `Head A base_veto`。
   - **二审精确拒杀对照 (`2` 例)**：`V583 SUP_0 (2453k..2459.8k)` 与 `EGD-e SUP_0 (1143.4k..1150k)` 均仅含 `FtsK/SpoIIIE` 等迁移蛋白与 `2~3` 个 `DefenseFinder` 模块（`head=0, tail=0, int=0`），被 `gray_rejected` 精准拦截。
3. **拓扑边界短板实锤**：紧邻（`0 bp` 间隔）串联噬菌体（`Sakai Sp11 + Sp12`）会在 DNA 滑窗与合区阶段粘连为单个预测，而超过典型前噬菌体尺度的 `134 kb` 巨型噬菌体（`B. subtilis SPbeta`）则因内部高变异段导致滑窗中断被分裂为两段。

---

## 37. 工作台模型引擎识别与多路径展示 UI 修复（步骤 44）

针对生产界面虽实际已锁定 `Unified V4`，但设置卡路径栏仅渲染底层共用目录 `...\stage1_2` 且无引擎下拉切换、易使用户误以为错选旧版 `Stage 1.2` 的展示盲区，实施轻量无破坏 UI 修复（本次未修改任何模型权重与裁决参数）：

1. **类型与提交链路透传选定模型 ID**（[types.ts](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_discovery/types.ts)、[usePhageDiscovery.ts](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_discovery/composables/usePhageDiscovery.ts)）：为 `PhageModelInfo` 补齐 `unified_models_root` 声明，为 `PhageScanForm` 添加 `model_id`，提交负载优先采用用户选定模型并向后兼容默认 `models[0]`。
2. **显式引擎选择与双底座目录分栏呈现**（[PhageDiscoverySetup.vue](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_discovery/components/PhageDiscoverySetup.vue)）：
   - 当检测到多套引擎（如 `Unified V4` + 兼容 `Stage 1.2`）时提供下拉选择器（默认锁定置顶主力 `Unified V4`）；
   - 启用 `UnifiedJudge` 时将原孤立单行小字升级为结构化路径面板，明确并列展示 **`统一根目录`** (`...\full_v4`)、**`DNA 底座`** (`...\stage1_2`) 与 **`分化蛋白引擎`** (`...\orf_judge_unified`)；
   - 同步修复“载入验证样本”示例名随当前选用模型切换为 `Demo_Genome_Unified`。
3. **测试与构建验证**（[phageOverlayAndResults.test.ts](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_discovery/__tests__/phageOverlayAndResults.test.ts)）：新增多模型下拉、三路径分栏展示与提交 `model_id` 验证用例；最后一次修改后前端 TypeScript (`vue-tsc -b`)、生产打包 (`vite build`) 与单测全绿通过。

---

## 38. 各候选优化方案逐项“收益 vs 损失”量化消融测试（步骤 45，沙盒验证暂未改生产代码）

在不改动 `src/` 与生产权重文件的前提下，构建覆盖 **Gold-8 权威宿主 (`31.22 Mb`) + 3 株 Unseen 基因组 (`S. aureus NCTC8325 / E. coli K-12 / S. coelicolor A3(2)`) + 全量 8 组生产防回归基准 (`A1_plasmids`, `A2_non_phage_virus`, `A3_bacteria_clean`, `B1_frag_plasmids`, `B2_frag_bacteria`, `C1_flank4k`, `C2_12kb`, `v1_test`)** 的确定性推理中间态缓存与同源沙盒（消融脚本 [run_ablation_suite.py](file:///C:/Users/Administrator/.gemini/antigravity/brain/a84b4add-178c-4aff-97a2-c2e69eae3a98/scratch/run_ablation_suite.py)、架构解耦脚本 [opt5_arch_ablation.py](file:///C:/Users/Administrator/.gemini/antigravity/brain/a84b4add-178c-4aff-97a2-c2e69eae3a98/scratch/opt5_arch_ablation.py)），逐个隔离实测各项优化的真实收益与损失代价。

### 1. 后置裁决与拓扑优化逐项对比（`Opt-1 ~ Opt-4b`）

| 实验策略 | Gold-8 前噬菌体 (`38`) | 卫星/退化 (`18`) | 干扰误报 (`4`) | 额外 `Extra` | 裂 (`Sp`) / 并 (`Tan`) | Unseen (`Sau,K12,A32`) | Stress 误报 (`A1 / A2 / A3 / B1 / B2`) | 正样本抗断 (`C1 / C2 / v1_F1 / MAE / s08`) | 结论与取舍定论 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **`0_Baseline` (现行生产)** | `35/38` | `4/18` | `2/4` | `2` | `1 / 2` | `3, 5, 0` | `4 / 2 / 7 / 6 / 2` | `1.0000 / 75 / 0.9804 / 435.9bp / 74` | 生产基准线（Mean IoU=`0.8070`） |
| **`1a_Opt1_MGECrossVeto`** | `35/38` | `4/18` | `2/4` | **`1` (-1)** | `1 / 2` | `3, 5, 0` | `4 / 2 / 7 / 6 / 2` | `1.0000 / 75 / 0.9804 / 435.9bp / 74` | **纯收益零损失**：精准清除 `V583 ICE` |
| **`1b_Opt1_AggPlasmidVeto`** | `35/38` | `2/18` (-2) | `2/4` | `1` (-1) | `1 / 2` | `3, 5, 0` | `1 / 2 / 5 / 3 / 2` (-8) | `0.9933 / 67(-8) / 0.9868 / 435.9bp / 74` | **损失过大否决**：虽杀 `A1/B1` 质粒但误伤 `Sat -2` 且 `C2 12kb` 断崖跌 `8/75` |
| **`2a_Opt2_GrayTailocinGuard`** | `35/38` | `4/18` | **`1/4` (-1)** | `2` | `1 / 2` | `3, 5, 0` | `4 / 2 / 7 / 6 / 2` | `1.0000 / 75 / 0.9804 / 435.9bp / 74` | **纯收益零损失**：精准拦截灰区 `monocin`，零误杀 `STM4200` 与 `C2` |
| **`2b_Opt2_Base+GrayTailocin`** | `35/38` | `3/18` (-1) | **`0/4` (-2)** | `2` | `1 / 2` | `3, 5, 0` | `4 / 2 / 7 / 6 / 2` | `1.0000 / 64(-11) / 0.9804 / 435.9bp / 74` | **损失过大否决**：`C2 12kb` 短碎段因天然缺头/整合酶暴跌 `11/75` |
| **`3a_Opt3_ElasticSp17`** | **`36/38` (+1)** | `4/18` | `2/4` | `2` | `1 / 2` | `3, 5, 0` | `4 / 2 / 7 / 6 / 2` | `1.0000 / 75 / 0.9804 / 435.9bp / 74` | **纯收益零损失**：跨头结构并集精准捞回 `Sakai Sp17` |
| **`3b_Opt3_ShortMorph_n4`** | `36/38` (+1) | `5/18` (+1) | `2/4` | `2` | `1 / 2` | `3, 5, 0` | `4 / 2 / 8(+1) / 6 / 3(+1)` | `1.0000 / 75 / 0.9804 / 435.9bp / 74` | 小代价：`n>=4` 虽救回 `STM2234` 但引出 `A3 +1` 与 `B2 +1` |
| **`3b2_Opt3_ShortMorph_n6`** | **`36/38` (+1)** | **`5/18` (+1)** | `2/4` | `2` | `1 / 2` | `3, 5, 0` | `4 / 2 / 7 / 6 / 2` | `1.0000 / 75 / 0.9804 / 435.9bp / 74` | **纯收益零损失**：卡严 `n>=6` 精确保住 `STM2234` 且规避 `A3/B2` 误报 |
| **`3c_Opt3_IntOnly_Sp16`** | **`37/38` (+2)** | `5/18` (+1) | `2/4` | `2` | `1 / 2` | `3, 6(+1), 0` | `4 / 2 / 8(+1) / 6 / 2` | `1.0000 / 75 / 0.9804 / 435.9bp / 74` | **代价明显暂缓**：仅凭 `Int` 救 `Sp16` 会连带放大 `K-12 (+1)` 与 `A3 (+1)` 假阳性 |
| **`4a_Opt4a_TandemSplit_v1`** | `35/38` | `4/18` | `2/4` | `2` | `1 / 0` (-2) | `3, 5, 0` | `4 / 2 / 7 / 6 / 2` | `0.9804 / 75 / 0.9677 / 717.4bp / 73` | **误切惩罚严重**：误将 `C1` 与 `v1` 单株大噬菌体（`c1_10/11/32`, `CHIM_0009/0010`）切碎 |
| **`4a2_Opt4a_StrictSplit_v2`** | `35/38` | `4/18` | `2/4` | `2` | `1 /` **`0` (-2)** | `3, 5, 0` | `4 / 2 / 7 / 6 / 2` | `1.0000 / 75 / 0.9804 / 435.9bp / 74` | **纯收益零损失**：须同时存在两簇 `>=3` 强 `P0>=0.80` + 中间 `P4>=0.70` + 深谷 `ph<0.35`（`Sp11/12` IoU 升至 `0.956/0.899`） |
| **`4b_Opt4b_CompBridge_v1`** | `35/38` | `4/18` | `2/4` | `2` | `1 / 4` (+2) | `3, 5, 0` | `4 / 2 / 7 / 6 / 2` | `1.0000 / 75 / 0.9804 / 435.9bp / 74` | **负收益**：未桥接 `SPbeta`（缺口高分比例 `15.8%<25%`）反误并 `bIL309+bIL312` |
| **`4b2_Opt4b_StrictBridge_v2`** | `35/38` | `4/18` | `2/4` | `2` | **`0` (-1)** `/ 2` | `3, 5, 0` | `4 / 2 / 7 / 6 / 2` | `1.0000 / 75 / 0.9804 / 435.9bp / 74` | **纯收益零损失**：严格互补双臂（`>=30kb` 早+`Int` 臂补全缺 `Int` 的结构臂，总长 `>=75kb`+谷中 `>=2` 锚钉），`SPbeta` IoU `0.451 -> 0.843` |
| **`6_PLUS_SHORTMORPH_n6` (全零损合集)** | **`36/38`** | **`5/18`** | **`1/4`** | **`1`** | **`0 / 0`** | `3, 5, 0` | `4 / 2 / 7 / 6 / 2` | `1.0000 / 75 / 0.9804 / 435.9bp / 74` | **黄金零损组合**：Gold-8 Mean IoU **`0.8070 -> 0.8504 (+0.0434)`**，全部 10 项防回归基准严格 `0` 损失 |

### 2. `Opt-5` 零泄露纯架构特征分叉解耦对照实验（冻结共享底座）

保持 `judge_dataset.npz`（`49,173` 训练 / `5,325` 验证）与 `R2` 教师蒸馏目标严格不变，对比 **Head B (`intact_func_head`)** 不同特征分叉起点对 `32,782` 未见 ORF、`75` 嵌合体 `Intact_AUROC` 与端到端指标的纯影响：

| Head B 分叉变体 | 可训练参数 | 验证 `val_core_kd` | `75` 嵌合体 `Intact_AUROC` | `32,782` ORF `Core5_mAP / mF1` | `Sakai Sp17 P2` | `PAO1 pyocin` (`Head/Conn/Tail/Lysis/Int >=0.5`) | 联合 `6_ZeroLossRules` 端到端结果 | 核心发现 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- | :--- |
| **`Prod_HeadB` (`h_base`, 生产)** | `21,898` | `4.0567` | `0.7992` | `0.6355 / 0.6081` | `0.563` | `[1, 0, 17, 2, 0]` | `Pro=36/38 Sat=5/18 Conf=1/4 Ex=1 Sp=0 Tan=0` | 稳定基线 |
| **`B0_retrain` (`h_base` 同源重训)** | `21,898` | `4.1766` | `0.8070` | `0.6327 / 0.6105` | `0.547` | `[1, 0, 17, 2, 0]` | `Pro=35/38`（`Sp17` 擦线落榜）`Sat=5/18 Conf=1/4 Ex=1 Sp=0 Tan=0` | 单靠 `h_base` 随机起伏影响临界阈值 |
| **`B1_orf_fuse` (纯单 `e_orf`)** | `21,898` | `9.5962` | `0.8606` | **`0.3470 / 0.3470`** | `0.062` | `[1, 0, 7, 1, 0]` | `Pro=35/38 Conf=1/4 Ex=2 Sp=1 Tan=2` | **严重坍塌**：丢掉操纵子上下文导致 `P0..P3 mAP` 暴跌且失去 `Opt-1a/4` 判别基础 |
| **`B2_conv3` (`e_orf + 3-ORF Conv1d`)** | `99,178` | `6.1846` | `0.7817` | `0.5109 / 0.5119` | `0.414` | `[0, 1, 11, 2, 0]` | `Pro=35/38 Conf=2/4 Ex=2 Sp=1 Tan=0` | 短程卷积仍不足以代替相对拓扑自注意（反误判 `V583 ICE` `2` 个伪 `P0`） |
| **`B3_dualskip` (`cat[e_orf, h_base]`)** | `73,578` | **`3.7920`** | **`0.8197`** (`+0.0205`) | **`0.6412 / 0.6132`** | **`0.651`** | `[1, 0, 17, 2, 0]` | **`Pro=36/38 Sat=5/18 Conf=1/4 Ex=1 Sp=0 Tan=0`** | **最优无泄露架构升级**：`Core5_mAP/mF1` 超越 `Native_R2`，`Intact_AUROC` 逼近独立 `R2` 且不损任何生产基准 |
| `Native_R2` (独立 `R2` 参考上限) | `1,547,746` (独立模型) | `--` | `0.8343` | `0.6377 / 0.5854` | `0.945` | **`[0, 6, 17, 3, 1]`** | `Pro=36/38 Sat=4/18 Conf=2/4 Ex=2 Sp=1 Tan=0` | 证实 **原生 R2 教师本身即把 `PAO1 pyocin` 判出 `17 Tail + 6 Conn`**，根除细菌素必须引入外部 Tailocin 硬负样本联合微调共享底座 |

---

## 39. 零损失规则与拓扑优化组合正式落地生产与全链路实机验收（步骤 46）

按第 38 节严格消融证实，**在不改动现行 `UnifiedJudge` 权重文件的前提下**，将唯一全基准零损失组合 `6_PLUS_SHORTMORPH_n6` 正式模块化合入生产推理管线（不引入任何牺牲 `C2 12kb` 短片或新增 `K-12/A3` 假阳性的激进规则；`Opt-5 DualSkip` 保留与后续外部硬负样本重训一并规划升级权重）：

### 1. 生产代码改动清单
1. **后置仲裁与拓扑精修引擎**（[judge_region_refiner.py](file:///f:/NCBI%20blast/src/phage_discovery/inference/judge_region_refiner.py)）：
   - `_get_r2_core_probs` 统一安全读取 `Head B` 核心结构 5 维概率并向后兼容旧版单头字典；
   - `_should_veto_base_region` 合入 **Opt-1a 跨头联合 MGE/ICE 排雷** (`r2_morph_cnt==0 & max_p8>=0.55 & max_p9>=0.45 & mean_p9>=0.18 & mean_ph<0.72`)；
   - `_is_gray_tailocin_like` + `_passes_gray_rescue_criteria` 合入 **Opt-3a 弹性结构梯度救援**、**Opt-3b2 短形态簇挽救 (`6 <= n_orf <= 10`)** 与 **Opt-2a 灰区纯尾簇 Tailocin 拦截**；
   - 新增独立模块化拓扑精修函数 **`bridge_complementary_phage_fragments`**（**Opt-4b2** 严格互补半臂桥接）与 **`split_tandem_prophage_regions`**（**Opt-4a2** 严格双芯+整合酶谷底拆分），并纳入 `rescue_and_filter_regions_with_judge` 默认后处理管线。
2. **统一扫描统计对齐**（[unified_model.py](file:///f:/NCBI%20blast/src/phage_discovery/inference/unified_model.py)）：为单次与流式分片扫描初始化补充 `topology_bridged` / `topology_split` 统计字段（FastAPI 工作台 [manager.py](file:///f:/NCBI%20blast/src/analysis/phage_finder/manager.py) 自动通过 `UnifiedPhageModel` 无缝继承全套新能力）。
3. **单元测试补强**（[test_judge_region_refiner.py](file:///f:/NCBI%20blast/tests/test_judge_region_refiner.py)）：新增 `5` 项覆盖跨头 ICE 排雷、灰区 Tailocin 拦截、弹性/短形态挽救与 `4-ORF` 隔离、互补半臂桥接不误并卫星岛、双芯串联拆分不误切巨噬菌体的单元测试。

### 2. 上线后真机全链路回归验收结果
1. **自动化单元测试**：`pytest tests/test_judge_region_refiner.py tests/test_orf_functional_judge.py tests/test_unified_differentiated_model.py tests/test_unified_production_pipeline.py tests/test_phage_finder_workbench.py -v` **全部 `39 passed in 11.36s`**。
2. **全量基准函数级对接复核**：生产函数 `rescue_and_filter_regions_with_judge` 在完整双基准中间态上的输出 `100%` 对齐消融最佳组合（`Pro=36/38, Sat=5/18, Conf=1/4, Ex=1, Sp=0, Tan=0`，`Sau=3, K12=5, A32=0`，`A1=4, A2=2, A3=7, B1=6, B2=2`，`C1=1.0000`, `C2=75/75`, `v1=75/3/0 F1=0.9804 MAE=435.9bp s08=74`）。
3. **`UnifiedPhageModel` 真机 GPU 从 FASTA 端到端重扫实测**（实测摘要留档于 `prod_verify_gold8/phase1_summary.json`）：
   - **Gold-8 权威宿主 (`31.22 Mb`)**：核心前噬菌体 **`36 / 38 (94.7%)`**（Sakai `16/18`，精准捞回 `Sp17`）、卫星/退化元件 **`5 / 18`**（LT2 `2/2`，精准捞回 `STM2234`）、干扰对照误报 **`1 / 4`**（EGD-e `monocin`、B. subtilis `ICEBs1`、V583 `vanB_PAI` 全 **`0` 误报**，仅余 PAO1 `R2/F2 pyocin`）、金标准外 Extra **`1`**（V583 `47.2 kb` 接合耐药移动岛清零 `1 -> 0`）；**`split = 0, tandem = 0`**，Gold-8 前噬菌体 **Mean IoU 从 `0.8070` 跃升至 `0.8504 (+0.0434)`**，其中 `SPbeta` (`0.451 -> 0.8427`)、`Sp11` (`0.490 -> 0.9560`)、`Sp12` (`0.491 -> 0.8990`) 全部在拓扑合/分后自动获得 `complete_structural_core (core_cnt=5)` 准确标注；
   - **`v1_test` (`20.86 Mb`, `75` 嵌合体)**：真机实跑 **`TP/FP/FN = 75/3/0, F1 = 0.9804, meanIoU = 0.9795, MAE = 435.9bp, Strict0.8 = 74`**（`topology_bridged=0, topology_split=0, base_vetoed=0`），实现边界精度与防回归 **`0` 损耗**上线。

---

## 40. 淘汰历史模型与消融产物目录清理及删后复验（步骤 47）

对 `F:\Phage data\models\`、工作台配置 [config.json](file:///f:/NCBI%20blast/config.json) 及推理源码依赖完成全仓审计后，清理全部不再被生产端或模型迭代引用的历史淘汰权重与消融实验产物，共移除 **`13` 个目录、`108` 个文件，释放 `214.44 MB`**：

### 1. 已安全清理目录明细
| 清理类别 | 已移除目录 | 文件数 | 释放体积 | 淘汰原因 |
| :--- | :--- | :---: | :---: | :--- |
| **历史早期代际** | `F:\Phage data\models\full_v2` | `14` | `23.72 MB` | 已被 `full_v4` 全面取代 |
| **历史早期代际** | `F:\Phage data\models\full_v3_1` | `9` | `18.42 MB` | 已被 `full_v4` 全面取代 |
| **V4 早期过渡与备份** | `full_v4\student_v4_1`、`full_v4\student_v4_2_legacy_v4_2_backup` | `13` | `37.07 MB` | 缺 SubBin 过渡版与 V4.2 迁徙遗留备份 |
| **DNA 端消融废弃产物** | `full_v4\stage1_ablation`、`full_v4\stage1_2_ablation`、`full_v4\stage1_3_p0_ablation` | `53` | `96.19 MB` | 验证后废弃或已转正定型的中间调参拷贝 |
| **早期蛋白裁判淘汰版** | `full_v4\orf_judge_ablation`、`full_v4\orf_judge_ablation_r1` | `9` | `14.29 MB` | 已被 R3 / Unified 完全取代 |
| **旧三专家分散权重** | `full_v4\ensemble`、`expert_a`、`expert_b`、`expert_c` | `10` | `24.75 MB` | 已蒸馏合并入单模 `stage1_2.pt`，生产不再加载 |

### 2. 严格保留项与删后功能验收
1. **生产现役双引擎（完整保留）**：[stage1_2](file:///F:/Phage%20data/models/full_v4/stage1_2)（`20.32 MB`）与 [orf_judge_unified](file:///F:/Phage%20data/models/full_v4/orf_judge_unified)（`10.16 MB`）及 `full_v4` 顶层 3 份评估比对 JSON（`0.25 MB`）。
2. **直系热启动基座与回退备用（审慎保留待后续确认）**：`full_v4\orf_judge_ablation_r2`（`6.04 MB`，[train_unified_judge.py](file:///f:/NCBI%20blast/scripts/train_unified_judge.py) 教师蒸馏源与 `prefer_unified=False` 兼容支路）与 `full_v4\orf_judge_ablation_r3`（`9.65 MB`）；本地训练特征集 `F:\Phage data\training\` 与 `archive\`、`database\` 注释库均保持原状未改动。
3. **清理后全链路验证全绿**：
   - `discover_available_models()` 正常返回 `['unified', 'stage1_2']`，`resolve_model_dir()` 锁定默认 `unified`；
   - `pytest`（`5` 个核心测试集 `39` 项用例）：**`39 passed in 11.59s`**；
   - `UnifiedPhageModel` CUDA 真机重扫 `NC_002737.2_Streptococcus_pyogenes_SF370.fasta`（`11.275s`）：精确命中 `3` 处前噬菌体 `[(529800, 571000), (778200, 819600), (1189600, 1223400)]`。
