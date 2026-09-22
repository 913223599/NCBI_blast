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
import { ref, onMounted } from 'vue'
import { apiGet, apiPost } from '../../bridge/electron-bridge'
import { useAppStore } from '../../stores/app'

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

// 重启提示对话框
const showRestartModal = ref(false)
const isRelaunching = ref(false)

/** 获取当前本地 Git 状态 */
async function loadStatus() {
  isLoadingInfo.value = true
  try {
    const res = await apiGet('/api/settings/update/status')
    if (res && res.is_git_repo) {
      currentInfo.value = res
    } else {
      currentInfo.value = res
    }
  } catch (err) {
    console.error('获取更新状态异常:', err)
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
  } catch (err: any) {
    checkResult.value.checked = true
    checkResult.value.error = String(err?.message || err)
    appStore.showNotification('检查更新发生异常', 'error')
  } finally {
    isChecking.value = false
  }
}

/** 拉取更新代码 */
async function handlePullUpdate() {
  if (isPulling.value) return
  isPulling.value = true
  pullLogs.value = ['正在启动更新任务...']
  pullError.value = null
  pullSuccess.value = false

  try {
    const res = await apiPost('/api/settings/update/pull', {
      auto_stash: autoStash.value
    })

    if (res && res.logs && Array.isArray(res.logs)) {
      pullLogs.value = res.logs
    }

    if (res && res.success) {
      pullSuccess.value = true
      showRestartModal.value = true
      appStore.showNotification('代码已成功更新！请重启应用以生效。', 'success')
      await loadStatus()
    } else {
      pullError.value = res?.message || '拉取更新失败'
      appStore.showNotification(pullError.value || '更新失败', 'error')
    }
  } catch (err: any) {
    pullError.value = String(err?.message || err)
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
    if ((window as any).electronAPI?.relaunchApp) {
      await (window as any).electronAPI.relaunchApp()
    } else {
      // 浏览器环境提示并自动刷新
      setTimeout(() => {
        window.location.reload()
      }, 1200)
    }
  } catch (err) {
    console.error('重启应用异常:', err)
    isRelaunching.value = false
    appStore.showNotification('自动重启受阻，请手动关闭并重新打开程序', 'warning')
  }
}

function openRemoteUrl() {
  const url = currentInfo.value?.remote_url
  if (!url) return
  const cleanUrl = url.replace(/\.git$/, '')
  if ((window as any).electronAPI?.openExternal) {
    (window as any).electronAPI.openExternal(cleanUrl)
  } else {
    window.open(cleanUrl, '_blank')
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

        <div class="workspace-tag" :class="{ 'has-mod': currentInfo?.has_uncommitted_changes }">
          <span class="ws-dot"></span>
          <span>{{ currentInfo?.has_uncommitted_changes ? '工作区有本地修改 (已支持自动暂存保护)' : '本地工作区干净整洁' }}</span>
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
            class="p-btn btn-pull-now"
            :disabled="isPulling"
            @click="handlePullUpdate"
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
          <button class="p-btn p-btn-outline" @click="showRestartModal = false" :disabled="isRelaunching">
            稍后手动重启
          </button>
          <button class="p-btn p-btn-primary btn-relaunch" @click="handleRelaunchApp" :disabled="isRelaunching">
            <span v-if="isRelaunching" class="spinner white"></span>
            <span>{{ isRelaunching ? '正在关闭并唤醒...' : '立即重启应用' }}</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.update-panel {
  padding: 24px 32px;
  max-width: 1040px;
}

.panel-header {
  margin-bottom: 24px;
}

.header-title-row {
  display: flex;
  align-items: center;
  gap: 14px;
}

.icon-wrap {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: #eff6ff;
  color: #2563eb;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid #bfdbfe;
}

.panel-header h2 {
  font-size: 1.35rem;
  font-weight: 700;
  color: #0f172a;
  margin: 0;
}

.panel-header .desc {
  font-size: 0.85rem;
  color: #64748b;
  margin: 4px 0 0;
}

.p-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 20px 24px;
  margin-bottom: 20px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.card-section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}

.dot-indicator {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #10b981;
}

.card-section-title h3,
.card-header-flex h3 {
  font-size: 1rem;
  font-weight: 700;
  color: #1e293b;
  margin: 0;
}

.desc-sm {
  font-size: 0.82rem;
  color: #64748b;
  margin: 4px 0 0;
}

/* 元数据表格网格 */
.meta-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  background: #f8fafc;
  padding: 16px;
  border-radius: 10px;
  border: 1px solid #edf2f7;
}

.meta-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.meta-label {
  font-size: 0.75rem;
  color: #94a3b8;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.meta-val {
  font-size: 0.95rem;
  color: #1e293b;
  font-weight: 600;
}

.meta-val.highlight {
  color: #2563eb;
  font-size: 1.05rem;
}

.branch-val {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #0d9488;
}

.commit-val code {
  background: #e2e8f0;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.85rem;
  color: #0f172a;
}

.sub-commit-info {
  margin-top: 14px;
  padding: 10px 14px;
  background: #f1f5f9;
  border-radius: 8px;
  font-size: 0.85rem;
  display: flex;
  gap: 8px;
}

.sub-label {
  color: #64748b;
  font-weight: 600;
  flex-shrink: 0;
}

.sub-msg {
  color: #334155;
  word-break: break-all;
}

/* 仓库与状态条 */
.repo-strip {
  margin-top: 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.repo-url-box {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.82rem;
  color: #475569;
  cursor: pointer;
  padding: 6px 12px;
  border-radius: 6px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  transition: all 0.15s;
}

.repo-url-box:hover {
  border-color: #93c5fd;
  color: #1d4ed8;
  background: #eff6ff;
}

.link-tag {
  font-size: 0.72rem;
  background: #e2e8f0;
  padding: 1px 6px;
  border-radius: 4px;
  color: #64748b;
}

.workspace-tag {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.8rem;
  color: #16a34a;
}

.workspace-tag .ws-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #16a34a;
}

.workspace-tag.has-mod {
  color: #d97706;
}

.workspace-tag.has-mod .ws-dot {
  background: #d97706;
}

/* 操作卡片 */
.card-header-flex {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.btn-check {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  font-weight: 600;
  border-radius: 8px;
}

/* 横幅提示 */
.banner {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 16px;
  border-radius: 10px;
  border: 1px solid transparent;
}

.banner-update {
  background: #eff6ff;
  border-color: #bfdbfe;
}

.badge-count {
  background: #2563eb;
  color: white;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 1rem;
}

.banner-latest {
  background: #f0fdf4;
  border-color: #bbf7d0;
}

.banner-icon-success {
  color: #16a34a;
  padding-top: 2px;
}

.banner-error {
  background: #fef2f2;
  border-color: #fecaca;
}

.banner h4 {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 700;
  color: #0f172a;
}

.banner-desc {
  margin: 4px 0 0;
  font-size: 0.85rem;
  color: #475569;
}

.banner-tip {
  margin: 6px 0 0;
  font-size: 0.78rem;
  color: #94a3b8;
}

/* 提交预览 */
.commits-preview-box {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  overflow: hidden;
}

.preview-header {
  display: flex;
  justify-content: space-between;
  padding: 10px 16px;
  background: #f1f5f9;
  font-size: 0.8rem;
  font-weight: 700;
  color: #475569;
}

.count-txt {
  color: #64748b;
  font-weight: 500;
}

.commits-list {
  max-height: 180px;
  overflow-y: auto;
}

.commit-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 16px;
  font-size: 0.82rem;
  border-bottom: 1px solid #f1f5f9;
}

.commit-row:last-child {
  border-bottom: none;
}

.c-hash {
  background: #e2e8f0;
  padding: 2px 5px;
  border-radius: 4px;
  color: #0f172a;
  font-size: 0.78rem;
  flex-shrink: 0;
}

.c-msg {
  flex: 1;
  color: #334155;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.c-author {
  color: #64748b;
  font-size: 0.75rem;
  flex-shrink: 0;
}

.c-date {
  color: #94a3b8;
  font-size: 0.75rem;
  flex-shrink: 0;
}

/* 拉取操作条 */
.pull-action-deck {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-top: 16px;
  border-top: 1px dashed #e2e8f0;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.85rem;
  color: #475569;
  cursor: pointer;
}

.btn-pull-now {
  background: #16a34a;
  color: white;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 24px;
  font-weight: 700;
  border-radius: 8px;
  border: none;
  cursor: pointer;
  transition: background 0.15s;
}

.btn-pull-now:hover:not(:disabled) {
  background: #15803d;
}

.btn-pull-now:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* 控制台卡片 */
.console-card {
  background: #0f172a;
  border: 1px solid #1e293b;
  color: #e2e8f0;
  padding: 16px;
}

.console-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.console-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.82rem;
  font-weight: 700;
  color: #94a3b8;
}

.term-dots {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #38bdf8;
  box-shadow: 14px 0 0 #f59e0b, 28px 0 0 #10b981;
  margin-right: 24px;
}

.tag-success {
  background: #166534;
  color: #bbf7d0;
  font-size: 0.72rem;
  padding: 2px 8px;
  border-radius: 4px;
}

.tag-error {
  background: #991b1b;
  color: #fecaca;
  font-size: 0.72rem;
  padding: 2px 8px;
  border-radius: 4px;
}

.tag-running {
  background: #1e3a8a;
  color: #bfdbfe;
  font-size: 0.72rem;
  padding: 2px 8px;
  border-radius: 4px;
}

.console-body {
  background: #020617;
  padding: 12px;
  border-radius: 6px;
  font-family: Consolas, Monaco, monospace;
  font-size: 0.78rem;
  max-height: 160px;
  overflow-y: auto;
  line-height: 1.6;
}

.console-line {
  white-space: pre-wrap;
  word-break: break-all;
}

/* 重启弹窗 (Modal) */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(15, 23, 42, 0.65);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-container {
  background: white;
  width: 90%;
  max-width: 480px;
  border-radius: 16px;
  padding: 28px;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.2);
}

.modal-header {
  display: flex;
  align-items: center;
  gap: 16px;
}

.modal-icon-success {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  background: #dcfce7;
  color: #16a34a;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.modal-title-box h3 {
  margin: 0;
  font-size: 1.15rem;
  font-weight: 700;
  color: #0f172a;
}

.modal-title-box p {
  margin: 4px 0 0;
  font-size: 0.82rem;
  color: #64748b;
}

.modal-body {
  margin: 20px 0;
}

.modal-p {
  font-size: 0.9rem;
  color: #334155;
  line-height: 1.5;
  margin: 0 0 12px;
}

.alert-box {
  background: #f8fafc;
  border-left: 3px solid #2563eb;
  padding: 10px 14px;
  font-size: 0.8rem;
  color: #64748b;
  border-radius: 4px;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 24px;
}

.btn-relaunch {
  background: #2563eb;
  color: white;
  padding: 10px 20px;
  font-weight: 700;
}

/* 动效与微调 */
.spinner {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(0, 0, 0, 0.2);
  border-top-color: currentColor;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  display: inline-block;
}

.spinner.white {
  border-color: rgba(255, 255, 255, 0.3);
  border-top-color: white;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.mt-16 { margin-top: 16px; }
.mt-24 { margin-top: 24px; }
</style>
