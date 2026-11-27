<script setup lang="ts">
import { useDatabasePanel } from './useDatabasePanel'

const {
  loadingBioDbs,
  taxStatus,
  cancellingDbIds,
  groupedDatabases,
  triggerUpdate,
  cancelUpdate,
  refreshAll,
  formatSizeMB,
} = useDatabasePanel()
</script>

<template>
  <div class="panel">
    <header class="panel-header">
      <div class="panel-header-row">
        <div>
          <h2>生物分析数据库管理</h2>
          <p class="desc">集中管理各个分析流水线所需的数据库版本与状态。</p>
        </div>
        <button type="button" class="p-btn p-btn-outline refresh-all-btn" @click="refreshAll">
          全局刷新
        </button>
      </div>
    </header>

    <div v-if="loadingBioDbs && !taxStatus" class="db-loading-state">
      <div class="spinner"></div>
      <span>正在扫描本地数据库配置...</span>
    </div>

    <!-- 动态渲染数据库分类 -->
    <div v-for="group in groupedDatabases" :key="group.category" class="p-card">
      <h3 class="db-group-title">{{ group.category }}</h3>

      <div class="db-unified-list">
        <div v-for="db in group.dbs" :key="db.id" class="db-item-row">
          <div class="db-row-main">
            <!-- Left: Name & Version -->
            <div class="db-name-col">
              <span class="p-status-dot" :class="{ active: db.installed }"></span>
              <div class="name-text">
                <span class="name">{{ db.name }}</span>
                <span class="p-badge db-version-badge">{{ db.version }}</span>
              </div>
              <div v-if="db.installed && db.path" class="db-meta-path">{{ db.path }}</div>
            </div>

            <!-- Middle: Stats -->
            <div class="db-stats-col">
              <div class="meta-item"><label>数据大小</label><span>{{ formatSizeMB(db.size_mb) }}</span></div>
              <div class="meta-item"><label>更新时间</label><span>{{ db.last_modified }}</span></div>
              <div class="meta-item">
                <label>当前状态</label>
                <span class="db-status-label" :class="db.installed ? 'status-ok' : 'status-err'">
                  {{ db.building ? '构建中...' : db.installed ? '完整就绪' : '尚未部署' }}
                </span>
              </div>
            </div>

            <!-- Right: Actions -->
            <div class="db-action-col">
              <button
                v-if="db.building"
                type="button"
                class="p-btn p-btn-outline db-cancel-btn"
                :disabled="Boolean(cancellingDbIds[db.id])"
                @click="cancelUpdate(db)"
              >
                {{ cancellingDbIds[db.id] ? '取消中...' : '取消' }}
              </button>
              <button
                v-if="db.url !== 'local_only' && db.url !== 'none'"
                type="button"
                class="p-btn p-btn-primary"
                :disabled="db.building"
                @click="triggerUpdate(db)"
              >
                {{ db.installed ? '检查更新' : '一键部署' }}
              </button>
            </div>
          </div>

          <!-- Progress Bar Row -->
          <div v-if="db.building" class="db-prog-row">
            <div class="p-progress-bar">
              <div class="fill" :style="{ width: db.progress + '%' }"></div>
            </div>
            <span class="prog-msg">{{ db.message }} ({{ db.progress }}%)</span>
          </div>

          <!-- Error Feedback Row -->
          <div v-else-if="db.updateStatus === 'error' && db.message" class="db-error-row">
            <span>{{ db.message }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped src="./databasePanel.css"></style>
