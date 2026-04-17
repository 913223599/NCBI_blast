<script setup lang="ts">
/**
 * SettingsView - 应用设置容器
 * 遵循单一职责原则，将复杂业务解耦至独立 Panel 组件中
 */
import { ref } from 'vue'

// 导入业务面板组件
import AITranslationPanel from '../components/settings/AITranslationPanel.vue'
import DatabasePanel from '../components/settings/DatabasePanel.vue'
import SystemParamsPanel from '../components/settings/SystemParamsPanel.vue'
import UserInterfacePanel from '../components/settings/UserInterfacePanel.vue'
import DictionaryPanel from '../components/settings/DictionaryPanel.vue'

/* -------- 侧边导航配置 -------- */
const panels = [
  { id: 'ai-translation', label: 'AI & 翻译', icon: '🤖' },
  { id: 'local-db', label: '本地数据库', icon: '💾' },
  { id: 'system-params', label: '系统参数', icon: '⚙️' },
  { id: 'user-interface', label: '界面显示', icon: '🖥️' },
  { id: 'dictionary', label: '词典管理', icon: '📖' }
]

const activePanel = ref('ai-translation')
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

    <!-- 动态内容区域 -->
    <div class="settings-content scroll-y">
      <AITranslationPanel v-if="activePanel === 'ai-translation'" />
      <DatabasePanel v-if="activePanel === 'local-db'" />
      <SystemParamsPanel v-if="activePanel === 'system-params'" />
      <UserInterfacePanel v-if="activePanel === 'user-interface'" />
      <DictionaryPanel v-if="activePanel === 'dictionary'" />
    </div>
  </div>
</template>

<style scoped>
.settings-view {
  display: flex;
  height: 100vh;
  background: #f1f5f9;
  overflow: hidden;
}

/* 侧边栏样式 */
.settings-sidebar {
  width: 200px;
  background: white;
  border-right: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  padding: 12px;
}

.settings-nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  margin-bottom: 4px;
  border-radius: 12px;
  cursor: pointer;
  color: #64748b;
  font-weight: 500;
  transition: all 0.2s;
}

.settings-nav-item:hover {
  background: #f8fafc;
  color: #2563eb;
}

.settings-nav-item.active {
  background: #eff6ff;
  color: #2563eb;
}

.nav-icon { font-size: 1.1rem; }

.settings-content {
  flex: 1;
  overflow-y: auto;
  position: relative;
}

.spacer { flex: 1; }
.version-tag {
  font-size: 0.75rem;
  color: #94a3b8;
  padding: 12px;
  text-align: center;
}

/* 兼容原有全局 CSS 变量 */
:root {
  --accent-blue: #2563eb;
}
</style>