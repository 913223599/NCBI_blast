import { initBridge as initElectron, onEvent as electronOnEvent, getClientId } from './electron-bridge'
import { createLogger } from '../utils/logger'

const log = createLogger('Bridge')

type BridgeInstance = Awaited<ReturnType<typeof initElectron>>
type EventHandler = Parameters<typeof electronOnEvent>[0]

interface BridgeWindow extends Window {
  pybridge?: BridgeInstance
}

/** 检测当前是否运行在 Electron 环境中 */
function isElectronEnvironment(): boolean {
  return Boolean(window.electronAPI)
}

/** 内部缓存单例 */
let _cachedBridge: BridgeInstance | null = null
let _isInitializing = false
const _readyCallbacks: Array<(bridge: BridgeInstance) => void> = []

/**
 * 初始化桥接并缓存单例
 * 在 App.vue 的 onMounted 中最先调用
 */
async function initBridge(): Promise<BridgeInstance> {
  if (_cachedBridge) return _cachedBridge
  if (_isInitializing) {
    return new Promise<BridgeInstance>((resolve) => _readyCallbacks.push(resolve))
  }

  _isInitializing = true
  try {
    const initialized = await initElectron()
    _cachedBridge = initialized
    ;(window as unknown as BridgeWindow).pybridge = initialized

    _readyCallbacks.forEach((cb) => cb(initialized))
    _readyCallbacks.length = 0

    return initialized
  } finally {
    _isInitializing = false
  }
}

/**
 * 同步获取桥接实例
 * 改进版：返回一个深层递归的 Proxy，支持在初始化完成前注册事件
 */
function getBridge(): BridgeInstance {
  if (_cachedBridge) return _cachedBridge

  // 递归 Proxy：处理 bridge.module.event.connect 这种多级调用
  const createProxy = (path: string[] = []): unknown => {
    return new Proxy(() => {}, {
      get(_target, prop) {
        if (typeof prop === 'string') {
          return createProxy([...path, prop])
        }
        return null
      },
      apply(_target, _thisArg, args: unknown[]) {
        const propPath = path.join('.')
        log.debug(`[Bridge Pending] 异步队列化调用: ${propPath}`)

        // 将调用推入就绪队列
        _readyCallbacks.push((bridge) => {
          let current: unknown = bridge
          for (let i = 0; i < path.length - 1; i++) {
            if (!current || typeof current !== 'object') return
            current = (current as Record<string, unknown>)[path[i]!]
            if (!current) return
          }
          if (!current || typeof current !== 'object') return
          const method = (current as Record<string, unknown>)[path[path.length - 1]!]
          if (typeof method === 'function') {
            Reflect.apply(method, current, args)
          }
        })
      },
    })
  }

  return createProxy() as BridgeInstance
}

/** 全局事件转发 */
function onEvent(handler: EventHandler): () => void {
  if (_cachedBridge) {
    // 允许所有桥接模式尝试监听事件。
    // electron-bridge.ts 的 onEvent 实现在非 Electron 环境下通过 WebSocket 工作。
    return electronOnEvent(handler)
  }

  // 如果桥接没好，先存起来
  let cleanup: (() => void) | null = null
  let disposed = false
  _readyCallbacks.push(() => {
    if (disposed) return
    cleanup = electronOnEvent(handler)
  })

  return () => {
    disposed = true
    if (cleanup) cleanup()
  }
}

function registerGlobalHandler(name: string, handler: (...args: unknown[]) => void): void {
  ;(window as unknown as Record<string, unknown>)[name] = handler
}

async function setupBridge(): Promise<BridgeInstance> {
  return await initBridge()
}

export { initBridge, getBridge, registerGlobalHandler, setupBridge, isElectronEnvironment, onEvent, getClientId }
