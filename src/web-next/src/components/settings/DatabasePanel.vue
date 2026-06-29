<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { getBridge, onEvent } from '../../bridge'
import { useAppStore } from '../../stores/app'

const appStore = useAppStore()
let eventCleanup: (() => void) | null = null

/* -------- 1. 16S/18S 参考数据库状态 -------- */
const bioDatabases = ref<any[]>([])
const loadingBioDbs = ref(false)
const dbUpdates = ref<Record<string, any>>({})

async function loadBioDatabases() {
  loadingBioDbs.value = true
  try {
    const res = await getBridge().get_all_db_status()
    if (res && res.success) {
      bioDatabases.value = res.data
    } else {
      appStore.showNotification('无法获取数据库状态', 'error')
    }
  } catch (err) {
    console.error('Failed to load databases:', err)
  } finally {
    loadingBioDbs.value = false
  }
}

async function triggerBioDbUpdate(dbId: string) {
  if (dbUpdates.value[dbId]?.status === 'updating') return

  try {
    const res = await getBridge().trigger_db_update(dbId)
    if (res && res.success) {
      appStore.showNotification(`已启动 ${dbId} 同步任务`, 'success')
      dbUpdates.value[dbId] = { status: 'updating', progress: 5, message: '正在启动...' }
    } else {
      appStore.showNotification(res?.error || '启动失败', 'error')
    }
  } catch (err) {
    appStore.showNotification('通信异常，请检查后端状态', 'error')
  }
}

/* -------- 2. NCBI 物种库状态 -------- */
const taxStatus = ref<any>(null)
let taxPollTimer: any = null

async function refreshTaxStatus() {
  try {
    const result = await getBridge().taxonomy_status()
    taxStatus.value = result

    // 如果正在构建中，启动轮询
    if (result?.building && !taxPollTimer) {
      taxPollTimer = setInterval(async () => {
        const updated = await getBridge().taxonomy_status()
        taxStatus.value = updated
        if (!updated?.building) {
          clearInterval(taxPollTimer)
          taxPollTimer = null
          loadBioDatabases() // 刷新相关数据
        }
      }, 2000)
    }
  } catch (e) { }
}

async function triggerTaxUpdate() {
  if (taxStatus.value?.building) return
  if (!confirm('NCBI 物种库更新涉及大量数据下载与解压，建议在网络环境良好时进行，是否继续？')) return

  appStore.showNotification('启动 NCBI 物种库增量更新', 'info')
  try {
    await getBridge().taxonomy_update()
    refreshTaxStatus()
  } catch (e) {
    appStore.showNotification('更新指令发送失败', 'error')
  }
}

const groupedDatabases = computed(() => {
  const groups: Record<string, any[]> = {}

  // 1. 常规生物学数据库 (16S, PhageScope等)
  for (const db of bioDatabases.value) {
    const cat = db.category || '未分类数据库'
    if (!groups[cat]) groups[cat] = []
    groups[cat].push({
      id: db.db_id,
      name: db.name,
      version: db.version,
      size_mb: db.size_mb || 0,
      last_modified: db.last_modified || '未知',
      installed: db.installed,
      path: db.path || '',
      url: db.url || 'local_only',
      type: 'bio',
      building: dbUpdates.value[db.db_id]?.status === 'updating',
      progress: dbUpdates.value[db.db_id]?.progress || 0,
      message: dbUpdates.value[db.db_id]?.message || ''
    })
  }

  // 2. 特殊的分类学数据库
  if (taxStatus.value) {
    const cat = 'NCBI 物种分类数据库'
    if (!groups[cat]) groups[cat] = []
    groups[cat].push({
      id: 'taxonomy',
      name: 'NCBI Taxonomy (ETE4)',
      version: 'Latest',
      size_mb: taxStatus.value.fileSizeMB || 0,
      last_modified: taxStatus.value.lastModified || '未知',
      installed: taxStatus.value.ready,
      path: 'database/ncbi_taxonomy',
      type: 'tax',
      building: taxStatus.value.building,
      progress: taxStatus.value.building ? 50 : 0,
      message: taxStatus.value.building ? '正在后台构建/同步中...' : ''
    })
  }

  return Object.keys(groups).map(cat => ({
    category: cat,
    dbs: groups[cat]
  }))
})

function triggerUpdate(db: any) {
  if (db.type === 'tax') {
    triggerTaxUpdate()
  } else {
    if (db.installed) {
      if (!confirm(`【${db.name}】当前已完整就绪。\n\n系统暂未检测到必须的远端版本变更。强制更新将重新下载并构建庞大的数据库文件（可能耗时较长），是否确定要继续覆盖更新？`)) {
        return
      }
    }
    triggerBioDbUpdate(db.id)
  }
}

function refreshAll() {
  refreshTaxStatus()
  loadBioDatabases()
}

function formatSizeMB(mb: number | string) {
  const v = Number(mb)
  if (isNaN(v) || v === 0) return '0 MB'
  if (v >= 1024) {
    return (v / 1024).toFixed(2) + ' GB'
  }
  return v.toFixed(2) + ' MB'
}

onMounted(() => {
  refreshTaxStatus()
  loadBioDatabases()

  // 订阅广播事件
  eventCleanup = onEvent((type, data) => {
    if (type === 'db_update_event' && data.db_id) {
      dbUpdates.value[data.db_id] = data
      if (data.status === 'success') {
        loadBioDatabases()
        appStore.showNotification(`${data.db_id} 更新完成`, 'success')
      }
    }
  })
})

onUnmounted(() => {
  if (eventCleanup) eventCleanup()
  if (taxPollTimer) clearInterval(taxPollTimer)
})
</script>

<template>
  <div class="panel">
    <header class="panel-header">
      <div style="display: flex; justify-content: space-between; align-items: flex-end; width: 100%;">
        <div>
          <h2>🧬 生物分析数据库管理</h2>
          <p class="desc">集中管理各个分析流水线所需的数据库版本与状态。</p>
        </div>
        <button class="p-btn p-btn-outline" @click="refreshAll" style="font-size: 0.8rem; padding: 6px 12px;">🔄
          全局刷新</button>
      </div>
    </header>

    <div v-if="loadingBioDbs && !taxStatus" class="db-loading-state">
      <div class="spinner"></div>
      <span>正在扫描本地数据库配置...</span>
    </div>

    <!-- 动态渲染数据库分类 -->
    <div v-for="group in groupedDatabases" :key="group.category" class="p-card">
      <h3 style="margin-bottom: 20px;">📚 {{ group.category }}</h3>

      <div class="db-unified-list">
        <div v-for="db in group.dbs" :key="db.id" class="db-item-row">

          <div class="db-row-main">
            <!-- Left: Name & Version -->
            <div class="db-name-col">
              <span class="p-status-dot" :class="{ active: db.installed }"></span>
              <div class="name-text">
                <span class="name">{{ db.name }}</span>
                <span class="p-badge" style="margin-left: 8px;">{{ db.version }}</span>
              </div>
              <div class="db-meta-path" v-if="db.installed && db.path">📁 {{ db.path }}</div>
            </div>

            <!-- Middle: Stats -->
            <div class="db-stats-col">
              <div class="meta-item"><label>数据大小</label><span>{{ formatSizeMB(db.size_mb) }}</span></div>
              <div class="meta-item"><label>更新时间</label><span>{{ db.last_modified }}</span></div>
              <div class="meta-item"><label>当前状态</label>
                <span :class="db.installed ? 'status-ok' : 'status-err'" style="font-weight: 700; font-size: 0.9rem;">
                  {{ db.building ? '🔄 构建中...' : db.installed ? '✅ 完整就绪' : '❌ 尚未部署' }}
                </span>
              </div>
            </div>

            <!-- Right: Actions -->
            <div class="db-action-col">
              <button 
                v-if="db.url !== 'local_only' && db.url !== 'none'"
                class="p-btn p-btn-primary" 
                :disabled="db.building" 
                @click="triggerUpdate(db)">
                {{ db.installed ? '检查更新' : '一键部署' }}
              </button>
            </div>
          </div>

          <!-- Progress Bar Row (Conditionally shown below) -->
          <div v-if="db.building" class="db-prog-row">
            <div class="p-progress-bar">
              <div class="fill" :style="{ width: db.progress + '%' }"></div>
            </div>
            <span class="prog-msg">{{ db.message }} ({{ db.progress }}%)</span>
          </div>

        </div>
      </div>
    </div>

  </div>
</template>

<style scoped>
.db-unified-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.db-item-row {
  background: #fdfdfd;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 16px 20px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
  transition: box-shadow 0.2s ease, border-color 0.2s ease;
}

.db-item-row:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
  border-color: #cbd5e1;
}

.db-row-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}

.db-name-col {
  flex: 0 0 35%;
  display: flex;
  flex-direction: column;
  gap: 6px;
  position: relative;
  padding-left: 16px;
}

.p-status-dot {
  position: absolute;
  left: 0;
  top: 8px;
}

.name-text {
  display: flex;
  align-items: center;
}

.name {
  font-weight: 700;
  color: #1e293b;
  font-size: 1.05rem;
}

.db-stats-col {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 40px;
  background: #f8fafc;
  padding: 10px 24px;
  border-radius: 8px;
  border: 1px solid #f1f5f9;
}

.db-action-col {
  flex: 0 0 auto;
}

.meta-item label {
  display: block;
  font-size: 0.65rem;
  color: #94a3b8;
  margin-bottom: 4px;
  font-weight: 600;
  text-transform: uppercase;
}

.meta-item span {
  font-size: 0.85rem;
  font-weight: 600;
  color: #334155;
}

.status-ok {
  color: #10b981 !important;
}

.status-err {
  color: #f59e0b !important;
}

.db-meta-path {
  font-size: 0.72rem;
  color: #94a3b8;
  word-break: break-all;
  margin-top: 4px;
}

.prog-msg {
  font-size: 0.8rem;
  color: #64748b;
  margin-top: 6px;
  display: block;
}

.db-prog-row {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px dashed #e2e8f0;
}

.db-loading-state,
.db-empty-state {
  padding: 40px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  color: #64748b;
  background: #f8fafc;
  border-radius: 12px;
  border: 1px dashed #e2e8f0;
}

.empty-icon {
  font-size: 2.5rem;
  opacity: 0.5;
}

.db-empty-state p {
  font-size: 0.85rem;
  font-style: italic;
}

.spinner {
  width: 28px;
  height: 28px;
  border: 3px solid #e2e8f0;
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
