import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, ref, KeepAlive } from 'vue'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

vi.mock('../../bridge', () => ({
  getBridge: () => ({
    get_help_structure: vi.fn().mockResolvedValue([
      {
        category: '入门指南',
        topics: [{ id: 'quick_start', title: '快速入门' }],
      },
    ]),
    get_help_content: vi.fn().mockResolvedValue({
      content: '# 标题\n\n安全段落\n\n<script>window.__xss=1</script><img src="x" onerror="window.__xss=2">',
    }),
    db_load_freezers: vi.fn(),
    db_load_all_records: vi.fn(),
  }),
  onEvent: () => () => {},
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: '/' }),
}))

describe('Phase 1 UI 显性 Bug 守护测试', () => {
  it('SettingsView 不应硬编码 100vh 导致 56px 顶栏下内容裁切，且不含失效 scoped :root', () => {
    const filePath = resolve(__dirname, '../SettingsView.vue')
    const source = readFileSync(filePath, 'utf-8')
    expect(source).not.toMatch(/\.settings-view\s*\{[^}]*height\s*:\s*100vh/s)
    expect(source).not.toMatch(/<style\s+scoped>[\s\S]*:root\s*\{/s)
  })

  it('DashboardView 所有快捷入口卡片都应渲染矢量 SVG 图标且不包含空 icon 块', async () => {
    setActivePinia(createPinia())
    const DashboardView = (await import('../DashboardView.vue')).default
    const wrapper = mount(DashboardView)
    const cards = wrapper.findAll('.action-card')
    expect(cards.length).toBeGreaterThanOrEqual(6)
    for (const card of cards) {
      expect(card.find('.card-icon svg').exists()).toBe(true)
    }
  })

  it('HelpView 应正确异步加载目录与内容并安全过滤危险脚本标签', async () => {
    setActivePinia(createPinia())
    const HelpView = (await import('../HelpView.vue')).default
    const wrapper = mount(HelpView)
    await flushPromises()

    const topicItems = wrapper.findAll('.topic-item')
    expect(topicItems.length).toBeGreaterThan(0)
    await topicItems[0]!.trigger('click')
    await flushPromises()

    const bodyEl = wrapper.find('.content-body')
    expect(bodyEl.exists()).toBe(true)
    expect(bodyEl.text()).toContain('安全段落')
    // DOM 节点层验证：不得生成危险 <script> 或 <img> 节点
    expect(bodyEl.find('script').exists()).toBe(false)
    expect(bodyEl.find('img').exists()).toBe(false)

    // 直接验证 safeSetHTML 白名单净化能力（移除危险标签及事件属性）
    const { safeSetHTML } = await import('../../utils/safeHtml')
    const box = document.createElement('div')
    safeSetHTML(box, '<p>正常文本</p><script>window.__xss=1</script><img src="x" onerror="window.__xss=2"><a href="javascript:alert(1)">bad</a>')
    expect(box.textContent).toContain('正常文本')
    expect(box.querySelector('script')).toBeNull()
    expect(box.querySelector('img')).toBeNull()
    expect(box.innerHTML.toLowerCase()).not.toContain('onerror')
    expect(box.innerHTML.toLowerCase()).not.toContain('javascript:')
  })

  it('StrainView 在 KeepAlive 失活后不应再响应全局键盘快捷键', async () => {
    setActivePinia(createPinia())
    const StrainView = (await import('../StrainView.vue')).default
    const DummyView = defineComponent({ template: '<div class="dummy">other</div>' })

    const Host = defineComponent({
      components: { StrainView, DummyView, KeepAlive },
      setup() {
        const showStrain = ref(true)
        return { showStrain }
      },
      template: `
        <KeepAlive>
          <StrainView v-if="showStrain" />
          <DummyView v-else />
        </KeepAlive>
      `,
    })

    const wrapper = mount(Host, {
      global: {
        stubs: {
          StrainSidebar: true,
          FreezerDetailPanel: true,
          StatisticsPanel: true,
          StrainListContainer: true,
          AddFreezerDialog: { template: '<div class="stub-add-dialog" />' },
          BatchImportDialog: true,
          SampleDetailDialog: true,
          KeyboardShortcutsHelp: true,
          CodeLookupManager: true,
        },
      },
    })

    // 切走视图使 StrainView 进入 KeepAlive deactivated 状态
    wrapper.vm.showStrain = false
    await flushPromises()

    // 在其他页面按 Ctrl+N，不应激活隐藏中的 StrainView 弹窗
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'n', ctrlKey: true, bubbles: true }))
    await flushPromises()

    // 切回 StrainView 验证弹窗并未被暗中打开
    wrapper.vm.showStrain = true
    await flushPromises()
    expect(wrapper.find('.stub-add-dialog').exists()).toBe(false)
    wrapper.unmount()
  })
})
