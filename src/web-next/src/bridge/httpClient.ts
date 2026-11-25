/**
 * HTTP REST 客户端与会话配置底座
 * 统一封装 client_id、API/WebSocket 基址自适应推导及 JSON 请求错误处理。
 */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { createLogger } from '../utils/logger'

const bridgeLog = createLogger('ElectronBridge')

// 生成当前会话的唯一标识符，用于排除广播回环
const MY_CLIENT_ID = 'client_' + Math.random().toString(36).substring(2, 10)

/** 获取当前客户端 ID */
export function getClientId(): string {
  return MY_CLIENT_ID
}

// 默认地址 (Electron 环境)
export let API_BASE = 'http://127.0.0.1:8765'
export let WS_URL = `ws://127.0.0.1:8765/ws?client_id=${MY_CLIENT_ID}`

// 局域网/外部浏览器自适应基址切换
if (typeof window !== 'undefined') {
  const { protocol, port, origin } = window.location
  if (port !== '5173' && (protocol === 'http:' || protocol === 'https:')) {
    bridgeLog.info(`检测到外部浏览器访问，自动切换 API 基址至: ${origin}`)
    API_BASE = origin
    const wsProtocol = protocol === 'https:' ? 'wss:' : 'ws:'
    WS_URL = `${wsProtocol}//${window.location.host}/ws?client_id=${MY_CLIENT_ID}`
  }
}

export async function apiGet(endpoint: string): Promise<any> {
  try {
    const response = await fetch(`${API_BASE}${endpoint}`)
    if (!response.ok) return { success: false, error: `HTTP ${response.status}`, status: response.status }

    const contentType = response.headers.get('content-type')
    if (contentType && contentType.includes('application/json')) {
      return await response.json()
    }
    return { success: true, text: await response.text() }
  } catch (err) {
    bridgeLog.error(`GET ${endpoint} 失败:`, err)
    return { success: false, error: String(err) }
  }
}

export async function apiPost(endpoint: string, body?: any): Promise<any> {
  try {
    const response = await fetch(`${API_BASE}${endpoint}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Client-ID': MY_CLIENT_ID,
      },
      body: body ? JSON.stringify(body) : undefined,
    })

    const contentType = response.headers.get('content-type')
    if (response.ok && contentType && contentType.includes('application/json')) {
      return await response.json()
    }

    if (!response.ok) {
      const errorText = await response.text().catch(() => 'Unknown Error')
      return { success: false, error: `HTTP ${response.status}: ${errorText}`, status: response.status }
    }

    return { success: true, text: await response.text() }
  } catch (err) {
    bridgeLog.error(`POST ${endpoint} 失败:`, err)
    return { success: false, error: String(err) }
  }
}

export async function apiDelete(endpoint: string): Promise<any> {
  try {
    const response = await fetch(`${API_BASE}${endpoint}`, {
      method: 'DELETE',
      headers: { 'X-Client-ID': MY_CLIENT_ID },
    })
    if (!response.ok) {
      let detail = ''
      try {
        const ct = response.headers.get('content-type') || ''
        if (ct.includes('application/json')) {
          const errJson = await response.json()
          detail = String(errJson?.detail || errJson?.error || errJson?.message || '')
        } else {
          detail = (await response.text()).trim()
        }
      } catch {
        detail = ''
      }
      return {
        success: false,
        error: detail ? `HTTP ${response.status}: ${detail}` : `HTTP ${response.status}`,
        status: response.status,
      }
    }
    const contentType = response.headers.get('content-type') || ''
    if (contentType.includes('application/json')) {
      return await response.json()
    }
    return { success: true }
  } catch (err) {
    bridgeLog.error(`DELETE ${endpoint} 失败:`, err)
    return { success: false, error: String(err) }
  }
}
