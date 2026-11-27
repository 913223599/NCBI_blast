/**
 * useSangonPipelineShared.ts - 供子 Composable 复用的订单可下载性判定与错误消息提取
 */
import type { SangonOrderItem } from '../../sangonTypes'
import { extractErrorMessage } from './sangonHelpers'

export { extractErrorMessage }

export function hasOrderDownloadChannelImpl(ord: SangonOrderItem): boolean {
  return Boolean(ord.download_zip_ready || ord.download_url || ord.cx_order_id)
}

export function isOrderDownloadableImpl(ord: SangonOrderItem): boolean {
  return !ord.ignored && ord.status === 'pending' && ord.zip_count === 0 && hasOrderDownloadChannelImpl(ord)
}
