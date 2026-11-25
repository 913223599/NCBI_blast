/**
 * 邮件自动化流水线领域类型与标签映射工具
 */
export interface AttachmentItem {
  filename: string
  size_bytes: number
  sha256?: string
  path: string
}

export interface InboxAttachmentItem {
  filename: string
  size_bytes: number
  sha256: string
  already_processed: boolean
}

export interface InboxMailItem {
  seq: number
  message_id: string
  sender: string
  subject: string
  date: string
  duplicate_count: number
  status: 'new' | 'partial' | 'processed' | 'no_attachment'
  new_attachment_count: number
  processed_attachment_count: number
  attachments: InboxAttachmentItem[]
}

export interface BatchItem {
  batch_name: string
  batch_path: string
  download_time: string
  sender: string
  subject: string
  mail_date: string
  attachments: AttachmentItem[]
  pipeline_status?: string
  pipeline_status_label?: string
  send_status?: string
  task_ids?: string[]
  last_error?: string
  pending?: boolean
  ignored?: boolean
  ignore_reason?: string
  ignored_at?: string
}

export interface OutboundPackage {
  task_id: string
  pack_time: string
  zip_name: string
  zip_path: string
  size_kb: number
  file_count: number
}

export interface DocxReportItem {
  name: string
  path: string
  size_kb: number
  mtime: string
}

export interface ProcessedItem {
  sha256: string
  message_id?: string
  filename: string
  first_seen: string
  batch: string
  sender: string
  subject: string
  mail_date: string
}

export interface AuthInfo {
  imap_ready: boolean
  imap_masked: string
  imap_file: string
  smtp_ready: boolean
  smtp_masked: string
  smtp_file: string
  smtp_separate: boolean
}

export function inboxStatusLabel(status: string): string {
  const map: Record<string, string> = {
    new: '待收新邮件',
    partial: '部分新附件',
    processed: '已全部去重',
    no_attachment: '无匹配附件',
  }
  return map[status] || status
}

export function stageLabel(stage?: string): string {
  const map: Record<string, string> = {
    idle: '空闲',
    running: '执行中',
    fetching: '扫描收件箱',
    queued: '准备处理批次',
    annotating: '基因组注释中',
    reporting: '构建 Word 报告中',
    packing: '打包产物中',
    sending: 'SMTP 回传中',
    completed: '完成',
    failed: '异常退出',
  }
  return map[stage || 'idle'] || (stage || '空闲')
}

export function extractLastLine(text: string): string {
  const lines = String(text || '')
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter(Boolean)
  return lines[lines.length - 1] ?? ''
}
