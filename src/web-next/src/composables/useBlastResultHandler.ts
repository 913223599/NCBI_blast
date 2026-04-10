/**
 * useBlastResultHandler - BLAST结果处理组合式函数
 * 
 * 职责：
 * - 获取和解析任务结果
 * - 结果数据格式化
 * - CSV导出
 * - 批量翻译
 */
import { ref } from 'vue'
import { useBlastStore } from '../stores/blast'
import { useAppStore } from '../stores/app'
import { getBridge } from '../bridge/pyqt-bridge'

export function useBlastResultHandler() {
  const blast = useBlastStore()
  const appStore = useAppStore()
  const isTranslating = ref(false)

  /**
   * 获取任务结果并解析
   */
  function fetchTaskResults(taskId: string) {
    try {
      getBridge().get_task_results(taskId, (resStr) => {
        try {
          const resultsArray = JSON.parse(resStr)
          if (!Array.isArray(resultsArray)) return

          const hits: any[] = []
          for (const res of resultsArray) {
            const queryId = res.sequence_id || '未知序列'
            const csvFile = res.csv_file || ''
            
            if (res.status === 'pending' || res.status === 'running') {
              hits.push(createPendingHit(queryId, csvFile))
            } else if (res.data && Array.isArray(res.data) && res.data.length > 0) {
              hits.push(createSuccessHit(queryId, res.data[0], csvFile))
            } else {
              hits.push(createNoHitsHit(queryId, csvFile))
            }
          }
          
          // 按查询序列ID排序
          hits.sort((a, b) => 
            a.queryTitle.localeCompare(b.queryTitle, undefined, { 
              numeric: true, 
              sensitivity: 'base' 
            })
          )
          
          blast.setResults(hits, `分析结果 (${hits.length} 项)`)
        } catch (e) {
          console.error('[ResultHandler] Parse results error:', e)
          appStore.showNotification('解析结果失败', 'error')
        }
      })
    } catch (error) {
      console.error('[ResultHandler] Fetch results error:', error)
      appStore.showNotification('获取结果失败', 'error')
    }
  }

  /**
   * 创建等待中的结果条目
   */
  function createPendingHit(queryId: string, csvFile: string) {
    return {
      queryTitle: queryId,
      speciesName: '等待比对...',
      genusStrain: '',
      geneSource: '',
      seqType: '',
      host: '',
      alignLen: '',
      identity: 0,
      evalue: '-',
      accession: '-',
      hitTitle: '',
      translatedName: null,
      csvFile,
      rawSequence: ''
    }
  }

  /**
   * 创建成功的结果条目
   */
  function createSuccessHit(queryId: string, bestHit: any, csvFile: string) {
    return {
      queryTitle: queryId,
      speciesName: bestHit.species || 'Unknown',
      genusStrain: [bestHit.genus, bestHit.strain].filter(Boolean).join(' · ') || '',
      geneSource: bestHit.gene_source || bestHit.gene_type || '',
      seqType: bestHit.seq_type || '',
      host: bestHit.host || '',
      alignLen: bestHit.align_len || '',
      identity: parseFloat(bestHit.similarity) || 0,
      evalue: String(bestHit.evalue || 'N/A'),
      accession: bestHit.acc || 'N/A',
      hitTitle: bestHit.title || '',
      translatedName: null,
      consensusList: bestHit.consensusList || [],
      csvFile,
      rawSequence: bestHit.raw_sequence || ''
    }
  }

  /**
   * 创建无匹配的结果条目
   */
  function createNoHitsHit(queryId: string, csvFile: string) {
    return {
      queryTitle: queryId,
      speciesName: '未找到匹配项 (No Hits)',
      genusStrain: '',
      geneSource: '',
      seqType: '',
      host: '',
      alignLen: '',
      identity: 0,
      evalue: '-',
      accession: '-',
      hitTitle: '',
      translatedName: null,
      csvFile,
      rawSequence: ''
    }
  }

  /**
   * 导出结果为CSV
   */
  async function exportResults(): Promise<void> {
    if (blast.results.length === 0) {
      appStore.showNotification('没有结果可导出', 'warning')
      return
    }

    // 检查是否存在未翻译的条目
    const untranslatedCount = blast.results.filter(
      h => h.speciesName && !h.translatedName
    ).length
    
    if (untranslatedCount > 0) {
      const confirmMsg = `存在 ${untranslatedCount} 条未翻译的物种条目。是否翻译后再导出？\n\n点击"确定"进行批量翻译，点击"取消"将直接导出当前结果（保留空白的翻译列）。`
      if (window.confirm(confirmMsg)) {
        await translateAll()
        
        if (blast.results.filter(h => h.speciesName && !h.translatedName).length > 0) {
          appStore.showNotification('部分翻译可能未完成，将执行导出。', 'info')
        }
      }
    }

    const csvContent = generateCsvContent()
    
    try {
      getBridge().save_file(csvContent, 'blast_results.csv')
      appStore.showNotification('导出指令已发送', 'success')
    } catch (error) {
      console.error('[ResultHandler] Export error:', error)
      appStore.showNotification('导出失败', 'error')
    }
  }

  /**
   * 生成CSV内容
   */
  function generateCsvContent(): string {
    const headers = [
      '查询序列',
      '鉴定物种(中文翻译)',
      '鉴定概率分布(中文翻译)',
      '原始鉴定物种(拉丁文)',
      '原始鉴定概率分布(拉丁文)',
      '分类/菌株信息',
      '基因/序列库',
      '相似度 (Identity)',
      'E值',
      '访问号',
      '详细标题'
    ]
    
    const rows = blast.results.map(hit => formatHitToRow(hit))
    
    return [
      headers.join(','),
      ...rows.map(row => 
        row.map(cell => {
          const str = String(cell || '').replace(/"/g, '""')
          return `"${str}"`
        }).join(',')
      )
    ].join('\n')
  }

  /**
   * 格式化单个结果为CSV行
   */
  function formatHitToRow(hit: any): string[] {
    const fullTrans = hit.translatedName || ''
    let mainTrans = fullTrans
    let probTrans = '-'

    const fullOriginal = hit.speciesName || ''
    let mainOriginal = fullOriginal
    let probOriginal = '-'

    // 处理百分比分布(共识算法结果) - 翻译名
    if (fullTrans.includes('%') && fullTrans.includes('(')) {
      const matchT = fullTrans.match(/^([^,(]+)\s*\(/)
      if (matchT && matchT[1]) {
        mainTrans = matchT[1].trim()
        probTrans = fullTrans
      }
    }

    // 处理百分比分布 - 原始名
    if (fullOriginal.includes('%') && fullOriginal.includes('(')) {
      const matchO = fullOriginal.match(/^([^,(]+)\s*\(/)
      if (matchO && matchO[1]) {
        mainOriginal = matchO[1].trim()
        probOriginal = fullOriginal
      }
    }

    return [
      hit.queryTitle,
      mainTrans,
      probTrans,
      mainOriginal,
      probOriginal,
      hit.genusStrain,
      `${hit.geneSource} (${hit.seqType})`,
      `${hit.identity.toFixed(1)}%`,
      hit.evalue,
      hit.accession,
      hit.hitTitle
    ]
  }

  /**
   * 批量翻译所有结果
   */
  async function translateAll(): Promise<void> {
    if (blast.results.length === 0) return
    if (isTranslating.value) return
    
    isTranslating.value = true
    appStore.showNotification(`开始翻译 ${blast.results.length} 条结果...`, 'info')
    
    const bridge = getBridge()
    const wordsToTranslate = new Set<string>()
    
    blast.results.forEach(hit => {
      if (!hit.translatedName) {
        if (hit.consensusList && hit.consensusList.length > 0) {
          hit.consensusList.forEach((c: any) => {
            if (c.name) wordsToTranslate.add(c.name)
          })
        } else if (hit.speciesName) {
          wordsToTranslate.add(hit.speciesName as string)
        }
      }
    })
      
    if (wordsToTranslate.size === 0) {
      isTranslating.value = false
      appStore.showNotification('未发现需要翻译的新条目', 'info')
      return
    }

    try {
      bridge.translate_batch(JSON.stringify(Array.from(wordsToTranslate)), 'species')
    } catch (e) {
      console.error('[ResultHandler] Batch translation error:', e)
    }

    // 重置状态
    setTimeout(() => { isTranslating.value = false }, 2000)
  }

  return {
    isTranslating,
    fetchTaskResults,
    exportResults,
    translateAll
  }
}
