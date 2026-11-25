import { API_BASE, apiGet, apiPost } from '../../../bridge/electron-bridge'
import { buildFigureUrlQuery, type FigureUrlOptions } from '../../phylo/core/FigurePreviewHelper'
import type {
  DiversityRenderPayload,
  GenomeMapRenderPayload,
  HostMatrixRenderPayload,
  NetworkRenderPayload,
  StudioRenderResponse,
  StudioSourcesResponse,
  SyntenyRenderPayload,
  ViridicRenderPayload,
} from '../types/studio'

async function unwrap<T>(promise: Promise<unknown>, fallbackMsg: string): Promise<T> {
  const res = (await promise) as Record<string, unknown> | null | undefined
  if (!res) {
    throw new Error(fallbackMsg)
  }
  if (typeof res.detail === 'string' && !res.render_id && !res.phylo_jobs) {
    throw new Error(res.detail)
  }
  if (res.success === false) {
    throw new Error(res.error ? String(res.error) : fallbackMsg)
  }
  return res as T
}

export const studioApi = {
  async getSources(): Promise<StudioSourcesResponse> {
    return unwrap<StudioSourcesResponse>(apiGet('/api/figure-studio/sources'), '加载绘图工坊数据源失败')
  },

  async renderViridic(payload: ViridicRenderPayload): Promise<StudioRenderResponse> {
    return unwrap<StudioRenderResponse>(
      apiPost('/api/figure-studio/render/viridic', payload),
      'VIRIDIC 热图渲染失败'
    )
  },

  async renderGenomeMap(payload: GenomeMapRenderPayload): Promise<StudioRenderResponse> {
    return unwrap<StudioRenderResponse>(
      apiPost('/api/figure-studio/render/genome-map', payload),
      '全基因组功能图渲染失败'
    )
  },

  async renderSynteny(payload: SyntenyRenderPayload): Promise<StudioRenderResponse> {
    return unwrap<StudioRenderResponse>(
      apiPost('/api/figure-studio/render/synteny', payload),
      '共线性丝带图渲染失败'
    )
  },

  async renderDiversity(payload: DiversityRenderPayload): Promise<StudioRenderResponse> {
    return unwrap<StudioRenderResponse>(
      apiPost('/api/figure-studio/render/diversity', payload),
      '核苷酸多样性图渲染失败'
    )
  },

  async renderNetwork(payload: NetworkRenderPayload): Promise<StudioRenderResponse> {
    return unwrap<StudioRenderResponse>(
      apiPost('/api/figure-studio/render/network', payload),
      '蛋白基因共享网络渲染失败'
    )
  },

  async renderHostMatrix(payload: HostMatrixRenderPayload): Promise<StudioRenderResponse> {
    return unwrap<StudioRenderResponse>(
      apiPost('/api/figure-studio/render/host-matrix', payload),
      '宿主谱矩阵渲染失败'
    )
  },

  getFileUrl(renderId: string, filename: string, options?: FigureUrlOptions): string {
    const q = buildFigureUrlQuery(options)
    return `${API_BASE}/api/figure-studio/files/${encodeURIComponent(renderId)}/${encodeURIComponent(filename)}${q}`
  },
}
