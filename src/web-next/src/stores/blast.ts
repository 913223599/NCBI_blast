/**
 * BLAST 分析状态管理 (Pinia Store)
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

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
    status: 'queued' | 'running' | 'done' | 'error' | 'paused'
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
    const results = ref<BlastHit[]>([])
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

    function addFile(filePath: string): void {
        if (!files.value.includes(filePath)) {
            files.value.push(filePath)
        }
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
        results.value.forEach(hit => {
            if (hit.speciesName.includes(original)) {
                if (!hit.translatedName) hit.translatedName = hit.speciesName
                // 替换原文或之前的 (AI翻译中...) 占位符
                const targetPattern = original + " (AI翻译中...)"
                if (hit.translatedName.includes(targetPattern)) {
                    hit.translatedName = hit.translatedName.replace(targetPattern, translated)
                } else {
                    hit.translatedName = hit.translatedName.replace(original, translated)
                }
            }
        })
    }

    function appendSingleResult(resultObj: any): void {
        const taskId = resultObj.task_id
        if (activeTaskId.value !== taskId) return // Only update currently viewed task

        const resData = resultObj.result
        if (!resData) return
        
        const queryId = resData.sequence_id || '未知序列'
        if (resData.data && Array.isArray(resData.data) && resData.data.length > 0) {
            const bestHit = resData.data[0]
            // Prevent duplicates
            const exists = results.value.some(h => h.queryTitle === queryId)
            if (!exists) {
                results.value.push({
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
                    translatedName: null
                })
                resultTitle.value = `分析结果 (已加载 ${results.value.length} 项)`
            }
        }
    }

    return {
        inputMode, files, queryText,
        params,
        tasks, activeTaskId,
        results, resultTitle,
        historyVisible,
        fileCount, hasInput,
        switchInputMode, addFile, removeFile, clearFiles,
        toggleHistory, addTask, updateTaskStatus,
        setResults, clearHistory, setActiveTask, appendSingleResult,
        updateTranslation,
        removeTask
    }
})
