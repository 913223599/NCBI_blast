# 在线更新 `git stash / pull` 未合并冲突死锁根因修复留档

## 1. 远程现场问题与根因分析

### 1.1 现场现象
远程主机（`CDDC-20261103OL`，当前提交 `e73e7b2`）在应用内“软件在线更新”点击“立即从 GitHub 拉取更新”时失败，日志输出：
- `[步骤 1/4] 检测到工作区有本地修改，正在自动暂存 (git stash)...`
- `暂存修改失败，将尝试直接合并: error: could not write index`
- `[步骤 2/4] 正在从 origin/master 拉取更新代码...`
- `error: Pulling is not possible because you have unmerged files.`

### 1.2 三重代码与状态根因
1. **误弹历史旧 `stash`（[git_updater.py](../src/backend/utils/git_updater.py)）**：此前仅依据 `git stash push` 返回码为 `0` 就将 `stashed` 置为 `True`。当工作区仅存在未追踪文件时，`git stash push` 返回 `0` 并输出 `No local changes to save`；随后步骤 3 会误把仓库中**历史遗留的旧 `stash`** `pop` 出来，与当前代码发生合并冲突并把工作区留在 `unmerged files` 死锁状态。
2. **`stash pop` 与 `pull --rebase` 冲突后未自清理**：
   - `git stash pop` 发生冲突后，未调用 `git reset --merge` 将索引恢复到安全态，导致后续所有 `git stash` / `git pull` 均因 `unmerged files` 与 `could not write index` 永久阻断；
   - `git pull --rebase` 冲突失败后也未执行 `git rebase --abort`。
3. **缺少前置冲突检测与 UI 自愈通道**：`get_git_info()` 与 `pull_remote_update()` 此前未检测 `unmerged files` 和进行中的 `rebase/merge` 状态，用户无法在前端得知具体冲突文件并一键清理恢复。

---

## 2. 本次修复内容

1. **后端更新引擎加固**（[src/backend/utils/git_updater.py](../src/backend/utils/git_updater.py)）：
   - 新增 `_resolve_git_dir`、`_detect_in_progress_op`、`_get_unmerged_files`、`_get_stash_top_ref`、`_abort_in_progress_op`、`_backup_and_reset_conflicts` 等单一职责辅助函数。
   - `get_git_info()` 新增返回 `has_conflicts`、`conflict_files`、`in_progress_op`。
   - `pull_remote_update()` 升级：
     - **精确判定新建 stash**：比对 `stash_before` 与 `stash_after`（及 `No local changes to save`），彻底杜绝误 `pop` 历史旧 stash；`git stash push` 失败时直接终止并报错，不再带病执行 `pull`。
     - **自动中止半途变基并清场**：`git pull --rebase` 失败后自动 `_abort_in_progress_op`；`git stash pop` 冲突时立即 `git reset --merge` 恢复已拉取的干净版本（本地修改仍安全保留在 `git stash` 中）。
     - **前置冲突检测与备份自愈（`resolve_conflicts=True`）**：存在未合并文件或半途操作时默认明确列出冲突文件并拦截；开启 `resolve_conflicts=True` 后自动将冲突文件按原相对路径备份至 `results/git_update_backups/<timestamp>/`，执行 abort 与 `reset --merge`（必要时对残留冲突路径 `reset HEAD` + `checkout -f HEAD`），随后重新拉取远端更新。
2. **更新接口与前端面板联动**（[src/backend/routes/settings.py](../src/backend/routes/settings.py)、[src/web-next/src/components/settings/UpdatePanel.vue](../src/web-next/src/components/settings/UpdatePanel.vue)）：
   - `PullUpdateRequest` 增加 `resolve_conflicts: bool = False` 透传给 `pull_remote_update`；
   - 前端面板展示未合并冲突数量与文件列表，并提供“备份冲突文件并清理后更新”一键恢复按钮。

---

## 3. 测试与校验结果

- 新增真实裸仓库 + 克隆仓库测试集 [tests/test_git_updater.py](../tests/test_git_updater.py)（4 项核心场景）：
  - 仅含未追踪文件时不误 `pop` 历史旧 stash；
  - `stash pop` 冲突后自动还原干净工作区并保留 stash，不死锁；
  - 前置 `unmerged files` 冲突检测、`results/git_update_backups/` 备份清理并更新至最新版；
  - 本地未推送提交触发 `rebase` 冲突后自动 `rebase --abort` 还原。
- `.venv\Scripts\python.exe -m pytest tests/test_git_updater.py -q`：**4 passed in 15.27s**
- `python -m ruff check src/backend/utils/git_updater.py src/backend/routes/settings.py tests/test_git_updater.py`：**All checks passed!**
- `.venv\Scripts\python.exe -m py_compile ...`：通过
- `npx vue-tsc --noEmit`：**0 errors**；`npx vitest run`：**13 test files, 59 tests passed**

---

## 4. 远程计算机 (`26.78.5.143`) 立即脱困执行指令

由于远程主机当前运行的是旧版更新脚本（`e73e7b2`），在拉取新版代码前需先在远程 `D:\NCBI blast` 执行一次一次性备份与索引重置（不会覆盖个人工作区未追踪数据文件），之后再点界面更新或 `git pull` 即可恢复顺畅更新：

```powershell
cd "D:\NCBI blast"
# 1. 查看冲突文件列表与正在进行的操作（只读确认）
git status
git diff --name-only --diff-filter=U

# 2. 若有重要本地改动先手动备份上述冲突文件，然后中止未完成变基/合并并清理未合并索引
git rebase --abort 2>$null
git merge --abort 2>$null
git reset --merge

# 3. 清理完毕后正常拉取最新代码，再重启后端/应用生效
git pull --rebase origin master
```
