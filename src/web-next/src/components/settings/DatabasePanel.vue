<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
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
  } catch (e) {}
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
      <h2>🧬 生物分析数据库管理</h2>
      <p class="desc">维护高性能比对所需的 16S/18S 参考源及 NCBI 谱系分类库。</p>
    </header>

    <!-- 16S/18S -->
    <div class="p-card">
      <h3>📚 生物参考数据库 (16S/18S)</h3>
      
      <div v-if="loadingBioDbs" class="db-loading-state">
        <div class="spinner"></div>
        <span>正在扫描本地数据库配置...</span>
      </div>

      <div v-else-if="bioDatabases.length === 0" class="db-empty-state">
        <div class="empty-icon">🗄️</div>
        <p>未检测到已注册的参考数据库，请检查后端 <code>bio_db_manager</code> 配置。</p>
      </div>

      <div v-else class="p-grid">
        <div v-for="db in bioDatabases" :key="db.db_id" class="db-item-card">
          <div class="db-main">
            <div class="db-name-row">
              <span class="p-status-dot" :class="{ active: db.installed }"></span>
              <span class="name">{{ db.name }}</span>
              <span class="p-badge">{{ db.version }}</span>
            </div>
            
            <div v-if="dbUpdates[db.db_id]" class="db-prog-area">
               <div class="p-progress-bar">
                 <div class="fill" :style="{ width: dbUpdates[db.db_id].progress + '%' }"></div>
               </div>
               <span class="prog-msg">{{ dbUpdates[db.db_id].message }} ({{ dbUpdates[db.db_id].progress }}%)</span>
            </div>

            <div class="db-meta" v-if="db.installed">📁 {{ db.path }}</div>
            <div class="db-meta error" v-else>⚠️ 尚未部署至本地</div>
          </div>
          
          <button 
            class="p-btn p-btn-outline" 
            :disabled="dbUpdates[db.db_id]?.status === 'updating'"
            @click="triggerBioDbUpdate(db.db_id)"
          >
            {{ db.installed ? '检查更新' : '一键自动化部署' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Taxonomy -->
    <div class="p-card" v-if="taxStatus">
      <h3>🔍 NCBI 物种分类数据库</h3>
      <div class="tax-info-grid">
         <div class="info-item">
           <label>当前状态</label>
           <div :class="['status-val', taxStatus.ready ? 'ready' : 'missing']">
             {{ taxStatus.building ? '🔄 构建中...' : taxStatus.ready ? '✅ 完整就绪' : '❌ 尚未构建' }}
           </div>
         </div>
         <div class="info-item">
           <label>数据大小 / 最后更新</label>
           <div class="val">{{ taxStatus.fileSizeMB }} MB / {{ taxStatus.lastModified || '未知' }}</div>
         </div>
      </div>

      <div class="actions">
        <button class="p-btn p-btn-outline" @click="refreshTaxStatus">🔄 刷新数据</button>
        <button class="p-btn p-btn-primary" :disabled="taxStatus.building" @click="triggerTaxUpdate">
          {{ taxStatus.building ? '⏳ 更新中...' : '🌐 从 NCBI 远端同步' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.db-item-card {
  background: #fdfdfd;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.name { font-weight: 700; color: #1e293b; }
.db-name-row { display: flex; align-items: center; gap: 8px; }
.db-meta { font-size: 0.72rem; color: #94a3b8; word-break: break-all; }
.error { color: #f59e0b; font-weight: 600; }
.prog-msg { font-size: 0.65rem; color: #64748b; }

.db-loading-state, .db-empty-state {
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
.empty-icon { font-size: 2.5rem; opacity: 0.5; }
.db-empty-state p { font-size: 0.85rem; font-style: italic; }

.spinner {
  width: 28px;
  height: 28px;
  border: 3px solid #e2e8f0;
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.tax-info-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 24px; }
.info-item { background: #f8fafc; padding: 12px 16px; border-radius: 8px; border: 1px solid #e2e8f0; }
.info-item label { display: block; font-size: 0.7rem; color: #94a3b8; margin-bottom: 4px; font-weight: 600; text-transform: uppercase; }
.status-val { font-weight: 700; font-size: 0.95rem; }
.status-val.ready { color: #10b981; }
.status-val.missing { color: #ef4444; }
.val { font-weight: 600; font-size: 0.95rem; }

.actions { display: flex; gap: 12px; justify-content: flex-end; }
</style>
