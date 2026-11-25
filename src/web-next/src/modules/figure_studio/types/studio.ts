export type StudioFormatType = 'pdf' | 'svg' | 'png'
export type StudioPaletteType = 'nature' | 'lancet' | 'okabe_ito' | 'monochrome'

export interface StudioFigureFile {
  filename: string
  format: string
  size_bytes: number
  download_url: string
}

export interface StudioRenderResponse {
  render_id: string
  tool_id: string
  title: string
  created_at: number
  figures: StudioFigureFile[]
  metadata: Record<string, unknown>
}

export interface StudioPhyloSourceItem {
  job_id: string
  title: string
  status: string
  leaf_count: number
  has_ani_matrix: boolean
  top_hits_count: number
  has_newick: boolean
  created_at: number
}

export interface StudioAnnotationSourceItem {
  task_id: string
  task_name: string
  sample_type: string
  feature_count: number
  genome_length: number
  created_at: string
}

export interface StudioSourcesResponse {
  phylo_jobs: StudioPhyloSourceItem[]
  annotation_tasks: StudioAnnotationSourceItem[]
  sample_presets: { id: string; label: string }[]
}

export interface ViridicRenderPayload {
  mode: 'viridic_dual' | 'tree_triangle'
  phylo_job_id?: string | null
  use_demo?: boolean
  labels?: string[]
  wgani_matrix?: number[][]
  af_matrix?: number[][]
  genome_lengths?: number[]
  newick?: string | null
  cluster_reorder: boolean
  show_values: boolean
  palette: StudioPaletteType
  title: string
  formats: StudioFormatType[]
  dpi: number
}

export interface GenomeMapRenderPayload {
  mode: 'circular' | 'linear_multitrack'
  annotation_task_id?: string | null
  gbk_path?: string | null
  gbk_content?: string | null
  use_demo?: boolean
  gc_window: number
  show_labels: boolean
  max_labels: number
  show_gc_content: boolean
  show_gc_skew: boolean
  palette: StudioPaletteType
  title?: string | null
  formats: StudioFormatType[]
  dpi: number
}

export interface SyntenyRenderPayload {
  mode: 'lovis4u' | 'clinker'
  annotation_task_ids?: string[]
  gbk_paths?: string[]
  use_demo?: boolean
  min_identity: number
  show_identity_labels: boolean
  show_labels: boolean
  palette: StudioPaletteType
  title: string
  formats: StudioFormatType[]
  dpi: number
}

export interface DiversityRenderPayload {
  ref_annotation_task_id?: string | null
  compare_annotation_task_ids?: string[]
  phylo_job_id?: string | null
  fasta_content?: string | null
  use_demo?: boolean
  window_size: number
  step_size: number
  show_gene_table: boolean
  palette: StudioPaletteType
  title: string
  formats: StudioFormatType[]
  dpi: number
}

export interface NetworkRenderPayload {
  phylo_job_id?: string | null
  annotation_task_ids?: string[]
  edges_csv?: string | null
  use_demo?: boolean
  min_weight: number
  color_by: 'family' | 'host'
  show_waffle: boolean
  show_labels: boolean
  palette: StudioPaletteType
  title: string
  formats: StudioFormatType[]
  dpi: number
}

export interface HostMatrixRenderPayload {
  mode: 'dual_tree_heatmap' | 'sparse_specificity'
  use_demo?: boolean
  matrix_csv?: string | null
  row_labels?: string[]
  col_labels?: string[]
  values?: number[][]
  col_groups?: string[]
  phylo_job_id?: string | null
  cluster_rows: boolean
  cluster_cols: boolean
  show_values: boolean
  palette: StudioPaletteType
  title: string
  formats: StudioFormatType[]
  dpi: number
}
