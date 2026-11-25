<script setup lang="ts">
/**
 * WorkbenchHubLayout - 多模块工作台可复用布局骨架
 * 统一封装顶栏标题/副标题、附加动作插槽、数量统计徽章、返回列表按钮、
 * 响应式工具卡片网格与具体工具工作区切换容器，消除跨工作台样板样式重复。
 */
import { computed } from 'vue'
import { useI18n } from '../../locales'

const { t } = useI18n()

const props = withDefaults(
  defineProps<{
    title: string
    subtitle: string
    active: boolean
    statLabel?: string
    statValue?: number | string
    backLabel?: string
    accent?: 'blue' | 'teal'
    gridMinWidth?: string
  }>(),
  {
    statLabel: '',
    statValue: '',
    backLabel: '',
    accent: 'blue',
    gridMinWidth: '300px',
  }
)

const resolvedStatLabel = computed(() => props.statLabel || t('common.available_tools'))
const resolvedBackLabel = computed(() => props.backLabel || t('common.back_to_list'))

const emit = defineEmits<{
  (e: 'back'): void
}>()
</script>

<template>
  <div class="hub-container" :class="`accent-${accent}`">
    <header class="hub-header">
      <div class="header-content">
        <h1>{{ title }}</h1>
        <p>{{ subtitle }}</p>
      </div>

      <div class="header-actions-bar">
        <slot name="header-extra" />

        <div v-if="!active && statValue !== ''" class="header-stats">
          <div class="stat-badge">
            <span class="label">{{ resolvedStatLabel }}</span>
            <span class="value">{{ statValue }}</span>
          </div>
        </div>

        <template v-else-if="active">
          <slot name="header-active-actions" />
          <button type="button" class="back-btn" @click="emit('back')">
            &larr; {{ resolvedBackLabel }}
          </button>
        </template>
      </div>
    </header>

    <div class="hub-content">
      <div
        v-if="!active"
        class="tools-grid"
        :style="{ gridTemplateColumns: `repeat(auto-fill, minmax(${gridMinWidth}, 1fr))` }"
      >
        <slot name="grid" />
      </div>

      <div v-else class="tool-workspace">
        <slot name="workspace" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.hub-container {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #f8fafc;
}

.hub-header {
  padding: 12px 24px;
  background: #ffffff;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.header-content h1 {
  margin: 0;
  font-size: 18px;
  color: #1e293b;
  letter-spacing: -0.4px;
}

.header-content p {
  margin: 2px 0 0;
  color: #64748b;
  font-size: 12px;
}

.header-actions-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.stat-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  background: #f1f5f9;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
}

.stat-badge .label {
  color: #64748b;
}

.accent-blue .stat-badge .value {
  color: #2563eb;
  font-weight: 700;
}

.accent-teal .stat-badge .value {
  color: #0f766e;
  font-weight: 700;
}

.back-btn {
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  padding: 6px 14px;
  border-radius: 6px;
  color: #334155;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  flex-shrink: 0;
  transition: all 0.2s;
}

.back-btn:hover {
  background: #e2e8f0;
  color: #0f172a;
}

.hub-content {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.tools-grid {
  flex: 1;
  min-height: 0;
  display: grid;
  gap: 16px;
  padding: 30px 40px;
  overflow-y: auto;
  align-content: start;
}

.tool-workspace {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 0;
  overflow-y: auto;
}
</style>
