<script setup lang="ts">
import DotplotCanvas from './DotplotCanvas.vue';
import AnalysisVariantTable from './AnalysisVariantTable.vue';

const props = defineProps<{
  currentResult: any;
  activeTab: 'plot' | 'diff';
}>();

const emit = defineEmits<{
  (e: 'updateTab', tab: 'plot' | 'diff'): void;
  (e: 'back'): void;
}>();
</script>

<template>
  <div class="analysis-results-area animate-fade-in" v-if="currentResult">
    <div class="workspace-header">
       <button class="btn-back-nav" @click="emit('back')">
         <span class="icon">←</span> 返回设置
       </button>
       <div class="header-main">
         <div class="title-with-badge">
           <h3>{{ currentResult.rotated ? '旋转一致性验证完成' : '序列差异深度探测' }}</h3>
           <span class="badge" :class="{ 'is-identity': currentResult.rotated }">
             {{ currentResult.rotated ? '完美匹配' : '检出差异' }}
           </span>
         </div>
         <div class="comp-pair">{{ currentResult.target_name }} <span class="vs-tag">VS</span> {{ currentResult.query_name }}</div>
       </div>
    </div>

    <!-- 核心统计大屏 -->
    <div class="summary-dashboard">
      <div class="stat-card primary-v2">
        <div class="glass-bg"></div>
        <div class="card-content">
          <div class="stat-val">{{ currentResult.identity }}<span class="unit">%</span></div>
          <div class="stat-label">核苷酸序列一致性 (Identity)</div>
          <div class="stat-progress">
            <div class="progress-bar-v2" :style="{ width: currentResult.identity + '%' }"></div>
          </div>
        </div>
      </div>
      <div class="stat-card secondary-v2">
        <div class="stat-val">{{ currentResult.variant_count }}</div>
        <div class="stat-label">检测到差异位点 (Variants)</div>
        <div class="variant-tags">
          <span class="tag snp">SNP</span>
          <span class="tag indel">INDEL</span>
        </div>
      </div>
    </div>

    <!-- 可视化与详情区 -->
    <div class="main-content-shelf shadow-glow">
      <div class="shelf-nav">
        <div class="tab-switcher">
          <button :class="{ active: activeTab === 'plot' }" @click="emit('updateTab', 'plot')">
            <span class="icon">📊</span> 共线性点图
          </button>
          <button :class="{ active: activeTab === 'diff' }" @click="emit('updateTab', 'diff')">
            <span class="icon">🧬</span> 差异详情
            <span class="counter" v-if="currentResult.variant_count">{{ currentResult.variant_count }}</span>
          </button>
        </div>
        <div class="nav-extra" v-if="activeTab === 'plot'">
          <div class="legend">
            <span class="lg-item forward">正向匹配</span>
            <span class="lg-item reverse">反向互补</span>
          </div>
        </div>
      </div>

      <div class="shelf-body">
        <div class="plot-container" v-if="activeTab === 'plot'">
          <div class="canvas-wrapper">
            <DotplotCanvas 
              :blocks="currentResult.blocks" 
              :q-len="currentResult.q_len" 
              :t-len="currentResult.t_len" 
            />
          </div>
        </div>
        <div class="diff-container scroll-v" v-else>
          <AnalysisVariantTable 
            :variants="currentResult.variants" 
            :total-count="currentResult.variant_count" 
          />
        </div>
      </div>
    </div>

    <div class="result-footer-tip">
      <div class="tip-content">
        <span class="icon">ℹ️</span>
        <p>{{ currentResult.message }}</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.analysis-results-area { display: flex; flex-direction: column; gap: 24px; padding-bottom: 40px; }

.workspace-header { display: flex; align-items: center; gap: 24px; }
.btn-back-nav { background: white; border: 1px solid #e2e8f0; color: #64748b; padding: 10px 18px; border-radius: 14px; font-weight: 800; font-size: 0.8rem; cursor: pointer; transition: all 0.2s; white-space: nowrap; }
.btn-back-nav:hover { color: #2563eb; border-color: #2563eb; transform: translateX(-4px); }

.header-main { flex: 1; }
.title-with-badge { display: flex; align-items: center; gap: 12px; }
.title-with-badge h3 { margin: 0; font-size: 1.3rem; font-weight: 950; color: #0f172a; letter-spacing: -0.02em; }
.badge { font-size: 10px; font-weight: 900; background: #fee2e2; color: #ef4444; padding: 2px 10px; border-radius: 6px; }
.badge.is-identity { background: #f0fdf4; color: #22c55e; }

.comp-pair { font-size: 0.75rem; color: #64748b; margin-top: 6px; font-weight: 800; font-family: 'JetBrains Mono', monospace; }
.vs-tag { color: #cbd5e1; margin: 0 8px; font-style: italic; }

.summary-dashboard { display: grid; grid-template-columns: 1.4fr 1fr; gap: 20px; }
.stat-card { border-radius: 24px; position: relative; overflow: hidden; }

/* 修正 CSS 报错：使用了错误的 blur 属性 */
.stat-card.primary-v2 { background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%); color: white; padding: 28px 36px; }
.glass-bg { position: absolute; top: -50%; right: -20%; width: 200px; height: 200px; background: rgba(255,255,255,0.05); border-radius: 50%; filter: blur(40px); }

.stat-card.secondary-v2 { background: white; border: 1px solid #f1f5f9; padding: 28px 36px; }

.stat-val { font-size: 3.2rem; font-weight: 950; letter-spacing: -0.05em; line-height: 1; }
.stat-val .unit { font-size: 1.2rem; color: rgba(255,255,255,0.6); margin-left: 6px; }
.secondary-v2 .stat-val .unit { color: #94a3b8; }

.stat-label { font-size: 0.75rem; font-weight: 800; text-transform: uppercase; color: rgba(255,255,255,0.6); margin-top: 14px; letter-spacing: 0.08em; }
.secondary-v2 .stat-label { color: #94a3b8; }

.stat-progress { height: 6px; background: rgba(255,255,255,0.1); border-radius: 3px; margin-top: 20px; }
.progress-bar-v2 { height: 100%; background: #60a5fa; border-radius: 3px; box-shadow: 0 0 15px rgba(96, 165, 250, 0.4); }

.main-content-shelf { background: white; border-radius: 28px; border: 1px solid #f1f5f9; overflow: hidden; min-height: 600px; display: flex; flex-direction: column; }
.shelf-nav { padding: 16px 32px; background: #fff; border-bottom: 1px solid #f8fafc; display: flex; justify-content: space-between; align-items: center; }
.tab-switcher { display: flex; gap: 8px; background: #f8fafc; padding: 4px; border-radius: 14px; }
.tab-switcher button { border: none; background: none; padding: 10px 24px; border-radius: 10px; font-size: 0.85rem; font-weight: 900; color: #64748b; cursor: pointer; transition: all 0.2s; display: flex; align-items: center; gap: 10px; }
.tab-switcher button.active { background: white; color: #2563eb; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }

.plot-container { flex: 1; display: flex; align-items: center; justify-content: center; background: #fcfdfe; position: relative; }
.canvas-wrapper { width: 95%; height: 95%; display: flex; align-items: center; justify-content: center; }

.result-footer-tip { background: #f8fafc; border-radius: 20px; padding: 24px 32px; border: 1px solid #f1f5f9; margin-top: 12px; border-left: 6px solid #3b82f6; }
.tip-content p { margin: 0; font-size: 0.95rem; color: #334155; line-height: 1.7; font-weight: 600; }

.animate-fade-in { animation: fadeIn 0.4s ease-out; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
</style>
