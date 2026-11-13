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
