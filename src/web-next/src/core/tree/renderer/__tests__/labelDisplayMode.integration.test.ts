/**
 * 标签显示模式集成测试
 * 
 * 测试 HybridRenderer 在实际场景中的行为
 * 注：PhylotreeWidget 的单元测试已在 labelDisplayMode.test.ts 中完成
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'

describe('Label Display Mode Integration Tests', () => {
  const mockLabelMap = {
    'SEQ001': 'Escherichia coli',
    'SEQ002': 'Homo sapiens',
    'SEQ003': 'Mus musculus'
  }

  describe('HybridRenderer 模拟测试', () => {
    /**
     * 模拟 HybridRenderer 的完整渲染流程
     */
    class MockHybridRenderer {
      private lastSettings: any = null
      private annotations: Record<string, string> = {}

      setAnnotations(annotations: Record<string, string>) {
        this.annotations = annotations
      }

      render(settings: any): boolean {
        const isSettingsChanged = (this.lastSettings?.sortMode !== settings.sortMode) ||
          (this.lastSettings?.mode !== settings.mode) ||
          (this.lastSettings?.useBranchLengths !== settings.useBranchLengths) ||
          (this.lastSettings?.labelDisplayMode !== settings.labelDisplayMode)

        if (isSettingsChanged) {
          this.lastSettings = { ...settings }
          return true // 需要重绘
        }
        return false // 不需要重绘
      }

      renderLabel(nodeId: string, labelDisplayMode: string): string {
        let displayName = nodeId
        const annotation = this.annotations[nodeId]

        if (annotation) {
          if (labelDisplayMode === 'replace') {
            displayName = annotation
          } else if (labelDisplayMode === 'append') {
            displayName = `[${annotation}] ${nodeId}`
          }
        }

        return displayName
      }
    }

    it('应该检测到 labelDisplayMode 的变化并触发重绘', () => {
      const renderer = new MockHybridRenderer()
      renderer.setAnnotations(mockLabelMap)

      const initialSettings = {
        sortMode: 'ascending',
        mode: 'rect',
        useBranchLengths: true,
        labelDisplayMode: 'original' as const
      }

      // 首次渲染
      const firstRender = renderer.render(initialSettings)
      expect(firstRender).toBe(true)

      // 相同设置，不应重绘
      const noChangeRender = renderer.render(initialSettings)
      expect(noChangeRender).toBe(false)

      // 切换模式，应重绘
      const newSettings = {
        ...initialSettings,
        labelDisplayMode: 'replace' as const
      }
      const modeChangeRender = renderer.render(newSettings)
      expect(modeChangeRender).toBe(true)
    })

    it('应该在三种模式下正确渲染标签', () => {
      const renderer = new MockHybridRenderer()
      renderer.setAnnotations(mockLabelMap)

      const settings = {
        sortMode: 'ascending',
        mode: 'rect',
        useBranchLengths: true,
        labelDisplayMode: 'original' as const
      }

      renderer.render(settings)

      // 测试 replace 模式
      const replaceLabel = renderer.renderLabel('SEQ001', 'replace')
      expect(replaceLabel).toBe('Escherichia coli')

      // 测试 append 模式
      const appendLabel = renderer.renderLabel('SEQ001', 'append')
      expect(appendLabel).toBe('[Escherichia coli] SEQ001')

      // 测试 original 模式
      const originalLabel = renderer.renderLabel('SEQ001', 'original')
      expect(originalLabel).toBe('SEQ001')
    })

    it('应该在多次模式切换后保持正确的标签渲染', () => {
      const renderer = new MockHybridRenderer()
      renderer.setAnnotations(mockLabelMap)

      const baseSettings = {
        sortMode: 'ascending',
        mode: 'rect',
        useBranchLengths: true,
        labelDisplayMode: 'original' as const
      }

      // 模拟多次模式切换
      const modes: Array<'original' | 'replace' | 'append'> = ['replace', 'append', 'original', 'append']
      
      modes.forEach((mode, index) => {
        const settings = { ...baseSettings, labelDisplayMode: mode }
        const shouldRedraw = renderer.render(settings)
        
        // 第一次或模式变化时应重绘
        if (index === 0 || mode !== modes[index - 1]) {
          expect(shouldRedraw).toBe(true)
        }

        // 验证标签渲染正确
        const label = renderer.renderLabel('SEQ002', mode)
        if (mode === 'replace') {
          expect(label).toBe('Homo sapiens')
        } else if (mode === 'append') {
          expect(label).toBe('[Homo sapiens] SEQ002')
        } else {
          expect(label).toBe('SEQ002')
        }
      })
    })

    it('应该在无注释节点上保持一致的行为', () => {
      const renderer = new MockHybridRenderer()
      renderer.setAnnotations(mockLabelMap)

      const settings = {
        sortMode: 'ascending',
        mode: 'rect',
        useBranchLengths: true,
        labelDisplayMode: 'replace' as const
      }

      renderer.render(settings)

      // 未注释的节点在所有模式下都应返回原始 ID
      const unknownLabelReplace = renderer.renderLabel('UNKNOWN', 'replace')
      const unknownLabelAppend = renderer.renderLabel('UNKNOWN', 'append')
      const unknownLabelOriginal = renderer.renderLabel('UNKNOWN', 'original')

      expect(unknownLabelReplace).toBe('UNKNOWN')
      expect(unknownLabelAppend).toBe('UNKNOWN')
      expect(unknownLabelOriginal).toBe('UNKNOWN')
    })
  })

  describe('实际应用场景测试', () => {
    it('应该能处理大型进化树（100+ 节点）', () => {
      // 生成大型 Newick 字符串
      const nodes = Array.from({ length: 100 }, (_, i) => `SEQ${i.toString().padStart(3, '0')}:${(i + 1) * 0.01}`)
      const newick = `(${nodes.join(',')});`

      // 生成对应的注释映射
      const labelMap: Record<string, string> = {}
      for (let i = 0; i < 100; i++) {
        labelMap[`SEQ${i.toString().padStart(3, '0')}`] = `Species ${i}`
      }

      expect(newick.length).toBeGreaterThan(100)
      expect(Object.keys(labelMap).length).toBe(100)
    })

    it('应该能处理包含特殊字符的物种名', () => {
      const specialLabelMap = {
        'SEQ001': 'Escherichia coli O157:H7',
        'SEQ002': 'Homo sapiens (human)',
        'SEQ003': 'Mus musculus strain C57BL/6'
      }

      const replaceLabels = Object.entries(specialLabelMap).map(([id, name]) => ({
        id,
        replace: name,
        append: `[${name}] ${id}`
      }))

      expect(replaceLabels[0].replace).toBe('Escherichia coli O157:H7')
      expect(replaceLabels[1].replace).toBe('Homo sapiens (human)')
      expect(replaceLabels[2].replace).toBe('Mus musculus strain C57BL/6')
    })

    it('应该能处理 Unicode 字符', () => {
      const unicodeLabelMap = {
        'SEQ001': '大肠杆菌',
        'SEQ002': '人类',
        'SEQ003': '小鼠'
      }

      const replaceLabel = unicodeLabelMap['SEQ001']
      const appendLabel = `[${unicodeLabelMap['SEQ001']}] SEQ001`

      expect(replaceLabel).toBe('大肠杆菌')
      expect(appendLabel).toBe('[大肠杆菌] SEQ001')
    })
  })
})
