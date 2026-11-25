import { API_BASE, apiDelete, apiGet, apiPost } from '../../../bridge/electron-bridge'
import { onEvent } from '../../../bridge'
import { buildFigureUrlQuery, type FigureUrlOptions } from '../core/FigurePreviewHelper'
import type {
  AniEngineType,
  AniScreenResult,
  CapabilitiesResponse,
  DeliveryQcReport,
  DeliveryScopeConfig,
  ItolPullRequest,
  ItolPullResponse,
  LabelFormatType,
  PhyloJobConfig,
  PhyloJobRecord,
  PublicationFigureRequest,
  PublicationRenderResponse,
  ReferenceCandidate,
  SequenceProfile,
  WorkspaceInfo,
} from '../types/phylo'

async function checkOk<T>(promise: Promise<unknown>, fallbackMsg: string): Promise<T> {
  const res = (await promise) as Record<string, unknown> | null | undefined
  if (!res) {
    throw new Error(fallbackMsg)
  }
  if (res.success === false) {
    throw new Error(res.error ? String(res.error) : fallbackMsg)
  }
  if (typeof res.detail === 'string' && !res.job_id && !res.files && !res.engines) {
    throw new Error(res.detail)
  }
  return res as T
}

export const phyloApi = {
  async getCapabilities(refresh = false): Promise<CapabilitiesResponse> {
    return checkOk<CapabilitiesResponse>(
      apiGet(`/api/phylo/capabilities?refresh=${refresh}`),
      '获取计算能力失败'
    )
  },

  async getWorkspace(): Promise<WorkspaceInfo> {
    return checkOk<WorkspaceInfo>(apiGet('/api/phylo/workspace'), '加载工作区失败')
  },

  async addWorkspaceFiles(paths: string[]): Promise<WorkspaceInfo> {
    return checkOk<WorkspaceInfo>(
      apiPost('/api/phylo/workspace/add', { paths }),
      '导入序列文件失败'
    )
  },

  async pasteSequences(content: string, filename?: string): Promise<WorkspaceInfo> {
    return checkOk<WorkspaceInfo>(
      apiPost('/api/phylo/workspace/paste', { content, filename }),
      '导入粘贴序列失败'
    )
  },

  async removeWorkspaceFile(filename: string): Promise<WorkspaceInfo> {
    return checkOk<WorkspaceInfo>(
      apiDelete(`/api/phylo/workspace/${encodeURIComponent(filename)}`),
      '移除文件失败'
    )
  },

  async clearWorkspace(): Promise<WorkspaceInfo> {
    return checkOk<WorkspaceInfo>(apiDelete('/api/phylo/workspace'), '清空工作区失败')
  },

  async profileWorkspace(files?: string[]): Promise<SequenceProfile> {
    return checkOk<SequenceProfile>(
      apiPost('/api/phylo/profile', { files }),
      '计算序列画像失败'
    )
  },

  async phageAniScreen(payload: {
    files?: string[]
    scope?: DeliveryScopeConfig
    ani_engine: AniEngineType
    threads?: number
  }): Promise<AniScreenResult> {
    return checkOk<AniScreenResult>(
      apiPost('/api/phylo/phage/ani-screen', payload),
      '全基因组 ANI 预判失败'
    )
  },

  async phageCurateRefs(payload: {
    files?: string[]
    ani_result?: AniScreenResult | null
    scope?: DeliveryScopeConfig
  }): Promise<ReferenceCandidate[]> {
    const res = await checkOk<ReferenceCandidate[]>(
      apiPost('/api/phylo/phage/curate-refs', payload),
      '构建候选参考集失败'
    )
    return Array.isArray(res) ? res : []
  },

  async submitJob(config: PhyloJobConfig): Promise<PhyloJobRecord> {
    return checkOk<PhyloJobRecord>(apiPost('/api/phylo/jobs', config), '启动分析任务失败')
  },

  async listJobs(limit = 50): Promise<PhyloJobRecord[]> {
    const res = await checkOk<{ jobs: PhyloJobRecord[] }>(
      apiGet(`/api/phylo/jobs?limit=${limit}`),
      '获取历史任务失败'
    )
    return res.jobs || []
  },

  async listActiveJobs(): Promise<PhyloJobRecord[]> {
    const res = await checkOk<{ jobs: PhyloJobRecord[] }>(
      apiGet('/api/phylo/jobs/active'),
      '查询活跃任务失败'
    )
    return res.jobs || []
  },

  async getJob(jobId: string): Promise<PhyloJobRecord> {
    return checkOk<PhyloJobRecord>(apiGet(`/api/phylo/jobs/${jobId}`), '查询任务详情失败')
  },

  async getJobQc(jobId: string): Promise<DeliveryQcReport> {
    return checkOk<DeliveryQcReport>(
      apiGet(`/api/phylo/jobs/${jobId}/qc`),
      '获取交付质检报告失败'
    )
  },

  async getJobLogs(jobId: string, tail = 300): Promise<string[]> {
    const res = await checkOk<{ lines: string[] }>(
      apiGet(`/api/phylo/jobs/${jobId}/logs?tail=${tail}`),
      '读取任务日志失败'
    )
    return res.lines || []
  },

  async cancelJob(jobId: string): Promise<boolean> {
    const res = await checkOk<{ success: boolean }>(
      apiPost(`/api/phylo/jobs/${jobId}/cancel`),
      '终止任务失败'
    )
    return Boolean(res.success)
  },

  async rerootJob(
    jobId: string,
    mode: 'midpoint' | 'outgroup',
    nodeName?: string
  ): Promise<PhyloJobRecord> {
    return checkOk<PhyloJobRecord>(
      apiPost(`/api/phylo/jobs/${jobId}/reroot`, { mode, node_name: nodeName }),
      '重定根失败'
    )
  },

  async deleteJob(jobId: string): Promise<boolean> {
    const res = await checkOk<{ success: boolean }>(
      apiDelete(`/api/phylo/jobs/${jobId}`),
      '删除记录失败'
    )
    return Boolean(res.success)
  },

  getExportUrl(
    jobId: string,
    fmt: 'newick' | 'distance_csv' | 'report_json' | 'delivery_zip'
  ): string {
    return `${API_BASE}/api/phylo/jobs/${encodeURIComponent(jobId)}/export/${fmt}`
  },

  getItolFileUrl(jobId: string, filename: string): string {
    return `${API_BASE}/api/phylo/jobs/${encodeURIComponent(jobId)}/export/itol/${encodeURIComponent(filename)}`
  },

  async renderPublicationFigure(
    jobId: string,
    payload: PublicationFigureRequest
  ): Promise<PublicationRenderResponse> {
    return checkOk<PublicationRenderResponse>(
      apiPost(`/api/phylo/jobs/${encodeURIComponent(jobId)}/render-publication`, payload),
      '离线出版级出图失败'
    )
  },

  async pullItolFigure(jobId: string, payload: ItolPullRequest): Promise<ItolPullResponse> {
    return checkOk<ItolPullResponse>(
      apiPost(`/api/phylo/jobs/${encodeURIComponent(jobId)}/itol/pull`, payload),
      '从 iTOL 拉取出图失败'
    )
  },

  getFigureUrl(jobId: string, filename: string, options?: FigureUrlOptions): string {
    const query = buildFigureUrlQuery(options)
    return `${API_BASE}/api/phylo/jobs/${encodeURIComponent(jobId)}/export/figure/${encodeURIComponent(filename)}${query}`
  },

  getItolUploadBundleUrl(jobId: string, labelFormat: LabelFormatType = 'name_acc'): string {
    return `${API_BASE}/api/phylo/jobs/${encodeURIComponent(jobId)}/export/itol_bundle?label_format=${encodeURIComponent(labelFormat)}`
  },

  getItolNewickUrl(jobId: string): string {
    return `${API_BASE}/api/phylo/jobs/${encodeURIComponent(jobId)}/export/itol_newick`
  },

  async fetchItolNewickText(jobId: string): Promise<string> {
    const resp = await fetch(`${API_BASE}/api/phylo/jobs/${encodeURIComponent(jobId)}/export/itol_newick`)
    if (!resp.ok) {
      throw new Error(`获取 iTOL 树文本失败 (HTTP ${resp.status})`)
    }
    return resp.text()
  },

  subscribeEvents(
    handler: (eventType: string, data: Record<string, unknown>) => void
  ): () => void {
    return onEvent((eventType: string, data: Record<string, unknown>) => {
      if (eventType.startsWith('phylo_')) {
        handler(eventType, data)
      }
    })
  },
}
