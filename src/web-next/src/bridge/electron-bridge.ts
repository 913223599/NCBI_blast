/**
 * Electron Bridge — 薄聚合门面入口
 * 底层已按单一职责拆解为 httpClient、wsClient 与 domains/{filesAndBlast,settingsAndStrain,analysis}，
 * 对外保持 100% 向后兼容的导出符号与调用签名。
 */
import { API_BASE, WS_URL, apiDelete, apiGet, apiPost, getClientId } from './httpClient'
import { bridgeSignals, connectWebSocket, onEvent } from './wsClient'
import { filesAndBlastDomain } from './domains/filesAndBlast'
import { settingsAndStrainDomain } from './domains/settingsAndStrain'
import { analysisDomain } from './domains/analysis'
import { createLogger } from '../utils/logger'

const bridgeLog = createLogger('ElectronBridge')

const electronBridge = {
  recall_event: bridgeSignals.recall_event,
  blast_event: bridgeSignals.blast_event,
  sync_event: bridgeSignals.sync_event,
  ...filesAndBlastDomain,
  ...settingsAndStrainDomain,
  ...analysisDomain,
}

let bridgeInstance: typeof electronBridge | null = null
let bridgeReadyPromise: Promise<typeof electronBridge> | null = null

/** 初始化 Electron 桥接并等待本地 FastAPI 后端连通 */
async function initBridge(): Promise<typeof electronBridge> {
  if (bridgeReadyPromise) return bridgeReadyPromise

  bridgeReadyPromise = new Promise(async (resolve) => {
    bridgeLog.debug('正在验证 API Server 连通性...')

    let apiStarted = false
    let attempts = 0
    while (attempts < 15 && !apiStarted) {
      try {
        const res = await fetch(`${API_BASE}/`)
        if (res.ok) {
          apiStarted = true
          bridgeLog.debug('API Server 已就绪')
        }
      } catch {
        attempts++
        await new Promise((r) => setTimeout(r, 800))
      }
    }

    if (!apiStarted) {
      bridgeLog.warn('API Server 连通性检查超时，尝试盲目初始化...')
    }

    connectWebSocket()
    bridgeInstance = electronBridge
    bridgeLog.debug('桥接准备完成')
    resolve(electronBridge)
  })

  return bridgeReadyPromise
}

/** 获取已初始化的桥接单例 */
function getBridge(): typeof electronBridge {
  if (!bridgeInstance) {
    throw new Error('[ElectronBridge] 桥接尚未初始化，请先调用 initBridge()')
  }
  return bridgeInstance
}

/** 注册全局回调（兼容历史全局事件钩子） */
function registerGlobalHandler(name: string, handler: (...args: unknown[]) => void): void {
  window[name] = handler
}

export {
  API_BASE,
  WS_URL,
  apiDelete,
  apiGet,
  apiPost,
  getClientId,
  initBridge,
  getBridge,
  registerGlobalHandler,
  onEvent,
}
