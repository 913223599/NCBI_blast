/**
 * useFreezerDetail - 冻存冰箱层级导航、占用率统计、拖拽框选与样本详情状态管理
 * 从 FreezerDetailPanel.vue 拆解而出，保持单一职责与完整响应式语义。
 */
import { computed, onMounted, onUnmounted, ref, toRaw, watch } from 'vue'
import { useI18n } from '../../../locales'
import {
  useStrainStore,
  type FreezerBox,
  type FreezerCabinet,
  type FreezerDrawer,
  type FreezerShelf,
  type StrainRecord,
} from '../../../stores/strain'
import { useAppStore } from '../../../stores/app'

export type FreezerBoxPosition = FreezerBox['positions'][number]

export interface EntryPositionPayload {
  freezerId: string
  shelfId: string
  cabinetId: string
  drawerId: string
  boxId: string
  position: string
  selectedPositions?: string[]
}

export function useFreezerDetail() {
  const { t } = useI18n()
  const strain = useStrainStore()
  const appStore = useAppStore()

  // 层级导航状态
  const currentLevel = ref<'shelf' | 'cabinet' | 'drawer' | 'box'>('shelf')
  const selectedShelf = ref<FreezerShelf | null>(null)
  const selectedCabinet = ref<FreezerCabinet | null>(null)
  const selectedDrawer = ref<FreezerDrawer | null>(null)
  const activeBoxId = ref<string>('')

  // 对话框与悬停状态
  const showEntryDialog = ref(false)
  const showDetailDialog = ref(false)
  const showEditDialog = ref(false)
  const selectedSample = ref<StrainRecord | null>(null)
  const hoveredSample = ref<StrainRecord | null>(null)
  const entryPosition = ref<EntryPositionPayload | null>(null)

  // 拖拽多选状态
  const isSelecting = ref(false)
  const selectionStartIdx = ref<number | null>(null)
  const selectedIndices = ref<Set<number>>(new Set())

  const totalPositions = computed(() => {
    if (!strain.activeFreezer) return 0
    let total = 0
    for (const shelf of strain.activeFreezer.shelves) {
      for (const cabinet of shelf.cabinets) {
        for (const drawer of cabinet.drawers) {
          for (const box of drawer.boxes) {
            total += box.rows * box.cols
          }
        }
      }
    }
    return total
  })

  const activeBox = computed<FreezerBox | null>(() => {
    if (!selectedDrawer.value || !activeBoxId.value) return null
    return selectedDrawer.value.boxes.find((b) => b.id === activeBoxId.value) || null
  })

  function getTotalCabinets(): number {
    if (!strain.activeFreezer) return 0
    let total = 0
    for (const shelf of strain.activeFreezer.shelves) {
      total += shelf.cabinets.length
    }
    return total
  }

  function getTotalDrawers(): number {
    if (!strain.activeFreezer) return 0
    let total = 0
    for (const shelf of strain.activeFreezer.shelves) {
      for (const cabinet of shelf.cabinets) {
        total += cabinet.drawers.length
      }
    }
    return total
  }

  function getCabinetStats(shelf: FreezerShelf): string {
    let totalDrawers = 0
    let totalBoxes = 0
    for (const cabinet of shelf.cabinets) {
      totalDrawers += cabinet.drawers.length
      for (const drawer of cabinet.drawers) {
        totalBoxes += drawer.boxes.length
      }
    }
    return `${totalDrawers} 抽屉 · ${totalBoxes} 盒`
  }

  function getDrawerCount(cabinet: FreezerCabinet): number {
    return (cabinet.drawers || []).length
  }

  function getBoxUsedCountAndTotal(box: FreezerBox | null | undefined) {
    if (!box || !box.positions) return { used: 0, total: 0 }
    const total = box.rows * box.cols
    const used = box.positions.filter((p) => p.occupied).length
    return { used, total }
  }

  function getShelfUsage(shelf: FreezerShelf): number {
    let totalCount = 0
    let usedCount = 0
    shelf.cabinets.forEach((c) => {
      c.drawers.forEach((d) => {
        d.boxes.forEach((b) => {
          const stats = getBoxUsedCountAndTotal(b)
          totalCount += stats.total
          usedCount += stats.used
        })
      })
    })
    return totalCount > 0 ? (usedCount / totalCount) * 100 : 0
  }

  function getCabinetUsage(_shelfId: string, cabinet: FreezerCabinet): number {
    let totalCount = 0
    let usedCount = 0
    cabinet.drawers.forEach((d) => {
      d.boxes.forEach((b) => {
        const stats = getBoxUsedCountAndTotal(b)
        totalCount += stats.total
        usedCount += stats.used
      })
    })
    return totalCount > 0 ? (usedCount / totalCount) * 100 : 0
  }

  function getDrawerUsage(_shelfId: string, _cabinetId: string, drawer: FreezerDrawer): number {
    let totalCount = 0
    let usedCount = 0
    drawer.boxes.forEach((b) => {
      const stats = getBoxUsedCountAndTotal(b)
      totalCount += stats.total
      usedCount += stats.used
    })
    return totalCount > 0 ? (usedCount / totalCount) * 100 : 0
  }

  function getBoxUsage(_shelfId: string | undefined, _cabinetId: string | undefined, _drawerId: string | undefined, box: FreezerBox): number {
    const stats = getBoxUsedCountAndTotal(box)
    return stats.total > 0 ? (stats.used / stats.total) * 100 : 0
  }

  function isPositionOccupied(shelfId: string, cabinetId: string, drawerId: string, boxId: string, posLabel: string): boolean {
    if (!strain.activeFreezer) return false
    return strain.records.some(
      (r: StrainRecord) =>
        r.freezerId === strain.activeFreezer!.id &&
        r.shelfId === shelfId &&
        r.cabinetId === cabinetId &&
        r.drawerId === drawerId &&
        r.boxId === boxId &&
        r.position === posLabel
    )
  }

  function getBoxUsedCount(box: FreezerBox | null | undefined): number {
    if (!box || !box.positions) return 0
    return box.positions.filter((p) => p.occupied).length
  }

  function getSteppedUsage(percentage: number): number {
    if (percentage <= 0) return 0
    const stepped = Math.ceil(percentage / 5) * 5
    return Math.min(stepped, 100)
  }

  function getUsageLevel(percentage: number): string {
    if (percentage >= 80) return 'high'
    if (percentage >= 50) return 'medium'
    if (percentage > 0) return 'low'
    return 'empty'
  }

  function selectShelf(shelf: FreezerShelf) {
    selectedShelf.value = shelf
    selectedCabinet.value = null
    selectedDrawer.value = null
    currentLevel.value = 'cabinet'
  }

  function selectCabinet(cabinet: FreezerCabinet) {
    selectedCabinet.value = cabinet
    selectedDrawer.value = null
    currentLevel.value = 'drawer'
  }

  function selectDrawer(drawer: FreezerDrawer) {
    selectedDrawer.value = drawer
    currentLevel.value = 'box'
    hoveredSample.value = null
    if (drawer.boxes.length > 0 && drawer.boxes[0]) {
      activeBoxId.value = drawer.boxes[0].id
    }
    selectedIndices.value.clear()
  }

  function handlePositionHover(position: FreezerBoxPosition | null | undefined, _box?: FreezerBox | null) {
    if (position?.sampleId) {
      hoveredSample.value = strain.records.find((r) => r.id === position.sampleId) || null
    } else {
      hoveredSample.value = null
    }
  }

  function getFilteredMetadata(metadata: Record<string, unknown> | null | undefined): Record<string, unknown> {
    if (!metadata) return {}
    const excludeKeys = ['description', 'notes', 'storageDate', 'isExpression']
    const filtered: Record<string, unknown> = {}
    Object.keys(metadata).forEach((key) => {
      if (!excludeKeys.includes(key) && metadata[key]) {
        filtered[key] = metadata[key]
      }
    })
    return filtered
  }

  function translateMetadataKey(key: string): string {
    return t(`metadata.${key}`)
  }

  function navigateToLevel(level: 'shelf' | 'cabinet' | 'drawer' | 'box') {
    currentLevel.value = level
    if (level === 'shelf') {
      selectedShelf.value = null
      selectedCabinet.value = null
      selectedDrawer.value = null
      activeBoxId.value = ''
    } else if (level === 'cabinet' && selectedShelf.value) {
      selectedCabinet.value = null
      selectedDrawer.value = null
      activeBoxId.value = ''
    } else if (level === 'drawer' && selectedCabinet.value) {
      selectedDrawer.value = null
      activeBoxId.value = ''
    }
  }

  function handlePositionLeftClick(position: FreezerBoxPosition, box: FreezerBox) {
    if (selectedIndices.value.size > 1) return

    if (position?.sampleId) {
      const sample = strain.records.find((r) => r.id === position.sampleId)
      if (sample) {
        selectedSample.value = sample
        showDetailDialog.value = true
        return
      }
    }

    if (!strain.activeFreezer || !selectedShelf.value || !selectedCabinet.value || !selectedDrawer.value) return
    selectedIndices.value.clear()
    entryPosition.value = {
      freezerId: strain.activeFreezer.id,
      shelfId: selectedShelf.value.id,
      cabinetId: selectedCabinet.value.id,
      drawerId: selectedDrawer.value.id,
      boxId: box.id,
      position: position.label,
    }
    showEntryDialog.value = true
  }

  function handlePositionMouseDown(idx: number, pos: FreezerBoxPosition) {
    if (pos.occupied) return
    isSelecting.value = true
    selectionStartIdx.value = idx
    selectedIndices.value.clear()
    selectedIndices.value.add(idx)
  }

  function handlePositionMouseEnter(idx: number, pos: FreezerBoxPosition) {
    if (!isSelecting.value) {
      handlePositionHover(pos, activeBox.value)
      return
    }
    if (selectionStartIdx.value === null || !activeBox.value || !selectedShelf.value || !selectedCabinet.value || !selectedDrawer.value) return

    const startIdx = selectionStartIdx.value
    const cols = activeBox.value.cols
    const minRow = Math.min(Math.floor(startIdx / cols), Math.floor(idx / cols))
    const maxRow = Math.max(Math.floor(startIdx / cols), Math.floor(idx / cols))
    const minCol = Math.min(startIdx % cols, idx % cols)
    const maxCol = Math.max(startIdx % cols, idx % cols)

    const newSelection = new Set<number>()
    for (let r = minRow; r <= maxRow; r++) {
      for (let c = minCol; c <= maxCol; c++) {
        const currentIdx = r * cols + c
        const currentPos = activeBox.value.positions[currentIdx]
        if (
          currentPos &&
          !isPositionOccupied(
            selectedShelf.value.id,
            selectedCabinet.value.id,
            selectedDrawer.value.id,
            activeBox.value.id,
            currentPos.label
          )
        ) {
          newSelection.add(currentIdx)
        }
      }
    }
    selectedIndices.value = newSelection
  }

  function handleGlobalMouseUp() {
    if (!isSelecting.value) return
    isSelecting.value = false

    if (
      selectedIndices.value.size > 1 &&
      activeBox.value &&
      strain.activeFreezer &&
      selectedShelf.value &&
      selectedCabinet.value &&
      selectedDrawer.value
    ) {
      const positions = Array.from(selectedIndices.value)
        .toSorted((a, b) => a - b)
        .map((idx) => activeBox.value!.positions[idx]?.label)
        .filter((lbl): lbl is string => Boolean(lbl))

      if (positions.length === 0) return
      entryPosition.value = {
        freezerId: strain.activeFreezer.id,
        shelfId: selectedShelf.value.id,
        cabinetId: selectedCabinet.value.id,
        drawerId: selectedDrawer.value.id,
        boxId: activeBox.value.id,
        position: positions[0]!,
        selectedPositions: positions,
      }
      showEntryDialog.value = true
    }
  }

  function clearSelection() {
    selectedIndices.value.clear()
  }

  function getSampleByPosition(
    freezerId: string,
    shelfId: string,
    cabinetId: string,
    drawerId: string,
    boxId: string,
    position: string
  ): StrainRecord | null {
    return (
      strain.records.find(
        (r: StrainRecord) =>
          r.freezerId === freezerId &&
          r.shelfId === shelfId &&
          r.cabinetId === cabinetId &&
          r.drawerId === drawerId &&
          r.boxId === boxId &&
          r.position === position
      ) || null
    )
  }

  function updateBoxOccupancy() {
    if (!strain.activeFreezer) return
    const rawFreezer = toRaw(strain.activeFreezer)

    for (const shelf of rawFreezer.shelves) {
      for (const cabinet of shelf.cabinets) {
        for (const drawer of cabinet.drawers) {
          for (const box of drawer.boxes) {
            for (const pos of box.positions) {
              pos.occupied = false
              pos.sampleId = undefined
            }
          }
        }
      }
    }

    const boxMap = new Map<string, (typeof rawFreezer.shelves)[0]['cabinets'][0]['drawers'][0]['boxes'][0]>()
    for (const shelf of rawFreezer.shelves) {
      for (const cabinet of shelf.cabinets) {
        for (const drawer of cabinet.drawers) {
          for (const box of drawer.boxes) {
            boxMap.set(box.id, box)
          }
        }
      }
    }

    const rawRecords = toRaw(strain.records)
    const freezerId = rawFreezer.id
    for (const record of rawRecords) {
      if (record.freezerId !== freezerId || !record.boxId || !record.position) continue
      const box = boxMap.get(record.boxId)
      if (!box) continue
      const pos = box.positions.find((p) => p.label === record.position)
      if (pos) {
        pos.occupied = true
        pos.sampleId = record.id
      }
    }

    strain.freezers = [...strain.freezers]
  }

  function handleSampleSaved() {
    updateBoxOccupancy()
  }

  function editFreezer() {
    showEditDialog.value = true
  }

  function handleFreezerUpdated() {
    // Dialog 内已发送全局通知
  }

  function closeDetail() {
    showDetailDialog.value = false
    selectedSample.value = null
  }

  function handleSampleDeleted() {
    closeDetail()
    updateBoxOccupancy()
  }

  function handleOutsideClick(e: MouseEvent) {
    if (selectedIndices.value.size === 0 || isSelecting.value) return
    const target = e.target as HTMLElement
    const gridArea = document.querySelector('.box-grid-area')
    if (gridArea?.contains(target)) return
    const dialog = document.querySelector('.dialog-overlay')
    if (dialog?.contains(target)) return
    clearSelection()
  }

  function addShelf() {
    appStore.showNotification('添加层功能开发中', 'info')
  }

  watch(
    () => strain.activeFreezerId,
    () => {
      currentLevel.value = 'shelf'
      selectedShelf.value = null
      selectedCabinet.value = null
      selectedDrawer.value = null
      activeBoxId.value = ''
      selectedIndices.value.clear()
      updateBoxOccupancy()
    }
  )

  watch(
    () => strain.records.length,
    () => {
      updateBoxOccupancy()
    }
  )

  onMounted(() => {
    document.addEventListener('mousedown', handleOutsideClick)
    updateBoxOccupancy()
  })

  onUnmounted(() => {
    document.removeEventListener('mousedown', handleOutsideClick)
  })

  return {
    t,
    strain,
    currentLevel,
    selectedShelf,
    selectedCabinet,
    selectedDrawer,
    activeBoxId,
    showEntryDialog,
    showDetailDialog,
    showEditDialog,
    selectedSample,
    hoveredSample,
    entryPosition,
    isSelecting,
    selectedIndices,
    totalPositions,
    activeBox,
    getTotalCabinets,
    getTotalDrawers,
    getCabinetStats,
    getDrawerCount,
    getShelfUsage,
    getCabinetUsage,
    getDrawerUsage,
    getBoxUsage,
    getBoxUsedCount,
    getSteppedUsage,
    getUsageLevel,
    selectShelf,
    selectCabinet,
    selectDrawer,
    handlePositionHover,
    getFilteredMetadata,
    translateMetadataKey,
    navigateToLevel,
    handlePositionLeftClick,
    handlePositionMouseDown,
    handlePositionMouseEnter,
    handleGlobalMouseUp,
    clearSelection,
    getSampleByPosition,
    handleSampleSaved,
    editFreezer,
    handleFreezerUpdated,
    handleSampleDeleted,
    closeDetail,
    addShelf,
  }
}
