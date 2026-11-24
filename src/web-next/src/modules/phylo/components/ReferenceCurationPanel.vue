<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { usePhyloStore } from '../stores/usePhyloStore'
import type { ReferenceCandidate } from '../types/phylo'

const emit = defineEmits<{
  (e: 'next-step'): void
}>()

const store = usePhyloStore()
const filterText = ref('')
const showTuning = ref(true)
const displayLimit = ref(120)

watch(filterText, () => {
  displayLimit.value = 120
})

const manualOutgroupText = computed({
  get: () => store.phageScope.outgroup_ids.join(', '),
  set: (val: string) => store.setManualOutgroupIds(val),
})

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
      (c.description || '').toLowerCase().includes(q) ||
      c.genus.toLowerCase().includes(q) ||
      c.family.toLowerCase().includes(q) ||
      c.host.toLowerCase().includes(q)
  )
})

const visibleCandidates = computed(() => filteredCandidates.value.slice(0, displayLimit.value))

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
      <button
        v-if="store.referenceCandidates.length > 0"
        class="btn-mini-inline"
        title="仅保留查询株、外群与 ICTV 代表"
        @click="store.selectOnlyIctvReps()"
      >仅留代表</button>
    </div>

    <!-- 参考群与外群规模可调参数 -->
    <div class="tuning-box">
      <div class="tuning-head" @click="showTuning = !showTuning">
        <span>参考群与外群参数配置</span>
        <span class="tuning-toggle">{{ showTuning ? '收起' : '展开调整' }}</span>
      </div>
      <template v-if="showTuning">
        <div class="t-field">
          <label>抽样策略</label>
          <select v-model="store.phageScope.sampling_mode" class="neo-input-sm">
            <option value="focused">精准属/种树</option>
            <option value="macro_family_host">宏观跨科/宿主分层全景树</option>
          </select>
        </div>
        <div class="tuning-grid">
          <div class="t-field">
            <label>参考群上限</label>
            <input
              type="number"
              v-model.number="store.phageScope.ref_max_count"
              min="5"
              max="5000"
              class="neo-input-sm"
            />
          </div>
          <div class="t-field">
            <label>每属代表数</label>
            <input
              type="number"
              v-model.number="store.phageScope.ictv_reps_per_genus"
              min="1"
              max="10"
              class="neo-input-sm"
            />
          </div>
          <div class="t-field">
            <label>覆盖属数量</label>
            <input
              type="number"
              v-model.number="store.phageScope.max_target_genera"
              min="1"
              max="50"
              class="neo-input-sm"
            />
          </div>
          <div class="t-field">
            <label>自动外群数</label>
            <input
              type="number"
              v-model.number="store.phageScope.outgroup_count"
              min="0"
              max="10"
              class="neo-input-sm"
            />
          </div>
        </div>
        <div class="t-field">
          <label>手动指定外群登录号 (逗号或空格分隔，可选)</label>
          <input
            v-model.lazy="manualOutgroupText"
            class="neo-input-sm"
            placeholder="例如: NC_055913, NC_042095"
          />
        </div>
        <button
          class="btn-reapply"
          :disabled="store.isCuratingRefs"
          @click="store.curatePhageReferences()"
        >
          {{ store.isCuratingRefs ? '正在按参数组装...' : '按当前参数重新生成参考集' }}
        </button>
      </template>
    </div>

    <div v-if="outgroupCount === 0 && store.referenceCandidates.length > 0" class="warn-banner">
      当前未指定外群，建议调大「自动外群数」重选，或在下方将至少 1 条同科不同属参考株标为 Outgroup。
    </div>

    <input
      v-model="filterText"
      class="neo-input"
      placeholder="筛选 登录号 / 名称 / 属 / 科 / 宿主..."
    />

    <div v-if="filteredCandidates.length === 0" class="empty-box">
      请先执行第 1 步「ANI 快速预判」或点击右上角「自动生成推荐集」。
    </div>

    <div v-else class="ref-list">
      <div
        v-for="item in visibleCandidates"
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

        <div v-if="item.description && item.description !== item.accession" class="ref-desc">
          {{ item.description }}
        </div>

        <div class="ref-meta">
          <span v-if="item.genus">属: {{ item.genus }}</span>
          <span v-if="item.family">科: {{ item.family }}</span>
          <span v-if="item.genome_length">{{ (item.genome_length / 1000).toFixed(1) }} kb</span>
          <span v-if="item.wg_ani !== null">ANI: {{ item.wg_ani.toFixed(1) }}%</span>
          <span v-if="item.host">{{ item.host }}</span>
        </div>
      </div>
      <button
        v-if="filteredCandidates.length > displayLimit"
        type="button"
        class="btn-load-more"
        @click="displayLimit += 120"
      >
        加载更多 (已显示 {{ visibleCandidates.length }} / 总计 {{ filteredCandidates.length }} 株)
      </button>
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
.stats-bar { display: flex; justify-content: space-between; align-items: center; background: #f1f5f9; padding: 6px 10px; border-radius: 6px; font-size: 11px; color: #334155; }
.btn-mini-inline { border: 1px solid #cbd5e1; background: #fff; color: #2563eb; border-radius: 4px; font-size: 10px; font-weight: 600; padding: 1px 6px; cursor: pointer; }
.tuning-box { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 7px; padding: 7px 9px; display: flex; flex-direction: column; gap: 6px; }
.tuning-head { display: flex; justify-content: space-between; align-items: center; font-size: 11px; font-weight: 700; color: #1e293b; cursor: pointer; }
.tuning-toggle { font-size: 10px; font-weight: 600; color: #2563eb; }
.tuning-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.t-field { display: flex; flex-direction: column; gap: 2px; }
.t-field label { font-size: 10px; font-weight: 600; color: #475569; }
.neo-input-sm { width: 100%; border: 1px solid #cbd5e1; border-radius: 5px; padding: 4px 6px; font-size: 11px; background: #fff; color: #0f172a; box-sizing: border-box; }
.btn-reapply { width: 100%; padding: 5px 8px; border: 1px solid #2563eb; border-radius: 5px; background: #eff6ff; color: #1d4ed8; font-size: 11px; font-weight: 700; cursor: pointer; }
.btn-reapply:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-load-more { width: 100%; padding: 6px 8px; border: 1px dashed #cbd5e1; border-radius: 6px; background: #f8fafc; color: #2563eb; font-size: 11px; font-weight: 600; cursor: pointer; }
.ref-desc { font-size: 10px; font-weight: 600; color: #334155; line-height: 1.3; }
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
