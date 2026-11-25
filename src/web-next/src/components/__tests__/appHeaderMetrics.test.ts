import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const apiGetMock = vi.fn()

vi.mock('../../bridge/electron-bridge', () => ({
  apiGet: (...args: unknown[]) => apiGetMock(...args),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: '/' }),
}))

describe('AppHeader 实时硬件微监控胶囊测试', () => {
  beforeEach(() => {
    apiGetMock.mockReset()
    setActivePinia(createPinia())
  })

  it('应渲染实时 CPU、RAM 与 GPU 算力百分比并在 Tooltip 展示显存与温度详情', async () => {
    apiGetMock.mockImplementation((endpoint: string) => {
      if (endpoint === '/api/health') {
        return Promise.resolve({ status: 'ok' })
      }
      if (String(endpoint).startsWith('/api/core/system_metrics')) {
        return Promise.resolve({
          cpu_percent: 25.0,
          memory_percent: 31.0,
          memory_used_gb: 10.0,
          memory_total_gb: 31.8,
          cpu_cores: 16,
          safe_cpu_budget: 12,
          gpu: {
            available: true,
            name: 'NVIDIA GeForce RTX 5060',
            utilization_percent: 7.0,
            used_vram_mb: 1092,
            free_vram_mb: 7031,
            total_vram_mb: 8123,
            vram_percent: 13.4,
            temperature_c: 44,
            source: 'nvidia-smi',
          },
        })
      }
      return Promise.resolve({})
    })

    const AppHeader = (await import('../layout/AppHeader.vue')).default
    const wrapper = mount(AppHeader, {
      global: {
        stubs: {
          CommandPaletteDialog: true,
          CitationsDialog: true,
        },
      },
    })
    await flushPromises()

    const pill = wrapper.find('button.metrics-pill')
    expect(pill.exists()).toBe(true)
    expect(pill.text()).toBe('CPU 25% · RAM 31% · GPU 7%')
    expect(pill.classes()).toContain('metrics-normal')

    const tooltip = pill.attributes('title') || ''
    expect(tooltip).toContain('NVIDIA GeForce RTX 5060')
    expect(tooltip).toContain('7%')
    expect(tooltip).toContain('1092/8123 MB')
    expect(tooltip).toContain('44°C')
  })

  it('高负载时应附加 metrics-high 警示样式并支持回退显存占比展示', async () => {
    apiGetMock.mockImplementation((endpoint: string) => {
      if (endpoint === '/api/health') {
        return Promise.resolve({ status: 'ok' })
      }
      return Promise.resolve({
        cpu_percent: 91.4,
        memory_percent: 50.0,
        memory_used_gb: 16.0,
        memory_total_gb: 32.0,
        cpu_cores: 16,
        safe_cpu_budget: 12,
        gpu: {
          available: true,
          name: 'CUDA Fallback',
          utilization_percent: null,
          used_vram_mb: 4000,
          free_vram_mb: 4000,
          total_vram_mb: 8000,
          vram_percent: 50.0,
          temperature_c: null,
          source: 'torch',
        },
      })
    })

    const AppHeader = (await import('../layout/AppHeader.vue')).default
    const wrapper = mount(AppHeader, {
      global: {
        stubs: {
          CommandPaletteDialog: true,
          CitationsDialog: true,
        },
      },
    })
    await flushPromises()

    const pill = wrapper.find('button.metrics-pill')
    expect(pill.text()).toBe('CPU 91% · RAM 50% · VRAM 50%')
    expect(pill.classes()).toContain('metrics-high')
  })
})
