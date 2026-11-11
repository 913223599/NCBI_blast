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



---

## 4. 第二阶段迭代优化记录（精简描述 + 历史清理 + 邮箱 Key 编辑 + 完整路径与自动迁移）

### 4.1 精简功能描述
- 更新 [OtherToolsView.vue](file:///f:/NCBI%20blast/src/web-next/src/views/OtherToolsView.vue)、[MailAutoPipelineModule.vue](file:///f:/NCBI%20blast/src/web-next/src/views/OtherTools/modules/MailAutoPipelineModule.vue)、[Sangon16SPipelineModule.vue](file:///f:/NCBI%20blast/src/web-next/src/views/OtherTools/modules/Sangon16SPipelineModule.vue) 中的标题、流程节点、指标卡片与按钮文案，去除修饰词，保留准确简洁的功能表述。

### 4.2 邮箱 Key（授权码）在线编辑
- 后端 [secret_store.py](file:///f:/NCBI%20blast/src/backend/services/other_tools/secret_store.py) 与 [config.py](file:///f:/NCBI%20blast/src/mail_download/config.py)：支持从独立密钥文件 `.mail_auth` / `.mail_smtp_auth`（已加入 `.gitignore`，不入库）优先读取授权码，并提供掩码回显。
- 路由 `POST /api/other_tools/mail_pipeline/auth`：支持在线写入或清除 IMAP / SMTP 授权码。
- 前端：在邮件模块“邮箱配置”弹窗与“授权码”弹窗、生工 16S 模块“邮箱 Key”弹窗中均可查看掩码状态并直接编辑保存邮箱 Key。

### 4.3 输入/输出目录显示完整路径并支持修改后自动迁移
- 后端 [dir_migrator.py](file:///f:/NCBI%20blast/src/backend/services/other_tools/dir_migrator.py)：实现 `migrate_directory()` 与 `rewrite_json_paths()`，当下载目录、回传目录或生工 16S 根目录变更时，自动将旧目录下的批次/订单迁移至新目录，同名文件保留不覆盖，并自动更新 `processed_index.json` / `manifest.json` 内的绝对路径。
- 前端 [PathField.vue](file:///f:/NCBI%20blast/src/web-next/src/views/OtherTools/components/PathField.vue)：展示完整绝对路径（`word-break: break-all` 不截断），支持一键修改保存并触发后端自动迁移。

### 4.4 历史数据清理功能
- 后端 [history_cleaner.py](file:///f:/NCBI%20blast/src/backend/services/other_tools/history_cleaner.py)：
  - `cleanup_mail_history()`：支持按类别（收件批次 `up_*`、回传压缩包、Word 报告、注释中间目录 `ANNO_*`、流水线日志、去重记录）及保留天数清理，或单条记录删除。
  - `cleanup_sangon_history()`：支持按订单清理“解压数据 (`原始数据/`)”、“BLAST 中间缓存”、“鉴定结果 CSV”或“整个订单目录”。
- 前端 [CleanupDialog.vue](file:///f:/NCBI%20blast/src/web-next/src/views/OtherTools/components/CleanupDialog.vue)：提供分类勾选与确认清理弹窗，同时在表格行提供单条删除/清理操作。

### 4.5 测试验证
- `python -m pytest tests/test_other_tools_api.py tests/test_mail_download.py -v`：32 项单元测试全部通过。

---

## 5. 第三阶段迭代优化记录（邮件获取去重、服务端/前端翻页）

### 5.1 邮件自动收件流去重与收件箱分页浏览
- [fetcher.py](file:///f:/NCBI%20blast/src/mail_download/fetcher.py)：头部筛选阶段拉取 `MESSAGE-ID`，新增当次批内同 `Message-ID` 邮件级去重（保留最新一封，统计 `skipped_dup_mails`）。
- [downloader.py](file:///f:/NCBI%20blast/src/mail_download/downloader.py)：在 `processed_index.json` 中同步记录邮件 `message_id`，新增 `has_message_id()` 与只读 `entries()` 查询接口。
- [mail_inbox_browser.py](file:///f:/NCBI%20blast/src/backend/services/other_tools/mail_inbox_browser.py)：新增邮件收件箱去重浏览服务 `list_whitelist_mails()`，支持发件人白名单内邮件批内去重（按 `Message-ID` 与主题+日期）、结合 SHA256/Message-ID 指纹库的 `only_new` 过滤与服务端分页切片（仅对当前页拉取全文解析附件指纹）。
- 路由 `POST /api/other_tools/mail_pipeline/list_mails` 与 `GET /api/other_tools/mail_pipeline/overview`（移除 `processed_items[:50]` 截断以支撑前端分页）。

### 5.2 生工 16S 邮件扫描两级去重、防误建记忆与服务端翻页
- [sangon_mail_scanner.py](file:///f:/NCBI%20blast/src/backend/services/other_tools/sangon_mail_scanner.py)：
  - 放弃原先 `ids[-15:]` 固定切片，改为两阶段拉取：全量头部 `(FROM SUBJECT DATE MESSAGE-ID)` 按 10 位订单号 / `Message-ID` 去重合并（累计 `duplicate_count`），再按服务端分页参数（`page`, `page_size`）仅对当前页邮件抓取正文解析 `cxOrderID` 与下载链接。
  - 引入本地 `.sangon_mail_index.json`（已加入 `.gitignore`）持久记录已扫描与历史已清理订单，防止使用清理功能删除历史订单后下次扫描再次自动建出空目录。
  - 新增手动单条目录初始化服务 `init_sangon_order_dir()`（路由 `POST /api/other_tools/sangon_16s/init_order`）。
- [history_cleaner.py](file:///f:/NCBI%20blast/src/backend/services/other_tools/history_cleaner.py)：删除订单目录时自动向 `.sangon_mail_index.json` 写入 `cleaned=True` 保护标记，并新增 `scan_index` 清理选项按需重置扫描去重记忆。

### 5.3 前端通用分页组件与界面适配
- 新增 [PaginationBar.vue](file:///f:/NCBI%20blast/src/web-next/src/views/OtherTools/components/PaginationBar.vue)：通用分页底栏组件（支持首页/上一页/页码/下一页/末页及每页条数切换）。
- 更新 [Sangon16SPipelineModule.vue](file:///f:/NCBI%20blast/src/web-next/src/views/OtherTools/modules/Sangon16SPipelineModule.vue)：
  - 生工通知邮件面板接入去重开关、仅显示新邮件、自动建目录、忽略清理记忆开关，显示批内合并数与目录去重状态，提供行内「建目录」按钮与服务端分页。
  - 为 `订单列表`（默认每页 6 条，避免结果预览被挤出首屏）与 `16S 鉴定结果`（默认每页 20 条）接入前端分页。
- 更新 [MailAutoPipelineModule.vue](file:///f:/NCBI%20blast/src/web-next/src/views/OtherTools/modules/MailAutoPipelineModule.vue)：
  - 新增 `收件箱邮件` 子标签页，支持邮件级去重开关、仅看含未处理附件邮件过滤与服务端真实翻页浏览。
  - 为 `收件批次`、`回传压缩包`、`Word 报告` 与 `去重记录` 全部接入 `<PaginationBar>` 分页。
- 修复 [api.ts](file:///f:/NCBI%20blast/src/web-next/src/views/OtherTools/api.ts) 在 `--exactOptionalPropertyTypes` 下的 `RequestInit.body` 类型定义。

### 5.4 本阶段测试与验证
- `python -m pytest tests/test_other_tools_api.py tests/test_mail_download.py -v`：新增离线 `FakeIMAP` 用例与路由校验后，35 项测试全部通过。
- 前端执行 `npm run build` (`vue-tsc -b && vite build`) 与严格类型检查，零报错通过。

---

## 6. 第四阶段全链路实测核查、断点修复与发信闭环（2026-11-11）

### 6.1 全链路核查目标与安全边界
围绕「生工 16S 下载 -> 解压 -> BLAST -> 导出」以及「邮件收件 -> 注释 -> Word 报告 -> 打包 -> SMTP 回传」两大自动化流水线开展真实环境（QQ IMAP/SMTP `913223599@qq.com` + 本地 16S 数据库 + 注释与报告流水线）断点排查与端到端自发自收验证：
- 所有 SMTP 发信实测均仅定向发送至配置账号本人邮箱 `913223599@qq.com`，不触碰外部 `reply_to`（`yssw_service@163.com`）。
- 严格遵守平台访问边界，对生工登录鉴权页引入的阿里云人机验证机制（`AliyunCaptcha.js`）不作任何绕过或自动化破解尝试，改用浏览器合规登录后本地下载包自动认领架构衔接。

### 6.2 排查发现并修复的系统断点
1. **外部与下载衔接断点（人机验证 + 本地下载包断层）**：
   - 实测 `notice.sangon.com` 预览地址返回 HTTP 502，`store.sangon.com/downloadAttachFile` 跳转至带 `AliyunCaptcha.js` 的 `passport.sangon.com`，无法无头直连下载；与此同时用户通过浏览器下载至本机 `Downloads` 的 `吴晨_*_测序结果.zip` 不会自动进入 `原始压缩包/`。
   - **修复**：保留浏览器合规跳转「打开下载页」，新增 [sangon_zip_importer.py](file:///f:/NCBI%20blast/src/backend/services/other_tools/sangon_zip_importer.py) 与 [sangon_settings.py](file:///f:/NCBI%20blast/src/backend/services/other_tools/sangon_settings.py) 的 `downloads_dir` 配置，新增 `POST /api/other_tools/sangon_16s/import_downloads` 接口及 `run_pipeline` 自动兜底认领逻辑，并在 [Sangon16SPipelineModule.vue](file:///f:/NCBI%20blast/src/web-next/src/views/OtherTools/modules/Sangon16SPipelineModule.vue) 增加待认领提示与一键认领操作。
2. **非测序物流邮件误建目录断点 (`sangon_mail_scanner.py`)**：
   - `info1@sangon.com` 中的发货通知（如 `1011709710`「已发货」）此前被当作测序通知创建空目录。
   - **修复**：新增 `_is_sequencing_notice_subject()` 过滤，将该类邮件标记为 `non_sequencing`，禁止建目录。
3. **无系统 `PATH` 启动环境找不到 `blastn.exe` (`tool_config.py` / `local_blast.py`)**：
   - `blastn.exe` 安装在 `D:\Program Files\NCBI\blast-2.16.0+\bin\blastn.exe` 时，Electron/子进程剥离 `PATH` 环境下仅扫描 `C:` 导致 `FileNotFoundError`。
   - **修复**：[tool_config.py](file:///f:/NCBI%20blast/src/workbench/models/tool_config.py) 扩展 `ProgramW6432` 与 `C:`~`F:` 多盘符 `NCBI\blast-*` 扫描；[local_blast.py](file:///f:/NCBI%20blast/src/blast/local_blast.py) 统一优先调用 `ToolConfig.resolve_bio_tool()`。
4. **`force_reblast=True` 静默命中缓存及 CSV 排序断点 (`other_tools.py`)**：
   - `BlastEngine.run` 检查已有 `reports/*.csv` 时会直接 Cache Restored，导致勾选「强制重新比对」无效；样本 CSV 导出默认字典序会导致 `-10` 排在 `-2` 之前。
   - **修复**：`force_reblast=True` 时先调用 `mgr.delete_task()` 并清理 `results/blast/{task_name}` 目录再重建任务；`_export_sangon_order_csv()` 增加样本编号自然数字排序 `_sangon_csv_sort_key`。
5. **Word 报告在 `tRNA = 0` 与动态安全审计场景崩溃断点 (`build_annotation_report.py`)**：
   - 真实标注产物 `ANNO_8CFE4CC4`（`cds=74, trna=0`）运行报告生成时在 `min(trna_starts)` 抛出 `ValueError`，且多处存在 `n_cds=0` 除零或安全审计静态文本问题。
   - **修复**：在 [scripts/build_annotation_report.py](file:///f:/NCBI%20blast/scripts/build_annotation_report.py) 修复 `n_trna == 0` 保护、回退引擎表格与安全审计动态输出，并在 `ANNO_8CFE4CC4` 沙盒副本实测生成完整 `.docx`（带 `[1]-[8]` 引用域）及压缩包通过。
6. **打包与 SMTP 多收件/抄送/测试发信断点 (`packer.py` / `sender.py` / `other_tools.py`)**：
   - [sender.py](file:///f:/NCBI%20blast/src/mail_download/sender.py) 修复 `sendmail` 漏传 `cc` 收件人并支持分号/逗号多收件人与 `Message-ID` 自动生成。
   - [packer.py](file:///f:/NCBI%20blast/src/mail_download/packer.py) 在 `DEFAULT_PRODUCT_GLOBS` 中纳入 `*.docx`。
   - [other_tools.py](file:///f:/NCBI%20blast/src/backend/routes/other_tools.py) 新增 `POST /api/other_tools/mail_pipeline/test_send`（含 `ANNOTATIONS_DIR` 最新 `.docx` 自动回退查找）与 `POST /api/other_tools/sangon_16s/send_result`，安全约定 `to` 留空或传 `self` 时仅发往自身账号。
   - [MailAutoPipelineModule.vue](file:///f:/NCBI%20blast/src/web-next/src/views/OtherTools/modules/MailAutoPipelineModule.vue) 与 [Sangon16SPipelineModule.vue](file:///f:/NCBI%20blast/src/web-next/src/views/OtherTools/modules/Sangon16SPipelineModule.vue) 接入「测试发信」与「发送结果邮件 / 发给自己」交互弹窗，严守零 Emoji 与 UTF-8 规范。

### 6.3 验证与实测结果
1. **自动化单元测试**：
   - `python -m pytest tests/test_mail_download.py tests/test_mail_send.py tests/test_other_tools_api.py -v`：57 项全部通过（覆盖两阶段收件、去重分页、Word 打包、CC/多收件人、`non_sequencing` 拦截、下载包归档、`force_reblast` 清理、`test_send` 与 `send_result` 安全默认发己、零 Emoji 与 UTF-8 合规检查）。
   - 联动扩展回归 `python -m pytest tests/test_auto_return_workflow.py tests/test_mail_download.py tests/test_mail_send.py tests/test_other_tools_api.py -v`：74 项全部通过（3.95s）。
2. **真实环境端到端联调与自发信回读**：
   - 真实生工邮件扫描：`raw=17, unique=13, non_sequencing=1`，确认 `1011709710` 已发货邮件被准确拦截未建空目录。
   - 沙盒全链路 16S 流程（剥离 `PATH` 中 BLAST 路径）：订单 `20261014_2140608938` 自动从 `Downloads` 认领 `吴晨_2140608938_测序结果.zip` -> 解压 22 条 `.1.fasta` -> 自动定位 `D:\Program Files\NCBI\blast-2.16.0+\bin\blastn.exe` 完成 16 线程 megablast -> 导出 22 行 11 列 CSV（命中 21 / 未命中 1）-> `force_reblast=True` 验证 22/22 CSV 重新生成。
   - 真实 SMTP 自发信与 IMAP 回读：
     - `POST /other_tools/mail_pipeline/test_send` 成功发送至 `913223599@qq.com`（IMAP `INBOX seq=3513`），压缩包完整包含 `smtp_self_test.txt` 与 `ANNO_NC_005859_注释报告.docx`。
     - `POST /other_tools/sangon_16s/send_result` 成功发送至 `913223599@qq.com`（IMAP `INBOX seq=3514`），附件 `16S鉴定结果_20261014_2140608938.zip` 解压校验含 22 行完整 UTF-8 中文 CSV。
     - 前置 `ANNO_8CFE4CC4` 全报告流水线复测（tRNA=0 修复后）成功生成 62.3 KB `.docx` 与 278.2 KB 归档包并已自收验证（`INBOX seq=3510`）。
3. **前端编译验证**：
   - `src/web-next` 下 `npm run build` (`vue-tsc -b && vite build`) 零报错通过（耗时 23.98s）。

---

## 7. 第五阶段注释回传全链路真机实测与工作台闭环（2026-11-11）

### 7.1 实测范围与隔离策略
围绕「IMAP 收件与去重 -> Pharokka + PhageScope + Phold AI + DeepSafetyAuditor 多引擎注释 -> Word 报告生成与 `[1]–[8]` 参考文献引用注入 -> ResultPacker 打包 -> SMTP 回传」开展基线真机实测，并排查修补前后端闭环断点，全程通过隔离配置与 `913223599@qq.com` 自发自收，测后清理临时目录。

### 7.2 发现并修复的断点
1. **Word 报告展示与回传目录脱节 (`auto_pipeline.py` / `other_tools.py` / `history_cleaner.py`)**：
   - `auto_pipeline.py` 仅将 `.docx` 打包进 `.zip`，未向 `cfg.resolved_send_dir` 同步复制，导致工作台「Word 报告」子表长期为空、清理项与 `test_send` 默认附带找不到报告。
   - **修复**：在 [auto_pipeline.py](file:///f:/NCBI%20blast/src/mail_download/auto_pipeline.py) `_pack_and_send()` 中新增 `_sync_docx_to_send_dir()` 同步复制 `.docx` 至回传目录；[other_tools.py](file:///f:/NCBI%20blast/src/backend/routes/other_tools.py) `/mail_pipeline/overview` 增加依据 `outbound_packages` 对应 `ANNOTATIONS_DIR/{task_id}/*.docx` 的回退检索与去重；[history_cleaner.py](file:///f:/NCBI%20blast/src/backend/services/other_tools/history_cleaner.py) 支持按文件名精确删除位于回退目录中的 `.docx`。
2. **批次重跑模式不支持发信及扩展名/退出的边界缺陷 (`auto_pipeline.py`)**：
   - `--annotate-only DIR` 原先硬编码 `do_send=False`、未读 `manifest.json` 填充原邮件信息、`*.fasta`/`*.fa`/`*.fna` 短路匹配缺失配置后缀、且构建/发送失败仍返回 `0`。
   - **修复**：新增 `_collect_batch_fastas()` 按 `cfg.attachment_exts` 全量采集、新增 `_load_batch_mail_info()` 统一读取原邮件信息、新增 `--send` 标志及 `_resolve_send_target()`（显式传入 `--to self` 安全解析为自身账号且缺失本人账号时不回退至 `reply_to`）、正确传递失败退出码 `1`，并将 `_register_test_batch()` 测试发件人标记修正为 `local-test-input`。
3. **`/mail_pipeline/run` `to="self"` 透传与结果压缩包直发缺失 (`other_tools.py` / `MailAutoPipelineModule.vue`)**：
   - `/mail_pipeline/run` 此前未解析 `to="self"`；前端缺少从回传压缩包直接发信以及对批次重跑并发信的交互操作。
   - **修复**：`/mail_pipeline/run` 前置调用 `_resolve_send_target()` 并校验批次与测试输入路径，对 `annotate_only_batch` 正确下发 `--to` / `--send`；新增 `POST /api/other_tools/mail_pipeline/send_package`（带文件名防穿越校验、`.manifest.json` 清单解析与默认发往自身安全约定）；[MailAutoPipelineModule.vue](file:///f:/NCBI%20blast/src/web-next/src/views/OtherTools/modules/MailAutoPipelineModule.vue) 主控制栏新增「回传目标」选择（含「仅发给自己测试」），收件批次接入「重跑」确认弹窗（支持仅打包 / 发给自己 / 自定义回传），回传压缩包接入「发信」弹窗。
4. **辅助脚本与调度器健壮性 (`scheduler.py` / `build_annotation_report.py`)**：
   - 修复 [scheduler.py](file:///f:/NCBI%20blast/src/mail_download/scheduler.py) `run_poll()` 非详细模式传入 `None` 导致参数解析异常的缺陷。
   - 强化 [build_annotation_report.py](file:///f:/NCBI%20blast/scripts/build_annotation_report.py) 对缺失 `safety_audit.json` 与 `swissprot_hits.tsv` 异常 `bit score` 值的容错（`_safe_float`）。

### 7.3 实测与回归验证记录
1. **自动化单元测试**：
   - `python -X utf8 -m pytest tests/test_auto_return_workflow.py tests/test_mail_download.py tests/test_mail_send.py tests/test_other_tools_api.py -v`：**80 项全部通过**（`5.94s`，覆盖 `.docx` 同步、`--annotate-only --to self`、`scheduler.run_poll`、`build_annotation_report.py` 缺失安全审计容错、`/overview` 回退列表、`/send_package` 安全路由、零 Emoji 与 UTF-8 合规检查）。
2. **基线全链路真机实测（剥离 `PATH` 中 BLAST）**：
   - `auto_pipeline` 从 QQ INBOX `seq=3515` 拉取待测 `e2e_phage_171216.fasta` -> Pharokka（66 CDS）+ PhageScope（7 CDS）+ Phold AI（1 CDS）+ 安全审计完成 74 个 CDS 注释 -> 构建 `61.6 KB` Word 报告并通过 `[1]–[8]` 引用校验 -> 打包 41 产物（`278.2 KB`）-> SMTP 发至 `913223599@qq.com` -> QQ INBOX `seq=3516` 回读校验全产物齐全 -> 二次运行 SHA256 指纹去重跳过（耗时 `335.2s`，`exit=0`）。
3. **修复后全链路与路由联调真机复测**：
   - 沙盒拉取批次 `up_20261111_172914_003515` 执行 `auto_pipeline --annotate-only --to self`（耗时 `294.5s`，`exit=0`）：确认 `send_dir` 同时落盘 `.zip` 与 `62,333 B` `.docx` 报告；QQ INBOX `seq=3517` 收到回传邮件且正文成功引用原邮件主题。
   - 挂载 FastAPI 路由联调 `GET /mail_pipeline/overview`（正常检出 `1` 压缩包与 `1` Word 报告）与 `POST /mail_pipeline/send_package`（在沙盒保留外部 `reply_to` 情况下传 `to="self"` 严格只发往 `913223599@qq.com`，QQ INBOX `seq=3518` 实收）。
4. **前端编译验证**：
   - `src/web-next` 下 `npm run build`（`vue-tsc -b && vite build`）零错误通过（`29.27s`）。

---

## 8. 「先仅收件后运行流水线不执行」断点定位与闭环修复（2026-11-11）

### 8.1 现场问题定位
1. **已收件批次未被自动接续**：用户先点击「仅收件」将邮件附件下载并写入 `processed_index.json`（如批次 `up_20261111_182735_003520` 内的 `12-A_asm_ngcs_scaffold_1.fasta`），随后点击「运行流水线」调用 [auto_pipeline.py](file:///f:/NCBI%20blast/src/mail_download/auto_pipeline.py)。因 `AttachmentSaver.save()` 指纹去重判定 0 个新附件，脚本直接以退出码 `0` 结束，导致已落地批次既未被注释也未打包回传。
2. **老批次无状态字段导致新旧难分**：原有 `manifest.json` 仅记录收件元数据，未记录流水线执行状态，难以在不误重跑历史已完成批次或 `_TEST` 目录的前提下精确识别待处理批次。
3. **运行状态与日志链路割裂**：[other_tools.py](file:///f:/NCBI%20blast/src/backend/routes/other_tools.py) `/mail_pipeline/run` 原先阻塞调用 `subprocess.run()`，运行期无法流式更新阶段文本；`/mail_pipeline/fetch` 与空跑退出信息也未落盘至 `pipeline.log`。
4. **前端横幅与状态回显失步**：[MailAutoPipelineModule.vue](file:///f:/NCBI%20blast/src/web-next/src/views/OtherTools/modules/MailAutoPipelineModule.vue) 在 `runtime.running` 由 `true -> false` 结束时未同步覆盖「流水线已在后台运行」蓝色横幅，且每次轮询覆盖用户输入的 `since_days`。

### 8.2 模块化修复与实现
1. **独立批次状态机（[batch_state.py](file:///f:/NCBI%20blast/src/mail_download/batch_state.py)）**：
   - 持久化维护 `manifest.json` 中的 `pipeline` 块（`downloaded` / `running` / `completed` / `failed`、关联 `task_ids` 与 `last_error`）。
   - 对缺少 `pipeline` 字段的历史批次，通过正则 `ANNO_<clean_stem>_<YYYYMMDD_HHMMSS>` 联动检索 `ANNOTATIONS_DIR` 与 `send_dir` 实际产物反推完成态，并通过 `collect_pending_batches()` 收集所有待处理非 `_TEST` 批次。
2. **下载初始化与流水线自动接续（[downloader.py](file:///f:/NCBI%20blast/src/mail_download/downloader.py) / [auto_pipeline.py](file:///f:/NCBI%20blast/src/mail_download/auto_pipeline.py)）**：
   - `AttachmentSaver.save()` 新建批次 `manifest.json` 时写入初始状态 `downloaded`。
   - `auto_pipeline.py` 完整模式（模式 B）在收件扫描后合并新下载批次与 `collect_pending_batches()` 待处理批次；抽取共享 `_run_batch_pipeline()` 在执行前后更新 `running` -> `completed` / `failed`，增加 `_emit()` 即时刷盘并向 `pipeline.log` 写入全流程扫描与执行审计日志。
3. **流式子进程监控与概览透出（[other_tools.py](file:///f:/NCBI%20blast/src/backend/routes/other_tools.py)）**：
   - `/mail_pipeline/overview` 为每个批次附加 `pipeline_status`、`pipeline_status_label`、`pending`、`task_ids` 及顶层 `pending_batches_count`。
   - `/mail_pipeline/fetch` 执行后同步写入 `pipeline.log`。
   - `/mail_pipeline/run` 升级为 `subprocess.Popen`（`-u` + `PYTHONUNBUFFERED=1`）逐行流式读取标准输出、推断并实时刷新运行 `stage` 与 `last_output`，并保留超时保护与终端 logger 输出。
4. **前端状态同步与视图增强（[MailAutoPipelineModule.vue](file:///f:/NCBI%20blast/src/web-next/src/views/OtherTools/modules/MailAutoPipelineModule.vue)）**：
   - 新增 `trackingRun` 监听任务起止，在运行结束或失败时立即把横幅与状态卡片切换为真实完成/失败反馈并重载列表。
   - 新增 `initializedOverview` 避免轮询覆盖用户编辑的 `since_days`，运行期间轮询缩短为 `2500ms`，并在「收件批次」表中增加「处理状态」列。

### 8.3 回归与隔离端到端验证记录
1. **自动化单元测试**：
   - `python -X utf8 -m pytest tests/test_auto_return_workflow.py tests/test_mail_download.py tests/test_mail_send.py tests/test_other_tools_api.py -v`：**81 项全部通过**（`3.96s`），新增 [test_mail_send.py](file:///f:/NCBI%20blast/tests/test_mail_send.py) 先收件后运行流水线自动接续与二次幂等跳过用例，[test_other_tools_api.py](file:///f:/NCBI%20blast/tests/test_other_tools_api.py) 升级为 `FakePopen` 流式监控测试并将 `batch_state.py` 纳入零 Emoji / UTF-8 静态门禁。
2. **前端构建检查**：
   - `src/web-next` 下 `npm run build`（`vue-tsc -b && vite build`）零错误通过（`13.28s`）。
3. **真实生产目录状态核验**：
   - 直接调用 `get_mail_pipeline_overview()` 核实 `pending_batches_count = 1`，真实批次 `up_20261111_182735_003520` 准确识别为 `downloaded`（`待注释处理`）。
4. **隔离沙盒全链路实测**：
   - 将 `12-A_asm_ngcs_scaffold_1.fasta`（`44,428 B`）置入「仅收件已完成、尚无注释产物」的沙盒环境后发起 `POST /api/other_tools/mail_pipeline/run`（`to="self"`，配置文件仍保留外部 `reply_to`）。
   - 流水线自动发现并接续处理该批次，耗时 `273.2s` 完成注释、生成 `61.7 KB` Word 报告与 `270.2 KB` 压缩包（含 41 个产物文件），`exit_code = 0`，批次状态流转为 `completed`（`pending_batches_count = 0`）。
   - 二次触发 `POST /api/other_tools/mail_pipeline/run` 耗时 `0.8s` 幂等跳过。
   - 读取 QQ IMAP `Sent Messages` 第 `108` 封邮件核实仅向 `913223599@qq.com` 发送成功且附件完整（`276,697 B`）；测后已清理沙盒在 `results/annotations/` 下生成的临时注释目录，真实待处理批次 `up_20261111_182735_003520` 原封保留。

---

## 9. 生工 16S「仅新邮件」与邮件列表显示逻辑优化（2026-11-11）

### 9.1 问题排查
1. **顶栏勾选不生效**：[Sangon16SPipelineModule.vue](file:///f:/NCBI%20blast/src/web-next/src/views/OtherTools/modules/Sangon16SPipelineModule.vue) 顶栏的「扫描去重」与「仅显示新邮件」未绑定 `@change` 处理，列表打开后切换顶栏复选框界面无反应。
2. **当次新建切换过滤即丢失**：全量扫描自动新建目录后，紧接着在同一会话内勾「仅新邮件」若重新请求后端，刚建目录在磁盘已转为 `existing`，导致结果骤减为 0。
3. **非测序邮件被历史目录掩盖**：若磁盘残留旧发货目录（如 `20261102_1011709710`），原先 `in_disk` 优先于 `not is_seq_mail` 会将发货通知误展示为绿色的 `目录已存在`。
4. **统计与状态语义区分弱**：`created` 与 `existing` 共用绿色样式，`onlyNew` 下空结果仅提示「暂无匹配生工邮件」，未告知已过滤数量及回切入口。

### 9.2 修改实施
1. **后端扫描分类与会话新建保留（[sangon_mail_scanner.py](file:///f:/NCBI%20blast/src/backend/services/other_tools/sangon_mail_scanner.py) / [other_tools.py](file:///f:/NCBI%20blast/src/backend/routes/other_tools.py)）**：
   - 将 `if not is_seq_mail:` 调整到 `in_disk` 之前，确保非测序通知始终标记为 `non_sequencing` 并附带 `legacy_dir_exists` 标识。
   - 新增 `preserve_created_orders` 参数与 `created_order_nos`、`new_count`、`created_count`、`existing_count`、`non_sequencing_count` 返回字段；仅在同一次面板筛选切换时保留本轮新建订单在「仅新邮件」下的可见性，主动点击「扫描邮件」时清空重置。
2. **前端双模块展示升级（[Sangon16SPipelineModule.vue](file:///f:/NCBI%20blast/src/web-next/src/views/OtherTools/modules/Sangon16SPipelineModule.vue) / [MailAutoPipelineModule.vue](file:///f:/NCBI%20blast/src/web-next/src/views/OtherTools/modules/MailAutoPipelineModule.vue)）**：
   - 顶栏复选框补全 `@change="handleMailFilterChange"` 即时联动，补充清晰规则悬停说明（明确按本地目录/索引判定，不看 IMAP 已读标记）。
   - 为 `created`（本次新建）、`new`（待建目录）、`existing`（目录已存在）、`history_skipped`（已清理跳过）、`non_sequencing`（非测序邮件）拆分五态视觉徽章，并在标题/徽章区和空态中清晰展示各分类过滤数量及一键「查看全部邮件」按钮；收件箱预览面板同步补充 `processedSkipped` 计数与「显示全部邮件」引导。

### 9.3 验证结果
1. **单元测试**：`python -X utf8 -m pytest tests/test_auto_return_workflow.py tests/test_mail_download.py tests/test_mail_send.py tests/test_other_tools_api.py -v` **81 项全部通过**（`5.40s`），新增 `preserve_created_orders` 会话保留、`non_sequencing` 优先级覆盖历史目录、分类统计计数及路由透传断言（[test_other_tools_api.py](file:///f:/NCBI%20blast/tests/test_other_tools_api.py)）。
2. **前端构建**：`src/web-next` 下 `npm run build`（`vue-tsc -b && vite build`）零错误通过（`13.23s`）。
3. **沙盒隔离真实邮箱复测**：连接 `913223599@qq.com` 隔离只读扫描校验实得 `raw_total=17, unique_total=13, dedup_removed=4, existing_count=12, non_sequencing_count=1, new_count=0`，并确认 `1011709710` 已准确识别为 `non_sequencing (legacy_dir_exists=True)`。


