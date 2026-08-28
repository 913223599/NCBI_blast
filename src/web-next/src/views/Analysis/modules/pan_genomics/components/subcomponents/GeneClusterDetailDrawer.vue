<script setup lang="ts">
/**
 * GeneClusterDetailDrawer.vue - 基因家族跨样本全景比对详细抽屉组件
 * 支持指定对照基准样本、氨基酸长度增删截短差、基因组物理位置坐标及功能产物全景比对。
 */
import { ref, watch } from 'vue'
import { getCatColor, getAminoAcidVariation } from '../../utils/pangenomeVariants'

const props = defineProps<{
  cluster: any | null
  visibleSampleIds: string[]
  sampleNames: Record<string, string>
  selectedPair: [string, string] | null
  totalSampleCount: number
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'locate-synteny', cluster: any): void
}>()

const selectedBaselineSampleId = ref<string>('')

// 每次打开或切换 cluster 时初始化对照基准株
watch(
  () => props.cluster,
  newCluster => {
    if (!newCluster) return
    if (props.selectedPair?.[0] && newCluster.presence_map?.[props.selectedPair[0]]) {
      selectedBaselineSampleId.value = props.selectedPair[0]
    } else {
      const firstPresent = props.visibleSampleIds.find((sid: string) => !!newCluster.presence_map?.[sid])
      selectedBaselineSampleId.value = firstPresent || props.visibleSampleIds[0] || ''
    }
  },
  { immediate: true }
)
</script>

<template>
  <div class="cds-detail-drawer-card" v-if="cluster">
    <div class="drawer-head">
      <div class="dh-left">
        <span
          class="chip-cat"
          :style="{ backgroundColor: getCatColor(cluster._inferredCategory || cluster.category) }"
        >
          {{ cluster._inferredCategory || cluster.category }}
        </span>
        <strong>{{ cluster.group_id }}</strong>
        <span class="dh-prod">{{ cluster.representative_product }}</span>
        <span class="dh-count">群体共享率: {{ cluster.sample_count }}/{{ totalSampleCount }} 样本</span>
      </div>
      <div class="dh-right">
        <div class="baseline-selector">
          <span class="bl-lbl">变异对照基准株:</span>
          <select v-model="selectedBaselineSampleId" class="baseline-select">
            <option v-for="sid in visibleSampleIds" :key="'opt-bl-' + sid" :value="sid">
              {{ sampleNames[sid] || sid }}
              {{ cluster.presence_map?.[sid] ? `(${cluster.presence_map[sid].length_aa} aa)` : '(缺失)' }}
            </option>
          </select>
        </div>
        <button class="btn-close-drawer" @click="emit('close')">关闭</button>
      </div>
    </div>

    <div class="drawer-samples-table-wrap">
      <table class="drawer-samples-table">
        <thead>
          <tr>
            <th>样本名称</th>
            <th>存在状态</th>
            <th>氨基酸变异类型 (相较于基准株)</th>
            <th>CDS Locus Tag</th>
            <th>基因组起止位置 (物理坐标)</th>
            <th>链方向</th>
            <th>氨基酸长度 (aa)</th>
            <th>功能产物描述 (Product)</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="sid in visibleSampleIds"
            :key="'drawer-s-' + sid"
            :class="{
              'row-baseline-highlight': sid === selectedBaselineSampleId,
              'row-present': !!cluster.presence_map?.[sid],
              'row-absent': !cluster.presence_map?.[sid]
            }"
          >
            <td>
              <strong>{{ sampleNames[sid] || sid }}</strong>
              <span v-if="sid === selectedBaselineSampleId" class="badge-ref-tag">基准</span>
            </td>
            <td>
              <span class="status-pill status-present" v-if="cluster.presence_map?.[sid]">存在 (Present)</span>
              <span class="status-pill status-absent" v-else>缺失 (Absent)</span>
            </td>
            <td>
              <div class="variation-cell">
                <span
                  class="var-badge"
                  :class="getAminoAcidVariation(cluster, sid, selectedBaselineSampleId).badgeClass"
                >
                  {{ getAminoAcidVariation(cluster, sid, selectedBaselineSampleId).badgeText }}
                </span>
                <span class="var-desc-text">
                  {{ getAminoAcidVariation(cluster, sid, selectedBaselineSampleId).diffDetail }}
                </span>
              </div>
            </td>
            <td>
              <code>{{ cluster.presence_map?.[sid]?.locus_tag || '—' }}</code>
            </td>
            <td>
              <span v-if="cluster.presence_map?.[sid]">
                {{ cluster.presence_map[sid].start }} .. {{ cluster.presence_map[sid].end }} bp
              </span>
              <span v-else class="text-slate">—</span>
            </td>
            <td>
              <code>{{ cluster.presence_map?.[sid]?.strand || '—' }}</code>
            </td>
            <td>
              <span v-if="cluster.presence_map?.[sid]" class="font-mono-val">
                {{ cluster.presence_map[sid].length_aa }} aa
              </span>
              <span v-else class="text-slate">—</span>
            </td>
            <td class="td-prod-text" :title="cluster.presence_map?.[sid]?.product">
              {{ cluster.presence_map?.[sid]?.product || '—' }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.cds-detail-drawer-card {
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  animation: fadeIn 0.15s ease-out;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.drawer-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #e2e8f0;
  padding-bottom: 8px;
  flex-wrap: wrap;
  gap: 8px;
}

.dh-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.chip-cat {
  font-size: 9.5px;
  font-weight: 700;
  color: #ffffff;
  padding: 2px 7px;
  border-radius: 3px;
}

.dh-prod {
  font-size: 12px;
  color: #334155;
  font-weight: 600;
}

.dh-count {
  font-size: 11px;
  color: #64748b;
  background: #f1f5f9;
  padding: 2px 6px;
  border-radius: 3px;
}

.dh-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.baseline-selector {
  display: flex;
  align-items: center;
  gap: 6px;
}

.bl-lbl {
  font-size: 11px;
  font-weight: 700;
  color: #475569;
}

.baseline-select {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  color: #0f172a;
  padding: 3px 8px;
}

.btn-close-drawer {
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  padding: 3px 10px;
  font-size: 11px;
  font-weight: 600;
  color: #475569;
  cursor: pointer;
}

.btn-close-drawer:hover {
  background: #fee2e2;
  color: #b91c1c;
  border-color: #fca5a5;
}

.drawer-samples-table-wrap {
  max-height: 280px;
  overflow-y: auto;
  border: 1px solid #f1f5f9;
  border-radius: 4px;
}

.drawer-samples-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
}

.drawer-samples-table th {
  background: #f8fafc;
  color: #64748b;
  font-weight: 700;
  text-align: left;
  padding: 6px 8px;
  border-bottom: 1px solid #e2e8f0;
  position: sticky;
  top: 0;
  z-index: 5;
}

.drawer-samples-table td {
  padding: 6px 8px;
  border-bottom: 1px solid #f1f5f9;
  color: #334155;
  vertical-align: middle;
}

.row-baseline-highlight {
  background: #eff6ff !important;
}

.row-present {
  background: #ffffff;
}

.row-absent {
  background: #fafafa;
  color: #94a3b8;
}

.badge-ref-tag {
  background: #2563eb;
  color: #ffffff;
  font-size: 9px;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 3px;
  margin-left: 5px;
}

.status-pill {
  font-size: 9.5px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 3px;
}

.status-present {
  background: #dcfce7;
  color: #15803d;
}

.status-absent {
  background: #f1f5f9;
  color: #94a3b8;
}

.variation-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}

.var-badge {
  font-size: 9.5px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 3px;
  white-space: nowrap;
}

.var-baseline {
  background: #2563eb;
  color: #ffffff;
}

.var-identical {
  background: #e2e8f0;
  color: #334155;
}

.var-deletion {
  background: #fee2e2;
  color: #b91c1c;
}

.var-insertion {
  background: #fef3c7;
  color: #b45309;
}

.var-present {
  background: #dbeafe;
  color: #1d4ed8;
}

.var-absent {
  background: #f1f5f9;
  color: #94a3b8;
}

.var-desc-text {
  font-size: 10px;
  color: #64748b;
}

.td-prod-text {
  max-width: 220px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.font-mono-val {
  font-family: monospace;
  font-weight: 600;
}

.text-slate {
  color: #94a3b8;
}
</style>
