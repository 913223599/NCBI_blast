/**
 * 流水号计数器管理
 *
 * 职责：仅管理计数器的读写和递增，不涉及编码拼接或对照表逻辑。
 * 计数器按 "A+BBB+CCC" (即分类路径) 隔离。
 */
import { ref, onMounted } from 'vue'
import { useStrainStore } from '../stores/strain'
import type { SerialCounter } from '../types/codeSystem'

export function useSerialCounter() {
  const strainStore = useStrainStore()
  const counters = ref<SerialCounter[]>([])

  const syncToStore = () => {
    strainStore.serialCounters = counters.value
    strainStore.autoSave()
  }

  onMounted(() => {
    if (strainStore.serialCounters.length > 0) {
      counters.value = strainStore.serialCounters
    }
  })

  /**
   * 获取指定分类路径的当前计数值
   * @param taxonomyPath - 分类路径，如 "1AAAAAA"
   * @returns 当前最大流水号，无记录时返回 0
   */
  function getCurrentValue(taxonomyPath: string): number {
    const counter = counters.value.find(
      (entry) => entry.counterKey === taxonomyPath
    )
    return counter?.currentValue ?? 0
  }

  /**
   * 递增并返回下一个流水号
   * @param taxonomyPath - 分类路径
   * @returns 新的流水号值
   */
  function increment(taxonomyPath: string): number {
    const existing = counters.value.find(
      (entry) => entry.counterKey === taxonomyPath
    )

    if (existing) {
      existing.currentValue += 1
      existing.updatedAt = new Date().toISOString()
      syncToStore()
      return existing.currentValue
    }

    const newCounter: SerialCounter = {
      counterKey: taxonomyPath,
      currentValue: 1,
      updatedAt: new Date().toISOString(),
    }
    counters.value.push(newCounter)
    syncToStore()
    return 1
  }

  /**
   * 批量递增，返回连续的流水号序列
   * @param taxonomyPath - 分类路径
   * @param count - 需要的数量
   * @returns 流水号数组 [startValue, startValue+1, ..., startValue+count-1]
   */
  function incrementBatch(taxonomyPath: string, count: number): number[] {
    if (count <= 0) return []

    const currentMax = getCurrentValue(taxonomyPath)
    const startValue = currentMax + 1
    const endValue = currentMax + count
    const serialNumbers: number[] = []

    for (let idx = startValue; idx <= endValue; idx++) {
      serialNumbers.push(idx)
    }

    // 一次性更新计数器
    const existing = counters.value.find(
      (entry) => entry.counterKey === taxonomyPath
    )
    if (existing) {
      existing.currentValue = endValue
      existing.updatedAt = new Date().toISOString()
    } else {
      counters.value.push({
        counterKey: taxonomyPath,
        currentValue: endValue,
        updatedAt: new Date().toISOString(),
      })
    }
    
    syncToStore()
    return serialNumbers
  }

  /**
   * 从已有数据重建计数器状态
   * @param existingCounters - 从持久化存储加载的计数器数组
   */
  function loadCounters(existingCounters: SerialCounter[]): void {
    counters.value = [...existingCounters]
  }

  /**
   * 获取全部计数器的快照（用于持久化）
   */
  function exportCounters(): SerialCounter[] {
    return [...counters.value]
  }

  return {
    counters,
    getCurrentValue,
    increment,
    incrementBatch,
    loadCounters,
    exportCounters,
  }
}
