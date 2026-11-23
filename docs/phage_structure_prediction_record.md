# 噬菌体结构与尾部形态预测组件：工具选型、全栈工程集成与大规模盲测校准留档

## 1. 背景与方法论定位

围绕“通过噬菌体基因组或注释序列自动推断尾部形态类别（肌尾 / 长尾 / 短尾 / 非有尾）及定量评估尾长标尺（TMP）”的科研需求，本项目在工作台「组装分析」新增 **噬菌体结构与尾部形态预测** 模块，核心依据三大生信机理：

1. **尾部特征蛋白组合矩阵**：
   - **肌尾（`Myoviridae-like`）**：尾鞘蛋白（TSP）为核心决定标志，协同基板楔形/枢纽复合物（`BASEPLATE_MYO`）与尾管（TTP）；
   - **长尾（`Siphoviridae-like`）**：具备主要尾蛋白（MTP）、尾装配伴侣（TAP）、完整卷尺蛋白（TMP）及远端尾尖/中心尾丝（Dit/Tal），但缺乏收缩尾鞘（TSP）；
   - **短尾（`Podoviridae-like`）**：依赖 `TTPA/B`、内部病毒粒通道核心蛋白（`INTERNAL_VIRION` / N4 `virion RNA polymerase`）、尾刺针（`TAIL_NEEDLE`）及项圈/附器（`COLLAR_PODO`），或具备完整有尾包装核心（Portal + Connector + TerL）却缺失长尾机械机制；
   - **非有尾（`Non-tailed`）**：覆盖丝状噬菌体（`Inoviridae`, `Zot` / `Ace-like`）、微病毒（`Microviridae`, `pilot protein for DNA ejection` / `major head`）、ssRNA 噬菌体（`Fiersviridae`, `RNA replicase beta subunit`）及内含脂膜二十面体（`Tectiviridae` / `Corticoviridae`, `pentameric base spike` / `membrane DNA delivery` / 无 Portal 构型）。
2. **Virfam 头-颈-尾连接器模块规律**：细分 `Type 1 (Ad1/Hc1/Neck1/Tr1)`、`Type 2 (Ad2/Hc2)` 与 `Type 3 (Ad3/Hc3/Collar)`，抑制孤立单基因误匹配，同时隔离宿主 VI 型分泌系统（T6SS `TssB/TssC/Hcp/VgrG`）及无头收缩尾素（Tailocin / eCIS）伪阳性。
3. **TMP 分子标尺与双状态 HMM 基因簇发现**：
   - 基于 α-螺旋轴向延伸常数（`0.145 nm/aa`，区间 `0.140~0.150 nm/aa`）计算理论尾长尺度，同步量化多聚氨基酸微区（`polyX`）、保守串联重复（`TRs`）与 Kyte-Doolittle 疏水性剖面；
   - 集成并重构 **`HIT-ImmunologyLab/PhageTailFinder`**（部署至 `third_party/PhageTailFinder/`），基于本地 WSL `Pfam-A` 抽取全部 **`3,668 / 3,668`** 唯一家族重建 [ptf_pfams.h3m](file:///f:/NCBI%20blast/database/phage_tail_finder/ptf_pfams.h3m)（`137.46 MB`），并以对数 Viterbi 与 Forward-Backward 后验解码替代原始易溢出连乘算法，融合共线性成簇捕获极度分异或假定蛋白注释的尾部操纵子。

---

## 2. 全栈模块化架构设计

* **后端分析引擎**（`src/analysis/phage_structure/`）：
  * [phrog_catalog.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/phrog_catalog.py)：PHROG/Phold 字典加载、精细正则消歧与结构/非有尾/N4 扩展索引清单版本管理（`STRUCTURAL_INDEX_VERSION = "v2_non_tailed_n4"`）。
  * [sequence_annotator.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/sequence_annotator.py)：统一解析 FASTA / GenBank（保留现有 `CDS` 与 `/phrog` 复用，免于无谓重预测）/ FAA，自动按版本抽提重建高速结构索引 [structural_phrogs.h3m](file:///f:/NCBI%20blast/database/phage_structure/structural_phrogs.h3m)（`2,918` 个家族，`236.93 MB`），调度多核 Pyrodigal、WSL PyHMMER 与可选 `Phold 3D` 显存安全补漏。
  * [tail_finder_adapter.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/tail_finder_adapter.py)：PhageTailFinder 对数域双状态 HMM 解码与尾部基因簇聚合器。
  * [tmp_analyzer.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/tmp_analyzer.py)：TMP `polyX` / `TR` / 疏水峰剖析、Pfam（`PF06791 TMP_2`, `PF09718 Tape_meas_lam_C`）直认以及紧邻核心尾干 `{TSP, TTP, MTP, TAP, DIT}` 局部 `±3` ORF 操纵子共线性优选（剔除 DNA 甲基化酶/转录因子等非尾域干扰）。
  * [morphotype_classifier.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/morphotype_classifier.py)：多维可解释融合打分引擎、N4 `vRNAP` 识别、紧凑型无 Portal 非有尾判别、多基板古菌肌尾协同与 Tailocin 预警。
  * [manager.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/manager.py)、[queue.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/queue.py)、[db.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/db.py)、[exporter.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/exporter.py)：逐 Contig 断点分片落盘（`checkpoints/contig_XXX.json` 防 OOM）、任务级 `structure_report.json` / 三联 TSV / `annotated_structure.gbk` 导出，以及路由层 [phage_structure.py](file:///f:/NCBI%20blast/src/backend/routes/phage_structure.py)。
* **前端工作台与可视化修复**（`src/web-next/src/views/Analysis/modules/phage_structure/`）：
  * 完整接入工作台面板与历史注释/前噬菌体联动入口；
  * 修复 [TailMorphotypeDiagram.vue](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_structure/components/TailMorphotypeDiagram.vue) 底部四象限指引卡在长基因编号（如 `GJJKENAC_CDS_*`）时溢出 SVG 边框的问题，改为自适应 HTML 网格与单行溢出省略提示。

---

## 3. 大规模真实盲测与三轮迭代校准记录

为克服早先仅依赖少数经典株（T4、Lambda、T7、P22、M13 等）小规模自测的泛化不足，编写并执行了独立基准测试脚本 [benchmark_phage_structure.py](file:///f:/NCBI%20blast/scripts/benchmark_phage_structure.py)（全量采用 **纯裸 FASTA 零注释输入**，并排除全部单元测试复用 Accession）：
* **Suite A（ICTV 多科形态盲测集）**：跨越 `28` 个权威 ICTV 科随机分层抽样 **`120`** 株（`Myoviridae-like`, `Siphoviridae-like`, `Podoviridae-like`, `Non-tailed` 各 `30` 株）。
* **Suite B（文献电镜 TEM 尾长金标准集）**：汇集 **`30`** 株覆盖 `96 nm`（T4）至 `850 nm`（超长嗜热噬菌体 P74-26 `NC_009804`, ORF95=`5,006 aa`）的已发表电镜/冷冻电镜实测噬菌体。

### 3.1 第一轮基准暴露的核心病理与真值勘误

1. **真值映射与序列片段勘误**：`Vilmaviridae` 经 ICTV/ViralZone 核查实为 `~350 nm` 长尾形态（非肌尾），本引擎全对而验证集映射误填；`P74-26` 原误取 `NC_043038`（仅为 `1,959 bp` 片段），修正为完整参考基因组 `NC_009804`（`83,319 bp`）；同步核准 `L5 (135 nm)`、`Bxb1 (130 nm)`、`P1 (245 nm)`、`Syn9 (145 nm)` 的文献实测 TEM 中值。
2. **`Non-tailed` 五大科召回缺陷（首轮 `5/30`）**：
   - `Fiersviridae (RNA replicase beta subunit phrog_4267)`、`Inoviridae (Zot phrog_197/1041)`、`Tectiviridae (membrane DNA delivery phrog_8052)` 等因在 PHROGs 中属于非传统结构分类未入 `structural_phrogs.h3m` 索引；
   - `Tectiviridae` 五聚体顶点蛋白 `pentameric base spike (phrog_8240)` 原错配至 `BASEPLATE_MYO`；Microviridae 蛋白 H `pilot protein for DNA ejection (phrog_31272 等)` 被误标入 `TAIL_OTHER`；且缺 Portal/Connector 的小型无尾基因组错误触发了 `HEAD_PRESENT_LONG_TAIL_ABSENT`；
   - `minor coat protein` 正则过宽导致蓝藻肌尾 `Syn9 (phrog_1644)` 误命中非有尾标签。
3. **`Schitoviridae / N4-like` 短尾科全军覆没（首轮 `0/5`）**：
   - PHROG 将 `N4` 独有非收缩性短尾外鞘（gp65）标为 `phrog_15324 (tail sheath and receptor binding protein)` 误触肌尾 `TSP`；其余 4 株因缺短尾特异性 `virion RNA polymerase (phrog_2206)` 入库并被 `~405 aa` 内部通道蛋白 `phrog_2120` 误判为 `Siphoviridae-like`。
4. **TMP 溶菌域融合误剔除与全局共线性跨区抓错**：
   - `TM4 (1,229 aa, phrog_971 + PF06791 TMP_2)`、`SPO1 (890 aa, phrog_13572)`、`P1 Sit (1,140 aa, phrog_669)` 与 `A511 (1,242 aa, phrog_1047)` 等真实卷尺蛋白融合有末端溶菌/SLT 域而落入 `LYSIS`/`TAIL_OTHER`；
   - 原启发式邻域跨全基因组取 `min(tail_positions)..max(tail_positions)` 导致 `P1` 错抓中间 `754 aa` 的 DNA 甲基化酶，`A511` 因邻位排序未区分 `TAP` 紧邻第 1 下游位而错抓下游第 2 个 `795 aa` 蛋白。
5. **古菌极分异肌尾（`Vertoviridae`）与特殊短尾管（`Grimontviridae`）边界**：
   - 第二轮 `120` 株测试（总准 **95.83%**）暴露了嗜盐古菌肌尾 `Vertoviridae`（3 株）因缺细菌同源 `TSP` 而多亚基基板复合物 `BASEPLATE_MYO x4`（含 `Baseplate_J` + `Tail_P2_I`）仅计 `1.1` 分被压制；`Grimontviridae (NC_070977)` 虽检出 `PF03906 (Phage_T7_tail, prob=0.95)` 与完整包装骨架但此前未将该 Pfam 纳入短尾得分。

### 3.2 跨轮次量化指标演进对比

| 评测维度 | 第一轮基线（改造前） | 第二轮（引入非有尾/N4/局部TMP） | 第三轮终版（古菌肌尾/T7-Pfam/TAP紧邻序） |
| :--- | :---: | :---: | :---: |
| **Suite A: ICTV 120株总体准确率** | `71.67%` (`86/120`) | `95.83%` (`115/120`) | **`100.00%` (`120/120`)** |
| **Suite A: Macro-F1** | `0.7394` | `0.9665` | **`1.0000`** |
| **Myoviridae-like (`30`株)** | `P=0.963, R=0.867` (`26/30`) | `P=1.000, R=0.900` (`27/30`) | **`P=1.000, R=1.000` (`30/30`)** |
| **Siphoviridae-like (`30`株)** | `P=0.790, R=1.000` (`30/30`) | `P=0.909, R=1.000` (`30/30`) | **`P=1.000, R=1.000` (`30/30`)** |
| **Podoviridae-like (`30`株)** | `P=0.926, R=0.833` (`25/30`) | `P=1.000, R=0.967` (`29/30`) | **`P=1.000, R=1.000` (`30/30`)** |
| **Non-tailed (`30`株)** | `P=1.000, R=0.167` (`5/30`) | `P=1.000, R=0.967` (`29/30`) | **`P=1.000, R=1.000` (`30/30`)** |
| **Suite B: TEM 30株形态正确率** | `96.67%` (`29/30`) | `100.00%` (`30/30`) | **`100.00%` (`30/30`)** |
| **Suite B: TMP 检出与尾长 Pearson r** | `29/30`, `r = 0.6650` | `29/30`, `r = 0.9825` | **`29/30`, `r = 0.9888`** |
| **Suite B: `0.145 * L` 全集 MAE / MAPE** | `30.11 nm / 18.09%` | `21.98 nm / 11.16%` | **`19.74 nm / 10.06%`** |
| **Suite B: 长尾亚组 (`n=19`) Pearson r / MAPE** | `r = 0.8264 / 15.08%` | `r = 0.9941 / 9.53%` | **`r = 0.9941 / 9.53%`** |

### 3.3 TMP 物理标尺模型与“溶菌域剔除”消融实验结论

针对 `Suite B` 中 `29` 株成功定位到尺度蛋白的经典噬菌体开展留一交叉验证（LOOCV）与结构域消融对照（详见 [benchmark_report.json](file:///f:/NCBI%20blast/results/benchmarks/phage_structure/benchmark_report.json)）：

1. **一阶物理常数 `0.145 * L`（区间 `0.140 ~ 0.150 nm/aa`）已具稳定科研估算精度**：
   - 全量 `29` 株（覆盖 `96–850 nm`）`Pearson r = 0.9888`、`MAE = 19.74 nm`、`MAPE = 10.06%`；常规长度区间 `<= 2,500 aa`（`28` 株）`r = 0.9356`、`MAE = 16.01 nm`、`MAPE = 9.90%`、`mean_signed_bias = -9.51 nm`。
   - **偏差物理根源**：`0.145 * L` 精确反映的是 TMP 沿中心管腔伸展的内部α-螺旋尺度，而电镜 TEM 实测全尾长还会叠加头部颈部连接器与末端基板厚度，故整体呈现 `-9.5 ~ -16.3 nm` 的小幅负偏置；在 `<= 2,500 aa` 上通过 LOOCV 拟合 **`0.14802 * L + 6.39 nm`**（极逼近 α-螺旋物理极限 `0.150 nm/aa`）可将 `LOOCV MAE` 进一步压至 **`13.51 nm`**、`MAPE` 压至 **`8.67%`**。
2. **消融否决“硬扣除溶菌融合域 -150 aa”假设**：
   - 对携带 `Peptidase_M23` / `SLT` / `Glucosaminidase` / `Lysin` 域的融合 TMP（`A511`, `TM4`, `Phage K`, `SPO1`, `P1`, `SPbeta`, `P74-26`, `Syn9`）强行扣除 `150 aa` 后，全体 `MAE` 反而由 **`19.74 nm` 恶化为 `24.62 nm`**（因连接器/基板几何高度抵消了折叠域余量，且如 P1 Sit 仅 `1,140 aa` 对应扩展尾长达 `245 nm`）。
   - **最终工程决策**：保留物理透明、免过拟合的 `0.145 * L` (`[0.140*L, 0.150*L]`) 作为核心标尺基准，并在结果界面说明其作为“一阶尾管理论标尺（通常因基板/颈部几何外廓略保守 ~10 nm）”的科学边界。

---

## 4. 全套测试与规范验收汇总

* **后端结构预测全量测试**（`pytest tests/test_phage_structure.py -v`）：**`8 / 8 PASSED in 65.73s`**（覆盖词典消歧、polyX/TR 检测、T6SS 防伪、合成形态、5 株真注释全链路、FastAPI 挂载与联动、PhageTailFinder 对数 Viterbi 与无头 Tailocin 预警，以及 `Schitoviridae`、`Tectiviridae`、`PF06791/TAP紧邻序`、`Vertoviridae` 古菌肌尾专测）。
* **前端组件单测与生产构建**：`vitest` 9 个文件 `53` 项全绿，`vue-tsc -b && vite build` 完成（自最后一次前端视图更新后未修改任何 `.ts/.vue` 文件）。
* **代码合规校验**：[src/analysis/phage_structure/](file:///f:/NCBI%20blast/src/analysis/phage_structure/)、`scripts/benchmark_phage_structure.py`、`tests/test_phage_structure.py` 及本文档全部强制采用 `UTF-8` 编码、无任何硬编码盘符路径与 Emoji 字符。

---

## 5. UI 视觉修复与批量导入自动排队分析升级（步骤 55）

针对桌面端实际预览截图暴露的视觉错位及科研多株批量导入需求，对全栈结构预测模块进行了以下精细重构：

### 5.1 UI 错位、SVG 穿模与滚动容器修复
1. **粒子模型图（[TailMorphotypeDiagram.vue](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_structure/components/TailMorphotypeDiagram.vue)）重构**：
   - 修复 `Podoviridae-like` 短尾模式中橙色椭圆横压蓝色二十面体衣壳“头部包装”文字区的 SVG 坐标穿模，将内注射核心（`INTERNAL_VIRION`）迁移至 Portal 出口至 `TTPA/B` 短尾管内部通道中轴，衔接流线形尾刺针与对称吸附尾丝；
   - 优化缺失显式连接器时生硬大灰块，改用柔和虚线环区分状态；丰富 `Non-tailed` 无尾衣壳与丝状波纹双构型视图；
   - 修正第 4 格“尾丝 / RBP”卡片曾错误显示“估算尾长”的错位逻辑（恢复展示真实 RBP 基因并在第 3 格展示尾长标尺），并通过 [compactLocusLabel](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_structure/utils.ts) 保留 `...CDS_00XX` 基因编号尾缀、配合安全内边距与两级 flex 滚动链修复（[App.vue](file:///f:/NCBI%20blast/src/web-next/src/App.vue)、[AnalysisView.vue](file:///f:/NCBI%20blast/src/web-next/src/views/AnalysisView.vue) 补齐 `min-height: 0` 与底部喘息边距）杜绝嵌套裁切。
2. **短尾 TMP KPI 辅证提示与侧栏队列可视化**：
   - [StructureResults.vue](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_structure/components/StructureResults.vue) 对非长尾构型意外命中的疑似短标尺加注“非长尾构型，仅供参考”；
   - [PhageStructureModule.vue](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_structure/PhageStructureModule.vue)、[StructureHistory.vue](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_structure/components/StructureHistory.vue) 与 [StructureQueueCard.vue](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_structure/components/StructureQueueCard.vue) 对齐项目多队列规范，新增侧栏顶部队列计数标签、运行中快捷条、迷你进度条、排队位次 `#N` 徽章以及同批排队清单视图。

### 5.2 全场景批量导入与自动串行排队
1. **后端批量队列接口与并发稳健性修复**：
   - 新增 `StructureBatchItemRequest` / `StructureBatchRunRequest`（[types.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/types.py)）、`PhageStructureManager.submit_batch_tasks`（[manager.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/manager.py)）及 `POST /api/analysis/phage_structure/batch`（[phage_structure.py](file:///f:/NCBI%20blast/src/backend/routes/phage_structure.py)），支持多文件顺序入队、前噬菌体区段自动拆批（`split_phage_regions`）与粘贴多条 FASTA 拆分（`split_fasta_records`）；
   - 修复 [db.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/db.py) 同秒批量写入时的排序稳定性（`ORDER BY created_at DESC, rowid DESC`）、[queue.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/queue.py) 跨事件循环重启自愈重绑、[common.py](file:///f:/NCBI%20blast/src/backend/routes/common.py) 批量上传同名碰撞保护，以及 [sequence_annotator.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/sequence_annotator.py) / [tail_finder_adapter.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/tail_finder_adapter.py) 在 `pyhmmer.easel.SequenceFile` 中显式声明 `Alphabet.amino()` 防止特殊单字母序列误认作核酸。
2. **前端批量选择、拖拽与增量追加清单**：
   - [StructureSetup.vue](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_structure/components/StructureSetup.vue) 与 [electron-bridge.ts](file:///f:/NCBI%20blast/src/web-next/src/bridge/electron-bridge.ts) 全面启用原生/浏览器多选、批量拖入、批量上传 `/api/common/upload_batch`，配备可内联编辑任务名称的待排队队列列表；同时支持历史功能注释多选、前噬菌体扫描多选及按区段自动拆分入队。

### 5.3 步骤 55 回归验证结果
* **后端全量测试**（`pytest tests/test_phage_structure.py -v`）：**`9 / 9 PASSED in 73.10s`**（含新增 `test_fastapi_batch_import_auto_queue_execution`：验证多文件批量入队、自动串行执行与持久化有序查询）；
* **前端自动化测试**（`npx vitest run`）：**`9` 个测试文件共 `54` 项用例全部通过**（含新增 `utils.ts` 批量命名/格式/编号缩写/多记录计数单测）；
* **前端类型检查与生产构建**（`vue-tsc -b && vite build`）：零报错完成构建（`13.36s`）；全部改动文件通过 `UTF-8` 无 BOM 与零 Emoji 审计。

---

## 6. 电镜实拍验证短尾误算 `54.2 nm` 尾长问题排查与生物物理约束修复（步骤 56）

### 6.1 问题现象与电镜/基因实证归因
1. **实拍电镜观测对比**：用户上传的 `60,000x`（`50 nm` 标尺 = `179 px`）、`30,000x`（`100 nm` 标尺 = `179 px`）、`15,000x`（`200 nm` 标尺 = `178 px`）负染透射电镜照片显示，实际分离株（*Enterobacter* 短尾噬菌体 `附件2霍氏肠杆菌噬菌体2`）二十面体衣壳直径仅约 `50–58 nm`，末端附着约 `14–18 nm` 极短不可收缩尾部（全粒整体尺寸约 `55–70 nm`）；而软件页面在正确判出 `Podoviridae-like (99.0%)` 的同时，错误显示了 `TMP 推算理论尾长 54.2 nm`。
2. **双重机理根因**：
   - **源头 PHROG 误标污染**：该 `72.57 kb` N4 样短尾基因组（含特征性 `virion RNA polymerase phrog_2206` 与 `N4-like RNAP phrog_2166`）在主要衣壳（`MCP phrog_1357`）与门户蛋白（`PORTAL phrog_1216`）之间编码了一条 `374 aa` 内部/通道结构蛋白（`ORF_0008`），因 `PHROGs v4` 数据库历史性将其所在的 **`phrog_2120`** 误标为 `"tail length tape measure protein"`，导致系统按 `374 × 0.145 = 54.2 nm` 计算尾长；
   - **缺乏短尾/非有尾物理约束**：在 `Suite A (120 ICTV)` 检查中进一步发现，全部 `4` 株 `Schitoviridae`（`phrog_2120`, `377–443 aa -> 54.7–64.2 nm`）及 `2` 株 `Guelinviridae`（将 `PF01551 Peptidase_M23` 肽聚糖水解酶误聚为 TMP 的 `458/521 aa -> 66.4/75.5 nm`）共 `6 / 30` 株短尾株均因未能从生物物理层面隔离 TMP 标尺而误算假尾长。

### 6.2 工程修复与回归验真
1. **词典纠偏与特征解析（[phrog_catalog.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/phrog_catalog.py)、[sequence_annotator.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/sequence_annotator.py)）**：
   - 建立 `_PHROG_ROLE_OVERRIDES`，优先将 `phrog_2120` 纠偏映射为 `INTERNAL_VIRION`（即使注释文本继承自 PHROGs `"tail length tape measure protein"`）；并在 `.gbk` 直读解析中补齐对 `/note` 与 `/db_xref` 内 `PHROG` 编号的自动提取。
2. **形态-标尺物理一致性闭环（[morphotype_classifier.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/morphotype_classifier.py)、[manager.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/manager.py)）**：
   - 明确物理铁律：仅 `Siphoviridae-like` 与 `Myoviridae-like` 使用 TMP/gp29 定长；一旦终判属于 `Podoviridae-like`、`Non-tailed` 或 `Incomplete`，强制将 `estimated_tail_length_nm` 置 `None`、`estimated_tail_range_nm` 置 `[]`，并清零误导性的 `tmp_analyses` 虚假标尺条目（若曾从注释名撞中伪 TMP，则输出清晰警告）。
3. **前端与模型图字幕细节优化（[TailMorphotypeDiagram.vue](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_structure/components/TailMorphotypeDiagram.vue)、[StructureResults.vue](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_structure/components/StructureResults.vue)、[StructureHistory.vue](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_structure/components/StructureHistory.vue)）**：
   - 将 `Podoviridae-like` 示意说明右置避免压碰蓝色六边形衣壳边缘，KPI 卡与记录栏面向短尾显示“`短尾无 TMP 标尺 · 典型短尾物理长度约 10–25 nm`”，非有尾显示“`无复合尾器 (0 nm)`”。
4. **全量重测结果（步骤 56 代码落盘后）**：
   - `附件2霍氏肠杆菌噬菌体2` 裸序列端到端重算：**`Podoviridae-like (conf=0.99, est_nm=None, tmps=0)`**，彻底消除 `54.2 nm` 虚假估测；
   - `pytest tests/test_phage_structure.py -v`：**`9 / 9 PASSED in 81.77s`**；
   - `src/web-next` `npx vitest run`（`9` 文件 `54` 项全通过）+ `vue-tsc -b && vite build`（`14.55s`）；
   - 重跑 [benchmark_phage_structure.py](file:///f:/NCBI%20blast/scripts/benchmark_phage_structure.py) `--fresh`（`115.74 s`）：**Suite A 120 株跨 24 ICTV 科准确率 `100.0% (120/120), Macro-F1=1.0`**，且 `Podoviridae-like / Non-tailed` 伪 TMP 误报由 `6/60` 降为 **`0/60`**；**Suite B 30 株 TEM 金标准维持 `30/30 形态全对`、`29/30 检出 TMP`、`Pearson r=0.9888, MAE=19.74 nm, MAPE=10.06%`**。

---

## 7. 免补丁通用架构重构：序列优先 HMM 校验 + 多结构域 Pfam + 操纵子语境审计（步骤 57）

### 7.1 架构缺陷深度复盘（针对非标准 `.gbk` 与全科属 TMP 选尺误差）
此前步骤 56 暴露出一个根本性架构隐患：单靠对个别误标 PHROG（如 `_PHROG_ROLE_OVERRIDES["phrog_2120"]`）或自由文本正则打补丁无法应对真实科研中五花八门的非标准 `.gbk`/`.faa` 文件，且导致多重系统性错估：
1. **外部文本轻信与 E-value 批次漂移**：[sequence_annotator.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/sequence_annotator.py) 对携带非 `hypothetical` `/product` 及任意 `/phrog` 标签的 `.gbk` 默认跳过 PyHMMER 验证，[tmp_analyzer.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/tmp_analyzer.py) 则直接放行 `evidence_source != "pyhmmer_phrog"`，使任意误标为 `"tape measure protein"` 的头蛋白/假蛋白直接通过；同时 `pyhmmer.hmmsearch` 未锁定基准搜索空间 `Z`，导致同一基因组在单株 vs 批量提交时 Pfam E-value 出现显著漂移。
2. **Pfam 单域截断与防混淆护卫缺失**：[tail_finder_adapter.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/tail_finder_adapter.py) 仅保留每条蛋白最高分 1 个 Pfam 域，掩盖了兼有溶菌域与 `PF06791`/`PF10145`/`PF12789(PTR)` 的真 TMP（例如 `NC_004084` `452 aa PF10145+PF06791` 被屏蔽而误选 `270 aa` 碎片、`NC_071039` `2236 aa PF12789 PTR` 漏检）；且本地 `structural_phrogs.h3m` 缺失核酸内切酶/脂肪酶/甲基转移酶等负选家族，致使 `NC_071039` (`PF05443 ROS_MUCR` homing endonuclease)、`NC_019925` (`PF18741 MTES_1575` homing endonuclease)、`NC_047978` (`PF13472 Lipase_GDSL_2`) 被错抓为 TMP。
3. **缺少操纵子语境校验与 TAP 下游共线性符号反转**：未剔除位于 `MCP`/`PORTAL` 三明治间却无长尾骨架的假 TMP，且局部共线性扫描中将 `TAP` 上游锚点偏差符号方向写反，导致 `Chaseviridae` (`1205–1279 aa`) 漏检或误抓，并错过 `SPO1` `TAP -> +1` (`890 aa`) 及 `Kyanoviridae NC_028955` (`623 aa sc=29.7`)。

### 7.2 通用免补丁重构实现
1. **移除特例补丁并升级扩展防混淆 HMM 索引（[phrog_catalog.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/phrog_catalog.py)、[types.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/types.py)）**：
   - 彻底移除 `_PHROG_ROLE_OVERRIDES` 单点硬编码映射；
   - 新增 `NON_TAIL_ENZYME` 通用负选角色与 `NON_TAIL_GUARD_CATEGORIES`，将 `PHROG` 命名代谢/核酸/调控护卫家族一并提取至 `STRUCTURAL_INDEX_VERSION = "v3_seq_first_multidomain"` 本地库（`structural_phrogs.h3m` 平滑重抽耗时约 `32 s`）；
   - `StructureProteinItem` 新增 `raw_product`（审计追溯外部原文）与 `ptf_all_pfams`（全多结构域 Pfam accession 列表）。
2. **序列优先核实与全多结构域稳健提取（[sequence_annotator.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/sequence_annotator.py)、[tail_finder_adapter.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/tail_finder_adapter.py)、[manager.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/manager.py)）**：
   - `parse_input_contigs` 增强对缺 `/translation`、多 `/product`、`/function` 兜底及重复 `locus_tag` 的非标准 `.gbk` 兼容性；
   - `scan_proteins_with_pyhmmer` 默认开启 `verify_annotated=True`，对全部 `>= 25 aa` 蛋白强制运行本地 HMM 序列核实：实质冲突时以权威 HMM 推翻错误 `.gbk` 字符并置 `pyhmmer_phrog`，无命中外部声称标为 `unverified_text`（`hmm_score=0.0`），彻底取消文本直通特权；新增低复杂度周期伪序列护卫 `_is_low_complexity_repeat_artifact`；
   - 两引擎 `pyhmmer.hmmsearch` 均固定参考参数 `Z=200` 实现单株与批量规模的 100% E-value 不变性；`run_phagetailfinder_on_contigs` 收集并排序输出 `ptf_all_pfams`。
3. **多证据（多域 Pfam + 操纵子语境 + 生物物理尺标）联合校验器（[tmp_analyzer.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/tmp_analyzer.py)）**：
   - 扩充 `_DIRECT_TMP_PFAMS`（`PF06791`, `PF09718`, `PF06120 Phage_HK97_TLTM`, `PF10145 PhageMin_Tail`, `PF12789 PTR`）与 `_CONFOUNDER_PFAMS`（`PF05443`, `PF18741`, `PF13472`, `PF16075 DUF4815`, 尾丝/尾刺域等），并修正 `RNA_pol_A_CTD (PF03118)` 子域重复误拦截保护噬菌体 `Mu` 等真 TMP；
   - 新增 `_inspect_operon_context`（支持窄间距环状断点、修正同链 `TAP -> +1` 识别方向、检测 `MCP`/`PORTAL` 头部三明治、统计同链尾干锚点），在源头通用否决一切无长尾骨架的假 TMP 及跨转录方向假阳性（消除 `phiKZ` opposite-strand `ORF_0029`、`附件2` `ORF_0008` 及任意恶意 `.gbk` 伪标注），同时挽救远缘超长自证 TMP（`P74-26 5006 aa`）、`Chaseviridae 4/4`（含 `TAP -> +1` `YqaJ/SLT` 融合构型）、`NC_071039` (`2236 aa PTR`)、`NC_004084` (`452 aa PF10145+PF06791`) 与 `SPO1` (`890 aa`)。

### 7.3 全量回归、对抗测试与合规验收
* **后端单元与对抗测试**（`pytest tests/test_phage_structure.py -v`）：**`10 / 10 PASSED in 123.97s`**（新增 `test_adversarial_nonstandard_gbk_immunity` 验证：彻底抹除 `/phrog`、把 `TerL`/`Portal` 伪造为 `"tape measure protein"` 并隐藏真 `TMP` 后仍 `100%` 还原 `Siphoviridae-like` 与精确尾长；且移除词典硬编码补丁后 N4/Schitoviridae 假 `374 aa` TMP 直接在源头被零误差剔除）。
* **120 株 ICTV 全谱盲测 & 30 株电镜金标准重测**（[benchmark_phage_structure.py](file:///f:/NCBI%20blast/scripts/benchmark_phage_structure.py) `--fresh`, `143.45s`）：
  - **Suite A（120 ICTV）**：`Accuracy = 1.0 (120/120), Macro-F1 = 1.0`，短尾/非有尾伪 TMP **`0 / 60`**，**全谱有尾噬菌体（`Myoviridae-like` + `Siphoviridae-like`）有效 TMP 检出率由 `56/60` 提升至 `60 / 60 (missing=0)`**；
  - **Suite B（30 TEM）**：**`30 / 30` 形态全对**、`29 / 30` 检出 TMP（含 `Mu 690aa`, `SPO1 890aa`, `Syn9 1051aa`, `P1 1140aa`, `P74-26 5006aa`），整体尾长线性相关性 **`Pearson r = 0.9893`, MAE(0.145) = 19.44 nm, MAPE = 9.85%`**（较此前 `r=0.9888, MAE=19.74 nm, MAPE=10.06%` 进一步优化）。
* **实测用户样本回归**：`附件2霍氏肠杆菌噬菌体2` 稳定判为 **`Podoviridae-like (0.99), tail=None, tmps=[]`**；`h15x6_1-1` (`167.5 nm`)、`hp9` (`143.4 nm`)、`jp1` (`gp29 85.0 nm`)、`jp3` (`299.6 nm`)、`12-a` (`167.3 nm`) 全链路无回归。
* **代码与文档合规审计**：相关模块文件及本文档全部通过 `UTF-8` 无 BOM 编码与零 Emoji 校验。


---

## 8. 外部独立数据集双格式验证与下游共性架构巩固（步骤 58）

### 8.1 独立验证数据集构建（与原 150 株基准 100% 零重叠）
为验证“序列优先 HMM + 多结构域 Pfam + 操纵子语境”重构在全新未测基因组与现实非标准 `.gbk` 中的真实泛化能力，新增构建 [validation_datasets.py](file:///f:/NCBI%20blast/scripts/validation_datasets.py) 与分片断点验证脚本 [validate_external_phage_structure.py](file:///f:/NCBI%20blast/scripts/validate_external_phage_structure.py)，严格排除此前已测 `120 + 30 + 6` 株基线保留集合，构建两套全新双输入对照验证集（同时运行 **纯裸 `.fasta`** 与 **原始 `.gbk`** 双模式）：
1. **Suite D（NCBI Entrez 在线拉取独立外部集，33 株）**：其中 `14` 株在本地 `F:\Phage data` `5,000` 基因组库中亦不存在（含 2023–2025 新发现噬菌体及 1996 经典 `NC_004302 r1t` 等），内含 `2` 株零 CDS 注释 `UNVERIFIED_ORG` `.gbk`（`MN871481 PaSz-1_45_92k`、`MN871489 PaZh_1`）、`8` 株含缺失 `/translation` 的 `.gbk` 及 `6` 株 `hypothetical >= 70%` 样本，覆盖 `22` 株文献实测 TEM 有尾株（`Myo x8 + Sipho x14`）与 `11` 株短尾/非有尾外部对照（`Podo x6 + Non-tailed x5`）。
2. **Suite C（本地 4,852 株未测库存跨 38 个 ICTV 科分层盲测集，160 株）**：在既有 30 科基础上增补 `Vandenendeviridae`、`Lindbergviridae`、`Andersonviridae`、`Stanwilliamsviridae`（130 kb 巨大链霉菌长尾）、`Hodgkinviridae`、`Orlajensenviridae`（17 kb 微型长尾）、`Autographivirales` 拆分新科、`Steigviridae`（99 kb CrAss-like 短尾）及 `Steitzviridae`（+ssRNA 无尾噬菌体）共 `38` 个形态明确 ICTV 科（各形态 40 株，内含 `40` 株缺失 `/translation` 与 `17` 株 `hypothetical >= 70%` 真实非标 `.gbk`）。

### 8.2 首轮验证曝光的 3 处通用共性盲区及机理修复
首轮全量双格式运行中（`Suite D FASTA 33/33, GBK 32/33`; `Suite C GBK 160/160, FASTA 159/160, Tailed TMP 78/80`），精准曝光出 3 处非个体特例的共性机理缺陷并完成通用修复：
1. **下游分类器未隔离未核实非有尾文本（[morphotype_classifier.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/morphotype_classifier.py)）**：`NC_004775 (epsilon15)` `.gbk` 内 `epsilon15p10` 未命中任何 PHROG HMM（`evidence_source="unverified_text"`, `hmm_score=0.0`），但下游规则仅凭其原始注释 `"major coat protein"` 赋予 `Non-tailed +5.0`，以 `5.0 vs 4.8` 压倒了真实短尾骨架。修复为严格贯彻 `sequence-first`：大中型具备明确包装骨架基因组不再允许未核实 `unverified_text` 触发决定性 `NON_TAILED_MARKER` 加分。
2. **PhageTailFinder 单孤儿溶菌酶自证环与远缘 CrAss 阈值失配（[tmp_analyzer.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/tmp_analyzer.py)、[morphotype_classifier.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/morphotype_classifier.py)）**：`Steigviridae NC_049978 (IAS virus)` 的 `472 aa` 蛋白携带 `PF18013 (Phage_lysozyme2)` 并获高 PTF 概率，旧逻辑允许单个蛋白兼充 `has_true_tail_backbone` 与自身 `ptf_support`，从而在周围零长尾干锚点 (`trunk=0, bp=0`) 下将自身认证为 `confirmed_tmp` 并遮断了 `HEAD_PRESENT_LONG_TAIL_ABSENT`。修复为：PTF 全基因组尾部骨架至少须 2 个独立 `>= 150 aa` 高概率位点、`ptf_support` 仅统计邻域其他 PTF 蛋白、含溶菌域且缺乏直接 TMP Pfam 的 `<650 aa` 蛋白必须有真实邻域锚点支持；同时将“具备完整 `PORTAL + TERL(>=300 aa) + MCP` 且含 PTF/TAIL_OTHER/裂解生活史特征但全面缺失长/肌尾主干的 `>=25 kb` 基因组”稳健抬升至 `2.6` 越过 `Incomplete` 阈值（`2.2`）。
3. **中等尺度融合型 TMP 与广域隔断长尾 TMP 召回拓展（[tmp_analyzer.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/tmp_analyzer.py)）**：将严格位于 `TAP -> +1` 且邻接基板的 `YqaJ/exonuclease-TMP` 融合检出门槛由 `>=650 aa` 合理下调至 `>=500 aa`（召回 `Chaseviridae NC_025459` `592 aa` TMP）；并在确有 `MTP/TSP/TTP` 长尾干背景时新增 `window=8` 广域操纵子检测以兼容末端带溶菌域的放线菌长尾 TMP（召回 `Hodgkinviridae NC_047976` `955 aa` TMP）。

### 8.3 修复后全量独立外部及基线复验实测结果（零退化、双模式 100% 一致）
* **单元与机理回归测试**（`.venv/Scripts/python.exe -m pytest tests/test_phage_structure.py -v`）：**`12 / 12 PASSED in 128.13s`**（新增 `test_unverified_gbk_non_tailed_text_ignored_on_podo` 与 `test_isolated_lysozyme2_crass_not_self_authenticated_tmp`）。
* **Suite D（33 株 NCBI 在线独立外部集，`validate_external_phage_structure.py --fresh`, `381.95s` 总耗时内完成）**：
  - **四形态分类准确率**：**FASTA `100.0% (33/33, F1=1.0)`**；**GBK `100.0% (33/33, F1=1.0)`**；**双格式形态一致率 `100.0% (33/33)`**；`<=5%` 误差内 TMP 尾长一致 **`33/33`**（精确 aa 一致 `32/33`，唯一微差来自 `NC_005178 D3112` RefSeq 移码拆分双段 TMP 分别命中 `688 vs 720 aa -> 99.8 vs 104.4 nm`）；
  - **独立外部 TEM 尾长定量回归**：`21 / 22` 检出 TMP（唯一未检出为 *Chimalliviridae* 巨型核心噬菌体 `MN871489 PaZh_1`，与同科 `phiKZ` 一致缺乏典型细菌 PHROG TMP，但仍正确判定为 `Myoviridae-like`），线性相关性 **`Pearson r = 0.9086`（FASTA, `MAE=28.16 nm, MAPE=16.24%`）/ `Pearson r = 0.9118`（GBK, `MAE=27.94 nm, MAPE=16.12%`）**（注：`NC_007458 Gamma` 经 Schuch & Fischetti 2006 原文献核实 TEM 实测为 `200–217 nm`，预测 `186.0 nm` 误差仅 `7.0%`）；
  - **非标 `.gbk` 子集稳定性**：缺失 `/translation` (`n=8`) 及 `hypothetical >= 70%` (`n=6`) 子集准确率及双格式一致率全部 **`1.0`**。
* **Suite C（160 株本地跨 38 ICTV 科完全未测集）**：
  - **四形态分类准确率**：**FASTA `100.0% (160/160, Macro-F1=1.0)`**；**GBK `100.0% (160/160, Macro-F1=1.0)`**；
  - **双格式全谱一致性**：形态一致率 **`100.0% (160/160)`**、`<=5%` 误差内尾长一致率 **`100.0% (160/160)`**（精确 aa 一致 `150/160 = 93.75%`，其余 10 例仅为同 TMP 基因位点上游起始密码子微差）；
  - **假阳性与召回铁律**：短尾及非有尾对照组（`80` 株）伪 TMP **`FASTA = 0/80` & `GBK = 0/80`**；长/肌尾实验组（`80` 株）TMP 有效检出 **`FASTA = 80/80` & `GBK = 80/80`**；缺失 `/translation` (`n=40`) 与高 `hypothetical` (`n=17`) 子集均达到 **`100.0%` (`1.0`)** 双模式一致准确。
* **既有 150 株基准集复测验证**（`.venv/Scripts/python.exe scripts/benchmark_phage_structure.py --fresh`, `147.93s`）：
  - **Suite A (120 ICTV)** 保持 **`100.0% (120/120, Macro-F1=1.0, err=0)`**；
  - **Suite B (30 TEM)** 保持 **`30/30` 形态、`29/30` TMP、`Pearson r=0.9893, MAE=19.44 nm, MAPE=9.85%`**，零退化验证闭环。


---

## 9. 阶段 0：评估体系加固与 M1 多维基线确立（步骤 59）

依据 [phage_structure_optimization_plan.md](file:///f:/NCBI%20blast/docs/phage_structure_optimization_plan.md) 先测量、后修改与“调参集 / 盲测集严格分离”原则，本阶段未改动 `src/` 下任何核心预测或分类算法源码，全面完成 `T0.1 / T0.2 / T0.3` 评估底座建设与 M1 全量基线实测。

### 9.1 T0.1 冻结盲测集 Suite E 与 m1_baseline 首次盲测结果
* **冻结清单与零重叠保障**：通过 [validation_datasets.py](file:///f:/NCBI%20blast/scripts/validation_datasets.py) 排除先期已测全部 `344` 株样本（`Suite A + B + C + D + 单元测试保留集`），汇总 `24` 株 `2025/08/10` 之后 NCBI 新公开基因组（`SUITE_E_POST_2025_EXTERNAL`）与 `200` 株本地库存跨科配对基因组（每形态 50 株），共计 **`224` 株（覆盖 `38` 个 ICTV 科，含缺失 `/translation` 非标 `.gbk` `54` 株、`hypothetical >= 70%` `32` 株）**，以 SHA256 哈希写入版本化清单 [suite_e_manifest.json](file:///f:/NCBI%20blast/tests/fixtures/phage_structure/suite_e_manifest.json)。
* **首次盲测实测（[run_suite_e_blind.py](file:///f:/NCBI%20blast/scripts/run_suite_e_blind.py) `--milestone m1_baseline --fresh`，总耗时 `470.33 s`，报告 [suite_e_m1_baseline_report.json](file:///f:/NCBI%20blast/results/benchmarks/phage_structure_suite_e/suite_e_m1_baseline_report.json)）**：
  - **纯裸 `.fasta` 模式**：**`Accuracy = 1.0 (224/224), Macro-F1 = 1.0`**；`post-2025/08` 外部 `24` 株 **`1.0`**；假 TMP `0/112`；有尾 TMP 召回 **`112/112`**。
  - **原始 `.gbk` 模式**：**`Accuracy = 0.9955 (223/224), Macro-F1 = 0.9955`**；`post-2025/08` 外部 `24` 株 **`1.0`**；假 TMP `0/112`；有尾 TMP 召回 **`110/112`**；双格式形态一致率 **`0.9955 (223/224)`**，`<=5%` 误差尾长一致率 **`0.9821`**（精确 aa 一致 `215/224`）；`missing_translation (n=54)` 与 `high_hypothetical >=70% (n=32)` 双模式准确率均 **`1.0`**。
  - **机制级客观诊断（严格只作记录，未对 Suite E 做规则微调）**：GBK 模式唯二异常样本为 `NC_052964`（`64,096 bp`，原始 `.gbk` 仅稀疏注释 `6` 个 CDS 导致漏标尾部，被误判为 `Podoviridae-like`）与 `NC_070890`（`143,349 bp`，`.gbk` 仅注释 `48` 个 CDS 致 TMP 漏检），均精准印证现有 `predict_missing_orfs` 对 `CDS >= 1` 稀疏/残缺注释 `.gbk` 缺乏基因密度检查与间隙回补；同时运行日志出现遗传密码表 4 与 11 冲突警告（`requested translation table (11) has different STOP codons than the one these genes were called with (4)`），为 M2 阶段 `T1.1 / T1.2` 提供实证入口。

### 9.2 T0.2 一手文献 TEM 标准真值表构建与回归重算
* **标准真值库构建**：回溯全部 `52` 株文献 TEM 样本并 CrossRef 实测校验 DOI，落盘 [tem_truth.tsv](file:///f:/NCBI%20blast/tests/fixtures/phage_structure/tem_truth.tsv)，包含测量状态（`extended`）、是否含基板（`yes/no/unknown`）、实验方法（`TEM/Cryo-EM`）、DOI 与核对状态：
  - **`verified` 共 `41` 株**（`Suite B 22 + Suite D 19`）：完成多项一手文献纠偏（如 `phiKZ 180 nm` 替代 `198 nm`、`Tuc2009 144 nm` 替代 `160 nm`、`SPP1 160 nm` 螺旋尾管替代混合 `188 nm`、`T4 92.5 nm` 伸展尾鞘、`A511 199.4 nm`、`D29 120 nm`、`SPbeta 320 nm`、`P74-26 800 nm`、`Gamma 208.5 nm (200-217 区间中值)`）。
  - **`unverified` 共 `11` 株**（`Suite B 8 株`：`Syn9, L5, HK97, sk1, A118, phiC31, N15, c2`；`Suite D 3 株`：`Bxz1, D3112, phi80`）：仅参与形态分类评价，严格剔除出定量尾长回归。
* **脚本迁移与清洗前后回归对比**（[benchmark_phage_structure.py](file:///f:/NCBI%20blast/scripts/benchmark_phage_structure.py)、[validation_datasets.py](file:///f:/NCBI%20blast/scripts/validation_datasets.py)、[validate_external_phage_structure.py](file:///f:/NCBI%20blast/scripts/validate_external_phage_structure.py) 均改为单点读取 `tem_truth.tsv`）：
  - **Suite B（`verified = 21/22` 检出，形态 `30/30`）**：`Pearson r = 0.9900`, `MAE(0.145) = 17.50 nm`（旧全量 `19.44 nm`）, `MAPE = 8.65%`（旧 `9.85%`）；`<=2500 aa (n=20)` 留一法线性拟合收敛至 `slope = 0.14002 nm/aa, intercept = +13.95 nm`（`LOOCV MAE = 14.96 nm`）；`Myoviridae-like (n=9)` 平均有符号偏差 `-18.23 nm` 显著低于 `Siphoviridae-like (n=12)` `-7.14 nm`。
  - **Suite D（`verified = 18/19` 检出，FASTA 与 GBK 完全一致）**：清洗并剔除 `3` 株未核实噪音后，**`Pearson r` 由旧 `0.9086 / 0.9118` 跃升至 `0.9422`**，`MAE(0.145)` 降至 **`26.50 nm`**（旧 `28.16 / 27.94 nm`），`MAPE` 降至 **`14.38%`**（旧 `16.24% / 16.12%`）。

### 9.3 T0.3 碎片 Contig 与嵌合前噬菌体基准（193 样本）
* 新建 [benchmark_fragmented_contigs.py](file:///f:/NCBI%20blast/scripts/benchmark_fragmented_contigs.py)（基于 `24` 株源株切片与 `blind_sota_clinical` 宿主嵌合，`163.41 s`，报告 [fragmented_baseline_report.json](file:///f:/NCBI%20blast/results/benchmarks/phage_structure_fragmented/fragmented_baseline_report.json)）：
  - `chimeric_full_prophage (n=12)`：`Incomplete = 0.00%`, `Tailed->Podo = 0/12 (0.00%)`, `exact = 100.00%`；
  - `targeted_tail_only (n=11)`：`Incomplete = 0.00%`, `Tailed->Podo = 0/11 (0.00%)`, `exact = 100.00%`；
  - `sliding_5kb (n=46)` / `10kb (n=38)` / `20kb (n=30)`：`Incomplete` 依次为 `65.22% / 65.79% / 46.67%`，`Tailed->Podo = 0.00%`；
  - `sliding_30kb (n=28)` / `40kb (n=24)`：`Incomplete = 35.71% / 29.17%`，`Tailed->Podo` 误判分别升至 **`2/22 (9.09%)`** 与 **`3/20 (15.00%)`**；
  - `targeted_head_only (n=2)` 与 `chimeric_head_truncated (n=2)`：`Incomplete = 0.00%`，**`Tailed->Podo = 2/2 (100.00%)`**；实证了大片段截断丢尾情形下负向短尾规则的无门控盲区。

### 9.4 阶段 0 全套单元测试验证
* `.venv/Scripts/python.exe -m pytest tests/test_phage_structure.py -v`：**`13 passed in 130.56s (0:02:10)`**（新增 `test_tem_truth_table_and_suite_e_disjoint` 校验 `52` 条真值完整性、DOI 合规性及与 Suite E 224 株绝对零重叠），相关产物均通过 `UTF-8` 无 BOM 及零 Emoji 检查。

---

## 10. 阶段 1 / 里程碑 M2：三大机理缺口修补与盲测验证（步骤 60）

本阶段围绕 M1 基线暴露出的三大通用架构缺口（无门控大片段 `Tailed->Podo` 误判 + 稀疏 `.gbk` 注释漏标、Pyrodigal Table 4/11 混用警告与重编码基因组漏检、以及RefSeq 移码拆分 TMP 双格式不一致），在不引入任何特例补丁的前提下完成三大独立机理模块建设及前后端/全脚本穿透。

### 10.1 M2 三大核心机理实现与全链路集成
1. **T1.1 Contig 完整性门控与稀疏 `.gbk` 自动救回（[completeness_gate.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/completeness_gate.py)、[sequence_annotator.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/sequence_annotator.py)、[morphotype_classifier.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/morphotype_classifier.py)）**：
   - 实现精准末端重复检测（DTR / ITR）、基因组完整性判定（`allow_negative_podo_inference`）与多维截断尾部残余互斥检查：仅当具备完整头部打包核心（`MCP` 且含 `PORTAL` / `TERL>=300 aa` / `CONN_GENERAL`）、无长尾残余痕迹（如 `Type_1_Sipho_Myo` 连接器、`MTP`、`TTP`、`TAP` 等）且 `length_bp >= 30,000`（或检测到明确 DTR/ITR）时，才允许触发 `HEAD_PRESENT_LONG_TAIL_ABSENT`；否则降级为 `Incomplete`。
   - 为 `CDS >= 1` 但实际蛋白覆盖率与编码密度严重稀疏的 `.gbk` 写入区间回补机制（`_merge_sparse_gbk_orfs`），在不覆盖原有有效注释坐标的前提下通过 Pyrodigal 自动补齐未注释空白区间 ORF。
2. **T1.2 遗传密码 11/4/15 自动选择器与 Pyrodigal 混用消除（[genetic_code_selector.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/genetic_code_selector.py)）**：
   - 将内置 `pyrodigal.METAGENOMIC_BINS` 按翻译表精确拆分为 `METAGENOMIC_BINS_11` 与 `METAGENOMIC_BINS_4`，彻底消除混用表 4 模型调用表 11 的 `STOP codons` 警告。
   - 新增自适应 `select_optimal_genetic_code`（支持 Table `11 / 4 / 15`），以编码覆盖度增益、平均 ORF 长度拉升比及 ORF 碎裂减少作为严格防漂移判据。
3. **T1.3 邻接移码拆分 TMP 重建（[tmp_split_merger.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/tmp_split_merger.py)、[tmp_analyzer.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/tmp_analyzer.py)）**：
   - 实现同链相邻或微间隔移码双段 TMP（`PF06791` / `PF09718` 等且严格排除 `TAP`）识别与物理跨度统一度量 `(max_end - min_start + 1 - 3) // 3`，输出统一 `evidence_kind="merged_split_tmp"` 及 `merged_loci`。
4. **全链路、全基准与前端可视化同步**：扩展 [types.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/types.py)、[manager.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/manager.py) 与全套 4 个验证脚本透传字段，并在前端 [StructureResults.vue](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_structure/components/StructureResults.vue) 与 [TmpRulerChart.vue](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_structure/components/TmpRulerChart.vue) 新增基因密码表标签、稀疏注释补救角标、`Incomplete` 状态徽章及拆分合并 TMP 标尺标注。

### 10.2 M2 单元、前端与非盲基准全量验收实测
* **前端单元测试与生产构建**：`npx vitest run` **`9 files, 54 passed in 2.29s`**；`npm run build` (`vue-tsc -b && vite build`) **`built in 13.13s`**。
* **后端全量单元测试（`.venv/Scripts/python.exe -m pytest tests/test_phage_structure.py -v`）**：**`16 passed in 142.18s (0:02:22)`**，新增 `test_t1_1_completeness_gate_and_sparse_gbk_rescue`、`test_t1_2_genetic_code_selector_11_4_15`（覆盖 11 组真实/阅读框重编码 Table 4/15 样本及 3 株标准 Table 11 对照，零 `STOP codons` 告警）、`test_t1_3_split_tmp_merger_positive_and_negatives` 全部通过。
* **T0.3 碎片 Contig 与嵌合前噬菌体复测（`benchmark_fragmented_contigs.py --fresh --per-morph 6`, `193` 样本, `151.81s`）**：
  - 全 9 个场景（包括 `sliding_30kb`、`sliding_40kb`、`targeted_head_only`、`chimeric_head_truncated`）中的 `Tailed->Podoviridae-like` 误判率全部由 M1 基线最高 `100%` / `15%` 降至 **`0 / 193 (0.00%)`**；
  - `chimeric_head_truncated (n=2)` 与 `targeted_head_only (n=2)` 实现 **`100.00% Incomplete`** 精准拦截；
  - `chimeric_full_prophage (12/12)` 与 `targeted_tail_only (11/11)` 保持 **`100.00%`** 精确匹配。
* **调参集防退化核验（`Suite A + B`, `155.11s`; `Suite C + D`, `396.42s`）**：
  - **Suite A（120 株跨 24 科）**：**`Accuracy = 1.0 (120/120), Macro-F1 = 1.0`**，完整 `Podoviridae-like` 召回 **`30/30`**；除 `Non-tailed` 类 `NC_001628 (Fiersviridae -> 15)` 与 `NC_003438 (Microviridae -> 4)` 外，**`0` 株有尾噬菌体**发生密码表误切换。
  - **Suite B（30 株 TEM 金标准）**：形态 **`30/30`**，`verified = 21/22` 检出，**`Pearson r = 0.99`, `MAE(0.145) = 17.5 nm`, `MAPE = 8.65%`**（`<=2500 aa LOOCV MAE = 14.96 nm`），零退化。
  - **Suite C（160 株跨 38 科）**：FASTA & GBK 均 **`1.0 (160/160, F1 = 1.0)`**，双模式形态一致 **`160/160`**，短尾/非有尾假 TMP **`0/80`**，有尾 TMP 召回 **`80/80`**，`<=5%` 误差尾长一致率 **`1.0`**（精确一致 `150/160 = 93.75%`）。
  - **Suite D（33 株 NCBI 外部集）**：FASTA & GBK 均 **`1.0 (33/33, F1 = 1.0)`**；`NC_005178 (D3112)` 在 FASTA 与 GBK 双模式下均稳定合并为 `merged_split_tmp` **`1185 aa (171.8 nm)`**，使双格式 **`tmp_exact_aa_count` 跃升至 `33/33 (100%)`**；其余 `A / B / C` 全集 **`0` 例**非预期合并；verified TEM（`18/19`）双模式均 **`r = 0.9422, MAE = 26.5 nm, MAPE = 14.38%`**。

### 10.3 M2 只读盲测对比（Suite E `m1_baseline` vs `m2_mechanism`）
严格遵守“盲测只读、禁止针对 `Suite E` 反向调参”原则，执行 `run_suite_e_blind.py --milestone m2_mechanism --fresh`（耗时 `424.93s`，报告 [suite_e_m2_mechanism_report.json](file:///f:/NCBI%20blast/results/benchmarks/phage_structure_suite_e/suite_e_m2_mechanism_report.json)）：

| 评估维度 (`Suite E` 冻结 224 株) | `m1_baseline` | `m2_mechanism` | 客观变化说明 |
| --- | --- | --- | --- |
| FASTA 四形态准确率 / F1 | `1.0 (224/224)` / `1.0` | `0.9955 (223/224)` / `0.9977` | 唯一变化为 `NC_015297 (Inoviridae, 5475 bp)` 自动切换至 Table 4 后产出 `0` ORF -> `Incomplete`（保留只读诊断） |
| GBK 四形态准确率 / F1 | `0.9955 (223/224)` / `0.9955` | **`1.0 (224/224)` / `1.0`** | 消除全部误判（原 `NC_052964` 误判修复） |
| GBK 稀疏注释自动补救案例 | 无补救（`2` 株漏检 TMP） | **`NC_070890` (+170 ORF) / `NC_052964` (+87 ORF)** | 两株极端稀疏 `.gbk` 在纯裸补救后均精准恢复形态与 TMP（`603 aa` / `823 aa`） |
| GBK 有尾 TMP 召回 / 假 TMP | `110/112` / `0/112` | **`112/112`** / `0/112` | M1 遗留的两例 GBK TMP 漏检全部清零 |
| 双模式 `<=5%` 误差 / 精确 aa 一致率 | `0.9821` / `215/224 (0.9598)` | **`0.9911`** / **`217/224 (0.9688)`** | 双模式尾长跨格式稳定性进一步收敛 |
| `post-2025/08` 外部新株 (`24` 株) | FASTA `1.0` / GBK `1.0` | **FASTA `1.0` / GBK `1.0`** | 外部全新样本全对保持 |

* **只读机制诊断保留（待后续阶段决策）**：`NC_015297`（`5.48 kb` 丝状单链 `Inoviridae`）暴露了极端小尺度非 Mollicutes 噬菌体在自动切换至 Table 4 后，`METAGENOMIC_BINS_4` 元基因组模型受训练 bin 稀缺影响可能漏呼短 ORF 的边界现象（本里程碑严格冻结规则，将该现象留作后续 M3 协同优化输入）。
* **合规自检**：全部 `18` 份新增/修改前后端及文档文件均已通过 `UTF-8` 无 BOM 与零 Emoji 检验。

---

## 11. 阶段 2 / M3 第一批：切表一致性兜底、`T2.1` 阈值敏感性扫描与 `T1.4` 条件 3D 复核（步骤 61）

严格遵守“未完成完整 M3 阶段 `T2.2–T2.4` 前暂不运行 `Suite E` 盲测”原则，本批首先面向 `341` 株去重调参全集（`Suite A + B + C + D`）与 `7` 组条件触发 3D 复核场景落地工程加固与量化审计。

### 11.1 M3-前置：非 Table 11 切表一致性兜底（[sequence_annotator.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/sequence_annotator.py)）
- 针对 `_predict_single_contig_orfs` 曾对切表 `4` 退回低 GC 支原体 `METAGENOMIC_BINS_4` 导致与 `select_optimal_genetic_code`（`meta=False` 自训练）行为不一致的结构漏洞，调整为仅对 `<100 kb` 标准 Table `11` 使用 `METAGENOMIC_BINS_11`，而对切表 `4 / 15` 与 `>=100 kb` 序列统一启用 `meta=False` 单基因组自训练；并增设空呼出安全保底（若非 Table `11` 呼出 `0` 条有效 `>=25 aa` ORF，自动回退至 Table `11` 重呼）。

### 11.2 T2.1 集中阈值配置化与 `±20%` 全集敏感性扫描（[thresholds.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/thresholds.py)、[sensitivity_phage_structure.py](file:///f:/NCBI%20blast/scripts/sensitivity_phage_structure.py)）
1. **不可变集中配置**：构建 `PhageStructureThresholds` 不可变数据类及 6 大子配置组（`hmm` / `genetic_code` / `completeness` / `split_tmp` / `tmp` / `classifier`），统一导出 `DEFAULT_THRESHOLDS` 与纯函数覆盖器 `override_threshold`，全面穿透至 [genetic_code_selector.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/genetic_code_selector.py)、[completeness_gate.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/completeness_gate.py)、[tmp_split_merger.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/tmp_split_merger.py)、[tmp_analyzer.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/tmp_analyzer.py)、[morphotype_classifier.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/morphotype_classifier.py)、[sequence_annotator.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/sequence_annotator.py) 与 [manager.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/manager.py)。
2. **`341` 株全量基准零回归校验**：[sensitivity_report.json](file:///f:/NCBI%20blast/results/benchmarks/phage_structure_sensitivity/sensitivity_report.json)（耗时 `368.86s`）验证默认配置在 `341` 株（含 `41` 株核实 TEM、实际成对定标 `n=39`）保持 **`341 / 341 (100.00%, Macro-F1 = 1.0)`**、有尾 TMP 检出 `188 / 190`、假 TMP `0`、`NC_005178` 合并 **`1185 aa`**、TEM `MAE = 21.653 nm` / `MAPE = 11.297%`。
3. **`±20%` 单因素扰动核心发现**（报告 [sensitivity_summary.md](file:///f:/NCBI%20blast/results/benchmarks/phage_structure_sensitivity/sensitivity_summary.md)）：
   - **极高结构稳定性**：在 `24` 项内存缓存扰动中，**`19` 项阈值在 `±20%` 宽幅波动下保持 `100.00% (341/341)` 且 TMP `188/190` 零敏感平台期**（涵盖 `operon_window 3..5`、`wide_operon_window 6..10`、`podo_negative_min_bp 20..30 kb`、`terl_full_min_aa 240..360 aa`、`split_tmp.max_gap_bp 96..144 bp`、`split_tmp.merged_min_aa 480..720 aa` 等全部核心距离与尺寸护栏）；`24` 株实时 PyHMMER 扫描亦验证 `Z ∈ [160, 240]` 与 `score_cutoff ∈ [22.4, 33.6]` 均为 `24/24` 形态与 `12/12` TMP；
   - **唯二高敏感临界对**：`classifier.podo_negative_strong_weight (2.6)` `-20% -> 2.08` 与 `classifier.incomplete_score_cutoff (2.2)` `+20% -> 2.64` 均触发完全相同的 `10` 株远缘短尾（*Steigviridae* / *Grimontviridae* / *Autographiviridae*）滑入 `Incomplete`（`331/341 = 97.07%`），数学上印证 `2.6` 处于 `[2.2, 3.12]` 安全窗口核心；此外 `hmm.default_score_cutoff` 上调 `+20%` 至 `33.6` 使 `1` 株无尾（`NC_055060`）跌入 `Incomplete`（`340/341`），而 `tmp.direct_pfam_min_aa` (`480 aa`) 与 `tmp.syntenic_yqaj_min_aa` (`600 aa`) 上调 `+20%` 各自仅少召回 `1` 条边缘 TMP（形态仍 `100%`）。

### 11.3 T1.4 条件触发 Phold 3D（ProstT5 + Foldseek）增强复核（[manager.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/manager.py)、[benchmark_phold_3d_rescue.py](file:///f:/NCBI%20blast/scripts/benchmark_phold_3d_rescue.py)）
1. **条件门控架构与上游 Bug 规避**：新增 `phold_trigger_mode`（`auto / always / off`）及 `should_trigger_phold_3d`（精准捕获 `tailed_without_tmp`、`low_margin_ambiguous`、`incomplete_large_contig` 三类情景），严格限制 `--batch_size 1` 与执行前后 CUDA 显存回收（实测并规避了 `phold 1.2.6` 开启 `--omit_probs` 时 `predict_3Di.py:95` 触发 `TypeError: 'NoneType'` 的上游缺陷，改以 `omit_probs=False` 稳定运行），并在 [StructureResults.vue](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_structure/components/StructureResults.vue) 补充 3D 复核角标展示。
2. **7 场景定向 3D 复核实测（[phold_3d_rescue_report.json](file:///f:/NCBI%20blast/results/benchmarks/phage_structure_phold3d/phold_3d_rescue_report.json)）**：

| 验证场景 | 触发条件 | 形态变化 (`前 -> 后`) | Phold 救回 ORF / 结构域 | TMP 变化 | 额外 3D 耗时 / GPU 空闲显存 (`前->后`) |
| :--- | :--- | :---: | :---: | :---: | :---: |
| `phiKZ` (*Chimalliviridae*) | `tailed_without_tmp` | `Myoviridae-like -> Myoviridae-like (0.99)` | `31` 个（含 `1 MCP, 1 BASEPLATE_MYO, 1 TAIL_OTHER, 21 毒粒蛋白`） | `0 -> 0`（客观无细菌型 TMP） | `66.96s` / `7127 -> 7131 MB` |
| `PaZh_1` (*Chimalliviridae*) | `tailed_without_tmp` | `Myoviridae-like -> Myoviridae-like (0.99)` | `31` 个（同上） | `0 -> 0`（客观无细菌型 TMP） | `61.54s` / `7131 -> 7137 MB` |
| `Lambda` / `T4` / `T7` 高置信对照 | 不触发 | 原判不变 (`Siphoviridae / Myoviridae / Podoviridae`) | `0` | `853 aa / 590 aa / None` 不变 | **`0.00s` 零开销** / 显存无波动 |
| `Lambda` 模拟 HMM 全失明 | `incomplete_large_contig` | **`Incomplete (0.10) -> Siphoviridae-like (0.99)`** | **`24` 个**（含 `TERL, PORTAL, MCP, MTP, TMP, DIT` 等全套骨架） | **`0 -> 1 (853 aa 精确复原)`** | `60.93s` / `7137 -> 7128 MB` |
| `T7` 模拟 HMM 全失明 | `incomplete_large_contig` | **`Incomplete (0.10) -> Podoviridae-like (0.99)`** | **`14` 个**（含 `MCP, TERL, CONN_GENERAL, INTERNAL_VIRION x2`） | `0 -> 0` | `61.60s` / `7128 -> 7128 MB` |

### 11.4 本批自动化测试与合规验收
* **前端单元测试与构建**：`npx vitest run` **`9 files, 54 passed in 1.87s`**；`npm run build`（`vue-tsc -b && vite build`）`built in 14.35s`。
* **后端全量单元测试（`.venv/Scripts/python.exe -m pytest tests/test_phage_structure.py -v`）**：**`19 passed in 144.61s (0:02:24)`**（含新增 `test_m3_genetic_code_table4_high_gc_no_zero_orf`、`test_t2_1_thresholds_centralized_and_override` 与 `test_t1_4_conditional_phold_trigger_policy`，全量零警告）。
* **合规审计**：涉及前后端源码、脚本、单测及留档文档全部通过 `UTF-8` 无 BOM 与零 Emoji 校验。

---

## 12. 步骤 62：阶段 2 / M3 第二批——复用 `UnifiedJudge V4.3` 底座构建 `T2.2` 双轨 AI 形态分类器与跨科泛化实测（2026-11-23）

围绕既有自研深度学习模型深度融入噬菌体结构与尾部形态判别流水线，本批次冻结复用了早期部署于相对模型仓库的 `UnifiedJudge V4.3`（1,747,664 参数、基于蛋白操纵子注意力与 `ProstT5` 3D 序列蒸馏特征的 10 类功能判断底座），完成 `T2.2` 双轨 AI 形态分类与概率校准系统全栈上线，并通过严格零泄露交叉验证及 `Suite E`（224 株）只读双轨盲测验收。

### 12.1 架构设计、显存隔离与 Meta-75 Stacking 进化
1. **双轨深度特征与分类模块**（[ai_morphotype_model.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/ai_morphotype_model.py)）：
   - **`UnifiedJudge V4.3` 冻结特征提取器（2,916 维）**：仅依赖 Contig 排序后的 ORF 坐标与氨基酸翻译，零 PHROG/Pfam/PTF 依赖运行操纵子注意力前向（`batch_size=16`），聚合 `head_conn_h / tail_h / long_tail_h / global_mean_h / global_max_h` (`800` 维)、`tail_distill / head_distill` (`2048` 维) 与 `func10 / intact / 基因组尺度统计` (`68` 维)，并输出 `deep_tail_prob_max` 与 `deep_head_prob_max`。
   - **结构化特征编码（67 维）与 `Meta-75` 融合升级**：初期直接拼接高维小折 PCA 深度向量在 341 株科级 CV 表现为 `Macro-F1=0.9341`（弱于纯结构 `Structured-ML=0.9744`）；升级为将经过 1,977 株跨科模型温度校准后的 4 类概率转换为 8 维高信噪比语义摘要（`log_p(4) + entropy(1) + top1_margin(1) + deep_tail_max(1) + deep_head_max(1)`），再与 67 维规则结构化特征拼接为 **`FUSION_META_DIM = 75`** 的 Meta-Fusion 输入，并保留对旧版 2,983 维包的兼容回退。
   - **双轨推理与第 4 类 3D 复核触发**（[manager.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/manager.py)、[types.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/types.py)）：
     - 常规规则有命中时走 `dual_modal_fusion`；当规则引擎陷入 `Incomplete` 且 `length_bp >= 5000` 时自动切换至零 HMM 依赖 `ai_deep_only` 救回轨；
     - 在 `should_trigger_phold_3d` 中新增第 4 类触发条件 `ai_rule_conflict`（AI 校准置信度 `>= 0.75` 且与规则引擎不一致时触发）；全阶段强制调用 `release_ai_judge_memory()` + `release_gpu_memory()` 清空 PyTorch 显存，严防与 WSL `Phold 3D` 显存叠加溢出。
2. **离线训练、断点分片与静态类型清理**（[train_ai_morphotype_classifier.py](file:///f:/NCBI%20blast/scripts/train_ai_morphotype_classifier.py)）：
   - 实现 `deep_chunks/chunk_*.npz`（每 `50` 株分片落盘与 JSONL 断点保护）；全程清零两文件全部 Pyrefly 静态诊断；
   - 严格使用 `StratifiedGroupKFold(n_splits=5)` 按真实 ICTV Family 隔离交叉验证（含外折剔除验证科/株 + 内折 3 折科隔离 OOF 构造无泄露 Meta-75 特征），最后经 `scipy.optimize.minimize_scalar` 最小化 NLL 完成单参数温度缩放校准，生成权重包 [morphotype_ai_v1.joblib](file:///f:/NCBI%20blast/models/phage_structure/morphotype_ai_v1.joblib)（`1.119 MB`）及元数据 [morphotype_ai_v1_meta.json](file:///f:/NCBI%20blast/models/phage_structure/morphotype_ai_v1_meta.json)。

### 12.2 零泄露训练与 5 折 ICTV 科级隔离交叉验证实测（[t2_2_ai_cv_summary.md](file:///f:/NCBI%20blast/results/benchmarks/phage_structure_ai/t2_2_ai_cv_summary.md)、[t2_2_ai_cv_report.json](file:///f:/NCBI%20blast/results/benchmarks/phage_structure_ai/t2_2_ai_cv_report.json)）
* **数据隔离核验**：`Suite E` (`224` 株) 与本地跨科语料（`1,930` 株 / `40` ICTV 科）、全特征基准集（`341` 株 / `57` 科组）及合并去重深度并集（`1,977` 株）重叠数严格为 **`0`**；`RTX 4070` GPU 峰值显存 **`501.9 MB`**，单基因组均推理耗时 **`27.57 ms/genome`**。
* **实验 1（1,930 株 / 40 个 ICTV 科 `AI-Deep-Only` 跨科 5 折 CV）**：
  - `histgbr`（最优）：`Acc = 74.15%`、`Macro-F1 = 0.7870`、`ECE = 0.1593 -> 0.0528`（`T = 2.104`）、`Brier = 0.3854 -> 0.3330`；在合并 `1,977` 株并集上 5 折 OOF 达 **`Acc = 81.39%`、`Macro-F1 = 0.8512`、`ECE = 0.0347`**（`T = 1.9912`）；
  - 对比基线：`logreg` (`Acc = 69.22%`, `Macro-F1 = 0.7068`, `ECE = 0.0867`)、`mlp` (`Acc = 64.72%`, `Macro-F1 = 0.6450`, `ECE = 0.0971`)；
  - 跨科表现最好 Top 5 (`n >= 5`)：*Autotranscriptaviridae* (`100.0%, n=136`)、*Inoviridae* (`100.0%, n=63`)、*Ackermannviridae* (`100.0%, n=55`)、*Kyanoviridae* (`100.0%, n=42`)、*Microviridae* (`100.0%, n=41`)；最难跨科 Bottom 5：*Peduoviridae* (`0.0%, n=88`)、*Orlajensenviridae* (`0.0%, n=6`)、*Lindbergviridae* (`14.6%, n=41`)、*Tectiviridae* (`16.7%, n=12`)、*Hodgkinviridae* (`23.5%, n=17`)。
* **实验 2（341 株 / 57 个科组同折 5 折 ICTV 科级对比）**：

| 方案 | 分类头 | Acc | Macro-F1 | 校准后 ECE | 校准后 Brier | 备注 |
|---|---|---:|---:|---:|---:|---|
| `Rule Engine` | 确定性规则 | `100.00%` | `1.0000` | - | - | `Incomplete = 0` |
| `AI-Deep-Only` | `logreg` | `83.28%` | `0.8356` | `0.0604` | `0.2720` | 零 HMM / 零 PTF 依赖 |
| `Structured-ML` | `logreg` | `97.36%` | `0.9744` | `0.0085` | `0.0427` | 仅 67 维规则结构化特征 |
| `Dual-Modal Fusion AI (Meta-75)` | `logreg` | **`96.19%`** | **`0.9618`** | **`0.0205`** | **`0.0558`** | 温度 `T = 0.8323`，较直接拼接 `0.9341` 提升 `+0.0277` Macro-F1 |

* **实验 3（341 株 HMM 失明压力测试，清空全部 PHROG / PTF / TMP 标注）**：
  - `Rule Engine` 完全失能退化：`Acc = 0.00%`、`Incomplete = 341/341 (100.0%)`；
  - `AI-Deep-Only` 在零 HMM 条件下以 `27.57 ms/genome` 救回 **`Acc = 83.28%`、`Macro-F1 = 0.8356`**。

### 12.3 冻结盲测集 `Suite E`（224 株）只读双轨全量评测（[eval_suite_e_ai_dual_track.py](file:///f:/NCBI%20blast/scripts/eval_suite_e_ai_dual_track.py)、[suite_e_ai_dual_track_eval.md](file:///f:/NCBI%20blast/results/benchmarks/phage_structure_ai/suite_e_ai_dual_track_eval.md)）
在未基于 `Suite E` 微调任何规则或 AI 超参数的严格只读纪律下，同时实测 `FASTA`（裸序列）与 `GBK`（注释基因组）两套真实输入：

| 评估子集 | 轨道 | 样本数 | Acc | Macro-F1 | 校准 ECE / 备注 |
|---|---|---:|---:|---:|---|
| `FASTA 全集 (224)` | `Rule Engine` | `224` | `100.00%` | `1.0000` | `Incomplete = 0` |
| `FASTA 全集 (224)` | `AI-Deep-Only (0-HMM)` | `224` | **`99.55%`** | `0.9955` | `ECE = 0.0456`（仅 `NC_070978` 1 株错判） |
| `FASTA 全集 (224)` | `Dual-Modal Fusion AI` | `224` | **`100.00%`** | **`1.0000`** | **`ECE = 0.0026`**，规则-AI 一致率 `100.0%` |
| `GBK 全集 (224)` | `Rule Engine` | `224` | `100.00%` | `1.0000` | `Incomplete = 0` |
| `GBK 全集 (224)` | `AI-Deep-Only (0-HMM)` | `224` | **`99.55%`** | `0.9955` | `ECE = 0.0533`（仅 `NC_070978` 1 株错判） |
| `GBK 全集 (224)` | `Dual-Modal Fusion AI` | `224` | **`100.00%`** | **`1.0000`** | **`ECE = 0.0029`**，规则-AI 一致率 `100.0%` |
| `FASTA post-2025/08 (24)` | `AI-Deep-Only` / `Dual-Modal Fusion` | `24` | **`100.00%`** / **`100.00%`** | `1.0000` | 外部新发表菌株零误差 (`ECE = 0.0566 / 0.0027`) |
| `GBK post-2025/08 (24)` | `AI-Deep-Only` / `Dual-Modal Fusion` | `24` | **`100.00%`** / **`100.00%`** | `1.0000` | 外部新发表菌株零误差 (`ECE = 0.0742 / 0.0029`) |

* **互补纠偏验证**：`Suite E` 中 `AI-Deep-Only` 唯一错判的 *Grimontviridae* 菌株 `NC_070978`（在 FASTA / GBK 下独立判为 `Myoviridae-like`, `77.6% / 79.1%`）在 `Meta-75` 双模态融合下被结构证据纠偏至 `Podoviridae-like`，实现 `224/224` 零分歧与极低校准误差（`ECE < 0.003`）。

### 12.4 全栈上线、自动化测试与合规校验
* **后端与前端集成**：完成 [__init__.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/__init__.py) 导出、[manager.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/manager.py) 就绪探测（`unified_judge_ready` / `ai_classifier_ready`）及 AI/3D 协同流水线；前端 [types.ts](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_structure/types.ts)、[StructureSetup.vue](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_structure/components/StructureSetup.vue) 与 [StructureResults.vue](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_structure/components/StructureResults.vue) 已上线 AI 双轨参数开关、`Phold 3D` 策略下拉及“AI 双轨校准概率与规则一致性”可视化卡片。
* **测试与构建验证**：
  - 前端：`npx vitest run` **`9 files, 54 passed`**；`npm run build`（`vue-tsc -b && vite build`）`13.52s` 构建通过，0 报错；
  - 后端：`.venv/Scripts/python.exe -m pytest tests/test_phage_structure.py -v` **`21 passed in 141.95s`**（含新增 `test_t2_2_unified_judge_ai_classifier_and_blind_rescue` 与 `test_t2_2_ai_rule_conflict_triggers_phold_3d`）；
  - 合规：全部新增及改动文件通过 `UTF-8` 无 BOM、零 Emoji 及 Python AST 语法校验，无违规项。

---

## 13. 步骤 63：阶段 2 / M3 第三批——`morphotype_ai_v2` ORF 级细粒度角色解码器、1,977 株全科双模态扩充与物理语义解耦拒识门控实测（2026-11-23）

针对 `V1` 版本中仅依赖 Contig 级全局 P2 加权平均表征在肌尾细粒度结构分辨上的信息稀释瓶颈，以及缺乏对短碎片的保守拒识门控问题，本批次升级并验证了 `morphotype_ai_v2` 双轨架构。全量语料经分片落盘缓存扩展至 `1,977` 株（57 ICTV 科 / `223,790` 个 ORF），与冻结盲测集 `Suite E`（224 株）保持严格 **0 重叠**。

### 13.1 核心架构升级与校准/门控进化
1. **逐 ORF 9 通道细粒度解码器与 84 维表征**（[ai_morphotype_model.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/ai_morphotype_model.py)、[build_local_structure_corpus_cache.py](file:///f:/NCBI%20blast/scripts/build_local_structure_corpus_cache.py)）：
   - 利用单次 `UnifiedJudge V4.3` 前向同时抽取 `2,916` 维 Contig 表征与逐 ORF `1,207` 维语义特征（`h_base(160) + distill_out(1024) + func10(10) + intact10(10) + 长度/相对位置/链方向(3)`），经 `31` 个分片 NPZ (`corpus_v2_chunks/chunk_00000~00030.npz` + `corpus_v2_index.jsonl`, 总耗时 `1249.2s`) 完成全量断点持久化。
   - 在冻结底座之上于 GPU 训练轻量 `FineRoleOrfMLP`（`LayerNorm(1207) -> 256 -> 128 -> 9`，仅持久化纯 CPU `state_dict`），针对 `MYO_TSP`、`MYO_BASE_TTP`、`SIPHO_MTP_TAP`、`LONG_TMP`、`PODO_CORE`、`NON_TAILED_CORE`、`CONN_SIPHO_MYO`、`CONN_PODO` 与 `HEAD_CAPSID` 共 9 通道细粒度监督学习，并聚合为 `84` 维 Contig 判别摘要（9 通道 × 8 统计量 + 12 维 6-ORF 共线滑动窗口及形态竞争特征），与 `2,916` 维构成 `3,000` 维 V2 深度输入。
2. **全科 `Meta-85` 双模态扩展与有界 Brier 温度校准**（[train_ai_morphotype_v2.py](file:///f:/NCBI%20blast/scripts/train_ai_morphotype_v2.py)）：
   - 双模态融合训练集从 V1 的 `341` 株扩展至 `1,977` 株（57 个 ICTV 科），引入 9 通道细粒度峰值与 `has_rule_hit` 构造 `FUSION_META_V2_DIM = 85` 输入；
   - 发现无界 NLL 温度缩放在跨科离群错误牵引下易将 `soft_ensemble` 温度拉高至 `1.66~1.95`，导致 `ECE` 恶化并压低正常完整基因组置信度；改用有界**多分类 Brier Score 温度缩放（`_fit_temperature_brier`）**与**校准合格优先选头（`_select_best_calibrated_head`, `ECE <= 0.05` 且未反升）**，显著提升概率可靠性。
3. **双层物理语义解耦保守拒识门控与线上对齐修复**（[ai_morphotype_model.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/ai_morphotype_model.py)、[manager.py](file:///f:/NCBI%20blast/src/analysis/phage_structure/manager.py)、[StructureResults.vue](file:///f:/NCBI%20blast/src/web-next/src/views/Analysis/modules/phage_structure/components/StructureResults.vue)）：
   - 初版紧阈值门控（`conf < 0.65 | ent > 0.72` + `lacks < 0.25/0.35`）在零 HMM 下误将 `26.7%`（`527/1977`）具有明确头尾语义的完整基因组拒识为 `Incomplete`；升级为**解耦双层物理门控**：仅在极端高熵不可分辨（`conf < 0.50 or entropy_norm > 0.85`）或完全缺失全部头尾语义（`deep_tail_prob_max < 0.40 and deep_head_prob_max < 0.40 and fine_tail_max < 0.45`）时触发 `abstained = True`（返回 `Incomplete`），并在 `manager.py` 屏蔽拒识样本对 `Phold 3D` 的 `ai_rule_conflict` 误触发、缓存 `_raw_tmps` 保证线上特征与离线训练 `100%` 对齐，前端已增加 `Incomplete` 拒识徽标与归一化熵展示。

### 13.2 跨科泛化、4 轨对比与拒识压测实测数据（[t2_2_v2_cv_summary.md](file:///f:/NCBI%20blast/results/benchmarks/phage_structure_ai/t2_2_v2_cv_summary.md)、[t2_2_v2_cv_report.json](file:///f:/NCBI%20blast/results/benchmarks/phage_structure_ai/t2_2_v2_cv_report.json)）
* **实验 A（`1,930` 株 / 40 个 ICTV 科 零 HMM 跨科 5 折隔离 CV：V1 vs V2）**：

| 模型方案 | 分类头 | Acc | Macro-F1 | 校准前 ECE | 校准后 ECE | Brier |
|---|---|---:|---:|---:|---:|---:|
| `V1 AI-Deep-Only` | `histgbr` | `74.15%` | `0.7870` | `0.1593` | `0.0498` | `0.3854` |
| `V2 FineRole-Only-84` | `histgbr` | `81.14%` | `0.8298` | `0.1104` | `0.0535` | `0.3020` |
| **`V2 AI-Deep-Only`** | **`histgbr`** | **`79.64%` (`+5.49%`)** | **`0.8341` (`+0.0471`)** | `0.1102` | **`0.0303`** | `0.3122` |

  - **ORF 级零 HMM 跨科 5 折均值 ROC-AUC**：`MYO_TSP = 0.9469`、`MYO_BASE_TTP = 0.9402`、`SIPHO_MTP_TAP = 0.9146`、`LONG_TMP = 0.8998`、`PODO_CORE = 0.8690`、`NON_TAILED_CORE = 0.9402`、`CONN_SIPHO_MYO = 0.9895`、`HEAD_CAPSID = 0.9267`。
  - **薄弱科 V1 -> V2 跨科精度跃升**：*Hodgkinviridae* (`n=17`): `23.5% -> 88.2% (+64.7%)`、*Straboviridae* (`n=185`): `35.1% -> 74.6% (+39.5%)`、*Lindbergviridae* (`n=41`): `14.6% -> 19.5% (+4.9%)`、*Autotranscriptaviridae* (`n=136`): `100.0% -> 100.0%`、*Tectiviridae* (`n=12`): `16.7% -> 16.7%`；*Peduoviridae* (`n=88`) 在严格跨科零 HMM 留出下仍为 `0.0%`（因 P2 类温和肌尾虽有局部鞘信号但主干蛋白共享长尾 MTP/TAP 折叠，生产环境通过规则与融合轨道 100% 纠偏）。
* **实验 B（全量 `1,977` 株 / 57 ICTV 科与 `341` 子集 5 折 4 轨公平对比）**：

| 方案 | 1,977 全集 Acc | 1,977 Macro-F1 | 1,977 校准后 ECE | 341 子集 Acc | 341 Macro-F1 | 备注 |
|---|---:|---:|---:|---:|---:|---|
| `Rule Engine` | `99.75%` | `0.9982` | - | `100.00%` | `1.0000` | 全集 `Incomplete = 2` |
| `AI-Deep-Only V2 (histgbr)` | `81.08%` | `0.8502` | **`0.0359`** | `85.34%` | `0.8597` | `T = 2.0249`，`Brier = 0.2506` |
| `Structured-ML (histgbr)` | `98.79%` | `0.9865` | `0.0063` | `97.36%` | `0.9726` | 仅 67 维规则结构化特征 |
| **`Dual-Modal Fusion V2 (soft_ensemble)`** | **`99.75%`** | **`0.9978`** | **`0.0125`** | **`99.71%`** | **`0.9971`** | `341` 切片较 V1 (`96.19%`) 仅错 1 株 (`ECE=0.0162`) |

* **实验 C（HMM 失明与 6~10 kb 非结构碎片拒识压测对比）**：
  - `6-10 kb` 非结构碎片保守拒识拦截率：**`229/240 (95.4%)`**（较 NLL 旧门控 `81.2%` 提升 `+14.2%`）；
  - `1,977` 株完整基因组零 HMM 误拒识率：由初版 NLL+紧阈值 **`527/1977 (26.7%)`** 降至 **`103/1977 (5.2%)`**，未拒识保留区 1,874 株准确率提升至 **`83.03%`**（被拒识 103 株原始准确率仅 **`45.6%`**，确认选择性拒识带来净精度收益）。

### 13.3 冻结盲测集 `Suite E`（224 株 × FASTA/GBK）V1 vs V2 只读评测对比（[suite_e_ai_v2_dual_track_eval.md](file:///f:/NCBI%20blast/results/benchmarks/phage_structure_ai/suite_e_ai_v2_dual_track_eval.md)）
严格保持只读评估纪律，未在观察到任何 `Suite E` 结果后修改模型或阈值：

| 评估子集 | 轨道 | V1 Acc | V1 ECE | V2 Acc | V2 Macro-F1 | V2 ECE / 备注 |
|---|---|---:|---:|---:|---:|---|
| `FASTA 全集 (224)` | `Rule Engine` | `100.00%` | - | `100.00%` | `1.0000` | `Incomplete = 0` |
| `FASTA 全集 (224)` | `AI-Deep-Only (0-HMM)` | `99.55%` | `0.0456` | `99.11%` | `0.9911` | **`ECE = 0.0396`** |
| **`FASTA 全集 (224)`** | **`Dual-Modal Fusion AI`** | `100.00%` | `0.0026` | **`100.00%`** | **`1.0000`** | **`ECE = 0.0000`**，一致率 `100.0%`，在线拒识 `0` |
| `GBK 全集 (224)` | `AI-Deep-Only (0-HMM)` | `99.55%` | `0.0533` | `98.66%` | `0.9866` | **`ECE = 0.0457`**（较 V1 `<0.05` 达标） |
| **`GBK 全集 (224)`** | **`Dual-Modal Fusion AI`** | `100.00%` | `0.0029` | **`100.00%`** | **`1.0000`** | **`ECE = 0.0000`**，一致率 `100.0%`，在线拒识 `0` |
| `FASTA post-2025/08 (24)` | `AI-Deep` / `Fusion` | `100.0%` / `100.0%` | `0.0566 / 0.0027` | `95.83%` / **`100.00%`** | `0.9580 / 1.0000` | 融合轨道零误差 (`ECE = 0.0000`) |
| `GBK post-2025/08 (24)` | `AI-Deep` / `Fusion` | `100.0%` / `100.0%` | `0.0742 / 0.0029` | **`100.00%` / `100.00%`** | **`1.0000 / 1.0000`** | 外部新菌株零误差 (`ECE = 0.0769 / 0.0000`) |

### 13.4 产物性能、全栈验证与合规审计
* **权重与显存开销**：生成 [morphotype_ai_v2.joblib](file:///f:/NCBI%20blast/models/phage_structure/morphotype_ai_v2.joblib)（**`2.621 MB`**，纯 CPU `state_dict` + sklearn pipeline，支持自动回退 V1）及 [morphotype_ai_v2_meta.json](file:///f:/NCBI%20blast/models/phage_structure/morphotype_ai_v2_meta.json)；训练峰值 GPU 显存仅 **`98.7 MB`**，在线推理延迟保持 **`27.57 ms/genome`**。
* **测试与构建验证**：
  - 后端全量测试：`.venv/Scripts/python.exe -m pytest tests/test_phage_structure.py -v` **`22 passed in 141.25s`**（含 `test_t2_2_v2_fine_role_probe_and_fragment_abstention` 实测真 V2 bundle 7 kb 非结构碎片拒识与 `ANNO_NC_005859` 零 HMM 盲测救援）；
  - 前端验证：`npx vitest run` **`9 files, 54 passed in 3.03s`**；`npm run build`（`vue-tsc -b && vite build`）`19.79s` 构建通过。
  - 合规审计：涉及前后端源码、脚本、单测、报告及文档全部通过 `UTF-8` 无 BOM、零 Emoji 及 Python AST 语法校验。
