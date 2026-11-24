import { describe, it, expect, beforeEach, vi } from 'vitest'
import { defineComponent } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import { useAssembly } from '../composables/useAssembly'
import type { AssemblyRunParams } from '../types'

const wsListeners: Array<(eventType: string, data: any) => void> = []
const apiGetMock = vi.fn()
const apiPostMock = vi.fn()
const apiDeleteMock = vi.fn()

vi.mock('../../../bridge/electron-bridge', () => ({
  API_BASE: '',
  onEvent: (handler: (eventType: string, data: any) => void) => {
    wsListeners.push(handler)
    return () => {
      const idx = wsListeners.indexOf(handler)
      if (idx >= 0) wsListeners.splice(idx, 1)
    }
  },
  apiGet: (...args: any[]) => apiGetMock(...args),
  apiPost: (...args: any[]) => apiPostMock(...args),
  apiDelete: (...args: any[]) => apiDeleteMock(...args),
}))

vi.mock('../../../utils/fileDownloader', () => ({
  downloadFileFromUrl: vi.fn(),
}))

function mountAssemblyComposable() {
  let state!: ReturnType<typeof useAssembly>
  const Harness = defineComponent({
    setup() {
      state = useAssembly()
      return () => null
    },
  })
  const wrapper = mount(Harness)
  return { state, wrapper }
}

const sampleParams: AssemblyRunParams = {
  name: 'Asm_Queued_Second',
  sample_type: 'BACTERIA',
  tech: 'ILLUMINA',
  mode: 'isolate',
  r1_path: 'data/r1.fastq.gz',
}

describe('useAssembly queue state transitions', () => {
  beforeEach(() => {
    wsListeners.length = 0
    vi.clearAllMocks()

    apiGetMock.mockImplementation((url: string) => {
      if (url === '/api/assembly/history') {
        return Promise.resolve({
          data: [
            {
              id: 'Asm_1',
              name: 'Asm_First',
              status: 'running',
              progress: 35,
              created_at: 1000,
              updated_at: 1001,
            },
          ],
        })
      }
      if (url === '/api/assembly/queue') {
        return Promise.resolve({
          data: {
            running_task: { id: 'Asm_1', name: 'Asm_First', status: 'running', progress: 35, created_at: 1000, updated_at: 1001 },
            waiting_count: 0,
            waiting_tasks: [],
            is_busy: true,
          },
        })
      }
      return Promise.resolve({ data: {} })
    })
  })

  it('keeps second task queued even when waiting queue_position equals 1 while engine is busy', async () => {
    const { state, wrapper } = mountAssemblyComposable()
    await flushPromises()

    apiPostMock.mockResolvedValueOnce({
      success: true,
      task_id: 'Asm_2',
      status: 'queued',
      is_busy: true,
      queue_position: 1,
    })

    await state.submitTask(sampleParams)
    await flushPromises()

    expect(state.currentTask.value?.id).toBe('Asm_2')
    expect(state.currentTask.value?.status).toBe('queued')
    expect(state.currentTask.value?.queue_position).toBe(1)
    expect(state.isRunning.value).toBe(false)

    // 前置任务结束，WS 派发到 Asm_2 开始运行
    for (const listener of wsListeners) {
      listener('assembly_queue_status', {
        current_task_id: 'Asm_2',
        is_busy: true,
        waiting_count: 0,
        waiting_tasks: [],
        running_task: { id: 'Asm_2', name: 'Asm_Queued_Second', status: 'running' },
        queue: [{ id: 'Asm_2', name: 'Asm_Queued_Second', status: 'running', position: 1 }],
      })
    }
    await flushPromises()

    expect(state.currentTask.value?.status).toBe('running')
    expect(state.isRunning.value).toBe(true)
    wrapper.unmount()
  })

  it('starts immediately for a single idle task even if legacy backend responds queued without busy flag', async () => {
    apiGetMock.mockImplementation((url: string) => {
      if (url === '/api/assembly/history') {
        return Promise.resolve({ data: [] })
      }
      if (url === '/api/assembly/queue') {
        return Promise.resolve({
          data: { running_task: null, waiting_count: 0, waiting_tasks: [], is_busy: false },
        })
      }
      return Promise.resolve({ data: {} })
    })

    const { state, wrapper } = mountAssemblyComposable()
    await flushPromises()

    apiPostMock.mockResolvedValueOnce({
      success: true,
      task_id: 'Asm_Single_1',
      status: 'queued',
      is_busy: false,
      queue_position: 1,
    })

    await state.submitTask(sampleParams)
    await flushPromises()

    expect(state.currentTask.value?.status).toBe('running')
    expect(state.isRunning.value).toBe(true)
    wrapper.unmount()
  })

  it('does not revert running task to queued when WS wins race before HTTP response', async () => {
    apiGetMock.mockImplementation((url: string) => {
      if (url === '/api/assembly/history') {
        return Promise.resolve({ data: [] })
      }
      if (url === '/api/assembly/queue') {
        return Promise.resolve({
          data: { running_task: null, waiting_count: 0, waiting_tasks: [], is_busy: false },
        })
      }
      return Promise.resolve({ data: {} })
    })

    const { state, wrapper } = mountAssemblyComposable()
    await flushPromises()

    let resolvePost!: (val: any) => void
    apiPostMock.mockReturnValueOnce(
      new Promise((resolve) => {
        resolvePost = resolve
      })
    )

    const submitPromise = state.submitTask(sampleParams)
    const submittedId = state.currentTask.value!.id

    // 模拟在 POST HTTP 返回之前 WS 已经抢先推进任务状态与日志
    for (const listener of wsListeners) {
      listener('assembly_queue_status', {
        current_task_id: submittedId,
        is_busy: true,
        waiting_count: 0,
        waiting_tasks: [],
        running_task: { id: submittedId, name: 'Asm_Single_Race', status: 'running' },
      })
      listener('assembly_progress', {
        task_id: submittedId,
        step: '测序数据质控',
        progress: 12,
        status: 'running',
      })
    }

    // 即使晚到的 HTTP 响应携带旧风格 queued 也不允许倒退
    resolvePost({
      success: true,
      task_id: submittedId,
      status: 'queued',
      is_busy: false,
      queue_position: 1,
    })
    await submitPromise
    await flushPromises()

    expect(state.currentTask.value?.status).toBe('running')
    expect(state.isRunning.value).toBe(true)
    wrapper.unmount()
  })

  it('self-heals queued focus task when fetchHistory or assembly_log confirms running', async () => {
    apiGetMock.mockImplementation((url: string) => {
      if (url === '/api/assembly/history') {
        return Promise.resolve({
          data: [
            {
              id: 'Asm_Heal_1',
              name: 'HealTask',
              status: 'running',
              last_step: 'NGCS组装',
              progress: 18,
              created_at: 2000,
              updated_at: 2005,
            },
          ],
        })
      }
      if (url === '/api/assembly/queue') {
        return Promise.resolve({
          data: {
            running_task: { id: 'Asm_Heal_1', name: 'HealTask', status: 'running' },
            waiting_count: 0,
            waiting_tasks: [],
            is_busy: true,
          },
        })
      }
      return Promise.resolve({ data: {} })
    })

    const { state, wrapper } = mountAssemblyComposable()
    await flushPromises()

    state.activeTaskId.value = 'Asm_Heal_1'
    state.currentTask.value = {
      id: 'Asm_Heal_1',
      name: 'HealTask',
      sample_type: 'BACTERIA',
      tech: 'ILLUMINA',
      status: 'queued',
      progress: 0,
      last_step: '排队中 (#1)',
      created_at: 2000,
      updated_at: 2001,
    }
    state.isRunning.value = false

    // 1. 收到 assembly_log 时立即纠偏
    for (const listener of wsListeners) {
      listener('assembly_log', { task_id: 'Asm_Heal_1', line: '[NGCS QC] Running fastp...' })
    }
    expect(state.currentTask.value.status).toBe('running')
    expect(state.isRunning.value).toBe(true)

    // 2. 假设再次被误置回 queued，fetchHistory 也能拉回 running 与进度
    state.currentTask.value.status = 'queued'
    state.isRunning.value = false
    await state.fetchHistory()
    expect(state.currentTask.value.status).toBe('running')
    expect(state.currentTask.value.progress).toBe(18)
    expect(state.isRunning.value).toBe(true)
    wrapper.unmount()
  })
})
