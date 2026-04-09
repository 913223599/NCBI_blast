/**
 * 对照表查询与管理
 *
 * 职责：管理三层对照表（大类/属/种）和来源字典的 CRUD 操作。
 *       不涉及编码生成和流水号逻辑。
 */
import { ref, computed } from 'vue'
import { useStrainStore } from '../stores/strain'
import type {
  CodeLookupEntry,
  SourceEntry,
  LookupLevel,
  CategoryCode,
} from '../types/codeSystem'
import { CATEGORY_MAP } from '../types/codeSystem'
import {
  DEFAULT_CODE_CONFIG,
} from '../data/builtinCodes'

/** 3位字母编码的正则（大写 A-Z） */
const CODE_PATTERN = /^[A-Z]{3}$/

/** 来源编码的正则（2位字母/数字/混合） */
const SOURCE_CODE_PATTERN = /^[A-Z0-9]{2}$/

export function useCodeLookup() {
  const strainStore = useStrainStore()

  // 计算属性同步 Store 状态
  const lookupEntries = computed(() => strainStore.codeLookupEntries)
  const sourceEntries = computed(() => strainStore.sourceEntries)
  const assignMode = ref<'random' | 'sequential'>(DEFAULT_CODE_CONFIG.assignMode)

  /** 内部强制刷新 Store (防抖保存) */
  const markChanged = () => {
    if (!strainStore.isInitialized) return 
    strainStore.autoSave()
  }

  /** 获取指定大类下的所有属 */
  function getGenusListByCategory(categoryCode: CategoryCode): CodeLookupEntry[] {
    return strainStore.codeLookupEntries.filter(
      (entry) =>
        entry.level === 2 &&
        entry.parentPath === categoryCode &&
        entry.enabled
    )
  }

  /** 获取指定属下的所有种 */
  function getSpeciesListByGenus(
    categoryCode: CategoryCode,
    genusCode: string
  ): CodeLookupEntry[] {
    const parentPath = `${categoryCode}${genusCode}`
    return strainStore.codeLookupEntries.filter(
      (entry) =>
        entry.level === 3 &&
        entry.parentPath === parentPath &&
        entry.enabled
    )
  }

  /** 根据完整路径查找词条 */
  function findByFullPath(fullPath: string): CodeLookupEntry | undefined {
    return strainStore.codeLookupEntries.find(
      (entry) => entry.fullPath === fullPath && entry.enabled
    )
  }

  /** 根据大类编码查名称 */
  function getCategoryName(categoryCode: string): string {
    return CATEGORY_MAP[categoryCode] ?? '未知大类'
  }

  /** 根据来源编码查名称 */
  function getSourceName(sourceCode: string): string {
    const entry = strainStore.sourceEntries.find(
      (item) => item.code === sourceCode && item.enabled
    )
    return entry?.name ?? '未知来源'
  }

  /** 翻译完整分类路径：返回 { genusName, speciesName } */
  function resolveTaxonomyPath(
    categoryCode: string,
    genusCode: string,
    speciesCode: string
  ): { genusName: string; speciesName: string } {
    const genusPath = `${categoryCode}${genusCode}`
    const speciesPath = `${genusPath}${speciesCode}`

    const genusEntry = strainStore.codeLookupEntries.find(
      (entry) => entry.fullPath === genusPath
    )
    const speciesEntry = strainStore.codeLookupEntries.find(
      (entry) => entry.fullPath === speciesPath
    )

    return {
      genusName: genusEntry?.name ?? '未知属',
      speciesName: speciesEntry?.name ?? '未知种',
    }
  }

  /** 搜索词条（按名称或学名模糊匹配） */
  function searchEntries(
    keyword: string,
    level?: LookupLevel,
    parentPath?: string
  ): CodeLookupEntry[] {
    const lowerKeyword = keyword.toLowerCase()
    return strainStore.codeLookupEntries.filter((entry) => {
      if (!entry.enabled) return false
      if (level !== undefined && entry.level !== level) return false
      if (parentPath !== undefined && entry.parentPath !== parentPath) return false

      const nameMatch = entry.name.toLowerCase().includes(lowerKeyword)
      const latinMatch = entry.latinName
        ? entry.latinName.toLowerCase().includes(lowerKeyword)
        : false
      return nameMatch || latinMatch
    })
  }

  /* ========== 来源字典管理 ========== */

  /** 获取所有启用的来源 */
  const enabledSources = computed(() =>
    strainStore.sourceEntries.filter((entry) => entry.enabled)
  )

  /** 检查来源编码是否可用 */
  function isSourceCodeAvailable(code: string): boolean {
    if (!SOURCE_CODE_PATTERN.test(code)) return false
    return !strainStore.sourceEntries.some((entry) => entry.code === code)
  }

  /** 添加来源词条 */
  function addSource(
    code: string,
    name: string,
    description?: string
  ): SourceEntry | null {
    if (!isSourceCodeAvailable(code)) return null

    const newEntry: SourceEntry = {
      code: code.toUpperCase(),
      name,
      description,
      isBuiltin: false,
      enabled: true,
    }
    strainStore.sourceEntries.push(newEntry)
    markChanged()
    return newEntry
  }

  /** 更新来源词条 */
  function updateSource(code: string, updates: Partial<Pick<SourceEntry, 'name' | 'description'>>): boolean {
    const entry = strainStore.sourceEntries.find((item) => item.code === code)
    if (!entry) return false
    
    if (updates.name) entry.name = updates.name
    if (updates.description !== undefined) entry.description = updates.description
    
    markChanged()
    return true
  }

  /** 删除来源词条（仅非预置） */
  function removeSource(code: string): boolean {
    const entry = strainStore.sourceEntries.find((item) => item.code === code)
    if (!entry || entry.isBuiltin) return false
    strainStore.sourceEntries = strainStore.sourceEntries.filter(
      (item) => item.code !== code
    )
    markChanged()
    return true
  }

  /** 切换来源启用状态 */
  function toggleSourceEnabled(code: string): boolean {
    const entry = strainStore.sourceEntries.find((item) => item.code === code)
    if (!entry) return false
    entry.enabled = !entry.enabled
    markChanged()
    return true
  }

  /* ========== 对照表管理 ========== */

  /** 检查 3 字母编码在指定父路径下是否可用 */
  function isCodeAvailable(
    code: string,
    level: LookupLevel,
    parentPath: string
  ): boolean {
    if (!CODE_PATTERN.test(code)) return false
    return !strainStore.codeLookupEntries.some(
      (entry) =>
        entry.level === level &&
        entry.parentPath === parentPath &&
        entry.code === code
    )
  }

  /** 分配下一个可用编码（顺序模式） */
  function allocateSequentialCode(
    level: LookupLevel,
    parentPath: string
  ): string | null {
    const existingCodes = new Set(
      strainStore.codeLookupEntries
        .filter(
          (entry) => entry.level === level && entry.parentPath === parentPath
        )
        .map((entry) => entry.code)
    )

    // 从 AAA 开始遍历到 ZZZ
    for (let first = 0; first < 26; first++) {
      for (let second = 0; second < 26; second++) {
        for (let third = 0; third < 26; third++) {
          const candidate =
            String.fromCharCode(65 + first) +
            String.fromCharCode(65 + second) +
            String.fromCharCode(65 + third)
          if (!existingCodes.has(candidate)) {
            return candidate
          }
        }
      }
    }
    return null // 所有编码耗尽（理论上不会发生：17576 种组合）
  }

  /** 分配下一个可用编码（随机模式） */
  function allocateRandomCode(
    level: LookupLevel,
    parentPath: string
  ): string | null {
    const existingCodes = new Set(
      strainStore.codeLookupEntries
        .filter(
          (entry) => entry.level === level && entry.parentPath === parentPath
        )
        .map((entry) => entry.code)
    )

    // 随机尝试，最多 1000 次后回退到顺序
    const MAX_RANDOM_ATTEMPTS = 1000
    for (let attempt = 0; attempt < MAX_RANDOM_ATTEMPTS; attempt++) {
      const candidate =
        String.fromCharCode(65 + Math.floor(Math.random() * 26)) +
        String.fromCharCode(65 + Math.floor(Math.random() * 26)) +
        String.fromCharCode(65 + Math.floor(Math.random() * 26))
      if (!existingCodes.has(candidate)) {
        return candidate
      }
    }

    // 回退到顺序分配
    return allocateSequentialCode(level, parentPath)
  }

  /** 分配编码（根据当前模式） */
  function allocateCode(
    level: LookupLevel,
    parentPath: string
  ): string | null {
    if (assignMode.value === 'random') {
      return allocateRandomCode(level, parentPath)
    }
    return allocateSequentialCode(level, parentPath)
  }

  /** 添加对照表词条 */
  function addLookupEntry(
    level: LookupLevel,
    parentPath: string,
    name: string,
    latinName?: string,
    description?: string,
    manualCode?: string
  ): CodeLookupEntry | null {
    let code: string

    if (manualCode) {
      if (!isCodeAvailable(manualCode, level, parentPath)) return null
      code = manualCode.toUpperCase()
    } else {
      const allocated = allocateCode(level, parentPath)
      if (!allocated) return null
      code = allocated
    }

    const newEntry: CodeLookupEntry = {
      code,
      level,
      parentPath,
      fullPath: `${parentPath}${code}`,
      name,
      latinName,
      description,
      isBuiltin: false,
      enabled: true,
    }

    strainStore.codeLookupEntries.push(newEntry)
    markChanged()
    return newEntry
  }

  /** 删除词条（仅非预置；删除属时同时删除其下所有种） */
  function removeLookupEntry(fullPath: string): boolean {
    const entry = strainStore.codeLookupEntries.find(
      (item) => item.fullPath === fullPath
    )
    if (!entry || entry.isBuiltin) return false

    // 级联删除子级
    strainStore.codeLookupEntries = strainStore.codeLookupEntries.filter(
      (item) =>
        item.fullPath !== fullPath && !item.parentPath.startsWith(fullPath)
    )
    markChanged()
    return true
  }

  /** 切换词条启用状态 */
  function toggleLookupEnabled(fullPath: string): boolean {
    const entry = strainStore.codeLookupEntries.find(
      (item) => item.fullPath === fullPath
    )
    if (!entry) return false
    entry.enabled = !entry.enabled
    markChanged()
    return true
  }

  /* ========== 批量加载/导出 ========== */

  /** 从持久化存储加载 */
  function loadLookupData(
    entries: CodeLookupEntry[],
    sources: SourceEntry[]
  ): void {
    strainStore.codeLookupEntries = [...entries]
    strainStore.sourceEntries = [...sources]
    markChanged()
  }

  /** 导出全部（用于持久化） */
  function exportLookupData(): {
    entries: CodeLookupEntry[]
    sources: SourceEntry[]
  } {
    return {
      entries: [...strainStore.codeLookupEntries],
      sources: [...strainStore.sourceEntries],
    }
  }

  return {
    lookupEntries,
    sourceEntries,
    enabledSources,
    assignMode,

    // 查询
    getGenusListByCategory,
    getSpeciesListByGenus,
    findByFullPath,
    getCategoryName,
    getSourceName,
    resolveTaxonomyPath,
    searchEntries,

    // 来源管理
    isSourceCodeAvailable,
    addSource,
    updateSource,
    removeSource,
    toggleSourceEnabled,

    // 对照表管理
    isCodeAvailable,
    allocateCode,
    addLookupEntry,
    removeLookupEntry,
    toggleLookupEnabled,

    // 持久化
    loadLookupData,
    exportLookupData,
  }
}
