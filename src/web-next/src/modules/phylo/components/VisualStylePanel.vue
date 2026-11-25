<script setup lang="ts">
import { usePhyloStore } from '../stores/usePhyloStore'
import { phyloApi } from '../api/phyloApi'
import PublicationExportCard from './PublicationExportCard.vue'

const store = usePhyloStore()

function downloadFormat(fmt: 'newick' | 'distance_csv' | 'report_json' | 'delivery_zip') {
  if (!store.currentJob) return
  window.open(phyloApi.getExportUrl(store.currentJob.job_id, fmt), '_blank')
}
</script>

<template>
  <div class="phylo-panel">
    <h3 class="panel-title">视图与拓扑控制</h3>

    <div class="form-group">
      <label>树形布局</label>
      <select v-model="store.visual.layout" class="neo-select">
        <option value="rect">矩形分支树 (Rectangular)</option>
        <option value="circular">环形放射树 (Circular)</option>
        <option value="unrooted">无根拓扑图 (Unrooted)</option>
      </select>
    </div>

    <div class="form-group">
      <label>分支排序策略</label>
      <select v-model="store.visual.sortMode" class="neo-select" @change="store.applyLocalSort()">
        <option value="original">原始顺序 (Original)</option>
        <option value="ladder-right">右梯形化 (Ladderize Right)</option>
        <option value="ladder-left">左梯形化 (Ladderize Left)</option>
        <option value="taxonomic">名称字典序 (Taxonomic)</option>
        <option value="distance">分枝长度排序 (Distance)</option>
      </select>
    </div>

    <div class="form-group">
      <label>科研期刊配色主题</label>
      <select v-model="store.visual.journalTheme" class="neo-select">
        <option value="nature">Nature (NPG) 学术经典</option>
        <option value="lancet">The Lancet 柳叶刀配色</option>
        <option value="okabe_ito">Okabe-Ito (色盲绝对安全)</option>
        <option value="monochrome">MBE 黑白极简印刷风</option>
      </select>
    </div>

    <div class="check-col">
      <label class="chk">
        <input type="checkbox" v-model="store.visual.useBranchLengths" />
        <span>按真实演化距离绘制枝长</span>
      </label>
      <label class="chk" v-if="store.visual.useBranchLengths && store.visual.layout !== 'unrooted'">
        <input type="checkbox" v-model="store.visual.alignTipLabels" />
        <span>对齐叶标签并显示虚线引导线</span>
      </label>
      <label class="chk">
        <input type="checkbox" v-model="store.visual.showLabels" />
        <span>显示样本名称标签</span>
      </label>
      <label class="chk" v-if="store.visual.showLabels">
        <input type="checkbox" v-model="store.visual.italicizeTaxa" />
        <span>拉丁分类学属名自动斜体</span>
      </label>
    </div>

    <div class="form-group" v-if="store.visual.showLabels">
      <label>叶节点标签格式</label>
      <select v-model="store.visual.labelFormat" class="neo-select">
        <option value="name_acc">实际名称 (登录号) [发表标准]</option>
        <option value="name">仅实际名称</option>
        <option value="accession">仅登录号</option>
      </select>
    </div>

    <div class="check-col">
      <label class="chk">
        <input type="checkbox" v-model="store.visual.showSupport" />
        <span>显示内部节点支持率 (支持双支持值)</span>
      </label>
      <label class="chk">
        <input type="checkbox" v-model="store.visual.highlightStrongUfboot" />
        <span>UFBoot &gt;= 95 实心黑点 / 其余空心点</span>
      </label>
      <label class="chk" v-if="store.visual.layout !== 'unrooted'">
        <input type="checkbox" v-model="store.visual.showCladeShading" />
        <span>单系支系柔和背景阴影 (Clade Shading)</span>
      </label>
      <label class="chk" v-if="store.visual.layout !== 'unrooted'">
        <input type="checkbox" v-model="store.visual.showMetadataStrips" />
        <span>显示外圈分类轨道 (Genus / Host / Size)</span>
      </label>
      <label class="chk" v-if="store.visual.layout === 'circular'">
        <input type="checkbox" v-model="store.visual.smartLabelCull" />
        <span>大规模环形树精简背景标签 (放大自动恢复)</span>
      </label>
    </div>

    <div class="form-group" v-if="store.visual.showSupport">
      <label>支持率显示阈值: &gt;= {{ store.visual.supportThreshold }}%</label>
      <input type="range" v-model.number="store.visual.supportThreshold" min="0" max="100" step="5" class="neo-range" />
    </div>

    <div class="form-group">
      <label>字体大小: {{ store.visual.fontSize }}px</label>
      <input type="range" v-model.number="store.visual.fontSize" min="8" max="22" step="1" class="neo-range" />
    </div>

    <div class="form-group">
      <label>行间距 (矩形模式): {{ store.visual.rowSpacing }}px</label>
      <input type="range" v-model.number="store.visual.rowSpacing" min="14" max="48" step="2" class="neo-range" />
    </div>

    <div class="btn-grid">
      <button class="btn-sec" :disabled="!store.hasTree" @click="store.rerootMidpoint()">中点定根</button>
      <button class="btn-sec" :disabled="!store.hasTree" @click="store.resetTopology()">还原原始拓扑</button>
    </div>

    <div v-if="store.currentJob?.metrics" class="metrics-card">
      <div class="m-title">拓扑质量摘要</div>
      <div class="m-row"><span>叶子节点数</span><b>{{ store.currentJob.metrics.leaf_count }}</b></div>
      <div class="m-row"><span>总进化枝长</span><b>{{ store.currentJob.metrics.total_branch_length }}</b></div>
      <div class="m-row"><span>演化直径</span><b>{{ store.currentJob.metrics.diameter }}</b></div>
      <div class="m-row" v-if="store.currentJob.metrics.mean_support !== null">
        <span>UFBoot 均值</span><b>{{ store.currentJob.metrics.mean_support }}%</b>
      </div>
      <div class="m-row" v-if="store.currentJob.metrics.mean_alrt !== null && store.currentJob.metrics.mean_alrt !== undefined">
        <span>SH-aLRT 均值</span><b>{{ store.currentJob.metrics.mean_alrt }}%</b>
      </div>
      <div class="m-row" v-if="store.currentJob.metrics.strong_ufboot_ratio !== null && store.currentJob.metrics.strong_ufboot_ratio !== undefined">
        <span>UFBoot &gt;= 95 占比</span><b>{{ store.currentJob.metrics.strong_ufboot_ratio }}%</b>
      </div>
      <div class="m-row" v-if="store.currentJob.metrics.best_model">
        <span>最优替换模型</span><b>{{ store.currentJob.metrics.best_model }}</b>
      </div>
      <div class="m-row" v-if="store.currentJob.metrics.best_model_bic !== null && store.currentJob.metrics.best_model_bic !== undefined">
        <span>ModelFinder BIC</span><b>{{ store.currentJob.metrics.best_model_bic }}</b>
      </div>
    </div>

    <div v-if="store.currentJob" class="export-group">
      <div class="m-title">后端归档数据导出</div>
      <div class="btn-grid">
        <button class="btn-sec" @click="downloadFormat('newick')">导出 Newick</button>
        <button class="btn-sec" @click="downloadFormat('report_json')">导出报告 JSON</button>
        <button
          v-if="store.currentJob.artifacts?.distance_csv"
          class="btn-sec"
          @click="downloadFormat('distance_csv')"
        >导出距离矩阵 CSV</button>
        <button
          v-if="store.currentJob.artifacts?.delivery_zip"
          class="btn-sec"
          @click="downloadFormat('delivery_zip')"
        >完整交付 ZIP</button>
      </div>
    </div>

    <PublicationExportCard />
  </div>
</template>

<style scoped>
.phylo-panel { display: flex; flex-direction: column; gap: 11px; }
.panel-title { font-size: 14px; font-weight: 700; color: #0f172a; margin: 0; }
.form-group { display: flex; flex-direction: column; gap: 4px; }
.form-group label { font-size: 11px; font-weight: 600; color: #475569; }
.neo-select { width: 100%; border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px 8px; font-size: 12px; background: #fff; color: #0f172a; }
.neo-range { width: 100%; accent-color: #2563eb; }
.check-col { display: flex; flex-direction: column; gap: 6px; font-size: 12px; color: #334155; }
.chk { display: flex; align-items: center; gap: 6px; cursor: pointer; }
.chk input { accent-color: #2563eb; }
.btn-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.btn-sec { padding: 7px 10px; border: 1px solid #cbd5e1; border-radius: 6px; background: #f8fafc; color: #1e293b; font-size: 12px; font-weight: 600; cursor: pointer; }
.btn-sec:hover:not(:disabled) { background: #eff6ff; border-color: #93c5fd; color: #1d4ed8; }
.btn-sec:disabled { opacity: 0.5; cursor: not-allowed; }
.metrics-card, .export-group { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px; display: flex; flex-direction: column; gap: 5px; }
.m-title { font-size: 11px; font-weight: 700; color: #475569; }
.m-row { display: flex; justify-content: space-between; font-size: 11px; color: #334155; }
</style>
