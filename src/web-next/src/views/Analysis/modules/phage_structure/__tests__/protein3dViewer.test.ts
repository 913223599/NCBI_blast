import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import {
  DEMO_HELIX_PDB,
  expandResidueIndices,
  parseResidueRanges,
  plddtColorHex,
} from '../components/viewer3d/structure3dHelper'
import Protein3DViewerModal from '../components/Protein3DViewerModal.vue'

describe('Phase 7 3D 蛋白结构可视化辅助与原生 Dialog 规范守护', () => {
  it('parseResidueRanges 与 expandResidueIndices 应正确解析残基区间并限制数量', () => {
    const ranges = parseResidueRanges('10-12, 25, 40-38, invalid, -3')
    expect(ranges).toEqual([
      { start: 10, end: 12 },
      { start: 25, end: 25 },
      { start: 38, end: 40 },
    ])
    expect(expandResidueIndices(ranges)).toEqual([10, 11, 12, 25, 38, 39, 40])
  })

  it('plddtColorHex 应按 AlphaFold 官方四段置信度色标映射', () => {
    expect(plddtColorHex(95)).toBe('#0053D6')
    expect(plddtColorHex(78)).toBe('#65CBF3')
    expect(plddtColorHex(62)).toBe('#FFDB13')
    expect(plddtColorHex(35)).toBe('#FF7D45')
    expect(DEMO_HELIX_PDB).toContain('ATOM')
  })

  it('Protein3DViewerModal 应使用原生 <dialog> 且不含冗余 role="dialog" 或 aria-modal', () => {
    const wrapper = mount(Protein3DViewerModal, {
      props: {
        open: false,
        context: {
          taskId: 'STR_TEST_01',
          locusTag: 'PHAGE_001',
          product: 'major capsid protein',
          lengthAa: 342,
        },
      },
    })

    const dialog = wrapper.find('dialog.protein-3d-dialog')
    expect(dialog.exists()).toBe(true)
    expect(dialog.attributes('role')).toBeUndefined()
    expect(dialog.attributes('aria-modal')).toBeUndefined()
    expect(dialog.attributes('closedby')).toBe('any')
    expect(dialog.attributes('aria-labelledby')).toBe('protein-3d-title')
    expect(wrapper.find('h1#protein-3d-title').text()).toContain('PHAGE_001')
  })
})
