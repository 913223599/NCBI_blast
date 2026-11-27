/**
 * 其他功能工作台通用请求工具
 */
import { resolveApiUrl } from '../../utils/fileDownloader'
import { createLogger } from '../../utils/logger'
const logger = createLogger('api')

export interface MigrationInfo {
  old?: string
  new?: string
  message?: string
  json_rewritten?: number
}

export async function getJson<T = Record<string, unknown>>(path: string): Promise<T> {
  const resp = await fetch(resolveApiUrl(path))
  const data = (await resp.json().catch(() => ({}))) as { detail?: string }
  if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`)
  return data as T
}

export async function postJson<T = Record<string, unknown>>(path: string, body?: unknown): Promise<T> {
  const init: RequestInit = {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  }
  if (body !== undefined) {
    init.body = JSON.stringify(body)
  }
  const resp = await fetch(resolveApiUrl(path), init)
  const data = (await resp.json().catch(() => ({}))) as { detail?: string }
  if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`)
  return data as T
}

export async function openLocalPath(pathStr: string): Promise<void> {
  try {
    await postJson('/api/other_tools/open_path', { path: pathStr })
  } catch (err) {
    logger.error(err)
  }
}

/** 汇总目录迁移结果为一句提示 */
export function describeMigration(m: MigrationInfo | null | undefined): string {
  if (!m) return ''
  const base = `${m.old ?? ''} -> ${m.new ?? ''}：${m.message || ''}`
  return m.json_rewritten ? `${base}，已修正 ${m.json_rewritten} 个清单文件中的路径` : base
}

