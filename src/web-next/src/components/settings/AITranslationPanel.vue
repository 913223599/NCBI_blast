<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { getBridge } from '../../bridge'
import { useAppStore } from '../../stores/app'

const appStore = useAppStore()

const apiKey = ref('')
const selectedModel = ref('')
const aiModels = ref<Array<{ key: string; name: string }>>([])
const newModelKey = ref('')
const newModelName = ref('')
const dropdownOpen = ref(false)
const saveStatus = ref<{ message: string; type: string } | null>(null)

function loadAISettings() {
  const bridge = getBridge()
  bridge.get_api_key('dashscope', (key: string) => { if (key) apiKey.value = key })
  bridge.get_ai_models?.((modelsStr: string) => {
    try {
      const models = JSON.parse(modelsStr)
      if (Array.isArray(models)) {
        aiModels.value = models
        bridge.get_selected_model?.((savedModel: string) => {
          if (savedModel && savedModel !== 'None') selectedModel.value = savedModel
          else if (models.length > 0) selectedModel.value = models[0].key
        })
      }
    } catch (e) { }
  })
}

function saveApiSettings() {
  getBridge().save_api_key('dashscope', apiKey.value)
  if (selectedModel.value) {
    getBridge().save_selected_model(selectedModel.value, () => {
      saveStatus.value = { message: '✓ 配置已同步', type: 'success' }
      appStore.showNotification('API 设置已保存', 'success')
      setTimeout(() => saveStatus.value = null, 3000)
    })
  }
}

function addModel() {
  if (!newModelKey.value.trim() || !newModelName.value.trim()) return
  getBridge().add_ai_model?.(newModelKey.value.trim(), newModelName.value.trim(), (success: boolean) => {
    if (success) {
      aiModels.value.push({ key: newModelKey.value.trim(), name: newModelName.value.trim() })
      newModelKey.value = ''; newModelName.value = ''
      appStore.showNotification('模型加入成功', 'success')
    }
  })
}

function deleteModel(key: string) {
  getBridge().delete_ai_model?.(key, (success: boolean) => {
    if (success) {
      aiModels.value = aiModels.value.filter(m => m.key !== key)
      appStore.showNotification('已移除模型', 'info')
    }
  })
}

onMounted(() => {
  loadAISettings()
})
</script>

<template>
  <div class="panel">
    <header class="panel-header">
      <h2>🤖 AI 翻译配置</h2>
      <p class="desc">配置 DashScope (通义千问) 接口以实现物种及基因功能的智能翻译与校验。</p>
    </header>

    <div class="p-card">
      <div class="p-form-group">
        <label>选择 AI 翻译模型</label>
        <select v-model="selectedModel" class="p-input">
          <option v-for="m in aiModels" :key="m.key" :value="m.key">{{ m.name }}</option>
        </select>
      </div>

      <div class="p-form-group">
        <label>DashScope API Key</label>
        <input v-model="apiKey" type="password" class="p-input" placeholder="sk-..." />
      </div>

      <div style="display: flex; justify-content: flex-end; align-items: center; gap: 16px;">
        <span v-if="saveStatus" :style="{ color: '#10b981', fontSize: '0.85rem' }">{{ saveStatus.message }}</span>
        <button class="p-btn p-btn-primary" @click="saveApiSettings">💾 保存配置</button>
      </div>
    </div>

    <!-- 模型库管理 -->
    <div class="p-card" style="margin-top: 32px;">
      <h3>📦 本地 AI 模型库</h3>
      <p class="desc-sm">在此添加或删除业务所需的特定 AI 模型标识。</p>
      
      <div class="p-grid" style="margin-bottom: 24px;">
        <div v-for="m in aiModels" :key="m.key" class="model-item">
          <div class="model-info">
             <div class="name">🤖 {{ m.name }}</div>
             <div class="key">{{ m.key }}</div>
          </div>
          <button class="btn-del" @click="deleteModel(m.key)">✕</button>
        </div>
      </div>

      <div class="add-box">
        <input v-model="newModelKey" class="p-input" placeholder="模型标识 (Key)" style="flex: 1" />
        <input v-model="newModelName" class="p-input" placeholder="显示名称 (Name)" style="flex: 1" />
        <button class="p-btn p-btn-outline" @click="addModel">➕ 添加模型</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.model-item {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 12px 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.name { font-weight: 700; font-size: 0.9rem; color: #334155; }
.key { font-size: 0.75rem; color: #94a3b8; font-family: monospace; }
.btn-del { 
  background: none; border: none; color: #94a3b8; cursor: pointer; padding: 4px;
}
.btn-del:hover { color: #ef4444; }

.add-box {
  display: flex;
  gap: 12px;
  padding-top: 16px;
  border-top: 1px dashed #e2e8f0;
}
</style>
