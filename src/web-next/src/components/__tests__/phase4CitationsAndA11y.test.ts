import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../../bridge/electron-bridge', () => ({
  apiGet: vi.fn().mockResolvedValue({
    schema_version: '1.0',
    count: 2,
    tools: [
      {
        id: 'viridic',
        name: 'VIRIDIC',
        module: 'figure_studio',
        authors: 'Moraru C, Varsani A, Kropinski AM.',
        year: 2020,
        title: 'VIRIDIC-A Novel Tool to Calculate the Intergenomic Similarities',
        journal: 'Viruses',
        doi: '10.3390/v12111268',
      },
      {
        id: 'prokka',
        name: 'Prokka',
        module: 'annotation',
        authors: 'Seemann T.',
        year: 2014,
        title: 'Prokka: rapid prokaryotic genome annotation',
        journal: 'Bioinformatics',
        doi: '10.1093/bioinformatics/btu153',
      },
    ],
  }),
}))

vi.mock('../../bridge', () => ({
  getBridge: () => ({
    get_ui_translations: vi.fn((cb: (s: string) => void) => cb('{}')),
    sync_event: { connect: vi.fn() },
  }),
  onEvent: () => () => {},
}))

describe('Phase 4 科研引文库接线、工作台语义按钮与结构蛋白导出测试', () => {
  it('CitationsDialog 应基于原生 <dialog> 加载文献库并支持模块筛选', async () => {
    setActivePinia(createPinia())
    const CitationsDialog = (await import('../common/CitationsDialog.vue')).default
    const wrapper = mount(CitationsDialog, {
      props: { open: true, defaultModule: 'all' },
    })
    await flushPromises()

    const dialogEl = wrapper.find('dialog')
    expect(dialogEl.exists()).toBe(true)
    expect(dialogEl.attributes('role')).toBeUndefined()
    expect(wrapper.findAll('.citation-card').length).toBe(2)

    const studioTab = wrapper.findAll('button.mod-tab').find((b) => b.text().includes('科研绘图工坊'))
    expect(studioTab).toBeDefined()
    await studioTab!.trigger('click')
    expect(wrapper.findAll('.citation-card').length).toBe(1)
    expect(wrapper.text()).toContain('VIRIDIC')
  })

  it('FigureStudioView / AnalysisView / OtherToolsView 工作台入口卡片均应为语义 button', async () => {
    setActivePinia(createPinia())
    const FigureStudioView = (await import('../../views/FigureStudioView.vue')).default
    const AnalysisView = (await import('../../views/AnalysisView.vue')).default
    const OtherToolsView = (await import('../../views/OtherToolsView.vue')).default

    const w1 = mount(FigureStudioView)
    expect(w1.findAll('button.tool-card').length).toBe(7)
    expect(w1.find('button.citations-btn').exists()).toBe(true)

    const w2 = mount(AnalysisView)
    expect(w2.findAll('button.tool-card').length).toBe(6)

    const w3 = mount(OtherToolsView)
    expect(w3.findAll('button.tool-card').length).toBe(2)
  })
})
