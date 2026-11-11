/**
 * 其他功能工作台通用请求工具
 */
import { resolveApiUrl } from '../../utils/fileDownloader'

export async function getJson<T = any>(path: string): Promise<T> {
  const resp = await fetch(resolveApiUrl(path))
  const data = await resp.json().catch(() => ({}))
  if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`)
  return data as T
}

export async function postJson<T = any>(path: string, body?: unknown): Promise<T> {
  const resp = await fetch(resolveApiUrl(path), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body)
  })
  const data = await resp.json().catch(() => ({}))
  if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`)
  return data as T
}

export async function openLocalPath(pathStr: string): Promise<void> {
  try {
    await postJson('/api/other_tools/open_path', { path: pathStr })
  } catch (err) {
    console.error(err)
  }
}

/** 汇总目录迁移结果为一句提示 */
export function describeMigration(m: any): string {
  if (!m) return ''
  const base = `${m.old} -> ${m.new}：${m.message || ''}`
  return m.json_rewritten ? `${base}，已修正 ${m.json_rewritten} 个清单文件中的路径` : base
}

