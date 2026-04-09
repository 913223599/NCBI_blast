/**
 * 标签显示模式 (Label Display Mode) 单元测试
 * 
 * 测试三种标签显示模式：
 * - replace: 仅显示物种名（覆盖原始 ID）
 * - append: 显示 [物种名] ID
 * - original: 仅显示原始 ID
 */
import { describe, it, expect, beforeEach } from 'vitest'
import type { LayoutSettings } from '../../core/tree/layout/LayoutEngine'

describe('Label Display Mode', () => {
  // Mock annotations map
  const mockAnnotations = {
    'SEQ001': 'Escherichia coli',
    'SEQ002': 'Homo sapiens',
    'SEQ003': 'Mus musculus'
  }

  /**
   * 模拟 HybridRenderer 的标签渲染逻辑
   */
  function renderLabel(
    nodeId: string,
    labelDisplayMode: 'replace' | 'append' | 'original',
    annotations: Record<string, string>
  ): string {
    let displayName = nodeId
    const annotation = annotations[nodeId]

    if (annotation) {
      if (labelDisplayMode === 'replace') {
        displayName = annotation  // 仅显示物种名
      } else if (labelDisplayMode === 'append') {
        displayName = `[${annotation}] ${nodeId}`  // 物种名 + ID
      }
      // 'original' 模式：保持 displayName 不变（只显示 ID）
    }

    return displayName
  }

  /**
   * 模拟 PhylotreeWidget 的标签渲染逻辑
   */
  function renderLabelPhylotree(
    nodeId: string,
    labelDisplayMode: 'replace' | 'append' | 'original',
    annotations: Record<string, string>
  ): string {
    // 清理节点 ID 中的引号和空格（与 PhylotreeWidget.vue 第 112 行一致）
    const cleanId = nodeId.replace(/^['"]|['"]$/g, '').trim()
    const annotation = annotations[cleanId]

    if (!annotation || labelDisplayMode === 'original') return cleanId
    if (labelDisplayMode === 'append') return `[${annotation}] ${cleanId}`
    return annotation // 'replace' 模式
  }

  describe('HybridRenderer 标签渲染', () => {
    it('应该在 replace 模式下仅显示物种名', () => {
      const result = renderLabel('SEQ001', 'replace', mockAnnotations)
      expect(result).toBe('Escherichia coli')
    })

    it('应该在 append 模式下显示 [物种名] ID', () => {
      const result = renderLabel('SEQ001', 'append', mockAnnotations)
      expect(result).toBe('[Escherichia coli] SEQ001')
    })

    it('应该在 original 模式下仅显示原始 ID', () => {
      const result = renderLabel('SEQ001', 'original', mockAnnotations)
      expect(result).toBe('SEQ001')
    })

    it('应该在没有注释时始终返回原始 ID', () => {
      const resultReplace = renderLabel('UNKNOWN', 'replace', mockAnnotations)
      const resultAppend = renderLabel('UNKNOWN', 'append', mockAnnotations)
      const resultOriginal = renderLabel('UNKNOWN', 'original', mockAnnotations)
      
      expect(resultReplace).toBe('UNKNOWN')
      expect(resultAppend).toBe('UNKNOWN')
      expect(resultOriginal).toBe('UNKNOWN')
    })

    it('应该正确处理多个节点的标签渲染', () => {
      const nodes = ['SEQ001', 'SEQ002', 'SEQ003']
      
      const replaceLabels = nodes.map(id => renderLabel(id, 'replace', mockAnnotations))
      expect(replaceLabels).toEqual([
        'Escherichia coli',
        'Homo sapiens',
        'Mus musculus'
      ])

      const appendLabels = nodes.map(id => renderLabel(id, 'append', mockAnnotations))
      expect(appendLabels).toEqual([
        '[Escherichia coli] SEQ001',
        '[Homo sapiens] SEQ002',
        '[Mus musculus] SEQ003'
      ])

      const originalLabels = nodes.map(id => renderLabel(id, 'original', mockAnnotations))
      expect(originalLabels).toEqual(['SEQ001', 'SEQ002', 'SEQ003'])
    })
  })

  describe('PhylotreeWidget 标签渲染', () => {
    it('应该在 replace 模式下仅显示物种名', () => {
      const result = renderLabelPhylotree('SEQ001', 'replace', mockAnnotations)
      expect(result).toBe('Escherichia coli')
    })

    it('应该在 append 模式下显示 [物种名] ID', () => {
      const result = renderLabelPhylotree('SEQ001', 'append', mockAnnotations)
      expect(result).toBe('[Escherichia coli] SEQ001')
    })

    it('应该在 original 模式下仅显示原始 ID', () => {
      const result = renderLabelPhylotree('SEQ001', 'original', mockAnnotations)
      expect(result).toBe('SEQ001')
    })

    it('应该在没有注释时始终返回原始 ID', () => {
      const resultReplace = renderLabelPhylotree('UNKNOWN', 'replace', mockAnnotations)
      const resultAppend = renderLabelPhylotree('UNKNOWN', 'append', mockAnnotations)
      const resultOriginal = renderLabelPhylotree('UNKNOWN', 'original', mockAnnotations)
      
      expect(resultReplace).toBe('UNKNOWN')
      expect(resultAppend).toBe('UNKNOWN')
      expect(resultOriginal).toBe('UNKNOWN')
    })

    it('应该清理节点 ID 中的引号和空格', () => {
      const result = renderLabelPhylotree("'SEQ001'", 'replace', mockAnnotations)
      expect(result).toBe('Escherichia coli')
    })
  })

  describe('两种渲染引擎的一致性', () => {
    it('应该在 replace 模式下产生相同的结果', () => {
      const nodeIds = ['SEQ001', 'SEQ002', 'SEQ003']
      
      nodeIds.forEach(id => {
        const hybridResult = renderLabel(id, 'replace', mockAnnotations)
        const phylotreeResult = renderLabelPhylotree(id, 'replace', mockAnnotations)
        expect(hybridResult).toBe(phylotreeResult)
      })
    })

    it('应该在 append 模式下产生相同的结果', () => {
      const nodeIds = ['SEQ001', 'SEQ002', 'SEQ003']
      
      nodeIds.forEach(id => {
        const hybridResult = renderLabel(id, 'append', mockAnnotations)
        const phylotreeResult = renderLabelPhylotree(id, 'append', mockAnnotations)
        expect(hybridResult).toBe(phylotreeResult)
      })
    })

    it('应该在 original 模式下产生相同的结果', () => {
      const nodeIds = ['SEQ001', 'SEQ002', 'SEQ003']
      
      nodeIds.forEach(id => {
        const hybridResult = renderLabel(id, 'original', mockAnnotations)
        const phylotreeResult = renderLabelPhylotree(id, 'original', mockAnnotations)
        expect(hybridResult).toBe(phylotreeResult)
      })
    })
  })

  describe('设置变更检测', () => {
    it('应该检测到 labelDisplayMode 的变化', () => {
      const lastSettings: Partial<LayoutSettings> = {
        sortMode: 'ascending',
        mode: 'rect',
        useBranchLengths: true,
        labelDisplayMode: 'original'
      }

      const newSettings: Partial<LayoutSettings> = {
        sortMode: 'ascending',
        mode: 'rect',
        useBranchLengths: true,
        labelDisplayMode: 'replace'
      }

      const isSettingsChanged = 
        (lastSettings.sortMode !== newSettings.sortMode) ||
        (lastSettings.mode !== newSettings.mode) ||
        (lastSettings.useBranchLengths !== newSettings.useBranchLengths) ||
        (lastSettings.labelDisplayMode !== newSettings.labelDisplayMode)

      expect(isSettingsChanged).toBe(true)
    })

    it('应该在 labelDisplayMode 未变化时不触发重绘', () => {
      const lastSettings: Partial<LayoutSettings> = {
        sortMode: 'ascending',
        mode: 'rect',
        useBranchLengths: true,
        labelDisplayMode: 'replace'
      }

      const newSettings: Partial<LayoutSettings> = {
        sortMode: 'ascending',
        mode: 'rect',
        useBranchLengths: true,
        labelDisplayMode: 'replace'
      }

      const isSettingsChanged = 
        (lastSettings.sortMode !== newSettings.sortMode) ||
        (lastSettings.mode !== newSettings.mode) ||
        (lastSettings.useBranchLengths !== newSettings.useBranchLengths) ||
        (lastSettings.labelDisplayMode !== newSettings.labelDisplayMode)

      expect(isSettingsChanged).toBe(false)
    })

    it('应该在其他设置变化时也正确检测', () => {
      const lastSettings: Partial<LayoutSettings> = {
        sortMode: 'ascending',
        mode: 'rect',
        useBranchLengths: true,
        labelDisplayMode: 'replace'
      }

      const newSettings: Partial<LayoutSettings> = {
        sortMode: 'descending', // 只有这个变了
        mode: 'rect',
        useBranchLengths: true,
        labelDisplayMode: 'replace'
      }

      const isSettingsChanged = 
        (lastSettings.sortMode !== newSettings.sortMode) ||
        (lastSettings.mode !== newSettings.mode) ||
        (lastSettings.useBranchLengths !== newSettings.useBranchLengths) ||
        (lastSettings.labelDisplayMode !== newSettings.labelDisplayMode)

      expect(isSettingsChanged).toBe(true)
    })
  })

  describe('边界情况', () => {
    it('应该处理空字符串 ID', () => {
      const result = renderLabel('', 'replace', mockAnnotations)
      expect(result).toBe('')
    })

    it('应该处理包含特殊字符的 ID', () => {
      const specialAnnotations = {
        'SEQ-001_TEST': 'Test Species'
      }
      
      const resultReplace = renderLabel('SEQ-001_TEST', 'replace', specialAnnotations)
      const resultAppend = renderLabel('SEQ-001_TEST', 'append', specialAnnotations)
      
      expect(resultReplace).toBe('Test Species')
      expect(resultAppend).toBe('[Test Species] SEQ-001_TEST')
    })

    it('应该处理空注释对象', () => {
      const emptyAnnotations: Record<string, string> = {}
      
      const result = renderLabel('SEQ001', 'replace', emptyAnnotations)
      expect(result).toBe('SEQ001')
    })

    it('应该处理 undefined 和 null 值', () => {
      const mixedAnnotations = {
        'SEQ001': 'Species A',
        'SEQ002': '',
        'SEQ003': undefined as any
      }
      
      const result1 = renderLabel('SEQ001', 'replace', mixedAnnotations)
      const result2 = renderLabel('SEQ002', 'replace', mixedAnnotations)
      const result3 = renderLabel('SEQ003', 'replace', mixedAnnotations)
      
      expect(result1).toBe('Species A')
      expect(result2).toBe('SEQ002') // 空字符串被视为无注释，返回原始 ID
      expect(result3).toBe('SEQ003') // undefined 被视为无注释
    })
  })

  describe('性能测试', () => {
    it('应该能快速渲染大量节点', () => {
      // 生成 10000 个节点
      const largeAnnotations: Record<string, string> = {}
      for (let i = 0; i < 10000; i++) {
        largeAnnotations[`SEQ${i.toString().padStart(5, '0')}`] = `Species ${i}`
      }

      const startTime = performance.now()
      
      // 渲染所有节点
      for (let i = 0; i < 10000; i++) {
        renderLabel(`SEQ${i.toString().padStart(5, '0')}`, 'replace', largeAnnotations)
      }
      
      const endTime = performance.now()
      const duration = endTime - startTime
      
      // 应该在 100ms 内完成
      expect(duration).toBeLessThan(100)
    })
  })
})
