/**
 * 本地存储工具 - 用于持久化保存冰箱数据
 */

const STORAGE_KEY = 'strain_freezer_data'

export interface StorageData {
  freezers: any[]
  records: any[]
  version: string
  lastSaved: string
}

/**
 * 保存数据到 localStorage
 */
export function saveToStorage(data: { freezers: any[]; records: any[] }): void {
  try {
    const storageData: StorageData = {
      freezers: data.freezers,
      records: data.records,
      version: '1.0.0',
      lastSaved: new Date().toISOString()
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(storageData))
    console.log('[Storage] Data saved successfully')
  } catch (error) {
    console.error('[Storage] Failed to save data:', error)
  }
}

/**
 * 从 localStorage 加载数据
 */
export function loadFromStorage(): { freezers: any[]; records: any[] } | null {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (!stored) {
      console.log('[Storage] No stored data found')
      return null
    }

    const data: StorageData = JSON.parse(stored)
    console.log(`[Storage] Data loaded from ${data.lastSaved}`)
    
    return {
      freezers: data.freezers || [],
      records: data.records || []
    }
  } catch (error) {
    console.error('[Storage] Failed to load data:', error)
    return null
  }
}

/**
 * 清除存储的数据
 */
export function clearStorage(): void {
  try {
    localStorage.removeItem(STORAGE_KEY)
    console.log('[Storage] Data cleared')
  } catch (error) {
    console.error('[Storage] Failed to clear data:', error)
  }
}
