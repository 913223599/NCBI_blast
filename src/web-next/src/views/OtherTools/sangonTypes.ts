/**
 * 生工 16S 模块共享类型定义
 */

export type SangonOrderStatus = 'completed' | 'blasted' | 'extracted' | 'downloaded' | 'pending'

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
}

export type MailDedupStatus = 'created' | 'existing' | 'history_skipped' | 'new' | 'non_sequencing'

export interface ScannedMailItem {
  seq: number
  message_id: string
  subject: string
  date: string
  order_no: string
  dir_name: string
  is_sequencing?: boolean
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
}

/** 订单表分段筛选：全部 / 待下载 / 处理中 / 已完成 */
export type OrderFilterKey = 'all' | 'pending' | 'processing' | 'completed'

/** 订单行主操作 */
export type OrderPrimaryAction = 'claim' | 'download' | 'run' | 'result'

