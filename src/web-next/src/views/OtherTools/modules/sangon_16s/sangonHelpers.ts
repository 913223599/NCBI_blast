/**
 * sangonHelpers.ts - 生工 16S 模块纯辅助与状态判定函数
 */
import type { SangonOrderItem } from '../../sangonTypes'

export function isProcessingStatus(status: SangonOrderItem['status']): boolean {
  return status === 'downloaded' || status === 'extracted' || status === 'blasted'
}

export function normalizeOrderKeyFrontend(raw: string): string {
  const s = String(raw || '').trim()
  const m = s.match(/(?<!\d)(\d{10})(?!\d)/)
  if (m && m[1]) return m[1]
  if (s.includes('_')) return s.split('_', 2)[1]?.trim() || s
  return s
}

export function statusLabel(st: string): string {
  const map: Record<string, string> = {
    completed: '已完成',
    blasted: '待导出',
    extracted: '待比对',
    downloaded: '待解压',
    pending: '待下载',
  }
  return map[st] || st
}

export function extractErrorMessage(err: unknown): string {
  if (err instanceof Error) return err.message
  if (typeof err === 'object' && err !== null && 'message' in err) {
    const msg = (err as { message?: unknown }).message
    if (msg !== undefined && msg !== null) return String(msg)
  }
  return String(err)
}
