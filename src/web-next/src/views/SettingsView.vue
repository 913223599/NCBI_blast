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
import UpdatePanel from '../components/settings/UpdatePanel.vue'

/* -------- 侧边导航配置 (纯 SVG 图标，全面禁用 Emoji) -------- */
const panels = [
  { id: 'ai-translation', label: 'AI & 翻译' },
  { id: 'local-db', label: '本地数据库' },
  { id: 'system-params', label: '系统参数' },
  { id: 'user-interface', label: '界面显示' },
  { id: 'dictionary', label: '词典管理' },
  { id: 'update', label: '软件更新' }
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
        <span class="nav-icon">
          <!-- 1. AI 翻译 -->
          <svg v-if="panel.id === 'ai-translation'" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="11" width="18" height="10" rx="2"></rect>
            <circle cx="12" cy="5" r="2"></circle>
            <path d="M12 7v4"></path>
            <line x1="8" y1="16" x2="8" y2="16"></line>
            <line x1="16" y1="16" x2="16" y2="16"></line>
          </svg>
          <!-- 2. 本地数据库 -->
          <svg v-else-if="panel.id === 'local-db'" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
            <ellipse cx="12" cy="5" rx="9" ry="3"></ellipse>
            <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path>
            <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path>
          </svg>
          <!-- 3. 系统参数 -->
          <svg v-else-if="panel.id === 'system-params'" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3"></circle>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
          </svg>
          <!-- 4. 界面显示 -->
          <svg v-else-if="panel.id === 'user-interface'" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect>
            <line x1="8" y1="21" x2="16" y2="21"></line>
            <line x1="12" y1="17" x2="12" y2="21"></line>
          </svg>
          <!-- 5. 词典管理 -->
          <svg v-else-if="panel.id === 'dictionary'" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path>
            <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path>
          </svg>
          <!-- 6. 软件更新 -->
          <svg v-else-if="panel.id === 'update'" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 12a9 9 0 0 1-9 9m9-9a9 9 0 0 0-9-9m9 9H3m9 9a9 9 0 0 1-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9" />
          </svg>
        </span>
        <span class="nav-label">{{ panel.label }}</span>
      </div>
      <div class="spacer" />
      <div class="version-tag" @click="activePanel = 'update'" title="点击进入软件更新">
        <span>NCBI BLAST Pro 2.1</span>
        <span class="check-update-link">检查更新</span>
      </div>
    </nav>

    <!-- 动态内容区域 -->
    <div class="settings-content scroll-y">
      <AITranslationPanel v-if="activePanel === 'ai-translation'" />
      <DatabasePanel v-if="activePanel === 'local-db'" />
      <SystemParamsPanel v-if="activePanel === 'system-params'" />
      <UserInterfacePanel v-if="activePanel === 'user-interface'" />
      <DictionaryPanel v-if="activePanel === 'dictionary'" />
      <UpdatePanel v-if="activePanel === 'update'" />
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
  padding: 10px 14px;
  margin-bottom: 4px;
  border-radius: 10px;
  cursor: pointer;
  color: #64748b;
  font-weight: 500;
  font-size: 0.9rem;
  transition: all 0.2s;
}

.settings-nav-item:hover {
  background: #f8fafc;
  color: #2563eb;
}

.settings-nav-item.active {
  background: #eff6ff;
  color: #2563eb;
  font-weight: 600;
}

.nav-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
}

.settings-content {
  flex: 1;
  overflow-y: auto;
  position: relative;
}

.spacer { flex: 1; }

.version-tag {
  font-size: 0.75rem;
  color: #94a3b8;
  padding: 10px;
  text-align: center;
  cursor: pointer;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  transition: background 0.15s;
}

.version-tag:hover {
  background: #f8fafc;
  color: #2563eb;
}

.check-update-link {
  font-size: 0.7rem;
  color: #3b82f6;
}

/* 兼容原有全局 CSS 变量 */
:root {
  --accent-blue: #2563eb;
}
</style>