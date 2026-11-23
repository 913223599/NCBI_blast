export type StructureSourceMode = 'file' | 'paste' | 'annotation' | 'phage_discovery'

export type MorphotypeCode =
  | 'Myoviridae-like'
  | 'Siphoviridae-like'
  | 'Podoviridae-like'
  | 'Non-tailed'
  | 'Incomplete'

export interface StructureCapabilities {
  ready: boolean
  wsl_pyhmmer_ready: boolean
  phold_ready: boolean
  phagetailfinder_ready: boolean
  unified_judge_ready?: boolean
  ai_classifier_ready?: boolean
  structural_hmm_cached: boolean
  structural_hmm_path: string
  all_phrogs_available: boolean
  cpu_cores: number
  safe_workers: number
}

export interface LinkedAnnotationSource {
  task_id: string
  task_name: string
  sample_type: string
  cds_count: number
  total_length: number
  created_at: string
}

export interface LinkedPhageDiscoverySource {
  task_id: string
  task_name: string
  region_count: number
  total_prophage_bp: number
  created_at: string
}

export interface StructureLinkedSources {
  annotations: LinkedAnnotationSource[]
  phage_discoveries: LinkedPhageDiscoverySource[]
}

export interface StructureInspectContig {
  id: string
  length_bp: number
  gc_percent: number
  cds_count: number
  input_type: string
}

export interface StructureInspectResponse {
  success: boolean
  num_contigs: number
  total_length: number
  contigs: StructureInspectContig[]
}

export interface StructureRunForm {
  task_name: string
  source_mode: StructureSourceMode
  fasta_path: string
  fasta_content: string
  source_task_id: string
  region_index?: number
  selected_contigs: string[]
  threads: number
  genetic_code: number
  auto_select_genetic_code?: boolean
  evalue_cutoff: number
  score_cutoff: number
  force_hmm_rescan: boolean
  enable_phold_enhance: boolean
  phold_trigger_mode?: 'auto' | 'always' | 'off'
  enable_ai_classifier?: boolean
  enable_phagetailfinder: boolean
  ptf_accurate_mode: boolean
}

export interface StructureBatchQueuedEntry {
  id: string
  file_name: string
  task_name: string
  source_mode: StructureSourceMode
  fasta_path?: string
  fasta_content?: string
  source_task_id?: string
  region_index?: number
  format_label: string
}

export interface StructureBatchRunPayload {
  items: Array<{
    task_name?: string
    source_mode: StructureSourceMode
    fasta_path?: string
    fasta_content?: string
    source_task_id?: string
    region_index?: number
    selected_contigs?: string[]
  }>
  threads?: number
  genetic_code: number
  auto_select_genetic_code?: boolean
  evalue_cutoff: number
  score_cutoff: number
  force_hmm_rescan: boolean
  enable_phold_enhance: boolean
  phold_trigger_mode?: 'auto' | 'always' | 'off'
  enable_ai_classifier?: boolean
  enable_phagetailfinder: boolean
  ptf_accurate_mode: boolean
  split_phage_regions?: boolean
  split_fasta_records?: boolean
}

export interface PolyXRegion {
  start_aa: number
  end_aa: number
  length_aa: number
  dominant_aa: string
  kind: 'homorun' | 'biased_window'
  snippet: string
}

export interface TandemRepeatUnit {
  start_aa: number
  end_aa: number
  period_aa: number
  copy_number: number
  length_aa: number
  identity: number
  similarity: number
  unit_sample: string
}

export interface HydrophobicSegment {
  start_aa: number
  end_aa: number
  mean_kd: number
}

export interface TmpAnalysisItem {
  locus_tag: string
  contig_id: string
  product: string
  phrog_id: string
  evidence_kind: 'confirmed_tmp' | 'merged_split_tmp' | 'gp29_tail_length' | 'putative_syntenic_tmp'
  merged_loci?: string[]
  confidence: number
  start_bp: number
  end_bp: number
  strand: string
  length_aa: number
  est_tail_length_nm: number
  est_tail_range_nm: number[]
  polyx_count: number
  polyx_total_aa: number
  polyx_fraction_pct: number
  polyx_aa_summary: Record<string, number>
  tr_count: number
  tr_total_aa: number
  tr_fraction_pct: number
  max_tr_period_aa: number
  polyx_regions: PolyXRegion[]
  tandem_repeats: TandemRepeatUnit[]
  hydrophobic_segments: HydrophobicSegment[]
  hydropathy_profile: number[]
  interpretation: string
}

export interface StructureProteinItem {
  locus_tag: string
  contig_id: string
  start: number
  end: number
  strand: string
  length_aa: number
  product: string
  phrog_id: string
  phrog_category: string
  structural_role: string
  role_label_cn: string
  hmm_score: number
  hmm_evalue: number
  evidence_source: string
  ptf_is_tail: boolean
  ptf_tail_prob: number
  ptf_pfam: string
  ptf_pfam_desc: string
  translation: string
}

export interface TailFinderCluster {
  cluster_id: string
  start_bp: number
  end_bp: number
  orf_count: number
  novel_orf_count: number
  mean_tail_prob: number
  loci: string[]
  pfam_hits: string[]
}

export interface ConnectorProfile {
  type_hint:
    | 'Type_1_Sipho_Myo'
    | 'Type_2_Sipho_Podo'
    | 'Type_3_Podoviridae'
    | 'Mixed_or_Uncertain'
    | 'Absent'
  type_label_cn: string
  portal_count: number
  ad1_count: number
  ad2_count: number
  ad3_count: number
  hc1_count: number
  hc2_count: number
  hc3_count: number
  neck1_count: number
  tail_terminator_count: number
  collar_podo_count: number
  general_connector_count: number
}

export interface StructuralModuleMatrix {
  head_packaging_count: number
  connector_count: number
  tail_sheath_count: number
  tail_tube_count: number
  major_tail_count: number
  tail_assembly_chaperone_count: number
  tape_measure_count: number
  tail_tubular_ab_count: number
  internal_virion_count: number
  tail_needle_count: number
  baseplate_count: number
  tail_fiber_rbp_count: number
  lysis_count: number
  integrase_count: number
  non_tailed_marker_count: number
  t6ss_confounder_count: number
}

export interface EvidenceItem {
  rule: string
  target_morphotype: string
  weight: number
  detail: string
  loci: string[]
}

export interface MorphotypePrediction {
  morphotype_code: MorphotypeCode
  morphotype_label_cn: string
  tail_feature_tag: string
  confidence: number
  class_scores: Record<string, number>
  decision_basis: string
  lifestyle_hint: 'Temperate' | 'Lytic' | 'Unknown'
  estimated_tail_length_nm: number | null
  estimated_tail_range_nm: number[]
  evidence_chain: EvidenceItem[]
  warnings: string[]
}

export interface CompletenessAssessment {
  status: 'complete' | 'high_quality' | 'partial_or_truncated' | 'incomplete'
  score: number
  has_dtr?: boolean
  dtr_length_bp?: number
  has_itr?: boolean
  has_intact_head_packaging?: boolean
  has_truncated_long_tail_remnant?: boolean
  allow_negative_podo_inference?: boolean
  sparse_annotation_rescued_orfs?: number
  reasons?: string[]
}

export interface AiMorphotypePrediction {
  predicted_morphotype: 'Myoviridae-like' | 'Siphoviridae-like' | 'Podoviridae-like' | 'Non-tailed'
  confidence: number
  calibrated_probs: Record<string, number>
  mode: 'dual_modal_fusion' | 'ai_deep_only'
  model_version: string
  agreement_with_rules: boolean
  conflict_note: string
  deep_tail_prob_max: number
  deep_head_prob_max: number
}

export interface ContigStructureResult {
  contig_id: string
  length_bp: number
  gc_percent: number
  total_orfs: number
  hmm_matched_orfs: number
  genetic_code_used?: number
  genetic_code_auto_selected?: boolean
  completeness?: CompletenessAssessment | null
  phold_3d_triggered?: boolean
  phold_3d_trigger_reason?: string
  phold_3d_rescued_orfs?: number
  ai_prediction?: AiMorphotypePrediction | null
  prediction: MorphotypePrediction
  connector_profile: ConnectorProfile
  module_matrix: StructuralModuleMatrix
  ptf_tail_protein_count: number
  ptf_tail_clusters: TailFinderCluster[]
  tmp_analyses: TmpAnalysisItem[]
  structural_proteins: StructureProteinItem[]
}

export interface PhageStructureResult {
  task_id: string
  task_name: string
  created_at: string
  source_mode: string
  elapsed_sec: number
  total_bp: number
  contig_count: number
  primary_prediction: MorphotypePrediction
  contigs: ContigStructureResult[]
  summary: {
    primary_morphotype?: MorphotypeCode
    primary_morphotype_cn?: string
    primary_confidence?: number
    estimated_tail_length_nm?: number | null
    contig_count?: number
    total_bp?: number
    total_orfs?: number
    tmp_count?: number
    ptf_tail_protein_count?: number
    ptf_cluster_count?: number
    elapsed_sec?: number
  }
  files: Record<string, string>
}

export interface StructureTaskHistoryItem {
  task_id: string
  task_name: string
  source_mode: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  progress: number
  queue_position?: number
  current_step?: string
  error_msg?: string
  created_at: string
  updated_at?: string
  summary?: PhageStructureResult['summary']
  files?: Record<string, string>
}

export interface StructureQueueSnapshot {
  max_workers?: number
  is_busy?: boolean
  running: string[]
  queued: string[]
  running_count: number
  queued_count: number
  running_tasks?: Array<{ task_id: string; task_name: string; current_step?: string }>
  waiting_tasks?: Array<{ task_id: string; task_name: string; position?: number }>
}

export interface StructureInitialPayload {
  sourceMode: StructureSourceMode
  taskId: string
  taskName: string
  regionIndex?: number
}
