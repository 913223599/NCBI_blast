/**
 * 泛基因组分析共享领域类型定义
 */
import type { ClusterVariantInfo } from './utils/pangenomeVariants'
import type { ClusteringTreeNode, HierarchicalClusteringResult } from './utils/clustering'

export interface GenePresenceEntry {
  length_aa?: number
  product?: string
  gene_id?: string
  locus_tag?: string
  notes?: string
  start?: number
  end?: number
  strand?: string
  [key: string]: unknown
}

export interface OrthologCluster {
  group_id?: string
  cluster_id?: string
  cluster_name?: string
  representative_product?: string
  representative_annotation?: {
    product?: string
    notes?: string
    [key: string]: unknown
  }
  notes?: string
  category?: string
  sample_count?: number
  presence_map?: Record<string, GenePresenceEntry | boolean | number | string | null | undefined>
  _inferredCategory?: string
  _consensusLen?: number
  _variantMap?: Record<string, ClusterVariantInfo>
  [key: string]: unknown
}

export interface EnrichedOrthologCluster extends OrthologCluster {
  _inferredCategory: string
  _consensusLen: number
  _variantMap: Record<string, ClusterVariantInfo>
}

export interface PhageLifestyleEntry {
  sample_id: string
  lifestyle?: string
  is_safe_for_therapy?: boolean
  has_toxin?: boolean
  has_integrase?: boolean
  anti_crispr_count?: number
  [key: string]: unknown
}

export interface ArmsRaceEntry {
  acr_count?: number
  [key: string]: unknown
}

export interface ClusteringTreeNodeLike {
  id: string
  left?: ClusteringTreeNodeLike | null
  right?: ClusteringTreeNodeLike | null
}

export interface PanGenomicsSampleApiItem {
  sample_id: string
  sample_name: string
  cds_count?: number
  annotated_count?: number
  sample_type?: string
}

export interface PanGenomicsProteinEntry {
  sample_id: string
  locus_tag: string
  product?: string
  length_aa?: number
  lysis_role?: string
  tail_type?: string
  [key: string]: unknown
}

export interface PanGenomicsAnalysisResult {
  task_id?: string
  sample_names: Record<string, string>
  ani_matrix: Record<string, Record<string, number | null>>
  af_matrix?: Record<string, Record<string, number>>
  ani_taxonomy_matrix?: Record<string, Record<string, string>>
  ani_metric_type?: string
  ani_clustering?: HierarchicalClusteringResult | null
  tail_identity_matrix?: Record<string, Record<string, number>>
  lysis_identity_matrix?: Record<string, Record<string, number>>
  clusters: OrthologCluster[]
  lifestyles: PhageLifestyleEntry[]
  arms_race_matrix?: Record<string, ArmsRaceEntry>
  tail_proteins?: PanGenomicsProteinEntry[]
  lysis_proteins?: PanGenomicsProteinEntry[]
  amg_genes?: Array<Record<string, unknown>>
  amg_pathway_distributions?: Record<string, Record<string, number>>
  scientific_synthesis_report?: Record<string, unknown> | null
  [key: string]: unknown
}

export type { ClusteringTreeNode, HierarchicalClusteringResult, ClusterVariantInfo }
