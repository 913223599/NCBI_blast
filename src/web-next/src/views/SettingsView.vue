<script setup lang="ts">
/**
 * SettingsView - 应用设置页面
 * 包含 AI翻译 / 系统参数 / 界面语言 / 词典管理
 * 使用自定义下拉组件解决 PyQt 环境下的布局重绘 Bug
 */
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { getBridge } from '../bridge'
import { useAppStore } from '../stores/app'

import { useVirtualList } from '@vueuse/core'

const appStore = useAppStore()

/* -------- 面板切换 -------- */
const panels = [
  { id: 'ai-translation', label: 'AI & 翻译', icon: '🤖' },
  { id: 'local-db', label: '本地数据库', icon: '💾' },
  { id: 'system-params', label: '系统参数', icon: '⚙️' },
  { id: 'user-interface', label: '界面显示', icon: '🖥️' },
  { id: 'dictionary', label: '词典管理', icon: '📖' }
]
const activePanel = ref('ai-translation')

/* -------- 统一状态存储 -------- */
const apiKey = ref('')
const selectedModel = ref('')
const aiModels = ref<Array<{ key: string; name: string }>>([])
const newModelKey = ref('')
const newModelName = ref('')
const saveStatus = ref<{ message: string; type: string } | null>(null)
const selectedLocale = ref('zh_CN')
const loadingDict = ref(false)

// 词典管理状态
const dictQuery = ref('')
const dictResults = ref<Array<{ english: string; chinese: string; category: string; source?: string }>>([])
const newTermEn = ref('')
const newTermZh = ref('')
const newTermCat = ref('species')

// 虚拟列表配置
const { list, containerProps, wrapperProps } = useVirtualList(
  dictResults,
  { itemHeight: 52 }
)

// 下拉菜单控制
const dropdownOpen = ref(false)
const selectRef = ref<HTMLElement | null>(null)
const dictDropdownOpen = ref(false)
const dictSelectRef = ref<HTMLElement | null>(null)
let searchTimer: any = null

const dictCategories = [
  { id: 'kingdom', label: '界 (Kingdom)' },
  { id: 'phylum', label: '门 (Phylum)' },
  { id: 'class_rank', label: '纲 (Class)' },
  { id: 'order', label: '目 (Order)' },
  { id: 'family', label: '科 (Family)' },
  { id: 'genus', label: '属 (Genus)' },
  { id: 'species', label: '物种 (Species)' },
  { id: 'gene', label: '基因 (Gene)' },
  { id: 'location', label: '地理/来源 (Location)' },
  { id: 'other', label: '其他 (Other)' }
]

/* -------- 工具函数 -------- */
function getCategoryLabel(id: string): string {
  return dictCategories.find(c => c.id === id)?.label || id
}

function selectModelOption(key: string) {
  selectedModel.value = key
  dropdownOpen.value = false
}

function selectDictCategory(id: string): void {
  newTermCat.value = id
  dictDropdownOpen.value = false
}

function handleClickOutside(event: MouseEvent) {
  const target = event.target as Node
  if (dropdownOpen.value && selectRef.value && !selectRef.value.contains(target)) {
    dropdownOpen.value = false
  }
  if (dictDropdownOpen.value && dictSelectRef.value && !dictSelectRef.value.contains(target)) {
    dictDropdownOpen.value = false
  }
}

function getSourceClass(source: string | undefined): string {
  if (!source) return 'manual';
  if (source.includes('ai')) return 'ai';
  if (source.includes('manual')) return 'manual';
  if (source.includes('verified')) return 'verified';
  return 'manual';
}

function getSourceLabel(source: string | undefined): string {
  if (!source) return '手动录入';
  if (source === 'ai_batch') return 'AI 批量智能提取';
  if (source === 'ai') return 'AI 智能提取';
  if (source === 'verified') return '已核对确信';
  if (source === 'manual_web' || source === 'manual') return '用户录入';
  if (source === 'migration') return '内置词库';
  return '系统预设';
}


/* -------- 生命周期 -------- */
onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  loadSettings()
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})

watch(activePanel, (newVal) => {
  if (newVal === 'dictionary' && dictResults.value.length === 0) {
    loadDictionary()
  }
  if (newVal === 'local-db') {
    loadLocalDatabases()
  }
})

/* -------- 数据库管理状态 -------- */
const localDatabases = ref<any[]>([])
const loadingDbs = ref(false)
const dbInputFile = ref('')
const dbTitle = ref('')
const dbOutName = ref('')
const dbType = ref('nucl')
const isCreatingDb = ref(false)

function loadLocalDatabases() {
  loadingDbs.value = true
  getBridge().list_local_databases((resStr: string) => {
    loadingDbs.value = false
    try {
      localDatabases.value = JSON.parse(resStr)
    } catch {
      localDatabases.value = []
    }
  })
}

function browseFasta() {
  getBridge().request_file_load('fasta')
  // 兼容旧版回调，或者直接拦截
  window.handleFileLoaded = (_content: string, type: string, path: string) => {
    if (type === 'fasta' && path) {
      dbInputFile.value = path
      // 自动提取默认名称
      const parts = path.split(/[/\\]/)
      const lastPart = parts[parts.length - 1] || ''
      const fileName = lastPart.split('.')[0] || 'new_database'
      
      if (!dbTitle.value) dbTitle.value = fileName
      if (!dbOutName.value) dbOutName.value = fileName.replace(/[^a-zA-Z0-9]/g, '_')
    }
  }
}

function createDatabase() {
  if (!dbInputFile.value || !dbTitle.value || !dbOutName.value) {
    appStore.showNotification('请填齐数据库创建信息', 'warning')
    return
  }
  isCreatingDb.value = true
  getBridge().make_blast_db(
    dbInputFile.value,
    dbType.value,
    dbTitle.value,
    dbOutName.value,
    (success: boolean, msg: string) => {
      isCreatingDb.value = false
      if (success) {
        appStore.showNotification(msg, 'success')
        loadLocalDatabases()
        dbInputFile.value = ''; dbTitle.value = ''; dbOutName.value = ''
      } else {
        appStore.showNotification(`创建失败: ${msg}`, 'error')
      }
    }
  )
}

function deleteDatabase(name: string) {
  if (!confirm(`确定删除数据库 "${name}"? 此操作不可恢复。`)) return
  getBridge().delete_database(name, (success: boolean) => {
    if (success) {
      appStore.showNotification('数据库已删除', 'info')
      loadLocalDatabases()
    } else {
      appStore.showNotification('删除失败，文件可能被占用', 'error')
    }
  })
}

/* -------- 业务逻辑 -------- */
async function loadSettings(): Promise<void> {
  try {
    const bridge = getBridge()
    bridge.get_api_key('dashscope', (key: string) => { if (key) apiKey.value = key })
    bridge.get_ai_models?.((modelsStr: string) => {
      try {
        const models = JSON.parse(modelsStr)
        if (Array.isArray(models)) {
          aiModels.value = models
          // 如果还没有选择模型，默认选择第一个
          if (aiModels.value.length > 0 && !selectedModel.value) {
            const firstModel = aiModels.value[0]
            if (firstModel) selectedModel.value = firstModel.key
          }
        }
      } catch (e) { console.error('[Settings] Parse models error:', e) }
    })
    
    // 获取已选择的模型（覆盖之前的默认值）
    bridge.get_selected_model?.((savedModel: string) => {
      if (savedModel && savedModel !== 'None') {
        selectedModel.value = savedModel
      }
    })
  } catch (error) { console.warn('[Settings] Bridge not ready') }
}

function addModel(): void {
  if (!newModelKey.value.trim() || !newModelName.value.trim()) {
    appStore.showNotification('请填写完整模型配置', 'warning')
    return
  }
  getBridge().add_ai_model?.(newModelKey.value.trim(), newModelName.value.trim(), (success: boolean) => {
    if (success) {
      aiModels.value.push({ key: newModelKey.value.trim(), name: newModelName.value.trim() })
      newModelKey.value = ''; newModelName.value = ''
      appStore.showNotification('模型加入成功', 'success')
    }
  })
}

function deleteModel(key: string): void {
  getBridge().delete_ai_model?.(key, (success: boolean) => {
    if (success) {
      aiModels.value = aiModels.value.filter(m => m.key !== key)
      appStore.showNotification('已移除模型', 'info')
    }
  })
}

function saveApiSettings(): void {
  const bridge = getBridge()
  bridge.save_api_key('dashscope', apiKey.value)
  if (selectedModel.value) {
    bridge.save_selected_model(selectedModel.value, () => {
      saveStatus.value = { message: '✓ 配置已同步', type: 'success' }
      appStore.showNotification('API 设置已保存', 'success')
      setTimeout(() => saveStatus.value = null, 3000)
    })
  }
}

function saveLanguage(): void {
  getBridge().save_ui_language(selectedLocale.value)
  appStore.setLocale(selectedLocale.value as any)
  appStore.showNotification('语言已切换', 'success')
}

const proofreadMode = ref(false)

/* -------- 词典管理逻辑 -------- */
function loadDictionary(): void {
  loadingDict.value = true
  // 解除只显示100条的限制，因为有了虚拟滚动，浏览器可以毫无压力处理几万条前端内存数据
  getBridge().get_all_dictionary_terms(proofreadMode.value, (termsStr: string) => {
    loadingDict.value = false
    try { 
      const terms = JSON.parse(termsStr)
      dictResults.value = Array.isArray(terms) ? terms : [] 
    } catch (e) { }
  })
}

function exportDictionaryCSV(): void {
  getBridge().get_all_dictionary_terms((termsStr: string) => {
    try {
      const terms = JSON.parse(termsStr)
      if (!Array.isArray(terms) || terms.length === 0) {
        appStore.showNotification('没有可导出的词典数据', 'warning')
        return
      }
      
      let csvContent = "" // getBridge().save_file handles the BOM if it ends with .csv
      csvContent += "英文原词,中文翻译,分类,来源\n"
      
      terms.forEach(term => {
        const en = term.english ? term.english.replace(/"/g, '""') : ''
        const zh = term.chinese ? term.chinese.replace(/"/g, '""') : ''
        const cat = term.category || ''
        const src = term.source || ''
        csvContent += `"${en}","${zh}","${cat}","${src}"\n`
      })
      
      const fileName = `Bio_Translation_Dict_${new Date().toISOString().slice(0,10)}.csv`
      getBridge().save_file(csvContent, fileName, (success: boolean) => {
        if (success) {
          appStore.showNotification('词库导出成功', 'success')
        } else {
          // User probably cancelled
          console.log('Export cancelled or failed')
        }
      })
    } catch (e) {
      appStore.showNotification('词库导出失败: 数据格式错误', 'error')
    }
  })
}

function searchDictionary(): void {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    if (!dictQuery.value.trim()) { loadDictionary(); return }
    loadingDict.value = true
    getBridge().search_dictionary(dictQuery.value.trim(), proofreadMode.value, (resStr: string) => {
      loadingDict.value = false
      try { dictResults.value = JSON.parse(resStr) } catch (e) { }
    })
  }, 300) // 300ms 防抖
}

function verifyTerm(english: string): void {
  getBridge().verify_dictionary_term(english, (success: boolean) => {
    if (success) {
      appStore.showNotification('词条已校对并标记为 verified', 'success')
      loadDictionary()
    }
  })
}

function saveTerm(): void {
  if (!newTermEn.value.trim() || !newTermZh.value.trim()) {
    appStore.showNotification('请填写英文原词和中文翻译', 'warning')
    return
  }
  getBridge().save_dictionary_term(newTermEn.value.trim(), newTermZh.value.trim(), newTermCat.value, (success: boolean) => {
    if (success) {
      appStore.showNotification('词条已保存', 'success')
      newTermEn.value = ''; newTermZh.value = ''; loadDictionary()
    }
  })
}

function deleteTerm(english: string): void {
  if (!confirm(`确定删除词条 "${english}"?`)) return
  getBridge().delete_dictionary_term(english, (success: boolean) => {
    if (success) { loadDictionary(); appStore.showNotification('已删除', 'info') }
  })
}

function editTerm(term: any): void {
  newTermEn.value = term.english
  newTermZh.value = term.chinese
  newTermCat.value = term.category || 'species'
  document.querySelector('.add-term-form')?.scrollIntoView({ behavior: 'smooth' })
}

/* -------- 物种分类数据库管理 -------- */
const taxStatus = ref<any>(null)
let taxPollTimer: any = null

async function refreshTaxStatus(): Promise<void> {
  try {
    const result = await getBridge().taxonomy_status()
    taxStatus.value = result
    
    // 如果正在构建，自动轮询
    if (result?.building && !taxPollTimer) {
      taxPollTimer = setInterval(async () => {
        try {
          const updated = await getBridge().taxonomy_status()
          taxStatus.value = updated
          if (!updated?.building) {
            clearInterval(taxPollTimer)
            taxPollTimer = null
            taxCheckResult.value = null
            appStore.showNotification('物种分类数据库更新完成！', 'success')
          }
        } catch (pollError) {
          console.error('[TaxStatus] Poll error:', pollError)
        }
      }, 2000)
    }
  } catch (fetchError) {
    console.error('[TaxStatus] Fetch error:', fetchError)
  }
}

async function triggerTaxUpdate(): Promise<void> {
  if (taxStatus.value?.building) return
  taxCheckResult.value = null
  appStore.showNotification('已启动后台更新，从 NCBI FTP 下载最新物种分类库...', 'info')
  try {
    await getBridge().taxonomy_update()
    // 立即开始轮询
    await refreshTaxStatus()
  } catch (updateError) {
    appStore.showNotification('更新触发失败: ' + String(updateError), 'error')
  }
}

const taxCheckResult = ref<any>(null)
const taxChecking = ref(false)

async function checkTaxUpdate(): Promise<void> {
  taxChecking.value = true
  taxCheckResult.value = null
  try {
    const result = await getBridge().taxonomy_check()
    taxCheckResult.value = result
    if (result?.hasUpdate) {
      appStore.showNotification('发现新版本！点击"从 NCBI 在线更新" 进行下载。', 'info')
    } else if (!result?.error) {
      appStore.showNotification('当前数据库已是最新版本。', 'success')
    }
  } catch (checkError) {
    taxCheckResult.value = { hasUpdate: false, error: String(checkError) }
  } finally {
    taxChecking.value = false
  }
}

// 切换到 local-db 面板时自动加载一次状态
watch(activePanel, (newVal) => {
  if (newVal === 'local-db') {
    refreshTaxStatus()
  }
})

onUnmounted(() => {
  if (taxPollTimer) clearInterval(taxPollTimer)
})
</script>

<template>
  <div class="settings-view">
    <!-- 侧边导航 -->
    <nav class="settings-sidebar">
      <div
        v-for="panel in panels"
        :key="panel.id"
        class="settings-nav-item"
        :class="{ active: activePanel === panel.id }"
        @click="activePanel = panel.id"
      >
        <span class="nav-icon">{{ panel.icon }}</span>
        <span class="nav-label">{{ panel.label }}</span>
      </div>
      <div class="spacer" />
      <div class="version-tag">NCBI BLAST Pro 2.0</div>
    </nav>

    <!-- 内容区域 -->
    <div class="settings-content">
      <!-- AI 翻译面板 -->
      <div v-if="activePanel === 'ai-translation'" class="panel">
        <h2>🤖 AI 翻译配置</h2>
        <div class="glass-card">
          <p class="desc">配置 DashScope (通义千问) API 以启用最匹配项翻译功能。</p>

          <!-- 模型选择 (自定义下拉菜单) -->
          <div class="form-group" ref="selectRef">
            <label>AI 翻译模型</label>
            <div class="custom-select">
              <div class="select-box form-input" @click="dropdownOpen = !dropdownOpen">
                {{ aiModels.find(m => m.key === selectedModel)?.name || '未选择模型' }}
                <span class="select-arrow">▼</span>
              </div>
              <transition name="fade">
                <div class="select-dropdown" v-if="dropdownOpen">
                  <div class="select-option" 
                    v-for="m in aiModels" :key="m.key" 
                    :class="{ active: selectedModel === m.key }"
                    @click.stop="selectModelOption(m.key)">
                    {{ m.name }}
                  </div>
                </div>
              </transition>
            </div>
          </div>

          <div class="form-group">
            <label>API Key</label>
            <input v-model="apiKey" type="password" class="form-input" placeholder="输入 DashScope API 密钥" />
          </div>

          <div class="actions-row">
            <span v-if="saveStatus" :class="['save-status', saveStatus.type]">{{ saveStatus.message }}</span>
            <button class="btn-premium" @click="saveApiSettings">保存 API 配置</button>
          </div>
        </div>

        <div class="glass-card" style="margin-top: 24px;">
           <label style="display: block; font-weight: 600; font-size: 0.9rem; margin-bottom: 16px; color: var(--text-primary);">📦 本地 AI 模型库</label>
           
           <!-- 模型网格列表 -->
           <div class="model-grid">
              <div v-for="m in aiModels" :key="m.key" class="model-card">
                <div class="model-card-info">
                  <div class="model-card-name">🤖 {{ m.name }}</div>
                  <div class="model-card-key">{{ m.key }}</div>
                </div>
                <button class="btn-delete-card" @click="deleteModel(m.key)" title="移除模型">✕</button>
              </div>
              <div v-if="aiModels.length === 0" class="empty-state-sm">
                尚未配置任何自定义模型
              </div>
            </div>

            <!-- 添加新模型表单 -->
            <div class="add-model-box">
              <div class="add-inputs">
                <input v-model="newModelKey" class="form-input" placeholder="模型标识 (如: qwen-max-0522)" />
                <input v-model="newModelName" class="form-input" placeholder="显示名称 (如: 通义千问-旗舰版)" />
              </div>
              <button class="btn-action-plus" @click="addModel">
                <span class="plus-icon">+</span> 添加模型
              </button>
            </div>
        </div>
      </div>

      <!-- 本地数据库面板 -->
      <div v-if="activePanel === 'local-db'" class="panel">
        <div class="panel-header-simple">
          <h2>💾 本地 BLAST 数据库管理</h2>
          <p class="desc-sm">管理用于本地比对分析的核酸和蛋白质序列数据库。</p>
        </div>

        <div class="db-manager-grid">
          <!-- 左侧：新建数据库 -->
          <div class="glass-card">
            <h3 style="font-size: 1rem; margin-bottom: 20px;">🔨 创建新数据库</h3>
            <div class="form-group">
              <label>输入 FASTA 文件</label>
              <div class="input-with-btn">
                <input v-model="dbInputFile" readonly class="form-input" placeholder="选择源文件..." />
                <button class="btn-action" @click="browseFasta">浏览</button>
              </div>
            </div>
            <div class="form-group">
              <label>数据库类型</label>
              <select v-model="dbType" class="form-input select-native">
                <option value="nucl">核酸 (Nucleotide)</option>
                <option value="prot">蛋白质 (Protein)</option>
              </select>
            </div>
            <div class="form-row" style="display: flex; gap: 12px;">
              <div class="form-group" style="flex: 1;">
                <label>数据库标题</label>
                <input v-model="dbTitle" class="form-input" placeholder="显示名称 (如: 16S_Core)" />
              </div>
              <div class="form-group" style="flex: 1;">
                <label>系统路径名</label>
                <input v-model="dbOutName" class="form-input" placeholder="英文文件名" />
              </div>
            </div>
            
            <button class="btn-premium" style="width: 100%; margin-top: 10px;" :disabled="isCreatingDb" @click="createDatabase">
              {{ isCreatingDb ? '⏳ 正在创建 (耗时取决于文件大小)...' : '🚀 开始创建数据库' }}
            </button>
          </div>

          <!-- 右侧：现有库列表 -->
          <div class="glass-card">
            <h3 style="font-size: 1rem; margin-bottom: 20px;">📂 现有数据库 ({{ localDatabases.length }})</h3>
            <div class="db-list-container scroll-v" style="max-height: 400px; overflow-y: auto;">
              <div v-if="loadingDbs" class="loading-placeholder">加载中...</div>
              <div v-else-if="localDatabases.length === 0" class="empty-state-sm">未发现本地数据库</div>
              <div v-for="db in localDatabases" :key="db.name" class="db-item-card">
                <div class="db-item-info">
                  <div class="db-item-name">
                    <span class="type-badge" :class="db.type">{{ db.type === 'nucl' ? '核酸' : '蛋白' }}</span>
                    {{ db.name }}
                  </div>
                  <div class="db-item-path" :title="db.path">{{ db.path }}</div>
                </div>
                <button class="btn-icon-link" @click="deleteDatabase(db.name)" title="删除数据库">🗑️</button>
              </div>
            </div>
            <button class="btn-action" style="width: 100%; margin-top: 16px;" @click="loadLocalDatabases">🔄 刷新列表</button>
          </div>
        </div>

        <!-- 物种分类数据库 -->
        <div class="glass-card" style="margin-top: 24px;">
          <h3 style="font-size: 1rem; margin-bottom: 16px;">🧬 NCBI 物种分类数据库</h3>
          <p class="desc-sm" style="margin-bottom: 16px;">
            基于 NCBI Taxonomy 的离线物种谱系查询库。用于 BLAST 鉴定后自动填充分类信息及编码对照表。
          </p>

          <!-- 状态信息 -->
          <div v-if="taxStatus" class="tax-status-grid">
            <div class="tax-status-item">
              <span class="tax-label">状态</span>
              <span :class="['tax-badge', taxStatus.ready ? 'ready' : 'missing']">
                {{ taxStatus.building ? '🔄 构建中...' : taxStatus.ready ? '✅ 就绪' : '❌ 未构建' }}
              </span>
            </div>
            <div v-if="taxStatus.fileSizeMB" class="tax-status-item">
              <span class="tax-label">文件大小</span>
              <span class="tax-value">{{ taxStatus.fileSizeMB }} MB</span>
            </div>
            <div v-if="taxStatus.lastModified" class="tax-status-item">
              <span class="tax-label">最后编译</span>
              <span class="tax-value">{{ taxStatus.lastModified }}</span>
            </div>
            <div v-if="taxStatus.ageDays !== undefined" class="tax-status-item">
              <span class="tax-label">距今</span>
              <span :class="['tax-value', taxStatus.ageDays > 180 ? 'stale' : '']">
                {{ Math.floor(taxStatus.ageDays) }} 天
                <span v-if="taxStatus.ageDays > 180" style="color: #f59e0b; margin-left: 4px;">⚠ 建议更新</span>
              </span>
            </div>
            <div v-if="taxStatus.dumpDate" class="tax-status-item">
              <span class="tax-label">原始数据</span>
              <span class="tax-value">{{ taxStatus.dumpDate }}</span>
            </div>
          </div>

          <!-- 构建进度 -->
          <div v-if="taxStatus?.building" class="tax-progress">
            <div class="progress-bar-track">
              <div class="progress-bar-fill animate-pulse" />
            </div>
            <p class="progress-text">{{ taxStatus.progress || '处理中...' }}</p>
          </div>

          <!-- 更新检查结果 -->
          <div v-if="taxCheckResult" class="tax-check-banner" :class="taxCheckResult.hasUpdate ? 'has-update' : 'up-to-date'">
            <template v-if="taxCheckResult.hasUpdate">
              <span>🆕 发现新版本可用！远端 MD5: <code>{{ taxCheckResult.remoteMd5?.slice(0, 12) }}...</code></span>
            </template>
            <template v-else-if="taxCheckResult.error">
              <span>⚠️ 检查失败: {{ taxCheckResult.error }}</span>
            </template>
            <template v-else>
              <span>✅ 当前已是最新版本 (MD5 一致)</span>
            </template>
          </div>

          <!-- 操作按钮 -->
          <div class="tax-actions">
            <button class="btn-action" @click="refreshTaxStatus">🔄 刷新状态</button>
            <button
              class="btn-action"
              :disabled="taxStatus?.building || taxChecking"
              @click="checkTaxUpdate"
            >
              {{ taxChecking ? '⏳ 检查中...' : '🔍 检查更新' }}
            </button>
            <button
              class="btn-premium"
              :disabled="taxStatus?.building"
              @click="triggerTaxUpdate"
            >
              {{ taxStatus?.building ? '⏳ 更新中...' : '🌐 从 NCBI 在线更新' }}
            </button>
          </div>
        </div>
      </div>

      <!-- 界面显示面板 -->
      <div v-if="activePanel === 'user-interface'" class="panel">
        <h2>🖥️ 界面显示设置</h2>
        <div class="glass-card">
          <div class="form-group">
            <label>界面语言 (UI Language)</label>
            <div class="custom-select" style="max-width: 300px;">
              <select v-model="selectedLocale" class="form-input select-native">
                <option value="zh_CN">简体中文</option>
                <option value="en_US">English</option>
              </select>
            </div>
          </div>
          <div class="actions-row">
            <button class="btn-premium" @click="saveLanguage">应用语言更改</button>
          </div>
        </div>
      </div>

      <!-- 词典管理面板 -->
      <div v-if="activePanel === 'dictionary'" class="panel">
        <div class="panel-header-simple">
          <h2>📖 常用生物学术语词典</h2>
          <p class="desc-sm">本地词条翻译结果会显示 [本地] 标记，AI 翻译后会自动同步至此库。</p>
        </div>

        <!-- 添加词条 -->
        <div class="glass-card add-term-form" style="margin-bottom: 24px;">
          <h3 style="font-size: 1rem; margin-bottom: 16px;">➕ 录入翻译条目</h3>
          <div class="add-term-grid">
            <div class="form-group">
              <label>英文原词 / 术语</label>
              <input v-model="newTermEn" type="text" class="form-input" placeholder="输入英文文本" />
            </div>
            <div class="form-group">
              <label>中文翻译</label>
              <input v-model="newTermZh" type="text" class="form-input" placeholder="输入对应中文" />
            </div>
            <div class="form-group" ref="dictSelectRef">
              <label>所属分类</label>
              <div class="custom-select">
                <div class="select-box form-input" @click="dictDropdownOpen = !dictDropdownOpen">
                  {{ getCategoryLabel(newTermCat) }}
                  <span class="select-arrow">▼</span>
                </div>
                <div class="select-dropdown" v-if="dictDropdownOpen">
                  <div v-for="cat in dictCategories" :key="cat.id"
                    class="select-option" :class="{ active: newTermCat === cat.id }"
                    @click.stop="selectDictCategory(cat.id)">
                    {{ cat.label }}
                  </div>
                </div>
              </div>
            </div>
            <div class="form-group action-group">
              <button class="btn-premium" style="width: 100%; height: 40px;" @click="saveTerm">保存并应用</button>
            </div>
          </div>
        </div>

        <div class="glass-card">
          <div class="search-row" style="margin-bottom: 20px; display: flex; gap: 12px; align-items: center;">
            <input v-model="dictQuery" type="search" class="form-input" 
              style="flex: 1"
              placeholder="快速搜索 (输入 'ai' 可查所有 AI 生成词条)..." @input="searchDictionary" />
            <label style="display: flex; align-items: center; gap: 6px; font-size: 0.9rem; cursor: pointer;">
              <input type="checkbox" v-model="proofreadMode" @change="loadDictionary" />
              开启纯净校对模式
            </label>
            <button class="btn-action" style="padding: 8px 16px;" @click="exportDictionaryCSV">⬇️ 导出完整词库 (CSV)</button>
            <button class="btn-action" style="padding: 8px 16px;" @click="loadDictionary">🔄 刷新数据</button>
          </div>

          <div class="dict-table-container">
            <div class="dict-grid-header">
              <div class="th">英文原词</div>
              <div class="th">翻译结果</div>
              <div class="th">分类</div>
              <div class="th">来源</div>
              <div class="th text-right">操作</div>
            </div>
            
            <div v-bind="containerProps" class="dict-virtual-container">
              <div v-if="loadingDict" class="dict-loading-overlay">
                <div class="neo-spinner"></div>
                <span>加载词录中...</span>
              </div>
              <div v-else-if="dictResults.length === 0" class="dict-empty-overlay">
                <span class="icon">🔍</span>
                <span>未找到相关词条</span>
              </div>
              <div v-bind="wrapperProps">
                <div v-for="item in list" :key="item.index" class="dict-grid-row">
                  <div class="td dict-en-cell">{{ item.data.english }}</div>
                  <div class="td dict-zh-cell">{{ item.data.chinese }}</div>
                  <div class="td"><span class="dict-cat-tag">{{ item.data.category }}</span></div>
                  <div class="td">
                    <span class="source-tag" :class="getSourceClass(item.data.source)">{{ getSourceLabel(item.data.source) }}</span>
                  </div>
                  <div class="td text-right dict-actions">
                    <button v-if="proofreadMode && item.data.source !== 'verified'" class="btn-icon-link" @click="verifyTerm(item.data.english)" title="标记为已通过校对">✔️</button>
                    <button class="btn-icon-link" @click="editTerm(item.data)">✏️</button>
                    <button class="btn-icon-link" @click="deleteTerm(item.data.english)">🗑️</button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.settings-view { display: flex; height: 100%; background: #f8fafc; }
.settings-sidebar { width: 220px; background: white; border-right: 1px solid var(--border-color); padding: 16px 8px; }
.settings-nav-item { display: flex; align-items: center; padding: 10px 14px; margin: 2px 0; border-radius: 8px; cursor: pointer; color: var(--text-secondary); font-size: 0.875rem; }
.settings-nav-item.active { background: rgba(59, 130, 246, 0.08); color: var(--accent-blue); font-weight: 600; }
.nav-icon { margin-right: 10px; }
.settings-content { flex: 1; overflow-y: auto; padding: 32px 48px; }
.panel h2 { font-size: 1.25rem; margin-bottom: 24px; color: var(--text-primary); }
.glass-card { background: white; border: 1px solid var(--border-color); border-radius: 12px; padding: 24px;  }
.desc { color: var(--text-secondary); font-size: 0.9rem; margin-bottom: 24px; }
.form-group { margin-bottom: 20px; position: relative; }
.form-group label { display: block; font-weight: 600; font-size: 0.875rem; margin-bottom: 8px; }
.form-input { width: 100%; padding: 10px 14px; border: 1px solid var(--border-color); border-radius: 6px; font-size: 0.875rem; box-sizing: border-box; }
.form-input:focus { outline: none; border-color: var(--accent-blue); }

/* 自定义下拉菜单核心逻辑 */
.custom-select { position: relative; width: 100%; user-select: none; }
.select-box { display: flex; justify-content: space-between; align-items: center; cursor: pointer; }
.select-dropdown { 
  position: absolute; top: 105%; left: 0; right: 0; 
  background: white; border: 1px solid var(--border-color); 
  border-radius: 8px;  
  z-index: 999; max-height: 250px; overflow-y: auto;
}
.select-option { padding: 10px 14px; font-size: 0.875rem; color: var(--text-primary); cursor: pointer; }
.select-option:hover { background: #f1f5f9; }
.select-option.active { color: var(--accent-blue); font-weight: 600; background: rgba(59, 130, 246, 0.05); }

/* 词典网格 */
.add-term-grid { display: flex; gap: 16px; align-items: flex-end; width: 100%; max-width: 100%; box-sizing: border-box; }
.add-term-grid .form-group { flex: 1; min-width: 0; margin-bottom: 0; }
.add-term-grid .form-group:nth-child(3) { flex: 0 0 170px; }
.add-term-grid .action-group { flex: 0 0 120px; }

.dict-table-container { border: 1px solid var(--border-color); border-radius: 8px; overflow: hidden; }
.dict-grid-header, .dict-grid-row {
  display: grid;
  grid-template-columns: 2.5fr 2fr 1fr 1fr 130px;
  gap: 16px;
  align-items: center;
  padding: 0 16px;
}
.dict-grid-header {
  height: 48px;
  background: var(--bg-secondary, #f8fafc);
  border-bottom: 1px solid var(--border-color);
  font-weight: 600;
  font-size: 0.85rem;
  color: var(--text-secondary);
}
.dict-grid-row {
  height: 52px;
  border-bottom: 1px solid var(--border-light);
  transition: background 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}
.dict-grid-row:hover { background: #f8fafc; }
.dict-virtual-container {
  height: calc(100vh - 400px);
  min-height: 400px;
  overflow-y: auto;
}
.text-right { text-align: right; justify-content: flex-end; }
.td { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 0.85rem; color: var(--text-primary); }
.dict-en-cell { font-weight: 600; }
.dict-zh-cell { color: var(--accent-blue); font-weight: 600; }
.dict-cat-tag { background: #f1f5f9; padding: 4px 8px; border-radius: 4px; font-size: 0.72rem; display: inline-block; }
.source-tag { font-size: 0.72rem; color: var(--text-muted); display: inline-block; padding: 2px 6px; border-radius: 4px; background: rgba(100,116,139,0.1); }
.source-tag.ai { background: rgba(239, 68, 68, 0.1); color: #ef4444; }
.source-tag.verified { background: rgba(16, 185, 129, 0.1); color: #10b981; }
.source-tag.manual { background: rgba(59, 130, 246, 0.1); color: var(--accent-blue); }

.dict-actions { display: flex; gap: 8px; justify-content: flex-end; overflow: visible; }
.btn-icon-link { background: none; backface-visibility: hidden; -webkit-backface-visibility: hidden; border: none; backface-visibility: hidden; -webkit-backface-visibility: hidden; font-size: 1.05rem; backface-visibility: hidden; -webkit-backface-visibility: hidden; cursor: pointer; backface-visibility: hidden; -webkit-backface-visibility: hidden; padding: 4px; backface-visibility: hidden; -webkit-backface-visibility: hidden; transition: transform 0.1s; backface-visibility: hidden; -webkit-backface-visibility: hidden; display: inline-flex; backface-visibility: hidden; -webkit-backface-visibility: hidden; align-items: center; backface-visibility: hidden; -webkit-backface-visibility: hidden; justify-content: center; backface-visibility: hidden; -webkit-backface-visibility: hidden; width: 26px; backface-visibility: hidden; -webkit-backface-visibility: hidden; height: 26px; backface-visibility: hidden; -webkit-backface-visibility: hidden; border-radius: 4px; backface-visibility: hidden; -webkit-backface-visibility: hidden; }
.btn-icon-link:hover { transform: scale(1.1); background: rgba(0,0,0,0.05); }

.btn-premium { background: var(--accent-blue); color: white; border: none; padding: 10px 24px; border-radius: 6px; font-weight: 600; cursor: pointer; }
.btn-action { background: white; border: 1px solid var(--accent-blue); color: var(--accent-blue); padding: 6px 14px; border-radius: 6px; cursor: pointer; }
.btn-delete { background: none; color: var(--text-muted); border: none; cursor: pointer; padding: 4px 8px; }
.btn-delete:hover { color: var(--accent-red); }
/* 模型库管理优化 */
.model-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; margin-bottom: 24px; }
.model-card { 
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 16px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}
.model-card:hover { border-color: var(--accent-blue); background: white;  }
.model-card-info { flex: 1; min-width: 0; }
.model-card-name { font-weight: 600; font-size: 0.9rem; color: var(--text-primary); margin-bottom: 2px; }
.model-card-key { font-size: 0.72rem; color: var(--text-muted); font-family: monospace; overflow: hidden; text-overflow: ellipsis; }
.btn-delete-card { background: none; backface-visibility: hidden; -webkit-backface-visibility: hidden; border: none; backface-visibility: hidden; -webkit-backface-visibility: hidden; font-size: 1rem; backface-visibility: hidden; -webkit-backface-visibility: hidden; color: #cbd5e1; backface-visibility: hidden; -webkit-backface-visibility: hidden; cursor: pointer; backface-visibility: hidden; -webkit-backface-visibility: hidden; padding: 4px; backface-visibility: hidden; -webkit-backface-visibility: hidden; line-height: 1; backface-visibility: hidden; -webkit-backface-visibility: hidden; transition: color 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden; }
.btn-delete-card:hover { color: var(--accent-red); }

.add-model-box { display: flex; flex-direction: column; gap: 12px; padding-top: 20px; border-top: 1px dashed #e2e8f0; }
.add-inputs { display: flex; gap: 8px; }
.add-inputs .form-input { flex: 1; }
.btn-action-plus { 
  display: flex; align-items: center; justify-content: center; gap: 8px;
  background: white; border: 1px solid var(--accent-blue); color: var(--accent-blue);
  padding: 10px; backface-visibility: hidden; -webkit-backface-visibility: hidden; border-radius: 8px; backface-visibility: hidden; -webkit-backface-visibility: hidden; font-weight: 600; backface-visibility: hidden; -webkit-backface-visibility: hidden; font-size: 0.85rem; backface-visibility: hidden; -webkit-backface-visibility: hidden; cursor: pointer; backface-visibility: hidden; -webkit-backface-visibility: hidden; transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}
.btn-action-plus:hover { background: var(--accent-blue); color: white; }
.plus-icon { font-size: 1.2rem; line-height: 1; }
.empty-state-sm { grid-column: 1 / -1; padding: 20px; text-align: center; color: var(--text-muted); font-size: 0.85rem; background: #f8fafc; border-radius: 10px; border: 1px dashed #e2e8f0; }

/* 词典加载动画与空状态 */
.dict-virtual-container {
  height: 500px;
  overflow-y: auto;
  position: relative;
  background: #fdfdfd;
}

.dict-loading-overlay {
  position: absolute;
  inset: 0;
  background: rgba(255, 255, 255, 0.8);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  z-index: 10;
  backdrop-filter: blur(2px);
}

.neo-spinner {
  width: 40px;
  height: 40px;
  border: 4px solid #f3f3f3;
  border-top: 4px solid #2563eb;
  border-radius: 50%;
  animation: neo-spin 1s linear infinite;
}

@keyframes neo-spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

.dict-empty-overlay {
  padding: 80px 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  color: #94a3b8;
  font-size: 1.1rem;
}
.dict-empty-overlay .icon { font-size: 3rem; opacity: 0.3; }

/* 词典行内操作按钮 */
.dict-actions { display: flex; gap: 16px; justify-content: flex-end; }
.btn-icon-link { 
  background: none; border: none; cursor: pointer; padding: 4px; 
  font-size: 1.05rem; backface-visibility: hidden; -webkit-backface-visibility: hidden; opacity: 0.4; backface-visibility: hidden; -webkit-backface-visibility: hidden; transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden; 
  display: flex; align-items: center; justify-content: center;
}
.btn-icon-link:hover { opacity: 1; transform: scale(1.2); }

/* 数据库管理特有样式 */
.db-manager-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; align-items: start; }
.input-with-btn { display: flex; gap: 8px; }
.db-item-card { 
  display: flex; justify-content: space-between; align-items: center; 
  padding: 12px 16px; background: #f8fafc; border: 1px solid #e2e8f0; 
  border-radius: 10px; margin-bottom: 10px;
}
.db-item-info { flex: 1; min-width: 0; }
.db-item-name { font-weight: 700; font-size: 0.95rem; display: flex; align-items: center; gap: 8px; }
.db-item-path { font-size: 0.75rem; color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.type-badge { font-size: 0.65rem; padding: 2px 6px; border-radius: 4px; font-weight: 800; color: white; }
.type-badge.nucl { background: #2563eb; }
.type-badge.prot { background: #16a34a; }

.spacer { flex: 1; }
.version-tag { font-size: 0.75rem; color: var(--text-muted); padding: 8px 14px; }

/* ─── 物种分类数据库管理 ─── */

.tax-status-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.tax-status-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 14px;
  background: var(--bg-tertiary, #f8fafc);
  border-radius: 8px;
  border: 1px solid var(--border-light, #e2e8f0);
}

.tax-label {
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--text-muted, #94a3b8);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.tax-value {
  font-size: 0.88rem;
  font-weight: 600;
  color: var(--text-primary, #1e293b);
}

.tax-value.stale {
  color: #f59e0b;
}

.tax-badge {
  font-size: 0.85rem;
  font-weight: 700;
}

.tax-badge.ready { color: #16a34a; }
.tax-badge.missing { color: #dc2626; }

.tax-progress {
  margin: 16px 0;
}

.progress-bar-track {
  height: 6px;
  background: var(--border-light, #e2e8f0);
  border-radius: 3px;
  overflow: hidden;
}

.progress-bar-fill {
  height: 100%;
  width: 100%;
  background: linear-gradient(90deg, #2563eb, #7c3aed, #2563eb);
  background-size: 200% 100%;
  border-radius: 3px;
}

.progress-bar-fill.animate-pulse {
  animation: shimmer 1.5s ease-in-out infinite;
}

@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

.progress-text {
  font-size: 0.78rem;
  color: var(--text-muted, #94a3b8);
  margin-top: 8px;
  text-align: center;
}

.tax-actions {
  display: flex;
  gap: 12px;
  margin-top: 16px;
}

.tax-check-banner {
  padding: 10px 16px;
  border-radius: 8px;
  font-size: 0.82rem;
  font-weight: 600;
  margin-bottom: 12px;
}

.tax-check-banner.has-update {
  background: #eff6ff;
  border: 1px solid #93c5fd;
  color: #1e40af;
}

.tax-check-banner.up-to-date {
  background: #f0fdf4;
  border: 1px solid #86efac;
  color: #166534;
}

.tax-check-banner code {
  font-family: 'Consolas', monospace;
  font-size: 0.75rem;
  background: rgba(0, 0, 0, 0.06);
  padding: 2px 6px;
  border-radius: 4px;
}
</style>