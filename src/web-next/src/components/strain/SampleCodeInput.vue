<template>
  <div class="sample-code-input">
    <!-- 模式切换 -->
    <div class="mode-switch">
      <button type="button" class="mode-btn" :class="{ active: mode === 'auto' }" @click="mode = 'auto'">
        自动编号
      </button>
      <button type="button" class="mode-btn" :class="{ active: mode === 'manual' }" @click="mode = 'manual'">
        手动输入
      </button>
    </div>

    <!-- 手动模式：自由输入 -->
    <div v-if="mode === 'manual'" class="manual-area">
      <input v-model="manualCode" class="code-text-input" placeholder="输入14位样本编号" maxlength="14"
        @input="handleManualInput" />
      <div v-if="manualCode && !manualValid" class="validation-error">
        {{ manualErrors.join('；') }}
      </div>
    </div>

    <!-- 自动模式：级联选择 -->
    <div v-if="mode === 'auto'" class="cascade-area">
      <!-- 第一行：来源 + 大类 -->
      <div class="cascade-row">
        <div class="cascade-field">
          <label class="field-label">来源 (XX)</label>
          <div class="selector-box" @click.stop="openPanel = openPanel === 'source' ? '' : 'source'">
            <span :class="{ placeholder: !selectedSource }">
              {{ selectedSource ? getSourceLabel() : '选择来源' }}
            </span>
            <span class="arrow-icon">▼</span>
            <!-- 来源下拉 -->
            <div v-if="openPanel === 'source'" class="dropdown-panel" @click.stop>
              <input v-model="sourceSearch" class="search-input" placeholder="搜索或输入新来源..." @click.stop />
              <div class="dropdown-list">
                <div v-for="source in filteredSources" :key="source.code" class="dropdown-item"
                  :class="{ selected: selectedSource === source.code }" @click.stop="selectSource(source.code)">
                  <span class="item-code">{{ source.code }}</span>
                  <span class="item-name">{{ source.name }}</span>
                </div>
                <div v-if="filteredSources.length === 0" class="dropdown-empty">
                  无匹配结果
                </div>
              </div>
              <!-- 快速添加来源 -->
              <div class="add-entry-area">
                <button type="button" class="add-btn" @click.stop="showAddSource = true">+ 新增来源</button>
              </div>
              <div v-if="showAddSource" class="inline-add-form" @click.stop>
                <input v-model="newSourceCode" class="mini-input" placeholder="编码(2位)" maxlength="2" />
                <input v-model="newSourceName" class="mini-input grow" placeholder="名称" />
                <button type="button" class="confirm-add-btn" @click.stop="handleAddSource"><svg width="14" height="14"
                    viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"
                    stroke-linejoin="round" aria-hidden="true">
                    <polyline points="20 6 9 17 4 12" />
                  </svg></button>
              </div>
            </div>
          </div>
        </div>

        <div class="cascade-field">
          <label class="field-label">大类 (A)</label>
          <div class="selector-box" @click.stop="openPanel = openPanel === 'category' ? '' : 'category'">
            <span :class="{ placeholder: !selectedCategory }">
              {{ selectedCategory ? getCategoryLabel() : '选择大类' }}
            </span>
            <span class="arrow-icon">▼</span>
            <div v-if="openPanel === 'category'" class="dropdown-panel" @click.stop>
              <div class="dropdown-list">
                <div v-for="(name, code) in CATEGORY_MAP" :key="code" class="dropdown-item"
                  :class="{ selected: selectedCategory === code }" @click.stop="selectCategory(code)">
                  <span class="item-code">{{ code }}</span>
                  <span class="item-name">{{ name }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 第二行：属 + 种 -->
      <div class="cascade-row">
        <div class="cascade-field">
          <label class="field-label">属 (BBB)</label>
          <div class="selector-box" :class="{ disabled: !selectedCategory }"
            @click.stop="selectedCategory && (openPanel = openPanel === 'genus' ? '' : 'genus')">
            <span :class="{ placeholder: !selectedGenus }">
              {{ selectedGenus ? getGenusLabel() : '选择属' }}
            </span>
            <span class="arrow-icon">▼</span>
            <div v-if="openPanel === 'genus'" class="dropdown-panel" @click.stop>
              <input v-model="genusSearch" class="search-input" placeholder="搜索属名或学名..." @click.stop />
              <div class="dropdown-list">
                <div v-for="entry in filteredGenus" :key="entry.code" class="dropdown-item"
                  :class="{ selected: selectedGenus === entry.code }" @click.stop="selectGenus(entry.code)">
                  <span class="item-code">{{ entry.code }}</span>
                  <span class="item-name">{{ entry.name }}</span>
                  <span v-if="entry.latinName" class="item-latin">{{ entry.latinName }}</span>
                </div>
                <div v-if="filteredGenus.length === 0" class="dropdown-empty">
                  无匹配结果
                </div>
              </div>
              <div class="add-entry-area">
                <button type="button" class="add-btn" @click.stop="showAddGenus = true">+ 新增属</button>
              </div>
              <div v-if="showAddGenus" class="inline-add-form" @click.stop>
                <input v-model="newGenusName" class="mini-input grow" placeholder="中文名" />
                <input v-model="newGenusLatin" class="mini-input grow" placeholder="学名(可选)" />
                <button type="button" class="confirm-add-btn" @click.stop="handleAddGenus"><svg width="14" height="14"
                    viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"
                    stroke-linejoin="round" aria-hidden="true">
                    <polyline points="20 6 9 17 4 12" />
                  </svg></button>
              </div>
            </div>
          </div>
        </div>

        <div class="cascade-field">
          <label class="field-label">种 (CCC)</label>
          <div class="selector-box" :class="{ disabled: !selectedGenus }"
            @click.stop="selectedGenus && (openPanel = openPanel === 'species' ? '' : 'species')">
            <span :class="{ placeholder: !selectedSpecies }">
              {{ selectedSpecies ? getSpeciesLabel() : '选择种' }}
            </span>
            <span class="arrow-icon">▼</span>
            <div v-if="openPanel === 'species'" class="dropdown-panel" @click.stop>
              <input v-model="speciesSearch" class="search-input" placeholder="搜索种名或学名..." @click.stop />
              <div class="dropdown-list">
                <div v-for="entry in filteredSpecies" :key="entry.code" class="dropdown-item"
                  :class="{ selected: selectedSpecies === entry.code }" @click.stop="selectSpecies(entry.code)">
                  <span class="item-code">{{ entry.code }}</span>
                  <span class="item-name">{{ entry.name }}</span>
                  <span v-if="entry.latinName" class="item-latin">{{ entry.latinName }}</span>
                </div>
                <div v-if="filteredSpecies.length === 0" class="dropdown-empty">
                  无匹配结果
                </div>
              </div>
              <div class="add-entry-area">
                <button type="button" class="add-btn" @click.stop="showAddSpecies = true">+ 新增种</button>
              </div>
              <div v-if="showAddSpecies" class="inline-add-form" @click.stop>
                <input v-model="newSpeciesName" class="mini-input grow" placeholder="中文名" />
                <input v-model="newSpeciesLatin" class="mini-input grow" placeholder="学名(可选)" />
                <button type="button" class="confirm-add-btn" @click.stop="handleAddSpecies"><svg width="14" height="14"
                    viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"
                    stroke-linejoin="round" aria-hidden="true">
                    <polyline points="20 6 9 17 4 12" />
                  </svg></button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 第三行：传代 + 流水号(自动) + 生成结果 -->
      <div class="cascade-row">
        <div class="cascade-field narrow">
          <label class="field-label">传代 (P)</label>
          <div class="selector-box" @click.stop="openPanel = openPanel === 'passage' ? '' : 'passage'">
            <div class="selector-value">{{ selectedPassage === 0 ? '0 (原始株)' : `${selectedPassage}
              (P${selectedPassage})` }}</div>
            <div class="selector-arrow">▾</div>

            <!-- 传代下拉面板 -->
            <div v-if="openPanel === 'passage'" class="dropdown-panel mini" @click.stop>
              <div class="dropdown-list">
                <div v-for="p in 10" :key="p - 1" class="dropdown-item" :class="{ selected: selectedPassage === p - 1 }"
                  @click.stop="selectedPassage = p - 1; openPanel = ''">
                  <span class="item-code">{{ p - 1 }}</span>
                  <span class="item-name">{{ p - 1 === 0 ? '原始株' : `第 ${p - 1} 代 (P${p - 1})` }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="cascade-field narrow">
          <label class="field-label">流水号</label>
          <div class="serial-display">
            {{ canGenerate ? nextSerialDisplay : '----' }}
          </div>
        </div>
      </div>
    </div>

    <!-- 生成结果展示 -->
    <div v-if="generatedCode" class="result-bar">
      <span class="result-label">样本编号</span>
      <span class="result-code">{{ generatedCode }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import type { CategoryCode, CodeLookupEntry } from '../../types/codeSystem'
import { CATEGORY_MAP } from '../../types/codeSystem'
import { useCodeGenerator } from '../../composables/useCodeGenerator'
import { createLogger } from '../../utils/logger'
import {
  type SampleCodeUpdatePayload,
  buildManualLengthError,
  filterSourcesByKeyword,
  filterTaxonomyEntriesByKeyword,
  replacePassageDigit,
} from './sampleCodeHelpers'
const logger = createLogger('SampleCodeInput')

const props = defineProps<{
  /** 初始编号（编辑场景） */
  initialCode?: string
  /** 初始选择（新建/导入场景，例如来自 BLAST） */
  initialSelections?: {
    source?: string
    category?: string
    genus?: string
    species?: string
    passage?: number
  }
}>()

const emit = defineEmits<{
  (event: 'update', data: SampleCodeUpdatePayload): void
}>()

const codeGen = useCodeGenerator()

/* ========== 状态 ========== */
const mode = ref<'auto' | 'manual'>('auto')
const openPanel = ref('')

// 来源
const selectedSource = ref('')
const sourceSearch = ref('')
const showAddSource = ref(false)
const newSourceCode = ref('')
const newSourceName = ref('')

// 大类
const selectedCategory = ref<CategoryCode | ''>('')

// 属
const selectedGenus = ref('')
const genusSearch = ref('')
const showAddGenus = ref(false)
const newGenusName = ref('')
const newGenusLatin = ref('')

// 种
const selectedSpecies = ref('')
const speciesSearch = ref('')
const showAddSpecies = ref(false)
const newSpeciesName = ref('')
const newSpeciesLatin = ref('')

// 传代
const selectedPassage = ref(0)

// 手动模式
const manualCode = ref('')
const manualValid = ref(false)
const manualErrors = ref<string[]>([])

// 生成结果
const generatedCode = ref('')

/* ========== 计算属性 ========== */

const filteredSources = computed(() =>
  filterSourcesByKeyword(codeGen.lookup.enabledSources.value, sourceSearch.value)
)

const genusList = computed<CodeLookupEntry[]>(() => {
  if (!selectedCategory.value) return []
  return codeGen.lookup.getGenusListByCategory(selectedCategory.value as CategoryCode)
})

const filteredGenus = computed(() =>
  filterTaxonomyEntriesByKeyword(genusList.value, genusSearch.value)
)

const speciesList = computed<CodeLookupEntry[]>(() => {
  if (!selectedCategory.value || !selectedGenus.value) return []
  return codeGen.lookup.getSpeciesListByGenus(
    selectedCategory.value as CategoryCode,
    selectedGenus.value
  )
})

const filteredSpecies = computed(() =>
  filterTaxonomyEntriesByKeyword(speciesList.value, speciesSearch.value)
)

const canGenerate = computed(() =>
  !!(selectedSource.value && selectedCategory.value && selectedGenus.value && selectedSpecies.value)
)

const nextSerialDisplay = computed(() => {
  if (!canGenerate.value) return '----'
  const taxonomyPath = `${selectedCategory.value}${selectedGenus.value}${selectedSpecies.value}`
  const nextValue = codeGen.counter.getCurrentValue(taxonomyPath) + 1
  return String(nextValue).padStart(4, '0')
})

/* ========== 选择处理 ========== */

function getSourceLabel(): string {
  return codeGen.lookup.getSourceName(selectedSource.value)
}

function getCategoryLabel(): string {
  return CATEGORY_MAP[selectedCategory.value] ?? ''
}

function getGenusLabel(): string {
  const entry = codeGen.lookup.findByFullPath(`${selectedCategory.value}${selectedGenus.value}`)
  return entry?.name ?? selectedGenus.value
}

function getSpeciesLabel(): string {
  const entry = codeGen.lookup.findByFullPath(
    `${selectedCategory.value}${selectedGenus.value}${selectedSpecies.value}`
  )
  return entry?.name ?? selectedSpecies.value
}

function selectSource(code: string): void {
  selectedSource.value = code
  openPanel.value = ''
  sourceSearch.value = ''
  tryGenerate()
}

function selectCategory(code: string): void {
  selectedCategory.value = code as CategoryCode
  selectedGenus.value = ''
  selectedSpecies.value = ''
  openPanel.value = ''
  generatedCode.value = ''
  tryGenerate()
}

function selectGenus(code: string): void {
  selectedGenus.value = code
  selectedSpecies.value = ''
  openPanel.value = ''
  genusSearch.value = ''
  generatedCode.value = ''
  tryGenerate()
}

function selectSpecies(code: string): void {
  selectedSpecies.value = code
  openPanel.value = ''
  speciesSearch.value = ''
  tryGenerate()
}

/* ========== 新增词条 ========== */

function handleAddSource(): void {
  const code = newSourceCode.value.toUpperCase().trim()
  const name = newSourceName.value.trim()
  if (!code || !name) return

  const entry = codeGen.lookup.addSource(code, name)
  if (entry) {
    selectedSource.value = entry.code
    showAddSource.value = false
    newSourceCode.value = ''
    newSourceName.value = ''
    tryGenerate()
  }
}

function handleAddGenus(): void {
  if (!selectedCategory.value || !newGenusName.value.trim()) return

  const entry = codeGen.lookup.addLookupEntry(
    2,
    selectedCategory.value,
    newGenusName.value.trim(),
    newGenusLatin.value.trim() || undefined
  )
  if (entry) {
    selectedGenus.value = entry.code
    selectedSpecies.value = ''
    showAddGenus.value = false
    newGenusName.value = ''
    newGenusLatin.value = ''
  }
}

function handleAddSpecies(): void {
  if (!selectedCategory.value || !selectedGenus.value || !newSpeciesName.value.trim()) return

  const parentPath = `${selectedCategory.value}${selectedGenus.value}`
  const entry = codeGen.lookup.addLookupEntry(
    3,
    parentPath,
    newSpeciesName.value.trim(),
    newSpeciesLatin.value.trim() || undefined
  )
  if (entry) {
    selectedSpecies.value = entry.code
    showAddSpecies.value = false
    newSpeciesName.value = ''
    newSpeciesLatin.value = ''
    tryGenerate()
  }
}

/* ========== 生成与手动输入 ========== */

function tryGenerate(): void {
  if (!canGenerate.value) {
    emit('update', {
      sampleCode: '',
      codeSource: selectedSource.value,
      codeCategory: selectedCategory.value as string,
      codeGenus: selectedGenus.value,
      codeSpecies: selectedSpecies.value,
      codePassage: selectedPassage.value,
      codeSerial: 0,
      generationRequest: null
    })
    return
  }

  try {
    const request = {
      sourceCode: selectedSource.value,
      categoryCode: selectedCategory.value as CategoryCode,
      genusCode: selectedGenus.value,
      speciesCode: selectedSpecies.value,
      passage: selectedPassage.value,
    }

    // 仅执行预览
    const code = codeGen.preview(request)
    generatedCode.value = code

    // 发送预览数据和请求凭据
    const taxonomyPath = `${selectedCategory.value}${selectedGenus.value}${selectedSpecies.value}`
    const serial = codeGen.counter.getCurrentValue(taxonomyPath) + 1 // 预览值

    emit('update', {
      sampleCode: code,
      codeSource: selectedSource.value,
      codeCategory: selectedCategory.value as string,
      codeGenus: selectedGenus.value,
      codeSpecies: selectedSpecies.value,
      codePassage: selectedPassage.value,
      codeSerial: serial,
      generationRequest: request
    })
  } catch (error) {
    logger.error('[SampleCodeInput] 预览失败:', error)
  }
}

function handleManualInput(): void {
  const code = manualCode.value.toUpperCase()
  manualCode.value = code

  if (code.length === 14) {
    const result = codeGen.validateCode(code)
    manualValid.value = result.valid
    manualErrors.value = result.errors

    if (result.valid) {
      generatedCode.value = code
      const parsed = codeGen.parse(code)
      if (parsed) {
        emit('update', {
          sampleCode: code,
          codeSource: parsed.source,
          codeCategory: parsed.category,
          codeGenus: parsed.genus,
          codeSpecies: parsed.species,
          codePassage: parsed.passage,
          codeSerial: parsed.serial
          // 手动模式不提供 generationRequest，因为不需要 commit 计数器
        })
      }
    } else {
      generatedCode.value = ''
    }
  } else {
    manualValid.value = false
    manualErrors.value = buildManualLengthError(code.length)
    generatedCode.value = ''
  }
}

/* ========== 传代变化时重新生成 ========== */
watch(selectedPassage, () => {
  if (canGenerate.value && generatedCode.value) {
    // 传代变化不消耗新流水号，只替换P位
    const base = generatedCode.value
    if (base.length === 14) {
      const updated = replacePassageDigit(base, selectedPassage.value)
      generatedCode.value = updated

      const taxonomyPath = `${selectedCategory.value}${selectedGenus.value}${selectedSpecies.value}`
      const serial = codeGen.counter.getCurrentValue(taxonomyPath)

      const request = {
        sourceCode: selectedSource.value,
        categoryCode: selectedCategory.value as CategoryCode,
        genusCode: selectedGenus.value,
        speciesCode: selectedSpecies.value,
        passage: selectedPassage.value,
      }

      emit('update', {
        sampleCode: updated,
        codeSource: selectedSource.value,
        codeCategory: selectedCategory.value as string,
        codeGenus: selectedGenus.value,
        codeSpecies: selectedSpecies.value,
        codePassage: selectedPassage.value,
        codeSerial: serial,
        generationRequest: request
      })
    }
  }
})

/* ========== 初始化 ========== */
onMounted(() => {
  if (props.initialCode) {
    const parsed = codeGen.parse(props.initialCode)
    if (parsed) {
      mode.value = 'auto'
      selectedSource.value = parsed.source
      selectedCategory.value = parsed.category
      selectedGenus.value = parsed.genus
      selectedSpecies.value = parsed.species
      selectedPassage.value = parsed.passage
      generatedCode.value = props.initialCode
    } else {
      mode.value = 'manual'
      manualCode.value = props.initialCode
    }
  } else if (props.initialSelections) {
    // 自动应用预填充的选项（例如来自 BLAST 的匹配结果）
    mode.value = 'auto'
    if (props.initialSelections.source) selectedSource.value = props.initialSelections.source
    if (props.initialSelections.category) selectedCategory.value = props.initialSelections.category as CategoryCode
    if (props.initialSelections.genus) selectedGenus.value = props.initialSelections.genus
    if (props.initialSelections.species) selectedSpecies.value = props.initialSelections.species
    if (props.initialSelections.passage !== undefined) selectedPassage.value = props.initialSelections.passage

    // 立即尝试生成编号
    setTimeout(() => {
      // 关键修复：如果来源为空，自动选择第一个可用来源（XX）
      if (!selectedSource.value) {
        const firstSource = codeGen.lookup.enabledSources.value[0]
        if (firstSource) {
          selectedSource.value = firstSource.code
        }
      }
      tryGenerate()
    }, 0)
  }

  document.addEventListener('click', closeAllPanels)
})

// 监听初始选择 props 的变化，支持动态预填
watch(() => props.initialSelections, (newVal) => {
  if (newVal) {
    mode.value = 'auto'
    if (newVal.source) selectedSource.value = newVal.source
    if (newVal.category) selectedCategory.value = newVal.category as CategoryCode
    if (newVal.genus) selectedGenus.value = newVal.genus
    if (newVal.species) selectedSpecies.value = newVal.species
    if (newVal.passage !== undefined) selectedPassage.value = newVal.passage

    setTimeout(tryGenerate, 0)
  }
}, { deep: true })

onUnmounted(() => {
  document.removeEventListener('click', closeAllPanels)
})

function closeAllPanels(): void {
  openPanel.value = ''
}
</script>

<style scoped src="./sampleCodeInput.css"></style>
