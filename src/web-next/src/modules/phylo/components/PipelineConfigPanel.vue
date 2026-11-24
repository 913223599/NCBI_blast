<script setup lang="ts">
import { computed, watch } from 'vue'
import { usePhyloStore } from '../stores/usePhyloStore'
import type { TreeEngineType } from '../types/phylo'

const store = usePhyloStore()

const isPhageMode = computed(() => store.workbenchMode === 'phage_taxonomy')
const isGenomeTrack = computed(() => store.effectiveTrack === 'genome')
const molType = computed(() => (isPhageMode.value ? 'protein' : store.profile?.mol_type || 'dna'))

const availableEngines = computed(() => {
  const engines = store.capabilities?.engines
  if (!engines) return []
  const list = Object.values(engines)
  if (isGenomeTrack.value) {
    return list.filter((e) => e.engine === 'bionj' || e.engine === 'nj')
  }
  if (isPhageMode.value) {
    return list.filter((e) => e.engine === 'iqtree' || e.engine === 'fasttree')
  }
  return list
})

const currentEngineCap = computed(() => {
  return store.capabilities?.engines?.[store.config.engine] || null
})

const availableModels = computed(() => {
  const cap = currentEngineCap.value
  if (!cap) return ['MFP', 'LG+G', 'JTT+G']
  return molType.value === 'protein' ? cap.models_protein : cap.models_dna
})

watch(isGenomeTrack, (genome) => {
  if (genome && store.config.engine !== 'bionj' && store.config.engine !== 'nj') {
    store.config.engine = 'bionj'
  }
})

watch(
  () => store.config.engine,
  (eng: TreeEngineType) => {
    const models = availableModels.value
    if (models.length > 0 && !models.includes(store.config.model)) {
      store.config.model = models[0]!
    }
    if (eng === 'iqtree' && store.config.bootstrap > 0 && store.config.bootstrap < 1000) {
      store.config.bootstrap = 1000
    }
  }
)

const cpuSafeMax = computed(() => store.capabilities?.cpu_safe_max || 16)
const cpuDefault = computed(() => store.capabilities?.cpu_default || 12)
const minSeqRequired = computed(() => (isPhageMode.value ? 1 : 3))
</script>

<template>
  <div class="phylo-panel">
    <div class="panel-header">
      <h3 class="panel-title">
        {{ isPhageMode ? '第 3-5 步：标志基因、比对与建树' : '分析管线配置' }}
      </h3>
      <button class="btn-link" @click="store.refreshCapabilities(true)">重检工具</button>
    </div>

    <div v-if="store.capabilities" class="hw-banner">
      <span>CPU 安全上限: {{ cpuSafeMax }} / {{ store.capabilities.cpu_logical_cores }} 核</span>
      <span v-if="store.capabilities.gpu_available" class="gpu-on">
        CUDA: {{ store.capabilities.gpu_name }} ({{ store.capabilities.gpu_free_vram_mb }} MB 空闲)
      </span>
      <span v-else class="gpu-off">CUDA 不可用 (自动走多核 NumPy)</span>
    </div>

    <div class="form-group">
      <label>任务标题 (可选)</label>
      <input v-model="store.config.title" class="neo-input" placeholder="留空将自动使用文件名" />
    </div>

    <!-- 噬菌体 8 步科研模式专属配置 -->
    <template v-if="isPhageMode">
      <div class="form-group">
        <label>第 3 步：标志基因路径</label>
        <select v-model="store.config.marker_mode" class="neo-select">
          <option value="terl">首选：大末端酶亚基 TerL (55 PHROGs HMM 精准提取)</option>
          <option value="proteome">备选：全基因组蛋白质组树 (DIAMOND S_G，目/科级定位)</option>
        </select>
      </div>

      <template v-if="store.config.marker_mode === 'terl'">
        <div class="form-row">
          <div class="form-group">
            <label>第 4 步：MAFFT 算法</label>
            <select v-model="store.config.msa_strategy" class="neo-select">
              <option value="linsi">L-INS-i (高精度首选)</option>
              <option value="einsi">E-INS-i (结构差异/长插入)</option>
              <option value="auto">--auto (自适应)</option>
              <option value="fast">Fast (快速启发)</option>
            </select>
          </div>
          <div class="form-group">
            <label>比对后修剪 (ClipKIT)</label>
            <select v-model="store.config.trim_mode" class="neo-select">
              <option value="kpic">ClipKIT -m kpic (推荐)</option>
              <option value="kpic_smart_gap">ClipKIT -m kpic-smart-gap</option>
              <option value="smart_gap">ClipKIT -m smart-gap</option>
              <option value="gap">按缺口比例过滤</option>
            </select>
          </div>
        </div>

        <div class="form-row">
          <div class="form-group">
            <label>第 5 步：构树引擎</label>
            <select v-model="store.config.engine" class="neo-select">
              <option
                v-for="eng in availableEngines"
                :key="eng.engine"
                :value="eng.engine"
                :disabled="!eng.available"
              >
                {{ eng.engine === 'iqtree' ? 'IQ-TREE ML' : 'FastTree' }}
              </option>
            </select>
          </div>
          <div class="form-group">
            <label>替换模型 (ModelFinder)</label>
            <select v-model="store.config.model" class="neo-select">
              <option v-for="m in availableModels" :key="m" :value="m">{{ m }}</option>
            </select>
          </div>
        </div>

        <div v-if="store.config.engine === 'iqtree'" class="card-sub">
          <div class="form-row">
            <div class="form-group">
              <label>UFBoot (-B): {{ store.config.bootstrap }}</label>
              <input
                type="number"
                v-model.number="store.config.bootstrap"
                min="0"
                max="5000"
                step="500"
                class="neo-input"
              />
            </div>
            <div class="form-group">
              <label>SH-aLRT (-alrt): {{ store.config.iqtree_alrt }}</label>
              <input
                type="number"
                v-model.number="store.config.iqtree_alrt"
                min="0"
                max="5000"
                step="500"
                class="neo-input"
              />
            </div>
          </div>
          <div class="form-row">
            <label class="chk" style="margin-top: 4px">
              <input type="checkbox" v-model="store.config.iqtree_bnni" />
              <span>开启 -bnni 降低过度乐观支持值风险</span>
            </label>
            <div class="form-group">
              <label>随机种子 (--seed)</label>
              <input type="number" v-model.number="store.config.iqtree_seed" class="neo-input" />
            </div>
          </div>
        </div>
      </template>

      <template v-else>
        <div class="form-group">
          <label>蛋白质组树聚类算法</label>
          <select v-model="store.phageScope.proteome_tree_method" class="neo-select">
            <option value="bionj">BioNJ (经典邻接法，-ln(S_G) 进化距离)</option>
            <option value="upgma">UPGMA (超度量外缘齐平，1 - S_G，适配环形全景图)</option>
          </select>
        </div>
      </template>
    </template>

    <!-- 通用进化树模式配置 -->
    <template v-else>
      <div class="form-group">
        <label>分析赛道 (Track)</label>
        <select v-model="store.config.track" class="neo-select">
          <option value="auto">
            自动智能分流 ({{ store.profile?.recommended_track === 'genome' ? '当前推荐: 全基因组 Mash' : '当前推荐: 经典比对' }})
          </option>
          <option value="genome">全基因组无对齐 (Mash MinHash + BioNJ/NJ)</option>
          <option value="gene">经典比对构树 (MSA + ML/NJ/Bayesian)</option>
        </select>
      </div>

      <template v-if="isGenomeTrack">
        <div class="track-tip">
          全基因组模式将跳过耗时的全局 MSA，使用 Mash MinHash 在秒级计算全基因组演化距离。
        </div>
        <div class="form-row">
          <div class="form-group">
            <label>K-mer 长度: {{ store.config.mash_kmer }}</label>
            <input type="range" v-model.number="store.config.mash_kmer" min="15" max="31" step="2" class="neo-range" />
          </div>
          <div class="form-group">
            <label>Sketch 采样数</label>
            <select v-model.number="store.config.mash_sketch" class="neo-select">
              <option :value="1000">1,000 (快速)</option>
              <option :value="5000">5,000 (高敏)</option>
              <option :value="10000">10,000 (精细)</option>
            </select>
          </div>
        </div>
      </template>

      <template v-else>
        <div class="form-row">
          <div class="form-group">
            <label>多序列比对 (MSA)</label>
            <select v-model="store.config.msa" class="neo-select">
              <option value="none">无需比对 (已对齐)</option>
              <option value="mafft" :disabled="!store.capabilities?.tools.mafft?.available">MAFFT</option>
              <option value="muscle" :disabled="!store.capabilities?.tools.muscle?.available">MUSCLE</option>
              <option value="clustalo" :disabled="!store.capabilities?.tools.clustalo?.available">ClustalO</option>
            </select>
          </div>
          <div class="form-group" v-if="store.config.msa === 'mafft'">
            <label>MAFFT 策略</label>
            <select v-model="store.config.msa_strategy" class="neo-select">
              <option value="auto">Auto (自适应)</option>
              <option value="fast">Fast (--retree 1)</option>
              <option value="linsi">L-INS-i (高精度)</option>
              <option value="einsi">E-INS-i (长插入)</option>
            </select>
          </div>
        </div>

        <div class="form-group">
          <label>比对修剪模式</label>
          <select v-model="store.config.trim_mode" class="neo-select">
            <option value="none">不修剪 (保留全部对齐列)</option>
            <option value="kpic">ClipKIT -m kpic</option>
            <option value="kpic_smart_gap">ClipKIT -m kpic-smart-gap</option>
            <option value="gap">按缺口比例过滤</option>
          </select>
        </div>
      </template>

      <div class="form-group">
        <label>构树引擎 (Engine)</label>
        <select v-model="store.config.engine" class="neo-select">
          <option
            v-for="eng in availableEngines"
            :key="eng.engine"
            :value="eng.engine"
            :disabled="!eng.available"
          >
            {{ eng.label }} {{ eng.available ? '' : '[不可用]' }}
          </option>
        </select>
        <div v-if="currentEngineCap?.notes" class="hint-text">{{ currentEngineCap.notes }}</div>
      </div>

      <div class="form-group" v-if="!isGenomeTrack">
        <label>替换模型 (Model)</label>
        <select v-model="store.config.model" class="neo-select">
          <option v-for="m in availableModels" :key="m" :value="m">{{ m }}</option>
        </select>
      </div>

      <div class="form-group" v-if="!isGenomeTrack && currentEngineCap?.supports_bootstrap">
        <label>Bootstrap 采样: {{ store.config.bootstrap === 0 ? '关闭' : store.config.bootstrap + ' 次' }}</label>
        <input
          type="range"
          v-model.number="store.config.bootstrap"
          :min="currentEngineCap.min_bootstrap"
          :max="currentEngineCap.max_bootstrap"
          :step="currentEngineCap.bootstrap_step || 50"
          class="neo-range"
        />
      </div>

      <div class="form-group" v-if="!isGenomeTrack && store.config.engine === 'mrbayes'">
        <label>MCMC 迭代代数: {{ store.config.mrbayes_ngen.toLocaleString() }}</label>
        <input type="range" v-model.number="store.config.mrbayes_ngen" min="2000" max="100000" step="2000" class="neo-range" />
      </div>
    </template>

    <!-- 并发与缓存公共选项 -->
    <div class="form-group">
      <label>
        并发线程: {{ store.config.threads === 0 ? `自动 (安全分配 ${cpuDefault} 核)` : `${store.config.threads} 核 (上限 ${cpuSafeMax})` }}
      </label>
      <input type="range" v-model.number="store.config.threads" min="0" :max="cpuSafeMax" step="1" class="neo-range" />
    </div>

    <div class="check-row">
      <label class="chk" v-if="!isPhageMode">
        <input type="checkbox" v-model="store.config.use_gpu" :disabled="!store.capabilities?.gpu_available" />
        <span>PyTorch CUDA 加速距离计算</span>
      </label>
      <label class="chk">
        <input type="checkbox" v-model="store.config.use_cache" />
        <span>启用阶段缓存复用 (回退重跑秒级命中)</span>
      </label>
      <label class="chk">
        <input type="checkbox" v-model="store.config.midpoint_root" />
        <span>自动外群 / 中点定根</span>
      </label>
    </div>

    <div class="action-bar">
      <button
        v-if="!store.isRunning"
        class="btn-start"
        :disabled="store.isSubmitting || !store.profile || store.profile.sequence_count < minSeqRequired"
        @click="store.startAnalysis()"
      >
        {{
          store.isSubmitting
            ? '正在启动...'
            : isPhageMode
              ? '启动 8 步科研建树与质检打包'
              : '启动系统发育分析'
        }}
      </button>
      <button
        v-else
        class="btn-stop"
        :disabled="store.isCancelling"
        @click="store.cancelActiveJob()"
      >
        {{ store.isCancelling ? '正在强杀进程...' : '立即终止当前分析' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.phylo-panel { display: flex; flex-direction: column; gap: 10px; }
.panel-header { display: flex; justify-content: space-between; align-items: center; }
.panel-title { font-size: 14px; font-weight: 700; color: #0f172a; margin: 0; }
.btn-link { background: none; border: none; color: #2563eb; font-size: 12px; cursor: pointer; font-weight: 600; }
.hw-banner { display: flex; flex-direction: column; gap: 2px; font-size: 11px; background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 8px; padding: 7px 10px; color: #334155; }
.gpu-on { color: #15803d; font-weight: 600; }
.gpu-off { color: #64748b; }
.card-sub { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 7px; padding: 8px; display: flex; flex-direction: column; gap: 6px; }
.track-tip { font-size: 11px; color: #1e40af; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 6px; padding: 7px 9px; line-height: 1.4; }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.form-group { display: flex; flex-direction: column; gap: 3px; }
.form-group label { font-size: 11px; font-weight: 600; color: #475569; }
.neo-input, .neo-select { width: 100%; border: 1px solid #cbd5e1; border-radius: 6px; padding: 5px 8px; font-size: 12px; background: #fff; color: #0f172a; box-sizing: border-box; }
.neo-range { width: 100%; accent-color: #2563eb; }
.hint-text { font-size: 11px; color: #64748b; line-height: 1.35; }
.check-row { display: flex; flex-direction: column; gap: 5px; font-size: 11px; color: #334155; }
.chk { display: flex; align-items: center; gap: 6px; cursor: pointer; }
.chk input { accent-color: #2563eb; }
.action-bar { margin-top: 4px; }
.btn-start { width: 100%; padding: 10px; border: none; border-radius: 8px; background: #2563eb; color: #fff; font-size: 13px; font-weight: 700; cursor: pointer; }
.btn-start:disabled { background: #94a3b8; cursor: not-allowed; }
.btn-stop { width: 100%; padding: 10px; border: none; border-radius: 8px; background: #dc2626; color: #fff; font-size: 13px; font-weight: 700; cursor: pointer; }
</style>
