# 泛基因组与功能注释分组词条深度审查及修正留档报告

- **审查时间**: 2026-11-10
- **审查范围**:
  - 后端注释融合与泛基因组引擎: `src/analysis/annotation/fuser.py`, `src/analysis/pan_genomics/engine.py`, `src/analysis/pan_genomics/clusterer.py`
  - 前端分组词条渲染与分类映射: `src/web-next/src/views/Analysis/modules/viewer/utils/render.ts`, `src/web-next/src/views/Analysis/modules/pan_genomics/utils/pangenomeVariants.ts`, `PanGenomicsChordDiagram.vue`, `WorkspaceCocktailDeRedundancy.vue`, `exportLandscapeFigure.ts`
  - 全库持久化数据验证: 31 个基因组注释任务（共 **4,110** 条 CDS 记录、**578** 种唯一 `product` 词条）及全部泛基因组分析任务（含当前工作台任务 `pan_20261110_145515_0f160b` 的 **222** 个同源基因家族 `OG_0001` ~ `OG_0222`）。

---

## 一、 深度审查发现的五大核心问题

### 1. 界面分组词条（中文命名）前后不一致与错别字
1. **同一界面上下两处分类名称不一致（截图中直接可见）**:
   - 顶部 `CDS 功能分类` 图例栏读取 `render.ts` 中的 `FUNCTIONAL_CATEGORIES["Tail & Host Interaction"]`，显示为 **`尾部与尾丝吸附`**；
   - 底部悬停状态栏与基因家族详情面板读取 `pangenomeVariants.ts` 中的 `CATEGORY_CHINESE_MAP["Tail & Host Interaction"]`，显示为 **`尾部与宿主吸附`**（如截图中 `OG_0166` 与 `OG_0165` 左侧蓝青色胶囊标签）；
   - 拓扑弦图 (`PanGenomicsChordDiagram.vue`) 中则写为 **`尾部与宿主吸附系统`**。
2. **“假定蛋白与未表征肽”用词失准及渲染模糊**:
   - `render.ts` 原定义为 `"假定蛋白与未表征肽 (Hypothetical)"`，“肽 (peptide)”仅指短链多肽，不适用于全长编码基因 (CDS)，且在小字号下“肽”字笔画密集形似“区”字。已统一规范为 **`假定蛋白与未表征 (Hypothetical)`**。
3. **病毒学标准术语与错别字（“溶源” vs “溶原”，“原件” vs “元件”）**:
   - `render.ts` 与 `pangenomeVariants.ts` 使用了非规范写法 `"溶源整合与切除"`，而 `WorkspacePopulationLandscape.vue` 使用 `"温和溶原"`；同时 `WorkspaceCocktailDeRedundancy.vue` 第 159 行存在错别字 `"[警示] 检出关键溶源整合原件"`。已全部统一修正为标准病毒学术语 **`溶原整合与切除`** 与 **`[警示] 检出关键溶原整合元件`**。
4. **高清大图导出 (PNG) 图例截断**:
   - `exportLandscapeFigure.ts` 第 439 行存在硬编码 `.slice(0, 7)`，导致导出的高清 PNG 图例丢失了最后 3 个分组词条（`溶原整合与切除`、`其他功能蛋白`、`假定蛋白与未表征`）。已移除 `.slice(0, 7)` 限制。

---

### 2. `notes` 证据链全文回退匹配导致的严重跨类污染（根因剖析）
原 `AnnotationFuser.infer_category` 与前端 `inferCategoryFromText` 在 `product` 未命中窄正则时，直接对整段 `notes` 文本执行全文正则匹配，引发了两类系统性误判：
1. **污染源 A — Phold 结构注释 `"DNA, RNA and nucleotide metabolism"` 被 `\bmetabolism\b` 劫持至辅助代谢基因 (`Metabolism & AMG`)**:
   - 当噬菌体 DNA 复制/修复或通用蛋白的 `product` 未被原 `Replication & Repair` 窄正则覆盖时，回退扫描 `notes` 中的 `[Phold AI] Phold Structure: DNA, RNA and nucleotide metabolism`，被 `Metabolism & AMG` 规则中的 `\bmetabolism\b` 捕获。
   - 导致当前任务中经典的噬菌体复制起始蛋白 **`OG_0059` (`Bacteriophage replication protein O`)**、噬菌体线性 DNA 末端保护蛋白 **`OG_0144` (`Mu Gam-like end protection`)**，以及 **`OG_0075` (`ATP-binding protein`)**、**`OG_0214` (`AAA family ATPase`)** 全部被误判为 **`辅助代谢基因 (Metabolism & AMG)`**，甚至混入了 Q4 辅助代谢基因通路统计。
2. **污染源 B — Acranker 机器学习低置信度附加注释 (`Anti-CRISPR: Acranker`) 劫持已知功能蛋白至防御互作 (`Defense & Host Interaction`)**:
   - 安全审计在 `notes` 末尾追加 `; Anti-CRISPR: Acranker (Identity: 37.8%...)` 后，任何 `product` 漏配的基因都会被 `notes` 中的 `Anti-CRISPR` 吸入 `Defense & Host Interaction`。
   - 导致当前任务中的引发体复制蛋白 **`OG_0188` (`primosomal protein`)**、溶原切除方向性因子 **`OG_0056` (`site-specific recombination directionality factor RDF`)**、未知功能蛋白 **`OG_0121` (`AB1gp22`)** 及 **`OG_0211` (`F-box domain protein`)** 被误判为 **`宿主防御与互作`**（而与 `OG_0056` 产物完全相同的同源家族 **`OG_0088`** 却因无 Acranker 备注掉入 **`其他功能蛋白`**，造成同名基因不同分类的自相矛盾）。

---

### 3. 未知功能结构域（DUF / UPF / PHA / ORF）锚点过严导致逃逸 `Hypothetical`
- 原 `UNANNOTATED_PATTERNS` 仅匹配 `^duf\d+` 和 `^protein\s+of\s+unknown\s+function$`（要求严格行首行尾锚定），且前端 `inferClusterCategory` 在推断出 `Hypothetical` 时会跳过并回退读取旧缓存 `c.category`。
- 导致 **`OG_0107` (`Family of unknown function (DUF6651) domain-containing protein`)** 被误判为 `尾部与尾丝吸附`，而 **`OG_0011` (`DUF4258`)**、**`OG_0092` (`DUF4468`)**、**`OG_0141` (`Protein of unknown function (DUF551)`)**、**`OG_0204` (`DUF4760`)**、**`OG_0031` (`PHA01971 domain-containing protein`)** 全部混入 `其他功能蛋白 (Other Functional)`。

---

### 4. 正则词边界 (`\b`) 与复合词匹配缺陷
- `DefenseFinder protein`（**`OG_0067`**、**`OG_0098`**）因单词连写无法匹配 `\bdefense\b`，原本掉入 `Other Functional`；
- `glycerophosphoryl diester phosphodiesterase`（**`OG_0178`**）及全库中的 `aminotransferase`、`acetyltransferase`、`glycosyltransferase`、`amidohydrolase`、`lyase`、`hydroxylase` 等复合酶学词条因原正则缺少词干前缀通配符 `[a-z0-9'-]*` 或对应酶学词根而漏配；
- 原 `acr[a-z0-9_-]+` 过于宽泛，将化学底物名 `3-(aryl)acrylate reductase` 中的 `acrylate` 误判为 Anti-CRISPR (`acr`)；现已收紧为标准命名模式 `acr(?:\b|(?:i{1,3}|iv|v|vi|[ef])\d*[a-z0-9]*)`。

---

### 5. 后端泛基因组统计分类表过时与 AMG 筛选过宽
- `src/analysis/pan_genomics/engine.py` 的 `_calculate_category_distributions` 仍使用旧版 9 分类（含已废弃的 `Structural`、`Packaging`，缺失 `Head & Packaging`、`Tail & Host Interaction`、`Integration & Excision`）；
- `_analyze_amg_and_trna` 中使用了 `if cat == "Metabolism & AMG" or matched_pathway`，导致含有 `chaperone` 的 `Tail assembly chaperone` 和含有 `methyltransferase` 的 `DNA methyltransferase` 均被误计入 AMG 列表。现已修正为严格要求 `ftype == "CDS" and cat == "Metabolism & AMG"`。

---

## 二、 统一规范后的十大标准功能分组词条对照表

| 标准英文分类键 (`Category Key`) | 统一中文分组词条 (`CATEGORY_CHINESE_MAP`) | 界面图例完整标签 (`FUNCTIONAL_CATEGORIES.label`) | 配色 (`HEX`) | 涵盖的核心生物学功能词条范围 |
| :--- | :--- | :--- | :--- | :--- |
| `Head & Packaging` | **头部与衣壳包装** | `头部与衣壳包装 (Head & Packaging)` | `#0284c7` | 主/次衣壳蛋白 (capsid/head)、门户蛋白 (portal)、末端酶大小亚基 (terminase)、支架蛋白 (scaffolding)、头部闭合/装饰/形态发生蛋白 (Hc1/Hc2/Hoc/PmgB)、内部病毒颗粒蛋白 (internal virion) |
| `Tail & Host Interaction` | **尾部与尾丝吸附** | `尾部与尾丝吸附 (Tail & Host)` | `#06b6d4` | 尾管 (tail tube)、尾鞘 (tail sheath)、尾丝 (tail fiber)、尾刺 (tail spike)、卷尺蛋白 (tape measure)、基板组件与穿刺溶菌酶 (baseplate hub/wedge/lysozyme)、头尾连接子 (head-tail adaptor/connector)、受体结合蛋白与菌毛黏附素 |
| `Replication & Repair` | **DNA复制与重组修复** | `DNA复制与重组修复 (Replication)` | `#f59e0b` | DNA 聚合酶、复制起始蛋白 (replication initiation / protein O)、解旋酶及加载器 (DnaB/Dda/P-like/DnaC)、引发酶与引发体 (primase/primosomal)、连接酶 (DNA/RNA ligase)、单链结合与退火蛋白 (SSB/Sak4/Erf)、重组解离酶与核酸酶 (Holliday resolvase/HNH/VSR/RecE)、线性末端保护蛋白 (Mu Gam-like) |
| `Lysis` | **宿主裂解系统** | `宿主裂解系统 (Lysis System)` | `#f43f5e` | 内溶素 (endolysin)、穿孔素与抗穿孔素 (holin/anti-holin/CidA)、跨膜裂解蛋白 (Rz-like spanin)、N-乙酰胞壁酸酶/酰胺酶/肽聚糖水解酶 (N-acetylmuramidase/amidase/murein hydrolase)、裂解抑制蛋白 (RIIA/RIIB/spackle) |
| `Transcription & Regulation` | **转录调控与开关** | `转录调控与开关 (Regulation)` | `#10b981` | RNA 聚合酶及修饰酶、转录阻遏/激活/调控蛋白 (repressor/CII-like/Arc-like/LysR/MarR/GntR/HTH)、抗阻遏蛋白 (anti-repressor)、抗终止蛋白 (anti-termination Q-like)、Sigma 与抗 Sigma 因子、翻译抑制因子 (RaiA) |
| `Defense & Host Interaction` | **宿主防御与互作** | `宿主防御与互作 (Defense / Acr)` | `#8b5cf6` | 抗 CRISPR (Acr/Acranker)、DefenseFinder 抗防御蛋白、Anti-CBASS/Anti-DarT/Thoeris、抗限制修饰与 DNA 甲基转移酶 (DarB/Lar/MrcBC inhibitor/DNA methyltransferase/N-6 DNA methylase)、毒素-抗毒素系统 (HicA/HicB/RelE/toxin)、超感染排斥、流产感染 (Abi-like)、耐药与毒力因子 |
| `Metabolism & AMG` | **辅助代谢基因** | `辅助代谢基因 (Metabolism & AMG)` | `#eab308` | 核糖核苷酸还原酶 (RNR/NrdD)、dUTPase、dCMP 脱氨酶、胸苷酸合酶、胸苷激酶、PhoH-like、QueC-like、MazG、硫氧还蛋白/铁氧还蛋白、二氢叶酸还原酶、磷酸二酯酶及各类氧化还原酶/转移酶/水解酶/裂解酶/异构酶、tRNA 合成与修饰酶 |
| `Integration & Excision` | **溶原整合与切除** | `溶原整合与切除 (Integration)` | `#6366f1` | 整合酶 (integrase)、酪氨酸/丝氨酸位点特异性重组酶 (tyrosine/serine recombinase)、切除酶 (excisionase / Xis)、位点特异性重组方向性因子 (RDF)、转座酶 (transposase / IS4 family) |
| `Other Functional` | **其他功能蛋白** | `其他功能蛋白 (Other)` | `#64748b` | ABC 转运蛋白与跨膜通透酶 (transporter/permease/symporter)、分子伴侣 (DnaJ/FimB)、通用 AAA+ ATPase / ATP-binding / GTP-binding / RNA-binding 蛋白、膜蛋白与脂蛋白 (membrane/lipoprotein)、金属蛋白酶 (metallo-protease)、结构域已知但非前八类的蛋白 (如 F-box、LAP2) |
| `Hypothetical` | **假定蛋白与未表征** | `假定蛋白与未表征 (Hypothetical)` | `#94a3b8` | 假定蛋白 (`hypothetical protein`)、未知功能结构域蛋白 (`DUFxxxx` / `UPFxxxx` / `PHAxxxx` / `Domain or Family of unknown function`)、未表征编号基因 (`ORFxxx` / `AB1gp22` / `gp42` / `Phage protein Gp45`) |

---

## 三、 当前工作台任务 (`pan_20261110_145515_0f160b`) 222 个同源基因家族中修正的 18 个家族明细

| 同源家族 ID | 代表性产物名称 (`representative_product`) | 修正前错误分组 (`OLD`) | 修正后准确分组 (`NEW`) | 修正原因说明 |
| :--- | :--- | :--- | :--- | :--- |
| **`OG_0059`** | `Bacteriophage replication protein O` | `辅助代谢基因 (Metabolism & AMG)` | **`DNA复制与重组修复 (Replication & Repair)`** | 噬菌体经典复制起始蛋白 O，原被 Phold `nucleotide metabolism` 备注污染 |
| **`OG_0144`** | `Mu Gam-like end protection` | `辅助代谢基因 (Metabolism & AMG)` | **`DNA复制与重组修复 (Replication & Repair)`** | Mu 噬菌体 Gam 样线性 DNA 末端保护蛋白（拮抗宿主 RecBCD 核酸外切酶），原被备注污染 |
| **`OG_0188`** | `primosomal protein` | `宿主防御与互作 (Defense & Host Interaction)` | **`DNA复制与重组修复 (Replication & Repair)`** | DNA 复制引发体蛋白，原漏配 `primosomal` 并被备注中低分 Acranker 劫持 |
| **`OG_0056`** | `site-specific recombination directionality factor RDF` | `宿主防御与互作 (Defense & Host Interaction)` | **`溶原整合与切除 (Integration & Excision)`** | 位点特异性重组方向性因子（切除酶辅助因子 RDF），原被备注中 Acranker 劫持 |
| **`OG_0088`** | `site-specific recombination directionality factor RDF` | `其他功能蛋白 (Other Functional)` | **`溶原整合与切除 (Integration & Excision)`** | 与 `OG_0056` 同名的溶原切除方向性因子 RDF，现已统一归入溶原整合与切除 |
| **`OG_0067`** | `DefenseFinder protein` | `其他功能蛋白 (Other Functional)` | **`宿主防御与互作 (Defense & Host Interaction)`** | DefenseFinder 鉴定的抗宿主防御系统蛋白，原被 `\bdefense\b` 词边界漏判 |
| **`OG_0098`** | `DefenseFinder protein` | `其他功能蛋白 (Other Functional)` | **`宿主防御与互作 (Defense & Host Interaction)`** | DefenseFinder 鉴定的抗宿主防御系统蛋白，原被 `\bdefense\b` 词边界漏判 |
| **`OG_0178`** | `glycerophosphoryl diester phosphodiesterase` | `其他功能蛋白 (Other Functional)` | **`辅助代谢基因 (Metabolism & AMG)`** | 甘油磷酸二酯磷酸二酯酶（典型噬菌体磷脂代谢 AMG），原漏配 `phosphodiesterase` |
| **`OG_0075`** | `ATP-binding protein` | `辅助代谢基因 (Metabolism & AMG)` | **`其他功能蛋白 (Other Functional)`** | 通用 ATP 结合蛋白，原被备注中 `nucleotide metabolism` 误判为 AMG |
| **`OG_0214`** | `AAA family ATPase` | `辅助代谢基因 (Metabolism & AMG)` | **`其他功能蛋白 (Other Functional)`** | 通用 AAA+ 家族 ATP 酶，原被备注中 `nucleotide metabolism` 误判为 AMG |
| **`OG_0211`** | `F-box domain protein` | `宿主防御与互作 (Defense & Host Interaction)` | **`其他功能蛋白 (Other Functional)`** | F-box 结构域蛋白，原被备注中低分 Acranker (37.8%) 误判为抗 CRISPR |
| **`OG_0107`** | `Family of unknown function (DUF6651) domain-containing protein` | `尾部与尾丝吸附 (Tail & Host Interaction)` | **`假定蛋白与未表征 (Hypothetical)`** | 未知功能结构域 DUF6651，原未识别句中 `DUF` 且被备注污染 |
| **`OG_0011`** | `Domain of unknown function (DUF4258) domain-containing protein` | `其他功能蛋白 (Other Functional)` | **`假定蛋白与未表征 (Hypothetical)`** | 未知功能结构域 DUF4258，现准确归入假定蛋白与未表征 |
| **`OG_0092`** | `Domain of unknown function (DUF4468) with TBP-like fold domain-containing protein` | `其他功能蛋白 (Other Functional)` | **`假定蛋白与未表征 (Hypothetical)`** | 未知功能结构域 DUF4468，现准确归入假定蛋白与未表征 |
| **`OG_0141`** | `Protein of unknown function (DUF551)` | `其他功能蛋白 (Other Functional)` | **`假定蛋白与未表征 (Hypothetical)`** | 未知功能蛋白 DUF551，现准确归入假定蛋白与未表征 |
| **`OG_0204`** | `Domain of unknown function (DUF4760) domain-containing protein` | `其他功能蛋白 (Other Functional)` | **`假定蛋白与未表征 (Hypothetical)`** | 未知功能结构域 DUF4760，现准确归入假定蛋白与未表征 |
| **`OG_0031`** | `PHA01971 domain-containing protein` | `其他功能蛋白 (Other Functional)` | **`假定蛋白与未表征 (Hypothetical)`** | 未表征噬菌体保守结构域编号 PHA01971，现准确归入假定蛋白与未表征 |
| **`OG_0121`** | `AB1gp22` | `宿主防御与互作 (Defense & Host Interaction)` | **`假定蛋白与未表征 (Hypothetical)`** | 鲍曼不动杆菌噬菌体未表征编号基因 `AB1gp22`，原被低分 Acranker 备注劫持 |

---

## 四、 全后端分类模块核验与 105 万条 PhageScope 权威库压测结果

### 1. 权威噬菌体数据库 (`database/phagescope/metadata/annotated_protein/*.tsv`) 全量压测
针对本地 RefSeq、GenBank 与 PhagesDB 三大权威注释元数据表（共计 **1,051,665** 条噬菌体编码蛋白、**19,579** 种唯一 `Product` 词条）进行了全量分类压测：

1. **修复下划线 (`_`) 阻塞正则词边界 `\b` 的系统性盲区**:
   - Python 与 JavaScript 正则引擎中 `\w` 包含下划线 `_`，导致 `\b` 无法匹配由下划线连接的专业术语（例如 `Pfam:Phage_holin_7_1`、`RNase_H superfamily`、`Peptidase_C39`、`Pfam:DUF5403`、`Pfam:GP24_25`）。
   - 在 `AnnotationFuser.is_unannotated`、`_match_category_rules`、`ProteinComparer.classify_protein` 及前端 `render.ts` 中统一在正则匹配前执行 `.replace("_", " ").replace("%3b", ";")` 归一化，彻底消除下划线词边界盲区。
2. **修复同源重组修复酶与脱酰胺酶的跨类误判**:
   - 将 `uvsx|reca|rad51|homologous` 加入 `Integration & Excision` 中 `recombinase` 的负向排除列表，确保 T4 噬菌体经典的同源重组修复酶 `UvsX-like recombinase` 与 `RecA-like DNA recombinase` 准确归入 **`Replication & Repair`**，不再被误判为溶原整合酶；
   - 将 `deamidase|amidotransferase` 加入 `Lysis` 中 `amidase` 的负向排除列表，确保 `Papain fold toxin 1, glutamine deamidase` 等谷氨酰胺脱酰胺酶准确归入 **`Defense & Host Interaction`** 或 **`Metabolism & AMG`**，不再被误判为裂解酰胺酶。
3. **大幅扩充八大核心分组与 `Hypothetical` 词条库**:
   - 扩充后，1,051,665 条权威噬菌体蛋白中落入 `Other Functional` 的比例从 **8.57% (90,124 条)** 大幅降至 **4.90% (51,540 条)**，超过 **38,500 条**噬菌体特异功能蛋白与结构域被精准召回至对应生物学分组：

| 标准分类键 (`Category Key`) | 权威库命中蛋白总数 | 占比 (%) | 涵盖唯一词条数 (`Unique Terms`) |
| :--- | ---: | ---: | ---: |
| `Hypothetical` | 582,637 | 55.40% | 3,278 |
| `Tail & Host Interaction` | 107,298 | 10.20% | 1,517 |
| `Replication & Repair` | 92,098 | 8.76% | 2,203 |
| `Head & Packaging` | 67,783 | 6.45% | 981 |
| `Metabolism & AMG` | 56,754 | 5.40% | 2,154 |
| `Other Functional` | 51,540 | 4.90% | 6,979 |
| `Transcription & Regulation` | 35,318 | 3.36% | 1,245 |
| `Lysis` | 28,856 | 2.74% | 515 |
| `Defense & Host Interaction` | 15,301 | 1.45% | 447 |
| `Integration & Excision` | 14,080 | 1.34% | 260 |
| **合计 (Total)** | **1,051,665** | **100.00%** | **19,579** |

---

### 2. 后端全链路二级分类器排查与统一修复清单

除主分类器 `src/analysis/annotation/fuser.py` 外，对后端其余 5 个涉及功能分类与关键词判定的模块进行了逐一排查与修复：

1. **`src/analysis/annotation/builtin_annotator.py` (第 285 行)**:
   - **原缺陷**: 当内置注释器对 >300 aa 的 ORF 未找到任何 motif 时，硬编码赋值为 `prod_desc = "putative structural/catalytic protein"`，导致下游 `AnnotationFuser.is_unannotated` 误以为该基因已有明确功能并归入 `Head & Packaging`，从而跳过了 Phold/Foldseek 结构挽救注释。
   - **修复**: 移除该伪注释启发式逻辑，未命中 motif 的 ORF 统一保持 `"hypothetical protein"`，交由下游同源与结构注释器挽救。
2. **`src/analysis/annotation/functional_assigner.py` (第 387 行)**:
   - **原缺陷**: `_parse_cdd_domain_product` 内部维护了一段过时的 `if/elif` 分支，返回旧版分类名 `"Structural"` 和 `"general"`。
   - **修复**: 统一替换为调用 `AnnotationFuser.infer_category(product)`。
3. **`src/analysis/pan_genomics/engine.py`**:
   - **`_analyze_tail_operons` (第 387-393 行)**: 补充 `\b` 词边界、英式拼写 `fibre`、`baseplate spike`、`sialidase`、`depolymerase`、`host range`、`host specificity`、`adhesin`、`minor/distal tail`。
   - **`_analyze_lifestyles_and_defense` (第 478-510 行)**: 补充识别 `tyrosine-type recombinase`、`CII-like regulator`、`prophage repressor`、`recombination directionality factor` (`rdf`)，排除同源重组酶 `uvsx/reca/rad51/homologous`，并将 `"溶源"` 统一规范为 `"溶原"`。
   - **`_analyze_lysis_cassette` (第 567-585 行)**: 为裂解盒识别正则补充严格 `\b` 词边界（如 `\brz(?:-like|1)?\b`、`\b[a-z0-9'-]*muramidase\b`）并要求 `cat == "Lysis"`，防止尾刺/结构溶菌酶或 `hemolysin` 混入裂解盒统计。
4. **`src/analysis/pan_genomics/clusterer.py` (第 94-129 行)**:
   - 在代表性注释投票中优先过滤所有满足 `AnnotationFuser.is_unannotated` 的未知功能/DUF 词条，并对聚类结果直接调用 `AnnotationFuser.infer_category(rep_prod)`。
5. **`src/analysis/protein_compare/engine.py` (第 27-180 行、第 305-365 行)**:
   - **原缺陷**: `is_hypothetical` 仅检查 4 个固定字符串；`classify_protein` 先检查 `direct_cat` 中是否含 `"packaging"`，导致所有 `AnnotationFuser` 标注为 `"Head & Packaging"` 的衣壳蛋白（如 `major capsid protein`、`portal protein`）被全部误归入 `"packaging"`（末端酶），使 `"capsid_head"` 分组被清空。
   - **修复**: `is_hypothetical` 统一委托给 `AnnotationFuser.is_unannotated`；全面扩充 `PROTEIN_CATEGORIES` 五大功能组正则；`classify_protein` 优先基于 `product` 词边界正则精确区分 `"packaging"` 与 `"capsid_head"`，再调用 `AnnotationFuser.infer_category` 进行兜底映射。


