# 其他功能工作台（Other Tools Workbench）集成过程留档

## 1. 背景与目标
为方便在 GUI 界面中统一管理和触发项目中的两大端到端自动化流水线，新增独立的左侧导航标签页 **其他功能 (`/other-tools`)**，视觉与交互架构对齐 **组装分析工作台 (`AnalysisView.vue`)**，集成以下两个功能模块：
1. **邮件自动收件 → 注释 → Word 报告 → SMTP 回传** (`MailAutoPipelineModule.vue`)
2. **生工 16S 测序结果自动化 BLAST 与导出流程** (`Sangon16SPipelineModule.vue`)

---

## 2. 架构设计与模块划分

### 2.1 后端路由模块 (`src/backend/routes/other_tools.py`)
遵循单一职责与模块化原则，在 `src/backend/routes/other_tools.py` 中创建前缀为 `/api/other_tools` 的 FastAPI 路由，并在 `src/backend/api_server.py` 中完成挂载：
- **邮件自动注释与 SMTP 回传接口**：
  - `GET /api/other_tools/mail_pipeline/overview`：读取 `mail_config.json`、检查 `.mail_auth` 授权码就绪状态、汇总 `results/email_downloads/processed_index.json` 已处理 SHA256 指纹、列出 `up_*` 批次清单、`results/email_sends` 下的打包产物 (`.zip` / `.manifest.json`) 与 `.docx` Word 报告，以及 `pipeline.log` 实时尾部日志。
  - `POST /api/other_tools/mail_pipeline/config`：在线更新保存 `mail_config.json`（IMAP/SMTP 服务器、白名单、附件扩展名、扫描天数等）。
  - `POST /api/other_tools/mail_pipeline/fetch`：立即触发 `MailFetcher` + `AttachmentSaver` 扫描 IMAP 收件箱并执行 SHA256 幂等落盘。
  - `POST /api/other_tools/mail_pipeline/run`：后台异步启动 `python -X utf8 -m src.mail_download.auto_pipeline`，支持全链路运行、仅生成不发信 (`--no-send`) 或指定已有批次重跑注释 (`--annotate-only`)。
- **生工 16S 测序自动化 BLAST 与导出接口**：
  - `GET /api/other_tools/sangon_16s/overview`：扫描 `G:\测序数据\生工16s` 下的 `YYYYMMDD_订单号` 订单目录，统计 `原始压缩包/*.zip`、`原始数据/*.1.fasta`、`*.ab1`、`BLAST结果/16S鉴定结果.csv` 及检出率状态。
  - `GET /api/other_tools/sangon_16s/order/{order_dir_name}/results`：解析指定订单的 11 列 `16S鉴定结果.csv`，返回供前端在线展示与检索的数据。
  - `POST /api/other_tools/sangon_16s/scan_mail`：连接 QQ 邮箱扫描 `info1@sangon.com` 测序完成通知邮件，提取 10 位订单号与 `cxOrderID` 下载链接，并自动初始化 `原始压缩包`、`原始数据`、`BLAST结果` 三级目录。
  - `POST /api/other_tools/sangon_16s/run_pipeline`：对选定或待处理的生工 16S 订单执行自动解压、提取 `*.1.fasta`（排除 haplotype 分型文件）、提交本地 `16S_ribosomal_RNA` 库并发 BLASTn 比对、调用 `BiologyTranslator` 批量汉化物种名称，并导出 11 列 `UTF-8-SIG` 标准 CSV。
- **本地资源联动接口**：
  - `POST /api/other_tools/open_path`：在 Windows 资源管理器中定位或打开生成的 `.docx` 报告、`.zip` 归档或 `16S鉴定结果.csv`。

### 2.2 前端视图与组件模块 (`src/web-next/src/`)
1. **导航与路由**：
   - `src/web-next/src/components/layout/AppSidebar.vue`：在“分析工具”分类下新增“其他功能”导航项及纯矢量 SVG 图标（无任何 Emoji）。
   - `src/web-next/src/router/index.ts`：注册 `/other-tools` 路由至 `OtherToolsView.vue`。
2. **工作台入口 (`src/web-next/src/views/OtherToolsView.vue`)**：
   - 采用与 `AnalysisView.vue` 一致的卡片网格与顶部状态栏设计，支持从工具卡片进入具体工作区，并在顶部提供快捷切换标签与“返回工具列表”按钮。
3. **子模块 1 (`src/web-next/src/views/OtherTools/modules/MailAutoPipelineModule.vue`)**：
   - 可视化展示 5 阶段流水线（IMAP 收件与 SHA256 去重 -> Pharokka+Phold 级联注释 -> Word 报告与文献引用 [1]-[8] -> ZIP 打包与清单 -> SMTP 自动回传）。
   - 提供一键收件、一键启动完整流水线、对历史 `up_*` 批次单点重跑、在线查看/打开 `.docx` 与 `.zip` 产物、查看 SHA256 指纹库与 `pipeline.log` 实时日志，以及 `mail_config.json` 配置弹窗。
4. **子模块 2 (`src/web-next/src/views/OtherTools/modules/Sangon16SPipelineModule.vue`)**：
   - 可视化展示 7 步生工 16S 自动化流程。
   - 支持一键扫描生工通知邮件并创建订单目录、展示所有 `YYYYMMDD_订单号` 批次状态、多选或单选订单触发自动解压+BLAST+导出，并在右侧提供 11 列鉴定结果的在线表格预览与关键词过滤。

---

## 3. 测试与验证记录
1. **后端接口与规范单元测试 (`tests/test_other_tools_api.py`)**：
   - 执行 `python -m pytest tests/test_other_tools_api.py -v`，3 项测试全部通过（耗时 1.42s），验证了邮件流水线概览、生工 16S 订单概览与 11 列 CSV 解析接口，以及所有新增/修改文件的 UTF-8 编码与零 Emoji 合规性。
2. **前端 TypeScript 类型检查与生产构建**：
   - 在 `src/web-next` 下执行 `npm run build` (`vue-tsc -b && vite build`)，零错误通过编译，成功生成 `OtherToolsView` 产物包。
