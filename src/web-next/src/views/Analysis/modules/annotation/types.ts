/**
 * 功能注释 TypeScript 类型定义
 */

export interface ContigMetaItem {
  id: string;
  description: string;
  length_bp: number;
  gc_content: number;
  selected: boolean;
}

export interface FastaInspectResult {
  success: boolean;
  error?: string;
  num_contigs: number;
  total_length: number;
  gc_content: number;
  contigs: ContigMetaItem[];
}

export interface AnnotationRunParams {
  task_name: string;
  sample_type: 'BACTERIA' | 'PHAGE' | 'VIRUS' | 'GENERAL';
  engine: 'auto' | 'phold' | 'prokka' | 'pharokka' | 'prodigal' | 'builtin';
  fasta_path?: string;
  fasta_content?: string;
  prefix: string;
  genetic_code: number;
  min_contig_len: number;
  threads?: number;
  selected_contigs?: string[];
  enable_waterfall?: boolean;
  enable_homology?: boolean;
  enable_phold?: boolean;
  enable_safety_audit?: boolean;
}

export interface FeatureItem {
  id: string;
  locus_tag: string;
  contig_id?: string | null;
  feature_type: string; // CDS, tRNA, rRNA, tmRNA, CRISPR, misc_feature
  start: number;
  end: number;
  strand: '+' | '-';
  length_bp: number;
  gene_name?: string | null;
  product: string;
  protein_id?: string | null;
  protein_length_aa?: number | null;
  molecular_weight_kda?: number | null;
  translation?: string | null;
  nucleotide_seq?: string | null;
  ec_number?: string | null;
  cog?: string | null;
  category?: string | null;
  source_engine?: string | null;
  evidence_sources?: string[];
  notes?: string | null;
}

export interface AnnotationSummary {
  total_length: number;
  num_contigs: number;
  gc_content: number;
  cds_count: number;
  trna_count: number;
  rrna_count: number;
  tmrna_count: number;
  crispr_count: number;
  other_count: number;
  total_features: number;
  annotated_count?: number;
  hypothetical_count?: number;
  coding_density_pct: number;
  avg_gene_length: number;
  engine_contributions?: Record<string, number>;
  category_distribution?: Record<string, number>;
}

export interface SafetyHitItem {
  cds_id: string;
  target_id: string;
  identity: number;
  evalue: string;
  bitscore: number;
  description?: string;
  source?: string;
}

export interface SafetyAuditResult {
  safety_passed: boolean;
  anti_crispr_status: string;
  risk_warnings: string[];
  amr_genes: SafetyHitItem[];
  virulent_factors: SafetyHitItem[];
  anti_crispr_genes: SafetyHitItem[];
}

export interface QueuedTaskItem {
  task_id: string;
  task_name: string;
  sample_type: string;
  engine: string;
  status: 'queued' | 'running';
  position: number;
  created_at: string;
}

export interface AnnotationQueueStatus {
  is_busy: boolean;
  is_paused: boolean;
  current_task: {
    task_id: string;
    task_name: string;
    status: string;
    progress: number;
    current_step: string;
  } | null;
  waiting_count: number;
  waiting_tasks: QueuedTaskItem[];
}

export interface AnnotationTaskItem {
  task_id: string;
  task_name: string;
  sample_type: string;
  engine: string;
  status: 'pending' | 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  progress: number;
  current_step: string;
  position?: number;
  error_msg?: string | null;
  created_at: string;
  updated_at: string;
  summary?: AnnotationSummary;
  files?: Record<string, string>;
  features?: FeatureItem[];
  feature_count?: number;
  gbk_content?: string;
  safety_audit?: SafetyAuditResult;
  checkv_quality?: string;
}

export interface ProgressEventPayload {
  task_id: string;
  progress: number;
  current_step: string;
  log?: string;
}

