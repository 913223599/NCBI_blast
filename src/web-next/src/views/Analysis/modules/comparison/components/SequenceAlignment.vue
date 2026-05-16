<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';

const props = defineProps<{
  s1: string;
  s2: string;
  s1Start: number;
  strand: '+' | '-';
}>();

const showOnlyMismatches = ref(true);

// 计算变异点索引
const mismatchIndices = computed(() => {
  const indices: number[] = [];
  for (let i = 0; i < props.s1.length; i++) {
    if (props.s1[i] !== props.s2[i]) indices.push(i);
  }
  return indices;
});

// 计算全段一致性行
const consensus = computed(() => {
  let res = "";
  for (let i = 0; i < props.s1.length; i++) {
    res += props.s1[i] === props.s2[i] ? "|" : " ";
  }
  return res;
});

const containerRef = ref<HTMLElement | null>(null);

/** 精确计算字符宽度并跳转 */
function jumpTo(index: number) {
  if (!containerRef.value) return;
  const container = containerRef.value;

  // 1. 获取左侧固定标签的宽度 (label 50px + track padding 24px)
  const offset = 74;

  // 2. 动态测量一个碱基节点的宽度 (避免魔法数字)
  let charWidth = 9.8; 
  const sampleBase = document.querySelector('.bases span');
  if (sampleBase) {
    charWidth = sampleBase.getBoundingClientRect().width;
  }

  // 3. 计算目标滚动位置，使其居中
  const targetX = (index * charWidth) + offset;
  const scrollX = targetX - (container.clientWidth / 2);
  
  container.scrollTo({ left: Math.max(0, scrollX), behavior: 'smooth' });
}

// 动态刻度宽度
const charWidthState = ref(9.8);
onMounted(() => {
  setTimeout(() => {
    const sample = document.querySelector('.bases span');
    if (sample) charWidthState.value = sample.getBoundingClientRect().width;
  }, 500);
});
</script>

<template>
  <div class="bio-diff-viewer">
    <!-- 1. 交互式热力图轨道 -->
    <div class="mismatch-track-wrapper">
      <div class="track-header">
        <span class="mismatch-badge">发现 {{ mismatchIndices.length }} 处单碱基变异 (SNPs/Indels)</span>
        <div class="controls">
          <span class="hint">点击下方轨道可快速横向定位</span>
        </div>
      </div>
      <div class="track-bar" @click="(e: any) => {
        const rect = e.currentTarget.getBoundingClientRect();
        const p = (e.clientX - rect.left) / rect.width;
        jumpTo(Math.floor(p * s1.length));
      }">
        <div v-for="idx in mismatchIndices" :key="idx" 
             class="tick" :style="{ left: (idx / s1.length * 100) + '%' }"></div>
      </div>
      <div class="track-labels">
        <span>0 bp</span>
        <span>{{ s1.length.toLocaleString() }} bp</span>
      </div>
    </div>

    <!-- 2. 全段水平滑动视图 -->
    <div class="diff-container custom-scrollbar" ref="containerRef">
      <div class="alignment-full-track">
        <!-- 头部坐标参考 (每 100bp 标记一次) -->
        <div class="ruler-row">
           <div class="label">POS</div>
           <div class="ruler-content">
              <span v-for="i in Math.ceil(s1.length / 100)" :key="i" 
                    class="ruler-tick" 
                    :style="{ left: ((i-1) * 100 * charWidthState) + 'px' }">
                {{ (s1Start + (i-1) * 100).toLocaleString() }}
              </span>
           </div>
        </div>

        <div class="alignment-grid">
          <!-- Ref Line -->
          <div class="grid-row ref">
            <div class="label">REF</div>
            <div class="bases">
              <span v-for="(b, i) in s1" :key="i" 
                    :id="`base-${i}`"
                    :class="{ 'diff': b !== s2[i] }">{{ b }}</span>
            </div>
          </div>
          <!-- Consensus Line -->
          <div class="grid-row mid">
            <div class="label"></div>
            <div class="consensus">{{ consensus }}</div>
          </div>
          <!-- Query Line -->
          <div class="grid-row qry">
            <div class="label">QRY</div>
            <div class="bases">
              <span v-for="(b, i) in s2" :key="i" :class="{ 'diff': b !== s1[i] }">{{ b }}</span>
            </div>
          </div>
        </div>
      </div>

      <div v-if="s1.length === 0" class="empty-state">
        无序列数据
      </div>
    </div>
  </div>
</template>

<style scoped>
.bio-diff-viewer {
  background: white; border: 1px solid #e2e8f0; border-radius: 12px;
  overflow: hidden; display: flex; flex-direction: column;
  width: 100%; max-width: 100%; flex-shrink: 0;
}

/* 热力图轨道 */
.mismatch-track-wrapper { 
  padding: 16px 20px; 
  background: #f8fafc; 
  border-bottom: 1px solid #f1f5f9;
  width: 100%;
  flex-shrink: 0;
  box-sizing: border-box;
}
.track-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.mismatch-badge { font-size: 12px; font-weight: 800; color: #ef4444; background: #fee2e2; padding: 4px 10px; border-radius: 6px; }

.track-bar { height: 6px; background: #e2e8f0; border-radius: 3px; position: relative; cursor: pointer; }
.tick { position: absolute; top: 0; width: 1.5px; height: 100%; background: #ef4444; }
.track-labels { display: flex; justify-content: space-between; font-size: 10px; color: #94a3b8; margin-top: 6px; font-family: monospace; }

.hint { font-size: 11px; color: #94a3b8; }

/* 对齐主体 */
.diff-container { 
  padding: 24px 0; 
  overflow-x: auto; 
  overflow-y: hidden;
  background: #ffffff;
  scroll-behavior: smooth;
  width: 100%;
  box-sizing: border-box;
}

.alignment-full-track {
  padding-left: 24px;
  display: block; 
  width: fit-content;
  min-width: 100%;
}

.ruler-row { height: 20px; position: relative; display: flex; align-items: center; margin-bottom: 8px; }
.ruler-content { position: relative; flex: 1; height: 100%; }
.ruler-tick { 
  position: absolute; top: 0; font-size: 9px; color: #cbd5e1; 
  font-family: monospace; border-left: 1px solid #f1f5f9; padding-left: 4px;
}

.alignment-grid { 
  font-family: 'Fira Code', 'Roboto Mono', monospace; 
  font-size: 14px; 
  display: flex; 
  flex-direction: column; 
  gap: 0; 
}
.grid-row { display: flex; align-items: center; line-height: 1.2; }
.grid-row .label { 
  width: 50px; flex-shrink: 0; font-size: 10px; font-weight: 800; 
  color: #94a3b8; user-select: none; position: sticky; left: 0; background: white; z-index: 10;
}

.bases { letter-spacing: 0.3em; color: #334155; white-space: nowrap; }
.bases span.diff { background: #fee2e2; color: #dc2626; font-weight: 800; border-radius: 2px; }

.consensus { letter-spacing: 0.3em; color: #94a3b8; font-weight: 300; white-space: pre; }

.empty-state { padding: 40px; text-align: center; color: #94a3b8; font-style: italic; width: 100%; }

/* 滚动条定制 */
.custom-scrollbar::-webkit-scrollbar { height: 10px; }
.custom-scrollbar::-webkit-scrollbar-track { background: #f8fafc; }
.custom-scrollbar::-webkit-scrollbar-thumb { background: #e2e8f0; border-radius: 10px; border: 3px solid #f8fafc; }
.custom-scrollbar::-webkit-scrollbar-thumb:hover { background: #cbd5e1; }
</style>
