<script setup lang="ts">
/**
 * OtherToolsView - 其他功能工作台入口
 * 职责：集成两个端到端自动化生物信息学流水线模块：
 *   1. 邮件自动收件 → 注释 → Word 报告 → SMTP 回传
 *   2. 生工 16S 测序结果自动化 BLAST 与导出流程
 * 遵循模块化设计，每个工具为一个独立的子组件，视觉风格对齐 AnalysisView.vue。
 */
import { defineAsyncComponent, ref } from 'vue'
import AsyncModuleLoading from '../components/common/AsyncModuleLoading.vue'
import AsyncModuleError from '../components/common/AsyncModuleError.vue'
import WorkbenchHubLayout from '../components/layout/WorkbenchHubLayout.vue'

const asyncOpts = {
  loadingComponent: AsyncModuleLoading,
  errorComponent: AsyncModuleError,
  delay: 150,
}

const MailAutoPipelineModule = defineAsyncComponent({
  ...asyncOpts,
  loader: () => import('./OtherTools/modules/MailAutoPipelineModule.vue'),
})
const Sangon16SPipelineModule = defineAsyncComponent({
  ...asyncOpts,
  loader: () => import('./OtherTools/modules/Sangon16SPipelineModule.vue'),
})

interface OtherToolItem {
  id: 'mail_pipeline' | 'sangon_16s'
  title: string
  description: string
  iconType: 'mail_pipeline' | 'sangon_16s'
  status: 'ready' | 'beta' | 'coming_soon'
  badgeText?: string
}

const tools = ref<OtherToolItem[]>([
  {
    id: 'mail_pipeline',
    title: '邮件自动收件 → 注释 → Word 报告 → SMTP 回传',
    description: '接收邮件中的 FASTA 附件，完成基因组注释与 Word 报告生成，打包后邮件回传。',
    iconType: 'mail_pipeline',
    status: 'ready'
  },
  {
    id: 'sangon_16s',
    title: '生工 16S 测序结果自动化 BLAST 与导出流程',
    description: '扫描生工通知邮件建立订单目录，解压提取 *.1.fasta 执行 16S BLAST 比对并导出 CSV。',
    iconType: 'sangon_16s',
    status: 'ready'
  }
])

const activeTool = ref<'mail_pipeline' | 'sangon_16s' | null>(null)

function selectTool(tool: OtherToolItem): void {
  if (tool.status === 'coming_soon') return
  activeTool.value = tool.id
}
</script>

<template>
  <WorkbenchHubLayout
    title="其他功能"
    subtitle="邮件自动注释回传与生工 16S 测序自动比对导出。"
    :active="Boolean(activeTool)"
    stat-label="工具数"
    :stat-value="tools.length"
    back-label="返回工具列表"
    accent="blue"
    grid-min-width="420px"
    @back="activeTool = null"
  >
    <template #header-active-actions>
      <div class="tool-switcher">
        <button
          v-for="item in tools"
          :key="item.id"
          type="button"
          class="switch-tab"
          :class="{ active: activeTool === item.id }"
          @click="activeTool = item.id"
        >
          {{ item.id === 'mail_pipeline' ? '邮件注释回传' : '生工 16S 比对' }}
        </button>
      </div>
    </template>

    <template #grid>
      <button
        v-for="tool in tools"
        :key="tool.id"
        type="button"
        :class="['tool-card', tool.status]"
        :disabled="tool.status === 'coming_soon'"
        @click="selectTool(tool)"
      >
        <div class="tool-icon-mini">
          <!-- 矢量 SVG 图标：严禁 Emoji -->
          <svg
            v-if="tool.iconType === 'mail_pipeline'"
            width="22"
            height="22"
            viewBox="0 0 24 24"
            fill="none"
            stroke="#2563eb"
            stroke-width="2.2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <rect x="2" y="4" width="20" height="16" rx="2" />
            <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
            <path d="M16 19h6" />
            <path d="m19 16 3 3-3 3" />
          </svg>

          <svg
            v-else-if="tool.iconType === 'sangon_16s'"
            width="22"
            height="22"
            viewBox="0 0 24 24"
            fill="none"
            stroke="#059669"
            stroke-width="2.2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M2 15c6.667-6 13.333 0 20-6" />
            <path d="M9 22c1.798-1.998 2.518-3.995 2.807-5.993" />
            <path d="M15 2c-1.798 1.998-2.518 3.995-2.807 5.993" />
            <circle cx="18" cy="18" r="3" />
            <path d="m20.2 20.2 1.8 1.8" />
          </svg>
        </div>

        <div class="tool-body">
          <div class="tool-title-row">
            <h3>{{ tool.title }}</h3>
            <span v-if="tool.badgeText" class="pipeline-tag">{{ tool.badgeText }}</span>
          </div>
          <p class="tool-desc">{{ tool.description }}</p>
        </div>
      </button>
    </template>

    <template #workspace>
      <MailAutoPipelineModule v-if="activeTool === 'mail_pipeline'" />
      <Sangon16SPipelineModule v-else-if="activeTool === 'sangon_16s'" />
    </template>
  </WorkbenchHubLayout>
</template>

<style scoped>
.tool-switcher {
  display: flex;
  background: #f1f5f9;
  padding: 3px;
  border-radius: 8px;
  gap: 4px;
}

.switch-tab {
  border: none;
  background: transparent;
  color: #64748b;
  font-size: 12px;
  font-weight: 600;
  padding: 5px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
}

.switch-tab:hover {
  color: #1e293b;
}

.switch-tab.active {
  background: white;
  color: #2563eb;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
}

.tool-card {
  width: 100%;
  text-align: left;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 18px;
  cursor: pointer;
  transition: all 0.2s ease;
  display: flex;
  align-items: flex-start;
  gap: 16px;
  position: relative;
}

.tool-card:hover:not(.coming_soon) {
  border-color: #3b82f6;
  background: #f0f7ff;
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.08);
  transform: translateY(-2px);
}

.tool-icon-mini {
  width: 44px;
  height: 44px;
  background: #f8fafc;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border: 1px solid #e2e8f0;
}

.tool-body {
  flex: 1;
  min-width: 0;
}

.tool-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.tool-title-row h3 {
  margin: 0;
  font-size: 15px;
  color: #1e293b;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.pipeline-tag {
  font-size: 10px;
  padding: 2px 7px;
  border-radius: 999px;
  background: #eff6ff;
  color: #2563eb;
  font-weight: 600;
  flex-shrink: 0;
}

.tool-desc {
  margin: 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>

