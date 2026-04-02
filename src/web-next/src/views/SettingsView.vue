<script setup lang="ts">
/**
 * SettingsView - 应用设置页面
 * 包含 AI翻译 / 系统参数 / 界面语言 / 词典管理
 * 使用自定义下拉组件解决 PyQt 环境下的布局重绘 Bug
 */
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { getBridge } from '../bridge/pyqt-bridge'
import { useAppStore } from '../stores/app'

const appStore = useAppStore()

/* -------- 面板切换 -------- */
const panels = [
  { id: 'ai-translation', label: 'AI & 翻译', icon: '🤖' },
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

// 词典管理状态
const dictQuery = ref('')
const dictResults = ref<Array<{ english: string; chinese: string; category: string; source?: string }>>([])
const newTermEn = ref('')
const newTermZh = ref('')
const newTermCat = ref('species')

// 下拉菜单控制 (全部采用自定义实现)
const dropdownOpen = ref(false)
const selectRef = ref<HTMLElement | null>(null)
const dictDropdownOpen = ref(false)
const dictSelectRef = ref<HTMLElement | null>(null)
let searchTimer: any = null

const dictCategories = [
  { id: 'species', label: '物种名 (Species)' },
  { id: 'genus', label: '属名 (Genus)' },
  { id: 'gene', label: '基因名 (Gene)' },
  { id: 'location', label: '地理/来源' },
  { id: 'other', label: '其他' }
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

/* -------- 生命周期 -------- */
onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  loadSettings()
  // 移除初始加载时的全量词典加载，改为切换到面板时按需加载，解决进入设置页时的卡顿
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})

/** 监听面板切换，执行延迟加载 */
watch(activePanel, (newVal) => {
  if (newVal === 'dictionary' && dictResults.value.length === 0) {
    loadDictionary()
  }
})

/* -------- 业务逻辑 -------- */
async function loadSettings(): Promise<void> {
  try {
    const bridge = getBridge()
    bridge.get_api_key('dashscope', (key: string) => { if (key) apiKey.value = key })
    bridge.get_ai_models((modelsStr: string) => {
      try {
        aiModels.value = JSON.parse(modelsStr)
        if (aiModels.value.length > 0 && !selectedModel.value) {
          selectedModel.value = aiModels.value[0]?.key ?? ''
        }
      } catch (e) { }
    })
    bridge.get_selected_model((savedModel: string) => {
      if (savedModel) selectedModel.value = savedModel
    })
  } catch (error) { console.warn('[Settings] Bridge not ready') }
}

function addModel(): void {
  if (!newModelKey.value.trim() || !newModelName.value.trim()) {
    appStore.showNotification('请填写完整模型配置', 'warning')
    return
  }
  getBridge().add_ai_model(newModelKey.value.trim(), newModelName.value.trim(), (success: boolean) => {
    if (success) {
      aiModels.value.push({ key: newModelKey.value.trim(), name: newModelName.value.trim() })
      newModelKey.value = ''; newModelName.value = ''
      appStore.showNotification('模型加入成功', 'success')
    }
  })
}

function deleteModel(key: string): void {
  getBridge().delete_ai_model(key, (success: boolean) => {
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

/* -------- 词典管理逻辑 -------- */
function loadDictionary(): void {
  getBridge().get_all_dictionary_terms((termsStr: string) => {
    try { dictResults.value = JSON.parse(termsStr) } catch (e) { }
  })
}

function searchDictionary(): void {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    if (!dictQuery.value.trim()) { loadDictionary(); return }
    getBridge().search_dictionary(dictQuery.value.trim(), (resStr: string) => {
      try { dictResults.value = JSON.parse(resStr) } catch (e) { }
    })
  }, 300) // 300ms 防抖
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
              placeholder="快速搜索本地词库 (英文或中文)..." @input="searchDictionary" />
            <button class="btn-action" style="padding: 8px 16px;" @click="loadDictionary">🔄 刷新数据</button>
          </div>

          <div class="dict-table-container">
            <table class="dict-table">
              <thead>
                <tr>
                  <th>英文原词</th>
                  <th>翻译结果</th>
                  <th>分类</th>
                  <th>来源</th>
                  <th style="text-align: right;">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(result, idx) in dictResults" :key="idx">
                  <td class="dict-en-cell">{{ result.english }}</td>
                  <td class="dict-zh-cell">{{ result.chinese }}</td>
                  <td><span class="dict-cat-tag">{{ result.category }}</span></td>
                  <td><span class="source-tag">{{ result.source || 'manual' }}</span></td>
                  <td style="text-align: right;">
                    <div class="dict-actions">
                      <button class="btn-icon-link" @click="editTerm(result)">✏️</button>
                      <button class="btn-icon-link" @click="deleteTerm(result.english)">🗑️</button>
                    </div>
                  </td>
                </tr>
                <tr v-if="dictResults.length === 0">
                  <td colspan="5" class="empty-hint">暂无词条，请在上方尝试录入</td>
                </tr>
              </tbody>
            </table>
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
.glass-card { background: white; border: 1px solid var(--border-color); border-radius: 12px; padding: 24px; box-shadow: var(--shadow-sm); }
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
  border-radius: 8px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); 
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

.dict-table-container { max-height: 500px; overflow-y: auto; border: 1px solid var(--border-color); border-radius: 8px; }
.dict-table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
.dict-table th { position: sticky; top: 0; background: #f8fafc; padding: 12px; text-align: left; border-bottom: 2px solid var(--border-color); z-index: 10; }
.dict-table td { padding: 12px; border-bottom: 1px solid var(--border-light); }
.dict-en-cell { font-weight: 600; }
.dict-zh-cell { color: var(--accent-blue); }
.dict-cat-tag { background: #f1f5f9; padding: 2px 8px; border-radius: 4px; font-size: 0.72rem; }
.source-tag { font-size: 0.72rem; color: var(--text-muted); }

.btn-premium { background: var(--accent-blue); color: white; border: none; padding: 10px 24px; border-radius: 6px; font-weight: 600; cursor: pointer; }
.btn-action { background: white; border: 1px solid var(--accent-blue); color: var(--accent-blue); padding: 6px 14px; border-radius: 6px; cursor: pointer; }
.btn-delete { background: none; color: var(--text-muted); border: none; cursor: pointer; padding: 4px 8px; }
.btn-delete:hover { color: var(--accent-red); }
/* 模型库管理优化 */
.model-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; margin-bottom: 24px; }
.model-card { 
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 16px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px;
  transition: all 0.2s;
}
.model-card:hover { border-color: var(--accent-blue); background: white; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }
.model-card-info { flex: 1; min-width: 0; }
.model-card-name { font-weight: 600; font-size: 0.9rem; color: var(--text-primary); margin-bottom: 2px; }
.model-card-key { font-size: 0.72rem; color: var(--text-muted); font-family: monospace; overflow: hidden; text-overflow: ellipsis; }
.btn-delete-card { background: none; border: none; font-size: 1rem; color: #cbd5e1; cursor: pointer; padding: 4px; line-height: 1; transition: color 0.2s; }
.btn-delete-card:hover { color: var(--accent-red); }

.add-model-box { display: flex; flex-direction: column; gap: 12px; padding-top: 20px; border-top: 1px dashed #e2e8f0; }
.add-inputs { display: flex; gap: 8px; }
.add-inputs .form-input { flex: 1; }
.btn-action-plus { 
  display: flex; align-items: center; justify-content: center; gap: 8px;
  background: white; border: 1px solid var(--accent-blue); color: var(--accent-blue);
  padding: 10px; border-radius: 8px; font-weight: 600; font-size: 0.85rem; cursor: pointer; transition: all 0.2s;
}
.btn-action-plus:hover { background: var(--accent-blue); color: white; }
.plus-icon { font-size: 1.2rem; line-height: 1; }
.empty-state-sm { grid-column: 1 / -1; padding: 20px; text-align: center; color: var(--text-muted); font-size: 0.85rem; background: #f8fafc; border-radius: 10px; border: 1px dashed #e2e8f0; }

/* 词典行内操作按钮 */
.dict-actions { display: flex; gap: 16px; justify-content: flex-end; }
.btn-icon-link { 
  background: none; border: none; cursor: pointer; padding: 4px; 
  font-size: 1.05rem; opacity: 0.4; transition: all 0.2s; 
  display: flex; align-items: center; justify-content: center;
}
.btn-icon-link:hover { opacity: 1; transform: scale(1.2); }

.spacer { flex: 1; }
.version-tag { font-size: 0.75rem; color: var(--text-muted); padding: 8px 14px; }
</style>
