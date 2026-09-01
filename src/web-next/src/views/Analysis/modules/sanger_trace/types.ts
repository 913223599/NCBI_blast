/**
 * Sanger Trace & Peak Deconvolution Types
 */

export type DiagnosisCategory = 
  | 'CLEAN_SINGLE'
  | 'HETERO_INDEL'
  | 'MIXED_TEMPLATE'
  | 'PARTIAL_POLYMORPHISM'
  | 'LOW_SNR';

export interface PeakDetail {
  index: number;
  pos: number;
  orig_base: string;
  primary_base: string;
  secondary_base: string;
  iupac_base: string;
  primary_val: number;
  secondary_val: number;
  ratio: number;
  quality: number;
  is_trimmed: boolean;
}

export interface DeconvAllele {
  allele_id: string;
  label: string;
  sequence: string;
  length: number;
  type: 'primary' | 'iupac' | 'indel_primary' | 'indel_secondary';
}

export interface TraceSummary {
  total_points: number;
  sampled_points: number;
  step: number;
  traces: {
    A: number[];
    C: number[];
    G: number[];
    T: number[];
  };
}

export interface SampleDiagnosis {
  category: DiagnosisCategory;
  description: string;
  action: string;
  is_indel: boolean;
  indel_shift: number;
  indel_match_rate: number;
}

export interface SampleDeconvResult {
  success: boolean;
  filename: string;
  sample_id: string;
  total_len: number;
  trimmed_len: number;
  trim_start: number;
  trim_end: number;
  avg_quality: number;
  avg_secondary_ratio: number;
  high_secondary_pct: number;
  machine_diff_count: number;
  diagnosis: SampleDiagnosis;
  sequences: {
    original_machine: string;
    primary_clean: string;
    iupac_consensus: string;
    alleles: DeconvAllele[];
  };
  peaks: PeakDetail[];
  trace_summary: TraceSummary;
  error?: string;
}

export interface BatchAnalysisResponse {
  success: boolean;
  archive_name?: string;
  total_samples: number;
  success_count: number;
  categories: Record<string, number>;
  samples: SampleDeconvResult[];
  error?: string;
}
