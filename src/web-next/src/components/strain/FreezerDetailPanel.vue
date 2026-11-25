<template>
  <div class="freezer-detail">
    <!-- 空状态 -->
    <div v-if="!strain.activeFreezer" class="empty-state">
      <div class="empty-icon"></div>
      <h2>选择冰箱查看详情</h2>
      <p>从左侧列表选择一个冰箱，查看其内部结构和样本分布</p>
    </div>

    <!-- 冰箱详情 -->
    <div v-else class="detail-content">
      <!-- 冰箱信息头部 -->
      <div class="freezer-header">
        <div class="header-left">
          <div class="freezer-icon-large"></div>
          <div class="freezer-info">
            <h2 class="freezer-name">{{ strain.activeFreezer?.name }}</h2>
            <div class="freezer-meta">
              <span class="meta-badge">{{ strain.activeFreezer?.model }}</span>
              <span class="meta-text">{{ strain.activeFreezer?.location }}</span>
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
            编辑
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
            {{ selectedShelf ? selectedShelf.name : '层' }}
          </button>
          <button
            v-if="selectedShelf"
            class="nav-btn"
            :class="{ active: currentLevel === 'cabinet' }"
            @click="navigateToLevel('cabinet')"
          >
            {{ selectedCabinet ? selectedCabinet.name : '柜' }}
          </button>
          <button
            v-if="selectedCabinet"
            class="nav-btn"
            :class="{ active: currentLevel === 'drawer' }"
            @click="navigateToLevel('drawer')"
          >
            {{ selectedDrawer ? selectedDrawer.name : '抽屉' }}
          </button>
          <button
            v-if="selectedDrawer"
            class="nav-btn"
            :class="{ active: currentLevel === 'box' }"
            @click="navigateToLevel('box')"
          >
            冻存盒
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
                    :class="{ 'pos-thumb-occupied': pos.occupied }"
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
                    <div class="ph-icon"></div>
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
                        occupied: pos.occupied,
                        selected: selectedIndices.has(Number(idx))
                      }"
                      @mousedown="handlePositionMouseDown(Number(idx), pos)"
                      @mouseenter="handlePositionMouseEnter(Number(idx), pos)"
                      @click="handlePositionLeftClick(pos, activeBox)"
                    >
                      <div class="pos-label">{{ pos.label }}</div>
                      <div v-if="pos.occupied" class="pos-indicator"></div>
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
import SampleEntryDialog from './SampleEntryDialog.vue'
import SampleDetailDialog from './SampleDetailDialog.vue'
import EditFreezerDialog from './EditFreezerDialog.vue'
import { useFreezerDetail } from './freezer/useFreezerDetail'

const {
  t, strain, currentLevel, selectedShelf, selectedCabinet, selectedDrawer, activeBoxId,
  showEntryDialog, showDetailDialog, showEditDialog, selectedSample, hoveredSample, entryPosition,
  isSelecting, selectedIndices, totalPositions, activeBox,
  getTotalCabinets, getTotalDrawers, getCabinetStats, getDrawerCount,
  getShelfUsage, getCabinetUsage, getDrawerUsage, getBoxUsage, getBoxUsedCount,
  getSteppedUsage, getUsageLevel, selectShelf, selectCabinet, selectDrawer,
  handlePositionHover, getFilteredMetadata, translateMetadataKey, navigateToLevel,
  handlePositionLeftClick, handlePositionMouseDown, handlePositionMouseEnter,
  handleGlobalMouseUp, clearSelection, getSampleByPosition, handleSampleSaved,
  editFreezer, handleFreezerUpdated, handleSampleDeleted, closeDetail, addShelf,
} = useFreezerDetail()
</script>

<style scoped src="./freezer/freezerDetail.css"></style>
