# 蛋白序列解析与多 FASTA 相似度检索过程留档

## 1. 任务目标

- **查询蛋白输入**：解析给定蛋白 FASTA 文件中的全部蛋白条目（共 29 条蛋白序列）。
- **目标序列输入**：扫描目标目录下的全部 FASTA 文件（共 67 个文件，708 条记录），自动识别核酸（DNA）、蛋白质（Protein）与非标准结构编码序列（如 Phold/Foldseek 3Di）。
- **检索与标记目标**：在目标 FASTA 序列中进行多核并行同源检索（DNA 使用 `tblastn`，Protein 使用 `blastp`，3Di 结构字母表序列自动跳过并显式标记），准确标记出含有相似度（`pident`）大于 30% 的目标文件及具体序列条目，并输出结构化统计表、带标记 FASTA 文件与简体中文汇总报告。

## 2. 第 1 步：数据勘察与环境核查（已完成）

### 2.1 输入数据勘察结果

1. **查询蛋白文件** (`1.fasta`)：
   - 共解析出 **29 条**蛋白质氨基酸序列（`Nadirvirus`, `Synechococcus`, `vg:78064367` 等），长度范围 207 aa - 711 aa。
   - 其中 `vg:13996267` 与 `vg:13995528` 序列内容完全一致（352 aa），流程中完整保留全部 29 条独立条目，不做静默删减。
2. **目标 FASTA 目录** (`新建文件夹 (2)`)：
   - 共 **67 个** `.fasta` 文件，总大小约 5.38 MB，包含 **708 条**记录：
     - **65 个 DNA 核酸文件**（140 条序列/contig，总计约 5.1 Mb），含多条记录文件（multi-FASTA，如 `Polished_Assembly.fasta` 含 25 条、`3.fasta` 含 19 条、`3133①.fasta` 含 14 条）及含中文/全角括号/圆圈数字文件名。
     - **1 个蛋白质氨基酸文件** (`phold_aa.fasta`，284 条 CDS 蛋白序列，53,426 aa)。
     - **1 个 3Di 结构编码文件** (`phold_3di.fasta`，284 条结构状态字母序列，53,426 符号，`M` 起始比例 0%，含大量 `DDDD`/`VVVV`/`PPPP` 结构状态片段）。该文件不属于氨基酸或核酸序列，必须自动识别并排除出 BLAST 检索，防止产生无意义假阳性。

### 2.2 本地运行环境核查

- **BLAST+ 引擎**：已安装 NCBI BLAST+ 2.16.0+（`tblastn`, `blastp`, `makeblastdb` 均可用）。
- **Python 环境**：项目虚拟环境 `.venv` 为 Python 3.13.5，`pytest` 可用。
- **硬件配置**：Intel Core i9-13900HX（24 物理核 / 32 逻辑线程）、47.78 GB 物理内存、NVIDIA RTX 4070 Laptop GPU（8 GB）。

## 3. 架构与工程规范设计

1. **模块化目录结构**（单一职责原则）：
   - `src/analysis/protein_search/models.py`：核心数据模型与配置定义。
   - `src/analysis/protein_search/fasta_parser.py`：UTF-8 流式 FASTA 解析、DNA/Protein/3Di 自动识别、纯 ASCII 安全 ID 映射。
   - `src/analysis/protein_search/blast_runner.py`：多核核心预算规划（动态预留至少 4 个逻辑核防止卡死）、分片建库（统一 `-dbsize` 保持统计可比）、并发 `tblastn`/`blastp` 调度与 `checkpoint.json` 原子断点保护。
   - `src/analysis/protein_search/marker.py`：分片结果流式聚合、`pident > 30%` 可信标记与边缘候选区分、TSV/带标记 FASTA/简体中文 Markdown 报告生成。
   - `src/analysis/protein_search/pipeline.py`：端到端流水线编排。
   - `scripts/run_protein_fasta_search.py`：无硬编码路径的命令行入口脚本。
   - `tests/test_protein_fasta_search.py`：完整单元测试与端到端 BLAST 验证套件（实施前先测后跑）。
2. **检索与标记判定口径**：
   - DNA 检索使用 `tblastn -db_gencode 11`（细菌与噬菌体遗传密码子表），Protein 检索使用 `blastp`。
   - 召回阈值：`evalue <= 1e-3`，`-max_target_seqs 2000`。
   - **可信阳性标记 (`[HIT>30%]`)**：`pident > 30.0%` 且 `evalue <= 1e-5` 且 `align_len >= 30 aa`（过滤极短随机假阳性片段）。
   - **边缘候选标记 (`[BORDERLINE>30%]`)**：`pident > 30.0%` 但 `evalue > 1e-5` 或 `align_len < 30 aa`，单独建表输出，确保透明可审计。
   - 同时在所有结果表中保留 `ppos`（正相似残基百分比）供进一步参考。
3. **编码与路径安全**：
   - 全链路强制 `UTF-8` 编码，严禁使用 GBK。
   - 对含空格、中文、全角字符的目标文件名及路径建立纯 ASCII 安全 ID 映射，并在 Windows 下使用相对/短路径调用 BLAST+，杜绝乱码与路径解析失败。

---
*后续步骤（代码实现、单元测试、真实数据执行、结果复核）将随推进持续追加留档。*

## 4. 第 2 步：模块化蛋白检索包与 CLI 实现（已完成）

已在工作区按单一职责原则完成全部代码模块与 CLI 脚本构建（无 Emoji、无硬编码路径、全 UTF-8 编码）：

- `src/analysis/protein_search/__init__.py`：包公共导出入口。
- `src/analysis/protein_search/models.py`：定义 `QueryProteinRecord`、`TargetSequenceRecord`、`ShardSpec`、`BlastHitRecord`、`SequenceMarkSummary`、`FileMarkSummary`、`SearchConfig`、`PipelineResult`。
- `src/analysis/protein_search/fasta_parser.py`：流式 UTF-8 FASTA 解析、DNA/Protein/3Di 自动识别、纯 ASCII 安全 ID 映射与按分片流式写出。
- `src/analysis/protein_search/blast_runner.py`：动态核心预留规划（32 逻辑核至少保留 4 核）、Windows 8.3 短路径与工作目录隔离、分片建库 + 统一 `-dbsize`、并发 `tblastn`/`blastp` 调度与原子落盘 `checkpoint.json`。
- `src/analysis/protein_search/marker.py`：流式分片聚合、`[HIT>30%]`/`[BORDERLINE>30%]`/`[NO_HIT]`/`[SKIPPED_3DI]` 标记、多维度 TSV、带标记头 FASTA 与简体中文 Markdown 报告导出。
- `src/analysis/protein_search/pipeline.py`：端到端流水线编排。
- `scripts/run_protein_fasta_search.py`：基于相对路径的 CLI 入口。

## 5. 第 3 步：单元测试与端到端集成验证（已完成）

执行命令：`pytest tests/test_protein_fasta_search.py -v`

- **测试结果**：`4 passed in 6.88s`（全部通过）。
- **验证覆盖点**：
  1. `test_compute_parallel_plan_preserves_host_cores`：验证 32 逻辑核主机保留 >= 4 核、8 逻辑核主机保留 >= 2 核，且并发进程与每进程线程乘积不超预算。
  2. `test_classify_file_sequences_distinguishes_dna_protein_and_3di`：验证 DNA、Protein、3Di（含文件名特征和内容启发式特征）自动分类无误。
  3. `test_parse_query_proteins_preserves_duplicate_content_entries`：验证 UTF-8 BOM 兼容以及相同序列内容不同条目 ID 完整保留。
  4. `test_end_to_end_sharded_blast_marking_and_checkpoint_resume`：验证含中文与全角括号文件名、multi-FASTA、真实 `tblastn` + `blastp`、3Di 自动跳过、带标记 FASTA 导出、`checkpoint.json` 原子断点续跑、以及多分片统一 `-dbsize` 与全库单分片 E-value 一致性。

## 6. 第 4 步：真实数据多核分片检索与异常排查修复（已完成）

### 6.1 首次运行异常与根因修复

- **现象**：首次在 `f:\NCBI blast\results\protein_fasta_search` 执行 `makeblastdb` 时报错 `BLAST Database error: Database memory map file error (code=3)`。
- **定位根因**：工作目录路径 `f:\NCBI blast` 含空格，此前仅对 BLAST 可执行文件与查询文件路径启用了 Windows 8.3 短路径，遗漏了子进程 `cwd`，触发了 Windows 下 NCBI BLAST+ 含空格路径内存映射问题。
- **修复措施**：
  1. 在 `src/analysis/protein_search/blast_runner.py` 中对子进程 `cwd` 强制应用 8.3 短路径；若目标盘禁用 8.3 短名导致路径仍含空格或非 ASCII，则自动回退到无空格临时目录沙箱并在完成后清理；
  2. 为 `makeblastdb` 显式指定 `-blastdb_version 4`，避免多并发进程下 LMDB 内存映射冲突；
  3. 在 `tests/test_protein_fasta_search.py` 中补充含空格与中文输出路径的回归用例，重新运行 `pytest` 全部通过（`4 passed in 5.00s`）。

### 6.2 真实数据检索执行结果

执行命令：
`python -X utf8 scripts/run_protein_fasta_search.py --query <1.fasta> --target-dir <新建文件夹 (2)> --output-dir results/protein_fasta_search --min-pident 30.0 --max-evalue 1e-5 --blast-evalue 1e-3 --min-align-len 30`

- **解析查询蛋白**：29 条。
- **扫描目标文件**：67 个文件 / 708 条序列（DNA = 65 个文件 140 条序列，Protein = 1 个文件 `phold_aa.fasta` 284 条序列，3Di = 1 个文件 `phold_3di.fasta` 284 条结构序列已安全跳过）。
- **分片执行**：共 8 个分片（7 个 DNA 分片 + 1 个 Protein 分片），首次并发执行完成；二次执行验证断点保护生效，`8/8` 分片命中复用。
- **阳性标记结论 (`[HIT>30%]`)**：共标记出 **5 个目标文件 / 5 条序列（17 条可信 HSP）**：
  1. `10T9-T12_asm_ngcs_scaffold_1.fasta` (`ngcs_scaffold_1`)：最高 `pident = 56.60%`（`vg:26645724`, `E = 3.30e-13`, `53 aa`），共命中 4 个查询蛋白（`vg:26645724`, `vg:26797564`, `Nadirvirus`, `vg:10020986`），且基因组 `94536..95528` 与 `96273..97259` 存在相邻串联双拷贝同源区。
  2. `三代测序拼接.fasta` (`ngcs_chromosome_1`)：最高 `pident = 52.83%`（`vg:26645724`, `E = 5.06e-12`, `53 aa`）。
  3. `二代测序拼接.fasta` (`ngcs_scaffold_1`)：最高 `pident = 52.83%`（`vg:26645724`, `E = 5.06e-12`, `53 aa`）。
  4. `混合.fasta` (`混合`)：最高 `pident = 52.83%`（`vg:26645724`, `E = 5.06e-12`, `53 aa`）。（注：以上 3 个文件为同一约 156.3 kb 噬菌体的三代/二代/混合组装版本，同时在 `blast_hits_all.tsv` 中被 `vg:26797564`、`vg:10020986`、`Nadirvirus` 等以 `E <= 1e-14` 支持）。
  5. `T5-WT_asm_ngcs_scaffold_1.fasta` (`ngcs_scaffold_1`)：最高 `pident = 43.48%`（`vg:79983405`, `E = 2.48e-65`, `299 aa`, 覆盖率 `99.32%`），共命中 8 个查询蛋白（覆盖率均接近 100%，最低 E-value 为 `2.02e-69`）。

## 7. 第 5 步：独立宽阈值敏感度复核与交付确认（已完成）

- **宽阈值单库复核**（关闭低复杂度过滤 `-seg no`，放宽至 `evalue <= 1.0`）：
  - 除上述 5 个强可信阳性文件外，全库 61 个 `[NO_HIT]` 文件中仅 `T7-0.fasta` ~ `T7-5.fasta` 出现 `E = 7.00e-03`、`pident = 31.58%`、`76 aa`（bitscore `35.8`）的弱局部匹配（仅对应 `vg:26797564` C 端片段，缺乏甲基转移酶催化核心基序，含 12% gap）；其余命中均 `E >= 0.16` 属随机噪声；`phold_aa.fasta` 无显著同源。
- **交付文件核验**（全部位于 `results/protein_fasta_search/`，UTF-8 编码）：
  - `search_report.md`
  - `marked_files_summary.tsv`
  - `marked_sequences_summary.tsv`
  - `query_proteins.tsv`
  - `blast_hits_gt30.tsv`
  - `blast_hits_borderline_gt30.tsv`
  - `blast_hits_all.tsv`
  - `marked_hit_sequences.fasta`
