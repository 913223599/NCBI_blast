import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import {
  buildMergedGroupSamples,
  formatPct,
  parseSamplePattern,
} from '../diversity/diversityHelpers'
import DiversityAnalysisModal from '../DiversityAnalysisModal.vue'
import type { DiversitySampleItem } from '../diversity/useDiversityModal'

vi.mock('../../../bridge/electron-bridge', () => ({
  API_BASE: 'http://localhost:8765',
  apiGet: vi.fn().mockResolvedValue([]),
  apiPost: vi.fn().mockResolvedValue({}),
  apiDelete: vi.fn().mockResolvedValue({ status: 'deleted' }),
}))

describe('diversityHelpers 强类型工具与分组聚合测试', () => {
  it('parseSamplePattern 支持范围与逗号列表匹配', () => {
    const samples = ['S1', 'S2', 'S3', 'S4', 'S5', 'S6']
    expect(parseSamplePattern('1-3', samples)).toEqual(['S1', 'S2', 'S3'])
    expect(parseSamplePattern('2, 5', samples)).toEqual(['S2', 'S5'])
  })

  it('formatPct 处理边界值与极小非零值', () => {
    expect(formatPct(null)).toBe('0.00')
    expect(formatPct(0)).toBe('0.00')
    expect(formatPct(0.004)).toBe('<0.01')
    expect(formatPct(12.345)).toBe('12.35')
  })

  it('buildMergedGroupSamples 正确聚合 Reads 并按 GCN 归一化', () => {
    const raw: DiversitySampleItem[] = [
      {
        sample_name: 'S1',
        total_reads: 100,
        classified_reads: 100,
        norm_result: {
          details: [
            { taxon: 'Bacillus subtilis', raw_count: 80, raw_pct: 80, norm_pct: 50, gcn_mean: 10 },
            { taxon: 'Pseudomonas putida', raw_count: 20, raw_pct: 20, norm_pct: 50, gcn_mean: 2 },
          ],
        },
      },
      {
        sample_name: 'S2',
        total_reads: 100,
        classified_reads: 100,
        norm_result: {
          details: [
            { taxon: 'Bacillus subtilis', raw_count: 20, raw_pct: 20, norm_pct: 20, gcn_mean: 10 },
          ],
        },
      },
      {
        sample_name: 'S3',
        total_reads: 50,
        classified_reads: 50,
        norm_result: { details: [] },
      },
    ]

    const merged = buildMergedGroupSamples(raw, [
      { id: 'g1', name: 'Control', pattern: '1-2', matchedSamples: ['S1', 'S2'] },
    ])
    expect(merged).toHaveLength(2)
    expect(merged[0]?.sample_name).toBe('Control')
    expect(merged[0]?.is_group).toBe(true)
    expect(merged[0]?.total_reads).toBe(200)
    expect(merged[1]?.sample_name).toBe('S3')
  })
})

describe('DiversityAnalysisModal 拆分后组件集成测试', () => {
  it('挂载薄外壳并能正确开关历史抽屉与暴露公共方法', async () => {
    setActivePinia(createPinia())
    const wrapper = mount(DiversityAnalysisModal, {
      props: { modelValue: true, embedded: true },
      global: {
        stubs: {
          UniversalUpload: true,
        },
      },
    })

    expect(wrapper.find('.modal-header-neo').exists()).toBe(true)
    expect(typeof wrapper.vm.toggleHistoryDrawer).toBe('function')
    expect(typeof wrapper.vm.resetToNewAnalysis).toBe('function')

    wrapper.vm.toggleHistoryDrawer()
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.history-drawer-neo').exists()).toBe(true)
  })
})
