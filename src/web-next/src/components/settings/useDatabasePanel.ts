import { ref, computed, onMounted, onUnmounted } from 'vue'
import { getBridge, onEvent } from '../../bridge'
import { useAppStore } from '../../stores/app'
import { useConfirmDialog } from '../../composables/useConfirmDialog'
import { createLogger } from '../../utils/logger'

const logger = createLogger('DatabasePanel')

export interface DbUpdateProgress {
  db_id?: string
  status?: string
  progress?: number
  message?: string
  updated_at?: number
}

export interface BioDatabaseItem {
  db_id: string
  name: string
  version: string
  category?: string
  size_mb?: number
  last_modified?: string
  installed: boolean
  path?: string
  url?: string
  update_state?: DbUpdateProgress | null
}

export interface TaxonomyDbStatus {
  ready?: boolean
  building?: boolean
  status?: string
  progress?: string
  error?: string
  fileSizeMB?: number
  lastModified?: string
}

export interface UnifiedDbCardItem {
  id: string
  name: string
  version: string
  size_mb: number
  last_modified: string
  installed: boolean
  path: string
  url?: string
  type: 'bio' | 'tax'
  building: boolean
  progress: number
  message: string
  updateStatus: string
}

export function parseTaxonomyProgress(progressText?: string, building?: boolean): number {
  if (!building) return 0
  const text = (progressText || '').trim()
  const pctMatch = text.match(/(\d+(?:\.\d+)?)\s*%/)
  if (pctMatch && pctMatch[1]) {
    const rawPct = Number(pctMatch[1])
    if (!Number.isNaN(rawPct)) {
      return Math.min(75, Math.max(10, 10 + Math.round(rawPct * 0.65)))
    }
  }
  if (text.includes('完成')) return 100
  if (text.includes('编译')) return 85
  if (text.includes('打包')) return 78
  if (text.includes('校验')) return 76
  if (text.includes('MD5') || text.includes('准备')) return 8
  return 15
}

export function formatSizeMB(mb: number | string): string {
  const v = Number(mb)
  if (Number.isNaN(v) || v === 0) return '0 MB'
  if (v >= 1024) {
    return `${(v / 1024).toFixed(2)} GB`
  }
  return `${v.toFixed(2)} MB`
}

export function useDatabasePanel() {
  const appStore = useAppStore()
  const confirmDialog = useConfirmDialog()
  let eventCleanup: (() => void) | null = null
  let bioPollTimer: ReturnType<typeof setInterval> | null = null
  let taxPollTimer: ReturnType<typeof setInterval> | null = null

  const bioDatabases = ref<BioDatabaseItem[]>([])
  const loadingBioDbs = ref(false)
  const dbUpdates = ref<Record<string, DbUpdateProgress>>({})
  const cancellingDbIds = ref<Record<string, boolean>>({})
  const taxStatus = ref<TaxonomyDbStatus | null>(null)

  function stopBioPollTimer() {
    if (bioPollTimer) {
      clearInterval(bioPollTimer)
      bioPollTimer = null
    }
  }

  function syncBioUpdateStateFromServer(item: BioDatabaseItem) {
    const remote = item.update_state
    if (!remote) return
    const local = dbUpdates.value[item.db_id]
    if (!local) {
      if (remote.status === 'updating') {
        dbUpdates.value[item.db_id] = { ...remote }
      }
      return
    }

    if (remote.status === 'updating') {
      if (local.status !== 'updating' || (remote.progress ?? 0) >= (local.progress ?? 0)) {
        dbUpdates.value[item.db_id] = { ...remote }
      }
      return
    }

    if (local.status === 'updating') {
      dbUpdates.value[item.db_id] = { ...remote }
      cancellingDbIds.value[item.db_id] = false
      if (remote.status === 'success') {
        appStore.showNotification(remote.message || `${item.name} 更新完成`, 'success')
      } else if (remote.status === 'error') {
        appStore.showNotification(remote.message || `${item.name} 更新失败`, 'error')
      } else if (remote.status === 'cancelled') {
        appStore.showNotification(remote.message || `已取消 ${item.name} 更新`, 'info')
      }
    }
  }

  function ensureBioPollTimer() {
    const hasActive = Object.values(dbUpdates.value).some((u) => u?.status === 'updating')
    if (!hasActive) {
      stopBioPollTimer()
      return
    }
    if (bioPollTimer) return
    bioPollTimer = setInterval(() => {
      void loadBioDatabases(true)
    }, 4000)
  }

  async function loadBioDatabases(silent = false) {
    if (!silent) {
      loadingBioDbs.value = true
    }
    try {
      const res = await getBridge().get_all_db_status()
      if (res && res.success) {
        const items = Array.isArray(res.data) ? (res.data as BioDatabaseItem[]) : []
        bioDatabases.value = items
        for (const item of items) {
          syncBioUpdateStateFromServer(item)
        }
        ensureBioPollTimer()
      } else if (!silent) {
        appStore.showNotification('无法获取数据库状态', 'error')
      }
    } catch (err) {
      logger.error('Failed to load databases:', err)
    } finally {
      if (!silent) {
        loadingBioDbs.value = false
      }
    }
  }

  async function triggerBioDbUpdate(dbId: string) {
    if (dbUpdates.value[dbId]?.status === 'updating') return

    cancellingDbIds.value[dbId] = false
    dbUpdates.value[dbId] = {
      db_id: dbId,
      status: 'updating',
      progress: 5,
      message: '正在连接服务端...',
    }
    ensureBioPollTimer()

    try {
      const res = await getBridge().trigger_db_update(dbId)
      if (res && res.success) {
        if (res.already_running) {
          appStore.showNotification(`${dbId} 同步任务正在进行中`, 'info')
        } else {
          appStore.showNotification(`已启动 ${dbId} 同步任务`, 'success')
        }
        const current = dbUpdates.value[dbId]
        if (res.state && current?.status === 'updating' && (current.progress ?? 0) <= 5) {
          dbUpdates.value[dbId] = { ...res.state }
        }
      } else {
        const errMsg = res?.error || '启动失败'
        dbUpdates.value[dbId] = { db_id: dbId, status: 'error', progress: 0, message: errMsg }
        appStore.showNotification(errMsg, 'error')
        ensureBioPollTimer()
      }
    } catch {
      const errMsg = '通信异常，请检查后端状态'
      dbUpdates.value[dbId] = { db_id: dbId, status: 'error', progress: 0, message: errMsg }
      appStore.showNotification(errMsg, 'error')
      ensureBioPollTimer()
    }
  }

  async function cancelBioDbUpdate(dbId: string) {
    if (cancellingDbIds.value[dbId]) return
    cancellingDbIds.value[dbId] = true
    try {
      const res = await getBridge().cancel_db_update(dbId)
      if (res && res.success) {
        const prev = dbUpdates.value[dbId]
        if (prev && prev.status === 'updating') {
          dbUpdates.value[dbId] = { ...prev, message: '正在取消更新任务...' }
        }
        appStore.showNotification(`已请求取消 ${dbId} 更新`, 'info')
      } else {
        cancellingDbIds.value[dbId] = false
        appStore.showNotification(res?.error || '取消失败', 'error')
      }
    } catch {
      cancellingDbIds.value[dbId] = false
      appStore.showNotification('取消请求发送失败', 'error')
    }
  }

  function startTaxPollIfNeeded() {
    if (!taxStatus.value?.building || taxPollTimer) return
    taxPollTimer = setInterval(async () => {
      try {
        const updated = (await getBridge().taxonomy_status()) as TaxonomyDbStatus | null
        taxStatus.value = updated
        if (!updated?.building) {
          if (taxPollTimer) clearInterval(taxPollTimer)
          taxPollTimer = null
          cancellingDbIds.value.taxonomy = false
          const msg = (updated?.progress || '').trim()
          if (updated?.status === 'cancelled' || msg.includes('已取消')) {
            appStore.showNotification(msg || '已取消 NCBI 物种库更新', 'info')
          } else if (updated?.status === 'error' || msg.includes('失败')) {
            appStore.showNotification(msg || 'NCBI 物种分类库更新失败', 'error')
          } else if (msg.includes('已是最新版本')) {
            appStore.showNotification(msg, 'info')
          } else {
            appStore.showNotification('NCBI 物种分类库更新完成', 'success')
          }
          void loadBioDatabases(true)
        }
      } catch (pollErr) {
        logger.warn('轮询 NCBI 物种库状态失败:', pollErr)
      }
    }, 2000)
  }

  async function cancelTaxUpdate() {
    if (cancellingDbIds.value.taxonomy) return
    cancellingDbIds.value.taxonomy = true
    try {
      const res = await getBridge().taxonomy_cancel()
      if (res && res.success) {
        if (taxStatus.value) {
          taxStatus.value = { ...taxStatus.value, progress: '正在取消更新任务...' }
        }
        appStore.showNotification('已请求取消 NCBI 物种库更新', 'info')
      } else {
        cancellingDbIds.value.taxonomy = false
        appStore.showNotification(res?.error || '取消失败', 'error')
      }
    } catch {
      cancellingDbIds.value.taxonomy = false
      appStore.showNotification('取消请求发送失败', 'error')
    }
  }

  async function cancelUpdate(db: UnifiedDbCardItem) {
    if (db.type === 'tax') {
      await cancelTaxUpdate()
    } else {
      await cancelBioDbUpdate(db.id)
    }
  }

  async function refreshTaxStatus() {
    try {
      const result = (await getBridge().taxonomy_status()) as TaxonomyDbStatus | null
      taxStatus.value = result
      startTaxPollIfNeeded()
    } catch (e) {
      logger.warn('获取 NCBI 物种库状态失败:', e)
    }
  }

  async function triggerTaxUpdate() {
    if (taxStatus.value?.building) return
    const ok = await confirmDialog.confirm({
      title: '更新 NCBI 物种库',
      message: 'NCBI 物种库更新涉及大量数据下载与解压，建议在网络环境良好时进行，是否继续？',
      confirmText: '开始更新',
    })
    if (!ok) return

    appStore.showNotification('启动 NCBI 物种库增量更新', 'info')
    try {
      await getBridge().taxonomy_update()
      await refreshTaxStatus()
    } catch {
      appStore.showNotification('更新指令发送失败', 'error')
    }
  }

  const groupedDatabases = computed(() => {
    const groups: Record<string, UnifiedDbCardItem[]> = {}

    for (const db of bioDatabases.value) {
      const cat = db.category || '未分类数据库'
      if (!groups[cat]) groups[cat] = []
      const upd = dbUpdates.value[db.db_id]
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
        building: upd?.status === 'updating',
        progress: upd?.progress || 0,
        message: upd?.message || '',
        updateStatus: upd?.status || '',
      })
    }

    if (taxStatus.value) {
      const cat = 'NCBI 物种分类数据库'
      if (!groups[cat]) groups[cat] = []
      const isTaxBuilding = Boolean(taxStatus.value.building)
      const taxProgText = (taxStatus.value.progress || '').trim()
      const taxIsError = !isTaxBuilding && taxProgText.includes('失败')
      groups[cat].push({
        id: 'taxonomy',
        name: 'NCBI Taxonomy (ETE4)',
        version: 'Latest',
        size_mb: taxStatus.value.fileSizeMB || 0,
        last_modified: taxStatus.value.lastModified || '未知',
        installed: Boolean(taxStatus.value.ready),
        path: 'database/ncbi_taxonomy',
        type: 'tax',
        building: isTaxBuilding,
        progress: parseTaxonomyProgress(taxProgText, isTaxBuilding),
        message: isTaxBuilding ? taxProgText || '正在后台构建/同步中...' : taxIsError ? taxProgText : '',
        updateStatus: isTaxBuilding ? 'updating' : taxIsError ? 'error' : '',
      })
    }

    const categoryOrder = [
      '噬菌体注释与分析',
      '功能注释与 AI 预测库',
      '结构域与特征家族库',
      '病原毒力与安全性数据库',
      '16S/18S 参考数据库',
      'NCBI 物种分类数据库',
    ]

    return Object.keys(groups)
      .sort((a, b) => {
        const idxA = categoryOrder.indexOf(a)
        const idxB = categoryOrder.indexOf(b)
        if (idxA !== -1 && idxB !== -1) return idxA - idxB
        if (idxA !== -1) return -1
        if (idxB !== -1) return 1
        return a.localeCompare(b, 'zh-CN')
      })
      .map((cat) => ({
        category: cat,
        dbs: groups[cat],
      }))
  })

  async function triggerUpdate(db: UnifiedDbCardItem) {
    if (db.type === 'tax') {
      await triggerTaxUpdate()
    } else {
      if (db.installed) {
        const ok = await confirmDialog.confirm({
          title: '确认覆盖更新数据库',
          message: `【${db.name}】当前已完整就绪。\n\n系统暂未检测到必须的远端版本变更。强制更新将重新下载并构建庞大的数据库文件（可能耗时较长），是否确定要继续覆盖更新？`,
          confirmText: '强制更新',
          danger: true,
        })
        if (!ok) return
      }
      await triggerBioDbUpdate(db.id)
    }
  }

  function refreshAll() {
    void refreshTaxStatus()
    void loadBioDatabases()
  }

  onMounted(() => {
    void refreshTaxStatus()
    void loadBioDatabases()

    eventCleanup = onEvent((type, data) => {
      if (type === 'db_update_event' && data && typeof data === 'object' && 'db_id' in data) {
        const progress = data as DbUpdateProgress
        if (!progress.db_id) return
        dbUpdates.value[progress.db_id] = progress

        if (progress.status === 'success') {
          cancellingDbIds.value[progress.db_id] = false
          void loadBioDatabases(true)
          appStore.showNotification(progress.message || `${progress.db_id} 更新完成`, 'success')
          ensureBioPollTimer()
        } else if (progress.status === 'error') {
          cancellingDbIds.value[progress.db_id] = false
          appStore.showNotification(progress.message || `${progress.db_id} 更新失败`, 'error')
          ensureBioPollTimer()
        } else if (progress.status === 'cancelled') {
          cancellingDbIds.value[progress.db_id] = false
          appStore.showNotification(progress.message || `已取消 ${progress.db_id} 更新`, 'info')
          ensureBioPollTimer()
        }
      }
    })
  })

  onUnmounted(() => {
    if (eventCleanup) eventCleanup()
    stopBioPollTimer()
    if (taxPollTimer) {
      clearInterval(taxPollTimer)
      taxPollTimer = null
    }
  })

  return {
    loadingBioDbs,
    taxStatus,
    cancellingDbIds,
    groupedDatabases,
    triggerUpdate,
    cancelUpdate,
    refreshAll,
    formatSizeMB,
  }
}
