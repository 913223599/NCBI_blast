<script setup lang="ts">
import { computed } from 'vue'
import { usePhyloStore } from '../stores/usePhyloStore'

const emit = defineEmits<{
  (e: 'next-step'): void
}>()

const store = usePhyloStore()

const aniCallLabel: Record<string, { text: string; cls: string }> = {
  same_species: { text: '>=95% 同种候选', cls: 'badge-green' },
  same_genus_new_species: { text: '70-95% 同属新种', cls: 'badge-blue' },
  genus_boundary_ambiguous: { text: '65-75% 属界模糊', cls: 'badge-amber' },
  novel_genus_candidate: { text: '<70% 候选新属', cls: 'badge-purple' },
}

const heatLabels = computed(() => {
  return (store.aniResult?.matrix_labels || []).slice(0, 12)
})

const heatRows = computed(() => {
  const mat = store.aniResult?.wgani_matrix || []
  const count = heatLabels.value.length
  return mat.slice(0, count).map((row) => row.slice(0, count))
})

function cellColor(val: number): string {
  if (val >= 95) return '#15803d'
  if (val >= 70) return '#2563eb'
  if (val >= 50) return '#38bdf8'
  if (val >= 20) return '#bae6fd'
  return '#f1f5f9'
}
</script>

<template>
  <div class="phylo-panel">
    <h3 class="panel-title">第 0-1 步：交付边界与 ANI 预判</h3>
    <p class="hint-text">
      原则：ANI/wgANI 负责“定性（种 >=95% / 属 >=70%）”，进化树负责“拓扑定位与自洽检验”。
    </p>

    <!-- 第 0 步：交付边界设定 -->
    <div class="card-box">
      <div class="sub-title">第 0 步：明确交付边界</div>
      <div class="form-row">
        <div class="form-group">
          <label>判定层级</label>
          <select v-model="store.phageScope.target_rank" class="neo-select">
            <option value="genus">属 / 种级定位 (推荐)</option>
            <option value="species">仅种内精细分辨</option>
            <option value="family_order">目 / 科级宏观定位</option>
          </select>
        </div>
        <div class="form-group">
          <label>ANI 精算引擎</label>
          <select v-model="store.config.ani_engine" class="neo-select">
            <option value="viridic_blastn">VIRIDIC-BLASTn (标准 wgANI)</option>
            <option value="fastani">FastANI (高速)</option>
            <option value="skani">skani (极速)</option>
            <option value="mash">仅 Mash MinHash</option>
          </select>
        </div>
      </div>

      <div class="form-row">
        <div class="form-group">
          <label>去冗余 ANI 阈值</label>
          <select v-model.number="store.phageScope.derep_ani" class="neo-select">
            <option :value="0.9">90% ANI (dRep 标准)</option>
            <option :value="0.95">95% ANI (种级合并)</option>
          </select>
        </div>
        <div class="form-group">
          <label>Treemmer 目标条数</label>
          <input
            type="number"
            v-model.number="store.phageScope.treemmer_target"
            min="10"
            max="5000"
            class="neo-input"
          />
        </div>
      </div>

      <div class="form-row">
        <div class="form-group">
          <label>参考群总数上限</label>
          <input
            type="number"
            v-model.number="store.phageScope.ref_max_count"
            min="5"
            max="5000"
            class="neo-input"
          />
        </div>
        <div class="form-group">
          <label>INPHARED 初筛 Top K</label>
          <input
            type="number"
            v-model.number="store.phageScope.mash_top_k"
            min="5"
            max="1000"
            class="neo-input"
          />
        </div>
      </div>

      <div class="form-group">
        <label>参考群抽样策略</label>
        <select v-model="store.phageScope.sampling_mode" class="neo-select">
          <option value="focused">精准属/种树（围绕近邻与同科代表）</option>
          <option value="macro_family_host">宏观全景树（跨病毒科与宿主门分层抽样，支持千株以上规模）</option>
        </select>
      </div>

      <div class="form-group">
        <label>可选离线参考库目录</label>
        <input
          v-model="store.phageScope.local_ref_dir"
          class="neo-input"
          placeholder="留空则自动检索本地 INPHARED + 缓存/NCBI"
        />
      </div>

      <label class="chk">
        <input type="checkbox" v-model="store.phageScope.enable_checkv" />
        <span>启用 CheckV 完整性过滤 (Completeness >= 95%)</span>
      </label>
    </div>

    <button
      class="btn-primary"
      :disabled="store.isScreeningAni || !store.profile || store.profile.sequence_count < 1"
      @click="store.runPhageAniScreen()"
    >
      {{ store.isScreeningAni ? '正在扫描 INPHARED 与计算 wgANI...' : '运行第 1 步：全库 ANI 快速预判' }}
    </button>

    <!-- 第 1 步预判结果 -->
    <template v-if="store.aniResult">
      <div
        class="summary-card"
        :class="{ 'summary-ambiguous': store.aniResult.ambiguous_zone }"
      >
        <div class="sum-head">
          <span>ANI 初步定性结论 ({{ store.aniResult.engine_used }})</span>
        </div>
        <div class="sum-body">{{ store.aniResult.summary_call }}</div>
        <div v-for="(w, i) in store.aniResult.warnings" :key="i" class="sum-warn">
          {{ w }}
        </div>
      </div>

      <div v-if="store.aniResult.top_hits.length" class="card-box">
        <div class="sub-title">
          Top 相似株 (共命中 {{ store.aniResult.top_hits.length }} 条)
        </div>
        <div class="hit-list">
          <div
            v-for="hit in store.aniResult.top_hits.slice(0, 10)"
            :key="hit.accession"
            class="hit-row"
          >
            <div class="hit-top">
              <span class="hit-acc">{{ hit.accession }}</span>
              <span
                class="hit-badge"
                :class="aniCallLabel[hit.classification_call]?.cls || 'badge-blue'"
              >
                {{ aniCallLabel[hit.classification_call]?.text || hit.classification_call }}
              </span>
            </div>
            <div class="hit-meta">
              <span>wgANI: <b>{{ hit.wg_ani.toFixed(1) }}%</b></span>
              <span>AF: {{ Math.min(hit.af_query, hit.af_ref).toFixed(0) }}%</span>
              <span v-if="hit.genus">属: {{ hit.genus }}</span>
              <span v-if="hit.mosaic_warning" class="mosaic-tag">嵌合提示</span>
            </div>
          </div>
        </div>
      </div>

      <!-- VIRIDIC-wgANI 轻热图 -->
      <div v-if="heatLabels.length >= 2" class="card-box">
        <div class="sub-title">wgANI 相似性热图 (前 {{ heatLabels.length }} 株)</div>
        <div class="heat-grid-wrap">
          <table class="heat-table">
            <thead>
              <tr>
                <th></th>
                <th v-for="lbl in heatLabels" :key="lbl" :title="lbl">
                  {{ lbl.slice(0, 7) }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, rIdx) in heatRows" :key="heatLabels[rIdx]">
                <td class="heat-row-lbl" :title="heatLabels[rIdx]">
                  {{ heatLabels[rIdx]?.slice(0, 8) }}
                </td>
                <td
                  v-for="(val, cIdx) in row"
                  :key="cIdx"
                  class="heat-cell"
                  :style="{
                    background: cellColor(val),
                    color: val >= 65 ? '#ffffff' : '#334155',
                  }"
                  :title="`${heatLabels[rIdx]} vs ${heatLabels[cIdx]}: ${val.toFixed(2)}%`"
                >
                  {{ Math.round(val) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <button class="btn-next" @click="emit('next-step')">
        进入第 2 步：审阅参考集与外群 ({{ store.referenceCandidates.length }} 条)
      </button>
    </template>
  </div>
</template>

<style scoped>
.phylo-panel { display: flex; flex-direction: column; gap: 10px; }
.panel-title { font-size: 14px; font-weight: 700; color: #0f172a; margin: 0; }
.hint-text { font-size: 11px; color: #64748b; margin: 0; line-height: 1.45; }
.card-box { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px; display: flex; flex-direction: column; gap: 8px; }
.sub-title { font-size: 12px; font-weight: 700; color: #1e293b; }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.form-group { display: flex; flex-direction: column; gap: 3px; }
.form-group label { font-size: 11px; font-weight: 600; color: #475569; }
.neo-input, .neo-select { width: 100%; border: 1px solid #cbd5e1; border-radius: 6px; padding: 5px 8px; font-size: 12px; background: #fff; color: #0f172a; box-sizing: border-box; }
.chk { display: flex; align-items: center; gap: 6px; font-size: 11px; color: #334155; cursor: pointer; }
.btn-primary { width: 100%; padding: 9px; border: none; border-radius: 8px; background: #2563eb; color: #fff; font-size: 12px; font-weight: 700; cursor: pointer; }
.btn-primary:disabled { background: #94a3b8; cursor: not-allowed; }
.btn-next { width: 100%; padding: 8px; border: 1px solid #2563eb; border-radius: 7px; background: #eff6ff; color: #1d4ed8; font-size: 12px; font-weight: 700; cursor: pointer; }
.summary-card { background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 9px 10px; font-size: 11px; color: #14532d; display: flex; flex-direction: column; gap: 4px; }
.summary-card.summary-ambiguous { background: #fffbeb; border-color: #fde68a; color: #78350f; }
.sum-head { font-weight: 700; font-size: 12px; }
.sum-body { line-height: 1.45; }
.sum-warn { color: #b45309; background: rgba(251, 191, 36, 0.15); padding: 3px 6px; border-radius: 4px; }
.hit-list { display: flex; flex-direction: column; gap: 6px; max-height: 220px; overflow-y: auto; }
.hit-row { background: #fff; border: 1px solid #e2e8f0; border-radius: 6px; padding: 6px 8px; display: flex; flex-direction: column; gap: 3px; }
.hit-top { display: flex; justify-content: space-between; align-items: center; }
.hit-acc { font-family: monospace; font-size: 11px; font-weight: 700; color: #0f172a; }
.hit-badge { font-size: 10px; padding: 1px 6px; border-radius: 999px; font-weight: 600; }
.badge-green { background: #dcfce7; color: #166534; }
.badge-blue { background: #dbeafe; color: #1e40af; }
.badge-amber { background: #fef3c7; color: #92400e; }
.badge-purple { background: #f3e8ff; color: #6b21a8; }
.hit-meta { display: flex; flex-wrap: wrap; gap: 8px; font-size: 10px; color: #475569; }
.mosaic-tag { color: #b91c1c; font-weight: 700; }
.heat-grid-wrap { overflow-x: auto; }
.heat-table { border-collapse: collapse; font-size: 9px; font-family: monospace; width: 100%; }
.heat-table th { font-weight: 600; color: #475569; padding: 2px; text-align: center; }
.heat-row-lbl { color: #334155; font-weight: 600; padding: 2px 4px; white-space: nowrap; }
.heat-cell { text-align: center; padding: 3px 2px; border: 1px solid #ffffff; border-radius: 2px; }
</style>
