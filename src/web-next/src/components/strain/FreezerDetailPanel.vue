<template>
  <div class="freezer-detail">
    <!-- 空状态 -->
    <div v-if="!strain.activeFreezer" class="empty-state">
      <div class="empty-icon">🧊</div>
      <h2>选择冰箱查看详情</h2>
      <p>从左侧列表选择一个冰箱，查看其内部结构和样本分布</p>
    </div>

    <!-- 冰箱详情 -->
    <div v-else class="detail-content">
      <!-- 冰箱信息头部 -->
      <div class="freezer-header">
        <div class="header-left">
          <div class="freezer-icon-large">🧊</div>
          <div class="freezer-info">
            <h2 class="freezer-name">{{ strain.activeFreezer?.name }}</h2>
            <div class="freezer-meta">
              <span class="meta-badge">{{ strain.activeFreezer?.model }}</span>
              <span class="meta-text">📍 {{ strain.activeFreezer?.location }}</span>
            </div>
            <div class="freezer-stats">
              {{ strain.activeFreezer?.shelves.length }} 层 · 
              {{ getTotalCabinets() }} 柜 · 
              {{ getTotalDrawers() }} 抽屉 · 
              {{ totalPositions }} 个存储位
            </div>
          </div>
        </div>
        <div class="header-actions">
          <button class="btn-edit" @click="editFreezer">
            ✏️ 编辑
          </button>
          <button class="btn-add-shelf" @click="addShelf">
            + 添加层
          </button>
        </div>
      </div>

      <!-- 平铺视图内容 -->
      <div class="grid-view">
        <!-- 层级导航 -->
        <div class="level-navigation">
          <button
            class="nav-btn"
            :class="{ active: currentLevel === 'shelf' }"
            @click="navigateToLevel('shelf')"
          >
            📚 {{ selectedShelf ? selectedShelf.name : '层' }}
          </button>
          <button
            v-if="selectedShelf"
            class="nav-btn"
            :class="{ active: currentLevel === 'cabinet' }"
            @click="navigateToLevel('cabinet')"
          >
            🗄️ {{ selectedCabinet ? selectedCabinet.name : '柜' }}
          </button>
          <button
            v-if="selectedCabinet"
            class="nav-btn"
            :class="{ active: currentLevel === 'drawer' }"
            @click="navigateToLevel('drawer')"
          >
            📥 {{ selectedDrawer ? selectedDrawer.name : '抽屉' }}
          </button>
          <button
            v-if="selectedDrawer"
            class="nav-btn"
            :class="{ active: currentLevel === 'box' }"
            @click="navigateToLevel('box')"
          >
            📦 冻存盒
          </button>
        </div>

        <!-- 显示当前层级内容 -->
        <div class="level-content">
          <!-- 层级别 -->
          <div v-if="currentLevel === 'shelf'" class="shelves-grid">
            <div
              v-for="shelf in (strain.activeFreezer?.shelves || [])"
              :key="shelf.id"
              class="shelf-card"
              :class="{ selected: selectedShelf?.id === shelf.id }"
              @click="selectShelf(shelf)"
            >
              <!-- 缩略图：展示柜的矩阵（每格显示该柜的抽屉使用填充度） -->
              <div class="thumbnail">
                <div class="thumbnail-grid cabinet-matrix-grid" 
                  :style="{ gridTemplateColumns: `repeat(${Math.min(shelf.cabinets.length, 8)}, 1fr)` }">
                  <div
                    v-for="cabinet in shelf.cabinets.slice(0, 20)"
                    :key="cabinet.id"
                    class="matrix-cell group-cell"
                    :title="`${cabinet.name}: ${getCabinetUsage(shelf.id, cabinet)}% 已用 (${getDrawerCount(cabinet)} 抽屉)`"
                  >
                    <div class="battery-container">
                      <div v-for="drawer in (cabinet.drawers || [])" :key="drawer.id" class="battery-slot">
                        <div 
                          class="battery-fill"
                          :class="getUsageLevel(getDrawerUsage(shelf.id, cabinet.id, drawer))"
                          :style="{ height: `${getSteppedUsage(getDrawerUsage(shelf.id, cabinet.id, drawer))}%` }"
                        ></div>
                      </div>
                    </div>
                  </div>
                </div>
                <div v-if="shelf.cabinets.length > 20" class="thumb-more">
                  +{{ shelf.cabinets.length - 20 }} 柜
                </div>
              </div>
              
              <div class="card-info">
                <div class="card-title">{{ shelf.name }}</div>
                <div class="card-stats">
                  {{ shelf.cabinets.length }} 柜 ·
                  {{ getCabinetStats(shelf) }} ·
                  <span class="usage-badge" :class="getUsageLevel(getShelfUsage(shelf))">
                    {{ Math.round(getShelfUsage(shelf)) }}% 已用
                  </span>
                </div>
              </div>
            </div>
          </div>

          <!-- 柜级别 -->
          <div v-else-if="currentLevel === 'cabinet' && selectedShelf" class="cabinets-grid">
            <div
              v-for="cabinet in selectedShelf.cabinets"
              :key="cabinet.id"
              class="cabinet-card"
              :class="{ selected: selectedCabinet?.id === cabinet.id }"
              @click="selectCabinet(cabinet)"
            >
              <!-- 缩略图：展示抽屉的矩阵（每格显示该抽屉的使用填充度） -->
              <div class="thumbnail">
                <div class="thumbnail-grid drawer-matrix-grid"
                  :style="{ gridTemplateColumns: `repeat(${Math.min((cabinet.drawers || []).length, 8)}, 1fr)` }">
                  <div
                    v-for="drawer in (cabinet.drawers || []).slice(0, 20)"
                    :key="drawer.id"
                    class="matrix-cell group-cell"
                    :title="`${drawer.name}: ${getDrawerUsage(selectedShelf.id, cabinet.id, drawer)}% 已用 (${(drawer.boxes || []).length} 盒)`"
                  >
                    <div class="battery-container">
                      <div v-for="box in (drawer.boxes || [])" :key="box.id" class="battery-slot">
                        <div 
                          class="battery-fill"
                          :class="getUsageLevel(getBoxUsage(selectedShelf.id, cabinet.id, drawer.id, box))"
                          :style="{ height: `${getSteppedUsage(getBoxUsage(selectedShelf.id, cabinet.id, drawer.id, box))}%` }"
                        ></div>
                      </div>
                    </div>
                  </div>
                </div>
                <div v-if="(cabinet.drawers || []).length > 20" class="thumb-more">
                  +{{ (cabinet.drawers || []).length - 20 }} 抽屉
                </div>
              </div>
              
              <div class="card-info">
                <div class="card-title">{{ cabinet.name }}</div>
                <div class="card-stats">
                  {{ cabinet.drawers.length }} 抽屉 ·
                  <span class="usage-badge" :class="getUsageLevel(getCabinetUsage(selectedShelf.id, cabinet))">
                    {{ Math.round(getCabinetUsage(selectedShelf.id, cabinet)) }}% 已用
                  </span>
                </div>
              </div>
            </div>
          </div>

          <!-- 抽屉级别 -->
          <div v-else-if="currentLevel === 'drawer' && selectedCabinet && selectedShelf" class="drawers-grid">
            <div
              v-for="drawer in (selectedCabinet.drawers || [])"
              :key="drawer.id"
              class="drawer-card"
              :class="{ selected: selectedDrawer?.id === drawer.id }"
              @click="selectDrawer(drawer)"
            >
              <!-- 缩略图：展示冻存盒的矩阵（每格显示该盒的真实位置点阵） -->
              <div class="thumbnail">
                <div v-if="(drawer.boxes || []).length > 0" 
                  class="thumbnail-grid box-matrix-grid"
                  :style="{ gridTemplateColumns: `repeat(${Math.min((drawer.boxes || []).length, 8)}, 1fr)` }">
                  <div
                    v-for="box in (drawer.boxes || []).slice(0, 20)"
                    :key="box.id"
                    class="matrix-cell box-cell"
                    :class="{ 'has-data': getBoxUsage(selectedShelf?.id || '', selectedCabinet?.id || '', drawer.id, box) > 0 }"
                    :title="`${box.name}: ${getBoxUsage(selectedShelf?.id || '', selectedCabinet?.id || '', drawer.id, box)}% 已用 (${box.rows}×${box.cols})`"
                  >
                    <div 
                      class="cell-position-grid" 
                      :style="{ 
                        gridTemplateColumns: `repeat(${box.cols}, 1fr)`,
                        gridTemplateRows: `repeat(${box.rows}, 1fr)`
                      }"
                    >
                      <div
                        v-for="pos in box.positions"
                        :key="pos.label"
                        class="pos-dot"
                        :class="{ 'pos-occupied': pos.occupied }"
                      ></div>
                    </div>
                  </div>
                </div>
                <div v-if="(drawer.boxes || []).length > 20" class="thumb-more">
                  +{{ (drawer.boxes || []).length - 20 }} 盒
                </div>
                <div v-if="(drawer.boxes || []).length === 0" class="thumb-empty">
                  无冻存盒
                </div>
              </div>
              
              <div class="card-info">
                <div class="card-title">{{ drawer.name }}</div>
                <div class="card-stats">
                  {{ (drawer.boxes || []).length }} 冻存盒 ·
                  <span class="usage-badge" :class="getUsageLevel(getDrawerUsage(selectedShelf?.id || '', selectedCabinet?.id || '', drawer))">
                    {{ Math.round(getDrawerUsage(selectedShelf?.id || '', selectedCabinet?.id || '', drawer)) }}% 已用
                  </span>
                </div>
              </div>
            </div>
          </div>

          <!-- 冻存盒级别：标签页式布局 -->
          <div v-else-if="currentLevel === 'box' && selectedDrawer && selectedCabinet && selectedShelf" class="boxes-view">
            <!-- 冻存盒标签页 -->
            <div class="box-tabs">
              <button
                v-for="box in (selectedDrawer.boxes || [])"
                :key="box.id"
                class="box-tab"
                :class="{ active: activeBoxId === box.id }"
                @click="activeBoxId = box.id"
              >
                <!-- 缩略图：展示位置网格映射 -->
                <div 
                  class="box-thumb-preview" 
                  :style="{ 
                    gridTemplateColumns: `repeat(${box.cols}, 1fr)`,
                    gridTemplateRows: `repeat(${box.rows}, 1fr)`
                  }"
                >
                  <div
                    v-for="pos in box.positions"
                    :key="pos.label"
                    class="pos-thumb-pixel"
                    :class="{ 'pos-thumb-occupied': isPositionOccupied(selectedShelf?.id || '', selectedCabinet?.id || '', selectedDrawer?.id || '', box.id, pos.label) }"
                  ></div>
                </div>
                <span class="box-tab-name">{{ box.name }}</span>
                <span class="box-tab-spec">{{ box.rows }}×{{ box.cols }}</span>
              </button>
            </div>
            
            <!-- 当前选中的冻存盒详情 -->
            <div v-if="activeBox" class="active-box-container">
              <div class="box-header">
                <h3 class="box-name">{{ activeBox.name }}</h3>
                <div class="box-header-stats">
                  <span class="box-spec">{{ activeBox.rows }} × {{ activeBox.cols }} ({{ activeBox.rows * activeBox.cols }}位)</span>
                  <span class="usage-badge" :class="getUsageLevel(getBoxUsage(selectedShelf?.id, selectedCabinet?.id, selectedDrawer?.id, activeBox))">
                    {{ Math.round(getBoxUsage(selectedShelf?.id, selectedCabinet?.id, selectedDrawer?.id, activeBox)) }}% 已用 ({{ activeBox ? getBoxUsedCount(activeBox) : 0 }}/{{ activeBox?.rows ? activeBox.rows * activeBox.cols : 0 }})
                  </span>
                </div>
              </div>
              
              <div class="box-main-content">
                <!-- 左侧：实时预览面板 -->
                <div class="sample-quick-preview">
                  <div v-if="hoveredSample" :key="hoveredSample.id" class="preview-card">
                    <div class="preview-header">
                      <span class="preview-type-tag" :class="hoveredSample.sampleType.toLowerCase()">{{ hoveredSample.sampleType }}</span>
                      <span class="preview-seq-tag" :class="hoveredSample.sequenceType.toLowerCase()">{{ hoveredSample.sequenceType }}</span>
                    </div>
                    <h4 class="preview-name">{{ hoveredSample.name }}</h4>
                    
                    <div class="preview-main-scroll">
                      <div class="preview-details">
                        <div class="p-detail-item">
                          <span class="p-label">编号</span>
                          <span class="p-value">{{ hoveredSample.accession || 'N/A' }}</span>
                        </div>
                        <div class="p-detail-item">
                          <span class="p-label">物种</span>
                          <span class="p-value">{{ hoveredSample.species || '未知' }}</span>
                        </div>
                        <div class="p-detail-item">
                          <span class="p-label">位置</span>
                          <span class="p-value-pos">{{ hoveredSample.position }}</span>
                        </div>
                      </div>

                      <!-- 动态元数据展示 -->
                      <div class="preview-metadata-section">
                        <h5 class="section-title">业务元数据</h5>
                        <div class="p-meta-grid">
                          <div v-for="(val, key) in getFilteredMetadata(hoveredSample.metadata)" :key="key" class="p-meta-item">
                            <span class="p-meta-label">{{ translateMetadataKey(String(key)) }}</span>
                            <span class="p-meta-value">{{ val }}</span>
                          </div>
                        </div>
                      </div>
                    </div>

                    <div class="preview-hint">点击单元格修改详情</div>
                  </div>
                  <div v-else class="preview-placeholder">
                    <div class="ph-icon">🔬</div>
                    <p>悬停在槽位上查看详情</p>
                  </div>
                </div>

                <!-- 右侧：冻存网格 -->
                <div class="box-grid-area" @mousedown.self="clearSelection" @mouseleave="handleGlobalMouseUp">
                  <div 
                    class="box-grid" 
                    :style="{
                      gridTemplateColumns: `repeat(${activeBox.cols}, 1fr)`
                    }"
                    @mouseup="handleGlobalMouseUp"
                  >
                    <div
                      v-for="(pos, idx) in activeBox.positions"
                      :key="pos.label"
                      class="position-cell"
                      :class="{ 
                        occupied: activeBox ? isPositionOccupied(selectedShelf?.id || '', selectedCabinet?.id || '', selectedDrawer?.id || '', activeBox.id, pos.label) : false,
                        selected: selectedIndices.has(Number(idx))
                      }"
                      @mousedown="handlePositionMouseDown(Number(idx), pos)"
                      @mouseenter="handlePositionMouseEnter(Number(idx), pos)"
                      @click="handlePositionLeftClick(pos, activeBox)"
                    >
                      <div class="pos-label">{{ pos.label }}</div>
                      <div v-if="activeBox && isPositionOccupied(selectedShelf?.id || '', selectedCabinet?.id || '', selectedDrawer?.id || '', activeBox.id, pos.label)" class="pos-indicator"></div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 样本录入对话框 -->
    <SampleEntryDialog
      v-if="showEntryDialog && entryPosition"
      :key="`${entryPosition.boxId}_${entryPosition.position}`"
      :freezer-id="entryPosition.freezerId"
      :shelf-id="entryPosition.shelfId"
      :cabinet-id="entryPosition.cabinetId"
      :drawer-id="entryPosition.drawerId"
      :box-id="entryPosition.boxId"
      :position="entryPosition.position"
      :selected-positions="entryPosition.selectedPositions"
      @close="showEntryDialog = false"
      @saved="handleSampleSaved"
    />

    <!-- 样本详情对话框 -->
    <SampleDetailDialog
      v-if="showDetailDialog && selectedSample"
      :key="selectedSample.id"
      :record="selectedSample"
      @close="closeDetail"
      @deleted="handleSampleDeleted"
    />

    <!-- 编辑冰箱对话框 -->
    <EditFreezerDialog
      v-if="showEditDialog && strain.activeFreezer"
      :freezer="strain.activeFreezer"
      @close="showEditDialog = false"
      @updated="handleFreezerUpdated"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, toRaw, onMounted, onUnmounted } from 'vue'
import { useStrainStore } from '../../stores/strain'
import { useAppStore } from '../../stores/app'
import type { StrainRecord } from '../../stores/strain'
import SampleEntryDialog from './SampleEntryDialog.vue'
import SampleDetailDialog from './SampleDetailDialog.vue'
import EditFreezerDialog from './EditFreezerDialog.vue'

const strain = useStrainStore()
const appStore = useAppStore()

// 层级导航状态
const currentLevel = ref<'shelf' | 'cabinet' | 'drawer' | 'box'>('shelf')
const selectedShelf = ref<any>(null)
const selectedCabinet = ref<any>(null)
const selectedDrawer = ref<any>(null)
const activeBoxId = ref<string>('')

// 监听冰箱切换，重置状态
watch(() => strain.activeFreezerId, () => {
  currentLevel.value = 'shelf'
  selectedShelf.value = null
  selectedCabinet.value = null
  selectedDrawer.value = null
  activeBoxId.value = ''
  selectedIndices.value.clear()
  updateBoxOccupancy()
})

// 监听记录数量变化（添加/删除），精确触发而非 deep watcher
watch(() => strain.records.length, () => {
  updateBoxOccupancy()
})

// 对话框状态
const showEntryDialog = ref(false)
const showDetailDialog = ref(false)
const showEditDialog = ref(false)
const selectedSample = ref<StrainRecord | null>(null)
const hoveredSample = ref<StrainRecord | null>(null)
const entryPosition = ref<{
  freezerId: string
  shelfId: string
  cabinetId: string
  drawerId: string
  boxId: string
  position: string
  selectedPositions?: string[]
} | null>(null)

// 拖拽多选相关
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

// 当前选中的冻存盒
const activeBox = computed(() => {
  if (!selectedDrawer.value || !activeBoxId.value) return null
  return selectedDrawer.value.boxes.find((b: any) => b.id === activeBoxId.value) || null
})

// 计算冰箱的柜和抽屉总数
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

// 计算选中层级的统计
function getCabinetStats(shelf: any): string {
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

function getDrawerCount(cabinet: any): number {
  return (cabinet.drawers || []).length
}

// 计算使用率（基于 records 实时统计，解决状态不同步问题）
function getShelfUsage(shelf: any): number {
  if (!strain.activeFreezer) return 0
  let totalPositions = 0
  for (const cabinet of shelf.cabinets) {
    for (const drawer of cabinet.drawers) {
      for (const box of drawer.boxes) {
        totalPositions += box.rows * box.cols
      }
    }
  }
  const usedPositions = strain.records.filter(r => 
    r.freezerId === strain.activeFreezer!.id && r.shelfId === shelf.id
  ).length
  return totalPositions > 0 ? (usedPositions / totalPositions) * 100 : 0
}

function getCabinetUsage(shelfId: string, cabinet: any): number {
  if (!strain.activeFreezer) return 0
  let totalPositions = 0
  for (const drawer of cabinet.drawers) {
    for (const box of drawer.boxes) {
      totalPositions += box.rows * box.cols
    }
  }
  const usedPositions = strain.records.filter(r => 
    r.freezerId === strain.activeFreezer!.id && 
    r.shelfId === shelfId && 
    r.cabinetId === cabinet.id
  ).length
  return totalPositions > 0 ? (usedPositions / totalPositions) * 100 : 0
}

function getDrawerUsage(shelfId: string, cabinetId: string, drawer: any): number {
  if (!strain.activeFreezer) return 0
  let totalPositions = 0
  for (const box of (drawer.boxes || [])) {
    totalPositions += box.rows * box.cols
  }
  const usedPositions = strain.records.filter(r => 
    r.freezerId === strain.activeFreezer!.id && 
    r.shelfId === shelfId && 
    r.cabinetId === cabinetId && 
    r.drawerId === drawer.id
  ).length
  return totalPositions > 0 ? (usedPositions / totalPositions) * 100 : 0
}

function getBoxUsage(shelfId: string, cabinetId: string, drawerId: string, box: any): number {
  const totalPositions = box.rows * box.cols
  const usedPositions = strain.records.filter(r => 
    r.freezerId === strain.activeFreezer!.id &&
    r.shelfId === shelfId &&
    r.cabinetId === cabinetId &&
    r.drawerId === drawerId &&
    r.boxId === box.id
  ).length
  return totalPositions > 0 ? (usedPositions / totalPositions) * 100 : 0
}

// 检查位置是否被占用（查询 records）
function isPositionOccupied(shelfId: string, cabinetId: string, drawerId: string, boxId: string, posLabel: string): boolean {
  if (!strain.activeFreezer) return false
  return strain.records.some(r => 
    r.freezerId === strain.activeFreezer!.id &&
    r.shelfId === shelfId &&
    r.cabinetId === cabinetId &&
    r.drawerId === drawerId &&
    r.boxId === boxId &&
    r.position === posLabel
  )
}

function getBoxUsedCount(box: any): number {
  if (!box || !box.positions) return 0
  return box.positions.filter((p: any) => p.occupied).length
}

// 计算阶梯式使用率（5%分度）
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

function selectShelf(shelf: any) {
  selectedShelf.value = shelf
  selectedCabinet.value = null
  selectedDrawer.value = null
  currentLevel.value = 'cabinet'
}

function selectCabinet(cabinet: any) {
  selectedCabinet.value = cabinet
  selectedDrawer.value = null
  currentLevel.value = 'drawer'
}

function selectDrawer(drawer: any) {
  selectedDrawer.value = drawer
  currentLevel.value = 'box'
  hoveredSample.value = null
  // 默认选中第一个冻存盒
  if (drawer.boxes.length > 0) {
    activeBoxId.value = drawer.boxes[0].id
  }
  selectedIndices.value.clear()
}

function handlePositionHover(position: any, box: any) {
  // 核心修正：不直接信任 position.occupied
  const sample = getSampleByPosition(
    strain.activeFreezer!.id,
    selectedShelf.value.id,
    selectedCabinet.value.id,
    selectedDrawer.value.id,
    box.id,
    position.label
  )
  
  if (sample) {
    hoveredSample.value = sample
  } else {
    hoveredSample.value = null
  }
}

// 过滤掉不适合在快速预览显示的元数据字段
function getFilteredMetadata(metadata: any) {
  if (!metadata) return {}
  const excludeKeys = ['description', 'notes', 'storageDate', 'isExpression']
  const filtered: any = {}
  Object.keys(metadata).forEach(key => {
    if (!excludeKeys.includes(key) && metadata[key]) {
      filtered[key] = metadata[key]
    }
  })
  return filtered
}

// 快速翻译元数据键名
function translateMetadataKey(key: string): string {
  const dict: any = {
    concentration: '浓度',
    potency: '效价/滴度',
    storageMedium: '储存介质',
    biosafetyLevel: '生物安全等级',
    cultureCondition: '培养条件',
    resistance: '抗性',
    genotype: '基因型',
    hostStrain: '宿主菌株',
    marker: '筛选标记',
    backbone: '载体骨干',
    promoter: '启动子',
    insertName: '插入片段',
    plasmidSize: '大小',
    purity: '纯度',
    molecularWeight: '分子量',
    buffer: '缓冲液',
    tags: '标签',
    cellType: '细胞类型',
    medium: '培养基',
    doublingTime: '倍增时间',
    titer: '滴度',
    serotype: '血清型',
    lifestyle: '生活史类型',
    morphology: '形态学',
    // BLAST 关联元数据
    blast_identity: '比对相似度 (%)',
    blast_evalue: 'E值 (e-value)',
    blast_task_id: '比对任务 ID',
    blast_hit_title: '最佳比对标题',
    original_query_id: '原始查询序列 ID',
    blast_accession: '比对编号'
  }
  return dict[key] || key
}

function navigateToLevel(level: 'shelf' | 'cabinet' | 'drawer' | 'box') {
  currentLevel.value = level
  
  // 根据导航层级重置下级选择
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

function handlePositionLeftClick(position: any, box: any) {
  // 如果当前有序选（拖拽结束），则优先触发此处的点击拦截逻辑
  if (selectedIndices.value.size > 1) {
    return
  }

  // 核心修正：不直接信任 position.occupied 属性（可能存在响应式延迟）
  // 直接从 store 记录中通过位置反查是否存在样本
  const sample = getSampleByPosition(
    strain.activeFreezer!.id,
    selectedShelf.value.id,
    selectedCabinet.value.id,
    selectedDrawer.value.id,
    box.id,
    position.label
  )

  if (sample) {
    // 显示样本详情
    selectedSample.value = sample
    showDetailDialog.value = true
  } else {
    // 确实没样本，清空选区进入录入模式
    selectedIndices.value.clear()
    
    // 显示录入对话框
    entryPosition.value = {
      freezerId: strain.activeFreezer!.id,
      shelfId: selectedShelf.value.id,
      cabinetId: selectedCabinet.value.id,
      drawerId: selectedDrawer.value.id,
      boxId: box.id,
      position: position.label
    }
    showEntryDialog.value = true
  }
}

// 鼠标按下：开始框选
function handlePositionMouseDown(idx: number, pos: any) {
  if (pos.occupied) return
  
  isSelecting.value = true
  selectionStartIdx.value = idx
  selectedIndices.value.clear()
  selectedIndices.value.add(idx)
}

// 鼠标进入：更新框选范围
function handlePositionMouseEnter(idx: number, pos: any) {
  // 预览悬停逻辑保持（如果不在选择中）
  if (!isSelecting.value) {
    handlePositionHover(pos, activeBox.value)
    return
  }

  if (selectionStartIdx.value === null || !activeBox.value) return

  // 计算矩形范围
  const startIdx = selectionStartIdx.value
  const endIdx = idx
  
  const cols = activeBox.value.cols
  const startRow = Math.floor(startIdx / cols)
  const startCol = startIdx % cols
  const endRow = Math.floor(endIdx / cols)
  const endCol = endIdx % cols

  const minRow = Math.min(startRow, endRow)
  const maxRow = Math.max(startRow, endRow)
  const minCol = Math.min(startCol, endCol)
  const maxCol = Math.max(startCol, endCol)

  const newSelection = new Set<number>()
  for (let r = minRow; r <= maxRow; r++) {
    for (let c = minCol; c <= maxCol; c++) {
      const currentIdx = r * cols + c
      const currentPos = activeBox.value.positions[currentIdx]
      // 仅允许选择空的格子
      if (currentPos && !isPositionOccupied(
        selectedShelf.value.id,
        selectedCabinet.value.id,
        selectedDrawer.value.id,
        activeBox.value.id,
        currentPos.label
      )) {
        newSelection.add(currentIdx)
      }
    }
  }
  selectedIndices.value = newSelection
}

// 全局鼠标松开：结束选择并触发对话框
function handleGlobalMouseUp() {
  if (!isSelecting.value) return
  isSelecting.value = false
  
  if (selectedIndices.value.size > 1 && activeBox.value) {
    const positions = Array.from(selectedIndices.value)
      .sort((a, b) => a - b)
      .map(idx => activeBox.value!.positions[idx].label)

    entryPosition.value = {
      freezerId: strain.activeFreezer!.id,
      shelfId: selectedShelf.value.id,
      cabinetId: selectedCabinet.value.id,
      drawerId: selectedDrawer.value.id,
      boxId: activeBox.value.id,
      position: positions[0], // 以第一个为起始基准
      selectedPositions: positions
    }
    showEntryDialog.value = true
  }
}

// 清除框选
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
  return strain.records.find(r => 
    r.freezerId === freezerId &&
    r.shelfId === shelfId &&
    r.cabinetId === cabinetId &&
    r.drawerId === drawerId &&
    r.boxId === boxId &&
    r.position === position
  ) || null
}



function handleSampleSaved() {
  // 刷新占用状态
  updateBoxOccupancy()
}

// 更新位置占用状态（使用 toRaw 绕过 Vue 代理，避免逐格子触发响应式更新）
function updateBoxOccupancy() {
  if (!strain.activeFreezer) return

  // 获取原始对象，批量修改不触发 Vue setter
  const rawFreezer = toRaw(strain.activeFreezer)

  // 1. 清空所有位置
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

  // 2. 建立快速查找索引，避免每条记录都五层 find
  const boxMap = new Map<string, typeof rawFreezer.shelves[0]['cabinets'][0]['drawers'][0]['boxes'][0]>()
  for (const shelf of rawFreezer.shelves) {
    for (const cabinet of shelf.cabinets) {
      for (const drawer of cabinet.drawers) {
        for (const box of drawer.boxes) {
          boxMap.set(box.id, box)
        }
      }
    }
  }

  // 3. 遍历记录，一次性标记占用
  const rawRecords = toRaw(strain.records)
  const freezerId = rawFreezer.id
  for (const record of rawRecords) {
    if (record.freezerId !== freezerId || !record.boxId || !record.position) continue
    const box = boxMap.get(record.boxId)
    if (!box) continue
    const pos = box.positions.find(p => p.label === record.position)
    if (pos) {
      pos.occupied = true
      pos.sampleId = record.id
    }
  }

  // 4. 批量修改完成后，强制触发 freezers ref 的依赖更新
  //    通过浅层重新赋值让 Vue 检测到变化并重渲染
  strain.freezers = [...strain.freezers]
}

function editFreezer() {
  showEditDialog.value = true
}

function handleFreezerUpdated() {
  // 可以在这里刷新本地状态或显示全局通知（Dialog 内已经发过通知了）
}

function handleSampleDeleted() {
  closeDetail()
  updateBoxOccupancy()
}

function closeDetail() {
  showDetailDialog.value = false
  selectedSample.value = null
}

// 全局点击拦截：点击网格以外区域清除框选状态
function handleOutsideClick(e: MouseEvent) {
  if (selectedIndices.value.size === 0 || isSelecting.value) return

  const target = e.target as HTMLElement
  
  // 1. 如果点击的是网格内部，由网格自身的 handlePositionMouseDown 处理，此处跳过
  const gridArea = document.querySelector('.box-grid-area')
  if (gridArea?.contains(target)) return

  // 2. 如果点击的是弹窗内部（正在录入），不应清除选区
  const dialog = document.querySelector('.dialog-overlay')
  if (dialog?.contains(target)) return

  // 3. 点击其他任何空白区域，清除选区
  clearSelection()
}

onMounted(() => {
  document.addEventListener('mousedown', handleOutsideClick)
  updateBoxOccupancy()
})

onUnmounted(() => {
  document.removeEventListener('mousedown', handleOutsideClick)
})

function addShelf() {
  appStore.showNotification('添加层功能开发中', 'info')
}
</script>

<style scoped>
.freezer-detail {
  height: 100%;
  overflow: auto;
  background: #f8fafc;
}

/* 空状态 */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 20px;
  text-align: center;
  height: 100%;
}

.empty-icon {
  font-size: 4rem;
  margin-bottom: 16px;
  opacity: 0.6;
}

.empty-state h2 {
  font-size: 1.5rem;
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 8px 0;
}

.empty-state p {
  font-size: 0.95rem;
  color: #64748b;
  margin: 0;
}

/* 详情内容 */
.detail-content {
  padding: 24px;
}

/* 冰箱头部 */
.freezer-header {
  background: white;
  border-radius: 16px;
  padding: 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 20px;
}

.freezer-icon-large {
  font-size: 3.5rem;
}

.freezer-info {
  flex: 1;
}

.freezer-name {
  font-size: 1.5rem;
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 8px 0;
}

.freezer-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 6px;
}

.meta-badge {
  padding: 4px 10px;
  background: #eff6ff;
  color: #2563eb;
  border-radius: 6px;
  font-size: 0.8rem;
  font-weight: 600;
}

.meta-text {
  font-size: 0.85rem;
  color: #64748b;
}

.freezer-stats {
  font-size: 0.85rem;
  color: #94a3b8;
  font-weight: 600;
}

.header-actions {
  display: flex;
  gap: 10px;
}

.btn-edit,
.btn-add-shelf {
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  border: none;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.btn-edit {
  background: #f1f5f9;
  color: #475569;
}

.btn-edit:hover {
  background: #e2e8f0;
}

.btn-add-shelf {
  background: linear-gradient(135deg, #10b981, #059669);
  color: white;
}

.btn-add-shelf:hover {
  transform: translateY(-1px);
}

/* 视图切换 */
.view-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 20px;
}

.view-tab {
  padding: 10px 20px;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  font-size: 0.9rem;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.view-tab:hover {
  border-color: #cbd5e1;
  color: #1e293b;
}

.view-tab.active {
  background: #2563eb;
  border-color: #2563eb;
  color: white;
}

/* 平铺视图 */
.grid-view {
  background: white;
  border-radius: 16px;
  padding: 20px;
}

.level-navigation {
  display: flex;
  gap: 8px;
  margin-bottom: 20px;
}

.nav-btn {
  padding: 10px 20px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  font-size: 0.9rem;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.nav-btn:hover {
  background: #e2e8f0;
  color: #1e293b;
}

.nav-btn.active {
  background: #2563eb;
  border-color: #2563eb;
  color: white;
}

.level-content {
  min-height: 400px;
}

.shelves-grid,
.cabinets-grid,
.drawers-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 16px;
}

.shelf-card,
.cabinet-card,
.drawer-card {
  background: #f8fafc;
  border: 2px solid #e2e8f0;
  border-radius: 12px;
  padding: 16px;
  cursor: pointer;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.shelf-card:hover,
.cabinet-card:hover,
.drawer-card:hover {
  border-color: #2563eb;
  background: #eff6ff;
  transform: translateY(-2px);
}

.shelf-card.selected,
.cabinet-card.selected,
.drawer-card.selected {
  border-color: #2563eb;
  background: #eff6ff;
}

/* 缩略图 */
.thumbnail {
  background: white;
  border-radius: 8px;
  padding: 8px;
  position: relative;
  border: 1px solid #e2e8f0;
  overflow: hidden;
  min-height: 60px;
}

.thumbnail-grid {
  display: grid;
  gap: 4px;
  width: 100%;
  max-height: 100px;
  overflow: hidden;
}

/* 层缩略图：柜矩阵 */
.cabinet-matrix-grid {
  grid-auto-rows: minmax(24px, auto);
}

/* 柜缩略图：抽屉矩阵 */
.drawer-matrix-grid {
  grid-auto-rows: minmax(24px, auto);
}

/* 抽屉缩略图：冻存盒矩阵 */
.box-matrix-grid {
  grid-auto-rows: minmax(24px, auto);
}

/* 矩阵单元格 */
.matrix-cell {
  aspect-ratio: 1;
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
  position: relative;
  min-width: 40px;
  min-height: 40px;
  padding: 3px;
}

/* 填充式缩略图单元格 */
.fill-cell {
  display: flex;
  align-items: flex-end;
  padding: 2px;
  background: #e2e8f0;
}

.fill-level {
  width: 100%;
  background: linear-gradient(to top, #2563eb, #3b82f6);
  border-radius: 2px;
  transition: height 0.3s ease; backface-visibility: hidden; -webkit-backface-visibility: hidden;
  min-height: 2px;
}

/* 电池型柱状图样式 */
.group-cell {
  background: #f1f5f9;
  border-color: #e2e8f0;
  padding: 4px;
}

.battery-container {
  display: flex;
  align-items: stretch;
  gap: 2px;
  width: 100%;
  height: 100%;
  padding: 2px;
}

.battery-slot {
  flex: 1;
  background: #e2e8f0;
  border-radius: 1px;
  position: relative;
  overflow: hidden;
}

.battery-fill {
  position: absolute;
  bottom: 0;
  left: 0;
  width: 100%;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
  min-height: 0;
}

/* 填充条颜色分级 */
.battery-fill.high { background: linear-gradient(to top, #dc2626, #ef4444); }
.battery-fill.medium { background: linear-gradient(to top, #d97706, #f59e0b); }
.battery-fill.low { background: linear-gradient(to top, #2563eb, #3b82f6); }
.battery-fill.empty { background: transparent; }

/* 单元格内的点阵网格 */
.cell-dot-grid {
  display: grid;
  gap: 1px;
  width: 100%;
  height: 100%;
  grid-template-columns: repeat(3, 1fr);
  grid-auto-rows: 1fr;
}

.dot-pixel {
  width: 100%;
  height: 100%;
  background: #cbd5e1;
  border-radius: 1px;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.dot-pixel.dot-active {
  background: #2563eb;
}

/* 冻存盒单元格特殊样式 */
.box-cell {
  padding: 3px;
}

/* 单元格内的位置网格（真实映射） */
.cell-position-grid {
  display: grid;
  gap: 1px;
  width: 100%;
  height: 100%;
}

.pos-dot {
  width: 100%;
  height: 100%;
  background: #e2e8f0;
  border-radius: 0.5px;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.pos-dot.pos-occupied {
  background: #2563eb;
}

.thumb-more {
  position: absolute;
  bottom: 2px;
  right: 2px;
  background: rgba(0, 0, 0, 0.7);
  color: white;
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 0.6rem;
  font-weight: 700;
}

.thumb-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 40px;
  color: #94a3b8;
  font-size: 0.7rem;
}

.card-info {
  flex: 1;
}

.card-title {
  font-size: 0.95rem;
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 4px 0;
}

.card-stats {
  font-size: 0.8rem;
  color: #64748b;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.usage-badge {
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.7rem;
  font-weight: 700;
}

.usage-badge.high {
  background: #fee2e2;
  color: #dc2626;
}

.usage-badge.medium {
  background: #fef3c7;
  color: #d97706;
}

.usage-badge.low {
  background: #d1fae5;
  color: #059669;
}

.usage-badge.empty {
  background: #f1f5f9;
  color: #94a3b8;
}

.boxes-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 冻存盒标签页 */
.box-tabs {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  padding: 12px;
  background: #f8fafc;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
}

.box-tab {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 12px;
  background: white;
  border: 2px solid #e2e8f0;
  border-radius: 10px;
  cursor: pointer;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
  font-size: 0.85rem;
  min-width: 90px;
  flex-shrink: 0;
}

.box-tab:hover {
  border-color: #cbd5e1;
  background: #f1f5f9;
}

.box-tab.active {
  border-color: #2563eb;
  background: #eff6ff;
}

/* 缩略图网格容器 */
.box-thumb-preview {
  display: grid;
  gap: 1px;
  width: 50px;
  height: 50px;
  background: #e2e8f0;
  border-radius: 4px;
  overflow: hidden;
  padding: 2px;
}

/* 缩略图片素点 */
.pos-thumb-pixel {
  width: 100%;
  height: 100%;
  background: #f1f5f9;
  border-radius: 0.5px;
  transition: transform 0.2s, opacity 0.2s; backface-visibility: hidden; -webkit-backface-visibility: hidden;
}

.pos-thumb-pixel.pos-thumb-occupied {
  background: #2563eb;
}

.box-tab-name {
  font-weight: 700;
  color: #1e293b;
  font-size: 0.8rem;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

.box-tab-spec {
  font-size: 0.7rem;
  color: #94a3b8;
  background: #f1f5f9;
  padding: 2px 6px;
  border-radius: 4px;
  white-space: nowrap;
}

/* 活动冻存盒容器 */
.active-box-container {
  background: white;
  border-radius: 12px;
  padding: 20px;
  border: 1px solid #e2e8f0;
}

.box-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid #e2e8f0;
}

.box-name {
  font-size: 1.1rem;
  font-weight: 700;
  color: #1e293b;
  margin: 0;
}

.box-header-stats {
  display: flex;
  align-items: center;
  gap: 12px;
}

.box-spec {
  font-size: 0.85rem;
  color: #64748b;
  background: #eff6ff;
  padding: 4px 10px;
  border-radius: 6px;
}

.box-main-content {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 24px;
  align-items: start;
}

.sample-quick-preview {
  width: 280px;
  min-width: 280px;
  max-width: 280px;
  height: 0;
  min-height: 100%;
  align-self: stretch;
  background: #f8fafc;
  border-radius: 12px;
  padding: 16px;
  border: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.preview-main-scroll {
  flex: 1;
  overflow-y: auto;
  margin-right: -4px;
  padding-right: 4px;
}

.preview-main-scroll::-webkit-scrollbar {
  width: 4px;
}

.preview-main-scroll::-webkit-scrollbar-thumb {
  background: #e2e8f0;
  border-radius: 4px;
}

.preview-metadata-section {
  margin-top: 20px;
  border-top: 1px solid #edf2f7;
  padding-top: 16px;
}

.section-title {
  font-size: 0.75rem;
  font-weight: 700;
  color: #475569;
  margin: 0 0 12px 0;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.p-meta-grid {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.p-meta-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: white;
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid #f1f5f9;
}

.p-meta-label {
  font-size: 0.7rem;
  color: #64748b;
  font-weight: 500;
}

.p-meta-value {
  font-size: 0.75rem;
  color: #1e293b;
  font-weight: 700;
  max-width: 65%;
  text-align: right;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.preview-card {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.preview-header {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.preview-type-tag, .preview-seq-tag {
  font-size: 0.65rem;
  padding: 2px 8px;
  border-radius: 12px;
  background: #e2e8f0;
  color: #475569;
  font-weight: 600;
  text-transform: uppercase;
}

.preview-type-tag.bacteria { background: #fee2e2; color: #991b1b; }
.preview-type-tag.virus { background: #ffedd5; color: #9a3412; }
.preview-type-tag.phage { background: #f0fdf4; color: #166534; }
.preview-seq-tag.dna { background: #eff6ff; color: #1e40af; }
.preview-seq-tag.rna { background: #fdf2f8; color: #9d174d; }

.preview-name {
  font-size: 1rem;
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 16px 0;
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.preview-details {
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex-grow: 1;
}

.p-detail-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.p-label {
  font-size: 0.7rem;
  color: #94a3b8;
  font-weight: 500;
}

.p-value {
  font-size: 0.85rem;
  color: #334155;
  font-weight: 600;
}

.p-value-pos {
  font-size: 1.2rem;
  font-weight: 800;
  color: #2563eb;
}

.preview-hint {
  font-size: 0.7rem;
  color: #94a3b8;
  text-align: center;
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid #e2e8f0;
}

.preview-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex-grow: 1;
  color: #94a3b8;
  text-align: center;
}

.ph-icon {
  font-size: 2.5rem;
  margin-bottom: 12px;
  opacity: 0.3;
}

.box-grid-area {
  flex: 1;
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 10px;
  background: #ffffff;
  border-radius: 8px;
  border: 1px solid #f1f5f9;
}

.box-grid {
  display: grid;
  gap: 4px;
  max-width: 850px;
  width: 100%;
}

.position-cell {
  aspect-ratio: 1;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  position: relative;
  font-size: 0.6rem;
}

.position-cell:hover {
  border-color: #3b82f6;
  background: #f1f5f9;
  z-index: 10;
  
}

.position-cell.occupied {
  background: linear-gradient(135deg, #fdf2f2, #fee2e2);
  border-color: #fecaca;
}

.position-cell.occupied:hover {
  background: linear-gradient(135deg, #fecaca, #fca5a5);
}

.position-cell.selected {
  background: #dbeafe !important;
  border-color: #2563eb !important;
  z-index: 5;
}

.position-cell.selected .pos-label {
  color: #1d4ed8;
}

.pos-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #64748b;
}

.position-cell.occupied .pos-label {
  color: #991b1b;
}

.pos-indicator {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #ef4444; /* 改为红色，更显眼 */
  margin-top: 1px;
}

/* 3D 视图占位 */
.view-3d-placeholder {
  background: white;
  border-radius: 16px;
  padding: 80px 20px;
  text-align: center;
}

.placeholder-content {
  max-width: 400px;
  margin: 0 auto;
}

.placeholder-icon {
  font-size: 4rem;
  margin-bottom: 16px;
  opacity: 0.6;
}

.placeholder-content h3 {
  font-size: 1.3rem;
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 8px 0;
}

.placeholder-content p {
  font-size: 0.95rem;
  color: #64748b;
  margin: 0;
}
</style>