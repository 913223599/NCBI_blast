import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { isImeComposingKey, shouldSubmitOnEnter } from '../../utils/ime'
import { useConfirmDialog } from '../../composables/useConfirmDialog'

vi.mock('../../bridge/electron-bridge', () => ({
  apiGet: vi.fn().mockResolvedValue({ status: 'ok', service: 'ncbi-bio-station' }),
}))

vi.mock('../../bridge', () => ({
  getBridge: () => ({
    get_ui_translations: vi.fn((cb: (s: string) => void) => cb('{}')),
    sync_event: { connect: vi.fn() },
  }),
  onEvent: () => () => {},
}))

const pushMock = vi.fn()
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: pushMock }),
  useRoute: () => ({ path: '/blast', meta: { title: 'BLAST 分析' } }),
}))

describe('Phase 3 A11y、顶栏信息架构、原生 Dialog 与 IME 安全守卫', () => {
  it('IME 安全守卫应拦截 isComposing 与 Safari keyCode===229 的 Enter', () => {
    const composingEvt = { key: 'Enter', isComposing: true, keyCode: 13, shiftKey: false } as KeyboardEvent
    const safari229Evt = { key: 'Enter', isComposing: false, keyCode: 229, shiftKey: false } as KeyboardEvent
    const normalEnter = { key: 'Enter', isComposing: false, keyCode: 13, shiftKey: false } as KeyboardEvent
    const shiftEnter = { key: 'Enter', isComposing: false, keyCode: 13, shiftKey: true } as KeyboardEvent

    expect(isImeComposingKey(composingEvt)).toBe(true)
    expect(isImeComposingKey(safari229Evt)).toBe(true)
    expect(shouldSubmitOnEnter(composingEvt)).toBe(false)
    expect(shouldSubmitOnEnter(safari229Evt)).toBe(false)
    expect(shouldSubmitOnEnter(normalEnter)).toBe(true)
    expect(shouldSubmitOnEnter(shiftEnter, { allowShiftNewline: true })).toBe(false)
  })

  it('AppSidebar 所有导航与折叠控件均为语义 button 且携带 aria-current / aria-expanded', async () => {
    setActivePinia(createPinia())
    const AppSidebar = (await import('../layout/AppSidebar.vue')).default
    const wrapper = mount(AppSidebar)

    const navBtns = wrapper.findAll('button.nav-item')
    expect(navBtns.length).toBe(9)
    const activeBtn = wrapper.find('button.nav-item.active')
    expect(activeBtn.exists()).toBe(true)
    expect(activeBtn.attributes('aria-current')).toBe('page')

    const toggleBtn = wrapper.find('button.toggle-btn')
    expect(toggleBtn.exists()).toBe(true)
    expect(toggleBtn.attributes('aria-expanded')).toBe('true')
  })

  it('AppHeader 应展示面包屑、服务健康状态胶囊及快捷操作按钮', async () => {
    setActivePinia(createPinia())
    const AppHeader = (await import('../layout/AppHeader.vue')).default
    const wrapper = mount(AppHeader)
    await flushPromises()

    expect(wrapper.find('.crumb-home').exists()).toBe(true)
    expect(wrapper.find('.header-search-btn').exists()).toBe(true)
    expect(wrapper.text()).toContain('服务就绪')
    expect(wrapper.findAll('.header-icon-btn').length).toBeGreaterThanOrEqual(3)
    wrapper.unmount()
  })

  it('AppConfirmDialog 应使用原生 <dialog> 且不含冗余 role="dialog" 或 aria-modal', async () => {
    const AppConfirmDialog = (await import('../common/AppConfirmDialog.vue')).default
    const wrapper = mount(AppConfirmDialog)
    const dialogEl = wrapper.find('dialog')
    expect(dialogEl.exists()).toBe(true)
    expect(dialogEl.attributes('role')).toBeUndefined()
    expect(dialogEl.attributes('aria-modal')).toBeUndefined()

    const { confirm } = useConfirmDialog()
    const promise = confirm({ title: '删除任务', message: '确认删除？', danger: true })
    await flushPromises()

    // 模拟原生 dialog 关闭且 returnValue='confirm'
    const nativeDialog = dialogEl.element as HTMLDialogElement
    nativeDialog.returnValue = 'confirm'
    await dialogEl.trigger('close')
    expect(await promise).toBe(true)
    // 验证 close 后立即重置 returnValue 防止陈旧值泄漏
    expect(nativeDialog.returnValue).toBe('')
  })

  it('AppConfirmDialog 应支持原生 <dialog> 输入模式 prompt() 与取消返回 null', async () => {
    const AppConfirmDialog = (await import('../common/AppConfirmDialog.vue')).default
    const wrapper = mount(AppConfirmDialog)
    const dialogEl = wrapper.find('dialog')
    const nativeDialog = dialogEl.element as HTMLDialogElement

    const { prompt } = useConfirmDialog()
    const promiseOk = prompt({
      title: '危险校验',
      message: '请输入 DELETE 确认清空',
      inputLabel: '确认口令',
      placeholder: 'DELETE',
      danger: true,
    })
    await flushPromises()

    const inputEl = wrapper.find('input#app-confirm-prompt-input')
    expect(inputEl.exists()).toBe(true)
    await inputEl.setValue('DELETE')
    nativeDialog.returnValue = 'confirm'
    await dialogEl.trigger('close')
    expect(await promiseOk).toBe('DELETE')

    const promiseCancel = prompt({ title: '取消测试', message: '输入内容' })
    await flushPromises()
    nativeDialog.returnValue = 'cancel'
    await dialogEl.trigger('close')
    expect(await promiseCancel).toBeNull()
  })

  it('全仓前端源码不应包含原生阻塞式 alert/confirm/prompt 调用', async () => {
    const fs = await import('node:fs')
    const path = await import('node:path')
    const srcRoot = path.resolve(__dirname, '../..')
    const nativeDialogRe = /(?<![.\w$])(?:window\.)?(?:alert|confirm|prompt)\s*\(/
    const violations: string[] = []

    const walk = (dir: string) => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        if (entry.name === '__tests__' || entry.name === 'node_modules') continue
        const full = path.join(dir, entry.name)
        if (entry.isDirectory()) {
          walk(full)
          continue
        }
        if (!/\.(vue|ts|js)$/.test(entry.name)) continue
        const content = fs.readFileSync(full, 'utf-8')
        content.split(/\r?\n/).forEach((line, idx) => {
          const trimmed = line.trim()
          if (
            trimmed.startsWith('//') ||
            trimmed.startsWith('*') ||
            /^function\s+(?:confirm|prompt)\s*\(/.test(trimmed)
          ) {
            return
          }
          if (nativeDialogRe.test(line)) {
            violations.push(`${path.relative(srcRoot, full)}:${idx + 1}: ${trimmed}`)
          }
        })
      }
    }

    walk(srcRoot)
    expect(violations).toEqual([])
  })
})
