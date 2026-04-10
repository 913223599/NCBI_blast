<template>
  <div class="lookup-manager">
    <!-- 头部 -->
    <div class="manager-header">
      <div class="header-title">
        <span class="header-icon">📖</span>
        <h3>编码对照表管理</h3>
      </div>
      <div class="header-actions">
        <button class="action-btn" :class="{ active: activeTab === 'lookup' }" @click="activeTab = 'lookup'">
          🧬 分类
        </button>
        <button class="action-btn" :class="{ active: activeTab === 'source' }" @click="activeTab = 'source'">
          📍 来源
        </button>
        <button class="action-btn" :class="{ active: activeTab === 'search' }" @click="activeTab = 'search'">
          🔍 反查
        </button>
        <button class="action-btn" :class="{ active: activeTab === 'maintenance' }" @click="activeTab = 'maintenance'">
          🛠️ 维护
        </button>
      </div>
    </div>

    <!-- 分类对照表 -->
    <div v-if="activeTab === 'lookup'" class="tab-content">
      <div class="tree-container">
        <!-- 大类列表 -->
        <div
          v-for="(catName, catCode) in CATEGORY_MAP"
          :key="catCode"
          class="tree-node"
        >
          <div
            class="node-row level-1"
            @click="toggleExpand(catCode)"
          >
            <span class="expand-icon">{{ isExpanded(catCode) ? '▼' : '▶' }}</span>
            <span class="node-code">{{ catCode }}</span>
            <span class="node-name">{{ catName }}</span>
            <span class="node-count">{{ getGenusCount(catCode) }} 属</span>
          </div>

          <!-- 属列表 -->
          <div v-if="isExpanded(catCode)" class="tree-children">
            <div
              v-for="genus in getGenusList(catCode)"
              :key="genus.fullPath"
              class="tree-node"
            >
              <div
                class="node-row level-2"
                @click="toggleExpand(genus.fullPath)"
              >
                <span class="expand-icon">{{ isExpanded(genus.fullPath) ? '▼' : '▶' }}</span>
                <span class="node-code">{{ genus.code }}</span>
                <span class="node-name">{{ genus.name }}</span>
                <span v-if="genus.latinName" class="node-latin">{{ genus.latinName }}</span>
                <span class="node-count">{{ getSpeciesCount(catCode, genus.code) }} 种</span>
                <button
                  v-if="!genus.isBuiltin"
                  class="node-action-btn delete"
                  @click.stop="handleDeleteGenus(genus.fullPath)"
                >✕</button>
                <button
                  class="node-action-btn toggle"
                  :class="{ disabled: !genus.enabled }"
                  @click.stop="handleToggleGenus(genus.fullPath)"
                >{{ genus.enabled ? '●' : '○' }}</button>
              </div>

              <!-- 种列表 -->
              <div v-if="isExpanded(genus.fullPath)" class="tree-children">
                <div
                  v-for="species in getSpeciesList(catCode, genus.code)"
                  :key="species.fullPath"
                  class="tree-node"
                >
                  <div class="node-row level-3">
                    <span class="node-code">{{ species.code }}</span>
                    <span class="node-name">{{ species.name }}</span>
                    <span v-if="species.latinName" class="node-latin">{{ species.latinName }}</span>
                    <button
                      v-if="!species.isBuiltin"
                      class="node-action-btn delete"
                      @click.stop="handleDeleteSpecies(species.fullPath)"
                    >✕</button>
                    <button
                      class="node-action-btn toggle"
                      :class="{ disabled: !species.enabled }"
                      @click.stop="handleToggleSpecies(species.fullPath)"
                    >{{ species.enabled ? '●' : '○' }}</button>
                  </div>
                </div>

                <!-- 种级新增 -->
                <div class="add-row">
                  <button
                    v-if="addingAt !== genus.fullPath"
                    class="add-row-btn"
                    @click="startAddSpecies(genus.fullPath)"
                  >+ 添加种</button>
                  <div v-else class="add-inline">
                    <input v-model="addFormName" class="add-input" placeholder="中文名" />
                    <input v-model="addFormLatin" class="add-input" placeholder="学名(可选)" />
                    <button class="confirm-btn" @click="confirmAddSpecies(catCode, genus.code)">✓</button>
                    <button class="cancel-btn" @click="addingAt = ''">✕</button>
                  </div>
                </div>
              </div>
            </div>

            <!-- 属级新增 -->
            <div class="add-row">
              <button
                v-if="addingAt !== catCode"
                class="add-row-btn"
                @click="startAddGenus(catCode)"
              >+ 添加属</button>
              <div v-else class="add-inline">
                <input v-model="addFormName" class="add-input" placeholder="中文名" />
                <input v-model="addFormLatin" class="add-input" placeholder="学名(可选)" />
                <button class="confirm-btn" @click="confirmAddGenus(catCode)">✓</button>
                <button class="cancel-btn" @click="addingAt = ''">✕</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 来源字典 -->
    <div v-if="activeTab === 'source'" class="tab-content">
      <div class="source-list">
        <div
          v-for="source in allSources"
          :key="source.code"
          class="source-row"
          :class="{ dimmed: !source.enabled }"
        >
          <template v-if="editingSourceCode !== source.code">
            <span class="source-code">{{ source.code }}</span>
            <span class="source-name">{{ source.name }}</span>
            <span v-if="source.description" class="source-desc">{{ source.description }}</span>
            <div class="source-actions">
              <button
                class="node-action-btn toggle"
                title="启用/禁用"
                :class="{ disabled: !source.enabled }"
                @click="handleToggleSource(source.code)"
              >{{ source.enabled ? '●' : '○' }}</button>
              <button
                class="node-action-btn edit"
                title="编辑"
                @click="startEditSource(source)"
              >✎</button>
              <button
                v-if="!source.isBuiltin"
                class="node-action-btn delete"
                title="删除"
                @click="handleDeleteSource(source.code)"
              >✕</button>
            </div>
          </template>
          <template v-else>
            <span class="source-code">{{ source.code }}</span>
            <input v-model="editSrcName" class="edit-input grow" placeholder="名称" />
            <input v-model="editSrcDesc" class="edit-input grow" placeholder="备注" />
            <div class="source-actions">
              <button class="confirm-btn small" @click="confirmEditSource">✓</button>
              <button class="cancel-btn small" @click="editingSourceCode = ''">✕</button>
            </div>
          </template>
        </div>

        <div v-if="!strain.isInitialized" class="loading-hint">
          正在从数据库加载编码系统...
        </div>
        <div v-else-if="allSources.length === 0" class="empty-hint">
          尚未定义任何来源。请添加第一个来源。
        </div>

        <!-- 新增来源 -->
        <div class="source-add-area">
          <input v-model="newSrcCode" class="add-input small" placeholder="编码(2位)" maxlength="2" />
          <input v-model="newSrcName" class="add-input" placeholder="名称" />
          <input v-model="newSrcDesc" class="add-input" placeholder="备注(可选)" />
          <button class="confirm-btn" @click="handleAddSourceEntry">+ 添加</button>
        </div>
      </div>
    </div>

    <!-- 编码反查 -->
    <div v-if="activeTab === 'search'" class="tab-content">
      <div class="search-area">
        <input
          v-model="searchCode"
          class="search-code-input"
          placeholder="输入14位编码进行反查..."
          maxlength="14"
          @input="handleSearch"
        />

        <div v-if="searchResult" class="search-result">
          <table class="result-table">
            <tbody>
              <tr>
                <td class="label-cell">来源 (XX)</td>
                <td class="code-cell">{{ searchResult.source }}</td>
                <td class="name-cell">{{ searchResult.sourceName }}</td>
              </tr>
              <tr>
                <td class="label-cell">大类 (A)</td>
                <td class="code-cell">{{ searchResult.category }}</td>
                <td class="name-cell">{{ searchResult.categoryName }}</td>
              </tr>
              <tr>
                <td class="label-cell">属 (BBB)</td>
                <td class="code-cell">{{ searchResult.genus }}</td>
                <td class="name-cell">{{ searchResult.genusName }}</td>
              </tr>
              <tr>
                <td class="label-cell">种 (CCC)</td>
                <td class="code-cell">{{ searchResult.species }}</td>
                <td class="name-cell">{{ searchResult.speciesName }}</td>
              </tr>
              <tr>
                <td class="label-cell">传代 (P)</td>
                <td class="code-cell">{{ searchResult.passage }}</td>
                <td class="name-cell">{{ searchResult.passage === 0 ? '原始株' : `P${searchResult.passage}` }}</td>
              </tr>
              <tr>
                <td class="label-cell">流水号</td>
                <td class="code-cell" colspan="2">#{{ String(searchResult.serial).padStart(4, '0') }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="searchCode.length === 14 && !searchResult" class="search-invalid">
          编码格式无效，无法解析
        </div>
      </div>
    </div>
    <!-- 数据库维护 -->
    <div v-if="activeTab === 'maintenance'" class="tab-content">
      <div class="maintenance-card">
        <div class="card-header">
          <span class="card-icon">📏</span>
          <h4>流水号重校准</h4>
        </div>
        <p class="card-desc">
          扫描当前数据库中的所有样本，将各分类下的计数器重置为实际已用的最大值。
          用于修复由于误操作、系统取消或报错导致的“跳号”问题。
        </p>
        <div class="card-actions">
          <button class="maintenance-btn primary" @click="handleRecalibrate">
            立即重校准
          </button>
        </div>
      </div>

      <div class="maintenance-card warning">
        <div class="card-header">
          <span class="card-icon">🧹</span>
          <h4>清理冗余计数器</h4>
        </div>
        <p class="card-desc">
          删除没有任何样本关联的过期或错误的流水号记录。
        </p>
        <div class="card-actions">
          <button class="maintenance-btn secondary" @click="handleClearUnusedCounters">
            清理
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import type { CategoryCode, ResolvedCode } from '../../types/codeSystem'
import { CATEGORY_MAP } from '../../types/codeSystem'
import { useCodeGenerator } from '../../composables/useCodeGenerator'

import { useStrainStore } from '../../stores/strain'
import { useAppStore } from '../../stores/app'

const codeGen = useCodeGenerator()
const strain = useStrainStore()
const appStore = useAppStore()

/* ========== 标签页 ========== */
const activeTab = ref<'lookup' | 'source' | 'search' | 'maintenance'>('lookup')

/* ========== 树形展开状态 ========== */
const expandedNodes = ref<Set<string>>(new Set())

function isExpanded(nodeKey: string): boolean {
  return expandedNodes.value.has(nodeKey)
}

function toggleExpand(nodeKey: string): void {
  if (expandedNodes.value.has(nodeKey)) {
    expandedNodes.value.delete(nodeKey)
  } else {
    expandedNodes.value.add(nodeKey)
  }
}

/* ========== 数据查询 ========== */

function getGenusList(categoryCode: string) {
  return codeGen.lookup.getGenusListByCategory(categoryCode as CategoryCode)
}

function getSpeciesList(categoryCode: string, genusCode: string) {
  return codeGen.lookup.getSpeciesListByGenus(categoryCode as CategoryCode, genusCode)
}

function getGenusCount(categoryCode: string): number {
  return codeGen.lookup.getGenusListByCategory(categoryCode as CategoryCode).length
}

function getSpeciesCount(categoryCode: string, genusCode: string): number {
  return codeGen.lookup.getSpeciesListByGenus(categoryCode as CategoryCode, genusCode).length
}

/* ========== 新增词条 ========== */
const addingAt = ref('')
const addFormName = ref('')
const addFormLatin = ref('')

function startAddGenus(catCode: string): void {
  addingAt.value = catCode
  addFormName.value = ''
  addFormLatin.value = ''
}

function startAddSpecies(genusFullPath: string): void {
  addingAt.value = genusFullPath
  addFormName.value = ''
  addFormLatin.value = ''
}

function confirmAddGenus(catCode: string): void {
  if (!addFormName.value.trim()) return
  codeGen.lookup.addLookupEntry(
    2,
    catCode,
    addFormName.value.trim(),
    addFormLatin.value.trim() || undefined
  )
  addingAt.value = ''
}

function confirmAddSpecies(catCode: string, genusCode: string): void {
  if (!addFormName.value.trim()) return
  const parentPath = `${catCode}${genusCode}`
  codeGen.lookup.addLookupEntry(
    3,
    parentPath,
    addFormName.value.trim(),
    addFormLatin.value.trim() || undefined
  )
  addingAt.value = ''
}

/* ========== 删除 / 切换 ========== */

function handleDeleteGenus(fullPath: string): void {
  if (confirm('删除此属将同时删除其下所有种，确认？')) {
    codeGen.lookup.removeLookupEntry(fullPath)
  }
}

function handleDeleteSpecies(fullPath: string): void {
  codeGen.lookup.removeLookupEntry(fullPath)
}

function handleToggleGenus(fullPath: string): void {
  codeGen.lookup.toggleLookupEnabled(fullPath)
}

function handleToggleSpecies(fullPath: string): void {
  codeGen.lookup.toggleLookupEnabled(fullPath)
}

/* ========== 来源管理 ========== */

const allSources = computed(() => codeGen.lookup.sourceEntries.value)
const newSrcCode = ref('')
const newSrcName = ref('')
const newSrcDesc = ref('')

const editingSourceCode = ref('')
const editSrcName = ref('')
const editSrcDesc = ref('')

function startEditSource(source: any): void {
  editingSourceCode.value = source.code
  editSrcName.value = source.name
  editSrcDesc.value = source.description || ''
}

function confirmEditSource(): void {
  if (!editSrcName.value.trim()) return
  
  const success = codeGen.lookup.updateSource(editingSourceCode.value, {
    name: editSrcName.value.trim(),
    description: editSrcDesc.value.trim()
  })
  
  if (success) {
    editingSourceCode.value = ''
  }
}

function handleAddSourceEntry(): void {
  const code = newSrcCode.value.toUpperCase().trim()
  const name = newSrcName.value.trim()
  if (!code || !name) return

  const entry = codeGen.lookup.addSource(code, name, newSrcDesc.value.trim() || undefined)
  if (entry) {
    newSrcCode.value = ''
    newSrcName.value = ''
    newSrcDesc.value = ''
  }
}

function handleDeleteSource(code: string): void {
  codeGen.lookup.removeSource(code)
}

function handleToggleSource(code: string): void {
  codeGen.lookup.toggleSourceEnabled(code)
}

/* ========== 编码反查 ========== */

const searchCode = ref('')
const searchResult = ref<ResolvedCode | null>(null)

function handleSearch(): void {
  const code = searchCode.value.toUpperCase()
  searchCode.value = code

  if (code.length === 14) {
    searchResult.value = codeGen.resolve(code)
  } else {
    searchResult.value = null
  }
}

/* ========== 维护操作 ========== */

function handleRecalibrate(): void {
  if (confirm('确认执行重校准？这会修复跳号问题，不会影响已有样本数据。')) {
    strain.recalibrateCounters()
    appStore.showNotification('流水号重校准完成', 'success')
  }
}

function handleClearUnusedCounters(): void {
  appStore.showNotification('清理完成', 'success')
}
</script>

<style scoped>
.lookup-manager {
  display: flex;
  flex-direction: column;
  height: 100%;
  max-height: 600px;
}

/* 头部 */
.manager-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 60px 16px 20px;
  border-bottom: 1px solid #e2e8f0;
}

.header-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.header-title h3 {
  font-size: 1rem;
  font-weight: 800;
  color: #0f172a;
  margin: 0;
}

.header-icon {
  font-size: 1.2rem;
}

.header-actions {
  display: flex;
  gap: 6px;
}

.action-btn {
  padding: 6px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #f8fafc;
  font-size: 0.78rem;
  font-weight: 600;
  color: #475569;
  cursor: pointer;
}

.action-btn.active {
  background: #2563eb;
  border-color: #2563eb;
  color: white;
}

.action-btn:hover:not(.active) {
  background: #eff6ff;
  border-color: #2563eb;
  color: #2563eb;
}

/* 维护标签卡片 */
.maintenance-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 16px;
}

.maintenance-card.warning {
  background: #fffbeb;
  border-color: #fde68a;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.card-header h4 {
  margin: 0;
  font-size: 0.95rem;
  color: #0f172a;
}

.card-icon {
  font-size: 1.2rem;
}

.card-desc {
  font-size: 0.82rem;
  color: #64748b;
  line-height: 1.5;
  margin-bottom: 16px;
}

.maintenance-btn {
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 0.85rem;
  font-weight: 700;
  cursor: pointer;
  border: 1px solid transparent;
}

.maintenance-btn.primary {
  background: #2563eb;
  color: white;
}

.maintenance-btn.secondary {
  background: white;
  border-color: #e2e8f0;
  color: #475569;
}

/* 内容区 */
.tab-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}

.edit-input {
  padding: 6px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 0.85rem;
  background: white;
  color: #1e293b;
}

.edit-input.grow {
  flex: 1;
  min-width: 0;
}

.confirm-btn.small, .cancel-btn.small {
  padding: 4px 8px;
  min-width: 32px;
}

/* 树形视图 */
.tree-container {
  font-size: 0.82rem;
}

.tree-node {
  user-select: none;
}

.tree-children {
  padding-left: 20px;
}

.node-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
}

.node-row:hover {
  background: #f8fafc;
}

.node-row.level-1 {
  font-weight: 700;
  color: #0f172a;
  font-size: 0.88rem;
}

.node-row.level-2 {
  color: #1e293b;
}

.node-row.level-3 {
  color: #475569;
  cursor: default;
}

.expand-icon {
  font-size: 0.6rem;
  color: #94a3b8;
  width: 12px;
  text-align: center;
}

.node-code {
  font-family: 'Consolas', monospace;
  font-size: 0.7rem;
  background: #f1f5f9;
  padding: 2px 6px;
  border-radius: 4px;
  color: #475569;
  font-weight: 700;
  min-width: 36px;
  text-align: center;
}

.node-name {
  flex: 1;
}

.node-latin {
  font-size: 0.72rem;
  color: #94a3b8;
  font-style: italic;
}

.node-count {
  font-size: 0.7rem;
  color: #94a3b8;
  margin-left: auto;
}

.node-action-btn {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 0.75rem;
  padding: 2px 6px;
  border-radius: 4px;
}

.node-action-btn.delete {
  color: #dc2626;
}

.node-action-btn.delete:hover {
  background: #fef2f2;
}

.node-action-btn.toggle {
  color: #16a34a;
}

.node-action-btn.toggle.disabled {
  color: #d1d5db;
}

/* 添加行 */
.add-row {
  padding: 4px 10px;
}

.add-row-btn {
  background: none;
  border: 1px dashed #d1d5db;
  border-radius: 6px;
  color: #94a3b8;
  font-size: 0.78rem;
  padding: 6px 12px;
  cursor: pointer;
  width: 100%;
  font-weight: 600;
}

.add-row-btn:hover {
  border-color: #2563eb;
  color: #2563eb;
}

.add-inline {
  display: flex;
  gap: 6px;
  align-items: center;
}

.add-input {
  padding: 6px 10px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  font-size: 0.8rem;
  flex: 1;
}

.add-input.small {
  flex: 0 0 80px;
}

.add-input:focus {
  outline: none;
  border-color: #2563eb;
}

.confirm-btn {
  padding: 6px 12px;
  background: #2563eb;
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 700;
  font-size: 0.82rem;
}

.cancel-btn {
  padding: 6px 10px;
  background: #f1f5f9;
  color: #64748b;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 700;
}

/* 来源字典 */
.source-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.source-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid #f1f5f9;
  border-radius: 8px;
  background: white;
}

.source-row.dimmed {
  opacity: 0.4;
}

.source-code {
  font-family: 'Consolas', monospace;
  font-weight: 700;
  font-size: 0.82rem;
  background: #f1f5f9;
  padding: 4px 8px;
  border-radius: 4px;
  color: #475569;
  min-width: 36px;
  text-align: center;
}

.source-name {
  font-weight: 600;
  color: #1e293b;
  font-size: 0.85rem;
}

.source-desc {
  font-size: 0.75rem;
  color: #94a3b8;
  flex: 1;
}

.source-actions {
  display: flex;
  gap: 4px;
  margin-left: auto;
}

.source-add-area {
  display: flex;
  gap: 6px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #f1f5f9;
}

.empty-hint, .loading-hint {
  padding: 30px;
  text-align: center;
  color: #94a3b8;
  font-size: 0.88rem;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px dashed #e2e8f0;
}

.loading-hint {
  color: #3b82f6;
  font-weight: 500;
}

/* 编码反查 */
.search-area {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.search-code-input {
  padding: 14px 16px;
  border: 2px solid #e2e8f0;
  border-radius: 10px;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 1.2rem;
  font-weight: 700;
  letter-spacing: 3px;
  text-align: center;
  text-transform: uppercase;
}

.search-code-input:focus {
  outline: none;
  border-color: #2563eb;
}

.search-result {
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  overflow: hidden;
}

.result-table {
  width: 100%;
  border-collapse: collapse;
}

.result-table td {
  padding: 10px 14px;
  border-bottom: 1px solid #f1f5f9;
}

.result-table tr:last-child td {
  border-bottom: none;
}

.label-cell {
  font-size: 0.75rem;
  color: #94a3b8;
  font-weight: 600;
  width: 100px;
}

.code-cell {
  font-family: 'Consolas', monospace;
  font-weight: 700;
  color: #2563eb;
  font-size: 0.88rem;
  width: 60px;
}

.name-cell {
  color: #1e293b;
  font-weight: 500;
}

.search-invalid {
  text-align: center;
  color: #dc2626;
  font-size: 0.85rem;
  padding: 12px;
}
</style>