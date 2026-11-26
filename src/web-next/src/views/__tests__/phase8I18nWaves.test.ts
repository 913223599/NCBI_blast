import { beforeEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { useAppStore } from '../../stores/app'
import AnalysisView from '../AnalysisView.vue'
import FigureStudioView from '../FigureStudioView.vue'
import OtherToolsView from '../OtherToolsView.vue'
import AssemblyResults from '../Assembly/components/AssemblyResults.vue'

describe('Phase 8 Wave 2-4 全站核心业务视图中英双语即时切换测试', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('AnalysisView、FigureStudioView、OtherToolsView 与 AssemblyResults 应在切换 en_US 后完整切换为英文', async () => {
    const appStore = useAppStore()
    appStore.setLocale('zh_CN')

    const analysis = mount(AnalysisView)
    const studio = mount(FigureStudioView)
    const other = mount(OtherToolsView)
    const asmResults = mount(AssemblyResults, {
      props: {
        task: {
          id: 'ASM_01',
          name: 'Phage_Demo',
          status: 'completed',
          tech: 'ILLUMINA',
          sample_type: 'PHAGE',
          duration_seconds: 12,
        } as any,
        result: {
          task_id: 'ASM_01',
          stats: {
            total_length: 48502,
            contigs: 1,
            max_contig_length: 48502,
            n50: 48502,
            gc_percent: 49.8,
            avg_depth: 120.5,
            is_circular: true,
          },
          contigs: [],
        } as any,
      },
    })

    expect(analysis.text()).toContain('组装分析工作台')
    expect(studio.text()).toContain('科研绘图工坊')
    expect(other.text()).toContain('自动化流水线')
    expect(asmResults.text()).toContain('组装完成')

    appStore.setLocale('en_US')
    await analysis.vm.$nextTick()
    await studio.vm.$nextTick()
    await other.vm.$nextTick()
    await asmResults.vm.$nextTick()

    expect(analysis.text()).toContain('Post-Assembly Analysis Workbench')
    expect(analysis.text()).toContain('Phage Structure & Tail Morphotype Prediction')
    expect(studio.text()).toContain('Figure Studio')
    expect(studio.text()).toContain('Citations (BibTeX)')
    expect(other.text()).toContain('Automation Pipelines')
    expect(asmResults.text()).toContain('Completed')
    expect(asmResults.text()).toContain('Download FASTA')

    // 确保无未翻译的原始 i18n 键泄漏
    expect(analysis.text()).not.toContain('analysis.hub.title')
    expect(studio.text()).not.toContain('studio.hub.title')
    expect(other.text()).not.toContain('other.hub.title')
    expect(asmResults.text()).not.toContain('assembly.results.')

    appStore.setLocale('zh_CN')
  })
})
