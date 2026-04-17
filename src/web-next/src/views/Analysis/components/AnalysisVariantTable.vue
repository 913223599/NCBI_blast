<script setup lang="ts">
import { ref } from 'vue';

interface Variant {
  pos: number;
  type: string;
  ref: string;
  alt: string;
  assessment?: string;
  len: number;
}

const props = defineProps<{
  variants: Variant[];
  totalCount: number;
}>();

// 用于处理悬停详情的响应式状态
const hoverData = ref<{ sequence: string; x: number; y: number } | null>(null);

function showFull(event: MouseEvent, seq: string) {
  const rect = (event.target as HTMLElement).getBoundingClientRect();
  hoverData.value = {
    sequence: seq,
    x: rect.left,
    y: rect.bottom + window.scrollY
  };
}

function hideFull() {
  hoverData.value = null;
}
</script>

<template>
  <div class="analysis-variant-table">
    <table class="v-table">
      <thead>
        <tr>
          <th width="120">位置 (Pos)</th>
          <th width="80">类型</th>
          <th width="120">评估结果</th>
          <th>参考 (REF)</th>
          <th>变异 (ALT)</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(v, vi) in variants" :key="vi">
          <td class="pos">{{ v.pos.toLocaleString() }}</td>
          <td>
            <span class="v-type-tag" :class="v.type">{{ v.type }}</span>
          </td>
          <td class="assessment-cell">
            <span class="assess-text">{{ v.assessment || '--' }}</span>
          </td>
          <td class="seq-cell">
            <div class="seq-clip" @mouseenter="showFull($event, v.ref)" @mouseleave="hideFull">
              {{ v.ref }}
            </div>
          </td>
          <td class="seq-cell">
            <div class="seq-clip alt" @mouseenter="showFull($event, v.alt)" @mouseleave="hideFull">
              {{ v.alt }}
            </div>
          </td>
        </tr>
        <tr v-if="totalCount === 0">
          <td colspan="5" class="empty-row">未检出核苷酸级别差异</td>
        </tr>
        <tr v-if="totalCount > 200">
          <td colspan="5" class="more-tip">... 仅显示前 200 处差异，完整数据请导出报表 ...</td>
        </tr>
      </tbody>
    </table>

    <!-- 浮层提示窗：解决布局抖动问题 -->
    <Teleport to="body">
      <div v-if="hoverData" 
           class="seq-popover" 
           :style="{ left: hoverData.x + 'px', top: hoverData.y + 'px' }">
        <div class="popover-arrow"></div>
        <div class="popover-content">
          <code>{{ hoverData.sequence }}</code>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.analysis-variant-table { background: white; width: 100%; height: 100%; }
.v-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
.v-table th { position: sticky; top: 0; background: #f8fafc; text-align: left; padding: 12px 16px; color: #64748b; font-weight: 800; border-bottom: 2px solid #f1f5f9; z-index: 10; font-size: 0.75rem; text-transform: uppercase; }
.v-table td { padding: 10px 16px; border-bottom: 1px solid #f1f5f9; color: #1e293b; vertical-align: middle; height: 44px; }
.v-table tr:hover { background: #f8fafc; }

.pos { font-family: 'JetBrains Mono', monospace; color: #64748b !important; font-weight: 600; font-size: 0.8rem; }
.v-type-tag { font-size: 9px; font-weight: 900; padding: 2px 6px; border-radius: 4px; display: inline-block; min-width: 32px; text-align: center; }
.v-type-tag.SNP { background: #eff6ff; color: #2563eb; }
.v-type-tag.INS { background: #f0fdf4; color: #16a34a; }
.v-type-tag.DEL { background: #fef2f2; color: #ef4444; }

.assess-text { font-size: 0.75rem; color: #64748b; font-weight: 500; }
.seq-clip { font-family: 'JetBrains Mono', monospace; font-weight: 800; font-size: 0.9rem; max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; cursor: help; border-bottom: 1px dashed #e2e8f0; }
.seq-clip.alt { color: #2563eb; }

.empty-row, .more-tip { text-align: center; color: #94a3b8; padding: 48px !important; font-style: italic; }

/* 浮层专用样式 */
.seq-popover { position: absolute; z-index: 9999; background: #1e293b; color: white; padding: 12px; border-radius: 8px; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3); max-width: 400px; pointer-events: none; margin-top: 8px; animation: popIn 0.15s ease-out; }
.popover-content { font-size: 0.85rem; word-break: break-all; line-height: 1.5; }
.popover-arrow { position: absolute; top: -5px; left: 20px; width: 10px; height: 10px; background: #1e293b; transform: rotate(45deg); }

@keyframes popIn {
  from { opacity: 0; transform: translateY(-5px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
