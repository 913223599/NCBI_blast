/**
 * 桥接域模块：系统配置、菌毒种库、帮助与分类学、文件上传与基因组拼接
 */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { API_BASE, apiDelete, apiGet, apiPost, getClientId } from '../httpClient'
import { createLogger } from '../../utils/logger'

const log = createLogger('Bridge:SettingsStrain')

export const settingsAndStrainDomain = {
  async get_ui_translations(callback?: (res: string) => void, lang?: string) {
    const query = lang ? `?lang=${encodeURIComponent(lang)}` : ''
    const result = await apiGet(`/api/settings/ui_translations${query}`)
    callback?.(JSON.stringify(result))
  },

  async get_ui_language(callback?: (res: string) => void) {
    const result = await apiGet('/api/settings/ui_language')
    callback?.(result.language || 'zh_CN')
  },

  async save_ui_language(langCode: string) {
    await apiPost('/api/settings/ui_language', { lang_code: langCode })
  },

  async get_api_key(service: string, callback?: (res: string) => void) {
    const result = await apiGet(`/api/settings/api_key/${service}`)
    callback?.(result.key || '')
  },

  async save_api_key(service: string, key: string) {
    await apiPost(`/api/settings/api_key/${service}`, { key })
  },

  async get_lan_share_info() {
    return await apiGet('/api/settings/lan_info')
  },

  async save_lan_share_settings(enabled: boolean) {
    return await apiPost('/api/settings/lan_share', { enabled })
  },

  async save_selected_model(modelKey: string, callback?: (res: boolean) => void) {
    const result = await apiPost('/api/settings/ai_model', { model_key: modelKey })
    callback?.(result.success)
  },

  async get_selected_model(callback?: (res: string) => void) {
    const result = await apiGet('/api/settings/ai_model')
    callback?.(result.model || '')
  },

  async get_ai_models(callback?: (res: string) => void) {
    const result = await apiGet('/api/settings/ai_models')
    callback?.(JSON.stringify(result))
  },

  async add_ai_model(key: string, name: string, callback?: (success: boolean) => void) {
    const result = await apiPost('/api/settings/ai_models', { key, name })
    callback?.(result.success)
  },

  async delete_ai_model(key: string, callback?: (success: boolean) => void) {
    const result = await apiDelete(`/api/settings/ai_models/${encodeURIComponent(key)}`)
    callback?.(result.success)
  },

  async db_save_freezer(freezer: any, callback?: (res: boolean) => void) {
    const result = await apiPost('/api/strain/freezer', { data: freezer })
    callback?.(result.success)
  },

  async db_delete_freezer(freezerId: string, callback?: (res: boolean) => void) {
    const result = await apiDelete(`/api/strain/freezer/${freezerId}`)
    callback?.(result.success)
  },

  async db_save_record(record: any, callback?: (res: boolean) => void) {
    const result = await apiPost('/api/strain/record', { data: record })
    callback?.(result.success)
  },

  async db_save_records_batch(records: any[], callback?: (res: boolean) => void) {
    const result = await apiPost('/api/strain/records/batch', { data: records })
    callback?.(result.success)
  },

  async db_delete_record(recordId: string, callback?: (res: boolean) => void) {
    const result = await apiDelete(`/api/strain/record/${recordId}`)
    callback?.(result.success)
  },

  async db_delete_records_batch(recordIds: string[], callback?: (res: boolean) => void) {
    const result = await apiPost('/api/strain/records/delete_batch', { ids: recordIds })
    callback?.(result.success)
  },

  async db_load_all(callback?: (res: any) => void) {
    const result = await apiGet('/api/strain/load')
    callback?.(result)
  },

  async db_clear_all(callback?: (res: boolean) => void) {
    const result = await apiPost('/api/strain/clear')
    callback?.(result.success)
  },

  async db_save_code_lookup(data: any, callback?: (res: boolean) => void) {
    const result = await apiPost('/api/strain/sys_config/codeLookup', data)
    callback?.(result.success)
  },

  async db_load_code_lookup(callback?: (res: any) => void) {
    const result = await apiGet('/api/strain/load')
    callback?.(result?.codeLookup || null)
  },

  async taxonomy_audit_batch(texts: string[], callback?: (res: any) => void) {
    const result = await apiPost('/api/taxonomy/audit', { texts })
    callback?.(result)
  },

  async db_save_sequence(seqJson: string, callback?: (res: boolean) => void) {
    const data = JSON.parse(seqJson)
    const result = await apiPost('/api/strain/sequence', data)
    callback?.(result.success)
  },

  async db_load_sequences_by_sample(sampleId: string, callback?: (res: string) => void) {
    const result = await apiGet(`/api/strain/sequences/${encodeURIComponent(sampleId)}`)
    callback?.(JSON.stringify(result))
  },

  async db_search_sequences(keyword: string, callback?: (res: string) => void) {
    const result = await apiGet(`/api/strain/sequences/search?keyword=${encodeURIComponent(keyword)}`)
    callback?.(JSON.stringify(result))
  },

  async db_delete_sequence(seqId: string, callback?: (res: boolean) => void) {
    const result = await apiDelete(`/api/strain/sequence/${encodeURIComponent(seqId)}`)
    callback?.(result.success)
  },

  async get_help_structure() {
    const result = await apiGet('/api/help/structure')
    if (window.handleBridgeEvent) {
      window.handleBridgeEvent('help_structure', result)
    }
    return result
  },

  async get_help_content(topicId: string) {
    const result = await apiGet(`/api/help/content/${encodeURIComponent(topicId)}`)
    if (window.handleBridgeEvent) {
      window.handleBridgeEvent('help_content', result)
    }
    return result
  },

  async sync_taxonomy(speciesName: string, callback?: (res: any) => void) {
    const result = await apiPost('/api/taxonomy/sync', { species_name: speciesName })
    callback?.(result)
  },

  async taxonomy_status(callback?: (res: any) => void) {
    const result = await apiGet('/api/taxonomy/status')
    callback?.(result)
    return result
  },

  async taxonomy_update(callback?: (res: any) => void) {
    const result = await apiPost('/api/taxonomy/update', {})
    callback?.(result)
    return result
  },

  async taxonomy_check(callback?: (res: any) => void) {
    const result = await apiGet('/api/taxonomy/check')
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
    const hashes = JSON.parse(hashesJson)
    const result = await apiPost('/api/translate/hashes', { hashes })
    return JSON.stringify(result)
  },

  async import_sequences_to_strains(paths: string[]) {
    return await apiPost('/api/strains/import_paths', { paths })
  },

  async get_taxonomy_lineage(query: string) {
    return await apiGet(`/api/taxonomy/lineage?query=${encodeURIComponent(query)}`)
  },

  async search_strains_by_category(category: string) {
    return await apiGet(`/api/strain/search/category?category=${category}`)
  },

  get_path_for_file(file: File): string {
    return window.electronAPI?.getPathForFile(file) || ''
  },

  async upload_file(file: File): Promise<any> {
    try {
      const formData = new FormData()
      formData.append('file', file)
      const response = await fetch(`${API_BASE}/api/common/upload`, {
        method: 'POST',
        body: formData,
      })
      return await response.json()
    } catch (err) {
      log.error('文件上传失败:', err)
      return { success: false, error: String(err) }
    }
  },

  async run_assembly_job(params: any): Promise<any> {
    return await apiPost('/api/assembly/run', {
      ...params,
      client_id: getClientId(),
    })
  },

  async start_assembly_pipeline(params: any): Promise<any> {
    return await this.run_assembly_job(params)
  },

  async get_all_db_status(callback?: (res: any) => void) {
    const result = await apiGet('/api/database/status')
    callback?.(result)
    return result
  },

  async trigger_db_update(dbId: string, callback?: (res: any) => void) {
    const result = await apiPost(`/api/database/update/${dbId}`)
    callback?.(result)
    return result
  },

  async get_blast_databases() {
    return await apiGet('/api/blast/databases')
  },

  async setup_assembly_env() {
    return await apiPost('/api/assembly/setup_conda')
  },

  async get_assembly_history() {
    return await apiGet('/api/assembly/history')
  },

  async fetchAssemblyHistory() {
    return await apiGet('/api/assembly/history')
  },

  async delete_assembly_task(taskId: string) {
    return await apiDelete(`/api/assembly/tasks/${taskId}`)
  },

  async get_assembly_report(taskId: string) {
    return await apiGet(`/api/assembly/report/${taskId}`)
  },

  async export_assembly_report(taskId: string) {
    return await apiGet(`/api/assembly/report/${taskId}/export`)
  },

  async stop_assembly_task(taskId: string) {
    return await apiPost(`/api/assembly/${taskId}/stop`)
  },

  async get_assembly_queue() {
    return await apiGet('/api/assembly/queue')
  },

  async reorder_assembly_queue(taskIds: string[]) {
    return await apiPost('/api/assembly/queue/reorder', { task_ids: taskIds })
  },

  async submit_assembly_batch(params: any): Promise<any> {
    return await apiPost('/api/assembly/batch', params)
  },
}
