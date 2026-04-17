
import { ref, reactive } from 'vue';
import { getBridge } from '../../../../../bridge';

export interface Alignment {
  ref_start: number;
  ref_end: number;
  query_start: number;
  query_end: number;
  len: number;
  identity: number;
  ref_id: string;
  query_id: string;
}

export function useComparison() {
  const isRunning = ref(false);
  const result = ref<any>(null);
  const error = ref<string | null>(null);
  
  const params = reactive({
    engine: 'mummer',
    minIdentity: 90,
    minLength: 100,
    autoOrientation: true
  });

  async function startAnalysis(refPath: string, queryPath: string) {
    if (!refPath || !queryPath) {
      error.value = '请先平衡参考序列与待测序列';
      return;
    }

    isRunning.value = true;
    error.value = null;
    result.value = null;

    try {
      const bridge = getBridge();
      // 这里调用后端的封装接口
      const payload = {
        ref: refPath,
        query: queryPath,
        options: { ...params }
      };

      const responseStr = await bridge.run_comparison_pipeline(JSON.stringify(payload));
      const response = JSON.parse(responseStr);

      if (response.status === 'success') {
        result.value = response.data;
      } else {
        error.value = response.message || '分析过程中发生未知错误';
      }
    } catch (e: any) {
      error.value = `通信异常: ${e.message}`;
    } finally {
      isRunning.value = false;
    }
  }

  return {
    isRunning,
    result,
    error,
    params,
    startAnalysis
  };
}
