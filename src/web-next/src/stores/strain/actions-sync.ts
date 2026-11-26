import type { Ref } from 'vue'
import { getBridge, onEvent } from '../../bridge'
import { createLogger } from '../../utils/logger'
import type { Freezer, StrainRecord } from './types'
import type { CodeLookupEntry, SerialCounter, SourceEntry } from '../../types/codeSystem'

interface CodeConfig {
  assignMode: string
  serialDigits: number
  version: string
}

const _log = createLogger('StrainSync')

interface RawStrainRecordPayload extends Partial<StrainRecord> {
  freezer_id?: string
  shelf_id?: string
  cabinet_id?: string
  drawer_id?: string
  box_id?: string
  sequence?: string
}

interface StrainLoadAllPayload {
  status?: string
  freezers?: Freezer[]
  records?: RawStrainRecordPayload[]
  total_count?: number
  codeLookup?: {
    entries?: CodeLookupEntry[]
    sources?: SourceEntry[]
    counters?: SerialCounter[]
    config?: Partial<CodeConfig>
  }
}

interface SyncActionState {
  freezers: Ref<Freezer[]>
  records: Ref<StrainRecord[]>
  codeLookupEntries: Ref<CodeLookupEntry[]>
  sourceEntries: Ref<SourceEntry[]>
  serialCounters: Ref<SerialCounter[]>
  codeConfig: Ref<CodeConfig>
  isInitialized: Ref<boolean>
  serverTotalCount: Ref<number>
  getIsUpdating: () => boolean
}

interface SyncEventPayload {
  module?: string
  original?: string
  translated?: string
}

export function useSyncActions(
  state: SyncActionState,
  recordsActions: { applyFilters: () => void },
  freezerActions?: { refreshFreezerOccupancy?: (shouldSave?: boolean) => void }
) {
  const {
    freezers,
    records,
    codeLookupEntries,
    sourceEntries,
    serialCounters,
    codeConfig,
    isInitialized,
  } = state

  let isLoading = false
  const getCooldown = () => parseInt(sessionStorage.getItem('sync_cooldown') || '0', 10)
  const setCooldown = () => {
    sessionStorage.setItem('sync_cooldown', Date.now().toString())
  }

  async function initFromDatabase() {
    const now = Date.now()
    const lastSync = getCooldown()
    if (isLoading || now - lastSync < 2500) {
      return
    }

    isLoading = true
    setCooldown()

    try {
      const bridge = getBridge()
      bridge.db_load_all<StrainLoadAllPayload | string>((result) => {
        if (!result) {
          isLoading = false
          return
        }

        try {
          const data: StrainLoadAllPayload | null =
            typeof result === 'string' ? (JSON.parse(result) as StrainLoadAllPayload) : result
          if (!data) {
            isLoading = false
            return
          }

          if (data.status === 'throttled') {
            _log.debug('[Sync] 后端节流中，保留当前内存数据')
            isLoading = false
            return
          }

          if (data.freezers) {
            _log.debug('[Sync] 收到后端冰箱结构更新，准备同步数据...')
            freezers.value = data.freezers
          }

          if (data.records) {
            const processed = data.records.map((r) => {
              const { sequence: _droppedSeq, ...rest } = r
              return {
                ...rest,
                freezerId: r.freezer_id || r.freezerId || '',
                shelfId: r.shelf_id || r.shelfId || '',
                cabinetId: r.cabinet_id || r.cabinetId || '',
                drawerId: r.drawer_id || r.drawerId || '',
                boxId: r.box_id || r.boxId || '',
                position: r.position || '',
              } as StrainRecord
            })
            records.value = processed
          }

          if (typeof data.total_count === 'number') {
            state.serverTotalCount.value = data.total_count
          }

          _log.debug('[Sync] 检查 codeLookup 数据:', Boolean(data.codeLookup))
          if (data.codeLookup) {
            const entries = data.codeLookup.entries || []
            _log.debug(`[Sync] 加载 codeLookup: ${entries.length} 个条目`)

            if (entries.length > 0) {
              _log.debug('[Sync] Sample entries:')
              entries.slice(0, 5).forEach((entry, idx) => {
                _log.debug(
                  `  [${idx}] level=${entry.level}, fullPath="${entry.fullPath}", parentPath="${entry.parentPath}", name=${entry.name}`
                )
              })
              const levelCounts: Record<number, number> = {}
              entries.forEach((e) => {
                const level = e.level || 0
                levelCounts[level] = (levelCounts[level] || 0) + 1
              })
              _log.debug('[Sync] Entries by level:', levelCounts)
            }

            codeLookupEntries.value = entries
            sourceEntries.value = data.codeLookup.sources || []
            serialCounters.value = data.codeLookup.counters || []
            codeConfig.value = {
              ...codeConfig.value,
              ...(data.codeLookup.config || {}),
            }
          } else {
            _log.warn('[Sync] 后端未返回 codeLookup 数据，使用空数组')
            codeLookupEntries.value = []
            sourceEntries.value = []
            serialCounters.value = []
          }

          recordsActions.applyFilters()
          _log.debug(`[Sync] 数据加载完成: ${records.value.length} 条样本, ${freezers.value.length} 个冰箱`)

          if (freezerActions?.refreshFreezerOccupancy) {
            _log.debug(`[Sync] 正在从 ${records.value.length} 条样本记录中恢复物理占用拓补...`)
            freezerActions.refreshFreezerOccupancy(false)
          }

          isInitialized.value = true
          _log.debug('[Sync] 系统初始化完成')
        } catch (e) {
          _log.error('[Sync] Parse Error', e)
        } finally {
          isLoading = false
        }
      })
    } catch {
      isLoading = false
    }
  }

  let cleanupHandler: (() => void) | null = null

  function setupSync() {
    if (cleanupHandler) return

    cleanupHandler = onEvent((type: string, rawData: unknown) => {
      const data = (rawData || {}) as SyncEventPayload

      if (type === 'data_updated' && data.module === 'strains') {
        const isLocalUpdating = state.getIsUpdating()
        _log.debug(`[Sync] 收到同步信号 | 模块: strains | 本地护盾状态: ${isLocalUpdating}`)
        if (!isLocalUpdating) {
          initFromDatabase()
        } else {
          _log.debug('[Sync] 本地正在写入，跳过本次后端信号拦截')
        }
      }

      if (type === 'data_updated' && data.module === 'dictionary') {
        const bridge = getBridge()
        bridge.db_load_code_lookup<{ counters?: SerialCounter[]; entries?: CodeLookupEntry[] } | null>((res) => {
          if (res?.counters) serialCounters.value = res.counters
          if (res?.entries) codeLookupEntries.value = res.entries
        })
      }

      if (type === 'translation_done' && data.original) {
        const entries = [...codeLookupEntries.value]
        let changed = false

        for (let i = 0; i < entries.length; i += 1) {
          const entry = entries[i]
          if (entry && (entry.latinName === data.original || entry.name === data.original)) {
            if (data.translated && data.translated !== data.original) {
              entries[i] = {
                ...entry,
                name: `${data.translated}(${data.original})`,
                verified: true,
              } as CodeLookupEntry
              changed = true
            }
          }
        }

        if (changed) {
          codeLookupEntries.value = entries
          autoSave()
        }
      }
    })
  }

  let autoSaveTimer: ReturnType<typeof setTimeout> | null = null

  async function autoSave() {
    if (!isInitialized.value) return
    if (autoSaveTimer) clearTimeout(autoSaveTimer)

    autoSaveTimer = setTimeout(async () => {
      try {
        const bridge = getBridge()
        const data = {
          entries: [...codeLookupEntries.value],
          sources: [...sourceEntries.value],
          counters: [...serialCounters.value],
          config: codeConfig.value,
        }
        bridge.db_save_code_lookup(data, (success: boolean) => {
          if (success) {
            _log.debug('[Sync] CodeLookup data persisted (debounced)')
          }
        })
      } catch (e) {
        _log.error('[Sync] AutoSave failed', e)
      } finally {
        autoSaveTimer = null
      }
    }, 800)
  }

  return {
    initFromDatabase,
    setupSync,
    autoSave,
    cleanup: () => {
      if (cleanupHandler) {
        cleanupHandler()
        cleanupHandler = null
      }
    },
  }
}
