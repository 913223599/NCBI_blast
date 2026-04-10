<template>
  <div class="search-filter-panel">
    <!-- 搜索栏 -->
    <div class="search-bar">
      <div class="search-input-wrapper">
        <span class="search-icon">🔍</span>
        <input
          v-model="localFilters.keyword"
          class="search-input"
          placeholder="搜索样本名称、Accession、物种..."
          @input="handleSearch"
        />
        <button v-if="localFilters.keyword" class="clear-btn" @click="clearKeyword">✕</button>
      </div>
      <button class="filter-toggle-btn" @click="showAdvanced = !showAdvanced">
        <span class="filter-icon">⚙️</span>
        <span>高级筛选</span>
        <span class="arrow" :class="{ open: showAdvanced }">▼</span>
      </button>
    </div>

    <!-- 高级筛选面板 -->
    <div v-show="showAdvanced" class="advanced-filters">
      <div class="filter-grid">
        <div class="filter-item">
          <label>序列类型</label>
          <div class="select-box-neo" @click.stop="toggleDropdown('sequenceType')">
            {{ getSequenceTypeLabel() }} <span class="arrow">▼</span>
            <div v-if="openDropdown === 'sequenceType'" class="dropdown-list">
              <div
                v-for="option in SEQUENCE_TYPE_OPTIONS"
                :key="option.value"
                class="opt"
                :class="{ selected: localFilters.sequenceType === option.value }"
                @click.stop="selectFilter('sequenceType', option.value)"
              >
                {{ option.label }}
              </div>
            </div>
          </div>
        </div>

        <div class="filter-item">
          <label>来源国家</label>
          <div class="select-box-neo" @click.stop="toggleDropdown('country')">
            {{ getCountryLabel() }} <span class="arrow">▼</span>
            <div v-if="openDropdown === 'country'" class="dropdown-list">
              <div
                v-for="country in strain.uniqueCountries"
                :key="country"
                class="opt"
                :class="{ selected: localFilters.country === country }"
                @click.stop="selectFilter('country', country)"
              >
                {{ country }}
              </div>
            </div>
          </div>
        </div>

        <div class="filter-item">
          <label>采集日期从</label>
          <input
            v-model="localFilters.dateFrom"
            type="date"
            class="date-input"
            @change="handleSearch"
          />
        </div>

        <div class="filter-item">
          <label>采集日期至</label>
          <input
            v-model="localFilters.dateTo"
            type="date"
            class="date-input"
            @change="handleSearch"
          />
        </div>
      </div>

      <div class="filter-actions">
        <button class="btn-reset" @click="resetFilters">
          🔄 重置筛选
        </button>
        <span class="result-count">
          找到 <strong>{{ strain.filteredCount }}</strong> 条结果
        </span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useStrainStore } from '../../stores/strain'

const strain = useStrainStore()
const emit = defineEmits(['update'])

const showAdvanced = ref(false)
const openDropdown = ref<string | null>(null)

const localFilters = ref({
  keyword: '',
  sequenceType: '',
  country: '',
  dateFrom: '',
  dateTo: ''
})

const SEQUENCE_TYPE_OPTIONS = [
  { value: '', label: '全部类型' },
  { value: 'DNA', label: 'DNA (核酸)' },
  { value: 'RNA', label: 'RNA (核酸)' },
  { value: 'Protein', label: 'Protein (蛋白)' }
]

function getSequenceTypeLabel(): string {
  return SEQUENCE_TYPE_OPTIONS.find(o => o.value === localFilters.value.sequenceType)?.label || '全部类型'
}

function getCountryLabel(): string {
  return localFilters.value.country || '全部国家'
}

function toggleDropdown(name: string) {
  openDropdown.value = openDropdown.value === name ? null : name
}

function selectFilter(field: keyof typeof localFilters.value, value: string) {
  (localFilters.value as any)[field] = value
  openDropdown.value = null
  applyFilters()
}

let searchTimer: number | null = null
function handleSearch() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => {
    applyFilters()
  }, 300)
}

function applyFilters() {
  // 更新 store 中的筛选条件
  Object.entries(localFilters.value).forEach(([key, value]) => {
    strain.setSearchFilter(key as any, value)
  })
  emit('update', localFilters.value)
}

function clearKeyword() {
  localFilters.value.keyword = ''
  applyFilters()
}

function resetFilters() {
  localFilters.value = {
    keyword: '',
    sequenceType: '',
    country: '',
    dateFrom: '',
    dateTo: ''
  }
  strain.resetFilters()
  emit('update', localFilters.value)
}

function handleClickOutside() {
  openDropdown.value = null
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  // 同步 store 中的筛选条件
  localFilters.value = { ...strain.searchFilters }
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
  if (searchTimer) clearTimeout(searchTimer)
})
</script>

<style scoped>
.search-filter-panel {
  background: white;
  border-radius: 12px;
  padding: 16px;
  
}

.search-bar {
  display: flex;
  gap: 12px;
  align-items: center;
}

.search-input-wrapper {
  flex: 1;
  position: relative;
}

.search-icon {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 1rem;
}

.search-input {
  width: 100%;
  padding: 10px 40px 10px 40px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  font-size: 0.9rem;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.search-input:focus {
  outline: none;
  border-color: #2563eb;
  
}

.clear-btn {
  position: absolute;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
}

.clear-btn:hover {
  background: #f1f5f9;
  color: #1e293b;
}

.filter-toggle-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 16px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  font-size: 0.85rem;
  color: #475569;
  cursor: pointer;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
  white-space: nowrap;
}

.filter-toggle-btn:hover {
  background: #e2e8f0;
  color: #1e293b;
}

.filter-icon {
  font-size: 1rem;
}

.arrow {
  font-size: 0.6rem;
  transition: transform 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.arrow.open {
  transform: rotate(180deg);
}

.advanced-filters {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #e2e8f0;
}

.filter-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}

.filter-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.filter-item label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
}

.select-box-neo {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 0.82rem;
  cursor: pointer;
  position: relative;
  display: flex;
  justify-content: space-between;
  align-items: center;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.select-box-neo:hover {
  border-color: #cbd5e1;
  background: white;
}

.select-box-neo .arrow {
  color: #94a3b8;
  font-size: 0.6rem;
  margin-left: 8px;
}

.dropdown-list {
  position: absolute;
  top: 110%;
  left: 0;
  right: 0;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  
  z-index: 100;
  max-height: 200px;
  overflow-y: auto;
  padding: 6px;
}

.dropdown-list .opt {
  padding: 10px 12px;
  font-size: 0.82rem;
  border-radius: 6px;
  cursor: pointer;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.dropdown-list .opt:hover {
  background: #f1f5f9;
  color: #2563eb;
}

.dropdown-list .opt.selected {
  color: #2563eb;
  font-weight: 700;
  background: #eff6ff;
}

.date-input {
  padding: 10px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.85rem;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.date-input:focus {
  outline: none;
  border-color: #2563eb;
  
}

.filter-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.btn-reset {
  padding: 8px 16px;
  background: #f1f5f9;
  border: none;
  border-radius: 8px;
  font-size: 0.85rem;
  color: #475569;
  cursor: pointer;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.btn-reset:hover {
  background: #e2e8f0;
  color: #1e293b;
}

.result-count {
  font-size: 0.85rem;
  color: #64748b;
}

.result-count strong {
  color: #2563eb;
  font-weight: 700;
}
</style>