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
        <tr
          v-for="record in records"
          :key="record.id"
          class="table-row"
          :class="{
            selected: selectedIds.has(record.id),
            active: activeId === record.id
          }"
          @click="emit('rowClick', record)"
          @dblclick="emit('viewDetail', record)"
        >
          <td class="col-checkbox">
            <input
              type="checkbox"
              :checked="selectedIds.has(record.id)"
              @click.stop
              @change="emit('toggleSelect', record.id)"
            />
          </td>
          <td v-if="visibility.accession" class="col-accession">
            <span class="accession-tag" @click.stop="emit('viewDetail', record)">
              {{ record.accession }}
            </span>
          </td>
          <td class="col-name" :title="record.name">{{ record.name }}</td>
          <td v-if="visibility.species" class="col-species">
            <span class="species-badge">{{ record.species }}</span>
          </td>
          <td v-if="visibility.strain" class="col-strain">{{ record.strain || '-' }}</td>
          <td v-if="visibility.sequenceType" class="col-type">
            <span class="type-badge" :class="record.sequenceType.toLowerCase()">
              {{ record.sequenceType }}
            </span>
          </td>
          <td v-if="visibility.source" class="col-source" :title="record.source">{{ record.source || '-' }}</td>
          <td v-if="visibility.host" class="col-host">{{ record.host || '-' }}</td>
          <td v-if="visibility.country" class="col-country">{{ record.country || '-' }}</td>
          <td v-if="visibility.collectionDate" class="col-date">{{ record.collectionDate || '-' }}</td>
          <td v-if="visibility.addedAt" class="col-date">{{ record.addedAt ? new Date(record.addedAt).toLocaleDateString() : '-' }}</td>
          <td v-if="visibility.location" class="col-location" :title="getLocationString(record)">
            {{ getLocationString(record) }}
          </td>
          <td class="col-actions">
            <div class="action-btns">
              <button class="action-btn-mini edit" @click.stop="emit('viewDetail', record)" title="编辑详情">
                ✏️
              </button>
              <button class="action-btn-mini delete" @click.stop="emit('deleteRow', record.id)" title="移除样本">
                🗑️
              </button>
            </div>
          </td>
        </tr>
      </tbody>
    </table>
    
    <div v-if="records.length === 0" class="empty-placeholder">
      <div class="empty-icon">📭</div>
      <p>未找到符合条件的样本记录</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useStrainStore } from '../../../stores/strain'
import type { StrainRecord } from '../../../stores/strain'

const strainStore = useStrainStore()

const props = defineProps<{
  records: StrainRecord[]
  selectedIds: Set<string>
  visibility: Record<string, boolean>
  activeId?: string
  sortKey?: string
  sortOrder?: 'asc' | 'desc' | null
}>()

const emit = defineEmits(['rowClick', 'toggleSelect', 'viewDetail', 'deleteRow', 'sort'])

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
}

.accession-tag:hover {
  background: #2563eb;
  color: white;
}

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
</style>
