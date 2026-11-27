import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { useAppStore } from '../../../stores/app'

type EventCb = (type: string, data: unknown) => void

let registeredEventCb: EventCb | null = null
const mockGetAllDbStatus = vi.fn()
const mockTriggerDbUpdate = vi.fn()
const mockCancelDbUpdate = vi.fn()
const mockTaxonomyStatus = vi.fn()
const mockTaxonomyUpdate = vi.fn()
const mockTaxonomyCancel = vi.fn()
const mockConfirm = vi.fn()

vi.mock('../../../bridge', () => ({
  getBridge: () => ({
    get_all_db_status: mockGetAllDbStatus,
    trigger_db_update: mockTriggerDbUpdate,
    cancel_db_update: mockCancelDbUpdate,
    taxonomy_status: mockTaxonomyStatus,
    taxonomy_update: mockTaxonomyUpdate,
    taxonomy_cancel: mockTaxonomyCancel,
  }),
  onEvent: (cb: EventCb) => {
    registeredEventCb = cb
    return () => {
      registeredEventCb = null
    }
  },
}))

vi.mock('../../../composables/useConfirmDialog', () => ({
  useConfirmDialog: () => ({
    confirm: mockConfirm,
  }),
}))

describe('DatabasePanel 数据库更新状态与异常交互测试', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    registeredEventCb = null
    mockGetAllDbStatus.mockReset()
    mockTriggerDbUpdate.mockReset()
    mockCancelDbUpdate.mockReset()
    mockTaxonomyStatus.mockReset()
    mockTaxonomyUpdate.mockReset()
    mockTaxonomyCancel.mockReset()
    mockConfirm.mockReset()
    mockConfirm.mockResolvedValue(true)
  })

  afterEach(() => {
    vi.clearAllTimers()
  })

  it('WS 实时进度先于 HTTP 响应到达时不应被 5% 初始占位覆写，且支持取消与错误提示', async () => {
    mockTaxonomyStatus.mockResolvedValue({
      ready: true,
      building: true,
      progress: '下载中... 50.0% (10MB / 20MB)',
      fileSizeMB: 100,
      lastModified: '2026-11-27 10:00:00',
    })
    mockGetAllDbStatus.mockResolvedValue({
      success: true,
      data: [
        {
          db_id: 'ncbi_16s',
          name: 'NCBI RefSeq (16S)',
          version: '2026-05',
          category: '16S/18S 参考数据库',
          size_mb: 391,
          last_modified: '2026-08-27 18:28:44',
          installed: false,
          url: 'https://ftp.ncbi.nlm.nih.gov/blast/db/16S_ribosomal_RNA.tar.gz',
          update_state: null,
        },
      ],
    })

    // 模拟 HTTP 请求返回前，WS 已推入 45% 进度
    mockTriggerDbUpdate.mockImplementation(async () => {
      registeredEventCb?.('db_update_event', {
        db_id: 'ncbi_16s',
        status: 'updating',
        progress: 45,
        message: '下载 NCBI RefSeq 16S：已下载 30.0 MB / 69.5 MB (1.2 MB/s)',
      })
      return {
        success: true,
        state: {
          db_id: 'ncbi_16s',
          status: 'updating',
          progress: 5,
          message: '正在连接 NCBI RefSeq (16S) 核心下载源...',
        },
      }
    })
    mockCancelDbUpdate.mockResolvedValue({ success: true })

    const DatabasePanel = (await import('../DatabasePanel.vue')).default
    const wrapper = mount(DatabasePanel)
    await flushPromises()

    // 验证 Taxonomy 真实进度解析 (10 + round(50 * 0.65) = 43%) 且渲染取消按钮
    expect(wrapper.text()).toContain('下载中... 50.0% (10MB / 20MB) (43%)')
    mockTaxonomyCancel.mockResolvedValue({ success: true })
    const taxCancelBtn = wrapper.findAll('button').find((b) => b.text().trim() === '取消')
    expect(taxCancelBtn).toBeTruthy()
    await taxCancelBtn!.trigger('click')
    await flushPromises()
    expect(mockTaxonomyCancel).toHaveBeenCalledTimes(1)

    const deployBtn = wrapper.findAll('button').find((b) => b.text().includes('一键部署'))
    expect(deployBtn).toBeTruthy()
    await deployBtn!.trigger('click')
    await flushPromises()

    // 必须保留 WS 的 45% 与真实下载速率文本，而不能倒退回 5%
    expect(wrapper.text()).toContain('已下载 30.0 MB / 69.5 MB (1.2 MB/s) (45%)')

    // 点击取消按钮应调用 cancel_db_update
    const cancelBtn = wrapper.findAll('button').find((b) => b.text().trim() === '取消')
    expect(cancelBtn).toBeTruthy()
    await cancelBtn!.trigger('click')
    await flushPromises()
    expect(mockCancelDbUpdate).toHaveBeenCalledWith('ncbi_16s')

    // 收到 error 事件时应弹出错误通知且展示失败提示条、解锁按钮
    const appStore = useAppStore()
    const notifySpy = vi.spyOn(appStore, 'showNotification')
    registeredEventCb?.('db_update_event', {
      db_id: 'ncbi_16s',
      status: 'error',
      progress: 0,
      message: 'NCBI RefSeq (16S) 更新失败: 连接超时',
    })
    await flushPromises()

    expect(notifySpy).toHaveBeenCalledWith('NCBI RefSeq (16S) 更新失败: 连接超时', 'error')
    expect(wrapper.find('.db-error-row').text()).toContain('连接超时')
  })

  it('挂载时应能从 get_all_db_status 的 update_state 自动恢复进行中的进度条', async () => {
    mockTaxonomyStatus.mockResolvedValue({ ready: true, building: false })
    mockGetAllDbStatus.mockResolvedValue({
      success: true,
      data: [
        {
          db_id: 'silva',
          name: 'SILVA (138.1)',
          version: '138.1',
          category: '16S/18S 参考数据库',
          size_mb: 1200,
          last_modified: '2026-06-10 15:11:49',
          installed: true,
          url: 'https://www.arb-silva.de/silva.fasta.gz',
          update_state: {
            db_id: 'silva',
            status: 'updating',
            progress: 68,
            message: '下载 SILVA (138.1)：已下载 180.0 MB / 188.0 MB (2.1 MB/s)',
          },
        },
      ],
    })

    const DatabasePanel = (await import('../DatabasePanel.vue')).default
    const wrapper = mount(DatabasePanel)
    await flushPromises()

    expect(wrapper.text()).toContain('构建中...')
    expect(wrapper.text()).toContain('已下载 180.0 MB / 188.0 MB (2.1 MB/s) (68%)')
  })
})
