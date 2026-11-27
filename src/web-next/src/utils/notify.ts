import { getActivePinia } from 'pinia'
import { useAppStore } from '../stores/app'

export type NotifyLevel = 'info' | 'success' | 'warning' | 'error'

/**
 * 统一非阻塞通知入口：优先使用 Pinia AppStore，
 * 在脱离根应用上下文的独立组件单测中优雅降级，避免 setup() 阶段抛无活跃 Pinia 异常。
 */
export function notifyUser(message: string, type: NotifyLevel = 'info'): void {
  if (getActivePinia()) {
    useAppStore().showNotification(message, type)
    return
  }
  const globalWin = (globalThis as { window?: { app?: { showNotification?: (msg: string, level: NotifyLevel) => void } } }).window
  const winApp = globalWin?.app
  if (typeof winApp?.showNotification === 'function') {
    winApp.showNotification(message, type)
  }
}
