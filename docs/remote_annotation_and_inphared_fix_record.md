# 组装历史导入与 INPHARED 索引动态发现修复留档

## 1. 远程报错分析与本地核对

1. **`AnnotationSetup.vue:424 TypeError: t.created_at?.slice is not a function`（本地与远程均存在）**
   - `GET /api/assembly/history` 返回的任务对象中 `created_at` 为浮点型 Unix 秒级时间戳（如 `1795593884.8658392`），主键字段为 `id`（如 `Assembly_1795593884862`），并未提供 `task_id` 与 `fasta_path`。
   - `AnnotationSetup.vue`、`PhageDiscoverySetup.vue` 与 `StructureHistory.vue` 直接对 `created_at` 调用 `.slice()`，且前两者下拉框绑定的 `t.task_id` 与 `final_assembly.fasta` 回退路径与真实接口不匹配。

2. **`POST /api/phylo/phage/ani-screen 400 (Bad Request)`**
   - 远程接口实际返回：`未找到 INPHARED Mash 索引文件: D:\NCBI blast\database\pharokka_db\9Aug2025_genomes.fa.msh`。
   - `src/phylo/engines/ani/inphared_index.py` 原先硬编码 `database/pharokka_db/9Aug2025_data.tsv` 与 `9Aug2025_genomes.fa.msh`，未调用 `ToolConfig.get_db_dir("pharokka_db")` 也不兼容其他日期的 `*_data.tsv` / `*_genomes.fa.msh`；同时远程机因 `.gitignore` 排除了 `database/` 与 `*.msh` 可能未同步这两个索引文件。

---

## 2. 已实施修复

1. **`src/backend/routes/assembly.py`**：
   - `get_assembly_history()` 为每条记录补齐向后兼容的 `task_id`，并在已完成任务中通过 `find_assembly_fasta()` 注入真实 `fasta_path`、`assembly_fasta` 与 `contigs_path`。
2. **`src/phylo/engines/ani/inphared_index.py`**：
   - 新增 `_resolve_inphared_paths()`，通过 `ToolConfig.get_db_dir("pharokka_db")` 兼容单/双层目录，自动发现成对的 `*_data.tsv` 与 `*_genomes.fa.msh`（跳过 macOS `._*` 隐藏文件，优先 `9Aug2025` 或最新文件）。
3. **前端组件时间与字段兼容性修复**：
   - `src/web-next/src/views/Analysis/modules/annotation/components/AnnotationSetup.vue`
   - `src/web-next/src/views/Analysis/modules/phage_discovery/components/PhageDiscoverySetup.vue`
   - `src/web-next/src/views/Analysis/modules/phage_structure/components/StructureHistory.vue`
   - 统一兼容秒级/毫秒级 Unix 时间戳与字符串格式、兼容 `t.task_id || t.id`、支持 `/api/assembly/result/{id}` 兜底。
4. **测试补充**：
   - `tests/phylo/test_phage_ani_and_ref.py` 新增 `test_inphared_index_auto_discovers_dated_files`。

---

## 3. 验证记录（2026-11-25）

- Python 静态检查：`pyrefly` 0 errors / 0 warnings，`ruff` All checks passed，`py_compile` 退出码 0。
- 后端单测：`tests/phylo/test_phage_ani_and_ref.py` 全部 PASSED。
- 前端检查：`vue-tsc --noEmit` 退出码 0，`vitest run` 全部 PASSED。
