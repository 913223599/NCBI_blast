/**
 * 功能注释 TypeScript 类型定义
 */

export interface AnnotationRunParams {
  task_name: string;
  sample_type: 'BACTERIA' | 'PHAGE' | 'VIRUS' | 'GENERAL';
  engine: 'auto' | 'prokka' | 'pharokka' | 'prodigal' | 'builtin';
  fasta_path?: string;
  fasta_content?: string;
  prefix: string;
  genetic_code: number;
  min_contig_len: number;
  threads?: number;
}

export interface FeatureItem {
  id: string;
  locus_tag: string;
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
  coding_density_pct: number;
  avg_gene_length: number;
}

export interface AnnotationTaskItem {
  task_id: string;
  task_name: string;
  sample_type: string;
  engine: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  progress: number;
  current_step: string;
  error_msg?: string | null;
  created_at: string;
  updated_at: string;
  summary?: AnnotationSummary;
  files?: Record<string, string>;
  features?: FeatureItem[];
  feature_count?: number;
  gbk_content?: string;
}

export interface ProgressEventPayload {
  task_id: string;
  progress: number;
  current_step: string;
  log?: string;
}
