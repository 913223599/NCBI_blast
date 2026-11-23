<script setup lang="ts">
import { computed, ref } from 'vue'
import { usePhyloStore } from '../stores/usePhyloStore'
import type { ReferenceCandidate } from '../types/phylo'

const emit = defineEmits<{
  (e: 'next-step'): void
}>()

const store = usePhyloStore()
const filterText = ref('')

const selectedList = computed(() => store.referenceCandidates.filter((r) => r.selected))
const queryCount = computed(() => selectedList.value.filter((r) => r.role === 'query').length)
const repCount = computed(() => selectedList.value.filter((r) => r.role === 'ictv_rep').length)
const outgroupCount = computed(() => selectedList.value.filter((r) => r.role === 'outgroup').length)

const filteredCandidates = computed(() => {
  const q = filterText.value.trim().toLowerCase()
  if (!q) return store.referenceCandidates
  return store.referenceCandidates.filter(
    (c) =>
      c.accession.toLowerCase().includes(q) ||
      c.genus.toLowerCase().includes(q) ||
      c.family.toLowerCase().includes(q) ||
      c.host.toLowerCase().includes(q)
  )
})

function onRoleChange(acc: string, ev: Event) {
  const target = ev.target as HTMLSelectElement
  store.setReferenceRole(acc, target.value as ReferenceCandidate['role'])
}
</script>

<template>
  <div class="phylo-panel">
    <div class="panel-header">
      <h3 class="panel-title">第 2 步：参考序列集与外群</h3>
      <button
        class="btn-link"
        :disabled="store.isCuratingRefs"
        @click="store.curatePhageReferences()"
      >
        {{ store.isCuratingRefs ? '组装中...' : '自动生成推荐集' }}
      </button>
    </div>

    <p class="hint-text">
      要“代表性”不要“穷举”：需确保每个目标属含 1-2 条 ICTV 代表，且至少指定 1 条目标类群之外的外群。
    </p>

    <div class="stats-bar">
      <span>已选: <b>{{ selectedList.length }}</b></span>
      <span>查询: <b>{{ queryCount }}</b></span>
      <span>ICTV代表: <b>{{ repCount }}</b></span>
      <span :class="{ 'og-warn': outgroupCount === 0 }">
        外群: <b>{{ outgroupCount }}</b>
      </span>
    </div>

    <div v-if="outgroupCount === 0 && store.referenceCandidates.length > 0" class="warn-banner">
      当前未指定外群，建议在下方至少将 1 条同科不同属参考株标为 Outgroup，以确定进化树根方向。
    </div>

    <input
      v-model="filterText"
      class="neo-input"
      placeholder="筛选 Accession / 属 / 科 / 宿主..."
    />

    <div v-if="filteredCandidates.length === 0" class="empty-box">
      请先执行第 1 步「ANI 快速预判」或点击右上角「自动生成推荐集」。
    </div>

    <div v-else class="ref-list">
      <div
        v-for="item in filteredCandidates"
        :key="item.accession"
        class="ref-card"
        :class="{
          'ref-query': item.role === 'query',
          'ref-outgroup': item.role === 'outgroup',
          'ref-dim': !item.selected,
        }"
      >
        <div class="ref-top">
          <label class="ref-check">
            <input
              type="checkbox"
              :checked="item.selected"
              :disabled="item.role === 'query'"
              @change="store.toggleReferenceSelected(item.accession)"
            />
            <span class="ref-acc">{{ item.accession }}</span>
          </label>
          <select
            v-if="item.role !== 'query'"
            class="role-select"
            :value="item.role"
            @change="(e) => onRoleChange(item.accession, e)"
          >
            <option value="ictv_rep">ICTV代表</option>
            <option value="neighbor">近邻参考</option>
            <option value="outgroup">外群 (Outgroup)</option>
          </select>
          <span v-else class="query-pill">新测序株</span>
        </div>

        <div class="ref-meta">
          <span v-if="item.genus">属: {{ item.genus }}</span>
          <span v-if="item.family">科: {{ item.family }}</span>
          <span v-if="item.genome_length">{{ (item.genome_length / 1000).toFixed(1) }} kb</span>
          <span v-if="item.wg_ani !== null">ANI: {{ item.wg_ani.toFixed(1) }}%</span>
          <span v-if="item.host">{{ item.host }}</span>
        </div>
      </div>
    </div>

    <button
      class="btn-next"
      :disabled="selectedList.length === 0"
      @click="emit('next-step')"
    >
      确认参考集 ({{ selectedList.length }} 株)，前往第 3-5 步建树
    </button>
  </div>
</template>

<style scoped>
.phylo-panel { display: flex; flex-direction: column; gap: 9px; }
.panel-header { display: flex; justify-content: space-between; align-items: center; }
.panel-title { font-size: 14px; font-weight: 700; color: #0f172a; margin: 0; }
.btn-link { background: none; border: none; color: #2563eb; font-size: 11px; font-weight: 600; cursor: pointer; }
.hint-text { font-size: 11px; color: #64748b; margin: 0; line-height: 1.4; }
.stats-bar { display: flex; justify-content: space-between; background: #f1f5f9; padding: 6px 10px; border-radius: 6px; font-size: 11px; color: #334155; }
.og-warn { color: #dc2626; }
.warn-banner { font-size: 11px; color: #92400e; background: #fffbeb; border: 1px solid #fde68a; border-radius: 6px; padding: 6px 8px; }
.neo-input { width: 100%; border: 1px solid #cbd5e1; border-radius: 6px; padding: 5px 8px; font-size: 12px; box-sizing: border-box; }
.empty-box { text-align: center; padding: 18px 10px; font-size: 11px; color: #94a3b8; background: #f8fafc; border: 1px dashed #cbd5e1; border-radius: 8px; }
.ref-list { display: flex; flex-direction: column; gap: 6px; max-height: 360px; overflow-y: auto; }
.ref-card { background: #fff; border: 1px solid #e2e8f0; border-radius: 7px; padding: 7px 8px; display: flex; flex-direction: column; gap: 4px; }
.ref-query { border-color: #fecaca; background: #fef2f2; }
.ref-outgroup { border-color: #94a3b8; background: #f8fafc; }
.ref-dim { opacity: 0.52; }
.ref-top { display: flex; justify-content: space-between; align-items: center; gap: 6px; }
.ref-check { display: flex; align-items: center; gap: 6px; cursor: pointer; min-width: 0; }
.ref-acc { font-family: monospace; font-size: 11px; font-weight: 700; color: #0f172a; overflow: hidden; text-overflow: ellipsis; }
.role-select { border: 1px solid #cbd5e1; border-radius: 4px; font-size: 10px; padding: 2px 4px; background: #fff; color: #334155; }
.query-pill { font-size: 10px; font-weight: 700; color: #b91c1c; background: #fee2e2; padding: 1px 6px; border-radius: 999px; }
.ref-meta { display: flex; flex-wrap: wrap; gap: 7px; font-size: 10px; color: #64748b; }
.btn-next { width: 100%; padding: 9px; border: none; border-radius: 8px; background: #2563eb; color: #fff; font-size: 12px; font-weight: 700; cursor: pointer; }
.btn-next:disabled { background: #94a3b8; cursor: not-allowed; }
</style>
