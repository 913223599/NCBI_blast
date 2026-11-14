import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import PhageDiscoveryResults from '../components/PhageDiscoveryResults.vue'
import PhageOverlayMap from '../components/PhageOverlayMap.vue'
import type {
  PhageContigOverlayData,
  PhageRegionItem,
  PhageScanResultPayload,
  PhageTaskRecord,
} from '../types'

function createSampleRegion(overrides: Partial<PhageRegionItem> = {}): PhageRegionItem {
  return {
    index: 0,
    region_id: 'Phage_001',
    contig_id: 'NC_007795.1',
    start_bp: 1458400,
    end_bp: 1510200,
    start_1based: 1458401,
    end_1based: 1510200,
    length_bp: 51800,
    peak_score: 0.992,
    mean_score: 0.929,
    window_count: 26,
    gc_percent: 33.4,
    orf_count: 56,
    completeness_key: 'high',
    completeness_label: '完整候选前噬菌体 (模型高置信)',
    gate_decision: 'bypass',
    gate_tier: '',
    hallmark_hits: 0,
    non_amg_hits: 0,
    transposase_hits: 0,
    amg_hits: 0,
    matched_titles: [],
    profile: [
      { start_bp: 1456400, end_bp: 1458400, prob: 0.12, in_region: false },
      { start_bp: 1458400, end_bp: 1510200, prob: 0.96, in_region: true },
      { start_bp: 1510200, end_bp: 1512200, prob: 0.15, in_region: false },
    ],
    gbk_file: 'Phage_001.gbk',
    ...overrides,
  }
}

function createFastaOverlayData(): PhageContigOverlayData {
  const region = createSampleRegion()
  return {
    contig_id: 'NC_007795.1',
    length_bp: 2821361,
    gc_percent: 32.9,
    source_format: 'fasta',
    base_tracks: [
      { start_bp: 0, end_bp: 100000, gc_pct: 33.0, gc_skew: 0.05, gene_count: 2 },
      { start_bp: 1400000, end_bp: 1600000, gc_pct: 34.1, gc_skew: -0.04, gene_count: 4 },
    ],
    score_tracks: [
      { start_bp: 0, end_bp: 1458400, max_prob: 0.15, mean_prob: 0.05 },
      { start_bp: 1458400, end_bp: 1510200, max_prob: 0.992, mean_prob: 0.929 },
      { start_bp: 1510200, end_bp: 2821361, max_prob: 0.1, mean_prob: 0.04 },
    ],
    base_features: [
      {
        index: 0,
        type: 'CDS',
        start_bp: 1460000,
        end_bp: 1461500,
        strand: 1,
        locus_tag: 'ORF_0001',
        gene: '',
        product: 'putative predicted ORF (500 aa)',
        note: '',
        source: 'Pyrodigal de novo',
        overlay_region_id: 'Phage_001',
        in_prophage: true,
      },
      {
        index: 1,
        type: 'CDS',
        start_bp: 200000,
        end_bp: 201200,
        strand: -1,
        locus_tag: 'ORF_0002',
        gene: '',
        product: 'putative predicted ORF (400 aa)',
        note: '',
        source: 'Pyrodigal de novo',
        overlay_region_id: null,
        in_prophage: false,
      },
    ],
    regions: [region],
    rejected_candidates: [],
  }
}

function createGenbankOverlayData(withMarkers: boolean): PhageContigOverlayData {
  const base = createFastaOverlayData()
  return {
    ...base,
    source_format: 'genbank',
    base_features: withMarkers
      ? [
          {
            index: 0,
            type: 'CDS',
            start_bp: 1458600,
            end_bp: 1459800,
            strand: 1,
            locus_tag: 'SAOUHSC_01500',
            gene: 'int',
            product: 'phage integrase',
            note: '',
            source: 'GenBank annotation',
            overlay_region_id: 'Phage_001',
            in_prophage: true,
          },
          {
            index: 1,
            type: 'tRNA',
            start_bp: 1458000,
            end_bp: 1458080,
            strand: 1,
            locus_tag: 'SAOUHSC_t01',
            gene: 'trnA',
            product: 'tRNA-Ala',
            note: '',
            source: 'GenBank annotation',
            overlay_region_id: null,
            in_prophage: false,
          },
        ]
      : [
          {
            index: 0,
            type: 'CDS',
            start_bp: 1460000,
            end_bp: 1461500,
            strand: 1,
            locus_tag: 'SAOUHSC_01501',
            gene: '',
            product: 'hypothetical protein',
            note: '',
            source: 'GenBank annotation',
            overlay_region_id: 'Phage_001',
            in_prophage: true,
          },
        ],
  }
}

function createTaskAndResult(): { task: PhageTaskRecord; result: PhageScanResultPayload } {
  const region = createSampleRegion()
  const task: PhageTaskRecord = {
    task_id: 'task_test_001',
    task_name: 'NC_007795.1_Staphylococcus',
    model_id: 'student_v4_2',
    model_version: 'V4.2',
    device: 'cuda',
    apply_protein_gate: false,
    status: 'completed',
    progress: 100,
    current_step: '扫描完成',
    created_at: '2026-11-14T00:00:00Z',
    updated_at: '2026-11-14T00:01:00Z',
    summary: {},
    files: { fasta: 'regions.fasta', tsv: 'regions.tsv' },
    result_path: 'result.json',
  }
  const result: PhageScanResultPayload = {
    task_id: task.task_id,
    task_name: task.task_name,
    summary: {
      contig_count: 1,
      total_bp: 2821361,
      total_windows: 1128,
      raw_region_count: 1,
      region_count: 1,
      rejected_count: 0,
      total_prophage_bp: 51800,
      prophage_fraction_pct: 1.836,
      source_format: 'fasta',
      model_id: 'student_v4_2',
      model_version: 'V4.2',
      model_label: 'Student V4.2',
      device_used: 'cuda',
      apply_protein_gate: false,
      timings_sec: { total_sec: 2.34 },
    },
    contigs: [
      {
        id: 'NC_007795.1',
        length: 2821361,
        gc_percent: 32.9,
        hit_count: 1,
        source_format: 'fasta',
        base_feature_count: 2,
      },
    ],
    regions: [region],
    rejected_candidates: [],
    files: { fasta: 'regions.fasta', tsv: 'regions.tsv' },
  }
  return { task, result }
}

describe('PhageDiscoveryResults 与 PhageOverlayMap 回归测试', () => {
  it('移除与叠图工作台重复的旧边界精细概率曲线卡片并保留清单与联动能力', async () => {
    const { task, result } = createTaskAndResult()
    const overlayData = createFastaOverlayData()

    const wrapper = mount(PhageDiscoveryResults, {
      props: {
        task,
        result,
        isLoading: false,
        overlayData,
        isOverlayLoading: false,
      },
    })

    // 保留新叠图工作台与前噬菌体清单
    expect(wrapper.text()).toContain('目标基因组底图与前噬菌体预测叠图工作台')
    expect(wrapper.text()).toContain('识别前噬菌体清单')

    // 确认已彻底移除重合的旧曲线卡片
    expect(wrapper.text()).not.toContain('边界精细概率曲线 (200bp SubBin 分辨率)')
    expect(wrapper.find('.profile-svg').exists()).toBe(false)

    // 叠图底部的快捷联动按钮应可透传 open-viewer / open-annotation
    const viewerBtn = wrapper.find('[data-testid="active-region-viewer-btn"]')
    const annoBtn = wrapper.find('[data-testid="active-region-anno-btn"]')
    expect(viewerBtn.exists()).toBe(true)
    expect(annoBtn.exists()).toBe(true)

    await viewerBtn.trigger('click')
    await annoBtn.trigger('click')
    expect(wrapper.emitted('open-viewer')?.[0]).toEqual([0])
    expect(wrapper.emitted('open-annotation')?.[0]).toEqual([0])
  })

  it('FASTA + Pyrodigal 模式下不虚构整合酶/转座酶与 tRNA/rRNA 能力，并自适应 badge 宽度防裁切', async () => {
    const overlayData = createFastaOverlayData()
    const wrapper = mount(PhageOverlayMap, {
      props: {
        contigs: [
          {
            id: 'NC_007795.1',
            length: 2821361,
            gc_percent: 32.9,
            hit_count: 1,
            source_format: 'fasta',
            base_feature_count: 2,
          },
        ],
        selectedContigId: 'NC_007795.1',
        overlayData,
        isLoading: false,
        selectedRegionIndex: 0,
      },
    })

    const legendText = wrapper.find('.legend-strip').text()
    expect(legendText).not.toContain('整合酶 / 转座酶')
    expect(legendText).not.toContain('tRNA / rRNA')
    expect(legendText).toContain('区段内 ORF')
    expect(legendText).toContain('宿主 ORF')

    const toggleText = wrapper.find('.layer-toggles').text()
    expect(toggleText).not.toContain('CDS/tRNA')
    expect(toggleText).toContain('底图特征 (ORF)')

    const placeholder = wrapper.find('.feat-search-input').attributes('placeholder') || ''
    expect(placeholder.toLowerCase()).not.toContain('integrase')
    expect(placeholder.toLowerCase()).not.toContain('trna')

    // 校验 Phage_001 线性 badge 背景矩形宽度足够容纳文本不被白色背景截断
    const badgeRect = wrapper.find('[data-region-badge="Phage_001"]')
    expect(badgeRect.exists()).toBe(true)
    expect(Number(badgeRect.attributes('width'))).toBeGreaterThanOrEqual(60)

    // 校验底部当前激活区段的联动按钮触发
    await wrapper.find('[data-testid="active-region-viewer-btn"]').trigger('click')
    await wrapper.find('[data-testid="active-region-anno-btn"]').trigger('click')
    expect(wrapper.emitted('open-region-viewer')?.[0]).toEqual([0])
    expect(wrapper.emitted('open-annotation')?.[0]).toEqual([0])
  })

  it('GenBank 模式且底图真正包含整合酶与 tRNA 注释时按需显示对应图例与开关标签', () => {
    const overlayWithMarkers = createGenbankOverlayData(true)
    const wrapperWithMarkers = mount(PhageOverlayMap, {
      props: {
        contigs: [
          {
            id: 'NC_007795.1',
            length: 2821361,
            gc_percent: 32.9,
            hit_count: 1,
            source_format: 'genbank',
            base_feature_count: 2,
          },
        ],
        selectedContigId: 'NC_007795.1',
        overlayData: overlayWithMarkers,
        isLoading: false,
        selectedRegionIndex: 0,
      },
    })

    const legendWithMarkers = wrapperWithMarkers.find('.legend-strip').text()
    expect(legendWithMarkers).toContain('整合酶 / 转座酶')
    expect(legendWithMarkers).toContain('tRNA / rRNA')
    expect(legendWithMarkers).toContain('区段内基因')
    expect(wrapperWithMarkers.find('.layer-toggles').text()).toContain('CDS/tRNA')

    // GenBank 但无任何 integrase 或 tRNA 注释时，也不误显示这两个图例
    const overlayWithoutMarkers = createGenbankOverlayData(false)
    const wrapperWithoutMarkers = mount(PhageOverlayMap, {
      props: {
        contigs: [
          {
            id: 'NC_007795.1',
            length: 2821361,
            gc_percent: 32.9,
            hit_count: 1,
            source_format: 'genbank',
            base_feature_count: 1,
          },
        ],
        selectedContigId: 'NC_007795.1',
        overlayData: overlayWithoutMarkers,
        isLoading: false,
        selectedRegionIndex: 0,
      },
    })
    const legendWithoutMarkers = wrapperWithoutMarkers.find('.legend-strip').text()
    expect(legendWithoutMarkers).not.toContain('整合酶 / 转座酶')
    expect(legendWithoutMarkers).not.toContain('tRNA / rRNA')
  })
})

