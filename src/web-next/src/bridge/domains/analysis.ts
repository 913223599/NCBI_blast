/**
 * 桥接域模块：组装后分析（比对对比、功能注释、前噬菌体发现、噬菌体结构预测、泛基因组、Sanger 峰图）
 */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { API_BASE, apiDelete, apiGet, apiPost } from '../httpClient'
import { createLogger } from '../../utils/logger'

const log = createLogger('Bridge:Analysis')

export const analysisDomain = {
  async fetchAnalysisHistory() {
    return await apiGet('/api/analysis/history')
  },

  async deleteAnalysisHistory(recordId: number) {
    return await apiDelete(`/api/analysis/history/${recordId}`)
  },

  async fetchAnalysisDetail(recordId: number) {
    return await apiGet(`/api/analysis/history/${recordId}`)
  },

  async run_comparison_pipeline(payload: string): Promise<string> {
    const result = await apiPost('/api/analysis/comparison/run', JSON.parse(payload))
    return JSON.stringify(result)
  },

  async get_comparison_history() {
    return await apiGet('/api/analysis/comparison/history')
  },

  async delete_comparison_task(task_id: string) {
    return await apiDelete(`/api/analysis/comparison/${task_id}`)
  },

  async get_comparison_task_results(task_id: string) {
    return await apiGet(`/api/analysis/comparison/${task_id}/results`)
  },

  async inspect_annotation_fasta(payload: { fasta_path?: string; fasta_content?: string }): Promise<any> {
    return await apiPost('/api/analysis/annotation/inspect', payload)
  },

  async run_annotation_task(payload: any): Promise<any> {
    return await apiPost('/api/analysis/annotation/run', payload)
  },

  async get_annotation_history(limit: number = 50): Promise<any> {
    return await apiGet(`/api/analysis/annotation/history?limit=${limit}`)
  },

  async get_annotation_result(taskId: string): Promise<any> {
    return await apiGet(`/api/analysis/annotation/${taskId}/result`)
  },

  async get_annotation_queue_status(): Promise<any> {
    return await apiGet('/api/analysis/annotation/queue/status')
  },

  async reorder_annotation_queue(taskIds: string[]): Promise<any> {
    return await apiPost('/api/analysis/annotation/queue/reorder', { task_ids: taskIds })
  },

  async delete_annotation_task(taskId: string): Promise<any> {
    return await apiDelete(`/api/analysis/annotation/${taskId}`)
  },

  async cancel_annotation_task(taskId: string): Promise<any> {
    return await apiPost(`/api/analysis/annotation/${taskId}/cancel`, {})
  },

  async request_directory_select(title: string = '选择目录'): Promise<string | null> {
    const electron = window.electronAPI
    if (!electron?.openFileDialog) return null
    const paths = await electron.openFileDialog({
      title,
      properties: ['openDirectory'],
    })
    return paths && paths.length > 0 ? (paths[0] ?? null) : null
  },

  async get_phage_discovery_models(): Promise<any> {
    return await apiGet('/api/analysis/phage_discovery/models')
  },

  async save_phage_discovery_config(payload: {
    models_root?: string
    default_model_dir?: string
    blast_db?: string
  }): Promise<any> {
    return await apiPost('/api/analysis/phage_discovery/config', payload)
  },

  async inspect_phage_discovery_fasta(payload: {
    fasta_path?: string
    fasta_content?: string
  }): Promise<any> {
    return await apiPost('/api/analysis/phage_discovery/inspect', payload)
  },

  async run_phage_discovery_task(payload: any): Promise<any> {
    return await apiPost('/api/analysis/phage_discovery/run', payload)
  },

  async get_phage_discovery_queue_status(): Promise<any> {
    return await apiGet('/api/analysis/phage_discovery/queue/status')
  },

  async get_phage_discovery_history(limit: number = 100): Promise<any> {
    return await apiGet(`/api/analysis/phage_discovery/history?limit=${limit}`)
  },

  async get_phage_discovery_result(taskId: string): Promise<any> {
    return await apiGet(`/api/analysis/phage_discovery/${encodeURIComponent(taskId)}/result`)
  },

  async get_phage_discovery_region_gbk(taskId: string, regionIndex: number): Promise<any> {
    return await apiGet(
      `/api/analysis/phage_discovery/${encodeURIComponent(taskId)}/region/${regionIndex}/gbk`
    )
  },

  async get_phage_discovery_overlay(taskId: string, contigId?: string): Promise<any> {
    const query = contigId ? `?contig_id=${encodeURIComponent(contigId)}` : ''
    return await apiGet(
      `/api/analysis/phage_discovery/${encodeURIComponent(taskId)}/overlay${query}`
    )
  },

  async get_phage_discovery_overlay_gbk(taskId: string, contigId?: string): Promise<any> {
    const query = contigId ? `?contig_id=${encodeURIComponent(contigId)}` : ''
    return await apiGet(
      `/api/analysis/phage_discovery/${encodeURIComponent(taskId)}/overlay-gbk${query}`
    )
  },

  async get_phage_discovery_fasta_text(taskId: string, regionIndex?: number): Promise<any> {
    const query = regionIndex !== undefined ? `?region_index=${regionIndex}` : ''
    return await apiGet(
      `/api/analysis/phage_discovery/${encodeURIComponent(taskId)}/fasta-text${query}`
    )
  },

  async cancel_phage_discovery_task(taskId: string): Promise<any> {
    return await apiPost(`/api/analysis/phage_discovery/${encodeURIComponent(taskId)}/cancel`)
  },

  async delete_phage_discovery_task(taskId: string): Promise<any> {
    return await apiDelete(`/api/analysis/phage_discovery/${encodeURIComponent(taskId)}`)
  },

  async open_phage_discovery_folder(taskId: string): Promise<any> {
    return await apiPost(`/api/analysis/phage_discovery/${encodeURIComponent(taskId)}/open-folder`)
  },

  get_phage_discovery_download_url(taskId: string, fileType: 'fasta' | 'tsv' | 'gff3' | 'gbk'): string {
    return `${API_BASE}/api/analysis/phage_discovery/${encodeURIComponent(taskId)}/download/${fileType}`
  },

  async get_phage_structure_capabilities(): Promise<any> {
    return await apiGet('/api/analysis/phage_structure/capabilities')
  },

  async get_phage_structure_sources(): Promise<any> {
    return await apiGet('/api/analysis/phage_structure/sources')
  },

  async inspect_phage_structure_input(payload: {
    source_mode: 'file' | 'paste' | 'annotation' | 'phage_discovery'
    fasta_path?: string
    fasta_content?: string
    source_task_id?: string
    region_index?: number
  }): Promise<any> {
    return await apiPost('/api/analysis/phage_structure/inspect', payload)
  },

  async run_phage_structure_task(payload: any): Promise<any> {
    return await apiPost('/api/analysis/phage_structure/run', payload)
  },

  async run_phage_structure_batch(payload: any): Promise<any> {
    return await apiPost('/api/analysis/phage_structure/batch', payload)
  },

  async upload_files_batch(files: File[]): Promise<any[]> {
    try {
      const formData = new FormData()
      for (const file of files) {
        formData.append('files', file)
      }
      const response = await fetch(`${API_BASE}/api/common/upload_batch`, {
        method: 'POST',
        body: formData,
      })
      const data = await response.json()
      return Array.isArray(data) ? data : []
    } catch (err) {
      log.error('批量上传失败:', err)
      return []
    }
  },

  async get_phage_structure_queue_status(): Promise<any> {
    return await apiGet('/api/analysis/phage_structure/queue/status')
  },

  async get_phage_structure_history(limit: number = 100): Promise<any> {
    return await apiGet(`/api/analysis/phage_structure/history?limit=${limit}`)
  },

  async get_phage_structure_result(taskId: string): Promise<any> {
    return await apiGet(`/api/analysis/phage_structure/${encodeURIComponent(taskId)}/result`)
  },

  async get_phage_structure_gbk(taskId: string): Promise<any> {
    return await apiGet(`/api/analysis/phage_structure/${encodeURIComponent(taskId)}/gbk`)
  },

  async cancel_phage_structure_task(taskId: string): Promise<any> {
    return await apiPost(`/api/analysis/phage_structure/${encodeURIComponent(taskId)}/cancel`)
  },

  async delete_phage_structure_task(taskId: string): Promise<any> {
    return await apiDelete(`/api/analysis/phage_structure/${encodeURIComponent(taskId)}`)
  },

  async open_phage_structure_folder(taskId: string): Promise<any> {
    return await apiPost(`/api/analysis/phage_structure/${encodeURIComponent(taskId)}/open-folder`)
  },

  get_phage_structure_download_url(
    taskId: string,
    fileType: 'json' | 'summary_tsv' | 'features_tsv' | 'tmp_tsv' | 'gbk'
  ): string {
    return `${API_BASE}/api/analysis/phage_structure/${encodeURIComponent(taskId)}/download/${fileType}`
  },

  async get_pan_genomics_samples(): Promise<any> {
    return await apiGet('/api/analysis/pan_genomics/samples')
  },

  async run_pan_genomics(params: any): Promise<any> {
    return await apiPost('/api/analysis/pan_genomics/run', params)
  },

  async get_pan_genomics_result(taskId: string): Promise<any> {
    return await apiGet(`/api/analysis/pan_genomics/${taskId}/result`)
  },

  async analyze_sanger_traces(filePaths: string[], trimThreshold: number = 20): Promise<any> {
    return await apiPost('/api/sanger/trace/analyze_path', {
      file_paths: filePaths,
      trim_threshold: trimThreshold,
    })
  },

  async export_sanger_fasta(samples: any[], mode: string = 'alleles'): Promise<any> {
    return await apiPost('/api/sanger/trace/export_fasta', {
      samples,
      mode,
    })
  },

  async create_blast_from_traces(payload: {
    task_name: string
    sequences: { id: string; sequence: string }[]
    program?: string
    database?: string
    evalue?: number
    max_hits?: number
    threads?: number
    filter_low_complexity?: boolean
    matrix?: string
    gap_open?: number
    gap_extend?: number
  }): Promise<any> {
    return await apiPost('/api/sanger/trace/send_to_blast', payload)
  },
}
