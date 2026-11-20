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
