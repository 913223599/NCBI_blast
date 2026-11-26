import { beforeEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { isKnownLocaleKey, STATIC_LOCALES, translateKey, type LocaleKey } from '../../locales'
import { useAppStore } from '../../stores/app'
import AnalysisView from '../AnalysisView.vue'
import FigureStudioView from '../FigureStudioView.vue'
import OtherToolsView from '../OtherToolsView.vue'
import AssemblyResults from '../Assembly/components/AssemblyResults.vue'
import AssemblyHistory from '../Assembly/components/AssemblyHistory.vue'
import AssemblyProgress from '../Assembly/components/AssemblyProgress.vue'
import StrainSidebar from '../../components/strain/StrainSidebar.vue'
import ViridicHeatmapTool from '../../modules/figure_studio/components/ViridicHeatmapTool.vue'
import HostMatrixTool from '../../modules/figure_studio/components/HostMatrixTool.vue'

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

  it('Batch P2A 深层子组件与强类型 LocaleKey 应支持中英即时切换且无键名泄漏', async () => {
    const appStore = useAppStore()
    appStore.setLocale('zh_CN')

    const sampleKey: LocaleKey = 'phylo.wb.mode.phage_taxonomy'
    expect(isKnownLocaleKey(sampleKey)).toBe(true)
    expect(isKnownLocaleKey('non.existent.key.xyz')).toBe(false)
    expect(translateKey(sampleKey, 'en_US')).toBe('Phage Taxonomy (8-Step Pipeline)')
    expect(Object.keys(STATIC_LOCALES.zh_CN).length).toBe(Object.keys(STATIC_LOCALES.en_US).length)

    const asmHistory = mount(AssemblyHistory, {
      props: { tasks: [], activeId: '', isLoading: false },
    })
    const asmProgress = mount(AssemblyProgress, {
      props: {
        task: { id: 'T1', name: 'Demo_Phage', status: 'running', tech: 'ILLUMINA', progress: 45 } as any,
        logs: [],
      },
    })
    const sidebar = mount(StrainSidebar)
    const viridic = mount(ViridicHeatmapTool)
    const hostMatrix = mount(HostMatrixTool)

    expect(asmHistory.text()).toContain('暂无拼接历史')
    expect(asmProgress.text()).toContain('终止组装')
    expect(sidebar.text()).toContain('保藏管理')
    expect(viridic.text()).toContain('VIRIDIC 双向热图与 ANI 矩阵')
    expect(hostMatrix.text()).toContain('双树宿主谱热图与特异性矩阵')

    appStore.setLocale('en_US')
    await asmHistory.vm.$nextTick()
    await asmProgress.vm.$nextTick()
    await sidebar.vm.$nextTick()
    await viridic.vm.$nextTick()
    await hostMatrix.vm.$nextTick()

    expect(asmHistory.text()).toContain('No assembly history yet')
    expect(asmProgress.text()).toContain('Stop Assembly')
    expect(sidebar.text()).toContain('Biobank Inventory')
    expect(viridic.text()).toContain('VIRIDIC Dual Heatmap & ANI Matrix')
    expect(hostMatrix.text()).toContain('Dual-Tree Host Range & Specificity Matrix')

    expect(viridic.text()).not.toContain('studio.viridic.')
    expect(hostMatrix.text()).not.toContain('studio.host.')
    expect(asmHistory.text()).not.toContain('assembly.history.')

    appStore.setLocale('zh_CN')
  })
})
