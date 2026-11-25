/**
 * WebSocket 实时事件通道与信号槽管理
 * 负责断线重连、心跳定时清理及全局事件分发。
 */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { WS_URL } from './httpClient'
import { createLogger } from '../utils/logger'

const wsLog = createLogger('ElectronBridge:WS')

export type EventHandler = (eventType: string, data: any) => void

const eventHandlers: EventHandler[] = []
let wsConnection: WebSocket | null = null
let wsReconnectTimer: ReturnType<typeof setTimeout> | null = null
let wsHeartbeatTimer: ReturnType<typeof setInterval> | null = null

const WS_RECONNECT_INTERVAL_MS = 3000
const WS_HEARTBEAT_INTERVAL_MS = 15000

function stopWsHeartbeat(): void {
  if (wsHeartbeatTimer) {
    clearInterval(wsHeartbeatTimer)
    wsHeartbeatTimer = null
  }
}

/** 轻量信号订阅器 */
export class BridgeSignal {
  private handlers: Array<(...args: any[]) => void> = []

  connect(handler: (...args: any[]) => void): void {
    this.handlers.push(handler)
  }

  emit(...args: any[]): void {
    for (const h of this.handlers) h(...args)
  }
}

/** 全局事件分发信号实例 */
export const bridgeSignals = {
  recall_event: new BridgeSignal(),
  blast_event: new BridgeSignal(),
  sync_event: new BridgeSignal(),
  phylo_event: new BridgeSignal(),
}

export function connectWebSocket(): void {
  if (wsReconnectTimer) {
    clearTimeout(wsReconnectTimer)
    wsReconnectTimer = null
  }
  if (wsConnection?.readyState === WebSocket.OPEN) return

  wsLog.debug('正在连接 WebSocket...')
  wsConnection = new WebSocket(WS_URL)

  wsConnection.onopen = () => {
    wsLog.debug('WebSocket 已连接')
    stopWsHeartbeat()
    wsHeartbeatTimer = setInterval(() => {
      if (wsConnection?.readyState === WebSocket.OPEN) {
        wsConnection.send('ping')
      }
    }, WS_HEARTBEAT_INTERVAL_MS)
  }

  wsConnection.onmessage = (event) => {
    try {
      const raw = event.data
      if (raw === '{"type": "pong"}') return

      const msg = JSON.parse(raw)
      if (msg.type === 'pong') return

      for (const handler of eventHandlers) {
        handler(msg.type, msg.data)
      }

      if (msg.type === 'data_updated') {
        bridgeSignals.sync_event.emit(msg.data)
      } else if (msg.type === 'single_result_update') {
        bridgeSignals.blast_event.emit(msg.type, JSON.stringify(msg.data))
      }

      if (msg.type === 'recall_result') {
        bridgeSignals.recall_event.emit(msg.data.success, msg.data.message || msg.data.recalled_name)
      } else if (
        ['translation_done', 'single_result_update', 'task_progress', 'batch_translation_result'].includes(msg.type)
      ) {
        bridgeSignals.blast_event.emit(msg.type, JSON.stringify(msg.data))
      } else if (msg.type && String(msg.type).startsWith('phylo_')) {
        bridgeSignals.phylo_event.emit(msg.type, msg.data)
      }

      if (window.handleBridgeEvent) {
        window.handleBridgeEvent(msg.type, msg.data)
      }
    } catch (parseError) {
      wsLog.warn('WebSocket 消息解析失败:', parseError)
    }
  }

  wsConnection.onclose = () => {
    wsLog.debug('WebSocket 连接断开，将自动重连...')
    stopWsHeartbeat()
    wsConnection = null
    wsReconnectTimer = setTimeout(connectWebSocket, WS_RECONNECT_INTERVAL_MS)
  }

  wsConnection.onerror = (err) => {
    wsLog.error('WebSocket 错误:', err)
  }
}

/** 注册事件监听器（接收 Python 推送） */
export function onEvent(handler: EventHandler): () => void {
  eventHandlers.push(handler)
  return () => {
    const index = eventHandlers.indexOf(handler)
    if (index >= 0) eventHandlers.splice(index, 1)
  }
}
