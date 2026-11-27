<script setup lang="ts">
/**
 * UpdatePanel.vue - 软件在线更新面板
 * 
 * 单一职责：
 * 1. 展示当前 Git 版本、分支、Commit 状态；
 * 2. 调度后端 API 执行远程差异比对与代码拉取；
 * 3. 展现待更新提交日志与终端执行流；
 * 4. 协同 Electron 主进程安全触发应用自动重启。
 */
import { ref, computed, onMounted } from 'vue'
import { apiGet, apiPost } from '../../bridge/electron-bridge'
import { useAppStore } from '../../stores/app'
import { createLogger } from '../../utils/logger'
const logger = createLogger('UpdatePanel')

const appStore = useAppStore()

interface GitInfo {
  is_git_repo: boolean
  branch: string
  commit_hash: string
  commit_full: string
  commit_message: string
  commit_date: string
  remote_url: string
  app_version: string
  has_uncommitted_changes: boolean
  has_conflicts?: boolean
  conflict_files?: string[]
  in_progress_op?: string | null
  error?: string
}

interface CommitItem {
  hash: string
  message: string
  author: string
  date: string
}

// 状态管理
const currentInfo = ref<GitInfo | null>(null)
const isLoadingInfo = ref(false)

const isChecking = ref(false)
const checkResult = ref<{
  checked: boolean
  hasUpdate: boolean
  behindCount: number
  remoteHead: string
  commits: CommitItem[]
  error: string | null
}>({
  checked: false,
  hasUpdate: false,
  behindCount: 0,
  remoteHead: '',
  commits: [],
  error: null
})

const isPulling = ref(false)
const autoStash = ref(true)
const pullLogs = ref<string[]>([])
const pullError = ref<string | null>(null)
const pullSuccess = ref(false)
const conflictFiles = ref<string[]>([])
const hasConflicts = computed(
  () => Boolean(currentInfo.value?.has_conflicts || conflictFiles.value.length > 0)
)

// 重启提示对话框
const showRestartModal = ref(false)
const isRelaunching = ref(false)

/** 获取当前本地 Git 状态 */
async function loadStatus() {
  isLoadingInfo.value = true
  try {
    const res = await apiGet('/api/settings/update/status')
    currentInfo.value = res
    conflictFiles.value = Array.isArray(res?.conflict_files) ? res.conflict_files : []
  } catch (err) {
    logger.error('获取更新状态异常:', err)
  } finally {
    isLoadingInfo.value = false
  }
}

/** 检查 GitHub 远程是否有新提交 */
async function handleCheckUpdate() {
  if (isChecking.value || isPulling.value) return
  isChecking.value = true
  checkResult.value.error = null

  try {
    const res = await apiGet('/api/settings/update/check')
    if (res && !res.error) {
      checkResult.value = {
        checked: true,
        hasUpdate: !!res.has_update,
        behindCount: res.behind_count || 0,
        remoteHead: res.remote_head || '',
        commits: res.commits || [],
        error: null
      }
      if (res.current_info) {
        currentInfo.value = res.current_info
      }
      if (res.has_update) {
        appStore.showNotification(`检测到 ${res.behind_count} 个新更新提交`, 'info')
      } else {
        appStore.showNotification('当前代码已是最新版本', 'success')
      }
    } else {
      checkResult.value = {
        checked: true,
        hasUpdate: false,
        behindCount: 0,
        remoteHead: '',
        commits: [],
        error: res?.error || '连接 GitHub 失败，请检查网络或代理'
      }
      appStore.showNotification(checkResult.value.error || '连接 GitHub 失败，请检查网络或代理', 'warning')
    }
  } catch (err: unknown) {
    checkResult.value.checked = true
    checkResult.value.error = err instanceof Error ? err.message : String(err)
    appStore.showNotification('检查更新发生异常', 'error')
  } finally {
    isChecking.value = false
  }
}

/** 拉取更新代码 */
async function handlePullUpdate(resolveConflicts = false) {
  if (isPulling.value) return
  isPulling.value = true
  pullLogs.value = [resolveConflicts ? '正在备份冲突文件并重置索引后更新...' : '正在启动更新任务...']
  pullError.value = null
  pullSuccess.value = false

  try {
    const res = await apiPost('/api/settings/update/pull', {
      auto_stash: autoStash.value,
      resolve_conflicts: resolveConflicts
    })

    if (res && res.logs && Array.isArray(res.logs)) {
      pullLogs.value = res.logs
    }

    if (Array.isArray(res?.conflict_files)) {
      conflictFiles.value = res.conflict_files
    }

    if (res && res.success) {
      conflictFiles.value = []
      pullSuccess.value = true
      showRestartModal.value = true
      appStore.showNotification('代码已成功更新！请重启应用以生效。', 'success')
      await loadStatus()
    } else {
      pullError.value = res?.message || '拉取更新失败'
      if (res?.has_conflicts) {
        await loadStatus()
      }
      appStore.showNotification(pullError.value || '更新失败', 'error')
    }
  } catch (err: unknown) {
    pullError.value = err instanceof Error ? err.message : String(err)
    pullLogs.value.push(`[异常] ${pullError.value}`)
    appStore.showNotification('执行更新时发生网络或系统错误', 'error')
  } finally {
    isPulling.value = false
  }
}

/** 触发应用重启 */
async function handleRelaunchApp() {
  isRelaunching.value = true
  appStore.showNotification('正在安全重启应用...', 'info')

  try {
    if (window.electronAPI?.relaunchApp) {
      await window.electronAPI.relaunchApp()
    } else {
      // 浏览器环境提示并自动刷新
      setTimeout(() => {
        window.location.reload()
      }, 1200)
    }
  } catch (err) {
    logger.error('重启应用异常:', err)
    isRelaunching.value = false
    appStore.showNotification('自动重启受阻，请手动关闭并重新打开程序', 'warning')
  }
}

function openRemoteUrl() {
  const url = currentInfo.value?.remote_url
  if (!url) return
  const cleanUrl = url.replace(/\.git$/, '')
  if (window.electronAPI?.openExternal) {
    window.electronAPI.openExternal(cleanUrl)
  } else {
    window.open(cleanUrl, '_blank', 'noopener,noreferrer')
  }
}

onMounted(() => {
  loadStatus()
})
</script>

<template>
  <div class="panel update-panel">
    <!-- 面板头部 -->
    <header class="panel-header">
      <div class="header-title-row">
        <div class="icon-wrap">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 12a9 9 0 0 1-9 9m9-9a9 9 0 0 0-9-9m9 9H3m9 9a9 9 0 0 1-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9" />
          </svg>
        </div>
        <div>
          <h2>软件在线更新</h2>
          <p class="desc">直接同步 GitHub 官方仓库的最新发布与算法修正，支持安全暂存、分支比对与热重启。</p>
        </div>
      </div>
    </header>

    <!-- 1. 当前版本卡片 -->
    <div class="p-card current-version-card">
      <div class="card-section-title">
        <span class="dot-indicator active"></span>
        <h3>当前运行版本与环境</h3>
      </div>

      <div class="meta-grid">
        <div class="meta-item">
          <span class="meta-label">软件发布版本</span>
          <span class="meta-val highlight">{{ currentInfo?.app_version || '2.1.0' }}</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">Git 分支</span>
          <span class="meta-val branch-val">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" class="meta-icon">
              <line x1="6" y1="3" x2="6" y2="15"></line>
              <circle cx="18" cy="6" r="3"></circle>
              <circle cx="6" cy="18" r="3"></circle>
              <path d="M18 9a9 9 0 0 1-9 9"></path>
            </svg>
            {{ currentInfo?.branch || 'master' }}
          </span>
        </div>
        <div class="meta-item">
          <span class="meta-label">本地 Commit</span>
          <span class="meta-val commit-val">
            <code>{{ currentInfo?.commit_hash || '未知' }}</code>
          </span>
        </div>
        <div class="meta-item">
          <span class="meta-label">最后更新时间</span>
          <span class="meta-val text-muted">{{ currentInfo?.commit_date?.slice(0, 19) || '无记录' }}</span>
        </div>
      </div>

      <div class="sub-commit-info" v-if="currentInfo?.commit_message">
        <span class="sub-label">最新提交说明:</span>
        <span class="sub-msg">{{ currentInfo.commit_message }}</span>
      </div>

      <!-- 远程仓库与工作区状态 -->
      <div class="repo-strip">
        <div class="repo-url-box" @click="openRemoteUrl" title="点击在浏览器中查看远程代码仓库">
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22"></path>
          </svg>
          <span class="repo-url">{{ currentInfo?.remote_url || 'https://github.com/913223599/NCBI_blast.git' }}</span>
          <span class="link-tag">打开 GitHub</span>
        </div>

        <div class="workspace-tag" :class="{ 'has-conflict': hasConflicts, 'has-mod': !hasConflicts && currentInfo?.has_uncommitted_changes }">
          <span class="ws-dot"></span>
          <span v-if="hasConflicts">检测到 {{ conflictFiles.length || currentInfo?.conflict_files?.length || 1 }} 个未合并冲突文件</span>
          <span v-else>{{ currentInfo?.has_uncommitted_changes ? '工作区有本地修改 (已支持自动暂存保护)' : '本地工作区干净整洁' }}</span>
        </div>
      </div>

      <!-- 冲突检测与一键备份自愈提示 -->
      <div v-if="hasConflicts" class="banner banner-error mt-16 conflict-banner">
        <div class="banner-body">
          <h4>检测到未完成的 Git 合并或冲突文件</h4>
          <p class="banner-desc">
            存在未合并索引时 `git stash` 与 `git pull` 会被拒绝；可先自动备份冲突文件至 `results/git_update_backups/` 并重置索引后再完成拉取。
          </p>
          <ul v-if="(conflictFiles.length || currentInfo?.conflict_files?.length)" class="conflict-file-list">
            <li v-for="cf in (conflictFiles.length ? conflictFiles : (currentInfo?.conflict_files || []))" :key="cf">
              <code>{{ cf }}</code>
            </li>
          </ul>
          <div class="conflict-actions">
            <button
              type="button"
              class="p-btn btn-recover-conflict"
              :disabled="isPulling"
              @click="() => handlePullUpdate(true)"
            >
              <span v-if="isPulling" class="spinner white"></span>
              <span>{{ isPulling ? '正在备份清理并更新...' : '备份冲突文件并清理后更新' }}</span>
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 2. 检查更新卡片 -->
    <div class="p-card action-card">
      <div class="card-header-flex">
        <div>
          <h3>版本同步与检查</h3>
          <p class="desc-sm">向 GitHub origin/master 发起查询，检测是否有未经拉取的特性提交。</p>
        </div>
        <button
          type="button"
          class="p-btn p-btn-primary btn-check"
          :disabled="isChecking || isPulling"
          @click="handleCheckUpdate"
        >
          <svg v-if="!isChecking" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" class="btn-svg">
            <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67" />
          </svg>
          <span v-else class="spinner"></span>
          <span>{{ isChecking ? '正在连接 GitHub...' : '检查最新版本' }}</span>
        </button>
      </div>

      <!-- 状态指示区 -->
      <div v-if="checkResult.checked" class="check-feedback mt-16">
        <!-- A. 发现新版本 -->
        <div v-if="checkResult.hasUpdate" class="banner banner-update">
          <div class="banner-icon-side">
            <div class="badge-count">{{ checkResult.behindCount }}</div>
          </div>
          <div class="banner-body">
            <h4>发现新版本发布！</h4>
            <p class="banner-desc">
              远程主分支领先本地 <strong>{{ checkResult.behindCount }}</strong> 个提交 (最新 Hash: <code>{{ checkResult.remoteHead }}</code>)。
            </p>
          </div>
        </div>

        <!-- B. 已经是最新 -->
        <div v-else-if="!checkResult.error" class="banner banner-latest">
          <div class="banner-icon-success">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2.5">
              <polyline points="20 6 9 17 4 12"></polyline>
            </svg>
          </div>
          <div class="banner-body">
            <h4>当前已是最新版本</h4>
            <p class="banner-desc">已与 GitHub origin/master 远端保持严格同步，无需执行拉取。</p>
          </div>
        </div>

        <!-- C. 检查异常报错 -->
        <div v-else class="banner banner-error">
          <div class="banner-body">
            <h4>检查更新失败</h4>
            <p class="banner-desc text-danger">{{ checkResult.error }}</p>
            <p class="banner-tip">提示：GitHub 访问可能受网络防火墙或代理影响，请确认网络畅通后重试。</p>
          </div>
        </div>
      </div>

      <!-- 待更新 Commit 列表预览 -->
      <div v-if="checkResult.hasUpdate && checkResult.commits.length > 0" class="commits-preview-box mt-16">
        <div class="preview-header">
          <span>待更新提交摘要 (更新日志)</span>
          <span class="count-txt">共 {{ checkResult.commits.length }} 条记录</span>
        </div>
        <div class="commits-list">
          <div v-for="c in checkResult.commits" :key="c.hash" class="commit-row">
            <code class="c-hash">{{ c.hash }}</code>
            <span class="c-msg">{{ c.message }}</span>
            <span class="c-author">{{ c.author }}</span>
            <span class="c-date">{{ c.date }}</span>
          </div>
        </div>
      </div>

      <!-- 执行拉取更新按钮 -->
      <div v-if="checkResult.hasUpdate" class="pull-action-deck mt-24">
        <div class="deck-left">
          <label class="checkbox-label">
            <input type="checkbox" v-model="autoStash" :disabled="isPulling" />
            <span>自动暂存本地修改 (Stash 保护，拉取完成后自动恢复)</span>
          </label>
        </div>
        <div class="deck-right">
          <button
            type="button"
            class="p-btn btn-pull-now"
            :disabled="isPulling"
            @click="() => handlePullUpdate(false)"
          >
            <span v-if="isPulling" class="spinner white"></span>
            <svg v-else viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="12" y1="5" x2="12" y2="19"></line>
              <polyline points="19 12 12 19 5 12"></polyline>
            </svg>
            <span>{{ isPulling ? '正在拉取代码与合并...' : '立即从 GitHub 拉取更新' }}</span>
          </button>
        </div>
      </div>
    </div>

    <!-- 3. 更新日志输出控制台 -->
    <div v-if="pullLogs.length > 0" class="p-card console-card">
      <div class="console-header">
        <div class="console-title">
          <span class="term-dots"></span>
          <span>执行日志控制台</span>
        </div>
        <span v-if="pullSuccess" class="tag-success">更新完成</span>
        <span v-else-if="pullError" class="tag-error">更新中断</span>
        <span v-else class="tag-running">运行中...</span>
      </div>
      <div class="console-body">
        <div v-for="(log, idx) in pullLogs" :key="idx" class="console-line">
          {{ log }}
        </div>
      </div>
    </div>

    <!-- 4. 重启提示对话框 (Modal) -->
    <div v-if="showRestartModal" class="modal-overlay">
      <div class="modal-container">
        <div class="modal-header">
          <div class="modal-icon-success">
            <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2.5">
              <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
              <polyline points="22 4 12 14.01 9 11.01"></polyline>
            </svg>
          </div>
          <div class="modal-title-box">
            <h3>代码更新已顺利就绪！</h3>
            <p>最新代码与算法逻辑已完整落盘并合并。</p>
          </div>
        </div>

        <div class="modal-body">
          <p class="modal-p">
            为了确保新的前端界面与 Python 业务计算进程加载最新特性，建议<strong>立即重启应用</strong>。
          </p>
          <div class="alert-box">
            <span>应用将平稳关闭当前后台 Sidecar 进程，并在几秒钟内自动唤醒重新拉起。</span>
          </div>
        </div>

        <div class="modal-footer">
          <button type="button" class="p-btn p-btn-outline" @click="showRestartModal = false" :disabled="isRelaunching">
            稍后手动重启
          </button>
          <button type="button" class="p-btn p-btn-primary btn-relaunch" @click="handleRelaunchApp" :disabled="isRelaunching">
            <span v-if="isRelaunching" class="spinner white"></span>
            <span>{{ isRelaunching ? '正在关闭并唤醒...' : '立即重启应用' }}</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped src="./updatePanel.css"></style>
