/**
 * 前噬菌体与噬菌体智能发现工作台 TypeScript 类型定义 (Student V4.2)
 */

export interface PhageDecoderDefaults {
  seed_threshold: number
  extend_threshold: number
  sub_threshold: number
  merge_gap_bp: number
  min_region_bp: number
}

export interface PhageModelInfo {
  model_id: string
  label: string
  version: string
  priority: number
  path: string
  weights_file: string
  params: number
  has_context_refiner: boolean
  has_subbin_refiner: boolean
  decoder_defaults: PhageDecoderDefaults
  recommended: boolean
}

export interface PhageComputeEnv {
  cpu_cores: number
  safe_workers: number
  cuda_available: boolean
  gpu_name: string
  gpu_vram_gb: number
  default_device: 'cuda' | 'cpu'
}

export interface PhageProteinGateStatus {
  ready: boolean
  blastp_bin: string
  blast_db: string
}

export interface PhageCapabilities {
  models: PhageModelInfo[]
  compute: PhageComputeEnv
  protein_gate: PhageProteinGateStatus
  has_model: boolean
}

export interface PhageContigInspectItem {
  id: string
  length: number
  gc_percent: number
  description?: string
}

export interface PhageProfileBin {
  start_bp: number
  end_bp: number
  prob: number
  in_region: boolean
}

export interface PhageRegionItem {
  index: number
  region_id: string
  contig_id: string
  start_bp: number
  end_bp: number
  start_1based: number
  end_1based: number
  length_bp: number
  peak_score: number
  mean_score: number
  window_count: number
  gc_percent: number
  orf_count: number
  completeness_key: string
  completeness_label: string
  gate_decision: string
  gate_tier: string
  hallmark_hits: number
  non_amg_hits: number
  transposase_hits: number
  amg_hits: number
  matched_titles: string[]
  profile: PhageProfileBin[]
  gbk_file: string
}

export interface PhageRejectedCandidate {
  contig_id: string
  start_bp: number
  end_bp: number
  length_bp: number
  peak_score: number
  hallmark_hits: number
  transposase_hits: number
  matched_titles: string[]
}

export interface PhageBaseTrackBin {
  start_bp: number
  end_bp: number
  gc_pct: number
  gc_skew: number
  gene_count: number
}

export interface PhageScoreTrackBin {
  start_bp: number
  end_bp: number
  max_prob: number
  mean_prob: number
}

export interface PhageBaseFeature {
  index: number
  type: string
  start_bp: number
  end_bp: number
  strand: number
  locus_tag: string
  gene: string
  product: string
  note: string
  source: string
  overlay_region_id: string | null
  in_prophage: boolean
}

export interface PhageContigOverlayData {
  contig_id: string
  length_bp: number
  gc_percent: number
  source_format: string
  base_tracks: PhageBaseTrackBin[]
  score_tracks: PhageScoreTrackBin[]
  base_features: PhageBaseFeature[]
  regions: PhageRegionItem[]
  rejected_candidates: PhageRejectedCandidate[]
  contigs?: PhageContigSummary[]
}

export interface PhageScanSummary {
  contig_count: number
  total_bp: number
  total_windows: number
  raw_region_count: number
  region_count: number
  rejected_count: number
  total_prophage_bp: number
  prophage_fraction_pct: number
  source_format?: string
  model_id: string
  model_version: string
  model_label: string
  device_used: string
  apply_protein_gate: boolean
  timings_sec: Record<string, number>
}

export interface PhageContigSummary {
  id: string
  length: number
  gc_percent: number
  hit_count: number
  source_format?: string
  base_feature_count?: number
  overlay_file?: string
}

export interface PhageScanResultPayload {
  task_id: string
  task_name: string
  summary: PhageScanSummary
  contigs: PhageContigSummary[]
  regions: PhageRegionItem[]
  rejected_candidates: PhageRejectedCandidate[]
  files: Record<string, string>
}

export interface PhageTaskRecord {
  task_id: string
  task_name: string
  model_id: string
  model_version: string
  device: string
  apply_protein_gate: boolean
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  progress: number
  current_step: string
  error_msg?: string
  created_at: string
  updated_at: string
  summary: Partial<PhageScanSummary>
  files: Record<string, string>
  result_path: string
}

export interface PhageQueueSnapshot {
  max_workers: number
  running: string[]
  queued: string[]
  running_count: number
  queued_count: number
}

export interface PhageLogItem {
  time: string
  line: string
  level: string
}

export interface PhageScanForm {
  task_name: string
  fasta_path: string
  fasta_content: string
  selected_contigs: string[]
  custom_model_dir: string
  device: 'auto' | 'cuda' | 'cpu'
  workers: number
  apply_protein_gate: boolean
  blast_db: string
  seed_threshold: number
  extend_threshold: number
  sub_threshold: number
  merge_gap_bp: number
  min_region_bp: number
}

