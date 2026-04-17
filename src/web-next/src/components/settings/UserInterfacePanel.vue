<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { getBridge } from '../../bridge'
import { useAppStore } from '../../stores/app'

const appStore = useAppStore()
const selectedLocale = ref('zh_CN')

function saveLanguage() {
  getBridge().save_ui_language(selectedLocale.value)
  appStore.setLocale(selectedLocale.value as any)
  appStore.showNotification('界面显示语言已动态切换', 'success')
}

onMounted(() => {
  selectedLocale.value = appStore.locale || 'zh_CN'
})
</script>

<template>
  <div class="panel">
    <header class="panel-header">
      <h2>🖥️ 界面显示与语言</h2>
      <p class="desc">调整本分析工作台的交互语言与视觉呈现方式。</p>
    </header>

    <div class="p-card">
      <div class="p-form-group">
        <label>显示语言 (Interface Language)</label>
        <select v-model="selectedLocale" class="p-input">
          <option value="zh_CN">简体中文 (Modern Chinese)</option>
          <option value="en_US">English (International Standard)</option>
        </select>
        <p class="hint mt-8">更改语言后，大部分界面标签将立即更新，部分底层日志可能需要重启应用生效。</p>
      </div>
      
      <div style="text-align: right; margin-top: 32px;">
        <button class="p-btn p-btn-primary" @click="saveLanguage">✅ 应用语言偏好</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.hint { font-size: 0.8rem; color: #94a3b8; }
.mt-8 { margin-top: 8px; }
</style>
