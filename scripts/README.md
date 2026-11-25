# Scripts 目录索引与维护规范

本目录承载 NCBI Bio-Station 的环境自愈、生信离线批处理、模型评测与自动化运维脚本。为兼容启动批处理（`RUN_DEV_ELECTRON.bat`）、运行时自愈提示及自动化测试路径契约，核心入口脚本保持顶层相对路径。

## 1. 启动引导与运维自愈（Ops & Runtime）

| 脚本 | 职责说明 |
| :--- | :--- |
| `verify_all.ps1` | 全栈一键质量门禁（Electron 语法、Ruff、Pytest、Vitest、Vue/TS 构建、Legacy Scan） |
| `bootstrap_runtime.ps1` | 启动期 Python/Node 运行时与缓存环境探测引导 |
| `verify_and_install_deps.py` | 校验并补齐 `requirements.txt` 核心 Python 依赖 |
| `check_npm_deps.js` | 校验根、`electron-shell`、`src/web-next` 的 `node_modules` 完整性 |
| `ensure_electron.ps1` | 校验与恢复 Electron 宿主二进制完整性 |
| `repair_integrity.ps1` | Windows 低完整性标记自愈修复 |
| `download_externals.ps1` | 外部生信二进制工具下载与校验 |
| `setup_assembly_env.sh` | WSL 基因组组装与 Prokka/Prodigal 环境配置 |
| `setup_pharokka.sh` | WSL Pharokka 噬菌体注释环境配置 |
| `setup_phold.sh` / `fix_phold_gpu_wsl.ps1` | WSL Phold + GPU 推理环境配置与修复 |
| `install_phage_tools.sh` / `fix_minced.sh` | 噬菌体注释工具链补充与 MinCED 修复 |
| `install_mail_poll_task.ps1` | Windows 定时邮件轮询计划任务注册 |
| `remote_ops_agent.py` / `remote_ops_client.py` | 远程运维协助端与客户端 |
| `generate_project_tree.ps1` | 导出项目目录树结构 |

## 2. 生信离线流水线与报告导出（Pipelines & Reporting）

| 脚本 | 职责说明 |
| :--- | :--- |
| `build_annotation_report.py` / `docx_citations.py` | 基因组注释 Word 报告生成与引文附录组装 |
| `build_t5_comparative_report.py` | 比较基因组对比报告生成 |
| `build_cdd_rps_index.py` / `build_downloaded_dbs.py` / `build_ptf_pfam_db.py` | 本地 CDD / RPS / Pfam / BLAST 索引库构建 |
| `run_protein_fasta_search.py` | 蛋白 FASTA 分片并行 BLAST 相似度检索 |
| `run_16s_blast.py` / `run_16s_blast_new_orders.py` / `export_gui_format_new_orders.py` / `translate_and_export.py` | 生工 16S 订单批量比对、翻译与导出脚本 |
| `predict_unified.py` | 前噬菌体统一模型生产推理 CLI |
| `heal_assembly_metrics.py` / `refresh_persisted_categories.py` / `refresh_task_results.py` | 历史任务指标与分类持久化刷新工具 |
| `process_user_downloads.py` / `vibrant_wrapper.sh` / `virsorter_wrapper.sh` | 下载归档与外部病毒识别工具包装脚本 |
| `自动化流程文档.md` / `citations_ops.json` | 自动化运维流程说明与引文运维数据 |

## 3. 模型训练、基准评估与验证（ML & Benchmarks）

| 脚本 | 职责说明 |
| :--- | :--- |
| `build_v4_3_dataset.py` / `fetch_v4_3_external_tailocins.py` / `validation_datasets.py` | 前噬菌体与尾丝数据集构建与验证集管理 |
| `train_v4_3_unified.py` / `train_unified_judge.py` / `finetune_stage1_2_v4_3.py` | Stage 1.2 / 统一判定器训练与微调 |
| `run_p0_distill_ablation.py` / `run_orf_judge_ablation.py` / `run_suite_e_blind.py` | 蒸馏消融实验与 Suite E 盲测评估 |
| `benchmark_fragmented_contigs.py` / `benchmark_phage_structure.py` / `benchmark_phold_3d_rescue.py` / `benchmark_project_capabilities.py` | 碎片化拼接、结构预测、Phold 3D 补救与全平台基准评测 |
| `sensitivity_phage_structure.py` / `validate_external_phage_structure.py` / `build_local_structure_corpus_cache.py` | 噬菌体结构预测敏感性与外部验证 |
| `audit_full_database_terms.py` / `deep_classification_audit.py` / `verify_consensus_algorithm.py` / `verify_label_display_mode.js` | 词库审计、共识分类核验与标签展示验证 |

## 使用约定

- 禁止将临时调试截图（`*.png`）、明文账号密码或个人绝对路径提交至本目录；
- 所有 Python 脚本必须显式使用 `encoding="utf-8"` 读写文本文件与子进程输出，并在并发计算时通过 `src.utils.resource_guard` 保留系统核心。
