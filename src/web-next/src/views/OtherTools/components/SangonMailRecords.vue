<script setup lang="ts">
/**
 * SangonMailRecords - 生工通知邮件记录折叠面板组件
 * 职责：
 * 1. 默认收起作为辅助核对与排查视图，避免与主订单列表产生视觉竞争；
 * 2. 对单次扫描缓存的全量邮件记录执行纯前端分类筛选（全部 / 新建与待建 / 已有目录 / 非测序 / 已清理跳过）与纯前端分页；
 * 3. 切换筛选或翻页均不重新连接 IMAP 邮箱，消除筛选副作用与等待延迟。
 */
import { ref, computed, watch } from 'vue'
import PaginationBar from './PaginationBar.vue'
import type { ScannedMailItem, MailScanSummary, MailDedupStatus } from '../sangonTypes'

type RecordFilterKey = 'all' | 'fresh' | 'existing' | 'non_sequencing' | 'history_skipped'

const props = withDefaults(
  defineProps<{
    mails: ScannedMailItem[]
    summary: MailScanSummary
    scanning?: boolean
    busy?: boolean
    hasScanned?: boolean
  }>(),
  {
    scanning: false,
    busy: false,
    hasScanned: false
  }
)

const emit = defineEmits<{
  (e: 'scan'): void
  (e: 'initOrder', mail: ScannedMailItem): void
}>()

const expanded = ref(false)
const activeFilter = ref<RecordFilterKey>('all')
const page = ref(1)
const pageSize = ref(10)

const filterTabs = computed(() => {
  const all = props.mails.length
  let fresh = 0
  let existing = 0
  let nonSeq = 0
  let skipped = 0
  for (const m of props.mails) {
    if (m.dedup_status === 'created' || m.dedup_status === 'new') fresh += 1
    else if (m.dedup_status === 'existing') existing += 1
    else if (m.dedup_status === 'non_sequencing') nonSeq += 1
    else if (m.dedup_status === 'history_skipped') skipped += 1
  }
  return [
    { key: 'all' as RecordFilterKey, label: '全部', count: all },
    { key: 'fresh' as RecordFilterKey, label: '新建 / 待建', count: fresh },
    { key: 'existing' as RecordFilterKey, label: '已有目录', count: existing },
    { key: 'non_sequencing' as RecordFilterKey, label: '非测序通知', count: nonSeq },
    { key: 'history_skipped' as RecordFilterKey, label: '已清理跳过', count: skipped }
  ]
})

const filteredMails = computed(() => {
  const f = activeFilter.value
  if (f === 'all') return props.mails
  if (f === 'fresh') {
    return props.mails.filter(m => m.dedup_status === 'created' || m.dedup_status === 'new')
  }
  return props.mails.filter(m => m.dedup_status === f)
})

const pagedMails = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredMails.value.slice(start, start + pageSize.value)
})

watch([activeFilter, () => props.mails.length], () => {
  page.value = 1
})

function dedupStatusLabel(st: MailDedupStatus): string {
  const map: Record<MailDedupStatus, string> = {
    created: '本次新建',
    existing: '目录已存在',
    history_skipped: '已清理跳过',
    new: '待建目录',
    non_sequencing: '非测序邮件'
  }
  return map[st] || st
}

function handleToggle(): void {
  expanded.value = !expanded.value
  if (expanded.value && !props.hasScanned && !props.scanning) {
    emit('scan')
  }
}

defineExpose({
  expand: () => {
    expanded.value = true
  },
  collapse: () => {
    expanded.value = false
  }
})
</script>

<template>
  <div class="mail-records-box">
    <div class="records-header" @click="handleToggle">
      <div class="header-left">
        <span class="fold-arrow">{{ expanded ? '▾' : '▸' }}</span>
        <h4>生工通知邮件记录</h4>
        <template v-if="hasScanned">
          <span class="meta-pill">共 {{ mails.length }} 条（原始 {{ summary.rawTotal }} 封）</span>
          <span v-if="summary.newCount > 0" class="meta-pill fresh">新订单 {{ summary.newCount }}</span>
          <span v-if="summary.dedupRemoved > 0" class="meta-pill">合并重复 {{ summary.dedupRemoved }}</span>
          <span v-if="summary.nonSequencingCount > 0" class="meta-pill">非测序 {{ summary.nonSequencingCount }}</span>
          <span v-if="summary.skippedKnown > 0" class="meta-pill warn">清理跳过 {{ summary.skippedKnown }}</span>
        </template>
        <span v-else class="meta-hint">默认收起，展开可核对原始通知邮件、非测序邮件或手动补建目录</span>
      </div>
      <div class="header-right" @click.stop>
        <button
          v-if="expanded"
          class="btn-mini"
          :disabled="scanning || busy"
          @click="emit('scan')"
        >
          {{ scanning ? '同步中...' : '重新同步邮件' }}
        </button>
        <button class="btn-mini" @click="handleToggle">
          {{ expanded ? '收起' : '展开查看' }}
        </button>
      </div>
    </div>

    <div v-if="expanded" class="records-body">
      <div class="filter-bar">
        <div class="seg-group">
          <button
            v-for="tab in filterTabs"
            :key="tab.key"
            :class="['seg-btn', { active: activeFilter === tab.key }]"
            @click="activeFilter = tab.key"
          >
            <span>{{ tab.label }}</span>
            <span class="seg-count">{{ tab.count }}</span>
          </button>
        </div>
        <span class="filter-tip">本地缓存即时筛选，切换不重连邮箱</span>
      </div>

      <table class="data-table">
        <thead>
          <tr>
            <th>订单目录</th>
            <th>订单号</th>
            <th>邮件主题</th>
            <th>时间</th>
            <th>识别状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="m in pagedMails" :key="`${m.seq}-${m.order_no}-${m.subject}`">
            <td class="mono-cell">{{ m.dir_name || '-' }}</td>
            <td class="bold-cell">{{ m.order_no || '-' }}</td>
            <td>
              <span>{{ m.subject }}</span>
              <span v-if="m.duplicate_count > 1" class="dup-count-tag">合并 {{ m.duplicate_count }} 封</span>
            </td>
            <td>{{ m.date }}</td>
            <td>
              <span
                :class="['status-pill', m.dedup_status]"
                :title="m.dedup_status === 'non_sequencing' && m.legacy_dir_exists ? '非测序通知邮件；本地存在历史遗留同名目录，可按需在订单列表中清理' : ''"
              >
                {{ dedupStatusLabel(m.dedup_status) }}
              </span>
            </td>
            <td class="actions-cell">
              <button
                v-if="!m.dir_ready && m.dir_name && m.dedup_status !== 'non_sequencing'"
                class="btn-mini primary"
                :disabled="busy"
                @click="emit('initOrder', m)"
              >
                建目录
              </button>
              <a
                v-if="m.download_url"
                :href="m.download_url"
                target="_blank"
                rel="noopener noreferrer"
                class="link-btn"
              >
                打开下载页
              </a>
              <span v-if="m.dir_ready && !m.download_url">-</span>
              <span v-else-if="m.dedup_status === 'non_sequencing'">-</span>
            </td>
          </tr>
          <tr v-if="pagedMails.length === 0">
            <td colspan="6" class="empty-cell">
              <span v-if="scanning">正在同步生工通知邮件...</span>
              <template v-else-if="hasScanned && activeFilter !== 'all'">
                <span>当前分类下无邮件记录</span>
                <button class="btn-mini primary inline-btn" @click="activeFilter = 'all'">查看全部 ({{ mails.length }})</button>
              </template>
              <span v-else>暂无生工通知邮件记录</span>
            </td>
          </tr>
        </tbody>
      </table>

      <PaginationBar
        v-if="filteredMails.length > 0"
        v-model:page="page"
        v-model:page-size="pageSize"
        :total="filteredMails.length"
        :page-size-options="[5, 10, 20, 50]"
      />
    </div>
  </div>
</template>

<style scoped>
.mail-records-box {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  overflow: hidden;
}

.records-header {
  padding: 10px 16px;
  background: #f8fafc;
  display: flex;
  justify-content: space-between;
  align-items: center;
  cursor: pointer;
  user-select: none;
  gap: 12px;
}

.records-header:hover {
  background: #f1f5f9;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.fold-arrow {
  font-size: 12px;
  color: #64748b;
  width: 14px;
}

.records-header h4 {
  margin: 0;
  font-size: 13px;
  color: #1e293b;
}

.meta-hint {
  font-size: 12px;
  color: #64748b;
}

.meta-pill {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
  background: #f1f5f9;
  color: #475569;
  border: 1px solid #cbd5e1;
}

.meta-pill.fresh {
  background: #ecfdf5;
  color: #047857;
  border-color: #6ee7b7;
}

.meta-pill.warn {
  background: #fffbeb;
  color: #b45309;
  border-color: #fde68a;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.records-body {
  border-top: 1px solid #e2e8f0;
}

.filter-bar {
  padding: 8px 16px;
  background: #ffffff;
  border-bottom: 1px solid #f1f5f9;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.seg-group {
  display: inline-flex;
  background: #f1f5f9;
  padding: 3px;
  border-radius: 7px;
  gap: 2px;
  flex-wrap: wrap;
}

.seg-btn {
  border: none;
  background: transparent;
  color: #475569;
  font-size: 12px;
  font-weight: 500;
  padding: 4px 10px;
  border-radius: 5px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.seg-btn.active {
  background: white;
  color: #0f172a;
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
}

.seg-count {
  font-size: 11px;
  color: #64748b;
  background: rgba(148, 163, 184, 0.2);
  padding: 0 5px;
  border-radius: 999px;
}

.seg-btn.active .seg-count {
  background: #eff6ff;
  color: #2563eb;
}

.filter-tip {
  font-size: 11px;
  color: #94a3b8;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.data-table th {
  text-align: left;
  padding: 9px 12px;
  background: #f8fafc;
  color: #475569;
  font-weight: 600;
  border-bottom: 1px solid #e2e8f0;
  white-space: nowrap;
}

.data-table td {
  padding: 8px 12px;
  border-bottom: 1px solid #f1f5f9;
  color: #334155;
}

.mono-cell {
  font-family: Consolas, monospace;
  color: #2563eb;
}

.bold-cell {
  font-weight: 600;
}

.dup-count-tag {
  margin-left: 6px;
  background: #f1f5f9;
  color: #475569;
  border: 1px solid #cbd5e1;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
}

.status-pill {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
}

.status-pill.created { background: #ecfdf5; color: #047857; border: 1px solid #6ee7b7; }
.status-pill.new { background: #fffbeb; color: #b45309; border: 1px solid #fcd34d; }
.status-pill.existing { background: #f8fafc; color: #475569; border: 1px solid #cbd5e1; }
.status-pill.history_skipped { background: #f5f3ff; color: #6d28d9; border: 1px solid #ddd6fe; }
.status-pill.non_sequencing { background: #f1f5f9; color: #64748b; border: 1px solid #cbd5e1; }

.actions-cell {
  display: flex;
  gap: 6px;
  align-items: center;
}

.btn-mini {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  padding: 4px 10px;
  border-radius: 5px;
  font-size: 11px;
  cursor: pointer;
  color: #334155;
}

.btn-mini.primary {
  background: #eff6ff;
  color: #2563eb;
  border-color: #93c5fd;
}

.btn-mini:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.link-btn {
  color: #2563eb;
  text-decoration: none;
  font-weight: 500;
}

.inline-btn {
  margin-left: 8px;
}

.empty-cell {
  text-align: center;
  color: #94a3b8;
  padding: 20px !important;
}
</style>
