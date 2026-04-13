/**
 * BLAST 分析状态管理 (Pinia Store)
 */
import { ref, computed, shallowRef } from 'vue'
import { defineStore } from 'pinia'
import { getBridge } from '../bridge'

/** BLAST 参数 */
export interface BlastParams {
    program: string
    database: string
    evalue: number
    maxHits: number
    matrix: string
    gapOpen: number
    gapExtend: number
    threads: number
    filterLowComplexity: boolean
}

/** BLAST 任务 */
export interface BlastTask {
    taskId: string
    fileName: string
    status: string
    progress: number
    startTime: string
    endTime?: string
}

/** BLAST 结果行 */
export interface BlastHit {
    queryTitle: string
    hitTitle: string
    /** 共识投票识别的物种名 */
    speciesName: string
    /** 种属 · 菌株 */
    genusStrain: string
    /** 基因来源，如 16S ribosomal RNA gene */
    geneSource: string
    /** 序列类型 */
    seqType: string
    /** 宿主信息 */
    host: string
    /** 比对长度 */
    alignLen: string
    identity: number
    evalue: string
    accession: string
    translatedName?: string | null
    /** 是否强制显示原文（即使已有译文） */
    showOriginal?: boolean
    /** 是否正在翻译中（用于 UI 加载动画） */
    isTranslating?: boolean
    consensusList?: {name: string, pct: number}[]
    /** 查看详情所用的结果 CSV 路径 */
    csvFile?: string
    /** 可视化所用的 XML 路径 */
    xmlFile?: string
    /** 原始序列内容 */
    rawSequence?: string
    /** 序列状态: pending, success, no_hits */
    status?: string
}

export const useBlastStore = defineStore('blast', () => {
    /* -------- 输入 -------- */
    const inputMode = ref<'file' | 'text'>('file')
    const files = ref<string[]>([])
    const queryText = ref('')

    /* -------- 参数 -------- */
    const params = ref<BlastParams>({
        program: 'auto',
        database: 'nt',
        evalue: 0.05,
        maxHits: 50,
        matrix: 'BLOSUM62',
        gapOpen: 11,
        gapExtend: 1,
        threads: 4,
        filterLowComplexity: true
    })

    /* -------- 任务 -------- */
    const tasks = ref<BlastTask[]>([])
    const activeTaskId = ref<string | null>(null)

    /* -------- 结果 -------- */
    const results = ref<BlastHit[]>([]) // 使用标准 ref 以支持行内状态（翻译切换/加载动画）
    const resultTitle = ref('分析结果')

    /* -------- 历史面板可见 -------- */
    const historyVisible = ref(false)

    /* -------- 计算属性 -------- */
    const fileCount = computed(() => files.value.length)
    const hasInput = computed(() => {
        return inputMode.value === 'file'
            ? files.value.length > 0
            : queryText.value.trim().length > 0
    })

    /* -------- 操作 -------- */
    function switchInputMode(mode: 'file' | 'text'): void {
        inputMode.value = mode
    }

    function sortFiles(): void {
        files.value.sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' }))
    }

    function addFile(filePath: string): void {
        if (!files.value.includes(filePath)) {
            files.value.push(filePath)
            sortFiles()
        }
    }

    function addFiles(filePaths: string[]): void {
        let changed = false
        filePaths.forEach(path => {
            if (!files.value.includes(path)) {
                files.value.push(path)
                changed = true
            }
        })
        if (changed) sortFiles()
    }

    function removeFile(filePath: string): void {
        files.value = files.value.filter(fileItem => fileItem !== filePath)
    }

    function clearFiles(): void {
        files.value = []
    }

    function toggleHistory(): void {
        historyVisible.value = !historyVisible.value
    }

    function addTask(task: BlastTask): void {
        tasks.value.unshift(task)
        activeTaskId.value = task.taskId
        results.value = [] // 切换到新任务时清空旧结果，为流式更新腾位
    }

    function updateTaskStatus(taskId: string, status: BlastTask['status'], progress?: number): void {
        const task = tasks.value.find(taskItem => taskItem.taskId === taskId)
        if (task) {
            task.status = status
            if (progress !== undefined) task.progress = progress
            if (status === 'done' || status === 'error') {
                task.endTime = new Date().toISOString()
            }
        }
    }

    function setResults(hits: BlastHit[], title?: string): void {
        results.value = hits
        if (title) resultTitle.value = title
    }

    function clearHistory(): void {
        tasks.value = []
        activeTaskId.value = null
    }

    function setActiveTask(taskId: string): void {
        if (activeTaskId.value !== taskId) {
            activeTaskId.value = taskId
            results.value = [] // Clear results while loading
            resultTitle.value = '分析结果 (加载中...)'
        }
    }

    function removeTask(taskId: string): void {
        tasks.value = tasks.value.filter(t => t.taskId !== taskId)
        if (activeTaskId.value === taskId) {
            activeTaskId.value = null
            results.value = []
            resultTitle.value = '分析结果'
        }
    }

    function updateTranslation(original: string, translated: string): void {
        // 创建新数组以触发 shallowRef 响应式
        results.value = results.value.map(hit => {
            let updatedHit = { ...hit }
            let changed = false

            // Check structured list first
            if (hit.consensusList && hit.consensusList.length > 0) {
                const targetObj = hit.consensusList.find(c => c.name === original)
                if (targetObj) {
                    if (!updatedHit.translatedName) updatedHit.translatedName = hit.speciesName
                    updatedHit.translatedName = updatedHit.translatedName.replace(original, translated)
                    updatedHit.showOriginal = false 
                    changed = true
                }
            } else if (hit.speciesName && hit.speciesName.includes(original)) {
                if (!updatedHit.translatedName) updatedHit.translatedName = hit.speciesName
                
                const alreadySplicedPattern = `${translated} (${original})`
                if (updatedHit.translatedName.includes(alreadySplicedPattern)) {
                    return hit // No change needed
                }

                const targetPattern = original + " (AI翻译中...)"
                if (updatedHit.translatedName.includes(targetPattern)) {
                    updatedHit.translatedName = updatedHit.translatedName.replace(targetPattern, translated)
                } else {
                    updatedHit.translatedName = updatedHit.translatedName.replace(original, translated)
                }
                updatedHit.showOriginal = false 
                changed = true
            }
            
            return changed ? updatedHit : hit
        })
    }

    function appendSingleResult(resultObj: any): void {
        const taskId = resultObj.task_id
        if (activeTaskId.value !== taskId) return // Only update currently viewed task

        const resData = resultObj.result
        if (!resData) return
        
        const queryId = resData.sequence_id || '未知序列'
        const existingIdx = results.value.findIndex(h => h.queryTitle === queryId)
        
        if (resData.status === 'pending' || resData.status === 'running') {
            if (existingIdx === -1) {
                results.value = [...results.value, {
                    queryTitle: queryId,
                    hitTitle: '',
                    speciesName: '等待比对...',
                    genusStrain: '',
                    geneSource: '',
                    seqType: '',
                    host: '',
                    alignLen: '',
                    identity: 0,
                    evalue: '-',
                    accession: '-',
                    translatedName: null
                }]
                resultTitle.value = `分析结果 (共 ${results.value.length} 项)`
            }
            return
        }
        
        let updatedHit = null
        if (resData.data && Array.isArray(resData.data) && resData.data.length > 0) {
            const bestHit = resData.data[0]
            updatedHit = {
                queryTitle: queryId,
                hitTitle: bestHit.title || '',
                speciesName: bestHit.species || 'Unknown',
                genusStrain: [bestHit.genus, bestHit.strain].filter(Boolean).join(' · ') || '',
                geneSource: bestHit.gene_source || bestHit.gene_type || '',
                seqType: bestHit.seq_type || '',
                host: bestHit.host || '',
                alignLen: bestHit.align_len || '',
                identity: parseFloat(bestHit.similarity) || 0,
                evalue: String(bestHit.evalue || 'N/A'),
                accession: bestHit.acc || 'N/A',
                translatedName: null,
                consensusList: bestHit.consensusList || [],
                csvFile: resData.csv_file || '',
                xmlFile: resData.xml_file || '',
                rawSequence: resData.raw_sequence || ''
            }
        } else {
             // Finished but no hits
             updatedHit = {
                queryTitle: queryId,
                hitTitle: '',
                speciesName: '未找到匹配项 (No Hits)',
                genusStrain: '',
                geneSource: '',
                seqType: '',
                host: '',
                alignLen: '',
                identity: 0,
                evalue: '-',
                accession: '-',
                translatedName: null
             }
        }

        if (existingIdx !== -1) {
             results.value = results.value.map((h, i) => i === existingIdx ? updatedHit : h)
        } else {
             results.value = [...results.value, updatedHit]
        }
        resultTitle.value = `分析结果 (共 ${results.value.length} 项)`
    }

    // 自动化同步已禁用

    return {
        inputMode, files, queryText,
        params,
        tasks, activeTaskId,
        results, resultTitle,
        historyVisible,
        fileCount, hasInput,
        switchInputMode, addFile, addFiles, removeFile, clearFiles,
        toggleHistory, addTask, updateTaskStatus,
        setResults, clearHistory, setActiveTask, appendSingleResult,
        updateTranslation,
        removeTask
    }
})
