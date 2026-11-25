<script setup lang="ts">
/**
 * HelpView - 帮助中心页面
 * 双栏布局：左侧主题导航 + 右侧安全 Markdown 渲染区
 */
import { ref, onMounted, nextTick } from 'vue'
import { getBridge } from '../bridge'
import { markdownToHtml, safeSetHTML } from '../utils/safeHtml'

interface HelpTopic {
  id: string
  title: string
  category: string
}

interface HelpGroupResponse {
  category: string
  topics: Array<{ id: string; title: string }>
}

const topics = ref<HelpTopic[]>([])
const activeTopic = ref<string>('')
const isLoading = ref(true)
const isContentLoading = ref(false)
const contentBodyRef = ref<HTMLElement | null>(null)

function normalizeTopics(raw: unknown): HelpTopic[] {
  if (!Array.isArray(raw)) return []
  const flattened: HelpTopic[] = []
  for (const item of raw as Array<HelpGroupResponse | HelpTopic>) {
    if ('topics' in item && Array.isArray(item.topics)) {
      for (const child of item.topics) {
        if (child?.id && child?.title) {
          flattened.push({ id: child.id, title: child.title, category: item.category || '帮助' })
        }
      }
    } else if ('id' in item && item.id && item.title) {
      flattened.push({ id: item.id, title: item.title, category: item.category || '帮助' })
    }
  }
  return flattened
}

async function renderMarkdownSafely(markdown: string): Promise<void> {
  await nextTick()
  if (!contentBodyRef.value) return
  const html = markdownToHtml(markdown)
  safeSetHTML(contentBodyRef.value, html)
}

async function loadTopics(): Promise<void> {
  isLoading.value = true
  try {
    const res = await getBridge().get_help_structure()
    const parsed = normalizeTopics(res)
    if (parsed.length > 0) {
      topics.value = parsed
      return
    }
  } catch (error) {
    console.warn('[Help] 加载帮助目录失败，回退默认索引:', error)
  } finally {
    isLoading.value = false
  }

  topics.value = [
    { id: 'quick_start', title: '快速入门', category: '入门指南' },
    { id: 'local_blast', title: '本地 BLAST', category: '核心功能' },
    { id: 'database_manager', title: '数据库管理', category: '核心功能' },
    { id: 'history', title: '任务历史', category: '核心功能' },
    { id: 'settings', title: '参数设置', category: '高级设置' },
    { id: 'translation_debugger', title: '翻译调试器', category: '高级设置' },
  ]
}

async function selectTopic(topicId: string): Promise<void> {
  activeTopic.value = topicId
  isContentLoading.value = true
  try {
    const res = await getBridge().get_help_content(topicId)
    const rawContent =
      typeof res === 'string'
        ? res
        : typeof res?.content === 'string'
          ? res.content
          : '# 提示\n\n当前主题暂无可用内容。'
    isContentLoading.value = false
    await renderMarkdownSafely(rawContent)
  } catch (error) {
    console.warn('[Help] 加载帮助正文失败:', error)
    isContentLoading.value = false
    await renderMarkdownSafely('# 加载失败\n\n暂时无法读取该帮助文档，请确认本地后端服务已启动。')
  }
}

function getCategories(): string[] {
  return [...new Set(topics.value.map((topicItem) => topicItem.category))]
}

onMounted(async () => {
  await loadTopics()
  if (topics.value.length > 0 && !activeTopic.value) {
    await selectTopic(topics.value[0]!.id)
  }
})
</script>

<template>
  <div class="help-view">
    <aside class="help-sidebar" aria-label="帮助主题目录">
      <div class="sidebar-header">
        <h2>帮助中心</h2>
        <p class="subtitle">NCBI Bio-Station 使用手册</p>
      </div>
      <div class="topic-list">
        <div v-if="isLoading" class="loading-hint">正在加载手册目录...</div>
        <template v-else>
          <template v-for="cat in getCategories()" :key="cat">
            <div class="topic-category">{{ cat }}</div>
            <button
              v-for="topic in topics.filter((topicItem) => topicItem.category === cat)"
              :key="topic.id"
              type="button"
              class="topic-item"
              :class="{ active: activeTopic === topic.id }"
              :aria-current="activeTopic === topic.id ? 'page' : undefined"
              @click="selectTopic(topic.id)"
            >
              {{ topic.title }}
            </button>
          </template>
        </template>
      </div>
    </aside>

    <section class="help-content" aria-label="帮助文档正文">
      <div v-if="!activeTopic" class="empty-state">
        <svg class="empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
          <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
          <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
        </svg>
        <h2>请从左侧选择一个主题开始阅读</h2>
        <p>您可以查阅 BLAST 配置、数据库管理、参数设置与工作流说明。</p>
      </div>
      <div v-else-if="isContentLoading" class="loading-hint">正在读取文档内容...</div>
      <article v-else ref="contentBodyRef" class="content-body selectable" />
    </section>
  </div>
</template>

<style scoped>
.help-view {
  display: flex;
  height: 100%;
  background: var(--bg-page);
}

.help-sidebar {
  width: 280px;
  min-width: 280px;
  background: var(--bg-card);
  border-right: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
}

.sidebar-header {
  padding: 20px;
  border-bottom: 1px solid var(--border-light);
}

.sidebar-header h2 {
  margin: 0;
  font-size: 1.05rem;
  color: var(--text-primary);
}

.subtitle {
  font-size: 0.8rem;
  color: var(--text-secondary);
  margin-top: 4px;
}

.topic-list {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

.topic-category {
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--text-muted);
  padding: 12px 10px 4px;
  font-weight: 600;
}

.topic-item {
  width: 100%;
  text-align: left;
  background: transparent;
  padding: 8px 12px;
  margin: 2px 0;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: 0.875rem;
  color: var(--text-secondary);
  transition: background-color 0.15s, color 0.15s;
}

.topic-item:hover {
  background: #f1f5f9;
  color: var(--text-primary);
}

.topic-item.active {
  background: rgba(59, 130, 246, 0.1);
  color: var(--accent-blue);
  font-weight: 600;
}

.topic-item:focus-visible {
  outline: 2px solid var(--accent-blue);
  outline-offset: -2px;
}

.loading-hint {
  text-align: center;
  color: var(--text-secondary);
  padding: 40px 0;
  font-size: 0.875rem;
}

.help-content {
  flex: 1;
  overflow-y: auto;
  background: var(--bg-card);
}

.empty-state {
  text-align: center;
  padding: 80px 40px;
  color: var(--text-secondary);
}

.empty-icon {
  width: 48px;
  height: 48px;
  margin: 0 auto 16px;
  color: var(--text-muted);
}

.empty-state h2 {
  font-size: 1.15rem;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.empty-state p {
  font-size: 0.9rem;
  color: var(--text-secondary);
}

.content-body {
  max-width: 860px;
  margin: 0 auto;
  padding: 32px 48px 48px;
  line-height: 1.75;
  color: var(--text-primary);
  font-size: 0.95rem;
}

.content-body :deep(h1) {
  font-size: 1.5rem;
  margin-bottom: 16px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border-color);
}

.content-body :deep(h2) {
  font-size: 1.2rem;
  margin: 24px 0 10px;
}

.content-body :deep(h3) {
  font-size: 1.02rem;
  margin: 18px 0 8px;
}

.content-body :deep(p) {
  margin-bottom: 12px;
}

.content-body :deep(ul),
.content-body :deep(ol) {
  margin: 0 0 14px 22px;
}

.content-body :deep(li) {
  margin-bottom: 6px;
}

.content-body :deep(code) {
  background: #f1f5f9;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: 'Cascadia Code', Consolas, monospace;
  font-size: 0.85em;
}

.content-body :deep(pre) {
  background: #0f172a;
  color: #e2e8f0;
  padding: 14px 16px;
  border-radius: var(--radius-md);
  overflow-x: auto;
  margin-bottom: 16px;
}

.content-body :deep(pre code) {
  background: transparent;
  padding: 0;
  color: inherit;
}

.content-body :deep(blockquote) {
  border-left: 3px solid var(--accent-blue);
  background: #f8fafc;
  padding: 10px 14px;
  margin: 12px 0;
  color: var(--text-secondary);
}
</style>
