/**
 * 生工 16S 模块共享类型定义
 */

export type SangonOrderStatus = 'completed' | 'blasted' | 'extracted' | 'downloaded' | 'pending'

export interface IgnoredOrderRule {
  order_no: string
  dir_name?: string
  reason?: string
  ignored_at?: string
}

export interface SangonSettingsMeta {
  sangon_root: string
  downloads_dir: string
  ignored_orders: Record<string, IgnoredOrderRule>
  ignore_subject_keywords: string[]
  sangon_account?: string
  sangon_password_file?: string
  auto_confirm_fee?: boolean
}

export interface SangonAuthMeta {
  account: string
  password_ready: boolean
  password_masked: string
  password_file: string
  auto_confirm_fee: boolean
}

export interface SangonOrderItem {
  dir_name: string
  order_date: string
  order_no: string
  order_path: string
  status: SangonOrderStatus
  zip_count: number
  zip_files: Array<{ name: string; size_kb: number }>
  raw_file_count: number
  consensus_fasta_count: number
  ab1_count: number
  blast_task_id: string
  blast_report_count: number
  has_result_csv: boolean
  result_csv_path: string
  result_mtime: string
  total_samples: number
  with_hits: number
  no_hits: number
  mail_subject?: string
  mail_date?: string
  cx_order_id?: string
  download_url?: string
  created_at?: string
  is_new?: boolean
  download_zip_ready?: boolean
  download_zip_name?: string
  ignored?: boolean
  ignore_reason?: string
  ignored_at?: string
}

export type MailDedupStatus = 'created' | 'existing' | 'history_skipped' | 'ignored' | 'new' | 'non_sequencing'

export interface ScannedMailItem {
  seq: number
  message_id: string
  subject: string
  date: string
  order_no: string
  dir_name: string
  is_sequencing?: boolean
  ignored?: boolean
  legacy_dir_exists?: boolean
  cx_order_id: string
  download_url: string
  dir_ready: boolean
  dedup_status: MailDedupStatus
  duplicate_count: number
}

export interface MailScanSummary {
  rawTotal: number
  uniqueTotal: number
  dedupRemoved: number
  skippedKnown: number
  ignoredCount: number
  newCount: number
  createdCount: number
  existingCount: number
  nonSequencingCount: number
}

export interface DownloadCandidateItem {
  order_no: string
  zip_name: string
  zip_path: string
  size_kb: number
  mtime_str: string
  matched_dir_name: string
  matched_status: string
  archived: boolean
  ignored?: boolean
  ignore_reason?: string
  ignored_at?: string
}

/** 订单表分段筛选：全部(有效) / 待下载 / 处理中 / 已完成 / 已忽略 */
export type OrderFilterKey = 'all' | 'pending' | 'processing' | 'completed' | 'ignored'

/** 订单行主操作 */
export type OrderPrimaryAction = 'claim' | 'download' | 'run' | 'result'

export interface SangonRuntimeSummary {
  total: number
  processed: number
  skipped_missing: number
  failed: number
}

export interface SangonRuntimeState {
  running: boolean
  current_order: string | null
  current_stage: string
  progress: number
  started_at: string | null
  finished_at: string | null
  last_message: string
  summary?: SangonRuntimeSummary
  logs: string[]
}
