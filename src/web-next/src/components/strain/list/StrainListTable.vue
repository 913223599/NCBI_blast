<template>
  <div class="table-scroll-container">
    <table class="strain-table">
      <thead>
        <tr>
          <th class="col-checkbox"></th>
          <th v-if="visibility.accession" class="col-accession sortable" @click="emit('sort', 'accession')">
            登录号 <span class="sort-icon">{{ getSortIcon('accession') }}</span>
          </th>
          <th class="col-name sortable" @click="emit('sort', 'name')">
            名称 <span class="sort-icon">{{ getSortIcon('name') }}</span>
          </th>
          <th v-if="visibility.species" class="col-species sortable" @click="emit('sort', 'species')">
            物种 <span class="sort-icon">{{ getSortIcon('species') }}</span>
          </th>
          <th v-if="visibility.strain" class="col-strain sortable" @click="emit('sort', 'strain')">
            菌株 <span class="sort-icon">{{ getSortIcon('strain') }}</span>
          </th>
          <th v-if="visibility.sequenceType" class="col-type sortable" @click="emit('sort', 'sequenceType')">
            类型 <span class="sort-icon">{{ getSortIcon('sequenceType') }}</span>
          </th>
          <th v-if="visibility.source" class="col-source">来源</th>
          <th v-if="visibility.host" class="col-host">宿主</th>
          <th v-if="visibility.country" class="col-country">地区</th>
          <th v-if="visibility.collectionDate" class="col-date sortable" @click="emit('sort', 'collectionDate')">
            采集时间 <span class="sort-icon">{{ getSortIcon('collectionDate') }}</span>
          </th>
          <th v-if="visibility.addedAt" class="col-date sortable" @click="emit('sort', 'addedAt')">
            录入时间 <span class="sort-icon">{{ getSortIcon('addedAt') }}</span>
          </th>
          <th v-if="visibility.location" class="col-location">
            位置
          </th>
          <th class="col-actions">操作</th>
        </tr>
      </thead>
      <tbody>
        <!-- 主行 -->
        <template v-for="group in records" :key="group.representative.id">
          <tr
            class="table-row"
            :class="{
              selected: props.selectedIds.has(group.representative.id),
              active: props.activeId === group.representative.id,
              'has-duplicates': getDuplicates(group).length > 0
            }"
            @click="emit('rowClick', group.representative)"
            @dblclick="emit('viewDetail', group.representative)"
          >
            <td class="col-checkbox">
              <input
                type="checkbox"
                :checked="props.selectedIds.has(group.representative.id)"
                @click.stop="handleCheckboxClick($event, group.representative, [group.representative, ...getDuplicates(group)])"
              />
            </td>
            
            <td v-if="visibility.accession" class="col-accession">
              <span 
                class="accession-tag" 
                :class="{ expandable: getDuplicates(group).length > 0, expanded: isExpanded(group.representative.accession) }"
                @click.stop="getDuplicates(group).length > 0 ? toggleExpand(group.representative.accession) : emit('viewDetail', group.representative)"
                :title="getDuplicates(group).length > 0 ? (isExpanded(group.representative.accession) ? '点击收起备份' : '点击展开备份') : ''"
              >
                {{ group.representative.accession }}
                <span v-if="getDuplicates(group).length > 0" class="duplicate-count">
                  ({{ getDuplicates(group).length + 1 }})
                </span>
              </span>
            </td>
            <td class="col-name" :title="group.representative.name">{{ group.representative.name }}</td>
            <td v-if="visibility.species" class="col-species">
              <span class="species-badge">{{ group.representative.species }}</span>
            </td>
            <td v-if="visibility.strain" class="col-strain">{{ group.representative.strain || '-' }}</td>
            <td v-if="visibility.sequenceType" class="col-type">
              <span v-if="group.representative.sequenceType" class="type-badge" :class="group.representative.sequenceType.toLowerCase()">
                {{ group.representative.sequenceType }}
              </span>
              <span v-else>-</span>
            </td>
            <td v-if="visibility.source" class="col-source" :title="group.representative.source">{{ group.representative.source || '-' }}</td>
            <td v-if="visibility.host" class="col-host">{{ group.representative.host || '-' }}</td>
            <td v-if="visibility.country" class="col-country">{{ group.representative.country || '-' }}</td>
            <td v-if="visibility.collectionDate" class="col-date">{{ group.representative.collectionDate || '-' }}</td>
            <td v-if="visibility.addedAt" class="col-date">{{ group.representative.addedAt ? new Date(group.representative.addedAt).toLocaleDateString() : '-' }}</td>
            <td v-if="visibility.location" class="col-location" :title="getLocationString(group.representative)">
              {{ getLocationString(group.representative) }}
            </td>
            <td class="col-actions">
              <div class="action-btns">
                <button class="action-btn-mini edit" @click.stop="emit('viewDetail', group.representative)" title="编辑详情">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M12 20h9M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
                  </svg>
                </button>
                <button class="action-btn-mini delete" @click.stop="emit('deleteRow', group.representative.id)" title="移除样本">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="3 6 5 6 21 6" />
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                  </svg>
                </button>
              </div>
            </td>
          </tr>
          
          <!-- 备份行（仅在展开时显示） -->
          <tr
            v-if="isExpanded(group.representative.accession) && getDuplicates(group).length > 0"
            v-for="(duplicate, index) in getDuplicates(group)"
            :key="duplicate.id"
            class="table-row duplicate-row"
            :class="{
              selected: props.selectedIds.has(duplicate.id),
              active: props.activeId === duplicate.id
            }"
            @click="emit('rowClick', duplicate)"
            @dblclick="emit('viewDetail', duplicate)"
          >
            <td class="col-checkbox">
              <input
                type="checkbox"
                :checked="props.selectedIds.has(duplicate.id)"
                @click.stop="handleCheckboxClick($event, duplicate, [group.representative, ...getDuplicates(group)])"
              />
            </td>
            <td v-if="visibility.accession" class="col-accession">
              <span class="accession-tag" @click.stop="emit('viewDetail', duplicate)">
                {{ duplicate.accession }}
              </span>
            </td>
            <td class="col-name" :title="duplicate.name">{{ duplicate.name }}</td>
            <td v-if="visibility.species" class="col-species">
              <span class="species-badge">{{ duplicate.species }}</span>
            </td>
            <td v-if="visibility.strain" class="col-strain">{{ duplicate.strain || '-' }}</td>
            <td v-if="visibility.sequenceType" class="col-type">
              <span v-if="duplicate.sequenceType" class="type-badge" :class="duplicate.sequenceType.toLowerCase()">
                {{ duplicate.sequenceType }}
              </span>
              <span v-else>-</span>
            </td>
            <td v-if="visibility.source" class="col-source" :title="duplicate.source">{{ duplicate.source || '-' }}</td>
            <td v-if="visibility.host" class="col-host">{{ duplicate.host || '-' }}</td>
            <td v-if="visibility.country" class="col-country">{{ duplicate.country || '-' }}</td>
            <td v-if="visibility.collectionDate" class="col-date">{{ duplicate.collectionDate || '-' }}</td>
            <td v-if="visibility.addedAt" class="col-date">{{ duplicate.addedAt ? new Date(duplicate.addedAt).toLocaleDateString() : '-' }}</td>
            <td v-if="visibility.location" class="col-location" :title="getLocationString(duplicate)">
              {{ getLocationString(duplicate) }}
            </td>
            <td class="col-actions">
              <div class="action-btns">
                <button class="action-btn-mini edit" @click.stop="emit('viewDetail', duplicate)" title="编辑详情">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M12 20h9M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
                  </svg>
                </button>
                <button class="action-btn-mini delete" @click.stop="emit('deleteRow', duplicate.id)" title="移除样本">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="3 6 5 6 21 6" />
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                  </svg>
                </button>
              </div>
            </td>
          </tr>
        </template>
      </tbody>
    </table>
    
    <div v-if="records.length === 0" class="empty-placeholder">
      <div class="empty-icon">
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.4">
          <path d="M22 12h-6l-2 3h-4l-2-3H2" />
          <path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
        </svg>
      </div>
      <p>未找到符合条件的样本记录</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useStrainStore } from '../../../stores/strain'
import type { StrainRecord } from '../../../stores/strain'

const strainStore = useStrainStore()

// 展开状态的记录（存储已展开的 accession）
const expandedAccessions = ref<Set<string>>(new Set())

const props = defineProps<{
  records: Array<{ representative: StrainRecord; duplicates: StrainRecord[] }>
  selectedIds: Set<string>
  visibility: Record<string, boolean>
  activeId?: string
  sortKey?: string
  sortOrder?: 'asc' | 'desc' | null
}>()

const emit = defineEmits(['rowClick', 'toggleSelect', 'viewDetail', 'deleteRow', 'sort', 'shiftSelect'])

// 辅助函数：安全获取 duplicates 数组（防止运行时 undefined 错误）
function getDuplicates(group: { representative: StrainRecord; duplicates: StrainRecord[] }): StrainRecord[] {
  return group.duplicates || []
}

// 计算所有可见记录的扁平化列表（用于 Shift 选择）
const flatRecords = computed(() => {
  const result: StrainRecord[] = []
  props.records.forEach(group => {
    result.push(group.representative)
    getDuplicates(group).forEach(dup => result.push(dup))
  })
  return result
})

// 切换展开/收起状态
function toggleExpand(accession: string) {
  if (expandedAccessions.value.has(accession)) {
    expandedAccessions.value.delete(accession)
  } else {
    expandedAccessions.value.add(accession)
  }
}

// 检查是否展开
function isExpanded(accession: string): boolean {
  return expandedAccessions.value.has(accession)
}

// 处理复选框点击（包括所有备份）
function handleCheckboxClick(event: MouseEvent, record: StrainRecord, allRecords: StrainRecord[]) {
  console.log('[handleCheckboxClick] shiftKey:', event.shiftKey, 'activeId:', props.activeId, 'record.id:', record.id)
  
  if (event.shiftKey && props.activeId) {
    // 触发 Shift 键多选事件，传递扁平化的所有记录列表
    console.log('[handleCheckboxClick] Emitting shiftSelect with', flatRecords.value.length, 'records')
    emit('shiftSelect', props.activeId, record.id, flatRecords.value.map(r => r.id))
  } else {
    // 非 Shift 点击：先设置 activeId，然后切换选中状态
    // 这样可以确保后续 Shift+点击有正确的起始点
    emit('rowClick', record)
    emit('toggleSelect', record.id)
  }
}

function getSortIcon(key: string) {
  if (props.sortKey !== key) return '↕️'
  if (props.sortOrder === 'asc') return '🔼'
  if (props.sortOrder === 'desc') return '🔽'
  return '↕️'
}

function getLocationString(record: StrainRecord) {
  if (record.freezerId && record.boxId) {
    const map = strainStore.locationMap
    const path = map[`${record.freezerId}|${record.boxId}`] || map[record.boxId] || '未知位置'
    return record.position ? `${path} - ${record.position}` : path
  }
  if (record.position) return record.position
  return '-'
}
</script>

<style scoped>
.table-scroll-container {
  flex: 1;
  overflow: auto;
  position: relative;
  background: white;
}

.strain-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.82rem;
  table-layout: fixed;
}

.strain-table thead {
  background: #f8fafc;
  position: sticky;
  top: 0;
  z-index: 20;
}

.strain-table th {
  padding: 10px 12px;
  text-align: left;
  font-weight: 800;
  color: #475569;
  border-bottom: 2px solid #e2e8f0;
  white-space: nowrap;
}

.strain-table th.sortable {
  cursor: pointer;
  user-select: none;
}

.strain-table th.sortable:hover {
  background: #f1f5f9;
  color: #2563eb;
}

.sort-icon {
  font-size: 0.7rem;
  margin-left: 4px;
  opacity: 0.7;
}

.table-row {
  border-bottom: 1px solid #f1f5f9;
  cursor: pointer;
  transition: background 0.1s;
}

.table-row:hover {
  background: #f8fafc;
}

.table-row.selected {
  background: #eff6ff !important;
}

.table-row.active {
  background: #dbeafe !important;
}

.strain-table td {
  padding: 8px 12px;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 列宽定义 */
.col-checkbox { width: 45px; text-align: center; }
.col-accession { width: 140px; }
.col-name { width: 180px; }
.col-species { width: 150px; }
.col-strain { width: 100px; }
.col-type { width: 80px; }
.col-source { width: 150px; }
.col-host { width: 100px; }
.col-country { width: 100px; }
.col-date { width: 100px; }
.col-location { width: 180px; }
.col-actions { width: 90px; text-align: center; }

.species-badge {
  display: inline-block;
  padding: 1px 6px;
  background: #f1f5f9;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 600;
  color: #64748b;
}

.type-badge {
  display: inline-block;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.65rem;
  font-weight: 800;
  text-transform: uppercase;
}

.type-badge.dna { background: #dbeafe; color: #1e40af; }
.type-badge.rna { background: #fce7f3; color: #9d174d; }
.type-badge.protein { background: #d1fae5; color: #065f46; }

.action-btns {
  display: flex;
  justify-content: center;
  gap: 6px;
}

.action-btn-mini {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 0.9rem;
  padding: 4px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.action-btn-mini:hover {
  background: #f1f5f9;
}

.action-btn-mini.delete:hover {
  background: #fef2f2;
}

.empty-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 100px 20px;
  text-align: center;
  color: #94a3b8;
}

.empty-icon {
  font-size: 3rem;
  margin-bottom: 12px;
  opacity: 0.5;
}

/* 登录号标签样式增强 */
.accession-tag {
  display: inline-block;
  padding: 2px 8px;
  background: #eff6ff;
  color: #2563eb;
  border-radius: 4px;
  font-weight: 700;
  font-family: monospace;
  cursor: pointer;
  border: 1px solid #dbeafe;
  transition: all 0.2s;
}

.accession-tag:hover {
  background: #2563eb;
  color: white;
}

/* 可展开的登录号样式 */
.accession-tag.expandable {
  cursor: pointer;
  position: relative;
  padding-right: 20px;
}

.accession-tag.expandable::after {
  content: '▶';
  position: absolute;
  right: 6px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 0.6em;
  color: inherit;
  opacity: 0.7;
  transition: transform 0.2s;
}

.accession-tag.expandable.expanded::after {
  content: '▼';
}

.accession-tag.expandable:hover::after {
  opacity: 1;
}

/* 备份行样式 */
.duplicate-row {
  background: #fafafa;
  border-left: 3px solid #cbd5e1;
}

.duplicate-row:hover {
  background: #f1f5f9;
}

.duplicate-row.selected {
  background: #eff6ff !important;
}

.duplicate-row.active {
  background: #dbeafe !important;
}

/* 重复数量标记 */
.duplicate-count {
  font-size: 0.7em;
  color: #64748b;
  margin-left: 4px;
}
</style>
