/**
 * 基因组组装 (Assembly) TypeScript 类型定义
 */

export interface AssemblyStats {
  total_length: number;
  contigs: number;
  n50: number;
  gc_percent: number;
  avg_depth: number;
  is_circular: boolean;
}

export interface AssemblyTaskItem {
  id: string;
  name: string;
  sample_id?: string;
  sample_type?: string;
  tech?: 'ILLUMINA' | 'NANOPORE' | 'PACBIO_HIFI' | 'MGI' | string;
  status: 'pending' | 'queued' | 'running' | 'completed' | 'failed' | 'aborted' | string;
  last_step?: string;
  progress: number;
  config?: any;
  results?: AssemblyStats | null;
  created_at: number;
  updated_at: number;
  duration_seconds?: number;
  queue_position?: number;
}

export interface AssemblyRunParams {
  name: string;
  sample_type: 'BACTERIA' | 'PHAGE' | 'VIRUS' | 'METAGENOME';
  tech: 'ILLUMINA' | 'NANOPORE' | 'PACBIO_HIFI';
  mode: 'isolate' | 'metagenome';
  r1_path: string;
  r2_path?: string;
  r1_name?: string;
  r2_name?: string;
  threads?: number;
  min_read_length?: number;
}

export interface AssemblyResultData {
  task_id: string;
  name: string;
  status: string;
  stats: AssemblyStats;
  fasta_exists: boolean;
  fasta_path?: string | null;
  fasta_size_bytes?: number;
  created_at?: number;
  updated_at?: number;
  duration_seconds?: number;
}

export interface AssemblyQueueStatus {
  running_task: AssemblyTaskItem | null;
  waiting_count: number;
  waiting_tasks: AssemblyTaskItem[];
  is_busy: boolean;
}
