export type TrackType = 'auto' | 'genome' | 'gene' | 'phage_taxonomy'
export type MsaToolType = 'none' | 'mafft' | 'muscle' | 'clustalo'
export type MsaStrategyType = 'auto' | 'fast' | 'accurate' | 'linsi' | 'einsi'
export type TrimModeType = 'none' | 'gap' | 'kpic' | 'kpic_smart_gap' | 'smart_gap'
export type AniEngineType = 'viridic_blastn' | 'fastani' | 'skani' | 'mash'
export type MarkerModeType = 'terl' | 'proteome'
export type SamplingModeType = 'focused' | 'macro_family_host'
export type TreeEngineType = 'bionj' | 'nj' | 'fasttree' | 'iqtree' | 'mrbayes'
export type JobStatusType = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
export type StageStatusType = 'pending' | 'running' | 'completed' | 'cached' | 'skipped' | 'failed' | 'cancelled'
export type WorkbenchMode = 'phage_taxonomy' | 'general'

export interface DeliveryScopeConfig {
  target_rank: 'species' | 'genus' | 'family_order'
  sampling_mode: SamplingModeType
  ani_species_threshold: number
  ani_genus_threshold: number
  ref_max_count: number
  ictv_reps_per_genus: number
  max_target_genera: number
  outgroup_count: number
  derep_ani: number
  derep_min_len: number
  treemmer_target: number
  treemmer_min_cluster: number
  checkv_min_completeness: number
  enable_checkv: boolean
  local_ref_dir: string | null
  outgroup_ids: string[]
  mash_top_k: number
}

export interface AniHitRecord {
  accession: string
  description: string
  mash_distance: number | null
  mash_ani: number | null
  wg_ani: number
  aligned_ani: number
  af_query: number
  af_ref: number
  genome_length: number
  gc_content: number
  host: string
  genus: string
  subfamily: string
  family: string
  order: string
  class_name: string
  realm: string
  classification_call:
    | 'same_species'
    | 'same_genus_new_species'
    | 'genus_boundary_ambiguous'
    | 'novel_genus_candidate'
  mosaic_warning: boolean
}

export interface AniScreenResult {
  query_ids: string[]
  engine_used: string
  engine_version: string
  command_preview: string
  top_hits: AniHitRecord[]
  matrix_labels: string[]
  wgani_matrix: number[][]
  af_matrix: number[][]
  candidate_genera: string[]
  candidate_families: string[]
  summary_call: string
  ambiguous_zone: boolean
  warnings: string[]
  recommended_outgroup_accessions: string[]
}

export interface ReferenceCandidate {
  accession: string
  name: string
  description?: string
  role: 'query' | 'ictv_rep' | 'neighbor' | 'outgroup'
  source: 'workspace' | 'inphared_cache' | 'ncbi_download' | 'local_dir'
  selected: boolean
  genome_length: number
  gc_content: number
  host: string
  genus: string
  family: string
  order: string
  wg_ani: number | null
  completeness: number | null
  local_path: string | null
  is_ictv_classified: boolean
}

export interface MarkerHitItem {
  sample_id: string
  protein_id: string
  phrog_id: string
  evalue: number | null
  bitscore: number | null
  aa_length: number
  status: 'extracted' | 'missing' | 'multi_copy'
  notes: string
}

export interface MarkerExtractionReport {
  mode: MarkerModeType
  total_genomes: number
  extracted_count: number
  missing_ids: string[]
  tool_used: string
  tool_version: string
  hits: MarkerHitItem[]
}

export interface QcCheckItem {
  key: string
  title: string
  criterion: string
  status: 'pass' | 'warn' | 'fail'
  observed: string
  explanation: string
}

export interface DeliveryQcReport {
  checks: QcCheckItem[]
  overall_status: 'pass' | 'warn' | 'fail'
  ani_tree_consistent: boolean
  consistency_note: string
  best_model: string | null
  best_model_bic: number | null
  iqtree_command: string | null
  conclusion_zh: string
  conclusion_en: string
  itol_files: string[]
}

export interface NodeMetadata {
  role?: 'query' | 'ictv_rep' | 'neighbor' | 'outgroup'
  description?: string
  genus?: string
  family?: string
  host?: string
  genome_length?: number
  gc_content?: number
  wg_ani?: number | null
}

export interface SequenceProfile {
  sequence_count: number
  unique_id_count: number
  duplicate_id_count: number
  mol_type: 'dna' | 'protein'
  min_length: number
  median_length: number
  max_length: number
  total_bases: number
  length_cv: number
  is_aligned: boolean
  has_gaps: boolean
  content_hash: string
  recommended_track: 'genome' | 'gene'
  recommended_msa: MsaToolType
  recommended_engine: TreeEngineType
  warnings: string[]
  sample_ids: string[]
}

export interface ToolDescriptor {
  name: string
  available: boolean
  runtime: 'native' | 'wsl' | 'python' | 'none'
  path: string
  version: string
  notes: string
}

export interface EngineCapabilities {
  engine: TreeEngineType
  label: string
  available: boolean
  supports_dna: boolean
  supports_protein: boolean
  supports_bootstrap: boolean
  min_bootstrap: number
  max_bootstrap: number
  bootstrap_step: number
  models_dna: string[]
  models_protein: string[]
  notes: string
}

export interface CapabilitiesResponse {
  cpu_logical_cores: number
  cpu_safe_max: number
  cpu_default: number
  gpu_available: boolean
  gpu_name: string
  gpu_total_vram_mb: number
  gpu_free_vram_mb: number
  wsl_available: boolean
  wsl_distro: string
  tools: Record<string, ToolDescriptor>
  engines: Record<string, EngineCapabilities>
}

export interface PhyloJobConfig {
  title?: string
  files?: string[]
  track: TrackType
  msa: MsaToolType
  msa_strategy: MsaStrategyType
  trim_mode: TrimModeType
  trim_gap_threshold: number | null
  engine: TreeEngineType
  model: string
  bootstrap: number
  iqtree_bnni: boolean
  iqtree_alrt: number
  iqtree_seed: number
  outgroup_ids: string[]
  threads: number
  use_gpu: boolean
  mash_kmer: number
  mash_sketch: number
  mrbayes_ngen: number
  midpoint_root: boolean
  use_cache: boolean
  phage_scope?: DeliveryScopeConfig | null
  marker_mode: MarkerModeType
  ani_engine: AniEngineType
  selected_references: ReferenceCandidate[]
  precomputed_ani_result?: AniScreenResult | null
}

export interface StageState {
  name: string
  label: string
  status: StageStatusType
  progress: number
  cached: boolean
  elapsed_sec: number
  message: string
  artifact_path?: string | null
}

export interface TreeMetrics {
  leaf_count: number
  internal_count: number
  total_branch_length: number
  diameter: number
  mean_support: number | null
  min_support: number | null
  max_support: number | null
  mean_alrt?: number | null
  strong_ufboot_ratio?: number | null
  has_dual_support?: boolean
  best_model?: string | null
  best_model_bic?: number | null
  is_rooted: boolean
}

export interface WorkspaceFileItem {
  name: string
  size: number
  modified_at: number
  ext: string
}

export interface WorkspaceInfo {
  files: WorkspaceFileItem[]
  profile: SequenceProfile | null
}

export interface PhyloJobRecord {
  job_id: string
  title: string
  status: JobStatusType
  resolved_track: 'genome' | 'gene' | 'phage_taxonomy'
  config: PhyloJobConfig
  profile: SequenceProfile | null
  stages: StageState[]
  progress: number
  current_stage: string
  message: string
  error: string | null
  created_at: number
  started_at: number | null
  finished_at: number | null
  elapsed_sec: number
  newick: string | null
  metrics: TreeMetrics | null
  job_dir: string
  artifacts: Record<string, unknown>
  ani_result?: AniScreenResult | null
  marker_report?: MarkerExtractionReport | null
  qc_report?: DeliveryQcReport | null
  node_metadata?: Record<string, NodeMetadata>
}

export type LayoutMode = 'rect' | 'circular' | 'unrooted'
export type SortMode = 'original' | 'ladder-right' | 'ladder-left' | 'taxonomic' | 'distance'
export type LabelFormatType = 'name_acc' | 'name' | 'accession'

export interface TreeVisualSettings {
  layout: LayoutMode
  useBranchLengths: boolean
  showLabels: boolean
  labelFormat: LabelFormatType
  showSupport: boolean
  supportThreshold: number
  fontSize: number
  rowSpacing: number
  sortMode: SortMode
  searchQuery: string
  showMetadataStrips: boolean
  highlightStrongUfboot: boolean
}

export type PublicationLayoutType = 'circular' | 'rectangular'
export type PublicationFormatType = 'pdf' | 'svg' | 'png'
export type PublicationSupportStyle = 'dots' | 'text' | 'both' | 'none'
export type ItolExportFormatType = 'pdf' | 'svg' | 'png' | 'eps'
export type ItolDisplayModeType = 'rectangular' | 'circular' | 'unrooted'

export interface PublicationFigureRequest {
  layout: PublicationLayoutType
  formats: PublicationFormatType[]
  dpi: number
  use_branch_lengths: boolean
  support_style: PublicationSupportStyle
  show_genus_strip: boolean
  show_genome_length: boolean
  show_gc_bar: boolean
  ladderize: boolean
  label_format: LabelFormatType
  title?: string | null
}

export interface PublicationFigureItem {
  filename: string
  format: string
  layout: string
  size_bytes: number
  download_url: string
}

export interface PublicationRenderResponse {
  job_id: string
  layout: string
  figures: PublicationFigureItem[]
}

export interface ItolPullRequest {
  tree_id_or_url: string
  format: ItolExportFormatType
  display_mode: ItolDisplayModeType
  bootstrap_display: boolean
  ignore_branch_length: boolean
  datasets_visible: string
  dpi: number
}

export interface ItolPullResponse {
  job_id: string
  tree_id: string
  filename: string
  format: string
  size_bytes: number
  download_url: string
  itol_tree_url: string
}
