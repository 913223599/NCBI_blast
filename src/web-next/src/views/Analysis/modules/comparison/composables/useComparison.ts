import { ref, reactive } from 'vue';
import { getBridge } from '../../../../../bridge';
import type { AlignmentResult } from '../utils/instantAlignment';
import { analyzeSequences } from '../utils/instantAlignment';

export interface Alignment {
  ref_start: number; ref_end: number; query_start: number; query_end: number;
  length: number; identity: number; strand: string; ref_id: string; query_id: string;
}

export function useComparison() {
  const isRunning = ref(false);
  const result = ref<AlignmentResult | null>(null);
  const error = ref<string | null>(null);

  const params = reactive({
    engine: 'mummer' as 'mummer' | 'minimap2',
    autoOrientation: true
  });

  async function runInstantAnalysis(payload: { seq1: string; seq2: string; name1: string; name2: string }) {
    isRunning.value = true;
    error.value = null;
    result.value = null;
    await new Promise(r => setTimeout(r, 100));

    try {
      const res = analyzeSequences(payload.seq1, payload.seq2);
      result.value = res;

      // 自动保存至后端历史数据库
      const bridge = getBridge();
      await bridge.run_comparison_pipeline(JSON.stringify({
        ref: payload.name1 || 'Sequence 1',
        query: payload.name2 || 'Sequence 2',
        options: {
          mode: 'save_only', // 特殊模式：仅保存结果不触发后端计算
          instant_data: {
            ref_length: res.len1,
            query_length: res.len2,
            average_identity: res.globalSim * 100,
            total_matches: res.dotplot.length,
            matched_length: res.dotplot.length * 15,
            was_flipped: res.mainStrand === '-',
            alignments: res.dotplot // 持久化比对点位，用于历史恢复
          }
        }
      }));
    } catch (e: any) {
      error.value = `即时分析失败: ${e.message}`;
    } finally {
      isRunning.value = false;
    }
  }

  async function loadHistoryResult(item: any) {
    if (!item?.task_id) return;
    
    isRunning.value = true;
    error.value = null;
    try {
      const bridge = getBridge();
      // 获取原始数据，处理可能的字符串/对象差异
      const rawDetail = await bridge.get_comparison_task_results(item.task_id);
      const detail = typeof rawDetail === 'string' ? JSON.parse(rawDetail) : rawDetail;

      if (!detail) throw new Error("后端未返回有效的任务详情");

      // 数据适配器：将后端标准输出转换为前端即时看板格式
      const summary = detail?.summary || item || {};
      
      result.value = {
        len1: summary.ref_length || 0,
        len2: summary.query_length || 0,
        globalSim: (summary.average_identity || 0) / 100,
        dotplot: (detail.alignments || summary.alignments || []).map((a: any) => ({
          x: a.x !== undefined ? a.x : a.ref_start, 
          y: a.y !== undefined ? a.y : a.query_start, 
          strand: a.strand === '+' ? '+' : '-'
        })),
        bins: [], 
        variants: (detail.variants || []).map((v: any) => ({
          start: v.ref_start, 
          end: v.ref_end, 
          score: (v.identity || 0) / 100,
          s1_sub: v.ref_seq || "", 
          s2_sub: v.query_seq || "",
          s2_start_pos: v.query_start
        })),
        binSize: 500,
        mainStrand: (summary.was_flipped || detail.metadata?.was_flipped) ? '-' : '+',
        strandRatio: 1,
        variantThreshold: 0.95
      };
    } catch (e: any) {
      console.error("History Load Error:", e);
      error.value = `加载历史记录失败: ${e.message}`;
    } finally {
      isRunning.value = false;
    }
  }

  return { isRunning, result, error, params, runInstantAnalysis, loadHistoryResult };
}
