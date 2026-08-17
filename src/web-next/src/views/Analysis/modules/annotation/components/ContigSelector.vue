<script setup lang="ts">
/**
 * ContigSelector - 多序列 FASTA 交互式 Contig 选择与筛选组件
 */
import { ref, computed, watch } from 'vue';
import type { ContigMetaItem } from '../types';

const props = defineProps<{
  contigs: ContigMetaItem[];
  totalLength: number;
  overallGc: number;
}>();

const emit = defineEmits<{
  (e: 'update:selection', selectedIds: string[]): void;
}>();

// 选中的 Contig ID 集合
const selectedIds = ref<Set<string>>(new Set());

// 搜索关键词
const searchQuery = ref<string>('');

// 记录上一次点击的索引（用于 Shift 范围选择）
const lastSelectedIndex = ref<number | null>(null);

// 初始化：默认全选
watch(
  () => props.contigs,
  (newContigs) => {
    if (newContigs && newContigs.length > 0) {
      selectedIds.value = new Set(newContigs.map(c => c.id));
      emitSelected();
    } else {
      selectedIds.value.clear();
      emitSelected();
    }
  },
  { immediate: true }
);

function emitSelected() {
  emit('update:selection', Array.from(selectedIds.value));
}

// 过滤后的列表
const filteredContigs = computed(() => {
  if (!searchQuery.value.trim()) {
    return props.contigs;
  }
  const q = searchQuery.value.toLowerCase().trim();
  return props.contigs.filter(c => 
    c.id.toLowerCase().includes(q) || (c.description && c.description.toLowerCase().includes(q))
  );
});

// 最大单条长度（用于进度条百分比）
const maxContigLen = computed(() => {
  if (props.contigs.length === 0) return 1;
  return Math.max(...props.contigs.map(c => c.length_bp));
});

// 统计信息
const selectedStats = computed(() => {
  const count = selectedIds.value.size;
  let len = 0;
  props.contigs.forEach(c => {
    if (selectedIds.value.has(c.id)) {
      len += c.length_bp;
    }
  });
  const pct = props.totalLength > 0 ? (len / props.totalLength * 100.0) : 0.0;
  return {
    count,
    length: len,
    lengthPct: pct.toFixed(1)
  };
});

// 切换单条选择
function toggleSelect(id: string, event?: MouseEvent, index?: number) {
  if (event && event.shiftKey && lastSelectedIndex.value !== null && index !== undefined) {
    // Shift 范围连选
    const start = Math.min(lastSelectedIndex.value, index);
    const end = Math.max(lastSelectedIndex.value, index);
    const shouldSelect = !selectedIds.value.has(id);
    for (let i = start; i <= end; i++) {
      const targetItem = filteredContigs.value[i];
      if (targetItem) {
        if (shouldSelect) {
          selectedIds.value.add(targetItem.id);
        } else {
          selectedIds.value.delete(targetItem.id);
        }
      }
    }
  } else {
    if (selectedIds.value.has(id)) {
      selectedIds.value.delete(id);
    } else {
      selectedIds.value.add(id);
    }
  }
  if (index !== undefined) {
    lastSelectedIndex.value = index;
  }
  emitSelected();
}

// 全选
function selectAll() {
  selectedIds.value = new Set(props.contigs.map(c => c.id));
  emitSelected();
}

// 全不选
function deselectAll() {
  selectedIds.value.clear();
  emitSelected();
}

// 反选
function invertSelection() {
  const newSet = new Set<string>();
  props.contigs.forEach(c => {
    if (!selectedIds.value.has(c.id)) {
      newSet.add(c.id);
    }
  });
  selectedIds.value = newSet;
  emitSelected();
}

// 快捷筛选：按长度阈值
function filterByMinLength(minBp: number) {
  const newSet = new Set<string>();
  props.contigs.forEach(c => {
    if (c.length_bp >= minBp) {
      newSet.add(c.id);
    }
  });
  selectedIds.value = newSet;
  emitSelected();
}

// 快捷筛选：Top N 最长
function filterTopN(n: number) {
  // props.contigs 已经由后端按长度降序排序
  const topItems = props.contigs.slice(0, n);
  selectedIds.value = new Set(topItems.map(c => c.id));
  emitSelected();
}

// 格式化数字
function formatNumber(num: number): string {
  return (num || 0).toLocaleString();
}
</script>

<template>
  <div class="contig-selector-card">
    <div class="selector-header">
      <div class="header-title-box">
        <div class="title-with-badge">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="2">
            <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
          </svg>
          <span class="header-title">序列筛选与分析范围 (Contigs Selection)</span>
          <span class="contig-total-badge">共 {{ contigs.length }} 条序列</span>
        </div>
        <div class="header-desc">
          检测到文件包含多条 Contig，您可按需勾选主要序列片段以避免垃圾碎片干扰或加速分析。
        </div>
      </div>

      <!-- 选中统计面板 -->
      <div class="stats-pill" :class="{ 'warning': selectedStats.count === 0 }">
        <div class="stat-col">
          <span class="stat-label">已选中</span>
          <span class="stat-val highlight">{{ selectedStats.count }} <span class="sub-unit">/ {{ contigs.length }} 条</span></span>
        </div>
        <div class="stat-divider"></div>
        <div class="stat-col">
          <span class="stat-label">分析长度</span>
          <span class="stat-val">{{ formatNumber(selectedStats.length) }} bp</span>
        </div>
        <div class="stat-divider"></div>
        <div class="stat-col">
          <span class="stat-label">总长占比</span>
          <span class="stat-val">{{ selectedStats.lengthPct }}%</span>
        </div>
      </div>
    </div>

    <!-- 工具栏：快捷操作与过滤 -->
    <div class="selector-toolbar">
      <div class="quick-btns">
        <button type="button" class="btn-tool" @click="selectAll">全选</button>
        <button type="button" class="btn-tool" @click="deselectAll">全不选</button>
        <button type="button" class="btn-tool" @click="invertSelection">反选</button>
        <span class="toolbar-sep">|</span>
        <button type="button" class="btn-preset" @click="filterByMinLength(500)">≥ 500 bp</button>
        <button type="button" class="btn-preset" @click="filterByMinLength(1000)">≥ 1,000 bp</button>
        <button type="button" class="btn-preset" @click="filterTopN(10)" v-if="contigs.length > 10">Top 10 最长</button>
        <button type="button" class="btn-preset" @click="filterTopN(20)" v-if="contigs.length > 20">Top 20 最长</button>
      </div>

      <div class="search-box">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2">
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <input 
          v-model="searchQuery" 
          type="text" 
          placeholder="搜索 Contig ID / 描述..." 
          class="search-input"
        />
        <button v-if="searchQuery" class="clear-search" @click="searchQuery = ''">×</button>
      </div>
    </div>

    <!-- Contig 列表表格 -->
    <div class="contig-table-container">
      <table class="contig-table">
        <thead>
          <tr>
            <th width="44" class="col-chk">
              <input 
                type="checkbox" 
                :checked="selectedStats.count === contigs.length && contigs.length > 0"
                :indeterminate="selectedStats.count > 0 && selectedStats.count < contigs.length"
                @change="selectedStats.count === contigs.length ? deselectAll() : selectAll()"
              />
            </th>
            <th width="50">#</th>
            <th width="280">Contig ID</th>
            <th width="140">长度 (bp)</th>
            <th>长度占比</th>
            <th width="90">GC 含量</th>
          </tr>
        </thead>
        <tbody>
          <tr 
            v-for="(item, idx) in filteredContigs" 
            :key="item.id"
            class="contig-row"
            :class="{ 'is-selected': selectedIds.has(item.id) }"
            @click="toggleSelect(item.id, $event, idx)"
          >
            <td class="col-chk" @click.stop>
              <input 
                type="checkbox" 
                :checked="selectedIds.has(item.id)"
                @change="toggleSelect(item.id, $event, idx)"
              />
            </td>
            <td class="col-idx">{{ idx + 1 }}</td>
            <td class="col-id" :title="item.id">
              <span class="contig-id-text">{{ item.id }}</span>
              <span v-if="item.description" class="contig-desc-text">{{ item.description }}</span>
            </td>
            <td class="col-len">{{ formatNumber(item.length_bp) }}</td>
            <td class="col-bar">
              <div class="len-bar-track">
                <div 
                  class="len-bar-fill"
                  :style="{ width: `${Math.max(2, Math.round(item.length_bp / maxContigLen * 100))}%` }"
                ></div>
              </div>
            </td>
            <td class="col-gc">
              <span class="gc-tag">{{ item.gc_content }}%</span>
            </td>
          </tr>
          <tr v-if="filteredContigs.length === 0">
            <td colspan="6" class="empty-hint">未找到匹配的 Contig 条目</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 底部警告提示 -->
    <div v-if="selectedStats.count === 0" class="warning-alert">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2">
        <circle cx="12" cy="12" r="10" />
        <line x1="12" y1="8" x2="12" y2="12" />
        <line x1="12" y1="16" x2="12.01" y2="16" />
      </svg>
      <span>请至少选择 1 条 Contig 序列以启动分析。</span>
    </div>
  </div>
</template>

<style scoped>
.contig-selector-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 16px;
  margin-bottom: 20px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.selector-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 14px;
}

.header-title-box {
  flex: 1;
}

.title-with-badge {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.header-title {
  font-size: 14px;
  font-weight: 700;
  color: #1e293b;
}

.contig-total-badge {
  background: #eff6ff;
  color: #2563eb;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 12px;
  border: 1px solid #bfdbfe;
}

.header-desc {
  font-size: 12px;
  color: #64748b;
  line-height: 1.4;
}

.stats-pill {
  display: flex;
  align-items: center;
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  padding: 6px 14px;
  gap: 12px;
}

.stats-pill.warning {
  border-color: #fca5a5;
  background: #fef2f2;
}

.stat-col {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}

.stat-label {
  font-size: 10px;
  color: #64748b;
  font-weight: 600;
  text-transform: uppercase;
}

.stat-val {
  font-size: 13px;
  font-weight: 700;
  color: #1e293b;
}

.stat-val.highlight {
  color: #2563eb;
}

.sub-unit {
  font-size: 11px;
  font-weight: 500;
  color: #94a3b8;
}

.stat-divider {
  width: 1px;
  height: 24px;
  background: #e2e8f0;
}

.selector-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}

.quick-btns {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.btn-tool {
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  color: #334155;
  font-size: 12px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 5px;
  cursor: pointer;
  transition: all 0.15s;
}

.btn-tool:hover {
  background: #e2e8f0;
  color: #0f172a;
}

.toolbar-sep {
  color: #cbd5e1;
  font-size: 12px;
  margin: 0 2px;
}

.btn-preset {
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  color: #166534;
  font-size: 11px;
  font-weight: 600;
  padding: 4px 8px;
  border-radius: 5px;
  cursor: pointer;
  transition: all 0.15s;
}

.btn-preset:hover {
  background: #dcfce7;
  border-color: #86efac;
}

.search-box {
  display: flex;
  align-items: center;
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  padding: 4px 8px;
  gap: 6px;
  width: 220px;
}

.search-input {
  border: none;
  background: transparent;
  font-size: 12px;
  color: #1e293b;
  outline: none;
  width: 100%;
}

.clear-search {
  border: none;
  background: transparent;
  color: #94a3b8;
  font-size: 14px;
  cursor: pointer;
}

.contig-table-container {
  max-height: 280px;
  overflow-y: auto;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
}

.contig-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.contig-table thead {
  position: sticky;
  top: 0;
  background: #f8fafc;
  z-index: 2;
}

.contig-table th {
  padding: 8px 10px;
  text-align: left;
  font-weight: 600;
  color: #475569;
  border-bottom: 1px solid #e2e8f0;
}

.contig-table td {
  padding: 6px 10px;
  border-bottom: 1px solid #f1f5f9;
  color: #334155;
}

.contig-row {
  cursor: pointer;
  transition: background 0.1s;
}

.contig-row:hover {
  background: #f8fafc;
}

.contig-row.is-selected {
  background: #f0f7ff;
}

.contig-row.is-selected:hover {
  background: #e0effe;
}

.col-chk {
  text-align: center;
}

.col-idx {
  color: #94a3b8;
  font-size: 11px;
}

.col-id {
  max-width: 280px;
}

.contig-id-text {
  font-weight: 700;
  color: #0f172a;
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.contig-desc-text {
  font-size: 10px;
  color: #64748b;
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.col-len {
  font-weight: 600;
  color: #1e293b;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.col-bar {
  vertical-align: middle;
}

.len-bar-track {
  height: 6px;
  background: #e2e8f0;
  border-radius: 3px;
  overflow: hidden;
  width: 100%;
}

.len-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #3b82f6, #60a5fa);
  border-radius: 3px;
}

.gc-tag {
  background: #f1f5f9;
  color: #475569;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 4px;
}

.empty-hint {
  text-align: center;
  padding: 20px;
  color: #94a3b8;
}

.warning-alert {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  padding: 8px 12px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 6px;
  color: #dc2626;
  font-size: 12px;
  font-weight: 600;
}
</style>
