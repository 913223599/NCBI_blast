/**
 * 桥接域模块：本地文件 IPC、BLAST 任务调度、本地数据库、翻译与词典管理
 */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { apiDelete, apiGet, apiPost } from '../httpClient'
import { createLogger } from '../../utils/logger'

const log = createLogger('Bridge:FilesBlast')

export const filesAndBlastDomain = {
  async request_file_load(fileType: string | string[], multiple: boolean = false): Promise<string[] | null> {
    const electron = window.electronAPI
    if (!electron) {
      log.warn('当前处于非 Electron 环境，无法调用原生文件对话框。')
      ;(window as any).app?.showNotification('局域网模式暂不支持直接读取本地文件，请使用上传逻辑', 'warning')
      return null
    }

    let dialogTitle = '批量导入: 文件'
    let filters: Array<{ name: string; extensions: string[] }> = []

    if (fileType === 'tree') {
      dialogTitle = '批量导入: 进化树数据 (序列/树文件)'
      filters = [
        { name: 'Tree Files', extensions: ['nwk', 'newick', 'tree', 'txt'] },
        { name: 'Sequence Files', extensions: ['fasta', 'fas', 'fa', 'fna', 'seq', 'txt'] },
        { name: 'Archives', extensions: ['zip', 'gz'] },
      ]
    } else if (fileType === 'annotation' || fileType === 'gbk' || fileType === 'phage') {
      dialogTitle = multiple
        ? '批量选择导入: 基因组序列与注释文件 (FASTA/GBK/FAA)'
        : '选择导入: 基因组序列与注释文件 (FASTA/GBK)'
      filters = [
        {
          name: '注释与序列文件',
          extensions: ['gbk', 'gb', 'gbff', 'genbank', 'faa', 'fasta', 'fa', 'fna', 'gff', 'gff3', 'gz', 'json'],
        },
        { name: 'GenBank 文件 (*.gbk, *.gb, *.gbff, *.genbank)', extensions: ['gbk', 'gb', 'gbff', 'genbank'] },
        { name: 'FASTA 序列 (*.fasta, *.faa, *.fa, *.fna)', extensions: ['fasta', 'faa', 'fa', 'fna'] },
        { name: 'GFF 注释 (*.gff, *.gff3)', extensions: ['gff', 'gff3'] },
        { name: '压缩序列 (*.gz)', extensions: ['gz'] },
        { name: 'JSON 特征 (*.json)', extensions: ['json'] },
      ]
    } else if (fileType === 'fasta') {
      dialogTitle = '批量导入: 序列文件 (FASTA)'
      filters = [
        { name: 'FASTA 序列', extensions: ['fasta', 'fas', 'fa', 'fna', 'seq', 'txt'] },
        { name: 'Sanger 测序', extensions: ['ab1', 'abi'] },
      ]
    } else if (Array.isArray(fileType)) {
      const isAnnoOrProt = fileType.some((ext) =>
        ['gbk', 'gb', 'genbank', 'faa', 'gff', 'gff3'].includes(ext.toLowerCase())
      )
      const isReads = fileType.some((ext) => ['fastq', 'fq', 'ab1'].includes(ext.toLowerCase()))

      if (isAnnoOrProt) {
        dialogTitle = '选择导入: 注释与蛋白质序列文件 (GBK/FASTA)'
        filters = [
          { name: '注释与序列文件', extensions: fileType },
          { name: 'GenBank 文件 (*.gbk, *.gb)', extensions: ['gbk', 'gb', 'genbank'] },
          { name: 'FASTA 序列 (*.fasta, *.faa, *.fa)', extensions: ['fasta', 'faa', 'fa', 'fna'] },
        ]
      } else if (isReads) {
        dialogTitle = '批量导入: 测序原始数据 (FASTQ/AB1)'
        filters = [
          { name: 'Sequencing Reads', extensions: ['fastq', 'fq', 'gz', 'fastq.gz', 'fq.gz', 'ab1'] },
          { name: 'Archives', extensions: ['zip', 'tar.gz'] },
        ]
      } else {
        dialogTitle = '批量导入: 序列文件'
        filters = [{ name: 'Supported Files', extensions: fileType }]
      }
    } else {
      dialogTitle = '批量导入: 序列文件'
      filters = [
        {
          name: 'Sequence Files',
          extensions: ['fasta', 'fas', 'fa', 'seq', 'ab1', 'abi', 'fastq', 'fq', 'gz', 'gbk', 'gb'],
        },
      ]
    }

    filters.push({ name: 'All Files', extensions: ['*'] })

    const properties = ['openFile']
    if (multiple) properties.push('multiSelections')

    const paths = await electron.openFileDialog({
      title: dialogTitle,
      filters,
      properties,
    })

    if (!paths || paths.length === 0) return null
    return paths
  },

  async show_open_dialog(options?: { fileType?: string; multiple?: boolean }): Promise<{ filePaths: string[] } | null> {
    const fileType = options?.fileType || 'annotation'
    const multiple = options?.multiple ?? true
    const paths = await this.request_file_load(fileType, multiple)
    return paths ? { filePaths: paths } : null
  },

  async save_file(content: string, filenameHint: string, callback?: (success: boolean) => void) {
    const electron = window.electronAPI

    if (electron) {
      const path = await electron.saveFileDialog({ defaultPath: filenameHint })
      if (path) {
        const success = await electron.writeFile(path, content)
        callback?.(success ?? false)
        return
      }
      callback?.(false)
      return
    }

    try {
      log.debug('正在通过浏览器 Blob 模式导出文件...')
      const blob = new Blob([content], { type: 'text/csv;charset=utf-8;' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.setAttribute('href', url)
      link.setAttribute('download', filenameHint || 'export.csv')
      link.style.visibility = 'hidden'
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(url)
      callback?.(true)
    } catch (err) {
      log.error('浏览器导出失败:', err)
      callback?.(false)
    }
  },

  open_results_dir(dirPath: string) {
    window.electronAPI?.openPath(dirPath)
  },

  open_external_url(url: string) {
    window.electronAPI?.openExternal(url)
  },

  async process_blast_files(paths: string[]) {
    return await apiPost('/api/blast/process_files', { paths })
  },

  async run_blast_job(paramsJson: string, callback?: (res: string) => void) {
    const params = JSON.parse(paramsJson)
    const result = await apiPost('/api/blast/run', params)
    callback?.(JSON.stringify(result))
  },

  async stop_blast_job(taskId: string) {
    await apiPost(`/api/blast/stop/${taskId}`)
  },

  async pause_blast_job(taskId: string) {
    await apiPost(`/api/blast/pause/${taskId}`)
  },

  async resume_blast_job(taskId: string) {
    await apiPost(`/api/blast/resume/${taskId}`)
  },

  async get_task_status(taskId: string, callback?: (res: string) => void) {
    const result = await apiGet(`/api/blast/status/${taskId}`)
    callback?.(JSON.stringify(result))
  },

  async get_task_results(taskId: string, callback?: (res: string) => void) {
    const result = await apiGet(`/api/blast/results/${taskId}`)
    callback?.(JSON.stringify(result))
  },

  async get_all_tasks(callback?: (res: string) => void) {
    const result = await apiGet('/api/blast/tasks')
    callback?.(JSON.stringify(result))
  },

  async delete_single_task(taskId: string) {
    await apiDelete(`/api/blast/task/${taskId}`)
  },

  async resume_task(taskId: string) {
    await apiPost(`/api/blast/resume/${taskId}`)
  },

  async clear_all_history() {
    await apiPost('/api/blast/clear')
  },

  async rename_task(taskId: string, newName: string) {
    await apiPost(`/api/blast/rename/${taskId}`, { new_name: newName })
  },

  async get_detailed_blast_results(csvFile: string) {
    const result = await apiGet(`/api/blast/detailed/${encodeURIComponent(csvFile)}`)
    if (window.handleBridgeEvent) {
      window.handleBridgeEvent('detailed_results_ready', result)
    }
    return result
  },

  async list_local_databases(callback?: (res: string) => void) {
    const result = await apiGet('/api/blast/databases')
    callback?.(JSON.stringify(result))
  },

  async make_blast_db(
    inputFile: string,
    dbType: string,
    title: string,
    outName: string | null,
    callback?: (success: boolean, message: string) => void
  ) {
    const result = await apiPost('/api/blast/database/make', {
      input_file: inputFile,
      db_type: dbType,
      title,
      out_name: outName,
    })
    callback?.(result.success, result.message)
  },

  async delete_database(name: string, callback?: (success: boolean) => void) {
    const result = await apiDelete(`/api/blast/database/${encodeURIComponent(name)}`)
    callback?.(result.success)
  },

  async get_alignment_visualization_data(
    xmlPath: string,
    sortMode: string = 'evalue',
    queryIdOrCallback?: string | ((res: string) => void),
    callback?: (res: string) => void
  ) {
    let queryId: string | undefined = undefined
    let actualCallback = callback
    if (typeof queryIdOrCallback === 'function') {
      actualCallback = queryIdOrCallback
    } else if (typeof queryIdOrCallback === 'string') {
      queryId = queryIdOrCallback
    }

    const result = await apiPost('/api/blast/visualization/data', {
      xml_path: xmlPath,
      sort_mode: sortMode,
      query_id: queryId,
    })
    actualCallback?.(JSON.stringify(result))
  },

  async translate_text(text: string, category: string, callback?: (res: string) => void) {
    const result = await apiPost('/api/translate/single', { text, category })
    callback?.(result.translated || text)
  },

  async translate_batch(textsJson: string, category: string) {
    const texts = JSON.parse(textsJson)
    await apiPost('/api/translate/batch', { texts, category })
  },

  async search_dictionary(
    query: string,
    proofreadModeOrCallback?: boolean | ((res: string) => void),
    callback?: (res: string) => void
  ) {
    let proofreadMode = false
    let actualCallback = callback
    if (typeof proofreadModeOrCallback === 'boolean') {
      proofreadMode = proofreadModeOrCallback
    } else if (typeof proofreadModeOrCallback === 'function') {
      actualCallback = proofreadModeOrCallback
    }
    const result = await apiGet(`/api/dictionary/search?query=${encodeURIComponent(query)}&proofread_mode=${proofreadMode}`)
    actualCallback?.(JSON.stringify(result))
  },

  async save_dictionary_term(english: string, chinese: string, category: string, callback?: (res: boolean) => void) {
    const result = await apiPost('/api/dictionary/save', { english, chinese, category })
    callback?.(result.success)
  },

  async delete_dictionary_term(english: string, callback?: (res: boolean) => void) {
    const result = await apiDelete(`/api/dictionary/term?english=${encodeURIComponent(english)}`)
    callback?.(result.success)
  },

  async verify_dictionary_term(english: string, callback?: (res: boolean) => void) {
    const result = await apiPost(`/api/dictionary/verify?english=${encodeURIComponent(english)}`)
    callback?.(result.success)
  },

  async get_all_dictionary_terms(
    proofreadModeOrCallback?: boolean | ((res: string) => void),
    callback?: (res: string) => void
  ) {
    let proofreadMode = false
    let actualCallback = callback
    if (typeof proofreadModeOrCallback === 'boolean') {
      proofreadMode = proofreadModeOrCallback
    } else if (typeof proofreadModeOrCallback === 'function') {
      actualCallback = proofreadModeOrCallback
    }
    const result = await apiGet(`/api/dictionary/all?proofread_mode=${proofreadMode}`)
    actualCallback?.(JSON.stringify(result))
  },

  async get_dictionary_page(
    page: number,
    limit: number,
    query: string,
    category: string,
    proofreadMode: boolean,
    callback?: (res: string) => void
  ) {
    const url = `/api/dictionary/page?page=${page}&limit=${limit}&query=${encodeURIComponent(query)}&category=${category}&proofread_mode=${proofreadMode}`
    const result = await apiGet(url)
    callback?.(JSON.stringify(result))
  },

  async get_all_dictionary_terms_for_export(
    proofreadMode: boolean,
    category: string,
    query: string,
    callback?: (res: string) => void
  ) {
    const url = `/api/dictionary/all?proofread_mode=${proofreadMode}&category=${category}&query=${encodeURIComponent(query)}&limit=-1`
    const result = await apiGet(url)
    callback?.(JSON.stringify(result))
  },

  async get_dictionary_stats(callback?: (res: any) => void) {
    const result = await apiGet('/api/dictionary/stats')
    callback?.(result)
    return result
  },

  async request_batch_blast(seqIdsJson: string, sourceRelPath: string) {
    const seq_ids = JSON.parse(seqIdsJson)
    return await apiPost('/api/blast/batch_from_tree', { seq_ids, source_rel_path: sourceRelPath })
  },

  async read_result_file(filePath: string) {
    return await window.electronAPI?.readFile(filePath)
  },
}
