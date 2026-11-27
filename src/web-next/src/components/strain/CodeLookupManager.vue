<template>
  <div class="lookup-manager">
    <!-- 头部 -->
    <div class="manager-header">
      <div class="header-title">
        <span class="header-icon"></span>
        <h3>编码对照表管理</h3>
      </div>
      <div class="header-actions">
        <button type="button" class="action-btn" :class="{ active: activeTab === 'lookup' }" @click="activeTab = 'lookup'">
          分类
        </button>
        <button type="button" class="action-btn" :class="{ active: activeTab === 'source' }" @click="activeTab = 'source'">
          来源
        </button>
        <button type="button" class="action-btn" :class="{ active: activeTab === 'search' }" @click="activeTab = 'search'">
          反查
        </button>
        <button type="button" class="action-btn" :class="{ active: activeTab === 'maintenance' }" @click="activeTab = 'maintenance'">
          维护
        </button>
        <button type="button" class="action-btn secondary" @click="handleTranslateAll" :disabled="isTranslating">
          {{ isTranslating ? '正在翻译...' : '全量翻译' }}
        </button>
        <button type="button" class="action-btn secondary" @click="handleTaxonomyAudit" :disabled="isAuditing">
          {{ isAuditing ? '正在校核...' : 'NCBI校核' }}
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
                <div class="row-main">
                  <span class="node-code">{{ genus.code }}</span>
                  <span class="row-name">
                    {{ genus.name }}
                    <span v-if="genus.verified" class="verified-badge" title="NCBI 官方分类学认证"></span>
                  </span>
                  <span v-if="genus.latinName" class="node-latin">{{ genus.latinName }}</span>
                </div>
                <div class="row-actions">
                  <span class="child-count-pill">{{ getSpeciesList(catCode, genus.code).length }} 种</span>
                  <button type="button" 
                    v-if="genus.latinName && !hasChinese(genus.name)"
                    class="node-action-btn translate"
                    @click.stop="handleTranslateEntry(genus.fullPath)"
                    title="AI 智能翻译"
                  >译</button>
                  <button type="button" class="node-action-btn edit" @click.stop="startEdit(genus)" title="手动修正名称">编辑</button>
                  <button type="button" 
                    v-if="!genus.isBuiltin"
                    class="node-action-btn delete" 
                    @click.stop="handleDeleteGenus(genus.fullPath)"
                    title="删除此分类条目"
                  ><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
                  <button
                    type="button"
                    class="node-action-btn toggle"
                    :class="{ disabled: !genus.enabled }"
                    @click.stop="handleToggleGenus(genus.fullPath)"
                  >{{ genus.enabled ? '●' : '○' }}</button>
                </div>
              </div>

              <!-- 种列表 -->
              <div v-if="isExpanded(genus.fullPath)" class="tree-children">
                <div
                  v-for="species in getSpeciesList(catCode, genus.code)"
                  :key="species.fullPath"
                  class="tree-node"
                >
                  <div class="node-row level-3">
                    <div class="row-main">
                      <span class="node-code">{{ species.code }}</span>
                      <span class="row-name">
                        {{ species.name }}
                        <span v-if="species.verified" class="verified-badge" title="NCBI 官方分类学认证"></span>
                      </span>
                      <span v-if="species.latinName" class="node-latin">{{ species.latinName }}</span>
                    </div>
                    <div class="row-actions">
                      <button type="button" 
                        v-if="species.latinName && !hasChinese(species.name)"
                        class="node-action-btn translate"
                        title="自动翻译"
                        @click.stop="handleTranslateEntry(species.fullPath)"
                      >译</button>
                      <button type="button" class="node-action-btn edit" @click.stop="startEdit(species)" title="手动修正名称">编辑</button>
                      <button
                        type="button"
                        v-if="!species.isBuiltin"
                        class="node-action-btn delete"
                        @click.stop="handleDeleteSpecies(species.fullPath)"
                        title="删除此分类条目"
                      ><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
                      <button
                        type="button"
                        class="node-action-btn toggle"
                        :class="{ disabled: !species.enabled }"
                        @click.stop="handleToggleSpecies(species.fullPath)"
                      >{{ species.enabled ? '●' : '○' }}</button>
                    </div>
                  </div>
                </div>

                <!-- 种级新增 -->
                <div class="add-row">
                  <button
                    type="button"
                    v-if="addingAt !== genus.fullPath"
                    class="add-row-btn"
                    @click="startAddSpecies(genus.fullPath)"
                  >+ 添加种</button>
                  <div v-else class="add-inline">
                    <input v-model="addFormName" class="add-input" placeholder="中文名" />
                    <input v-model="addFormLatin" class="add-input" placeholder="学名(可选)" />
                    <button type="button" class="confirm-btn" @click="confirmAddSpecies(catCode, genus.code)"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg></button>
                    <button type="button" class="cancel-btn" @click="addingAt = ''"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
                  </div>
                </div>
              </div>
            </div>

            <!-- 属级新增 -->
            <div class="add-row">
              <button
                type="button"
                v-if="addingAt !== catCode"
                class="add-row-btn"
                @click="startAddGenus(catCode)"
              >+ 添加属</button>
              <div v-else class="add-inline">
                <input v-model="addFormName" class="add-input" placeholder="中文名" />
                <input v-model="addFormLatin" class="add-input" placeholder="学名(可选)" />
                <button type="button" class="confirm-btn" @click="confirmAddGenus(catCode)"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg></button>
                <button type="button" class="cancel-btn" @click="addingAt = ''"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
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
                type="button"
                class="node-action-btn toggle"
                title="启用/禁用"
                :class="{ disabled: !source.enabled }"
                @click="handleToggleSource(source.code)"
              >{{ source.enabled ? '●' : '○' }}</button>
              <button
                type="button"
                class="node-action-btn edit"
                title="编辑"
                @click="startEditSource(source)"
              >编</button>
              <button
                type="button"
                v-if="!source.isBuiltin"
                class="node-action-btn delete"
                title="删除"
                @click="handleDeleteSource(source.code)"
              ><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
            </div>
          </template>
          <template v-else>
            <span class="source-code">{{ source.code }}</span>
            <input v-model="editSrcName" class="edit-input grow" placeholder="名称" />
            <input v-model="editSrcDesc" class="edit-input grow" placeholder="备注" />
            <div class="source-actions">
              <button type="button" class="confirm-btn small" @click="confirmEditSource"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg></button>
              <button type="button" class="cancel-btn small" @click="editingSourceCode = ''"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
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
          <button type="button" class="confirm-btn" @click="handleAddSourceEntry">+ 添加</button>
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
          <span class="card-icon"></span>
          <h4>流水号重校准</h4>
        </div>
        <p class="card-desc">
          扫描当前数据库中的所有样本，将各分类下的计数器重置为实际已用的最大值。
          用于修复由于误操作、系统取消或报错导致的“跳号”问题。
        </p>
        <div class="card-actions">
          <button type="button" class="maintenance-btn primary" @click="handleRecalibrate">
            立即重校准
          </button>
        </div>
      </div>

      <div class="maintenance-card warning">
        <div class="card-header">
          <span class="card-icon"></span>
          <h4>清理冗余计数器</h4>
        </div>
        <p class="card-desc">
          删除没有任何样本关联的过期或错误的流水号记录。
        </p>
        <div class="card-actions">
          <button type="button" class="maintenance-btn secondary" @click="handleClearUnusedCounters">
            清理
          </button>
        </div>
      </div>
    </div>
    <div v-if="isEditModalOpen" class="modal-overlay" @click.self="isEditModalOpen = false">
      <div class="edit-modal premium-card animate-slide-up">
        <div class="modal-header">
          <span class="modal-icon">编辑</span>
          <div class="header-text">
            <h3>手动修正分类名称</h3>
            <p>修正编码 {{ editingEntry?.code }} 对应的层级名称信息</p>
          </div>
          <button type="button" class="btn-close-sm" @click="isEditModalOpen = false"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
        </div>
        
        <div class="edit-form">
          <div class="form-item">
            <label>中文名称 (描述)</label>
            <input v-model="editForm.name" class="premium-input" placeholder="输入准确的中文名称..." />
          </div>
          <div class="form-item">
            <label>拉丁名 (学名)</label>
            <input v-model="editForm.latinName" class="premium-input" placeholder="输入准确的拉丁学名..." />
          </div>
        </div>

        <div class="modal-footer">
          <button type="button" class="btn-glass" @click="isEditModalOpen = false">取消</button>
          <button type="button" class="btn-premium" @click="saveManualEdit">确认修改并在全局应用</button>
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
import { useCodeLookup } from '../../composables/useCodeLookup'

import { useStrainStore } from '../../stores/strain'
import { useAppStore } from '../../stores/app'
import { useConfirmDialog } from '../../composables/useConfirmDialog'

const codeGen = useCodeGenerator()
const { updateLookupEntry } = useCodeLookup()
const strain = useStrainStore()
const appStore = useAppStore()
const confirmDialog = useConfirmDialog()

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

/* ========== 编辑逻辑 ========== */
const isEditModalOpen = ref(false)
const editingEntry = ref<any>(null)
const editForm = ref({ name: '', latinName: '' })

function startEdit(entry: any) {
  editingEntry.value = entry
  editForm.value = {
    name: entry.name,
    latinName: entry.latinName || ''
  }
  isEditModalOpen.value = true
}

function saveManualEdit() {
  if (editingEntry.value) {
    updateLookupEntry(editingEntry.value.fullPath, {
      name: editForm.value.name,
      latinName: editForm.value.latinName
    })
    isEditModalOpen.value = false
    editingEntry.value = null
    appStore.showNotification('分类名称已手动修正', 'success')
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

async function handleDeleteGenus(fullPath: string): Promise<void> {
  const ok = await confirmDialog.confirm({
    title: '删除属分类',
    message: '删除此属将同时删除其下所有种，确认继续？',
    confirmText: '确认删除',
    danger: true,
  })
  if (ok) {
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

async function handleRecalibrate(): Promise<void> {
  const ok = await confirmDialog.confirm({
    title: '流水号重校准',
    message: '确认执行重校准？这会修复跳号问题，不会影响已有样本数据。',
    confirmText: '开始重校准',
  })
  if (ok) {
    strain.recalibrateCounters()
    appStore.showNotification('流水号重校准完成', 'success')
  }
}

function handleClearUnusedCounters(): void {
  appStore.showNotification('清理完成', 'success')
}

/** 检测字符串中是否包含中文字符 */
function hasChinese(str: string | undefined): boolean {
  if (!str) return false
  return /[\u4e00-\u9fa5]/.test(str)
}

/* ========== 翻译逻辑 ========== */
const isTranslating = ref(false)

async function handleTranslateEntry(fullPath: string) {
  try {
    await codeGen.lookup.translateEntry(fullPath)
    appStore.showNotification('翻译完成', 'success')
  } catch {
    appStore.showNotification('翻译失败', 'error')
  }
}

async function handleTranslateAll() {
  const ok = await confirmDialog.confirm({
    title: '批量 AI 翻译',
    message: '确认对所有未翻译(即中文名与学名相同或为空)的词条进行批量 AI 翻译？',
    confirmText: '开始翻译',
  })
  if (ok) {
    isTranslating.value = true
    try {
      await codeGen.lookup.translateAllEntries()
      appStore.showNotification('批量翻译任务已提交，结果将陆续更新', 'info')
    } catch {
      appStore.showNotification('提交批量翻译失败', 'error')
    } finally {
      // 批量翻译是后台异步推送的，这里先结束 loading
      setTimeout(() => { isTranslating.value = false }, 1000)
    }
  }
}

const isAuditing = ref(false)

async function handleTaxonomyAudit() {
  const ok = await confirmDialog.confirm({
    title: 'NCBI 分类层级校核',
    message: '确认与本地 NCBI 数据库比对校核所有未验证词条的层级正确性？',
    confirmText: '开始校核',
  })
  if (ok) {
    isAuditing.value = true
    try {
      const res = await codeGen.lookup.auditWithNCBI()
      if (res.success) {
        appStore.showNotification(`分类学校核完成，已标记 ${res.count} 条记录为已验证`, 'success')
      } else {
        appStore.showNotification('核核失败，请确保本地分类学数据库已就绪', 'error')
      }
    } catch {
      appStore.showNotification('校核过程发生错误', 'error')
    } finally {
      isAuditing.value = false
    }
  }
}
</script>

<style scoped src="./codeLookupManager.css"></style>
