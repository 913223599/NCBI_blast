/**
 * 核心蛋白跨样本比对模块类型定义
 */

export interface ComparableTaskItem {
  task_id: string;
  task_name: string;
  sample_type: string;
  engine: string;
  cds_count: number;
  total_length: number;
  created_at: string;
}

export interface MutationSiteItem {
  pos: number;
  ref_aa: string;
  alt_aa: string;
  impact_type?: string;
  impact_label?: string;
  description: string;
}

export interface RegionDomainItem {
  name: string;
  start: number;
  end: number;
  length: number;
  identity_pct: number;
  mutation_count: number;
  conservative_count: number;
  radical_count: number;
  status: 'conserved' | 'moderate' | 'hypervariable';
}

export interface ProteinComparisonRowItem {
  category: string;
  category_label: string;
  
  sample_a_id: string;
  sample_a_tag: string;
  sample_a_product: string;
  sample_a_len: number;
  sample_a_range: string;
  sample_a_strand: string;
  sample_a_seq: string;
  
  sample_b_id?: string;
  sample_b_tag?: string;
  sample_b_product?: string;
  sample_b_len?: number;
  sample_b_range?: string;
  sample_b_strand?: string;
  sample_b_seq?: string;
  
  match_status: 'identical' | 'highly_conserved' | 'divergent' | 'unique_a' | 'unique_b';
  identity_pct: number;
  diff_count: number;
  mutations: MutationSiteItem[];
  length_diff: number;
  notes?: string;

  aligned_seq_a?: string;
  aligned_markup?: string;
  aligned_seq_b?: string;
  conservative_mutation_cnt?: number;
  radical_mutation_cnt?: number;
  indel_cnt?: number;
  hotspot_conclusion?: string;
  region_domains?: RegionDomainItem[];
}

export interface ProteinComparisonResultPayload {
  sample_a_name: string;
  sample_b_name: string;
  sample_a_total_cds: number;
  sample_b_total_cds: number;
  total_compared_pairs: number;
  identical_count: number;
  conserved_count: number;
  divergent_count: number;
  unique_a_count: number;
  unique_b_count: number;
  average_identity_pct: number;
  category_summary: Record<string, { total: number; identical: number; conserved: number; divergent: number; unique: number }>;
  rows: ProteinComparisonRowItem[];
}
