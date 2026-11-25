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

const getHelpStructureMock = vi.fn().mockResolvedValue([
  {
    category: '入门指南',
    topics: [
      { id: 'quick_start', title: '快速入门' },
      { id: 'local_blast', title: '本地 BLAST 比对' },
    ],
  },
  {
    category: '进阶模块',
    topics: [{ id: 'figure_studio', title: '科研绘图工坊' }],
  },
])

const getHelpContentMock = vi.fn().mockResolvedValue({
  content: '# 帮助标题\n\n## 第一节 安装配置\n\n正文段落。\n\n## 第二节 常见问题\n\n更多说明。',
})

vi.mock('../../bridge', () => ({
  getBridge: () => ({
    get_ui_translations: vi.fn((cb: (s: string) => void) => cb('{}')),
    sync_event: { connect: vi.fn() },
    get_help_structure: getHelpStructureMock,
    get_help_content: getHelpContentMock,
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

  it('safeHtml 应为 Markdown 标题分配安全锚点并拦截 DOM Clobbering 非法 id', async () => {
    const { extractMarkdownHeadings, markdownToHtml, safeSetHTML } = await import('../../utils/safeHtml')
    const md = '# 主标题\n\n```bash\n# 代码块注释不应计入大纲\n```\n\n## 第二章\n\n### 子章节'
    const headings = extractMarkdownHeadings(md)
    expect(headings.map((h) => [h.id, h.level, h.text])).toEqual([
      ['help-sec-1', 1, '主标题'],
      ['help-sec-2', 2, '第二章'],
      ['help-sec-3', 3, '子章节'],
    ])

    const container = document.createElement('div')
    safeSetHTML(container, `${markdownToHtml(md)}<h2 id="evil-clobber">危险ID</h2>`)
    expect(container.querySelector('#help-sec-2')?.textContent).toBe('第二章')
    expect(container.querySelector('#evil-clobber')).toBeNull()
  })

  it('HelpView 应支持侧栏即时搜索筛选与正文章节大纲 TOC', async () => {
    const HelpView = (await import('../../views/HelpView.vue')).default
    const wrapper = mount(HelpView)
    await flushPromises()

    expect(wrapper.findAll('button.topic-item').length).toBe(3)
    expect(wrapper.findAll('button.toc-btn').length).toBe(2)

    const searchInput = wrapper.find('input.help-search-input')
    await searchInput.setValue('绘图')
    expect(wrapper.findAll('button.topic-item').length).toBe(1)
    expect(wrapper.find('button.topic-item').text()).toContain('科研绘图工坊')
  })

  it('CommandPaletteDialog 应基于原生 <dialog> 支持关键词过滤与导航事件触发', async () => {
    const CommandPaletteDialog = (await import('../common/CommandPaletteDialog.vue')).default
    const wrapper = mount(CommandPaletteDialog, {
      props: { open: true },
    })
    await flushPromises()

    const dialogEl = wrapper.find('dialog')
    expect(dialogEl.exists()).toBe(true)
    expect(dialogEl.attributes('role')).toBeUndefined()
    expect(dialogEl.attributes('aria-modal')).toBeUndefined()

    const inputEl = wrapper.find('input.palette-input')
    await inputEl.setValue('引文')
    const items = wrapper.findAll('button.palette-item')
    expect(items.length).toBe(1)
    await items[0]!.trigger('click')
    expect(wrapper.emitted('action')?.[0]).toEqual(['citations'])
  })

  it('Phase 8 Wave 1 双语静态兜底应在切换 en_US 后瞬间生效于框架与主视图', async () => {
    setActivePinia(createPinia())
    const { useAppStore } = await import('../../stores/app')
    const appStore = useAppStore()
    appStore.setLocale('en_US')

    const HelpView = (await import('../../views/HelpView.vue')).default
    const CitationsDialog = (await import('../common/CitationsDialog.vue')).default
    const CommandPaletteDialog = (await import('../common/CommandPaletteDialog.vue')).default

    const helpW = mount(HelpView)
    await flushPromises()
    expect(helpW.text()).toContain('Help Center')
    expect(helpW.text()).toContain('On this page')

    const citW = mount(CitationsDialog, { props: { open: true } })
    await flushPromises()
    expect(citW.text()).toContain('Academic Citations & BibTeX Library')
    expect(citW.text()).toContain('All Modules')

    const palW = mount(CommandPaletteDialog, { props: { open: true } })
    await flushPromises()
    expect(palW.text()).toContain('Dashboard Overview')
    expect(palW.text()).toContain('Quick Actions')

    appStore.setLocale('zh_CN')
  })
})
