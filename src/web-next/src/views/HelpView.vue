<script setup lang="ts">
/**
 * HelpView - 帮助中心页面
 * 从旧版 index.html #help-view 迁移
 * 双栏布局：左侧主题列表 + 右侧内容区
 */
import { ref, onMounted } from 'vue'
import { getBridge } from '../bridge/pyqt-bridge'

interface HelpTopic {
  id: string
  title: string
  category: string
}

const topics = ref<HelpTopic[]>([])
const activeTopic = ref<string>('')
const contentHtml = ref('')
const isLoading = ref(true)

onMounted(() => {
  loadTopics()
})

function loadTopics(): void {
  try {
    const bridge = getBridge()
    bridge.get_help_structure()
    // 结果将通过桥接回调填充 topics
    isLoading.value = false
  } catch (error) {
    console.warn('[Help] Bridge not ready:', error)
    isLoading.value = false
    // 提供示例数据用于开发
    topics.value = [
      { id: 'getting-started', title: '快速入门', category: '基础' },
      { id: 'blast-usage', title: 'BLAST 使用指南', category: '分析工具' },
      { id: 'node-studio', title: '节点工作台教程', category: '分析工具' },
      { id: 'tree-explorer', title: '进化树可视化', category: '分析工具' },
      { id: 'api-config', title: 'API 配置说明', category: '系统设置' },
      { id: 'faq', title: '常见问题', category: '帮助' }
    ]
  }
}

function selectTopic(topicId: string): void {
  activeTopic.value = topicId
  contentHtml.value = ''
  try {
    getBridge().get_help_content(topicId)
  } catch (error) {
    contentHtml.value = `<p style="color: #94a3b8;">内容加载中...</p>`
  }
}

/** 按 category 分组 */
function getCategories(): string[] {
  return [...new Set(topics.value.map(topicItem => topicItem.category))]
}
</script>

<template>
  <div class="help-view">
    <!-- 左侧主题列表 -->
    <aside class="help-sidebar">
      <div class="sidebar-header">
        <h3>📖 帮助中心</h3>
        <p class="subtitle">NCBI Bio-Station 指南</p>
      </div>
      <div class="topic-list">
        <div v-if="isLoading" class="loading-hint">正在加载手册...</div>
        <template v-else>
          <template v-for="cat in getCategories()" :key="cat">
            <div class="topic-category">{{ cat }}</div>
            <div
              v-for="topic in topics.filter(topicItem => topicItem.category === cat)"
              :key="topic.id"
              class="topic-item"
              :class="{ active: activeTopic === topic.id }"
              @click="selectTopic(topic.id)"
            >
              {{ topic.title }}
            </div>
          </template>
        </template>
      </div>
    </aside>

    <!-- 右侧内容区 -->
    <div class="help-content">
      <div v-if="!activeTopic" class="empty-state">
        <div class="empty-icon">📄</div>
        <h2>请从左侧选择一个主题开始阅读</h2>
        <p>您可以找到关于 BLAST 配置、数据库管理和系统设置的详细说明。</p>
      </div>
      <div v-else class="content-body" v-html="contentHtml" />
    </div>
  </div>
</template>

<style scoped>
.help-view {
  display: flex;
  height: 100%;
  background: #f8fafc;
}

.help-sidebar {
  width: 280px;
  min-width: 280px;
  background: white;
  border-right: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  
}

.sidebar-header {
  padding: 24px 20px;
  border-bottom: 1px solid var(--border-light);
}
.sidebar-header h3 { margin: 0; font-size: 1.1rem; color: #0f172a; }
.subtitle { font-size: 0.8rem; color: var(--text-muted); margin-top: 4px; }

.topic-list {
  flex: 1;
  overflow-y: auto;
  padding: 16px 12px;
}

.topic-category {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--text-muted);
  padding: 12px 12px 4px;
  font-weight: 600;
}

.topic-item {
  padding: 8px 12px;
  margin: 2px 0;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.875rem;
  color: var(--text-secondary);
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}
.topic-item:hover { background: #f1f5f9; color: var(--text-primary); }
.topic-item.active { background: rgba(59, 130, 246, 0.08); color: var(--accent-blue); font-weight: 600; }

.loading-hint { text-align: center; color: var(--text-muted); padding: 40px 0; font-size: 0.85rem; }

.help-content {
  flex: 1;
  overflow-y: auto;
  background: white;
  padding-top: 20px;
}

.empty-state {
  text-align: center;
  padding: 100px 40px;
  color: #cbd5e1;
}
.empty-icon { font-size: 3rem; margin-bottom: 24px; opacity: 0.3; }
.empty-state h2 { font-size: 1.2rem; color: #94a3b8; margin-bottom: 8px; }
.empty-state p { font-size: 0.9rem; color: #cbd5e1; }

.content-body {
  max-width: 850px;
  margin: 0 auto;
  padding: 40px 60px;
  line-height: 1.7;
  color: #334155;
  font-size: 0.95rem;
}
</style>