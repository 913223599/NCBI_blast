<template>
  <div class="filter-panel">
    <h3 class="panel-title">高级筛选</h3>

    <!-- 关键词搜索 -->
    <div class="form-group">
      <label>关键词搜索</label>
      <input
        v-model="keyword"
        class="text-input"
        placeholder="搜索名称、物种、登录号..."
        @input="handleSearch"
      />
    </div>

    <!-- 物种筛选 -->
    <div class="form-group">
      <label>物种</label>
      <select v-model="species" class="select-input" @change="handleFilter">
        <option value="">全部物种</option>
        <option v-for="s in strain.uniqueSpecies" :key="s" :value="s">
          {{ s }}
        </option>
      </select>
    </div>

    <!-- 序列类型 -->
    <div class="form-group">
      <label>序列类型</label>
      <div class="checkbox-group">
        <label class="checkbox-item">
          <input type="checkbox" value="DNA" v-model="sequenceTypes" @change="handleFilter" />
          <span>DNA</span>
        </label>
        <label class="checkbox-item">
          <input type="checkbox" value="RNA" v-model="sequenceTypes" @change="handleFilter" />
          <span>RNA</span>
        </label>
        <label class="checkbox-item">
          <input type="checkbox" value="Protein" v-model="sequenceTypes" @change="handleFilter" />
          <span>Protein</span>
        </label>
      </div>
    </div>

    <!-- 国家/地区 -->
    <div class="form-group">
      <label>国家/地区</label>
      <select v-model="country" class="select-input" @change="handleFilter">
        <option value="">全部地区</option>
        <option v-for="c in strain.uniqueCountries" :key="c" :value="c">
          {{ c }}
        </option>
      </select>
    </div>

    <!-- 采集日期范围 -->
    <div class="form-group">
      <label>采集日期范围</label>
      <div class="date-range">
        <input
          v-model="dateFrom"
          type="date"
          class="text-input"
          @change="handleFilter"
        />
        <span class="date-separator">至</span>
        <input
          v-model="dateTo"
          type="date"
          class="text-input"
          @change="handleFilter"
        />
      </div>
    </div>

    <!-- 操作按钮 -->
    <div class="filter-actions">
      <button class="btn-reset" @click="handleReset">重置筛选</button>
    </div>

    <!-- 筛选结果统计 -->
    <div class="filter-stats">
      <span class="stat-text">
        显示 {{ strain.filteredCount }} / {{ strain.totalRecords }} 条记录
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useStrainStore } from '../../stores/strain'

const strain = useStrainStore()

const keyword = ref('')
const species = ref('')
const sequenceTypes = ref<string[]>([])
const country = ref('')
const dateFrom = ref('')
const dateTo = ref('')

function handleSearch() {
  strain.setSearchFilter('keyword', keyword.value)
}

function handleFilter() {
  strain.setSearchFilter('species', species.value)
  strain.setSearchFilter('sequenceType', sequenceTypes.value.join(','))
  strain.setSearchFilter('country', country.value)
  strain.setSearchFilter('dateFrom', dateFrom.value)
  strain.setSearchFilter('dateTo', dateTo.value)
}

function handleReset() {
  keyword.value = ''
  species.value = ''
  sequenceTypes.value = []
  country.value = ''
  dateFrom.value = ''
  dateTo.value = ''
  strain.resetFilters()
}
</script>

<style scoped>
.filter-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.panel-title {
  font-size: 1rem;
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 8px 0;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-group label {
  font-size: 0.75rem;
  font-weight: 700;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.02em;
}

.text-input,
.select-input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  font-size: 0.85rem;
  transition: border-color 0.2s;
  background: white;
}

.text-input:focus,
.select-input:focus {
  outline: none;
  border-color: #2563eb;
}

.checkbox-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.checkbox-item {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-size: 0.85rem;
  color: #475569;
}

.checkbox-item input[type="checkbox"] {
  width: 16px;
  height: 16px;
  cursor: pointer;
}

.date-range {
  display: flex;
  align-items: center;
  gap: 8px;
}

.date-separator {
  color: #94a3b8;
  font-size: 0.85rem;
}

.filter-actions {
  padding-top: 8px;
  border-top: 1px solid #e2e8f0;
}

.btn-reset {
  width: 100%;
  padding: 10px;
  background: #f1f5f9;
  border: none;
  border-radius: 10px;
  font-size: 0.85rem;
  font-weight: 600;
  color: #475569;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-reset:hover {
  background: #e2e8f0;
}

.filter-stats {
  padding: 12px;
  background: #eff6ff;
  border-radius: 10px;
  text-align: center;
}

.stat-text {
  font-size: 0.85rem;
  font-weight: 600;
  color: #2563eb;
}
</style>
