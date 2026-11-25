<script setup lang="ts">
/**
 * HelpView - 帮助中心页面
 * 双栏布局：左侧支持即时检索的主题导航 + 右侧带章节大纲锚点（TOC）的安全 Markdown 渲染区
 */
import { computed, nextTick, onMounted, ref } from 'vue'
import { getBridge } from '../bridge'
import {
  extractMarkdownHeadings,
  markdownToHtml,
  safeSetHTML,
  type MarkdownHeading,
} from '../utils/safeHtml'
import { shouldSubmitOnEnter } from '../utils/ime'

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
const searchQuery = ref('')
const activeTopic = ref<string>('')
const isLoading = ref(true)
const isContentLoading = ref(false)
const contentBodyRef = ref<HTMLElement | null>(null)
const contentHeadings = ref<MarkdownHeading[]>([])
const activeHeadingId = ref<string>('')

const filteredTopics = computed<HelpTopic[]>(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return topics.value
  return topics.value.filter(
    (item) =>
      item.title.toLowerCase().includes(q) ||
      item.category.toLowerCase().includes(q) ||
      item.id.toLowerCase().includes(q)
  )
})

const visibleCategories = computed<string[]>(() => [
  ...new Set(filteredTopics.value.map((topicItem) => topicItem.category)),
])

const tocItems = computed<MarkdownHeading[]>(() => {
  const sub = contentHeadings.value.filter((h) => h.level >= 2)
  return sub.length >= 2 ? sub : contentHeadings.value
})

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
  contentHeadings.value = extractMarkdownHeadings(markdown)
  activeHeadingId.value = contentHeadings.value[0]?.id ?? ''
  await nextTick()
  if (!contentBodyRef.value) return
  const html = markdownToHtml(markdown)
  safeSetHTML(contentBodyRef.value, html)
}

function jumpToHeading(headingId: string): void {
  activeHeadingId.value = headingId
  const container = contentBodyRef.value
  if (!container) return
  const target = container.querySelector<HTMLElement>(`#${headingId}`)
  if (target && typeof target.scrollIntoView === 'function') {
    target.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

function handleSearchKeydown(event: KeyboardEvent): void {
  if (!shouldSubmitOnEnter(event)) return
  if (filteredTopics.value.length > 0) {
    event.preventDefault()
    void selectTopic(filteredTopics.value[0]!.id)
  }
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
        <div class="sidebar-search">
          <input
            v-model="searchQuery"
            type="search"
            class="help-search-input"
            placeholder="筛选帮助主题或分类..."
            aria-label="筛选帮助主题"
            @keydown="handleSearchKeydown"
          />
          <button
            v-if="searchQuery"
            type="button"
            class="search-clear-btn"
            aria-label="清空搜索词"
            @click="searchQuery = ''"
          >
            清空
          </button>
        </div>
      </div>

      <div class="topic-list">
        <div v-if="isLoading" class="loading-hint">正在加载手册目录...</div>
        <div v-else-if="filteredTopics.length === 0" class="loading-hint">
          未找到与 "{{ searchQuery }}" 匹配的帮助主题
        </div>
        <template v-else>
          <template v-for="cat in visibleCategories" :key="cat">
            <div class="topic-category">{{ cat }}</div>
            <button
              v-for="topic in filteredTopics.filter((topicItem) => topicItem.category === cat)"
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
      <div v-else class="content-shell">
        <nav v-if="tocItems.length >= 2" class="toc-bar" aria-label="文档章节目录">
          <span class="toc-label">本页目录</span>
          <div class="toc-links">
            <button
              v-for="heading in tocItems"
              :key="heading.id"
              type="button"
              class="toc-btn"
              :class="{ active: activeHeadingId === heading.id, sub: heading.level >= 3 }"
              @click="jumpToHeading(heading.id)"
            >
              {{ heading.text }}
            </button>
          </div>
        </nav>
        <article ref="contentBodyRef" class="content-body selectable" />
      </div>
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
  padding: 18px 16px 14px;
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

.sidebar-search {
  margin-top: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.help-search-input {
  flex: 1;
  min-width: 0;
  height: 32px;
  padding: 0 10px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  font-size: 0.82rem;
  background: #f8fafc;
  color: var(--text-primary);
}

.help-search-input:focus {
  outline: none;
  border-color: var(--accent-blue);
  background: #ffffff;
}

.search-clear-btn {
  padding: 4px 8px;
  font-size: 0.75rem;
  border-radius: var(--radius-sm);
  background: #f1f5f9;
  color: var(--text-secondary);
  border: 1px solid var(--border-color);
}

.search-clear-btn:hover {
  background: #e2e8f0;
  color: var(--text-primary);
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
  padding: 40px 12px;
  font-size: 0.875rem;
}

.help-content {
  flex: 1;
  overflow-y: auto;
  background: var(--bg-card);
}

.content-shell {
  max-width: 900px;
  margin: 0 auto;
}

.toc-bar {
  position: sticky;
  top: 0;
  z-index: 2;
  background: rgba(248, 250, 252, 0.96);
  border-bottom: 1px solid var(--border-color);
  padding: 10px 48px;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.toc-label {
  font-size: 0.74rem;
  font-weight: 700;
  color: var(--text-muted);
  flex-shrink: 0;
}

.toc-links {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.toc-btn {
  padding: 3px 9px;
  font-size: 0.76rem;
  border-radius: 999px;
  background: #ffffff;
  color: var(--text-secondary);
  border: 1px solid var(--border-color);
  transition: background-color 0.15s, color 0.15s, border-color 0.15s;
}

.toc-btn.sub {
  font-size: 0.72rem;
  color: var(--text-muted);
}

.toc-btn:hover,
.toc-btn.active {
  background: #eff6ff;
  color: var(--accent-blue);
  border-color: #93c5fd;
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
  padding: 28px 48px 48px;
  line-height: 1.75;
  color: var(--text-primary);
  font-size: 0.95rem;
}

.content-body :deep(h1) {
  font-size: 1.5rem;
  margin-bottom: 16px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border-color);
  scroll-margin-top: 64px;
}

.content-body :deep(h2) {
  font-size: 1.2rem;
  margin: 24px 0 10px;
  scroll-margin-top: 64px;
}

.content-body :deep(h3),
.content-body :deep(h4) {
  font-size: 1.02rem;
  margin: 18px 0 8px;
  scroll-margin-top: 64px;
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
