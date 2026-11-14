import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { parseGenBank } from '../utils/parser'
import GenomeViewerModule from '../GenomeViewerModule.vue'

function buildLegacyFullSpanGbk(): string {
  const seq = 'ATGCGTACGT'.repeat(300) // 3000 bp
  return [
    'LOCUS       Phage_001_NC_008        3000 bp    DNA     linear   PHG 14-NOV-2026',
    'FEATURES             Location/Qualifiers',
    '     misc_feature    1..3000',
    '                     /label="Phage_001 (完整候选前噬菌体)"',
    '                     /note="Contig=NC_008207.1; GlobalCoord=1..3000; PeakScore=0.9977; MeanScore=0.9650"',
    '     CDS             10..309',
    '                     /locus_tag="Phage_001_ORF_0001"',
    '                     /product="putative prophage protein"',
    '     CDS             complement(400..700)',
    '                     /locus_tag="Phage_001_ORF_0002"',
    '                     /product="phage terminase large subunit"',
    'ORIGIN',
    `        1 ${seq}`,
    '//',
  ].join('\n')
}

function buildLegacyFlankedAndNormalMiscGbk(): string {
  const seq = 'ATGCGTACGT'.repeat(300) // 3000 bp
  return [
    'LOCUS       Phage_001_chr           3000 bp    DNA     linear   PHG 14-NOV-2026',
    'FEATURES             Location/Qualifiers',
    '     misc_feature    500..2500',
    '                     /label="Phage_001"',
    '                     /note="Contig=chr_1; GlobalCoord=10500..12500; PeakScore=0.9800"',
    '     misc_feature    100..160',
    '                     /label="attP_site"',
    '                     /note="integration attachment site"',
    '     CDS             600..900',
    '                     /locus_tag="Phage_001_ORF_0001"',
    '                     /product="hypothetical protein"',
    'ORIGIN',
    `        1 ${seq}`,
    '//',
  ].join('\n')
}

function buildOverlayWithProphageRegionGbk(): string {
  const seq = 'ATGCGTACGT'.repeat(300) // 3000 bp
  return [
    'LOCUS       NC_008207               3000 bp    DNA     linear   BCT 14-NOV-2026',
    'FEATURES             Location/Qualifiers',
    '     prophage_region 500..2500',
    '                     /locus_tag="Phage_001"',
    '                     /label="Phage_001"',
    '                     /product="Predicted Prophage (高置信)"',
    '                     /note="PhageDiscovery V4.2; Peak=0.992; Mean=0.950; GC=40.0%"',
    '     CDS             600..1200',
    '                     /locus_tag="ORF_0001"',
    '                     /product="major capsid protein"',
    '     CDS             complement(1300..1900)',
    '                     /locus_tag="ORF_0002"',
    '                     /product="hypothetical protein"',
    'ORIGIN',
    `        1 ${seq}`,
    '//',
  ].join('\n')
}

describe('GenomeViewer 前噬菌体联动注释兼容性与纯化测试', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('自动清洗历史全长贯穿的旧版 PhageDiscovery misc_feature，消除覆盖全圈的假定蛋白大箭头', () => {
    const parsed = parseGenBank(buildLegacyFullSpanGbk())
    expect(parsed.sequence.length).toBe(3000)
    expect(parsed.features.map((f) => f.locus_tag)).toEqual([
      'Phage_001_ORF_0001',
      'Phage_001_ORF_0002',
    ])
  })

  it('带侧翼的旧版 PhageDiscovery misc_feature 自动升级为 prophage_region，普通短 misc_feature 保持保留', () => {
    const parsed = parseGenBank(buildLegacyFlankedAndNormalMiscGbk())
    expect(parsed.features).toHaveLength(3)

    const upgraded = parsed.features[0]
    expect(upgraded.type).toBe('prophage_region')
    expect(upgraded.name).toBe('Phage_001')

    const normalMisc = parsed.features[1]
    expect(normalMisc.type).toBe('misc_feature')
    expect(normalMisc.name).toBe('attP_site')
  })

  it('prophage_region 仅在包络层渲染，不计入左侧基因列表、CDS 计数与蛋白 aa/kDa 估算', async () => {
    vi.useFakeTimers()
    const wrapper = mount(GenomeViewerModule, {
      props: {
        initialGbk: buildOverlayWithProphageRegionGbk(),
        initialName: 'NC_008207_overlay.gbk',
      },
    })
    await vi.advanceTimersByTimeAsync(100)

    expect(wrapper.find('.feat-total-tag').text()).toBe('2 / 2 个')
    expect(wrapper.find('.center-cds-count').text()).toBe('CDS: 2 个特征')
    expect(wrapper.findAll('.prophage-overlay-layer path')).toHaveLength(1)
    expect(wrapper.findAll('.features-layer path')).toHaveLength(2)

    const totalLegendCount = wrapper
      .findAll('.legend-count')
      .reduce((acc, el) => acc + Number(el.text()), 0)
    expect(totalLegendCount).toBe(2)

    // 点击半透明区段包络后不应展示错误的氨基酸规模或复制蛋白按钮
    await wrapper.find('.prophage-overlay-layer path').trigger('click')
    const drawerText = wrapper.find('.feature-inspector-drawer').text()
    expect(drawerText).toContain('Phage_001')
    expect(drawerText).not.toContain('蛋白规模:')
    expect(drawerText).not.toContain('复制蛋白翻译序列')

    wrapper.unmount()
  })
})

