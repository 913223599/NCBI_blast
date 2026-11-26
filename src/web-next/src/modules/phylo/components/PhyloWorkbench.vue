<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from '../../../locales'
import { useAppStore } from '../../../stores/app'
import { usePhyloStore } from '../stores/usePhyloStore'
import type { WorkbenchMode } from '../types/phylo'
import DataIntakePanel from './DataIntakePanel.vue'
import DeliveryQcPanel from './DeliveryQcPanel.vue'
import HistoryPanel from './HistoryPanel.vue'
import JobProgressBanner from './JobProgressBanner.vue'
import PhageAniPanel from './PhageAniPanel.vue'
import PipelineConfigPanel from './PipelineConfigPanel.vue'
import ReferenceCurationPanel from './ReferenceCurationPanel.vue'
import TreeViewport from './TreeViewport.vue'
import VisualStylePanel from './VisualStylePanel.vue'

type TabType = 'intake' | 'ani' | 'refs' | 'config' | 'qc' | 'visual' | 'history'

const { t } = useI18n()
const appStore = useAppStore()
const store = usePhyloStore()
const activeTab = ref<TabType>('intake')
const sidebarOpen = ref(true)

function selectTab(tab: TabType) {
  if (activeTab.value === tab && sidebarOpen.value) {
    sidebarOpen.value = false
  } else {
    activeTab.value = tab
    sidebarOpen.value = true
  }
}

function goTab(tab: TabType) {
  activeTab.value = tab
  sidebarOpen.value = true
}

function setMode(mode: WorkbenchMode) {
  store.workbenchMode = mode
  store.applyRecommendedDefaults(store.profile)
  if (mode === 'general' && (activeTab.value === 'ani' || activeTab.value === 'refs' || activeTab.value === 'qc')) {
    activeTab.value = 'config'
  }
}

watch(
  () => store.currentJob?.job_id,
  (jid) => {
    if (jid && store.currentJob?.qc_report && store.workbenchMode === 'phage_taxonomy') {
      activeTab.value = 'qc'
      sidebarOpen.value = true
    }
  }
)

watch(
  () => appStore.locale,
  () => {
    appStore.setPageTitle(t('phylo.wb.page_title'))
  }
)

onMounted(async () => {
  appStore.setPageTitle(t('phylo.wb.page_title'))
  await store.init()
})

onUnmounted(() => {
  store.dispose()
})
</script>

<template>
  <div class="phylo-workbench">
    <!-- 顶部栏 -->
    <header class="wb-topbar">
      <div class="wb-left">
        <div class="mode-switch">
          <button type="button" class="mode-btn" :class="{ active: store.workbenchMode === 'phage_taxonomy' }"
            @click="setMode('phage_taxonomy')">{{ t('phylo.wb.mode.phage_taxonomy') }}</button>
          <button type="button" class="mode-btn" :class="{ active: store.workbenchMode === 'general' }"
            @click="setMode('general')">{{ t('phylo.wb.mode.general') }}</button>
        </div>

        <div class="wb-tabs">
          <button type="button" class="wb-tab" :class="{ active: activeTab === 'intake' && sidebarOpen }"
            @click="selectTab('intake')">{{ t('phylo.wb.tab.intake') }}</button>

          <template v-if="store.workbenchMode === 'phage_taxonomy'">
            <button type="button" class="wb-tab" :class="{ active: activeTab === 'ani' && sidebarOpen }"
              @click="selectTab('ani')">{{ t('phylo.wb.tab.ani') }}</button>
            <button type="button" class="wb-tab" :class="{ active: activeTab === 'refs' && sidebarOpen }"
              @click="selectTab('refs')">{{ t('phylo.wb.tab.refs') }}</button>
            <button type="button" class="wb-tab" :class="{ active: activeTab === 'config' && sidebarOpen }"
              @click="selectTab('config')">{{ t('phylo.wb.tab.build') }}</button>
            <button type="button" class="wb-tab" :class="{ active: activeTab === 'qc' && sidebarOpen }"
              @click="selectTab('qc')">{{ t('phylo.wb.tab.qc') }}</button>
          </template>
          <template v-else>
            <button type="button" class="wb-tab" :class="{ active: activeTab === 'config' && sidebarOpen }"
              @click="selectTab('config')">{{ t('phylo.wb.tab.config') }}</button>
          </template>

          <button type="button" class="wb-tab" :class="{ active: activeTab === 'visual' && sidebarOpen }"
            @click="selectTab('visual')">{{ t('phylo.wb.tab.visual') }}</button>
          <button type="button" class="wb-tab" :class="{ active: activeTab === 'history' && sidebarOpen }"
            @click="selectTab('history')">{{ t('phylo.wb.tab.history') }}</button>
        </div>
      </div>

      <div class="wb-right">
        <span v-if="store.profile && store.profile.sequence_count > 0" class="wb-pill">
          {{ t('phylo.wb.seq_pill', { count: store.profile.sequence_count, mol: store.profile.mol_type.toUpperCase() }) }}
        </span>
        <button type="button" v-if="store.isRunning" class="wb-stop-pill" :disabled="store.isCancelling"
          @click="store.cancelActiveJob()">
          {{ store.isCancelling ? t('phylo.wb.cancelling') : t('phylo.wb.force_stop') }}
        </button>
      </div>
    </header>

    <!-- 主体区 -->
    <div class="wb-body">
      <aside class="wb-sidebar" :class="{ collapsed: !sidebarOpen }">
        <div class="wb-sidebar-inner">
          <DataIntakePanel v-show="activeTab === 'intake'" />
          <PhageAniPanel v-show="activeTab === 'ani'" @next-step="goTab('refs')" />
          <ReferenceCurationPanel v-show="activeTab === 'refs'" @next-step="goTab('config')" />
          <PipelineConfigPanel v-show="activeTab === 'config'" />
          <DeliveryQcPanel v-show="activeTab === 'qc'" @back-to-refs="goTab('refs')" />
          <VisualStylePanel v-show="activeTab === 'visual'" />
          <HistoryPanel v-show="activeTab === 'history'" />
        </div>
      </aside>

      <section class="wb-main" :aria-label="t('phylo.wb.workspace_aria')">
        <div v-if="store.activeJob" class="wb-banner-slot">
          <JobProgressBanner />
        </div>
        <TreeViewport />
      </section>
    </div>
  </div>
</template>

<style scoped>
.phylo-workbench {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  background: #f1f5f9;
  overflow: hidden;
}

.wb-topbar {
  min-height: 48px;
  background: #ffffff;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 14px;
  flex-shrink: 0;
  gap: 10px;
  flex-wrap: wrap;
}

.wb-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.mode-switch {
  display: flex;
  background: #f1f5f9;
  padding: 2px;
  border-radius: 7px;
  border: 1px solid #e2e8f0;
}

.mode-btn {
  padding: 4px 10px;
  border: none;
  border-radius: 5px;
  background: transparent;
  font-size: 11px;
  font-weight: 700;
  color: #475569;
  cursor: pointer;
}

.mode-btn.active {
  background: #ffffff;
  color: #1d4ed8;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
}

.wb-tabs {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.wb-tab {
  padding: 5px 10px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: #475569;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.wb-tab:hover {
  background: #f8fafc;
  color: #0f172a;
}

.wb-tab.active {
  background: #eff6ff;
  color: #1d4ed8;
  border-color: #bfdbfe;
}

.wb-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.wb-pill {
  font-size: 11px;
  color: #334155;
  background: #f1f5f9;
  padding: 3px 9px;
  border-radius: 999px;
  font-weight: 600;
}

.wb-stop-pill {
  border: none;
  background: #dc2626;
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  padding: 5px 11px;
  border-radius: 6px;
  cursor: pointer;
}

.wb-body {
  flex: 1;
  display: flex;
  min-height: 0;
  overflow: hidden;
}

.wb-sidebar {
  width: 356px;
  background: #ffffff;
  border-right: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  transition: width 0.2s ease;
  overflow: hidden;
  flex-shrink: 0;
}

.wb-sidebar.collapsed {
  width: 0;
  border-right: none;
}

.wb-sidebar-inner {
  width: 356px;
  height: 100%;
  overflow-y: auto;
  padding: 14px 15px;
  box-sizing: border-box;
}

.wb-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  height: 100%;
  position: relative;
}

.wb-banner-slot {
  padding: 10px 14px 0 14px;
  background: #ffffff;
}
</style>
