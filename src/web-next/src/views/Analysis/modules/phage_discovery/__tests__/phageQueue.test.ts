import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import PhageDiscoveryModule from '../PhageDiscoveryModule.vue'
import type { PhageScanForm } from '../types'

const wsListeners: Array<(eventType: string, data: any) => void> = []

const mockBridge = {
  get_phage_discovery_models: vi.fn(),
  get_phage_discovery_queue_status: vi.fn(),
  get_phage_discovery_history: vi.fn(),
  run_phage_discovery_task: vi.fn(),
  cancel_phage_discovery_task: vi.fn(),
  inspect_phage_discovery_fasta: vi.fn(),
  get_phage_discovery_result: vi.fn(),
  get_assembly_history: vi.fn(),
}

vi.mock('../../../../../bridge/electron-bridge', () => ({
  getBridge: () => mockBridge,
  onEvent: (handler: (eventType: string, data: any) => void) => {
    wsListeners.push(handler)
    return () => {
      const idx = wsListeners.indexOf(handler)
      if (idx >= 0) wsListeners.splice(idx, 1)
    }
  },
}))

const SetupStub = defineComponent({
  name: 'PhageDiscoverySetup',
  props: ['isQueueBusy'],
  emits: ['submit', 'inspect', 'save-config', 'refresh-capabilities'],
  setup(props) {
    return () =>
      h('div', { class: 'setup-stub', 'data-queue-busy': String(props.isQueueBusy) }, 'setup')
  },
})

function buildSampleForm(): PhageScanForm {
  return {
    task_name: 'NC_003197_SecondScan',
    fasta_path: 'data/demo.fna',
    fasta_content: '',
    selected_contigs: [],
    custom_model_dir: '',
    device: 'cuda',
    workers: 2,
    apply_protein_gate: false,
    blast_db: '',
    seed_threshold: 0.95,
    extend_threshold: 0.3,
    sub_threshold: 0.45,
    merge_gap_bp: 3000,
    min_region_bp: 3000,
  }
}

describe('PhageDiscovery queuing UI behavior', () => {
  beforeEach(() => {
    wsListeners.length = 0
    vi.clearAllMocks()

    mockBridge.get_phage_discovery_models.mockResolvedValue({
      has_model: true,
      models: [{ model_id: 'student_v4_2', version: 'V4.2', label: 'Student V4.2' }],
      compute: { default_device: 'cuda', cuda_available: true, cpu_count: 8, safe_workers: 4 },
      protein_gate: { ready: false },
    })

    mockBridge.get_phage_discovery_history.mockResolvedValue({
      tasks: [
        {
          task_id: 'phage_running_1',
          task_name: 'Genome_Running_First',
          model_id: 'student_v4_2',
          model_version: 'V4.2',
          device: 'cuda',
          apply_protein_gate: false,
          status: 'running',
          progress: 40,
          current_step: '正在执行滑动窗口...',
          created_at: '2026-11-14 01:07:00',
          updated_at: '2026-11-14 01:07:01',
          summary: {},
          files: {},
          result_path: '',
        },
      ],
    })

    mockBridge.get_phage_discovery_queue_status.mockResolvedValue({
      max_workers: 1,
      is_busy: true,
      running: ['phage_running_1'],
      queued: [],
      running_count: 1,
      queued_count: 0,
      running_tasks: [
        {
          task_id: 'phage_running_1',
          task_name: 'Genome_Running_First',
          status: 'running',
        },
      ],
      waiting_tasks: [],
    })

    mockBridge.run_phage_discovery_task.mockResolvedValue({
      task_id: 'phage_queued_2',
      status: 'queued',
      queue_position: 1,
      is_busy: true,
      running_count: 1,
      queued_count: 1,
      device: 'cuda',
      model: { model_id: 'student_v4_2' },
    })
  })

  it('renders PhageDiscoveryQueueCard instead of PhageDiscoveryProgress when submitted while queue is busy', async () => {
    const wrapper = mount(PhageDiscoveryModule, {
      global: {
        stubs: {
          PhageDiscoverySetup: SetupStub,
          PhageDiscoveryResults: true,
        },
      },
    })
    await flushPromises()

    const setupEl = wrapper.findComponent(SetupStub)
    expect(setupEl.exists()).toBe(true)
    expect(setupEl.attributes('data-queue-busy')).toBe('true')

    mockBridge.get_phage_discovery_queue_status.mockResolvedValue({
      max_workers: 1,
      is_busy: true,
      running: ['phage_running_1'],
      queued: ['phage_queued_2'],
      running_count: 1,
      queued_count: 1,
      running_tasks: [{ task_id: 'phage_running_1', task_name: 'Genome_Running_First' }],
      waiting_tasks: [{ task_id: 'phage_queued_2', task_name: 'NC_003197_SecondScan', position: 1 }],
    })

    setupEl.vm.$emit('submit', buildSampleForm())
    await flushPromises()

    expect(wrapper.find('.phage-queue-card').exists()).toBe(true)
    expect(wrapper.find('.progress-card').exists()).toBe(false)
    expect(wrapper.text()).toContain('前噬菌体扫描任务正在排队等待中')
    expect(wrapper.text()).toContain('#1')
    expect(wrapper.text()).toContain('Genome_Running_First')

    // 后端推送队列快照：前序结束，本任务出队开始运行 -> 平滑切换至 PhageDiscoveryProgress
    for (const listener of wsListeners) {
      listener('phage_discovery_queue_update', {
        max_workers: 1,
        is_busy: true,
        running: ['phage_queued_2'],
        queued: [],
        running_count: 1,
        queued_count: 0,
        running_tasks: [{ task_id: 'phage_queued_2', task_name: 'NC_003197_SecondScan' }],
        waiting_tasks: [],
      })
    }
    await flushPromises()

    expect(wrapper.find('.phage-queue-card').exists()).toBe(false)
    expect(wrapper.find('.progress-card').exists()).toBe(true)
    wrapper.unmount()
  })
})
