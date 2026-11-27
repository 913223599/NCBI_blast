/**
 * 桥接域模块：系统配置、菌毒种库、帮助与分类学、文件上传与基因组拼接
 */
import { API_BASE, apiDelete, apiGet, apiPost, getClientId } from '../httpClient'
import { createLogger } from '../../utils/logger'

const log = createLogger('Bridge:SettingsStrain')

export interface UploadFileResponse {
  success?: boolean
  path?: string
  paths?: string[]
  file_path?: string
  error?: string
  [key: string]: unknown
}

export interface LanShareInfoResponse {
  enabled?: boolean
  [key: string]: unknown
}

export interface DbStatusResponse {
  success?: boolean
  data?: unknown[]
  error?: string
  [key: string]: unknown
}

export interface DbUpdateState {
  db_id?: string
  status?: string
  progress?: number
  message?: string
  updated_at?: number
}

export interface DbUpdateResponse {
  success?: boolean
  already_running?: boolean
  state?: DbUpdateState
  message?: string
  error?: string
  [key: string]: unknown
}

export const settingsAndStrainDomain = {
  async get_ui_translations(callback?: (res: string) => void, lang?: string) {
    const query = lang ? `?lang=${encodeURIComponent(lang)}` : ''
    const result = await apiGet<Record<string, unknown>>(`/api/settings/ui_translations${query}`)
    callback?.(JSON.stringify(result))
  },

  async get_ui_language(callback?: (res: string) => void) {
    const result = await apiGet<{ language?: string }>('/api/settings/ui_language')
    callback?.(result.language || 'zh_CN')
  },

  async save_ui_language(langCode: string) {
    await apiPost('/api/settings/ui_language', { lang_code: langCode })
  },

  async get_api_key(service: string, callback?: (res: string) => void) {
    const result = await apiGet<{ key?: string }>(`/api/settings/api_key/${service}`)
    callback?.(result.key || '')
  },

  async save_api_key(service: string, key: string) {
    await apiPost(`/api/settings/api_key/${service}`, { key })
  },

  async get_lan_share_info() {
    return await apiGet<LanShareInfoResponse>('/api/settings/lan_info')
  },

  async save_lan_share_settings(enabled: boolean) {
    return await apiPost<Record<string, unknown>>('/api/settings/lan_share', { enabled })
  },

  async save_selected_model(modelKey: string, callback?: (res: boolean) => void) {
    const result = await apiPost<{ success: boolean }>('/api/settings/ai_model', { model_key: modelKey })
    callback?.(result.success)
  },

  async get_selected_model(callback?: (res: string) => void) {
    const result = await apiGet<{ model?: string }>('/api/settings/ai_model')
    callback?.(result.model || '')
  },

  async get_ai_models(callback?: (res: string) => void) {
    const result = await apiGet<unknown>('/api/settings/ai_models')
    callback?.(JSON.stringify(result))
  },

  async add_ai_model(key: string, name: string, callback?: (success: boolean) => void) {
    const result = await apiPost<{ success: boolean }>('/api/settings/ai_models', { key, name })
    callback?.(result.success)
  },

  async delete_ai_model(key: string, callback?: (success: boolean) => void) {
    const result = await apiDelete<{ success: boolean }>(`/api/settings/ai_models/${encodeURIComponent(key)}`)
    callback?.(result.success)
  },

  async db_save_freezer(freezer: unknown, callback?: (res: boolean) => void) {
    const result = await apiPost<{ success: boolean }>('/api/strain/freezer', { data: freezer })
    callback?.(result.success)
  },

  async db_delete_freezer(freezerId: string, callback?: (res: boolean) => void) {
    const result = await apiDelete<{ success: boolean }>(`/api/strain/freezer/${freezerId}`)
    callback?.(result.success)
  },

  async db_save_record(record: unknown, callback?: (res: boolean) => void) {
    const result = await apiPost<{ success: boolean }>('/api/strain/record', { data: record })
    callback?.(result.success)
  },

  async db_save_records_batch(records: unknown[], callback?: (res: boolean) => void) {
    const result = await apiPost<{ success: boolean }>('/api/strain/records/batch', { data: records })
    callback?.(result.success)
  },

  async db_delete_record(recordId: string, callback?: (res: boolean) => void) {
    const result = await apiDelete<{ success: boolean }>(`/api/strain/record/${recordId}`)
    callback?.(result.success)
  },

  async db_delete_records_batch(recordIds: string[], callback?: (res: boolean) => void) {
    const result = await apiPost<{ success: boolean }>('/api/strain/records/delete_batch', { ids: recordIds })
    callback?.(result.success)
  },

  async db_load_all<T = Record<string, unknown>>(callback?: (res: T) => void) {
    const result = await apiGet<T>('/api/strain/load')
    callback?.(result)
  },

  async db_clear_all(callback?: (res: boolean) => void) {
    const result = await apiPost<{ success: boolean }>('/api/strain/clear')
    callback?.(result.success)
  },

  async db_save_code_lookup(data: unknown, callback?: (res: boolean) => void) {
    const result = await apiPost<{ success: boolean }>('/api/strain/sys_config/codeLookup', data)
    callback?.(result.success)
  },

  async db_load_code_lookup<T = Record<string, unknown> | null>(callback?: (res: T) => void) {
    const result = await apiGet<{ codeLookup?: T }>('/api/strain/load')
    callback?.((result?.codeLookup ?? null) as T)
  },

  async taxonomy_audit_batch<T = Record<string, unknown>>(texts: string[], callback?: (res: T) => void) {
    const result = await apiPost<T>('/api/taxonomy/audit', { texts })
    callback?.(result)
  },

  async db_save_sequence(seqJson: string, callback?: (res: boolean) => void) {
    const data: unknown = JSON.parse(seqJson)
    const result = await apiPost<{ success: boolean }>('/api/strain/sequence', data)
    callback?.(result.success)
  },

  async db_load_sequences_by_sample(sampleId: string, callback?: (res: string) => void) {
    const result = await apiGet<unknown>(`/api/strain/sequences/${encodeURIComponent(sampleId)}`)
    callback?.(JSON.stringify(result))
  },

  async db_search_sequences(keyword: string, callback?: (res: string) => void) {
    const result = await apiGet<unknown>(`/api/strain/sequences/search?keyword=${encodeURIComponent(keyword)}`)
    callback?.(JSON.stringify(result))
  },

  async db_delete_sequence(seqId: string, callback?: (res: boolean) => void) {
    const result = await apiDelete<{ success: boolean }>(`/api/strain/sequence/${encodeURIComponent(seqId)}`)
    callback?.(result.success)
  },

  async get_help_structure() {
    const result = await apiGet<Record<string, unknown>>('/api/help/structure')
    if (window.handleBridgeEvent) {
      window.handleBridgeEvent('help_structure', result)
    }
    return result
  },

  async get_help_content(topicId: string) {
    const result = await apiGet<Record<string, unknown>>(`/api/help/content/${encodeURIComponent(topicId)}`)
    if (window.handleBridgeEvent) {
      window.handleBridgeEvent('help_content', result)
    }
    return result
  },

  async sync_taxonomy<T = Record<string, unknown>>(speciesName: string, callback?: (res: T) => void) {
    const result = await apiPost<T>('/api/taxonomy/sync', { species_name: speciesName })
    callback?.(result)
  },

  async taxonomy_status<T = Record<string, unknown>>(callback?: (res: T) => void) {
    const result = await apiGet<T>('/api/taxonomy/status')
    callback?.(result)
    return result
  },

  async taxonomy_update<T = Record<string, unknown>>(callback?: (res: T) => void) {
    const result = await apiPost<T>('/api/taxonomy/update', {})
    callback?.(result)
    return result
  },

  async taxonomy_cancel<T = DbUpdateResponse>(callback?: (res: T) => void) {
    const result = await apiPost<T>('/api/taxonomy/cancel', {})
    callback?.(result)
    return result
  },

  async taxonomy_check<T = Record<string, unknown>>(callback?: (res: T) => void) {
    const result = await apiGet<T>('/api/taxonomy/check')
    callback?.(result)
    return result
  },

  on_page_ready() {
    log.debug('Page ready')
  },

  log_message(message: string) {
    log.debug(message)
  },

  on_js_error(message: string) {
    log.error(message)
  },

  async get_annotations_by_hashes(hashesJson: string) {
    const hashes: unknown = JSON.parse(hashesJson)
    const result = await apiPost<unknown>('/api/translate/hashes', { hashes })
    return JSON.stringify(result)
  },

  async import_sequences_to_strains(paths: string[]) {
    return await apiPost<Record<string, unknown>>('/api/strains/import_paths', { paths })
  },

  async get_taxonomy_lineage(query: string) {
    return await apiGet<Record<string, unknown>>(`/api/taxonomy/lineage?query=${encodeURIComponent(query)}`)
  },

  async search_strains_by_category(category: string) {
    return await apiGet<Record<string, unknown>>(`/api/strain/search/category?category=${category}`)
  },

  get_path_for_file(file: File): string {
    return window.electronAPI?.getPathForFile(file) || ''
  },

  async upload_file(file: File): Promise<UploadFileResponse> {
    try {
      const formData = new FormData()
      formData.append('file', file)
      const response = await fetch(`${API_BASE}/api/common/upload`, {
        method: 'POST',
        body: formData,
      })
      return (await response.json()) as UploadFileResponse
    } catch (err) {
      log.error('文件上传失败:', err)
      return { success: false, error: String(err) }
    }
  },

  async run_assembly_job<T = Record<string, unknown>>(params: Record<string, unknown>): Promise<T> {
    return await apiPost<T>('/api/assembly/run', {
      ...params,
      client_id: getClientId(),
    })
  },

  async start_assembly_pipeline<T = Record<string, unknown>>(params: Record<string, unknown>): Promise<T> {
    return await this.run_assembly_job<T>(params)
  },

  async get_all_db_status<T = DbStatusResponse>(callback?: (res: T) => void) {
    const result = await apiGet<T>('/api/database/status')
    callback?.(result)
    return result
  },

  async trigger_db_update<T = DbUpdateResponse>(dbId: string, callback?: (res: T) => void) {
    const result = await apiPost<T>(`/api/database/update/${dbId}`)
    callback?.(result)
    return result
  },

  async cancel_db_update<T = DbUpdateResponse>(dbId: string, callback?: (res: T) => void) {
    const result = await apiPost<T>(`/api/database/cancel/${dbId}`)
    callback?.(result)
    return result
  },

  async get_blast_databases() {
    return await apiGet<Record<string, unknown>>('/api/blast/databases')
  },

  async setup_assembly_env() {
    return await apiPost<Record<string, unknown>>('/api/assembly/setup_conda')
  },

  async get_assembly_history<T = Record<string, unknown>>() {
    return await apiGet<T>('/api/assembly/history')
  },

  async fetchAssemblyHistory<T = Record<string, unknown>>() {
    return await apiGet<T>('/api/assembly/history')
  },

  async delete_assembly_task(taskId: string) {
    return await apiDelete<Record<string, unknown>>(`/api/assembly/tasks/${taskId}`)
  },

  async get_assembly_report(taskId: string) {
    return await apiGet<Record<string, unknown>>(`/api/assembly/report/${taskId}`)
  },

  async export_assembly_report(taskId: string) {
    return await apiGet<Record<string, unknown>>(`/api/assembly/report/${taskId}/export`)
  },

  async stop_assembly_task(taskId: string) {
    return await apiPost<Record<string, unknown>>(`/api/assembly/${taskId}/stop`)
  },

  async get_assembly_queue() {
    return await apiGet<Record<string, unknown>>('/api/assembly/queue')
  },

  async reorder_assembly_queue(taskIds: string[]) {
    return await apiPost<Record<string, unknown>>('/api/assembly/queue/reorder', { task_ids: taskIds })
  },

  async submit_assembly_batch<T = Record<string, unknown>>(params: Record<string, unknown>): Promise<T> {
    return await apiPost<T>('/api/assembly/batch', params)
  },
}
